// opgen's worker (opgen.cpp runs one per generator CPU): its connections, its share of the
// slots or of the open-loop schedule, and the record of every exchange it ran. Linux.
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

#include <time.h>

#include <openssl/ssl.h>

namespace oneport::opgen::detail
{

	inline std::int64_t now_ns() noexcept
	{
		timespec ts{};
		clock_gettime(CLOCK_MONOTONIC, &ts);
		return static_cast<std::int64_t>(ts.tv_sec) * 1'000'000'000 + ts.tv_nsec;
	}

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
		int fd = -1;
		std::uint32_t gen = 0;
		bool active = false;
		bool connecting = false;
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

		/// A socket set up for one exchange: non-blocking, IP_BIND_ADDRESS_NO_PORT, TCP_NODELAY,
		/// bound to the block's next source address; -1 on failure.
		int make_socket();

		void arm_deadline(std::uint32_t i);

		/// Opens slot i's connection for a new exchange (churn) or a new connection (keep-alive).
		void start(std::uint32_t i, std::int64_t due);

		void connected(std::uint32_t i);

		void queue(Conn& c, const Bytes& b);

		/// Sends what is queued; false once the connection has failed.
		bool flush(std::uint32_t i);

		bool flush_tls(std::uint32_t i);

		void on_event(std::uint32_t i, std::uint32_t events);

		void readable(std::uint32_t i);

		void drive_tls(std::uint32_t i);

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
		loop::EpollLoop loop_;
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
		std::string error_;
	};

}  // namespace oneport::opgen::detail
