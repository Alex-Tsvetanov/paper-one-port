// record_clienthello: prints the ClientHello that an OpenSSL client writes with the settings of
// bench/tls (hypotheses.md, section 2.1; proposal I18, I24), SNI oneport.test and ALPN http/1.1,
// as the text of tests/fixtures/tls/clienthello.hex: '#' comment lines, then the record in hex.
//
// The client is OpenSSL's own: SSL_do_handshake on a fresh client SSL writes its first flight,
// one TLS record holding the ClientHello, into a memory BIO, and this program prints those bytes.
// No server and no socket take part. Run once on L with the pinned OpenSSL (release flavour);
// opcase replays the bytes wherever a case needs a ClientHello and no handshake (proposal I18).
#include "tls.hpp"

#include <cstdio>
#include <ctime>
#include <stdexcept>
#include <string>

#include <openssl/bio.h>
#include <openssl/crypto.h>
#include <openssl/ssl.h>

int main()
{
	try
	{
		const oneport::tls::Ctx ctx = oneport::tls::client_ctx();
		SSL* ssl = SSL_new(ctx.get());
		BIO* in = BIO_new(BIO_s_mem());
		BIO* out = BIO_new(BIO_s_mem());
		if (ssl == nullptr || in == nullptr || out == nullptr) throw std::runtime_error("SSL_new or BIO_new");
		SSL_set_bio(ssl, in, out);
		SSL_set_connect_state(ssl);
		const std::string name(oneport::tls::kServerName);
		const auto alpn = oneport::tls::alpn_wire("http/1.1");
		if (SSL_set_tlsext_host_name(ssl, name.c_str()) != 1 || SSL_set_alpn_protos(ssl, alpn.data(), static_cast<unsigned>(alpn.size())) != 0)
		{
			throw std::runtime_error("SNI or ALPN");
		}
		const int r = SSL_do_handshake(ssl);
		if (r == 1 || SSL_get_error(ssl, r) != SSL_ERROR_WANT_READ) throw std::runtime_error("the client did not stop at its first flight");
		char* data = nullptr;
		const long n = BIO_get_mem_data(out, &data);
		if (n < 5) throw std::runtime_error("no ClientHello record");
		const std::time_t now = std::time(nullptr);
		char date[32];
		std::strftime(date, sizeof(date), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&now));
		std::printf("# The recorded ClientHello of design/proposal.md I18: one TLS record, as an OpenSSL client\n");
		std::printf("# wrote it with the settings of I24 (bench/tls: TLS 1.3 only, TLS_AES_128_GCM_SHA256,\n");
		std::printf("# ecdsa_secp256r1_sha256, X25519 only), SNI %s and ALPN http/1.1.\n", name.c_str());
		std::printf("# Made by bench/cases/record_clienthello.cpp, run on L at %s, linked against\n", date);
		std::printf("# %s (bench/cmake/pins.cmake, release flavour).\n", OpenSSL_version(OPENSSL_VERSION));
		std::printf("# Record bytes: %ld; record length field (the ClientHello message with its 4-byte header,\n", n);
		std::printf("# the length l of hypotheses.md WL7): %ld.\n", n - 5);
		std::printf("# TEST MATERIAL: its random, session id and X25519 key share were drawn once and are public.\n");
		for (long i = 0; i < n; ++i)
		{
			std::printf("%02x", static_cast<unsigned>(static_cast<unsigned char>(data[i])));
			std::printf((i + 1) % 32 == 0 || i + 1 == n ? "\n" : "");
		}
		SSL_free(ssl);
		return 0;
	}
	catch (const std::exception& e)
	{
		std::fprintf(stderr, "record_clienthello: %s: %s\n", e.what(), oneport::tls::take_errors().c_str());
		return 1;
	}
}
