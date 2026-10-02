// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
//
// io_uring backend, on raw system calls, without liburing (proposal I2). Only the worker touches
// the ring, so it is created SINGLE_ISSUER and DEFER_TASKRUN, disabled, and enabled by start()
// on the worker thread, which makes the worker its issuer. stop() writes an eventfd and never
// touches the ring; a single-shot poll watches that eventfd, and the eventfd is never read, so
// a poll armed after stop() completes at once. Once stopped, a wait polls rather than blocks.
#include "oneport/loop.hpp"

#if defined(__linux__)

#include "common.hpp"
#include "linux_fd.hpp"

#include <algorithm>
#include <atomic>
#include <bit>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <system_error>

#include <linux/io_uring.h>
#include <poll.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace oneport::loop
{

	namespace
	{

		static_assert(std::endian::native == std::endian::little, "poll32_events is written for little-endian hosts");

		constexpr unsigned kEntries = 8;  // SQEs; M0 submits only the stop poll, M1 sizes the ring
		constexpr std::uint64_t kStopTag = 2;
		constexpr unsigned kRequiredFeatures = IORING_FEAT_EXT_ARG | IORING_FEAT_SINGLE_MMAP | IORING_FEAT_NODROP;

		int sys_setup(unsigned entries, io_uring_params* p) { return static_cast<int>(::syscall(__NR_io_uring_setup, entries, p)); }

		int sys_enter(int fd, unsigned to_submit, unsigned min_complete, unsigned flags, const void* arg, std::size_t argsz)
		{
			return static_cast<int>(::syscall(__NR_io_uring_enter, fd, to_submit, min_complete, flags, arg, argsz));
		}

		int sys_register(int fd, unsigned op, const void* arg, unsigned nr)
		{
			return static_cast<int>(::syscall(__NR_io_uring_register, fd, op, arg, nr));
		}

		/// Unmaps a region on scope exit unless released.
		class Mapping
		{
		public:
			Mapping(void* p, std::size_t n) : p_(p), n_(n) {}
			~Mapping()
			{
				if (p_ != nullptr) ::munmap(p_, n_);
			}
			Mapping(const Mapping&) = delete;
			Mapping& operator=(const Mapping&) = delete;
			void release() noexcept { p_ = nullptr; }

		private:
			void* p_;
			std::size_t n_;
		};

		void* map_ring(int fd, std::size_t size, off_t offset, const char* what)
		{
			void* p = ::mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_POPULATE, fd, offset);
			if (p == MAP_FAILED) detail::throw_errno(what);
			return p;
		}

		template <class T>
		T* at(void* base, unsigned offset)
		{
			return reinterpret_cast<T*>(static_cast<char*>(base) + offset);
		}

		// Ring indices shared with the kernel. The compiler builtins, rather than std::atomic_ref,
		// because the instrumented libc++ used for MemorySanitizer may predate atomic_ref.
		unsigned load_acquire(const unsigned* p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
		unsigned load_relaxed(const unsigned* p) { return __atomic_load_n(p, __ATOMIC_RELAXED); }
		void store_release(unsigned* p, unsigned v) { __atomic_store_n(p, v, __ATOMIC_RELEASE); }

	}  // namespace

	UringLoop::UringLoop()
	{
		detail::Fd stop_fd = detail::make_eventfd("eventfd (stop)");

		// The kernel fills this through a raw system call, which MemorySanitizer cannot see: it is
		// value-initialized first, so every field it reads back is defined.
		io_uring_params p{};
		p.flags = IORING_SETUP_SINGLE_ISSUER | IORING_SETUP_DEFER_TASKRUN | IORING_SETUP_R_DISABLED;
		detail::Fd ring_fd(sys_setup(kEntries, &p));
		if (ring_fd.get() < 0) detail::throw_errno("io_uring_setup (single issuer, deferred task run)");
		detail::kernel_wrote(&p, sizeof(p));
		if ((p.features & kRequiredFeatures) != kRequiredFeatures)
		{
			throw std::system_error(ENOTSUP, std::generic_category(),
			                        "io_uring: the kernel lacks the extended wait argument, single mmap or no-drop completions");
		}

		const std::size_t sq_size = p.sq_off.array + p.sq_entries * sizeof(unsigned);
		const std::size_t cq_size = p.cq_off.cqes + p.cq_entries * sizeof(io_uring_cqe);
		const std::size_t map_size = std::max(sq_size, cq_size);
		void* map = map_ring(ring_fd.get(), map_size, IORING_OFF_SQ_RING, "mmap (io_uring rings)");
		Mapping map_guard(map, map_size);
		const std::size_t sqes_size = p.sq_entries * sizeof(io_uring_sqe);
		void* sqes = map_ring(ring_fd.get(), sqes_size, IORING_OFF_SQES, "mmap (io_uring submission entries)");
		Mapping sqes_guard(sqes, sqes_size);

		ring_.map = map;
		ring_.map_size = map_size;
		ring_.sqes = sqes;
		ring_.sqes_size = sqes_size;
		ring_.sq_head = at<unsigned>(map, p.sq_off.head);
		ring_.sq_tail = at<unsigned>(map, p.sq_off.tail);
		ring_.sq_array = at<unsigned>(map, p.sq_off.array);
		ring_.sq_mask = *at<unsigned>(map, p.sq_off.ring_mask);
		ring_.sq_entries = p.sq_entries;
		ring_.cq_head = at<unsigned>(map, p.cq_off.head);
		ring_.cq_tail = at<unsigned>(map, p.cq_off.tail);
		ring_.cq_mask = *at<unsigned>(map, p.cq_off.ring_mask);
		ring_.cqes = at<void>(map, p.cq_off.cqes);

		map_guard.release();
		sqes_guard.release();
		ring_.fd = ring_fd.release();
		stop_fd_ = stop_fd.release();
	}

	UringLoop::~UringLoop()
	{
		::munmap(ring_.sqes, ring_.sqes_size);
		::munmap(ring_.map, ring_.map_size);
		::close(ring_.fd);  // the kernel cancels the poll
		::close(stop_fd_);
	}

	void UringLoop::start()
	{
		if (started_.exchange(true)) throw std::logic_error("oneport loop: start() may be called once");
		// The enabling thread becomes the ring's single issuer.
		if (sys_register(ring_.fd, IORING_REGISTER_ENABLE_RINGS, nullptr, 0) < 0) detail::throw_errno("io_uring_register (enable)");
		arm_stop_poll();
		submit();
	}

	void UringLoop::stop() noexcept
	{
		stop_.store(true, std::memory_order_release);
		detail::signal_eventfd(stop_fd_, "io_uring: write to the stop eventfd failed");
	}

	void* UringLoop::next_sqe()
	{
		const unsigned head = load_acquire(ring_.sq_head);
		const unsigned tail = load_relaxed(ring_.sq_tail) + sq_pending_;
		if (tail - head >= ring_.sq_entries) throw std::runtime_error("io_uring: submission queue full");
		const unsigned index = tail & ring_.sq_mask;
		auto* sqe = static_cast<io_uring_sqe*>(ring_.sqes) + index;
		std::memset(sqe, 0, sizeof(*sqe));
		ring_.sq_array[index] = index;
		++sq_pending_;
		return sqe;
	}

	void UringLoop::arm_stop_poll()
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe());
		sqe->opcode = IORING_OP_POLL_ADD;
		sqe->fd = stop_fd_;
		sqe->poll32_events = POLLIN;
		sqe->user_data = kStopTag;
	}

	void UringLoop::submit()
	{
		if (sq_pending_ == 0) return;
		const unsigned n = sq_pending_;
		store_release(ring_.sq_tail, load_relaxed(ring_.sq_tail) + n);
		sq_pending_ = 0;
		int submitted = -1;
		do
		{
			submitted = sys_enter(ring_.fd, n, 0, 0, nullptr, 0);
		} while (submitted < 0 && errno == EINTR);  // a signal: nothing was taken, submit again
		if (submitted < 0) detail::throw_errno("io_uring_enter (submit)");
		if (static_cast<unsigned>(submitted) != n) throw std::runtime_error("io_uring: the kernel took fewer submissions than given");
	}

	void UringLoop::wait(Bound bound)
	{
		bound = detail::checked_bound(bound);
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: wait() before start()");
		// The stop poll is single-shot: once a wait has reaped it, nothing would end a blocking
		// wait, so after stop() every wait polls (a zero bound) instead of blocking.
		if (stopped()) bound = std::chrono::nanoseconds(0);
		// Value-initialized, as the kernel reads them through a raw system call.
		__kernel_timespec ts{};
		if (bound)
		{
			ts.tv_sec = bound->count() / 1000000000;
			ts.tv_nsec = bound->count() % 1000000000;
		}
		io_uring_getevents_arg arg{};
		arg.sigmask = 0;
		arg.sigmask_sz = _NSIG / 8;
		arg.ts = bound ? reinterpret_cast<std::uintptr_t>(&ts) : 0;
		const int r = sys_enter(ring_.fd, 0, 1, IORING_ENTER_GETEVENTS | IORING_ENTER_EXT_ARG, &arg, sizeof(arg));
		if (r < 0 && errno != ETIME && errno != EINTR) detail::throw_errno("io_uring_enter (wait)");
		passes_.fetch_add(1, std::memory_order_relaxed);
		reap();
	}

	/// Takes every completion. In M0 the stop poll is the only submission; a completion with any
	/// other tag is a broken invariant of this build. M1 dispatches the socket completions.
	void UringLoop::reap()
	{
		unsigned head = load_relaxed(ring_.cq_head);
		const unsigned tail = load_acquire(ring_.cq_tail);
		auto* cqes = static_cast<io_uring_cqe*>(ring_.cqes);
		for (; head != tail; ++head)
		{
			const io_uring_cqe& cqe = cqes[head & ring_.cq_mask];
			detail::kernel_wrote(&cqe, sizeof(cqe));
			if (cqe.user_data != kStopTag) throw std::logic_error("io_uring: a completion with an unknown tag");
			if (cqe.res < 0) throw std::system_error(-cqe.res, std::generic_category(), "io_uring poll on the stop eventfd");
		}
		store_release(ring_.cq_head, head);
	}

}  // namespace oneport::loop

#endif  // __linux__
