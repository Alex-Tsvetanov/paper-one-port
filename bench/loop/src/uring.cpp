// Derived from paper-wake-defect loop/ at commit 0af1ac4, same author.
//
// io_uring backend, on raw system calls, without liburing (proposal I2). Only the worker touches
// the ring, so it is created SINGLE_ISSUER and DEFER_TASKRUN, disabled, and enabled by start()
// on the worker thread, which makes the worker its issuer. stop() writes an eventfd and never
// touches the ring; a single-shot poll watches that eventfd, and the eventfd is never read, so
// a poll armed after stop() completes at once. Once stopped, a wait polls rather than blocks.
//
// M2b adds the submissions the server makes (proposal I4, I5, I11, I17), the provided-buffer
// rings of replay mode, the non-waiting reap of hypotheses.md 1(b), and the counters of I29
// (io_uring_enter calls, submissions by opcode). Submissions queue in the shared ring and are
// published to the kernel by the next io_uring_enter, which wait() combines with its wait; a
// full queue is submitted early. With DEFER_TASKRUN the kernel posts completions only while
// this thread is inside io_uring_enter with GETEVENTS, so every completion is reaped by wait(),
// reap_now() or drain().
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
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace oneport::loop
{

	namespace
	{

		static_assert(std::endian::native == std::endian::little, "poll32_events is written for little-endian hosts");
		static_assert(UringLoop::kOpcodes >= IORING_OP_LAST, "the opcode counters must cover every opcode");

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
		p.flags = IORING_SETUP_SINGLE_ISSUER | IORING_SETUP_DEFER_TASKRUN | IORING_SETUP_R_DISABLED | IORING_SETUP_CQSIZE |
		          IORING_SETUP_SUBMIT_ALL;
		p.cq_entries = kCqEntries;
		detail::Fd ring_fd(sys_setup(kSqEntries, &p));
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
		ring_.sq_flags = at<unsigned>(map, p.sq_off.flags);
		ring_.sq_array = at<unsigned>(map, p.sq_off.array);
		ring_.sq_mask = *at<unsigned>(map, p.sq_off.ring_mask);
		ring_.sq_entries = p.sq_entries;
		ring_.cq_head = at<unsigned>(map, p.cq_off.head);
		ring_.cq_tail = at<unsigned>(map, p.cq_off.tail);
		ring_.cq_mask = *at<unsigned>(map, p.cq_off.ring_mask);
		ring_.cqes = at<void>(map, p.cq_off.cqes);
		sq_local_tail_ = load_relaxed(ring_.sq_tail);

		map_guard.release();
		sqes_guard.release();
		ring_.fd = ring_fd.release();
		stop_fd_ = stop_fd.release();
		done_.reserve(kCqEntries);
		reaped_.reserve(kCqEntries);
	}

	UringLoop::~UringLoop()
	{
		::munmap(ring_.sqes, ring_.sqes_size);
		::munmap(ring_.map, ring_.map_size);
		::close(ring_.fd);  // the kernel cancels what is still armed and unregisters the buffer rings
		for (const BufferRing& b : buffer_rings_) ::munmap(b.map, b.map_size);
		::close(stop_fd_);
	}

	void UringLoop::start()
	{
		if (started_.exchange(true)) throw std::logic_error("oneport loop: start() may be called once");
		// The enabling thread becomes the ring's single issuer.
		if (sys_register(ring_.fd, IORING_REGISTER_ENABLE_RINGS, nullptr, 0) < 0) detail::throw_errno("io_uring_register (enable)");
		arm_stop_poll();
		submit_now();
	}

	void UringLoop::stop() noexcept
	{
		stop_.store(true, std::memory_order_release);
		detail::signal_eventfd(stop_fd_, "io_uring: write to the stop eventfd failed");
	}

	void* UringLoop::next_sqe(std::uint8_t opcode)
	{
		if (sq_local_tail_ - load_acquire(ring_.sq_head) >= ring_.sq_entries) submit_now();  // full: submit early
		if (sq_local_tail_ - load_acquire(ring_.sq_head) >= ring_.sq_entries) throw std::runtime_error("io_uring: submission queue full");
		const unsigned index = sq_local_tail_ & ring_.sq_mask;
		auto* sqe = static_cast<io_uring_sqe*>(ring_.sqes) + index;
		std::memset(sqe, 0, sizeof(*sqe));
		sqe->opcode = opcode;
		ring_.sq_array[index] = index;
		++sq_local_tail_;
		++by_opcode_[opcode];
		return sqe;
	}

	unsigned UringLoop::publish() noexcept
	{
		store_release(ring_.sq_tail, sq_local_tail_);
		return sq_local_tail_ - load_acquire(ring_.sq_head);
	}

	int UringLoop::enter(unsigned min_complete, bool getevents, const void* ts)
	{
		const unsigned to_submit = publish();
		io_uring_getevents_arg arg{};
		arg.sigmask = 0;
		arg.sigmask_sz = _NSIG / 8;
		arg.ts = reinterpret_cast<std::uintptr_t>(ts);
		const unsigned flags = (getevents ? IORING_ENTER_GETEVENTS : 0u) | IORING_ENTER_EXT_ARG;
		++enter_calls_;
		return sys_enter(ring_.fd, to_submit, min_complete, flags, &arg, sizeof(arg));
	}

	void UringLoop::submit_now()
	{
		for (;;)
		{
			if (publish() == 0) return;
			const int r = enter(0, false, nullptr);
			if (r > 0) continue;  // SUBMIT_ALL: every entry is taken; loop to confirm the queue is empty
			if (r == 0) throw std::runtime_error("io_uring: the kernel took no submission");
			if (errno == EINTR) continue;  // a signal: nothing was taken, submit again
			if (errno == EBUSY || errno == EAGAIN)
			{
				// The completion queue's overflow list blocks submissions: flush it, reap later.
				if (enter(0, true, nullptr) < 0 && errno != EINTR && errno != ETIME) detail::throw_errno("io_uring_enter (flush)");
				continue;
			}
			detail::throw_errno("io_uring_enter (submit)");
		}
	}

	void UringLoop::arm_stop_poll()
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_POLL_ADD));
		sqe->fd = stop_fd_;
		sqe->poll32_events = POLLIN;
		sqe->user_data = kStopTag;
	}

	std::span<const Completion> UringLoop::wait(Bound bound)
	{
		bound = detail::checked_bound(bound);
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: wait() before start()");
		// The stop poll is single-shot: once a wait has reaped it, nothing would end a blocking
		// wait, so after stop() every wait polls (a zero bound) instead of blocking.
		if (stopped()) bound = std::chrono::nanoseconds(0);
		// Value-initialized, as the kernel reads it through a raw system call.
		__kernel_timespec ts{};
		if (bound)
		{
			ts.tv_sec = bound->count() / 1000000000;
			ts.tv_nsec = bound->count() % 1000000000;
		}
		const int r = enter(1, true, bound ? &ts : nullptr);
		if (r < 0 && errno != ETIME && errno != EINTR && errno != EBUSY && errno != EAGAIN) detail::throw_errno("io_uring_enter (wait)");
		passes_.fetch_add(1, std::memory_order_relaxed);
		done_.clear();
		reap(done_);
		return done_;
	}

	std::span<const Completion> UringLoop::reap_now()
	{
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: reap_now() before start()");
		const int r = enter(0, true, nullptr);
		if (r < 0 && errno != ETIME && errno != EINTR && errno != EBUSY && errno != EAGAIN) detail::throw_errno("io_uring_enter (reap)");
		reaped_.clear();
		reap(reaped_);
		return reaped_;
	}

	std::span<const Completion> UringLoop::drain(std::chrono::nanoseconds bound)
	{
		bound = *detail::checked_bound(bound);
		if (!started_.load(std::memory_order_relaxed)) throw std::logic_error("oneport loop: drain() before start()");
		__kernel_timespec ts{};
		ts.tv_sec = bound.count() / 1000000000;
		ts.tv_nsec = bound.count() % 1000000000;
		const int r = enter(1, true, &ts);
		if (r < 0 && errno != ETIME && errno != EINTR && errno != EBUSY && errno != EAGAIN) detail::throw_errno("io_uring_enter (drain)");
		done_.clear();
		reap(done_);
		return done_;
	}

	/// Takes every completion into `out`, except the stop poll's. With no-drop completions an
	/// overflowing queue parks entries in the kernel; they are flushed into the ring and taken too.
	void UringLoop::reap(std::vector<Completion>& out)
	{
		for (;;)
		{
			unsigned head = load_relaxed(ring_.cq_head);
			const unsigned tail = load_acquire(ring_.cq_tail);
			auto* cqes = static_cast<io_uring_cqe*>(ring_.cqes);
			for (; head != tail; ++head)
			{
				const io_uring_cqe& cqe = cqes[head & ring_.cq_mask];
				detail::kernel_wrote(&cqe, sizeof(cqe));
				if (cqe.user_data == kStopTag)
				{
					if (cqe.res < 0) throw std::system_error(-cqe.res, std::generic_category(), "io_uring poll on the stop eventfd");
					continue;
				}
				out.push_back(Completion{cqe.user_data, cqe.res, cqe.flags});
			}
			store_release(ring_.cq_head, head);
			if ((load_acquire(ring_.sq_flags) & IORING_SQ_CQ_OVERFLOW) == 0) return;
			if (enter(0, true, nullptr) < 0 && errno != EINTR && errno != ETIME && errno != EBUSY && errno != EAGAIN)
			{
				detail::throw_errno("io_uring_enter (overflow flush)");
			}
		}
	}

	// ---- Submissions ----

	void UringLoop::accept_multishot(int fd, std::uint64_t user_data)
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_ACCEPT));
		sqe->fd = fd;
		sqe->ioprio = IORING_ACCEPT_MULTISHOT;
		sqe->accept_flags = SOCK_NONBLOCK | SOCK_CLOEXEC;
		sqe->user_data = user_data;
	}

	// A receive is an IORING_OP_READ on the socket, with no offset (-1: a socket is a stream, so
	// the kernel reads at position 0, which sock_read_iter requires; io_uring/rw.c and net/socket.c
	// at v7.2.6). Not IORING_OP_RECV (M5): at v7.2.6 every RECV allocates its io_async_msghdr at
	// preparation (io_recvmsg_prep_setup, io_uring/net.c), from kmalloc-512 on L, and an armed
	// READ an io_async_rw (io_uring/rw.c, io_rw_alloc_async), so a pending connection's armed
	// receive holds less kernel memory; the receive is the same (sock_recvmsg with MSG_DONTWAIT),
	// into the same provided buffers, and its completion reports the same bytes, 0 at EOF.
	void UringLoop::recv(int fd, void* buf, std::uint32_t len, std::uint64_t user_data)
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_READ));
		sqe->fd = fd;
		sqe->addr = reinterpret_cast<std::uintptr_t>(buf);
		sqe->len = len;
		sqe->off = ~std::uint64_t{0};
		sqe->user_data = user_data;
	}

	void UringLoop::recv_select(int fd, std::uint16_t group, std::uint64_t user_data)
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_READ));
		sqe->fd = fd;
		sqe->flags = IOSQE_BUFFER_SELECT;
		sqe->buf_group = group;
		sqe->len = 0;  // the selected buffer's length
		sqe->off = ~std::uint64_t{0};
		sqe->user_data = user_data;
	}

	void UringLoop::poll(int fd, std::uint32_t events, std::uint64_t user_data)
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_POLL_ADD));
		sqe->fd = fd;
		sqe->poll32_events = events;
		sqe->user_data = user_data;
	}

	void UringLoop::connect(int fd, const void* addr, std::uint32_t addr_len, std::uint64_t user_data)
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_CONNECT));
		sqe->fd = fd;
		sqe->addr = reinterpret_cast<std::uintptr_t>(addr);
		sqe->off = addr_len;
		sqe->user_data = user_data;
	}

	void UringLoop::splice(int fd_in, int fd_out, std::uint32_t len, std::uint32_t flags, std::uint64_t user_data)
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_SPLICE));
		sqe->fd = fd_out;
		sqe->off = ~std::uint64_t{0};  // no offset: fd_out is a pipe or a socket
		sqe->splice_fd_in = fd_in;
		sqe->splice_off_in = ~std::uint64_t{0};
		sqe->len = len;
		sqe->splice_flags = flags;
		sqe->user_data = user_data;
	}

	void UringLoop::cancel(std::uint64_t target, std::uint64_t user_data)
	{
		auto* sqe = static_cast<io_uring_sqe*>(next_sqe(IORING_OP_ASYNC_CANCEL));
		sqe->fd = -1;
		sqe->addr = target;
		sqe->user_data = user_data;
	}

	// ---- Provided buffers ----

	void UringLoop::add_buffer_ring(std::uint16_t group, unsigned entries)
	{
		if (entries == 0 || (entries & (entries - 1)) != 0 || entries > 32768) throw std::invalid_argument("io_uring: a buffer ring needs a power of two of entries");
		for (const BufferRing& b : buffer_rings_)
		{
			if (b.group == group) throw std::logic_error("io_uring: buffer group registered twice");
		}
		const std::size_t size = entries * sizeof(io_uring_buf);
		// Anonymous, page-aligned memory the kernel reads; zeroed by mmap, so defined for MSan.
		void* map = ::mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
		if (map == MAP_FAILED) detail::throw_errno("mmap (io_uring buffer ring)");
		Mapping guard(map, size);
		io_uring_buf_reg reg{};
		reg.ring_addr = reinterpret_cast<std::uintptr_t>(map);
		reg.ring_entries = entries;
		reg.bgid = group;
		if (sys_register(ring_.fd, IORING_REGISTER_PBUF_RING, &reg, 1) < 0) detail::throw_errno("io_uring_register (provided-buffer ring)");
		guard.release();
		buffer_rings_.push_back(BufferRing{group, map, size, entries, 0});
	}

	UringLoop::BufferRing& UringLoop::buffer_ring(std::uint16_t group)
	{
		for (BufferRing& b : buffer_rings_)
		{
			if (b.group == group) return b;
		}
		throw std::logic_error("io_uring: no such buffer group");
	}

	void UringLoop::provide(std::uint16_t group, void* addr, std::uint32_t len, std::uint16_t bid)
	{
		BufferRing& b = buffer_ring(group);
		auto* ring = static_cast<io_uring_buf_ring*>(b.map);
		io_uring_buf& slot = ring->bufs[b.tail & (b.entries - 1)];
		slot.addr = reinterpret_cast<std::uintptr_t>(addr);
		slot.len = len;
		slot.bid = bid;
		++b.tail;
		__atomic_store_n(&ring->tail, b.tail, __ATOMIC_RELEASE);
	}

}  // namespace oneport::loop

#endif  // __linux__
