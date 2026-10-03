// Relay dispatch (design/proposal.md I17, I18; hypotheses.md, section 2.1, "Dispatch") and the
// relay's copy (rule E of section 8: user-space buffers of RELAY_BUF bytes per direction, or
// splice), on epoll and io_uring.
//
// A connection classified on a relaying (one-port) listener, or dispatched to the fallback by
// T_fb, is not handed to an in-process handler: the front opens a loopback connection to the
// backend port of its class (the backend's listeners follow --relay-port in the order of I20),
// writes the bytes replay read, then copies both ways. TLS is never terminated: the front reads
// the ClientHello's records itself, reassembled up to B_CH message bytes with
// bench/server/clienthello.hpp, and routes by its SNI and ALPN (pass-through). In replay a
// ClientHello whole in the first read is routed from the receive buffer; one still incomplete
// after a read moves into storage of its own, sized to the record bytes the reassembly needs next
// (a copy in user space, counted), the receive buffer goes back to the pool, and the next reads go
// into the storage (M5: a pending connection then holds the records it has, not a receive buffer);
// in peek they stay in the socket, and SO_RCVLOWAT waits for the bytes the reassembly needs next;
// T_dec bounds the wait. The route table (a design choice of M2b, the one
// name and the two protocols the frozen settings serve): SNI oneport.test, with no ALPN or an
// ALPN list that offers http/1.1 or h2, goes to the backend's TLS port; any other ClientHello,
// or a record stream that is not one, is closed (counted route_rejected).
//
// Design choices of M2b, recorded in design/status.md:
//   - A direction's end is passed on as a half-close (shutdown of the destination's writing), and
//     the connection closes when both directions have ended; an error closes both, and a reset
//     on either side closes the other by reset. Reading "until one side closes" as each side's
//     direction keeps exchanges whose client shuts down writing before it reads (HC1's h2c).
//   - The PROXY header is consumed by the front (I9) and not passed on: the backend runs with
//     --proxy off, and the source the server records is the front's.
//   - TCP_NODELAY on both relayed sockets, as nginx's stream module sets by default
//     (tcp_nodelay on, for client and proxied connections), so a write is passed on at once. The
//     client's socket inherits it from the relaying listener, set once at start (M5); the backend's
//     is set before its connect.
//   - System calls the copy does not need are not made (M5): a connect whose end epoll reports with
//     EPOLLOUT and no error is not asked for SO_ERROR; a side is read when the copy starts only if
//     it may hold bytes (Relay::up_ready, down_ready); a read that returns less than its room
//     after an event that reported the source's half-close (EPOLLRDHUP) has reached the end, which
//     no second read is made to see (TCP delivers the FIN after every byte before it); and the
//     direction that ends last is closed by close(), whose FIN passes its end on, without a
//     shutdown() first.
//   - T_dec bounds pass-through's wait for the whole ClientHello: the route is the decision
//     there, so T_dec stays armed from accept (or the PROXY header's end) until the route is
//     chosen; a ClientHello still incomplete at T_dec is closed and counted route_timeouts
//     (M3's reading, which supersedes M2b's; design/status.md). No timer once a connection is
//     relayed.
#include "worker.hpp"

#if defined(__linux__)

#include "clienthello.hpp"

#include <fcntl.h>
#include <linux/io_uring.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace oneport::server::detail
{

	namespace
	{

		constexpr unsigned kSpliceFlags = SPLICE_F_NONBLOCK | SPLICE_F_MOVE;

		/// The pass-through route table: SNI oneport.test (the name of the test certificate, I24),
		/// and no ALPN or an ALPN list that offers http/1.1 or h2, the protocols the backend's TLS
		/// port serves.
		bool routable(const clienthello::Hello& h, std::span<const std::byte> msg) noexcept
		{
			if (clienthello::text(msg, h.sni) != tls::kServerName) return false;
			if (!h.alpn.present) return true;
			const std::string_view list = clienthello::text(msg, h.alpn);
			for (std::size_t p = 0; p < list.size();)
			{
				const std::size_t n = static_cast<unsigned char>(list[p]);
				if (p + 1 + n > list.size()) return false;
				const std::string_view name = list.substr(p + 1, n);
				if (name == "http/1.1" || name == "h2") return true;
				p += 1 + n;
			}
			return false;
		}

	}  // namespace

	void Worker::start_relay(Conn* c, Proto p, Entry entry)
	{
		c->relay = std::make_unique<Relay>();
		Relay& r = *c->relay;
		r.proto = p;
		r.splice = shared_.splice;
		c->proto = p;
		// The client's side may hold bytes the relay has not read: a peek left them queued, a read
		// filled the buffer, the peer's end was seen, or nothing was read yet (T_fb).
		r.up_ready = entry != Entry::replay || c->last_read_full || c->eof_seen || c->observe_pass == pass_;
		if (p != Proto::tls)
		{
			relay_connect(c, Route::by_class);
			return;
		}
		// Pass-through: the ClientHello's records decide the route.
		c->stage = Stage::route;
		r.route = Route::by_sni;
		if (entry == Entry::peek)
		{
			r.up_ready = true;  // the bytes are in the socket
			route_readable(c, c->observe_pass == pass_);
			return;
		}
		// Replay: the bytes are in the receive buffer.
		const std::span<const std::byte> held =
			c->buf != nullptr ? std::span<const std::byte>(c->buf->data.data() + c->beg, c->len - c->beg) : std::span<const std::byte>();
		if (!try_route(c, held, c->eof_seen)) return;
		// Epoll is edge-triggered: a read that filled the buffer may have left bytes queued.
		if (c->stage == Stage::route && !uring() && c->last_read_full) route_readable(c, false);
	}

	// ---- Pass-through ----

	void Worker::route_readable(Conn* c, bool rdhup)
	{
		Relay& r = *c->relay;
		if (peeks(c))
		{
			if (hello_scratch_.size() < kHelloWireMax) hello_scratch_.resize(kHelloWireMax);
			const ssize_t n = peek(c, hello_scratch_);
			if (n < 0) return;  // nothing queued, or closed by peek()
			if (n == 0)
			{
				route_reject(c);  // the peer ended before its ClientHello did
				return;
			}
			try_route(c, std::span<const std::byte>(hello_scratch_.data(), static_cast<std::size_t>(n)), rdhup);
			return;
		}
		// Replay on epoll: read on, into the receive buffer or the ClientHello's own storage.
		if (r.hello.empty())
		{
			if (c->buf == nullptr) take_buffer(c);
			route_after_read(c, read_into(c, rdhup));
			return;
		}
		ReadResult rr;
		for (;;)
		{
			// The storage holds what the reassembly needs next; a read that fills it may leave more
			// queued, which edge-triggered readiness will not report again, so the reassembly is
			// asked for its next need before the next read.
			hello_room(c, r.hello_need);
			const std::size_t room = r.hello.size() - r.hello_len;
			if (room == 0) break;
			const ssize_t n = ::recv(c->fd, r.hello.data() + r.hello_len, room, 0);
			++c_.recv_calls;
			if (n > 0)
			{
				r.hello_len += static_cast<std::uint32_t>(n);
				rr.bytes += static_cast<std::uint32_t>(n);
				c_.bytes_received += static_cast<std::uint64_t>(n);
				c->bytes_received += static_cast<std::uint64_t>(n);
				c->last_read_pass = pass_;
				if (static_cast<std::size_t>(n) < room && !rdhup) break;
				if (static_cast<std::size_t>(n) == room && !hello_needs_more(c))
				{
					r.up_ready = true;  // more may be queued behind the ClientHello
					break;
				}
				continue;
			}
			if (n == 0)
			{
				++c_.recv_eof;
				rr.eof = true;
				c->eof_seen = true;
				break;
			}
			if (errno == EINTR) continue;
			if (errno != EAGAIN && errno != EWOULDBLOCK)
			{
				rr.error = true;
				rr.reset = errno == ECONNRESET;
			}
			else
			{
				++c_.recv_again;
			}
			break;
		}
		route_after_read(c, rr);
	}

	void Worker::route_after_read(Conn* c, const ReadResult& rr)
	{
		if (rr.error)
		{
			relay_abort(c, rr.reset);
			return;
		}
		Relay& r = *c->relay;
		std::span<const std::byte> wire;
		if (!r.hello.empty()) wire = std::span<const std::byte>(r.hello.data(), r.hello_len);
		else if (c->buf != nullptr) wire = std::span<const std::byte>(c->buf->data.data() + c->beg, c->len - c->beg);
		try_route(c, wire, rr.eof || c->eof_seen);
	}

	bool Worker::try_route(Conn* c, std::span<const std::byte> wire, bool eof)
	{
		Relay& r = *c->relay;
		if (!peeks(c)) r.held_max = std::max(r.held_max, static_cast<std::uint32_t>(wire.size()));
		hello_msg_.resize(detect::kBCh);
		const clienthello::Reassembled a = clienthello::reassemble(wire, hello_msg_);
		if (a.verdict == clienthello::Verdict::yes)
		{
			const std::span<const std::byte> msg(hello_msg_.data(), a.msg_len);
			const clienthello::Hello h = clienthello::parse(msg);
			r.hello_msg = a.msg_len;
			r.hello_records = a.records;
			if (!h.ok || !routable(h, msg))
			{
				route_reject(c);
				return false;
			}
			if (peeks(c) && c->lowat != 1) set_lowat(c, 1);  // reset before the relay reads
			relay_connect(c, Route::by_sni);
			return c->fd >= 0 && !c->zombie;
		}
		if (a.verdict == clienthello::Verdict::no || eof || wire.size() >= kHelloWireMax)
		{
			route_reject(c);
			return false;
		}
		if (peeks(c))
		{
			set_lowat(c, a.need);  // the records the reassembly needs next
			return true;
		}
		// Replay: the ClientHello waits in storage of its own, sized to the record bytes the
		// reassembly needs next, and the receive buffer goes back to the pool.
		r.hello_need = std::min<std::uint32_t>(a.need, kHelloWireMax);
		if (r.hello.empty() && c->buf != nullptr && c->len > c->beg)
		{
			const std::uint32_t n = c->len - c->beg;
			r.hello.reserve(r.hello_need);
			r.hello.assign(c->buf->data.data() + c->beg, c->buf->data.data() + c->len);
			r.hello_len = n;
			c_.bytes_copied += n;  // a ClientHello moved out of the receive buffer: a copy in user space (I29)
			c->beg = c->len;
			drop_empty_buffer(c);
		}
		if (c->buf != nullptr) r.buffer_waiting = true;
		hello_room(c, r.hello_need);
		return true;
	}

	void Worker::hello_room(Conn* c, std::uint32_t need)
	{
		Relay& r = *c->relay;
		const std::size_t want = std::min<std::size_t>(kHelloWireMax, std::max<std::size_t>(need, r.hello_len));
		if (want > r.hello.capacity() && r.hello_len > 0) c_.bytes_copied += r.hello_len;  // the storage grows: its bytes move (I29)
		r.hello.resize(want);
		r.hello_room_max = std::max(r.hello_room_max, static_cast<std::uint32_t>(r.hello.capacity()));
	}

	bool Worker::hello_needs_more(Conn* c)
	{
		Relay& r = *c->relay;
		hello_msg_.resize(detect::kBCh);
		const clienthello::Reassembled a = clienthello::reassemble(std::span<const std::byte>(r.hello.data(), r.hello_len), hello_msg_);
		if (a.verdict != clienthello::Verdict::more || r.hello_len >= kHelloWireMax) return false;
		r.hello_need = std::min<std::uint32_t>(a.need, kHelloWireMax);
		return true;
	}

	void Worker::route_reject(Conn* c)
	{
		++c_.route_rejected;
		relay_report(c, Route::rejected);
		close_conn(c);
	}

	// ---- The backend connection ----

	void Worker::relay_connect(Conn* c, Route route)
	{
		disarm(c, TimerKind::t_dec);  // the route is decided: pass-through's wait ends (worker.cpp, dispatch)
		Relay& r = *c->relay;
		r.route = route;
		c->stage = Stage::relay;
		const sockaddr_in& to = shared_.backends[static_cast<std::size_t>(r.proto)];
		r.port = ntohs(to.sin_port);
		const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
		if (fd < 0)
		{
			relay_connected(c, errno);
			return;
		}
		r.fd = fd;
		const int one = 1;
		::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));  // the client's socket inherits it from the listener
		++c_.setsockopt_calls;
		++c_.connect_calls;
		if (uring())
		{
			ur_->connect(fd, &to, sizeof(to), ud(c, Op::b_connect));
			posted(c, Op::b_connect);
			return;
		}
		// Epoll: edge-triggered, with EPOLLOUT for the connect's end and the upward copy's waits.
		const auto slot = static_cast<std::size_t>(fd);
		if (slot >= by_fd_.size())
		{
			by_fd_.resize(slot + 1, nullptr);
			gen_by_fd_.resize(slot + 1, 0);
		}
		by_fd_[slot] = c;
		r.gen = ++gen_by_fd_[slot] & 0x3FFFFFFFu;
		ep_->add(fd, EPOLLIN | EPOLLOUT | EPOLLRDHUP | EPOLLET, tag_of(fd, r.gen));
		++c_.epoll_ctl_calls;
		if (::connect(fd, reinterpret_cast<const sockaddr*>(&to), sizeof(to)) == 0)
		{
			r.down_ready = true;  // not seen through epoll: read it
			relay_connected(c, 0);
			return;
		}
		if (errno == EINPROGRESS) return;  // EPOLLOUT reports the end
		relay_connected(c, errno);
	}

	void Worker::relay_connected(Conn* c, int error)
	{
		Relay& r = *c->relay;
		if (error != 0)
		{
			++c_.relay_connect_errors;
			relay_report(c, Route::connect_failed);
			close_conn(c);
			return;
		}
		r.connected = true;
		++c_.relayed;
		if (r.route == Route::by_sni) ++c_.routed_by_sni;
		relay_report(c, r.route);
		if (r.splice)
		{
			for (Dir* d : {&r.up, &r.down})
			{
				int p[2] = {-1, -1};
				if (::pipe2(p, O_NONBLOCK | O_CLOEXEC) != 0)
				{
					relay_abort(c, false);
					return;
				}
				d->pipe_r = p[0];
				d->pipe_w = p[1];
			}
		}
		const std::uint64_t id = c->id;
		auto alive = [c, id] { return c->id == id && c->fd >= 0 && !c->zombie; };
		if (uring())
		{
			relay_next_uring(c, true);
			if (alive()) relay_next_uring(c, false);
			return;
		}
		// Epoll is edge-triggered: a side that may hold bytes is read now; the bytes replay holds
		// are sent in any case.
		if (r.up_ready ? !relay_pump(c, true) : !send_held(c, true)) return;
		if (alive() && r.down_ready) relay_pump(c, false);
	}

	void Worker::relay_report(const Conn* c, Route route)
	{
		if (shared_.hooks.relayed == nullptr) return;
		const Relay& r = *c->relay;
		RelayReport rep;
		rep.worker = index_;
		rep.conn = c->id;
		rep.peer_port = c->peer_port;
		rep.route = route;
		rep.proto = r.proto;
		rep.backend_port = r.port;
		rep.route_pass = pass_;
		rep.hello_len = r.hello_msg;
		rep.hello_records = r.hello_records;
		rep.held_max = r.held_max;
		rep.hello_room_max = r.hello_room_max;
		rep.buffer_waiting = r.buffer_waiting;
		shared_.hooks.relayed(shared_.hooks.ctx, rep);
	}

	// ---- The copy ----

	bool Worker::has_held(const Conn* c, bool up) const noexcept
	{
		const Relay& r = *c->relay;
		if (up) return r.hello_beg < r.hello_len || (c->buf != nullptr && c->beg < c->len);
		return r.down.buf != nullptr && r.down.beg < r.down.len;
	}

	bool Worker::send_held(Conn* c, bool up)
	{
		Relay& r = *c->relay;
		Dir& d = up ? r.up : r.down;
		const int dst = up ? r.fd : c->fd;
		for (;;)
		{
			std::byte* from = nullptr;
			std::uint32_t* beg = nullptr;
			std::uint32_t end = 0;
			if (up && r.hello_beg < r.hello_len)
			{
				from = r.hello.data();
				beg = &r.hello_beg;
				end = r.hello_len;
			}
			else if (up && c->buf != nullptr && c->beg < c->len)
			{
				from = c->buf->data.data();
				beg = &c->beg;
				end = c->len;
			}
			else if (!up && d.buf != nullptr && d.beg < d.len)
			{
				from = d.buf->data.data();
				beg = &d.beg;
				end = d.len;
			}
			else
			{
				// Everything held is sent: the buffers go back, the ClientHello's storage too.
				d.blocked = false;
				if (up)
				{
					if (!r.hello.empty())
					{
						r.hello.clear();
						r.hello.shrink_to_fit();
						r.hello_len = 0;
						r.hello_beg = 0;
					}
					drop_empty_buffer(c);
				}
				else if (d.buf != nullptr && !(r.down_own && (c->posted & bit(Op::b_recv)) != 0))
				{
					pool_.put(d.buf);
					d.buf = nullptr;
					d.beg = 0;
					d.len = 0;
				}
				return true;
			}
			const std::uint32_t n = end - *beg;
			const ssize_t w = ::send(dst, from + *beg, n, MSG_NOSIGNAL | MSG_DONTWAIT);
			++c_.send_calls;
			if (w < 0)
			{
				if (errno == EINTR) continue;
				if (errno == EAGAIN || errno == EWOULDBLOCK)
				{
					d.blocked = true;
					wait_writable(c, up);
					return true;
				}
				relay_abort(c, errno == ECONNRESET || errno == EPIPE);
				return false;
			}
			*beg += static_cast<std::uint32_t>(w);
			c_.bytes_sent += static_cast<std::uint64_t>(w);
			if (!up) c->bytes_sent += static_cast<std::uint64_t>(w);
			if (static_cast<std::uint32_t>(w) < n)
			{
				d.blocked = true;
				wait_writable(c, up);
				return true;
			}
		}
	}

	void Worker::wait_writable(Conn* c, bool up)
	{
		Relay& r = *c->relay;
		if (uring())
		{
			const Op op = up ? Op::b_poll_out : Op::poll_out;
			if ((c->posted & bit(op)) != 0) return;
			ur_->poll(up ? r.fd : c->fd, POLLOUT, ud(c, op));
			posted(c, op);
			++c_.out_waits;
			return;
		}
		++c_.out_waits;
		// Epoll: the backend socket waits with EPOLLOUT from its registration on; the client's is
		// added once.
		if (up || c->want_out) return;
		ep_->modify(c->fd, kConnEvents | EPOLLOUT, tag_of(c->fd, c->gen));
		++c_.epoll_ctl_calls;
		c->want_out = true;
	}

	bool Worker::relay_after_eof(Conn* c, bool up)
	{
		Relay& r = *c->relay;
		Dir& d = up ? r.up : r.down;
		const Dir& other = up ? r.down : r.up;
		if (!d.shut)
		{
			d.shut = true;
			if (other.shut)
			{
				// Both directions have ended: close() sends this side's FIN, so no shutdown() first.
				close_conn(c);
				return false;
			}
			::shutdown(up ? r.fd : c->fd, SHUT_WR);
			++c_.shutdown_calls;
		}
		if (r.up.shut && r.down.shut)
		{
			close_conn(c);
			return false;
		}
		return true;
	}

	void Worker::relay_abort(Conn* c, bool reset)
	{
		if (c->relay) c->relay->reset = reset;
		close_conn(c);
	}

	// ---- Epoll ----

	void Worker::relay_event(Conn* c, bool backend, std::uint32_t events)
	{
		Relay& r = *c->relay;
		if (backend && !r.connected)
		{
			if ((events & (EPOLLOUT | EPOLLERR | EPOLLHUP)) == 0) return;
			// EPOLLOUT without an error is a connect that ended well; only a failed one is asked
			// for its error (M5).
			int error = 0;
			if ((events & (EPOLLERR | EPOLLHUP)) != 0)
			{
				socklen_t n = sizeof(error);
				if (::getsockopt(r.fd, SOL_SOCKET, SO_ERROR, &error, &n) != 0) error = errno;
				if (error == 0) error = ECONNREFUSED;
			}
			r.down_ready = (events & (EPOLLIN | EPOLLRDHUP)) != 0;
			relay_connected(c, error);
			return;
		}
		if (!r.connected)
		{
			r.up_ready = true;  // the client's readiness while the connect is pending: read it at the start
			return;
		}
		const std::uint64_t id = c->id;
		const bool in = (events & (EPOLLIN | EPOLLRDHUP | EPOLLERR | EPOLLHUP)) != 0;
		const bool out = (events & EPOLLOUT) != 0;
		// The destination's writability first, then the source's readiness.
		const bool dst_up = backend;  // the backend is the upward copy's destination
		if (out && (dst_up ? r.up.blocked : r.down.blocked))
		{
			if (!relay_pump(c, dst_up)) return;
		}
		// A reported half-close with no error (a reset raises EPOLLERR) lets a short read end the source.
		if (in && c->id == id && c->fd >= 0) relay_pump(c, !backend, (events & EPOLLRDHUP) != 0 && (events & EPOLLERR) == 0);
	}

	bool Worker::relay_pump(Conn* c, bool up, bool src_rdhup)
	{
		return c->relay->splice ? pump_splice(c, up) : pump_user(c, up, src_rdhup);
	}

	bool Worker::pump_user(Conn* c, bool up, bool src_rdhup)
	{
		Relay& r = *c->relay;
		Dir& d = up ? r.up : r.down;
		const int src = up ? c->fd : r.fd;
		for (;;)
		{
			if (!send_held(c, up)) return false;
			if (d.blocked) return true;
			if (d.eof) return relay_after_eof(c, up);
			Buffer*& buf = up ? c->buf : d.buf;
			std::uint32_t& beg = up ? c->beg : d.beg;
			std::uint32_t& len = up ? c->len : d.len;
			if (buf == nullptr)
			{
				buf = pool_.get();
				beg = 0;
				len = 0;
			}
			const std::uint32_t room = kRelayBuf - len;
			const ssize_t n = ::recv(src, buf->data.data() + len, room, 0);
			++c_.recv_calls;
			if (n > 0)
			{
				len += static_cast<std::uint32_t>(n);
				c_.bytes_received += static_cast<std::uint64_t>(n);
				if (up) c->bytes_received += static_cast<std::uint64_t>(n);
				// After a reported half-close, a short read has taken every byte before the FIN.
				if (src_rdhup && static_cast<std::uint32_t>(n) < room) d.eof = true;
				continue;
			}
			const int e = errno;
			if (len == beg)
			{
				pool_.put(buf);
				buf = nullptr;
				beg = 0;
				len = 0;
			}
			if (n == 0)
			{
				++c_.recv_eof;
				d.eof = true;
				continue;
			}
			if (e == EINTR) continue;
			if (e == EAGAIN || e == EWOULDBLOCK)
			{
				++c_.recv_again;
				return true;
			}
			relay_abort(c, e == ECONNRESET);
			return false;
		}
	}

	bool Worker::pump_splice(Conn* c, bool up)
	{
		Relay& r = *c->relay;
		Dir& d = up ? r.up : r.down;
		const int src = up ? c->fd : r.fd;
		const int dst = up ? r.fd : c->fd;
		for (;;)
		{
			if (has_held(c, up))
			{
				// The bytes replay read come first, sent from user space.
				if (!send_held(c, up)) return false;
				if (d.blocked) return true;
				continue;
			}
			if (d.in_pipe > 0)
			{
				const ssize_t n = ::splice(d.pipe_r, nullptr, dst, nullptr, d.in_pipe, kSpliceFlags);
				++c_.splice_calls;
				if (n > 0)
				{
					d.in_pipe -= static_cast<std::uint32_t>(n);
					c_.bytes_spliced += static_cast<std::uint64_t>(n);
					continue;
				}
				if (n < 0 && errno == EINTR) continue;
				if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
				{
					d.blocked = true;
					wait_writable(c, up);
					return true;
				}
				relay_abort(c, n < 0 && (errno == ECONNRESET || errno == EPIPE));
				return false;
			}
			d.blocked = false;
			if (d.eof) return relay_after_eof(c, up);
			const ssize_t n = ::splice(src, nullptr, d.pipe_w, nullptr, kSpliceChunk, kSpliceFlags);
			++c_.splice_calls;
			if (n > 0)
			{
				d.in_pipe += static_cast<std::uint32_t>(n);
				continue;
			}
			if (n == 0)
			{
				d.eof = true;
				continue;
			}
			if (errno == EINTR) continue;
			if (errno == EAGAIN || errno == EWOULDBLOCK) return true;
			relay_abort(c, errno == ECONNRESET);
			return false;
		}
	}

	// ---- io_uring ----

	void Worker::relay_next_uring(Conn* c, bool up)
	{
		if (c->fd < 0 || c->zombie) return;
		Relay& r = *c->relay;
		if (!r.connected) return;
		Dir& d = up ? r.up : r.down;
		if (d.shut) return;
		const int src = up ? c->fd : r.fd;
		const int dst = up ? r.fd : c->fd;
		if (has_held(c, up))
		{
			if (d.blocked)
			{
				wait_writable(c, up);
				return;
			}
			if (!send_held(c, up) || d.blocked) return;
		}
		if (r.splice)
		{
			const Op out = up ? Op::up_splice_out : Op::down_splice_out;
			const Op in = up ? Op::up_splice_in : Op::down_splice_in;
			if (d.in_pipe > 0)
			{
				if (d.blocked)
				{
					wait_writable(c, up);
					return;
				}
				if ((c->posted & bit(out)) == 0)
				{
					ur_->splice(d.pipe_r, dst, d.in_pipe, kSpliceFlags, ud(c, out));
					posted(c, out);
					++c_.splice_calls;
				}
				return;
			}
			if (d.eof)
			{
				relay_after_eof(c, up);
				return;
			}
			if ((c->posted & bit(in)) != 0) return;
			const Op poll = up ? Op::poll_in : Op::b_poll_in;
			if ((c->posted & bit(poll)) == 0)
			{
				ur_->poll(src, POLLIN | POLLRDHUP, ud(c, poll));
				posted(c, poll);
			}
			return;
		}
		if (d.eof)
		{
			relay_after_eof(c, up);
			return;
		}
		if (up)
		{
			post_recv(c);
			return;
		}
		if ((c->posted & bit(Op::b_recv)) != 0) return;
		if (d.buf != nullptr)
		{
			ur_->recv(r.fd, d.buf->data.data() + d.len, kRelayBuf - d.len, ud(c, Op::b_recv));
			r.down_own = true;
		}
		else
		{
			ur_->recv_select(r.fd, kBufferGroup, ud(c, Op::b_recv));
			r.down_own = false;
		}
		posted(c, Op::b_recv);
	}

	void Worker::relay_completion(Conn* c, Op op, const loop::Completion& x)
	{
		Relay& r = *c->relay;
		switch (op)
		{
			case Op::b_connect: relay_connected(c, x.res == 0 ? 0 : -x.res); return;
			case Op::recv:
			case Op::b_recv:
			{
				const bool up = op == Op::recv;
				const ReadResult rr = up ? take_recv(c, c->buf, c->len, x) : take_recv(c, r.down.buf, r.down.len, x);
				if (rr.retry) ++c_.recv_retries;
				else if (rr.error)
				{
					relay_abort(c, rr.reset);
					return;
				}
				else if (rr.eof) (up ? r.up : r.down).eof = true;
				relay_next_uring(c, up);
				return;
			}
			case Op::poll_out:
			case Op::b_poll_out:
			{
				const bool up = op == Op::b_poll_out;  // the backend is the upward copy's destination
				(up ? r.up : r.down).blocked = false;
				relay_next_uring(c, up);
				return;
			}
			case Op::poll_in:
			case Op::b_poll_in:
			{
				const bool up = op == Op::poll_in;
				if (!r.splice)
				{
					relay_next_uring(c, up);  // the peek path's last poll: the copy receives
					return;
				}
				Dir& d = up ? r.up : r.down;
				const Op in = up ? Op::up_splice_in : Op::down_splice_in;
				if (d.shut || (c->posted & bit(in)) != 0) return;
				ur_->splice(up ? c->fd : r.fd, d.pipe_w, kSpliceChunk, kSpliceFlags, ud(c, in));
				posted(c, in);
				++c_.splice_calls;
				return;
			}
			case Op::up_splice_in:
			case Op::down_splice_in:
			{
				const bool up = op == Op::up_splice_in;
				Dir& d = up ? r.up : r.down;
				if (x.res > 0) d.in_pipe += static_cast<std::uint32_t>(x.res);
				else if (x.res == 0) d.eof = true;
				else if (x.res != -EAGAIN && x.res != -EINTR)
				{
					relay_abort(c, x.res == -ECONNRESET);
					return;
				}
				relay_next_uring(c, up);
				return;
			}
			case Op::up_splice_out:
			case Op::down_splice_out:
			{
				const bool up = op == Op::up_splice_out;
				Dir& d = up ? r.up : r.down;
				if (x.res > 0)
				{
					d.in_pipe -= static_cast<std::uint32_t>(x.res);
					c_.bytes_spliced += static_cast<std::uint64_t>(x.res);
					d.blocked = false;
				}
				else if (x.res == -EAGAIN)
				{
					d.blocked = true;
				}
				else if (x.res != -EINTR)
				{
					relay_abort(c, x.res == -ECONNRESET || x.res == -EPIPE);
					return;
				}
				relay_next_uring(c, up);
				return;
			}
			case Op::cancel:
			case Op::accept: return;
		}
	}

}  // namespace oneport::server::detail

#endif  // __linux__
