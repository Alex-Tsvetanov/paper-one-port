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
//   - gen.binaries: the opgen, opcase and ophold programs against the oneport program.
// On Windows (M6b) the same loads and protocols run against the server on IOCP
// (gen.<load>.<proto>.IOCP, gen.open_loop.IOCP, gen.probe.IOCP), and Windows' own forms of the
// rest: gen.source_block and gen.failures with Winsock listeners (a refused loopback connect is
// reported only after about 2 s on W, so its window is longer), gen.pin_reuse_unicastport (the
// socket option opgen sets in place of IP_BIND_ADDRESS_NO_PORT, tested before use), and
// gen.binaries with the oneport and opgen programs (opcase's and ophold's programs are Linux only).
// Functional and untimed: no rate is asserted.
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#endif

#include "test_support.hpp"

#include "hpack.hpp"
#include "opgen.hpp"

#include <algorithm>
#include <cmath>

#if defined(_WIN32) && defined(ONEPORT_HAVE_TLS)

#include "harness.hpp"

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <array>
#include <atomic>
#include <mutex>
#include <set>
#include <sstream>
#include <thread>

#endif

#if defined(__linux__) && defined(ONEPORT_HAVE_TLS)

#include "harness.hpp"

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

#if (defined(__linux__) || defined(_WIN32)) && defined(ONEPORT_HAVE_TLS)

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

#endif

#if defined(__linux__) && defined(ONEPORT_HAVE_TLS)

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
			return std::nullopt;
		}

#endif

#if defined(_WIN32) && defined(ONEPORT_HAVE_TLS)

		/// Winsock 2.2 for one test (the in-process server starts its own too).
		struct Winsock
		{
			Winsock()
			{
				WSADATA d{};
				ok = ::WSAStartup(MAKEWORD(2, 2), &d) == 0;
			}
			~Winsock()
			{
				if (ok) ::WSACleanup();
			}
			Winsock(const Winsock&) = delete;
			Winsock& operator=(const Winsock&) = delete;
			bool ok = false;
		};

		sockaddr_in loopback_v4(std::uint32_t host_order_addr, std::uint16_t port)
		{
			sockaddr_in a{};
			a.sin_family = AF_INET;
			a.sin_port = htons(port);
			a.sin_addr.s_addr = htonl(host_order_addr);
			return a;
		}

		/// A loopback socket bound by the system's choice of port; `listen` makes it a listener.
		SOCKET bound_socket(bool listen, std::uint16_t& port)
		{
			const SOCKET s = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
			if (s == INVALID_SOCKET) return s;
			const BOOL one = TRUE;
			::setsockopt(s, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char*>(&one), sizeof(one));
			sockaddr_in a = loopback_v4(INADDR_LOOPBACK, 0);
			if (::bind(s, reinterpret_cast<sockaddr*>(&a), sizeof(a)) != 0 || (listen && ::listen(s, SOMAXCONN) != 0))
			{
				::closesocket(s);
				return INVALID_SOCKET;
			}
			int n = sizeof(a);
			::getsockname(s, reinterpret_cast<sockaddr*>(&a), &n);
			port = ntohs(a.sin_port);
			return s;
		}

		/// A listener that records each connection's source address and closes it at once.
		struct WinRecorder
		{
			Winsock ws;
			SOCKET fd = INVALID_SOCKET;
			std::uint16_t port = 0;
			std::atomic<bool> stop{false};
			std::set<std::uint32_t> sources;
			std::thread t;

			WinRecorder()
			{
				fd = bound_socket(true, port);
				t = std::thread([this] {
					while (!stop.load())
					{
						fd_set r;
						FD_ZERO(&r);
						FD_SET(fd, &r);
						timeval tv{0, 50'000};
						if (::select(0, &r, nullptr, nullptr, &tv) <= 0) continue;
						sockaddr_in peer{};
						int len = sizeof(peer);
						const SOCKET c = ::accept(fd, reinterpret_cast<sockaddr*>(&peer), &len);
						if (c == INVALID_SOCKET) continue;
						sources.insert(ntohl(peer.sin_addr.s_addr));
						::closesocket(c);
					}
				});
			}
			void finish()
			{
				stop.store(true);
				if (t.joinable()) t.join();
			}
			~WinRecorder()
			{
				finish();
				if (fd != INVALID_SOCKET) ::closesocket(fd);
			}
			WinRecorder(const WinRecorder&) = delete;
			WinRecorder& operator=(const WinRecorder&) = delete;
		};

		Result win_source_block()
		{
			std::set<std::uint32_t> seen;
			{
				WinRecorder rec;
				CHECK(rec.fd != INVALID_SOCKET, "a recording listener");
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

		Result win_failures()
		{
			const Winsock ws;
			// A port that refuses: bound and not listening, held for the test's length. On W a
			// refused loopback connect completes with its error only after about 2 s (the SYN is
			// sent again after the reset; read on W in M6b), so the window is 2.6 s and the timeout
			// 4 s, and the failures counted are those whose connect failed inside the window.
			{
				std::uint16_t port = 0;
				const SOCKET held = bound_socket(false, port);
				CHECK(held != INVALID_SOCKET && port != 0, "a bound loopback port");
				og::Options o = short_window(og::Proto::mqtt, og::Load::churn, port);
				o.warmup = 0ms;
				o.duration = 2600ms;
				o.timeout = 4000ms;
				const og::Result r = og::run(o, nullptr);
				::closesocket(held);
				CHECK(r.ok && r.measure.completed == 0 && r.measure.errors.connect > 0 && r.measure.errors.total() == r.measure.errors.connect,
				      "refused: completed " << r.measure.completed << ", connect failures " << r.measure.errors.connect << ", errors "
				                            << r.measure.errors.total());
			}
			// A server that accepts and never answers: every exchange times out.
			{
				std::uint16_t port = 0;
				const SOCKET l = bound_socket(true, port);
				CHECK(l != INVALID_SOCKET, "a silent listener");
				og::Options o = short_window(og::Proto::http1, og::Load::churn, port);
				o.conns = 2;
				o.warmup = 0ms;
				o.duration = 200ms;
				o.timeout = 100ms;
				const og::Result r = og::run(o, nullptr);
				::closesocket(l);
				CHECK(r.ok && r.measure.completed == 0 && r.measure.errors.timeout > 0, "silent: completed " << r.measure.completed << ", timeouts " << r.measure.errors.timeout);
			}
			return std::nullopt;
		}

		/// What opgen's sockets rest on in place of Linux's IP_BIND_ADDRESS_NO_PORT (section 2.4),
		/// tested before use as the IOCP pins are: SO_REUSE_UNICASTPORT is accepted before bind;
		/// explicit binds to two addresses of 127.0.0.0/8 may hold the same port, so each address
		/// of a block has a port space of its own; and a connection from a socket bound so arrives
		/// from that address. Pinned as read on W in M6b, not more: whether the option changes which
		/// port bind picks is not tested (bind still names a port at once, as getsockname shows).
		Result pin_reuse_unicastport()
		{
			const Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			std::uint16_t lport = 0;
			const SOCKET l = bound_socket(true, lport);
			CHECK(l != INVALID_SOCKET, "a listener");
			const SOCKET a = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
			const SOCKET b = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
			const BOOL one = TRUE;
			Result bad;
			if (::setsockopt(a, SOL_SOCKET, SO_REUSE_UNICASTPORT, reinterpret_cast<const char*>(&one), sizeof(one)) != 0)
			{
				bad = "SO_REUSE_UNICASTPORT refused: " + std::to_string(::WSAGetLastError());
			}
			sockaddr_in src = loopback_v4(0x7F000C21u, 0);  // 127.0.12.33
			if (!bad && ::bind(a, reinterpret_cast<sockaddr*>(&src), sizeof(src)) != 0) bad = "bind to 127.0.12.33:0 failed";
			int n = sizeof(src);
			::getsockname(a, reinterpret_cast<sockaddr*>(&src), &n);
			const std::uint16_t pa = ntohs(src.sin_port);
			if (!bad && pa == 0) bad = "no port after bind";
			// The same port on another address of the block.
			sockaddr_in other = loopback_v4(0x7F000C22u, pa);  // 127.0.12.34
			::setsockopt(b, SOL_SOCKET, SO_REUSE_UNICASTPORT, reinterpret_cast<const char*>(&one), sizeof(one));
			if (!bad && ::bind(b, reinterpret_cast<sockaddr*>(&other), sizeof(other)) != 0)
			{
				bad = "the same port on 127.0.12.34 refused: " + std::to_string(::WSAGetLastError());
			}
			sockaddr_in dst = loopback_v4(INADDR_LOOPBACK, lport);
			if (!bad && ::connect(a, reinterpret_cast<sockaddr*>(&dst), sizeof(dst)) != 0) bad = "connect from 127.0.12.33";
			if (!bad && ::connect(b, reinterpret_cast<sockaddr*>(&dst), sizeof(dst)) != 0) bad = "connect from 127.0.12.34 on the same port";
			std::set<std::uint32_t> peers;
			for (int k = 0; !bad && k < 2; ++k)
			{
				sockaddr_in peer{};
				int len = sizeof(peer);
				const SOCKET c = ::accept(l, reinterpret_cast<sockaddr*>(&peer), &len);
				if (c == INVALID_SOCKET) bad = "accept";
				else
				{
					if (ntohs(peer.sin_port) != pa) bad = "a peer port other than the bound one";
					peers.insert(ntohl(peer.sin_addr.s_addr));
					::closesocket(c);
				}
			}
			::closesocket(a);
			::closesocket(b);
			::closesocket(l);
			if (bad) return bad;
			CHECK(peers == (std::set<std::uint32_t>{0x7F000C21u, 0x7F000C22u}), "the two connections did not arrive from their bound addresses");
			return std::nullopt;
		}

		/// A program started with its standard output on a pipe, read by a thread.
		struct WinProcess
		{
			PROCESS_INFORMATION pi{};
			HANDLE out = nullptr;
			std::thread reader;
			std::mutex m;
			std::string text;
			bool started = false;

			bool start(const std::vector<std::string>& args)
			{
				SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
				HANDLE w = nullptr;
				if (!CreatePipe(&out, &w, &sa, 0)) return false;
				SetHandleInformation(out, HANDLE_FLAG_INHERIT, 0);
				STARTUPINFOA si{};
				si.cb = sizeof(si);
				si.dwFlags = STARTF_USESTDHANDLES;
				si.hStdOutput = w;
				si.hStdError = w;
				std::string cmd;
				for (const auto& a : args) cmd += (cmd.empty() ? "" : " ") + ("\"" + a + "\"");
				started = CreateProcessA(nullptr, cmd.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi) != 0;
				CloseHandle(w);
				if (!started) return false;
				reader = std::thread([this] {
					std::array<char, 4096> buf{};
					DWORD k = 0;
					while (ReadFile(out, buf.data(), static_cast<DWORD>(buf.size()), &k, nullptr) && k > 0)
					{
						std::lock_guard lock(m);
						text.append(buf.data(), k);
					}
				});
				return true;
			}

			std::string snapshot()
			{
				std::lock_guard lock(m);
				std::string t = text;
				std::erase(t, '\r');  // the C runtime's text-mode stdout ends lines with CRLF
				return t;
			}

			/// The number after the first `key` on a complete line, waiting at most 10 s.
			long value_after(const std::string& key)
			{
				for (int i = 0; i < 1000; ++i)
				{
					const std::string t = snapshot();
					const auto at = t.find(key);
					const auto eol = at == std::string::npos ? std::string::npos : t.find('\n', at);
					if (eol != std::string::npos) return std::stol(t.substr(at + key.size(), eol - at - key.size()));
					std::this_thread::sleep_for(10ms);
				}
				return -1;
			}

			/// Its exit code once it has ended (at most `ms`), and all it printed.
			int wait(DWORD ms = 60000)
			{
				if (!started) return -1;
				WaitForSingleObject(pi.hProcess, ms);
				DWORD code = 1;
				GetExitCodeProcess(pi.hProcess, &code);
				if (reader.joinable()) reader.join();
				CloseHandle(out);
				CloseHandle(pi.hThread);
				CloseHandle(pi.hProcess);
				started = false;
				return static_cast<int>(code);
			}

			~WinProcess()
			{
				if (started)
				{
					TerminateProcess(pi.hProcess, 99);  // only a program this test started, left running by a failed check
					wait(10000);
				}
			}
		};

		Result win_binaries()
		{
			const std::vector<std::string>& p = extra_paths();
			CHECK(!binary_path().empty() && p.size() == 1, "needs the oneport and opgen paths");
			const std::string& oneport = binary_path();
			const std::string& opgen = p[0];
			WinProcess server;
			CHECK(server.start({oneport, "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc", "--backend", "IOCP"}), "spawn oneport");
			const long port = server.value_after("oneport: listening HTTP/1.1 127.0.0.1:");
			CHECK(port > 0, "oneport printed no listening line");
			WinProcess probe;
			CHECK(probe.start({opgen, "--port", std::to_string(port), "--proto", "http1", "--probe"}), "spawn the probe");
			CHECK(probe.wait() == 0 && probe.snapshot().find("\"probe_detail\":\"http1: exchange completed\"") != std::string::npos, "the probe failed");
			WinProcess gen;
			CHECK(gen.start({opgen, "--port", std::to_string(port), "--proto", "http1", "--cpus", "2,3", "--conns", "2", "--warmup-ms", "50",
			                 "--duration-ms", "150", "--src-base", "127.0.12.1", "--k-src", "2"}),
			      "spawn opgen");
			CHECK(gen.wait() == 0, "opgen's exit");
			const std::string g = gen.snapshot();
			CHECK(g.find("MEASURE_START ") != std::string::npos && g.find("MEASURE_END ") != std::string::npos, "no markers");
			CHECK(g.find("\"ok\":true") != std::string::npos && g.find("\"connect_failures\":0") != std::string::npos, "the report");
			// The server stops on its event (bench/server/main.cpp), as the W window runner stops it.
			HANDLE stop = OpenEventW(EVENT_MODIFY_STATE, FALSE, (L"Local\\oneport-stop-" + std::to_wstring(server.pi.dwProcessId)).c_str());
			CHECK(stop != nullptr, "the server's stop event could not be opened");
			SetEvent(stop);
			CloseHandle(stop);
			CHECK(server.wait(30000) == 0, "oneport's exit");
			CHECK(server.snapshot().find("counter accepted ") != std::string::npos, "oneport printed no counters");
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
			r["gen.probe" + s] = on(probe);
		}
		r["gen.source_block"] = source_block;
		r["gen.failures"] = failures;
		r["gen.binaries"] = binaries;
#endif
#if defined(_WIN32) && defined(ONEPORT_HAVE_TLS)
		{
			const std::string s = ".IOCP";
			auto on = [](std::function<Result()> fn) {
				return [fn] {
					suite_backend() = Backend::iocp;
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
			r["gen.probe" + s] = on(probe);
			r["gen.source_block"] = win_source_block;
			r["gen.failures"] = win_failures;
			r["gen.pin_reuse_unicastport"] = pin_reuse_unicastport;
			r["gen.binaries"] = win_binaries;
		}
#endif
	}

}  // namespace oneport::test
