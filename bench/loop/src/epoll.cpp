// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
//
// epoll backend. The stop eventfd is level-triggered and never read, so once stop() writes it
// every later wait returns at once. The wait is epoll_pwait2 with a timespec (proposal I13); the
// kernel of L has it (5.11 and later), so no millisecond fallback is kept. M1 adds the
// registration of sockets (add, modify) and returns each wait's events to the server.
#include "oneport/loop.hpp"

#if defined(__linux__)

#include "common.hpp"
#include "linux_fd.hpp"

#include <cerrno>
#include <cstdint>
#include <ctime>
#include <stdexcept>

#include <sys/epoll.h>
#include <unistd.h>

namespace oneport::loop
{

	namespace
	{

		void ctl(int epoll_fd, int op, int fd, std::uint32_t events, std::uint64_t tag, const char* what)
		{
			epoll_event ev{};
			ev.events = events;
			ev.data.u64 = tag;
			if (::epoll_ctl(epoll_fd, op, fd, &ev) != 0) detail::throw_errno(what);
		}

	}  // namespace

	EpollLoop::EpollLoop()
	{
		detail::Fd epoll_fd(::epoll_create1(EPOLL_CLOEXEC));
		if (epoll_fd.get() < 0) detail::throw_errno("epoll_create1");
		detail::Fd stop_fd = detail::make_eventfd("eventfd (stop)");
		ctl(epoll_fd.get(), EPOLL_CTL_ADD, stop_fd.get(), EPOLLIN, kStopTag, "epoll_ctl (stop)");
		epoll_fd_ = epoll_fd.release();
		stop_fd_ = stop_fd.release();
	}

	EpollLoop::~EpollLoop()
	{
		::close(epoll_fd_);
		::close(stop_fd_);
	}

	void EpollLoop::start()
	{
		if (started_.exchange(true)) throw std::logic_error("oneport loop: start() may be called once");
	}

	void EpollLoop::stop() noexcept
	{
		stop_.store(true, std::memory_order_release);
		detail::signal_eventfd(stop_fd_, "epoll: write to the stop eventfd failed");
	}

	void EpollLoop::add(int fd, std::uint32_t events, std::uint64_t tag)
	{
		ctl(epoll_fd_, EPOLL_CTL_ADD, fd, events, tag, "epoll_ctl (add)");
	}

	void EpollLoop::modify(int fd, std::uint32_t events, std::uint64_t tag)
	{
		ctl(epoll_fd_, EPOLL_CTL_MOD, fd, events, tag, "epoll_ctl (modify)");
	}

	/// One wait. The stop eventfd's event is dropped from what is returned: stop() sets its flag
	/// before it signals, so stopped() already says it.
	std::span<const epoll_event> EpollLoop::wait(Bound bound)
	{
		bound = detail::checked_bound(bound);
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: wait() before start()");
		// Value-initialized, and unpoisoned up to what the kernel reports, for MemorySanitizer.
		events_ = {};
		timespec ts{};
		if (bound)
		{
			ts.tv_sec = static_cast<time_t>(bound->count() / 1000000000);
			ts.tv_nsec = static_cast<long>(bound->count() % 1000000000);
		}
		int n = ::epoll_pwait2(epoll_fd_, events_.data(), static_cast<int>(events_.size()), bound ? &ts : nullptr, nullptr);
		if (n < 0 && errno != EINTR) detail::throw_errno(wait_method);
		if (n < 0) n = 0;
		if (n > 0) detail::kernel_wrote(events_.data(), static_cast<std::size_t>(n) * sizeof(epoll_event));
		passes_.fetch_add(1, std::memory_order_relaxed);
		// Drop the stop event, keeping the others in order.
		std::size_t kept = 0;
		for (int i = 0; i < n; ++i)
		{
			if (events_[static_cast<std::size_t>(i)].data.u64 == kStopTag) continue;
			events_[kept++] = events_[static_cast<std::size_t>(i)];
		}
		return {events_.data(), kept};
	}

}  // namespace oneport::loop

#endif  // __linux__
