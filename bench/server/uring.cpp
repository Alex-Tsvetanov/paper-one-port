// The worker on io_uring (see worker.hpp; proposal I4, I5, I11, I15; hypotheses.md, section 1(b)).
//
// Accept is one multishot IORING_OP_ACCEPT per listener and worker (I4), armed again when a
// completion comes without IORING_CQE_F_MORE. A connection's input comes as completions:
//   replay    an IORING_OP_RECV into a buffer the kernel selects from the worker's provided-buffer
//             ring when data arrives, so a pending receive holds no buffer (I15); once the
//             connection holds a buffer, into the room after its bytes;
//   peek      an IORING_OP_POLL_ADD for POLLIN | POLLRDHUP, then the synchronous MSG_PEEK of
//             worker.cpp; an undecided peek sets SO_RCVLOWAT and polls again, which the kernel
//             completes only at the mark (pinned by server.kernel_rcvlowat_uring, RK4);
//   handler   receives as in replay, in both detection modes, as in dedicated mode.
// The check of 1(b): in replay a non-waiting reap of the ring (reap_for); in peek the one-byte
// MSG_PEEK. Output is the synchronous send of handlers.cpp, and its queue waits for a POLLOUT
// poll. The kernel's writes are invisible to MemorySanitizer: every receive unpoisons exactly
// the `res` bytes its completion reports, at the buffer it names (hypotheses.md, section 11).
//
// A closed connection cancels what it has in flight and keeps its buffers until the last
// completion arrives (finalize); only then is its slot reused. At stop every operation is
// cancelled and drained before the ring's buffers go back to the pool.
#include "worker.hpp"

#if defined(__linux__)

#include <linux/io_uring.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace oneport::server::detail
{

	namespace
	{

		/// The longest a stopping worker waits for its cancelled operations to end. A design choice
		/// of M2b: far above a cancellation's cost; a worker that reaches it reports an error.
		constexpr std::chrono::seconds kDrainLimit{5};

		std::uint64_t accept_ud(std::size_t listener) noexcept
		{
			return (static_cast<std::uint64_t>(Op::accept) << 56) | static_cast<std::uint64_t>(listener);
		}

		/// Marks bytes the kernel wrote into user memory as initialized for MemorySanitizer, exactly
		/// the `n` a completion reports (hypotheses.md, section 11: the io_uring blind spot's
		/// mitigation); nothing in other builds.
		void kernel_wrote([[maybe_unused]] const void* p, [[maybe_unused]] std::size_t n) noexcept
		{
#if defined(ONEPORT_MSAN_POISON)
			__msan_unpoison(p, n);
#endif
		}

		/// The opcode counters, copied out of the ring.
		void copy_submissions(Counters& c, const loop::UringLoop& ring)
		{
			const auto& s = ring.submissions();
			for (std::size_t i = 0; i < c.uring_submissions.size() && i < s.size(); ++i) c.uring_submissions[i] = s[i];
		}

	}  // namespace

	std::uint64_t Worker::ud(const Conn* c, Op op) const noexcept
	{
		return (static_cast<std::uint64_t>(op) << 56) | (static_cast<std::uint64_t>(c->gen & 0xFFFFFFu) << 32) | c->slot;
	}

	void Worker::run_uring()
	{
		try
		{
			ur_->start();
			provide_ring();
			for (ListenerState& l : listeners_)
			{
				ur_->accept_multishot(l.fd, accept_ud(l.index));
				l.accept_armed = true;
			}
			prev_return_ = Clock::now();
			while (!ur_->stopped())
			{
				pass_uring();
			}
		}
		catch (const std::exception& e)
		{
			error_ = std::string("worker ") + std::to_string(index_) + ": " + e.what();
		}
		try
		{
			close_all();
			for (ListenerState& l : listeners_)
			{
				if (l.accept_armed) ur_->cancel(accept_ud(l.index), static_cast<std::uint64_t>(Op::cancel) << 56);
			}
			auto armed = [this] {
				for (const ListenerState& l : listeners_)
				{
					if (l.accept_armed) return true;
				}
				return false;
			};
			const TimePoint until = Clock::now() + kDrainLimit;
			while ((zombies_ > 0 || armed()) && Clock::now() < until)
			{
				for (const loop::Completion& x : ur_->drain(std::chrono::milliseconds(10))) on_completion(x);
			}
			if (zombies_ > 0 || armed())
			{
				if (!error_) error_ = "worker " + std::to_string(index_) + ": " + std::to_string(zombies_) + " connections still had operations in flight at stop";
			}
			else
			{
				// Nothing is in flight: the ring's buffers go back to the pool.
				for (std::size_t id = 0; id < in_ring_.size(); ++id)
				{
					if (in_ring_[id] == 0) continue;
					in_ring_[id] = 0;
					pool_.put(pool_.by_id(static_cast<std::uint16_t>(id)));
				}
				ring_buffers_ = 0;
			}
		}
		catch (const std::exception& e)
		{
			if (!error_) error_ = std::string("worker ") + std::to_string(index_) + " at stop: " + e.what();
		}
		c_.conns_open = open_;
		c_.buffers_allocated = pool_.allocated();
		c_.buffers_outstanding = pool_.outstanding() - ring_buffers_;
		c_.ring_buffers = kRingBuffers;
		c_.passes = ur_->passes();
		c_.io_uring_enter_calls = ur_->enter_calls();
		copy_submissions(c_, *ur_);
	}

	void Worker::pass_uring()
	{
		const std::span<const loop::Completion> done = ur_->wait(bound_now());
		const TimePoint wait_return = Clock::now();  // the clock, re-read after every wait (I13)
		pass_ = ur_->passes();
		// Every completion is taken, even after stop(): each may hold a buffer or end a closed
		// connection's last operation.
		for (const loop::Completion& x : done) on_completion(x);
		if (ur_->stopped()) return;
		if (shared_.hooks.before_expiries != nullptr) shared_.hooks.before_expiries(shared_.hooks.ctx, index_, wait_return, earliest());
		expire(wait_return);
		prev_return_ = wait_return;
	}

	// ---- Provided buffers ----

	void Worker::provide_ring()
	{
		ur_->add_buffer_ring(kBufferGroup, kRingBuffers);
		for (unsigned i = 0; i < kRingBuffers; ++i) provide_one();
	}

	void Worker::provide_one()
	{
		Buffer* b = pool_.get();
		if (in_ring_.size() <= b->id) in_ring_.resize(static_cast<std::size_t>(b->id) + 1, 0);
		in_ring_[b->id] = 1;
		++ring_buffers_;
		ur_->provide(kBufferGroup, b->data.data(), kRecvBuf, b->id);
	}

	Buffer* Worker::take_selected(const loop::Completion& x)
	{
		const auto id = static_cast<std::uint16_t>(x.flags >> IORING_CQE_BUFFER_SHIFT);
		Buffer* b = pool_.by_id(id);
		if (b == nullptr || id >= in_ring_.size() || in_ring_[id] == 0) throw std::logic_error("io_uring: a completion names a buffer the ring does not hold");
		in_ring_[id] = 0;
		--ring_buffers_;
		provide_one();  // the ring keeps its count
		return b;
	}

	// ---- Completions ----

	void Worker::on_completion(const loop::Completion& x)
	{
		const auto op = static_cast<Op>(x.user_data >> 56);
		if (op == Op::cancel) return;
		if (op == Op::accept)
		{
			on_accept_completion(x);
			return;
		}
		const auto slot = static_cast<std::uint32_t>(x.user_data & 0xFFFFFFFFu);
		const auto gen = static_cast<std::uint32_t>((x.user_data >> 32) & 0xFFFFFFu);
		if (slot >= conns_.size()) throw std::logic_error("io_uring: a completion for no connection");
		Conn* c = conns_[slot].get();
		if (c->gen != gen || (c->posted & bit(op)) == 0) throw std::logic_error("io_uring: a completion for an operation not in flight");
		c->posted = static_cast<std::uint16_t>(c->posted & ~bit(op));
		if (c->zombie)
		{
			// Closed: what the operation brought is dropped, and a provided buffer goes back.
			if ((x.flags & IORING_CQE_F_BUFFER) != 0) pool_.put(take_selected(x));
			if (c->posted == 0) finalize(c);
			return;
		}
		switch (op)
		{
			case Op::recv:
			{
				++c->recv_events;
				if (c->stage == Stage::relay)
				{
					relay_completion(c, op, x);
					return;
				}
				if (c->stage == Stage::route)
				{
					if (c->recv_into == Into::hello)
					{
						Relay& r = *c->relay;
						ReadResult rr;
						++c_.recv_calls;
						if (x.res > 0)
						{
							kernel_wrote(r.hello.data() + r.hello_len, static_cast<std::size_t>(x.res));
							r.hello_len += static_cast<std::uint32_t>(x.res);
							rr.bytes = static_cast<std::uint32_t>(x.res);
							c_.bytes_received += rr.bytes;
							c->bytes_received += rr.bytes;
							c->last_read_pass = pass_;
						}
						else if (x.res == 0)
						{
							rr.eof = true;
							c->eof_seen = true;
						}
						else if (x.res == -EINTR || x.res == -EAGAIN)
						{
							rr.retry = true;
						}
						else
						{
							rr.error = true;
							rr.reset = x.res == -ECONNRESET;
						}
						if (!rr.retry) route_after_read(c, rr);
					}
					else
					{
						const ReadResult rr = take_recv(c, c->buf, c->len, x);
						if (rr.retry) ++c_.recv_retries;
						else route_after_read(c, rr);
					}
					if (c->fd >= 0 && !c->zombie && c->stage == Stage::route) pending_io(c);
					return;
				}
				const ReadResult rr = take_recv(c, c->buf, c->len, x);
				if (rr.retry)
				{
					++c_.recv_retries;
					if (c->stage == Stage::handler) want_read(c);
					else pending_io(c);
					return;
				}
				switch (c->stage)
				{
					case Stage::proxy:
					case Stage::detect:
						++c->wakeups;
						++c_.detection_wakeups;
						if (c->stage == Stage::proxy) proxy_after_read(c, rr, rr.eof);
						else detect_after_read(c, rr);
						if (c->fd >= 0 && !c->zombie && (c->stage == Stage::proxy || c->stage == Stage::detect || c->stage == Stage::route))
						{
							audit_pending(c);
							pending_io(c);
						}
						return;
					case Stage::handler:
						if (rr.error)
						{
							close_conn(c);
							return;
						}
						if (handler_run(c)) want_read(c);
						return;
					case Stage::route:
					case Stage::relay: return;  // handled above
				}
				return;
			}
			case Op::poll_in:
			{
				const bool rdhup = x.res > 0 && (x.res & POLLRDHUP) != 0;
				const bool err = x.res < 0 || (x.res & (POLLERR | POLLHUP)) != 0;
				switch (c->stage)
				{
					case Stage::proxy:
					case Stage::detect:
						++c->wakeups;
						++c_.detection_wakeups;
						if (rdhup) c->observe_pass = pass_;
						if (err)
						{
							end_detection(c, Outcome::reset, 0);
							return;
						}
						if (c->stage == Stage::proxy) on_proxy_readable(c, rdhup);
						else on_detect_readable(c, rdhup);
						if (c->fd >= 0 && !c->zombie && (c->stage == Stage::proxy || c->stage == Stage::detect || c->stage == Stage::route))
						{
							audit_pending(c);
							pending_io(c);
						}
						return;
					case Stage::route:
						if (err)
						{
							relay_abort(c, true);
							return;
						}
						route_readable(c, rdhup);
						if (c->fd >= 0 && !c->zombie && c->stage == Stage::route) pending_io(c);
						return;
					case Stage::relay: relay_completion(c, op, x); return;
					case Stage::handler: want_read(c); return;  // the peek path's last poll: the handler receives
				}
				return;
			}
			case Op::poll_out:
				if (c->stage == Stage::relay)
				{
					relay_completion(c, op, x);
					return;
				}
				if (!c->pend.empty()) flush(c);
				return;
			case Op::cancel:
			case Op::accept: return;
			default: relay_completion(c, op, x); return;
		}
	}

	void Worker::on_accept_completion(const loop::Completion& x)
	{
		ListenerState& l = listeners_[static_cast<std::size_t>(x.user_data & 0xFFFFu)];
		if ((x.flags & IORING_CQE_F_MORE) == 0) l.accept_armed = false;
		if (x.res >= 0)
		{
			++c_.accept_calls;
			if (ur_->stopped())
			{
				::close(x.res);  // stopping: never a connection
			}
			else
			{
				// A multishot accept gives no peer address per connection; the tests' hooks key
				// their reports by it, so it is read only when a hook is set.
				std::uint16_t peer_port = 0;
				if (shared_.hooks.detection != nullptr || shared_.hooks.closed != nullptr || shared_.hooks.relayed != nullptr)
				{
					sockaddr_in peer{};
					socklen_t n = sizeof(peer);
					if (::getpeername(x.res, reinterpret_cast<sockaddr*>(&peer), &n) == 0 && peer.sin_family == AF_INET) peer_port = ntohs(peer.sin_port);
				}
				accepted(l, x.res, peer_port);
			}
		}
		else if (x.res != -ECANCELED)
		{
			++c_.accept_calls;
			++c_.accept_errors;
		}
		if (!l.accept_armed && !ur_->stopped())
		{
			ur_->accept_multishot(l.fd, accept_ud(l.index));
			l.accept_armed = true;
		}
	}

	ReadResult Worker::take_recv(Conn* c, Buffer*& buf, std::uint32_t& len, const loop::Completion& x)
	{
		ReadResult rr;
		++c_.recv_calls;
		Buffer* selected = (x.flags & IORING_CQE_F_BUFFER) != 0 ? take_selected(x) : nullptr;
		if (x.res > 0)
		{
			const auto n = static_cast<std::uint32_t>(x.res);
			if (selected != nullptr)
			{
				if (buf != nullptr) throw std::logic_error("io_uring: a provided buffer for a connection that holds one");
				buf = selected;
				len = 0;
				if (&buf == &c->buf) c->beg = 0;
				else if (c->relay && &buf == &c->relay->down.buf) c->relay->down.beg = 0;
			}
			// MemorySanitizer cannot see the kernel's copy: exactly the bytes the completion reports.
			kernel_wrote(buf->data.data() + len, n);
			len += n;
			rr.bytes = n;
			c_.bytes_received += n;
			c->bytes_received += n;
			c->last_read_pass = pass_;
			c->last_read_full = len == kRecvBuf;
			return rr;
		}
		if (selected != nullptr) pool_.put(selected);  // not seen on L's kernel (server.kernel_uring_recv_select)
		if (x.res == 0)
		{
			rr.eof = true;
			if (&buf == &c->buf)
			{
				c->eof_seen = true;
				c->observe_pass = pass_;
			}
			return rr;
		}
		if (x.res == -ENOBUFS || x.res == -EINTR || x.res == -EAGAIN)
		{
			rr.retry = true;
			return rr;
		}
		rr.error = true;
		rr.reset = x.res == -ECONNRESET;
		return rr;
	}

	// ---- Posting ----

	void Worker::post_recv(Conn* c)
	{
		if ((c->posted & bit(Op::recv)) != 0) return;
		if (c->buf != nullptr)
		{
			const std::uint32_t room = kRecvBuf - c->len;
			if (room == 0) return;  // the caller decides what a full buffer means
			ur_->recv(c->fd, c->buf->data.data() + c->len, room, ud(c, Op::recv));
			c->recv_into = Into::own;
		}
		else
		{
			ur_->recv_select(c->fd, kBufferGroup, ud(c, Op::recv));
			c->recv_into = Into::provided;
		}
		posted(c, Op::recv);
	}

	void Worker::post_poll_in(Conn* c)
	{
		if ((c->posted & bit(Op::poll_in)) != 0) return;
		ur_->poll(c->fd, POLLIN | POLLRDHUP, ud(c, Op::poll_in));
		posted(c, Op::poll_in);
	}

	void Worker::pending_io(Conn* c)
	{
		if (c->fd < 0 || c->zombie) return;
		if (peeks(c))
		{
			post_poll_in(c);
			return;
		}
		if (c->stage == Stage::route && c->relay && !c->relay->hello.empty())
		{
			// Pass-through: the ClientHello's records outgrew the receive buffer and are read into
			// its own storage.
			if ((c->posted & bit(Op::recv)) != 0) return;
			Relay& r = *c->relay;
			const std::size_t want = std::min<std::size_t>(kHelloWireMax, std::max<std::size_t>(r.hello.size(), r.hello_len + kRecvBuf));
			r.hello.resize(want);
			if (r.hello_len >= r.hello.size()) return;  // at kHelloWireMax: try_route has decided by then
			ur_->recv(c->fd, r.hello.data() + r.hello_len, static_cast<std::uint32_t>(r.hello.size() - r.hello_len), ud(c, Op::recv));
			c->recv_into = Into::hello;
			posted(c, Op::recv);
			return;
		}
		post_recv(c);
	}

	void Worker::want_read(Conn* c)
	{
		if (c->fd < 0 || c->zombie || c->stage != Stage::handler) return;
		if (!c->pend.empty())
		{
			c->read_deferred = true;  // resumed by flush()
			return;
		}
		if (c->eof_seen || (c->posted & bit(Op::recv)) != 0) return;
		if (c->buf != nullptr && c->len == kRecvBuf)
		{
			close_conn(c);  // a full buffer its handler cannot consume
			return;
		}
		post_recv(c);
	}

	std::optional<int> Worker::reap_for(Conn* c)
	{
		std::optional<int> got;
		const std::uint64_t target = ud(c, Op::recv);
		for (const loop::Completion& x : ur_->reap_now())
		{
			if (!got && x.user_data == target) got = x.res;
			on_completion(x);
		}
		return got;
	}

	void Worker::cancel_all(Conn* c)
	{
		for (unsigned k = 0; k < static_cast<unsigned>(Op::cancel); ++k)
		{
			const auto op = static_cast<Op>(k);
			if ((c->posted & bit(op)) != 0) ur_->cancel(ud(c, op), static_cast<std::uint64_t>(Op::cancel) << 56);
		}
		c->zombie = true;
		++zombies_;
	}

}  // namespace oneport::server::detail

#endif  // __linux__
