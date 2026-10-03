// The worker on IOCP (see worker.hpp; proposal I4, I5, I11, I13, I15, I29; hypotheses.md, sections
// 1(b) and 2.1). M6a.
//
// Accept: every listener keeps N_ACCEPTEX AcceptEx requests outstanding (kAcceptEx), each with a
// socket made for it; a completed request is posted again at once. AcceptEx has no receive buffer
// (dwReceiveDataLength = 0) unless --iocp-accept buffer names the form with one, which applies to
// one-port listeners without a fallback only (I5; the parser refuses it with a fallback). An
// accepted socket gets SO_UPDATE_ACCEPT_CONTEXT, non-blocking mode, the worker's port and
// FILE_SKIP_COMPLETION_PORT_ON_SUCCESS (I5), so an operation that completes at once queues no
// packet: it is handled from a queue in the same pass (settle).
//
// A connection's input:
//   zero-byte form (rule E's default)  a zero-byte WSARecv, completed when bytes (or the peer's
//                                      end) arrive, then a synchronous recv into the handler's
//                                      buffer, as epoll reads on readiness;
//   posted form                        a WSARecv with the handler's buffer, posted at once, so a
//                                      pending connection holds that buffer (I15);
//   peek                               the zero-byte WSARecv, then a synchronous recv(MSG_PEEK)
//                                      into the worker's scratch buffer (I11). Windows has no
//                                      SO_RCVLOWAT, so an undecided peek switches the connection
//                                      to replay: the queued bytes are read into the handler's
//                                      buffer at once and matching continues there (counted,
//                                      peek_to_replay). A half-close is then a read of 0 bytes.
// The check of 1(b): with a receive posted with a buffer (the posted form in replay), a
// non-waiting reap of the port; otherwise a one-byte MSG_PEEK (worker.cpp, expire_fb).
// Output is the synchronous send of handlers.cpp; what the socket does not take waits in the
// connection's queue for an overlapped WSASend of it (want_out), and output emitted meanwhile
// waits behind it (pend_more).
//
// A closed connection's socket is closed at once, which cancels its operations; their
// completions still arrive, so the connection keeps its OVERLAPPEDs, buffers and queue until the
// last one (finalize), as on io_uring. At stop every connection is closed, every AcceptEx
// cancelled, and their completions drained.
#include "worker.hpp"

#if defined(_WIN32)

#include <algorithm>
#include <climits>
#include <cstring>
#include <utility>

namespace oneport::server::detail
{

	namespace
	{

		/// The longest a stopping worker waits for its cancelled operations to end. A design choice
		/// of M6a, as on io_uring: far above a cancellation's cost; a worker that reaches it reports
		/// an error.
		constexpr std::chrono::seconds kDrainLimit{5};

		/// The zero-byte WSARecv's buffer: zero bytes at a valid address, as libuv's zero read.
		char zero_byte_buffer = 0;

		/// The Winsock error of an operation that completed with a status other than success.
		int op_error(SOCKET s, OVERLAPPED* ov)
		{
			DWORD bytes = 0;
			DWORD flags = 0;
			if (WSAGetOverlappedResult(s, ov, &bytes, FALSE, &flags)) return 0;
			const int e = WSAGetLastError();
			return e == 0 ? WSAECONNABORTED : e;
		}

		template <class Fn>
		Fn extension(SOCKET s, GUID guid, const char* what)
		{
			Fn fn = nullptr;
			DWORD got = 0;
			if (WSAIoctl(s, SIO_GET_EXTENSION_FUNCTION_POINTER, &guid, sizeof(guid), &fn, sizeof(fn), &got, nullptr, nullptr) != 0) throw_wsa(what);
			return fn;
		}

	}  // namespace

	// ---- The worker's run and pass ----

	void Worker::run_iocp()
	{
		try
		{
			ic_->start();
			for (ListenerState& l : listeners_)
			{
				const SOCKET ls = sock(l.fd);
				ic_->associate(static_cast<std::uintptr_t>(ls), kListenerKeyBase + l.index);
				if (accept_ex_ == nullptr)
				{
					accept_ex_ = extension<LPFN_ACCEPTEX>(ls, WSAID_ACCEPTEX, "WSAIoctl (AcceptEx)");
					accept_addrs_ = extension<LPFN_GETACCEPTEXSOCKADDRS>(ls, WSAID_GETACCEPTEXSOCKADDRS, "WSAIoctl (GetAcceptExSockaddrs)");
				}
				l.accept_buffer = shared_.iocp_accept == IocpAccept::buffer && l.spec->detects && !l.spec->fallback;
				l.accepts.reserve(kAcceptEx);
				for (std::size_t i = 0; i < kAcceptEx; ++i)
				{
					l.accepts.push_back(std::make_unique<AcceptReq>());
					l.accepts.back()->listener = l.index;
					post_accept(l, *l.accepts.back());
				}
			}
			prev_return_ = Clock::now();
			while (!ic_->stopped())
			{
				pass_iocp();
			}
		}
		catch (const std::exception& e)
		{
			error_ = std::string("worker ") + std::to_string(index_) + ": " + e.what();
		}
		try
		{
			stop_iocp();
		}
		catch (const std::exception& e)
		{
			if (!error_) error_ = std::string("worker ") + std::to_string(index_) + " at stop: " + e.what();
		}
		c_.conns_open = open_;
		c_.buffers_allocated = pool_.allocated();
		c_.buffers_outstanding = pool_.outstanding();
		c_.passes = ic_->passes();
		c_.gqcs_calls = ic_->gqcs_calls();
	}

	void Worker::pass_iocp()
	{
		const std::span<const loop::IocpEntry> done = ic_->wait(bound_now());
		const TimePoint wait_return = Clock::now();  // the clock, re-read after every wait (I13)
		pass_ = ic_->passes();
		// Every completion is taken, even after stop(): each may end a closed connection's last
		// operation or return an AcceptEx's socket.
		take_entries(done);
		if (ic_->stopped()) return;
		if (shared_.hooks.before_expiries != nullptr) shared_.hooks.before_expiries(shared_.hooks.ctx, index_, wait_return, earliest());
		expire(wait_return);
		settle();
		prev_return_ = wait_return;
	}

	void Worker::take_entries(std::span<const loop::IocpEntry> xs)
	{
		for (const loop::IocpEntry& x : xs)
		{
			on_entry(x);
			settle();
		}
	}

	void Worker::settle()
	{
		// Handling one may queue more; each is taken in order until none is left.
		while (inline_at_ < inline_.size())
		{
			const Inline x = inline_[inline_at_++];
			Conn* c = conns_[x.slot].get();
			if (c->gen != x.gen || (c->posted & bit(x.op)) == 0) throw std::logic_error("iocp: an immediate completion for an operation not in flight");
			c->posted = static_cast<std::uint16_t>(c->posted & ~bit(x.op));
			if (c->zombie)
			{
				if (c->posted == 0) finalize(c);
				continue;
			}
			on_op(c, x.op, x.bytes, x.error);
		}
		inline_.clear();
		inline_at_ = 0;
	}

	void Worker::queue_inline(Conn* c, Op op, std::uint32_t bytes, int error)
	{
		posted(c, op);  // in flight until settle() takes it, as a posted operation is until its packet
		inline_.push_back(Inline{c->slot, c->gen, op, bytes, error});
	}

	// ---- Completions ----

	void Worker::on_entry(const loop::IocpEntry& x)
	{
		if (x.overlapped == nullptr) throw std::logic_error("iocp: a completion without an operation");
		if (x.key >= kListenerKeyBase)
		{
			on_accept_entry(*reinterpret_cast<AcceptReq*>(x.overlapped), x);
			return;
		}
		if (x.key != kConnKey) throw std::logic_error("iocp: a completion with an unknown key");
		auto* io = reinterpret_cast<IoOp*>(x.overlapped);
		if (io->slot >= conns_.size()) throw std::logic_error("iocp: a completion for no connection");
		Conn* c = conns_[io->slot].get();
		if ((c->posted & bit(io->op)) == 0) throw std::logic_error("iocp: a completion for an operation not in flight");
		c->posted = static_cast<std::uint16_t>(c->posted & ~bit(io->op));
		if (c->zombie)
		{
			if (c->posted == 0) finalize(c);
			return;
		}
		const int error = x.status == 0 ? 0 : op_error(sock(c->fd), &io->ov);
		on_op(c, io->op, x.bytes, error);
	}

	void Worker::on_op(Conn* c, Op op, std::uint32_t bytes, int error)
	{
		switch (op)
		{
			case Op::poll_in:  // the zero-byte WSARecv: bytes, or the peer's end, are there
				switch (c->stage)
				{
					case Stage::proxy:
					case Stage::detect:
						++c->wakeups;
						++c_.detection_wakeups;
						if (error != 0)
						{
							end_detection(c, Outcome::reset, 0);
							return;
						}
						if (c->stage == Stage::proxy) on_proxy_readable(c, false);
						else on_detect_readable(c, false);
						if (c->fd >= 0 && !c->zombie && (c->stage == Stage::proxy || c->stage == Stage::detect))
						{
							audit_pending(c);
							pending_io(c);
						}
						return;
					case Stage::handler:
						if (error != 0)
						{
							close_conn(c);
							return;
						}
						if (posted_form())
						{
							want_read(c);  // the handler's receive is the WSARecv with its buffer
							return;
						}
						handler_readable(c, false, true);
						if (c->fd >= 0 && !c->zombie) want_read(c);
						return;
					case Stage::route:
					case Stage::relay: throw std::logic_error("iocp: relay dispatch is Linux only");
				}
				return;
			case Op::recv:  // the WSARecv with the handler's buffer (the posted form)
			{
				ReadResult rr;
				if (error != 0)
				{
					rr.error = true;
					rr.reset = error == WSAECONNRESET;
				}
				else if (bytes == 0)
				{
					rr.eof = true;
					c->eof_seen = true;
					c->observe_pass = pass_;
				}
				else
				{
					c->len += bytes;
					rr.bytes = bytes;
					c_.bytes_received += bytes;
					c->bytes_received += bytes;
					c->last_read_pass = pass_;
					c->last_read_full = c->len == kRecvBuf;
				}
				switch (c->stage)
				{
					case Stage::proxy:
					case Stage::detect:
						++c->wakeups;
						++c_.detection_wakeups;
						if (c->stage == Stage::proxy) proxy_after_read(c, rr, rr.eof);
						else detect_after_read(c, rr);
						if (c->fd >= 0 && !c->zombie && (c->stage == Stage::proxy || c->stage == Stage::detect))
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
					case Stage::relay: throw std::logic_error("iocp: relay dispatch is Linux only");
				}
				return;
			}
			case Op::poll_out:  // the output queue's WSASend
				if (error != 0)
				{
					close_conn(c);
					return;
				}
				c_.bytes_sent += bytes;
				c->bytes_sent += bytes;
				c->pend_off += bytes;
				flush(c);
				return;
			default: throw std::logic_error("iocp: a completion of an operation IOCP does not post");
		}
	}

	// ---- Accept ----

	void Worker::post_accept(ListenerState& l, AcceptReq& r)
	{
		for (int attempt = 0;; ++attempt)
		{
			r.s = ::WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, nullptr, 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
			if (r.s == INVALID_SOCKET) throw_wsa("WSASocket (AcceptEx)");
			std::memset(&r.ov, 0, sizeof(r.ov));
			void* out = r.addrs.data();
			DWORD data = 0;
			if (l.accept_buffer)
			{
				// The handler's buffer: the first bytes, then the two addresses at its end.
				if (r.buf == nullptr) r.buf = pool_.get();
				out = r.buf->data.data();
				data = kRecvBuf - 2 * kAcceptAddr;
			}
			DWORD got = 0;
			++c_.accept_calls;
			if (accept_ex_(sock(l.fd), r.s, out, data, kAcceptAddr, kAcceptAddr, &got, &r.ov) || WSAGetLastError() == ERROR_IO_PENDING)
			{
				// Done at once or pending: either way a packet follows, since the listener does not
				// skip the port on success.
				r.posted = true;
				++accepts_in_flight_;
				return;
			}
			const int e = WSAGetLastError();
			::closesocket(r.s);
			r.s = INVALID_SOCKET;
			++c_.accept_errors;
			// WSAECONNRESET: a client reset before its accept (AcceptEx docs); post again.
			if (e != WSAECONNRESET || attempt >= 16) throw std::system_error(e, std::system_category(), "AcceptEx");
		}
	}

	void Worker::on_accept_entry(AcceptReq& r, const loop::IocpEntry& x)
	{
		ListenerState& l = listeners_[r.listener];
		r.posted = false;
		--accepts_in_flight_;
		const SOCKET s = std::exchange(r.s, INVALID_SOCKET);
		Buffer* buf = std::exchange(r.buf, nullptr);
		if (ic_->stopped())
		{
			// Cancelled at stop, or done just before it: never a connection.
			::closesocket(s);
			if (buf != nullptr) pool_.put(buf);
			return;
		}
		if (x.status != 0)
		{
			// A client that reset before the accept completed: its socket goes, the request is
			// posted again.
			++c_.accept_errors;
			::closesocket(s);
			r.buf = buf;  // reused by the next post
			post_accept(l, r);
			return;
		}
		const SOCKET ls = sock(l.fd);
		u_long nonblocking = 1;
		bool ok = ::setsockopt(s, SOL_SOCKET, SO_UPDATE_ACCEPT_CONTEXT, reinterpret_cast<const char*>(&ls), sizeof(ls)) == 0 &&
		          ::ioctlsocket(s, FIONBIO, &nonblocking) == 0;
		if (ok)
		{
			try
			{
				ic_->associate(static_cast<std::uintptr_t>(s), kConnKey);
			}
			catch (const std::system_error&)
			{
				ok = false;
			}
		}
		ok = ok && SetFileCompletionNotificationModes(reinterpret_cast<HANDLE>(s), FILE_SKIP_COMPLETION_PORT_ON_SUCCESS);
		// The tests key their reports by the client's port; the server needs none, so it is read
		// only when a hook is set (as on io_uring). GetAcceptExSockaddrs parses the request's
		// buffer: no system call.
		std::uint16_t peer_port = 0;
		if (ok && (shared_.hooks.detection != nullptr || shared_.hooks.closed != nullptr || shared_.hooks.relayed != nullptr))
		{
			sockaddr* local = nullptr;
			sockaddr* remote = nullptr;
			int local_len = 0;
			int remote_len = 0;
			void* base = buf != nullptr ? static_cast<void*>(buf->data.data()) : static_cast<void*>(r.addrs.data());
			const DWORD data = buf != nullptr ? kRecvBuf - 2 * kAcceptAddr : 0;
			accept_addrs_(base, data, kAcceptAddr, kAcceptAddr, &local, &local_len, &remote, &remote_len);
			if (remote != nullptr && remote->sa_family == AF_INET) peer_port = ntohs(reinterpret_cast<const sockaddr_in*>(remote)->sin_port);
		}
		// The listener keeps N_ACCEPTEX outstanding: this request is posted again first.
		post_accept(l, r);
		if (!ok)
		{
			++c_.accept_errors;
			::closesocket(s);
			if (buf != nullptr) pool_.put(buf);
			return;
		}
		const int fd = fd_of(s);
		// --iocp-accept buffer: the bytes AcceptEx received are the connection's first read, taken
		// by pending_io(), which accepted() calls for a one-port listener.
		accept_buf_ = buf;
		accept_bytes_ = x.bytes;
		accepted(l, fd, peer_port);
		if (Buffer* left = std::exchange(accept_buf_, nullptr)) pool_.put(left);
		accept_bytes_ = 0;
	}

	// ---- Posting ----

	void Worker::post_poll_in(Conn* c)
	{
		if ((c->posted & bit(Op::poll_in)) != 0) return;
		IoOp& io = c->io_zero;
		std::memset(&io.ov, 0, sizeof(io.ov));
		io.slot = c->slot;
		io.op = Op::poll_in;
		WSABUF b{0, &zero_byte_buffer};
		DWORD got = 0;
		DWORD flags = 0;
		++c_.zero_byte_recv_calls;
		if (::WSARecv(sock(c->fd), &b, 1, &got, &flags, &io.ov, nullptr) == 0)
		{
			queue_inline(c, Op::poll_in, 0, 0);  // bytes or the end are there already
			return;
		}
		const int e = WSAGetLastError();
		if (e == WSA_IO_PENDING) posted(c, Op::poll_in);
		else queue_inline(c, Op::poll_in, 0, e);
	}

	void Worker::post_recv(Conn* c)
	{
		if ((c->posted & bit(Op::recv)) != 0) return;
		if (c->buf == nullptr) take_buffer(c);  // the posted form holds the handler's buffer while it waits (I15)
		const std::uint32_t room = kRecvBuf - c->len;
		if (room == 0) return;  // the caller decides what a full buffer means
		IoOp& io = c->io_recv;
		std::memset(&io.ov, 0, sizeof(io.ov));
		io.slot = c->slot;
		io.op = Op::recv;
		WSABUF b{room, reinterpret_cast<char*>(c->buf->data.data() + c->len)};
		DWORD got = 0;
		DWORD flags = 0;
		++c_.recv_calls;
		c->recv_into = Into::own;
		if (::WSARecv(sock(c->fd), &b, 1, &got, &flags, &io.ov, nullptr) == 0)
		{
			queue_inline(c, Op::recv, got, 0);
			return;
		}
		const int e = WSAGetLastError();
		if (e == WSA_IO_PENDING) posted(c, Op::recv);
		else queue_inline(c, Op::recv, 0, e);
	}

	void Worker::post_send(Conn* c)
	{
		if ((c->posted & bit(Op::poll_out)) != 0) return;
		IoOp& io = c->io_send;
		std::memset(&io.ov, 0, sizeof(io.ov));
		io.slot = c->slot;
		io.op = Op::poll_out;
		const std::size_t left = c->pend.size() - c->pend_off;
		WSABUF b{static_cast<ULONG>(std::min<std::size_t>(left, INT_MAX)), reinterpret_cast<char*>(c->pend.data() + c->pend_off)};
		DWORD sent = 0;
		++c_.send_calls;
		++c_.out_waits;
		if (::WSASend(sock(c->fd), &b, 1, &sent, 0, &io.ov, nullptr) == 0)
		{
			queue_inline(c, Op::poll_out, sent, 0);
			return;
		}
		const int e = WSAGetLastError();
		if (e == WSA_IO_PENDING) posted(c, Op::poll_out);
		else queue_inline(c, Op::poll_out, 0, e);
	}

	void Worker::pending_io(Conn* c)
	{
		if (c->fd < 0 || c->zombie) return;
		if (Buffer* b = std::exchange(accept_buf_, nullptr))
		{
			// AcceptEx's receive buffer brought the first bytes: they are the first read, in the
			// handler's buffer, and detection runs on them as in replay. They are no longer in the
			// socket, so this connection does not peek.
			const std::uint32_t n = std::exchange(accept_bytes_, 0);
			c->no_peek = true;
			c->buf = b;
			c->beg = 0;
			c->len = n;
			c_.bytes_received += n;
			c->bytes_received += n;
			c->last_read_pass = pass_;
			c->last_read_full = n == kRecvBuf;
			ReadResult rr;
			rr.bytes = n;
			++c->wakeups;
			++c_.detection_wakeups;
			if (c->stage == Stage::proxy) proxy_after_read(c, rr, false);
			else detect_after_read(c, rr);
			if (c->fd < 0 || c->zombie || (c->stage != Stage::proxy && c->stage != Stage::detect)) return;
			audit_pending(c);
		}
		if (peeks(c) || !posted_form()) post_poll_in(c);
		else post_recv(c);
	}

	void Worker::want_read(Conn* c)
	{
		if (c->fd < 0 || c->zombie || c->stage != Stage::handler) return;
		if (!c->pend.empty())
		{
			c->read_deferred = true;  // resumed by flush()
			return;
		}
		if (c->eof_seen) return;
		if (c->buf != nullptr && c->len == kRecvBuf)
		{
			close_conn(c);  // a full buffer its handler cannot consume
			return;
		}
		if (posted_form()) post_recv(c);
		else post_poll_in(c);
	}

	std::optional<int> Worker::reap_for(Conn* c)
	{
		std::optional<int> got;
		const OVERLAPPED* target = &c->io_recv.ov;
		for (const loop::IocpEntry& x : ic_->reap_now())
		{
			if (!got && x.overlapped == target && (c->posted & bit(Op::recv)) != 0) got = x.status != 0 ? -1 : static_cast<int>(x.bytes);
			on_entry(x);
			settle();
		}
		return got;
	}

	void Worker::cancel_all(Conn* c)
	{
		// closesocket() has cancelled every operation; each completion still arrives (finalize).
		c->zombie = true;
		++zombies_;
	}

	// ---- Output ----

	void Worker::want_out(Conn* c) { post_send(c); }

	bool Worker::flush(Conn* c)
	{
		if (c->pend_off < c->pend.size())
		{
			post_send(c);  // the rest of the queue
			return true;
		}
		c->pend.clear();
		c->pend_off = 0;
		if (!c->pend_more.empty())
		{
			c->pend.swap(c->pend_more);  // what was emitted meanwhile: no copy
			post_send(c);
			return true;
		}
		if (c->close_after_out)
		{
			close_conn(c);
			return false;
		}
		// Resume: a read that waited for this flush, or bytes left in the buffer by a full read.
		const std::uint64_t id = c->id;
		c->read_deferred = false;
		if (handler_run(c)) want_read(c);
		return c->id == id && c->fd >= 0 && !c->zombie;
	}

	// ---- The switch to replay (I11) ----

	void Worker::switch_to_replay(Conn* c)
	{
		c->no_peek = true;
		c->peek_switched = true;
		++c_.peek_to_replay;
		if (c->buf == nullptr) take_buffer(c);
		const ReadResult rr = read_into(c, false);
		if (c->stage == Stage::proxy) proxy_after_read(c, rr, false);
		else detect_after_read(c, rr);
	}

	// ---- Stop ----

	void Worker::stop_iocp()
	{
		close_all();
		settle();
		for (ListenerState& l : listeners_)
		{
			for (auto& r : l.accepts)
			{
				if (r->posted) ::CancelIoEx(reinterpret_cast<HANDLE>(sock(l.fd)), &r->ov);  // ERROR_NOT_FOUND: its packet is queued
			}
		}
		const TimePoint until = Clock::now() + kDrainLimit;
		while ((zombies_ > 0 || accepts_in_flight_ > 0) && Clock::now() < until)
		{
			take_entries(ic_->drain(std::chrono::milliseconds(10)));
		}
		if ((zombies_ > 0 || accepts_in_flight_ > 0) && !error_)
		{
			error_ = "worker " + std::to_string(index_) + ": " + std::to_string(zombies_) + " connections and " + std::to_string(accepts_in_flight_) +
			         " AcceptEx requests still had operations in flight at stop";
		}
	}

	// ---- Relay dispatch: Linux only (hypotheses.md, section 2.1; the parser refuses it on IOCP) ----

	void Worker::start_relay(Conn*, Proto, Entry) { throw std::logic_error("oneport: relay dispatch is Linux only"); }

}  // namespace oneport::server::detail

#endif  // _WIN32
