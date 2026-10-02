// The TLS settings of the server, the backend and the generators (hypotheses.md, section 2.1;
// design/proposal.md, I22 to I24), on the pinned OpenSSL 3.5 (bench/cmake/pins.cmake):
//   - TLS 1.3 only;
//   - cipher suite TLS_AES_128_GCM_SHA256, signature scheme ecdsa_secp256r1_sha256;
//   - key exchange group X25519 only;
//   - one ECDSA P-256 certificate from a fixed test key (tests/fixtures/tls);
//   - no session tickets (SSL_CTX_set_num_tickets(ctx, 0)), no session cache, no early data.
// ALPN: the server accepts "http/1.1" and "h2" and takes the first of the client's protocols that
// it serves (a design choice of M2a); a client that offers ALPN with neither gets the fatal
// alert no_application_protocol (RFC 7301 s3.2); a client that offers no ALPN gets HTTP/1.1.
// SNI selects nothing in-process: there is one certificate. Routing by SNI and ALPN is the relay's
// pass-through (proposal I17, I22), which parses the ClientHello itself.
//
// The server feeds OpenSSL through a BIO of its own (new_bio): the loop owns the socket on every
// backend (I22), so OpenSSL reads the bytes the worker received and writes into the worker's
// output, never the socket.
#pragma once

#include <cstddef>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <openssl/ssl.h>

namespace oneport::tls
{

	inline constexpr const char* kCipherSuites = "TLS_AES_128_GCM_SHA256";
	inline constexpr const char* kGroups = "X25519";
	inline constexpr const char* kSigalgs = "ecdsa_secp256r1_sha256";
	/// The name in the test certificate (CN and SAN), and the clients' SNI.
	inline constexpr std::string_view kServerName = "oneport.test";

	struct CtxFree
	{
		void operator()(SSL_CTX* c) const noexcept { SSL_CTX_free(c); }
	};
	using Ctx = std::unique_ptr<SSL_CTX, CtxFree>;

	/// The server's context: the settings above, the test certificate and key, the ALPN choice.
	/// Throws std::runtime_error with OpenSSL's reason.
	Ctx server_ctx();

	/// A client's context with the same settings, verifying the peer against the test
	/// certificate. `groups` replaces the frozen X25519 only in negative tests.
	Ctx client_ctx(const char* groups = kGroups);

	/// The application protocol the server chose by ALPN.
	enum class Alpn : unsigned char
	{
		http1,
		h2,
	};
	/// What ALPN chose on an established connection: HTTP/1.1 if the client offered none.
	Alpn chosen(const SSL* ssl) noexcept;

	/// The wire form of an ALPN list of one protocol, for SSL_set_alpn_protos.
	std::vector<unsigned char> alpn_wire(std::string_view protocol);

	/// The server's I/O through OpenSSL: reads take the bytes [in + used, in + in_len) and
	/// advance `used`; writes append to *out. One per worker; the worker points it at a
	/// connection's bytes before each OpenSSL call on that connection.
	struct BioIo
	{
		const std::byte* in = nullptr;
		std::size_t in_len = 0;
		std::size_t used = 0;
		std::vector<std::byte>* out = nullptr;
	};

	/// A BIO over `io`, for both directions of one SSL (SSL_set_bio(ssl, b, b)).
	BIO* new_bio(BioIo* io);

	/// OpenSSL's queued errors as one line, and the queue cleared.
	std::string take_errors();

	/// The test material (tests/fixtures/tls), embedded at configure time.
	std::string_view test_cert_pem() noexcept;
	std::string_view test_key_pem() noexcept;

}  // namespace oneport::tls
