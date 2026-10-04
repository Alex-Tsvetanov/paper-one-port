// opcase hold: the silent background of the mixed-protocol cell (see hold.hpp). Linux and Windows.
#include "hold.hpp"

#if defined(__linux__)

#include <algorithm>
#include <cerrno>
#include <cstring>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

namespace oneport::opcase
{

	namespace
	{

		std::int64_t mono_ns() noexcept
		{
			timespec ts{};
			clock_gettime(CLOCK_MONOTONIC, &ts);
			return static_cast<std::int64_t>(ts.tv_sec) * 1'000'000'000 + ts.tv_nsec;
		}

		void reset_close(int fd) noexcept
		{
			const linger l{1, 0};
			::setsockopt(fd, SOL_SOCKET, SO_LINGER, &l, sizeof(l));
			::close(fd);
		}

		struct Slot
		{
			int fd = -1;
			std::uint16_t port = 0;
			bool connected = false;
			std::int64_t started = 0;  // when its connect was made
		};

		/// Opens one slot's connection: a non-blocking connect, from the block when one is given.
		void open_slot(Slot& s, const HoldOptions& o, std::uint64_t& next_src, HoldResult& r)
		{
			++r.connects;
			s.connected = false;
			s.started = mono_ns();
			const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
			if (fd < 0)
			{
				++r.connect_failures;
				s.fd = -1;
				return;
			}
			if (o.k_src > 0)
			{
				const int one = 1;
				::setsockopt(fd, IPPROTO_IP, IP_BIND_ADDRESS_NO_PORT, &one, sizeof(one));
				sockaddr_in src{};
				src.sin_family = AF_INET;
				src.sin_addr.s_addr = htonl(o.src_base + static_cast<std::uint32_t>(next_src++ % o.k_src));
				if (::bind(fd, reinterpret_cast<const sockaddr*>(&src), sizeof(src)) != 0)
				{
					::close(fd);
					++r.connect_failures;
					s.fd = -1;
					return;
				}
			}
			sockaddr_in to{};
			to.sin_family = AF_INET;
			to.sin_port = htons(s.port);
			to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			if (::connect(fd, reinterpret_cast<const sockaddr*>(&to), sizeof(to)) == 0)
			{
				s.fd = fd;
				s.connected = true;
				return;
			}
			if (errno == EINPROGRESS)
			{
				s.fd = fd;
				return;
			}
			::close(fd);
			++r.connect_failures;
			s.fd = -1;
		}

		/// Reads what a held connection has: bytes are discarded; true when the peer has closed it
		/// (EOF, a reset, or an error).
		bool drain(int fd, HoldResult& r)
		{
			char buf[4096];
			for (;;)
			{
				const ssize_t n = ::recv(fd, buf, sizeof(buf), 0);
				if (n > 0)
				{
					r.bytes_received += static_cast<std::uint64_t>(n);
					continue;
				}
				if (n == 0) return true;
				if (errno == EAGAIN || errno == EWOULDBLOCK) return false;
				if (errno == EINTR) continue;
				return true;
			}
		}

	}  // namespace

	HoldResult hold(const HoldOptions& o, const std::atomic<bool>& stop, const std::function<void(const HoldResult&)>& on_ready)
	{
		HoldResult r;
		if (o.n == 0 || o.ports.empty())
		{
			r.error = "hold: no connection to hold (n is 0 or no port)";
			return r;
		}
		std::vector<Slot> slots(o.n);
		for (std::size_t i = 0; i < slots.size(); ++i) slots[i].port = o.ports[i % o.ports.size()];
		std::uint64_t next_src = 0;
		bool ready = false;
		std::vector<pollfd> pfds;
		std::vector<std::size_t> which;
		pfds.reserve(slots.size());
		which.reserve(slots.size());
		const auto limit_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(o.connect_limit).count();
		while (!stop.load(std::memory_order_relaxed))
		{
			++r.passes;
			// Every empty slot gets a connection: at the start, after a failed connect, and, with
			// the reopen policy, after the peer closed it.
			for (Slot& s : slots)
			{
				if (s.fd < 0 && (s.started == 0 || o.reopen || !s.connected)) open_slot(s, o, next_src, r);
			}
			pfds.clear();
			which.clear();
			for (std::size_t i = 0; i < slots.size(); ++i)
			{
				if (slots[i].fd < 0) continue;
				pfds.push_back(pollfd{slots[i].fd, static_cast<short>(slots[i].connected ? (POLLIN | POLLRDHUP) : POLLOUT), 0});
				which.push_back(i);
			}
			const int got = ::poll(pfds.data(), pfds.size(), 50);
			if (got < 0 && errno != EINTR)
			{
				r.error = std::string("hold: poll: ") + std::strerror(errno);
				break;
			}
			const std::int64_t now = mono_ns();
			for (std::size_t k = 0; k < pfds.size(); ++k)
			{
				Slot& s = slots[which[k]];
				const short ev = got > 0 ? pfds[k].revents : 0;
				if (!s.connected)
				{
					if (ev != 0)
					{
						int err = 0;
						socklen_t len = sizeof(err);
						::getsockopt(s.fd, SOL_SOCKET, SO_ERROR, &err, &len);
						if (err == 0)
						{
							s.connected = true;
							continue;
						}
					}
					else if (now - s.started < limit_ns)
					{
						continue;
					}
					::close(s.fd);
					s.fd = -1;
					++r.connect_failures;
					continue;
				}
				if (ev == 0) continue;
				if (drain(s.fd, r))
				{
					::close(s.fd);
					s.fd = -1;
					++r.closed_by_peer;
					if (o.reopen)
					{
						open_slot(s, o, next_src, r);
						++r.reopened;
					}
				}
			}
			const auto held = static_cast<std::uint32_t>(std::count_if(slots.begin(), slots.end(), [](const Slot& s) { return s.fd >= 0 && s.connected; }));
			if (!ready && held == o.n)
			{
				ready = true;
				r.ready_ns = mono_ns();
				r.held_at_ready = held;
				r.held_min = held;
				if (on_ready) on_ready(r);
			}
			else if (ready)
			{
				r.held_min = std::min(r.held_min, held);
			}
		}
		r.held_at_stop = static_cast<std::uint32_t>(std::count_if(slots.begin(), slots.end(), [](const Slot& s) { return s.fd >= 0 && s.connected; }));
		for (Slot& s : slots)
		{
			if (s.fd >= 0) reset_close(s.fd);
			s.fd = -1;
		}
		r.stop_ns = mono_ns();
		r.ok = r.error.empty();
		return r;
	}

}  // namespace oneport::opcase

#elif defined(_WIN32)

// The same policy on Winsock (M7e), for the mixed cell on IOCP: non-blocking sockets polled with
// WSAPoll, which has no POLLRDHUP, so a held connection's end is seen when it is readable and its
// receive returns 0 or an error; a connect that completes is writable, one that fails reports an
// error or never completes within connect_limit; each source address of the block is bound with
// SO_REUSE_UNICASTPORT, Windows' counterpart of IP_BIND_ADDRESS_NO_PORT that opgen sets on W (the
// revision log's entry "W before the code freeze", item 6 (a)). Times are std::chrono::steady_clock's
// (QueryPerformanceCounter), the clock of the server on W.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <algorithm>
#include <mutex>

namespace oneport::opcase
{

	namespace
	{

		std::int64_t mono_ns() noexcept
		{
			return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
		}

		/// Winsock 2.2, started once for the process and never cleaned up (as script.cpp's client).
		int winsock_once()
		{
			static std::once_flag once;
			static int rc = 0;
			std::call_once(once, [] {
				WSADATA d{};
				rc = ::WSAStartup(MAKEWORD(2, 2), &d);
			});
			return rc;
		}

		void reset_close(SOCKET s) noexcept
		{
			const linger l{1, 0};
			::setsockopt(s, SOL_SOCKET, SO_LINGER, reinterpret_cast<const char*>(&l), sizeof(l));
			::closesocket(s);
		}

		struct Slot
		{
			SOCKET s = INVALID_SOCKET;
			std::uint16_t port = 0;
			bool connected = false;
			std::int64_t started = 0;  // when its connect was made
		};

		void fail_slot(Slot& s, SOCKET fd, HoldResult& r) noexcept
		{
			if (fd != INVALID_SOCKET) ::closesocket(fd);
			++r.connect_failures;
			s.s = INVALID_SOCKET;
		}

		/// Opens one slot's connection: a non-blocking connect, from the block when one is given.
		void open_slot(Slot& s, const HoldOptions& o, std::uint64_t& next_src, HoldResult& r)
		{
			++r.connects;
			s.connected = false;
			s.started = mono_ns();
			const SOCKET fd = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
			if (fd == INVALID_SOCKET) return fail_slot(s, fd, r);
			u_long non_blocking = 1;
			if (::ioctlsocket(fd, FIONBIO, &non_blocking) != 0) return fail_slot(s, fd, r);
			if (o.k_src > 0)
			{
				const BOOL one = TRUE;
				if (::setsockopt(fd, SOL_SOCKET, SO_REUSE_UNICASTPORT, reinterpret_cast<const char*>(&one), sizeof(one)) != 0) return fail_slot(s, fd, r);
				sockaddr_in src{};
				src.sin_family = AF_INET;
				src.sin_addr.s_addr = htonl(o.src_base + static_cast<std::uint32_t>(next_src++ % o.k_src));
				if (::bind(fd, reinterpret_cast<const sockaddr*>(&src), sizeof(src)) != 0) return fail_slot(s, fd, r);
			}
			sockaddr_in to{};
			to.sin_family = AF_INET;
			to.sin_port = htons(s.port);
			to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			if (::connect(fd, reinterpret_cast<const sockaddr*>(&to), sizeof(to)) == 0)
			{
				s.s = fd;
				s.connected = true;
				return;
			}
			if (::WSAGetLastError() == WSAEWOULDBLOCK)
			{
				s.s = fd;
				return;
			}
			fail_slot(s, fd, r);
		}

		/// Reads what a held connection has: bytes are discarded; true when the peer has closed it
		/// (EOF, a reset, or an error).
		bool drain(SOCKET fd, HoldResult& r)
		{
			char buf[4096];
			for (;;)
			{
				const int n = ::recv(fd, buf, static_cast<int>(sizeof(buf)), 0);
				if (n > 0)
				{
					r.bytes_received += static_cast<std::uint64_t>(n);
					continue;
				}
				if (n == 0) return true;
				const int e = ::WSAGetLastError();
				if (e == WSAEWOULDBLOCK) return false;
				if (e == WSAEINTR) continue;
				return true;
			}
		}

	}  // namespace

	HoldResult hold(const HoldOptions& o, const std::atomic<bool>& stop, const std::function<void(const HoldResult&)>& on_ready)
	{
		HoldResult r;
		if (o.n == 0 || o.ports.empty())
		{
			r.error = "hold: no connection to hold (n is 0 or no port)";
			return r;
		}
		if (const int e = winsock_once(); e != 0)
		{
			r.error = "hold: WSAStartup failed (" + std::to_string(e) + ")";
			return r;
		}
		std::vector<Slot> slots(o.n);
		for (std::size_t i = 0; i < slots.size(); ++i) slots[i].port = o.ports[i % o.ports.size()];
		std::uint64_t next_src = 0;
		bool ready = false;
		std::vector<WSAPOLLFD> pfds;
		std::vector<std::size_t> which;
		pfds.reserve(slots.size());
		which.reserve(slots.size());
		const auto limit_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(o.connect_limit).count();
		while (!stop.load(std::memory_order_relaxed))
		{
			++r.passes;
			for (Slot& s : slots)
			{
				if (s.s == INVALID_SOCKET && (s.started == 0 || o.reopen || !s.connected)) open_slot(s, o, next_src, r);
			}
			pfds.clear();
			which.clear();
			for (std::size_t i = 0; i < slots.size(); ++i)
			{
				if (slots[i].s == INVALID_SOCKET) continue;
				WSAPOLLFD p{};
				p.fd = slots[i].s;
				p.events = static_cast<SHORT>(slots[i].connected ? POLLRDNORM : POLLWRNORM);
				pfds.push_back(p);
				which.push_back(i);
			}
			int got = 0;
			if (pfds.empty())
			{
				::Sleep(50);  // WSAPoll refuses an empty set; every slot failed to open in this pass
			}
			else
			{
				got = ::WSAPoll(pfds.data(), static_cast<ULONG>(pfds.size()), 50);
				if (got == SOCKET_ERROR)
				{
					r.error = "hold: WSAPoll failed (" + std::to_string(::WSAGetLastError()) + ")";
					break;
				}
			}
			const std::int64_t now = mono_ns();
			for (std::size_t k = 0; k < pfds.size(); ++k)
			{
				Slot& s = slots[which[k]];
				const SHORT ev = got > 0 ? pfds[k].revents : static_cast<SHORT>(0);
				if (!s.connected)
				{
					if (ev != 0)
					{
						int err = 0;
						int len = sizeof(err);
						::getsockopt(s.s, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&err), &len);
						if (err == 0 && (ev & (POLLERR | POLLHUP | POLLNVAL)) == 0)
						{
							s.connected = true;
							continue;
						}
					}
					else if (now - s.started < limit_ns)
					{
						continue;
					}
					fail_slot(s, s.s, r);
					continue;
				}
				if (ev == 0) continue;
				if (drain(s.s, r))
				{
					::closesocket(s.s);
					s.s = INVALID_SOCKET;
					++r.closed_by_peer;
					if (o.reopen)
					{
						open_slot(s, o, next_src, r);
						++r.reopened;
					}
				}
			}
			const auto held = static_cast<std::uint32_t>(
				std::count_if(slots.begin(), slots.end(), [](const Slot& s) { return s.s != INVALID_SOCKET && s.connected; }));
			if (!ready && held == o.n)
			{
				ready = true;
				r.ready_ns = mono_ns();
				r.held_at_ready = held;
				r.held_min = held;
				if (on_ready) on_ready(r);
			}
			else if (ready)
			{
				r.held_min = std::min(r.held_min, held);
			}
		}
		r.held_at_stop = static_cast<std::uint32_t>(
			std::count_if(slots.begin(), slots.end(), [](const Slot& s) { return s.s != INVALID_SOCKET && s.connected; }));
		for (Slot& s : slots)
		{
			if (s.s != INVALID_SOCKET) reset_close(s.s);
			s.s = INVALID_SOCKET;
		}
		r.stop_ns = mono_ns();
		r.ok = r.error.empty();
		return r;
	}

}  // namespace oneport::opcase

#else

namespace oneport::opcase
{

	HoldResult hold(const HoldOptions&, const std::atomic<bool>&, const std::function<void(const HoldResult&)>&)
	{
		HoldResult r;
		r.error = "hold: Linux and Windows only";
		return r;
	}

}  // namespace oneport::opcase

#endif

namespace oneport::opcase
{

	std::string hold_json(const HoldOptions& o, const HoldResult& r)
	{
		std::string ports;
		for (std::size_t i = 0; i < o.ports.size(); ++i) ports += (i ? "," : "") + std::to_string(o.ports[i]);
		auto u = [](std::uint64_t v) { return std::to_string(v); };
		std::string s = "{\"hold\": true, \"ok\": " + std::string(r.ok ? "true" : "false") + ", \"error\": \"";
		for (const char c : r.error)
		{
			if (c == '"' || c == '\\') s += '\\';
			if (static_cast<unsigned char>(c) >= 0x20) s += c;
		}
		s += "\", \"ports\": [" + ports + "], \"n\": " + u(o.n) + ", \"reopen\": " + (o.reopen ? "true" : "false");
		s += ", \"connects\": " + u(r.connects) + ", \"connect_failures\": " + u(r.connect_failures);
		s += ", \"closed_by_peer\": " + u(r.closed_by_peer) + ", \"reopened\": " + u(r.reopened) + ", \"bytes_received\": " + u(r.bytes_received);
		s += ", \"held_at_ready\": " + u(r.held_at_ready) + ", \"held_min\": " + u(r.held_min) + ", \"held_at_stop\": " + u(r.held_at_stop);
		s += ", \"ready_ns\": " + std::to_string(r.ready_ns) + ", \"stop_ns\": " + std::to_string(r.stop_ns) + ", \"passes\": " + u(r.passes) + "}";
		return s;
	}

}  // namespace oneport::opcase
