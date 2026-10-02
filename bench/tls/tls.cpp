#include "tls.hpp"

#include <cstring>
#include <stdexcept>

#include <openssl/err.h>
#include <openssl/pem.h>
#include <openssl/x509.h>

namespace oneport::tls
{

	namespace
	{

		[[noreturn]] void fail(const char* what) { throw std::runtime_error(std::string("oneport TLS: ") + what + ": " + take_errors()); }

		struct BioFree
		{
			void operator()(BIO* b) const noexcept { BIO_free(b); }
		};
		struct X509Free
		{
			void operator()(X509* x) const noexcept { X509_free(x); }
		};
		struct PkeyFree
		{
			void operator()(EVP_PKEY* k) const noexcept { EVP_PKEY_free(k); }
		};

		std::unique_ptr<X509, X509Free> read_cert()
		{
			const std::string_view pem = test_cert_pem();
			std::unique_ptr<BIO, BioFree> b(BIO_new_mem_buf(pem.data(), static_cast<int>(pem.size())));
			if (!b) fail("BIO_new_mem_buf");
			std::unique_ptr<X509, X509Free> x(PEM_read_bio_X509(b.get(), nullptr, nullptr, nullptr));
			if (!x) fail("the test certificate");
			return x;
		}

		/// The settings both sides share (I24).
		void common(SSL_CTX* ctx, const char* groups)
		{
			if (SSL_CTX_set_min_proto_version(ctx, TLS1_3_VERSION) != 1) fail("min version");
			if (SSL_CTX_set_max_proto_version(ctx, TLS1_3_VERSION) != 1) fail("max version");
			if (SSL_CTX_set_ciphersuites(ctx, kCipherSuites) != 1) fail("cipher suites");
			if (SSL_CTX_set1_groups_list(ctx, groups) != 1) fail("groups");
			if (SSL_CTX_set1_sigalgs_list(ctx, kSigalgs) != 1) fail("signature algorithms");
			SSL_CTX_set_session_cache_mode(ctx, SSL_SESS_CACHE_OFF);
			if (SSL_CTX_set_max_early_data(ctx, 0) != 1) fail("early data");
		}

		/// The first of the client's protocols that the server serves (http/1.1 or h2).
		int select_alpn(SSL*, const unsigned char** out, unsigned char* outlen, const unsigned char* in, unsigned int inlen, void*)
		{
			unsigned int i = 0;
			while (i < inlen)
			{
				const unsigned int n = in[i];
				if (n == 0 || i + 1 + n > inlen) break;
				const std::string_view p(reinterpret_cast<const char*>(in + i + 1), n);
				if (p == "http/1.1" || p == "h2")
				{
					*out = in + i + 1;
					*outlen = static_cast<unsigned char>(n);
					return SSL_TLSEXT_ERR_OK;
				}
				i += 1 + n;
			}
			return SSL_TLSEXT_ERR_ALERT_FATAL;  // no_application_protocol (RFC 7301 s3.2)
		}

		// ---- The server's BIO ----

		int bio_write_ex(BIO* b, const char* data, std::size_t len, std::size_t* written)
		{
			auto* io = static_cast<BioIo*>(BIO_get_data(b));
			BIO_clear_retry_flags(b);
			const auto* p = reinterpret_cast<const std::byte*>(data);
			io->out->insert(io->out->end(), p, p + len);
			*written = len;
			return 1;
		}

		int bio_read_ex(BIO* b, char* data, std::size_t len, std::size_t* readbytes)
		{
			auto* io = static_cast<BioIo*>(BIO_get_data(b));
			BIO_clear_retry_flags(b);
			const std::size_t left = io->in_len - io->used;
			if (left == 0)
			{
				BIO_set_retry_read(b);
				*readbytes = 0;
				return 0;
			}
			const std::size_t n = len < left ? len : left;
			std::memcpy(data, io->in + io->used, n);
			io->used += n;
			*readbytes = n;
			return 1;
		}

		long bio_ctrl(BIO*, int cmd, long, void*) { return cmd == BIO_CTRL_FLUSH ? 1 : 0; }

		int bio_create(BIO* b)
		{
			BIO_set_init(b, 1);
			return 1;
		}

		int bio_destroy(BIO*) { return 1; }

		BIO_METHOD* bio_method()
		{
			static BIO_METHOD* const m = [] {
				BIO_METHOD* x = BIO_meth_new(BIO_get_new_index() | BIO_TYPE_SOURCE_SINK, "oneport worker");
				if (x == nullptr || BIO_meth_set_write_ex(x, bio_write_ex) != 1 || BIO_meth_set_read_ex(x, bio_read_ex) != 1 ||
				    BIO_meth_set_ctrl(x, bio_ctrl) != 1 || BIO_meth_set_create(x, bio_create) != 1 || BIO_meth_set_destroy(x, bio_destroy) != 1)
				{
					fail("BIO_meth_new");
				}
				return x;
			}();
			return m;
		}

	}  // namespace

	Ctx server_ctx()
	{
		Ctx ctx(SSL_CTX_new(TLS_server_method()));
		if (!ctx) fail("SSL_CTX_new");
		common(ctx.get(), kGroups);
		if (SSL_CTX_set_num_tickets(ctx.get(), 0) != 1) fail("tickets");
		const auto cert = read_cert();
		if (SSL_CTX_use_certificate(ctx.get(), cert.get()) != 1) fail("use the certificate");
		const std::string_view pem = test_key_pem();
		std::unique_ptr<BIO, BioFree> b(BIO_new_mem_buf(pem.data(), static_cast<int>(pem.size())));
		if (!b) fail("BIO_new_mem_buf");
		std::unique_ptr<EVP_PKEY, PkeyFree> key(PEM_read_bio_PrivateKey(b.get(), nullptr, nullptr, nullptr));
		if (!key) fail("the test key");
		if (SSL_CTX_use_PrivateKey(ctx.get(), key.get()) != 1) fail("use the key");
		if (SSL_CTX_check_private_key(ctx.get()) != 1) fail("the key does not match the certificate");
		SSL_CTX_set_alpn_select_cb(ctx.get(), select_alpn, nullptr);
		return ctx;
	}

	Ctx client_ctx(const char* groups)
	{
		Ctx ctx(SSL_CTX_new(TLS_client_method()));
		if (!ctx) fail("SSL_CTX_new");
		common(ctx.get(), groups);
		const auto cert = read_cert();
		if (X509_STORE_add_cert(SSL_CTX_get_cert_store(ctx.get()), cert.get()) != 1) fail("trust the test certificate");
		SSL_CTX_set_verify(ctx.get(), SSL_VERIFY_PEER, nullptr);
		return ctx;
	}

	Alpn chosen(const SSL* ssl) noexcept
	{
		const unsigned char* p = nullptr;
		unsigned int n = 0;
		SSL_get0_alpn_selected(ssl, &p, &n);
		if (n == 2 && p[0] == 'h' && p[1] == '2') return Alpn::h2;
		return Alpn::http1;
	}

	std::vector<unsigned char> alpn_wire(std::string_view protocol)
	{
		std::vector<unsigned char> w;
		w.push_back(static_cast<unsigned char>(protocol.size()));
		w.insert(w.end(), protocol.begin(), protocol.end());
		return w;
	}

	BIO* new_bio(BioIo* io)
	{
		BIO* b = BIO_new(bio_method());
		if (b == nullptr) return nullptr;
		BIO_set_data(b, io);
		return b;
	}

	std::string take_errors()
	{
		std::string s;
		unsigned long e = 0;
		while ((e = ERR_get_error()) != 0)
		{
			char buf[256];
			ERR_error_string_n(e, buf, sizeof(buf));
			if (!s.empty()) s += "; ";
			s += buf;
		}
		return s.empty() ? "no OpenSSL error queued" : s;
	}

}  // namespace oneport::tls
