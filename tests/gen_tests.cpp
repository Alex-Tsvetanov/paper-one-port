// opgen, ophold and opcase's window programs (hypotheses.md, section 2.4; design/status.md, M3).
// Section 11 asks the records to cover opgen, opcase and ophold, so every load and protocol of
// opgen runs here, in-process against the server, under each sanitizer build:
//   - gen.options, gen.quantiles, gen.h2_status: the command line, the quantiles and the start of
//     an h2 response's header block (pure, every platform);
//   - gen.churn.<proto>.<backend>, gen.keepalive.<proto>.<backend>: WL1's and WL3's exchanges
//     against a server in dedicated mode (stub mode for the TLS stub exchange), every exchange
//     completed without error, and the server's view consistent with the generator's;
//   - gen.open_loop.<backend>: WL2 at a fixed rate, the exchanges due counted from the schedule;
//   - gen.probe.<backend>: the probe of each protocol;
//   - gen.source_block: every connection's source address lies in the block;
//   - gen.failures: a refused port counts connect failures, a silent server counts timeouts;
//   - gen.hold.<backend>: the mixed-protocol cell's silent background (opcase's holder) against
//     one-port mode, whose T_dec closes it and the holder opens it again, and against dedicated ports;
//   - gen.binaries: the opgen, opcase and ophold programs against the oneport program.
// Functional and untimed: no rate is asserted.
#include "test_support.hpp"

#include "hpack.hpp"
#include "opgen.hpp"

#include <algorithm>
#include <cmath>

#if defined(__linux__) && defined(ONEPORT_HAVE_TLS)

#include "apps.hpp"
#include "harness.hpp"
#include "hold.hpp"

#include <array>
#include <atomic>
#include <set>
#include <spawn.h>
#include <sstream>
#include <thread>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

#endif

namespace oneport::test
{

	namespace
	{

		using namespace std::chrono_literals;
		namespace og = oneport::opgen;

		std::vector<std::string_view> words(std::initializer_list<std::string_view> w) { return {w}; }

		Result options()
		{
			auto ok = [](std::initializer_list<std::string_view> w) { return og::parse_args(words(w)); };
			const auto a = ok({"--port", "8080", "--proto", "h2c"});
			CHECK(a && a->port == 8080 && a->proto == og::Proto::h2c && a->load == og::Load::churn && a->rate == 0 && a->threads == 1 && a->k_src == 1,
			      "defaults");
			const auto b = ok({"--port", "1", "--proto", "tls", "--load", "keepalive", "--conns", "64", "--cpus", "2-4,7", "--src-base", "127.0.2.0",
			                   "--k-src", "256", "--warmup-ms", "1000", "--duration-ms", "5000", "--timeout-ms", "250"});
			CHECK(b && b->threads == 4 && b->cpus == (std::vector<int>{2, 3, 4, 7}) && b->src_base == 0x7F000200u && b->k_src == 256 && b->conns == 64,
			      "a full keep-alive line: " << (b ? std::string("parsed") : b.error()));
			CHECK(b->timeout == 250ms && b->warmup == 1000ms && b->duration == 5000ms, "durations");
			const auto c = ok({"--port", "9", "--proto", "tls-stub", "--rate", "1234.5"});
			CHECK(c && c->rate == 1234.5 && c->proto == og::Proto::tls_stub, "open loop");
			CHECK(ok({"--port", "9", "--proto", "mqtt", "--probe"})->probe, "--probe");
			CHECK(ok({"--port", "9", "--proto", "http1", "--rate", "100", "--spin-us", "0"})->spin == 0ns, "--spin-us 0");
			CHECK(ok({"--port", "9", "--proto", "http1"})->spin == 200us, "the default spin");
			// Refused.
			CHECK(!ok({"--proto", "h2c"}), "no port");
			CHECK(!ok({"--port", "9"}), "no protocol");
			CHECK(!ok({"--port", "0", "--proto", "h2c"}), "port 0");
			CHECK(!ok({"--port", "9", "--proto", "quic"}), "an unknown protocol");
			CHECK(!ok({"--port", "9", "--proto", "ssh", "--load", "keepalive"}), "SSH has no keep-alive load (WL3)");
			CHECK(!ok({"--port", "9", "--proto", "tls-stub", "--load", "keepalive"}), "the stub exchange has no keep-alive load");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--load", "keepalive", "--rate", "10"}), "open loop is churn's");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--src-base", "127.0.0.1"}), "a block holding the server's 127.0.0.1");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--src-base", "127.255.255.250", "--k-src", "6"}), "a block holding 127.255.255.255");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--src-base", "10.0.0.2"}), "a block outside 127.0.0.0/8");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--cpus", "4-2"}), "a backward CPU range");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--cpus", "2-3", "--threads", "3"}), "--threads against --cpus");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--port", "10"}), "a flag twice");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--rate", "0"}), "rate 0");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--duration-ms", "0"}), "an empty window");
			CHECK(!ok({"--port", "9", "--proto", "http1", "--bogus", "1"}), "an unknown flag");
			CHECK(og::dotted(0x7F000102u) == "127.0.1.2" && og::parse_dotted("127.0.1.2") == 0x7F000102u, "dotted");
			CHECK(!og::parse_dotted("127.0.1") && !og::parse_dotted("127.0.1.256") && !og::parse_dotted("127.0.1.2x"), "bad dotted forms");
			return std::nullopt;
		}

		Result h2_status()
		{
			auto ok = [](std::initializer_list<unsigned> v) {
				std::vector<std::byte> b;
				for (const unsigned x : v) b.push_back(static_cast<std::byte>(x));
				return og::detail::h2_status_200(b.data(), b.size());
			};
			CHECK(ok({0x88}), ":status 200 first");
			CHECK(ok({0x3F, 0xE1, 0x1F, 0x88, 0x76}), "after a size update of 4096 (Jetty 12.1's first block)");
			CHECK(ok({0x20, 0x3F, 0xE1, 0x1F, 0x88}), "after two size updates, 0 then 4096");
			CHECK(!ok({0x89}), ":status 204");
			CHECK(!ok({}), "an empty block");
			CHECK(!ok({0x3F, 0xE1, 0x1F}), "a size update and nothing after it");
			CHECK(!ok({0x3F, 0xE1}), "a size update cut short");
			CHECK(!ok({0x3F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x01, 0x88}), "a size integer longer than 5 bytes");
			CHECK(!ok({0x48, 0x03, 0x32, 0x30, 0x30}), ":status 200 as a literal is not the static index");
			return std::nullopt;
		}

		Result quantile_rules()
		{
			const og::Quantiles odd = og::quantiles({5, 1, 3});
			CHECK(odd.n == 3 && odd.median == 3 && odd.min == 1 && odd.max == 5 && odd.mean == 3, "odd count");
			const og::Quantiles even = og::quantiles({4, 1, 3, 2});
			CHECK(even.median == 2.5, "even count: the mean of the middle two, " << even.median);
			std::vector<std::uint64_t> v(1000);
			for (std::size_t i = 0; i < v.size(); ++i) v[i] = 1000 - i;  // 1..1000, reversed
			const og::Quantiles q = og::quantiles(v);
			CHECK(q.p99 == 990 && q.p999 == 999, "nearest rank: p99 " << q.p99 << ", p99.9 " << q.p999);
			CHECK(og::quantiles({}).n == 0, "empty");
			return std::nullopt;
		}

#if defined(__linux__) && defined(ONEPORT_HAVE_TLS)

		og::Options short_window(og::Proto p, og::Load l, std::uint16_t port)
		{
			og::Options o;
			o.proto = p;
			o.load = l;
			o.port = port;
			// Short and narrow: each test opens a few thousand connections at most, since L tracks every
			// connection in a table of 262,144 that holds each closed one 120 s (design/status.md, M3),
			// and the four sanitizer suites run at once.
			o.conns = 2;
			o.threads = 2;
			o.warmup = 20ms;
			o.duration = 100ms;
			o.timeout = 2000ms;
			o.src_base = 0x7F000A01u;  // 127.0.10.1
			o.k_src = 4;
			return o;
		}

		detect::Proto server_class(og::Proto p)
		{
			switch (p)
			{
				case og::Proto::http1: return detect::Proto::http1;
				case og::Proto::h2c: return detect::Proto::h2c;
				case og::Proto::tls:
				case og::Proto::tls_stub: return detect::Proto::tls;
				case og::Proto::mqtt: return detect::Proto::mqtt;
				case og::Proto::ssh: return detect::Proto::ssh;
			}
			return detect::Proto::http1;
		}

		Result one_load(og::Proto p, og::Load l)
		{
			ServerArgs a;
			a.mode = p == og::Proto::tls_stub ? Mode::stub : Mode::dedicated;
			Running srv(a);
			const og::Options o = short_window(p, l, srv.port_of(server_class(p)));
			std::ostringstream markers;
			const og::Result r = og::run(o, &markers);
			CHECK(r.ok, "opgen failed: " << r.error);
			CHECK(markers.str().find("MEASURE_START ") != std::string::npos && markers.str().find("MEASURE_END ") != std::string::npos, "no markers");
			CHECK(r.measure.completed > 0, "nothing completed in the window");
			CHECK(r.measure.errors.total() == 0 && r.warmup.errors.total() == 0,
			      "errors: window " << r.measure.errors.total() << " (timeouts " << r.measure.errors.timeout << ", resets " << r.measure.errors.reset
			                        << ", eof " << r.measure.errors.eof << ", protocol " << r.measure.errors.protocol << ", tls " << r.measure.errors.tls
			                        << ", connect " << r.measure.errors.connect << "), warm-up " << r.warmup.errors.total());
			CHECK(r.wall_s > 0.09 && r.wall_s < 0.5, "window of " << r.wall_s << " s");
			CHECK(r.ttfb.n == r.measure.completed && r.exchange.n == r.measure.completed, "a TTFB per completed exchange");
			CHECK(r.ttfb.min > 0 && r.ttfb.median <= static_cast<double>(r.exchange.max), "TTFB within the exchange");
			CHECK(r.thread_cpu_s.size() == 2 && r.cpu_s > 0, "the workers' CPU time");
			if (auto bad = srv.stop_and_check()) return bad;
			const server::Counters c = srv.server->totals();
			if (l == og::Load::churn)
			{
				// Every connect reached the server, and each was accepted once.
				CHECK(c.accepted == r.measure.connects, "server accepted " << c.accepted << ", opgen connected " << r.measure.connects);
				CHECK(c.accepted >= r.measure.completed + r.warmup.completed, "fewer connections than exchanges");
			}
			else
			{
				CHECK(c.accepted == o.conns, "keep-alive: " << c.accepted << " connections for " << o.conns << " slots");
			}
			return std::nullopt;
		}

		Result open_loop()
		{
			ServerArgs a;
			a.mode = Mode::dedicated;
			Running srv(a);
			og::Options o = short_window(og::Proto::http1, og::Load::churn, srv.port_of(detect::Proto::http1));
			o.rate = 1000;
			const og::Result r = og::run(o, nullptr);
			CHECK(r.ok, "opgen failed: " << r.error);
			// 1,000 per second over the measured wall time, from the schedule, give or take one.
			const double expect = 1000.0 * r.wall_s;
			CHECK(std::fabs(static_cast<double>(r.due) - expect) <= 2.0, "due " << r.due << ", expected about " << expect);
			CHECK(r.due_completed == r.due && r.due_unfinished == 0, "completed " << r.due_completed << " of " << r.due);
			CHECK(r.ttfb.n == r.due_completed && r.issue_lag.n == r.due_completed && r.ttfb_connect.n == r.due_completed, "one sample per exchange");
			CHECK(r.ttfb.median >= r.ttfb_connect.median, "TTFB from the due time is at least TTFB from connect");
			if (auto bad = srv.stop_and_check()) return bad;
			return std::nullopt;
		}

		/// Runs opcase's holder (bench/cases/hold.hpp) for `run_for`, then stops it.
		opcase::HoldResult hold_for(const opcase::HoldOptions& o, std::chrono::milliseconds run_for)
		{
			std::atomic<bool> stop{false};
			std::atomic<bool> ready{false};
			opcase::HoldResult r;
			std::thread t([&] { r = opcase::hold(o, stop, [&](const opcase::HoldResult&) { ready.store(true); }); });
			std::this_thread::sleep_for(run_for);
			stop.store(true);
			t.join();
			std::this_thread::sleep_for(150ms);  // the server observes the holder's resets before it stops
			return r;
		}

		/// The mixed-protocol cell's silent background (section 10): the holder keeps its count by
		/// one policy in both modes. Against one-port mode, whose T_dec closes a silent connection
		/// (1 f), every closed connection is opened again at once; with the policy off, none is;
		/// against a dedicated port no connection is closed, and a port that speaks at accept (SSH)
		/// has its line read and discarded.
		Result hold()
		{
			{
				ServerArgs a;
				a.mode = Mode::one_port;
				a.t_dec = 200ms;
				Running srv(a);
				opcase::HoldOptions o;
				o.ports = {srv.port()};
				o.n = 6;
				o.src_base = 0x7F000E01u;  // 127.0.14.1
				o.k_src = 2;
				const opcase::HoldResult r = hold_for(o, 900ms);
				CHECK(r.ok, "hold: " << r.error);
				CHECK(r.ready_ns > 0 && r.held_at_ready == 6, "never held all 6 (" << r.held_at_ready << ")");
				CHECK(r.connect_failures == 0, r.connect_failures << " connects failed");
				CHECK(r.closed_by_peer >= 6, "T_dec closed only " << r.closed_by_peer << " held connections in 900 ms");
				CHECK(r.reopened == r.closed_by_peer && r.connects == 6 + r.reopened, "reopened " << r.reopened << " of " << r.closed_by_peer
				                                                                                 << " closed, " << r.connects << " connects");
				CHECK(r.bytes_received == 0, "a one-port server sent " << r.bytes_received << " bytes to a silent client");
				if (auto bad = srv.stop_and_check()) return bad;
				const server::Counters c = srv.server->totals();
				CHECK(c.accepted == r.connects, "accepted " << c.accepted << " of " << r.connects << " connects");
				CHECK(c.outcomes[static_cast<std::size_t>(server::Outcome::silent)] == r.closed_by_peer,
				      "silent outcomes " << c.outcomes[static_cast<std::size_t>(server::Outcome::silent)] << ", closes seen " << r.closed_by_peer);
			}
			{
				ServerArgs a;
				a.mode = Mode::one_port;
				a.t_dec = 200ms;
				Running srv(a);
				opcase::HoldOptions o;
				o.ports = {srv.port()};
				o.n = 4;
				o.reopen = false;
				const opcase::HoldResult r = hold_for(o, 600ms);
				CHECK(r.ok && r.held_at_ready == 4, "the control never held its 4");
				CHECK(r.closed_by_peer == 4 && r.reopened == 0 && r.connects == 4 && r.held_at_stop == 0,
				      "without the policy: closed " << r.closed_by_peer << ", reopened " << r.reopened << ", held at the stop " << r.held_at_stop);
				if (auto bad = srv.stop_and_check()) return bad;
			}
			{
				ServerArgs a;
				a.mode = Mode::dedicated;
				a.t_dec = 200ms;
				Running srv(a);
				opcase::HoldOptions o;
				o.ports = {srv.port_of(detect::Proto::http1), srv.port_of(detect::Proto::ssh)};
				o.n = 4;
				const opcase::HoldResult r = hold_for(o, 600ms);
				CHECK(r.ok && r.held_at_ready == 4 && r.held_min == 4 && r.held_at_stop == 4, "dedicated: held " << r.held_at_ready << ", at least "
				                                                                                                 << r.held_min << ", at the stop " << r.held_at_stop);
				CHECK(r.closed_by_peer == 0 && r.reopened == 0 && r.connects == 4, "dedicated: closed " << r.closed_by_peer << ", connects " << r.connects);
				CHECK(r.bytes_received == 2 * apps::kSshBanner.size(), "the SSH port's lines: " << r.bytes_received << " bytes");
				if (auto bad = srv.stop_and_check()) return bad;
			}
			return std::nullopt;
		}

		Result probe()
		{
			for (const og::Proto p : {og::Proto::http1, og::Proto::h2c, og::Proto::tls, og::Proto::mqtt, og::Proto::ssh, og::Proto::tls_stub})
			{
				ServerArgs a;
				a.mode = p == og::Proto::tls_stub ? Mode::stub : Mode::dedicated;
				Running srv(a);
				og::Options o = short_window(p, og::Load::churn, srv.port_of(server_class(p)));
				o.probe = true;
				const og::Result r = og::run(o, nullptr);
				CHECK(r.ok && r.measure.completed == 1 && r.measure.errors.total() == 0, og::name(p) << ": probe " << r.probe_detail << " " << r.error);
				if (auto bad = srv.stop_and_check()) return bad;
				CHECK(srv.server->totals().accepted == 1, og::name(p) << ": the probe is one connection");
			}
			return std::nullopt;
		}

		/// A listener that records each connection's source address and closes it at once.
		struct Recorder
		{
			int fd = -1;
			std::uint16_t port = 0;
			std::atomic<bool> stop{false};
			std::set<std::uint32_t> sources;
			std::thread t;

			Recorder()
			{
				fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				sockaddr_in a{};
				a.sin_family = AF_INET;
				a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				::bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a));
				::listen(fd, 128);
				socklen_t n = sizeof(a);
				::getsockname(fd, reinterpret_cast<sockaddr*>(&a), &n);
				port = ntohs(a.sin_port);
				t = std::thread([this] {
					while (!stop.load())
					{
						pollfd p{fd, POLLIN, 0};
						if (::poll(&p, 1, 50) <= 0) continue;
						sockaddr_in peer{};
						socklen_t len = sizeof(peer);
						const int c = ::accept(fd, reinterpret_cast<sockaddr*>(&peer), &len);
						if (c < 0) continue;
						sources.insert(ntohl(peer.sin_addr.s_addr));
						::close(c);
					}
				});
			}
			/// Stops accepting; the sources are then stable.
			void finish()
			{
				stop.store(true);
				if (t.joinable()) t.join();
			}
			~Recorder()
			{
				finish();
				::close(fd);
			}
		};

		/// A loopback port nothing listens on: bound once by the kernel's choice, then closed.
		/// A loopback port that refuses every connect: bound and not listening, so a SYN to it gets a
		/// reset, and kept bound for the holder's life, so no other test can be given that port. (A
		/// port bound and closed again could be handed to a concurrent test's listener, which then
		/// accepted this test's connects: seen on L in M4a, gen.failures beside
		/// server.kernel_uring_recv_select.)
		struct RefusedPort
		{
			int fd = -1;
			std::uint16_t port = 0;
			RefusedPort()
			{
				fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				sockaddr_in a{};
				a.sin_family = AF_INET;
				a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				if (fd < 0 || ::bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a)) != 0) return;
				socklen_t n = sizeof(a);
				::getsockname(fd, reinterpret_cast<sockaddr*>(&a), &n);
				port = ntohs(a.sin_port);
			}
			~RefusedPort()
			{
				if (fd >= 0) ::close(fd);
			}
			RefusedPort(const RefusedPort&) = delete;
			RefusedPort& operator=(const RefusedPort&) = delete;
		};

		Result source_block()
		{
			std::set<std::uint32_t> seen;
			{
				Recorder rec;
				og::Options o = short_window(og::Proto::http1, og::Load::churn, rec.port);
				o.k_src = 3;
				o.src_base = 0x7F000B07u;  // 127.0.11.7
				o.conns = 2;
				o.warmup = 0ms;
				o.duration = 100ms;
				const og::Result r = og::run(o, nullptr);
				CHECK(r.ok, "opgen failed: " << r.error);
				CHECK(r.measure.errors.eof + r.measure.errors.reset > 0, "the recorder's closes are not counted as failures");
				rec.finish();
				seen = rec.sources;
			}
			CHECK(seen == (std::set<std::uint32_t>{0x7F000B07u, 0x7F000B08u, 0x7F000B09u}), seen.size() << " source addresses, expected the 3 of the block");
			return std::nullopt;
		}

		Result failures()
		{
			// A port that refuses: every exchange fails at connect.
			{
				const RefusedPort refused;
				CHECK(refused.port != 0, "a bound loopback port");
				og::Options o = short_window(og::Proto::mqtt, og::Load::churn, refused.port);
				o.warmup = 0ms;
				o.duration = 200ms;
				const og::Result r = og::run(o, nullptr);
				CHECK(r.ok && r.measure.completed == 0 && r.measure.errors.connect > 0 && r.measure.errors.total() == r.measure.errors.connect,
				      "refused: completed " << r.measure.completed << ", connect failures " << r.measure.errors.connect);
			}
			// A server that accepts and never answers: every exchange times out.
			{
				const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				sockaddr_in a{};
				a.sin_family = AF_INET;
				a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				::bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a));
				::listen(fd, 128);
				socklen_t n = sizeof(a);
				::getsockname(fd, reinterpret_cast<sockaddr*>(&a), &n);
				og::Options o = short_window(og::Proto::http1, og::Load::churn, ntohs(a.sin_port));
				o.conns = 2;
				o.warmup = 0ms;
				o.duration = 200ms;
				o.timeout = 100ms;
				const og::Result r = og::run(o, nullptr);
				::close(fd);
				CHECK(r.ok && r.measure.completed == 0 && r.measure.errors.timeout > 0, "silent: completed " << r.measure.completed << ", timeouts " << r.measure.errors.timeout);
			}
			return std::nullopt;
		}

		/// A spawned program and what it prints.
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

			/// The number after the first `key` on a complete line.
			long value_after(const std::string& key)
			{
				for (;;)
				{
					const auto at = text.find(key);
					const auto eol = at == std::string::npos ? std::string::npos : text.find('\n', at);
					if (eol != std::string::npos) return std::stol(text.substr(at + key.size(), eol - at - key.size()));
					if (!read_more(10000)) return -1;
				}
			}

			int wait()
			{
				while (read_more(30000))
				{
				}
				int status = 0;
				::waitpid(pid, &status, 0);
				::close(out);
				pid = -1;
				return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
			}

			int stop()
			{
				if (pid < 0) return -1;
				::kill(pid, SIGTERM);
				return wait();
			}

			~Process()
			{
				if (pid >= 0) stop();
			}
		};

		Result binaries()
		{
			const std::vector<std::string>& p = extra_paths();
			CHECK(!binary_path().empty() && p.size() == 3, "needs the oneport, opgen, opcase and ophold paths");
			const std::string& oneport = binary_path();
			const std::string& opgen = p[0];
			const std::string& opcase = p[1];
			const std::string& ophold = p[2];
			// opgen against the oneport program: the probe, then a short closed-loop window.
			Process server;
			CHECK(server.start({oneport, "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc", "--backend", "epoll"}), "spawn oneport");
			const long port = server.value_after("oneport: listening HTTP/1.1 127.0.0.1:");
			CHECK(port > 0, "oneport printed no listening line");
			Process probe;
			CHECK(probe.start({opgen, "--port", std::to_string(port), "--proto", "http1", "--probe"}), "spawn the probe");
			CHECK(probe.wait() == 0 && probe.text.find("\"probe_detail\":\"http1: exchange completed\"") != std::string::npos, "the probe failed");
			Process gen;
			CHECK(gen.start({opgen, "--port", std::to_string(port), "--proto", "http1", "--threads", "1", "--conns", "2", "--warmup-ms", "50",
			                 "--duration-ms", "150", "--src-base", "127.0.12.1", "--k-src", "2"}),
			      "spawn opgen");
			CHECK(gen.wait() == 0, "opgen's exit");
			CHECK(gen.text.find("MEASURE_START ") != std::string::npos && gen.text.find("MEASURE_END ") != std::string::npos, "no markers");
			CHECK(gen.text.find("\"ok\":true") != std::string::npos && gen.text.find("\"connect_failures\":0") != std::string::npos, "the report");
			CHECK(server.stop() == 0, "oneport's exit");
			CHECK(server.text.find("counter accepted ") != std::string::npos, "oneport printed no counters");
			// ophold holds what opcase opens: silent connections, then partial ClientHellos.
			for (const std::string kase : {"silent", "partial-hello"})
			{
				Process hold;
				CHECK(hold.start({ophold, "--port", "0", "--backlog", "64"}), "spawn ophold");
				const long hport = hold.value_after("ophold: listening 127.0.0.1:");
				CHECK(hport > 0, "ophold printed no listening line");
				Process reset;
				CHECK(reset.start({opcase, "probe-reset", "--port", std::to_string(hport)}), "spawn the reset probe");
				CHECK(reset.wait() == 0, "the reset probe failed");
				Process open;
				CHECK(open.start({opcase, "open", "--port", std::to_string(hport), "--case", kase, "--n", "100", "--batch", "25", "--pace-ms", "10",
				                  "--close-at-ms", "600", "--src-base", "127.0.13.1", "--k-src", "4"}),
				      "spawn opcase");
				CHECK(open.value_after("OPENED ") == 100, kase << ": opened");
				CHECK(open.wait() == 0, kase << ": opcase's exit");
				CHECK(open.text.find("CLOSED 100 ") != std::string::npos, kase << ": closed");
				const std::string per = kase == "silent" ? "\"bytes_per_conn\":0" : "\"bytes_per_conn\":108";
				CHECK(open.text.find(per) != std::string::npos, kase << ": the bytes per connection");
				::kill(hold.pid, SIGTERM);
				const long held = hold.value_after("ophold: held ");
				CHECK(hold.wait() == 0 && (held == 100 || held == 101), kase << ": ophold held " << held << ", not the 100 (and the reset probe)");
			}
			// opcase hold against the oneport program in one-port mode: T_dec closes each silent
			// connection and the holder opens it again; SIGTERM ends it with a line of counts.
			Process onep;
			CHECK(onep.start({oneport, "--mode", "one-port", "--detect", "replay", "--dispatch", "inproc", "--backend", "epoll", "--t-dec-ms", "200"}),
			      "spawn oneport in one-port mode");
			const long oport = onep.value_after("oneport: listening one-port 127.0.0.1:");
			CHECK(oport > 0, "oneport printed no one-port listening line");
			Process bg;
			CHECK(bg.start({opcase, "hold", "--ports", std::to_string(oport), "--n", "3", "--src-base", "127.0.15.1", "--k-src", "2"}), "spawn opcase hold");
			CHECK(bg.value_after("HOLD ") == 3, "opcase hold never held its 3");
			std::this_thread::sleep_for(700ms);
			CHECK(bg.stop() == 0, "opcase hold's exit");
			const long reopened = bg.value_after("\"reopened\": ");
			CHECK(reopened >= 3, "opcase hold reopened " << reopened << " connections in 700 ms at T_dec = 200 ms");
			CHECK(bg.text.find("\"connect_failures\": 0") != std::string::npos, "opcase hold: a connect failed");
			std::this_thread::sleep_for(150ms);
			CHECK(onep.stop() == 0, "oneport's exit");
			// opcase case --list: the constants, then each variant's frozen expectation.
			Process list;
			CHECK(list.start({opcase, "case", "--list", "--hc", "12"}), "spawn opcase case --list");
			CHECK(list.wait() == 0, "opcase case --list's exit");
			CHECK(list.text.find("{\"constants\": {\"response200_hex\": ") == 0, "no constants line first");
			CHECK(list.text.find("\"id\": \"HC12\"") != std::string::npos && list.text.find("\"when\": \"t_hdr\"") != std::string::npos &&
			          list.text.find("\"expect\": \"proxy_timeout\"") != std::string::npos,
			      "HC12's expectation is not listed: " << list.text.substr(0, 400));
			return std::nullopt;
		}

#endif

	}  // namespace

	void register_gen_tests(Registry& r)
	{
		r["gen.options"] = options;
		r["gen.quantiles"] = quantile_rules;
		r["gen.h2_status"] = h2_status;
#if defined(__linux__) && defined(ONEPORT_HAVE_TLS)
		for (const Backend b : {Backend::epoll, Backend::io_uring})
		{
			const std::string s = "." + std::string(token(b));
			auto on = [b](std::function<Result()> fn) {
				return [b, fn] {
					suite_backend() = b;
					return fn();
				};
			};
			for (const og::Proto p : {og::Proto::http1, og::Proto::h2c, og::Proto::tls, og::Proto::mqtt, og::Proto::ssh, og::Proto::tls_stub})
			{
				r["gen.churn." + std::string(og::name(p)) + s] = on([p] { return one_load(p, og::Load::churn); });
			}
			for (const og::Proto p : {og::Proto::http1, og::Proto::h2c, og::Proto::tls, og::Proto::mqtt})
			{
				r["gen.keepalive." + std::string(og::name(p)) + s] = on([p] { return one_load(p, og::Load::keepalive); });
			}
			r["gen.open_loop" + s] = on(open_loop);
			r["gen.hold" + s] = on(hold);
			r["gen.probe" + s] = on(probe);
		}
		r["gen.source_block"] = source_block;
		r["gen.failures"] = failures;
		r["gen.binaries"] = binaries;
#endif
	}

}  // namespace oneport::test
