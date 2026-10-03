// opcase case: the hard cases of Appendix A against any system by port (M5's carried item; the
// competitors' descriptive table of section 10, and WL8's hard-case runs against the server in its
// own process with --record). Linux.
//
//   opcase case --port N [--proxy-port N] --hc K [--variant PREFIX] [--replicates R]
//               [--t-fb-ms 3000] [--t-dec-ms 3000] [--t-hdr-ms 3000] [--gap-split-ms 10] [--drip-gap-ms 5]
//               [--g-ms 100] [--wait-ms 60000]
//
// Runs every variant of hard case K (bench/cases/cases.hpp, in its fixed order), or those whose id
// starts with PREFIX, R times each, against 127.0.0.1: a variant whose setup needs the PROXY
// header against --proxy-port, every other against --port (the caller starts the system with the
// listener the setup names: a fallback, a PROXY listener). The timers and gaps build the scripts as
// the suite's variants() does: the frozen timers are 3 s (section 1); GAP_SPLIT and G come from the
// pilot entry (section 9.2), and until then the suite's stand-ins are the defaults. --wait-ms bounds
// every wait of a script and its final read: T_OBS = 60 s (section 10). Prints one JSON line per
// run: the variant, its frozen expectation, and the transcript, every time in nanoseconds of
// CLOCK_MONOTONIC, the clock of the server's --record. It judges nothing; the runner does.
#include "cases.hpp"
#include "run_cases.hpp"

#include <charconv>
#include <chrono>
#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

namespace oneport::opcase
{

	namespace
	{

		template <class T>
		bool number(std::string_view s, T& v)
		{
			const auto [p, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
			return ec == std::errc{} && p == s.data() + s.size();
		}

		long long ns(TimePoint t) { return static_cast<long long>(std::chrono::duration_cast<std::chrono::nanoseconds>(t.time_since_epoch()).count()); }

		std::string_view name(When w)
		{
			switch (w)
			{
				case When::at_once: return "at_once";
				case When::t_fb: return "t_fb";
				case When::t_dec: return "t_dec";
				case When::t_hdr: return "t_hdr";
			}
			return "?";
		}

		std::string_view name(Reply r)
		{
			switch (r)
			{
				case Reply::dedicated: return "dedicated";
				case Reply::http200: return "http200";
				case Reply::http400: return "http400";
				case Reply::closed: return "closed";
				case Reply::any: return "any";
				case Reply::tls_flight: return "tls_flight";
			}
			return "?";
		}

		std::string hex(const Bytes& b)
		{
			static constexpr char kHex[] = "0123456789abcdef";
			std::string s;
			s.reserve(2 * b.size());
			for (const std::byte x : b)
			{
				const auto v = std::to_integer<unsigned>(x);
				s += kHex[v >> 4];
				s += kHex[v & 15];
			}
			return s;
		}

		std::string quoted(std::string_view s)
		{
			std::string out = "\"";
			for (const char ch : s)
			{
				if (ch == '"' || ch == '\\') out += '\\';
				if (static_cast<unsigned char>(ch) < 0x20) continue;
				out += ch;
			}
			return out + "\"";
		}

		bool needs_proxy(Setup s) { return s == Setup::proxy || s == Setup::proxy_fallback_smtp; }

		int usage()
		{
			std::fprintf(stderr,
			             "usage: opcase case --port N [--proxy-port N] --hc K [--variant PREFIX] [--replicates R]\n"
			             "                   [--t-fb-ms 3000] [--t-dec-ms 3000] [--t-hdr-ms 3000] [--gap-split-ms 10]\n"
			             "                   [--drip-gap-ms 5] [--g-ms 100] [--wait-ms 60000]\n");
			return 2;
		}

	}  // namespace

	std::string run_line(const Variant& v, int hc, unsigned replicate, std::uint16_t port, const Transcript& t)
	{
		std::string s = "{\"id\": " + quoted(v.id) + ", \"hc\": " + std::to_string(hc) + ", \"replicate\": " + std::to_string(replicate);
		s += ", \"setup\": " + quoted(name(v.setup)) + ", \"expect\": " + quoted(name(v.expect)) + ", \"proto\": " + quoted(detect::name(v.proto));
		s += ", \"when\": " + quoted(name(v.when)) + ", \"reply\": " + quoted(name(v.reply));
		s += ", \"at\": " + (v.at ? std::to_string(*v.at) : std::string("null"));
		s += ", \"port\": " + std::to_string(port) + ", \"connected\": " + (t.connected ? "true" : "false");
		s += ", \"local_port\": " + std::to_string(t.local_port) + ", \"before_connect_ns\": " + std::to_string(ns(t.before_connect));
		s += ", \"after_connect_ns\": " + std::to_string(ns(t.after_connect)) + ", \"write_ns\": [";
		for (std::size_t i = 0; i < t.write_times.size(); ++i) s += (i ? ", " : "") + std::to_string(ns(t.write_times[i]));
		s += "], \"sent\": " + std::to_string(t.sent.size()) + ", \"write_failed\": " + (t.write_failed ? "true" : "false");
		s += ", \"received_hex\": \"" + hex(t.received) + "\"";
		s += ", \"first_byte_ns\": " + (t.first_byte ? std::to_string(ns(*t.first_byte)) : std::string("null"));
		s += ", \"end_ns\": " + (t.end ? std::to_string(ns(*t.end)) : std::string("null"));
		s += std::string(", \"eof\": ") + (t.eof ? "true" : "false") + ", \"reset\": " + (t.reset ? "true" : "false");
		s += std::string(", \"client_reset\": ") + (t.client_reset ? "true" : "false") + ", \"timed_out\": " + (t.timed_out ? "true" : "false");
		if (t.tls)
		{
			const TlsResult& r = *t.tls;
			s += std::string(", \"tls\": {\"handshake\": ") + (r.handshake ? "true" : "false") + ", \"version\": " + quoted(r.version) +
			     ", \"cipher\": " + quoted(r.cipher) + ", \"alpn\": " + quoted(r.alpn) + ", \"plain_hex\": \"" + hex(r.plain) + "\"" +
			     ", \"close_notify\": " + (r.close_notify ? "true" : "false") + ", \"error\": " + quoted(r.error) + "}";
		}
		else
		{
			s += ", \"tls\": null";
		}
		return s + "}";
	}

	int run_cases(int argc, char** argv)
	{
		unsigned port = 0;
		unsigned proxy_port = 0;
		int hc = 0;
		std::string prefix;
		unsigned replicates = 1;
		SuiteParams p;
		p.t_fb = p.t_dec = p.t_hdr = std::chrono::milliseconds(3000);  // section 1's frozen timers
		unsigned wait_ms = 60000;                                       // T_OBS (section 10)
		for (int i = 2; i + 1 < argc; i += 2)
		{
			const std::string_view a = argv[i];
			const std::string_view val = argv[i + 1];
			unsigned ms = 0;
			bool ok = true;
			if (a == "--port") ok = number(val, port) && port > 0 && port < 65536;
			else if (a == "--proxy-port") ok = number(val, proxy_port) && proxy_port > 0 && proxy_port < 65536;
			else if (a == "--hc") ok = number(val, hc) && hc >= 1 && hc <= kCases;
			else if (a == "--variant") prefix = std::string(val);
			else if (a == "--replicates") ok = number(val, replicates) && replicates > 0;
			else if (a == "--wait-ms") ok = number(val, wait_ms) && wait_ms > 0;
			else if (number(val, ms) && ms > 0)
			{
				if (a == "--t-fb-ms") p.t_fb = std::chrono::milliseconds(ms);
				else if (a == "--t-dec-ms") p.t_dec = std::chrono::milliseconds(ms);
				else if (a == "--t-hdr-ms") p.t_hdr = std::chrono::milliseconds(ms);
				else if (a == "--gap-split-ms") p.gap_split = std::chrono::milliseconds(ms);
				else if (a == "--drip-gap-ms") p.drip_gap = std::chrono::milliseconds(ms);
				else if (a == "--g-ms") p.g = std::chrono::milliseconds(ms);
				else ok = false;
			}
			else ok = false;
			if (!ok) return usage();
		}
		if ((argc - 2) % 2 != 0 || port == 0 || hc == 0) return usage();
		Limits limits;
		limits.wait = std::chrono::milliseconds(wait_ms);
		int failures = 0;
		for (const Variant& v : variants(hc, p))
		{
			if (!v.id.starts_with(prefix)) continue;
			const unsigned target = needs_proxy(v.setup) ? proxy_port : port;
			if (target == 0)
			{
				std::printf("{\"id\": %s, \"hc\": %d, \"skipped\": \"no --proxy-port for its PROXY setup\"}\n", quoted(v.id).c_str(), hc);
				continue;
			}
			for (unsigned r = 1; r <= replicates; ++r)
			{
				const Transcript t = run(v.script, static_cast<std::uint16_t>(target), limits);
				if (!t.connected) ++failures;
				std::puts(run_line(v, hc, r, static_cast<std::uint16_t>(target), t).c_str());
				std::fflush(stdout);
			}
		}
		return failures == 0 ? 0 : 1;
	}

}  // namespace oneport::opcase
