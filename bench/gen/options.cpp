// opgen's command line, names and JSON report (opgen.hpp). Every platform.
#include "opgen.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <set>
#include <sstream>

namespace oneport::opgen
{

	std::string_view name(Proto p) noexcept
	{
		switch (p)
		{
			case Proto::http1: return "http1";
			case Proto::h2c: return "h2c";
			case Proto::tls: return "tls";
			case Proto::mqtt: return "mqtt";
			case Proto::ssh: return "ssh";
			case Proto::tls_stub: return "tls-stub";
		}
		return "?";
	}

	Quantiles quantiles(std::vector<std::uint64_t> v)
	{
		Quantiles q;
		q.n = v.size();
		if (v.empty()) return q;
		std::sort(v.begin(), v.end());
		const std::size_t n = v.size();
		q.median = n % 2 == 1 ? static_cast<double>(v[n / 2]) : (static_cast<double>(v[n / 2 - 1]) + static_cast<double>(v[n / 2])) / 2.0;
		auto rank = [&](double p) {
			const auto k = static_cast<std::size_t>(std::ceil(p * static_cast<double>(n)));
			return v[std::clamp<std::size_t>(k, 1, n) - 1];
		};
		q.p99 = rank(0.99);
		q.p999 = rank(0.999);
		long double sum = 0;
		for (const auto x : v) sum += static_cast<long double>(x);
		q.mean = static_cast<double>(sum / static_cast<long double>(n));
		q.min = v.front();
		q.max = v.back();
		return q;
	}

	std::string_view name(Load l) noexcept { return l == Load::churn ? "churn" : "keepalive"; }

	std::string dotted(std::uint32_t a)
	{
		return std::to_string(a >> 24) + "." + std::to_string((a >> 16) & 0xFF) + "." + std::to_string((a >> 8) & 0xFF) + "." + std::to_string(a & 0xFF);
	}

	std::optional<std::uint32_t> parse_dotted(std::string_view s)
	{
		std::uint32_t out = 0;
		for (int part = 0; part < 4; ++part)
		{
			unsigned v = 0;
			const auto [p, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
			if (ec != std::errc{} || p == s.data() || v > 255) return std::nullopt;
			out = (out << 8) | v;
			s.remove_prefix(static_cast<std::size_t>(p - s.data()));
			if (part < 3)
			{
				if (s.empty() || s.front() != '.') return std::nullopt;
				s.remove_prefix(1);
			}
		}
		if (!s.empty()) return std::nullopt;
		return out;
	}

	std::string usage()
	{
		return "usage: opgen --port N --proto http1|h2c|tls|mqtt|ssh|tls-stub [--load churn|keepalive]\n"
		       "             [--conns C] [--rate R] [--threads N] [--cpus LIST] [--src-base A.B.C.D] [--k-src K]\n"
		       "             [--warmup-ms MS] [--duration-ms MS] [--timeout-ms MS] [--probe] [--out FILE]\n"
		       "  --load churn       a new connection per exchange (WL1); with --rate, open loop (WL2)\n"
		       "  --load keepalive   C connections, one request in flight each (WL3)\n"
		       "  --cpus             one CPU per worker thread, e.g. 2-13 or 2,3,4; sets --threads\n"
		       "  --src-base, --k-src  the window's source-address block in 127.0.0.0/8 (K_SRC addresses)\n"
		       "  --probe            one exchange of the protocol, then a report (exit 0 if it completed)\n"
		       "  --out              the JSON report (else standard output); MEASURE_START and MEASURE_END\n"
		       "                     go to standard output at the window's two clock readings\n";
	}

	namespace
	{

		template <class T>
		bool number(std::string_view s, T& v)
		{
			const auto [p, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
			return ec == std::errc{} && p == s.data() + s.size();
		}

		bool cpu_list(std::string_view s, std::vector<int>& out)
		{
			out.clear();
			while (!s.empty())
			{
				const std::size_t comma = s.find(',');
				const std::string_view item = s.substr(0, comma);
				const std::size_t dash = item.find('-');
				int lo = 0;
				int hi = 0;
				if (dash == std::string_view::npos)
				{
					if (!number(item, lo)) return false;
					hi = lo;
				}
				else if (!number(item.substr(0, dash), lo) || !number(item.substr(dash + 1), hi))
				{
					return false;
				}
				if (lo < 0 || hi < lo || hi > 1023) return false;
				for (int c = lo; c <= hi; ++c) out.push_back(c);
				if (comma == std::string_view::npos) break;
				s.remove_prefix(comma + 1);
			}
			return !out.empty();
		}

	}  // namespace

	std::expected<Options, std::string> parse_args(const std::vector<std::string_view>& args)
	{
		Options o;
		std::set<std::string_view> seen;
		bool have_port = false;
		bool have_proto = false;
		bool have_threads = false;
		std::string out_unused;
		for (std::size_t i = 0; i < args.size(); ++i)
		{
			const std::string_view a = args[i];
			if (a == "--probe")
			{
				o.probe = true;
				continue;
			}
			if (a.substr(0, 2) != "--") return std::unexpected("unexpected argument " + std::string(a));
			if (!seen.insert(a).second) return std::unexpected(std::string(a) + " given twice");
			if (i + 1 >= args.size()) return std::unexpected(std::string(a) + " needs a value");
			const std::string_view v = args[++i];
			auto bad = [&] { return std::unexpected(std::string(a) + ": bad value " + std::string(v)); };
			if (a == "--port")
			{
				unsigned p = 0;
				if (!number(v, p) || p == 0 || p > 65535) return bad();
				o.port = static_cast<std::uint16_t>(p);
				have_port = true;
			}
			else if (a == "--proto")
			{
				if (v == "http1") o.proto = Proto::http1;
				else if (v == "h2c") o.proto = Proto::h2c;
				else if (v == "tls") o.proto = Proto::tls;
				else if (v == "mqtt") o.proto = Proto::mqtt;
				else if (v == "ssh") o.proto = Proto::ssh;
				else if (v == "tls-stub") o.proto = Proto::tls_stub;
				else return bad();
				have_proto = true;
			}
			else if (a == "--load")
			{
				if (v == "churn") o.load = Load::churn;
				else if (v == "keepalive") o.load = Load::keepalive;
				else return bad();
			}
			else if (a == "--conns")
			{
				if (!number(v, o.conns) || o.conns == 0) return bad();
			}
			else if (a == "--rate")
			{
				double r = 0;
				if (!number(v, r) || !(r > 0) || !std::isfinite(r)) return bad();
				o.rate = r;
			}
			else if (a == "--threads")
			{
				if (!number(v, o.threads) || o.threads == 0 || o.threads > 1024) return bad();
				have_threads = true;
			}
			else if (a == "--cpus")
			{
				if (!cpu_list(v, o.cpus)) return bad();
			}
			else if (a == "--src-base")
			{
				const auto b = parse_dotted(v);
				if (!b) return bad();
				o.src_base = *b;
			}
			else if (a == "--k-src")
			{
				if (!number(v, o.k_src) || o.k_src == 0) return bad();
			}
			else if (a == "--warmup-ms" || a == "--duration-ms" || a == "--timeout-ms")
			{
				std::uint64_t ms = 0;
				if (!number(v, ms) || ms > 3'600'000) return bad();
				const auto d = std::chrono::milliseconds(ms);
				if (a == "--warmup-ms") o.warmup = d;
				else if (a == "--duration-ms") o.duration = d;
				else o.timeout = d;
				if (a != "--warmup-ms" && ms == 0) return bad();
			}
			else if (a == "--out")
			{
				out_unused = std::string(v);  // read by main
			}
			else
			{
				return std::unexpected("unknown flag " + std::string(a));
			}
		}
		if (!have_port) return std::unexpected("missing --port");
		if (!have_proto) return std::unexpected("missing --proto");
		if (!o.cpus.empty())
		{
			if (have_threads && o.threads != o.cpus.size()) return std::unexpected("--threads differs from the count of --cpus");
			o.threads = static_cast<std::uint32_t>(o.cpus.size());
		}
		if (o.load == Load::keepalive && (o.proto == Proto::ssh || o.proto == Proto::tls_stub))
		{
			return std::unexpected("--load keepalive serves http1, h2c, tls and mqtt (WL3)");
		}
		if (o.rate > 0 && o.load != Load::churn) return std::unexpected("--rate is the open loop of churn (WL2)");
		// The block lies in 127.0.0.0/8 and leaves out 127.0.0.0, the server's 127.0.0.1 and
		// 127.255.255.255.
		const std::uint64_t last = static_cast<std::uint64_t>(o.src_base) + o.k_src - 1;
		if ((o.src_base >> 24) != 127 || (last >> 24) != 127 || o.src_base <= 0x7F000001u || last >= 0x7FFFFFFFu)
		{
			return std::unexpected("--src-base and --k-src: the block must lie in 127.0.0.2 to 127.255.255.254");
		}
		return o;
	}

	namespace
	{

		std::string q(const Quantiles& x)
		{
			std::ostringstream s;
			s << "{\"n\":" << x.n << ",\"median\":" << x.median << ",\"p99\":" << x.p99 << ",\"p999\":" << x.p999 << ",\"mean\":" << x.mean
			  << ",\"min\":" << x.min << ",\"max\":" << x.max << "}";
			return s.str();
		}

		std::string e(const Errors& x)
		{
			std::ostringstream s;
			s << "{\"connect\":" << x.connect << ",\"timeout\":" << x.timeout << ",\"reset\":" << x.reset << ",\"eof\":" << x.eof
			  << ",\"protocol\":" << x.protocol << ",\"tls\":" << x.tls << ",\"total\":" << x.total() << "}";
			return s.str();
		}

		std::string ph(const Phase& p)
		{
			std::ostringstream s;
			s << "{\"completed\":" << p.completed << ",\"errors\":" << e(p.errors) << "}";
			return s.str();
		}

		std::string esc(std::string_view v)
		{
			std::string out;
			for (const char c : v)
			{
				if (c == '"' || c == '\\')
				{
					out += '\\';
					out += c;
				}
				else if (static_cast<unsigned char>(c) < 0x20)
				{
					char buf[8];
					std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned>(static_cast<unsigned char>(c)));
					out += buf;
				}
				else
				{
					out += c;
				}
			}
			return out;
		}

	}  // namespace

	std::string to_json(const Options& o, const Result& r)
	{
		std::ostringstream s;
		s.precision(17);
		s << "{\"tool\":\"opgen\",\"ok\":" << (r.ok ? "true" : "false") << ",\"error\":\"" << esc(r.error) << "\"";
		s << ",\"proto\":\"" << name(o.proto) << "\",\"load\":\"" << name(o.load) << "\",\"mode\":\"" << (o.rate > 0 ? "open" : "closed")
		  << "\",\"rate\":" << o.rate << ",\"conns\":" << o.conns << ",\"threads\":" << o.threads << ",\"cpus\":[";
		for (std::size_t i = 0; i < o.cpus.size(); ++i) s << (i ? "," : "") << o.cpus[i];
		s << "],\"src_base\":\"" << dotted(o.src_base) << "\",\"k_src\":" << o.k_src << ",\"port\":" << o.port;
		s << ",\"warmup_ms\":" << std::chrono::duration_cast<std::chrono::milliseconds>(o.warmup).count()
		  << ",\"duration_ms\":" << std::chrono::duration_cast<std::chrono::milliseconds>(o.duration).count()
		  << ",\"timeout_ms\":" << std::chrono::duration_cast<std::chrono::milliseconds>(o.timeout).count() << ",\"probe\":" << (o.probe ? "true" : "false");
		s << ",\"measure_start_ns\":" << r.start_ns << ",\"measure_end_ns\":" << r.end_ns << ",\"wall_s\":" << r.wall_s;
		s << ",\"warmup\":" << ph(r.warmup) << ",\"measure\":" << ph(r.measure) << ",\"connects_run\":" << r.measure.connects
		  << ",\"all_completed\":" << r.all_completed;
		const std::uint64_t attempts = r.measure.completed + r.measure.errors.total();
		s << ",\"error_share\":" << (attempts ? static_cast<double>(r.measure.errors.total()) / static_cast<double>(attempts) : 1.0);
		s << ",\"connect_failures\":" << (r.warmup.errors.connect + r.measure.errors.connect);
		s << ",\"due\":" << r.due << ",\"due_completed\":" << r.due_completed << ",\"due_errors\":" << e(r.due_errors)
		  << ",\"due_unfinished\":" << r.due_unfinished << ",\"completed_share\":" << (r.due ? static_cast<double>(r.due_completed) / static_cast<double>(r.due) : 0.0);
		s << ",\"ttfb_ns\":" << q(r.ttfb) << ",\"ttfb_connect_ns\":" << q(r.ttfb_connect) << ",\"exchange_ns\":" << q(r.exchange)
		  << ",\"issue_lag_ns\":" << q(r.issue_lag);
		s << ",\"cpu\":{\"threads_s\":[";
		for (std::size_t i = 0; i < r.thread_cpu_s.size(); ++i) s << (i ? "," : "") << r.thread_cpu_s[i];
		s << "],\"sum_s\":" << r.cpu_s << ",\"pct\":" << r.cpu_pct << ",\"max_thread_pct\":" << r.max_thread_cpu_pct << ",\"process_s\":" << r.process_cpu_s << "}";
		s << ",\"peak_concurrency_per_worker\":" << r.peak_concurrency << ",\"probe_detail\":\"" << esc(r.probe_detail) << "\"}";
		return s.str();
	}

}  // namespace oneport::opgen
