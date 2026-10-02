#include "apps.hpp"

#include "http1.hpp"

#include <algorithm>
#include <array>

namespace oneport::apps
{

	namespace
	{

		std::uint8_t u8(std::byte b) noexcept { return std::to_integer<std::uint8_t>(b); }

		char lower(std::uint8_t c) noexcept { return static_cast<char>(c >= 'A' && c <= 'Z' ? c + 32 : c); }

		/// Does `line` start with the verb `v` (lower case), case-insensitively, alone or before a space?
		bool verb(std::span<const std::byte> line, std::string_view v) noexcept
		{
			if (line.size() < v.size()) return false;
			for (std::size_t i = 0; i < v.size(); ++i)
			{
				if (lower(u8(line[i])) != v[i]) return false;
			}
			return line.size() == v.size() || u8(line[v.size()]) == ' ';
		}

	}  // namespace

	Step http1(std::span<const std::byte> in, Room room, bool eof, std::vector<std::byte>& out)
	{
		Step s;
		while (s.used < in.size())
		{
			const std::span<const std::byte> data = in.subspan(s.used);
			const bool at_start = room.at_start && s.used == 0;
			const http1::Parsed p = http1::parse(data, room.full && at_start);
			switch (p.status)
			{
				case http1::Status::more:
					if (room.full && !at_start)
					{
						s.next = Next::need_room;
						return s;
					}
					s.next = eof ? Next::close_now : Next::more;  // an incomplete request at EOF: no response
					return s;
				case http1::Status::bad_grammar:
					s.next = Next::close_now;  // closed without a response, as the detector closes it
					return s;
				case http1::Status::bad_request:
					s.used = static_cast<std::uint32_t>(in.size());
					append(out, http1::kResponse400);
					s.next = Next::close_after_output;
					return s;
				case http1::Status::request:
					s.used += p.length;
					append(out, http1::kResponse200);
					if (!p.keep_alive)
					{
						s.next = Next::close_after_output;
						return s;
					}
					break;
			}
		}
		s.next = eof ? Next::close_after_output : Next::more;
		return s;
	}

	Step ssh(SshState& st, std::span<const std::byte> in, bool eof)
	{
		static constexpr std::string_view kPrefix = "SSH-";
		Step s;
		for (const std::byte b : in)
		{
			++s.used;
			const std::uint8_t c = u8(b);
			if (st.seen < kPrefix.size() && c != static_cast<std::uint8_t>(kPrefix[st.seen]))
			{
				s.next = Next::close_now;  // not an identification line: the detector's grammar
				return s;
			}
			++st.seen;
			if (c == '\n' || st.seen >= kSshLineMax)
			{
				s.next = Next::close_after_output;  // the line is read: close (I26)
				return s;
			}
		}
		s.next = eof ? Next::close_after_output : Next::more;
		return s;
	}

	Step smtp(std::span<const std::byte> in, Room room, bool eof, std::vector<std::byte>& out)
	{
		Step s;
		for (;;)
		{
			const std::span<const std::byte> rest = in.subspan(s.used);
			std::size_t crlf = rest.size();
			for (std::size_t i = 1; i < rest.size(); ++i)
			{
				if (u8(rest[i]) == '\n' && u8(rest[i - 1]) == '\r')
				{
					crlf = i - 1;
					break;
				}
			}
			if (crlf == rest.size())
			{
				if (rest.size() >= kSmtpLineMax || (room.full && room.at_start && s.used == 0))
				{
					s.used = static_cast<std::uint32_t>(in.size());
					append(out, kSmtpUnknown);  // a line too long (RFC 5321 s4.2.2: 500 includes it)
					s.next = Next::close_after_output;
					return s;
				}
				if (room.full && !rest.empty() && !(room.at_start && s.used == 0))
				{
					s.next = Next::need_room;
					return s;
				}
				s.next = eof ? Next::close_after_output : Next::more;
				return s;
			}
			if (crlf + 2 > kSmtpLineMax)
			{
				s.used = static_cast<std::uint32_t>(in.size());
				append(out, kSmtpUnknown);
				s.next = Next::close_after_output;
				return s;
			}
			const std::span<const std::byte> line = rest.first(crlf);
			s.used += static_cast<std::uint32_t>(crlf + 2);
			if (verb(line, "ehlo"))
			{
				append(out, kSmtpEhlo);
			}
			else if (line.size() == 4 && verb(line, "quit"))
			{
				append(out, kSmtpBye);
				s.next = Next::close_after_output;
				return s;
			}
			else
			{
				append(out, kSmtpUnknown);
			}
		}
	}

	Step mqtt(MqttState& m, std::span<const std::byte> in, bool eof, std::vector<std::byte>& out)
	{
		static constexpr std::array<std::uint8_t, 6> kName{0x00, 0x04, 'M', 'Q', 'T', 'T'};
		Step s;
		auto close = [&s](Next n) {
			s.next = n;
			return s;
		};
		while (s.used < in.size())
		{
			if (m.phase == 3)
			{
				const std::uint32_t n = std::min<std::uint32_t>(m.left, static_cast<std::uint32_t>(in.size()) - s.used);
				s.used += n;
				m.left -= n;
			}
			else
			{
				const std::uint8_t b = u8(in[s.used]);
				++s.used;
				switch (m.phase)
				{
					case 0:
						// The first packet must be CONNECT; after CONNACK, PINGREQ or DISCONNECT.
						if (!m.connected ? b != 0x10 : (b != 0xC0 && b != 0xE0)) return close(Next::close_now);
						m.type = b;
						m.rl = 0;
						m.rl_bytes = 0;
						m.phase = 1;
						break;
					case 1:
						m.rl |= static_cast<std::uint32_t>(b & 0x7F) << (7 * m.rl_bytes);
						++m.rl_bytes;
						if ((b & 0x80) != 0)
						{
							if (m.rl_bytes == 4) return close(Next::close_now);  // a fifth length byte (MQTT 5.0 s1.5.5)
							break;
						}
						if (m.type == 0x10)
						{
							if (m.rl < kName.size() + 1) return close(Next::close_now);
							m.vh = 0;
							m.phase = 2;
							break;
						}
						if (m.type == 0xC0)
						{
							if (m.rl != 0) return close(Next::close_now);
							append(out, std::string_view("\xD0\x00", 2));  // PINGRESP
							m.phase = 0;
							break;
						}
						return close(Next::close_after_output);  // DISCONNECT
					case 2:
						if (m.vh < kName.size())
						{
							if (b != kName[m.vh]) return close(Next::close_now);
						}
						else
						{
							if (b != 4 && b != 5) return close(Next::close_now);
							m.level = b;
						}
						++m.vh;
						if (m.vh == kName.size() + 1)
						{
							m.left = m.rl - static_cast<std::uint32_t>(kName.size() + 1);
							m.phase = 3;
						}
						break;
					default: return close(Next::close_now);
				}
			}
			if (m.phase == 3 && m.left == 0)
			{
				append(out, m.level == 5 ? std::string_view("\x20\x03\x00\x00\x00", 5) : std::string_view("\x20\x02\x00\x00", 4));  // CONNACK
				m.connected = true;
				m.phase = 0;
			}
		}
		return close(eof ? Next::close_after_output : Next::more);
	}

}  // namespace oneport::apps
