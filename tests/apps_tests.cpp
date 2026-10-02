// Pure tests of the handlers' protocol steps (bench/server/apps.cpp). No socket; they run on every
// platform.
#include "apps.hpp"
#include "fixtures.hpp"
#include "http1.hpp"
#include "test_support.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace oneport::test
{

	namespace
	{

		using apps::Next;
		using opcase::Bytes;
		using opcase::text;

		std::string str(const std::vector<std::byte>& b)
		{
			std::string s;
			for (const std::byte x : b) s += static_cast<char>(std::to_integer<unsigned char>(x));
			return s;
		}

		Bytes raw(std::initializer_list<unsigned> v)
		{
			Bytes b;
			for (const unsigned x : v) b.push_back(static_cast<std::byte>(x));
			return b;
		}

		// ---- SMTP ----

		Result smtp_lines()
		{
			std::vector<std::byte> out;
			const Bytes in = text("EHLO a.test\r\nehlo\r\nNOOP\r\n\r\nEHLOX\r\nQUIT\r\nEHLO late\r\n");
			const apps::Step s = apps::smtp(in, {true, false}, false, out);
			const std::string want = std::string(apps::kSmtpEhlo) + std::string(apps::kSmtpEhlo) + std::string(apps::kSmtpUnknown) +
			                         std::string(apps::kSmtpUnknown) + std::string(apps::kSmtpUnknown) + std::string(apps::kSmtpBye);
			CHECK(str(out) == want, "replies: " << str(out).size() << " bytes, expected " << want.size());
			CHECK(s.next == Next::close_after_output, "QUIT closes");
			CHECK(s.used == in.size() - text("EHLO late\r\n").size(), "nothing after QUIT is read");
			return std::nullopt;
		}

		Result smtp_partial_and_limits()
		{
			std::vector<std::byte> out;
			apps::Step s = apps::smtp(text("EHL"), {true, false}, false, out);
			CHECK(s.used == 0 && s.next == Next::more && out.empty(), "a partial line waits");
			s = apps::smtp(text("EHL"), {true, false}, true, out);
			CHECK(s.next == Next::close_after_output && out.empty(), "a partial line at EOF closes, unanswered");
			s = apps::smtp(text("EHLO a\r\nEHL"), {false, true}, false, out);
			CHECK(s.next == Next::need_room && s.used == 8, "a partial line at the end of a full buffer asks for room");
			out.clear();
			s = apps::smtp(Bytes(apps::kSmtpLineMax, std::byte{'x'}), {true, false}, false, out);
			CHECK(s.next == Next::close_after_output && str(out) == apps::kSmtpUnknown, "512 bytes without CRLF: 500, then close");
			out.clear();
			Bytes long_line(apps::kSmtpLineMax - 1, std::byte{'x'});
			const Bytes crlf = text("\r\n");
			long_line.insert(long_line.end(), crlf.begin(), crlf.end());
			s = apps::smtp(long_line, {true, false}, false, out);
			CHECK(s.next == Next::close_after_output && str(out) == apps::kSmtpUnknown, "a 513-byte line: 500, then close");
			return std::nullopt;
		}

		// ---- MQTT ----

		Result mqtt_connect_ping_disconnect()
		{
			for (const int level : {4, 5})
			{
				const Bytes in = opcase::cat({opcase::mqtt_connect(level, level == 5 ? 13 : 12), raw({0xC0, 0x00}), raw({0xC0, 0x00}), opcase::mqtt_disconnect()});
				// Byte by byte, then all at once: the same replies.
				for (const bool drip : {true, false})
				{
					apps::MqttState m{};
					std::vector<std::byte> out;
					apps::Step s;
					std::size_t used = 0;
					if (drip)
					{
						for (std::size_t i = 0; i < in.size() && s.next == Next::more; ++i)
						{
							s = apps::mqtt(m, std::span<const std::byte>(in).subspan(i, 1), false, out);
							used += s.used;
						}
					}
					else
					{
						s = apps::mqtt(m, in, false, out);
						used = s.used;
					}
					const Bytes connack = level == 5 ? raw({0x20, 0x03, 0x00, 0x00, 0x00}) : raw({0x20, 0x02, 0x00, 0x00});
					CHECK(out == opcase::cat({connack, raw({0xD0, 0x00}), raw({0xD0, 0x00})}), "level " << level << (drip ? ", dripped" : "") << ": wrong replies");
					CHECK(s.next == Next::close_after_output && used == in.size(), "DISCONNECT closes");
				}
			}
			return std::nullopt;
		}

		Result mqtt_streams_payload()
		{
			// HC24's 4-byte Remaining Length: 2,097,152 bytes, skipped as they arrive, never held.
			const Bytes in = opcase::mqtt_connect(4, 2097152);
			apps::MqttState m{};
			std::vector<std::byte> out;
			std::size_t at = 0;
			while (at < in.size())
			{
				const std::size_t n = std::min<std::size_t>(4096, in.size() - at);
				const apps::Step s = apps::mqtt(m, std::span<const std::byte>(in).subspan(at, n), false, out);
				CHECK(s.used == n && s.next == Next::more, "a chunk of the CONNECT was not consumed");
				CHECK(at + n == in.size() || out.empty(), "CONNACK before the CONNECT ended");
				at += n;
			}
			CHECK(out == raw({0x20, 0x02, 0x00, 0x00}), "no CONNACK after the CONNECT's last byte");
			return std::nullopt;
		}

		Result mqtt_refusals()
		{
			auto refused = [](const Bytes& in) {
				apps::MqttState m{};
				std::vector<std::byte> out;
				const apps::Step s = apps::mqtt(m, in, false, out);
				return s.next == Next::close_now && out.empty();
			};
			CHECK(refused(raw({0x30, 0x00})), "a first packet other than CONNECT");
			CHECK(refused(opcase::mqtt_isdp()), "MQTT 3.1 (MQIsdp)");
			CHECK(refused(raw({0x10, 0x80, 0x80, 0x80, 0x80, 0x01})), "a fifth Remaining Length byte");
			CHECK(refused(raw({0x10, 0x01, 0x00})), "a CONNECT too short for its name and level");
			Bytes level3 = opcase::mqtt_connect(4, 12);
			level3[8] = std::byte{3};
			CHECK(refused(level3), "level 3");
			apps::MqttState m{};
			std::vector<std::byte> out;
			apps::Step s = apps::mqtt(m, opcase::cat({opcase::mqtt_connect(4, 12), raw({0x30, 0x00})}), false, out);
			CHECK(s.next == Next::close_now && out == raw({0x20, 0x02, 0x00, 0x00}), "PUBLISH after CONNACK closes");
			return std::nullopt;
		}

		// ---- SSH ----

		Result ssh_line()
		{
			apps::SshState st{};
			apps::Step s = apps::ssh(st, text("SSH-2.0-x"), false);
			CHECK(s.next == Next::more && s.used == 9, "a partial line waits");
			s = apps::ssh(st, text(" comment\r\nmore"), false);
			CHECK(s.next == Next::close_after_output && s.used == 10, "the line ends at its LF");
			apps::SshState other{};
			CHECK(apps::ssh(other, text("SSX-"), false).next == Next::close_now, "not SSH-: closed");
			apps::SshState longer{};
			Bytes l = text("SSH-");
			l.resize(400, std::byte{'a'});
			s = apps::ssh(longer, l, false);
			CHECK(s.next == Next::close_after_output && s.used == apps::kSshLineMax, "255 bytes without LF: closed");
			return std::nullopt;
		}

		// ---- HTTP/1.1 ----

		Result http_room()
		{
			std::vector<std::byte> out;
			const Bytes two = opcase::cat({text("GET / HTTP/1.1\r\nHost: a\r\n\r\n"), text("GET / HTTP/1.1\r\nHo")});
			apps::Step s = apps::http1(two, {false, true}, false, out);
			CHECK(s.next == Next::need_room && str(out) == http1::kResponse200, "a partial request at the end of a full buffer asks for room");
			out.clear();
			s = apps::http1(text("GET / HTTP/1.1\r\nHo"), {true, true}, false, out);
			CHECK(s.next == Next::close_after_output && str(out) == http1::kResponse400, "a request that fills the buffer: 400");
			out.clear();
			s = apps::http1(text("GET  / HTTP/1.1\r\n"), {true, false}, false, out);
			CHECK(s.next == Next::close_now && out.empty(), "a second SP: closed without a response");
			return std::nullopt;
		}

	}  // namespace

	void register_apps_tests(Registry& r)
	{
		r["apps.smtp_lines"] = smtp_lines;
		r["apps.smtp_partial_and_limits"] = smtp_partial_and_limits;
		r["apps.mqtt_connect_ping_disconnect"] = mqtt_connect_ping_disconnect;
		r["apps.mqtt_streams_payload"] = mqtt_streams_payload;
		r["apps.mqtt_refusals"] = mqtt_refusals;
		r["apps.ssh_line"] = ssh_line;
		r["apps.http_room"] = http_room;
	}

}  // namespace oneport::test
