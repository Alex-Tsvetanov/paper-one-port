// Relay dispatch, pass-through and stub mode (design/proposal.md I17, I18; hypotheses.md, section
// 2.1, "Dispatch" and "Stub mode"), on each Linux backend (the suffix of each test's name):
//   - relay.exchanges.<copy>.<mode>: every protocol through the front to a dedicated backend, each
//     transcript equal to the backend's own; a 2 MB upload, output that blocks both ways, a reset,
//     a refused backend; the counters of I29 under the M2b rule (the user-space relay copies
//     nothing in user space; splice moves its bytes inside the kernel);
//   - relay.pass_through.<mode>: TLS routed by the ClientHello's SNI and ALPN to a stub backend,
//     ClientHellos larger than the receive buffer and than B_CH, and the ones with no route;
//   - relay.stub: stub mode's ports, the TLS port reading one record;
//   - relay.matrix: the front's flag combinations;
//   - relay.binary: the binary as a backend process and a front process.
// Functional and untimed: the only times checked are the fallback's lower bound.
#include "test_support.hpp"

#if defined(__linux__) && defined(ONEPORT_HAVE_TLS)

#include "apps.hpp"
#include "cases.hpp"
#include "harness.hpp"
#include "http1.hpp"
#include "script.hpp"
#include "tls.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cstring>
#include <spawn.h>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

namespace oneport::test
{

	namespace
	{

		using namespace std::chrono_literals;
		using opcase::Bytes;
		using opcase::Script;
		using opcase::text;

		const Bytes kGetKeepAlive = text("GET / HTTP/1.1\r\nHost: oneport.test\r\n\r\n");

		std::size_t be16(const Bytes& b, std::size_t i) { return (std::to_integer<std::size_t>(b[i]) << 8) | std::to_integer<std::size_t>(b[i + 1]); }

		/// The recorded ClientHello's handshake message (its one record without the header).
		Bytes hello_message() { return opcase::slice(opcase::recorded_client_hello(), 5, opcase::recorded_client_hello().size()); }

		/// The offset of a ClientHello message's extensions length.
		std::size_t extensions_at(const Bytes& m)
		{
			std::size_t p = 4 + 2 + 32;
			p += 1 + std::to_integer<std::size_t>(m[p]);
			p += 2 + be16(m, p);
			p += 1 + std::to_integer<std::size_t>(m[p]);
			return p;
		}

		void put16(Bytes& b, std::size_t at, std::size_t v)
		{
			b[at] = static_cast<std::byte>((v >> 8) & 0xFF);
			b[at + 1] = static_cast<std::byte>(v & 0xFF);
		}

		/// The recorded message with a padding extension (RFC 7685, type 21) appended, so that the
		/// message is `total` bytes long, its 4-byte header included.
		Bytes padded_message(std::size_t total)
		{
			Bytes m = hello_message();
			const std::size_t add = total - m.size();
			const std::size_t pad = add - 4;
			const std::size_t ext = extensions_at(m);
			m.push_back(std::byte{0x00});
			m.push_back(std::byte{0x15});
			m.push_back(static_cast<std::byte>((pad >> 8) & 0xFF));
			m.push_back(static_cast<std::byte>(pad & 0xFF));
			m.insert(m.end(), pad, std::byte{0});
			put16(m, ext, be16(m, ext) + add);
			const std::size_t body = m.size() - 4;
			m[1] = static_cast<std::byte>((body >> 16) & 0xFF);
			m[2] = static_cast<std::byte>((body >> 8) & 0xFF);
			m[3] = static_cast<std::byte>(body & 0xFF);
			return m;
		}

		/// A handshake message in TLS records of the given sizes (the last takes the rest).
		Bytes as_records(const Bytes& m, std::vector<std::size_t> sizes)
		{
			Bytes out;
			std::size_t from = 0;
			sizes.push_back(m.size());
			for (std::size_t want : sizes)
			{
				const std::size_t n = std::min(want, m.size() - from);
				if (n == 0) break;
				out.push_back(std::byte{0x16});
				out.push_back(std::byte{0x03});
				out.push_back(std::byte{0x01});
				out.push_back(static_cast<std::byte>((n >> 8) & 0xFF));
				out.push_back(static_cast<std::byte>(n & 0xFF));
				out.insert(out.end(), m.begin() + static_cast<std::ptrdiff_t>(from), m.begin() + static_cast<std::ptrdiff_t>(from + n));
				from += n;
			}
			return out;
		}

		/// `b` with every `from` replaced by `to` (of the same length).
		Bytes replaced(Bytes b, std::string_view from, std::string_view to)
		{
			const Bytes f = text(from);
			const Bytes t = text(to);
			for (auto it = std::search(b.begin(), b.end(), f.begin(), f.end()); it != b.end(); it = std::search(it, b.end(), f.begin(), f.end()))
			{
				std::copy(t.begin(), t.end(), it);
			}
			return b;
		}

		/// A server in dedicated or stub mode, and a one-port front relaying to it.
		struct Relayed
		{
			Running backend;
			Running front;
			Relayed(Mode backend_mode, ServerArgs f) : backend(backend_args(backend_mode)), front(with_backend(f, backend.port(0))) {}

			static ServerArgs backend_args(Mode m)
			{
				ServerArgs b;
				b.mode = m;
				return b;
			}
			static ServerArgs with_backend(ServerArgs f, std::uint16_t port)
			{
				f.mode = Mode::one_port;
				f.dispatch = Dispatch::relay;
				f.relay_port = port;
				return f;
			}

			/// Runs `s` against the front; returns the transcript and the route reports.
			opcase::Transcript run(const Script& s, std::vector<server::RelayReport>& relays)
			{
				opcase::Transcript t = opcase::run(s, front.port());
				std::vector<server::DetectionReport> reps;
				front.collector.wait_close(t.local_port, 10000ms, reps, &relays);
				return t;
			}

			opcase::Transcript direct(const Script& s, detect::Proto p)
			{
				opcase::Transcript t = opcase::run(s, backend.port_of(p));
				std::vector<server::DetectionReport> reps;
				backend.collector.wait_close(t.local_port, 10000ms, reps);
				return t;
			}

			Result stop()
			{
				if (auto bad = front.stop_and_check()) return "front: " + *bad;
				if (auto bad = backend.stop_and_check()) return "backend: " + *bad;
				return std::nullopt;
			}
		};

		Result one_route(const std::vector<server::RelayReport>& relays, server::Route route, std::uint16_t port, const std::string& what)
		{
			CHECK(relays.size() == 1, what << ": " << relays.size() << " route reports");
			CHECK(relays[0].route == route, what << ": routed " << server::name(relays[0].route) << ", expected " << server::name(route));
			if (route != server::Route::rejected) CHECK(relays[0].backend_port == port, what << ": to port " << relays[0].backend_port << ", expected " << port);
			return std::nullopt;
		}

		/// A loopback client with a small receive buffer that writes `n` keep-alive requests and
		/// then one with Connection: close, all before it reads; returns the bytes received.
		std::size_t pipelined(std::uint16_t port, std::size_t n)
		{
			const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			const int small = 4096;
			::setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &small, sizeof(small));
			sockaddr_in a{};
			a.sin_family = AF_INET;
			a.sin_port = htons(port);
			a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			if (::connect(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a)) != 0)
			{
				::close(fd);
				return 0;
			}
			std::thread writer([fd, n] {
				Bytes all;
				for (std::size_t i = 0; i < n; ++i) all.insert(all.end(), kGetKeepAlive.begin(), kGetKeepAlive.end());
				const Bytes last = opcase::http_get();
				all.insert(all.end(), last.begin(), last.end());
				std::size_t done = 0;
				while (done < all.size())
				{
					const ssize_t w = ::send(fd, all.data() + done, all.size() - done, MSG_NOSIGNAL);
					if (w <= 0) break;
					done += static_cast<std::size_t>(w);
				}
			});
			std::this_thread::sleep_for(200ms);  // let the output back up while nothing is read
			std::size_t got = 0;
			std::array<char, 65536> buf{};
			for (;;)
			{
				pollfd p{fd, POLLIN, 0};
				if (::poll(&p, 1, 10000) <= 0) break;
				const ssize_t k = ::recv(fd, buf.data(), buf.size(), 0);
				if (k <= 0) break;
				got += static_cast<std::size_t>(k);
			}
			writer.join();
			::close(fd);
			return got;
		}

		// ---- relay.exchanges ----

		Result exchanges(RelayCopy copy, Detect detect)
		{
			ServerArgs f;
			f.relay_copy = copy;
			f.detect = detect;
			Relayed r(Mode::dedicated, f);
			struct Case
			{
				std::string name;
				Script script;
				detect::Proto proto;
				bool tls;
			};
			opcase::TlsPlan tls_plan;
			tls_plan.requests = {kGetKeepAlive, opcase::http_get()};
			opcase::TlsPlan no_alpn;
			no_alpn.alpn = "";
			no_alpn.requests = {opcase::http_get()};
			opcase::TlsPlan h2;
			h2.alpn = "h2";
			h2.requests = {opcase::h2c_opening()};
			const std::vector<Case> cases{
				{"HTTP/1.1", Script{}.write(opcase::http_get()), detect::Proto::http1, false},
				{"HTTP/1.1 keep-alive", Script{}.write(kGetKeepAlive).gap(20ms).write(opcase::http_get()), detect::Proto::http1, false},
				{"h2c, the client shuts down writing first", Script{}.write(opcase::h2c_opening()).shutdown_write(), detect::Proto::h2c, false},
				{"MQTT", Script{}.write(opcase::cat({opcase::mqtt_connect(5, 13), opcase::mqtt_disconnect()})), detect::Proto::mqtt, false},
				{"SSH", Script{}.write(opcase::ssh_line("relay")).shutdown_write(), detect::Proto::ssh, false},
				{"a 2 MB MQTT CONNECT", Script{}.write(opcase::cat({opcase::mqtt_connect(4, 2097152), opcase::mqtt_disconnect()})), detect::Proto::mqtt, false},
				{"TLS, HTTP/1.1", Script{}.tls(tls_plan), detect::Proto::tls, true},
				{"TLS, no ALPN", Script{}.tls(no_alpn), detect::Proto::tls, true},
				{"TLS, ALPN h2", Script{}.tls(h2), detect::Proto::tls, true},
			};
			std::uint64_t relayed = 0;
			for (const Case& c : cases)
			{
				const opcase::Transcript d = r.direct(c.script, c.proto);
				std::vector<server::RelayReport> relays;
				const opcase::Transcript t = r.run(c.script, relays);
				if (auto bad = one_route(relays, c.tls ? server::Route::by_sni : server::Route::by_class, r.backend.port_of(c.proto), c.name)) return bad;
				++relayed;
				if (c.tls)
				{
					CHECK(t.tls && t.tls->handshake && d.tls && d.tls->handshake, c.name << ": a handshake did not complete");
					CHECK(t.tls->plain == d.tls->plain && t.tls->alpn == d.tls->alpn, c.name << ": the decrypted transcript differs from the backend's own");
				}
				else
				{
					CHECK(!d.received.empty(), c.name << ": the backend sent nothing");
					CHECK(t.received == d.received, c.name << ": " << t.received.size() << " bytes through the relay, " << d.received.size() << " from the backend");
				}
				CHECK(t.eof && !t.reset && d.eof, c.name << ": the relay did not pass on the backend's EOF");
			}
			// Output that blocks both ways: the client reads nothing until it has written everything.
			constexpr std::size_t kPipelined = 20000;
			const std::size_t want = (kPipelined + 1) * http1::kResponse200.size();
			const std::size_t got = pipelined(r.front.port(), kPipelined);
			CHECK(got == want, "pipelined: " << got << " bytes of responses, expected " << want);
			++relayed;
			// A reset from the client after its connection is relayed.
			{
				const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				sockaddr_in a{};
				a.sin_family = AF_INET;
				a.sin_port = htons(r.front.port());
				a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				CHECK(::connect(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a)) == 0, "connect");
				sockaddr_in local{};
				socklen_t n = sizeof(local);
				::getsockname(fd, reinterpret_cast<sockaddr*>(&local), &n);
				const Bytes partial = text("GET / HTTP/1.1\r\nHost: oneport.test\r\n");
				CHECK(::send(fd, partial.data(), partial.size(), 0) == static_cast<ssize_t>(partial.size()), "send");
				std::this_thread::sleep_for(100ms);
				const linger l{1, 0};
				::setsockopt(fd, SOL_SOCKET, SO_LINGER, &l, sizeof(l));
				::close(fd);
				std::vector<server::DetectionReport> reps;
				std::vector<server::RelayReport> relays;
				CHECK(r.front.collector.wait_close(ntohs(local.sin_port), 10000ms, reps, &relays), "the front did not close the reset connection");
				if (auto bad = one_route(relays, server::Route::by_class, r.backend.port_of(detect::Proto::http1), "reset")) return bad;
				++relayed;
			}
			if (auto bad = r.stop()) return bad;
			const server::Counters c = r.front.server->totals();
			CHECK(c.relayed == relayed && c.relay_connect_errors == 0 && c.route_rejected == 0, "relayed " << c.relayed << " of " << relayed);
			CHECK(c.routed_by_sni == 3, c.routed_by_sni << " routed by SNI");
			CHECK(c.connect_calls == relayed, c.connect_calls << " connects for " << relayed << " relayed connections");
			// I29, the M2b rule: the user-space relay receives and sends from the same bytes, so it
			// copies nothing in user space; splice moves the bytes inside the kernel.
			CHECK(c.bytes_copied == 0, "the relay copied " << c.bytes_copied << " bytes in user space");
			if (copy == RelayCopy::splice)
			{
				CHECK(c.splice_calls > 0 && c.bytes_spliced > want, "splice moved " << c.bytes_spliced << " bytes in " << c.splice_calls << " calls");
			}
			else
			{
				CHECK(c.splice_calls == 0 && c.bytes_spliced == 0, "the user-space relay spliced");
				CHECK(c.bytes_received > 2097152 + want && c.bytes_sent > 2097152 + want, "the boundary counters miss the relayed bytes");
			}
			CHECK(c.shutdown_calls >= 2 * (relayed - 1), c.shutdown_calls << " half-closes passed on");
			return std::nullopt;
		}

		/// A backend that refuses: the front closes the client's connection, and counts it.
		Result refused()
		{
			const int l = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			sockaddr_in a{};
			a.sin_family = AF_INET;
			a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			CHECK(::bind(l, reinterpret_cast<sockaddr*>(&a), sizeof(a)) == 0, "bind");
			socklen_t n = sizeof(a);
			::getsockname(l, reinterpret_cast<sockaddr*>(&a), &n);
			::close(l);  // nothing listens on this port now, nor on the five after it, very likely
			ServerArgs f;
			f.dispatch = Dispatch::relay;
			f.relay_port = ntohs(a.sin_port);
			Running front(f);
			const opcase::Transcript t = opcase::run(Script{}.write(opcase::http_get()), front.port());
			std::vector<server::DetectionReport> reps;
			std::vector<server::RelayReport> relays;
			CHECK(front.collector.wait_close(t.local_port, 10000ms, reps, &relays), "the front did not close the connection");
			if (auto bad = one_route(relays, server::Route::connect_failed, ntohs(a.sin_port), "refused")) return bad;
			CHECK(t.received.empty() && (t.eof || t.reset), "the client got a reply, or no close");
			if (auto bad = front.stop_and_check()) return bad;
			const server::Counters c = front.server->totals();
			CHECK(c.relay_connect_errors == 1 && c.relayed == 0, "connect errors " << c.relay_connect_errors);
			return std::nullopt;
		}

		// ---- relay.pass_through ----

		Result pass_through(Detect detect)
		{
			ServerArgs f;
			f.detect = detect;
			Relayed r(Mode::stub, f);
			const std::uint16_t tls_port = r.backend.port_of(detect::Proto::tls);
			const Bytes body = text(apps::kStubBody);
			const Bytes rec = opcase::recorded_client_hello();
			const std::uint32_t replay_room = detect == Detect::replay ? 1 : 0;
			auto routed = [&](const std::string& what, const Script& s, std::uint32_t msg, std::uint32_t records) -> Result {
				std::vector<server::RelayReport> relays;
				const opcase::Transcript t = r.run(s, relays);
				if (auto bad = one_route(relays, server::Route::by_sni, tls_port, what)) return bad;
				CHECK(relays[0].hello_len == msg && relays[0].hello_records == records,
				      what << ": reassembled " << relays[0].hello_len << " bytes in " << relays[0].hello_records << " records");
				CHECK(relays[0].held_max <= replay_room * (msg + 5 * records), what << ": held " << relays[0].held_max << " bytes (B2 d)");
				CHECK(t.received == body && t.eof, what << ": the stub's 13 bytes and its close did not come back (" << t.received.size() << " bytes)");
				return std::nullopt;
			};
			auto rejected = [&](const std::string& what, const Script& s) -> Result {
				std::vector<server::RelayReport> relays;
				const opcase::Transcript t = r.run(s, relays);
				if (auto bad = one_route(relays, server::Route::rejected, 0, what)) return bad;
				CHECK(t.received.empty() && (t.eof || t.reset), what << ": a reply, or no close");
				return std::nullopt;
			};
			const std::uint32_t rec_msg = static_cast<std::uint32_t>(rec.size() - 5);
			if (auto bad = routed("the recorded ClientHello", Script{}.write(rec).await_close(), rec_msg, 1)) return bad;
			if (auto bad = routed("in two writes", Script{}.split(rec, {40}, 30ms).await_close(), rec_msg, 1)) return bad;
			// Larger than the receive buffer: 6000 message bytes in one record, in two writes.
			const Bytes big = as_records(padded_message(6000), {});
			if (auto bad = routed("6000 message bytes", Script{}.split(big, {3000}, 30ms).await_close(), 6000, 1)) return bad;
			// Larger than B_CH: 17000 message bytes in two records.
			if (auto bad = rejected("17000 message bytes", Script{}.write(as_records(padded_message(17000), {16000})).await_close())) return bad;
			if (auto bad = rejected("another SNI", Script{}.write(replaced(rec, "oneport.test", "otherone.tst")).await_close())) return bad;
			if (auto bad = rejected("ALPN with neither protocol", Script{}.write(replaced(rec, "http/1.1", "spdy/3.1")).await_close())) return bad;
			Bytes malformed = rec;
			const std::size_t ext = 5 + extensions_at(hello_message());
			put16(malformed, ext, be16(malformed, ext) + 1);
			if (auto bad = rejected("a malformed ClientHello", Script{}.write(malformed).await_close())) return bad;
			if (auto bad = rejected("the peer's end mid-ClientHello", Script{}.write(opcase::slice(rec, 0, 100)).gap(30ms).shutdown_write())) return bad;
			if (auto bad = r.stop()) return bad;
			const server::Counters c = r.front.server->totals();
			CHECK(c.routed_by_sni == 3 && c.route_rejected == 5, "routed " << c.routed_by_sni << ", rejected " << c.route_rejected);
			if (detect == Detect::replay)
			{
				CHECK(c.bytes_copied >= 4096, "the 6000-byte ClientHello did not move out of the receive buffer (" << c.bytes_copied << " bytes copied)");
			}
			else
			{
				CHECK(c.bytes_copied == 0 && c.lowat_sets >= 1, "peek: copied " << c.bytes_copied << ", marks set " << c.lowat_sets);
			}
			return std::nullopt;
		}

		// ---- relay.stub ----

		Result stub()
		{
			ServerArgs a;
			a.mode = Mode::stub;
			Running srv(a);
			for (const auto& spec : srv.server->listeners()) CHECK(spec.stub && !spec.detects, "listener " << spec.name << " is not a stub port");
			const std::uint16_t tls = srv.port_of(detect::Proto::tls);
			const Bytes rec = opcase::recorded_client_hello();
			auto run = [&srv](const Script& s, std::uint16_t port) {
				opcase::Transcript t = opcase::run(s, port);
				std::vector<server::DetectionReport> reps;
				srv.collector.wait_close(t.local_port, 10000ms, reps);
				return t;
			};
			auto t = run(Script{}.write(rec).await_close(), tls);
			CHECK(t.received == text(apps::kStubBody) && t.eof, "the TLS port did not answer one record with the 13-byte body");
			t = run(Script{}.split(rec, {100}, 50ms).await_close(), tls);
			CHECK(t.received == text(apps::kStubBody) && t.first_byte && t.write_times.size() == 2 && *t.first_byte >= t.write_times[1],
			      "the TLS port answered before the whole record arrived");
			t = run(Script{}.write(opcase::http_get()).await_close(), tls);
			CHECK(t.received.empty() && (t.eof || t.reset), "the TLS port answered bytes that are not a TLS record");
			t = run(Script{}.write(opcase::http_get()), srv.port_of(detect::Proto::http1));
			CHECK(t.received == text(http1::kResponse200), "the HTTP/1.1 port did not answer 200");
			t = run(Script{}.write(opcase::cat({opcase::mqtt_connect(4, 12), opcase::mqtt_disconnect()})), srv.port_of(detect::Proto::mqtt));
			CHECK(t.received.size() == 4 && std::to_integer<int>(t.received[0]) == 0x20, "the MQTT port did not answer CONNACK");
			return srv.stop_and_check();
		}

		// ---- relay.matrix ----

		Result matrix()
		{
			int combos = 0;
			for (const Detect detect : {Detect::replay, Detect::peek})
				for (const Proxy proxy : {Proxy::off, Proxy::on})
					for (const Fallback fallback : {Fallback::none, Fallback::smtp})
						for (const RelayCopy copy : {RelayCopy::user_space, RelayCopy::splice})
							for (const std::uint32_t workers : {1u, 2u})
							{
								ServerArgs f;
								f.detect = detect;
								f.proxy = proxy;
								f.fallback = fallback;
								f.relay_copy = copy;
								f.workers = workers;
								f.t_fb = f.t_dec = f.t_hdr = 100ms;
								const std::string what = std::string(token(detect)) + (proxy == Proxy::on ? " proxy" : "") + (fallback == Fallback::smtp ? " SMTP" : "") +
								                         (copy == RelayCopy::splice ? " splice" : " user-space") + " workers " + std::to_string(workers);
								Relayed r(Mode::dedicated, f);
								const Bytes header = proxy == Proxy::on ? opcase::proxy_v2() : Bytes{};
								std::vector<server::RelayReport> relays;
								auto t = r.run(Script{}.write(opcase::cat({header, opcase::http_get()})), relays);
								CHECK(t.received == text(http1::kResponse200) && t.eof, what << ": no 200");
								if (fallback == Fallback::smtp)
								{
									relays.clear();
									t = r.run(Script{}.write(header).await_line().shutdown_write(), relays);
									CHECK(t.received == text(apps::kSmtpGreeting), what << ": a silent client does not reach the fallback");
									CHECK(t.first_byte && *t.first_byte - t.before_connect >= f.t_fb, what << ": the fallback spoke before T_fb");
									if (auto bad = one_route(relays, server::Route::by_class, r.backend.port_of(detect::Proto::smtp), what)) return bad;
								}
								if (auto bad = r.stop()) return what + ": " + *bad;
								++combos;
							}
			CHECK(combos == 32, combos << " combinations");
			return std::nullopt;
		}

		// ---- relay.binary ----

		/// A spawned oneport process and what it prints.
		struct Process
		{
			pid_t pid = -1;
			int out = -1;
			std::string text;

			bool start(const std::vector<std::string>& args)
			{
				int p[2];
				if (::pipe(p) != 0) return false;
				posix_spawn_file_actions_t fa;
				posix_spawn_file_actions_init(&fa);
				posix_spawn_file_actions_adddup2(&fa, p[1], 1);
				posix_spawn_file_actions_addclose(&fa, p[0]);
				std::vector<std::string> copy = args;
				std::vector<char*> argv;
				for (auto& s : copy) argv.push_back(s.data());
				argv.push_back(nullptr);
				const int rc = posix_spawn(&pid, copy[0].c_str(), &fa, nullptr, argv.data(), environ);
				posix_spawn_file_actions_destroy(&fa);
				::close(p[1]);
				out = p[0];
				return rc == 0;
			}

			bool read_more(int ms)
			{
				pollfd p{out, POLLIN, 0};
				if (::poll(&p, 1, ms) <= 0) return false;
				std::array<char, 4096> buf{};
				const ssize_t k = ::read(out, buf.data(), buf.size());
				if (k <= 0) return false;
				text.append(buf.data(), static_cast<std::size_t>(k));
				return true;
			}

			/// The port of the first "listening <name> 127.0.0.1:<port>" line.
			std::uint16_t port_of(const std::string& name)
			{
				const std::string key = "oneport: listening " + name + " 127.0.0.1:";
				for (;;)
				{
					const auto at = text.find(key);
					const auto eol = at == std::string::npos ? std::string::npos : text.find('\n', at);
					if (eol != std::string::npos) return static_cast<std::uint16_t>(std::stoi(text.substr(at + key.size(), eol - at - key.size())));
					if (!read_more(10000)) return 0;
				}
			}

			/// SIGTERM, then the rest of its output and its exit status.
			int stop()
			{
				if (pid < 0) return -1;
				::kill(pid, SIGTERM);
				while (read_more(10000))
				{
				}
				int status = 0;
				::waitpid(pid, &status, 0);
				::close(out);
				pid = -1;
				return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
			}

			~Process()
			{
				if (pid >= 0) stop();
			}
		};

		Result binary()
		{
			const std::string& path = binary_path();
			CHECK(!path.empty(), "no binary path given");
			const std::string backend(token(suite_backend()));
			Process b;
			CHECK(b.start({path, "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc", "--backend", backend}), "spawn the backend");
			const std::uint16_t bport = b.port_of("HTTP/1.1");
			CHECK(bport != 0, "the backend printed no listening line");
			Process f;
			CHECK(f.start({path, "--mode", "one-port", "--detect", "replay", "--dispatch", "relay", "--backend", backend, "--relay-port", std::to_string(bport)}),
			      "spawn the front");
			const std::uint16_t fport = f.port_of("one-port");
			CHECK(fport != 0, "the front printed no listening line");
			const auto http = opcase::run(Script{}.write(opcase::http_get()), fport);
			opcase::TlsPlan plan;
			plan.requests = {opcase::http_get()};
			const auto tls = opcase::run(Script{}.tls(plan), fport);
			const int fexit = f.stop();
			const int bexit = b.stop();
			CHECK(http.received == text(http1::kResponse200), "HTTP/1.1 through the relay: no 200");
			CHECK(tls.tls && tls.tls->handshake && tls.tls->plain == text(http1::kResponse200), "TLS through the relay: no handshake or no 200");
			CHECK(fexit == 0 && bexit == 0, "exit codes: front " << fexit << ", backend " << bexit);
			CHECK(f.text.find("counter relayed 2\n") != std::string::npos && f.text.find("counter routed_by_sni 1\n") != std::string::npos,
			      "the front's counters do not show two relayed connections, one by SNI");
			CHECK(b.text.find("counter accepted 2\n") != std::string::npos, "the backend's counters do not show two connections");
			return std::nullopt;
		}

	}  // namespace

	void register_relay_tests(Registry& r)
	{
		for (const Backend b : {Backend::epoll, Backend::io_uring})
		{
			const std::string s = "." + std::string(token(b));
			auto on = [b](Result (*fn)()) {
				return [b, fn] {
					suite_backend() = b;
					return fn();
				};
			};
			r["relay.exchanges.user_space.replay" + s] = on([] { return exchanges(RelayCopy::user_space, Detect::replay); });
			r["relay.exchanges.user_space.peek" + s] = on([] { return exchanges(RelayCopy::user_space, Detect::peek); });
			r["relay.exchanges.splice.replay" + s] = on([] { return exchanges(RelayCopy::splice, Detect::replay); });
			r["relay.exchanges.splice.peek" + s] = on([] { return exchanges(RelayCopy::splice, Detect::peek); });
			r["relay.refused" + s] = on(refused);
			r["relay.pass_through.replay" + s] = on([] { return pass_through(Detect::replay); });
			r["relay.pass_through.peek" + s] = on([] { return pass_through(Detect::peek); });
			r["relay.stub" + s] = on(stub);
			r["relay.matrix" + s] = on(matrix);
			r["relay.binary" + s] = on(binary);
		}
	}

}  // namespace oneport::test

#else

namespace oneport::test
{
	void register_relay_tests(Registry&) {}
}  // namespace oneport::test

#endif
