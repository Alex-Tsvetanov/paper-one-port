// IOCP (Windows, M6a): the Windows behaviour the IOCP backend rests on, pinned before use as
// proposal I11 asks ("Both are pinned by tests before use") and as RK4 pinned io_uring's; then the
// server on IOCP where the hard cases do not reach: both receive forms (the zero-byte form, rule E's
// only candidate, and the posted form, section 10's secondary variant) and B2(d) in each, the check
// of 1(b) in both its forms with a byte in the pass of the expiry, the switch to replay, both
// AcceptEx forms, every mode of the binary, a stop with a pending connection, and the binary
// itself.
// Untimed: no test measures a rate. Nothing received is printed beyond counts.
#include "test_support.hpp"

#if defined(_WIN32) && defined(ONEPORT_HAVE_TLS)

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <mswsock.h>
#include <mstcpip.h>
#include <windows.h>

#include "apps.hpp"
#include "cases.hpp"
#include "harness.hpp"
#include "http1.hpp"
#include "script.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace oneport::test
{

	namespace
	{

		using namespace std::chrono_literals;
		using opcase::Bytes;
		using opcase::Script;
		using opcase::text;

		const Bytes kGetKeepAlive = text("GET / HTTP/1.1\r\nHost: oneport.test\r\n\r\n");

		/// Winsock 2.2 for one test.
		struct Winsock
		{
			Winsock()
			{
				WSADATA d{};
				ok = ::WSAStartup(MAKEWORD(2, 2), &d) == 0;
			}
			~Winsock() { ::WSACleanup(); }
			bool ok = false;
		};

		/// A socket closed at the end of its scope.
		struct Sock
		{
			SOCKET s = INVALID_SOCKET;
			Sock() = default;
			explicit Sock(SOCKET x) : s(x) {}
			Sock(Sock&& o) noexcept : s(std::exchange(o.s, INVALID_SOCKET)) {}
			Sock(const Sock&) = delete;
			Sock& operator=(const Sock&) = delete;
			Sock& operator=(Sock&&) = delete;
			~Sock()
			{
				if (s != INVALID_SOCKET) ::closesocket(s);
			}
			SOCKET release() { return std::exchange(s, INVALID_SOCKET); }
		};

		/// A completion port closed at the end of its scope.
		struct Port
		{
			HANDLE h = CreateIoCompletionPort(INVALID_HANDLE_VALUE, nullptr, 0, 1);
			Port() = default;
			Port(const Port&) = delete;
			Port& operator=(const Port&) = delete;
			~Port() { CloseHandle(h); }
		};

		SOCKET overlapped_socket() { return ::WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, nullptr, 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT); }

		sockaddr_in loopback(std::uint16_t port)
		{
			sockaddr_in a{};
			a.sin_family = AF_INET;
			a.sin_port = htons(port);
			a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			return a;
		}

		/// A listening socket on a free loopback port.
		SOCKET listener(std::uint16_t& port)
		{
			const SOCKET l = overlapped_socket();
			if (l == INVALID_SOCKET) return l;
			const BOOL one = TRUE;
			::setsockopt(l, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char*>(&one), sizeof(one));
			sockaddr_in a = loopback(0);
			if (::bind(l, reinterpret_cast<sockaddr*>(&a), sizeof(a)) != 0 || ::listen(l, SOMAXCONN) != 0)
			{
				::closesocket(l);
				return INVALID_SOCKET;
			}
			int n = sizeof(a);
			::getsockname(l, reinterpret_cast<sockaddr*>(&a), &n);
			port = ntohs(a.sin_port);
			return l;
		}

		/// A connected loopback pair: `client`, and `server` as accept() returned it, non-blocking,
		/// on `port` with FILE_SKIP_COMPLETION_PORT_ON_SUCCESS, as the IOCP worker sets them up.
		struct Pair
		{
			Sock client;
			Sock server;
		};

		Result make_pair(Pair& p, HANDLE port)
		{
			std::uint16_t lp = 0;
			Sock l(listener(lp));
			CHECK(l.s != INVALID_SOCKET, "listener: " << WSAGetLastError());
			p.client.s = overlapped_socket();
			const BOOL one = TRUE;
			::setsockopt(p.client.s, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof(one));
			sockaddr_in a = loopback(lp);
			CHECK(::connect(p.client.s, reinterpret_cast<sockaddr*>(&a), sizeof(a)) == 0, "connect: " << WSAGetLastError());
			p.server.s = ::accept(l.s, nullptr, nullptr);
			CHECK(p.server.s != INVALID_SOCKET, "accept: " << WSAGetLastError());
			u_long nonblocking = 1;
			CHECK(::ioctlsocket(p.server.s, FIONBIO, &nonblocking) == 0, "FIONBIO");
			CHECK(CreateIoCompletionPort(reinterpret_cast<HANDLE>(p.server.s), port, 7, 0) == port, "associate: " << GetLastError());
			CHECK(SetFileCompletionNotificationModes(reinterpret_cast<HANDLE>(p.server.s), FILE_SKIP_COMPLETION_PORT_ON_SUCCESS), "skip mode");
			return std::nullopt;
		}

		char zero_byte = 0;

		/// Posts a zero-byte WSARecv: 0 if it completed at once, WSA_IO_PENDING, or the error.
		int post_zero_byte(SOCKET s, OVERLAPPED& ov)
		{
			std::memset(&ov, 0, sizeof(ov));
			WSABUF b{0, &zero_byte};
			DWORD got = 0;
			DWORD flags = 0;
			if (::WSARecv(s, &b, 1, &got, &flags, &ov, nullptr) == 0) return 0;
			return WSAGetLastError();
		}

		/// One dequeue of the port within `ms`; nullptr if nothing came.
		OVERLAPPED* dequeue(HANDLE port, DWORD ms, DWORD& bytes, bool& ok)
		{
			ULONG_PTR key = 0;
			OVERLAPPED* ov = nullptr;
			bytes = 0;
			ok = GetQueuedCompletionStatus(port, &bytes, &key, &ov, ms) != FALSE;
			return ov;
		}

		int send_text(SOCKET s, std::string_view t) { return ::send(s, t.data(), static_cast<int>(t.size()), 0); }

		/// recv on the server's non-blocking socket: the count, 0 at EOF, or -(the error).
		int recv_some(SOCKET s, char* buf, int len, int flags)
		{
			const int n = ::recv(s, buf, len, flags);
			return n == SOCKET_ERROR ? -WSAGetLastError() : n;
		}

		// ---- Pins ----

		/// Windows does not support SO_RCVLOWAT: setsockopt fails (proposal I11). This is why IOCP
		/// switches to replay. The SOL_SOCKET options documentation names WSAEINVAL on Windows Vista
		/// and later and WSAENOPROTOOPT on earlier versions; W (Windows 11, build 26200) returned
		/// WSAENOPROTOOPT on 2026-10-03 (design/status-m6.md). Either is the refusal the design needs.
		Result pin_rcvlowat()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			Port port;
			Pair p;
			if (auto bad = make_pair(p, port.h)) return bad;
			const int mark = 30;
			const int r = ::setsockopt(p.server.s, SOL_SOCKET, SO_RCVLOWAT, reinterpret_cast<const char*>(&mark), sizeof(mark));
			const int e = r == 0 ? 0 : WSAGetLastError();
			CHECK(r != 0 && (e == WSAEINVAL || e == WSAENOPROTOOPT), "setsockopt(SO_RCVLOWAT) returned " << r << ", error " << e);
			return std::nullopt;
		}

		/// The zero-byte WSARecv is a readiness signal: with nothing queued it stays pending; it
		/// completes, with 0 bytes, once bytes arrive; recv(MSG_PEEK) then returns them without
		/// consuming them; with bytes queued it completes at once and, in skip mode, queues no
		/// packet (FILE_SKIP_COMPLETION_PORT_ON_SUCCESS).
		Result pin_zero_byte()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			Port port;
			Pair p;
			if (auto bad = make_pair(p, port.h)) return bad;
			OVERLAPPED ov{};
			CHECK(post_zero_byte(p.server.s, ov) == WSA_IO_PENDING, "a zero-byte WSARecv with nothing queued did not stay pending");
			DWORD bytes = 0;
			bool ok = false;
			CHECK(dequeue(port.h, 200, bytes, ok) == nullptr, "a zero-byte WSARecv completed with nothing queued");
			CHECK(send_text(p.client.s, "0123456789") == 10, "send");
			CHECK(dequeue(port.h, 2000, bytes, ok) == &ov && ok && bytes == 0, "the zero-byte WSARecv did not complete with 0 bytes when bytes arrived");
			std::array<char, 64> buf{};
			CHECK(recv_some(p.server.s, buf.data(), 64, MSG_PEEK) == 10 && std::memcmp(buf.data(), "0123456789", 10) == 0, "MSG_PEEK did not return the bytes");
			CHECK(recv_some(p.server.s, buf.data(), 64, MSG_PEEK) == 10, "MSG_PEEK consumed the bytes");
			CHECK(post_zero_byte(p.server.s, ov) == 0, "a zero-byte WSARecv with bytes queued did not complete at once");
			CHECK(dequeue(port.h, 200, bytes, ok) == nullptr, "an operation that completed at once queued a packet in skip mode");
			CHECK(recv_some(p.server.s, buf.data(), 64, 0) == 10, "recv did not take the 10 bytes");
			CHECK(recv_some(p.server.s, buf.data(), 64, 0) == -WSAEWOULDBLOCK, "the socket is not drained and non-blocking");
			return std::nullopt;
		}

		/// A half-close completes a pending zero-byte WSARecv; MSG_PEEK and recv then return 0 (no
		/// byte: 1 h's "silent"). With bytes before the half-close, MSG_PEEK returns the bytes, and
		/// recv returns them, then 0 (1 h's "undecided"): seen as a read of 0 bytes, as in replay.
		Result pin_zero_byte_half_close()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			for (const bool with_bytes : {false, true})
			{
				Port port;
				Pair p;
				if (auto bad = make_pair(p, port.h)) return bad;
				OVERLAPPED ov{};
				CHECK(post_zero_byte(p.server.s, ov) == WSA_IO_PENDING, "the zero-byte WSARecv did not stay pending");
				if (with_bytes) CHECK(send_text(p.client.s, "GE") == 2, "send");
				CHECK(::shutdown(p.client.s, SD_SEND) == 0, "shutdown");
				DWORD bytes = 0;
				bool ok = false;
				CHECK(dequeue(port.h, 2000, bytes, ok) == &ov && ok && bytes == 0, "the half-close did not complete the zero-byte WSARecv");
				std::array<char, 16> buf{};
				if (with_bytes)
				{
					std::this_thread::sleep_for(20ms);  // the FIN behind the bytes
					CHECK(recv_some(p.server.s, buf.data(), 16, MSG_PEEK) == 2, "MSG_PEEK did not return the 2 bytes before the half-close");
					CHECK(recv_some(p.server.s, buf.data(), 16, 0) == 2, "recv did not return the 2 bytes");
				}
				else
				{
					CHECK(recv_some(p.server.s, buf.data(), 16, MSG_PEEK) == 0, "MSG_PEEK after a half-close with no byte did not return 0");
				}
				CHECK(recv_some(p.server.s, buf.data(), 16, 0) == 0, "recv after the half-close did not return 0");
			}
			return std::nullopt;
		}

		/// A reset completes a pending zero-byte WSARecv with an error, WSAECONNRESET.
		Result pin_zero_byte_reset()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			Port port;
			Pair p;
			if (auto bad = make_pair(p, port.h)) return bad;
			OVERLAPPED ov{};
			CHECK(post_zero_byte(p.server.s, ov) == WSA_IO_PENDING, "the zero-byte WSARecv did not stay pending");
			const linger l{1, 0};
			::setsockopt(p.client.s, SOL_SOCKET, SO_LINGER, reinterpret_cast<const char*>(&l), sizeof(l));
			::closesocket(p.client.release());
			DWORD bytes = 0;
			bool ok = true;
			CHECK(dequeue(port.h, 2000, bytes, ok) == &ov && !ok, "the reset did not complete the zero-byte WSARecv with an error");
			DWORD flags = 0;
			const BOOL r = WSAGetOverlappedResult(p.server.s, &ov, &bytes, FALSE, &flags);
			const int e = r ? 0 : WSAGetLastError();
			CHECK(e == WSAECONNRESET, "the reset's error is " << e << ", not WSAECONNRESET (" << WSAECONNRESET << ")");
			return std::nullopt;
		}

		/// The check of 1(b) in the zero-byte form: a one-byte MSG_PEEK finds a byte that arrived
		/// while the zero-byte WSARecv was pending, before its completion is dequeued, and does not
		/// take it; the completion is still queued.
		Result pin_peek_beside_zero_byte()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			Port port;
			Pair p;
			if (auto bad = make_pair(p, port.h)) return bad;
			OVERLAPPED ov{};
			CHECK(post_zero_byte(p.server.s, ov) == WSA_IO_PENDING, "the zero-byte WSARecv did not stay pending");
			char one = 0;
			CHECK(recv_some(p.server.s, &one, 1, MSG_PEEK) == -WSAEWOULDBLOCK, "MSG_PEEK found a byte before any was sent");
			CHECK(send_text(p.client.s, "G") == 1, "send");
			std::this_thread::sleep_for(50ms);
			CHECK(recv_some(p.server.s, &one, 1, MSG_PEEK) == 1 && one == 'G', "MSG_PEEK did not find the byte beside the pending zero-byte WSARecv");
			DWORD bytes = 0;
			bool ok = false;
			CHECK(dequeue(port.h, 2000, bytes, ok) == &ov && ok, "the zero-byte WSARecv's completion was not queued");
			CHECK(recv_some(p.server.s, &one, 1, 0) == 1, "the byte was taken by the peek");
			return std::nullopt;
		}

		/// Closing a socket completes its pending operations with an error, and their packets still
		/// arrive: the IOCP worker keeps a closed connection's OVERLAPPED until then (finalize).
		Result pin_close_completes()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			Port port;
			Pair p;
			if (auto bad = make_pair(p, port.h)) return bad;
			OVERLAPPED ov{};
			CHECK(post_zero_byte(p.server.s, ov) == WSA_IO_PENDING, "the zero-byte WSARecv did not stay pending");
			::closesocket(p.server.release());
			DWORD bytes = 0;
			bool ok = true;
			CHECK(dequeue(port.h, 2000, bytes, ok) == &ov && !ok, "closing the socket did not complete its pending operation with an error");
			return std::nullopt;
		}

		/// AcceptEx with dwReceiveDataLength = 0 completes as soon as a connection arrives; with a
		/// receive buffer it waits for data, and its completion reports the bytes (AcceptEx docs).
		Result pin_acceptex()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			for (const bool with_buffer : {false, true})
			{
				Port port;
				std::uint16_t lp = 0;
				Sock l(listener(lp));
				CHECK(l.s != INVALID_SOCKET, "listener");
				CHECK(CreateIoCompletionPort(reinterpret_cast<HANDLE>(l.s), port.h, 9, 0) == port.h, "associate the listener");
				LPFN_ACCEPTEX accept_ex = nullptr;
				GUID guid = WSAID_ACCEPTEX;
				DWORD got = 0;
				CHECK(::WSAIoctl(l.s, SIO_GET_EXTENSION_FUNCTION_POINTER, &guid, sizeof(guid), &accept_ex, sizeof(accept_ex), &got, nullptr, nullptr) == 0, "AcceptEx");
				Sock a(overlapped_socket());
				constexpr DWORD kAddr = sizeof(sockaddr_in) + 16;
				std::array<char, 256 + 2 * kAddr> buf{};
				const DWORD data = with_buffer ? 256 : 0;
				OVERLAPPED ov{};
				const BOOL done = accept_ex(l.s, a.s, buf.data(), data, kAddr, kAddr, &got, &ov);
				CHECK(done || WSAGetLastError() == ERROR_IO_PENDING, "AcceptEx: " << WSAGetLastError());
				Sock c(overlapped_socket());
				sockaddr_in addr = loopback(lp);
				CHECK(::connect(c.s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
				DWORD bytes = 0;
				bool ok = false;
				if (with_buffer)
				{
					CHECK(dequeue(port.h, 300, bytes, ok) == nullptr, "AcceptEx with a receive buffer completed before any data");
					CHECK(send_text(c.s, "SSH") == 3, "send");
					CHECK(dequeue(port.h, 2000, bytes, ok) == &ov && ok && bytes == 3 && std::memcmp(buf.data(), "SSH", 3) == 0,
					      "AcceptEx with a receive buffer did not complete with the 3 bytes");
				}
				else
				{
					CHECK(dequeue(port.h, 2000, bytes, ok) == &ov && ok && bytes == 0, "AcceptEx without a receive buffer did not complete at the connect");
				}
			}
			return std::nullopt;
		}

		// ---- The server on IOCP ----

		opcase::Transcript run_and_wait(Running& srv, const Script& s, std::uint16_t port, std::vector<server::DetectionReport>* reps = nullptr)
		{
			opcase::Transcript t = opcase::run(s, port);
			std::vector<server::DetectionReport> r;
			srv.collector.wait_close(t.local_port, 10000ms, r);
			if (reps != nullptr) *reps = std::move(r);
			return t;
		}

		std::size_t count(const Bytes& b, std::string_view needle)
		{
			const Bytes n = text(needle);
			std::size_t k = 0;
			for (auto it = b.begin(); (it = std::search(it, b.end(), n.begin(), n.end())) != b.end(); ++it) ++k;
			return k;
		}

		struct Arm
		{
			std::string name;
			Mode mode;
			Detect detect;
		};
		const std::array<Arm, 3> kArms{{{"one-port replay", Mode::one_port, Detect::replay},
		                                {"one-port peek", Mode::one_port, Detect::peek},
		                                {"dedicated", Mode::dedicated, Detect::replay}}};

		std::string form_name(IocpReceive f) { return f == IocpReceive::posted ? "posted" : "zero-byte"; }

		/// Both receive forms (I31 E2) in every arm: HTTP/1.1 keep-alive with pipelining,
		/// TLS with a request, h2c, an SMTP fallback (one-port) or port (dedicated), and an SSH line.
		/// The posted form holds the handler's buffer while it waits (I15), so a silent connection
		/// holds one; the zero-byte form never does.
		Result receive_forms()
		{
			for (const IocpReceive form : {IocpReceive::zero_byte, IocpReceive::posted})
			{
				for (const Arm& a : kArms)
				{
					const std::string label = form_name(form) + " " + a.name;
					ServerArgs args;
					args.mode = a.mode;
					args.detect = a.detect;
					args.iocp_receive = form;
					args.fallback = a.mode == Mode::one_port ? Fallback::smtp : Fallback::none;
					Running srv(args);
					const bool one = a.mode == Mode::one_port;
					auto port = [&](detect::Proto p) { return one ? srv.port() : srv.port_of(p); };
					const Bytes three = opcase::cat({kGetKeepAlive, kGetKeepAlive, opcase::http_get()});
					auto t = run_and_wait(srv, Script{}.write(three), port(detect::Proto::http1));
					CHECK(count(t.received, "Hello, World!") == 3 && t.eof, label << ": HTTP/1.1: " << t.received.size() << " bytes");
					opcase::TlsPlan plan;
					plan.requests.push_back(opcase::http_get());
					t = run_and_wait(srv, Script{}.tls(plan), port(detect::Proto::tls));
					CHECK(t.tls && t.tls->handshake && t.tls->plain == text(http1::kResponse200), label << ": TLS: " << (t.tls ? t.tls->error : "no result"));
					t = run_and_wait(srv, Script{}.write(opcase::h2c_opening()).shutdown_write(), port(detect::Proto::h2c));
					CHECK(count(t.received, "Hello, World!") == 1, label << ": h2c: " << t.received.size() << " bytes");
					t = run_and_wait(srv, Script{}.await_line().write(opcase::smtp_line("EHLO c.test")).write(opcase::smtp_line("QUIT")), port(detect::Proto::smtp));
					CHECK(t.received.size() > 4 && t.received[0] == std::byte{'2'} && t.eof, label << ": SMTP: " << t.received.size() << " bytes");
					t = run_and_wait(srv, Script{}.write(opcase::ssh_line()), port(detect::Proto::ssh));
					CHECK(t.received == text(apps::kSshBanner) && t.eof, label << ": SSH: " << t.received.size() << " bytes");
					if (auto bad = srv.stop_and_check()) return label + ": " + *bad;
					const server::Counters c = srv.server->totals();
					if (form == IocpReceive::posted)
					{
						CHECK(c.zero_byte_recv_calls == 0 || a.detect == Detect::peek, label << ": the posted form made zero-byte receives in replay");
					}
					else
					{
						CHECK(c.zero_byte_recv_calls > 0, label << ": the zero-byte form made no zero-byte receive");
					}
					CHECK(c.gqcs_calls >= c.passes && c.passes > 0, label << ": GetQueuedCompletionStatusEx calls " << c.gqcs_calls << ", passes " << c.passes);
				}
			}
			return std::nullopt;
		}

		/// B2(d) in each receive form: a silent pending connection, closed at T_dec ("silent", 1(f)),
		/// held no data buffer in the zero-byte form, in either detection mode, and held the
		/// handler's buffer in the posted form in replay, which the audit reports. That violation is
		/// why rule E may not choose the posted form (the coordinator's decision of 2026-10-03,
		/// hypotheses.md revision log); section 10 keeps it as a secondary, descriptive variant. In
		/// peek mode no receive is posted with a buffer during detection, in either form.
		Result silent_buffer()
		{
			for (const IocpReceive form : {IocpReceive::zero_byte, IocpReceive::posted})
			{
				for (const Detect detect : {Detect::replay, Detect::peek})
				{
					const std::string label = form_name(form) + (detect == Detect::peek ? " peek" : " replay");
					ServerArgs args;
					args.detect = detect;
					args.iocp_receive = form;
					Running srv(args);
					std::vector<server::DetectionReport> reps;
					const opcase::Transcript t = run_and_wait(srv, Script{}.await_close(), srv.port(), &reps);
					CHECK(!t.timed_out && t.received.empty(), label << ": the server did not close the silent connection without a byte");
					CHECK(reps.size() == 1, label << ": " << reps.size() << " detection reports");
					CHECK(reps[0].outcome == server::Outcome::silent, label << ": not closed as silent");
					const bool holds = form == IocpReceive::posted && detect == Detect::replay;
					CHECK(reps[0].buffer_while_silent == holds,
					      label << (holds ? ": the posted form's buffer while silent was not reported (B2 d)" : ": held a data buffer while no byte had arrived (B2 d)"));
					if (auto bad = srv.stop_and_check()) return label + ": " + *bad;
				}
			}
			return std::nullopt;
		}

		/// Makes a request reach the socket in the pass that handles an expiry, after the pass's
		/// completions and before its expiries (hypotheses.md, section 11).
		struct ByteInExpiryPass
		{
			std::atomic<SOCKET> client{INVALID_SOCKET};
			std::atomic<bool> fired{false};
			static void hook(void* ctx, unsigned, server::TimePoint wait_return, std::optional<server::TimePoint> earliest)
			{
				auto* self = static_cast<ByteInExpiryPass*>(ctx);
				if (self->fired.load() || !earliest || *earliest > wait_return) return;
				const SOCKET s = self->client.load();
				if (s == INVALID_SOCKET) return;
				const Bytes req = opcase::http_get();
				if (::send(s, reinterpret_cast<const char*>(req.data()), static_cast<int>(req.size()), 0) != static_cast<int>(req.size())) return;
				// Until the server's side holds it: no byte in flight, by the client's TCP_INFO.
				for (int i = 0; i < 1000; ++i)
				{
					TCP_INFO_v0 info{};
					DWORD version = 0;
					DWORD got = 0;
					if (::WSAIoctl(s, SIO_TCP_INFO, &version, sizeof(version), &info, sizeof(info), &got, nullptr, nullptr) == 0 && info.BytesInFlight == 0) break;
					std::this_thread::sleep_for(1ms);
				}
				std::this_thread::sleep_for(5ms);  // and its receive's completion queued
				self->fired.store(true);
			}
		};

		/// The check of 1(b) with a byte in the pass of the expiry, in both IOCP forms: the one-byte
		/// MSG_PEEK (the zero-byte form, and the peek path) and the non-waiting reap of the port
		/// (the posted form in replay). The byte wins: no fallback, the request is answered.
		Result check_byte_wins(Detect detect, IocpReceive form)
		{
			ByteInExpiryPass ctx;
			ServerArgs a;
			a.detect = detect;
			a.iocp_receive = form;
			a.fallback = Fallback::smtp;
			server::Hooks extra;
			extra.ctx = &ctx;
			extra.before_expiries = &ByteInExpiryPass::hook;
			Running srv(a, extra);
			Sock client(overlapped_socket());
			const BOOL one = TRUE;
			::setsockopt(client.s, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof(one));
			sockaddr_in addr = loopback(srv.port());
			CHECK(::connect(client.s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
			ctx.client.store(client.s);
			sockaddr_in local{};
			int n = sizeof(local);
			::getsockname(client.s, reinterpret_cast<sockaddr*>(&local), &n);
			std::string got;
			for (;;)
			{
				WSAPOLLFD p{client.s, POLLRDNORM, 0};
				if (::WSAPoll(&p, 1, 5000) <= 0) break;
				std::array<char, 512> buf{};
				const int k = ::recv(client.s, buf.data(), static_cast<int>(buf.size()), 0);
				if (k <= 0) break;
				got.append(buf.data(), static_cast<std::size_t>(k));
			}
			std::vector<server::DetectionReport> reps;
			srv.collector.wait_close(ntohs(local.sin_port), 10000ms, reps);
			CHECK(ctx.fired.load(), "the hook never saw a pass with an expiry");
			CHECK(got == http1::kResponse200, "the byte won: the request is answered 200, not by the fallback (" << got.size() << " bytes)");
			CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::classified && reps[0].proto == detect::Proto::http1, "classified HTTP/1.1");
			if (auto bad = srv.stop_and_check()) return bad;
			const server::Counters c = srv.server->totals();
			CHECK(c.check_calls == 1 && c.check_found_byte == 1, "one check, which found the byte (" << c.check_calls << ", " << c.check_found_byte << ")");
			bool byte_won = false;
			for (const auto& ev : c.timed) byte_won = byte_won || (ev.kind == server::TimerKind::t_fb && ev.result == server::TimerResult::byte_won);
			CHECK(byte_won, "the T_fb event records that the byte won");
			CHECK(c.fallback[static_cast<std::size_t>(detect::Proto::smtp)] == 0, "no fallback dispatch");
			return std::nullopt;
		}

		/// IOCP's switch to replay (I11): a request whose first write leaves the peek undecided is
		/// read into the handler's buffer, counted once, and answered; its report says it was
		/// replayed, and in the PROXY stage too. In replay mode no switch happens.
		Result peek_switch()
		{
			for (const Detect detect : {Detect::peek, Detect::replay})
			{
				for (const bool proxy : {false, true})
				{
					ServerArgs a;
					a.detect = detect;
					a.proxy = proxy ? Proxy::on : Proxy::off;
					Running srv(a);
					const Bytes header = opcase::proxy_v2();
					const Bytes req = opcase::http_get();
					Script s;
					if (proxy) s.write(opcase::slice(header, 0, 10)).gap(30ms).write(opcase::cat({opcase::slice(header, 10, header.size()), opcase::slice(req, 0, 2)}));
					else s.write(opcase::slice(req, 0, 2));
					s.gap(30ms).write(opcase::slice(req, 2, req.size()));
					std::vector<server::DetectionReport> reps;
					const auto t = run_and_wait(srv, s, srv.port(), &reps);
					const std::string label = std::string(detect == Detect::peek ? "peek" : "replay") + (proxy ? ", PROXY" : "");
					CHECK(t.received == text(http1::kResponse200) && t.eof, label << ": not answered 200: " << t.received.size() << " bytes");
					CHECK(reps.size() == 1 && reps[0].outcome == server::Outcome::classified, label << ": not classified");
					if (auto bad = srv.stop_and_check()) return label + ": " + *bad;
					const server::Counters c = srv.server->totals();
					const std::uint64_t want = detect == Detect::peek ? 1 : 0;
					CHECK(c.peek_to_replay == want, label << ": " << c.peek_to_replay << " switches to replay, expected " << want);
					CHECK(reps[0].replayed == (detect == Detect::peek), label << ": the report's replay flag");
					CHECK(c.setsockopt_calls == 0 && c.lowat_sets == 0, label << ": SO_RCVLOWAT was set on IOCP");
				}
			}
			return std::nullopt;
		}

		/// AcceptEx with a receive buffer (--iocp-accept buffer, hypotheses.md section 10): the first
		/// bytes come with the accept, in the handler's buffer, and detection runs on them in both
		/// detection modes; later bytes follow by the receive form. Without the buffer form, no
		/// accept completes with data.
		Result accept_forms()
		{
			for (const Detect detect : {Detect::replay, Detect::peek})
			{
				ServerArgs a;
				a.detect = detect;
				a.iocp_accept = IocpAccept::buffer;
				Running srv(a);
				std::vector<server::DetectionReport> reps;
				auto t = run_and_wait(srv, Script{}.write(opcase::http_get()), srv.port(), &reps);
				CHECK(t.received == text(http1::kResponse200) && t.eof, "buffer form: HTTP/1.1 not answered: " << t.received.size() << " bytes");
				CHECK(reps.size() == 1 && reps[0].replayed && reps[0].wakeups == 1, "buffer form: not decided on the accept's bytes");
				const Bytes req = opcase::http_get();
				t = run_and_wait(srv, Script{}.write(opcase::slice(req, 0, 2)).gap(30ms).write(opcase::slice(req, 2, req.size())), srv.port(), &reps);
				CHECK(t.received == text(http1::kResponse200) && t.eof, "buffer form: a split request not answered");
				opcase::TlsPlan plan;
				plan.requests.push_back(opcase::http_get());
				t = run_and_wait(srv, Script{}.tls(plan), srv.port());
				CHECK(t.tls && t.tls->handshake && t.tls->plain == text(http1::kResponse200), "buffer form: TLS");
				if (auto bad = srv.stop_and_check()) return std::string("buffer form: ") + *bad;
				CHECK(srv.server->totals().peek_to_replay == 0, "buffer form: a switch to replay counted");
			}
			return std::nullopt;
		}

		/// Every mode of the binary's server on IOCP, stub mode included (I18): the stub's TLS port
		/// reads one record and answers the 13-byte body; its HTTP/1.1 port answers 200.
		Result stub_mode()
		{
			ServerArgs a;
			a.mode = Mode::stub;
			Running srv(a);
			const auto t = run_and_wait(srv, Script{}.write(opcase::recorded_client_hello()), srv.port_of(detect::Proto::tls));
			CHECK(t.received == text("Hello, World!") && t.eof, "the stub's TLS port: " << t.received.size() << " bytes");
			const auto h = run_and_wait(srv, Script{}.write(opcase::http_get()), srv.port_of(detect::Proto::http1));
			CHECK(h.received == text(http1::kResponse200) && h.eof, "the stub's HTTP/1.1 port");
			return srv.stop_and_check();
		}

		/// A stop with connections pending in detection and in a handler: each is closed, its
		/// operations cancelled and their completions drained, with no worker error, connection or
		/// buffer left (harness.hpp), in both forms.
		Result stop_with_pending()
		{
			Winsock ws;
			CHECK(ws.ok, "WSAStartup");
			for (const IocpReceive form : {IocpReceive::zero_byte, IocpReceive::posted})
			{
				ServerArgs a;
				a.iocp_receive = form;
				a.t_fb = 60000ms;
				a.t_dec = 60000ms;
				Running srv(a);
				std::vector<Sock> clients;
				for (int i = 0; i < 4; ++i)
				{
					clients.emplace_back(overlapped_socket());
					sockaddr_in addr = loopback(srv.port());
					CHECK(::connect(clients.back().s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0, "connect");
				}
				CHECK(send_text(clients[1].s, "GE") == 2, "send");                    // pending in detection, with bytes
				CHECK(send_text(clients[2].s, "GET / HTTP/1.1\r\n") == 16, "send");  // in the handler, mid-request
				std::this_thread::sleep_for(100ms);
				if (auto bad = srv.stop_and_check()) return form_name(form) + ": " + *bad;
				const server::Counters c = srv.server->totals();
				CHECK(c.outcomes[static_cast<std::size_t>(server::Outcome::stopped)] == 3, form_name(form) << ": "
				                                                                                      << c.outcomes[static_cast<std::size_t>(server::Outcome::stopped)]
				                                                                                      << " connections stopped in detection, expected 3");
			}
			return std::nullopt;
		}

		/// The binary on IOCP: it starts, answers an HTTP/1.1 request, stops when its stop event is
		/// set (main.cpp), exits 0 and prints its counters.
		Result binary_smoke()
		{
			const std::string& path = binary_path();
			CHECK(!path.empty(), "no binary path given");
			SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
			HANDLE out_r = nullptr;
			HANDLE out_w = nullptr;
			CHECK(CreatePipe(&out_r, &out_w, &sa, 0), "CreatePipe");
			SetHandleInformation(out_r, HANDLE_FLAG_INHERIT, 0);
			STARTUPINFOA si{};
			si.cb = sizeof(si);
			si.dwFlags = STARTF_USESTDHANDLES;
			si.hStdOutput = out_w;
			si.hStdError = out_w;
			si.hStdInput = nullptr;
			std::string cmd = "\"" + path + "\" --mode one-port --detect peek --dispatch inproc --backend IOCP";
			PROCESS_INFORMATION pi{};
			const BOOL started = CreateProcessA(nullptr, cmd.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi);
			CloseHandle(out_w);
			if (!started)
			{
				CloseHandle(out_r);
				return std::string("CreateProcess: ") + std::to_string(GetLastError());
			}
			std::string text_out;
			std::atomic<bool> reading{true};
			std::mutex m;
			std::thread reader([&] {
				std::array<char, 4096> buf{};
				DWORD k = 0;
				while (ReadFile(out_r, buf.data(), static_cast<DWORD>(buf.size()), &k, nullptr) && k > 0)
				{
					std::lock_guard lock(m);
					text_out.append(buf.data(), k);
				}
				reading.store(false);
			});
			const std::string key = "oneport: listening one-port 127.0.0.1:";
			std::uint16_t port = 0;
			for (int i = 0; i < 1000 && port == 0 && reading.load(); ++i)
			{
				{
					std::lock_guard lock(m);
					const auto at = text_out.find(key);
					const auto eol = at == std::string::npos ? std::string::npos : text_out.find('\n', at);
					if (eol != std::string::npos) port = static_cast<std::uint16_t>(std::stoi(text_out.substr(at + key.size(), eol - at - key.size())));
				}
				if (port == 0) std::this_thread::sleep_for(10ms);
			}
			Result r;
			if (port == 0) r = "the binary printed no listening line";
			else
			{
				const auto t = opcase::run(Script{}.write(opcase::http_get()), port);
				if (t.received != text(http1::kResponse200)) r = "the binary did not answer 200";
			}
			const std::wstring name = L"Local\\oneport-stop-" + std::to_wstring(pi.dwProcessId);
			HANDLE stop = OpenEventW(EVENT_MODIFY_STATE, FALSE, name.c_str());
			if (stop != nullptr)
			{
				SetEvent(stop);
				CloseHandle(stop);
			}
			else
			{
				TerminateProcess(pi.hProcess, 99);  // only if the event cannot be opened
				if (!r) r = "the binary's stop event could not be opened";
			}
			WaitForSingleObject(pi.hProcess, 30000);
			DWORD code = 1;
			GetExitCodeProcess(pi.hProcess, &code);
			reader.join();
			CloseHandle(out_r);
			CloseHandle(pi.hThread);
			CloseHandle(pi.hProcess);
			if (r) return r;
			std::erase(text_out, '\r');  // the C runtime's text-mode stdout ends lines with CRLF
			CHECK(code == 0, "the binary did not exit 0 after its stop event (" << code << ")");
			CHECK(text_out.find("counter accepted 1\n") != std::string::npos, "the counters do not show one connection");
			CHECK(text_out.find("counter classified HTTP/1.1 1\n") != std::string::npos, "the counters do not show the classification");
			CHECK(text_out.find("oneport: connection state ") != std::string::npos, "no connection-state size line");
			return std::nullopt;
		}

		/// What is served on Windows: IOCP with one worker, in-process.
		Result not_served()
		{
			Config c = make_config(ServerArgs{});
			for (const Mode m : {Mode::one_port, Mode::dedicated, Mode::stub})
			{
				c.mode = m;
				CHECK(!server::not_served(c), token(m) << " on IOCP is not served");
			}
			c.mode = Mode::one_port;
			c.workers = 2;
			CHECK(server::not_served(c).has_value(), "two workers on IOCP are served");
			c.workers = 1;
			c.backend = Backend::epoll;
			CHECK(server::not_served(c).has_value(), "epoll is served on Windows");
			bool refused = false;
			try
			{
				server::Server s(c);
			}
			catch (const std::invalid_argument&)
			{
				refused = true;
			}
			CHECK(refused, "the server refuses a configuration not served");
			return std::nullopt;
		}

	}  // namespace

	void register_iocp_tests(Registry& r)
	{
		auto on_iocp = [](std::function<Result()> fn) {
			return [fn] {
				suite_backend() = Backend::iocp;
				return fn();
			};
		};
		r["iocp.pin_rcvlowat"] = pin_rcvlowat;
		r["iocp.pin_zero_byte"] = pin_zero_byte;
		r["iocp.pin_zero_byte_half_close"] = pin_zero_byte_half_close;
		r["iocp.pin_zero_byte_reset"] = pin_zero_byte_reset;
		r["iocp.pin_peek_beside_zero_byte"] = pin_peek_beside_zero_byte;
		r["iocp.pin_close_completes"] = pin_close_completes;
		r["iocp.pin_acceptex"] = pin_acceptex;
		r["iocp.receive_forms"] = on_iocp(receive_forms);
		r["iocp.silent_buffer"] = on_iocp(silent_buffer);
		r["iocp.check_byte_wins.replay_zero_byte"] = on_iocp([] { return check_byte_wins(Detect::replay, IocpReceive::zero_byte); });
		r["iocp.check_byte_wins.replay_posted"] = on_iocp([] { return check_byte_wins(Detect::replay, IocpReceive::posted); });
		r["iocp.check_byte_wins.peek"] = on_iocp([] { return check_byte_wins(Detect::peek, IocpReceive::zero_byte); });
		r["iocp.peek_switch"] = on_iocp(peek_switch);
		r["iocp.accept_forms"] = on_iocp(accept_forms);
		r["iocp.stub_mode"] = on_iocp(stub_mode);
		r["iocp.stop_with_pending"] = on_iocp(stop_with_pending);
		r["iocp.binary_smoke"] = on_iocp(binary_smoke);
		r["iocp.not_served"] = on_iocp(not_served);
	}

}  // namespace oneport::test

#else

namespace oneport::test
{
	void register_iocp_tests(Registry&) {}
}  // namespace oneport::test

#endif
