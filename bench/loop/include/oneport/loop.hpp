// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
//
// The event loop of one oneport worker: one per worker thread, one backend per process
// (design/proposal.md, I1). M0 keeps what proposal I2 takes from P1's loop and nothing else:
//
//   epoll     an epoll set; stop is an eventfd in it, level-triggered and never read
//   io_uring  a ring on raw system calls, created SINGLE_ISSUER, DEFER_TASKRUN and R_DISABLED,
//             enabled by start() on the worker; stop is an eventfd watched by a single-shot poll
//   IOCP      a completion port; stop is a completion packet with the stop key
//
// P1's wake path, its task queue and its seeded defect are P1's experiment and are not here.
// The wait bound is an argument of each wait, because the server bounds each pass by its
// earliest deadline (proposal I13). Sockets, receives and the deadline queue come with M1.
#pragma once

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace oneport::loop
{

	/// The bound of one wait. std::nullopt blocks until an event or stop(); a zero bound polls.
	using Bound = std::optional<std::chrono::nanoseconds>;

#if defined(__linux__)

	class EpollLoop
	{
	public:
		/// Throws std::system_error when a setup call fails.
		EpollLoop();
		~EpollLoop();
		EpollLoop(const EpollLoop&) = delete;
		EpollLoop& operator=(const EpollLoop&) = delete;

		/// Worker thread, once, before the first wait. Throws std::logic_error on a second call.
		void start();
		/// One wait on the worker thread. Returns at once after stop(). Throws
		/// std::invalid_argument for a negative bound, std::logic_error before start() and
		/// std::system_error when the wait fails.
		void wait(Bound bound);
		/// Any thread, any time, more than once. Ends a blocked wait and every later one.
		void stop() noexcept;
		bool stopped() const noexcept { return stop_.load(std::memory_order_acquire); }
		/// Number of wait returns so far.
		std::uint64_t passes() const noexcept { return passes_.load(std::memory_order_relaxed); }

		static constexpr const char* name = "epoll";
		static constexpr const char* wait_method = "epoll_pwait2";

	private:
		std::atomic<bool> stop_{false};
		std::atomic<bool> started_{false};
		std::atomic<std::uint64_t> passes_{0};
		int epoll_fd_ = -1;
		int stop_fd_ = -1;
	};

	class UringLoop
	{
	public:
		/// As EpollLoop. Also throws std::system_error when the kernel refuses the ring or lacks
		/// a required feature (extended wait argument, single mmap, no-drop completions).
		UringLoop();
		~UringLoop();
		UringLoop(const UringLoop&) = delete;
		UringLoop& operator=(const UringLoop&) = delete;

		/// Worker thread, once, before the first wait: enables the ring, which makes the caller
		/// its single issuer, and arms the stop poll.
		void start();
		/// One wait, then the completions are reaped. As EpollLoop::wait.
		void wait(Bound bound);
		void stop() noexcept;
		bool stopped() const noexcept { return stop_.load(std::memory_order_acquire); }
		std::uint64_t passes() const noexcept { return passes_.load(std::memory_order_relaxed); }

		static constexpr const char* name = "io_uring";
		static constexpr const char* wait_method = "io_uring_enter(getevents, ext_arg; single_issuer, defer_taskrun)";

	private:
		// Views into the rings the kernel shares with this process.
		struct Ring
		{
			int fd = -1;
			void* map = nullptr;
			std::size_t map_size = 0;
			void* sqes = nullptr;
			std::size_t sqes_size = 0;
			unsigned* sq_head = nullptr;
			unsigned* sq_tail = nullptr;
			unsigned* sq_array = nullptr;
			unsigned sq_mask = 0;
			unsigned sq_entries = 0;
			unsigned* cq_head = nullptr;
			unsigned* cq_tail = nullptr;
			unsigned cq_mask = 0;
			void* cqes = nullptr;
		};

		void arm_stop_poll();
		void submit();
		void reap();
		void* next_sqe();

		std::atomic<bool> stop_{false};
		std::atomic<bool> started_{false};
		std::atomic<std::uint64_t> passes_{0};
		Ring ring_;
		unsigned sq_pending_ = 0;  // SQEs written but not yet submitted; worker only
		int stop_fd_ = -1;
	};

#elif defined(_WIN32)

	class IocpLoop
	{
	public:
		/// Throws std::system_error when the port cannot be created.
		IocpLoop();
		~IocpLoop();
		IocpLoop(const IocpLoop&) = delete;
		IocpLoop& operator=(const IocpLoop&) = delete;

		void start();
		/// As EpollLoop::wait. The bound is rounded up to whole milliseconds, as the wait call
		/// takes it; such a wait can still end up to one timer tick early (proposal I13).
		void wait(Bound bound);
		void stop() noexcept;
		bool stopped() const noexcept { return stop_.load(std::memory_order_acquire); }
		std::uint64_t passes() const noexcept { return passes_.load(std::memory_order_relaxed); }

		static constexpr const char* name = "IOCP";
		static constexpr const char* wait_method = "GetQueuedCompletionStatus";

	private:
		std::atomic<bool> stop_{false};
		std::atomic<bool> started_{false};
		std::atomic<std::uint64_t> passes_{0};
		void* port_ = nullptr;  // HANDLE
	};

#endif

}  // namespace oneport::loop
