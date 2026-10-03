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
// earliest deadline (proposal I13). M1 adds socket registration and event output on epoll; M2b
// adds io_uring's submissions (multishot accept, receive into a buffer or a provided buffer,
// poll, connect, splice, cancel), its provided-buffer rings, the non-waiting reap of
// hypotheses.md 1(b), and its counters. The server (bench/server) keeps the deadline queue and
// the sockets' state.
#pragma once

#include <array>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#if defined(__linux__)
#include <sys/epoll.h>
#endif

namespace oneport::loop
{

	/// The bound of one wait. std::nullopt blocks until an event or stop(); a zero bound polls.
	using Bound = std::optional<std::chrono::nanoseconds>;

#if defined(__linux__)

	class EpollLoop
	{
	public:
		/// The most events one wait returns. A design choice of M1: the 64 connection slots per
		/// server core of WL1 (hypotheses.md, section 3), so one wait can report every slot.
		static constexpr std::size_t kMaxEvents = 64;
		/// The tag of the stop eventfd; registrations must use other tags.
		static constexpr std::uint64_t kStopTag = ~std::uint64_t{0};

		/// Throws std::system_error when a setup call fails.
		EpollLoop();
		~EpollLoop();
		EpollLoop(const EpollLoop&) = delete;
		EpollLoop& operator=(const EpollLoop&) = delete;

		/// Worker thread, once, before the first wait. Throws std::logic_error on a second call.
		void start();
		/// One wait on the worker thread. Returns at once after stop(). Throws
		/// std::invalid_argument for a negative bound, std::logic_error before start() and
		/// std::system_error when the wait fails. Returns the events of the registered
		/// descriptors (never the stop eventfd's), valid until the next wait.
		std::span<const epoll_event> wait(Bound bound);
		/// Registers `fd` for `events` with `tag` as its event data. Throws std::system_error.
		void add(int fd, std::uint32_t events, std::uint64_t tag);
		/// Changes a registration. Throws std::system_error.
		void modify(int fd, std::uint32_t events, std::uint64_t tag);
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
		std::array<epoll_event, kMaxEvents> events_{};
	};

	/// One io_uring completion, copied out of the shared ring (its bytes unpoisoned for
	/// MemorySanitizer as they are read, proposal Z6).
	struct Completion
	{
		std::uint64_t user_data = 0;
		std::int32_t res = 0;
		std::uint32_t flags = 0;
	};

	class UringLoop
	{
	public:
		/// The ring's sizes. Design choices of M2b: 256 submission entries, which the worker
		/// submits before it waits (a full queue is submitted early, never refused); 4096
		/// completion entries, so a pass of WL1's 64 connections, or of B3's batches, fits without
		/// the kernel's overflow list (which is flushed if it is ever used).
		static constexpr unsigned kSqEntries = 256;
		static constexpr unsigned kCqEntries = 4096;
		/// The user_data of the stop poll; submissions must use other values.
		static constexpr std::uint64_t kStopTag = ~std::uint64_t{0};
		/// The submissions counted by opcode (I29), indexed by IORING_OP_*.
		static constexpr std::size_t kOpcodes = 80;

		/// As EpollLoop. Also throws std::system_error when the kernel refuses the ring or lacks
		/// a required feature (extended wait argument, single mmap, no-drop completions).
		UringLoop();
		~UringLoop();
		UringLoop(const UringLoop&) = delete;
		UringLoop& operator=(const UringLoop&) = delete;

		/// Worker thread, once, before the first wait: enables the ring, which makes the caller
		/// its single issuer, and arms the stop poll.
		void start();
		/// One pass's wait: submits every queued submission, waits for a completion or the bound,
		/// and reaps every completion. As EpollLoop::wait otherwise. The completions (never the
		/// stop poll's) are valid until the next wait() or drain().
		std::span<const Completion> wait(Bound bound);
		/// The non-waiting reap of hypotheses.md 1(b): submits what is queued, runs the ring's
		/// deferred task work without waiting, and reaps what has completed. Not a pass. Its
		/// completions are valid until the next reap_now().
		std::span<const Completion> reap_now();
		/// After stop(): waits at most `bound` for completions (cancelled operations finishing),
		/// as wait() would before stop(). Not a pass. Shares wait()'s result buffer.
		std::span<const Completion> drain(std::chrono::nanoseconds bound);
		void stop() noexcept;
		bool stopped() const noexcept { return stop_.load(std::memory_order_acquire); }
		std::uint64_t passes() const noexcept { return passes_.load(std::memory_order_relaxed); }

		// ---- Submissions: worker thread only. Each queues one entry; wait() submits them. ----

		/// A multishot accept (I4): one completion per connection, res the new descriptor
		/// (non-blocking, close-on-exec), flagged IORING_CQE_F_MORE while it stays armed.
		void accept_multishot(int fd, std::uint64_t user_data);
		/// A receive of at most `len` bytes into `buf`.
		void recv(int fd, void* buf, std::uint32_t len, std::uint64_t user_data);
		/// A receive into a buffer the kernel takes from provided-buffer group `group` when data
		/// arrives (IOSQE_BUFFER_SELECT), so the pending receive holds no buffer (I11, I15). The
		/// completion names the buffer: IORING_CQE_F_BUFFER and its id above
		/// IORING_CQE_BUFFER_SHIFT.
		void recv_select(int fd, std::uint16_t group, std::uint64_t user_data);
		/// A single-shot IORING_OP_POLL_ADD for `events` (poll(2) bits); res is the ready mask.
		void poll(int fd, std::uint32_t events, std::uint64_t user_data);
		/// IORING_OP_CONNECT. `addr` must stay valid until the next wait() submits it.
		void connect(int fd, const void* addr, std::uint32_t addr_len, std::uint64_t user_data);
		/// IORING_OP_SPLICE of at most `len` bytes from `fd_in` to `fd_out`, neither with an
		/// offset, with splice(2) `flags`.
		void splice(int fd_in, int fd_out, std::uint32_t len, std::uint32_t flags, std::uint64_t user_data);
		/// IORING_OP_ASYNC_CANCEL of the operation submitted with `target`.
		void cancel(std::uint64_t target, std::uint64_t user_data);

		// ---- Provided buffers (IORING_REGISTER_PBUF_RING) ----

		/// Registers a ring of `entries` (a power of two) provided buffers as group `group`.
		/// Throws std::system_error when the kernel refuses it.
		void add_buffer_ring(std::uint16_t group, unsigned entries);
		/// Adds one buffer to group `group` and publishes it to the kernel.
		void provide(std::uint16_t group, void* addr, std::uint32_t len, std::uint16_t bid);

		// ---- Counters (proposal I29) ----

		std::uint64_t enter_calls() const noexcept { return enter_calls_; }
		const std::array<std::uint64_t, kOpcodes>& submissions() const noexcept { return by_opcode_; }

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
			unsigned* sq_flags = nullptr;
			unsigned* sq_array = nullptr;
			unsigned sq_mask = 0;
			unsigned sq_entries = 0;
			unsigned* cq_head = nullptr;
			unsigned* cq_tail = nullptr;
			unsigned cq_mask = 0;
			void* cqes = nullptr;
		};

		struct BufferRing
		{
			std::uint16_t group = 0;
			void* map = nullptr;
			std::size_t map_size = 0;
			unsigned entries = 0;
			std::uint16_t tail = 0;
		};

		void arm_stop_poll();
		/// Publishes the queued entries; returns how many the kernel has not consumed yet.
		unsigned publish() noexcept;
		/// io_uring_enter with what is queued; `min_complete` and `ts` as the wait needs.
		int enter(unsigned min_complete, bool getevents, const void* ts);
		void submit_now();
		void reap(std::vector<Completion>& out);
		void* next_sqe(std::uint8_t opcode);
		BufferRing& buffer_ring(std::uint16_t group);

		std::atomic<bool> stop_{false};
		std::atomic<bool> started_{false};
		std::atomic<std::uint64_t> passes_{0};
		Ring ring_;
		unsigned sq_local_tail_ = 0;  // entries written; published to the kernel by publish()
		int stop_fd_ = -1;
		std::vector<Completion> done_;     // wait() and drain()
		std::vector<Completion> reaped_;   // reap_now()
		std::vector<BufferRing> buffer_rings_;
		std::uint64_t enter_calls_ = 0;
		std::array<std::uint64_t, kOpcodes> by_opcode_{};
	};

#elif defined(_WIN32)

	/// One IOCP completion, copied out of the port's OVERLAPPED_ENTRY (M6a).
	struct IocpEntry
	{
		std::uintptr_t key = 0;      // the completion key the handle was associated with
		void* overlapped = nullptr;  // the operation's OVERLAPPED
		std::uint32_t bytes = 0;     // the bytes the operation transferred
		std::uintptr_t status = 0;   // the operation's status (OVERLAPPED::Internal, an NTSTATUS); 0 on success
	};

	class IocpLoop
	{
	public:
		/// The most completions one wait returns. A design choice of M6a, as EpollLoop's
		/// kMaxEvents: the 64 connection slots per server core of WL1 (hypotheses.md, section 3).
		static constexpr std::size_t kMaxEntries = 64;
		/// The key of the stop packet; associations must use other keys.
		static constexpr std::uintptr_t kStopKey = 2;

		/// Throws std::system_error when the port cannot be created.
		IocpLoop();
		~IocpLoop();
		IocpLoop(const IocpLoop&) = delete;
		IocpLoop& operator=(const IocpLoop&) = delete;

		void start();
		/// As EpollLoop::wait: one GetQueuedCompletionStatusEx call that dequeues at most
		/// kMaxEntries completions. The bound is rounded up to whole milliseconds, as the wait call
		/// takes it; such a wait can still end up to one timer tick early (proposal I13). Returns
		/// the completions (never the stop packet), valid until the next wait() or drain().
		std::span<const IocpEntry> wait(Bound bound);
		/// The non-waiting reap of hypotheses.md 1(b): dequeues what has completed, without
		/// waiting. Not a pass. Its completions are valid until the next reap_now().
		std::span<const IocpEntry> reap_now();
		/// After stop(): waits at most `bound` for completions (cancelled operations finishing),
		/// as wait() would before stop(). Not a pass. Shares wait()'s result buffer.
		std::span<const IocpEntry> drain(std::chrono::nanoseconds bound);
		/// Associates a handle (a SOCKET) with the port, its completions carrying `key`. Throws
		/// std::system_error.
		void associate(std::uintptr_t handle, std::uintptr_t key);
		void stop() noexcept;
		bool stopped() const noexcept { return stop_.load(std::memory_order_acquire); }
		std::uint64_t passes() const noexcept { return passes_.load(std::memory_order_relaxed); }
		/// GetQueuedCompletionStatusEx calls: every wait, reap and drain (proposal I29).
		std::uint64_t gqcs_calls() const noexcept { return gqcs_calls_; }

		static constexpr const char* name = "IOCP";
		static constexpr const char* wait_method = "GetQueuedCompletionStatusEx";

	private:
		/// One dequeue of at most kMaxEntries completions into `out`, waiting `wait_ms`.
		void dequeue(unsigned long wait_ms, std::vector<IocpEntry>& out);

		std::atomic<bool> stop_{false};
		std::atomic<bool> started_{false};
		std::atomic<std::uint64_t> passes_{0};
		void* port_ = nullptr;  // HANDLE
		std::uint64_t gqcs_calls_ = 0;
		std::vector<IocpEntry> done_;    // wait() and drain()
		std::vector<IocpEntry> reaped_;  // reap_now()
	};

#endif

}  // namespace oneport::loop
