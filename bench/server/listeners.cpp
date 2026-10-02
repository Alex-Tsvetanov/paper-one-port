// The listener setup: the one place outside the flag parser that reads Config::mode
// (design/proposal.md I21; the structural test tests/check_mode_readers.cmake enforces it).
// The mode becomes a list of listener roles here, and nothing after this file knows it: a
// one-port listener detects, a dedicated listener sets each connection's class at accept, and
// from then on both run the same code.
#include "server.hpp"

#include <string>

namespace oneport::server
{

	std::optional<std::string> not_served(const Config& config)
	{
		if (config.backend == Backend::io_uring) return "the io_uring backend is M2b";
		if (config.backend == Backend::iocp) return "the IOCP backend is M6 (Windows)";
		if (config.dispatch == Dispatch::relay) return "relay dispatch is M2b";
		if (config.mode == Mode::stub) return "stub mode, the relay's backend, is M2b";
		return std::nullopt;
	}

	std::vector<ListenerSpec> listener_specs(const Config& config)
	{
		const bool proxy = config.proxy == Proxy::on;
		std::vector<ListenerSpec> specs;
		if (config.mode == Mode::one_port)
		{
			ListenerSpec s;
			s.detects = true;
			s.proxy = proxy;
			if (config.fallback == Fallback::smtp) s.fallback = Proto::smtp;
			if (config.fallback == Fallback::ssh) s.fallback = Proto::ssh;
			s.name = "one-port";
			specs.push_back(s);
			return specs;
		}
		// Dedicated mode (and, from M2b, stub mode): one port per class, in the order of I20.
		for (const Proto p : {Proto::http1, Proto::h2c, Proto::tls, Proto::mqtt, Proto::ssh, Proto::smtp})
		{
			ListenerSpec s;
			s.detects = false;
			s.proto = p;
			s.proxy = proxy;
			s.name = std::string(detect::name(p));
			specs.push_back(s);
		}
		return specs;
	}

}  // namespace oneport::server
