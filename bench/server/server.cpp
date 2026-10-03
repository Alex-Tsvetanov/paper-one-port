// oneport's server on epoll and io_uring (design/proposal.md I3 to I5, I9 to I18, I20, I22 to I24,
// I26, I27, I29; the fallback rules of hypotheses.md, section 1).
//
// One worker per thread, each with its own epoll set or io_uring ring (bench/loop). On epoll the
// sockets are non-blocking and registered edge-triggered with EPOLLRDHUP in both modes (the
// trigger mode is fixed in engineering, proposal I11: edge-triggered, as the M1 brief and nginx's
// peek path have it); io_uring is completion-based (bench/server/uring.cpp).
//
// A pass: wait until the earliest deadline (epoll_pwait2, or io_uring_enter with its timeout),
// read the clock, handle every readiness event or completion, then every expiry whose deadline is
// at or before the clock reading taken after the wait. A deadline that passes while the pass
// handles events waits for the next pass, whose wait then returns at once (B2 b). Before a
// fallback dispatch, the check of 1(b) peeks one byte, or on io_uring in replay reaps the ring
// without waiting.
//
// The connection state is a tagged union of handler states, and dispatch is a switch on the tag
// (I3). A one-port listener sets the tag at classification, a dedicated listener at accept.
#include "server.hpp"

#include <array>
#include <stdexcept>
#include <system_error>
#include <thread>

#if defined(__linux__)

#include "worker.hpp"

#include <fstream>
#include <random>
#include <utility>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
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

		/// The kernel's ephemeral port range (net.ipv4.ip_local_port_range); its default if unreadable.
		std::pair<std::uint32_t, std::uint32_t> ephemeral_range()
		{
			std::ifstream f("/proc/sys/net/ipv4/ip_local_port_range");
			std::uint32_t low = 0;
			std::uint32_t high = 0;
			if (f >> low >> high && low > 0 && low <= high) return {low, high};
			return {32768, 60999};
		}

		/// Whether nothing holds `port` on 127.0.0.1: a bind without SO_REUSEPORT succeeds.
		bool port_free(std::uint16_t port)
		{
			const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			if (fd < 0) return false;
			const int one = 1;
			::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
			sockaddr_in a{};
			a.sin_family = AF_INET;
			a.sin_port = htons(port);
			a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			const bool ok = ::bind(fd, reinterpret_cast<const sockaddr*>(&a), sizeof(a)) == 0;
			::close(fd);
			return ok;
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
		tls::Ctx ssl_ctx;  // the server's TLS context (bench/tls), one for every worker
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
			// A test convenience, not a value of the design: a run of free consecutive ports below
			// the ephemeral range, where no client's connect takes a port, so neither the clients'
			// connections nor their TIME-WAIT sockets can hold one; from a random first port, at
			// most 200 tries. With SO_REUSEPORT each port is probed first without it, so a group
			// of another process is never joined by chance.
			const std::uint32_t low = ephemeral_range().first;
			const std::uint32_t first_port = 10000;
			if (low > first_port + n)
			{
				std::mt19937 pick(std::random_device{}());
				std::uniform_int_distribution<std::uint32_t> base_of(first_port, static_cast<std::uint32_t>(low - n));
				for (int attempt = 0; attempt < 200; ++attempt)
				{
					const std::uint32_t base = base_of(pick);
					std::vector<int> out;
					bool ok = true;
					for (std::size_t i = 0; i < n && ok; ++i)
					{
						const auto port = static_cast<std::uint16_t>(base + i);
						if (reuseport && !port_free(port))
						{
							ok = false;
							break;
						}
						const int fd = open_listener(port, reuseport, backlog);
						if (fd < 0) ok = false;
						else out.push_back(fd);
					}
					if (ok) return out;
					for (const int f : out) ::close(f);
				}
			}
			// No room below the ephemeral range: a first port the kernel picks, and the ports after it.
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
					const std::uint32_t port = static_cast<std::uint32_t>(base) + static_cast<std::uint32_t>(i);
					if (port > 65535 || (reuseport && !port_free(static_cast<std::uint16_t>(port))))
					{
						ok = false;
						break;
					}
					const int fd = open_listener(static_cast<std::uint16_t>(port), reuseport, backlog);
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
		if (auto why = not_served(config)) throw std::invalid_argument("not served yet: " + *why);
		impl_->config = config;
		impl_->ssl_ctx = tls::server_ctx();
		impl_->shared.ssl_ctx = impl_->ssl_ctx.get();
		impl_->options = options;
		impl_->specs = listener_specs(config);
		impl_->shared.backend = config.backend;
		impl_->shared.detect = config.detect;
		// Relay dispatch applies to one-port listeners only; the listeners know whether they detect.
		impl_->shared.relay = config.dispatch == Dispatch::relay && config.relay_port.has_value();
		impl_->shared.splice = config.relay_copy == RelayCopy::splice;
		if (impl_->shared.relay)
		{
			for (std::size_t i = 0; i < detect::kProtos; ++i)
			{
				// The backend's listeners, in the order of I20: HTTP/1.1, h2c, TLS, MQTT, SSH, SMTP.
				static constexpr std::array<Proto, detect::kProtos> kOrder{Proto::http1, Proto::h2c, Proto::tls, Proto::mqtt, Proto::ssh, Proto::smtp};
				const std::uint32_t port = static_cast<std::uint32_t>(*config.relay_port) + static_cast<std::uint32_t>(i);
				if (port > 65535) throw std::invalid_argument("--relay-port leaves no room for the backend's six ports");
				sockaddr_in& a = impl_->shared.backends[static_cast<std::size_t>(kOrder[i])];
				a = sockaddr_in{};
				a.sin_family = AF_INET;
				a.sin_port = htons(static_cast<std::uint16_t>(port));
				a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			}
		}
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
		if (m.shared.relay)
		{
			// Relay dispatch: TCP_NODELAY on each relaying (one-port) listener, once at start; the
			// sockets it accepts inherit it (pinned: server.kernel_nodelay_inherited), so a relayed
			// client socket needs no setsockopt of its own (M5). Not set in in-process dispatch.
			const int one = 1;
			for (const auto& fds : m.fds)
			{
				for (std::size_t i = 0; i < fds.size(); ++i)
				{
					if (m.specs[i].detects && ::setsockopt(fds[i], IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one)) != 0) throw_errno("setsockopt (TCP_NODELAY)");
				}
			}
		}
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

#elif !defined(_WIN32)  // neither Linux nor Windows: nothing is served (Windows: server_win.cpp)

	struct Server::Impl
	{
		std::vector<ListenerSpec> specs;
	};

	Server::Server(const Config& config, Options) : impl_(std::make_unique<Impl>())
	{
		if (auto why = not_served(config)) throw std::invalid_argument("not served yet: " + *why);
		throw std::invalid_argument("not served yet on this platform");
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
