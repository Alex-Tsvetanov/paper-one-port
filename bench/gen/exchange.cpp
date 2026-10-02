// The bytes of opgen's exchanges (WL1, WL3) and the checks of the server's responses
// (exchange.hpp).
#include "exchange.hpp"

#include "fixtures.hpp"

#include <charconv>
#include <cstring>

namespace oneport::opgen::detail
{

	// ---- The exchanges' bytes (WL1, WL3) ----

	/// GET / with Host oneport.test and Connection: close (opcase), or keep-alive.
	const Bytes& http_close()
	{
		static const Bytes b = opcase::http_get();
		return b;
	}
	const Bytes& http_keep()
	{
		static const Bytes b = opcase::text("GET / HTTP/1.1\r\nHost: oneport.test\r\n\r\n");
		return b;
	}

	namespace
	{

		void put8(Bytes& b, unsigned v) { b.push_back(static_cast<std::byte>(v & 0xFF)); }

		/// An h2 frame header (RFC 9113 s4.1).
		void frame(Bytes& b, std::uint32_t len, unsigned type, unsigned flags, std::uint32_t stream)
		{
			put8(b, len >> 16);
			put8(b, len >> 8);
			put8(b, len);
			put8(b, type);
			put8(b, flags);
			put8(b, stream >> 24);
			put8(b, stream >> 16);
			put8(b, stream >> 8);
			put8(b, stream);
		}

	}  // namespace

	/// HEADERS on `stream`, END_STREAM and END_HEADERS: GET http://oneport.test/ in static-table
	/// fields (RFC 7541 Appendix A), :authority as a literal without indexing, as opcase's h2c
	/// opening, so the server's dynamic table never changes.
	Bytes h2_headers(std::uint32_t stream)
	{
		const Bytes block = opcase::cat({Bytes{std::byte{0x82}, std::byte{0x86}, std::byte{0x84}, std::byte{0x01}, std::byte{0x0C}}, opcase::text("oneport.test")});
		Bytes b;
		frame(b, static_cast<std::uint32_t>(block.size()), 0x1, 0x05, stream);
		b.insert(b.end(), block.begin(), block.end());
		return b;
	}

	/// The preface, an empty SETTINGS frame and HEADERS on stream 1 (WL1's first write).
	const Bytes& h2_opening()
	{
		static const Bytes b = [] {
			Bytes o = opcase::text("PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n");
			frame(o, 0, 0x4, 0, 0);
			const Bytes h = h2_headers(1);
			o.insert(o.end(), h.begin(), h.end());
			return o;
		}();
		return b;
	}

	/// GOAWAY, last stream 0, NO_ERROR (s6.8).
	const Bytes& h2_goaway()
	{
		static const Bytes b = [] {
			Bytes o;
			frame(o, 8, 0x7, 0, 0);
			for (int i = 0; i < 8; ++i) put8(o, 0);
			return o;
		}();
		return b;
	}

	Bytes h2_settings_ack()
	{
		Bytes o;
		frame(o, 0, 0x4, 0x1, 0);
		return o;
	}

	Bytes h2_window_update(std::uint32_t inc)
	{
		Bytes o;
		frame(o, 4, 0x8, 0, 0);
		put8(o, inc >> 24);
		put8(o, inc >> 16);
		put8(o, inc >> 8);
		put8(o, inc);
		return o;
	}

	const Bytes& mqtt_connect()
	{
		static const Bytes b = opcase::mqtt_connect(4, 12);  // MQTT 3.1.1, an empty client identifier, as HC1
		return b;
	}
	const Bytes kMqttConnack{std::byte{0x20}, std::byte{0x02}, std::byte{0x00}, std::byte{0x00}};
	const Bytes kPingreq{std::byte{0xC0}, std::byte{0x00}};
	const Bytes kPingresp{std::byte{0xD0}, std::byte{0x00}};
	const Bytes& mqtt_disconnect()
	{
		static const Bytes b = opcase::mqtt_disconnect();
		return b;
	}

	const Bytes& ssh_line()
	{
		static const Bytes b = opcase::text("SSH-2.0-opgen_1.0\r\n");
		return b;
	}

	const Bytes& stub_hello()
	{
		static const Bytes b = opcase::recorded_client_hello();
		return b;
	}

	bool starts_with(const std::byte* p, std::size_t n, std::string_view s) noexcept
	{
		if (n < s.size()) return false;
		return std::memcmp(p, s.data(), s.size()) == 0;
	}

	/// The position just after "\r\n\r\n" in [p, p + n), or 0.
	std::size_t header_end(const std::byte* p, std::size_t n) noexcept
	{
		for (std::size_t i = 3; i < n; ++i)
		{
			if (p[i] == std::byte{'\n'} && p[i - 1] == std::byte{'\r'} && p[i - 2] == std::byte{'\n'} && p[i - 3] == std::byte{'\r'}) return i + 1;
		}
		return 0;
	}

	/// A response of 200 with Content-Length; returns its whole length once complete, 0 while
	/// incomplete, or -1 if it is not a 200 with a 13-byte body "Hello, World!".
	long http_response(const std::byte* p, std::size_t n) noexcept
	{
		const std::size_t he = header_end(p, n);
		if (he == 0) return n > 8192 ? -1 : 0;
		if (!starts_with(p, he, "HTTP/1.1 200 ")) return -1;
		// Content-Length, case-insensitively, at the start of a header line.
		long clen = -1;
		for (std::size_t i = 0; i + 16 < he; ++i)
		{
			if (p[i] != std::byte{'\n'}) continue;
			static constexpr std::string_view key = "content-length:";
			bool match = true;
			for (std::size_t k = 0; k < key.size(); ++k)
			{
				const char ch = static_cast<char>(p[i + 1 + k]);
				if (static_cast<char>(ch >= 'A' && ch <= 'Z' ? ch + 32 : ch) != key[k])
				{
					match = false;
					break;
				}
			}
			if (!match) continue;
			std::size_t q = i + 1 + key.size();
			while (q < he && p[q] == std::byte{' '}) ++q;
			long v = 0;
			const char* first = reinterpret_cast<const char*>(p + q);
			const auto [ptr, ec] = std::from_chars(first, reinterpret_cast<const char*>(p + he), v);
			if (ec != std::errc{} || ptr == first) return -1;
			clen = v;
			break;
		}
		if (clen != static_cast<long>(kBody.size())) return -1;
		if (n < he + static_cast<std::size_t>(clen)) return 0;
		if (std::memcmp(p + he, kBody.data(), kBody.size()) != 0) return -1;
		return static_cast<long>(he) + clen;
	}

}  // namespace oneport::opgen::detail
