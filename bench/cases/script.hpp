// opcase's client: a hard case is a script of writes and gaps (hypotheses.md, section 2.4),
// run over loopback with TCP_NODELAY and one write per chunk. Each write's time is recorded on
// the server's clock (CLOCK_MONOTONIC: the suite runs the server in the same process, so the
// clocks are one). The transcript keeps every byte the server sent and how the connection ended.
//
// A TLS step (TlsPlan) runs a live OpenSSL client with the settings of bench/tls: its first
// flight, the ClientHello, is written as the plan cuts it, and the rest of the handshake and the
// requests follow as the server answers. Its transcript adds what the handshake negotiated and
// the decrypted bytes: a handshake's wire bytes differ on every connection (the server's random,
// key share and signature), so two TLS transcripts are compared after decryption.
#pragma once

#include "fixtures.hpp"

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
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

	/// A live TLS exchange (Linux, with bench/tls).
	struct TlsPlan
	{
		std::string alpn = "http/1.1";         // the one protocol offered; empty: no ALPN
		std::string groups;                    // empty: the frozen X25519; else a negative test's list
		std::vector<std::size_t> cuts;         // offsets in prefix + first flight: one write per chunk
		std::chrono::nanoseconds gap{};        // between those writes
		std::uint8_t record_minor = 0;         // 0: as OpenSSL wrote it; else the record version's minor byte
		std::size_t fragment_at = 0;           // > 0: the ClientHello in two records, the first with this many handshake bytes
		Bytes prefix;                          // written before the ClientHello, in its first write (a PROXY header)
		std::vector<Bytes> requests;           // after the handshake, one TLS write each
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
			tls,             // a live TLS exchange (`plan`), then read until the server closes
		};
		Kind kind = Kind::write;
		Bytes bytes;
		std::chrono::nanoseconds d{};
		Anchor anchor = Anchor::after_connect;
		std::optional<TlsPlan> plan;
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
		Script& tls(TlsPlan p);
		/// One write per chunk: `b` split after each offset in `cuts`, `gap` between the writes.
		Script& split(const Bytes& b, const std::vector<std::size_t>& cuts, std::chrono::nanoseconds gap);
	};

	/// What a TLS step saw.
	struct TlsResult
	{
		bool handshake = false;  // the handshake completed
		std::string version;     // "TLSv1.3"
		std::string cipher;      // "TLS_AES_128_GCM_SHA256"
		std::string group;       // "x25519"
		std::string sigalg;      // the server's signature, as "<key type NID>+<hash NID>" short names
		std::string alpn;        // the protocol the server chose, or empty
		bool verified = false;   // the server's certificate verified, for oneport.test
		bool resumable = false;  // a session ticket made the session resumable
		Bytes client_hello;      // the first flight as written (after any change of the plan)
		Bytes plain;             // the server's decrypted bytes
		bool close_notify = false;
		std::string error;       // why the exchange stopped, if it did
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
		std::optional<TlsResult> tls;
	};

	struct Limits
	{
		std::chrono::milliseconds wait{10000};  // the longest any await or the final read waits
	};

	/// Runs `script` against 127.0.0.1:`port`. Linux only.
	Transcript run(const Script& script, std::uint16_t port, const Limits& limits = {});

	/// The first line of the bytes, without its CRLF, for messages (never echoed in full).
	std::string first_line(const Bytes& b);

}  // namespace oneport::opcase
