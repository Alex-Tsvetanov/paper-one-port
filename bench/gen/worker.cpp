// opgen's worker: the loads, the loop, and each connection from connect to its end (worker.hpp).
// The protocols' readers are in parse.cpp.
#include "worker.hpp"

#include "tls.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <utility>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <sched.h>
#include <sys/epoll.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <unistd.h>

#include <openssl/err.h>

namespace oneport::opgen::detail
{

	Worker::Worker(const Options& o, Control& ctl, unsigned index, SSL_CTX* ctx) : o_(o), ctl_(ctl), index_(index), ctx_(ctx)
	{
		src_next_ = index;
	}

	Worker::~Worker()
	{
		for (Conn& c : conns_) drop(c);
		if (spare_fd_ >= 0) ::close(spare_fd_);
	}

	void Worker::run()
	{
		try
		{
			if (!o_.cpus.empty())
			{
				cpu_set_t set;
				CPU_ZERO(&set);
				CPU_SET(o_.cpus[index_ % o_.cpus.size()], &set);
				if (pthread_setaffinity_np(pthread_self(), sizeof(set), &set) != 0) throw std::runtime_error("pthread_setaffinity_np failed");
			}
			// A timed wait ends when it is due, not up to the default 50 us of timer slack later: the
			// open loop starts each exchange at its due time, and WL2 measures from it (a design
			// choice of M3, design/status.md).
			if (::prctl(PR_SET_TIMERSLACK, 1UL, 0UL, 0UL, 0UL) != 0) throw std::runtime_error("prctl(PR_SET_TIMERSLACK) failed");
			loop_.start();
			if (o_.rate > 0) run_open();
			else run_closed();
		}
		catch (const std::exception& e)
		{
			error_ = e.what();
		}
		for (Conn& c : conns_) drop(c);
		ctl_.finished.fetch_add(1, std::memory_order_release);
	}

	std::uint32_t Worker::my_slots() const noexcept
	{
		const std::uint32_t n = o_.threads;
		return o_.conns / n + (index_ < o_.conns % n ? 1 : 0);
	}

	void Worker::run_closed()
	{
		const std::uint32_t slots = o_.probe ? (index_ == 0 ? 1 : 0) : my_slots();
		conns_.resize(slots);
		records_.reserve(kRecordsReserved);
		for (std::uint32_t i = 0; i < slots; ++i) start(i, now_ns());
		std::int64_t drain_until = INT64_MAX;
		for (;;)
		{
			const int phase = ctl_.phase.load(std::memory_order_acquire);
			if (phase >= 2) break;
			if (phase == 1 && drain_until == INT64_MAX) drain_until = now_ns() + o_.timeout.count() + 100'000'000;
			if (active_ == 0 && (phase == 1 || o_.probe)) break;
			if (now_ns() >= drain_until) break;
			pass(std::chrono::milliseconds(retry_.empty() ? 50 : 1));
			if (o_.probe && !records_.empty()) break;
		}
	}

	void Worker::run_open()
	{
		records_.reserve(kRecordsReserved);
		conns_.reserve(kOpenSlotsReserved);
		// Thread k takes the global schedule's exchanges n with n mod threads = k: due at
		// origin + n / rate. The next exchange's socket is made, set up and bound before it falls
		// due, so at the due time only the registration and connect run; and the last kSpinNs
		// before a due time are spent polling, not asleep, so no wake-up latency delays it.
		const double step = 1e9 / o_.rate;
		std::uint64_t n = index_;
		std::int64_t drain_until = INT64_MAX;
		for (;;)
		{
			const int phase = ctl_.phase.load(std::memory_order_acquire);
			if (phase >= 2) break;
			const std::int64_t t_end = ctl_.t_end.load(std::memory_order_acquire);
			const std::int64_t now = now_ns();
			// Start every exchange that has fallen due, and none due at or after the end.
			for (;;)
			{
				const auto due = ctl_.origin + static_cast<std::int64_t>(std::llround(static_cast<double>(n) * step));
				if (due > now || due >= t_end) break;
				const std::uint32_t i = take_slot();
				start(i, due);
				n += o_.threads;
			}
			if (phase == 1)
			{
				if (drain_until == INT64_MAX) drain_until = now + o_.timeout.count() + 100'000'000;
				if (active_ == 0 || now >= drain_until) break;
			}
			else if (spare_fd_ < 0)
			{
				spare_fd_ = make_socket();
			}
			const auto next_due = ctl_.origin + static_cast<std::int64_t>(std::llround(static_cast<double>(n) * step));
			std::int64_t wait = std::max<std::int64_t>(0, next_due - now_ns() - kSpinNs);
			wait = std::min<std::int64_t>(wait, 50'000'000);
			if (!retry_.empty()) wait = std::min<std::int64_t>(wait, 1'000'000);
			pass(std::chrono::nanoseconds(wait));
		}
		unfinished_ = active_;
		if (spare_fd_ >= 0) ::close(std::exchange(spare_fd_, -1));
	}

	int Worker::make_socket()
	{
		const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
		if (fd < 0) return -1;
		const int one = 1;
		::setsockopt(fd, IPPROTO_IP, IP_BIND_ADDRESS_NO_PORT, &one, sizeof(one));
		::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
		sockaddr_in src{};
		src.sin_family = AF_INET;
		src.sin_addr.s_addr = htonl(next_src());
		if (::bind(fd, reinterpret_cast<const sockaddr*>(&src), sizeof(src)) != 0)
		{
			::close(fd);
			return -1;
		}
		return fd;
	}

	std::uint32_t Worker::take_slot()
	{
		if (!free_.empty())
		{
			const std::uint32_t i = free_.back();
			free_.pop_back();
			return i;
		}
		conns_.emplace_back();
		return static_cast<std::uint32_t>(conns_.size() - 1);
	}

	void Worker::pass(std::chrono::nanoseconds bound)
	{
		const auto events = loop_.wait(bound);
		for (const epoll_event& ev : events)
		{
			const auto idx = static_cast<std::uint32_t>(ev.data.u64 >> 32);
			const auto gen = static_cast<std::uint32_t>(ev.data.u64 & 0xFFFFFFFFu);
			if (idx >= conns_.size()) continue;
			Conn& c = conns_[idx];
			if (!c.active || c.gen != gen || c.fd < 0) continue;
			on_event(idx, ev.events);
		}
		const std::int64_t now = now_ns();
		while (!deadlines_.empty() && deadlines_.front().at <= now)
		{
			const Deadline d = deadlines_.front();
			deadlines_.pop_front();
			Conn& c = conns_[d.idx];
			if (c.active && c.xid == d.xid) fail(d.idx, End::timeout);
		}
		if (!retry_.empty())
		{
			std::vector<std::uint32_t> again;
			again.swap(retry_);
			for (const std::uint32_t i : again) next(i);
		}
	}

	std::uint32_t Worker::next_src() noexcept
	{
		const std::uint32_t a = o_.src_base + static_cast<std::uint32_t>(src_next_ % o_.k_src);
		src_next_ += o_.threads;
		return a;
	}

	void Worker::arm_deadline(std::uint32_t i)
	{
		Conn& c = conns_[i];
		c.xid = ++xid_;
		deadlines_.push_back(Deadline{i, c.xid, now_ns() + o_.timeout.count()});
	}

	void Worker::start(std::uint32_t i, std::int64_t due)
	{
		Conn& c = conns_[i];
		c.active = true;
		++active_;
		peak_ = std::max<std::uint64_t>(peak_, active_);
		c.connecting = true;
		c.handshaking = false;
		c.ready = false;
		c.done_reading = false;
		c.in_len = 0;
		c.out.clear();
		c.out_off = 0;
		c.stream = 1;
		c.status_ok = false;
		c.body = 0;
		c.window_used = 0;
		c.rec = Record{};
		c.rec.due = due;
		++c.gen;
		arm_deadline(i);
		const int fd = spare_fd_ >= 0 ? std::exchange(spare_fd_, -1) : make_socket();
		if (fd < 0)
		{
			c.rec.begin = now_ns();
			fail(i, End::connect);
			return;
		}
		c.fd = fd;
		loop_.add(fd, EPOLLIN | EPOLLOUT | EPOLLRDHUP | EPOLLET, (static_cast<std::uint64_t>(i) << 32) | c.gen);
		sockaddr_in to{};
		to.sin_family = AF_INET;
		to.sin_port = htons(o_.port);
		to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		c.rec.begin = now_ns();  // just before connect (WL1)
		if (o_.rate <= 0) c.rec.due = c.rec.begin;
		++connects_;
		if (::connect(fd, reinterpret_cast<const sockaddr*>(&to), sizeof(to)) == 0)
		{
			connected(i);
			return;
		}
		if (errno == EINPROGRESS) return;
		fail(i, End::connect);
	}

	void Worker::connected(std::uint32_t i)
	{
		Conn& c = conns_[i];
		c.connecting = false;
		if (o_.load == Load::keepalive && (o_.proto == Proto::http1 || o_.proto == Proto::h2c))
		{
			// Keep-alive: the connect is the connection's setup; the first request starts now (TLS
			// and MQTT restart it after their handshake or CONNECT).
			c.rec.begin = now_ns();
			c.rec.due = c.rec.begin;
		}
		switch (o_.proto)
		{
			case Proto::http1: queue(c, o_.load == Load::churn ? http_close() : http_keep()); break;
			case Proto::h2c: queue(c, h2_opening()); break;
			case Proto::mqtt: queue(c, mqtt_connect()); break;
			case Proto::ssh: queue(c, ssh_line()); break;
			case Proto::tls_stub: queue(c, stub_hello()); break;
			case Proto::tls:
			{
				c.ssl = SSL_new(ctx_);
				if (c.ssl == nullptr || SSL_set_fd(c.ssl, c.fd) != 1)
				{
					fail(i, End::tls);
					return;
				}
				SSL_set_connect_state(c.ssl);
				SSL_set_tlsext_host_name(c.ssl, std::string(tls::kServerName).c_str());
				SSL_set1_host(c.ssl, std::string(tls::kServerName).c_str());
				static const std::vector<unsigned char> alpn = tls::alpn_wire("http/1.1");
				SSL_set_alpn_protos(c.ssl, alpn.data(), static_cast<unsigned>(alpn.size()));
				c.handshaking = true;
				drive_tls(i);
				return;
			}
		}
		flush(i);
	}

	void Worker::queue(Conn& c, const Bytes& b)
	{
		if (c.out_off == c.out.size())
		{
			c.out.clear();
			c.out_off = 0;
		}
		c.out.insert(c.out.end(), b.begin(), b.end());
	}

	bool Worker::flush(std::uint32_t i)
	{
		Conn& c = conns_[i];
		if (o_.proto == Proto::tls) return flush_tls(i);
		while (c.out_off < c.out.size())
		{
			const ssize_t n = ::send(c.fd, c.out.data() + c.out_off, c.out.size() - c.out_off, MSG_NOSIGNAL);
			if (n > 0)
			{
				c.out_off += static_cast<std::size_t>(n);
				continue;
			}
			if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return true;
			if (n < 0 && errno == EINTR) continue;
			fail(i, End::reset);
			return false;
		}
		return true;
	}

	bool Worker::flush_tls(std::uint32_t i)
	{
		Conn& c = conns_[i];
		if (c.handshaking || c.out_off == c.out.size()) return true;
		std::size_t n = 0;
		if (SSL_write_ex(c.ssl, c.out.data() + c.out_off, c.out.size() - c.out_off, &n) == 1)
		{
			c.out_off += n;
			return true;
		}
		const int e = SSL_get_error(c.ssl, 0);
		if (e == SSL_ERROR_WANT_WRITE || e == SSL_ERROR_WANT_READ) return true;
		ERR_clear_error();
		fail(i, e == SSL_ERROR_SYSCALL ? End::reset : End::tls);
		return false;
	}

	void Worker::on_event(std::uint32_t i, std::uint32_t events)
	{
		Conn& c = conns_[i];
		const std::uint64_t xid = c.xid;
		if (c.connecting)
		{
			if ((events & (EPOLLOUT | EPOLLERR | EPOLLHUP)) == 0) return;
			int err = 0;
			socklen_t len = sizeof(err);
			::getsockopt(c.fd, SOL_SOCKET, SO_ERROR, &err, &len);
			if (err != 0)
			{
				fail(i, End::connect);
				return;
			}
			connected(i);
			if (!c.active || c.xid != xid) return;  // ended (and the slot may hold a new connection)
		}
		if (o_.proto == Proto::tls)
		{
			if ((events & EPOLLIN) != 0 && c.rec.first < 0) c.rec.first = now_ns();  // the ServerHello's arrival
			drive_tls(i);
			return;
		}
		if ((events & EPOLLOUT) != 0 && !flush(i)) return;
		if (!c.active || c.xid != xid) return;
		if ((events & (EPOLLIN | EPOLLRDHUP | EPOLLHUP | EPOLLERR)) != 0) readable(i);
	}

	void Worker::readable(std::uint32_t i)
	{
		Conn& c = conns_[i];
		const std::uint64_t xid = c.xid;
		for (;;)
		{
			if (c.in_len == c.in.size())
			{
				fail(i, End::protocol);
				return;
			}
			const ssize_t n = ::recv(c.fd, c.in.data() + c.in_len, c.in.size() - c.in_len, 0);
			if (n > 0)
			{
				if (c.rec.first < 0) c.rec.first = now_ns();
				c.in_len += static_cast<std::uint32_t>(n);
				parse(i);
				if (!c.active || c.xid != xid) return;  // the exchange ended (and a new one may have started)
				continue;
			}
			if (n == 0)
			{
				on_eof(i);
				return;
			}
			if (errno == EINTR) continue;
			if (errno == EAGAIN || errno == EWOULDBLOCK) return;
			fail(i, End::reset);
			return;
		}
	}

	void Worker::drive_tls(std::uint32_t i)
	{
		Conn& c = conns_[i];
		const std::uint64_t xid = c.xid;
		if (c.handshaking)
		{
			const int r = SSL_do_handshake(c.ssl);
			if (r != 1)
			{
				const int e = SSL_get_error(c.ssl, r);
				if (e == SSL_ERROR_WANT_READ || e == SSL_ERROR_WANT_WRITE) return;
				ERR_clear_error();
				fail(i, e == SSL_ERROR_SYSCALL ? End::reset : End::tls);
				return;
			}
			c.handshaking = false;
			queue(c, o_.load == Load::churn ? http_close() : http_keep());
			if (o_.load == Load::keepalive)
			{
				// The handshake is the connection's setup: the first request starts now.
				c.ready = true;
				c.rec.begin = now_ns();
				c.rec.due = c.rec.begin;
				c.rec.first = -1;
			}
		}
		if (!flush_tls(i)) return;
		for (;;)
		{
			if (c.in_len == c.in.size())
			{
				fail(i, End::protocol);
				return;
			}
			std::size_t n = 0;
			errno = 0;
			if (SSL_read_ex(c.ssl, c.in.data() + c.in_len, c.in.size() - c.in_len, &n) == 1)
			{
				if (o_.load == Load::keepalive && c.rec.first < 0) c.rec.first = now_ns();
				c.in_len += static_cast<std::uint32_t>(n);
				parse(i);
				if (!c.active || c.xid != xid) return;
				if (!flush_tls(i)) return;
				continue;
			}
			const int e = SSL_get_error(c.ssl, 0);
			if (e == SSL_ERROR_WANT_READ) return;
			if (e == SSL_ERROR_WANT_WRITE) return;
			ERR_clear_error();
			// close_notify, or (OpenSSL 3) an EOF with no error queued and no errno.
			if (e == SSL_ERROR_ZERO_RETURN || (e == SSL_ERROR_SYSCALL && errno == 0 && ERR_peek_error() == 0))
			{
				on_eof(i);  // close_notify, or the TCP end
				return;
			}
			fail(i, e == SSL_ERROR_SYSCALL ? End::reset : End::tls);
			return;
		}
	}

	void Worker::request_done(std::uint32_t i, const Bytes& next)
	{
		Conn& c = conns_[i];
		c.ready = true;
		c.rec.end = now_ns();
		c.rec.how = End::completed;
		if (c.in_len != 0)
		{
			fail(i, End::protocol);
			return;
		}
		records_.push_back(c.rec);
		if (ctl_.phase.load(std::memory_order_acquire) >= 1 || o_.probe)
		{
			close_conn(i);
			return;
		}
		c.rec = Record{};
		c.rec.begin = now_ns();
		c.rec.due = c.rec.begin;
		arm_deadline(i);
		queue(c, next);
		flush(i);
	}

	void Worker::on_eof(std::uint32_t i)
	{
		Conn& c = conns_[i];
		if (c.done_reading)
		{
			complete(i);  // the server closed first, after the whole response (WL1)
			return;
		}
		fail(i, End::eof);
	}

	void Worker::complete(std::uint32_t i)
	{
		Conn& c = conns_[i];
		c.rec.end = now_ns();
		c.rec.how = End::completed;
		records_.push_back(c.rec);
		if (o_.probe) probe_detail = std::string(name(o_.proto)) + ": exchange completed";
		close_conn(i);
		next(i);
	}

	void Worker::fail(std::uint32_t i, End how)
	{
		Conn& c = conns_[i];
		c.rec.end = now_ns();
		c.rec.how = how;
		if (c.rec.begin == 0) c.rec.begin = c.rec.end;
		records_.push_back(c.rec);
		if (o_.probe)
		{
			static constexpr std::array<std::string_view, 7> names{"completed", "connect", "timeout", "reset", "eof", "protocol", "tls"};
			probe_detail = std::string(name(o_.proto)) + ": failed (" + std::string(names[static_cast<std::size_t>(how)]) + ")";
		}
		const bool was_connect = how == End::connect;
		close_conn(i);
		if (was_connect && o_.rate <= 0 && !o_.probe)
		{
			retry_.push_back(i);  // a slot whose connect failed tries again in the next pass
			return;
		}
		next(i);
	}

	void Worker::close_conn(std::uint32_t i)
	{
		Conn& c = conns_[i];
		drop(c);
		if (c.active)
		{
			c.active = false;
			--active_;
		}
		c.xid = 0;
		if (o_.rate > 0) free_.push_back(i);
	}

	void Worker::drop(Conn& c) noexcept
	{
		if (c.ssl != nullptr)
		{
			SSL_free(c.ssl);
			c.ssl = nullptr;
		}
		if (c.fd >= 0)
		{
			::close(c.fd);
			c.fd = -1;
		}
	}

	void Worker::next(std::uint32_t i)
	{
		if (o_.rate > 0 || o_.probe) return;
		if (ctl_.phase.load(std::memory_order_acquire) >= 1) return;
		start(i, now_ns());
	}

}  // namespace oneport::opgen::detail
