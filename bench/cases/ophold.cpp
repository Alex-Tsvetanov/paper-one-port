// ophold, the holder (hypotheses.md, section 2.4; WL7): it accepts connections and holds them
// without reading or polling them, so that a window of silent connections held by it measures the
// kernel's per-socket baseline for B3 (K_BASE). Linux.
//
//   ophold --port N [--backlog B]
//
// It listens on 127.0.0.1:N (0: a port the kernel picks, for the tests) with backlog B (default
// 10000, WL7's N_PEND: "listen backlogs at N_PEND wherever a system has a setting"), prints
// "ophold: listening 127.0.0.1:N backlog B'" (B' the backlog after the kernel's cap at
// net.core.somaxconn), accepts in a blocking loop on the listener alone and keeps every accepted
// descriptor open, untouched. At
// SIGINT or SIGTERM it prints "ophold: held <count>" and exits 0; the descriptors close at exit.
// Its soft RLIMIT_NOFILE starts at the hard limit (WL7).
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <charconv>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <string_view>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <pthread.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <unistd.h>

namespace
{

	std::atomic<std::uint64_t> g_held{0};

	bool number(std::string_view s, unsigned& v)
	{
		const auto [p, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
		return ec == std::errc{} && p == s.data() + s.size();
	}

}  // namespace

int main(int argc, char** argv)
{
	unsigned port = 0;
	bool have_port = false;
	unsigned backlog = 10000;
	for (int i = 1; i < argc; ++i)
	{
		const std::string_view a = argv[i];
		if (i + 1 < argc && a == "--port" && number(argv[i + 1], port) && port < 65536)
		{
			have_port = true;
			++i;
			continue;
		}
		if (i + 1 < argc && a == "--backlog" && number(argv[i + 1], backlog) && backlog > 0)
		{
			++i;
			continue;
		}
		std::fprintf(stderr, "usage: ophold --port N [--backlog B]\n");
		return 2;
	}
	if (!have_port)
	{
		std::fprintf(stderr, "usage: ophold --port N [--backlog B]\n");
		return 2;
	}
	rlimit lim{};
	if (getrlimit(RLIMIT_NOFILE, &lim) == 0 && lim.rlim_cur < lim.rlim_max)
	{
		lim.rlim_cur = lim.rlim_max;
		setrlimit(RLIMIT_NOFILE, &lim);
	}
	// The stop signals are taken by a thread of their own; the main thread only accepts.
	sigset_t stop;
	sigemptyset(&stop);
	sigaddset(&stop, SIGINT);
	sigaddset(&stop, SIGTERM);
	pthread_sigmask(SIG_BLOCK, &stop, nullptr);
	const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
	const int one = 1;
	::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
	sockaddr_in a{};
	a.sin_family = AF_INET;
	a.sin_port = htons(static_cast<std::uint16_t>(port));
	a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	if (fd < 0 || ::bind(fd, reinterpret_cast<const sockaddr*>(&a), sizeof(a)) != 0 || ::listen(fd, static_cast<int>(backlog)) != 0)
	{
		std::fprintf(stderr, "ophold: cannot listen on 127.0.0.1:%u: %s\n", port, std::strerror(errno));
		return 1;
	}
	std::thread waiter([&stop] {
		int sig = 0;
		sigwait(&stop, &sig);
		std::printf("ophold: held %llu\n", static_cast<unsigned long long>(g_held.load()));
		std::fflush(stdout);
		std::_Exit(0);
	});
	waiter.detach();
	sockaddr_in bound{};
	socklen_t bound_len = sizeof(bound);
	::getsockname(fd, reinterpret_cast<sockaddr*>(&bound), &bound_len);
	// The kernel caps a backlog at net.core.somaxconn; the line names the value that applies.
	unsigned somaxconn = backlog;
	if (std::FILE* f = std::fopen("/proc/sys/net/core/somaxconn", "r"))
	{
		if (std::fscanf(f, "%u", &somaxconn) != 1) somaxconn = backlog;
		std::fclose(f);
	}
	std::printf("ophold: listening 127.0.0.1:%u backlog %u\n", static_cast<unsigned>(ntohs(bound.sin_port)), std::min(backlog, somaxconn));
	std::fflush(stdout);
	std::vector<int> held;
	held.reserve(backlog);
	for (;;)
	{
		const int c = ::accept4(fd, nullptr, nullptr, SOCK_CLOEXEC);
		if (c >= 0)
		{
			held.push_back(c);  // held, never read, never polled
			g_held.fetch_add(1);
			continue;
		}
		if (errno == EINTR || errno == ECONNABORTED) continue;
		std::fprintf(stderr, "ophold: accept: %s\n", std::strerror(errno));
		return 1;
	}
}
