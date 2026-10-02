// The h2 handler (design/proposal.md I26; hypotheses.md, section 2.1): nghttp2's server session
// through its memory functions, the same build and settings in both modes and under TLS with
// ALPN h2. Every request stream that ends gets 200 with Content-Type text/plain,
// Content-Length 13 and the body "Hello, World!", the HTTP/1.1 handler's response.
//
// Design choices of M2a: the server's SETTINGS carries one setting, MAX_CONCURRENT_STREAMS 100
// (RFC 9113 s6.5.2 advises no less than 100); it is queued when the session is made and leaves
// with the first output, which follows the first input, so no mode sends a byte before the
// client's preface arrives. nghttp2's HTTP messaging checks stay on, so a request without
// :method, :scheme, :path, or :authority and Host, is reset by nghttp2, in both modes.
#pragma once

#include <cstddef>
#include <span>
#include <vector>

struct nghttp2_session;

namespace oneport::server::h2
{

	/// A server session with its SETTINGS queued, or nullptr if nghttp2 cannot make one.
	nghttp2_session* open() noexcept;

	void close(nghttp2_session* s) noexcept;

	/// Feeds received bytes. False on a connection error: the session must end, after drain().
	bool feed(nghttp2_session* s, std::span<const std::byte> bytes) noexcept;

	/// Appends every frame the session has to send. False on an error.
	bool drain(nghttp2_session* s, std::vector<std::byte>& out);

	/// True when the session neither wants to read nor to write (after a GOAWAY, for example).
	bool finished(nghttp2_session* s) noexcept;

}  // namespace oneport::server::h2
