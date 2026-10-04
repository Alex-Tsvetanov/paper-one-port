// opcase case: the hard cases of Appendix A against any system by port (M5's carried item; the
// competitors' descriptive table of section 10, and WL8's hard-case runs against the server in its
// own process with --record). Linux.
//
//   opcase case --port N [--proxy-port N] --hc K [--variant PREFIX | --id ID] [--replicates R]
//               [--t-fb-ms 3000] [--t-dec-ms 3000] [--t-hdr-ms 3000] [--gap-split-ms 10] [--drip-gap-ms 5]
//               [--g-ms 100] [--wait-ms 60000]
//   opcase case --list [--hc K] [the same timers and gaps]
//
// Runs every variant of hard case K (bench/cases/cases.hpp, in its fixed order), or those whose id
// starts with PREFIX, or the one whose id is ID, R times each, against 127.0.0.1: a variant whose
// setup needs the PROXY header against --proxy-port, every other against --port (the caller starts the system with the
// listener the setup names: a fallback, a PROXY listener). The timers and gaps build the scripts as
// the suite's variants() does: the frozen timers are 3 s (section 1); GAP_SPLIT and G come from the
// pilot entry (section 9.2), and until then the suite's stand-ins are the defaults. --wait-ms bounds
// every wait of a script and its final read: T_OBS = 60 s (section 10). Prints one JSON line per
// run: the variant, its frozen expectation, and the transcript, every time in nanoseconds of
// CLOCK_MONOTONIC, the clock of the server's --record. It judges nothing; the runner does.
//
// --list (M7c) runs nothing: it prints one line of the constants a judge needs (the replies of
// section 2.1's handlers, the receive buffer that bounds replay's bytes under B2(d), B_CH), then
// one JSON line per variant of case K, or of every case, with its whole frozen expectation as the
// suite's judge reads it (tests/case_tests.cpp): the listener setup, the outcome, the class, when
// it ends, the reply, the dedicated port that gives the reference transcript, the reply of the
// dedicated HTTP/1.1 port where the grammar is checked there too, the deciding byte, the write
// that completes a PROXY header, the PROXY source and refusal reason, and the coverage; the source
// and the reason in the form of the server's --record (bench/server/record.cpp).
#include "apps.hpp"
#include "cases.hpp"
#include "http1.hpp"
#include "run_cases.hpp"
#include "server.hpp"

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

		std::string_view name(Coverage c) { return c == Coverage::full ? "full" : "partial"; }

		template <class T>
		std::string opt(const std::optional<T>& v)
		{
			return v ? std::to_string(*v) : std::string("null");
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

		// Not named quoted: MSVC's standard headers declare std::quoted, which argument-dependent lookup
		// finds for a std::string argument and prefers to this function (M6b, on W).
		std::string json_quoted(std::string_view s)
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

		std::string hex_text(std::string_view t)
		{
			Bytes b;
			for (const char c : t) b.push_back(static_cast<std::byte>(static_cast<unsigned char>(c)));
			return hex(b);
		}

		/// A PROXY source in the form of the server's record (bench/server/record.cpp).
		std::string source_json(const detect::ProxySource& p)
		{
			static constexpr char kHex[] = "0123456789abcdef";
			std::string addr;
			for (const std::uint8_t b : p.addr)
			{
				addr += kHex[b >> 4];
				addr += kHex[b & 15];
			}
			return "{\"family\": " + std::to_string(static_cast<unsigned>(p.family)) + ", \"addr\": \"" + addr + "\", \"port\": " +
			       std::to_string(p.port) + "}";
		}

		/// The constants a judge of the runs needs, once, before the variants.
		std::string constants_line()
		{
			return "{\"constants\": {\"response200_hex\": \"" + hex_text(http1::kResponse200) + "\", \"response400_hex\": \"" +
			       hex_text(http1::kResponse400) + "\", \"ssh_banner_hex\": \"" + hex_text(apps::kSshBanner) + "\", \"smtp_greeting_hex\": \"" +
			       hex_text(apps::kSmtpGreeting) + "\", \"smtp_unknown_hex\": \"" + hex_text(apps::kSmtpUnknown) +
			       "\", \"recv_buf\": " + std::to_string(server::kRecvBuf) + ", \"b_ch\": " + std::to_string(detect::kBCh) + "}}";
		}

		int usage()
		{
			std::fprintf(stderr,
			             "usage: opcase case --port N [--proxy-port N] --hc K [--variant PREFIX | --id ID] [--replicates R]\n"
			             "       opcase case --list [--hc K] [the timers and gaps]\n"
			             "                   [--t-fb-ms 3000] [--t-dec-ms 3000] [--t-hdr-ms 3000] [--gap-split-ms 10]\n"
			             "                   [--drip-gap-ms 5] [--g-ms 100] [--wait-ms 60000]\n");
			return 2;
		}

	}  // namespace

	std::string variant_line(const Variant& v, int hc)
	{
		std::string s = "{\"id\": " + json_quoted(v.id) + ", \"hc\": " + std::to_string(hc) + ", \"title\": " + json_quoted(title(hc));
		s += ", \"setup\": " + json_quoted(name(v.setup)) + ", \"needs_proxy\": " + (needs_proxy(v.setup) ? "true" : "false");
		s += ", \"fallback\": " + std::string(v.setup == Setup::fallback_smtp || v.setup == Setup::proxy_fallback_smtp ? "true" : "false");
		s += ", \"expect\": " + json_quoted(name(v.expect)) + ", \"proto\": " + json_quoted(detect::name(v.proto));
		s += ", \"when\": " + json_quoted(name(v.when)) + ", \"reply\": " + json_quoted(name(v.reply)) + ", \"dedicated\": " + json_quoted(detect::name(v.dedicated));
		s += ", \"dedicated_http_reply\": " + (v.dedicated_http_reply ? json_quoted(name(*v.dedicated_http_reply)) : std::string("null"));
		s += ", \"at\": " + opt(v.at) + ", \"header_write\": " + opt(v.header_write);
		s += ", \"source\": " + (v.source ? source_json(*v.source) : std::string("null"));
		s += ", \"proxy_reason\": " + (v.proxy_reason ? std::to_string(static_cast<unsigned>(*v.proxy_reason)) : std::string("null"));
		s += ", \"coverage\": " + json_quoted(name(v.coverage)) + ", \"pending\": " + json_quoted(v.pending) + "}";
		return s;
	}

	std::string run_line(const Variant& v, int hc, unsigned replicate, std::uint16_t port, const Transcript& t)
	{
		std::string s = "{\"id\": " + json_quoted(v.id) + ", \"hc\": " + std::to_string(hc) + ", \"replicate\": " + std::to_string(replicate);
		s += ", \"setup\": " + json_quoted(name(v.setup)) + ", \"expect\": " + json_quoted(name(v.expect)) + ", \"proto\": " + json_quoted(detect::name(v.proto));
		s += ", \"when\": " + json_quoted(name(v.when)) + ", \"reply\": " + json_quoted(name(v.reply));
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
			s += std::string(", \"tls\": {\"handshake\": ") + (r.handshake ? "true" : "false") + ", \"version\": " + json_quoted(r.version) +
			     ", \"cipher\": " + json_quoted(r.cipher) + ", \"group\": " + json_quoted(r.group) + ", \"sigalg\": " + json_quoted(r.sigalg) +
			     ", \"verified\": " + (r.verified ? "true" : "false") + ", \"resumable\": " + (r.resumable ? "true" : "false") +
			     ", \"alpn\": " + json_quoted(r.alpn) + ", \"plain_hex\": \"" + hex(r.plain) + "\"" +
			     ", \"close_notify\": " + (r.close_notify ? "true" : "false") + ", \"error\": " + json_quoted(r.error) + "}";
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
		std::string exact;
		bool list = false;
		unsigned replicates = 1;
		SuiteParams p;
		p.t_fb = p.t_dec = p.t_hdr = std::chrono::milliseconds(3000);  // section 1's frozen timers
		unsigned wait_ms = 60000;                                       // T_OBS (section 10)
		int i = 2;
		if (i < argc && std::string_view(argv[i]) == "--list")
		{
			list = true;
			++i;
		}
		for (; i + 1 < argc; i += 2)
		{
			const std::string_view a = argv[i];
			const std::string_view val = argv[i + 1];
			unsigned ms = 0;
			bool ok = true;
			if (a == "--port") ok = number(val, port) && port > 0 && port < 65536;
			else if (a == "--proxy-port") ok = number(val, proxy_port) && proxy_port > 0 && proxy_port < 65536;
			else if (a == "--hc") ok = number(val, hc) && hc >= 1 && hc <= kCases;
			else if (a == "--variant") prefix = std::string(val);
			else if (a == "--id") exact = std::string(val);
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
		if (i != argc || (!prefix.empty() && !exact.empty())) return usage();
		if (list)
		{
			std::puts(constants_line().c_str());
			for (int k = 1; k <= kCases; ++k)
			{
				if (hc != 0 && k != hc) continue;
				for (const Variant& v : variants(k, p))
				{
					if (v.id.starts_with(prefix) && (exact.empty() || v.id == exact)) std::puts(variant_line(v, k).c_str());
				}
			}
			std::fflush(stdout);
			return 0;
		}
		if (port == 0 || hc == 0) return usage();
		Limits limits;
		limits.wait = std::chrono::milliseconds(wait_ms);
		int failures = 0;
		for (const Variant& v : variants(hc, p))
		{
			if (!v.id.starts_with(prefix) || (!exact.empty() && v.id != exact)) continue;
			const unsigned target = needs_proxy(v.setup) ? proxy_port : port;
			if (target == 0)
			{
				std::printf("{\"id\": %s, \"hc\": %d, \"skipped\": \"no --proxy-port for its PROXY setup\"}\n", json_quoted(v.id).c_str(), hc);
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
