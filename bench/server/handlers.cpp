// The worker's handlers (proposal I26: the HTTP/1.1 handler and the M1 stubs), its output and
// its connections' lifecycle (see worker.hpp).
#include "worker.hpp"

#if defined(__linux__)

#include "http1.hpp"

#include <algorithm>
#include <charconv>
#include <cstring>

#include <sys/socket.h>
#include <unistd.h>

namespace oneport::server::detail
{

	// ---- Handlers (I26) ----

	void Worker::init_handler(Conn* c)
	{
		if (c->stage == Stage::http1)
		{
			c->h.http = HttpState{false};
		}
		else
		{
			c->h.stub = StubState{};
			c->h.stub.hash = 14695981039346656037ull;  // FNV-1a 64 offset basis
		}
	}

	void Worker::enter_handler(Conn* c, Proto p, Entry entry)
	{
		c->proto = p;
		c->stage = p == Proto::http1 ? Stage::http1 : Stage::stub;
		init_handler(c);
		switch (entry)
		{
			case Entry::accept:
			case Entry::fallback:
				// Nothing received: an SSH or SMTP stub speaks first; the rest wait for bytes.
				if (c->stage == Stage::stub) handler_readable(c, false, false);
				return;
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
		for (;;)
		{
			if (must_read && !c->eof_seen)
			{
				if (c->buf == nullptr) take_buffer(c);
				const ReadResult rr = read_into(c, rdhup);
				if (rr.error)
				{
					close_conn(c);
					return;
				}
			}
			const bool eof = c->eof_seen;
			const bool open = c->stage == Stage::http1 ? http_consume(c, eof) : stub_consume(c, eof);
			if (!open) return;
			if (c->buf != nullptr && c->beg == c->len) drop_empty_buffer(c);
			if (eof || c->out_len > 0 || !c->last_read_full) return;
			must_read = true;  // the buffer was full: more may be queued
		}
	}

	bool Worker::http_consume(Conn* c, bool eof)
	{
		while (c->out_len == 0 && c->buf != nullptr && c->beg < c->len)
		{
			const std::span<const std::byte> data(c->buf->data.data() + c->beg, c->len - c->beg);
			const bool full = c->len == kRecvBuf;
			const http1::Parsed p = http1::parse(data, full && c->beg == 0);
			if (p.status == http1::Status::more && full && c->beg > 0)
			{
				// Make room: move the unparsed tail to the start, counted as a user-space copy.
				std::memmove(c->buf->data.data(), data.data(), data.size());
				c_.bytes_copied += data.size();
				c->len = static_cast<std::uint32_t>(data.size());
				c->beg = 0;
				c->last_read_full = true;  // read on into the space made
				return true;
			}
			switch (p.status)
			{
				case http1::Status::more:
					if (eof)
					{
						close_conn(c);
						return false;
					}
					return true;
				case http1::Status::bad_grammar:
					close_conn(c);  // closed without a response, as the detector closes it
					return false;
				case http1::Status::bad_request:
					c->beg = c->len;
					return send(c, as_bytes(http1::kResponse400), true);
				case http1::Status::request:
					c->beg += p.length;
					if (!send(c, as_bytes(http1::kResponse200), !p.keep_alive)) return false;
					if (!p.keep_alive) return true;
					break;
			}
		}
		if (eof && c->out_len == 0)
		{
			close_conn(c);
			return false;
		}
		if (eof) c->close_after_out = true;
		return true;
	}

	bool Worker::stub_consume(Conn* c, bool eof)
	{
		StubState& s = c->h.stub;
		if (c->bytes_sent == 0 && c->out_len == 0 && !s.trailer_pending)
		{
			if (!send(c, as_bytes(stub_marker(c->proto)), false)) return false;
		}
		if (c->buf != nullptr)
		{
			for (std::uint32_t i = c->beg; i < c->len; ++i)
			{
				s.hash ^= std::to_integer<std::uint64_t>(c->buf->data[i]);
				s.hash *= 1099511628211ull;  // FNV-1a 64 prime
			}
			s.count += c->len - c->beg;
			c->beg = c->len;
		}
		if (!eof) return true;
		const std::string_view name = detect::name(c->proto);
		char* p = s.trailer.data();
		char* const end = s.trailer.data() + s.trailer.size();
		auto put = [&p](std::string_view t) {
			std::memcpy(p, t.data(), t.size());
			p += t.size();
		};
		put("oneport M1 stub ");
		put(name);
		put(" received ");
		p = std::to_chars(p, end, s.count).ptr;
		put(" bytes fnv1a64 ");
		std::array<char, 16> hex{};
		const auto hres = std::to_chars(hex.data(), hex.data() + hex.size(), s.hash, 16);
		const auto hex_len = static_cast<std::size_t>(hres.ptr - hex.data());
		for (std::size_t k = hex_len; k < 16; ++k) put("0");
		put(std::string_view(hex.data(), hex_len));
		put("\r\n");
		s.trailer_len = static_cast<std::uint8_t>(p - s.trailer.data());
		if (c->out_len > 0)
		{
			s.trailer_pending = true;  // sent when the marker is out
			c->close_after_out = false;
			return true;
		}
		return send(c, std::as_bytes(std::span<const char>(s.trailer.data(), s.trailer_len)), true);
	}

	// ---- Output ----

	bool Worker::send(Conn* c, std::span<const std::byte> bytes, bool close_after)
	{
		const ssize_t w = ::send(c->fd, bytes.data(), bytes.size(), MSG_NOSIGNAL | MSG_DONTWAIT);
		++c_.send_calls;
		if (w < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
		{
			close_conn(c);
			return false;
		}
		const auto done = static_cast<std::uint32_t>(std::max<ssize_t>(w, 0));
		c_.bytes_sent += done;
		c->bytes_sent += done;
		if (done == bytes.size())
		{
			if (close_after)
			{
				close_conn(c);
				return false;
			}
			return true;
		}
		c->out = bytes.data() + done;
		c->out_len = static_cast<std::uint32_t>(bytes.size()) - done;
		c->close_after_out = close_after;
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
		const ssize_t w = ::send(c->fd, c->out, c->out_len, MSG_NOSIGNAL | MSG_DONTWAIT);
		++c_.send_calls;
		if (w < 0)
		{
			if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return true;
			close_conn(c);
			return false;
		}
		c_.bytes_sent += static_cast<std::uint64_t>(w);
		c->bytes_sent += static_cast<std::uint64_t>(w);
		c->out += w;
		c->out_len -= static_cast<std::uint32_t>(w);
		if (c->out_len > 0) return true;
		c->out = nullptr;
		loop_.modify(c->fd, kConnEvents, tag_of(c));
		++c_.epoll_ctl_calls;
		c->want_out = false;
		if (c->close_after_out)
		{
			close_conn(c);
			return false;
		}
		if (c->stage == Stage::stub && c->h.stub.trailer_pending)
		{
			c->h.stub.trailer_pending = false;
			return send(c, std::as_bytes(std::span<const char>(c->h.stub.trailer.data(), c->h.stub.trailer_len)), true);
		}
		// Requests parsed while the output was blocked wait in the buffer.
		if (c->stage == Stage::http1) return http_consume(c, false);
		return true;
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
		if (shared_.hooks.closed != nullptr)
		{
			CloseReport r;
			r.worker = index_;
			r.conn = c->id;
			r.peer_port = c->peer_port;
			r.handled = c->stage == Stage::http1 || c->stage == Stage::stub;
			r.proto = c->proto;
			r.bytes_received = c->bytes_received;
			r.bytes_sent = c->bytes_sent;
			shared_.hooks.closed(shared_.hooks.ctx, r);
		}
		by_fd_[static_cast<std::size_t>(c->fd)] = nullptr;
		::close(c->fd);  // also removes it from the epoll set
		c->fd = -1;
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
