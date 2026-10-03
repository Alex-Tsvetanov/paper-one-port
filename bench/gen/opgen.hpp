// opgen, the load generator (hypotheses.md, sections 2.4 and 3; design/proposal.md, I30).
//
// Scripted exchanges per protocol (WL1's table), in three loads:
//   - churn, closed loop (WL1): C connection slots; each repeats connect, one exchange, close;
//   - churn, open loop (WL2): exchanges fall due at a fixed rate, whether or not earlier ones
//     completed, each on a new connection; latency runs from the due time;
//   - keep-alive (WL3): C connections established before the measured window, one request in
//     flight per connection.
// Protocols: HTTP/1.1, h2c (prior knowledge, static-table header fields, read to END_STREAM),
// TLS with HTTP/1.1 (the OpenSSL build and settings of bench/tls), MQTT 3.1.1, SSH, and the TLS
// stub exchange (the recorded ClientHello, read the stub's 13 bytes to EOF).
//
// Counting. Only the measured window counts. The main thread takes the clock after the warm-up
// and again after the window, and prints MEASURE_START and MEASURE_END at those instants (the
// window runner snapshots the server there). Closed loop: the exchanges that completed without
// error between the two readings, and the wall time between them. Open loop: the exchanges due
// between them, and how many of those completed without error. No rate is computed from
// anything else, and no other tool's summary is read.
//
// Time to first response byte (TTFB): from just before connect to the first byte the server
// sends on the connection, on the generator's clock (CLOCK_MONOTONIC); in open loop from the due
// time. Exact samples: the quantiles are of the window's values, not of a histogram.
//
// Source addresses (section 2.4): every connection binds a source address of the window's block,
// base + (n mod K_SRC), with IP_BIND_ADDRESS_NO_PORT, so bind reserves no port and connect picks
// one that keeps the 4-tuple unique.
//
// Saturation. opgen reports the CPU time of each of its worker threads over the measured window,
// so the window runner can apply section 7's generator rule; the runner also reads the busy share
// of the generator's CPUs from /proc/stat, and the rule uses the larger (lab/t1/t1.py).
#pragma once

#include <chrono>
#include <cstdint>
#include <expected>
#include <optional>
#include <ostream>
#include <string>
#include <string_view>
#include <vector>

namespace oneport::opgen
{

	enum class Proto : std::uint8_t
	{
		http1,
		h2c,
		tls,       // TLS with HTTP/1.1 (ALPN http/1.1)
		mqtt,      // MQTT 3.1.1
		ssh,
		tls_stub,  // the recorded ClientHello against stub mode's TLS port
	};
	std::string_view name(Proto p) noexcept;

	enum class Load : std::uint8_t
	{
		churn,
		keepalive,
	};
	std::string_view name(Load l) noexcept;

	struct Options
	{
		Proto proto = Proto::http1;
		Load load = Load::churn;
		std::uint16_t port = 0;
		/// Closed loop and keep-alive: the connection slots (C of WL1 and WL3).
		std::uint32_t conns = 64;
		/// Open loop (churn only): exchanges per second; 0 is closed loop.
		double rate = 0;
		std::uint32_t threads = 1;
		/// One CPU per thread, or empty: no affinity.
		std::vector<int> cpus;
		/// The source-address block: base (host byte order) and its size, K_SRC.
		std::uint32_t src_base = 0x7F000101u;  // 127.0.1.1
		std::uint32_t k_src = 1;
		std::chrono::nanoseconds warmup = std::chrono::seconds(1);
		std::chrono::nanoseconds duration = std::chrono::seconds(5);
		/// An exchange (or a keep-alive request) that has not completed this long after its start
		/// fails: churn's from just before connect, keep-alive's from its send (the first one of a
		/// connection from just before connect, its setup included).
		std::chrono::nanoseconds timeout = std::chrono::milliseconds(1000);
		/// --probe: one exchange, then report it.
		bool probe = false;
	};

	/// Parses opgen's command line (no program name). An error names the flag.
	std::expected<Options, std::string> parse_args(const std::vector<std::string_view>& args);
	std::string usage();

	/// Exact quantiles of a window's samples, in nanoseconds.
	struct Quantiles
	{
		std::uint64_t n = 0;
		double median = 0;  // the mean of the two middle values when n is even
		std::uint64_t p99 = 0;   // nearest rank: the value at rank ceil(0.99 n)
		std::uint64_t p999 = 0;
		double mean = 0;
		std::uint64_t min = 0;
		std::uint64_t max = 0;
	};
	Quantiles quantiles(std::vector<std::uint64_t> v);

	/// Failures, by kind. Each failed exchange counts once, in its first kind.
	struct Errors
	{
		/// connect() refused or failed, at once or later (SO_ERROR), or not complete at the
		/// exchange's timeout (a SYN never answered).
		std::uint64_t connect = 0;
		std::uint64_t timeout = 0;   // no progress for Options::timeout
		std::uint64_t reset = 0;     // the server reset the connection, or a send or receive failed
		std::uint64_t eof = 0;       // the server closed before the exchange was complete
		std::uint64_t protocol = 0;  // a response that is not the expected one
		std::uint64_t tls = 0;       // a TLS failure that is none of the above
		std::uint64_t total() const noexcept { return connect + timeout + reset + eof + protocol + tls; }
	};

	struct Phase
	{
		std::uint64_t completed = 0;  // exchanges (keep-alive: requests) completed without error
		Errors errors{};
		std::uint64_t connects = 0;   // connect() calls
	};

	struct Result
	{
		bool ok = false;           // the run itself worked (not whether the exchanges did)
		std::string error;         // why not
		std::int64_t start_ns = 0;  // MEASURE_START, CLOCK_MONOTONIC
		std::int64_t end_ns = 0;    // MEASURE_END
		double wall_s = 0;          // end - start
		Phase warmup;
		Phase measure;              // completions (closed loop) between the two readings; its `connects` counts the whole run
		std::uint64_t all_completed = 0;  // every completion of the run (warm-up, window and drain): keep-alive's requests per connection
		// Open loop: the exchanges due in the window and how many of them completed without error.
		std::uint64_t due = 0;
		std::uint64_t due_completed = 0;
		Errors due_errors{};
		std::uint64_t due_unfinished = 0;  // neither completed nor failed when the drain ended
		Quantiles ttfb;      // per exchange in the window: connect (open loop: due) to the first response byte
		Quantiles ttfb_connect;  // open loop: from just before connect, beside it
		Quantiles exchange;  // per exchange in the window: connect (open loop: due) to its completion
		Quantiles issue_lag; // open loop: from the due time to just before connect
		std::vector<double> thread_cpu_s;  // CPU time of each worker thread over the window
		double cpu_s = 0;                  // their sum
		double cpu_pct = 0;                // cpu_s / (wall_s x threads), in percent
		double max_thread_cpu_pct = 0;
		double process_cpu_s = 0;          // the whole process over the window
		std::uint64_t peak_concurrency = 0;  // open loop: the most exchanges one worker had in flight at once
		// --probe
		std::string probe_detail;
	};

	/// Runs the configured load (or the probe) against 127.0.0.1:port. `markers` receives the
	/// MEASURE_START and MEASURE_END lines, flushed at once; it may be null. Linux only.
	Result run(const Options& o, std::ostream* markers);

	/// The result as one JSON object, with the options that produced it.
	std::string to_json(const Options& o, const Result& r);

	/// The dotted form of an IPv4 address in host byte order, and its parse.
	std::string dotted(std::uint32_t addr);
	std::optional<std::uint32_t> parse_dotted(std::string_view s);

}  // namespace oneport::opgen
