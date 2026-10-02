// The handlers of I26 over sockets, on epoll, in one-port mode (both detection modes) and in
// dedicated mode: TLS with the frozen settings (I24) and ALPN http/1.1 or h2, h2c, MQTT, SSH with
// the banner timing of I28, SMTP, and the output path under backpressure. Functional and untimed:
// the only times checked are timer bounds and "nothing before the client spoke".
#include "test_support.hpp"

#if defined(__linux__) && defined(ONEPORT_HAVE_TLS)

#include "apps.hpp"
#include "cases.hpp"
#include "clienthello.hpp"
#include "harness.hpp"
#include "http1.hpp"
#include "script.hpp"
#include "tls.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <openssl/ssl.h>

namespace oneport::test
{

	namespace
	{

		using namespace std::chrono_literals;
		using opcase::Bytes;
		using opcase::Script;
		using opcase::text;

		const Bytes kGetKeepAlive = text("GET / HTTP/1.1\r\nHost: oneport.test\r\n\r\n");

		Bytes raw(std::initializer_list<unsigned> v)
		{
			Bytes b;
			for (const unsigned x : v) b.push_back(static_cast<std::byte>(x));
			return b;
		}

		std::size_t count(const Bytes& b, std::string_view needle)
		{
			const Bytes n = text(needle);
			std::size_t k = 0;
			for (auto it = b.begin(); (it = std::search(it, b.end(), n.begin(), n.end())) != b.end(); ++it) ++k;
			return k;
		}

		/// One server per mode of a test: one-port (replay or peek) or dedicated.
		struct Arm
		{
			std::string name;
			Mode mode;
			Detect detect;
		};
		const std::array<Arm, 3> kArms{{{"one-port replay", Mode::one_port, Detect::replay},
		                                {"one-port peek", Mode::one_port, Detect::peek},
		                                {"dedicated", Mode::dedicated, Detect::replay}}};

		std::uint16_t port_for(Running& srv, const Arm& a, detect::Proto p) { return a.mode == Mode::dedicated ? srv.port_of(p) : srv.port(); }

		opcase::Transcript run_and_wait(Running& srv, const Script& s, std::uint16_t port)
		{
			opcase::Transcript t = opcase::run(s, port);
			std::vector<server::DetectionReport> reps;
			srv.collector.wait_close(t.local_port, 10000ms, reps);
			return t;
		}

		// ---- TLS ----

		/// The frozen settings in the server's context (I24).
		Result tls_context()
		{
			const tls::Ctx ctx = tls::server_ctx();
			SSL_CTX* c = ctx.get();
			CHECK(SSL_CTX_get_min_proto_version(c) == TLS1_3_VERSION && SSL_CTX_get_max_proto_version(c) == TLS1_3_VERSION, "TLS 1.3 only");
			CHECK(SSL_CTX_get_num_tickets(c) == 0, "session tickets");
			CHECK(SSL_CTX_get_session_cache_mode(c) == SSL_SESS_CACHE_OFF, "session cache");
			CHECK(SSL_CTX_get_max_early_data(c) == 0, "early data");
			SSL* s = SSL_new(c);
			CHECK(s != nullptr, "SSL_new");
			// The suites the version limits leave for negotiation (TLS 1.2's list is never used).
			STACK_OF(SSL_CIPHER)* ciphers = SSL_get1_supported_ciphers(s);
			const int n = ciphers != nullptr ? sk_SSL_CIPHER_num(ciphers) : 0;
			const std::string first = n > 0 ? SSL_CIPHER_get_name(sk_SSL_CIPHER_value(ciphers, 0)) : "";
			sk_SSL_CIPHER_free(ciphers);
			SSL_free(s);
			CHECK(n == 1 && first == "TLS_AES_128_GCM_SHA256", n << " suites, the first " << first);
			return std::nullopt;
		}

		/// opcase's live client and the recording are the same settings by construction: the
		/// ClientHello the live client wrote has the recording's length and bytes everywhere but
		/// in the three fields each connection draws afresh (random, legacy_session_id, the X25519
		/// key share).
		Result clienthello_live()
		{
			ServerArgs args;
			Running srv(args);
			opcase::TlsPlan plan;
			plan.requests = {opcase::http_get()};
			const auto t = run_and_wait(srv, Script{}.tls(plan), srv.port());
			CHECK(t.tls && t.tls->handshake, "no handshake");
			const Bytes& live = t.tls->client_hello;
			const Bytes rec = opcase::recorded_client_hello();
			CHECK(live.size() == rec.size(), "the live ClientHello has " << live.size() << " bytes, the recording " << rec.size());
			std::array<std::byte, detect::kBCh> a{};
			std::array<std::byte, detect::kBCh> b{};
			const auto ra = clienthello::reassemble(live, a);
			const auto rb = clienthello::reassemble(rec, b);
			CHECK(ra.verdict == clienthello::Verdict::yes && rb.verdict == clienthello::Verdict::yes && ra.msg_len == rb.msg_len, "both reassemble");
			const auto ha = clienthello::parse(std::span<const std::byte>(a.data(), ra.msg_len));
			const auto hb = clienthello::parse(std::span<const std::byte>(b.data(), rb.msg_len));
			CHECK(ha.ok && hb.ok, "both parse");
			std::vector<bool> fresh(ra.msg_len, false);
			for (const clienthello::Field f : {ha.random, ha.session_id, ha.x25519})
			{
				for (std::uint32_t i = 0; i < f.len; ++i) fresh[f.off + i] = true;
			}
			CHECK(ha.random.off == hb.random.off && ha.session_id.off == hb.session_id.off && ha.session_id.len == hb.session_id.len &&
			          ha.x25519.off == hb.x25519.off && ha.x25519.len == hb.x25519.len,
			      "the fields lie at other places");
			std::size_t same_fresh = 0;
			for (std::uint32_t i = 0; i < ra.msg_len; ++i)
			{
				if (fresh[i])
				{
					same_fresh += a[i] == b[i] ? 1 : 0;
					continue;
				}
				CHECK(a[i] == b[i], "the live ClientHello differs from the recording at handshake byte " << i);
			}
			CHECK(same_fresh < 96 / 2, "the random, session id and key share look recorded, not drawn");
			CHECK(std::equal(live.begin(), live.begin() + 5, rec.begin()), "the record headers differ");
			return srv.stop_and_check();
		}

		/// A full handshake and three requests on one connection (WL3's keep-alive form, then
		/// WL1's close), in each mode; the decrypted transcripts agree.
		Result tls_exchange()
		{
			std::vector<Bytes> plains;
			for (const Arm& a : kArms)
			{
				ServerArgs args;
				args.mode = a.mode;
				args.detect = a.detect;
				Running srv(args);
				opcase::TlsPlan plan;
				plan.requests = {kGetKeepAlive, kGetKeepAlive, opcase::http_get()};
				const auto t = run_and_wait(srv, Script{}.tls(plan), port_for(srv, a, detect::Proto::tls));
				CHECK(t.tls && t.tls->handshake, a.name << ": no handshake: " << (t.tls ? t.tls->error : "no TLS result"));
				const opcase::TlsResult& r = *t.tls;
				CHECK(r.version == "TLSv1.3" && r.cipher == "TLS_AES_128_GCM_SHA256" && r.group == "x25519", a.name << ": " << r.version << " " << r.cipher << " " << r.group);
				CHECK(r.sigalg == "ecdsa_secp256r1_sha256" && r.verified, a.name << ": signature " << r.sigalg << ", verified " << r.verified);
				CHECK(r.alpn == "http/1.1", a.name << ": ALPN " << r.alpn);
				CHECK(!r.resumable, a.name << ": a session ticket arrived");
				CHECK(r.plain == opcase::cat({text(http1::kResponse200), text(http1::kResponse200), text(http1::kResponse200)}), a.name << ": " << r.plain.size() << " plaintext bytes");
				CHECK(r.close_notify && t.eof, a.name << ": the server closes with close_notify after Connection: close");
				plains.push_back(r.plain);
				if (auto bad = srv.stop_and_check()) return a.name + ": " + *bad;
			}
			return std::nullopt;
		}

		/// ALPN h2: the h2 handler behind TLS, the same exchange in each mode.
		Result tls_h2()
		{
			std::vector<Bytes> plains;
			for (const Arm& a : kArms)
			{
				ServerArgs args;
				args.mode = a.mode;
				args.detect = a.detect;
				Running srv(args);
				opcase::TlsPlan plan;
				plan.alpn = "h2";
				plan.requests = {opcase::h2c_opening()};
				const auto t = run_and_wait(srv, Script{}.tls(plan), port_for(srv, a, detect::Proto::tls));
				CHECK(t.tls && t.tls->handshake && t.tls->alpn == "h2", a.name << ": no h2 handshake");
				CHECK(count(t.tls->plain, "Hello, World!") == 1, a.name << ": no h2 response body");
				CHECK(t.eof, a.name << ": the server closes after the client's GOAWAY");
				plains.push_back(t.tls->plain);
				if (auto bad = srv.stop_and_check()) return a.name + ": " + *bad;
			}
			CHECK(plains[0] == plains[1] && plains[1] == plains[2], "the decrypted h2 transcripts differ between the modes");
			return std::nullopt;
		}

		/// What the frozen settings refuse: a client without X25519; ALPN with neither protocol.
		/// And a client without ALPN gets HTTP/1.1.
		Result tls_refusals()
		{
			for (const Arm& a : kArms)
			{
				ServerArgs args;
				args.mode = a.mode;
				args.detect = a.detect;
				Running srv(args);
				const std::uint16_t port = port_for(srv, a, detect::Proto::tls);
				opcase::TlsPlan p256;
				p256.groups = "P-256";
				p256.requests = {opcase::http_get()};
				auto t = run_and_wait(srv, Script{}.tls(p256), port);
				CHECK(t.tls && !t.tls->handshake && t.tls->plain.empty(), a.name << ": a P-256-only client completed a handshake");
				opcase::TlsPlan spdy;
				spdy.alpn = "spdy/3";
				spdy.requests = {opcase::http_get()};
				t = run_and_wait(srv, Script{}.tls(spdy), port);
				CHECK(t.tls && !t.tls->handshake, a.name << ": ALPN without http/1.1 or h2 completed a handshake");
				opcase::TlsPlan none;
				none.alpn = "";
				none.requests = {opcase::http_get()};
				t = run_and_wait(srv, Script{}.tls(none), port);
				CHECK(t.tls && t.tls->handshake && t.tls->alpn.empty() && t.tls->plain == text(http1::kResponse200), a.name << ": no ALPN is not served as HTTP/1.1");
				if (auto bad = srv.stop_and_check()) return a.name + ": " + *bad;
			}
			return std::nullopt;
		}

		// ---- h2c ----

		/// Two streams on one connection, in each mode; the transcripts agree byte for byte.
		Result h2c_streams()
		{
			// The opening's HEADERS frame (fixtures.cpp), again on stream 3, before the GOAWAY.
			const Bytes one = opcase::h2c_opening();
			const std::size_t goaway = one.size() - 17;
			const std::size_t headers = 24 + 9;
			Bytes two(one.begin(), one.begin() + static_cast<std::ptrdiff_t>(goaway));
			Bytes h3(one.begin() + static_cast<std::ptrdiff_t>(headers), one.begin() + static_cast<std::ptrdiff_t>(goaway));
			h3[8] = std::byte{3};  // the stream identifier's last byte
			two.insert(two.end(), h3.begin(), h3.end());
			two.insert(two.end(), one.begin() + static_cast<std::ptrdiff_t>(goaway), one.end());
			std::vector<Bytes> got;
			for (const Arm& a : kArms)
			{
				ServerArgs args;
				args.mode = a.mode;
				args.detect = a.detect;
				Running srv(args);
				const auto t = run_and_wait(srv, Script{}.write(two).shutdown_write(), port_for(srv, a, detect::Proto::h2c));
				CHECK(count(t.received, "Hello, World!") == 2, a.name << ": " << count(t.received, "Hello, World!") << " response bodies for two streams");
				CHECK(t.eof, a.name << ": not closed");
				got.push_back(t.received);
				if (auto bad = srv.stop_and_check()) return a.name + ": " + *bad;
			}
			CHECK(got[0] == got[1] && got[1] == got[2], "the h2c transcripts differ between the modes");
			return std::nullopt;
		}

		// ---- MQTT ----

		Result mqtt_session()
		{
			for (const Arm& a : kArms)
			{
				ServerArgs args;
				args.mode = a.mode;
				args.detect = a.detect;
				Running srv(args);
				const std::uint16_t port = port_for(srv, a, detect::Proto::mqtt);
				auto t = run_and_wait(srv, Script{}.write(opcase::mqtt_connect(4, 12)).gap(20ms).write(raw({0xC0, 0x00})).gap(20ms).write(raw({0xC0, 0x00, 0xE0, 0x00})), port);
				CHECK(t.received == raw({0x20, 0x02, 0x00, 0x00, 0xD0, 0x00, 0xD0, 0x00}) && t.eof, a.name << ": 3.1.1: " << t.received.size() << " bytes");
				t = run_and_wait(srv, Script{}.write(opcase::cat({opcase::mqtt_connect(5, 13), opcase::mqtt_disconnect()})), port);
				CHECK(t.received == raw({0x20, 0x03, 0x00, 0x00, 0x00}) && t.eof, a.name << ": 5.0: " << t.received.size() << " bytes");
				t = run_and_wait(srv, Script{}.write(opcase::cat({opcase::mqtt_connect(4, 12), raw({0x30, 0x02, 0x00, 0x00})})), port);
				CHECK(t.received == raw({0x20, 0x02, 0x00, 0x00}) && (t.eof || t.reset), a.name << ": PUBLISH is not served: closed after CONNACK");
				if (auto bad = srv.stop_and_check()) return a.name + ": " + *bad;
			}
			return std::nullopt;
		}

		// ---- SSH: the banner's timing (I28) ----

		Result ssh_banner_timing()
		{
			// Dedicated: the line at accept, before the client sends anything.
			{
				ServerArgs args;
				args.mode = Mode::dedicated;
				Running srv(args);
				const auto t = run_and_wait(srv, Script{}.await_line().write(opcase::ssh_line()), srv.port_of(detect::Proto::ssh));
				CHECK(t.received == text(apps::kSshBanner) && t.eof, "dedicated: the line is not sent at accept");
				CHECK(t.first_byte && t.write_times.size() == 1 && *t.first_byte <= t.write_times[0], "dedicated: the line came after the client's");
				if (auto bad = srv.stop_and_check()) return "dedicated: " + *bad;
			}
			// One-port: nothing until the client's "SSH-" decides the class; then the line.
			for (const Detect d : {Detect::replay, Detect::peek})
			{
				ServerArgs args;
				args.detect = d;
				Running srv(args);
				const auto t = run_and_wait(srv, Script{}.gap(100ms).write(opcase::ssh_line()), srv.port());
				CHECK(t.received == text(apps::kSshBanner) && t.eof, "one-port: no line after the client's");
				CHECK(t.first_byte && *t.first_byte >= t.write_times.at(0), "one-port: the server spoke before the client's SSH-");
				if (auto bad = srv.stop_and_check()) return "one-port: " + *bad;
			}
			// The SSH fallback: a silent client gets the line at T_fb.
			{
				ServerArgs args;
				args.fallback = Fallback::ssh;
				args.t_fb = args.t_dec = 200ms;
				Running srv(args);
				const auto t = run_and_wait(srv, Script{}.await_line().write(opcase::ssh_line()), srv.port());
				CHECK(t.received == text(apps::kSshBanner) && t.eof, "fallback: no line");
				CHECK(t.first_byte && *t.first_byte - t.before_connect >= args.t_fb, "fallback: the line came before T_fb");
				if (auto bad = srv.stop_and_check()) return "fallback: " + *bad;
			}
			return std::nullopt;
		}

		// ---- SMTP ----

		Result smtp_dialogue()
		{
			const std::string want = std::string(apps::kSmtpGreeting) + std::string(apps::kSmtpEhlo) + std::string(apps::kSmtpUnknown) + std::string(apps::kSmtpBye);
			for (const bool fallback : {false, true})
			{
				ServerArgs args;
				args.mode = fallback ? Mode::one_port : Mode::dedicated;
				if (fallback)
				{
					args.fallback = Fallback::smtp;
					args.t_fb = args.t_dec = 200ms;
				}
				Running srv(args);
				const std::uint16_t port = fallback ? srv.port() : srv.port_of(detect::Proto::smtp);
				const auto t = run_and_wait(srv, Script{}.await_line().write(text("EHLO c.test\r\n")).gap(20ms).write(text("NOOP\r\nQUIT\r\n")), port);
				CHECK(t.received == text(want) && t.eof, (fallback ? "fallback" : "dedicated") << ": " << t.received.size() << " bytes, '" << opcase::first_line(t.received) << "'");
				if (auto bad = srv.stop_and_check()) return *bad;
			}
			return std::nullopt;
		}

		// ---- Output under backpressure ----

		/// A client that pipelines many requests over a small receive buffer and reads only after
		/// a pause: the server's sends meet a full socket, the rest waits in the connection's
		/// queue for EPOLLOUT, its reads wait for the flush, and every response arrives in order.
		/// Plain: 200,000 requests, so the responses (15.6 MB) exceed L's largest send buffer
		/// (tcp_wmem 4 MB) and must wait. Over TLS: 1,000, which the single-threaded client can
		/// write before it reads.
		Result output_backpressure()
		{
			for (const bool over_tls : {false, true})
			{
				const int kRequests = over_tls ? 1000 : 200000;
				for (const Arm& a : kArms)
				{
					ServerArgs args;
					args.mode = a.mode;
					args.detect = a.detect;
					Running srv(args);
					std::size_t got = 0;
					if (!over_tls)
					{
						const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
						const int small = 4096;
						::setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &small, sizeof(small));
						sockaddr_in addr{};
						addr.sin_family = AF_INET;
						addr.sin_port = htons(port_for(srv, a, detect::Proto::http1));
						addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
						CHECK(::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
						std::atomic<bool> written{false};
						std::thread writer([fd, kRequests, &written] {
							Bytes all;
							for (int i = 0; i < kRequests - 1; ++i) all.insert(all.end(), kGetKeepAlive.begin(), kGetKeepAlive.end());
							const Bytes last = opcase::http_get();
							all.insert(all.end(), last.begin(), last.end());
							std::size_t done = 0;
							while (done < all.size())
							{
								const ssize_t w = ::send(fd, all.data() + done, all.size() - done, MSG_NOSIGNAL);
								if (w <= 0) break;
								done += static_cast<std::size_t>(w);
							}
							written.store(true);
						});
						// Read only once every request is written (or after 10 s, if the server's
						// receive buffer cannot hold the rest): the responses meanwhile fill the socket.
						for (int i = 0; i < 1000 && !written.load(); ++i) std::this_thread::sleep_for(10ms);
						Bytes in;
						std::array<std::byte, 65536> buf{};
						for (;;)
						{
							pollfd p{fd, POLLIN, 0};
							if (::poll(&p, 1, 10000) <= 0) break;
							const ssize_t n = ::recv(fd, buf.data(), buf.size(), 0);
							if (n <= 0) break;
							in.insert(in.end(), buf.begin(), buf.begin() + n);
						}
						writer.join();
						::close(fd);
						got = count(in, "Hello, World!");
						CHECK(in.size() == static_cast<std::size_t>(kRequests) * http1::kResponse200.size(), a.name << ": " << in.size() << " bytes for " << kRequests << " responses");
					}
					else
					{
						opcase::TlsPlan plan;
						for (int i = 0; i < kRequests - 1; ++i) plan.requests.push_back(kGetKeepAlive);
						plan.requests.push_back(opcase::http_get());
						const auto t = run_and_wait(srv, Script{}.tls(plan), port_for(srv, a, detect::Proto::tls));
						CHECK(t.tls && t.tls->handshake, a.name << ": TLS: no handshake");
						got = count(t.tls->plain, "Hello, World!");
					}
					CHECK(got == static_cast<std::size_t>(kRequests), a.name << (over_tls ? " over TLS" : "") << ": " << got << " of " << kRequests << " responses");
					if (auto bad = srv.stop_and_check()) return a.name + ": " + *bad;
					const server::Counters c = srv.server->totals();
					CHECK(over_tls || c.epoll_ctl_calls > 2, a.name << ": the server never waited for EPOLLOUT");
				}
			}
			return std::nullopt;
		}

	}  // namespace

	void register_handler_tests(Registry& r)
	{
		r["handlers.tls_context"] = tls_context;
		r["handlers.clienthello_live"] = clienthello_live;
		r["handlers.tls_exchange"] = tls_exchange;
		r["handlers.tls_h2"] = tls_h2;
		r["handlers.tls_refusals"] = tls_refusals;
		r["handlers.h2c_streams"] = h2c_streams;
		r["handlers.mqtt_session"] = mqtt_session;
		r["handlers.ssh_banner_timing"] = ssh_banner_timing;
		r["handlers.smtp_dialogue"] = smtp_dialogue;
		r["handlers.output_backpressure"] = output_backpressure;
	}

}  // namespace oneport::test

#else

namespace oneport::test
{
	void register_handler_tests(Registry&) {}
}  // namespace oneport::test

#endif
