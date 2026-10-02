// The runtime flags of oneport. One binary, every option of every flag built in: hypotheses.md
// ("Words": mode, detection, dispatch, backend; section 8, rule E: "Both options of each are
// built into the frozen binary as flag values") and design/proposal.md (A1; the flag names
// --mode, --detect, --dispatch and --backend of I1, I11, I16, I17 and I20).
//
// Spelling: each flag and each value has exactly one spelling, case-sensitive, with no alias.
// The values are the frozen names (one-port, dedicated, stub; replay, peek; inproc, relay;
// epoll, io_uring, IOCP). The four arm flags have no default: the pilot runs "two starts of the
// same binary and flags" and an A/B pair differs by the mode alone, so every arm is spelled out.
// Flags that do not apply to a mode or backend are accepted and echoed, so that one flag set
// serves both arms of a cell (dedicated mode ignores --detect, for example).
//
// The mode is read once, by the listener setup (proposal I21). Only this parser, its printer
// and the listener setup may read Config::mode; M1 adds the structural test that checks it.
#pragma once

#include <cstdint>
#include <expected>
#include <optional>
#include <span>
#include <string>
#include <string_view>

namespace oneport
{

	enum class Mode
	{
		one_port,   // one listening socket; detection, then dispatch
		dedicated,  // one listening socket per protocol, consecutive ports, no detection
		stub,       // the backend of M3 and of B3 against the proxies: least work per exchange
	};

	enum class Detect
	{
		replay,  // the first read goes into the handler's buffer (proposal I11)
		peek,    // MSG_PEEK into a per-worker scratch buffer
	};

	enum class Dispatch
	{
		inproc,  // the classified connection stays on its worker (I16)
		relay,   // a loopback connection to the backend chosen by class, Linux only (I17)
	};

	enum class Backend
	{
		epoll,
		io_uring,
		iocp,  // spelled IOCP
	};

	/// Rule E's IOCP receive form: a zero-byte WSARecv then recv into the handler's buffer, or a
	/// WSARecv with the buffer posted at once.
	enum class IocpReceive
	{
		zero_byte,
		posted,
	};

	/// The AcceptEx form on IOCP (hypotheses.md, section 10; proposal I5): AcceptEx with no receive
	/// buffer (dwReceiveDataLength = 0), the default, or with a receive buffer, which completes
	/// only once data arrives and gives the first bytes at accept time. The receive buffer applies
	/// to one-port listeners only and is refused with a fallback (I5). Added in M6a.
	enum class IocpAccept
	{
		no_buffer,
		buffer,
	};

	/// Rule E's relay copy: user-space buffers of RELAY_BUF bytes per direction, or splice.
	enum class RelayCopy
	{
		user_space,
		splice,
	};

	/// The PROXY v1 and v2 prefix, configured per listener and never guessed.
	enum class Proxy
	{
		off,
		on,
	};

	/// The one fallback protocol a listener may name; SSH is the secondary configuration.
	enum class Fallback
	{
		none,
		smtp,  // spelled SMTP
		ssh,   // spelled SSH
	};

	/// The shared listener of I4, or a SO_REUSEPORT group, one socket per worker (secondary).
	enum class Listener
	{
		shared,
		reuseport,
	};

	enum class Platform
	{
		Linux,
		Windows,
	};

#if defined(_WIN32)
	inline constexpr Platform kThisPlatform = Platform::Windows;
#else
	inline constexpr Platform kThisPlatform = Platform::Linux;
#endif

	/// The design value of T_fb, T_dec and T_hdr: 3 s (hypotheses.md, section 1).
	inline constexpr std::int64_t kDesignTimerMs = 3000;

	struct Config
	{
		Mode mode{};
		Detect detect{};
		Dispatch dispatch{};
		Backend backend{};
		IocpReceive iocp_receive = IocpReceive::zero_byte;
		IocpAccept iocp_accept = IocpAccept::no_buffer;
		RelayCopy relay_copy = RelayCopy::user_space;
		Proxy proxy = Proxy::off;
		Fallback fallback = Fallback::none;
		Listener listener = Listener::shared;
		std::uint32_t workers = 1;
		std::optional<std::uint16_t> port;  // the first port; dedicated mode takes consecutive ones
		/// Relay dispatch: the first port of the backend, a server in dedicated or stub mode on
		/// 127.0.0.1 (proposal I17, I18), whose six listeners follow in the order of I20.
		std::optional<std::uint16_t> relay_port;
		std::int64_t t_fb_ms = kDesignTimerMs;
		std::int64_t t_dec_ms = kDesignTimerMs;
		std::int64_t t_hdr_ms = kDesignTimerMs;
	};

	struct Command
	{
		enum Kind
		{
			serve,
			print_config,  // parse, print the whole configuration, exit 0
			help,
		};
		Kind kind = serve;
		Config config;
	};

	/// Parses the arguments after the program name. Returns the command, or why it is refused.
	std::expected<Command, std::string> parse_args(std::span<const std::string_view> args, Platform platform = kThisPlatform);

	/// One "flag value" line per setting, in a fixed order, with the spellings the parser takes.
	std::string describe(const Config& config);

	/// The usage text.
	std::string usage();

	std::string_view token(Mode v);
	std::string_view token(Detect v);
	std::string_view token(Dispatch v);
	std::string_view token(Backend v);

}  // namespace oneport
