#include "script.hpp"

#include <algorithm>
#include <cerrno>
#include <stdexcept>
#include <string>
#include <system_error>
#include <thread>

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
		steps.push_back(Step{Step::Kind::write, std::move(b), {}, Anchor::after_connect});
		return *this;
	}
	Script& Script::gap(std::chrono::nanoseconds d)
	{
		steps.push_back(Step{Step::Kind::gap, {}, d, Anchor::after_connect});
		return *this;
	}
	Script& Script::write_at(Anchor a, std::chrono::nanoseconds d, Bytes b)
	{
		steps.push_back(Step{Step::Kind::write_at, std::move(b), d, a});
		return *this;
	}
	Script& Script::shutdown_write()
	{
		steps.push_back(Step{Step::Kind::shutdown_write, {}, {}, Anchor::after_connect});
		return *this;
	}
	Script& Script::reset()
	{
		steps.push_back(Step{Step::Kind::reset, {}, {}, Anchor::after_connect});
		return *this;
	}
	Script& Script::await_line()
	{
		steps.push_back(Step{Step::Kind::await_line, {}, {}, Anchor::after_connect});
		return *this;
	}
	Script& Script::await_close()
	{
		steps.push_back(Step{Step::Kind::await_close, {}, {}, Anchor::after_connect});
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

#if defined(__linux__)

	namespace
	{

		class Client
		{
		public:
			Client(Transcript& t, const Limits& limits) : t_(t), limits_(limits) {}
			~Client()
			{
				if (fd_ >= 0) ::close(fd_);
			}
			Client(const Client&) = delete;
			Client& operator=(const Client&) = delete;

			bool connect(std::uint16_t port)
			{
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
					pollfd p{fd_, POLLIN, 0};
					const int r = ::poll(&p, 1, static_cast<int>(std::min<long long>(left, 1000)));
					if (r < 0 && errno == EINTR) continue;
					if (r > 0) read_some();
					if (Clock::now() >= until) return;
				}
			}

			bool closed() const noexcept { return t_.eof || t_.reset || fd_ < 0; }

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
					const ssize_t w = ::send(fd_, b.data() + done, b.size() - done, MSG_NOSIGNAL);
					if (w < 0)
					{
						if (errno == EINTR) continue;
						t_.write_failed = true;
						return;
					}
					done += static_cast<std::size_t>(w);
				}
				t_.sent.insert(t_.sent.end(), b.begin(), b.end());
			}

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
				const ssize_t n = ::recv(fd_, buf_.data(), buf_.size(), MSG_DONTWAIT);
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

			Transcript& t_;
			const Limits& limits_;
			int fd_ = -1;
			std::vector<std::byte> buf_ = std::vector<std::byte>(65536);
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

	Transcript run(const Script&, std::uint16_t, const Limits&) { throw std::runtime_error("opcase: the M1 client runs on Linux only"); }

#endif

}  // namespace oneport::opcase
