// The worker's handlers (proposal I26), TLS termination (I22 to I24), its output and its
// connections' lifecycle (see worker.hpp). The protocol steps are in apps.cpp and h2.cpp.
//
// Every handler runs the same code in both modes: entry differs (accept, classification or T_fb),
// and so does where the first bytes are (in the buffer after replay, in the socket after peek),
// and nothing after it. TLS reads the received bytes through the worker's BIO from the
// connection's buffer, the one the handler would read into, and decrypts into a second buffer
// (`plain`), from which the HTTP/1.1 or h2 handler reads as from the socket's bytes.
//
// Output: a step appends to out_ (for TLS, OpenSSL encrypts it into wire_); one send per step.
// What the socket does not take is copied into the connection's `pend` and sent on EPOLLOUT;
// while it waits, the connection reads nothing more, and the read resumes after the flush.
#include "worker.hpp"

#if defined(__linux__)

#include <algorithm>
#include <cstring>

#include <openssl/err.h>
#include <sys/socket.h>
#include <unistd.h>

namespace oneport::server::detail
{

	using apps::Next;

	// ---- Handlers (I26) ----

	bool Worker::start_handler(Conn* c, Proto p)
	{
		c->stage = Stage::handler;
		c->proto = p;
		out_.clear();
		switch (p)
		{
			case Proto::http1: c->app = App::http1; return true;
			case Proto::h2c:
				c->app = App::h2;
				c->a.h2 = h2::open();
				if (c->a.h2 == nullptr)
				{
					c->app = App::none;
					close_conn(c);
					return false;
				}
				return true;  // its SETTINGS leaves with the first output
			case Proto::tls:
			{
				c->app = App::none;  // HTTP/1.1 or h2, by ALPN, once the handshake completes
				c->ssl = SSL_new(shared_.ssl_ctx);
				BIO* b = c->ssl != nullptr ? tls::new_bio(&bio_) : nullptr;
				if (b == nullptr)
				{
					ERR_clear_error();
					close_conn(c);
					return false;
				}
				SSL_set_bio(c->ssl, b, b);
				SSL_set_accept_state(c->ssl);
				return true;
			}
			case Proto::mqtt:
				c->app = App::mqtt;
				c->a.mqtt = apps::MqttState{};  // every field zero: a union's {} sets only its first member
				return true;
			case Proto::ssh:
				c->app = App::ssh;
				c->a.ssh = apps::SshState{};
				apps::append(out_, apps::kSshBanner);  // on entry: at accept, at classification or at T_fb (I28)
				return commit(c, out_, Next::more);
			case Proto::smtp:
				c->app = App::smtp;
				apps::append(out_, apps::kSmtpGreeting);
				return commit(c, out_, Next::more);
		}
		return true;
	}

	void Worker::enter_handler(Conn* c, Proto p, Entry entry)
	{
		if (!start_handler(c, p)) return;
		switch (entry)
		{
			case Entry::accept:
			case Entry::fallback:
				return;  // nothing received: wait for readiness
			case Entry::replay:
				// The bytes are in the buffer; read on only if the last read filled it.
				handler_readable(c, c->observe_pass == pass_, c->last_read_full);
				return;
			case Entry::peek:
				// The bytes are still queued, and edge-triggered readiness will not repeat.
				handler_readable(c, c->observe_pass == pass_, true);
				return;
		}
	}

	ReadResult Worker::read_into(Conn* c, bool rdhup)
	{
		ReadResult r;
		c->last_read_full = false;
		for (;;)
		{
			const std::uint32_t room = kRecvBuf - c->len;
			if (room == 0)
			{
				c->last_read_full = true;
				break;
			}
			const ssize_t n = ::recv(c->fd, c->buf->data.data() + c->len, room, 0);
			++c_.recv_calls;
			if (n > 0)
			{
				c->len += static_cast<std::uint32_t>(n);
				r.bytes += static_cast<std::uint32_t>(n);
				c_.bytes_received += static_cast<std::uint64_t>(n);
				c->bytes_received += static_cast<std::uint64_t>(n);
				if (static_cast<std::uint32_t>(n) < room && !rdhup) break;
				continue;
			}
			if (n == 0)
			{
				r.eof = true;
				c->eof_seen = true;
				c->observe_pass = pass_;
				break;
			}
			if (errno == EINTR) continue;
			if (errno != EAGAIN && errno != EWOULDBLOCK) r.error = true;
			break;
		}
		if (r.bytes > 0) c->last_read_pass = pass_;
		return r;
	}

	void Worker::take_buffer(Conn* c)
	{
		c->buf = pool_.get();
		c->beg = 0;
		c->len = 0;
	}

	void Worker::drop_empty_buffer(Conn* c) noexcept
	{
		if (c->buf == nullptr) return;
		pool_.put(c->buf);
		c->buf = nullptr;
		c->beg = 0;
		c->len = 0;
	}

	void Worker::audit_pending(int fd, std::uint32_t gen) noexcept
	{
		Conn* c = by_fd_[static_cast<std::size_t>(fd)];
		if (c == nullptr || c->gen != gen) return;  // closed
		if (c->stage != Stage::proxy && c->stage != Stage::detect) return;
		if (c->buf != nullptr && c->len == 0) c->buffer_while_silent = true;
	}

	void Worker::handler_readable(Conn* c, bool rdhup, bool must_read)
	{
		if (rdhup) c->rdhup_seen = true;
		for (;;)
		{
			if (!c->pend.empty())
			{
				if (must_read) c->read_deferred = true;  // resumed by flush()
				return;
			}
			if (must_read && !c->eof_seen)
			{
				if (c->buf == nullptr) take_buffer(c);
				const ReadResult rr = read_into(c, c->rdhup_seen);
				if (rr.error)
				{
					close_conn(c);
					return;
				}
			}
			Next next = Next::more;
			std::vector<std::byte>* wire = &out_;
			if (c->proto == Proto::tls)
			{
				next = tls_step(c);
				wire = &wire_;
			}
			else
			{
				out_.clear();
				next = app_step(c, View{c->buf, c->beg, c->len}, c->eof_seen, out_);
				if (next == Next::need_room)
				{
					c->last_read_full = true;  // the tail moved to the front: read on into the room
					next = Next::more;
				}
			}
			if (!commit(c, *wire, next)) return;
			if (c->buf != nullptr && c->beg == c->len) drop_empty_buffer(c);
			if (c->eof_seen || !c->last_read_full) return;
			must_read = true;  // the buffer was full: more may be queued
		}
	}

	Next Worker::app_step(Conn* c, View v, bool eof, std::vector<std::byte>& out)
	{
		const std::span<const std::byte> in = v.buf != nullptr ? std::span<const std::byte>(v.buf->data.data() + v.beg, v.len - v.beg)
		                                                       : std::span<const std::byte>();
		const apps::Room room{v.beg == 0, v.len == kRecvBuf};
		apps::Step s;
		switch (c->app)
		{
			case App::http1: s = apps::http1(in, room, eof, out); break;
			case App::smtp: s = apps::smtp(in, room, eof, out); break;
			case App::mqtt: s = apps::mqtt(c->a.mqtt, in, eof, out); break;
			case App::ssh: s = apps::ssh(c->a.ssh, in, eof); break;
			case App::h2:
			{
				const bool ok = in.empty() || h2::feed(c->a.h2, in);
				s.used = static_cast<std::uint32_t>(in.size());
				const bool sent = h2::drain(c->a.h2, out);
				if (!ok || !sent || eof || h2::finished(c->a.h2)) s.next = Next::close_after_output;
				break;
			}
			case App::none: s.next = Next::close_now; break;
		}
		v.beg += s.used;
		if (s.next == Next::need_room)
		{
			if (v.beg == 0) return Next::close_now;  // nothing to move: a step must decide a full buffer itself
			// Move the incomplete tail to the start, counted as a user-space copy (I29).
			const std::uint32_t n = v.len - v.beg;
			std::memmove(v.buf->data.data(), v.buf->data.data() + v.beg, n);
			c_.bytes_copied += n;
			v.beg = 0;
			v.len = n;
		}
		return s.next;
	}

	// ---- TLS (I22 to I24) ----

	Next Worker::tls_step(Conn* c)
	{
		wire_.clear();
		bio_.in = c->buf != nullptr ? c->buf->data.data() + c->beg : nullptr;
		bio_.in_len = c->buf != nullptr ? c->len - c->beg : 0;
		bio_.used = 0;
		bio_.out = &wire_;
		Next next = Next::more;
		if (!c->tls_open)
		{
			ERR_clear_error();
			const int r = SSL_do_handshake(c->ssl);
			if (r == 1)
			{
				c->tls_open = true;
				if (tls::chosen(c->ssl) == tls::Alpn::h2)
				{
					c->a.h2 = h2::open();
					c->app = c->a.h2 != nullptr ? App::h2 : App::none;
				}
				else
				{
					c->app = App::http1;
				}
			}
			else
			{
				const int e = SSL_get_error(c->ssl, r);
				ERR_clear_error();
				if (e != SSL_ERROR_WANT_READ && e != SSL_ERROR_WANT_WRITE) next = Next::close_after_output;  // with OpenSSL's alert, if any
				else if (c->eof_seen) next = Next::close_after_output;  // the peer left mid-handshake: send what OpenSSL wrote, then close
			}
		}
		if (c->tls_open && next == Next::more) next = tls_app(c);
		c->beg += static_cast<std::uint32_t>(bio_.used);
		return next;
	}

	Next Worker::tls_app(Conn* c)
	{
		for (;;)
		{
			// Decrypt what has arrived, as far as the plaintext buffer holds it.
			bool full = false;
			while (!c->tls_peer_done)
			{
				if (c->plain == nullptr)
				{
					c->plain = pool_.get();
					c->pbeg = 0;
					c->plen = 0;
				}
				if (c->plen == kRecvBuf)
				{
					full = true;
					break;
				}
				std::size_t n = 0;
				ERR_clear_error();
				if (SSL_read_ex(c->ssl, c->plain->data.data() + c->plen, kRecvBuf - c->plen, &n) == 1)
				{
					c->plen += static_cast<std::uint32_t>(n);
					continue;
				}
				const int e = SSL_get_error(c->ssl, 0);
				ERR_clear_error();
				if (e == SSL_ERROR_WANT_READ) break;
				if (e == SSL_ERROR_ZERO_RETURN)
				{
					c->tls_peer_done = true;  // close_notify
					break;
				}
				return Next::close_after_output;  // a fatal error; OpenSSL's alert, if any, is in wire_
			}
			const bool eof = c->tls_peer_done || (c->eof_seen && bio_.used == bio_.in_len && !full);
			out_.clear();
			Next next = app_step(c, View{c->plain, c->pbeg, c->plen}, eof, out_);
			if (!out_.empty())
			{
				std::size_t w = 0;
				ERR_clear_error();
				if (SSL_write_ex(c->ssl, out_.data(), out_.size(), &w) != 1 || w != out_.size())
				{
					ERR_clear_error();
					return Next::close_now;
				}
			}
			if (c->plain != nullptr && c->pbeg == c->plen)
			{
				pool_.put(c->plain);
				c->plain = nullptr;
				c->pbeg = 0;
				c->plen = 0;
			}
			if (next == Next::need_room) continue;  // the tail moved: decrypt more behind it
			if (next == Next::close_after_output)
			{
				ERR_clear_error();
				SSL_shutdown(c->ssl);  // close_notify, into wire_
				ERR_clear_error();
			}
			if (next != Next::more || !full) return next;
		}
	}

	// ---- Output ----

	bool Worker::commit(Conn* c, std::vector<std::byte>& wire, Next next)
	{
		if (!wire.empty())
		{
			const bool open = emit(c, wire);
			wire.clear();
			if (!open) return false;
		}
		switch (next)
		{
			case Next::close_now:
				close_conn(c);
				return false;
			case Next::close_after_output:
				if (c->pend.empty())
				{
					close_conn(c);
					return false;
				}
				c->close_after_out = true;
				return true;
			case Next::more:
			case Next::need_room: return true;
		}
		return true;
	}

	bool Worker::emit(Conn* c, std::span<const std::byte> bytes)
	{
		if (!c->pend.empty())
		{
			c->pend.insert(c->pend.end(), bytes.begin(), bytes.end());
			return true;
		}
		const ssize_t w = ::send(c->fd, bytes.data(), bytes.size(), MSG_NOSIGNAL | MSG_DONTWAIT);
		++c_.send_calls;
		if (w < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
		{
			close_conn(c);
			return false;
		}
		const auto done = static_cast<std::size_t>(std::max<ssize_t>(w, 0));
		c_.bytes_sent += done;
		c->bytes_sent += done;
		if (done == bytes.size()) return true;
		c->pend.assign(bytes.begin() + static_cast<std::ptrdiff_t>(done), bytes.end());
		c->pend_off = 0;
		if (!c->want_out)
		{
			loop_.modify(c->fd, kConnEvents | EPOLLOUT, tag_of(c));
			++c_.epoll_ctl_calls;
			c->want_out = true;
		}
		return true;
	}

	bool Worker::flush(Conn* c)
	{
		const std::size_t left = c->pend.size() - c->pend_off;
		const ssize_t w = ::send(c->fd, c->pend.data() + c->pend_off, left, MSG_NOSIGNAL | MSG_DONTWAIT);
		++c_.send_calls;
		if (w < 0)
		{
			if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return true;
			close_conn(c);
			return false;
		}
		c_.bytes_sent += static_cast<std::uint64_t>(w);
		c->bytes_sent += static_cast<std::uint64_t>(w);
		c->pend_off += static_cast<std::size_t>(w);
		if (c->pend_off < c->pend.size()) return true;
		c->pend.clear();
		c->pend_off = 0;
		loop_.modify(c->fd, kConnEvents, tag_of(c));
		++c_.epoll_ctl_calls;
		c->want_out = false;
		if (c->close_after_out)
		{
			close_conn(c);
			return false;
		}
		// Resume: a read that waited for this flush, or bytes left in the buffer by a full read.
		const bool again = c->read_deferred || c->last_read_full;
		c->read_deferred = false;
		handler_readable(c, false, again);
		return c->fd >= 0 && by_fd_[static_cast<std::size_t>(c->fd)] == c;
	}

	// ---- Connections ----

	std::uint64_t Worker::tag_of(const Conn* c) const noexcept
	{
		return (static_cast<std::uint64_t>(c->gen) << 32) | static_cast<std::uint32_t>(c->fd);
	}

	Conn* Worker::new_conn(int fd)
	{
		const auto slot = static_cast<std::size_t>(fd);
		if (slot >= by_fd_.size())
		{
			by_fd_.resize(slot + 1, nullptr);
			gen_by_fd_.resize(slot + 1, 0);
		}
		Conn* c = nullptr;
		if (free_conns_.empty())
		{
			conns_.push_back(std::make_unique<Conn>());
			c = conns_.back().get();
		}
		else
		{
			c = free_conns_.back();
			free_conns_.pop_back();
		}
		*c = Conn{};
		c->fd = fd;
		c->gen = ++gen_by_fd_[slot] & 0x3FFFFFFFu;  // 30 bits: a tag never sets kListenerTag's bit
		c->id = ++next_id_;
		by_fd_[slot] = c;
		++open_;
		return c;
	}

	void Worker::close_conn(Conn* c)
	{
		for (std::size_t k = 0; k < 3; ++k) disarm(c, static_cast<TimerKind>(k));
		drop_empty_buffer(c);
		if (c->plain != nullptr)
		{
			pool_.put(c->plain);
			c->plain = nullptr;
		}
		if (c->ssl != nullptr)
		{
			SSL_free(c->ssl);  // and its BIO
			c->ssl = nullptr;
			ERR_clear_error();
		}
		if (c->app == App::h2 && c->a.h2 != nullptr)
		{
			h2::close(c->a.h2);
			c->a.h2 = nullptr;
		}
		c->app = App::none;
		if (shared_.hooks.closed != nullptr)
		{
			CloseReport r;
			r.worker = index_;
			r.conn = c->id;
			r.peer_port = c->peer_port;
			r.handled = c->stage == Stage::handler;
			r.proto = c->proto;
			r.bytes_received = c->bytes_received;
			r.bytes_sent = c->bytes_sent;
			shared_.hooks.closed(shared_.hooks.ctx, r);
		}
		by_fd_[static_cast<std::size_t>(c->fd)] = nullptr;
		::close(c->fd);  // also removes it from the epoll set
		c->fd = -1;
		c->pend.clear();
		c->pend.shrink_to_fit();
		++c_.closed;
		--open_;
		free_conns_.push_back(c);
	}

	void Worker::close_all()
	{
		for (std::size_t slot = 0; slot < by_fd_.size(); ++slot)
		{
			Conn* c = by_fd_[slot];
			if (c == nullptr) continue;
			if (c->stage == Stage::proxy || c->stage == Stage::detect)
			{
				++c_.outcomes[static_cast<std::size_t>(Outcome::stopped)];
				report(c, Outcome::stopped, Proto::http1, 0);
			}
			close_conn(c);
		}
		c_.conns_open = open_;
		c_.buffers_allocated = pool_.allocated();
		c_.buffers_outstanding = pool_.outstanding();
		c_.passes = loop_.passes();
	}

}  // namespace oneport::server::detail

#endif  // __linux__
