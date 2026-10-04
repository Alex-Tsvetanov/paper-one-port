// An in-process server for the tests: the server on its worker threads, the reports of its hooks
// collected per client port, and the checks every test makes after stopping it. Linux only.
#pragma once

#include "config.hpp"
#include "server.hpp"
#include "test_support.hpp"

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace oneport::test
{

	/// The backend a test runs on when it does not name one: each server and handler test is
	/// registered once per Linux backend (tests/server_tests.cpp), and sets this while it runs.
	inline Backend& suite_backend()
	{
		static Backend b = Backend::epoll;
		return b;
	}

	struct ServerArgs
	{
		Mode mode = Mode::one_port;
		Detect detect = Detect::replay;
		Backend backend = suite_backend();
		Dispatch dispatch = Dispatch::inproc;
		RelayCopy relay_copy = RelayCopy::user_space;
		std::optional<std::uint16_t> relay_port;  // relay: the backend server's first port
		Proxy proxy = Proxy::off;
		Fallback fallback = Fallback::none;
		Listener listener = Listener::shared;
		std::uint32_t workers = 1;
		std::chrono::milliseconds t_fb{300};
		std::chrono::milliseconds t_dec{300};
		std::chrono::milliseconds t_hdr{300};
#if defined(_WIN32)
		IocpReceive iocp_receive = IocpReceive::zero_byte;  // the IOCP receive form (M6a)
		IocpAccept iocp_accept = IocpAccept::no_buffer;     // the AcceptEx form (M6a)
#endif
	};

	inline Config make_config(const ServerArgs& a)
	{
		Config c;
		c.mode = a.mode;
		c.detect = a.detect;
		c.dispatch = a.dispatch;
		c.backend = a.backend;
		c.relay_copy = a.relay_copy;
		c.relay_port = a.relay_port;
		c.proxy = a.proxy;
		c.fallback = a.fallback;
		c.listener = a.listener;
		c.workers = a.workers;
		c.t_fb_ms = a.t_fb.count();
		c.t_dec_ms = a.t_dec.count();
		c.t_hdr_ms = a.t_hdr.count();
#if defined(_WIN32)
		c.iocp_receive = a.iocp_receive;
		c.iocp_accept = a.iocp_accept;
#endif
		return c;
	}

	/// The reports of one server's hooks, keyed by the client's port.
	class Collector
	{
	public:
		static void on_detection(void* ctx, const server::DetectionReport& r)
		{
			auto* self = static_cast<Collector*>(ctx);
			{
				std::lock_guard lock(self->m_);
				self->detections_[r.peer_port].push_back(r);
			}
			self->cv_.notify_all();
		}

		static void on_close(void* ctx, const server::CloseReport& r)
		{
			auto* self = static_cast<Collector*>(ctx);
			{
				std::lock_guard lock(self->m_);
				self->closes_[r.peer_port].push_back(r);
			}
			self->cv_.notify_all();
		}

		static void on_relayed(void* ctx, const server::RelayReport& r)
		{
			auto* self = static_cast<Collector*>(ctx);
			{
				std::lock_guard lock(self->m_);
				self->relays_[r.peer_port].push_back(r);
			}
			self->cv_.notify_all();
		}

		/// Waits for the server's close of the connection from `port`, and takes its reports.
		bool wait_close(std::uint16_t port, std::chrono::milliseconds limit, std::vector<server::DetectionReport>& detections,
		                std::vector<server::RelayReport>* relays = nullptr)
		{
			std::unique_lock lock(m_);
			const bool closed = cv_.wait_for(lock, limit, [&] { return closes_.contains(port); });
			if (!closed) return false;
			closes_.erase(port);
			auto it = detections_.find(port);
			if (it != detections_.end())
			{
				detections = std::move(it->second);
				detections_.erase(it);
			}
			auto rt = relays_.find(port);
			if (rt != relays_.end())
			{
				if (relays != nullptr) *relays = std::move(rt->second);
				relays_.erase(rt);
			}
			return true;
		}

		server::Hooks hooks()
		{
			server::Hooks h;
			h.ctx = this;
			h.detection = &Collector::on_detection;
			h.closed = &Collector::on_close;
			h.relayed = &Collector::on_relayed;
			return h;
		}

	private:
		std::mutex m_;
		std::condition_variable cv_;
		std::map<std::uint16_t, std::vector<server::DetectionReport>> detections_;
		std::map<std::uint16_t, std::vector<server::CloseReport>> closes_;
		std::map<std::uint16_t, std::vector<server::RelayReport>> relays_;
	};

#if defined(_WIN32)
	/// How long a test waits after starting a server on IOCP before its first client (Running).
	inline constexpr std::chrono::milliseconds kIocpStartWait{250};
#endif

	/// A started server with its collector.
	struct Running
	{
		ServerArgs args;
		Collector collector;
		std::unique_ptr<server::Server> server;

		/// Starts the server. `extra` may add a before_expiries hook with its own context.
		explicit Running(const ServerArgs& a, server::Hooks extra = {}) : args(a), extra_(extra)
		{
			server::Options o;
			o.hooks.ctx = this;
			o.hooks.detection = [](void* ctx, const server::DetectionReport& r) { Collector::on_detection(&static_cast<Running*>(ctx)->collector, r); };
			o.hooks.closed = [](void* ctx, const server::CloseReport& r) { Collector::on_close(&static_cast<Running*>(ctx)->collector, r); };
			o.hooks.relayed = [](void* ctx, const server::RelayReport& r) { Collector::on_relayed(&static_cast<Running*>(ctx)->collector, r); };
			if (extra.before_expiries != nullptr) o.hooks.before_expiries = &Running::forward_before_expiries;
			server = std::make_unique<server::Server>(make_config(a), o);
			server->start();
#if defined(_WIN32)
			// On IOCP, start() returns once the worker threads run, and each worker posts its
			// listeners' AcceptEx requests itself after it starts (bench/server/iocp.cpp,
			// run_iocp). A client that connects and resets before a request is posted can end
			// with no close reported: its connection either never reaches a request or completes
			// one with an error, which on_accept_entry closes without a report (the likely cause,
			// not established). The suite's first client starts within microseconds of start():
			// HC22's partial variant, which resets 10 ms after its first byte, failed its first
			// replicate, and only that one, on W (the M7 freeze night, design/status.md). On
			// Linux the worker takes connections from the listen queue with accept() whenever it
			// starts, and HC22 has passed in every run of the suite on L. The suite waits here;
			// the measured runs start their clients from another process after the server's
			// lines.
			std::this_thread::sleep_for(kIocpStartWait);
#endif
		}

		Running(const Running&) = delete;
		Running& operator=(const Running&) = delete;

		std::uint16_t port(std::size_t listener = 0) const { return server->ports().at(listener); }

		/// The port of a dedicated listener by class.
		std::uint16_t port_of(detect::Proto p) const
		{
			const auto& specs = server->listeners();
			for (std::size_t i = 0; i < specs.size(); ++i)
			{
				if (!specs[i].detects && specs[i].proto == p) return server->ports()[i];
			}
			return 0;
		}

		/// Stops the server and checks what must hold after any run: no worker error, every
		/// accepted connection closed, no connection or buffer left, one detection outcome per
		/// connection of a one-port listener, and B2(a, b) for every timed event.
		Result stop_and_check()
		{
			server->stop();
			const auto err = server->error();
			CHECK(!err, "a worker failed: " << *err);
			const server::Counters t = server->totals();
			CHECK(t.accepted == t.closed, "accepted " << t.accepted << ", closed " << t.closed);
			CHECK(t.conns_open == 0, t.conns_open << " connections left open");
			CHECK(t.recv_eof + t.recv_again <= t.recv_calls, "receives at the end " << t.recv_eof << " and empty " << t.recv_again << " exceed " << t.recv_calls);
			CHECK(t.buffers_outstanding == 0, t.buffers_outstanding << " buffers not returned");
			CHECK(t.relayed + t.relay_connect_errors + t.route_rejected + t.route_timeouts <= t.accepted, "more relay ends than connections");
			CHECK(t.outcomes[static_cast<std::size_t>(server::Outcome::rejected_budget)] == 0, "a budget was exceeded");
			if (args.mode == Mode::one_port)
			{
				std::uint64_t sum = 0;
				for (const auto n : t.outcomes) sum += n;
				CHECK(sum == t.accepted, "outcomes " << sum << " for " << t.accepted << " connections");
			}
			for (const server::TimedEvent& ev : t.timed)
			{
				if (auto bad = check_timed(ev)) return bad;
			}
			return std::nullopt;
		}

		/// B2(a) and (b) for one timed event: never early, and handled in the first pass whose
		/// wait returned at or after its deadline; the deadline is its timer's duration after
		/// its start.
		Result check_timed(const server::TimedEvent& ev) const
		{
			using std::chrono::duration_cast;
			using std::chrono::nanoseconds;
			const std::chrono::milliseconds t = ev.kind == server::TimerKind::t_fb    ? args.t_fb
			                                    : ev.kind == server::TimerKind::t_dec ? args.t_dec
			                                                                          : args.t_hdr;
			CHECK(ev.deadline - ev.start == duration_cast<nanoseconds>(t), server::name(ev.kind) << ": deadline is not start + T");
			CHECK(ev.prev_wait_return < ev.deadline, server::name(ev.kind) << ": the previous pass's wait returned after the deadline (B2 b)");
			CHECK(ev.deadline <= ev.wait_return, server::name(ev.kind) << ": handled in a pass whose wait returned before the deadline (B2 a)");
			CHECK(ev.wait_return <= ev.handled_at, server::name(ev.kind) << ": handled before its pass's wait returned");
			return std::nullopt;
		}

	private:
		static void forward_before_expiries(void* ctx, unsigned worker, server::TimePoint t, std::optional<server::TimePoint> e)
		{
			auto* self = static_cast<Running*>(ctx);
			self->extra_.before_expiries(self->extra_.ctx, worker, t, e);
		}

		server::Hooks extra_{};
	};

}  // namespace oneport::test
