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
		void append(Bytes& b, const Bytes& more) { b.insert(b.end(), more.begin(), more.end()); }

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
		// SETTINGS, empty (RFC 9113 s6.5).
		for (const unsigned v : {0x00u, 0x00u, 0x00u, 0x04u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u}) put8(b, v);
		// HEADERS on stream 1, END_STREAM and END_HEADERS (s6.2): GET http://oneport.test/ in
		// static-table fields (RFC 7541 Appendix A): :method GET (index 2), :scheme http (6),
		// :path / (4), and :authority (1) with a literal value, without indexing (s6.2.2).
		const Bytes block = cat({Bytes{std::byte{0x82}, std::byte{0x86}, std::byte{0x84}, std::byte{0x01}, std::byte{0x0C}}, text("oneport.test")});
		put8(b, 0);
		put16(b, static_cast<unsigned>(block.size()));
		for (const unsigned v : {0x01u, 0x05u, 0x00u, 0x00u, 0x00u, 0x01u}) put8(b, v);
		append(b, block);
		// GOAWAY (s6.8): last stream 0, NO_ERROR. The client is done; the server still answers
		// stream 1, which the client opened.
		for (const unsigned v : {0x00u, 0x00u, 0x08u, 0x07u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u}) put8(b, v);
		for (int i = 0; i < 8; ++i) put8(b, 0);
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
