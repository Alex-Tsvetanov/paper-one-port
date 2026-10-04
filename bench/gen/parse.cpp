// opgen's readers of the server's bytes, per protocol (worker.hpp): HTTP/1.1 (also inside TLS),
// h2 frames to END_STREAM (also inside TLS, ALPN h2), MQTT's CONNACK and PINGRESP, SSH's
// identification line, and the TLS stub's 13 bytes.
#include "hpack.hpp"
#include "worker.hpp"

#include <algorithm>
#include <cstring>

#include <openssl/err.h>
#include <openssl/ssl.h>

namespace oneport::opgen::detail
{

	void Worker::consume(Conn& c, std::size_t n) noexcept
	{
		std::memmove(c.in.data(), c.in.data() + n, c.in_len - n);
		c.in_len -= static_cast<std::uint32_t>(n);
	}

	void Worker::parse(std::uint32_t i)
	{
		Conn& c = conns_[i];
		if (c.done_reading)
		{
			// After the response only the server's close may come (churn).
			fail(i, End::protocol);
			return;
		}
		switch (o_.proto)
		{
			case Proto::http1:
			case Proto::tls:
			{
				const long n = http_response(c.in.data(), c.in_len);
				if (n < 0)
				{
					fail(i, End::protocol);
					return;
				}
				if (n == 0) return;
				consume(c, static_cast<std::size_t>(n));
				if (o_.load == Load::churn)
				{
					if (c.in_len != 0)
					{
						fail(i, End::protocol);
						return;
					}
					c.done_reading = true;  // the server closes first
					return;
				}
				request_done(i, http_keep());
				return;
			}
			case Proto::h2c:
			case Proto::tls_h2: parse_h2(i); return;
			case Proto::mqtt: parse_mqtt(i); return;
			case Proto::ssh:
			{
				const auto* p = c.in.data();
				const auto* lf = std::find(p, p + c.in_len, std::byte{'\n'});
				if (lf == p + c.in_len)
				{
					if (c.in_len > 255) fail(i, End::protocol);
					return;
				}
				if (!starts_with(p, c.in_len, "SSH-2.0-"))
				{
					fail(i, End::protocol);
					return;
				}
				consume(c, static_cast<std::size_t>(lf - p) + 1);
				if (c.in_len != 0)
				{
					fail(i, End::protocol);
					return;
				}
				c.done_reading = true;
				return;
			}
			case Proto::tls_stub:
			{
				if (c.in_len > kBody.size() || std::memcmp(c.in.data(), kBody.data(), c.in_len) != 0)
				{
					fail(i, End::protocol);
					return;
				}
				if (c.in_len == kBody.size())
				{
					c.in_len = 0;
					c.done_reading = true;
				}
				return;
			}
		}
	}

	void Worker::parse_h2(std::uint32_t i)
	{
		Conn& c = conns_[i];
		for (;;)
		{
			if (c.in_len < 9) return;
			const auto* p = c.in.data();
			const auto u8 = [p](std::size_t k) { return std::to_integer<std::uint32_t>(p[k]); };
			const std::uint32_t len = (u8(0) << 16) | (u8(1) << 8) | u8(2);
			const std::uint32_t type = u8(3);
			const std::uint32_t flags = u8(4);
			const std::uint32_t stream = ((u8(5) & 0x7F) << 24) | (u8(6) << 16) | (u8(7) << 8) | u8(8);
			if (len > c.in.size() - 9)
			{
				fail(i, End::protocol);
				return;
			}
			if (c.in_len < 9 + len) return;
			const std::byte* body = p + 9;
			bool end_stream = false;
			switch (type)
			{
				case 0x0:  // DATA
				{
					if (stream != c.stream)
					{
						fail(i, End::protocol);
						return;
					}
					std::uint32_t off = 0;
					std::uint32_t data = len;
					if ((flags & 0x8) != 0)  // PADDED
					{
						if (len < 1 || std::to_integer<std::uint32_t>(body[0]) + 1 > len)
						{
							fail(i, End::protocol);
							return;
						}
						off = 1;
						data = len - 1 - std::to_integer<std::uint32_t>(body[0]);
					}
					for (std::uint32_t k = 0; k < data; ++k)
					{
						if (c.body < c.body_bytes.size()) c.body_bytes[c.body] = static_cast<char>(body[off + k]);
						++c.body;
					}
					c.window_used += len;
					end_stream = (flags & 0x1) != 0;
					break;
				}
				case 0x1:  // HEADERS
				{
					if (stream != c.stream)
					{
						fail(i, End::protocol);
						return;
					}
					std::uint32_t off = 0;
					if ((flags & 0x8) != 0) off += 1;
					if ((flags & 0x20) != 0) off += 5;
					// :status 200 is the static table's index 8 (0x88), after any dynamic table size
					// updates at the block's start (RFC 7541 s4.2; found in M4b-2: Jetty 12.1 sends one).
					c.status_ok = off < len && h2_status_200(body + off, len - off);
					if ((flags & 0x4) == 0)
					{
						fail(i, End::protocol);  // no CONTINUATION from this server
						return;
					}
					end_stream = (flags & 0x1) != 0;
					break;
				}
				case 0x4:  // SETTINGS
					if ((flags & 0x1) == 0 && o_.load == Load::keepalive) queue(c, h2_settings_ack());
					break;
				case 0x3:  // RST_STREAM
				case 0x7:  // GOAWAY
					fail(i, End::protocol);
					return;
				default: break;  // WINDOW_UPDATE, PING, PRIORITY: nothing to do
			}
			consume(c, 9 + len);
			if (!end_stream) continue;
			if (!c.status_ok || c.body != kBody.size() || std::string_view(c.body_bytes.data(), c.body_bytes.size()) != kBody)
			{
				fail(i, End::protocol);
				return;
			}
			if (o_.load == Load::churn)
			{
				// WL1: read to END_STREAM, then GOAWAY; the client closes first. Inside TLS the client
				// then sends close_notify before it closes (RFC 8446 s6.1).
				queue(c, h2_goaway());
				if (!flush(i)) return;
				if (c.ssl != nullptr)
				{
					SSL_shutdown(c.ssl);  // non-blocking: close_notify is written, the peer's is not awaited
					ERR_clear_error();
				}
				complete(i);
				return;
			}
			c.stream += 2;
			c.status_ok = false;
			c.body = 0;
			Bytes next;
			if (c.window_used >= 32768)
			{
				next = h2_window_update(c.window_used);
				c.window_used = 0;
			}
			const Bytes h = h2_headers(c.stream);
			next.insert(next.end(), h.begin(), h.end());
			request_done(i, next);
			return;
		}
	}

	void Worker::parse_mqtt(std::uint32_t i)
	{
		Conn& c = conns_[i];
		if (!c.ready)
		{
			if (c.in_len < kMqttConnack.size()) return;
			if (!std::equal(kMqttConnack.begin(), kMqttConnack.end(), c.in.begin()))
			{
				fail(i, End::protocol);
				return;
			}
			consume(c, kMqttConnack.size());
			if (o_.load == Load::churn)
			{
				if (c.in_len != 0)
				{
					fail(i, End::protocol);
					return;
				}
				queue(c, mqtt_disconnect());
				if (!flush(i)) return;
				complete(i);  // WL1: the client closes first
				return;
			}
			// Keep-alive: CONNECT is the setup; the first PINGREQ is the first request.
			c.ready = true;
			c.rec.begin = now_ns();
			c.rec.due = c.rec.begin;
			c.rec.first = -1;
			queue(c, kPingreq);
			flush(i);
			return;
		}
		if (c.in_len < kPingresp.size()) return;
		if (!std::equal(kPingresp.begin(), kPingresp.end(), c.in.begin()))
		{
			fail(i, End::protocol);
			return;
		}
		consume(c, kPingresp.size());
		request_done(i, kPingreq);
	}

}  // namespace oneport::opgen::detail
