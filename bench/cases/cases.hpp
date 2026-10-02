// opcase's case table: the 25 hard cases of hypotheses.md, Appendix A, each expanded into the
// scripts that run it, with the frozen expected outcome of each (proposal I33: bench/cases holds
// opcase and the expected-outcome table).
//
// Three frozen values do not exist yet: GAP_SPLIT and G come from the A/A pilot (section 9.2),
// and the timers are 3 s. The suite runs "at short test timeouts" (section 11) with the stand-ins
// of SuiteParams, design choices of M1 recorded in design/status.md; they are not those values.
#pragma once

#include "detect.hpp"
#include "script.hpp"

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace oneport::opcase
{

	/// The suite's stand-ins (design/status.md, "M1 suite parameters").
	struct SuiteParams
	{
		std::chrono::milliseconds t_fb{300};
		std::chrono::milliseconds t_dec{300};
		std::chrono::milliseconds t_hdr{300};
		std::chrono::milliseconds gap_split{10};  // GAP_SPLIT's stand-in (HC2, HC10, HC20)
		std::chrono::milliseconds drip_gap{5};    // HC3: 24 bytes take 120 ms, well inside T_dec
		std::chrono::milliseconds g{100};         // G's stand-in (HC7)
		unsigned replicates = 16;                 // the frozen count (section 5.2, B1)
	};

	/// The one-port listener a variant needs.
	enum class Setup : std::uint8_t
	{
		plain,               // no PROXY, no fallback
		fallback_smtp,       // SMTP fallback
		proxy,               // PROXY required
		proxy_fallback_smtp, // both
	};

	enum class Expect : std::uint8_t
	{
		classified,
		rejected,
		undecided,
		silent,
		fallback,
		proxy_rejected,
		proxy_timeout,
		reset,
	};

	/// What ends the detection.
	enum class When : std::uint8_t
	{
		at_once,  // no timer: the pass that observes the bytes or the half-close
		t_fb,
		t_dec,
		t_hdr,
	};

	/// What the client must receive.
	enum class Reply : std::uint8_t
	{
		dedicated,  // the same bytes as the same script against the dedicated port of `dedicated`
		http200,    // http1::kResponse200, then EOF
		http400,    // http1::kResponse400, then EOF
		closed,     // nothing, then EOF or a reset
		any,        // not checked (the client resets)
	};

	/// How much of the frozen outcome M1 checks.
	enum class Coverage : std::uint8_t
	{
		full,     // all of it
		stub,     // detection and timing; the handler is an M1 stub, so the exchange is pending M2
		partial,  // the detection part only; the rest of the outcome is pending M2 (`pending`)
	};

	struct Variant
	{
		std::string id;  // "HC02.h2c.k05"
		Script script;
		Setup setup = Setup::plain;
		Expect expect = Expect::classified;
		detect::Proto proto = detect::Proto::http1;  // classified, fallback
		When when = When::at_once;
		/// For a timer anchored at the PROXY header: the index of the write that completes it.
		std::optional<std::size_t> header_write;
		Reply reply = Reply::closed;
		detect::Proto dedicated = detect::Proto::http1;
		/// Z2: the HTTP/1.1 grammar in dedicated mode too; the reply on the dedicated HTTP port.
		std::optional<Reply> dedicated_http_reply;
		std::optional<std::uint32_t> at;  // the deciding byte (rejected) or decision length
		std::optional<detect::ProxySource> source;
		std::optional<detect::ProxyReason> proxy_reason;
		Coverage coverage = Coverage::full;
		std::string pending;  // what of the frozen outcome waits for a later milestone
	};

	inline constexpr int kCases = 25;

	/// The frozen case text, shortened (Appendix A).
	std::string_view title(int hc);

	/// The variants of hard case `hc` (1 to 25), in a fixed order.
	std::vector<Variant> variants(int hc, const SuiteParams& p);

	/// The suite's one-port timers for a setup, as server flags see them.
	std::string_view name(Setup s);
	std::string_view name(Expect e);

}  // namespace oneport::opcase
