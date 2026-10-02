// Pure tests of the ClientHello reader (bench/server/clienthello.hpp) on the recorded ClientHello
// (tests/fixtures/tls/clienthello.hex) and of opcase's record helpers. No socket; they run on every
// platform.
#include "clienthello.hpp"
#include "fixtures.hpp"
#include "test_support.hpp"

#include <algorithm>
#include <array>
#include <cstdint>

namespace oneport::test
{

	namespace
	{

		using opcase::Bytes;
		using opcase::text;

		// ---- The recorded ClientHello ----

		Result recorded_client_hello()
		{
			const Bytes r = opcase::recorded_client_hello();
			CHECK(std::to_integer<int>(r[0]) == 0x16 && std::to_integer<int>(r[1]) == 0x03 && std::to_integer<int>(r[2]) == 0x01,
			      "not a handshake record with version 03 01");
			const std::size_t len = (std::to_integer<std::size_t>(r[3]) << 8) | std::to_integer<std::size_t>(r[4]);
			CHECK(len + 5 == r.size(), "the record length " << len << " does not match the " << r.size() << " bytes recorded");
			std::array<std::byte, detect::kBCh> buf{};
			const clienthello::Reassembled a = clienthello::reassemble(r, buf);
			CHECK(a.verdict == clienthello::Verdict::yes && a.records == 1 && a.msg_len == len && a.wire_len == r.size(), "one record, one ClientHello");
			const std::span<const std::byte> m(buf.data(), a.msg_len);
			const clienthello::Hello h = clienthello::parse(m);
			CHECK(h.ok, "the ClientHello does not parse");
			CHECK(clienthello::text(m, h.sni) == "oneport.test", "SNI '" << clienthello::text(m, h.sni) << "'");
			CHECK(clienthello::text(m, h.alpn) == std::string_view("\x08http/1.1", 9), "ALPN is not exactly http/1.1");
			CHECK(h.x25519.present && h.x25519.len == 32, "no 32-byte X25519 key share");
			CHECK(h.random.len == 32 && h.session_id.present, "random and session id");
			auto has = [&h](std::uint16_t t) {
				for (std::uint8_t i = 0; i < h.n_exts; ++i)
					if (h.exts[i] == t) return true;
				return false;
			};
			CHECK(has(0) && has(10) && has(13) && has(16) && has(43) && has(51), "server_name, supported_groups, signature_algorithms, ALPN, supported_versions, key_share");
			// The matcher's view (section 1): TLS at 6 bytes.
			const detect::Decision d = detect::classify(std::span<const std::byte>(r).first(6));
			CHECK(d.outcome == detect::Outcome::classified && d.proto == detect::Proto::tls && d.at == 6, "the detection table does not say TLS at 6 bytes");
			return std::nullopt;
		}

		Result clienthello_fragments()
		{
			const Bytes r = opcase::recorded_client_hello();
			std::size_t first = 0;
			const Bytes two = opcase::fragment_client_hello(r, 40, &first);
			CHECK(first == 45 && two.size() == r.size() + 5, "two records: 45 bytes, then the rest");
			std::array<std::byte, detect::kBCh> a{};
			std::array<std::byte, detect::kBCh> b{};
			const auto one = clienthello::reassemble(r, a);
			const auto both = clienthello::reassemble(two, b);
			CHECK(both.verdict == clienthello::Verdict::yes && both.records == 2 && both.msg_len == one.msg_len, "the two records reassemble");
			CHECK(std::equal(a.begin(), a.begin() + one.msg_len, b.begin()), "to the same message");
			CHECK(clienthello::reassemble(std::span<const std::byte>(two).first(first + 3), b).verdict == clienthello::Verdict::more, "a partial second record waits");
			CHECK(clienthello::reassemble(text("GET / HTTP/1.1\r\n"), b).verdict == clienthello::Verdict::no, "not TLS");
			const Bytes v0303 = opcase::with_record_version(r, 0x03);
			CHECK(std::to_integer<int>(v0303[2]) == 0x03 && clienthello::reassemble(v0303, b).verdict == clienthello::Verdict::yes, "record version 03 03");
			return std::nullopt;
		}

	}  // namespace

	void register_clienthello_tests(Registry& r)
	{
		r["clienthello.recorded"] = recorded_client_hello;
		r["clienthello.fragments"] = clienthello_fragments;
	}

}  // namespace oneport::test
