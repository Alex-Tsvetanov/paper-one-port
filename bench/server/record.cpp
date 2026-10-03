// The per-connection decision record of the binary (see record.hpp).
#include "record.hpp"

#include <chrono>
#include <cstdint>
#include <stdexcept>
#include <string_view>

namespace oneport::server
{

	namespace
	{

		std::int64_t ns(TimePoint t) noexcept { return std::chrono::duration_cast<std::chrono::nanoseconds>(t.time_since_epoch()).count(); }

		/// A JSON object written field by field; keys and the names written are plain ASCII.
		class Obj
		{
		public:
			Obj& num(std::string_view k, std::int64_t v) { return raw(k, std::to_string(v)); }
			Obj& unum(std::string_view k, std::uint64_t v) { return raw(k, std::to_string(v)); }
			Obj& flag(std::string_view k, bool v) { return raw(k, v ? "true" : "false"); }
			Obj& str(std::string_view k, std::string_view v) { return raw(k, std::string("\"") + std::string(v) + "\""); }
			Obj& raw(std::string_view k, const std::string& v)
			{
				s_ += s_.size() > 1 ? ", \"" : "\"";
				s_ += k;
				s_ += "\": ";
				s_ += v;
				return *this;
			}
			std::string done() { return s_ + "}"; }

		private:
			std::string s_ = "{";
		};

		std::string_view name(TimerResult r) noexcept
		{
			switch (r)
			{
				case TimerResult::closed: return "closed";
				case TimerResult::fallback: return "fallback";
				case TimerResult::byte_won: return "byte_won";
				case TimerResult::waited: return "waited";
			}
			return "?";
		}

		std::string timed(const TimedEvent& e)
		{
			return Obj{}
				.str("kind", name(e.kind))
				.str("result", name(e.result))
				.num("start_ns", ns(e.start))
				.num("deadline_ns", ns(e.deadline))
				.num("wait_return_ns", ns(e.wait_return))
				.num("prev_wait_return_ns", ns(e.prev_wait_return))
				.num("handled_at_ns", ns(e.handled_at))
				.unum("pass", e.pass)
				.done();
		}

		std::string source(const detect::ProxySource& p)
		{
			static constexpr char kHex[] = "0123456789abcdef";
			std::string addr;
			for (const std::uint8_t b : p.addr)
			{
				addr += kHex[b >> 4];
				addr += kHex[b & 15];
			}
			return Obj{}.unum("family", static_cast<unsigned>(p.family)).str("addr", addr).unum("port", p.port).done();
		}

	}  // namespace

	Recorder::Recorder(const std::string& path)
	{
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable : 4996)  // MSVC deprecates fopen (C4996); fopen's sharing and behaviour are the ones wanted
#endif
		f_ = std::fopen(path.c_str(), "w");
#ifdef _MSC_VER
#pragma warning(pop)
#endif
		if (f_ == nullptr) throw std::runtime_error("oneport: --record: cannot open " + path);
	}

	Recorder::~Recorder()
	{
		if (f_ != nullptr) std::fclose(f_);
	}

	void Recorder::write(const std::string& s)
	{
		const std::lock_guard<std::mutex> lock(m_);
		std::fwrite(s.data(), 1, s.size(), f_);
		std::fputc('\n', f_);
	}

	void Recorder::flush()
	{
		const std::lock_guard<std::mutex> lock(m_);
		std::fflush(f_);
	}

	std::string Recorder::line(const DetectionReport& r)
	{
		return Obj{}
			.str("event", "detection")
			.unum("worker", r.worker)
			.unum("conn", r.conn)
			.unum("peer_port", r.peer_port)
			.str("outcome", name(r.outcome))
			.str("proto", detect::name(r.proto))
			.unum("at", r.at)
			.unum("proxy_reason", static_cast<unsigned>(r.proxy_reason))
			.unum("accept_pass", r.accept_pass)
			.unum("end_pass", r.end_pass)
			.unum("last_read_pass", r.last_read_pass)
			.unum("observe_pass", r.observe_pass)
			.num("accept_ns", ns(r.accept_time))
			.num("timers_start_ns", ns(r.timers_start))
			.num("end_ns", ns(r.end_time))
			.unum("app_bytes", r.app_bytes)
			.unum("max_user_bytes", r.max_user_bytes)
			.flag("buffer_while_silent", r.buffer_while_silent)
			.unum("wakeups", r.wakeups)
			.unum("lowat_sets", r.lowat_sets)
			.unum("lowat_resets", r.lowat_resets)
			.flag("has_proxy", r.has_proxy)
			.raw("proxy", r.has_proxy ? source(r.proxy) : std::string("null"))
			.raw("timed", r.timed ? timed(r.event) : std::string("null"))
			.flag("replayed", r.replayed)
			.done();
	}

	std::string Recorder::line(const RelayReport& r)
	{
		return Obj{}
			.str("event", "relayed")
			.unum("worker", r.worker)
			.unum("conn", r.conn)
			.unum("peer_port", r.peer_port)
			.str("route", name(r.route))
			.str("proto", detect::name(r.proto))
			.unum("backend_port", r.backend_port)
			.unum("route_pass", r.route_pass)
			.unum("hello_len", r.hello_len)
			.unum("hello_records", r.hello_records)
			.unum("held_max", r.held_max)
			.unum("hello_room_max", r.hello_room_max)
			.flag("buffer_waiting", r.buffer_waiting)
			.done();
	}

	std::string Recorder::line(const CloseReport& r)
	{
		return Obj{}
			.str("event", "closed")
			.unum("worker", r.worker)
			.unum("conn", r.conn)
			.unum("peer_port", r.peer_port)
			.flag("handled", r.handled)
			.str("proto", detect::name(r.proto))
			.unum("bytes_received", r.bytes_received)
			.unum("bytes_sent", r.bytes_sent)
			.done();
	}

	Hooks Recorder::hooks()
	{
		Hooks h;
		h.ctx = this;
		h.detection = [](void* ctx, const DetectionReport& r) { static_cast<Recorder*>(ctx)->write(line(r)); };
		h.relayed = [](void* ctx, const RelayReport& r) { static_cast<Recorder*>(ctx)->write(line(r)); };
		h.closed = [](void* ctx, const CloseReport& r) { static_cast<Recorder*>(ctx)->write(line(r)); };
		return h;
	}

}  // namespace oneport::server
