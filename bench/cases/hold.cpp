// opcase hold: the silent background of the mixed-protocol cell (see hold.hpp). Linux.
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

#else

namespace oneport::opcase
{

	HoldResult hold(const HoldOptions&, const std::atomic<bool>&, const std::function<void(const HoldResult&)>&)
	{
		HoldResult r;
		r.error = "hold: Linux only";
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
