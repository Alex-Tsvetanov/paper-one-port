// The internals of oneport's server on epoll: connection state, deadline lists, buffers and
// the worker (design/proposal.md I3 to I5, I9 to I16, I26, I27, I29). Linux only. The worker's
// pass, accept, PROXY, detection and timers are in worker.cpp; its handlers, output and
// connection lifecycle in handlers.cpp.
#pragma once

#if defined(__linux__)

#include "oneport/loop.hpp"
#include "server.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include <sys/epoll.h>
#include <sys/types.h>

#if defined(__has_feature)
#if __has_feature(address_sanitizer)
#define ONEPORT_ASAN_POISON 1
#endif
#if __has_feature(memory_sanitizer)
#define ONEPORT_MSAN_POISON 1
#endif
#endif
#if defined(__SANITIZE_ADDRESS__) && !defined(ONEPORT_ASAN_POISON)
#define ONEPORT_ASAN_POISON 1
#endif
#if defined(ONEPORT_ASAN_POISON)
#include <sanitizer/asan_interface.h>
#endif
#if defined(ONEPORT_MSAN_POISON)
#include <sanitizer/msan_interface.h>
#endif

namespace oneport::server::detail
{

	using std::chrono::nanoseconds;

	constexpr std::uint64_t kListenerTag = std::uint64_t{1} << 62;
	constexpr std::uint32_t kConnEvents = EPOLLIN | EPOLLRDHUP | EPOLLET;

	[[noreturn]] inline void throw_errno(const char* what) { throw std::system_error(errno, std::generic_category(), what); }

	// ---- Buffers: the handlers' receive buffers, from a per-worker free list ----

	struct Buffer
	{
		std::array<std::byte, kRecvBuf> data;
	};

	/// Buffers are taken on the first readiness, never at accept (I27). A free buffer is
	/// poisoned for ASan and MSan, so a read of a returned buffer, or of bytes it held before,
	/// is reported.
	class BufferPool
	{
	public:
		Buffer* get()
		{
			Buffer* b = nullptr;
			if (free_.empty())
			{
				all_.push_back(std::make_unique<Buffer>());
				b = all_.back().get();
			}
			else
			{
				b = free_.back();
				free_.pop_back();
#if defined(ONEPORT_ASAN_POISON)
				ASAN_UNPOISON_MEMORY_REGION(b, sizeof(Buffer));
#endif
			}
#if defined(ONEPORT_MSAN_POISON)
			__msan_poison(b, sizeof(Buffer));
#endif
			++outstanding_;
			return b;
		}
		void put(Buffer* b) noexcept
		{
#if defined(ONEPORT_ASAN_POISON)
			ASAN_POISON_MEMORY_REGION(b, sizeof(Buffer));
#endif
			free_.push_back(b);
			--outstanding_;
		}
		std::size_t allocated() const noexcept { return all_.size(); }
		std::size_t outstanding() const noexcept { return outstanding_; }
		~BufferPool()
		{
#if defined(ONEPORT_ASAN_POISON)
			for (Buffer* b : free_) ASAN_UNPOISON_MEMORY_REGION(b, sizeof(Buffer));
#endif
		}

	private:
		std::vector<std::unique_ptr<Buffer>> all_;
		std::vector<Buffer*> free_;
		std::size_t outstanding_ = 0;
	};

	// ---- Connection state (I3, I15) ----

	enum class Stage : std::uint8_t
	{
		proxy,   // reading the PROXY header
		detect,  // one-port: deciding the class
		http1,   // the HTTP/1.1 handler
		stub,    // an M1 stub handler (h2c, TLS, MQTT, SSH, SMTP): replaced in M2
	};

	/// How a handler is entered, which says whether it must read at once.
	enum class Entry : std::uint8_t
	{
		accept,      // dedicated: nothing received yet, wait for readiness
		replay,      // classified in replay mode: the bytes are in the buffer
		peek,        // classified in peek mode: the bytes are still in the socket
		fallback,    // T_fb: nothing received
	};

	struct ListenerState;
	struct Conn;

	struct Link
	{
		Conn* prev = nullptr;
		Conn* next = nullptr;
		TimePoint deadline{};
		bool armed = false;
	};

	/// The HTTP/1.1 handler's state.
	struct HttpState
	{
		bool closing;  // the last response is the last one
	};

	/// An M1 stub handler's state: the bytes it received, counted and hashed (FNV-1a, 64 bits),
	/// so a test can check from the client side that the handler saw every byte from the first.
	struct StubState
	{
		std::uint64_t count;
		std::uint64_t hash;
		bool trailer_pending;  // the client's EOF came while the marker was still being sent
		std::uint8_t trailer_len;
		std::array<char, 96> trailer;
	};

	struct Conn
	{
		int fd = -1;
		std::uint32_t gen = 0;
		Stage stage = Stage::detect;
		Proto proto = Proto::http1;
		ListenerState* listener = nullptr;
		std::uint64_t id = 0;
		std::uint16_t peer_port = 0;

		Buffer* buf = nullptr;
		std::uint32_t beg = 0;  // the handler's bytes are buf[beg, len)
		std::uint32_t len = 0;
		bool last_read_full = false;  // the last read stopped at a full buffer
		bool eof_seen = false;        // a receive returned 0: the peer shut down writing

		// Detection.
		std::uint32_t app_seen = 0;  // application bytes observed
		std::uint32_t lowat = 1;
		std::uint32_t wakeups = 0;
		std::uint32_t lowat_sets = 0;
		std::uint32_t lowat_resets = 0;
		std::uint32_t max_user_bytes = 0;
		bool buffer_while_silent = false;
		bool has_proxy = false;
		detect::ProxySource proxy{};
		std::uint64_t accept_pass = 0;
		std::uint64_t last_read_pass = 0;
		std::uint64_t observe_pass = 0;
		TimePoint accept_time{};
		TimePoint timers_start{};
		std::array<Link, 3> timers{};  // indexed by TimerKind

		// Output: a pending tail, from a static response or the stub's trailer.
		const std::byte* out = nullptr;
		std::uint32_t out_len = 0;
		bool close_after_out = false;
		bool want_out = false;  // EPOLLOUT registered

		std::uint64_t bytes_received = 0;
		std::uint64_t bytes_sent = 0;

		union
		{
			HttpState http;
			StubState stub;
		} h{};
	};

	/// One deadline list per listener and timer: every connection of a listener waits under the
	/// same duration, so a FIFO is ordered by deadline (I13).
	struct DeadlineList
	{
		Conn* head = nullptr;
		Conn* tail = nullptr;
		std::size_t size = 0;

		void push(Conn* c, TimerKind k, TimePoint deadline) noexcept
		{
			Link& l = c->timers[static_cast<std::size_t>(k)];
			l.deadline = deadline;
			l.armed = true;
			l.next = nullptr;
			l.prev = tail;
			if (tail != nullptr) tail->timers[static_cast<std::size_t>(k)].next = c;
			else head = c;
			tail = c;
			++size;
		}
		void remove(Conn* c, TimerKind k) noexcept
		{
			Link& l = c->timers[static_cast<std::size_t>(k)];
			if (!l.armed) return;
			if (l.prev != nullptr) l.prev->timers[static_cast<std::size_t>(k)].next = l.next;
			else head = l.next;
			if (l.next != nullptr) l.next->timers[static_cast<std::size_t>(k)].prev = l.prev;
			else tail = l.prev;
			l = Link{};
			--size;
		}
	};

	struct ListenerState
	{
		int fd = -1;
		std::size_t index = 0;
		const ListenerSpec* spec = nullptr;
		std::array<DeadlineList, 3> lists{};
	};

	/// The M1 stub handlers' first line, per class.
	constexpr std::string_view stub_marker(Proto p) noexcept
	{
		switch (p)
		{
			case Proto::tls: return "oneport M1 stub TLS\r\n";
			case Proto::h2c: return "oneport M1 stub h2c\r\n";
			case Proto::mqtt: return "oneport M1 stub MQTT\r\n";
			case Proto::ssh: return "oneport M1 stub SSH\r\n";
			case Proto::smtp: return "oneport M1 stub SMTP\r\n";
			case Proto::http1: return "oneport M1 stub HTTP\r\n";
		}
		return "oneport M1 stub\r\n";
	}

	inline std::span<const std::byte> as_bytes(std::string_view s) noexcept { return std::as_bytes(std::span<const char>(s.data(), s.size())); }

	/// What every worker shares, read-only after start().
	struct Shared
	{
		Detect detect = Detect::replay;
		nanoseconds t_fb{};
		nanoseconds t_dec{};
		nanoseconds t_hdr{};
		bool exclusive_listeners = true;  // the shared layout: EPOLLEXCLUSIVE on each worker's set
		Hooks hooks{};
	};

	struct ReadResult
	{
		std::uint32_t bytes = 0;
		bool eof = false;
		bool error = false;
	};

	class Worker
	{
	public:
		Worker(unsigned index, const Shared& shared, const std::vector<ListenerSpec>& specs, const std::vector<int>& fds)
			: index_(index), shared_(shared)
		{
			listeners_.resize(specs.size());
			for (std::size_t i = 0; i < specs.size(); ++i)
			{
				listeners_[i].fd = fds[i];
				listeners_[i].index = i;
				listeners_[i].spec = &specs[i];
			}
		}

		Worker(const Worker&) = delete;
		Worker& operator=(const Worker&) = delete;

		~Worker();

		void stop() noexcept { loop_.stop(); }

		void run();

		const Counters& counters() const noexcept { return c_; }
		const std::optional<std::string>& error() const noexcept { return error_; }

	private:
		// ---- The pass ----

		std::optional<TimePoint> earliest() const noexcept;

		void pass_once();

		void on_event(std::uint64_t tag, std::uint32_t events);

		// ---- Accept ----

		void on_accept(ListenerState& l);

		void start_detection_timers(Conn* c, TimePoint start);

		// ---- The PROXY header (I9 step 1) ----

		/// Peek mode on a one-port listener peeks the header and consumes it exactly; replay
		/// mode, and every dedicated listener, reads it into the handler's buffer.
		bool peeks(const Conn* c) const noexcept { return c->listener->spec->detects && shared_.detect == Detect::peek; }

		void on_proxy_readable(Conn* c, bool rdhup);

		void header_complete(Conn* c, const detect::ProxyResult& r);

		// ---- Detection (I9 steps 2 and 3, I11) ----

		void observed_app_bytes(Conn* c, std::uint32_t n);

		void on_detect_readable(Conn* c, bool rdhup);

		void run_detection(Conn* c, std::span<const std::byte> bytes, bool eof);

		void dispatch(Conn* c, Proto p, std::uint32_t at);

		/// Closes a connection whose detection ended without a handler.
		void end_detection(Conn* c, Outcome o, std::uint32_t at, detect::ProxyReason why = detect::ProxyReason::none,
		                   const TimedEvent* ev = nullptr);

		void report(const Conn* c, Outcome o, Proto p, std::uint32_t at, detect::ProxyReason why = detect::ProxyReason::none,
		            const TimedEvent* ev = nullptr);

		/// One MSG_PEEK receive of at most `window` bytes into the worker's scratch buffer.
		/// Returns the bytes, 0 at EOF, or -1 when nothing is queued or the connection was
		/// closed for an error.
		ssize_t peek(Conn* c, std::size_t window);

		void set_lowat(Conn* c, std::uint32_t total);

		// ---- Timers (I13; hypotheses.md, section 1) ----

		void arm(Conn* c, TimerKind k, TimePoint deadline) noexcept;

		void disarm(Conn* c, TimerKind k) noexcept { c->listener->lists[static_cast<std::size_t>(k)].remove(c, k); }

		static TimePoint deadline_of(const Conn* c, TimerKind k) noexcept { return c->timers[static_cast<std::size_t>(k)].deadline; }

		/// Records a timed event; `deadline` is read before the timer is disarmed.
		TimedEvent record(const Conn* c, TimerKind k, TimePoint deadline, TimePoint wait_return, TimerResult result);

		/// Every expiry at or before the clock reading taken after this pass's wait, after all of
		/// the pass's readiness events (1 b): T_hdr, then T_fb, then T_dec.
		void expire(TimePoint wait_return);

		void expire_hdr(Conn* c, TimePoint wait_return);

		/// T_fb: no byte yet (the timer is disarmed at the first byte). The check of 1(b): one
		/// non-blocking peek of one byte. A byte wins and decides; otherwise the fallback.
		void expire_fb(Conn* c, TimePoint wait_return);

		/// T_dec: bytes but no decision is "undecided" (1 d); silence without a fallback is
		/// "silent" (1 f). A silent connection of a fallback listener is left to T_fb, which
		/// never closes it (1 a).
		void expire_dec(Conn* c, TimePoint wait_return);

		// ---- Handlers (I26) ----

		void init_handler(Conn* c);

		void enter_handler(Conn* c, Proto p, Entry entry);

		/// Reads into the connection's buffer until the socket is drained, the buffer is full or
		/// the peer has shut down. A short read means drained: with edge-triggered readiness,
		/// any later byte raises a new event. After a half-close it reads on to see the EOF.
		ReadResult read_into(Conn* c, bool rdhup);

		void take_buffer(Conn* c);

		void drop_empty_buffer(Conn* c) noexcept;

		void track_user_bytes(Conn* c) noexcept { c->max_user_bytes = std::max(c->max_user_bytes, c->len); }

		/// B2(d): a connection still pending after an event holds no data buffer unless it holds
		/// bytes. Recorded, and reported with the detection.
		void audit_pending(int fd, std::uint32_t gen) noexcept;

		/// The handler's readiness: read (when `must_read`), then let the handler consume. An
		/// EOF already read by the detection or PROXY stage is in `eof_seen`.
		void handler_readable(Conn* c, bool rdhup, bool must_read);

		/// Parses and answers every complete request in the buffer. Returns false once the
		/// connection is closed.
		bool http_consume(Conn* c, bool eof);

		/// An M1 stub: the marker at entry, then every received byte counted and hashed, and
		/// at the client's EOF a trailer with the count and the hash, then close. M2 replaces
		/// each stub with the protocol's handler (I26).
		bool stub_consume(Conn* c, bool eof);

		// ---- Output ----

		/// Sends `bytes`; what the socket does not take waits for EPOLLOUT. Returns false once
		/// the connection is closed.
		bool send(Conn* c, std::span<const std::byte> bytes, bool close_after);

		/// Sends the pending tail on EPOLLOUT. Returns false once the connection is closed.
		bool flush(Conn* c);

		// ---- Connections ----

		std::uint64_t tag_of(const Conn* c) const noexcept;

		Conn* new_conn(int fd);

		void close_conn(Conn* c);

		void close_all();

		unsigned index_;
		const Shared& shared_;
		loop::EpollLoop loop_;
		std::vector<ListenerState> listeners_;
		std::vector<std::unique_ptr<Conn>> conns_;
		std::vector<Conn*> free_conns_;
		std::vector<Conn*> by_fd_;
		std::vector<std::uint32_t> gen_by_fd_;
		BufferPool pool_;
		std::array<std::byte, detect::kPeekWindow> scratch_{};  // the per-worker peek buffer (I11)
		std::uint64_t pass_ = 0;
		TimePoint prev_return_{};
		std::uint64_t next_id_ = 0;
		std::uint64_t open_ = 0;
		Counters c_;
		std::optional<std::string> error_;
	};

}  // namespace oneport::server::detail

#endif  // __linux__
