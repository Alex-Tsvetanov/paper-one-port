// opcase hold: the silent background of the mixed-protocol cell (hypotheses.md, section 10: "C1's
// HTTP/1.1 churn with a fixed background of TLS keep-alive, MQTT keep-alive and silent
// connections, the same in both modes"; section 9.1: N_BG_SILENT).
//
// It holds `n` silent connections: each connects and sends nothing. A server in one-port mode
// closes a silent connection at T_dec (1 f), or hands it to a fallback at T_fb (1 a), while a
// dedicated port has no detection timer. So that the background stays fixed in both modes, the
// holder keeps `n` connections open by one policy, the same in either arm: a connection the peer
// closes (EOF or reset seen) is closed and opened again at once, to the same port, in the pass that
// saw it close; a connect that fails or does not complete within `connect_limit` is counted and
// made again at once. Bytes a server sends on a held connection (the SSH line or SMTP greeting of
// a dedicated port) are read and discarded. In dedicated mode no held connection is closed by the
// server, so the policy never fires; in one-port mode it reopens each connection every T_dec. What
// the policy did is counted and reported (`reopened`, `closed_by_peer`, `held_min`).
//
// At the stop every held connection is closed by reset (SO_LINGER on, zero timeout), so the
// background leaves no TIME-WAIT socket. Linux, and Windows since M7e (the mixed cell on IOCP).
#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace oneport::opcase
{

	struct HoldOptions
	{
		std::vector<std::uint16_t> ports;  // connection i goes to ports[i % ports.size()], and is reopened there
		std::uint32_t n = 0;
		bool reopen = true;                // false: a connection the peer closes stays closed (a test's control)
		std::uint32_t src_base = 0;        // host byte order; 0: no bind
		std::uint32_t k_src = 0;
		std::chrono::milliseconds connect_limit{1000};
	};

	struct HoldResult
	{
		bool ok = false;
		std::string error;
		std::uint64_t connects = 0;          // connect() calls
		std::uint64_t connect_failures = 0;  // refused, failed later, or not complete within connect_limit
		std::uint64_t closed_by_peer = 0;    // EOF or reset seen on a held connection
		std::uint64_t reopened = 0;          // connects made in place of a connection the peer closed
		std::uint64_t bytes_received = 0;    // bytes a server sent on a held connection, discarded
		std::uint32_t held_at_ready = 0;
		std::uint32_t held_min = 0;          // the fewest held at the end of any pass after ready
		std::uint32_t held_at_stop = 0;
		std::int64_t ready_ns = 0;           // when all n were held for the first time (0: never): CLOCK_MONOTONIC on Linux, steady_clock on Windows
		std::int64_t stop_ns = 0;
		std::uint64_t passes = 0;
	};

	/// Holds o.n silent connections to 127.0.0.1 until `stop` is set, by the policy above.
	/// `on_ready` is called once, in the first pass that ends with all n held. Linux and Windows.
	HoldResult hold(const HoldOptions& o, const std::atomic<bool>& stop, const std::function<void(const HoldResult&)>& on_ready = {});

	/// The result as one JSON object, with the options that produced it.
	std::string hold_json(const HoldOptions& o, const HoldResult& r);

}  // namespace oneport::opcase
