// oneport's server: listeners, workers, detection, timers, dispatch and handlers
// (design/proposal.md, section 2; hypotheses.md, section 2.1).
//
// Served: the epoll backend with in-process dispatch, in one-port and dedicated mode, with both
// detection modes, PROXY on or off, every fallback, both listener layouts and any worker count,
// and every handler of I26 (HTTP/1.1, h2, TLS, MQTT, SSH, SMTP). The io_uring backend, relay
// dispatch and stub mode are M2b; IOCP is M6 (not_served()).
//
// The counters (proposal I29) are plain integers per worker, read after stop(). The reports and
// hooks below are the test suite's view of each connection (tests/case_tests.cpp); with no hook
// set, nothing is built for them.
#pragma once

#include "config.hpp"
#include "detect.hpp"

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace oneport::server
{

	using Clock = std::chrono::steady_clock;  // CLOCK_MONOTONIC on L
	using TimePoint = Clock::time_point;
	using detect::Proto;

	/// The receive buffer of every handler, the same size in both modes (proposal I27). Replay
	/// mode reads the first bytes into it. A design choice of M1: one page on L (4096 bytes, read
	/// 2026-10-02), which holds HC23's 4,096 bytes in one read.
	inline constexpr std::uint32_t kRecvBuf = 4096;

	/// How a connection's detection ended. The first six are the frozen outcome names
	/// (hypotheses.md, section 1 and 2.1); the rest are design choices of M1, for ends the frozen
	/// text does not name.
	enum class Outcome : std::uint8_t
	{
		classified,       // a matcher said yes
		rejected,         // the bytes ruled out every matcher (1 e)
		undecided,        // bytes, no decision, at T_dec or at a half-close (1 d, 1 h)
		silent,           // no byte, at T_dec without a fallback or at a half-close (1 f, 1 h)
		fallback,         // T_fb expired with no byte (1 a)
		rejected_budget,  // more than B_dec bytes while undecided (section 1, "Budgets")
		proxy_rejected,   // the PROXY header cannot match, is too long or is malformed (I9)
		proxy_timeout,    // T_hdr expired before the PROXY header was complete (HC12)
		reset,            // the peer reset, or a receive failed, during detection (HC22)
		stopped,          // still pending when the server stopped
	};
	inline constexpr std::size_t kOutcomes = 10;
	std::string_view name(Outcome o) noexcept;

	enum class TimerKind : std::uint8_t
	{
		t_hdr,
		t_fb,
		t_dec,
	};
	std::string_view name(TimerKind k) noexcept;

	/// What handling an expiry did.
	enum class TimerResult : std::uint8_t
	{
		closed,     // T_hdr or T_dec closed the connection
		fallback,   // T_fb dispatched it to the fallback handler
		byte_won,   // the check of 1(b) found a byte, so the bytes decide
		waited,     // T_dec on a silent connection of a fallback listener: T_fb decides (design/status.md)
	};

	/// One timed event (proposal I29, B2): its deadline, when the wait of the pass that handled it
	/// returned, when the previous pass's wait returned, and which pass handled it. B2(a) and (b)
	/// hold when prev_wait_return < deadline <= wait_return <= handled_at.
	struct TimedEvent
	{
		std::uint64_t conn = 0;
		TimerKind kind = TimerKind::t_dec;
		TimerResult result = TimerResult::closed;
		TimePoint start{};  // when the timer started: accept, or the PROXY header's completion
		TimePoint deadline{};
		TimePoint wait_return{};
		TimePoint prev_wait_return{};
		TimePoint handled_at{};
		std::uint64_t pass = 0;
	};

	/// The counters of one worker (proposal I29), without atomics. Operations count calls.
	struct Counters
	{
		// Operations by kind.
		std::uint64_t accept_calls = 0;
		std::uint64_t recv_calls = 0;
		std::uint64_t peek_calls = 0;
		std::uint64_t send_calls = 0;
		std::uint64_t setsockopt_calls = 0;  // each SO_RCVLOWAT set and reset
		std::uint64_t check_calls = 0;       // the non-blocking check of 1(b)
		std::uint64_t epoll_wait_calls = 0;
		std::uint64_t epoll_ctl_calls = 0;
		std::uint64_t zero_byte_recv_calls = 0;  // IOCP (M6)
		std::uint64_t io_uring_enter_calls = 0;  // io_uring (M2b)
		std::uint64_t gqcs_calls = 0;            // GetQueuedCompletionStatus (M6)
		std::uint64_t peek_to_replay = 0;        // IOCP's switch (M6)
		std::uint64_t lowat_sets = 0;
		std::uint64_t lowat_resets = 0;
		std::uint64_t check_found_byte = 0;
		// Payload bytes across the user and kernel boundary, and copied in user space.
		std::uint64_t bytes_received = 0;
		std::uint64_t bytes_peeked = 0;
		std::uint64_t bytes_sent = 0;
		std::uint64_t bytes_copied = 0;
		// Wakeups of connections during detection (the PROXY header included).
		std::uint64_t detection_wakeups = 0;
		// Connections and their outcomes.
		std::uint64_t accepted = 0;
		std::uint64_t closed = 0;
		std::array<std::uint64_t, kOutcomes> outcomes{};
		std::array<std::uint64_t, detect::kProtos> classified{};  // per class
		std::array<std::uint64_t, detect::kProtos> fallback{};    // per fallback class
		std::uint64_t accept_errors = 0;
		// State at the end (after stop()).
		std::uint64_t conns_open = 0;
		std::uint64_t buffers_allocated = 0;
		std::uint64_t buffers_outstanding = 0;
		std::uint64_t passes = 0;
		std::vector<TimedEvent> timed;

		Counters& operator+=(const Counters& o);
	};

	/// "counter <name> <value>" lines, in a fixed order.
	std::string describe(const Counters& c);

	/// The end of one connection's detection (test hook). In a dedicated listener without PROXY no
	/// detection happens and none is reported.
	struct DetectionReport
	{
		unsigned worker = 0;
		std::uint64_t conn = 0;
		std::uint16_t peer_port = 0;  // the accepted socket's peer port
		Outcome outcome = Outcome::stopped;
		Proto proto = Proto::http1;  // classified: the class; fallback: the fallback's class
		std::uint32_t at = 0;        // classified: the decision length; rejected: the deciding byte
		detect::ProxyReason proxy_reason = detect::ProxyReason::none;
		std::uint64_t accept_pass = 0;
		std::uint64_t end_pass = 0;
		std::uint64_t last_read_pass = 0;  // the pass of the last receive or peek that returned bytes
		std::uint64_t observe_pass = 0;    // the pass that observed a half-close (0: none)
		TimePoint accept_time{};
		TimePoint timers_start{};  // T_fb and T_dec start here (accept, or the PROXY header's end)
		TimePoint end_time{};
		std::uint32_t app_bytes = 0;         // application bytes observed
		std::uint32_t max_user_bytes = 0;    // the most payload bytes the connection held in user space
		bool buffer_while_silent = false;    // a data buffer held while no byte had arrived (B2 d)
		std::uint32_t wakeups = 0;
		std::uint32_t lowat_sets = 0;
		std::uint32_t lowat_resets = 0;
		bool has_proxy = false;
		detect::ProxySource proxy{};
		bool timed = false;
		TimedEvent event{};
	};

	/// A connection's close (test hook).
	struct CloseReport
	{
		unsigned worker = 0;
		std::uint64_t conn = 0;
		std::uint16_t peer_port = 0;
		bool handled = false;  // reached a handler
		Proto proto = Proto::http1;
		std::uint64_t bytes_received = 0;
		std::uint64_t bytes_sent = 0;
	};

	/// Test instrumentation, null in the binary. Each hook runs on the worker thread.
	struct Hooks
	{
		void* ctx = nullptr;
		void (*detection)(void* ctx, const DetectionReport&) = nullptr;
		void (*closed)(void* ctx, const CloseReport&) = nullptr;
		/// Called in every pass after its readiness events and before its expiries, with the time
		/// its wait returned and the earliest armed deadline, so a test can make a byte arrive in
		/// the pass that handles an expiry (hypotheses.md, section 11: "the check of 1(b) ... with a
		/// byte in the pass of the expiry").
		void (*before_expiries)(void* ctx, unsigned worker, TimePoint wait_return, std::optional<TimePoint> earliest) = nullptr;
	};

	/// One listening socket's role, from the listener setup (listeners.cpp, the only reader of the
	/// mode; proposal I21).
	struct ListenerSpec
	{
		bool detects = false;  // one-port: detection, then dispatch; dedicated: the class at accept
		Proto proto = Proto::http1;
		bool proxy = false;
		std::optional<Proto> fallback;  // one-port only
		std::string name;               // "one-port", or the class of a dedicated port
	};

	/// Why this configuration is not served yet, and in which milestone it is, or nullopt.
	std::optional<std::string> not_served(const Config& config);

	/// The listeners of a configuration, in port order: one in one-port mode; in dedicated mode
	/// HTTP/1.1, h2c, TLS, MQTT, SSH and SMTP on consecutive ports (proposal I20).
	std::vector<ListenerSpec> listener_specs(const Config& config);

	struct Options
	{
		Hooks hooks{};
	};

	class Server
	{
	public:
		/// Throws std::invalid_argument when the configuration is not served yet, and
		/// std::runtime_error when the TLS context cannot be made.
		explicit Server(const Config& config, Options options = {});
		~Server();
		Server(const Server&) = delete;
		Server& operator=(const Server&) = delete;

		/// Binds the listeners on 127.0.0.1 and starts the workers. Throws std::system_error.
		void start();
		/// Stops the workers and joins them; idempotent.
		void stop();

		/// The bound ports, in listener order.
		std::vector<std::uint16_t> ports() const;
		const std::vector<ListenerSpec>& listeners() const;
		/// After stop(): per worker, and summed.
		std::vector<Counters> per_worker() const;
		Counters totals() const;
		/// After stop(): the first error a worker raised, if any.
		std::optional<std::string> error() const;

		/// The size of one connection's state, fixed at compile time (proposal I15).
		static std::size_t conn_state_bytes() noexcept;

	private:
		struct Impl;
		std::unique_ptr<Impl> impl_;
	};

}  // namespace oneport::server
