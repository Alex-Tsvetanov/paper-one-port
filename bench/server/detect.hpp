// The detection table of oneport: pure, constexpr, and free of I/O.
//
// hypotheses.md, section 1 ("Detection", the matcher table, the budgets) and design/proposal.md
// I6 to I10 and I14. Every matcher is a constexpr function over the bytes received so far, and the
// table, its first-byte array and its buckets are computed at compile time. The checks of I7 over
// the sample corpus are static_asserts in detect_corpus.hpp. The PROXY v1 and v2 parser is here
// too; it runs before the table, on a configured listener only (I9).
//
// No function here keeps state between calls: a connection keeps its bytes (in its buffer in
// replay mode, in the socket's queue in peek mode) and the table is run on all of them each time
// more arrive. So feeding a signature in any split gives the same decision as one write.
#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>
#include <string_view>
#include <utility>

namespace oneport::detect
{

	using Bytes = std::span<const std::byte>;

	// ---- Frozen constants (hypotheses.md, section 1) ----

	/// B_dec: the most bytes after any PROXY header that a connection may need while undecided.
	inline constexpr std::uint32_t kBDec = 24;
	/// B_CH: the most bytes of a ClientHello reassembled in pass-through (relay mode, M2).
	inline constexpr std::uint32_t kBCh = 16384;
	/// The longest PROXY v2 header accepted, the size both formats were designed to fit (survey 2.4).
	inline constexpr std::uint32_t kProxyV2Max = 536;
	/// The longest PROXY v1 line, CRLF included (survey 2.4).
	inline constexpr std::uint32_t kProxyV1Max = 107;
	/// The largest TLS record length, 2^14 (RFC 8446 s5.1).
	inline constexpr std::uint32_t kTlsRecordMax = 16384;

	/// The classes a connection can end in. The first five have matchers, in the order of the
	/// frozen table; SMTP is reached only as a fallback (hypotheses.md, section 1).
	enum class Proto : std::uint8_t
	{
		tls,
		h2c,
		http1,
		ssh,
		mqtt,
		smtp,
	};
	inline constexpr std::size_t kMatchers = 5;
	inline constexpr std::size_t kProtos = 6;

	constexpr std::string_view name(Proto p) noexcept
	{
		switch (p)
		{
			case Proto::tls: return "TLS";
			case Proto::h2c: return "h2c";
			case Proto::http1: return "HTTP/1.1";
			case Proto::ssh: return "SSH";
			case Proto::mqtt: return "MQTT";
			case Proto::smtp: return "SMTP";
		}
		return "?";
	}

	constexpr std::uint8_t u8(std::byte b) noexcept { return std::to_integer<std::uint8_t>(b); }

	// ---- One matcher's answer ----

	enum class Verdict : std::uint8_t
	{
		yes,   // decided: the bytes are this protocol
		no,    // ruled out
		more,  // not yet decided
	};

	/// `at` depends on the verdict:
	///   yes   the matcher decided after `at` bytes (its decision length);
	///   no    the at-th byte (index at - 1) ruled the matcher out;
	///   more  the fewest bytes in all with which the matcher could still say yes. This is "the
	///         number of bytes still needed" of proposal I6, counted from the start; peek mode sets
	///         SO_RCVLOWAT to it (I11).
	struct Match
	{
		Verdict verdict;
		std::uint32_t at;
		friend constexpr bool operator==(const Match&, const Match&) = default;
	};

	constexpr Match yes(std::uint32_t at) noexcept { return {Verdict::yes, at}; }
	constexpr Match no(std::uint32_t at) noexcept { return {Verdict::no, at}; }
	constexpr Match more(std::uint32_t at) noexcept { return {Verdict::more, at}; }

	// ---- The matchers (hypotheses.md, section 1; proposal I8) ----

	/// TLS: byte 0 = 0x16; byte 1 = 0x03; byte 2 any (RFC 8446 s5.1); a record length of at most
	/// 2^14; byte 5 = 0x01, client_hello. Decides at 6 bytes.
	constexpr Match match_tls(Bytes b) noexcept
	{
		constexpr std::uint32_t kNeed = 6;
		const std::size_t n = b.size();
		if (n >= 1 && u8(b[0]) != 0x16) return no(1);
		if (n >= 2 && u8(b[1]) != 0x03) return no(2);
		// Byte 2, the minor record version, may be anything.
		// Bytes 3 and 4: the record length, big-endian, at most 0x4000. A high byte above 0x40
		// already exceeds it, whatever byte 4 is.
		if (n >= 4 && u8(b[3]) > 0x40) return no(4);
		if (n >= 5 && ((static_cast<std::uint32_t>(u8(b[3])) << 8) | u8(b[4])) > kTlsRecordMax) return no(5);
		if (n >= 6 && u8(b[5]) != 0x01) return no(6);
		return n >= kNeed ? yes(kNeed) : more(kNeed);
	}

	/// The client connection preface of RFC 9113 s3.4.
	inline constexpr std::string_view kH2Preface{"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n", 24};

	/// h2c: the 24-byte preface exactly. Decides at 24 bytes, or at the first byte that differs.
	constexpr Match match_h2c(Bytes b) noexcept
	{
		const std::size_t n = std::min<std::size_t>(b.size(), kH2Preface.size());
		for (std::size_t i = 0; i < n; ++i)
		{
			if (u8(b[i]) != static_cast<std::uint8_t>(kH2Preface[i])) return no(static_cast<std::uint32_t>(i + 1));
		}
		constexpr auto kNeed = static_cast<std::uint32_t>(kH2Preface.size());
		return b.size() >= kNeed ? yes(kNeed) : more(kNeed);
	}

	/// The nine methods: RFC 9110 s9.1 and PATCH (RFC 5789). A compile-time constant (proposal I8).
	inline constexpr std::array<std::string_view, 9> kMethods{"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"};

	/// HTTP/1.1: at most one leading CRLF (RFC 9112 s2.2), then one of the nine methods, then one
	/// SP. Decides at 4 to 10 bytes. That the SP is the only one, the strict reading of ambiguity 9,
	/// is checked by the HTTP/1.1 handler on the byte after it, in both modes (proposal I26).
	constexpr Match match_http1(Bytes b) noexcept
	{
		std::uint32_t off = 0;
		if (!b.empty() && u8(b[0]) == '\r')
		{
			if (b.size() < 2) return more(2 + 4);
			if (u8(b[1]) != '\n') return no(2);
			off = 2;
		}
		const Bytes r = b.subspan(off);
		std::uint32_t least_more = std::numeric_limits<std::uint32_t>::max();
		std::uint32_t last_no = 0;  // where the last method still possible was ruled out
		for (const std::string_view m : kMethods)
		{
			const std::size_t len = m.size() + 1;  // the method and its SP
			bool agrees = true;
			std::size_t i = 0;
			for (; i < r.size() && i < len; ++i)
			{
				const char want = i < m.size() ? m[i] : ' ';
				if (u8(r[i]) != static_cast<std::uint8_t>(want))
				{
					agrees = false;
					break;
				}
			}
			if (!agrees)
			{
				last_no = std::max(last_no, static_cast<std::uint32_t>(off + i + 1));
				continue;
			}
			if (r.size() >= len) return yes(static_cast<std::uint32_t>(off + len));
			least_more = std::min(least_more, static_cast<std::uint32_t>(off + len));
		}
		if (least_more != std::numeric_limits<std::uint32_t>::max()) return more(least_more);
		return no(last_no);
	}

	/// SSH: `SSH-` (RFC 4253 s4.2). Decides at 4 bytes.
	constexpr Match match_ssh(Bytes b) noexcept
	{
		constexpr std::string_view kPrefix = "SSH-";
		const std::size_t n = std::min(b.size(), kPrefix.size());
		for (std::size_t i = 0; i < n; ++i)
		{
			if (u8(b[i]) != static_cast<std::uint8_t>(kPrefix[i])) return no(static_cast<std::uint32_t>(i + 1));
		}
		constexpr auto kNeed = static_cast<std::uint32_t>(kPrefix.size());
		return b.size() >= kNeed ? yes(kNeed) : more(kNeed);
	}

	/// MQTT: byte 0 = 0x10 (CONNECT); a Remaining Length of 1 to 4 bytes; then `00 04 4D 51 54 54`
	/// ("MQTT") and level 4 or 5 (MQTT 3.1.1 s3.1.2.1, s3.1.2.2; MQTT 5.0 s3.1.2.2). Decides at 9 to
	/// 12 bytes. The Remaining Length is decoded only for its length, as the frozen text states it;
	/// its value is not checked.
	constexpr Match match_mqtt(Bytes b) noexcept
	{
		const std::size_t n = b.size();
		if (n >= 1 && u8(b[0]) != 0x10) return no(1);
		std::uint32_t rl = 0;  // bytes of the Remaining Length seen
		bool rl_done = false;
		for (std::size_t i = 1; i < n && i <= 4; ++i)
		{
			++rl;
			if ((u8(b[i]) & 0x80) == 0)
			{
				rl_done = true;
				break;
			}
			if (i == 4) return no(5);  // a fifth length byte would be needed
		}
		if (!rl_done) return more(1 + (rl + 1) + 7);
		constexpr std::array<std::uint8_t, 6> kName{0x00, 0x04, 'M', 'Q', 'T', 'T'};
		const std::uint32_t name_at = 1 + rl;
		for (std::uint32_t j = 0; j < kName.size(); ++j)
		{
			const std::uint32_t i = name_at + j;
			if (i >= n) return more(name_at + 7);
			if (u8(b[i]) != kName[j]) return no(i + 1);
		}
		const std::uint32_t level_at = name_at + 6;
		if (level_at >= n) return more(level_at + 1);
		const std::uint8_t level = u8(b[level_at]);
		if (level != 4 && level != 5) return no(level_at + 1);
		return yes(level_at + 1);
	}

	// ---- The table ----

	/// A set of byte values, 256 bits.
	struct ByteSet
	{
		std::array<std::uint64_t, 4> words{};
		constexpr bool has(std::uint8_t v) const noexcept { return ((words[v >> 6] >> (v & 63)) & 1) != 0; }
		constexpr void add(std::uint8_t v) noexcept { words[v >> 6] |= std::uint64_t{1} << (v & 63); }
		constexpr bool empty() const noexcept { return words[0] == 0 && words[1] == 0 && words[2] == 0 && words[3] == 0; }
		friend constexpr bool operator==(const ByteSet&, const ByteSet&) = default;
	};

	using MatchFn = Match (*)(Bytes) noexcept;

	/// One matcher descriptor (proposal I6). `first` is derived from `match` (every byte value
	/// that one byte alone does not rule out), so the two cannot disagree. `need_min` and
	/// `need_max` are the fewest and the most bytes it needs to say yes.
	struct Matcher
	{
		Proto proto;
		MatchFn match;
		std::uint32_t need_min;
		std::uint32_t need_max;
		ByteSet first;
	};

	consteval ByteSet first_bytes(MatchFn f)
	{
		ByteSet s;
		for (unsigned v = 0; v < 256; ++v)
		{
			const std::array<std::byte, 1> one{static_cast<std::byte>(v)};
			if (f(one).verdict != Verdict::no) s.add(static_cast<std::uint8_t>(v));
		}
		return s;
	}

	consteval Matcher make(Proto p, MatchFn f, std::uint32_t need_min, std::uint32_t need_max)
	{
		return Matcher{p, f, need_min, need_max, first_bytes(f)};
	}

	/// The frozen table, in its order (hypotheses.md, section 1).
	inline constexpr std::array<Matcher, kMatchers> kTable{
		make(Proto::tls, &match_tls, 6, 6),
		make(Proto::h2c, &match_h2c, 24, 24),
		make(Proto::http1, &match_http1, 4, 10),
		make(Proto::ssh, &match_ssh, 4, 4),
		make(Proto::mqtt, &match_mqtt, 9, 12),
	};

	/// One first-byte bucket: the candidate matchers, as indices into kTable, smaller `need_max`
	/// first ("for speed only", proposal I7), the table's order breaking ties.
	struct Bucket
	{
		std::array<std::uint8_t, kMatchers> index{};
		std::uint8_t count = 0;
	};

	consteval std::array<Bucket, 256> make_buckets()
	{
		std::array<Bucket, 256> buckets{};
		for (unsigned v = 0; v < 256; ++v)
		{
			Bucket& b = buckets[v];
			for (std::uint8_t m = 0; m < kMatchers; ++m)
			{
				if (kTable[m].first.has(static_cast<std::uint8_t>(v))) b.index[b.count++] = m;
			}
			// Insertion sort by need_max; stable, so the table's order breaks ties.
			for (std::uint8_t i = 1; i < b.count; ++i)
			{
				for (std::uint8_t j = i; j > 0 && kTable[b.index[j]].need_max < kTable[b.index[j - 1]].need_max; --j)
				{
					std::swap(b.index[j], b.index[j - 1]);
				}
			}
		}
		return buckets;
	}

	/// The 256-entry array from the first byte to its candidate matchers (proposal I7).
	inline constexpr std::array<Bucket, 256> kBuckets = make_buckets();

	// ---- Classification (proposal I9 steps 2 and 3) ----

	enum class Outcome : std::uint8_t
	{
		classified,
		rejected,
		more,
	};

	/// `at`: for classified, the decision length; for rejected, the byte (1-based) that ruled out
	/// the last candidate; for more, the fewest bytes in all with which some candidate could still
	/// say yes (the low-water mark of peek mode).
	struct Decision
	{
		Outcome outcome;
		Proto proto;
		std::uint32_t at;
		friend constexpr bool operator==(const Decision&, const Decision&) = default;
	};

	enum class Order : std::uint8_t
	{
		bucket,    // the server's order
		reversed,  // the bucket reversed: the compile-time check that order cannot change a decision
	};

	/// Classifies the application bytes received so far (after any PROXY header). An empty
	/// candidate set rejects at once (S6 e). Otherwise the candidates run until one says yes; if
	/// none does, the bytes are undecided while any candidate says more, and rejected when all say
	/// no. Budgets are checked by the caller (the server), on the bytes it holds.
	template <Order order = Order::bucket>
	constexpr Decision classify(Bytes b) noexcept
	{
		if (b.empty()) return {Outcome::more, Proto::http1, 1};
		const Bucket& bucket = kBuckets[u8(b[0])];
		if (bucket.count == 0) return {Outcome::rejected, Proto::http1, 1};
		std::uint32_t least_more = std::numeric_limits<std::uint32_t>::max();
		std::uint32_t last_no = 0;
		for (std::uint8_t k = 0; k < bucket.count; ++k)
		{
			const std::uint8_t idx = order == Order::bucket ? bucket.index[k] : bucket.index[bucket.count - 1 - k];
			const Matcher& m = kTable[idx];
			const Match r = m.match(b);
			if (r.verdict == Verdict::yes) return {Outcome::classified, m.proto, r.at};
			if (r.verdict == Verdict::more) least_more = std::min(least_more, r.at);
			if (r.verdict == Verdict::no) last_no = std::max(last_no, r.at);
		}
		if (least_more != std::numeric_limits<std::uint32_t>::max()) return {Outcome::more, Proto::http1, least_more};
		return {Outcome::rejected, Proto::http1, last_no};
	}

	// ---- PROXY v1 and v2 (proposal I9 step 1; survey 2.4) ----

	enum class ProxyVerdict : std::uint8_t
	{
		done,  // a complete, valid header of `at` bytes
		no,    // close the connection
		more,  // a partial header: at least `at` bytes are needed in all
	};

	enum class ProxyReason : std::uint8_t
	{
		none,
		prefix,     // the bytes cannot start a header of either version (HC11)
		too_long,   // a v2 header longer than kProxyV2Max, or a v1 line longer than kProxyV1Max (HC14)
		malformed,  // the header started but is not valid
	};

	enum class ProxyFamily : std::uint8_t
	{
		none,    // no address recorded
		inet,    // TCP or UDP over IPv4
		inet6,   // TCP or UDP over IPv6
		unix_,   // AF_UNIX: no address the server records
		unspec,  // v1 UNKNOWN, v2 AF_UNSPEC: use the real endpoints
		local,   // v2 LOCAL command: use the real endpoints
	};

	/// The source address a header carries (HC9). For inet only the first 4 bytes of `addr` count.
	struct ProxySource
	{
		ProxyFamily family = ProxyFamily::none;
		std::array<std::uint8_t, 16> addr{};
		std::uint16_t port = 0;
		friend constexpr bool operator==(const ProxySource&, const ProxySource&) = default;
	};

	struct ProxyResult
	{
		ProxyVerdict verdict;
		std::uint32_t at;
		ProxyReason reason = ProxyReason::none;
		std::uint8_t version = 0;
		ProxySource source{};
	};

	/// The 12-byte v2 signature (survey 2.4).
	inline constexpr std::array<std::uint8_t, 12> kProxyV2Sig{0x0D, 0x0A, 0x0D, 0x0A, 0x00, 0x0D, 0x0A, 0x51, 0x55, 0x49, 0x54, 0x0A};
	/// The v1 prefix.
	inline constexpr std::string_view kProxyV1Prefix = "PROXY";

	namespace proxy_detail
	{

		constexpr ProxyResult reject(std::uint32_t at, ProxyReason why) noexcept { return {ProxyVerdict::no, at, why}; }
		constexpr ProxyResult need(std::uint32_t at) noexcept { return {ProxyVerdict::more, at}; }

		constexpr bool is_digit(std::uint8_t c) noexcept { return c >= '0' && c <= '9'; }
		constexpr int hex_value(std::uint8_t c) noexcept
		{
			if (c >= '0' && c <= '9') return c - '0';
			if (c >= 'a' && c <= 'f') return c - 'a' + 10;
			if (c >= 'A' && c <= 'F') return c - 'A' + 10;
			return -1;
		}

		/// A decimal number of 1 to `max_digits` digits, no leading zero unless it is "0".
		constexpr bool parse_decimal(Bytes s, std::uint32_t max_value, std::uint32_t& out) noexcept
		{
			if (s.empty() || s.size() > 5) return false;
			if (s.size() > 1 && u8(s[0]) == '0') return false;
			std::uint32_t v = 0;
			for (const std::byte c : s)
			{
				if (!is_digit(u8(c))) return false;
				v = v * 10 + (u8(c) - '0');
			}
			if (v > max_value) return false;
			out = v;
			return true;
		}

		/// Dotted decimal IPv4, four octets, no leading zeros.
		constexpr bool parse_ipv4(Bytes s, std::array<std::uint8_t, 16>& out) noexcept
		{
			std::size_t start = 0;
			for (int octet = 0; octet < 4; ++octet)
			{
				std::size_t end = start;
				while (end < s.size() && u8(s[end]) != '.') ++end;
				if ((octet < 3) != (end < s.size())) return false;
				std::uint32_t v = 0;
				if (end - start > 3 || !parse_decimal(s.subspan(start, end - start), 255, v)) return false;
				out[static_cast<std::size_t>(octet)] = static_cast<std::uint8_t>(v);
				start = end + 1;
			}
			return true;
		}

		/// IPv6 text: eight groups of 1 to 4 hex digits, or fewer with one "::".
		constexpr bool parse_ipv6(Bytes s, std::array<std::uint8_t, 16>& out) noexcept
		{
			std::array<std::uint16_t, 8> head{};
			std::array<std::uint16_t, 8> tail{};
			std::size_t nhead = 0;
			std::size_t ntail = 0;
			bool gap = false;
			std::size_t i = 0;
			if (s.size() >= 2 && u8(s[0]) == ':' && u8(s[1]) == ':')
			{
				gap = true;
				i = 2;
			}
			else if (!s.empty() && u8(s[0]) == ':')
			{
				return false;
			}
			while (i < s.size())
			{
				std::uint32_t v = 0;
				std::size_t digits = 0;
				while (i < s.size() && hex_value(u8(s[i])) >= 0)
				{
					if (++digits > 4) return false;
					v = v * 16 + static_cast<std::uint32_t>(hex_value(u8(s[i])));
					++i;
				}
				if (digits == 0) return false;
				if (gap)
				{
					if (ntail == 8) return false;
					tail[ntail++] = static_cast<std::uint16_t>(v);
				}
				else
				{
					if (nhead == 8) return false;
					head[nhead++] = static_cast<std::uint16_t>(v);
				}
				if (i == s.size()) break;
				if (u8(s[i]) != ':') return false;
				++i;
				if (i < s.size() && u8(s[i]) == ':')
				{
					if (gap) return false;
					gap = true;
					++i;
					if (i == s.size()) break;
				}
				else if (i == s.size())
				{
					return false;  // a trailing single colon
				}
			}
			if (gap ? nhead + ntail > 7 : nhead != 8) return false;
			std::array<std::uint16_t, 8> g{};
			for (std::size_t k = 0; k < nhead; ++k) g[k] = head[k];
			for (std::size_t k = 0; k < ntail; ++k) g[8 - ntail + k] = tail[k];
			for (std::size_t k = 0; k < 8; ++k)
			{
				out[2 * k] = static_cast<std::uint8_t>(g[k] >> 8);
				out[2 * k + 1] = static_cast<std::uint8_t>(g[k] & 0xFF);
			}
			return true;
		}

		constexpr bool equals(Bytes s, std::string_view t) noexcept
		{
			if (s.size() != t.size()) return false;
			for (std::size_t i = 0; i < s.size(); ++i)
			{
				if (u8(s[i]) != static_cast<std::uint8_t>(t[i])) return false;
			}
			return true;
		}

		/// v1: "PROXY" SP ("TCP4" | "TCP6") SP src SP dst SP sport SP dport CRLF, or "PROXY UNKNOWN"
		/// and anything up to CRLF. At most kProxyV1Max bytes with the CRLF.
		constexpr ProxyResult parse_v1(Bytes b) noexcept
		{
			const std::size_t n = b.size();
			for (std::size_t i = 0; i < std::min<std::size_t>(n, kProxyV1Prefix.size()); ++i)
			{
				if (u8(b[i]) != static_cast<std::uint8_t>(kProxyV1Prefix[i])) return reject(static_cast<std::uint32_t>(i + 1), ProxyReason::prefix);
			}
			if (n < 8) return need(8);  // v1 needs 8 bytes with the first 5 equal to "PROXY"
			if (u8(b[5]) != ' ') return reject(6, ProxyReason::malformed);
			// The line: printable ASCII up to CR LF.
			std::size_t cr = 0;
			for (std::size_t i = 6; i < n && i < kProxyV1Max; ++i)
			{
				const std::uint8_t c = u8(b[i]);
				if (c == '\r')
				{
					cr = i;
					break;
				}
				if (c < 0x20 || c > 0x7E) return reject(static_cast<std::uint32_t>(i + 1), ProxyReason::malformed);
			}
			if (cr == 0)
			{
				if (n >= kProxyV1Max) return reject(kProxyV1Max, ProxyReason::too_long);
				return need(static_cast<std::uint32_t>(n + 1));
			}
			if (cr + 1 >= kProxyV1Max) return reject(kProxyV1Max, ProxyReason::too_long);
			if (cr + 1 >= n) return need(static_cast<std::uint32_t>(cr + 2));
			if (u8(b[cr + 1]) != '\n') return reject(static_cast<std::uint32_t>(cr + 2), ProxyReason::malformed);
			const auto len = static_cast<std::uint32_t>(cr + 2);
			// The fields between "PROXY " and CR, separated by single spaces.
			std::array<Bytes, 6> field{};
			std::size_t nfield = 0;
			std::size_t start = 6;
			for (std::size_t i = 6; i <= cr; ++i)
			{
				if (i == cr || u8(b[i]) == ' ')
				{
					if (nfield == field.size()) return reject(len, ProxyReason::malformed);
					field[nfield++] = b.subspan(start, i - start);
					start = i + 1;
					if (nfield == 1 && equals(field[0], "UNKNOWN"))
					{
						// The receiver ignores everything up to the CRLF (survey 2.4, the spec's v1).
						ProxyResult r{ProxyVerdict::done, len, ProxyReason::none, 1};
						r.source.family = ProxyFamily::unspec;
						return r;
					}
				}
			}
			if (nfield != 5) return reject(len, ProxyReason::malformed);
			ProxyResult r{ProxyVerdict::done, len, ProxyReason::none, 1};
			std::array<std::uint8_t, 16> dst{};
			std::uint32_t sport = 0;
			std::uint32_t dport = 0;
			if (equals(field[0], "TCP4"))
			{
				r.source.family = ProxyFamily::inet;
				if (!parse_ipv4(field[1], r.source.addr) || !parse_ipv4(field[2], dst)) return reject(len, ProxyReason::malformed);
			}
			else if (equals(field[0], "TCP6"))
			{
				r.source.family = ProxyFamily::inet6;
				if (!parse_ipv6(field[1], r.source.addr) || !parse_ipv6(field[2], dst)) return reject(len, ProxyReason::malformed);
			}
			else
			{
				return reject(len, ProxyReason::malformed);
			}
			if (!parse_decimal(field[3], 65535, sport) || !parse_decimal(field[4], 65535, dport)) return reject(len, ProxyReason::malformed);
			r.source.port = static_cast<std::uint16_t>(sport);
			return r;
		}

		/// v2: the signature, version 2 with command LOCAL or PROXY, the family, the length, the
		/// address block and any TLVs. At most kProxyV2Max bytes in all.
		constexpr ProxyResult parse_v2(Bytes b) noexcept
		{
			const std::size_t n = b.size();
			for (std::size_t i = 0; i < std::min<std::size_t>(n, kProxyV2Sig.size()); ++i)
			{
				if (u8(b[i]) != kProxyV2Sig[i]) return reject(static_cast<std::uint32_t>(i + 1), ProxyReason::prefix);
			}
			if (n >= 13)
			{
				const std::uint8_t ver_cmd = u8(b[12]);
				if ((ver_cmd >> 4) != 0x2) return reject(13, ProxyReason::prefix);  // the 13th byte must match: version 2
				if ((ver_cmd & 0x0F) > 0x1) return reject(13, ProxyReason::malformed);
			}
			if (n < 16) return need(16);  // v2 needs 16 bytes with the first 13 matching
			const std::uint8_t cmd = u8(b[12]) & 0x0F;
			const std::uint8_t fam = u8(b[13]);
			std::uint32_t addr_len = 0;
			switch (fam)
			{
				case 0x00: addr_len = 0; break;                // AF_UNSPEC
				case 0x11: case 0x12: addr_len = 12; break;    // IPv4, stream or datagram
				case 0x21: case 0x22: addr_len = 36; break;    // IPv6
				case 0x31: case 0x32: addr_len = 216; break;   // AF_UNIX
				default: return reject(14, ProxyReason::malformed);
			}
			const std::uint32_t len = (static_cast<std::uint32_t>(u8(b[14])) << 8) | u8(b[15]);
			const std::uint32_t total = 16 + len;
			if (total > kProxyV2Max) return reject(16, ProxyReason::too_long);
			if (len < addr_len) return reject(16, ProxyReason::malformed);
			if (n < total) return need(total);
			if (fam != 0x00)
			{
				// TLVs after the address block: type (1), length (2), value; each must fit exactly.
				std::uint32_t p = 16 + addr_len;
				while (p < total)
				{
					if (p + 3 > total) return reject(total, ProxyReason::malformed);
					const std::uint32_t tl = (static_cast<std::uint32_t>(u8(b[p + 1])) << 8) | u8(b[p + 2]);
					if (p + 3 + tl > total) return reject(total, ProxyReason::malformed);
					p += 3 + tl;
				}
			}
			ProxyResult r{ProxyVerdict::done, total, ProxyReason::none, 2};
			if (cmd == 0x0)
			{
				r.source.family = ProxyFamily::local;
				return r;
			}
			switch (fam >> 4)
			{
				case 0x1:
					r.source.family = ProxyFamily::inet;
					for (std::size_t k = 0; k < 4; ++k) r.source.addr[k] = u8(b[16 + k]);
					r.source.port = static_cast<std::uint16_t>((u8(b[24]) << 8) | u8(b[25]));
					break;
				case 0x2:
					r.source.family = ProxyFamily::inet6;
					for (std::size_t k = 0; k < 16; ++k) r.source.addr[k] = u8(b[16 + k]);
					r.source.port = static_cast<std::uint16_t>((u8(b[48]) << 8) | u8(b[49]));
					break;
				case 0x3: r.source.family = ProxyFamily::unix_; break;
				default: r.source.family = ProxyFamily::unspec; break;
			}
			return r;
		}

	}  // namespace proxy_detail

	/// The PROXY header on a configured listener, by the strict rule of survey 2.4: v2 needs 16
	/// bytes with the first 13 matching, v1 needs 8 with the first 5 equal to "PROXY"; a prefix
	/// that cannot match closes the connection; a v2 header longer than kProxyV2Max is rejected
	/// as soon as its length field arrives. On done, `at` is the header's length, which the
	/// caller consumes exactly.
	constexpr ProxyResult parse_proxy(Bytes b) noexcept
	{
		if (b.empty()) return proxy_detail::need(8);
		const std::uint8_t c = u8(b[0]);
		if (c == kProxyV2Sig[0]) return proxy_detail::parse_v2(b);
		if (c == static_cast<std::uint8_t>(kProxyV1Prefix[0])) return proxy_detail::parse_v1(b);
		return proxy_detail::reject(1, ProxyReason::prefix);
	}

	/// The most bytes a peek must see to decide a PROXY header and then the table: the longest v2
	/// header and B_dec after it. Both are frozen constants.
	inline constexpr std::uint32_t kPeekWindow = kProxyV2Max + kBDec;

}  // namespace oneport::detect
