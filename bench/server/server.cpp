// oneport's server on epoll (design/proposal.md I3 to I5, I9 to I16, I20, I26, I27, I29; the
// fallback rules of hypotheses.md, section 1).
//
// One worker per thread, each with its own epoll set (bench/loop). The sockets are non-blocking
// and registered edge-triggered with EPOLLRDHUP in both modes (the trigger mode is fixed in
// engineering, proposal I11: edge-triggered, as the M1 brief and nginx's peek path have it).
//
// A pass: wait until the earliest deadline (epoll_pwait2), read the clock, handle every readiness
// event, then every expiry whose deadline is at or before the clock reading taken after the wait.
// A deadline that passes while the pass handles events waits for the next pass, whose wait then
// returns at once (B2 b). Before a fallback dispatch, the check of 1(b) peeks one byte.
//
// The connection state is a tagged union of handler states, and dispatch is a switch on the tag
// (I3). A one-port listener sets the tag at classification, a dedicated listener at accept.
#include "server.hpp"

#include <stdexcept>
#include <system_error>
#include <thread>

#if defined(__linux__)

#include "worker.hpp"

#include <fstream>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#endif

namespace oneport::server
{

#if defined(__linux__)

	namespace
	{

		using detail::Shared;
		using detail::Worker;
		using detail::throw_errno;

		/// The backlog: net.core.somaxconn, read at startup (proposal I5); SOMAXCONN if unreadable.
		int listen_backlog()
		{
			std::ifstream f("/proc/sys/net/core/somaxconn");
			int v = 0;
			if (f >> v && v > 0) return v;
			return SOMAXCONN;
		}

		/// A listening socket on 127.0.0.1:port (0: any free port). Returns -1 with errno set when
		/// the port is in use, so the caller can try another.
		int open_listener(std::uint16_t port, bool reuseport, int backlog)
		{
			const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
			if (fd < 0) throw_errno("socket");
			const int one = 1;
			if (::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) != 0) throw_errno("setsockopt (SO_REUSEADDR)");
			if (reuseport && ::setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one)) != 0) throw_errno("setsockopt (SO_REUSEPORT)");
			sockaddr_in a{};
			a.sin_family = AF_INET;
			a.sin_port = htons(port);
			a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			if (::bind(fd, reinterpret_cast<const sockaddr*>(&a), sizeof(a)) != 0)
			{
				const int e = errno;
				::close(fd);
				errno = e;
				return -1;
			}
			if (::listen(fd, backlog) != 0) throw_errno("listen");
			return fd;
		}

		std::uint16_t bound_port(int fd)
		{
			sockaddr_in a{};
			socklen_t n = sizeof(a);
			if (::getsockname(fd, reinterpret_cast<sockaddr*>(&a), &n) != 0) throw_errno("getsockname");
			return ntohs(a.sin_port);
		}

	}  // namespace

	struct Server::Impl
	{
		Config config;
		Options options;
		std::vector<ListenerSpec> specs;
		Shared shared;
		std::vector<std::vector<int>> fds;  // per worker (the shared layout repeats one list)
		std::vector<int> owned;             // every listening socket, closed at the end
		std::vector<std::uint16_t> ports;
		std::vector<std::unique_ptr<Worker>> workers;
		std::vector<std::thread> threads;
		bool started = false;
		bool stopped = false;

		/// Binds one socket per listener, on consecutive ports from `base` (0: free ports, found
		/// by binding the first anywhere and trying the next ones after it).
		std::vector<int> bind_all(bool reuseport, int backlog, const std::vector<std::uint16_t>& want)
		{
			const std::size_t n = specs.size();
			if (!want.empty())
			{
				std::vector<int> out;
				for (std::size_t i = 0; i < n; ++i)
				{
					const int fd = open_listener(want[i], reuseport, backlog);
					if (fd < 0)
					{
						for (const int f : out) ::close(f);
						throw_errno("bind");
					}
					out.push_back(fd);
				}
				return out;
			}
			// A test convenience, not a value of the design: try up to 100 free first ports.
			for (int attempt = 0; attempt < 100; ++attempt)
			{
				std::vector<int> out;
				const int first = open_listener(0, reuseport, backlog);
				if (first < 0) throw_errno("bind");
				out.push_back(first);
				const std::uint16_t base = bound_port(first);
				bool ok = true;
				for (std::size_t i = 1; i < n && ok; ++i)
				{
					if (static_cast<std::uint32_t>(base) + i > 65535)
					{
						ok = false;
						break;
					}
					const int fd = open_listener(static_cast<std::uint16_t>(base + i), reuseport, backlog);
					if (fd < 0) ok = false;
					else out.push_back(fd);
				}
				if (ok) return out;
				for (const int f : out) ::close(f);
			}
			throw std::runtime_error("no run of free consecutive ports on 127.0.0.1");
		}
	};

	Server::Server(const Config& config, Options options) : impl_(std::make_unique<Impl>())
	{
		if (auto why = not_served_in_m1(config)) throw std::invalid_argument("not served in M1: " + *why);
		impl_->config = config;
		impl_->options = options;
		impl_->specs = listener_specs(config);
		impl_->shared.detect = config.detect;
		impl_->shared.t_fb = std::chrono::milliseconds(config.t_fb_ms);
		impl_->shared.t_dec = std::chrono::milliseconds(config.t_dec_ms);
		impl_->shared.t_hdr = std::chrono::milliseconds(config.t_hdr_ms);
		impl_->shared.exclusive_listeners = config.listener == Listener::shared;
		impl_->shared.hooks = options.hooks;
	}

	Server::~Server()
	{
		try
		{
			stop();
		}
		catch (...)
		{
		}
		for (const int fd : impl_->owned) ::close(fd);
	}

	void Server::start()
	{
		Impl& m = *impl_;
		if (m.started) throw std::logic_error("Server::start() may be called once");
		m.started = true;
		const int backlog = listen_backlog();
		const bool reuseport = m.config.listener == Listener::reuseport;
		std::vector<std::uint16_t> want;
		if (m.config.port)
		{
			for (std::size_t i = 0; i < m.specs.size(); ++i) want.push_back(static_cast<std::uint16_t>(*m.config.port + i));
		}
		const std::uint32_t nworkers = m.config.workers;
		if (!reuseport)
		{
			const std::vector<int> fds = m.bind_all(false, backlog, want);
			m.owned = fds;
			for (std::uint32_t w = 0; w < nworkers; ++w) m.fds.push_back(fds);
		}
		else
		{
			// One socket per worker and listener, in a SO_REUSEPORT group on the same ports.
			const std::vector<int> first = m.bind_all(true, backlog, want);
			m.owned = first;
			m.fds.push_back(first);
			std::vector<std::uint16_t> ports;
			for (const int fd : first) ports.push_back(bound_port(fd));
			for (std::uint32_t w = 1; w < nworkers; ++w)
			{
				const std::vector<int> more = m.bind_all(true, backlog, ports);
				m.owned.insert(m.owned.end(), more.begin(), more.end());
				m.fds.push_back(more);
			}
		}
		for (const int fd : m.fds.front()) m.ports.push_back(bound_port(fd));
		for (std::uint32_t w = 0; w < nworkers; ++w) m.workers.push_back(std::make_unique<Worker>(w, m.shared, m.specs, m.fds[w]));
		for (std::uint32_t w = 0; w < nworkers; ++w)
		{
			Worker* worker = m.workers[w].get();
			m.threads.emplace_back([worker] { worker->run(); });
		}
	}

	void Server::stop()
	{
		Impl& m = *impl_;
		if (!m.started || m.stopped) return;
		m.stopped = true;
		for (auto& w : m.workers) w->stop();
		for (auto& t : m.threads) t.join();
	}

	std::vector<std::uint16_t> Server::ports() const { return impl_->ports; }
	const std::vector<ListenerSpec>& Server::listeners() const { return impl_->specs; }

	std::vector<Counters> Server::per_worker() const
	{
		std::vector<Counters> out;
		for (const auto& w : impl_->workers) out.push_back(w->counters());
		return out;
	}

	Counters Server::totals() const
	{
		Counters t;
		for (const auto& w : impl_->workers) t += w->counters();
		return t;
	}

	std::optional<std::string> Server::error() const
	{
		for (const auto& w : impl_->workers)
		{
			if (w->error()) return w->error();
		}
		return std::nullopt;
	}

	std::size_t Server::conn_state_bytes() noexcept { return sizeof(detail::Conn); }

#else  // not Linux: M1 serves nothing here (IOCP is M6)

	struct Server::Impl
	{
		std::vector<ListenerSpec> specs;
	};

	Server::Server(const Config& config, Options) : impl_(std::make_unique<Impl>())
	{
		if (auto why = not_served_in_m1(config)) throw std::invalid_argument("not served in M1: " + *why);
		throw std::invalid_argument("not served in M1 on this platform");
	}
	Server::~Server() = default;
	void Server::start() {}
	void Server::stop() {}
	std::vector<std::uint16_t> Server::ports() const { return {}; }
	const std::vector<ListenerSpec>& Server::listeners() const { return impl_->specs; }
	std::vector<Counters> Server::per_worker() const { return {}; }
	Counters Server::totals() const { return {}; }
	std::optional<std::string> Server::error() const { return std::nullopt; }
	std::size_t Server::conn_state_bytes() noexcept { return 0; }

#endif

}  // namespace oneport::server
