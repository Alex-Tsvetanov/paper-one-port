// The ClientHello reader of pass-through (design/proposal.md I17, I22, ambiguity 4 of I10;
// hypotheses.md, section 2.1, "Dispatch"): the handshake bytes of the TLS records that carry a
// ClientHello are reassembled, up to B_CH, and the ClientHello's server name (SNI) and ALPN list
// are read from it. Pure: no I/O, no allocation.
//
// The relay's pass-through routes by it (bench/server/relay.cpp); the tests also check the recorded
// ClientHello and opcase's TLS client with it (tests/clienthello_tests.cpp, handler_tests.cpp).
#pragma once

#include "detect.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace oneport::clienthello
{

	using detect::u8;

	enum class Verdict : std::uint8_t
	{
		yes,   // a whole ClientHello was reassembled
		no,    // not a ClientHello in handshake records, malformed, or longer than B_CH
		more,  // incomplete
	};

	struct Reassembled
	{
		Verdict verdict = Verdict::more;
		std::uint32_t msg_len = 0;  // the handshake message's bytes, its 4-byte header included
		std::uint32_t wire_len = 0; // the record bytes, headers included, up to the record that completed it
		std::uint32_t records = 0;  // the records that carried it
		std::uint32_t need = 0;     // more: the fewest record bytes in all, headers included, with which it can go on
	};

	/// Copies the handshake fragments of the records at the start of `wire` into `out` (at least
	/// B_CH bytes) until a whole ClientHello is there. A record must be whole before it counts.
	constexpr Reassembled reassemble(std::span<const std::byte> wire, std::span<std::byte> out) noexcept
	{
		Reassembled r;
		std::size_t pos = 0;
		std::size_t got = 0;
		const std::size_t cap = out.size() < detect::kBCh ? out.size() : detect::kBCh;
		for (;;)
		{
			if (got >= 4)
			{
				if (u8(out[0]) != 0x01) return {Verdict::no, 0, 0, r.records};
				const std::size_t need = 4 + ((std::size_t{u8(out[1])} << 16) | (std::size_t{u8(out[2])} << 8) | u8(out[3]));
				if (need > cap) return {Verdict::no, 0, 0, r.records};
				if (got >= need) return {Verdict::yes, static_cast<std::uint32_t>(need), static_cast<std::uint32_t>(pos), r.records};
			}
			if (wire.size() - pos < 5)
			{
				r.need = static_cast<std::uint32_t>(pos + 5);
				return r;
			}
			if (u8(wire[pos]) != 0x16 || u8(wire[pos + 1]) != 0x03) return {Verdict::no, 0, 0, r.records};
			const std::size_t len = (std::size_t{u8(wire[pos + 3])} << 8) | u8(wire[pos + 4]);
			if (len == 0 || len > 16384) return {Verdict::no, 0, 0, r.records};  // RFC 8446 s5.1
			if (wire.size() - pos - 5 < len)
			{
				r.need = static_cast<std::uint32_t>(pos + 5 + len);
				return r;
			}
			if (got + len > cap) return {Verdict::no, 0, 0, r.records};
			for (std::size_t i = 0; i < len; ++i) out[got + i] = wire[pos + 5 + i];
			got += len;
			pos += 5 + len;
			++r.records;
		}
	}

	/// Where a field lies in the message.
	struct Field
	{
		std::uint32_t off = 0;
		std::uint32_t len = 0;
		bool present = false;
	};

	struct Hello
	{
		bool ok = false;
		Field random;      // 32 bytes
		Field session_id;  // legacy_session_id's bytes
		Field sni;         // the host_name of server_name
		Field alpn;        // the protocol_name_list's bytes (each name with its length byte)
		Field x25519;      // the X25519 key_exchange bytes of key_share
		std::array<std::uint16_t, 32> exts{};  // extension types, in order
		std::uint8_t n_exts = 0;
	};

	namespace detail
	{
		constexpr std::uint32_t be16(std::span<const std::byte> b, std::size_t i) noexcept { return (std::uint32_t{u8(b[i])} << 8) | u8(b[i + 1]); }
	}  // namespace detail

	/// Reads a whole ClientHello handshake message (type 1, 3-byte length, body).
	constexpr Hello parse(std::span<const std::byte> m) noexcept
	{
		using detail::be16;
		Hello h;
		if (m.size() < 4 || u8(m[0]) != 0x01) return h;
		const std::size_t end = 4 + ((std::size_t{u8(m[1])} << 16) | (std::size_t{u8(m[2])} << 8) | u8(m[3]));
		if (end > m.size()) return h;
		std::size_t p = 4 + 2;  // legacy_version
		if (p + 32 > end) return h;
		h.random = {static_cast<std::uint32_t>(p), 32, true};
		p += 32;
		if (p + 1 > end) return h;
		const std::size_t sid = u8(m[p]);
		if (p + 1 + sid > end) return h;
		h.session_id = {static_cast<std::uint32_t>(p + 1), static_cast<std::uint32_t>(sid), true};
		p += 1 + sid;
		if (p + 2 > end) return h;
		p += 2 + be16(m, p);  // cipher_suites
		if (p + 1 > end) return h;
		p += 1 + u8(m[p]);  // legacy_compression_methods
		if (p + 2 > end) return h;
		const std::size_t ext_end = p + 2 + be16(m, p);
		if (ext_end != end) return h;
		p += 2;
		while (p < ext_end)
		{
			if (p + 4 > ext_end) return h;
			const std::uint32_t type = be16(m, p);
			const std::size_t len = be16(m, p + 2);
			const std::size_t d = p + 4;
			if (d + len > ext_end) return h;
			if (h.n_exts < h.exts.size()) h.exts[h.n_exts++] = static_cast<std::uint16_t>(type);
			if (type == 0 && len >= 5)  // server_name (RFC 6066 s3): list length, name_type 0, length, name
			{
				if (u8(m[d + 2]) != 0) return h;
				const std::size_t n = be16(m, d + 3);
				if (d + 5 + n > d + len) return h;
				h.sni = {static_cast<std::uint32_t>(d + 5), static_cast<std::uint32_t>(n), true};
			}
			else if (type == 16 && len >= 2)  // application_layer_protocol_negotiation (RFC 7301 s3.1)
			{
				const std::size_t n = be16(m, d);
				if (d + 2 + n > d + len) return h;
				h.alpn = {static_cast<std::uint32_t>(d + 2), static_cast<std::uint32_t>(n), true};
			}
			else if (type == 51 && len >= 2)  // key_share (RFC 8446 s4.2.8): client_shares
			{
				const std::size_t list_end = d + 2 + be16(m, d);
				if (list_end > d + len) return h;
				for (std::size_t q = d + 2; q + 4 <= list_end;)
				{
					const std::uint32_t group = be16(m, q);
					const std::size_t k = be16(m, q + 2);
					if (q + 4 + k > list_end) return h;
					if (group == 0x001D) h.x25519 = {static_cast<std::uint32_t>(q + 4), static_cast<std::uint32_t>(k), true};
					q += 4 + k;
				}
			}
			p = d + len;
		}
		h.ok = true;
		return h;
	}

	inline std::string_view text(std::span<const std::byte> m, Field f) noexcept
	{
		return f.present ? std::string_view(reinterpret_cast<const char*>(m.data()) + f.off, f.len) : std::string_view();
	}

}  // namespace oneport::clienthello
