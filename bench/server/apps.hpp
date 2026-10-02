// The handlers of design/proposal.md I26 that need no library, as pure steps over received bytes
// (hypotheses.md, section 2.1, "Handlers"). The worker (handlers.cpp) gives each step the bytes in
// its receive buffer, or for TLS the decrypted bytes, and sends what the step appends to `out`.
// The same code serves both modes (I21): in one-port mode a handler is entered at classification,
// in dedicated mode at accept, and from then on nothing differs.
//
// Each handler applies the detector's grammar to its first bytes, as the HTTP/1.1 handler does
// (I26), so input that one-port mode would reject is closed without a response in dedicated mode
// too: SSH's "SSH-", MQTT's CONNECT up to the protocol level.
//
// The bytes they send are design choices of M2a, recorded in design/status.md:
//   SSH   "SSH-2.0-oneport" and CRLF at entry (I26); then the client's line is read up to its LF,
//         at most 255 bytes (RFC 4253 s4.2), and the connection closes.
//   SMTP  at entry "220 oneport.test ESMTP"; per CRLF-terminated line: EHLO (the verb, case-
//         insensitive, alone or before a space) "250 oneport.test"; QUIT "221 oneport.test
//         closing", then close; any other line, the empty one included, "500 syntax error,
//         command unrecognized". A line of 512 bytes or more without its CRLF (RFC 5321
//         s4.5.3.1.4) gets that 500 and the connection closes.
//   MQTT  CONNECT, read to its end, gets CONNACK accepted: 20 02 00 00 at level 4 (3.1.1
//         s3.2), 20 03 00 00 00 at level 5 (5.0 s3.2, an empty property list); PINGREQ C0 00 gets
//         PINGRESP D0 00; DISCONNECT closes. Any other packet, a second CONNECT, or a CONNECT
//         whose Remaining Length cannot hold its protocol name and level, closes without a
//         response. The payload of a CONNECT is skipped as it arrives, never held.
#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>
#include <vector>

namespace oneport::apps
{

	/// What the handler does after a step.
	enum class Next : std::uint8_t
	{
		more,                // wait for more bytes
		need_room,           // an incomplete unit fills the buffer's tail: move it to the start, read on
		close_after_output,  // close once everything appended so far is sent
		close_now,           // close without sending more
	};

	struct Step
	{
		std::uint32_t used = 0;  // bytes consumed from the front of `in`
		Next next = Next::more;
	};

	/// Where the input lies in its buffer: `at_start` when it begins at the buffer's first byte,
	/// `full` when the buffer has no room after it.
	struct Room
	{
		bool at_start = true;
		bool full = false;
	};

	// ---- HTTP/1.1 (http1.hpp's parser) ----

	/// Answers every complete request in `in` in order: 200, or 400 then close; a request line
	/// that breaks the detector's grammar closes without a response.
	Step http1(std::span<const std::byte> in, Room room, bool eof, std::vector<std::byte>& out);

	// ---- SSH ----

	inline constexpr std::string_view kSshBanner = "SSH-2.0-oneport\r\n";
	inline constexpr std::uint32_t kSshLineMax = 255;

	struct SshState
	{
		std::uint16_t seen;  // bytes of the client's line so far
	};

	Step ssh(SshState& s, std::span<const std::byte> in, bool eof);

	// ---- SMTP ----

	inline constexpr std::string_view kSmtpGreeting = "220 oneport.test ESMTP\r\n";
	inline constexpr std::string_view kSmtpEhlo = "250 oneport.test\r\n";
	inline constexpr std::string_view kSmtpBye = "221 oneport.test closing\r\n";
	inline constexpr std::string_view kSmtpUnknown = "500 syntax error, command unrecognized\r\n";
	inline constexpr std::uint32_t kSmtpLineMax = 512;

	Step smtp(std::span<const std::byte> in, Room room, bool eof, std::vector<std::byte>& out);

	// ---- MQTT ----

	struct MqttState
	{
		std::uint8_t phase;     // 0: a packet's first byte; 1: its Remaining Length; 2: CONNECT's name and level; 3: the rest
		std::uint8_t type;      // the packet's first byte
		std::uint8_t rl_bytes;  // Remaining Length bytes read
		std::uint8_t vh;        // CONNECT bytes checked of 00 04 'M' 'Q' 'T' 'T' level
		std::uint8_t level;     // 4 or 5
		bool connected;         // CONNACK sent
		std::uint32_t rl;       // the Remaining Length
		std::uint32_t left;     // the packet's bytes still to skip
	};

	Step mqtt(MqttState& m, std::span<const std::byte> in, bool eof, std::vector<std::byte>& out);

	// ---- Stub mode's TLS port (proposal I18; hypotheses.md, section 2.1, "Stub mode") ----

	/// The fixed 13-byte body of I26 that the stub writes for a TLS record.
	inline constexpr std::string_view kStubBody = "Hello, World!";

	struct StubTlsState
	{
		std::uint8_t seen;                 // record header bytes read, at most 5
		bool answered;                     // the body is written
		std::uint8_t hdr[5];               // the record header
		std::uint32_t left;                // record body bytes still to skip
	};

	/// The stub's TLS handler: reads one whole TLS record, its 5-byte header (content type 22,
	/// handshake; major version 3; a length of at most 2^14, as the detector's TLS matcher reads
	/// it) and then that many bytes, skipped as they arrive; then writes the 13-byte body and
	/// closes. It never handshakes. Other first bytes close without a response; bytes after the
	/// record are not read. Design choices of M2b, recorded in design/status.md.
	Step stub_tls(StubTlsState& s, std::span<const std::byte> in, bool eof, std::vector<std::byte>& out);

	inline void append(std::vector<std::byte>& out, std::string_view s)
	{
		const auto* p = reinterpret_cast<const std::byte*>(s.data());
		out.insert(out.end(), p, p + s.size());
	}

}  // namespace oneport::apps
