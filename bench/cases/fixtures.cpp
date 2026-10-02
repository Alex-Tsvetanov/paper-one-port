#include "fixtures.hpp"

#include <algorithm>
#include <stdexcept>

namespace oneport::opcase
{

	namespace
	{

		void put8(Bytes& b, unsigned v) { b.push_back(static_cast<std::byte>(v & 0xFF)); }
		void put16(Bytes& b, unsigned v)
		{
			put8(b, v >> 8);
			put8(b, v);
		}
		void put24(Bytes& b, unsigned v)
		{
			put8(b, v >> 16);
			put16(b, v);
		}
		void append(Bytes& b, const Bytes& more) { b.insert(b.end(), more.begin(), more.end()); }

		/// A TLS extension: type, length, body.
		Bytes extension(unsigned type, const Bytes& body)
		{
			Bytes e;
			put16(e, type);
			put16(e, static_cast<unsigned>(body.size()));
			append(e, body);
			return e;
		}

		Bytes record(std::uint8_t minor, const Bytes& fragment)
		{
			Bytes r;
			put8(r, 0x16);
			put8(r, 0x03);
			put8(r, minor);
			put16(r, static_cast<unsigned>(fragment.size()));
			append(r, fragment);
			return r;
		}

		/// The minimal Variable Byte Integer encoding (MQTT 5.0 s1.5.5).
		Bytes varint(std::uint32_t v)
		{
			Bytes b;
			do
			{
				std::uint8_t digit = v % 128;
				v /= 128;
				if (v > 0) digit |= 0x80;
				put8(b, digit);
			} while (v > 0);
			return b;
		}

	}  // namespace

	Bytes text(std::string_view s)
	{
		Bytes b;
		b.reserve(s.size());
		for (const char c : s) b.push_back(static_cast<std::byte>(static_cast<unsigned char>(c)));
		return b;
	}

	Bytes cat(std::initializer_list<Bytes> parts)
	{
		Bytes b;
		for (const Bytes& p : parts) append(b, p);
		return b;
	}

	Bytes slice(const Bytes& b, std::size_t from, std::size_t to)
	{
		to = std::min(to, b.size());
		from = std::min(from, to);
		return Bytes(b.begin() + static_cast<std::ptrdiff_t>(from), b.begin() + static_cast<std::ptrdiff_t>(to));
	}

	Bytes http_get(std::string_view leading)
	{
		return text(std::string(leading) + "GET / HTTP/1.1\r\nHost: oneport.test\r\nConnection: close\r\n\r\n");
	}

	Bytes h2c_opening()
	{
		Bytes b = text(detect::kH2Preface);
		for (const unsigned v : {0x00u, 0x00u, 0x00u, 0x04u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u}) put8(b, v);
		return b;
	}

	Bytes ssh_line(std::string_view comment)
	{
		std::string s = "SSH-2.0-opcase_1.0";
		if (!comment.empty())
		{
			s += ' ';
			s += comment;
		}
		s += "\r\n";
		return text(s);
	}

	Bytes smtp_line(std::string_view line) { return text(std::string(line) + "\r\n"); }

	Bytes client_hello(std::uint8_t record_minor, std::string_view sni, std::size_t split, std::size_t* first_record)
	{
		Bytes body;
		put16(body, 0x0303);                                // legacy_version
		for (unsigned i = 0; i < 32; ++i) put8(body, i);    // random
		put8(body, 32);                                     // legacy_session_id
		for (unsigned i = 0; i < 32; ++i) put8(body, 0x20 + i);
		put16(body, 2);                                     // cipher_suites: TLS_AES_128_GCM_SHA256
		put16(body, 0x1301);
		put8(body, 1);                                      // legacy_compression_methods: null
		put8(body, 0);
		Bytes exts;
		{
			Bytes sn;  // server_name (RFC 6066 s3)
			put16(sn, static_cast<unsigned>(sni.size() + 3));
			put8(sn, 0);
			put16(sn, static_cast<unsigned>(sni.size()));
			append(sn, text(sni));
			append(exts, extension(0x0000, sn));
		}
		append(exts, extension(0x000A, Bytes{std::byte{0}, std::byte{2}, std::byte{0}, std::byte{0x1D}}));   // supported_groups: x25519
		append(exts, extension(0x000D, Bytes{std::byte{0}, std::byte{2}, std::byte{4}, std::byte{3}}));      // signature_algorithms
		append(exts, extension(0x002B, Bytes{std::byte{2}, std::byte{3}, std::byte{4}}));                    // supported_versions: TLS 1.3
		{
			Bytes ks;  // key_share: one X25519 entry; the key bytes are a fixed pattern
			put16(ks, 36);
			put16(ks, 0x001D);
			put16(ks, 32);
			for (unsigned i = 0; i < 32; ++i) put8(ks, 0x40 + i);
			append(exts, extension(0x0033, ks));
		}
		{
			Bytes alpn;  // application_layer_protocol_negotiation (RFC 7301): http/1.1
			put16(alpn, 9);
			put8(alpn, 8);
			append(alpn, text("http/1.1"));
			append(exts, extension(0x0010, alpn));
		}
		put16(body, static_cast<unsigned>(exts.size()));
		append(body, exts);
		Bytes hs;
		put8(hs, 0x01);  // client_hello
		put24(hs, static_cast<unsigned>(body.size()));
		append(hs, body);
		if (split == 0 || split >= hs.size())
		{
			Bytes r = record(record_minor, hs);
			if (first_record != nullptr) *first_record = r.size();
			return r;
		}
		Bytes first = record(record_minor, slice(hs, 0, split));
		if (first_record != nullptr) *first_record = first.size();
		return cat({first, record(record_minor, slice(hs, split, hs.size()))});
	}

	Bytes recorded_client_hello()
	{
		Bytes b;
		const std::string_view hex = recorded_client_hello_hex();
		int hi = -1;
		bool comment = false;
		for (const char ch : hex)
		{
			if (ch == '\n')
			{
				comment = false;
				continue;
			}
			if (comment) continue;
			if (ch == '#')
			{
				comment = true;
				continue;
			}
			int v = -1;
			if (ch >= '0' && ch <= '9') v = ch - '0';
			else if (ch >= 'a' && ch <= 'f') v = ch - 'a' + 10;
			else if (ch >= 'A' && ch <= 'F') v = ch - 'A' + 10;
			else if (ch == ' ' || ch == '\r' || ch == '\t') continue;
			else throw std::runtime_error("recorded_client_hello: a character that is not hex in tests/fixtures/tls/clienthello.hex");
			if (hi < 0)
			{
				hi = v;
				continue;
			}
			put8(b, static_cast<unsigned>(hi * 16 + v));
			hi = -1;
		}
		if (hi >= 0 || b.size() < 5) throw std::runtime_error("recorded_client_hello: tests/fixtures/tls/clienthello.hex holds no whole record");
		return b;
	}

	Bytes with_record_version(Bytes one_record, std::uint8_t minor)
	{
		if (one_record.size() < 5) throw std::invalid_argument("with_record_version: no record header");
		one_record[2] = static_cast<std::byte>(minor);
		return one_record;
	}

	Bytes fragment_client_hello(const Bytes& one_record, std::size_t first, std::size_t* first_record)
	{
		if (one_record.size() < 5) throw std::invalid_argument("fragment_client_hello: no record header");
		const std::size_t len = (std::to_integer<std::size_t>(one_record[3]) << 8) | std::to_integer<std::size_t>(one_record[4]);
		if (len + 5 != one_record.size()) throw std::invalid_argument("fragment_client_hello: not exactly one record");
		if (first == 0 || first >= len) throw std::invalid_argument("fragment_client_hello: the split must lie inside the handshake bytes");
		const auto minor = std::to_integer<std::uint8_t>(one_record[2]);
		const Bytes hs = slice(one_record, 5, one_record.size());
		Bytes a = record(minor, slice(hs, 0, first));
		if (first_record != nullptr) *first_record = a.size();
		return cat({a, record(minor, slice(hs, first, hs.size()))});
	}

	Bytes mqtt_connect(int level, std::uint32_t remaining_length)
	{
		Bytes vh;
		put16(vh, 4);  // the protocol name: its length, then "MQTT"
		append(vh, text("MQTT"));
		put8(vh, static_cast<unsigned>(level));
		put8(vh, 0x02);  // Clean Session / Clean Start
		put16(vh, 60);   // Keep Alive
		if (level == 5) put8(vh, 0);  // no properties
		if (remaining_length < vh.size() + 2) throw std::invalid_argument("mqtt_connect: Remaining Length too small");
		const std::uint32_t rest = remaining_length - static_cast<std::uint32_t>(vh.size()) - 2;
		const std::uint32_t id_len = std::min<std::uint32_t>(rest, 65535);
		Bytes b;
		put8(b, 0x10);
		append(b, varint(remaining_length));
		append(b, vh);
		put16(b, id_len);
		b.insert(b.end(), rest, std::byte{'c'});  // the identifier, then any filler
		return b;
	}

	Bytes mqtt_disconnect() { return Bytes{std::byte{0xE0}, std::byte{0x00}}; }

	Bytes mqtt_isdp()
	{
		Bytes vh;
		put16(vh, 6);    // the protocol name: its length, then "MQIsdp"
		append(vh, text("MQIsdp"));
		put8(vh, 3);     // protocol level 3
		put8(vh, 0x02);
		put16(vh, 60);
		put16(vh, 0);    // empty client identifier
		Bytes b;
		put8(b, 0x10);
		append(b, varint(static_cast<std::uint32_t>(vh.size())));
		append(b, vh);
		return b;
	}

	detect::ProxySource proxy_source()
	{
		detect::ProxySource s;
		s.family = detect::ProxyFamily::inet;
		s.addr[0] = 192;
		s.addr[1] = 0;
		s.addr[2] = 2;
		s.addr[3] = 10;
		s.port = 4711;
		return s;
	}

	Bytes proxy_v2(std::size_t total)
	{
		if (total < 28) throw std::invalid_argument("proxy_v2: a TCP/IPv4 header has at least 28 bytes");
		Bytes b;
		for (const std::uint8_t v : detect::kProxyV2Sig) put8(b, v);
		put8(b, 0x21);  // version 2, PROXY
		put8(b, 0x11);  // TCP over IPv4
		put16(b, static_cast<unsigned>(total - 16));
		for (const unsigned v : {192u, 0u, 2u, 10u, 198u, 51u, 100u, 20u}) put8(b, v);
		put16(b, 4711);
		put16(b, 443);
		std::size_t left = total - 28;
		while (left > 0)
		{
			if (left < 3) throw std::invalid_argument("proxy_v2: 1 or 2 bytes cannot hold a TLV");
			std::size_t value = std::min<std::size_t>(left - 3, 65535);
			if (left - 3 - value > 0 && left - 3 - value < 3) value -= 3;  // leave room for a whole TLV
			put8(b, 0x04);  // PP2_TYPE_NOOP
			put16(b, static_cast<unsigned>(value));
			b.insert(b.end(), value, std::byte{0});
			left -= 3 + value;
		}
		return b;
	}

	Bytes proxy_v2_alpn_authority()
	{
		Bytes tlvs;
		put8(tlvs, 0x01);  // PP2_TYPE_ALPN
		put16(tlvs, 8);
		append(tlvs, text("http/1.1"));
		put8(tlvs, 0x02);  // PP2_TYPE_AUTHORITY
		put16(tlvs, 12);
		append(tlvs, text("oneport.test"));
		Bytes b = proxy_v2(28);
		b[14] = static_cast<std::byte>(((12 + tlvs.size()) >> 8) & 0xFF);
		b[15] = static_cast<std::byte>((12 + tlvs.size()) & 0xFF);
		append(b, tlvs);
		return b;
	}

	Bytes proxy_v1() { return text("PROXY TCP4 192.0.2.10 198.51.100.20 4711 443\r\n"); }

}  // namespace oneport::opcase
