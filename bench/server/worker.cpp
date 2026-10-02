// The worker's pass on epoll, accept, the PROXY header, detection and timers (see worker.hpp).
// The detection and the timers are shared with io_uring (uring.cpp): what differs is how the
// bytes reach them (proxy_after_read, detect_after_read) and the check of 1(b).
#include "worker.hpp"

#if defined(__linux__)

#include <algorithm>
#include <cstring>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

namespace oneport::server::detail
{

	Worker::Worker(unsigned index, const Shared& shared, const std::vector<ListenerSpec>& specs, const std::vector<int>& fds)
		: index_(index), shared_(shared)
	{
		if (uring()) ur_ = std::make_unique<loop::UringLoop>();
		else ep_ = std::make_unique<loop::EpollLoop>();
		listeners_.resize(specs.size());
		for (std::size_t i = 0; i < specs.size(); ++i)
		{
			listeners_[i].fd = fds[i];
			listeners_[i].index = i;
			listeners_[i].spec = &specs[i];
		}
	}

	Worker::~Worker()
	{
		ur_.reset();  // the ring first: its operations reference the descriptors and buffers below
		for (auto& c : conns_)
		{
			if (c->fd >= 0) ::close(c->fd);
			if (c->relay && c->relay->fd >= 0) ::close(c->relay->fd);
		}
	}

	void Worker::stop() noexcept
	{
		if (ur_) ur_->stop();
		else ep_->stop();
	}

	void Worker::run()
	{
		if (uring())
		{
			run_uring();
			return;
		}
		try
		{
			ep_->start();
			const std::uint32_t listen_events = EPOLLIN | EPOLLET | (shared_.exclusive_listeners ? EPOLLEXCLUSIVE : 0u);
			for (const ListenerState& l : listeners_)
			{
				ep_->add(l.fd, listen_events, kListenerTag | l.index);
				++c_.epoll_ctl_calls;
			}
			prev_return_ = Clock::now();
			while (!ep_->stopped())
			{
				pass_epoll();
			}
		}
		catch (const std::exception& e)
		{
			error_ = std::string("worker ") + std::to_string(index_) + ": " + e.what();
		}
		close_all();
	}

	// ---- The pass ----

	std::optional<TimePoint> Worker::earliest() const noexcept
	{
		std::optional<TimePoint> e;
		for (const ListenerState& l : listeners_)
		{
			for (std::size_t k = 0; k < l.lists.size(); ++k)
			{
				const Conn* h = l.lists[k].head;
				if (h == nullptr) continue;
				const TimePoint d = h->timers[k].deadline;
				if (!e || d < *e) e = d;
			}
		}
		return e;
	}

	loop::Bound Worker::bound_now() const
	{
		const std::optional<TimePoint> first = earliest();
		if (!first) return std::nullopt;
		const TimePoint now = Clock::now();
		return *first > now ? std::chrono::duration_cast<nanoseconds>(*first - now) : nanoseconds(0);
	}

	void Worker::pass_epoll()
	{
		const std::span<const epoll_event> events = ep_->wait(bound_now());
		const TimePoint wait_return = Clock::now();  // the clock, re-read after every wait (I13)
		++c_.epoll_wait_calls;
		pass_ = ep_->passes();
		if (ep_->stopped()) return;
		for (const epoll_event& ev : events) on_event(ev.data.u64, ev.events);
		if (shared_.hooks.before_expiries != nullptr) shared_.hooks.before_expiries(shared_.hooks.ctx, index_, wait_return, earliest());
		expire(wait_return);
		prev_return_ = wait_return;
	}

	void Worker::on_event(std::uint64_t tag, std::uint32_t events)
	{
		if ((tag & kListenerTag) != 0)
		{
			on_accept(listeners_[static_cast<std::size_t>(tag & 0xFFFF)]);
			return;
		}
		const auto fd = static_cast<int>(tag & 0xFFFFFFFFu);
		const auto gen = static_cast<std::uint32_t>(tag >> 32);
		if (fd < 0 || static_cast<std::size_t>(fd) >= by_fd_.size()) return;
		Conn* c = by_fd_[static_cast<std::size_t>(fd)];
		if (c == nullptr) return;  // closed in this pass
		const bool backend = c->relay && c->relay->fd == fd;
		if (backend ? c->relay->gen != gen : (c->fd != fd || c->gen != gen)) return;  // the fd was reused
		const bool rdhup = (events & EPOLLRDHUP) != 0;
		const bool err = (events & (EPOLLERR | EPOLLHUP)) != 0;
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
				audit_pending(c);
				return;
			case Stage::route:
				if (err)
				{
					relay_abort(c, true);
					return;
				}
				route_readable(c, rdhup);
				return;
			case Stage::relay: relay_event(c, backend, events); return;
			case Stage::handler:
				if (rdhup) c->rdhup_seen = true;
				if ((events & EPOLLOUT) != 0 && !c->pend.empty())
				{
					if (!flush(c)) return;  // closed; a flush that empties the queue resumes the handler
				}
				if ((events & (EPOLLIN | EPOLLRDHUP | EPOLLERR | EPOLLHUP)) != 0) handler_readable(c, rdhup, true);
				return;
		}
	}

	// ---- Accept ----

	void Worker::on_accept(ListenerState& l)
	{
		for (;;)
		{
			sockaddr_storage peer{};
			socklen_t peer_len = sizeof(peer);
			const int fd = ::accept4(l.fd, reinterpret_cast<sockaddr*>(&peer), &peer_len, SOCK_NONBLOCK | SOCK_CLOEXEC);
			++c_.accept_calls;
			if (fd < 0)
			{
				if (errno == EINTR || errno == ECONNABORTED) continue;
				if (errno != EAGAIN && errno != EWOULDBLOCK) ++c_.accept_errors;
				return;
			}
			accepted(l, fd, peer.ss_family == AF_INET ? ntohs(reinterpret_cast<const sockaddr_in&>(peer).sin_port) : 0);
		}
	}

	void Worker::accepted(ListenerState& l, int fd, std::uint16_t peer_port)
	{
		Conn* c = new_conn(fd);
		c->listener = &l;
		c->peer_port = peer_port;
		c->accept_pass = pass_;
		++c_.accepted;
		if (!uring())
		{
			try
			{
				ep_->add(fd, kConnEvents, tag_of(fd, c->gen));
				++c_.epoll_ctl_calls;
			}
			catch (const std::system_error&)
			{
				++c_.accept_errors;
				close_conn(c);
				return;
			}
		}
		const ListenerSpec& spec = *l.spec;
		if (spec.proxy || spec.detects) c->accept_time = Clock::now();  // timers start at accept
		if (spec.proxy)
		{
			c->stage = Stage::proxy;
			arm(c, TimerKind::t_hdr, c->accept_time + shared_.t_hdr);
			if (uring()) pending_io(c);
		}
		else if (spec.detects)
		{
			c->stage = Stage::detect;
			start_detection_timers(c, c->accept_time);
			if (uring()) pending_io(c);
		}
		else
		{
			enter_handler(c, spec.proto, Entry::accept);
		}
	}

	void Worker::start_detection_timers(Conn* c, TimePoint start)
	{
		c->timers_start = start;
		if (c->listener->spec->fallback) arm(c, TimerKind::t_fb, start + shared_.t_fb);
		arm(c, TimerKind::t_dec, start + shared_.t_dec);
	}

	// ---- The PROXY header (I9 step 1) ----

	void Worker::on_proxy_readable(Conn* c, bool rdhup)
	{
		if (peeks(c))
		{
			const ssize_t n = peek(c, scratch_);
			if (n < 0) return;  // nothing, or closed by peek()
			if (n == 0)
			{
				end_detection(c, Outcome::silent, 0);
				return;
			}
			const std::span<const std::byte> seen(scratch_.data(), static_cast<std::size_t>(n));
			const detect::ProxyResult r = detect::parse_proxy(seen);
			if (r.verdict == detect::ProxyVerdict::no)
			{
				end_detection(c, Outcome::proxy_rejected, r.at, r.reason);
				return;
			}
			if (r.verdict == detect::ProxyVerdict::more)
			{
				if (rdhup) end_detection(c, Outcome::undecided, 0);
				else set_lowat(c, r.at);
				return;
			}
			// Consume exactly the header, so the next read starts at the first application byte.
			const ssize_t got = ::recv(c->fd, scratch_.data(), r.at, MSG_DONTWAIT);
			++c_.recv_calls;
			if (got != static_cast<ssize_t>(r.at))
			{
				end_detection(c, Outcome::reset, 0);
				return;
			}
			c_.bytes_received += r.at;
			c->bytes_received += r.at;
			if (!header_complete(c, r) || c->stage != Stage::detect) return;
			// The application bytes of the same peek are still queued; decide on them now.
			const std::size_t app = static_cast<std::size_t>(n) - r.at;
			if (app == 0)
			{
				if (rdhup) end_detection(c, Outcome::silent, 0);
				return;
			}
			const std::size_t keep = std::min<std::size_t>(app, detect::kBDec);  // B_dec after the header
			observed_app_bytes(c, static_cast<std::uint32_t>(keep));
			run_detection(c, std::span<const std::byte>(scratch_.data() + r.at, keep), rdhup);
			return;
		}
		// Read into the handler's buffer (epoll; io_uring's receive completes into it).
		if (c->buf == nullptr) take_buffer(c);
		const ReadResult rr = read_into(c, rdhup);
		proxy_after_read(c, rr, rdhup);
	}

	void Worker::proxy_after_read(Conn* c, const ReadResult& rr, bool rdhup)
	{
		if (rr.error)
		{
			end_detection(c, Outcome::reset, 0);
			return;
		}
		if (c->buf == nullptr || c->len == c->beg)
		{
			drop_empty_buffer(c);
			if (rr.eof) end_detection(c, Outcome::silent, 0);
			return;
		}
		track_user_bytes(c);
		const detect::ProxyResult r = detect::parse_proxy(std::span<const std::byte>(c->buf->data.data() + c->beg, c->len - c->beg));
		if (r.verdict == detect::ProxyVerdict::no)
		{
			end_detection(c, Outcome::proxy_rejected, r.at, r.reason);
			return;
		}
		if (r.verdict == detect::ProxyVerdict::more)
		{
			if (rr.eof) end_detection(c, Outcome::undecided, 0);
			return;
		}
		c->beg += r.at;
		if (!header_complete(c, r)) return;
		if (c->stage == Stage::detect)
		{
			if (c->len == c->beg)
			{
				drop_empty_buffer(c);
				if (rr.eof) end_detection(c, Outcome::silent, 0);
				return;
			}
			observed_app_bytes(c, c->len - c->beg);
			run_detection(c, std::span<const std::byte>(c->buf->data.data() + c->beg, c->len - c->beg), rr.eof);
			return;
		}
		// A dedicated listener: its handler takes the bytes after the header.
		if (c->len == c->beg) drop_empty_buffer(c);
		if (uring())
		{
			if (handler_run(c)) want_read(c);
			return;
		}
		handler_readable(c, rdhup, c->last_read_full);
	}

	bool Worker::header_complete(Conn* c, const detect::ProxyResult& r)
	{
		disarm(c, TimerKind::t_hdr);
		c->has_proxy = true;
		c->proxy = r.source;
		if (c->listener->spec->detects)
		{
			c->stage = Stage::detect;
			start_detection_timers(c, Clock::now());  // T_fb and T_dec start when the header is complete
			if (peeks(c) && c->lowat != 1) set_lowat(c, 1);
			return true;
		}
		// A dedicated listener: the handler enters now (SSH and SMTP speak at entry); the caller
		// hands it the bytes after the header.
		return start_handler(c, c->listener->spec->proto);
	}

	// ---- Detection (I9 steps 2 and 3, I11) ----

	void Worker::observed_app_bytes(Conn* c, std::uint32_t n)
	{
		if (c->app_seen == 0 && n > 0) disarm(c, TimerKind::t_fb);  // a byte arrived: T_fb no longer applies
		c->app_seen = n;
		c->last_read_pass = pass_;
	}

	void Worker::on_detect_readable(Conn* c, bool rdhup)
	{
		if (peeks(c))
		{
			const ssize_t n = peek(c, std::span<std::byte>(scratch_.data(), detect::kBDec));
			if (n < 0) return;
			if (n == 0)
			{
				end_detection(c, c->app_seen > 0 ? Outcome::undecided : Outcome::silent, 0);
				return;
			}
			observed_app_bytes(c, static_cast<std::uint32_t>(n));
			run_detection(c, std::span<const std::byte>(scratch_.data(), static_cast<std::size_t>(n)), rdhup);
			return;
		}
		// Replay: the first read goes into the buffer the handler will parse (I11).
		if (c->buf == nullptr) take_buffer(c);
		detect_after_read(c, read_into(c, rdhup));
	}

	void Worker::detect_after_read(Conn* c, const ReadResult& rr)
	{
		if (rr.error)
		{
			end_detection(c, Outcome::reset, 0);
			return;
		}
		if (c->buf == nullptr || c->len == c->beg)
		{
			drop_empty_buffer(c);
			if (rr.eof) end_detection(c, c->app_seen > 0 ? Outcome::undecided : Outcome::silent, 0);
			return;
		}
		track_user_bytes(c);
		observed_app_bytes(c, c->len - c->beg);
		run_detection(c, std::span<const std::byte>(c->buf->data.data() + c->beg, c->len - c->beg), rr.eof);
	}

	void Worker::run_detection(Conn* c, std::span<const std::byte> bytes, bool eof)
	{
		const detect::Decision d = detect::classify(bytes);
		switch (d.outcome)
		{
			case detect::Outcome::classified: dispatch(c, d.proto, d.at); return;
			case detect::Outcome::rejected: end_detection(c, Outcome::rejected, d.at); return;
			case detect::Outcome::more: break;
		}
		if (bytes.size() >= detect::kBDec)
		{
			// Unreachable while every need is at most B_dec (detect_corpus.hpp); kept as the rule.
			end_detection(c, Outcome::rejected_budget, static_cast<std::uint32_t>(bytes.size()));
			return;
		}
		if (eof)
		{
			end_detection(c, Outcome::undecided, 0);  // 1(h)
			return;
		}
		if (peeks(c)) set_lowat(c, d.at);
	}

	void Worker::dispatch(Conn* c, Proto p, std::uint32_t at)
	{
		disarm(c, TimerKind::t_fb);
		disarm(c, TimerKind::t_dec);
		++c_.outcomes[static_cast<std::size_t>(Outcome::classified)];
		++c_.classified[static_cast<std::size_t>(p)];
		const bool peeked = peeks(c);
		// Reset before the handler reads; the relay's pass-through sets its own mark.
		if (peeked && c->lowat != 1 && !(shared_.relay && p == Proto::tls)) set_lowat(c, 1);
		report(c, Outcome::classified, p, at);
		enter_handler(c, p, peeked ? Entry::peek : Entry::replay);
	}

	void Worker::end_detection(Conn* c, Outcome o, std::uint32_t at, detect::ProxyReason why, const TimedEvent* ev)
	{
		++c_.outcomes[static_cast<std::size_t>(o)];
		report(c, o, Proto::http1, at, why, ev);
		close_conn(c);
	}

	void Worker::report(const Conn* c, Outcome o, Proto p, std::uint32_t at, detect::ProxyReason why, const TimedEvent* ev)
	{
		if (shared_.hooks.detection == nullptr) return;
		DetectionReport r;
		r.worker = index_;
		r.conn = c->id;
		r.peer_port = c->peer_port;
		r.outcome = o;
		r.proto = p;
		r.at = at;
		r.proxy_reason = why;
		r.accept_pass = c->accept_pass;
		r.end_pass = pass_;
		r.last_read_pass = c->last_read_pass;
		r.observe_pass = c->observe_pass;
		r.accept_time = c->accept_time;
		r.timers_start = c->timers_start;
		r.end_time = Clock::now();
		r.app_bytes = c->app_seen;
		r.max_user_bytes = c->max_user_bytes;
		r.buffer_while_silent = c->buffer_while_silent;
		r.wakeups = c->wakeups;
		r.lowat_sets = c->lowat_sets;
		r.lowat_resets = c->lowat_resets;
		r.has_proxy = c->has_proxy;
		r.proxy = c->proxy;
		if (ev != nullptr)
		{
			r.timed = true;
			r.event = *ev;
		}
		shared_.hooks.detection(shared_.hooks.ctx, r);
	}

	ssize_t Worker::peek(Conn* c, std::span<std::byte> into)
	{
		const ssize_t n = ::recv(c->fd, into.data(), into.size(), MSG_PEEK | MSG_DONTWAIT);
		++c_.peek_calls;
		if (n > 0)
		{
			c_.bytes_peeked += static_cast<std::uint64_t>(n);
			c->last_read_pass = pass_;
			return n;
		}
		if (n == 0) return 0;
		if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return -1;
		if (c->stage == Stage::route) relay_abort(c, true);
		else end_detection(c, Outcome::reset, 0);
		return -1;
	}

	void Worker::set_lowat(Conn* c, std::uint32_t total)
	{
		if (c->lowat == total) return;
		const int v = static_cast<int>(total);
		if (::setsockopt(c->fd, SOL_SOCKET, SO_RCVLOWAT, &v, sizeof(v)) != 0) throw_errno("setsockopt (SO_RCVLOWAT)");
		++c_.setsockopt_calls;
		if (total == 1)
		{
			++c_.lowat_resets;
			++c->lowat_resets;
		}
		else
		{
			++c_.lowat_sets;
			++c->lowat_sets;
		}
		c->lowat = total;
	}

	// ---- Timers (I13; hypotheses.md, section 1) ----

	void Worker::arm(Conn* c, TimerKind k, TimePoint deadline) noexcept
	{
		c->listener->lists[static_cast<std::size_t>(k)].push(c, k, deadline);
	}

	TimedEvent Worker::record(const Conn* c, TimerKind k, TimePoint deadline, TimePoint wait_return, TimerResult result)
	{
		TimedEvent ev;
		ev.conn = c->id;
		ev.kind = k;
		ev.result = result;
		ev.start = k == TimerKind::t_hdr ? c->accept_time : c->timers_start;
		ev.deadline = deadline;
		ev.wait_return = wait_return;
		ev.prev_wait_return = prev_return_;
		ev.handled_at = Clock::now();
		ev.pass = pass_;
		c_.timed.push_back(ev);
		return ev;
	}

	void Worker::expire(TimePoint wait_return)
	{
		for (std::size_t k = 0; k < 3; ++k)
		{
			for (ListenerState& l : listeners_)
			{
				DeadlineList& list = l.lists[k];
				while (list.head != nullptr && list.head->timers[k].deadline <= wait_return)
				{
					Conn* c = list.head;
					const auto kind = static_cast<TimerKind>(k);
					if (kind == TimerKind::t_hdr) expire_hdr(c, wait_return);
					else if (kind == TimerKind::t_fb) expire_fb(c, wait_return);
					else expire_dec(c, wait_return);
				}
			}
		}
	}

	void Worker::expire_hdr(Conn* c, TimePoint wait_return)
	{
		const TimedEvent ev = record(c, TimerKind::t_hdr, deadline_of(c, TimerKind::t_hdr), wait_return, TimerResult::closed);
		disarm(c, TimerKind::t_hdr);
		end_detection(c, Outcome::proxy_timeout, 0, detect::ProxyReason::none, &ev);
	}

	void Worker::expire_fb(Conn* c, TimePoint wait_return)
	{
		const TimePoint deadline = deadline_of(c, TimerKind::t_fb);
		disarm(c, TimerKind::t_fb);
		if (uring() && !peeks(c))
		{
			// io_uring replay: a receive is posted with a buffer, so the check is a non-waiting
			// reap of the ring's completions (1 b). Every completion it reaps is handled now; if
			// this connection's receive was among them, its bytes (or its end) decided it, and the
			// connection may be closed, even reused, by then: the event is recorded first.
			const TimedEvent ev = record(c, TimerKind::t_fb, deadline, wait_return, TimerResult::fallback);
			const std::size_t at = c_.timed.size() - 1;
			++c_.check_calls;
			if (const std::optional<int> res = reap_for(c))
			{
				// Bytes (or ENOBUFS: bytes are queued, and the receive posted again brings them):
				// the byte wins. 0 or an error: the half-close or the reset ended the connection.
				++c_.check_found_byte;
				c_.timed[at].result = (*res > 0 || *res == -ENOBUFS) ? TimerResult::byte_won : TimerResult::closed;
				return;
			}
			disarm(c, TimerKind::t_dec);
			const Proto p = *c->listener->spec->fallback;
			++c_.outcomes[static_cast<std::size_t>(Outcome::fallback)];
			++c_.fallback[static_cast<std::size_t>(p)];
			report(c, Outcome::fallback, p, 0, detect::ProxyReason::none, &ev);
			enter_handler(c, p, Entry::fallback);
			return;
		}
		else
		{
			std::array<std::byte, 1> one{};
			const ssize_t n = ::recv(c->fd, one.data(), one.size(), MSG_PEEK | MSG_DONTWAIT);
			++c_.check_calls;
			if (n == 1)
			{
				++c_.check_found_byte;
				record(c, TimerKind::t_fb, deadline, wait_return, TimerResult::byte_won);
				on_detect_readable(c, false);  // the bytes alone decide the connection
				if (uring() && c->fd >= 0 && !c->zombie && (c->stage == Stage::detect || c->stage == Stage::route)) pending_io(c);
				return;
			}
			if (n == 0)
			{
				c->observe_pass = pass_;
				const TimedEvent ev = record(c, TimerKind::t_fb, deadline, wait_return, TimerResult::closed);
				end_detection(c, Outcome::silent, 0, detect::ProxyReason::none, &ev);  // 1(h): a half-close, no byte
				return;
			}
			if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
			{
				const TimedEvent ev = record(c, TimerKind::t_fb, deadline, wait_return, TimerResult::closed);
				end_detection(c, Outcome::reset, 0, detect::ProxyReason::none, &ev);
				return;
			}
		}
		const TimedEvent ev = record(c, TimerKind::t_fb, deadline, wait_return, TimerResult::fallback);
		disarm(c, TimerKind::t_dec);
		const Proto p = *c->listener->spec->fallback;
		++c_.outcomes[static_cast<std::size_t>(Outcome::fallback)];
		++c_.fallback[static_cast<std::size_t>(p)];
		report(c, Outcome::fallback, p, 0, detect::ProxyReason::none, &ev);
		enter_handler(c, p, Entry::fallback);
	}

	void Worker::expire_dec(Conn* c, TimePoint wait_return)
	{
		if (c->app_seen == 0 && c->listener->spec->fallback)
		{
			record(c, TimerKind::t_dec, deadline_of(c, TimerKind::t_dec), wait_return, TimerResult::waited);
			disarm(c, TimerKind::t_dec);
			return;
		}
		const TimedEvent ev = record(c, TimerKind::t_dec, deadline_of(c, TimerKind::t_dec), wait_return, TimerResult::closed);
		disarm(c, TimerKind::t_dec);
		end_detection(c, c->app_seen > 0 ? Outcome::undecided : Outcome::silent, 0, detect::ProxyReason::none, &ev);
	}

}  // namespace oneport::server::detail

#endif  // __linux__
