// opcase as a program (hypotheses.md, section 2.4): B3's openings of WL7 against any system by
// port, and the probe of a B3 or ophold window. The hard cases run in-process in the test suite
// (cases.hpp); this binary serves the windows. Linux; on Windows (M7e) `case` and `hold` only, for
// W's runners (the pilot's timer and split parts, the hard cases on IOCP, the mixed cell's silent
// background on IOCP): `open` and `probe-reset` serve B3, which runs on L. On Windows the holder
// stops when the named event "Local\oneport-stop-<pid>" is set, as the server does
// (bench/server/main.cpp), since the W runner starts it without a console.
//
//   opcase open --port N --case silent|partial-hello [--n 10000] [--batch 25] [--pace-ms 25]
//               [--close-at-ms 30000] [--src-base A.B.C.D --k-src K]
//     WL7's opening: from t = 0, the first connect, batches of --batch connections, one batch every
//     --pace-ms, until --n are open (each design choices of WL7: N_PEND = 10,000, 25 every 25 ms);
//     each connection then sends the case's bytes, with TCP_NODELAY and one write: nothing
//     (silent), or the TLS record header announcing the recorded ClientHello of length l and its
//     first floor(l/2) bytes (partial-hello). At t = --close-at-ms every connection is closed by
//     reset (SO_LINGER on, zero timeout), so no TIME-WAIT socket is created. Prints "T0 <ns>" at
//     the first connect (CLOCK_MONOTONIC), "OPENED <count> <ns>" after the last batch, "CLOSED
//     <count> <ns>" after the resets, and a JSON line of counts last.
//   opcase probe-reset --port N
//     connects, then closes by reset (the probe of WL7's phase before t = 0, for a system that
//     answers nothing, such as ophold).
//   opcase case --port N [--proxy-port N] --hc K [--variant PREFIX] [--replicates R] [timers, gaps]
//     the hard cases of Appendix A against any system by port, one JSON line per run (M5;
//     bench/cases/run_cases.cpp); `opcase case --list` prints each variant's frozen expectation.
//   opcase hold --ports P[,P...] --n N [--reopen on|off] [--src-base A.B.C.D --k-src K]
//     the mixed-protocol cell's silent background (section 10; bench/cases/hold.hpp): holds N
//     silent connections, round robin over the ports, a connection the peer closes opened again at
//     once to the same port, until SIGTERM or SIGINT. Prints "HOLD <held> <ns>" once all N are
//     held (CLOCK_MONOTONIC), then, at the stop, every connection closed by reset, a JSON line of
//     counts.
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#endif

#include "fixtures.hpp"
#include "hold.hpp"
#include "run_cases.hpp"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <charconv>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#if defined(__linux__)
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#elif defined(_WIN32)
#include <windows.h>

#include <thread>
#endif

namespace
{

#if defined(__linux__)
	std::int64_t now_ns() noexcept
	{
		timespec ts{};
		clock_gettime(CLOCK_MONOTONIC, &ts);
		return static_cast<std::int64_t>(ts.tv_sec) * 1'000'000'000 + ts.tv_nsec;
	}

	void sleep_until(std::int64_t t)
	{
		for (;;)
		{
			const std::int64_t now = now_ns();
			if (now >= t) return;
			const std::int64_t d = t - now;
			timespec ts{static_cast<time_t>(d / 1'000'000'000), static_cast<long>(d % 1'000'000'000)};
			clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, nullptr);
		}
	}
#endif

	template <class T>
	bool number(std::string_view s, T& v)
	{
		const auto [p, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
		return ec == std::errc{} && p == s.data() + s.size();
	}

	std::optional<std::uint32_t> dotted(std::string_view s)
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

#if defined(__linux__)
	void reset_close(int fd)
	{
		const linger l{1, 0};
		::setsockopt(fd, SOL_SOCKET, SO_LINGER, &l, sizeof(l));
		::close(fd);
	}
#endif

	int usage()
	{
		std::fprintf(stderr,
		             "usage: opcase open --port N --case silent|partial-hello [--n 10000] [--batch 25] [--pace-ms 25]\n"
		             "                   [--close-at-ms 30000] [--src-base A.B.C.D --k-src K]\n"
		             "       opcase probe-reset --port N\n"
		             "       opcase case --port N [--proxy-port N] --hc K [--variant PREFIX | --id ID] [--replicates R] ...\n"
		             "       opcase case --list [--hc K] ...\n"
		             "       opcase hold --ports P[,P...] --n N [--reopen on|off] [--src-base A.B.C.D --k-src K]\n");
		return 2;
	}

	std::atomic<bool> g_hold_stop{false};

	void hold_on_signal(int) { g_hold_stop.store(true, std::memory_order_relaxed); }

#if defined(_WIN32)
	/// The holder's stop on Windows: the named event Local\oneport-stop-<pid>, which the W runner
	/// sets as it sets the server's (bench/run/wsys.py, set_stop_event). False if it cannot be made.
	bool watch_stop_event()
	{
		const std::wstring name = L"Local\\oneport-stop-" + std::to_wstring(::GetCurrentProcessId());
		HANDLE ev = ::CreateEventW(nullptr, TRUE, FALSE, name.c_str());
		if (ev == nullptr) return false;
		std::thread([ev] {
			if (::WaitForSingleObject(ev, INFINITE) == WAIT_OBJECT_0) g_hold_stop.store(true, std::memory_order_relaxed);
		}).detach();
		return true;
	}
#endif

	/// `opcase hold ...`: the silent background (hold.hpp).
	int hold_main(int argc, char** argv)
	{
		oneport::opcase::HoldOptions o;
		bool have_n = false;
		for (int i = 2; i + 1 < argc; i += 2)
		{
			const std::string_view a = argv[i];
			std::string_view v = argv[i + 1];
			bool ok = true;
			if (a == "--ports")
			{
				while (ok && !v.empty())
				{
					const std::size_t comma = v.find(',');
					unsigned port = 0;
					ok = number(v.substr(0, comma), port) && port > 0 && port < 65536;
					if (ok) o.ports.push_back(static_cast<std::uint16_t>(port));
					v = comma == std::string_view::npos ? std::string_view{} : v.substr(comma + 1);
				}
			}
			else if (a == "--n")
			{
				ok = number(v, o.n) && o.n > 0;
				have_n = ok;
			}
			else if (a == "--reopen")
			{
				ok = v == "on" || v == "off";
				o.reopen = v == "on";
			}
			else if (a == "--k-src") ok = number(v, o.k_src) && o.k_src > 0;
			else if (a == "--src-base")
			{
				const auto b = dotted(v);
				ok = b && (*b >> 24) == 127 && *b > 0x7F000001u;
				if (ok) o.src_base = *b;
			}
			else ok = false;
			if (!ok) return usage();
		}
		if ((argc - 2) % 2 != 0 || o.ports.empty() || !have_n || (o.src_base == 0) != (o.k_src == 0)) return usage();
		if (o.k_src > 0 && static_cast<std::uint64_t>(o.src_base) + o.k_src - 1 >= 0x7FFFFFFFu) return usage();
#if defined(__linux__)
		rlimit lim{};
		if (getrlimit(RLIMIT_NOFILE, &lim) == 0 && lim.rlim_cur < lim.rlim_max)
		{
			lim.rlim_cur = lim.rlim_max;
			setrlimit(RLIMIT_NOFILE, &lim);
		}
#elif defined(_WIN32)
		if (!watch_stop_event())
		{
			std::fprintf(stderr, "opcase: CreateEvent failed (%lu)\n", ::GetLastError());
			return 1;
		}
#endif
		std::signal(SIGTERM, hold_on_signal);
		std::signal(SIGINT, hold_on_signal);
		const oneport::opcase::HoldResult r = oneport::opcase::hold(o, g_hold_stop, [](const oneport::opcase::HoldResult& at) {
			std::printf("HOLD %u %lld\n", at.held_at_ready, static_cast<long long>(at.ready_ns));
			std::fflush(stdout);
		});
		std::printf("%s\n", oneport::opcase::hold_json(o, r).c_str());
		std::fflush(stdout);
		return r.ok ? 0 : 1;
	}

#if defined(__linux__)
	sockaddr_in loopback(std::uint16_t port)
	{
		sockaddr_in to{};
		to.sin_family = AF_INET;
		to.sin_port = htons(port);
		to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		return to;
	}

	int probe_reset(std::uint16_t port)
	{
		const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
		const sockaddr_in to = loopback(port);
		if (fd < 0 || ::connect(fd, reinterpret_cast<const sockaddr*>(&to), sizeof(to)) != 0)
		{
			std::fprintf(stderr, "opcase: probe connect failed: %s\n", std::strerror(errno));
			if (fd >= 0) ::close(fd);
			return 1;
		}
		reset_close(fd);
		std::printf("{\"probe\":\"reset\",\"ok\":true}\n");
		return 0;
	}
#endif

}  // namespace

int main(int argc, char** argv)
{
	if (argc < 2) return usage();
	const std::string_view cmd = argv[1];
	if (cmd == "case") return oneport::opcase::run_cases(argc, argv);
	if (cmd == "hold") return hold_main(argc, argv);
#if defined(_WIN32)
	std::fprintf(stderr, "opcase: %.*s runs on Linux only (B3's openings and probe); on Windows: case and hold\n",
	             static_cast<int>(cmd.size()), cmd.data());
	return usage();
#else
	unsigned port = 0;
	std::string kase;
	std::uint32_t n = 10000;
	std::uint32_t batch = 25;
	std::uint32_t pace_ms = 25;
	std::uint32_t close_at_ms = 30000;
	std::uint32_t src_base = 0;
	std::uint32_t k_src = 0;
	for (int i = 2; i + 1 < argc; i += 2)
	{
		const std::string_view a = argv[i];
		const std::string_view v = argv[i + 1];
		bool ok = true;
		if (a == "--port") ok = number(v, port) && port > 0 && port < 65536;
		else if (a == "--case") kase = std::string(v);
		else if (a == "--n") ok = number(v, n) && n > 0;
		else if (a == "--batch") ok = number(v, batch) && batch > 0;
		else if (a == "--pace-ms") ok = number(v, pace_ms);
		else if (a == "--close-at-ms") ok = number(v, close_at_ms);
		else if (a == "--k-src") ok = number(v, k_src) && k_src > 0;
		else if (a == "--src-base")
		{
			const auto b = dotted(v);
			ok = b && (*b >> 24) == 127 && *b > 0x7F000001u;
			if (ok) src_base = *b;
		}
		else ok = false;
		if (!ok) return usage();
	}
	if ((argc - 2) % 2 != 0 || port == 0) return usage();
	if (cmd == "probe-reset") return probe_reset(static_cast<std::uint16_t>(port));
	if (cmd != "open" || (kase != "silent" && kase != "partial-hello")) return usage();
	if ((src_base == 0) != (k_src == 0)) return usage();
	// As opgen's: the block lies in 127.0.0.2 to 127.255.255.254.
	if (k_src > 0 && static_cast<std::uint64_t>(src_base) + k_src - 1 >= 0x7FFFFFFFu) return usage();
	rlimit lim{};
	if (getrlimit(RLIMIT_NOFILE, &lim) == 0 && lim.rlim_cur < lim.rlim_max)
	{
		lim.rlim_cur = lim.rlim_max;
		setrlimit(RLIMIT_NOFILE, &lim);
	}
	oneport::opcase::Bytes bytes;
	if (kase == "partial-hello")
	{
		const oneport::opcase::Bytes rec = oneport::opcase::recorded_client_hello();
		const std::size_t ell = rec.size() - 5;  // the length the record header announces (WL7's l)
		bytes = oneport::opcase::slice(rec, 0, 5 + ell / 2);
	}
	const sockaddr_in to = loopback(static_cast<std::uint16_t>(port));
	std::vector<int> open;
	open.reserve(n);
	std::uint64_t connect_failures = 0;
	std::uint64_t write_failures = 0;
	std::uint64_t src_next = 0;
	const std::int64_t t0 = now_ns();
	std::printf("T0 %lld\n", static_cast<long long>(t0));
	std::fflush(stdout);
	for (std::uint32_t b = 0; open.size() + connect_failures < n; ++b)
	{
		sleep_until(t0 + static_cast<std::int64_t>(b) * pace_ms * 1'000'000);
		std::vector<pollfd> pending;
		const std::uint32_t want = static_cast<std::uint32_t>(std::min<std::uint64_t>(batch, n - open.size() - connect_failures));
		for (std::uint32_t k = 0; k < want; ++k)
		{
			const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
			if (fd < 0)
			{
				++connect_failures;
				continue;
			}
			const int one = 1;
			::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
			if (k_src > 0)
			{
				::setsockopt(fd, IPPROTO_IP, IP_BIND_ADDRESS_NO_PORT, &one, sizeof(one));
				sockaddr_in src{};
				src.sin_family = AF_INET;
				src.sin_addr.s_addr = htonl(src_base + static_cast<std::uint32_t>(src_next++ % k_src));
				if (::bind(fd, reinterpret_cast<const sockaddr*>(&src), sizeof(src)) != 0)
				{
					::close(fd);
					++connect_failures;
					continue;
				}
			}
			if (::connect(fd, reinterpret_cast<const sockaddr*>(&to), sizeof(to)) == 0 || errno == EINPROGRESS)
			{
				pending.push_back(pollfd{fd, POLLOUT, 0});
				continue;
			}
			::close(fd);
			++connect_failures;
		}
		// Each connect of the batch completes within a second, or counts as failed.
		const std::int64_t limit = now_ns() + 1'000'000'000;
		std::size_t left = pending.size();
		while (left > 0 && now_ns() < limit)
		{
			const int ms = static_cast<int>(std::max<std::int64_t>(1, (limit - now_ns()) / 1'000'000));
			if (::poll(pending.data(), pending.size(), ms) <= 0) continue;
			for (pollfd& p : pending)
			{
				if (p.fd < 0 || p.revents == 0) continue;
				int err = 0;
				socklen_t len = sizeof(err);
				::getsockopt(p.fd, SOL_SOCKET, SO_ERROR, &err, &len);
				if (err != 0)
				{
					::close(p.fd);
					++connect_failures;
				}
				else
				{
					// One write per chunk (section 2.4): the case's bytes, if any.
					if (!bytes.empty() && ::send(p.fd, bytes.data(), bytes.size(), MSG_NOSIGNAL) != static_cast<ssize_t>(bytes.size())) ++write_failures;
					open.push_back(p.fd);
				}
				p.fd = -1;
				--left;
			}
		}
		for (pollfd& p : pending)
		{
			if (p.fd < 0) continue;
			::close(p.fd);
			++connect_failures;
		}
	}
	const std::int64_t opened_at = now_ns();
	std::printf("OPENED %zu %lld\n", open.size(), static_cast<long long>(opened_at));
	std::fflush(stdout);
	sleep_until(t0 + static_cast<std::int64_t>(close_at_ms) * 1'000'000);
	for (const int fd : open) reset_close(fd);
	const std::int64_t closed_at = now_ns();
	std::printf("CLOSED %zu %lld\n", open.size(), static_cast<long long>(closed_at));
	std::printf("{\"case\":\"%s\",\"n\":%u,\"opened\":%zu,\"connect_failures\":%llu,\"write_failures\":%llu,\"bytes_per_conn\":%zu,"
	            "\"t0_ns\":%lld,\"opened_ns\":%lld,\"closed_ns\":%lld,\"batch\":%u,\"pace_ms\":%u,\"close_at_ms\":%u}\n",
	            kase.c_str(), n, open.size(), static_cast<unsigned long long>(connect_failures), static_cast<unsigned long long>(write_failures),
	            bytes.size(), static_cast<long long>(t0), static_cast<long long>(opened_at), static_cast<long long>(closed_at), batch, pace_ms,
	            close_at_ms);
	return connect_failures == 0 && write_failures == 0 ? 0 : 1;
#endif
}
