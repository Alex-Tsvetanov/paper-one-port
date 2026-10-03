// The listener setup: the one place outside the flag parser that reads Config::mode
// (design/proposal.md I21; the structural test tests/check_mode_readers.cmake enforces it).
// The mode becomes a list of listener roles here, and nothing after this file knows it: a
// one-port listener detects, a dedicated listener sets each connection's class at accept, and
// from then on both run the same code. Stub mode (I18) is the dedicated layout with the stub's
// TLS handler on its TLS port, marked on the listener here.
#include "server.hpp"

#include <string>

namespace oneport::server
{

	std::optional<std::string> not_served(const Config& config)
	{
#if defined(_WIN32)
		if (config.backend != Backend::iocp) return "the epoll and io_uring backends are Linux only";
		if (config.mode == Mode::one_port && config.dispatch == Dispatch::relay) return "relay dispatch is Linux only (hypotheses.md, section 2.1)";
		if (config.workers > 1)
		{
			return "IOCP with more than one worker: proposal I4 shares one completion port among the worker threads, "
			       "which M6a does not build (design/status-m6.md)";
		}
		return std::nullopt;
#else
		if (config.backend == Backend::iocp) return "the IOCP backend is M6 (Windows)";
		return std::nullopt;
#endif
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
		// Dedicated and stub mode: one port per class, in the order of I20.
		const bool stub = config.mode == Mode::stub;
		for (const Proto p : {Proto::http1, Proto::h2c, Proto::tls, Proto::mqtt, Proto::ssh, Proto::smtp})
		{
			ListenerSpec s;
			s.detects = false;
			s.proto = p;
			s.proxy = proxy;
			s.stub = stub;
			s.name = std::string(detect::name(p));
			specs.push_back(s);
		}
		return specs;
	}

}  // namespace oneport::server
