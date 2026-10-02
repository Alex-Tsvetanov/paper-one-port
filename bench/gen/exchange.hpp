// The bytes of opgen's exchanges, per protocol and load (hypotheses.md, section 3: WL1's table and
// WL3), and the checks of the server's responses. h2 frames carry static-table header fields only
// (design/proposal.md, I30); MQTT is 3.1.1 with an empty client identifier, as the hard cases'
// CONNECT (opcase); the TLS stub exchange is the recorded ClientHello (I18).
#pragma once

#include "fixtures.hpp"

#include <cstddef>
#include <cstdint>
#include <string_view>

namespace oneport::opgen::detail
{

	using Bytes = opcase::Bytes;

	/// The 13-byte body of every 200 (section 2.1).
	inline constexpr std::string_view kBody = "Hello, World!";

	/// GET / with Host oneport.test and Connection: close (opcase), or keep-alive.
	const Bytes& http_close();
	const Bytes& http_keep();

	/// HEADERS on `stream`, END_STREAM and END_HEADERS: GET http://oneport.test/ in static-table
	/// fields, :authority as a literal without indexing.
	Bytes h2_headers(std::uint32_t stream);
	/// The preface, an empty SETTINGS frame and HEADERS on stream 1 (WL1's first write).
	const Bytes& h2_opening();
	/// GOAWAY, last stream 0, NO_ERROR.
	const Bytes& h2_goaway();
	Bytes h2_settings_ack();
	Bytes h2_window_update(std::uint32_t inc);

	const Bytes& mqtt_connect();
	const Bytes& mqtt_disconnect();
	extern const Bytes kMqttConnack;
	extern const Bytes kPingreq;
	extern const Bytes kPingresp;

	const Bytes& ssh_line();
	const Bytes& stub_hello();

	bool starts_with(const std::byte* p, std::size_t n, std::string_view s) noexcept;
	/// The position just after the empty line that ends the header (CR LF CR LF) in [p, p + n),
	/// or 0.
	std::size_t header_end(const std::byte* p, std::size_t n) noexcept;
	/// A response of 200 with Content-Length: its whole length once complete, 0 while incomplete,
	/// or -1 if it is not a 200 with the 13-byte body.
	long http_response(const std::byte* p, std::size_t n) noexcept;

}  // namespace oneport::opgen::detail
