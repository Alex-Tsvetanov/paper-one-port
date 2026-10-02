// opcase fixtures: the client byte strings of the hard cases (hypotheses.md, Appendix A).
//
// Each builder follows the message's specification (named beside it). The ClientHello is the
// recorded one of proposal I18, captured once from OpenSSL with the settings of I24
// (tests/fixtures/tls/clienthello.hex, made by bench/cases/record_clienthello.cpp); where a case
// needs a handshake that completes, opcase runs a live OpenSSL client with the same settings
// instead (script.hpp, TlsPlan).
#pragma once

#include "detect.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace oneport::opcase
{

	using Bytes = std::vector<std::byte>;

	Bytes text(std::string_view s);
	Bytes cat(std::initializer_list<Bytes> parts);
	Bytes slice(const Bytes& b, std::size_t from, std::size_t to);

	/// "GET / HTTP/1.1", Host and Connection: close (RFC 9112 s3).
	Bytes http_get(std::string_view leading = "");
	/// The h2c exchange of WL1 as one byte string: the preface, an empty SETTINGS frame, one
	/// HEADERS frame with END_STREAM (GET / for oneport.test), and GOAWAY (RFC 9113 s3.4, s6).
	Bytes h2c_opening();
	/// An identification string (RFC 4253 s4.2), with an optional comment after a space.
	Bytes ssh_line(std::string_view comment = "");
	/// "EHLO" and "QUIT" lines of an SMTP client (RFC 5321).
	Bytes smtp_line(std::string_view line);

	/// The recorded ClientHello: one TLS record as OpenSSL 3.5.9 wrote it with the settings of I24,
	/// SNI oneport.test and ALPN http/1.1 (tests/fixtures/tls/clienthello.hex).
	Bytes recorded_client_hello();
	/// The text of that fixture, embedded at configure time ('#' comment lines and hex).
	std::string_view recorded_client_hello_hex() noexcept;
	/// A one-record ClientHello with its legacy_record_version minor byte set to `minor` (HC19).
	Bytes with_record_version(Bytes one_record, std::uint8_t minor);
	/// A one-record ClientHello re-fragmented into two records, the first holding `first`
	/// handshake bytes (HC20). `first_record` receives the first record's length, header included.
	Bytes fragment_client_hello(const Bytes& one_record, std::size_t first, std::size_t* first_record = nullptr);

	/// MQTT CONNECT at `level` (4: 3.1.1, s3.1; 5: 5.0, s3.1) with a Remaining Length of exactly
	/// `remaining_length`, minimally encoded (MQTT 5.0 s1.5.5). The payload is a client identifier
	/// of the length that makes it up; past the 65,535 bytes an identifier can hold, the rest is
	/// filler, since no well-formed CONNECT reaches a 4-byte Remaining Length.
	Bytes mqtt_connect(int level, std::uint32_t remaining_length);
	Bytes mqtt_disconnect();
	/// An MQTT 3.1 CONNECT, protocol name "MQIsdp", level 3 (out of scope, S8).
	Bytes mqtt_isdp();

	/// The PROXY source used by every PROXY case: 192.0.2.10 port 4711 (RFC 5737 TEST-NET-1).
	detect::ProxySource proxy_source();
	/// A v2 PROXY header over TCP/IPv4 from proxy_source() to 198.51.100.20:443, with TLVs whose
	/// bytes make the header `total` bytes long (at least 28; 28 means no TLV). TLVs are NOOP
	/// (type 0x04) of at most 65,535 value bytes each.
	Bytes proxy_v2(std::size_t total = 28);
	/// A v2 header with an ALPN and an AUTHORITY TLV.
	Bytes proxy_v2_alpn_authority();
	/// "PROXY TCP4 192.0.2.10 198.51.100.20 4711 443" and CRLF.
	Bytes proxy_v1();

}  // namespace oneport::opcase
