// Pure tests of the ClientHello reader (bench/server/clienthello.hpp) on the recorded ClientHello
// (tests/fixtures/tls/clienthello.hex) and of opcase's record helpers. No socket; they run on every
// platform.
#include "clienthello.hpp"
#include "fixtures.hpp"
#include "test_support.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

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

		/// scan() decides as reassemble() does, without the copy (M5): on every prefix of the
		/// recorded ClientHello, of its two-record form (the handshake header whole in the first
		/// record, and split across the two), of a ClientHello longer than B_CH, and of input that is
		/// not TLS or not a ClientHello.
		Result clienthello_scan()
		{
			const Bytes r = opcase::recorded_client_hello();
			std::vector<Bytes> inputs{r, opcase::fragment_client_hello(r, 40), opcase::fragment_client_hello(r, 2), text("GET / HTTP/1.1\r\n\r\n")};
			Bytes not_hello = r;
			not_hello[5] = std::byte{0x02};  // a ServerHello's type
			inputs.push_back(not_hello);
			Bytes too_long = r;
			too_long[6] = std::byte{0x01};  // the handshake length's top byte: 65536 more than B_CH allows
			inputs.push_back(too_long);
			std::array<std::byte, detect::kBCh> buf{};
			std::size_t compared = 0;
			for (const Bytes& in : inputs)
			{
				for (std::size_t n = 0; n <= in.size(); ++n)
				{
					const std::span<const std::byte> w = std::span<const std::byte>(in).first(n);
					const clienthello::Reassembled a = clienthello::reassemble(w, buf);
					const clienthello::Reassembled s = clienthello::scan(w);
					CHECK(a.verdict == s.verdict && a.msg_len == s.msg_len && a.wire_len == s.wire_len && a.records == s.records && a.need == s.need,
					      "scan and reassemble differ on " << n << " of " << in.size() << " bytes");
					++compared;
				}
			}
			CHECK(clienthello::scan(r).verdict == clienthello::Verdict::yes && clienthello::scan(not_hello).verdict == clienthello::Verdict::no &&
			          clienthello::scan(too_long).verdict == clienthello::Verdict::no,
			      "the whole inputs");
			CHECK(compared > 3 * r.size(), compared << " prefixes compared");
			return std::nullopt;
		}

		// ---- M7: the bound on what the reassembly asks for (design/status.md, M7) ----

		void push(Bytes& w, std::size_t v) { w.push_back(static_cast<std::byte>(v & 0xFF)); }

		/// A handshake record's header (record version 03 01) announcing `len` bytes.
		void record_header(Bytes& w, std::size_t len)
		{
			push(w, 0x16);
			push(w, 0x03);
			push(w, 0x01);
			push(w, len >> 8);
			push(w, len);
		}

		/// A ClientHello's 4-byte handshake header for a message of `msg` bytes, the header included.
		void hello_header(Bytes& w, std::size_t msg)
		{
			const std::size_t body = msg - 4;
			push(w, 0x01);
			push(w, body >> 16);
			push(w, body >> 8);
			push(w, body);
		}

		void filler(Bytes& w, std::size_t n) { w.insert(w.end(), n, std::byte{0}); }

		/// clienthello::scan() as it was before M7 (one-port f7d62a2): a record that would take the
		/// handshake bytes past B_CH was refused only once whole. The oracle of the property that M7
		/// moves no verdict but the moment of a "no".
		clienthello::Reassembled before_m7(std::span<const std::byte> wire)
		{
			using clienthello::Verdict;
			const auto b = [&wire](std::size_t i) { return std::to_integer<std::size_t>(wire[i]); };
			clienthello::Reassembled r;
			std::size_t pos = 0;
			std::size_t got = 0;
			std::array<std::size_t, 4> head{};
			for (;;)
			{
				if (got >= 4)
				{
					if (head[0] != 0x01) return {Verdict::no, 0, 0, r.records};
					const std::size_t need = 4 + ((head[1] << 16) | (head[2] << 8) | head[3]);
					if (need > detect::kBCh) return {Verdict::no, 0, 0, r.records};
					if (got >= need) return {Verdict::yes, static_cast<std::uint32_t>(need), static_cast<std::uint32_t>(pos), r.records};
				}
				if (wire.size() - pos < 5)
				{
					r.need = static_cast<std::uint32_t>(pos + 5);
					return r;
				}
				if (b(pos) != 0x16 || b(pos + 1) != 0x03) return {Verdict::no, 0, 0, r.records};
				const std::size_t len = (b(pos + 3) << 8) | b(pos + 4);
				if (len == 0 || len > 16384) return {Verdict::no, 0, 0, r.records};
				if (wire.size() - pos - 5 < len)
				{
					r.need = static_cast<std::uint32_t>(pos + 5 + len);
					return r;
				}
				if (got + len > detect::kBCh) return {Verdict::no, 0, 0, r.records};
				for (std::size_t i = 0; i < len && got + i < head.size(); ++i) head[got + i] = b(pos + 5 + i);
				got += len;
				pos += 5 + len;
				++r.records;
			}
		}

		bool same(const clienthello::Reassembled& a, const clienthello::Reassembled& b)
		{
			return a.verdict == b.verdict && a.msg_len == b.msg_len && a.wire_len == b.wire_len && a.records == b.records && a.need == b.need;
		}

		/// helloroom1's three framings (design/status.md, M7 preparation), as the relay holds them
		/// when the bytes named have arrived: what the reassembly asks for before and after M7.
		/// A: a 512-byte ClientHello in one record, its first 9 bytes: 517, the record (unchanged).
		/// B: a 104-byte ClientHello in a record whose header announces 16,384: 16,389, which is
		///    B_CH and one record's 5 bytes, the bound itself (unchanged; design/status.md, M7).
		/// C: record 1 whole with 16,000 bytes of a 16,384-byte ClientHello, then record 2's header
		///    announcing 16,384: before M7 "more" with 32,394; now "no" at that header.
		Result helloroom1_shapes()
		{
			std::array<std::byte, detect::kBCh> buf{};
			Bytes a;
			record_header(a, 512);
			hello_header(a, 512);
			Bytes b;
			record_header(b, 16384);
			hello_header(b, 104);
			Bytes c;
			record_header(c, 16000);
			hello_header(c, 16384);
			filler(c, 16000 - 4);
			record_header(c, 16384);
			CHECK(a.size() == 9 && b.size() == 9 && c.size() == 16010, "the shapes' sizes");
			using clienthello::Verdict;
			const auto ra = clienthello::reassemble(a, buf);
			const auto rb = clienthello::reassemble(b, buf);
			const auto rc = clienthello::reassemble(c, buf);
			CHECK(ra.verdict == Verdict::more && ra.records == 0 && ra.need == 517, "A: need " << ra.need);
			CHECK(rb.verdict == Verdict::more && rb.records == 0 && rb.need == 16389 && rb.need == detect::kBCh + 5, "B: need " << rb.need);
			CHECK(rc.verdict == Verdict::no && rc.records == 1, "C: verdict " << static_cast<int>(rc.verdict) << ", need " << rc.need);
			// helloroom1's numbers, from the reassembler before M7.
			CHECK(before_m7(a).need == 517 && before_m7(b).need == 16389, "before M7: A and B");
			CHECK(before_m7(c).verdict == Verdict::more && before_m7(c).need == 32394, "before M7: C asked for " << before_m7(c).need);
			for (const Bytes* w : {&a, &b, &c}) CHECK(same(clienthello::scan(*w), clienthello::reassemble(*w, buf)), "scan and reassemble differ");
			return std::nullopt;
		}

		/// The refusal at the record header, on C's whole stream (record 2 complete, 16,384 bytes:
		/// 384 of the ClientHello, then 16,000 more): on every prefix the verdict is never "yes";
		/// before record 2's header is whole it is "more" as before M7, and from then on "no"; the
		/// whole stream gets "no" from both, so the accepted inputs are the same. At the boundary,
		/// a record 2 that announces exactly the 384 bytes the message lacks (16,384 in all, B_CH)
		/// is accepted, and its storage, 16,394 bytes, is B_CH and two records' 5 bytes.
		Result refusal_at_header()
		{
			using clienthello::Verdict;
			std::array<std::byte, detect::kBCh> buf{};
			Bytes c;
			record_header(c, 16000);
			hello_header(c, 16384);
			filler(c, 16000 - 4);
			const std::size_t second = c.size();
			record_header(c, 16384);
			filler(c, 16384);
			std::size_t refused = 0;
			for (std::size_t n = 0; n <= c.size(); ++n)
			{
				const std::span<const std::byte> w = std::span<const std::byte>(c).first(n);
				const auto now = clienthello::reassemble(w, buf);
				const auto old = before_m7(w);
				CHECK(now.verdict != Verdict::yes, "a yes at " << n << " bytes");
				if (n < second + 5)
				{
					CHECK(same(now, old) && now.verdict == Verdict::more, "before record 2's header, at " << n << " bytes");
				}
				else
				{
					CHECK(now.verdict == Verdict::no && now.records == 1, "not refused at " << n << " bytes");
					++refused;
				}
				CHECK(same(clienthello::scan(w), now), "scan and reassemble differ at " << n << " bytes");
			}
			CHECK(refused == c.size() - second - 4, refused << " prefixes refused");
			CHECK(before_m7(c).verdict == Verdict::no, "before M7 the whole stream was not refused");
			// The boundary: the message's last 384 bytes in a record of exactly 384.
			Bytes edge = Bytes(c.begin(), c.begin() + static_cast<std::ptrdiff_t>(second));
			record_header(edge, 384);
			filler(edge, 384);
			const auto e = clienthello::reassemble(edge, buf);
			CHECK(e.verdict == Verdict::yes && e.msg_len == detect::kBCh && e.records == 2 && e.wire_len == detect::kBCh + 10,
			      "the 16,384-byte ClientHello in records of 16,000 and 384: verdict " << static_cast<int>(e.verdict));
			const auto part = clienthello::reassemble(std::span<const std::byte>(edge).first(edge.size() - 1), buf);
			CHECK(part.verdict == Verdict::more && part.need == detect::kBCh + 10, "its storage: " << part.need);
			return std::nullopt;
		}

		/// The bound on every prefix of several framings: when the verdict is "more", `need` is at
		/// most B_CH and 5 bytes per record (the whole ones and the incomplete one) and more than
		/// the bytes held; scan() agrees with reassemble(); the verdict differs from the
		/// reassembler before M7 only by an earlier "no" in a stream that it refused too; and every
		/// whole stream gets the same verdict as before M7.
		Result need_bound()
		{
			using clienthello::Verdict;
			std::array<std::byte, detect::kBCh> buf{};
			const Bytes rec = opcase::recorded_client_hello();
			std::vector<Bytes> streams{rec, opcase::fragment_client_hello(rec, 40), opcase::fragment_client_hello(rec, 2)};
			// A 600-byte message in 1-byte records (the most records per message byte).
			{
				Bytes m;
				hello_header(m, 600);
				filler(m, 596);
				Bytes w;
				for (const std::byte x : m)
				{
					record_header(w, 1);
					w.push_back(x);
				}
				streams.push_back(w);
			}
			// A message of B_CH bytes: in one record; in records of 16,000 and 384; and in records of
			// 16,000 and 16,384 (refused at the second header).
			for (const std::size_t first : {std::size_t{16384}, std::size_t{16000}})
			{
				for (const std::size_t rest : {std::size_t{384}, std::size_t{16384}})
				{
					if (first == 16384 && rest == 16384) continue;
					Bytes w;
					record_header(w, first);
					hello_header(w, 16384);
					filler(w, first - 4);
					if (first < 16384)
					{
						record_header(w, rest);
						filler(w, rest);
					}
					streams.push_back(w);
				}
			}
			// B's stream whole: a 104-byte ClientHello, then 16,280 bytes more in its record.
			{
				Bytes w;
				record_header(w, 16384);
				hello_header(w, 104);
				filler(w, 16384 - 4);
				streams.push_back(w);
			}
			// A message one byte longer than B_CH, in records of 16,000 and the rest.
			{
				Bytes w;
				record_header(w, 16000);
				hello_header(w, 16385);
				filler(w, 16000 - 4);
				record_header(w, 385);
				filler(w, 385);
				streams.push_back(w);
			}
			std::size_t checked = 0;
			std::size_t earlier = 0;
			for (const Bytes& s : streams)
			{
				// Every prefix of the short streams; of the long ones every prefix within 8 bytes of a
				// record boundary and every 61st byte, so the sweep stays short under the sanitizers.
				std::vector<std::size_t> at;
				std::vector<std::size_t> edges{0, s.size()};
				for (std::size_t p = 0; p + 5 <= s.size();)
				{
					const std::size_t len = (std::to_integer<std::size_t>(s[p + 3]) << 8) | std::to_integer<std::size_t>(s[p + 4]);
					edges.push_back(p + 5);
					p += 5 + len;
					edges.push_back(std::min(p, s.size()));
				}
				for (std::size_t n = 0; n <= s.size(); ++n)
				{
					bool near = s.size() <= 4096 || n % 61 == 0;
					for (const std::size_t e : edges) near = near || (n + 8 >= e && n <= e + 8);
					if (near) at.push_back(n);
				}
				for (const std::size_t n : at)
				{
					const std::span<const std::byte> w = std::span<const std::byte>(s).first(n);
					const auto now = clienthello::reassemble(w, buf);
					const auto old = before_m7(w);
					CHECK(same(clienthello::scan(w), now), "scan and reassemble differ at " << n << " of " << s.size() << " bytes");
					if (now.verdict == Verdict::more)
					{
						CHECK(now.need > n && now.need <= detect::kBCh + 5 * (now.records + 1),
						      "need " << now.need << " at " << n << " of " << s.size() << " bytes, " << now.records << " records whole");
					}
					if (!same(now, old))
					{
						CHECK(now.verdict == Verdict::no && old.verdict == Verdict::more && before_m7(s).verdict == Verdict::no,
						      "a verdict other than an earlier no at " << n << " of " << s.size() << " bytes");
						++earlier;
					}
					++checked;
				}
				CHECK(same(clienthello::reassemble(s, buf), before_m7(s)), "the whole stream of " << s.size() << " bytes: another verdict");
			}
			CHECK(checked > 5000 && earlier > 0, checked << " prefixes checked, " << earlier << " refused earlier");
			return std::nullopt;
		}

	}  // namespace

	void register_clienthello_tests(Registry& r)
	{
		r["clienthello.recorded"] = recorded_client_hello;
		r["clienthello.fragments"] = clienthello_fragments;
		r["clienthello.scan"] = clienthello_scan;
		r["clienthello.helloroom1"] = helloroom1_shapes;
		r["clienthello.refusal"] = refusal_at_header;
		r["clienthello.need_bound"] = need_bound;
	}

}  // namespace oneport::test
