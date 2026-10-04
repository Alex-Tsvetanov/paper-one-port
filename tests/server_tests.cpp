// The server's functional tests on epoll (Linux): HTTP/1.1, both modes, the peek path's
// SO_RCVLOWAT, the check of 1(b) with a byte in the pass of the expiry, two workers on the shared
// listener and on SO_REUSEPORT, every flag combination served, and the binary itself. The other
// handlers have their own tests (tests/handler_tests.cpp).
// Untimed: no test measures a rate; the only times are the timers' bounds.
#include "test_support.hpp"

#if defined(__linux__)

#include "apps.hpp"
#include "cases.hpp"
#include "harness.hpp"
#include "http1.hpp"
#include "oneport/loop.hpp"
#include "run_cases.hpp"
#include "script.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <fstream>
#include <atomic>
#include <cerrno>
#include <cstring>
#include <spawn.h>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <linux/io_uring.h>
#include <linux/sockios.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
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

		Bytes cat(std::initializer_list<Bytes> parts) { return opcase::cat(parts); }

		Bytes repeat(std::string_view s, std::size_t n)
		{
			std::string r;
			for (std::size_t i = 0; i < n; ++i) r += s;
			return text(r);
		}

		/// Runs `s` and waits until the server has closed the connection; returns its reports.
		std::vector<server::DetectionReport> run_and_wait(Running& srv, const Script& s, std::uint16_t port, opcase::Transcript& t)
		{
			t = opcase::run(s, port);
			std::vector<server::DetectionReport> reps;
			srv.collector.wait_close(t.local_port, 10000ms, reps);
			return reps;
		}

		// ---- HTTP/1.1 keep-alive, pipelining and close, in both modes ----

		Result http_keepalive(Mode mode, Detect detect)
		{
			ServerArgs a;
			a.mode = mode;
			a.detect = detect;
			Running srv(a);
			Script s;
			s.write(kGetKeepAlive).gap(20ms).write(kGetKeepAlive).gap(20ms).write(cat({kGetKeepAlive, kGetKeepAlive})).gap(20ms).write(opcase::http_get());
			opcase::Transcript t;
			run_and_wait(srv, s, srv.port(), t);
			CHECK(t.received == repeat(http1::kResponse200, 5), "five 200 responses expected; got " << t.received.size() << " bytes");
			CHECK(t.eof && !t.reset, "the server closes after Connection: close");
			return srv.stop_and_check();
		}

		// ---- Dedicated mode: six consecutive ports, the handlers at accept ----

		Result dedicated_ports()
		{
			ServerArgs a;
			a.mode = Mode::dedicated;
			Running srv(a);
			const auto ports = srv.server->ports();
			const auto& specs = srv.server->listeners();
			CHECK(ports.size() == 6 && specs.size() == 6, "six listeners");
			const std::array<detect::Proto, 6> order{detect::Proto::http1, detect::Proto::h2c, detect::Proto::tls, detect::Proto::mqtt, detect::Proto::ssh, detect::Proto::smtp};
			for (std::size_t i = 0; i < 6; ++i)
			{
				CHECK(ports[i] == ports[0] + i, "port " << i << " is not consecutive");
				CHECK(!specs[i].detects && specs[i].proto == order[i], "listener " << i << " is " << specs[i].name);
			}
			opcase::Transcript t;
			run_and_wait(srv, Script{}.write(opcase::http_get()), ports[0], t);
			CHECK(t.received == text(http1::kResponse200) && t.eof, "the dedicated HTTP/1.1 port answers 200");
			// SSH and SMTP speak at accept (I26, I28); the others wait for the client's bytes.
			for (std::size_t i = 1; i < 6; ++i)
			{
				const bool speaks = order[i] == detect::Proto::ssh || order[i] == detect::Proto::smtp;
				run_and_wait(srv, speaks ? Script{}.await_line().shutdown_write() : Script{}.gap(100ms).shutdown_write(), ports[i], t);
				if (order[i] == detect::Proto::ssh) CHECK(t.received == text(apps::kSshBanner), "the SSH port says '" << opcase::first_line(t.received) << "'");
				if (order[i] == detect::Proto::smtp) CHECK(t.received == text(apps::kSmtpGreeting), "the SMTP port says '" << opcase::first_line(t.received) << "'");
				if (!speaks)
				{
					// Nothing before the client's EOF; h2c may then send its SETTINGS as it closes.
					CHECK(!t.first_byte || *t.first_byte - t.after_connect >= 100ms, "port " << i << " spoke before the client");
				}
				CHECK(t.eof, "port " << i << " closes after the client's EOF");
			}
			return srv.stop_and_check();
		}

		/// Dedicated mode with PROXY on: T_hdr in the deadline queue (the pilot's timer part).
		Result dedicated_proxy()
		{
			ServerArgs a;
			a.mode = Mode::dedicated;
			a.proxy = Proxy::on;
			a.t_hdr = 200ms;
			Running srv(a);
			opcase::Transcript t;
			auto reps = run_and_wait(srv, Script{}.write(opcase::slice(opcase::proxy_v2(), 0, 10)).await_close(), srv.port(), t);
			CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::proxy_timeout, "an incomplete header is closed at T_hdr");
			CHECK(reps[0].timed && reps[0].event.kind == server::TimerKind::t_hdr, "by the T_hdr expiry");
			if (auto bad = srv.check_timed(reps[0].event)) return bad;
			CHECK(t.end && *t.end - t.before_connect >= a.t_hdr, "the client saw the close before T_hdr");
			reps = run_and_wait(srv, Script{}.write(cat({opcase::proxy_v2(), opcase::http_get()})), srv.port(), t);
			CHECK(reps.empty(), "a complete header ends no detection on a dedicated port");
			CHECK(t.received == text(http1::kResponse200), "the request after the header is answered");
			run_and_wait(srv, Script{}.write(opcase::proxy_v2()).await_line().shutdown_write(), srv.port_of(detect::Proto::smtp), t);
			CHECK(t.received == text(apps::kSmtpGreeting), "the SMTP handler greets once the header is complete");
			return srv.stop_and_check();
		}

		// ---- Peek: SO_RCVLOWAT ----

		/// A drip below the low-water mark wakes nothing in peek mode (I11), and every drip wakes
		/// replay mode.
		Result peek_lowat(Detect detect)
		{
			ServerArgs a;
			a.detect = detect;
			a.t_dec = 5000ms;
			Running srv(a);
			const Bytes all = opcase::h2c_opening();
			Script s;
			s.write(opcase::slice(all, 0, 16));
			for (std::size_t i = 16; i < 24; ++i) s.gap(30ms).write(opcase::slice(all, i, i + 1));
			s.gap(30ms).write(opcase::slice(all, 24, all.size())).shutdown_write();
			opcase::Transcript t;
			const auto reps = run_and_wait(srv, s, srv.port(), t);
			CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::classified && reps[0].proto == detect::Proto::h2c, "classified h2c");
			const auto& r = reps[0];
			if (detect == Detect::peek)
			{
				CHECK(r.wakeups == 2, "peek: " << r.wakeups << " wakeups; 2 expected (16 bytes, then the 24th)");
				CHECK(r.lowat_sets == 1 && r.lowat_resets == 1, "peek: SO_RCVLOWAT set " << r.lowat_sets << ", reset " << r.lowat_resets);
				CHECK(r.max_user_bytes == 0, "peek holds no payload in user space");
			}
			else
			{
				CHECK(r.wakeups >= 3, "replay: " << r.wakeups << " wakeups; each drip should wake it");
				CHECK(r.lowat_sets == 0 && r.lowat_resets == 0, "replay never sets SO_RCVLOWAT");
			}
			if (auto bad = srv.stop_and_check()) return bad;
			const server::Counters c = srv.server->totals();
			CHECK(c.setsockopt_calls == c.lowat_sets + c.lowat_resets, "every setsockopt is a set or a reset");
			return std::nullopt;
		}

		/// The kernel behaviour the peek path rests on, pinned on L's kernel (proposal RK4, I11):
		/// with edge-triggered epoll, setting SO_RCVLOWAT at or below the queued bytes raises an
		/// event; above them, data that stays below the mark raises none; reaching the mark does;
		/// and a half-close is reported whatever the mark.
		Result kernel_rcvlowat_et()
		{
			const int l = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			sockaddr_in addr{};
			addr.sin_family = AF_INET;
			addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			CHECK(::bind(l, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0 && ::listen(l, 1) == 0, "listen");
			socklen_t n = sizeof(addr);
			::getsockname(l, reinterpret_cast<sockaddr*>(&addr), &n);
			const int c = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			const int one = 1;
			::setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
			CHECK(::connect(c, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
			const int s = ::accept4(l, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
			CHECK(s >= 0, "accept");
			const int ep = ::epoll_create1(EPOLL_CLOEXEC);
			epoll_event ev{};
			ev.events = EPOLLIN | EPOLLRDHUP | EPOLLET;
			CHECK(::epoll_ctl(ep, EPOLL_CTL_ADD, s, &ev) == 0, "epoll_ctl");
			auto wait = [ep](int ms) {
				std::array<epoll_event, 4> out{};
				const int k = ::epoll_wait(ep, out.data(), static_cast<int>(out.size()), ms);
				return k > 0 ? out[0].events : 0u;
			};
			auto lowat = [s](int v) { return ::setsockopt(s, SOL_SOCKET, SO_RCVLOWAT, &v, sizeof(v)) == 0; };
			const std::array<char, 10> ten{};
			CHECK(::send(c, ten.data(), ten.size(), 0) == 10, "send");
			CHECK((wait(1000) & EPOLLIN) != 0, "10 bytes raise an event");
			CHECK(wait(0) == 0, "edge-triggered: no second event for the same bytes");
			CHECK(lowat(5), "SO_RCVLOWAT 5");
			CHECK((wait(1000) & EPOLLIN) != 0, "setting the mark at or below the queued bytes raises an event");
			CHECK(lowat(30), "SO_RCVLOWAT 30");
			CHECK(wait(0) == 0, "a mark above the queued bytes raises none");
			CHECK(::send(c, ten.data(), ten.size(), 0) == 10, "send");
			CHECK(wait(100) == 0, "20 bytes below a mark of 30 raise no event");
			CHECK(::send(c, ten.data(), ten.size(), 0) == 10, "send");
			CHECK((wait(1000) & EPOLLIN) != 0, "30 bytes reach the mark");
			CHECK(lowat(100), "SO_RCVLOWAT 100");
			::shutdown(c, SHUT_WR);
			CHECK((wait(1000) & EPOLLRDHUP) != 0, "a half-close is reported above the mark");
			::close(ep);
			::close(s);
			::close(c);
			::close(l);
			return std::nullopt;
		}

		/// The kernel behaviour the relay's listener rests on (M5), pinned on L's kernel: a socket
		/// accepted from a listener with TCP_NODELAY has it set, and one from a listener without it
		/// has not. Pinned through accept4; io_uring's accept hands out the same child socket the
		/// kernel made at the handshake.
		Result kernel_nodelay_inherited()
		{
			for (const bool set : {true, false})
			{
				const int l = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				sockaddr_in addr{};
				addr.sin_family = AF_INET;
				addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				CHECK(::bind(l, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0 && ::listen(l, 1) == 0, "listen");
				const int one = 1;
				if (set) CHECK(::setsockopt(l, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one)) == 0, "TCP_NODELAY on the listener");
				socklen_t n = sizeof(addr);
				::getsockname(l, reinterpret_cast<sockaddr*>(&addr), &n);
				const int c = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				CHECK(::connect(c, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
				const int s = ::accept4(l, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
				CHECK(s >= 0, "accept");
				int v = -1;
				socklen_t vn = sizeof(v);
				CHECK(::getsockopt(s, IPPROTO_TCP, TCP_NODELAY, &v, &vn) == 0, "getsockopt");
				CHECK((v != 0) == set, "the accepted socket's TCP_NODELAY is " << v << " from a listener " << (set ? "with" : "without") << " it");
				::close(s);
				::close(c);
				::close(l);
			}
			return std::nullopt;
		}

		/// A connected pair over loopback: the client `c` (blocking, TCP_NODELAY) and the server's
		/// accepted socket `s` (non-blocking). Closes all three on scope exit.
		struct Pair
		{
			int l = -1;
			int c = -1;
			int s = -1;
			Pair()
			{
				l = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				sockaddr_in addr{};
				addr.sin_family = AF_INET;
				addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				if (::bind(l, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0 || ::listen(l, 8) != 0) return;
				socklen_t n = sizeof(addr);
				::getsockname(l, reinterpret_cast<sockaddr*>(&addr), &n);
				port = ntohs(addr.sin_port);
				c = connect_client();
				s = ::accept4(l, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
			}
			~Pair()
			{
				for (const int fd : {s, c, l})
				{
					if (fd >= 0) ::close(fd);
				}
			}
			Pair(const Pair&) = delete;
			Pair& operator=(const Pair&) = delete;
			int connect_client() const
			{
				const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				const int one = 1;
				::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
				sockaddr_in addr{};
				addr.sin_family = AF_INET;
				addr.sin_port = htons(port);
				addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0)
				{
					::close(fd);
					return -1;
				}
				return fd;
			}
			bool ok() const { return l >= 0 && c >= 0 && s >= 0; }
			std::uint16_t port = 0;
		};

		/// The completions of `ring` with user_data `ud` within `bound`, waiting pass by pass.
		std::vector<loop::Completion> completions_of(loop::UringLoop& ring, std::uint64_t ud, std::chrono::milliseconds bound, std::size_t want = 1)
		{
			std::vector<loop::Completion> got;
			const auto until = std::chrono::steady_clock::now() + bound;
			while (got.size() < want)
			{
				const auto now = std::chrono::steady_clock::now();
				if (now >= until) break;
				for (const loop::Completion& x : ring.wait(std::chrono::duration_cast<std::chrono::nanoseconds>(until - now)))
				{
					if (x.user_data == ud) got.push_back(x);
				}
			}
			return got;
		}

		/// The io_uring peek path's kernel behaviour, pinned on L's kernel before the backend uses
		/// it (proposal I11 and RK4): an IORING_OP_POLL_ADD for POLLIN | POLLRDHUP on a TCP socket
		/// completes at once when bytes are queued and SO_RCVLOWAT is at or below them; after an
		/// undecided peek sets the mark above the queued bytes, a poll armed again does not
		/// complete at once, bytes that stay below the mark complete nothing, reaching the mark
		/// completes it with POLLIN, and a half-close completes it with POLLRDHUP whatever the mark.
		/// If this test fails, io_uring takes IOCP's rule (RK4): an undecided peek switches the
		/// connection to replay.
		Result kernel_rcvlowat_uring()
		{
			Pair p;
			CHECK(p.ok(), "a loopback pair");
			loop::UringLoop ring;
			ring.start();
			auto lowat = [&p](int v) { return ::setsockopt(p.s, SOL_SOCKET, SO_RCVLOWAT, &v, sizeof(v)) == 0; };
			auto peeked = [&p] {
				std::array<char, 128> buf{};
				return ::recv(p.s, buf.data(), buf.size(), MSG_PEEK | MSG_DONTWAIT);
			};
			const std::array<char, 10> ten{};
			constexpr std::uint32_t kMask = POLLIN | POLLRDHUP;
			CHECK(::send(p.c, ten.data(), ten.size(), 0) == 10, "send");
			ring.poll(p.s, kMask, 1);
			auto got = completions_of(ring, 1, 1000ms);
			CHECK(got.size() == 1 && (got[0].res & POLLIN) != 0, "10 queued bytes complete the first poll with POLLIN");
			CHECK(peeked() == 10, "the peek sees the 10 bytes");
			// The peek is undecided: the mark goes above the queued bytes and the poll is armed again.
			CHECK(lowat(30), "SO_RCVLOWAT 30");
			ring.poll(p.s, kMask, 2);
			CHECK(completions_of(ring, 2, 200ms).empty(), "the poll armed again after an undecided peek completed at once (the mark is above the queued bytes)");
			CHECK(::send(p.c, ten.data(), ten.size(), 0) == 10, "send");
			CHECK(completions_of(ring, 2, 200ms).empty(), "20 bytes below a mark of 30 completed the poll");
			CHECK(::send(p.c, ten.data(), ten.size(), 0) == 10, "send");
			got = completions_of(ring, 2, 1000ms);
			CHECK(got.size() == 1 && (got[0].res & POLLIN) != 0 && (got[0].res & POLLRDHUP) == 0, "30 bytes reach the mark: POLLIN, no POLLRDHUP");
			CHECK(peeked() == 30, "the peek sees the 30 bytes");
			// A half-close is reported above the mark.
			CHECK(lowat(100), "SO_RCVLOWAT 100");
			ring.poll(p.s, kMask, 3);
			CHECK(completions_of(ring, 3, 100ms).empty(), "30 bytes below a mark of 100 completed the poll");
			::shutdown(p.c, SHUT_WR);
			got = completions_of(ring, 3, 1000ms);
			CHECK(got.size() == 1 && (got[0].res & POLLRDHUP) != 0, "a half-close completes the poll with POLLRDHUP above the mark");
			// Reset before the handler reads, as the server does: the bytes, then EOF.
			CHECK(lowat(1), "SO_RCVLOWAT 1");
			std::array<char, 128> buf{};
			CHECK(::recv(p.s, buf.data(), buf.size(), MSG_DONTWAIT) == 30, "the handler reads the 30 bytes");
			CHECK(::recv(p.s, buf.data(), buf.size(), MSG_DONTWAIT) == 0, "then the EOF");
			CHECK(ring.submissions()[IORING_OP_POLL_ADD] >= 4, "the polls are counted by opcode");
			return std::nullopt;
		}

		/// The rest of the io_uring behaviour the backend rests on, pinned on L's kernel: a receive
		/// (IORING_OP_READ on the socket since M5) that selects a provided buffer holds none until
		/// data arrives, and then names it; with the ring empty it fails with ENOBUFS and the bytes
		/// stay queued; at EOF it returns 0, and if it names a buffer (io_uring/rw.c at v7.2.6 puts a
		/// selected buffer for 0 bytes too) the buffer is one of the ring's, which the backend gives
		/// back to its pool (uring.cpp, take_recv); a multishot accept completes once per
		/// connection, flagged IORING_CQE_F_MORE.
		Result kernel_uring_recv_select()
		{
			Pair p;
			CHECK(p.ok(), "a loopback pair");
			loop::UringLoop ring;
			ring.start();
			constexpr std::uint16_t kGroup = 1;
			ring.add_buffer_ring(kGroup, 4);
			std::array<std::array<char, 64>, 2> bufs{};
			ring.provide(kGroup, bufs[0].data(), 64, 0);
			ring.provide(kGroup, bufs[1].data(), 64, 1);
			auto bid_of = [](const loop::Completion& x) { return static_cast<int>(x.flags >> IORING_CQE_BUFFER_SHIFT); };
			ring.recv_select(p.s, kGroup, 1);
			CHECK(completions_of(ring, 1, 100ms).empty(), "a receive completed with no data");
			const std::string first = "0123456789";
			CHECK(::send(p.c, first.data(), first.size(), 0) == 10, "send");
			auto got = completions_of(ring, 1, 1000ms);
			CHECK(got.size() == 1 && got[0].res == 10 && (got[0].flags & IORING_CQE_F_BUFFER) != 0, "10 bytes in a selected buffer");
			const int b0 = bid_of(got[0]);
			CHECK(b0 == 0 || b0 == 1, "the buffer id is one provided");
			CHECK(std::string(bufs[static_cast<std::size_t>(b0)].data(), 10) == first, "the bytes are in the buffer the completion names");
			ring.recv_select(p.s, kGroup, 2);
			CHECK(::send(p.c, "abcde", 5, 0) == 5, "send");
			got = completions_of(ring, 2, 1000ms);
			CHECK(got.size() == 1 && got[0].res == 5 && (got[0].flags & IORING_CQE_F_BUFFER) != 0 && bid_of(got[0]) == 1 - b0, "5 bytes in the other buffer");
			// The ring is empty.
			ring.recv_select(p.s, kGroup, 3);
			CHECK(::send(p.c, "xyz", 3, 0) == 3, "send");
			got = completions_of(ring, 3, 1000ms);
			CHECK(got.size() == 1 && got[0].res == -ENOBUFS && (got[0].flags & IORING_CQE_F_BUFFER) == 0, "an empty ring fails the receive with ENOBUFS (res " << (got.empty() ? 0 : got[0].res) << ")");
			ring.provide(kGroup, bufs[0].data(), 64, 0);
			ring.recv_select(p.s, kGroup, 4);
			got = completions_of(ring, 4, 1000ms);
			CHECK(got.size() == 1 && got[0].res == 3 && bid_of(got[0]) == 0, "the 3 bytes stayed queued for the next receive");
			// EOF.
			ring.provide(kGroup, bufs[1].data(), 64, 1);
			ring.recv_select(p.s, kGroup, 5);
			::shutdown(p.c, SHUT_WR);
			got = completions_of(ring, 5, 1000ms);
			CHECK(got.size() == 1 && got[0].res == 0, "EOF completes the receive with 0");
			CHECK((got[0].flags & IORING_CQE_F_BUFFER) == 0 || bid_of(got[0]) == 1, "at EOF the completion named a buffer the ring did not hold");
			// Multishot accept.
			ring.accept_multishot(p.l, 9);
			const int c1 = p.connect_client();
			const int c2 = p.connect_client();
			got = completions_of(ring, 9, 1000ms, 2);
			for (const int fd : {c1, c2})
			{
				if (fd >= 0) ::close(fd);
			}
			CHECK(got.size() == 2, "two connections, two accept completions");
			for (const loop::Completion& x : got)
			{
				CHECK(x.res >= 0 && (x.flags & IORING_CQE_F_MORE) != 0, "an accept completion with a descriptor, still armed");
				::close(x.res);
			}
			CHECK(ring.enter_calls() > 0 && ring.submissions()[IORING_OP_READ] == 5 && ring.submissions()[IORING_OP_RECV] == 0 && ring.submissions()[IORING_OP_ACCEPT] == 1,
			      "the counters");
			return std::nullopt;
		}

		// ---- The check of 1(b), with a byte in the pass of the expiry ----

		struct ByteInExpiryPass
		{
			std::atomic<int> client{-1};
			std::atomic<bool> fired{false};
			static void hook(void* ctx, unsigned, server::TimePoint wait_return, std::optional<server::TimePoint> earliest)
			{
				auto* self = static_cast<ByteInExpiryPass*>(ctx);
				if (self->fired.load() || !earliest || *earliest > wait_return) return;
				// This pass handles an expiry: the request reaches the socket now, after the pass's
				// readiness events and before its expiries. Wait until the server's side holds it.
				const Bytes req = opcase::http_get();
				const int fd = self->client.load();
				if (fd < 0) return;
				if (::send(fd, req.data(), req.size(), MSG_NOSIGNAL) != static_cast<ssize_t>(req.size())) return;
				for (int i = 0; i < 1000; ++i)
				{
					int unacked = 0;
					if (::ioctl(fd, SIOCOUTQ, &unacked) == 0 && unacked == 0) break;
					std::this_thread::sleep_for(1ms);
				}
				self->fired.store(true);
			}
		};

		Result check_byte_wins(Detect detect)
		{
			ByteInExpiryPass ctx;
			ServerArgs a;
			a.detect = detect;
			a.fallback = Fallback::smtp;
			server::Hooks extra;
			extra.ctx = &ctx;
			extra.before_expiries = &ByteInExpiryPass::hook;
			Running srv(a, extra);
			const int client = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			sockaddr_in addr{};
			addr.sin_family = AF_INET;
			addr.sin_port = htons(srv.port());
			addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			const int one = 1;
			::setsockopt(client, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
			CHECK(::connect(client, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
			ctx.client.store(client);
			sockaddr_in local{};
			socklen_t n = sizeof(local);
			::getsockname(client, reinterpret_cast<sockaddr*>(&local), &n);
			std::string got;
			for (;;)
			{
				pollfd p{client, POLLIN, 0};
				if (::poll(&p, 1, 5000) <= 0) break;
				std::array<char, 512> buf{};
				const ssize_t k = ::recv(client, buf.data(), buf.size(), 0);
				if (k <= 0) break;
				got.append(buf.data(), static_cast<std::size_t>(k));
			}
			std::vector<server::DetectionReport> reps;
			srv.collector.wait_close(ntohs(local.sin_port), 10000ms, reps);
			CHECK(ctx.fired.load(), "the hook never saw a pass with an expiry");
			CHECK(got == http1::kResponse200, "the byte won: the request is answered 200, not by the fallback");
			CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::classified && reps[0].proto == detect::Proto::http1, "classified HTTP/1.1");
			if (auto bad = srv.stop_and_check()) return bad;
			const server::Counters c = srv.server->totals();
			::close(client);
			CHECK(c.check_calls == 1 && c.check_found_byte == 1, "one check, which found the byte (" << c.check_calls << ", " << c.check_found_byte << ")");
			bool byte_won = false;
			for (const auto& ev : c.timed) byte_won = byte_won || (ev.kind == server::TimerKind::t_fb && ev.result == server::TimerResult::byte_won);
			CHECK(byte_won, "the T_fb event records that the byte won");
			CHECK(c.fallback[static_cast<std::size_t>(detect::Proto::smtp)] == 0, "no fallback dispatch");
			return std::nullopt;
		}

		// ---- Two workers ----

		Result two_workers(Listener listener, Detect detect)
		{
			ServerArgs a;
			a.workers = 2;
			a.listener = listener;
			a.detect = detect;
			Running srv(a);
			constexpr int kThreads = 8;
			constexpr int kEach = 25;
			std::atomic<int> ok{0};
			std::vector<std::thread> threads;
			const std::uint16_t port = srv.port();
			for (int i = 0; i < kThreads; ++i)
			{
				threads.emplace_back([&ok, port] {
					for (int j = 0; j < kEach; ++j)
					{
						const auto t = opcase::run(Script{}.write(opcase::http_get()), port);
						if (t.received == text(http1::kResponse200) && t.eof) ok.fetch_add(1);
					}
				});
			}
			for (auto& t : threads) t.join();
			CHECK(ok.load() == kThreads * kEach, ok.load() << " of " << kThreads * kEach << " exchanges answered 200");
			if (auto bad = srv.stop_and_check()) return bad;
			const auto per = srv.server->per_worker();
			CHECK(per.size() == 2, "two workers");
			const server::Counters c = srv.server->totals();
			CHECK(c.accepted == kThreads * kEach && c.classified[static_cast<std::size_t>(detect::Proto::http1)] == kThreads * kEach, "every connection classified once");
			return std::nullopt;
		}

		// ---- Every flag combination served ----

		Result flag_matrix()
		{
			int combos = 0;
			for (const Mode mode : {Mode::one_port, Mode::dedicated})
				for (const Detect detect : {Detect::replay, Detect::peek})
					for (const Proxy proxy : {Proxy::off, Proxy::on})
						for (const Fallback fallback : {Fallback::none, Fallback::smtp, Fallback::ssh})
							for (const Listener listener : {Listener::shared, Listener::reuseport})
								for (const std::uint32_t workers : {1u, 2u})
								{
									ServerArgs a;
									a.mode = mode;
									a.detect = detect;
									a.proxy = proxy;
									a.fallback = fallback;
									a.listener = listener;
									a.workers = workers;
									a.t_fb = a.t_dec = a.t_hdr = 100ms;
									const std::string what = std::string(token(mode)) + " " + std::string(token(detect)) + (proxy == Proxy::on ? " proxy" : "") +
									                         (fallback == Fallback::smtp ? " SMTP" : fallback == Fallback::ssh ? " SSH" : "") +
									                         (listener == Listener::reuseport ? " reuseport" : "") + " workers " + std::to_string(workers);
									Running srv(a);
									const Bytes header = proxy == Proxy::on ? opcase::proxy_v2() : Bytes{};
									opcase::Transcript t;
									run_and_wait(srv, Script{}.write(cat({header, opcase::http_get()})), srv.port(), t);
									CHECK(t.received == text(http1::kResponse200) && t.eof, what << ": no 200");
									if (mode == Mode::one_port && fallback != Fallback::none)
									{
										run_and_wait(srv, Script{}.write(header).await_line().shutdown_write(), srv.port(), t);
										const std::string_view want = fallback == Fallback::smtp ? apps::kSmtpGreeting : apps::kSshBanner;
										CHECK(t.received == text(want), what << ": a silent client does not reach the fallback");
										CHECK(t.first_byte && *t.first_byte - t.before_connect >= a.t_fb, what << ": the fallback spoke before T_fb");
									}
									if (mode == Mode::dedicated)
									{
										run_and_wait(srv, Script{}.write(header).await_line().shutdown_write(), srv.port_of(detect::Proto::smtp), t);
										CHECK(t.received == text(apps::kSmtpGreeting), what << ": the SMTP port");
									}
									if (auto bad = srv.stop_and_check()) return std::string(what + ": " + *bad);
									++combos;
								}
			CHECK(combos == 96, combos << " combinations");
			return std::nullopt;
		}

		// ---- Stop with a pending connection; configurations not served yet ----

		Result stop_with_pending()
		{
			ServerArgs a;
			a.t_fb = a.t_dec = 10000ms;
			Running srv(a);
			const int c = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
			sockaddr_in addr{};
			addr.sin_family = AF_INET;
			addr.sin_port = htons(srv.port());
			addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			CHECK(::connect(c, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
			std::this_thread::sleep_for(100ms);
			if (auto bad = srv.stop_and_check()) return bad;
			::close(c);
			const server::Counters t = srv.server->totals();
			CHECK(t.outcomes[static_cast<std::size_t>(server::Outcome::stopped)] == 1, "the pending connection is counted stopped");
			return std::nullopt;
		}

		/// Since M2b every Linux arm is served: both backends, every mode, both dispatch modes.
		/// IOCP waits for M6.
		Result not_served()
		{
			Config c = make_config(ServerArgs{});
			for (const Backend b : {Backend::epoll, Backend::io_uring})
				for (const Mode m : {Mode::one_port, Mode::dedicated, Mode::stub})
					for (const Dispatch d : {Dispatch::inproc, Dispatch::relay})
					{
						c.backend = b;
						c.mode = m;
						c.dispatch = d;
						CHECK(!server::not_served(c), token(m) << " " << token(d) << " on " << token(b) << " is not served");
					}
			c.backend = Backend::iocp;
			CHECK(server::not_served(c) == std::optional<std::string>("the IOCP backend is M6 (Windows)"), "IOCP");
			bool refused = false;
			try
			{
				server::Server s(c);
			}
			catch (const std::invalid_argument&)
			{
				refused = true;
			}
			CHECK(refused, "the server refuses a configuration not served yet");
			CHECK(server::Server::conn_state_bytes() > 0, "the connection state has a size");
			return std::nullopt;
		}

		// ---- The binary ----

		Result binary_smoke()
		{
			const std::string& path = binary_path();
			CHECK(!path.empty(), "no binary path given");
			int out[2];
			CHECK(::pipe(out) == 0, "pipe");
			posix_spawn_file_actions_t fa;
			posix_spawn_file_actions_init(&fa);
			posix_spawn_file_actions_adddup2(&fa, out[1], 1);
			posix_spawn_file_actions_addclose(&fa, out[0]);
			std::vector<std::string> args{path, "--mode", "one-port", "--detect", "peek", "--dispatch", "inproc", "--backend", std::string(token(suite_backend()))};
			std::vector<char*> argv;
			for (auto& s : args) argv.push_back(s.data());
			argv.push_back(nullptr);
			pid_t pid = 0;
			const int rc = posix_spawn(&pid, path.c_str(), &fa, nullptr, argv.data(), environ);
			posix_spawn_file_actions_destroy(&fa);
			::close(out[1]);
			CHECK(rc == 0, "posix_spawn: " << std::strerror(rc));
			std::string text_out;
			std::uint16_t port = 0;
			auto read_more = [&](int ms) {
				pollfd p{out[0], POLLIN, 0};
				if (::poll(&p, 1, ms) <= 0) return false;
				std::array<char, 4096> buf{};
				const ssize_t k = ::read(out[0], buf.data(), buf.size());
				if (k <= 0) return false;
				text_out.append(buf.data(), static_cast<std::size_t>(k));
				return true;
			};
			const std::string key = "oneport: listening one-port 127.0.0.1:";
			while (port == 0 && read_more(10000))
			{
				const auto at = text_out.find(key);
				const auto eol = at == std::string::npos ? std::string::npos : text_out.find('\n', at);
				if (eol != std::string::npos) port = static_cast<std::uint16_t>(std::stoi(text_out.substr(at + key.size(), eol - at - key.size())));
			}
			Result r;
			if (port == 0)
			{
				r = "the binary printed no listening line";
			}
			else
			{
				const auto t = opcase::run(Script{}.write(opcase::http_get()), port);
				if (t.received != text(http1::kResponse200)) r = "the binary did not answer 200";
			}
			::kill(pid, SIGTERM);
			while (read_more(10000))
			{
			}
			int status = 0;
			::waitpid(pid, &status, 0);
			::close(out[0]);
			if (r) return r;
			CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 0, "the binary did not exit 0 after SIGTERM");
			CHECK(text_out.find("counter accepted 1\n") != std::string::npos, "the counters do not show one connection");
			CHECK(text_out.find("counter classified HTTP/1.1 1\n") != std::string::npos, "the counters do not show the classification");
			CHECK(text_out.find("oneport: connection state ") != std::string::npos, "no connection-state size line");
			return std::nullopt;
		}

		/// opcase case's line (M5): HC1's HTTP/1.1 variant against the server by port, its frozen
		/// expectation and its transcript in one JSON line.
		Result cases_by_port()
		{
			ServerArgs args;
			Running srv(args);
			const std::vector<opcase::Variant> vs = opcase::variants(1, opcase::SuiteParams{});
			const auto it = std::find_if(vs.begin(), vs.end(), [](const opcase::Variant& v) { return v.proto == detect::Proto::http1; });
			CHECK(it != vs.end(), "HC1 has an HTTP/1.1 variant");
			const opcase::Transcript t = opcase::run(it->script, srv.port());
			std::vector<server::DetectionReport> reps;
			srv.collector.wait_close(t.local_port, 10000ms, reps);
			const std::string ln = opcase::run_line(*it, 1, 1, srv.port(), t);
			for (const std::string& want : {std::string("\"id\": \"") + it->id + "\"", std::string("\"expect\": \"classified\""),
			                               std::string("\"proto\": \"HTTP/1.1\""), std::string("\"connected\": true"),
			                               std::string("\"local_port\": ") + std::to_string(t.local_port), std::string("485454502f312e3120323030")})
			{
				CHECK(ln.find(want) != std::string::npos, "the line lacks " << want << ": " << ln.substr(0, 400));
			}
			return srv.stop_and_check();
		}

		/// The binary's decision record (--record; WL8, M5): one HTTP/1.1 exchange, then SIGTERM; the
		/// record holds the connection's detection line, keyed by the client's local port, with its
		/// accept and decision on opcase's clock (after the client's connect began, the decision no
		/// earlier than its write), and its close line.
		Result binary_record()
		{
			const std::string& path = binary_path();
			CHECK(!path.empty(), "no binary path given");
			char tmpl[] = "/tmp/oneport-record-XXXXXX";
			const int tf = ::mkstemp(tmpl);
			CHECK(tf >= 0, "mkstemp");
			::close(tf);
			const std::string record = tmpl;
			int out[2];
			CHECK(::pipe(out) == 0, "pipe");
			posix_spawn_file_actions_t fa;
			posix_spawn_file_actions_init(&fa);
			posix_spawn_file_actions_adddup2(&fa, out[1], 1);
			posix_spawn_file_actions_addclose(&fa, out[0]);
			std::vector<std::string> args{path, "--mode", "one-port", "--detect", "replay", "--dispatch", "inproc", "--backend",
			                              std::string(token(suite_backend())), "--record", record};
			std::vector<char*> argv;
			for (auto& s : args) argv.push_back(s.data());
			argv.push_back(nullptr);
			pid_t pid = 0;
			const int rc = posix_spawn(&pid, path.c_str(), &fa, nullptr, argv.data(), environ);
			posix_spawn_file_actions_destroy(&fa);
			::close(out[1]);
			CHECK(rc == 0, "posix_spawn: " << std::strerror(rc));
			std::string text_out;
			std::uint16_t port = 0;
			auto read_more = [&](int ms) {
				pollfd p{out[0], POLLIN, 0};
				if (::poll(&p, 1, ms) <= 0) return false;
				std::array<char, 4096> buf{};
				const ssize_t k = ::read(out[0], buf.data(), buf.size());
				if (k <= 0) return false;
				text_out.append(buf.data(), static_cast<std::size_t>(k));
				return true;
			};
			const std::string key = "oneport: listening one-port 127.0.0.1:";
			while (port == 0 && read_more(10000))
			{
				const auto at = text_out.find(key);
				const auto eol = at == std::string::npos ? std::string::npos : text_out.find('\n', at);
				if (eol != std::string::npos) port = static_cast<std::uint16_t>(std::stoi(text_out.substr(at + key.size(), eol - at - key.size())));
			}
			opcase::Transcript t;
			if (port != 0) t = opcase::run(Script{}.write(opcase::http_get()), port);
			// The connection's lines reach the file while the server still runs (M7c: a runner reads
			// them then, bench/run/hardcase_run.py and pilot_run.py's timer part).
			bool closed_before_stop = false;
			const std::string closed_key = "\"event\": \"closed\"";
			const std::string peer_key = "\"peer_port\": " + std::to_string(t.local_port) + ",";
			for (int i = 0; i < 250 && port != 0 && !closed_before_stop; ++i)
			{
				std::ifstream g(record);
				for (std::string ln; std::getline(g, ln);)
				{
					if (ln.find(closed_key) != std::string::npos && ln.find(peer_key) != std::string::npos) closed_before_stop = true;
				}
				if (!closed_before_stop) std::this_thread::sleep_for(std::chrono::milliseconds(20));
			}
			::kill(pid, SIGTERM);
			while (read_more(10000))
			{
			}
			int status = 0;
			::waitpid(pid, &status, 0);
			::close(out[0]);
			std::ifstream f(record);
			std::vector<std::string> lines;
			for (std::string ln; std::getline(f, ln);) lines.push_back(ln);
			::unlink(record.c_str());
			CHECK(port != 0, "the binary printed no listening line");
			CHECK(t.received == text(http1::kResponse200) && !t.write_times.empty(), "the binary did not answer 200");
			CHECK(closed_before_stop, "the record's close line did not reach the file while the server ran");
			CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 0, "the binary did not exit 0 after SIGTERM");
			auto field = [](const std::string& ln, const std::string& k) -> std::string {
				const auto at = ln.find("\"" + k + "\": ");
				if (at == std::string::npos) return {};
				const auto from = at + k.size() + 4;
				const auto to = ln.find_first_of(",}", from);
				return ln.substr(from, to - from);
			};
			const std::string peer = std::to_string(t.local_port);
			const auto ns_of = [](opcase::TimePoint tp) { return std::chrono::duration_cast<std::chrono::nanoseconds>(tp.time_since_epoch()).count(); };
			std::size_t detections = 0;
			std::size_t closes = 0;
			for (const std::string& ln : lines)
			{
				if (field(ln, "peer_port") != peer) continue;
				if (field(ln, "event") == "\"detection\"")
				{
					++detections;
					CHECK(field(ln, "outcome") == "\"classified\"" && field(ln, "proto") == "\"HTTP/1.1\"", "the detection line: " << ln);
					const long long accept_ns = std::stoll(field(ln, "accept_ns"));
					const long long end_ns = std::stoll(field(ln, "end_ns"));
					CHECK(accept_ns >= ns_of(t.before_connect) && end_ns >= ns_of(t.write_times.front()) && end_ns >= accept_ns,
					      "the record's times are not on opcase's clock: " << ln);
				}
				if (field(ln, "event") == "\"closed\"") ++closes;
			}
			CHECK(detections == 1 && closes == 1, detections << " detection and " << closes << " close lines for the connection in " << lines.size() << " lines");
			return std::nullopt;
		}

	}  // namespace

	void register_server_tests(Registry& r)
	{
		// Once per Linux backend, named with it last; the kernel pins and not_served once.
		for (const Backend b : {Backend::epoll, Backend::io_uring})
		{
			const std::string s = "." + std::string(token(b));
			auto on = [b](std::function<Result()> fn) {
				return [b, fn] {
					suite_backend() = b;
					return fn();
				};
			};
			r["server.http_keepalive.oneport_replay" + s] = on([] { return http_keepalive(Mode::one_port, Detect::replay); });
			r["server.http_keepalive.oneport_peek" + s] = on([] { return http_keepalive(Mode::one_port, Detect::peek); });
			r["server.http_keepalive.dedicated" + s] = on([] { return http_keepalive(Mode::dedicated, Detect::replay); });
			r["server.dedicated_ports" + s] = on(dedicated_ports);
			r["server.dedicated_proxy" + s] = on(dedicated_proxy);
			r["server.peek_lowat.peek" + s] = on([] { return peek_lowat(Detect::peek); });
			r["server.peek_lowat.replay" + s] = on([] { return peek_lowat(Detect::replay); });
			r["server.check_byte_wins.replay" + s] = on([] { return check_byte_wins(Detect::replay); });
			r["server.check_byte_wins.peek" + s] = on([] { return check_byte_wins(Detect::peek); });
			r["server.two_workers.shared_replay" + s] = on([] { return two_workers(Listener::shared, Detect::replay); });
			r["server.two_workers.shared_peek" + s] = on([] { return two_workers(Listener::shared, Detect::peek); });
			r["server.two_workers.reuseport_replay" + s] = on([] { return two_workers(Listener::reuseport, Detect::replay); });
			r["server.two_workers.reuseport_peek" + s] = on([] { return two_workers(Listener::reuseport, Detect::peek); });
			r["server.flag_matrix" + s] = on(flag_matrix);
			r["server.stop_with_pending" + s] = on(stop_with_pending);
			r["server.binary_smoke" + s] = on(binary_smoke);
			r["server.binary_record" + s] = on(binary_record);
			r["server.cases_by_port" + s] = on(cases_by_port);
		}
		r["server.kernel_rcvlowat_et"] = kernel_rcvlowat_et;
		r["server.kernel_nodelay_inherited"] = kernel_nodelay_inherited;
		r["server.kernel_rcvlowat_uring"] = kernel_rcvlowat_uring;
		r["server.kernel_uring_recv_select"] = kernel_uring_recv_select;
		r["server.not_served"] = not_served;
	}

}  // namespace oneport::test

#else

namespace oneport::test
{
	void register_server_tests(Registry&) {}
}  // namespace oneport::test

#endif
