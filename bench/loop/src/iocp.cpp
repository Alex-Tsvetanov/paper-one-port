// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
//
// IOCP backend. One completion port; stop queues a packet with the stop key. The worker waits in
// GetQueuedCompletionStatusEx with the bound rounded up to whole milliseconds, as the call takes
// it, so the process's timer resolution sets the period of timed returns (proposal I13). M6a adds
// what the server needs: each wait dequeues up to kMaxEntries completions, a non-waiting reap
// (hypotheses.md 1(b), IOCP's posted-buffer form), a drain after stop, the association of
// sockets with the port, and the count of GetQueuedCompletionStatusEx calls (proposal I29).
#include "oneport/loop.hpp"

#if defined(_WIN32)

#include "common.hpp"

#include <array>
#include <cstdint>
#include <stdexcept>
#include <system_error>

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

namespace oneport::loop
{

	namespace
	{

		[[noreturn]] void throw_last_error(const char* what)
		{
			throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), what);
		}

		DWORD to_wait_ms(Bound bound)
		{
			if (!bound) return INFINITE;
			const std::int64_t ms = (bound->count() + 999999) / 1000000;
			return ms >= static_cast<std::int64_t>(INFINITE) ? INFINITE - 1 : static_cast<DWORD>(ms);
		}

		DWORD to_wait_ms(std::chrono::nanoseconds bound)
		{
			return to_wait_ms(Bound(bound));
		}

		void post_packet(void* port, ULONG_PTR key, const char* what) noexcept
		{
			if (!PostQueuedCompletionStatus(static_cast<HANDLE>(port), 0, key, nullptr))
			{
				detail::fatal(what, static_cast<long>(GetLastError()));
			}
		}

	}  // namespace

	IocpLoop::IocpLoop()
	{
		port_ = CreateIoCompletionPort(INVALID_HANDLE_VALUE, nullptr, 0, 1);
		if (port_ == nullptr) throw_last_error("CreateIoCompletionPort");
		done_.reserve(kMaxEntries);
		reaped_.reserve(kMaxEntries);
	}

	IocpLoop::~IocpLoop() { CloseHandle(static_cast<HANDLE>(port_)); }

	void IocpLoop::start()
	{
		if (started_.exchange(true)) throw std::logic_error("oneport loop: start() may be called once");
	}

	void IocpLoop::stop() noexcept
	{
		// The packet ends one wait; the flag, set first, makes every later wait return at once.
		stop_.store(true, std::memory_order_release);
		post_packet(port_, kStopKey, "iocp: posting the stop packet failed");
	}

	void IocpLoop::associate(std::uintptr_t handle, std::uintptr_t key)
	{
		if (key == kStopKey) throw std::invalid_argument("oneport loop: the stop key cannot be associated");
		if (CreateIoCompletionPort(reinterpret_cast<HANDLE>(handle), static_cast<HANDLE>(port_), key, 0) == nullptr)
		{
			throw_last_error("CreateIoCompletionPort (associate)");
		}
	}

	void IocpLoop::dequeue(unsigned long wait_ms, std::vector<IocpEntry>& out)
	{
		std::array<OVERLAPPED_ENTRY, kMaxEntries> raw{};
		ULONG removed = 0;
		out.clear();
		++gqcs_calls_;
		if (!GetQueuedCompletionStatusEx(static_cast<HANDLE>(port_), raw.data(), static_cast<ULONG>(raw.size()), &removed, wait_ms, FALSE))
		{
			const DWORD error = GetLastError();
			if (error == WAIT_TIMEOUT) return;
			throw std::system_error(static_cast<int>(error), std::system_category(), wait_method);
		}
		for (ULONG i = 0; i < removed; ++i)
		{
			const OVERLAPPED_ENTRY& e = raw[i];
			if (e.lpCompletionKey == kStopKey && e.lpOverlapped == nullptr) continue;  // the stop packet
			IocpEntry x;
			x.key = e.lpCompletionKey;
			x.overlapped = e.lpOverlapped;
			x.bytes = e.dwNumberOfBytesTransferred;
			x.status = e.lpOverlapped != nullptr ? static_cast<std::uintptr_t>(e.lpOverlapped->Internal) : 0;
			out.push_back(x);
		}
	}

	/// One wait. After stop() the wait does not block, because the stop packet may already have
	/// been taken by an earlier wait; the completions it finds are still returned.
	std::span<const IocpEntry> IocpLoop::wait(Bound bound)
	{
		bound = detail::checked_bound(bound);
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: wait() before start()");
		const DWORD wait_ms = stopped() ? 0 : to_wait_ms(bound);
		dequeue(wait_ms, done_);
		passes_.fetch_add(1, std::memory_order_relaxed);
		return {done_.data(), done_.size()};
	}

	std::span<const IocpEntry> IocpLoop::reap_now()
	{
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: reap_now() before start()");
		dequeue(0, reaped_);
		return {reaped_.data(), reaped_.size()};
	}

	std::span<const IocpEntry> IocpLoop::drain(std::chrono::nanoseconds bound)
	{
		if (bound.count() < 0) throw std::invalid_argument("oneport loop: a drain bound must be >= 0 ns");
		dequeue(to_wait_ms(bound), done_);
		return {done_.data(), done_.size()};
	}

}  // namespace oneport::loop

#endif  // _WIN32
