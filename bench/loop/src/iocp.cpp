// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
//
// IOCP backend. One completion port; stop queues a packet with the stop key. The worker waits in
// GetQueuedCompletionStatus with the bound rounded up to whole milliseconds, as the call takes
// it, so the process's timer resolution sets the period of timed returns (proposal I13).
#include "oneport/loop.hpp"

#if defined(_WIN32)

#include "common.hpp"

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

		constexpr ULONG_PTR kStopKey = 2;

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

	/// One wait. In M0 the stop packet is the only completion. After stop() the wait does not
	/// block, because the packet may already have been taken by an earlier wait.
	void IocpLoop::wait(Bound bound)
	{
		bound = detail::checked_bound(bound);
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: wait() before start()");
		const DWORD wait_ms = stopped() ? 0 : to_wait_ms(bound);
		DWORD bytes = 0;
		ULONG_PTR key = 0;
		OVERLAPPED* overlapped = nullptr;
		const BOOL ok = GetQueuedCompletionStatus(static_cast<HANDLE>(port_), &bytes, &key, &overlapped, wait_ms);
		passes_.fetch_add(1, std::memory_order_relaxed);
		if (ok) return;
		const DWORD error = GetLastError();
		if (overlapped == nullptr && error == WAIT_TIMEOUT) return;
		throw std::system_error(static_cast<int>(error), std::system_category(), wait_method);
	}

}  // namespace oneport::loop

#endif  // _WIN32
