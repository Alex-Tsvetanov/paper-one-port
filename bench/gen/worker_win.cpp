// opgen's worker on Windows (M6b; worker.hpp): what differs from Linux's epoll worker, which
// worker.cpp calls through its blocks for _WIN32.
//
// Each worker has a completion port of its own. A connection is a socket set up as the server's
// IOCP worker sets an accepted one (bench/server/iocp.cpp): overlapped, non-blocking,
// TCP_NODELAY, associated with the port with FILE_SKIP_COMPLETION_PORT_ON_SUCCESS, so an
// operation that completes at once queues no packet and is handled where it was issued.
//   - Source address (hypotheses.md section 2.4): Windows has no IP_BIND_ADDRESS_NO_PORT. Its
//     counterpart is SO_REUSE_UNICASTPORT, which lets an explicit bind before a connect share an
//     ephemeral port across 4-tuples, as connect's implicit bind does (Winsock's SOL_SOCKET
//     options); a socket that refuses it is not used (the exchange fails at connect).
//   - Connect: ConnectEx, then SO_UPDATE_CONNECT_CONTEXT.
//   - Receive: a zero-byte WSARecv reports bytes or the end (pinned by iocp.pin_zero_byte and
//     iocp.pin_zero_byte_half_close); then synchronous recv drains the socket as Linux's
//     edge-triggered worker does, and the first byte is stamped after the recv that returned it.
//     TLS keeps OpenSSL's socket BIO, so its first byte is stamped as on Linux (on_bio).
//   - Send: synchronous send; what the socket does not take is sent again in the next pass.
//   - Closing a socket cancels its pending operation, whose completion still arrives: every
//     operation has its own OVERLAPPED from a free list, tagged with the slot and the slot's
//     generation, and a completion of a closed connection only returns its operation.
//   - Timed waits: GetQueuedCompletionStatusEx takes whole milliseconds and, without
//     timeBeginPeriod (which opgen does not call), ends on the default timer tick (15.625 ms on
//     W). The open loop therefore wakes on a high-resolution waitable timer: a helper thread on
//     the worker's CPU waits on it and posts a packet to the port, which ends the worker's wait;
//     the last Options::spin before a due time is spent polling, as on Linux. On W such a timer
//     woke 0.3 to 0.5 ms late at the median and up to about 1.3 ms late (design/status-m6b.md),
//     so the W window runner passes a spin above that. The closed loop and keep-alive wait for
//     completions with a bound of whole milliseconds, which only bounds how late a timeout is seen.
#include "worker.hpp"

#if defined(_WIN32)

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <mswsock.h>
#include <windows.h>

#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <system_error>
#include <thread>

namespace oneport::opgen::detail
{

	enum class OpKind : std::uint8_t
	{
		connect,
		readable,  // a zero-byte WSARecv
	};

	/// One pending operation: its OVERLAPPED, and the slot and generation it belongs to.
	struct Op
	{
		OVERLAPPED ov{};
		std::uint32_t idx = 0;
		std::uint32_t gen = 0;
		OpKind kind = OpKind::readable;
		Op* next_free = nullptr;
	};

	namespace
	{

		/// The key of the timer thread's packet; sockets are associated with key 0.
		constexpr ULONG_PTR kTimerKey = 1;
		/// How long a worker waits at its end for the completions of the operations it cancelled.
		constexpr std::int64_t kDrainLimitNs = 5'000'000'000;
		constexpr std::size_t kEntries = 64;

		[[noreturn]] void throw_last(const char* what)
		{
			throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), what);
		}

		DWORD whole_ms(std::chrono::nanoseconds d)
		{
			const auto ms = (d.count() + 999'999) / 1'000'000;
			return static_cast<DWORD>(std::clamp<std::int64_t>(ms, 0, 60'000));
		}

	}  // namespace

	struct Io
	{
		HANDLE port = nullptr;
		HANDLE timer = nullptr;  // open loop: the high-resolution waitable timer
		HANDLE quit = nullptr;   // ends the timer thread
		std::thread timer_thread;
		LPFN_CONNECTEX connect_ex = nullptr;
		std::deque<Op> pool;  // stable addresses: an OVERLAPPED stays where the kernel was given it
		Op* free = nullptr;
		std::uint64_t outstanding = 0;  // operations pending: issued, not completed at once, not dequeued
		bool leak = false;

		Op* take(std::uint32_t idx, std::uint32_t gen, OpKind kind)
		{
			Op* op = free;
			if (op != nullptr) free = op->next_free;
			else op = &pool.emplace_back();
			std::memset(&op->ov, 0, sizeof(op->ov));
			op->idx = idx;
			op->gen = gen;
			op->kind = kind;
			op->next_free = nullptr;
			return op;
		}

		void give(Op* op) noexcept
		{
			op->next_free = free;
			free = op;
		}

		~Io()
		{
			if (timer_thread.joinable())
			{
				SetEvent(quit);
				timer_thread.join();
			}
			if (leak)
			{
				// A cancelled operation did not complete within the drain: its OVERLAPPED may still be
				// written, so the storage is left allocated (finish_io reports it).
				static_cast<void>(new std::deque<Op>(std::move(pool)));
			}
			if (timer != nullptr) CloseHandle(timer);
			if (quit != nullptr) CloseHandle(quit);
			if (port != nullptr) CloseHandle(port);
		}
	};

	void IoFree::operator()(Io* io) const noexcept { delete io; }

	void Worker::close_socket(int fd) noexcept { ::closesocket(static_cast<SOCKET>(fd)); }

	void Worker::pin_thread()
	{
		if (o_.cpus.empty()) return;
		const int cpu = o_.cpus[index_ % o_.cpus.size()];
		if (cpu < 0 || cpu >= 64) throw std::runtime_error("CPU " + std::to_string(cpu) + " is outside processor group 0");
		if (SetThreadAffinityMask(GetCurrentThread(), DWORD_PTR{1} << cpu) == 0) throw_last("SetThreadAffinityMask");
	}

	void Worker::start_io()
	{
		io_.reset(new Io);
		io_->port = CreateIoCompletionPort(INVALID_HANDLE_VALUE, nullptr, 0, 1);
		if (io_->port == nullptr) throw_last("CreateIoCompletionPort");
		const SOCKET s = ::WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, nullptr, 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
		if (s == INVALID_SOCKET) throw std::runtime_error("WSASocketW failed: " + std::to_string(::WSAGetLastError()));
		GUID id = WSAID_CONNECTEX;
		DWORD got = 0;
		const int rc = ::WSAIoctl(s, SIO_GET_EXTENSION_FUNCTION_POINTER, &id, sizeof(id), &io_->connect_ex, sizeof(io_->connect_ex), &got, nullptr, nullptr);
		const int err = ::WSAGetLastError();
		::closesocket(s);
		if (rc != 0 || io_->connect_ex == nullptr) throw std::runtime_error("ConnectEx not found: " + std::to_string(err));
		if (o_.rate <= 0) return;
		io_->timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
		if (io_->timer == nullptr) throw_last("CreateWaitableTimerExW (high resolution)");
		io_->quit = CreateEventW(nullptr, TRUE, FALSE, nullptr);
		if (io_->quit == nullptr) throw_last("CreateEventW");
		const DWORD_PTR cpu_mask = o_.cpus.empty() ? 0 : DWORD_PTR{1} << o_.cpus[index_ % o_.cpus.size()];
		io_->timer_thread = std::thread([port = io_->port, timer = io_->timer, quit = io_->quit, cpu_mask] {
			if (cpu_mask != 0) SetThreadAffinityMask(GetCurrentThread(), cpu_mask);
			const HANDLE hs[2] = {quit, timer};
			for (;;)
			{
				const DWORD r = WaitForMultipleObjects(2, hs, FALSE, INFINITE);
				if (r != WAIT_OBJECT_0 + 1) return;
				PostQueuedCompletionStatus(port, 0, kTimerKey, nullptr);
			}
		});
	}

	void Worker::finish_io() noexcept
	{
		if (!io_) return;
		if (io_->timer_thread.joinable())
		{
			SetEvent(io_->quit);
			io_->timer_thread.join();
		}
		const std::int64_t limit = now_ns() + kDrainLimitNs;
		while (io_->outstanding > 0 && now_ns() < limit)
		{
			std::array<OVERLAPPED_ENTRY, kEntries> e{};
			ULONG n = 0;
			if (!GetQueuedCompletionStatusEx(io_->port, e.data(), static_cast<ULONG>(e.size()), &n, 100, FALSE)) continue;
			for (ULONG k = 0; k < n; ++k)
			{
				if (e[k].lpOverlapped == nullptr) continue;
				--io_->outstanding;
				io_->give(CONTAINING_RECORD(e[k].lpOverlapped, Op, ov));
			}
		}
		if (io_->outstanding > 0)
		{
			io_->leak = true;
			if (error_.empty()) error_ = std::to_string(io_->outstanding) + " cancelled operations did not complete within 5 s";
		}
		io_.reset();
	}

	int Worker::make_socket()
	{
		const SOCKET s = ::WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, nullptr, 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
		if (s == INVALID_SOCKET) return -1;
		auto refuse = [s] {
			::closesocket(s);
			return -1;
		};
		if (s > static_cast<SOCKET>(INT_MAX)) return refuse();  // Conn::fd holds it as an int
		u_long non_blocking = 1;
		const BOOL one = TRUE;
		if (::ioctlsocket(s, FIONBIO, &non_blocking) != 0) return refuse();
		if (::setsockopt(s, SOL_SOCKET, SO_REUSE_UNICASTPORT, reinterpret_cast<const char*>(&one), sizeof(one)) != 0) return refuse();
		::setsockopt(s, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof(one));
		sockaddr_in src{};
		src.sin_family = AF_INET;
		src.sin_addr.s_addr = htonl(next_src());
		if (::bind(s, reinterpret_cast<const sockaddr*>(&src), sizeof(src)) != 0) return refuse();
		if (CreateIoCompletionPort(reinterpret_cast<HANDLE>(s), io_->port, 0, 0) == nullptr) return refuse();
		if (!SetFileCompletionNotificationModes(reinterpret_cast<HANDLE>(s), FILE_SKIP_COMPLETION_PORT_ON_SUCCESS | FILE_SKIP_SET_EVENT_ON_HANDLE))
		{
			return refuse();
		}
		return static_cast<int>(s);
	}

	void Worker::connect_win(std::uint32_t i)
	{
		Conn& c = conns_[i];
		const int fd = spare_fd_ >= 0 ? std::exchange(spare_fd_, -1) : make_socket();
		if (fd < 0)
		{
			c.rec.begin = now_ns();
			fail(i, End::connect);
			return;
		}
		c.fd = fd;
		sockaddr_in to{};
		to.sin_family = AF_INET;
		to.sin_port = htons(o_.port);
		to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		Op* const op = io_->take(i, c.gen, OpKind::connect);
		c.rec.begin = now_ns();  // just before connect (WL1)
		if (o_.rate <= 0) c.rec.due = c.rec.begin;
		++connects_;
		if (!io_->connect_ex(static_cast<SOCKET>(fd), reinterpret_cast<const sockaddr*>(&to), sizeof(to), nullptr, 0, nullptr, &op->ov))
		{
			if (::WSAGetLastError() == ERROR_IO_PENDING)
			{
				++io_->outstanding;  // on_completion takes it from here
				return;
			}
			io_->give(op);
			fail(i, End::connect);
			return;
		}
		// The connect completed at once: no packet comes.
		io_->give(op);
		const std::uint32_t gen = c.gen;
		if (::setsockopt(static_cast<SOCKET>(fd), SOL_SOCKET, SO_UPDATE_CONNECT_CONTEXT, nullptr, 0) != 0)
		{
			fail(i, End::connect);
			return;
		}
		connected(i);
		if (conns_[i].active && conns_[i].gen == gen) arm_read(i);
	}

	void Worker::on_completion(void* p, std::uint32_t, std::uintptr_t status)
	{
		Op* const op = static_cast<Op*>(p);
		const std::uint32_t i = op->idx;
		const std::uint32_t gen = op->gen;
		const OpKind kind = op->kind;
		io_->give(op);
		if (i >= conns_.size()) return;
		Conn& c = conns_[i];
		if (!c.active || c.gen != gen || c.fd < 0) return;  // an operation of a closed connection
		if (kind == OpKind::connect)
		{
			if (status != 0 || ::setsockopt(static_cast<SOCKET>(c.fd), SOL_SOCKET, SO_UPDATE_CONNECT_CONTEXT, nullptr, 0) != 0)
			{
				fail(i, End::connect);  // refused, unreachable or reset
				return;
			}
			connected(i);
		}
		else
		{
			c.reading = false;
			if (over_tls(o_.proto)) drive_tls(i);
			else readable(i);
		}
		// Still the same connection? (The generation, not the exchange's id, which keep-alive
		// changes with every request; a new connection in the slot arms its own reads.)
		if (conns_[i].active && conns_[i].gen == gen) arm_read(i);
	}

	void Worker::arm_read(std::uint32_t i)
	{
		for (;;)
		{
			Conn& c = conns_[i];
			if (!c.active || c.fd < 0 || c.reading || c.connecting) return;
			// A send waiting for room is retried in the pass first (want_write).
			for (const auto& w : write_retry_)
			{
				if (w.first == i && w.second == c.gen) return;
			}
			const std::uint32_t gen = c.gen;
			Op* const op = io_->take(i, gen, OpKind::readable);
			WSABUF none{0, nullptr};
			DWORD got = 0;
			DWORD flags = 0;
			if (::WSARecv(static_cast<SOCKET>(c.fd), &none, 1, &got, &flags, &op->ov, nullptr) == 0)
			{
				// Bytes, or the end, are there already: no packet. Read them, then post again.
				io_->give(op);
				if (over_tls(o_.proto)) drive_tls(i);
				else readable(i);
				if (!conns_[i].active || conns_[i].gen != gen) return;
				continue;
			}
			if (::WSAGetLastError() == WSA_IO_PENDING)
			{
				++io_->outstanding;
				c.reading = true;
				return;
			}
			io_->give(op);
			fail(i, End::reset);
			return;
		}
	}

	void Worker::readable(std::uint32_t i)
	{
		Conn& c = conns_[i];
		const std::uint64_t xid = c.xid;
		for (;;)
		{
			if (c.in_len == c.in.size())
			{
				fail(i, End::protocol);
				return;
			}
			const int n = ::recv(static_cast<SOCKET>(c.fd), reinterpret_cast<char*>(c.in.data() + c.in_len), static_cast<int>(c.in.size() - c.in_len), 0);
			if (n > 0)
			{
				if (c.rec.first < 0) c.rec.first = now_ns();
				c.in_len += static_cast<std::uint32_t>(n);
				parse(i);
				if (!c.active || c.xid != xid) return;  // the exchange ended (and a new one may have started)
				continue;
			}
			if (n == 0)
			{
				on_eof(i);
				return;
			}
			if (::WSAGetLastError() == WSAEWOULDBLOCK) return;
			fail(i, End::reset);
			return;
		}
	}

	bool Worker::flush(std::uint32_t i)
	{
		Conn& c = conns_[i];
		if (over_tls(o_.proto)) return flush_tls(i);
		while (c.out_off < c.out.size())
		{
			const int n = ::send(static_cast<SOCKET>(c.fd), reinterpret_cast<const char*>(c.out.data() + c.out_off), static_cast<int>(c.out.size() - c.out_off), 0);
			if (n > 0)
			{
				c.out_off += static_cast<std::size_t>(n);
				continue;
			}
			if (n < 0 && ::WSAGetLastError() == WSAEWOULDBLOCK)
			{
				want_write(i);
				return true;
			}
			fail(i, End::reset);
			return false;
		}
		return true;
	}

	void Worker::want_write(std::uint32_t i)
	{
		const std::uint32_t gen = conns_[i].gen;
		for (const auto& w : write_retry_)
		{
			if (w.first == i && w.second == gen) return;
		}
		write_retry_.emplace_back(i, gen);
	}

	void Worker::pass(std::chrono::nanoseconds bound)
	{
		DWORD wait_ms = 0;
		if (bound.count() > 0)
		{
			wait_ms = whole_ms(bound);
			if (io_->timer != nullptr)
			{
				// The timer thread's packet ends the wait when the bound has passed; the whole
				// milliseconds after it are only a backstop.
				LARGE_INTEGER due;
				due.QuadPart = -std::max<LONGLONG>(1, static_cast<LONGLONG>(bound.count() / 100));  // relative, in 100 ns
				if (SetWaitableTimerEx(io_->timer, &due, 0, nullptr, nullptr, nullptr, 0)) wait_ms += 16;
			}
		}
		if (!write_retry_.empty()) wait_ms = std::min<DWORD>(wait_ms, 1);
		std::array<OVERLAPPED_ENTRY, kEntries> e{};
		ULONG n = 0;
		if (!GetQueuedCompletionStatusEx(io_->port, e.data(), static_cast<ULONG>(e.size()), &n, wait_ms, FALSE))
		{
			if (GetLastError() != WAIT_TIMEOUT) throw_last("GetQueuedCompletionStatusEx");
			n = 0;
		}
		for (ULONG k = 0; k < n; ++k)
		{
			if (e[k].lpOverlapped == nullptr) continue;  // the timer thread's packet
			--io_->outstanding;
			on_completion(CONTAINING_RECORD(e[k].lpOverlapped, Op, ov), e[k].dwNumberOfBytesTransferred,
			              static_cast<std::uintptr_t>(e[k].lpOverlapped->Internal));
		}
		const std::int64_t now = now_ns();
		while (!deadlines_.empty() && deadlines_.front().at <= now)
		{
			const Deadline d = deadlines_.front();
			deadlines_.pop_front();
			Conn& c = conns_[d.idx];
			// A connect that has not completed by the deadline failed (section 7: "any connect
			// failed"), as one refused at once; any other exchange timed out.
			if (c.active && c.xid == d.xid) fail(d.idx, c.connecting ? End::connect : End::timeout);
		}
		if (!retry_.empty())
		{
			std::vector<std::uint32_t> again;
			again.swap(retry_);
			for (const std::uint32_t i : again) next(i);
		}
		if (!write_retry_.empty())
		{
			std::vector<std::pair<std::uint32_t, std::uint32_t>> again;
			again.swap(write_retry_);
			for (const auto& [i, gen] : again)
			{
				if (!conns_[i].active || conns_[i].gen != gen) continue;
				if (over_tls(o_.proto)) drive_tls(i);
				else flush(i);
				if (conns_[i].active && conns_[i].gen == gen) arm_read(i);
			}
		}
	}

}  // namespace oneport::opgen::detail

#endif  // _WIN32
