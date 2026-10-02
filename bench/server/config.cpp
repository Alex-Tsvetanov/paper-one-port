#include "config.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <limits>
#include <string>
#include <system_error>
#include <vector>

namespace oneport
{

	namespace
	{

		template <class E>
		struct Choice
		{
			E value;
			std::string_view token;
		};

		constexpr std::array<Choice<Mode>, 3> kModes{{
			{Mode::one_port, "one-port"},
			{Mode::dedicated, "dedicated"},
			{Mode::stub, "stub"},
		}};
		constexpr std::array<Choice<Detect>, 2> kDetects{{{Detect::replay, "replay"}, {Detect::peek, "peek"}}};
		constexpr std::array<Choice<Dispatch>, 2> kDispatches{{{Dispatch::inproc, "inproc"}, {Dispatch::relay, "relay"}}};
		constexpr std::array<Choice<Backend>, 3> kBackends{{
			{Backend::epoll, "epoll"},
			{Backend::io_uring, "io_uring"},
			{Backend::iocp, "IOCP"},
		}};
		constexpr std::array<Choice<IocpReceive>, 2> kIocpReceives{{{IocpReceive::zero_byte, "zero-byte"}, {IocpReceive::posted, "posted"}}};
		constexpr std::array<Choice<RelayCopy>, 2> kRelayCopies{{{RelayCopy::user_space, "user-space"}, {RelayCopy::splice, "splice"}}};
		constexpr std::array<Choice<Proxy>, 2> kProxies{{{Proxy::off, "off"}, {Proxy::on, "on"}}};
		constexpr std::array<Choice<Fallback>, 3> kFallbacks{{
			{Fallback::none, "none"},
			{Fallback::smtp, "SMTP"},
			{Fallback::ssh, "SSH"},
		}};
		constexpr std::array<Choice<Listener>, 2> kListeners{{{Listener::shared, "shared"}, {Listener::reuseport, "reuseport"}}};

		/// The four arm flags, which have no default, in the order an error names them.
		constexpr std::array<std::string_view, 4> kRequired{"--mode", "--detect", "--dispatch", "--backend"};

		/// Every flag that takes a value.
		constexpr std::array<std::string_view, 15> kValueFlags{
			"--mode",     "--detect",  "--dispatch", "--backend",    "--iocp-receive", "--relay-copy", "--proxy",    "--fallback",
			"--listener", "--workers", "--port",     "--relay-port", "--t-fb-ms",      "--t-dec-ms",   "--t-hdr-ms",
		};

		template <class E, std::size_t N>
		std::string_view token_of(const std::array<Choice<E>, N>& table, E value)
		{
			for (const auto& c : table)
			{
				if (c.value == value) return c.token;
			}
			return "?";
		}

		template <class E, std::size_t N>
		std::string list_of(const std::array<Choice<E>, N>& table)
		{
			std::string s;
			for (const auto& c : table)
			{
				if (!s.empty()) s += ", ";
				s += c.token;
			}
			return s;
		}

		/// Sets `out` from `value`, or returns why it cannot.
		template <class E, std::size_t N>
		std::optional<std::string> set_choice(E& out, const std::array<Choice<E>, N>& table, std::string_view flag, std::string_view value)
		{
			for (const auto& c : table)
			{
				if (c.token == value)
				{
					out = c.value;
					return std::nullopt;
				}
			}
			return std::string(flag) + ": '" + std::string(value) + "' is not one of " + list_of(table);
		}

		/// A whole decimal number in [lo, hi], digits only, or nullopt.
		template <class T>
		std::optional<T> whole(std::string_view s, T lo, T hi)
		{
			if (s.empty() || s.front() < '0' || s.front() > '9') return std::nullopt;
			T v{};
			const auto [end, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
			if (ec != std::errc{} || end != s.data() + s.size() || v < lo || v > hi) return std::nullopt;
			return v;
		}

		std::optional<std::string> set_timer(std::int64_t& out, std::string_view flag, std::string_view value)
		{
			const auto v = whole<std::int64_t>(value, 1, std::numeric_limits<std::int64_t>::max());
			if (!v) return std::string(flag) + ": '" + std::string(value) + "' is not a whole number of milliseconds of at least 1";
			out = *v;
			return std::nullopt;
		}

		std::optional<std::string> apply(Config& c, std::string_view flag, std::string_view value)
		{
			if (flag == "--mode") return set_choice(c.mode, kModes, flag, value);
			if (flag == "--detect") return set_choice(c.detect, kDetects, flag, value);
			if (flag == "--dispatch") return set_choice(c.dispatch, kDispatches, flag, value);
			if (flag == "--backend") return set_choice(c.backend, kBackends, flag, value);
			if (flag == "--iocp-receive") return set_choice(c.iocp_receive, kIocpReceives, flag, value);
			if (flag == "--relay-copy") return set_choice(c.relay_copy, kRelayCopies, flag, value);
			if (flag == "--proxy") return set_choice(c.proxy, kProxies, flag, value);
			if (flag == "--fallback") return set_choice(c.fallback, kFallbacks, flag, value);
			if (flag == "--listener") return set_choice(c.listener, kListeners, flag, value);
			if (flag == "--workers")
			{
				const auto v = whole<std::uint32_t>(value, 1, std::numeric_limits<std::uint32_t>::max());
				if (!v) return std::string(flag) + ": '" + std::string(value) + "' is not a whole number of workers of at least 1";
				c.workers = *v;
				return std::nullopt;
			}
			if (flag == "--port" || flag == "--relay-port")
			{
				const auto v = whole<std::uint32_t>(value, 1, 65535);
				if (!v) return std::string(flag) + ": '" + std::string(value) + "' is not a port from 1 to 65535";
				(flag == "--port" ? c.port : c.relay_port) = static_cast<std::uint16_t>(*v);
				return std::nullopt;
			}
			if (flag == "--t-fb-ms") return set_timer(c.t_fb_ms, flag, value);
			if (flag == "--t-dec-ms") return set_timer(c.t_dec_ms, flag, value);
			return set_timer(c.t_hdr_ms, flag, value);  // --t-hdr-ms, the last of kValueFlags
		}

		bool is_value_flag(std::string_view a) { return std::ranges::find(kValueFlags, a) != kValueFlags.end(); }

		/// Combinations the design rules out, whatever the platform.
		std::optional<std::string> check_combination(const Config& c)
		{
			if (c.dispatch == Dispatch::relay && c.backend == Backend::iocp)
			{
				return "--dispatch relay needs epoll or io_uring: the relay is Linux only (proposal I17)";
			}
			if (c.mode == Mode::one_port && c.dispatch == Dispatch::relay && !c.relay_port)
			{
				return "--dispatch relay needs --relay-port, the first port of its backend (a server in dedicated or stub mode)";
			}
			if (c.listener == Listener::reuseport && c.backend == Backend::iocp)
			{
				return "--listener reuseport needs epoll or io_uring: the SO_REUSEPORT group is measured on those "
				       "backends only (hypotheses.md, section 10)";
			}
			return std::nullopt;
		}

		std::optional<std::string> check_platform(const Config& c, Platform platform)
		{
			const bool linux_backend = c.backend == Backend::epoll || c.backend == Backend::io_uring;
			if (platform == Platform::Linux && !linux_backend)
			{
				return "--backend " + std::string(token(c.backend)) + " is not compiled on this platform (Linux compiles epoll and io_uring)";
			}
			if (platform == Platform::Windows && linux_backend)
			{
				return "--backend " + std::string(token(c.backend)) + " is not compiled on this platform (Windows compiles IOCP)";
			}
			return std::nullopt;
		}

	}  // namespace

	std::string_view token(Mode v) { return token_of(kModes, v); }
	std::string_view token(Detect v) { return token_of(kDetects, v); }
	std::string_view token(Dispatch v) { return token_of(kDispatches, v); }
	std::string_view token(Backend v) { return token_of(kBackends, v); }

	std::expected<Command, std::string> parse_args(std::span<const std::string_view> args, Platform platform)
	{
		Command cmd;
		std::vector<std::string_view> seen;
		for (std::size_t i = 0; i < args.size(); ++i)
		{
			const std::string_view a = args[i];
			if (a == "--help")
			{
				cmd.kind = Command::help;
				return cmd;
			}
			if (!a.starts_with("--")) return std::unexpected("unexpected argument '" + std::string(a) + "'");
			if (std::ranges::find(seen, a) != seen.end()) return std::unexpected(std::string(a) + " is given twice");
			if (a == "--print-config")
			{
				seen.push_back(a);
				cmd.kind = Command::print_config;
				continue;
			}
			if (!is_value_flag(a)) return std::unexpected("unknown flag '" + std::string(a) + "'");
			seen.push_back(a);
			if (i + 1 >= args.size() || args[i + 1].starts_with("--")) return std::unexpected(std::string(a) + " needs a value");
			if (auto error = apply(cmd.config, a, args[++i])) return std::unexpected(*error);
		}
		std::string missing;
		for (const std::string_view f : kRequired)
		{
			if (std::ranges::find(seen, f) != seen.end()) continue;
			if (!missing.empty()) missing += ", ";
			missing += f;
		}
		if (!missing.empty()) return std::unexpected("missing " + missing + ": the four arm flags have no default");
		if (auto error = check_combination(cmd.config)) return std::unexpected(*error);
		if (auto error = check_platform(cmd.config, platform)) return std::unexpected(*error);
		return cmd;
	}

	std::string describe(const Config& c)
	{
		std::string s;
		auto line = [&s](std::string_view key, std::string_view value) {
			s += key;
			s += ' ';
			s += value;
			s += '\n';
		};
		line("mode", token(c.mode));
		line("detect", token(c.detect));
		line("dispatch", token(c.dispatch));
		line("backend", token(c.backend));
		line("iocp-receive", token_of(kIocpReceives, c.iocp_receive));
		line("relay-copy", token_of(kRelayCopies, c.relay_copy));
		line("proxy", token_of(kProxies, c.proxy));
		line("fallback", token_of(kFallbacks, c.fallback));
		line("listener", token_of(kListeners, c.listener));
		line("workers", std::to_string(c.workers));
		line("port", c.port ? std::to_string(*c.port) : std::string("unset"));
		line("relay-port", c.relay_port ? std::to_string(*c.relay_port) : std::string("unset"));
		line("t-fb-ms", std::to_string(c.t_fb_ms));
		line("t-dec-ms", std::to_string(c.t_dec_ms));
		line("t-hdr-ms", std::to_string(c.t_hdr_ms));
		return s;
	}

	std::string usage()
	{
		return "usage: oneport --mode M --detect D --dispatch P --backend B [options] [--print-config]\n"
		       "\n"
		       "The four arm flags, required:\n"
		       "  --mode          " + list_of(kModes) + "\n"
		       "  --detect        " + list_of(kDetects) + " (accepted and unused in dedicated and stub mode)\n"
		       "  --dispatch      " + list_of(kDispatches) + " (relay: Linux only)\n"
		       "  --backend       " + list_of(kBackends) + " (Linux: epoll, io_uring; Windows: IOCP)\n"
		       "Options, with their defaults first:\n"
		       "  --iocp-receive  " + list_of(kIocpReceives) + "\n"
		       "  --relay-copy    " + list_of(kRelayCopies) + "\n"
		       "  --proxy         " + list_of(kProxies) + " (PROXY v1 and v2 on every listener)\n"
		       "  --fallback      " + list_of(kFallbacks) + "\n"
		       "  --listener      " + list_of(kListeners) + " (reuseport: epoll and io_uring only)\n"
		       "  --workers       N >= 1, default 1\n"
		       "  --port          1 to 65535, the first listening port\n"
		       "  --relay-port    1 to 65535, the backend's first port; required by one-port mode with\n"
		       "                  --dispatch relay (its six listeners follow in the order HTTP/1.1, h2c,\n"
		       "                  TLS, MQTT, SSH, SMTP)\n"
		       "  --t-fb-ms, --t-dec-ms, --t-hdr-ms\n"
		       "                  T_fb, T_dec, T_hdr in whole milliseconds >= 1, default " + std::to_string(kDesignTimerMs) + "\n"
		       "  --print-config  print the parsed configuration and exit\n"
		       "  --help          print this text and exit\n"
		       "Each flag and value has one spelling, case-sensitive. Served on 127.0.0.1: every mode and\n"
		       "dispatch on epoll and io_uring; IOCP from M6.\n";
	}

}  // namespace oneport
