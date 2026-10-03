// The internals of oneport's server: connection state, deadline lists, buffers and the worker
// (design/proposal.md I3 to I5, I9 to I18, I22, I26, I27, I29). Linux only.
//
// One worker per thread, on one backend chosen per process (I1): epoll or io_uring. The detection,
// the timers, the handlers and the output are one piece of code; what differs is how bytes and
// readiness reach it:
//   epoll     readiness events, then synchronous receives and peeks (worker.cpp, handlers.cpp);
//   io_uring  completions of receives into a provided buffer or the connection's own buffer, of
//             polls that wait for the peek path, and of a multishot accept (uring.cpp).
// Output is a synchronous send on both; what the socket does not take waits in the connection's
// queue for writability (EPOLLOUT, or an IORING_OP_POLL_ADD for POLLOUT). Relay dispatch and
// pass-through are in relay.cpp.
//
// On Windows (M6a) the worker runs on IOCP (iocp.cpp), completion-based like io_uring: a zero-byte
// WSARecv is the readiness of the peek path and of the zero-byte receive form, then a synchronous
// recv or MSG_PEEK on the non-blocking socket; the posted form (section 10's secondary variant, no
// rule E candidate since it breaks B2(d)) posts the WSARecv with the handler's buffer. Output is
// the synchronous send; what the socket does not take waits in the connection's queue for an
// overlapped WSASend of it. Accept is AcceptEx, N_ACCEPTEX outstanding
// per listener. Relay dispatch is Linux only (hypotheses.md, section 2.1).
#pragma once

#if defined(__linux__) || defined(_WIN32)

#if defined(_WIN32)
// Winsock before anything that may include windows.h.
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
#endif

#include "apps.hpp"
#include "h2.hpp"
#include "oneport/loop.hpp"
#include "server.hpp"
#include "tls.hpp"

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

#if defined(__linux__)
#include <netinet/in.h>
#include <sys/epoll.h>
#include <sys/types.h>
#endif

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
#if defined(__linux__)
	constexpr std::uint32_t kConnEvents = EPOLLIN | EPOLLRDHUP | EPOLLET;
#endif

	/// io_uring: the provided-buffer group of the handlers' receive buffers, and how many buffers
	/// its ring holds free. A design choice of M2b: 128, twice WL1's 64 connection slots per
	/// server core, so one pass's receives rarely empty it; a receive that finds it empty fails
	/// with ENOBUFS and is posted again (counted, recv_retries). Each buffer the ring gives a
	/// connection is replaced at once from the pool, so the ring's buffers are a fixed count per
	/// worker, allocated at start, and a connection holds a buffer only from its first byte.
	constexpr std::uint16_t kBufferGroup = 0;
	constexpr unsigned kRingBuffers = 128;

	/// RELAY_BUF (hypotheses.md, section 9.1), the relay's user-space buffer per direction. A
	/// design choice of M2b: the handlers' receive buffer (kRecvBuf, I27), so in relay mode replay
	/// reads into the buffer the relay sends from, and both directions use one pool.
	constexpr std::uint32_t kRelayBuf = kRecvBuf;
	/// --relay-copy splice: the bytes asked of one splice, the default pipe capacity (16 pages
	/// of 4096 bytes on L).
	constexpr std::uint32_t kSpliceChunk = 65536;
	/// Pass-through: the most record bytes a ClientHello of at most B_CH message bytes can arrive
	/// in, since every record carries at least one byte behind its 5-byte header.
	constexpr std::uint32_t kHelloWireMax = 6 * detect::kBCh;

	[[noreturn]] inline void throw_errno(const char* what) { throw std::system_error(errno, std::generic_category(), what); }

#if defined(_WIN32)
	using ssize_t = std::ptrdiff_t;

	/// The last Winsock error as a std::system_error.
	[[noreturn]] inline void throw_wsa(const char* what) { throw std::system_error(WSAGetLastError(), std::system_category(), what); }

	/// A SOCKET kept in the shared code's `int fd`, where -1 stays "closed". Socket handles of the
	/// Windows TCP/IP provider are kernel handles, and a 64-bit process may truncate a kernel handle
	/// to its lower 32 bits or sign-extend it back (Microsoft, "Interprocess Communication Between
	/// 32-bit and 64-bit Applications"); INVALID_SOCKET sign-extends from -1. fd_of() checks it.
	inline SOCKET sock(int fd) noexcept { return static_cast<SOCKET>(static_cast<std::intptr_t>(fd)); }
	inline int fd_of(SOCKET s)
	{
		const auto v = static_cast<std::intptr_t>(s);
		if (v < 0 || v > static_cast<std::intptr_t>(0x7FFFFFFF)) throw std::runtime_error("oneport: a socket handle does not fit in 32 bits");
		return static_cast<int>(v);
	}

	/// The completion keys of a worker's port: its connections, and each listener by its index.
	constexpr std::uintptr_t kConnKey = 16;
	constexpr std::uintptr_t kListenerKeyBase = 32;

	/// N_ACCEPTEX (hypotheses.md, section 9.1; proposal I5): the AcceptEx requests each listener
	/// keeps outstanding, the same in both modes. A design choice of M6a: 64, WL1's connection slots
	/// per server core, so every slot of a closed loop finds an AcceptEx posted when it reconnects.
	constexpr std::size_t kAcceptEx = 64;
	/// AcceptEx's room for each address: sizeof(sockaddr_in) + 16 (AcceptEx docs).
	constexpr std::uint32_t kAcceptAddr = sizeof(sockaddr_in) + 16;
#endif

	// ---- Buffers: the handlers' receive buffers, from a per-worker free list ----

	struct Buffer
	{
		std::array<std::byte, kRecvBuf> data;
		std::uint16_t id = 0;  // its index in the pool: the io_uring buffer id
	};

	/// Buffers are taken on the first readiness or completion, never at accept (I27). A free
	/// buffer is poisoned for ASan and MSan, so a read of a returned buffer, or of bytes it held
	/// before, is reported. At most 65536 buffers per worker, the io_uring buffer id's range.
	class BufferPool
	{
	public:
		Buffer* get()
		{
			Buffer* b = nullptr;
			if (free_.empty())
			{
				if (all_.size() > 0xFFFF) throw std::runtime_error("oneport: more than 65536 receive buffers on one worker");
				all_.push_back(std::make_unique<Buffer>());
				b = all_.back().get();
				b->id = static_cast<std::uint16_t>(all_.size() - 1);
			}
			else
			{
				b = free_.back();
				free_.pop_back();
#if defined(ONEPORT_ASAN_POISON)
				ASAN_UNPOISON_MEMORY_REGION(b->data.data(), b->data.size());
#endif
			}
#if defined(ONEPORT_MSAN_POISON)
			__msan_poison(b->data.data(), b->data.size());
#endif
			++outstanding_;
			return b;
		}
		void put(Buffer* b) noexcept
		{
#if defined(ONEPORT_ASAN_POISON)
			ASAN_POISON_MEMORY_REGION(b->data.data(), b->data.size());
#endif
			free_.push_back(b);
			--outstanding_;
		}
		Buffer* by_id(std::uint16_t id) const noexcept { return id < all_.size() ? all_[id].get() : nullptr; }
		std::size_t allocated() const noexcept { return all_.size(); }
		std::size_t outstanding() const noexcept { return outstanding_; }
		~BufferPool()
		{
#if defined(ONEPORT_ASAN_POISON)
			for (Buffer* b : free_) ASAN_UNPOISON_MEMORY_REGION(b->data.data(), b->data.size());
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
		proxy,    // reading the PROXY header
		detect,   // one-port: deciding the class
		route,    // relay, TLS: reading the ClientHello for its SNI and ALPN (pass-through)
		relay,    // relay: connecting to the backend, then copying both ways
		handler,  // the class's handler (I26), entered at classification, at accept or at T_fb
	};

	/// How a handler or the relay is entered, which says where the first bytes are.
	enum class Entry : std::uint8_t
	{
		accept,      // dedicated: nothing received yet
		replay,      // classified in replay mode: the bytes are in the buffer
		peek,        // classified in peek mode: the bytes are still in the socket
		fallback,    // T_fb: nothing received
	};

	/// The application handler of a connection. A TLS connection has `none` until its handshake
	/// chooses HTTP/1.1 or h2 by ALPN.
	enum class App : std::uint8_t
	{
		none,
		http1,
		h2,
		mqtt,
		ssh,
		smtp,
		stub_tls,  // stub mode's TLS port (I18)
	};

	/// The io_uring operations a connection can have in flight, at most one of each; the kind is
	/// in the operation's user_data and a bit in Conn::posted. The client socket's, then the
	/// relay's backend socket's, then the relay's splices.
	enum class Op : std::uint8_t
	{
		recv,             // client: a receive (detection in replay, the handler, the relay's upward copy)
		poll_in,          // client: POLLIN | POLLRDHUP (the peek path; splice's upward copy)
		poll_out,         // client: POLLOUT (the output queue; the relay's downward copy blocked)
		b_connect,        // backend: the relay's connect
		b_recv,           // backend: a receive (the relay's downward copy)
		b_poll_in,        // backend: POLLIN | POLLRDHUP (splice's downward copy)
		b_poll_out,       // backend: POLLOUT (the relay's upward copy blocked)
		up_splice_in,     // client to the upward pipe
		up_splice_out,    // the upward pipe to the backend
		down_splice_in,   // backend to the downward pipe
		down_splice_out,  // the downward pipe to the client
		cancel,           // an IORING_OP_ASYNC_CANCEL; its completion is ignored
		accept,           // a listener's multishot accept (user_data holds the listener's index)
	};
	constexpr std::uint16_t bit(Op op) noexcept { return static_cast<std::uint16_t>(1u << static_cast<unsigned>(op)); }

	/// Where a posted io_uring receive writes: a provided buffer the kernel selects, the room after
	/// the bytes of a buffer the connection holds, or pass-through's ClientHello storage.
	enum class Into : std::uint8_t
	{
		provided,
		own,
		hello,
	};

#if defined(_WIN32)
	/// IOCP: one overlapped operation of a connection, its OVERLAPPED first, so a completion's
	/// pointer is the operation's. The ops it uses: Op::poll_in, the zero-byte WSARecv (readiness);
	/// Op::recv, the WSARecv with the handler's buffer (the posted form); Op::poll_out, the
	/// overlapped WSASend of the output queue (the wait for writability).
	struct IoOp
	{
		OVERLAPPED ov{};
		std::uint32_t slot = 0;
		Op op = Op::recv;
	};

	/// IOCP: one outstanding AcceptEx of a listener. With --iocp-accept buffer it receives into a
	/// handler's buffer: the data first, then the two addresses in the buffer's last 2 * kAcceptAddr
	/// bytes (AcceptEx docs); otherwise only the addresses, into `addrs`.
	struct AcceptReq
	{
		OVERLAPPED ov{};
		std::size_t listener = 0;
		SOCKET s = INVALID_SOCKET;
		bool posted = false;
		Buffer* buf = nullptr;
		std::array<std::byte, 2 * kAcceptAddr> addrs{};
	};

	/// IOCP: an operation that completed at once. FILE_SKIP_COMPLETION_PORT_ON_SUCCESS (proposal I5)
	/// queues no packet for it, so the worker handles it from a queue in the same pass (settle()).
	struct Inline
	{
		std::uint32_t slot = 0;
		std::uint32_t gen = 0;
		Op op = Op::recv;
		std::uint32_t bytes = 0;
		int error = 0;  // a Winsock error, 0 on success
	};
#endif

	struct ListenerState;
	struct Conn;

	struct Link
	{
		Conn* prev = nullptr;
		Conn* next = nullptr;
		TimePoint deadline{};
		bool armed = false;
	};

	/// A view of a connection's input: the received bytes, or for TLS the decrypted ones.
	struct View
	{
		Buffer*& buf;
		std::uint32_t& beg;
		std::uint32_t& len;
	};

	/// One direction of the relay. Upward (client to backend) reads into the connection's own
	/// receive buffer (Conn::buf), where replay left the first bytes; downward has its own.
	struct Dir
	{
		Buffer* buf = nullptr;  // downward only: bytes received and not yet sent are buf[beg, len)
		std::uint32_t beg = 0;
		std::uint32_t len = 0;
		int pipe_r = -1;  // splice: the pipe between the two sockets
		int pipe_w = -1;
		std::uint32_t in_pipe = 0;  // splice: bytes in the pipe not yet sent on
		bool eof = false;           // the source shut down writing
		bool shut = false;          // ... and its destination's writing is shut down too
		bool blocked = false;       // the destination took less than given: waits for writability
	};

	/// The state relay dispatch adds to a connection, made at dispatch, so a pending connection
	/// holds none of it (I15).
	struct Relay
	{
		int fd = -1;            // the backend connection
		std::uint32_t gen = 0;  // epoll: its tag's generation
		std::uint16_t port = 0;
		Proto proto = Proto::http1;
		bool connected = false;
		bool splice = false;
		bool reset = false;      // a side reset: the other is closed by reset too
		bool down_own = false;   // io_uring: the backend's posted receive writes into down.buf
		Route route = Route::by_class;
		Dir up;
		Dir down;
		// Pass-through (replay): a ClientHello whose records outgrow the receive buffer moves here.
		std::vector<std::byte> hello;  // storage; its bytes are hello[hello_beg, hello_len)
		std::uint32_t hello_len = 0;
		std::uint32_t hello_beg = 0;
		std::uint32_t hello_msg = 0;      // the reassembled message's length, its header included
		std::uint32_t hello_records = 0;  // the records that carried it
		std::uint32_t held_max = 0;       // the most payload bytes held while the ClientHello was incomplete
	};

	struct Conn
	{
		int fd = -1;
		std::uint32_t gen = 0;
		std::uint32_t slot = 0;  // its index in the worker's connections (io_uring user_data)
		Stage stage = Stage::detect;
		Proto proto = Proto::http1;
		App app = App::none;
		ListenerState* listener = nullptr;
		std::uint64_t id = 0;
		std::uint16_t peer_port = 0;

		// io_uring: the operations in flight, a bit per Op, and whether the connection waits for
		// them to finish after its close.
		std::uint16_t posted = 0;
		bool zombie = false;
		Into recv_into = Into::provided;  // where the posted receive writes
		std::uint32_t recv_events = 0;  // receive completions (the check of 1(b) in replay)

		Buffer* buf = nullptr;
		std::uint32_t beg = 0;  // the handler's bytes are buf[beg, len)
		std::uint32_t len = 0;
		bool last_read_full = false;  // the last read stopped at a full buffer
		bool eof_seen = false;        // a receive returned 0: the peer shut down writing
		bool rdhup_seen = false;      // an event reported the peer's half-close

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

		// TLS (I22 to I24): OpenSSL through the worker's BIO; the decrypted bytes in `plain`.
		SSL* ssl = nullptr;
		Buffer* plain = nullptr;
		std::uint32_t pbeg = 0;
		std::uint32_t plen = 0;
		bool tls_open = false;       // the handshake is complete
		bool tls_peer_done = false;  // the peer's close_notify arrived

		// Output the socket did not take, owned, sent on writability before anything else.
		std::vector<std::byte> pend;
		std::size_t pend_off = 0;
		bool close_after_out = false;
		bool want_out = false;       // epoll: EPOLLOUT registered
		bool read_deferred = false;  // a read waited for the pending output

		std::uint64_t bytes_received = 0;
		std::uint64_t bytes_sent = 0;

		std::unique_ptr<Relay> relay;

#if defined(_WIN32)
		// IOCP: its overlapped operations (IoOp); the output emitted while the queue's WSASend is
		// in flight, which may not touch `pend` until it completes; a closed connection's queue,
		// kept until that WSASend completes.
		IoOp io_zero{};
		IoOp io_recv{};
		IoOp io_send{};
		std::vector<std::byte> pend_more;
		std::vector<std::byte> sending;
		bool no_peek = false;        // detection reads into the handler's buffer: after IOCP's switch (I11) or AcceptEx's buffer
		bool peek_switched = false;  // an undecided peek switched it to replay (peek_to_replay)
#endif

		/// The application handler's state, by `app`.
		union
		{
			bool http_unused;
			nghttp2_session* h2;
			apps::MqttState mqtt;
			apps::SshState ssh;
			apps::StubTlsState stub;
		} a{};
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
		bool accept_armed = false;  // io_uring: its multishot accept is in flight
#if defined(_WIN32)
		std::vector<std::unique_ptr<AcceptReq>> accepts;  // IOCP: N_ACCEPTEX outstanding AcceptEx requests
		bool accept_buffer = false;  // --iocp-accept buffer applies: a one-port listener (no fallback, by the parser)
#endif
	};

	inline std::span<const std::byte> as_bytes(std::string_view s) noexcept { return std::as_bytes(std::span<const char>(s.data(), s.size())); }

	/// What every worker shares, read-only after start().
	struct Shared
	{
		Backend backend = Backend::epoll;
		Detect detect = Detect::replay;
		nanoseconds t_fb{};
		nanoseconds t_dec{};
		nanoseconds t_hdr{};
		bool exclusive_listeners = true;  // the shared layout: EPOLLEXCLUSIVE on each worker's set
		Hooks hooks{};
		SSL_CTX* ssl_ctx = nullptr;  // the server's TLS context (tls::server_ctx), shared by the workers
		// Relay dispatch (I17): one-port listeners hand classified connections to the backend.
		bool relay = false;
		bool splice = false;                                // --relay-copy splice
		std::array<sockaddr_in, detect::kProtos> backends{};  // by class, the backend's ports in the order of I20
#if defined(_WIN32)
		IocpReceive iocp_receive = IocpReceive::zero_byte;  // the receive form (config.hpp)
		IocpAccept iocp_accept = IocpAccept::no_buffer;     // the AcceptEx form
#endif
	};

	struct ReadResult
	{
		std::uint32_t bytes = 0;
		bool eof = false;
		bool error = false;
		bool reset = false;  // the error is the peer's reset
		bool retry = false;  // io_uring: the ring had no buffer (ENOBUFS); the receive is posted again
	};

	class Worker
	{
	public:
		Worker(unsigned index, const Shared& shared, const std::vector<ListenerSpec>& specs, const std::vector<int>& fds);

		Worker(const Worker&) = delete;
		Worker& operator=(const Worker&) = delete;

		~Worker();

		void stop() noexcept;

		void run();

		const Counters& counters() const noexcept { return c_; }
		const std::optional<std::string>& error() const noexcept { return error_; }

	private:
#if defined(__linux__)
		bool uring() const noexcept { return shared_.backend == Backend::io_uring; }
#else
		/// IOCP is completion-based like io_uring, so the shared paths that post an operation and
		/// wait for its completion take io_uring's branch: pending_io after accept and after the
		/// PROXY header, want_read when a handler wants input, the close's cancel of what is in
		/// flight, the slot's generation. Their IOCP implementations are in iocp.cpp; nothing
		/// io_uring-specific is compiled on Windows.
		bool uring() const noexcept { return true; }
#endif

		// ---- The pass (worker.cpp; io_uring's in uring.cpp) ----

		std::optional<TimePoint> earliest() const noexcept;

		loop::Bound bound_now() const;

		void pass_epoll();

		void on_event(std::uint64_t tag, std::uint32_t events);

		// ---- Accept ----

		void on_accept(ListenerState& l);

		/// A new connection on listener `l`: its state, its timers, and its first operation.
		void accepted(ListenerState& l, int fd, std::uint16_t peer_port);

		void start_detection_timers(Conn* c, TimePoint start);

		// ---- The PROXY header (I9 step 1) ----

		/// Peek mode on a one-port listener peeks the header and consumes it exactly; replay
		/// mode, and every dedicated listener, reads it into the handler's buffer.
#if defined(__linux__)
		bool peeks(const Conn* c) const noexcept { return c->listener->spec->detects && shared_.detect == Detect::peek; }
#else
		/// On IOCP a connection stops peeking once an undecided peek switched it to replay (I11), or
		/// when AcceptEx's receive buffer took its first bytes out of the socket.
		bool peeks(const Conn* c) const noexcept { return c->listener->spec->detects && shared_.detect == Detect::peek && !c->no_peek; }
#endif

		/// Readiness during the header: the peek path (both backends), or a read (epoll replay).
		void on_proxy_readable(Conn* c, bool rdhup);

		/// After bytes were read into the buffer during the header (epoll and io_uring replay).
		void proxy_after_read(Conn* c, const ReadResult& rr, bool rdhup);

		/// The header is consumed: on a one-port listener detection starts; on a dedicated one the
		/// handler is entered. Returns false once the connection is closed.
		bool header_complete(Conn* c, const detect::ProxyResult& r);

		// ---- Detection (I9 steps 2 and 3, I11) ----

		void observed_app_bytes(Conn* c, std::uint32_t n);

		/// Readiness during detection: the peek path (both backends), or a read (epoll replay).
		void on_detect_readable(Conn* c, bool rdhup);

		/// After bytes were read into the buffer during detection (epoll and io_uring replay).
		void detect_after_read(Conn* c, const ReadResult& rr);

		void run_detection(Conn* c, std::span<const std::byte> bytes, bool eof);

		void dispatch(Conn* c, Proto p, std::uint32_t at);

		/// Closes a connection whose detection ended without a handler.
		void end_detection(Conn* c, Outcome o, std::uint32_t at, detect::ProxyReason why = detect::ProxyReason::none,
		                   const TimedEvent* ev = nullptr);

		void report(const Conn* c, Outcome o, Proto p, std::uint32_t at, detect::ProxyReason why = detect::ProxyReason::none,
		            const TimedEvent* ev = nullptr);

		/// One MSG_PEEK receive of at most `window` bytes into `into` (the worker's scratch).
		/// Returns the bytes, 0 at EOF, or -1 when nothing is queued or the connection was
		/// closed for an error.
		ssize_t peek(Conn* c, std::span<std::byte> into);

		void set_lowat(Conn* c, std::uint32_t total);

		// ---- Timers (I13; hypotheses.md, section 1) ----

		void arm(Conn* c, TimerKind k, TimePoint deadline) noexcept;

		void disarm(Conn* c, TimerKind k) noexcept { c->listener->lists[static_cast<std::size_t>(k)].remove(c, k); }

		static TimePoint deadline_of(const Conn* c, TimerKind k) noexcept { return c->timers[static_cast<std::size_t>(k)].deadline; }

		/// Records a timed event; `deadline` is read before the timer is disarmed.
		TimedEvent record(const Conn* c, TimerKind k, TimePoint deadline, TimePoint wait_return, TimerResult result);

		/// Every expiry at or before the clock reading taken after this pass's wait, after all of
		/// the pass's readiness events and completions (1 b): T_hdr, then T_fb, then T_dec.
		void expire(TimePoint wait_return);

		void expire_hdr(Conn* c, TimePoint wait_return);

		/// T_fb: no byte yet (the timer is disarmed at the first byte). The check of 1(b) finds a
		/// byte or not; a byte wins and decides; otherwise the fallback.
		void expire_fb(Conn* c, TimePoint wait_return);

		/// T_dec: bytes but no decision is "undecided" (1 d); silence without a fallback is
		/// "silent" (1 f). A silent connection of a fallback listener is left to T_fb, which
		/// never closes it (1 a).
		void expire_dec(Conn* c, TimePoint wait_return);

		// ---- Handlers (I26; handlers.cpp) ----

		/// Enters the handler of class `p`, or in relay dispatch the relay to its backend.
		void enter_handler(Conn* c, Proto p, Entry entry);

		/// Sets up the handler's state; SSH and SMTP send their first line. False once closed.
		bool start_handler(Conn* c, Proto p);

		/// Reads into the connection's buffer until the socket is drained, the buffer is full or
		/// the peer has shut down (epoll). A short read means drained: with edge-triggered
		/// readiness, any later byte raises a new event. After a half-close it reads on to EOF.
		ReadResult read_into(Conn* c, bool rdhup);

		void take_buffer(Conn* c);

		void drop_empty_buffer(Conn* c) noexcept;

		void track_user_bytes(Conn* c) noexcept { c->max_user_bytes = std::max(c->max_user_bytes, c->len - c->beg); }

		/// B2(d): a connection still pending after an event holds no data buffer unless it holds
		/// bytes. Recorded, and reported with the detection.
		void audit_pending(Conn* c) noexcept;

		/// The handler's readiness on epoll: read (when `must_read`), then let the handler consume
		/// and send. While output is pending nothing more is read (the read waits for the flush).
		void handler_readable(Conn* c, bool rdhup, bool must_read);

		/// One handler step over the bytes the buffer holds, and its output sent. False once closed.
		bool handler_run(Conn* c);

		/// One step of the connection's application handler over `v`, its output appended to
		/// `out`. A need for room moves the incomplete tail to the buffer's start.
		apps::Next app_step(Conn* c, View v, bool eof, std::vector<std::byte>& out);

		/// One step of a TLS connection: the received bytes into OpenSSL, the handshake, the
		/// decrypted bytes through the application handler, its output through OpenSSL. The
		/// bytes to send are left in wire_. OpenSSL's state is made only once the ClientHello is
		/// complete in the handler's buffer, or cannot be completed there (M5).
		apps::Next tls_step(Conn* c);

		/// Makes the connection's OpenSSL state: SSL_new on the server's context and the worker's
		/// BIO, in accept state. False if OpenSSL could not.
		bool tls_new(Conn* c);

		/// After the handshake: decrypt, run the application handler, encrypt.
		apps::Next tls_app(Conn* c);

		// ---- Output (handlers.cpp) ----

		/// Sends `wire`, then acts on `next`. Returns false once the connection is closed.
		bool commit(Conn* c, std::vector<std::byte>& wire, apps::Next next);

		/// Sends `bytes`, or queues them behind pending output; what the socket does not take is
		/// copied into the connection's queue and waits for writability. False once closed.
		bool emit(Conn* c, std::span<const std::byte> bytes);

		/// Sends the pending output once the socket is writable. False once the connection is closed.
		bool flush(Conn* c);

		/// Waits for the client socket's writability: EPOLLOUT, or a POLLOUT poll.
		void want_out(Conn* c);

		// ---- io_uring (uring.cpp) ----

#if defined(__linux__)
		void run_uring();

		void pass_uring();

		void on_completion(const loop::Completion& x);

		void on_accept_completion(const loop::Completion& x);

		std::uint64_t ud(const Conn* c, Op op) const noexcept;
#endif

		/// Posts `op`'s submission bookkeeping: its bit, for the close to cancel it.
		void posted(Conn* c, Op op) noexcept { c->posted = static_cast<std::uint16_t>(c->posted | bit(op)); }

		/// A receive on the client socket: into the room after the buffer's bytes if it holds a
		/// buffer, else into a provided buffer, so a connection with no byte holds none (I15).
		void post_recv(Conn* c);

		/// The poll of the peek path: POLLIN | POLLRDHUP on the client socket.
		void post_poll_in(Conn* c);

		/// After a completion during the PROXY header, detection or the route: the next wait.
		void pending_io(Conn* c);

		/// The handler wants input: a receive, unless output waits, the peer has shut down or one
		/// is posted already.
		void want_read(Conn* c);

#if defined(__linux__)
		/// A receive's bytes into `buf` (a provided buffer the completion names becomes it), the
		/// `res` bytes unpoisoned for MSan.
		ReadResult take_recv(Conn* c, Buffer*& buf, std::uint32_t& len, const loop::Completion& x);

		/// The provided buffer a completion names, taken from the ring, which gets another at once.
		Buffer* take_selected(const loop::Completion& x);

		/// Puts one buffer from the pool into the ring.
		void provide_one();
#endif

		/// io_uring replay's check of 1(b): the non-waiting reap, every completion handled. Returns
		/// the result of `c`'s receive completion if one was among them.
		std::optional<int> reap_for(Conn* c);

#if defined(__linux__)
		/// Sets up the ring's provided buffers.
		void provide_ring();
#endif

		/// After close(): cancels what is in flight; the connection is freed when the last
		/// completion arrives (finalize).
		void cancel_all(Conn* c);

		void finalize(Conn* c);

#if defined(_WIN32)
		// ---- IOCP (iocp.cpp) ----
		// post_recv, post_poll_in, pending_io, want_read, reap_for, cancel_all, want_out and flush
		// above have IOCP implementations there too: post_poll_in posts the zero-byte WSARecv,
		// post_recv the WSARecv with the handler's buffer (the posted form), want_out the
		// overlapped WSASend of the queue, and flush continues after its completion.

		void run_iocp();

		void pass_iocp();

		/// Handles every completion IOCP reported at once (Inline), in order, as the port's.
		void settle();

		void on_entry(const loop::IocpEntry& x);

		void on_accept_entry(AcceptReq& r, const loop::IocpEntry& x);

		/// Posts one AcceptEx on the listener with a new socket (and, in the buffer form, a buffer).
		void post_accept(ListenerState& l, AcceptReq& r);

		/// A connection operation's end, from the port or from settle(): `bytes` moved, `error` a
		/// Winsock error or 0.
		void on_op(Conn* c, Op op, std::uint32_t bytes, int error);

		/// An operation that completed at once: handled by settle(), in this pass.
		void queue_inline(Conn* c, Op op, std::uint32_t bytes, int error);

		/// The overlapped WSASend of the queue's unsent bytes, pend[pend_off, end).
		void post_send(Conn* c);

		/// IOCP has no SO_RCVLOWAT, so an undecided peek switches the connection to replay for the
		/// rest of its detection (hypotheses.md, section 2.1; proposal I11): the queued bytes are
		/// read into the handler's buffer now and matching continues there. Counted (I29).
		void switch_to_replay(Conn* c);

		/// The non-waiting reap of 1(b) and the stop's drain hand their completions here.
		void take_entries(std::span<const loop::IocpEntry> xs);

		/// At stop: every connection closed, every AcceptEx cancelled, and their completions
		/// drained before the requests' memory goes.
		void stop_iocp();

		bool posted_form() const noexcept { return shared_.iocp_receive == IocpReceive::posted; }
#endif

		// ---- Relay dispatch and pass-through (relay.cpp) ----

		/// Classified (or T_fb) on a relaying listener: TLS waits for its ClientHello's route;
		/// every other class connects to its backend port.
		void start_relay(Conn* c, Proto p, Entry entry);

		/// Pass-through: readiness while the ClientHello is incomplete (both backends' peek path,
		/// and epoll's replay), and bytes received into the buffer or the ClientHello's storage.
		void route_readable(Conn* c, bool rdhup);
		void route_after_read(Conn* c, const ReadResult& rr);

		/// Pass-through on the records held so far (replay) or peeked (peek): routes, waits, or
		/// rejects. Returns false once the connection is closed.
		bool try_route(Conn* c, std::span<const std::byte> wire, bool eof);

		/// Pass-through found no route: closed, counted, reported.
		void route_reject(Conn* c);

		/// Opens the backend connection for the route and starts its connect.
		void relay_connect(Conn* c, Route route);

		/// The connect finished with `error` (0: connected): the copy starts both ways.
		void relay_connected(Conn* c, int error);

		void relay_report(const Conn* c, Route route);

		/// Epoll: a readiness event on the client (`backend` false) or the backend socket.
		void relay_event(Conn* c, bool backend, std::uint32_t events);

		/// Epoll: moves what it can in one direction, by the user-space copy or splice, then
		/// passes on the half-close once the source has ended. False once the connection is closed.
		bool relay_pump(Conn* c, bool up);
		bool pump_user(Conn* c, bool up);
		bool pump_splice(Conn* c, bool up);

		/// Whether a direction holds bytes in user space not yet sent (replayed, the ClientHello's,
		/// or received), and sends them. send_held returns false once the connection is closed;
		/// a destination that takes less leaves the direction blocked, waiting for writability.
		bool has_held(const Conn* c, bool up) const noexcept;
		bool send_held(Conn* c, bool up);

		/// Waits for the writability of a direction's destination.
		void wait_writable(Conn* c, bool up);

		/// After a direction ended: the half-close passed on; both ended closes the connection.
		/// False once the connection is closed.
		bool relay_after_eof(Conn* c, bool up);

		/// An error or a reset on either side: both are closed, by reset if a side reset.
		void relay_abort(Conn* c, bool reset);

#if defined(__linux__)
		/// io_uring: a completion of one of the relay's operations.
		void relay_completion(Conn* c, Op op, const loop::Completion& x);
#endif

		/// io_uring: what a direction waits for next, after any bytes it holds are sent.
		void relay_next_uring(Conn* c, bool up);

		// ---- Connections (handlers.cpp) ----

		std::uint64_t tag_of(int fd, std::uint32_t gen) const noexcept;

		Conn* new_conn(int fd);

		void close_conn(Conn* c);

		void close_all();

		unsigned index_;
		const Shared& shared_;
#if defined(__linux__)
		std::unique_ptr<loop::EpollLoop> ep_;
		std::unique_ptr<loop::UringLoop> ur_;
#else
		std::unique_ptr<loop::IocpLoop> ic_;
		std::vector<Inline> inline_;  // operations that completed at once, handled by settle()
		std::size_t inline_at_ = 0;   // settle()'s position in inline_
		LPFN_ACCEPTEX accept_ex_ = nullptr;
		LPFN_GETACCEPTEXSOCKADDRS accept_addrs_ = nullptr;
		std::size_t accepts_in_flight_ = 0;  // AcceptEx requests whose completion has not been taken
		Buffer* accept_buf_ = nullptr;       // --iocp-accept buffer: the accepted connection's first bytes, for pending_io()
		std::uint32_t accept_bytes_ = 0;
#endif
		std::vector<ListenerState> listeners_;
		std::vector<std::unique_ptr<Conn>> conns_;
		std::vector<Conn*> free_conns_;
		std::vector<Conn*> by_fd_;  // epoll: the connection that owns a descriptor, client or backend
		std::vector<std::uint32_t> gen_by_fd_;
		BufferPool pool_;
		std::uint32_t ring_buffers_ = 0;  // io_uring: provided buffers the ring holds
		std::vector<std::uint8_t> in_ring_;  // io_uring: by buffer id, whether the ring holds it
		std::uint32_t zombies_ = 0;       // io_uring: closed connections whose operations are in flight
		std::array<std::byte, detect::kPeekWindow> scratch_{};  // the per-worker peek buffer (I11)
		std::vector<std::byte> hello_scratch_;  // pass-through: the peeked records (peek mode), up to kHelloWireMax
		std::vector<std::byte> hello_msg_;      // pass-through: the reassembled ClientHello, B_CH bytes
		std::vector<std::byte> out_;   // a handler's output, staged until it is sent or encrypted
		std::vector<std::byte> wire_;  // a TLS connection's output, from OpenSSL
		tls::BioIo bio_;               // what OpenSSL reads and writes on this worker (tls::new_bio)
		std::uint64_t pass_ = 0;
		TimePoint prev_return_{};
		std::uint64_t next_id_ = 0;
		std::uint64_t open_ = 0;
		Counters c_;
		std::optional<std::string> error_;
	};

}  // namespace oneport::server::detail

#endif  // __linux__ || _WIN32
