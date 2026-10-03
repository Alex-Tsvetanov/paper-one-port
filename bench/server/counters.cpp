// The names of outcomes and timers, and the counters' sum and printout (proposal I29).
#include "server.hpp"

#include <string>

#if defined(__linux__)
#include <linux/io_uring.h>
#endif

namespace oneport::server
{

	std::string_view name(Outcome o) noexcept
	{
		switch (o)
		{
			case Outcome::classified: return "classified";
			case Outcome::rejected: return "rejected";
			case Outcome::undecided: return "undecided";
			case Outcome::silent: return "silent";
			case Outcome::fallback: return "fallback";
			case Outcome::rejected_budget: return "rejected_budget";
			case Outcome::proxy_rejected: return "proxy_rejected";
			case Outcome::proxy_timeout: return "proxy_timeout";
			case Outcome::reset: return "reset";
			case Outcome::stopped: return "stopped";
		}
		return "?";
	}

	std::string_view name(TimerKind k) noexcept
	{
		switch (k)
		{
			case TimerKind::t_hdr: return "T_hdr";
			case TimerKind::t_fb: return "T_fb";
			case TimerKind::t_dec: return "T_dec";
		}
		return "?";
	}

	std::string_view name(Route r) noexcept
	{
		switch (r)
		{
			case Route::by_class: return "by_class";
			case Route::by_sni: return "by_sni";
			case Route::rejected: return "rejected";
			case Route::connect_failed: return "connect_failed";
			case Route::timed_out: return "timed_out";
		}
		return "?";
	}

	namespace
	{

		/// The io_uring opcodes the server submits, by the names of IORING_OP_*; others by number.
		std::string opcode_name(std::size_t op)
		{
#if defined(__linux__)
			switch (op)
			{
				case IORING_OP_POLL_ADD: return "POLL_ADD";
				case IORING_OP_ACCEPT: return "ACCEPT";
				case IORING_OP_ASYNC_CANCEL: return "ASYNC_CANCEL";
				case IORING_OP_CONNECT: return "CONNECT";
				case IORING_OP_RECV: return "RECV";
				case IORING_OP_READ: return "READ";
				case IORING_OP_SPLICE: return "SPLICE";
				default: break;
			}
#endif
			return "op" + std::to_string(op);
		}

	}  // namespace

	Counters& Counters::operator+=(const Counters& o)
	{
		accept_calls += o.accept_calls;
		recv_calls += o.recv_calls;
		recv_eof += o.recv_eof;
		recv_again += o.recv_again;
		peek_calls += o.peek_calls;
		send_calls += o.send_calls;
		setsockopt_calls += o.setsockopt_calls;
		check_calls += o.check_calls;
		epoll_wait_calls += o.epoll_wait_calls;
		epoll_ctl_calls += o.epoll_ctl_calls;
		zero_byte_recv_calls += o.zero_byte_recv_calls;
		io_uring_enter_calls += o.io_uring_enter_calls;
		gqcs_calls += o.gqcs_calls;
		peek_to_replay += o.peek_to_replay;
		lowat_sets += o.lowat_sets;
		lowat_resets += o.lowat_resets;
		check_found_byte += o.check_found_byte;
		connect_calls += o.connect_calls;
		splice_calls += o.splice_calls;
		shutdown_calls += o.shutdown_calls;
		recv_retries += o.recv_retries;
		out_waits += o.out_waits;
		for (std::size_t i = 0; i < uring_submissions.size(); ++i) uring_submissions[i] += o.uring_submissions[i];
		bytes_received += o.bytes_received;
		bytes_peeked += o.bytes_peeked;
		bytes_sent += o.bytes_sent;
		bytes_copied += o.bytes_copied;
		bytes_spliced += o.bytes_spliced;
		detection_wakeups += o.detection_wakeups;
		accepted += o.accepted;
		closed += o.closed;
		for (std::size_t i = 0; i < outcomes.size(); ++i) outcomes[i] += o.outcomes[i];
		for (std::size_t i = 0; i < classified.size(); ++i) classified[i] += o.classified[i];
		for (std::size_t i = 0; i < fallback.size(); ++i) fallback[i] += o.fallback[i];
		accept_errors += o.accept_errors;
		relayed += o.relayed;
		routed_by_sni += o.routed_by_sni;
		route_rejected += o.route_rejected;
		route_timeouts += o.route_timeouts;
		relay_connect_errors += o.relay_connect_errors;
		tls_states += o.tls_states;
		conns_open += o.conns_open;
		buffers_allocated += o.buffers_allocated;
		buffers_outstanding += o.buffers_outstanding;
		ring_buffers += o.ring_buffers;
		passes += o.passes;
		timed.insert(timed.end(), o.timed.begin(), o.timed.end());
		return *this;
	}

	std::string describe(const Counters& c)
	{
		std::string s;
		auto line = [&s](std::string_view key, std::uint64_t v) {
			s += "counter ";
			s += key;
			s += ' ';
			s += std::to_string(v);
			s += '\n';
		};
		line("accept_calls", c.accept_calls);
		line("recv_calls", c.recv_calls);
		line("recv_eof", c.recv_eof);
		line("recv_again", c.recv_again);
		line("peek_calls", c.peek_calls);
		line("send_calls", c.send_calls);
		line("setsockopt_calls", c.setsockopt_calls);
		line("check_calls", c.check_calls);
		line("epoll_wait_calls", c.epoll_wait_calls);
		line("epoll_ctl_calls", c.epoll_ctl_calls);
		line("zero_byte_recv_calls", c.zero_byte_recv_calls);
		line("io_uring_enter_calls", c.io_uring_enter_calls);
		line("gqcs_calls", c.gqcs_calls);
		line("peek_to_replay", c.peek_to_replay);
		line("lowat_sets", c.lowat_sets);
		line("lowat_resets", c.lowat_resets);
		line("check_found_byte", c.check_found_byte);
		line("connect_calls", c.connect_calls);
		line("splice_calls", c.splice_calls);
		line("shutdown_calls", c.shutdown_calls);
		line("recv_retries", c.recv_retries);
		line("out_waits", c.out_waits);
		for (std::size_t i = 0; i < c.uring_submissions.size(); ++i)
		{
			if (c.uring_submissions[i] == 0) continue;
			s += "counter io_uring_submissions ";
			s += opcode_name(i);
			s += ' ';
			s += std::to_string(c.uring_submissions[i]);
			s += '\n';
		}
		line("bytes_received", c.bytes_received);
		line("bytes_peeked", c.bytes_peeked);
		line("bytes_sent", c.bytes_sent);
		line("bytes_copied", c.bytes_copied);
		line("bytes_spliced", c.bytes_spliced);
		line("detection_wakeups", c.detection_wakeups);
		line("accepted", c.accepted);
		line("closed", c.closed);
		for (std::size_t i = 0; i < kOutcomes; ++i)
		{
			s += "counter outcome ";
			s += name(static_cast<Outcome>(i));
			s += ' ';
			s += std::to_string(c.outcomes[i]);
			s += '\n';
		}
		for (std::size_t i = 0; i < detect::kProtos; ++i)
		{
			s += "counter classified ";
			s += detect::name(static_cast<Proto>(i));
			s += ' ';
			s += std::to_string(c.classified[i]);
			s += '\n';
		}
		for (std::size_t i = 0; i < detect::kProtos; ++i)
		{
			s += "counter fallback ";
			s += detect::name(static_cast<Proto>(i));
			s += ' ';
			s += std::to_string(c.fallback[i]);
			s += '\n';
		}
		line("accept_errors", c.accept_errors);
		line("relayed", c.relayed);
		line("routed_by_sni", c.routed_by_sni);
		line("route_rejected", c.route_rejected);
		line("route_timeouts", c.route_timeouts);
		line("relay_connect_errors", c.relay_connect_errors);
		line("tls_states", c.tls_states);
		line("conns_open", c.conns_open);
		line("buffers_allocated", c.buffers_allocated);
		line("buffers_outstanding", c.buffers_outstanding);
		line("ring_buffers", c.ring_buffers);
		line("passes", c.passes);
		line("timed_events", c.timed.size());
		return s;
	}

}  // namespace oneport::server
