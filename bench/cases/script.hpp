// opcase's client: a hard case is a script of writes and gaps (hypotheses.md, section 2.4),
// run over loopback with TCP_NODELAY and one write per chunk. Each write's time is recorded on
// the server's clock (CLOCK_MONOTONIC: in M1 the server runs in the same process, so the clocks
// are one). The transcript keeps every byte the server sent and how the connection ended.
#pragma once

#include "fixtures.hpp"

#include <chrono>
#include <cstdint>
#include <optional>
#include <vector>

namespace oneport::opcase
{

	using Clock = std::chrono::steady_clock;
	using TimePoint = Clock::time_point;

	enum class Anchor : std::uint8_t
	{
		before_connect,  // just before connect(): no later than the server's accept
		after_connect,   // just after connect() returned
	};

	struct Step
	{
		enum class Kind : std::uint8_t
		{
			write,           // one send of `bytes`
			gap,             // wait `d`, reading what the server sends
			write_at,        // wait until `anchor` + `d`, then one send of `bytes`
			shutdown_write,  // shutdown(SHUT_WR)
			reset,           // close with SO_LINGER 0: the peer gets a reset; nothing more is read
			await_line,      // read until the server's first CRLF-terminated line has arrived
			await_close,     // read until the server closes
		};
		Kind kind = Kind::write;
		Bytes bytes;
		std::chrono::nanoseconds d{};
		Anchor anchor = Anchor::after_connect;
	};

	struct Script
	{
		std::vector<Step> steps;

		Script& write(Bytes b);
		Script& gap(std::chrono::nanoseconds d);
		Script& write_at(Anchor a, std::chrono::nanoseconds d, Bytes b);
		Script& shutdown_write();
		Script& reset();
		Script& await_line();
		Script& await_close();
		/// One write per chunk: `b` split after each offset in `cuts`, `gap` between the writes.
		Script& split(const Bytes& b, const std::vector<std::size_t>& cuts, std::chrono::nanoseconds gap);
	};

	struct Transcript
	{
		bool connected = false;
		std::uint16_t local_port = 0;
		TimePoint before_connect{};
		TimePoint after_connect{};
		std::vector<TimePoint> write_times;  // one per write performed, just before the send
		Bytes sent;
		bool write_failed = false;  // a write found the connection closed by the server
		Bytes received;
		std::optional<TimePoint> first_byte;  // the server's first byte
		std::optional<TimePoint> end;         // EOF or reset seen
		bool eof = false;
		bool reset = false;      // the server's side reset the connection
		bool client_reset = false;
		bool timed_out = false;  // a wait reached its limit
	};

	struct Limits
	{
		std::chrono::milliseconds wait{10000};  // the longest any await or the final read waits
	};

	/// Runs `script` against 127.0.0.1:`port`. Linux only in M1.
	Transcript run(const Script& script, std::uint16_t port, const Limits& limits = {});

	/// The first line of the bytes, without its CRLF, for messages (never echoed in full).
	std::string first_line(const Bytes& b);

}  // namespace oneport::opcase
