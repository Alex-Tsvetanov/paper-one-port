// The names of outcomes and timers, and the counters' sum and printout (proposal I29).
#include "server.hpp"

#include <string>

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

	Counters& Counters::operator+=(const Counters& o)
	{
		accept_calls += o.accept_calls;
		recv_calls += o.recv_calls;
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
		bytes_received += o.bytes_received;
		bytes_peeked += o.bytes_peeked;
		bytes_sent += o.bytes_sent;
		bytes_copied += o.bytes_copied;
		detection_wakeups += o.detection_wakeups;
		accepted += o.accepted;
		closed += o.closed;
		for (std::size_t i = 0; i < outcomes.size(); ++i) outcomes[i] += o.outcomes[i];
		for (std::size_t i = 0; i < classified.size(); ++i) classified[i] += o.classified[i];
		for (std::size_t i = 0; i < fallback.size(); ++i) fallback[i] += o.fallback[i];
		accept_errors += o.accept_errors;
		conns_open += o.conns_open;
		buffers_allocated += o.buffers_allocated;
		buffers_outstanding += o.buffers_outstanding;
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
		line("bytes_received", c.bytes_received);
		line("bytes_peeked", c.bytes_peeked);
		line("bytes_sent", c.bytes_sent);
		line("bytes_copied", c.bytes_copied);
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
		line("conns_open", c.conns_open);
		line("buffers_allocated", c.buffers_allocated);
		line("buffers_outstanding", c.buffers_outstanding);
		line("passes", c.passes);
		line("timed_events", c.timed.size());
		return s;
	}

}  // namespace oneport::server
