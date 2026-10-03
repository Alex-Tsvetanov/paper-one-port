// oneport's server on IOCP, Windows (M6a; design/proposal.md I4, I5, I20, I22 to I24; the
// fallback rules of hypotheses.md, section 1). The pass, the detection, the timers and the
// handlers are the shared worker's (worker.cpp, handlers.cpp); IOCP's accept, receive forms and
// output queue are in iocp.cpp. This file holds the listeners and the workers' threads.
//
// Listeners: one socket per listener on 127.0.0.1, with SO_EXCLUSIVEADDRUSE, because Windows'
// SO_REUSEADDR would let another socket bind the same address; the backlog is SOMAXCONN (proposal
// I5). One worker: proposal I4 shares one completion port among the worker threads, which the
// per-worker connection state, deadline lists and counters do not allow as built, so more than one
// worker is not served yet (listeners.cpp, not_served).
#include "server.hpp"

#if defined(_WIN32)

#include "worker.hpp"

#include <random>
#include <stdexcept>
#include <system_error>
#include <thread>

namespace oneport::server
{

	namespace
	{

		using detail::Shared;
		using detail::Worker;
		using detail::fd_of;
		using detail::sock;
		using detail::throw_wsa;

		/// Winsock 2.2 for the server's lifetime: WSAStartup counts its calls, and each is matched by
		/// one WSACleanup.
		struct Winsock
		{
			Winsock()
			{
				WSADATA d{};
				const int e = ::WSAStartup(MAKEWORD(2, 2), &d);
				if (e != 0) throw std::system_error(e, std::system_category(), "WSAStartup");
			}
			~Winsock() { ::WSACleanup(); }
			Winsock(const Winsock&) = delete;
			Winsock& operator=(const Winsock&) = delete;
		};

		/// A listening socket on 127.0.0.1:port (0: any free port), or INVALID_SOCKET with `error`
		/// set when the port is taken or excluded (WSAEADDRINUSE, WSAEACCES), so the caller can try
		/// another.
		SOCKET open_listener(std::uint16_t port, int& error)
		{
			const SOCKET s = ::WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, nullptr, 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
			if (s == INVALID_SOCKET) throw_wsa("WSASocket");
			const BOOL one = TRUE;
			if (::setsockopt(s, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char*>(&one), sizeof(one)) != 0)
			{
				const int e = WSAGetLastError();
				::closesocket(s);
				throw std::system_error(e, std::system_category(), "setsockopt (SO_EXCLUSIVEADDRUSE)");
			}
			sockaddr_in a{};
			a.sin_family = AF_INET;
			a.sin_port = htons(port);
			a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			if (::bind(s, reinterpret_cast<const sockaddr*>(&a), sizeof(a)) != 0)
			{
				error = WSAGetLastError();
				::closesocket(s);
				return INVALID_SOCKET;
			}
			if (::listen(s, SOMAXCONN) != 0)
			{
				const int e = WSAGetLastError();
				::closesocket(s);
				throw std::system_error(e, std::system_category(), "listen");
			}
			return s;
		}

		std::uint16_t bound_port(SOCKET s)
		{
			sockaddr_in a{};
			int n = sizeof(a);
			if (::getsockname(s, reinterpret_cast<sockaddr*>(&a), &n) != 0) throw_wsa("getsockname");
			return ntohs(a.sin_port);
		}

		/// The ports a test server (no --port) draws its run from. Unlike L, W leaves no range free of
		/// clients' ports: its dynamic range for TCP is 1025 to 65535 (`netsh int ipv4 show
		/// dynamicport tcp`, read on 2026-10-03; design/status-m6.md), so each port of a run is probed
		/// by its bind, which fails on a port that is taken or in an excluded range.
		constexpr std::uint32_t kTestPortLow = 10000;
		constexpr std::uint32_t kTestPortHigh = 65535;

	}  // namespace

	struct Server::Impl
	{
		Winsock winsock;  // first: alive before every socket and after the last
		Config config;
		Options options;
		std::vector<ListenerSpec> specs;
		Shared shared;
		std::vector<int> fds;  // the listening sockets (detail::sock), closed at the end
		std::vector<std::uint16_t> ports;
		tls::Ctx ssl_ctx;  // the server's TLS context (bench/tls)
		std::vector<std::unique_ptr<Worker>> workers;
		std::vector<std::thread> threads;
		bool started = false;
		bool stopped = false;

		/// Binds one socket per listener, on consecutive ports from `want` (empty: free ports).
		std::vector<int> bind_all(const std::vector<std::uint16_t>& want)
		{
			const std::size_t n = specs.size();
			std::vector<int> out;
			auto close_all = [&out] {
				for (const int f : out) ::closesocket(sock(f));
				out.clear();
			};
			if (!want.empty())
			{
				for (std::size_t i = 0; i < n; ++i)
				{
					int error = 0;
					const SOCKET s = open_listener(want[i], error);
					if (s == INVALID_SOCKET)
					{
						close_all();
						throw std::system_error(error, std::system_category(), "bind");
					}
					out.push_back(fd_of(s));
				}
				return out;
			}
			// A test convenience, not a value of the design: a run of free consecutive ports from a
			// random first port, at most 200 tries; a port that is taken or excluded fails its bind.
			std::mt19937 pick(std::random_device{}());
			std::uniform_int_distribution<std::uint32_t> base_of(kTestPortLow, static_cast<std::uint32_t>(kTestPortHigh - n));
			for (int attempt = 0; attempt < 200; ++attempt)
			{
				const std::uint32_t base = base_of(pick);
				bool ok = true;
				for (std::size_t i = 0; i < n && ok; ++i)
				{
					int error = 0;
					const SOCKET s = open_listener(static_cast<std::uint16_t>(base + i), error);
					if (s == INVALID_SOCKET) ok = false;
					else out.push_back(fd_of(s));
				}
				if (ok) return out;
				close_all();
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
		impl_->shared.relay = false;  // relay dispatch is Linux only (hypotheses.md, section 2.1)
		impl_->shared.t_fb = std::chrono::milliseconds(config.t_fb_ms);
		impl_->shared.t_dec = std::chrono::milliseconds(config.t_dec_ms);
		impl_->shared.t_hdr = std::chrono::milliseconds(config.t_hdr_ms);
		impl_->shared.hooks = options.hooks;
		impl_->shared.iocp_receive = config.iocp_receive;
		impl_->shared.iocp_accept = config.iocp_accept;
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
		impl_->workers.clear();  // before the listeners they post AcceptEx on
		for (const int fd : impl_->fds) ::closesocket(sock(fd));
	}

	void Server::start()
	{
		Impl& m = *impl_;
		if (m.started) throw std::logic_error("Server::start() may be called once");
		m.started = true;
		std::vector<std::uint16_t> want;
		if (m.config.port)
		{
			for (std::size_t i = 0; i < m.specs.size(); ++i) want.push_back(static_cast<std::uint16_t>(*m.config.port + i));
		}
		m.fds = m.bind_all(want);
		for (const int fd : m.fds) m.ports.push_back(bound_port(sock(fd)));
		for (std::uint32_t w = 0; w < m.config.workers; ++w) m.workers.push_back(std::make_unique<Worker>(w, m.shared, m.specs, m.fds));
		for (std::uint32_t w = 0; w < m.config.workers; ++w)
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

}  // namespace oneport::server

#endif  // _WIN32
