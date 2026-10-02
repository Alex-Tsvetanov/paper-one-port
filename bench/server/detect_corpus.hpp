// The sample corpus of the detection table and the compile-time checks of proposal I7.
//
// Every sample is a byte string built from the shape a specification gives (the RFC and section
// are named beside it). A sample need only be as long as its matcher's decision; several are the
// first bytes of a longer message. The checks run at compile time (static_assert at the end), so a
// table that broke one of them would not build. The tests run the same corpus again at run time,
// through the same function the server calls, at every split (tests/detect_tests.cpp).
#pragma once

#include "detect.hpp"

#include <array>
#include <cstddef>
#include <string_view>

namespace oneport::detect::corpus
{

	/// The bytes of a string literal, without its terminating NUL.
	template <std::size_t N>
	consteval std::array<std::byte, N - 1> text(const char (&s)[N])
	{
		std::array<std::byte, N - 1> a{};
		for (std::size_t i = 0; i + 1 < N; ++i) a[i] = static_cast<std::byte>(static_cast<unsigned char>(s[i]));
		return a;
	}

	template <class... T>
	consteval std::array<std::byte, sizeof...(T)> hex(T... v)
	{
		return {static_cast<std::byte>(v)...};
	}

	template <std::size_t A, std::size_t B>
	consteval std::array<std::byte, A + B> join(const std::array<std::byte, A>& a, const std::array<std::byte, B>& b)
	{
		std::array<std::byte, A + B> r{};
		for (std::size_t i = 0; i < A; ++i) r[i] = a[i];
		for (std::size_t i = 0; i < B; ++i) r[A + i] = b[i];
		return r;
	}

	struct Sample
	{
		Proto proto;
		Bytes bytes;
		std::string_view source;
	};

	// HTTP/1.1: the request-target forms of RFC 9112 s3.2, each listed method (RFC 9110 s9.3,
	// RFC 5789 s2), and one leading CRLF (RFC 9112 s2.2).
	inline constexpr auto kHttpOrigin = text("GET /where?q=now HTTP/1.1\r\nHost: www.example.org\r\n\r\n");
	inline constexpr auto kHttpAbsolute = text("GET http://www.example.org/pub/WWW/TheProject.html HTTP/1.1\r\n");
	inline constexpr auto kHttpAuthority = text("CONNECT www.example.com:80 HTTP/1.1\r\n");
	inline constexpr auto kHttpAsterisk = text("OPTIONS * HTTP/1.1\r\n");
	inline constexpr auto kHttpHead = text("HEAD / HTTP/1.1\r\n");
	inline constexpr auto kHttpPost = text("POST / HTTP/1.1\r\n");
	inline constexpr auto kHttpPut = text("PUT / HTTP/1.1\r\n");
	inline constexpr auto kHttpDelete = text("DELETE / HTTP/1.1\r\n");
	inline constexpr auto kHttpTrace = text("TRACE / HTTP/1.1\r\n");
	inline constexpr auto kHttpPatch = text("PATCH /file.txt HTTP/1.1\r\n");
	inline constexpr auto kHttpLeadingCrlf = text("\r\nGET / HTTP/1.1\r\n");

	// h2c: the preface (RFC 9113 s3.4) and the empty SETTINGS frame that must follow it (s6.5).
	inline constexpr auto kH2c = join(text("PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"), hex(0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00));

	// TLS: the record header and handshake header of a ClientHello (RFC 8446 s5.1, s4.1.2), with
	// legacy_record_version 0x0301 and 0x0303, and with the largest record length.
	inline constexpr auto kTls0301 = hex(0x16, 0x03, 0x01, 0x00, 0xF4, 0x01, 0x00, 0x00, 0xF0, 0x03, 0x03);
	inline constexpr auto kTls0303 = hex(0x16, 0x03, 0x03, 0x00, 0xF4, 0x01, 0x00, 0x00, 0xF0, 0x03, 0x03);
	inline constexpr auto kTlsMaxRecord = hex(0x16, 0x03, 0x01, 0x40, 0x00, 0x01, 0x00, 0x3F, 0xFC, 0x03, 0x03);

	// SSH: the identification string of RFC 4253 s4.2, with and without a comment.
	inline constexpr auto kSsh = text("SSH-2.0-billsSSH_3.6.3q3\r\n");
	inline constexpr auto kSshComment = text("SSH-2.0-billsSSH_3.6.3q3 a comment\r\n");

	// MQTT: CONNECT (MQTT 3.1.1 s3.1; MQTT 5.0 s3.1) with a Remaining Length of 1 to 4 bytes. The
	// longer ones are the first bytes of the packet.
	inline constexpr auto kMqtt311 = hex(0x10, 0x0C, 0x00, 0x04, 'M', 'Q', 'T', 'T', 0x04, 0x02, 0x00, 0x3C, 0x00, 0x00);
	inline constexpr auto kMqtt5 = hex(0x10, 0x0D, 0x00, 0x04, 'M', 'Q', 'T', 'T', 0x05, 0x02, 0x00, 0x3C, 0x00, 0x00, 0x00);
	inline constexpr auto kMqttRl2 = hex(0x10, 0x80, 0x01, 0x00, 0x04, 'M', 'Q', 'T', 'T', 0x04, 0x02, 0x00);
	inline constexpr auto kMqttRl3 = hex(0x10, 0x80, 0x80, 0x01, 0x00, 0x04, 'M', 'Q', 'T', 'T', 0x05, 0x02);
	inline constexpr auto kMqttRl4 = hex(0x10, 0x80, 0x80, 0x80, 0x01, 0x00, 0x04, 'M', 'Q', 'T', 'T', 0x04);

	inline constexpr std::array kSamples{
		Sample{Proto::http1, kHttpOrigin, "RFC 9112 s3.2.1, origin-form"},
		Sample{Proto::http1, kHttpAbsolute, "RFC 9112 s3.2.2, absolute-form"},
		Sample{Proto::http1, kHttpAuthority, "RFC 9112 s3.2.3, authority-form"},
		Sample{Proto::http1, kHttpAsterisk, "RFC 9112 s3.2.4, asterisk-form"},
		Sample{Proto::http1, kHttpHead, "RFC 9110 s9.3.2"},
		Sample{Proto::http1, kHttpPost, "RFC 9110 s9.3.3"},
		Sample{Proto::http1, kHttpPut, "RFC 9110 s9.3.4"},
		Sample{Proto::http1, kHttpDelete, "RFC 9110 s9.3.5"},
		Sample{Proto::http1, kHttpTrace, "RFC 9110 s9.3.8"},
		Sample{Proto::http1, kHttpPatch, "RFC 5789 s2.1"},
		Sample{Proto::http1, kHttpLeadingCrlf, "RFC 9112 s2.2"},
		Sample{Proto::h2c, kH2c, "RFC 9113 s3.4, s6.5"},
		Sample{Proto::tls, kTls0301, "RFC 8446 s5.1, s4.1.2"},
		Sample{Proto::tls, kTls0303, "RFC 8446 s5.1, s4.1.2"},
		Sample{Proto::tls, kTlsMaxRecord, "RFC 8446 s5.1"},
		Sample{Proto::ssh, kSsh, "RFC 4253 s4.2"},
		Sample{Proto::ssh, kSshComment, "RFC 4253 s4.2"},
		Sample{Proto::mqtt, kMqtt311, "MQTT 3.1.1 s3.1"},
		Sample{Proto::mqtt, kMqtt5, "MQTT 5.0 s3.1"},
		Sample{Proto::mqtt, kMqttRl2, "MQTT 3.1.1 s2.2.3"},
		Sample{Proto::mqtt, kMqttRl3, "MQTT 5.0 s1.5.5"},
		Sample{Proto::mqtt, kMqttRl4, "MQTT 3.1.1 s2.2.3"},
	};

	// PROXY headers (survey 2.4): v1 TCP4, TCP6 and UNKNOWN, v2 PROXY over IPv4 and LOCAL.
	inline constexpr auto kProxyV1Tcp4 = text("PROXY TCP4 192.0.2.10 198.51.100.20 4711 443\r\n");
	inline constexpr auto kProxyV1Tcp6 = text("PROXY TCP6 2001:db8::a 2001:db8::14 4711 443\r\n");
	inline constexpr auto kProxyV1Unknown = text("PROXY UNKNOWN\r\n");
	inline constexpr auto kProxyV2Tcp4 = hex(0x0D, 0x0A, 0x0D, 0x0A, 0x00, 0x0D, 0x0A, 0x51, 0x55, 0x49, 0x54, 0x0A, 0x21, 0x11, 0x00, 0x0C,
	                                         192, 0, 2, 10, 198, 51, 100, 20, 0x12, 0x67, 0x01, 0xBB);
	inline constexpr auto kProxyV2Local = hex(0x0D, 0x0A, 0x0D, 0x0A, 0x00, 0x0D, 0x0A, 0x51, 0x55, 0x49, 0x54, 0x0A, 0x20, 0x00, 0x00, 0x00);

	// ---- The checks of proposal I7 ----

	/// Each protocol's samples are accepted by its matcher, at a length in [need_min, need_max],
	/// and need_max is at most B_dec.
	consteval bool samples_accepted()
	{
		for (const Matcher& m : kTable)
		{
			if (m.need_min > m.need_max || m.need_max > kBDec) return false;
		}
		for (const Sample& s : kSamples)
		{
			const Matcher& m = kTable[static_cast<std::size_t>(s.proto)];
			const Match r = m.match(s.bytes);
			if (r.verdict != Verdict::yes || r.at < m.need_min || r.at > m.need_max) return false;
		}
		return true;
	}

	/// Every prefix of every sample is rejected, or left need-more, by every other matcher: no
	/// matcher accepts any prefix of another protocol's sample.
	consteval bool prefixes_disjoint()
	{
		for (const Sample& s : kSamples)
		{
			for (std::size_t len = 0; len <= s.bytes.size(); ++len)
			{
				for (const Matcher& m : kTable)
				{
					if (m.proto == s.proto) continue;
					if (m.match(s.bytes.first(len)).verdict == Verdict::yes) return false;
				}
			}
		}
		return true;
	}

	/// On every prefix of every sample, classification in the bucket order equals classification
	/// in the reversed order, is never a rejection or another class, is "more" before the
	/// sample's decision length and "classified" from it on; while "more", the low-water mark lies
	/// beyond the bytes held and within B_dec.
	consteval bool order_cannot_change_a_decision()
	{
		for (const Sample& s : kSamples)
		{
			const std::uint32_t at = kTable[static_cast<std::size_t>(s.proto)].match(s.bytes).at;
			for (std::size_t len = 1; len <= s.bytes.size(); ++len)
			{
				const Decision d = classify<Order::bucket>(s.bytes.first(len));
				if (d != classify<Order::reversed>(s.bytes.first(len))) return false;
				if (len < at)
				{
					if (d.outcome != Outcome::more || d.at <= len || d.at > kBDec) return false;
				}
				else if (d.outcome != Outcome::classified || d.proto != s.proto || d.at != at)
				{
					return false;
				}
			}
		}
		return true;
	}

	/// The first-byte sets the matchers imply are the ones the frozen table states.
	consteval bool first_bytes_as_frozen()
	{
		auto set = [](std::initializer_list<int> v) {
			ByteSet s;
			for (const int c : v) s.add(static_cast<std::uint8_t>(c));
			return s;
		};
		return kTable[0].first == set({0x16})                                     // TLS
		       && kTable[1].first == set({'P'})                                   // h2c
		       && kTable[2].first == set({'\r', 'G', 'H', 'P', 'D', 'C', 'O', 'T'})  // HTTP/1.1
		       && kTable[3].first == set({'S'})                                   // SSH
		       && kTable[4].first == set({0x10});                                 // MQTT
	}

	/// Every bucket holds exactly the matchers whose first-byte set has its byte, smaller need_max
	/// first; only 'P' holds two (HTTP/1.1, then h2c).
	consteval bool buckets_consistent()
	{
		for (unsigned v = 0; v < 256; ++v)
		{
			const Bucket& b = kBuckets[v];
			std::size_t expected = 0;
			for (const Matcher& m : kTable) expected += m.first.has(static_cast<std::uint8_t>(v)) ? 1 : 0;
			if (b.count != expected) return false;
			for (std::uint8_t k = 0; k < b.count; ++k)
			{
				if (!kTable[b.index[k]].first.has(static_cast<std::uint8_t>(v))) return false;
				if (k > 0 && kTable[b.index[k]].need_max < kTable[b.index[k - 1]].need_max) return false;
			}
		}
		const Bucket& p = kBuckets['P'];
		return p.count == 2 && kTable[p.index[0]].proto == Proto::http1 && kTable[p.index[1]].proto == Proto::h2c;
	}

	/// HC16's derivation: every complement of a preface byte is at least 0x80, no first-byte set
	/// holds such a byte, and the preface with byte k complemented is rejected at byte k + 1.
	consteval bool hc16_derivation()
	{
		for (const char c : kH2Preface)
		{
			if ((static_cast<std::uint8_t>(c) ^ 0xFF) < 0x80) return false;
		}
		for (unsigned v = 0x80; v < 256; ++v)
		{
			if (kBuckets[v].count != 0) return false;
		}
		for (std::size_t k = 0; k < kH2Preface.size(); ++k)
		{
			std::array<std::byte, 24> p{};
			for (std::size_t i = 0; i < p.size(); ++i) p[i] = static_cast<std::byte>(static_cast<unsigned char>(kH2Preface[i]));
			p[k] = static_cast<std::byte>(u8(p[k]) ^ 0xFF);
			for (std::size_t len = 1; len <= p.size(); ++len)
			{
				const Decision d = classify(Bytes(p).first(len));
				if (len <= k ? d.outcome != Outcome::more : (d.outcome != Outcome::rejected || d.at != k + 1)) return false;
			}
		}
		return true;
	}

	/// A PROXY header is complete exactly at its length, "more" before it, and gives its source.
	consteval bool proxy_samples_parse()
	{
		const ProxyResult v1 = parse_proxy(kProxyV1Tcp4);
		const ProxyResult v1six = parse_proxy(kProxyV1Tcp6);
		const ProxyResult v1unknown = parse_proxy(kProxyV1Unknown);
		const ProxyResult v2 = parse_proxy(kProxyV2Tcp4);
		const ProxyResult local = parse_proxy(kProxyV2Local);
		if (v1.verdict != ProxyVerdict::done || v1.at != kProxyV1Tcp4.size() || v1.version != 1) return false;
		if (v1.source.family != ProxyFamily::inet || v1.source.port != 4711 || v1.source.addr[0] != 192 || v1.source.addr[3] != 10) return false;
		if (v1six.verdict != ProxyVerdict::done || v1six.source.family != ProxyFamily::inet6 || v1six.source.addr[0] != 0x20 ||
		    v1six.source.addr[15] != 0x0A)
			return false;
		if (v1unknown.verdict != ProxyVerdict::done || v1unknown.source.family != ProxyFamily::unspec) return false;
		if (v2.verdict != ProxyVerdict::done || v2.at != kProxyV2Tcp4.size() || v2.version != 2) return false;
		if (v2.source.family != ProxyFamily::inet || v2.source.port != 4711 || v2.source.addr[0] != 192 || v2.source.addr[3] != 10) return false;
		if (local.verdict != ProxyVerdict::done || local.at != 16 || local.source.family != ProxyFamily::local) return false;
		const std::array<Bytes, 5> headers{kProxyV1Tcp4, kProxyV1Tcp6, kProxyV1Unknown, kProxyV2Tcp4, kProxyV2Local};
		for (const Bytes h : headers)
		{
			for (std::size_t len = 0; len < h.size(); ++len)
			{
				const ProxyResult r = parse_proxy(h.first(len));
				if (r.verdict != ProxyVerdict::more || r.at <= len || r.at > h.size()) return false;
			}
		}
		return true;
	}

	/// No sample of the table starts a PROXY header: a PROXY listener closes each of them at once,
	/// within the 13 bytes the v2 decision rule reads (HC11).
	consteval bool samples_are_not_proxy()
	{
		for (const Sample& s : kSamples)
		{
			const ProxyResult r = parse_proxy(s.bytes);
			if (r.verdict != ProxyVerdict::no || r.at > 13) return false;
		}
		return true;
	}

	static_assert(samples_accepted(), "a sample is not accepted by its own matcher, or a need is out of range");
	static_assert(prefixes_disjoint(), "a matcher accepts a prefix of another protocol's sample");
	static_assert(order_cannot_change_a_decision(), "the order of the table changes a decision on the corpus");
	static_assert(first_bytes_as_frozen(), "a first-byte set differs from the frozen table");
	static_assert(buckets_consistent(), "the first-byte buckets are inconsistent");
	static_assert(hc16_derivation(), "HC16's derivation does not hold");
	static_assert(proxy_samples_parse(), "a PROXY sample does not parse as expected");
	static_assert(samples_are_not_proxy(), "a table sample would start a PROXY header");

}  // namespace oneport::detect::corpus
