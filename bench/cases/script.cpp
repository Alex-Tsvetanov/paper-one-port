#include "script.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <memory>
#include <stdexcept>
#include <string>
#include <system_error>
#include <thread>

#if defined(_WIN32)
// Winsock before OpenSSL's headers and anything else that may include windows.h.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <mutex>
#endif

#if defined(ONEPORT_HAVE_TLS)
#include "tls.hpp"

#include <openssl/err.h>
#include <openssl/ssl.h>
#endif

#if defined(__linux__)
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace oneport::opcase
{

	Script& Script::write(Bytes b)
	{
		steps.push_back(Step{Step::Kind::write, std::move(b), {}, Anchor::after_connect, std::nullopt});
		return *this;
	}
	Script& Script::gap(std::chrono::nanoseconds d)
	{
		steps.push_back(Step{Step::Kind::gap, {}, d, Anchor::after_connect, std::nullopt});
		return *this;
	}
	Script& Script::write_at(Anchor a, std::chrono::nanoseconds d, Bytes b)
	{
		steps.push_back(Step{Step::Kind::write_at, std::move(b), d, a, std::nullopt});
		return *this;
	}
	Script& Script::shutdown_write()
	{
		steps.push_back(Step{Step::Kind::shutdown_write, {}, {}, Anchor::after_connect, std::nullopt});
		return *this;
	}
	Script& Script::reset()
	{
		steps.push_back(Step{Step::Kind::reset, {}, {}, Anchor::after_connect, std::nullopt});
		return *this;
	}
	Script& Script::await_line()
	{
		steps.push_back(Step{Step::Kind::await_line, {}, {}, Anchor::after_connect, std::nullopt});
		return *this;
	}
	Script& Script::await_close()
	{
		steps.push_back(Step{Step::Kind::await_close, {}, {}, Anchor::after_connect, std::nullopt});
		return *this;
	}
	Script& Script::tls(TlsPlan p)
	{
		Step st{Step::Kind::tls, {}, {}, Anchor::after_connect, std::move(p)};
		steps.push_back(std::move(st));
		return *this;
	}
	Script& Script::split(const Bytes& b, const std::vector<std::size_t>& cuts, std::chrono::nanoseconds g)
	{
		std::size_t from = 0;
		for (const std::size_t cut : cuts)
		{
			write(slice(b, from, cut));
			gap(g);
			from = cut;
		}
		return write(slice(b, from, b.size()));
	}

	std::string first_line(const Bytes& b)
	{
		std::string s;
		for (const std::byte x : b)
		{
			const auto c = std::to_integer<unsigned char>(x);
			if (c == '\r' || c == '\n') break;
			s += (c >= 0x20 && c < 0x7F) ? static_cast<char>(c) : '.';
			if (s.size() >= 60) break;
		}
		return s;
	}

#if defined(__linux__) || defined(_WIN32)

	namespace
	{

#if defined(_WIN32)
		/// The client on Winsock (M6a): the same steps as on Linux, with Winsock's calls. The socket
		/// stays blocking, as on Linux, and is read only after WSAPoll reports it readable; it is
		/// kept in an int as the server keeps its sockets (a kernel handle's lower 32 bits).
		SOCKET as_socket(int fd) noexcept { return static_cast<SOCKET>(static_cast<std::intptr_t>(fd)); }

		/// Winsock 2.2, started once for the process and never cleaned up (the test process ends).
		void winsock_once()
		{
			static std::once_flag once;
			std::call_once(once, [] {
				WSADATA d{};
				const int e = ::WSAStartup(MAKEWORD(2, 2), &d);
				if (e != 0) throw std::system_error(e, std::system_category(), "opcase: WSAStartup");
			});
		}
#endif

		class Client
		{
		public:
			Client(Transcript& t, const Limits& limits) : t_(t), limits_(limits) {}
#if defined(_WIN32)
			~Client()
			{
				if (fd_ >= 0) ::closesocket(as_socket(fd_));
				if (timer_ != nullptr) ::CloseHandle(timer_);
			}

			/// Waits until the socket is readable (or reports its end) or until `until`; true if
			/// readable. WSAPoll's timeout ends on the system timer's tick (about 15.6 ms at Windows'
			/// default resolution), which would stretch every gap of a script, so the last 20 ms of
			/// a wait run in steps of at most 1 ms on a high-resolution waitable timer (Windows 10
			/// version 1803 and later), which ends within its step whatever the system timer's
			/// resolution. Process-local: no system setting changes.
			bool wait_readable(TimePoint until)
			{
				using namespace std::chrono;
				for (;;)
				{
					WSAPOLLFD p{as_socket(fd_), POLLRDNORM, 0};
					const auto now = Clock::now();
					if (now >= until) return ::WSAPoll(&p, 1, 0) > 0;
					const auto left = until - now;
					if (left > 20ms)
					{
						const auto coarse = duration_cast<milliseconds>(left - 20ms).count();
						const int r = ::WSAPoll(&p, 1, static_cast<int>(std::min<long long>(coarse, 1000)));
						if (r != 0) return r > 0;
						continue;
					}
					const int r = ::WSAPoll(&p, 1, 0);
					if (r != 0) return r > 0;
					sleep_precise(std::min<nanoseconds>(left, 1ms));
				}
			}

			void sleep_precise(std::chrono::nanoseconds d)
			{
				if (timer_ == nullptr)
				{
					timer_ = ::CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
					if (timer_ == nullptr) throw std::system_error(static_cast<int>(::GetLastError()), std::system_category(), "opcase: CreateWaitableTimerEx");
				}
				LARGE_INTEGER due{};
				due.QuadPart = -std::max<long long>(1, d.count() / 100);  // relative, in 100 ns units
				if (!::SetWaitableTimer(timer_, &due, 0, nullptr, nullptr, FALSE)) throw std::system_error(static_cast<int>(::GetLastError()), std::system_category(), "opcase: SetWaitableTimer");
				::WaitForSingleObject(timer_, INFINITE);
			}
#else
			~Client()
			{
				if (fd_ >= 0) ::close(fd_);
			}
#endif
			Client(const Client&) = delete;
			Client& operator=(const Client&) = delete;

			bool connect(std::uint16_t port)
			{
#if defined(_WIN32)
				winsock_once();
				const SOCKET s = ::WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, nullptr, 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
				if (s == INVALID_SOCKET) throw std::system_error(WSAGetLastError(), std::system_category(), "opcase: socket");
				fd_ = static_cast<int>(static_cast<std::intptr_t>(s));
				const BOOL one = TRUE;
				::setsockopt(s, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof(one));
				sockaddr_in a{};
				a.sin_family = AF_INET;
				a.sin_port = htons(port);
				a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				t_.before_connect = Clock::now();
				if (::connect(s, reinterpret_cast<const sockaddr*>(&a), sizeof(a)) != 0) return false;
				t_.after_connect = Clock::now();
				sockaddr_in local{};
				int n = sizeof(local);
				::getsockname(s, reinterpret_cast<sockaddr*>(&local), &n);
				t_.local_port = ntohs(local.sin_port);
				t_.connected = true;
				return true;
#else
				fd_ = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
				if (fd_ < 0) throw std::system_error(errno, std::generic_category(), "opcase: socket");
				const int one = 1;
				::setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
				sockaddr_in a{};
				a.sin_family = AF_INET;
				a.sin_port = htons(port);
				a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
				t_.before_connect = Clock::now();
				if (::connect(fd_, reinterpret_cast<const sockaddr*>(&a), sizeof(a)) != 0) return false;
				t_.after_connect = Clock::now();
				sockaddr_in local{};
				socklen_t n = sizeof(local);
				::getsockname(fd_, reinterpret_cast<sockaddr*>(&local), &n);
				t_.local_port = ntohs(local.sin_port);
				t_.connected = true;
				return true;
#endif
			}

			/// Reads what the server sends until `until`, or until it closes. With
			/// `stop_at_line`, also stops once a CRLF-terminated line has arrived.
			void pump(TimePoint until, bool stop_at_line = false)
			{
				while (!closed())
				{
					if (stop_at_line && has_line()) return;
					const auto now = Clock::now();
					const auto left = until > now ? std::chrono::duration_cast<std::chrono::milliseconds>(until - now).count() + 1 : 0;
#if defined(_WIN32)
					(void)left;
					const int r = wait_readable(std::min(until, now + std::chrono::seconds(1))) ? 1 : 0;
#else
					pollfd p{fd_, POLLIN, 0};
					const int r = ::poll(&p, 1, static_cast<int>(std::min<long long>(left, 1000)));
					if (r < 0 && errno == EINTR) continue;
#endif
					if (r > 0) read_some();
					if (Clock::now() >= until) return;
				}
			}

			/// Waits until `until` at most for one read's worth of what the server sends.
			void pump_some(TimePoint until)
			{
				if (closed()) return;
				const auto now = Clock::now();
				const auto left = until > now ? std::chrono::duration_cast<std::chrono::milliseconds>(until - now).count() + 1 : 0;
#if defined(_WIN32)
				(void)left;
				const int r = wait_readable(std::min(until, now + std::chrono::seconds(1))) ? 1 : 0;
#else
				pollfd p{fd_, POLLIN, 0};
				const int r = ::poll(&p, 1, static_cast<int>(std::min<long long>(left, 1000)));
#endif
				if (r > 0) read_some();
			}

			bool closed() const noexcept { return t_.eof || t_.reset || fd_ < 0; }

#if defined(ONEPORT_HAVE_TLS)
			/// A live TLS exchange (script.hpp, TlsPlan).
			void tls_exchange(const TlsPlan& plan)
			{
				TlsResult res;
				static const tls::Ctx frozen = tls::client_ctx();
				tls::Ctx custom;
				SSL_CTX* ctx = frozen.get();
				if (!plan.groups.empty())
				{
					custom = tls::client_ctx(plan.groups.c_str());
					ctx = custom.get();
				}
				const std::unique_ptr<SSL, SslFree> ssl(SSL_new(ctx));
				BIO* rb = BIO_new(BIO_s_mem());
				BIO* wb = BIO_new(BIO_s_mem());
				if (!ssl || rb == nullptr || wb == nullptr) throw std::runtime_error("opcase TLS: SSL_new or BIO_new");
				SSL_set_bio(ssl.get(), rb, wb);
				SSL_set_connect_state(ssl.get());
				const std::string name(tls::kServerName);
				SSL_set_tlsext_host_name(ssl.get(), name.c_str());
				SSL_set1_host(ssl.get(), name.c_str());
				if (!plan.alpn.empty())
				{
					const auto w = tls::alpn_wire(plan.alpn);
					SSL_set_alpn_protos(ssl.get(), w.data(), static_cast<unsigned>(w.size()));
				}
				ERR_clear_error();
				if (SSL_do_handshake(ssl.get()) == 1) throw std::runtime_error("opcase TLS: a handshake without a server");
				ERR_clear_error();
				Bytes hello = take(wb);
				if (plan.record_minor != 0) hello = with_record_version(hello, plan.record_minor);
				std::vector<std::size_t> cuts = plan.cuts;
				if (plan.fragment_at > 0)
				{
					std::size_t first = 0;
					hello = fragment_client_hello(hello, plan.fragment_at, &first);
					if (cuts.empty()) cuts.push_back(plan.prefix.size() + first);
				}
				res.client_hello = hello;
				const Bytes flight = cat({plan.prefix, hello});
				std::size_t from = 0;
				for (const std::size_t cut : cuts)
				{
					write(slice(flight, from, cut));
					pump(Clock::now() + plan.gap);
					from = cut;
				}
				write(slice(flight, from, flight.size()));
				// The rest as the server answers.
				std::size_t fed = 0;
				bool requests_sent = false;
				const TimePoint until = limit();
				for (;;)
				{
					if (t_.received.size() > fed)
					{
						BIO_write(rb, t_.received.data() + fed, static_cast<int>(t_.received.size() - fed));
						fed = t_.received.size();
					}
					if (!res.handshake)
					{
						ERR_clear_error();
						const int r = SSL_do_handshake(ssl.get());
						if (r == 1)
						{
							res.handshake = true;
							describe(ssl.get(), res);
						}
						else if (SSL_get_error(ssl.get(), r) != SSL_ERROR_WANT_READ)
						{
							res.error = "handshake: " + tls::take_errors();
							send_all(wb);
							break;
						}
					}
					if (res.handshake && !requests_sent)
					{
						for (const Bytes& q : plan.requests)
						{
							std::size_t n = 0;
							if (SSL_write_ex(ssl.get(), q.data(), q.size(), &n) != 1 || n != q.size()) res.error = "SSL_write: " + tls::take_errors();
						}
						requests_sent = true;
					}
					send_all(wb);
					if (res.handshake && !res.close_notify && !read_plain(ssl.get(), res)) break;
					if (closed() && t_.received.size() == fed) break;
					if (Clock::now() >= until)
					{
						t_.timed_out = true;
						break;
					}
					if (t_.received.size() == fed) pump_some(until);
				}
				if (SSL_SESSION* sess = SSL_get_session(ssl.get())) res.resumable = SSL_SESSION_is_resumable(sess) == 1;
				ERR_clear_error();
				t_.tls = std::move(res);
			}
#endif

			void write(const Bytes& b)
			{
				pump(Clock::now());  // see a close first, as a client would
				if (closed())
				{
					t_.write_failed = true;
					return;
				}
				t_.write_times.push_back(Clock::now());
				std::size_t done = 0;
				while (done < b.size())
				{
#if defined(_WIN32)
					const int w = ::send(as_socket(fd_), reinterpret_cast<const char*>(b.data() + done), static_cast<int>(std::min<std::size_t>(b.size() - done, std::size_t{1} << 30)), 0);
					if (w == SOCKET_ERROR)
					{
						t_.write_failed = true;
						return;
					}
#else
					const ssize_t w = ::send(fd_, b.data() + done, b.size() - done, MSG_NOSIGNAL);
					if (w < 0)
					{
						if (errno == EINTR) continue;
						t_.write_failed = true;
						return;
					}
#endif
					done += static_cast<std::size_t>(w);
				}
				t_.sent.insert(t_.sent.end(), b.begin(), b.end());
			}

#if defined(_WIN32)
			void shutdown_write()
			{
				if (fd_ >= 0) ::shutdown(as_socket(fd_), SD_SEND);
			}

			void reset()
			{
				if (fd_ < 0) return;
				const linger l{1, 0};
				::setsockopt(as_socket(fd_), SOL_SOCKET, SO_LINGER, reinterpret_cast<const char*>(&l), sizeof(l));
				::closesocket(as_socket(fd_));
				fd_ = -1;
				t_.client_reset = true;
			}
#else
			void shutdown_write()
			{
				if (fd_ >= 0) ::shutdown(fd_, SHUT_WR);
			}

			void reset()
			{
				if (fd_ < 0) return;
				const linger l{1, 0};
				::setsockopt(fd_, SOL_SOCKET, SO_LINGER, &l, sizeof(l));
				::close(fd_);
				fd_ = -1;
				t_.client_reset = true;
			}
#endif

			TimePoint limit() const { return Clock::now() + limits_.wait; }

		private:
			bool has_line() const
			{
				for (std::size_t i = 1; i < t_.received.size(); ++i)
				{
					if (t_.received[i] == std::byte{'\n'} && t_.received[i - 1] == std::byte{'\r'}) return true;
				}
				return false;
			}

			void read_some()
			{
#if defined(_WIN32)
				// Called only after WSAPoll reported the socket readable, so the read does not block.
				const int n = ::recv(as_socket(fd_), reinterpret_cast<char*>(buf_.data()), static_cast<int>(buf_.size()), 0);
				if (n == SOCKET_ERROR)
				{
					const int e = WSAGetLastError();
					if (e == WSAEWOULDBLOCK || e == WSAEINTR) return;
					t_.reset = true;
					t_.end = Clock::now();
					return;
				}
#else
				const ssize_t n = ::recv(fd_, buf_.data(), buf_.size(), MSG_DONTWAIT);
#endif
				if (n > 0)
				{
					if (!t_.first_byte) t_.first_byte = Clock::now();
					t_.received.insert(t_.received.end(), buf_.begin(), buf_.begin() + n);
					return;
				}
				if (n == 0)
				{
					t_.eof = true;
					t_.end = Clock::now();
					return;
				}
				if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return;
				t_.reset = true;
				t_.end = Clock::now();
			}

#if defined(ONEPORT_HAVE_TLS)
			struct SslFree
			{
				void operator()(SSL* s) const noexcept { SSL_free(s); }
			};

			static Bytes take(BIO* b)
			{
				Bytes out;
				std::array<std::byte, 4096> buf{};
				int n = 0;
				while ((n = BIO_read(b, buf.data(), static_cast<int>(buf.size()))) > 0) out.insert(out.end(), buf.begin(), buf.begin() + n);
				return out;
			}

			void send_all(BIO* b)
			{
				const Bytes out = take(b);
				if (!out.empty()) write(out);
			}

			/// Decrypts what has arrived. False once the exchange cannot go on.
			static bool read_plain(SSL* ssl, TlsResult& res)
			{
				std::array<std::byte, 4096> buf{};
				for (;;)
				{
					std::size_t n = 0;
					ERR_clear_error();
					if (SSL_read_ex(ssl, buf.data(), buf.size(), &n) == 1)
					{
						res.plain.insert(res.plain.end(), buf.begin(), buf.begin() + static_cast<std::ptrdiff_t>(n));
						continue;
					}
					const int e = SSL_get_error(ssl, 0);
					if (e == SSL_ERROR_WANT_READ) return true;
					if (e == SSL_ERROR_ZERO_RETURN)
					{
						res.close_notify = true;
						return true;
					}
					// An EOF without close_notify, or an error: the exchange ends here.
					if (res.error.empty() && e != SSL_ERROR_SYSCALL) res.error = "SSL_read: " + tls::take_errors();
					ERR_clear_error();
					return false;
				}
			}

			static void describe(SSL* ssl, TlsResult& res)
			{
				res.version = SSL_get_version(ssl);
				res.cipher = SSL_get_cipher_name(ssl);
				if (const char* g = SSL_get0_group_name(ssl)) res.group = g;
				const char* sig = nullptr;
				if (SSL_get0_peer_signature_name(ssl, &sig) == 1 && sig != nullptr) res.sigalg = sig;
				const unsigned char* p = nullptr;
				unsigned int n = 0;
				SSL_get0_alpn_selected(ssl, &p, &n);
				res.alpn.assign(reinterpret_cast<const char*>(p), n);
				res.verified = SSL_get0_peer_certificate(ssl) != nullptr && SSL_get_verify_result(ssl) == X509_V_OK;
			}
#endif

			Transcript& t_;
			const Limits& limits_;
			int fd_ = -1;
			std::vector<std::byte> buf_ = std::vector<std::byte>(65536);
#if defined(_WIN32)
			HANDLE timer_ = nullptr;  // the high-resolution waitable timer of wait_readable()
#endif
		};

	}  // namespace

	Transcript run(const Script& script, std::uint16_t port, const Limits& limits)
	{
		Transcript t;
		Client client(t, limits);
		if (!client.connect(port)) return t;
		for (const Step& s : script.steps)
		{
			if (t.client_reset) break;
			switch (s.kind)
			{
				case Step::Kind::write: client.write(s.bytes); break;
				case Step::Kind::gap: client.pump(Clock::now() + s.d); break;
				case Step::Kind::write_at:
				{
					const TimePoint at = (s.anchor == Anchor::before_connect ? t.before_connect : t.after_connect) + s.d;
					client.pump(at);
					client.write(s.bytes);
					break;
				}
				case Step::Kind::shutdown_write: client.shutdown_write(); break;
				case Step::Kind::reset: client.reset(); break;
				case Step::Kind::await_line:
				{
					const TimePoint until = client.limit();
					client.pump(until, true);
					if (Clock::now() >= until) t.timed_out = true;
					break;
				}
				case Step::Kind::await_close:
				{
					const TimePoint until = client.limit();
					client.pump(until);
					if (!client.closed()) t.timed_out = true;
					break;
				}
				case Step::Kind::tls:
#if defined(ONEPORT_HAVE_TLS)
					client.tls_exchange(*s.plan);
					break;
#else
					throw std::runtime_error("opcase: this build has no TLS client");
#endif
			}
		}
		if (!t.client_reset)
		{
			const TimePoint until = client.limit();
			client.pump(until);
			if (!client.closed()) t.timed_out = true;
		}
		return t;
	}

#else

	Transcript run(const Script&, std::uint16_t, const Limits&) { throw std::runtime_error("opcase: the client runs on Linux only"); }

#endif

}  // namespace oneport::opcase
