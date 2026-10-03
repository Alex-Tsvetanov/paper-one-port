// opgen's worker (opgen.cpp runs one per generator CPU): its connections, its share of the
// slots or of the open-loop schedule, and the record of every exchange it ran. Linux, on epoll;
// and Windows (M6b), on a completion port of its own (worker_win.cpp): ConnectEx, a zero-byte
// WSARecv as readiness, then synchronous non-blocking recv and send, as the server's IOCP worker
// reads (proposal I11).
#pragma once

#include "exchange.hpp"
#include "oneport/loop.hpp"
#include "opgen.hpp"

#include <array>
#include <atomic>
#include <climits>
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

#if defined(_WIN32)
// Before OpenSSL's headers, which include windows.h on Windows: no min and max macros.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <chrono>
#include <memory>
#include <utility>
#else
#include <time.h>
#endif

#include <openssl/ssl.h>

namespace oneport::opgen::detail
{

#if defined(_WIN32)
	/// The generator's clock on Windows: std::chrono::steady_clock, which MSVC reads from
	/// QueryPerformanceCounter, the clock the server's IOCP worker and opcase use on W (proposal I30).
	inline std::int64_t now_ns() noexcept
	{
		return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
	}
#else
	inline std::int64_t now_ns() noexcept
	{
		timespec ts{};
		clock_gettime(CLOCK_MONOTONIC, &ts);
		return static_cast<std::int64_t>(ts.tv_sec) * 1'000'000'000 + ts.tv_nsec;
	}
#endif

	// ---- One exchange's record ----

	enum class End : std::uint8_t
	{
		completed,
		connect,
		timeout,
		reset,
		eof,
		protocol,
		tls,
	};

	inline void count(Errors& e, End k) noexcept
	{
		switch (k)
		{
			case End::completed: break;
			case End::connect: ++e.connect; break;
			case End::timeout: ++e.timeout; break;
			case End::reset: ++e.reset; break;
			case End::eof: ++e.eof; break;
			case End::protocol: ++e.protocol; break;
			case End::tls: ++e.tls; break;
		}
	}

	/// One exchange (churn) or one request (keep-alive), as it ended.
	struct Record
	{
		std::int64_t due = 0;    // open loop: when it fell due; else equal to begin
		std::int64_t begin = 0;  // just before connect (keep-alive: just before the request's send)
		std::int64_t first = -1;  // the first byte the server sent; -1: none
		std::int64_t end = 0;     // completion or failure
		End how = End::completed;
	};

	// ---- Shared control ----

	struct Control
	{
		std::atomic<int> phase{0};  // 0 warm-up and window, 1 stop: no new exchange, 2 quit
		std::atomic<std::int64_t> t_end{INT64_MAX};
		std::atomic<unsigned> finished{0};  // workers that have ended
		std::int64_t origin = 0;  // open loop: the schedule's origin
	};

	// ---- A worker ----

	struct Conn
	{
		int fd = -1;  // Windows: the SOCKET, whose value fits an int (worker_win.cpp refuses one that does not)
		std::uint32_t gen = 0;
		bool active = false;
		bool connecting = false;
#if defined(_WIN32)
		bool reading = false;  // a zero-byte WSARecv is pending
#endif
		bool handshaking = false;  // TLS
		bool ready = false;        // keep-alive: the connection's setup is done
		bool done_reading = false;  // the response is complete; churn now waits for the server's close
		SSL* ssl = nullptr;
		std::uint64_t xid = 0;  // the exchange or request in flight
		Record rec{};
		std::array<std::byte, 16384> in{};
		std::uint32_t in_len = 0;
		Bytes out;
		std::size_t out_off = 0;
		// h2
		std::uint32_t stream = 1;
		bool status_ok = false;
		std::uint32_t body = 0;
		std::array<char, 13> body_bytes{};
		std::uint32_t window_used = 0;
	};

	struct Deadline
	{
		std::uint32_t idx;
		std::uint64_t xid;
		std::int64_t at;
	};

	/// Room reserved at a worker's start so that no reallocation stalls it inside a window (design
	/// choices of M3): records for about 7 s of WL3's fastest keep-alive cell on one of 12
	/// threads (140,000 requests per second in M3's first A/A windows), and open-loop slots
	/// (each holds a 16 KB input buffer) far above WL2's concurrency per thread.
	inline constexpr std::size_t kRecordsReserved = 131072;
	inline constexpr std::size_t kOpenSlotsReserved = 256;

#if defined(_WIN32)
	/// A Windows worker's completion port, its timer and its pending operations (worker_win.cpp).
	struct Io;
	struct IoFree
	{
		void operator()(Io* io) const noexcept;
	};
#endif

	class Worker
	{
	public:
		Worker(const Options& o, Control& ctl, unsigned index, SSL_CTX* ctx);

		~Worker();

		Worker(const Worker&) = delete;
		Worker& operator=(const Worker&) = delete;

		void run();

		const std::string& error() const noexcept { return error_; }
		std::vector<Record>& records() noexcept { return records_; }
		std::uint64_t connects() const noexcept { return connects_; }
		std::uint64_t peak() const noexcept { return peak_; }
		std::uint64_t unfinished() const noexcept { return unfinished_; }
		std::string probe_detail;

	private:
		// ---- Loads ----

		std::uint32_t my_slots() const noexcept;

		void run_closed();

		void run_open();

		std::uint32_t take_slot();

		// ---- The loop ----

		void pass(std::chrono::nanoseconds bound);

		// ---- An exchange ----

		std::uint32_t next_src() noexcept;

#if defined(_WIN32)
		// ---- Windows (worker_win.cpp) ----

		/// A socket set up for one exchange: overlapped and non-blocking, SO_REUSE_UNICASTPORT (the
		/// Windows form of IP_BIND_ADDRESS_NO_PORT: bind reserves no port of its own), TCP_NODELAY,
		/// bound to the block's next source address, associated with the worker's port with
		/// FILE_SKIP_COMPLETION_PORT_ON_SUCCESS; -1 on failure.
		int make_socket();
		/// Pins the worker thread to its CPU (Options::cpus).
		void pin_thread();
		/// The port, ConnectEx, and in open loop the high-resolution timer and its thread.
		void start_io();
		/// After every socket is closed: waits for the pending operations' completions (at most 5 s),
		/// so no OVERLAPPED is freed while the kernel may still write it.
		void finish_io() noexcept;
		static void close_socket(int fd) noexcept;
		/// Slot i's connect: ConnectEx on the next socket (start() has set the record up).
		void connect_win(std::uint32_t i);
		/// A completion dequeued from the port: a connect, or a zero-byte receive (readiness).
		void on_completion(void* op, std::uint32_t bytes, std::uintptr_t status);
		/// Reads what the socket holds, then posts the zero-byte WSARecv that reports more, until it
		/// stays pending; nothing once the exchange has ended.
		void arm_read(std::uint32_t i);
		/// A send that the socket did not take (WSAEWOULDBLOCK, or TLS's want-write) is tried again
		/// in each pass; the client's requests are a few hundred bytes, so this is not expected.
		void want_write(std::uint32_t i);
#else
		/// A socket set up for one exchange: non-blocking, IP_BIND_ADDRESS_NO_PORT, TCP_NODELAY,
		/// bound to the block's next source address; -1 on failure.
		int make_socket();
#endif

		void arm_deadline(std::uint32_t i);

		/// Opens slot i's connection for a new exchange (churn) or a new connection (keep-alive).
		void start(std::uint32_t i, std::int64_t due);

		void connected(std::uint32_t i);

		void queue(Conn& c, const Bytes& b);

		/// Sends what is queued; false once the connection has failed.
		bool flush(std::uint32_t i);

		bool flush_tls(std::uint32_t i);

#if !defined(_WIN32)
		void on_event(std::uint32_t i, std::uint32_t events);
#endif

		void readable(std::uint32_t i);

		void drive_tls(std::uint32_t i);

		/// TLS: OpenSSL's socket BIO calls this around each of its operations. A read that
		/// returned bytes sets tls_read_ns_ when unset, so an exchange's first byte is stamped as
		/// the socket read inside OpenSSL returned it, as the plain path stamps it after recv.
		static long on_bio(BIO* b, int oper, const char* argp, std::size_t len, int argi, long argl, int ret, std::size_t* processed);

		/// After each TLS call: the exchange's first byte, if it has none yet, is the first read
		/// with bytes in that call (M3 reading 3: TLS's first byte is the handshake flight).
		void note_tls_read(Conn& c) noexcept;

		void consume(Conn& c, std::size_t n) noexcept;

		/// The protocol's reader over c.in.
		void parse(std::uint32_t i);

		void parse_h2(std::uint32_t i);

		void parse_mqtt(std::uint32_t i);

		/// Keep-alive: a request completed; the next starts unless the window is over.
		void request_done(std::uint32_t i, const Bytes& next);

		void on_eof(std::uint32_t i);

		/// Churn: the exchange completed.
		void complete(std::uint32_t i);

		void fail(std::uint32_t i, End how);

		void close_conn(std::uint32_t i);

		void drop(Conn& c) noexcept;

		/// Closed loop: the slot's next exchange, unless the window is over.
		void next(std::uint32_t i);

		const Options& o_;
		Control& ctl_;
		unsigned index_;
		SSL_CTX* ctx_;
#if defined(_WIN32)
		std::unique_ptr<Io, IoFree> io_;
		std::vector<std::pair<std::uint32_t, std::uint32_t>> write_retry_;  // slot and its connection's generation (want_write)
#else
		loop::EpollLoop loop_;
#endif
		std::vector<Conn> conns_;
		std::vector<std::uint32_t> free_;
		std::vector<std::uint32_t> retry_;
		std::deque<Deadline> deadlines_;
		std::vector<Record> records_;
		std::uint64_t xid_ = 0;
		std::uint64_t active_ = 0;
		std::uint64_t peak_ = 0;
		std::uint64_t unfinished_ = 0;
		std::uint64_t connects_ = 0;
		std::uint64_t src_next_ = 0;
		int spare_fd_ = -1;  // open loop: the next exchange's socket, made before it falls due
		std::int64_t tls_read_ns_ = -1;  // TLS: the first socket read with bytes in the current call; -1: none
		std::string error_;
	};

}  // namespace oneport::opgen::detail
