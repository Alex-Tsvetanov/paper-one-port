// The server's functional tests on epoll (Linux): handlers, both modes, the peek path's
// SO_RCVLOWAT, the check of 1(b) with a byte in the pass of the expiry, two workers on the shared
// listener and on SO_REUSEPORT, every flag combination M1 serves, and the binary itself.
// Untimed: no test measures a rate; the only times are the timers' bounds.
#include "test_support.hpp"

#if defined(__linux__)

#include "cases.hpp"
#include "harness.hpp"
#include "http1.hpp"
#include "script.hpp"

#include <array>
#include <atomic>
#include <cerrno>
#include <cstring>
#include <spawn.h>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <linux/sockios.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

namespace oneport::test
{

	namespace
	{

		using namespace std::chrono_literals;
		using opcase::Bytes;
		using opcase::Script;
		using opcase::text;

		const Bytes kGetKeepAlive = text("GET / HTTP/1.1\r\nHost: oneport.test\r\n\r\n");

		Bytes cat(std::initializer_list<Bytes> parts) { return opcase::cat(parts); }

		Bytes repeat(std::string_view s, std::size_t n)
		{
			std::string r;
			for (std::size_t i = 0; i < n; ++i) r += s;
			return text(r);
		}

		/// Runs `s` and waits until the server has closed the connection; returns its reports.
		std::vector<server::DetectionReport> run_and_wait(Running& srv, const Script& s, std::uint16_t port, opcase::Transcript& t)
		{
			t = opcase::run(s, port);
			std::vector<server::DetectionReport> reps;
			srv.collector.wait_close(t.local_port, 10000ms, reps);
			return reps;
		}

		// ---- HTTP/1.1 keep-alive, pipelining and close, in both modes ----

		Result http_keepalive(Mode mode, Detect detect)
		{
			ServerArgs a;
			a.mode = mode;
			a.detect = detect;
			Running srv(a);
			Script s;
			s.write(kGetKeepAlive).gap(20ms).write(kGetKeepAlive).gap(20ms).write(cat({kGetKeepAlive, kGetKeepAlive})).gap(20ms).write(opcase::http_get());
			opcase::Transcript t;
			run_and_wait(srv, s, srv.port(), t);
			CHECK(t.received == repeat(http1::kResponse200, 5), "five 200 responses expected; got " << t.received.size() << " bytes");
			CHECK(t.eof && !t.reset, "the server closes after Connection: close");
			return srv.stop_and_check();
		}

		// ---- Dedicated mode: six consecutive ports, the handlers at accept ----

		Result dedicated_ports()
		{
			ServerArgs a;
			a.mode = Mode::dedicated;
			Running srv(a);
			const auto ports = srv.server->ports();
			const auto& specs = srv.server->listeners();
			CHECK(ports.size() == 6 && specs.size() == 6, "six listeners");
			const std::array<detect::Proto, 6> order{detect::Proto::http1, detect::Proto::h2c, detect::Proto::tls, detect::Proto::mqtt, detect::Proto::ssh, detect::Proto::smtp};
			for (std::size_t i = 0; i < 6; ++i)
			{
				CHECK(ports[i] == ports[0] + i, "port " << i << " is not consecutive");
				CHECK(!specs[i].detects && specs[i].proto == order[i], "listener " << i << " is " << specs[i].name);
			}
			opcase::Transcript t;
			run_and_wait(srv, Script{}.write(opcase::http_get()), ports[0], t);
			CHECK(t.received == text(http1::kResponse200) && t.eof, "the dedicated HTTP/1.1 port answers 200");
			for (std::size_t i = 1; i < 6; ++i)
			{
				run_and_wait(srv, Script{}.await_line().shutdown_write(), ports[i], t);
				const std::string want = "oneport M1 stub " + std::string(detect::name(order[i]));
				CHECK(opcase::first_line(t.received) == want, "port " << i << " says '" << opcase::first_line(t.received) << "'");
				CHECK(t.eof, "port " << i << " closes after the client's EOF");
			}
			return srv.stop_and_check();
		}

		/// Dedicated mode with PROXY on: T_hdr in the deadline queue (the pilot's timer part).
		Result dedicated_proxy()
		{
			ServerArgs a;
			a.mode = Mode::dedicated;
			a.proxy = Proxy::on;
			a.t_hdr = 200ms;
			Running srv(a);
			opcase::Transcript t;
			auto reps = run_and_wait(srv, Script{}.write(opcase::slice(opcase::proxy_v2(), 0, 10)).await_close(), srv.port(), t);
			CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::proxy_timeout, "an incomplete header is closed at T_hdr");
			CHECK(reps[0].timed && reps[0].event.kind == server::TimerKind::t_hdr, "by the T_hdr expiry");
			if (auto bad = srv.check_timed(reps[0].event)) return bad;
			CHECK(t.end && *t.end - t.before_connect >= a.t_hdr, "the client saw the close before T_hdr");
			reps = run_and_wait(srv, Script{}.write(cat({opcase::proxy_v2(), opcase::http_get()})), srv.port(), t);
			CHECK(reps.empty(), "a complete header ends no detection on a dedicated port");
			CHECK(t.received == text(http1::kResponse200), "the request after the header is answered");
			run_and_wait(srv, Script{}.write(opcase::proxy_v2()).await_line().shutdown_write(), srv.port_of(detect::Proto::smtp), t);
			CHECK(opcase::first_line(t.received) == "oneport M1 stub SMTP", "the SMTP stub speaks once the header is complete");
			return srv.stop_and_check();
		}

		// ---- Peek: SO_RCVLOWAT ----

		/// A drip below the low-water mark wakes nothing in peek mode (I11), and every drip wakes
		/// replay mode.
		Result peek_lowat(Detect detect)
		{
			ServerArgs a;
			a.detect = detect;
			a.t_dec = 5000ms;
			Running srv(a);
			const Bytes all = opcase::h2c_opening();
			Script s;
			s.write(opcase::slice(all, 0, 16));
			for (std::size_t i = 16; i < 24; ++i) s.gap(30ms).write(opcase::slice(all, i, i + 1));
			s.gap(30ms).write(opcase::slice(all, 24, all.size())).shutdown_write();
			opcase::Transcript t;
			const auto reps = run_and_wait(srv, s, srv.port(), t);
			CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::classified && reps[0].proto == detect::Proto::h2c, "classified h2c");
			const auto& r = reps[0];
			if (detect == Detect::peek)
			{
				CHECK(r.wakeups == 2, "peek: " << r.wakeups << " wakeups; 2 expected (16 bytes, then the 24th)");
				CHECK(r.lowat_sets == 1 && r.lowat_resets == 1, "peek: SO_RCVLOWAT set " << r.lowat_sets << ", reset " << r.lowat_resets);
				CHECK(r.max_user_bytes == 0, "peek holds no payload in user space");
			}
			else
			{
				CHECK(r.wakeups >= 3, "replay: " << r.wakeups << " wakeups; each drip should wake it");
				CHECK(r.lowat_sets == 0 && r.lowat_resets == 0, "replay never sets SO_RCVLOWAT");
			}
			if (auto bad = srv.stop_and_check()) return bad;
			const server::Counters c = srv.server->totals();
			CHECK(c.setsockopt_calls == c.lowat_sets + c.lowat_resets, "every setsockopt is a set or a reset");
			return std::nullopt;
		}

		/// The kernel behaviour the peek path rests on, pinned on L's kernel (proposal RK4, I11):
		/// with edge-triggered epoll, setting SO_RCVLOWAT at or below the queued bytes raises an
		/// event; above them, data that stays below the mark raises none; reaching the mark does;
		/// and a half-close is reported whatever the mark.
		Result kernel_rcvlowat_et()
		{
			const int l = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			sockaddr_in addr{};
			addr.sin_family = AF_INET;
			addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			CHECK(::bind(l, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0 && ::listen(l, 1) == 0, "listen");
			socklen_t n = sizeof(addr);
			::getsockname(l, reinterpret_cast<sockaddr*>(&addr), &n);
			const int c = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			const int one = 1;
			::setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
			CHECK(::connect(c, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
			const int s = ::accept4(l, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
			CHECK(s >= 0, "accept");
			const int ep = ::epoll_create1(EPOLL_CLOEXEC);
			epoll_event ev{};
			ev.events = EPOLLIN | EPOLLRDHUP | EPOLLET;
			CHECK(::epoll_ctl(ep, EPOLL_CTL_ADD, s, &ev) == 0, "epoll_ctl");
			auto wait = [ep](int ms) {
				std::array<epoll_event, 4> out{};
				const int k = ::epoll_wait(ep, out.data(), static_cast<int>(out.size()), ms);
				return k > 0 ? out[0].events : 0u;
			};
			auto lowat = [s](int v) { return ::setsockopt(s, SOL_SOCKET, SO_RCVLOWAT, &v, sizeof(v)) == 0; };
			const std::array<char, 10> ten{};
			CHECK(::send(c, ten.data(), ten.size(), 0) == 10, "send");
			CHECK((wait(1000) & EPOLLIN) != 0, "10 bytes raise an event");
			CHECK(wait(0) == 0, "edge-triggered: no second event for the same bytes");
			CHECK(lowat(5), "SO_RCVLOWAT 5");
			CHECK((wait(1000) & EPOLLIN) != 0, "setting the mark at or below the queued bytes raises an event");
			CHECK(lowat(30), "SO_RCVLOWAT 30");
			CHECK(wait(0) == 0, "a mark above the queued bytes raises none");
			CHECK(::send(c, ten.data(), ten.size(), 0) == 10, "send");
			CHECK(wait(100) == 0, "20 bytes below a mark of 30 raise no event");
			CHECK(::send(c, ten.data(), ten.size(), 0) == 10, "send");
			CHECK((wait(1000) & EPOLLIN) != 0, "30 bytes reach the mark");
			CHECK(lowat(100), "SO_RCVLOWAT 100");
			::shutdown(c, SHUT_WR);
			CHECK((wait(1000) & EPOLLRDHUP) != 0, "a half-close is reported above the mark");
			::close(ep);
			::close(s);
			::close(c);
			::close(l);
			return std::nullopt;
		}

		// ---- The check of 1(b), with a byte in the pass of the expiry ----

		struct ByteInExpiryPass
		{
			std::atomic<int> client{-1};
			std::atomic<bool> fired{false};
			static void hook(void* ctx, unsigned, server::TimePoint wait_return, std::optional<server::TimePoint> earliest)
			{
				auto* self = static_cast<ByteInExpiryPass*>(ctx);
				if (self->fired.load() || !earliest || *earliest > wait_return) return;
				// This pass handles an expiry: the request reaches the socket now, after the pass's
				// readiness events and before its expiries. Wait until the server's side holds it.
				const Bytes req = opcase::http_get();
				const int fd = self->client.load();
				if (fd < 0) return;
				if (::send(fd, req.data(), req.size(), MSG_NOSIGNAL) != static_cast<ssize_t>(req.size())) return;
				for (int i = 0; i < 1000; ++i)
				{
					int unacked = 0;
					if (::ioctl(fd, SIOCOUTQ, &unacked) == 0 && unacked == 0) break;
					std::this_thread::sleep_for(1ms);
				}
				self->fired.store(true);
			}
		};

		Result check_byte_wins(Detect detect)
		{
			ByteInExpiryPass ctx;
			ServerArgs a;
			a.detect = detect;
			a.fallback = Fallback::smtp;
			server::Hooks extra;
			extra.ctx = &ctx;
			extra.before_expiries = &ByteInExpiryPass::hook;
			Running srv(a, extra);
			const int client = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			sockaddr_in addr{};
			addr.sin_family = AF_INET;
			addr.sin_port = htons(srv.port());
			addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			const int one = 1;
			::setsockopt(client, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
			CHECK(::connect(client, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
			ctx.client.store(client);
			sockaddr_in local{};
			socklen_t n = sizeof(local);
			::getsockname(client, reinterpret_cast<sockaddr*>(&local), &n);
			std::string got;
			for (;;)
			{
				pollfd p{client, POLLIN, 0};
				if (::poll(&p, 1, 5000) <= 0) break;
				std::array<char, 512> buf{};
				const ssize_t k = ::recv(client, buf.data(), buf.size(), 0);
				if (k <= 0) break;
				got.append(buf.data(), static_cast<std::size_t>(k));
			}
			std::vector<server::DetectionReport> reps;
			srv.collector.wait_close(ntohs(local.sin_port), 10000ms, reps);
			CHECK(ctx.fired.load(), "the hook never saw a pass with an expiry");
			CHECK(got == http1::kResponse200, "the byte won: the request is answered 200, not by the fallback");
			CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::classified && reps[0].proto == detect::Proto::http1, "classified HTTP/1.1");
			if (auto bad = srv.stop_and_check()) return bad;
			const server::Counters c = srv.server->totals();
			::close(client);
			CHECK(c.check_calls == 1 && c.check_found_byte == 1, "one check, which found the byte (" << c.check_calls << ", " << c.check_found_byte << ")");
			bool byte_won = false;
			for (const auto& ev : c.timed) byte_won = byte_won || (ev.kind == server::TimerKind::t_fb && ev.result == server::TimerResult::byte_won);
			CHECK(byte_won, "the T_fb event records that the byte won");
			CHECK(c.fallback[static_cast<std::size_t>(detect::Proto::smtp)] == 0, "no fallback dispatch");
			return std::nullopt;
		}

		// ---- Two workers ----

		Result two_workers(Listener listener, Detect detect)
		{
			ServerArgs a;
			a.workers = 2;
			a.listener = listener;
			a.detect = detect;
			Running srv(a);
			constexpr int kThreads = 8;
			constexpr int kEach = 25;
			std::atomic<int> ok{0};
			std::vector<std::thread> threads;
			const std::uint16_t port = srv.port();
			for (int i = 0; i < kThreads; ++i)
			{
				threads.emplace_back([&ok, port] {
					for (int j = 0; j < kEach; ++j)
					{
						const auto t = opcase::run(Script{}.write(opcase::http_get()), port);
						if (t.received == text(http1::kResponse200) && t.eof) ok.fetch_add(1);
					}
				});
			}
			for (auto& t : threads) t.join();
			CHECK(ok.load() == kThreads * kEach, ok.load() << " of " << kThreads * kEach << " exchanges answered 200");
			if (auto bad = srv.stop_and_check()) return bad;
			const auto per = srv.server->per_worker();
			CHECK(per.size() == 2, "two workers");
			const server::Counters c = srv.server->totals();
			CHECK(c.accepted == kThreads * kEach && c.classified[static_cast<std::size_t>(detect::Proto::http1)] == kThreads * kEach, "every connection classified once");
			return std::nullopt;
		}

		// ---- Every flag combination M1 serves ----

		Result flag_matrix()
		{
			int combos = 0;
			for (const Mode mode : {Mode::one_port, Mode::dedicated})
				for (const Detect detect : {Detect::replay, Detect::peek})
					for (const Proxy proxy : {Proxy::off, Proxy::on})
						for (const Fallback fallback : {Fallback::none, Fallback::smtp, Fallback::ssh})
							for (const Listener listener : {Listener::shared, Listener::reuseport})
								for (const std::uint32_t workers : {1u, 2u})
								{
									ServerArgs a;
									a.mode = mode;
									a.detect = detect;
									a.proxy = proxy;
									a.fallback = fallback;
									a.listener = listener;
									a.workers = workers;
									a.t_fb = a.t_dec = a.t_hdr = 100ms;
									const std::string what = std::string(token(mode)) + " " + std::string(token(detect)) + (proxy == Proxy::on ? " proxy" : "") +
									                         (fallback == Fallback::smtp ? " SMTP" : fallback == Fallback::ssh ? " SSH" : "") +
									                         (listener == Listener::reuseport ? " reuseport" : "") + " workers " + std::to_string(workers);
									Running srv(a);
									const Bytes header = proxy == Proxy::on ? opcase::proxy_v2() : Bytes{};
									opcase::Transcript t;
									run_and_wait(srv, Script{}.write(cat({header, opcase::http_get()})), srv.port(), t);
									CHECK(t.received == text(http1::kResponse200) && t.eof, what << ": no 200");
									if (mode == Mode::one_port && fallback != Fallback::none)
									{
										run_and_wait(srv, Script{}.write(header).await_line().shutdown_write(), srv.port(), t);
										const std::string want = fallback == Fallback::smtp ? "oneport M1 stub SMTP" : "oneport M1 stub SSH";
										CHECK(opcase::first_line(t.received) == want, what << ": a silent client does not reach the fallback");
										CHECK(t.first_byte && *t.first_byte - t.before_connect >= a.t_fb, what << ": the fallback spoke before T_fb");
									}
									if (mode == Mode::dedicated)
									{
										run_and_wait(srv, Script{}.write(header).await_line().shutdown_write(), srv.port_of(detect::Proto::smtp), t);
										CHECK(opcase::first_line(t.received) == "oneport M1 stub SMTP", what << ": the SMTP port");
									}
									if (auto bad = srv.stop_and_check()) return std::string(what + ": " + *bad);
									++combos;
								}
			CHECK(combos == 96, combos << " combinations");
			return std::nullopt;
		}

		// ---- Stop with a pending connection; configurations M1 does not serve ----

		Result stop_with_pending()
		{
			ServerArgs a;
			a.t_fb = a.t_dec = 10000ms;
			Running srv(a);
			const int c = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			sockaddr_in addr{};
			addr.sin_family = AF_INET;
			addr.sin_port = htons(srv.port());
			addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			CHECK(::connect(c, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
			std::this_thread::sleep_for(100ms);
			if (auto bad = srv.stop_and_check()) return bad;
			::close(c);
			const server::Counters t = srv.server->totals();
			CHECK(t.outcomes[static_cast<std::size_t>(server::Outcome::stopped)] == 1, "the pending connection is counted stopped");
			return std::nullopt;
		}

		Result not_served()
		{
			Config c = make_config(ServerArgs{});
			c.backend = Backend::io_uring;
			CHECK(server::not_served_in_m1(c) == std::optional<std::string>("the io_uring backend is M2"), "io_uring");
			c.backend = Backend::epoll;
			c.dispatch = Dispatch::relay;
			CHECK(server::not_served_in_m1(c).has_value(), "relay");
			c.dispatch = Dispatch::inproc;
			c.mode = Mode::stub;
			CHECK(server::not_served_in_m1(c).has_value(), "stub mode");
			bool refused = false;
			try
			{
				server::Server s(c);
			}
			catch (const std::invalid_argument&)
			{
				refused = true;
			}
			CHECK(refused, "the server refuses a configuration M1 does not serve");
			c.mode = Mode::one_port;
			CHECK(!server::not_served_in_m1(c), "one-port epoll inproc is served");
			CHECK(server::Server::conn_state_bytes() > 0, "the connection state has a size");
			return std::nullopt;
		}

		// ---- The binary ----

		Result binary_smoke()
		{
			const std::string& path = binary_path();
			CHECK(!path.empty(), "no binary path given");
			int out[2];
			CHECK(::pipe(out) == 0, "pipe");
			posix_spawn_file_actions_t fa;
			posix_spawn_file_actions_init(&fa);
			posix_spawn_file_actions_adddup2(&fa, out[1], 1);
			posix_spawn_file_actions_addclose(&fa, out[0]);
			std::vector<std::string> args{path, "--mode", "one-port", "--detect", "peek", "--dispatch", "inproc", "--backend", "epoll"};
			std::vector<char*> argv;
			for (auto& s : args) argv.push_back(s.data());
			argv.push_back(nullptr);
			pid_t pid = 0;
			const int rc = posix_spawn(&pid, path.c_str(), &fa, nullptr, argv.data(), environ);
			posix_spawn_file_actions_destroy(&fa);
			::close(out[1]);
			CHECK(rc == 0, "posix_spawn: " << std::strerror(rc));
			std::string text_out;
			std::uint16_t port = 0;
			auto read_more = [&](int ms) {
				pollfd p{out[0], POLLIN, 0};
				if (::poll(&p, 1, ms) <= 0) return false;
				std::array<char, 4096> buf{};
				const ssize_t k = ::read(out[0], buf.data(), buf.size());
				if (k <= 0) return false;
				text_out.append(buf.data(), static_cast<std::size_t>(k));
				return true;
			};
			const std::string key = "oneport: listening one-port 127.0.0.1:";
			while (port == 0 && read_more(10000))
			{
				const auto at = text_out.find(key);
				const auto eol = at == std::string::npos ? std::string::npos : text_out.find('\n', at);
				if (eol != std::string::npos) port = static_cast<std::uint16_t>(std::stoi(text_out.substr(at + key.size(), eol - at - key.size())));
			}
			Result r;
			if (port == 0)
			{
				r = "the binary printed no listening line";
			}
			else
			{
				const auto t = opcase::run(Script{}.write(opcase::http_get()), port);
				if (t.received != text(http1::kResponse200)) r = "the binary did not answer 200";
			}
			::kill(pid, SIGTERM);
			while (read_more(10000))
			{
			}
			int status = 0;
			::waitpid(pid, &status, 0);
			::close(out[0]);
			if (r) return r;
			CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 0, "the binary did not exit 0 after SIGTERM");
			CHECK(text_out.find("counter accepted 1\n") != std::string::npos, "the counters do not show one connection");
			CHECK(text_out.find("counter classified HTTP/1.1 1\n") != std::string::npos, "the counters do not show the classification");
			CHECK(text_out.find("oneport: connection state ") != std::string::npos, "no connection-state size line");
			return std::nullopt;
		}

	}  // namespace

	void register_server_tests(Registry& r)
	{
		r["server.http_keepalive.oneport_replay"] = [] { return http_keepalive(Mode::one_port, Detect::replay); };
		r["server.http_keepalive.oneport_peek"] = [] { return http_keepalive(Mode::one_port, Detect::peek); };
		r["server.http_keepalive.dedicated"] = [] { return http_keepalive(Mode::dedicated, Detect::replay); };
		r["server.dedicated_ports"] = dedicated_ports;
		r["server.dedicated_proxy"] = dedicated_proxy;
		r["server.peek_lowat.peek"] = [] { return peek_lowat(Detect::peek); };
		r["server.peek_lowat.replay"] = [] { return peek_lowat(Detect::replay); };
		r["server.kernel_rcvlowat_et"] = kernel_rcvlowat_et;
		r["server.check_byte_wins.replay"] = [] { return check_byte_wins(Detect::replay); };
		r["server.check_byte_wins.peek"] = [] { return check_byte_wins(Detect::peek); };
		r["server.two_workers.shared_replay"] = [] { return two_workers(Listener::shared, Detect::replay); };
		r["server.two_workers.shared_peek"] = [] { return two_workers(Listener::shared, Detect::peek); };
		r["server.two_workers.reuseport_replay"] = [] { return two_workers(Listener::reuseport, Detect::replay); };
		r["server.two_workers.reuseport_peek"] = [] { return two_workers(Listener::reuseport, Detect::peek); };
		r["server.flag_matrix"] = flag_matrix;
		r["server.stop_with_pending"] = stop_with_pending;
		r["server.not_served"] = not_served;
		r["server.binary_smoke"] = binary_smoke;
	}

}  // namespace oneport::test

#else

namespace oneport::test
{
	void register_server_tests(Registry&) {}
}  // namespace oneport::test

#endif
