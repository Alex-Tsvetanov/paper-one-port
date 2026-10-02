// The detection table at run time (hypotheses.md, section 11: "the detection table on its corpus
// at every split"), through the same function the server calls, and the PROXY parser.
#include "detect.hpp"
#include "detect_corpus.hpp"
#include "test_support.hpp"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace oneport::test
{

	namespace
	{

		using namespace oneport::detect;
		using Buf = std::vector<std::byte>;

		Buf bytes(std::string_view s)
		{
			Buf b;
			for (const char c : s) b.push_back(static_cast<std::byte>(static_cast<unsigned char>(c)));
			return b;
		}

		Buf bytes(std::initializer_list<int> v)
		{
			Buf b;
			for (const int x : v) b.push_back(static_cast<std::byte>(x));
			return b;
		}

		Decision classify_bytes(const Buf& b) { return classify(Bytes(b.data(), b.size())); }
		ProxyResult proxy(const Buf& b) { return parse_proxy(Bytes(b.data(), b.size())); }

		/// Every sample, fed as the server feeds it: the first chunk, then the whole, at every split
		/// point, and byte by byte. Before the sample's decision length the bytes stay undecided
		/// with a low-water mark beyond them; from it on they are classified as the sample's class.
		Result corpus_splits()
		{
			for (const auto& s : corpus::kSamples)
			{
				const Buf all(s.bytes.begin(), s.bytes.end());
				const Decision whole = classify_bytes(all);
				CHECK(whole.outcome == Outcome::classified && whole.proto == s.proto, "the sample of " << s.source << " is not classified as " << name(s.proto));
				for (std::size_t k = 1; k < all.size(); ++k)
				{
					const Buf first(all.begin(), all.begin() + static_cast<std::ptrdiff_t>(k));
					const Decision d1 = classify_bytes(first);
					if (k < whole.at)
					{
						CHECK(d1.outcome == Outcome::more, s.source << " split at " << k << ": decided early");
						CHECK(d1.at > k && d1.at <= kBDec, s.source << " split at " << k << ": low-water mark " << d1.at);
					}
					else
					{
						CHECK(d1 == whole, s.source << " split at " << k << ": a different decision after the decision length");
					}
					CHECK(classify_bytes(all) == whole, s.source << " split at " << k << ": the whole differs");
				}
			}
			return std::nullopt;
		}

		/// Every first byte: undecided if a matcher's first-byte set holds it, rejected at byte 1
		/// otherwise; the only bucket with two matchers is 'P'.
		Result first_bytes()
		{
			std::size_t accepted = 0;
			for (unsigned v = 0; v < 256; ++v)
			{
				const Decision d = classify_bytes(Buf{static_cast<std::byte>(v)});
				bool any = false;
				for (const Matcher& m : kTable) any = any || m.first.has(static_cast<std::uint8_t>(v));
				if (any)
				{
					++accepted;
					CHECK(d.outcome == Outcome::more, "byte " << v << " is a first byte but is not undecided");
				}
				else
				{
					CHECK(d.outcome == Outcome::rejected && d.at == 1, "byte " << v << " is no first byte but is not rejected at 1");
				}
			}
			CHECK(accepted == 11, accepted << " first bytes; the frozen table has 11 (0x16, P, CR, G, H, D, C, O, T, S, 0x10)");
			CHECK(kBuckets['P'].count == 2, "the P bucket");
			return std::nullopt;
		}

		/// The order of the table cannot change a decision: every input of one and two bytes, and
		/// every corpus sample with any one byte replaced by any value, classify alike in the
		/// bucket order and reversed.
		Result order()
		{
			for (unsigned a = 0; a < 256; ++a)
			{
				for (unsigned b = 0; b < 256; ++b)
				{
					const std::array<std::byte, 2> in{static_cast<std::byte>(a), static_cast<std::byte>(b)};
					CHECK(classify<Order::bucket>(in) == classify<Order::reversed>(in), "order changes the decision of " << a << " " << b);
				}
			}
			for (const auto& s : corpus::kSamples)
			{
				Buf in(s.bytes.begin(), s.bytes.end());
				if (in.size() > kBDec) in.resize(kBDec);
				for (std::size_t i = 0; i < in.size(); ++i)
				{
					const std::byte keep = in[i];
					for (unsigned v = 0; v < 256; ++v)
					{
						in[i] = static_cast<std::byte>(v);
						for (std::size_t len = 1; len <= in.size(); ++len)
						{
							const Bytes p(in.data(), len);
							CHECK(classify<Order::bucket>(p) == classify<Order::reversed>(p), s.source << ": byte " << i << " = " << v);
						}
					}
					in[i] = keep;
				}
			}
			return std::nullopt;
		}

		/// HC16 at run time: the preface with byte k complemented is undecided up to byte k and
		/// rejected at byte k + 1.
		Result hc16()
		{
			for (std::size_t k = 0; k < kH2Preface.size(); ++k)
			{
				Buf p = bytes(kH2Preface);
				p[k] = static_cast<std::byte>(std::to_integer<unsigned>(p[k]) ^ 0xFF);
				const Decision d = classify_bytes(p);
				CHECK(d.outcome == Outcome::rejected && d.at == k + 1, "k = " << k << ": rejected at " << d.at);
			}
			return std::nullopt;
		}

		Result http1_methods()
		{
			for (const std::string_view m : kMethods)
			{
				const Decision d = classify_bytes(bytes(std::string(m) + " /"));
				CHECK(d.outcome == Outcome::classified && d.proto == Proto::http1 && d.at == m.size() + 1, m << " SP");
				const Decision crlf = classify_bytes(bytes("\r\n" + std::string(m) + " /"));
				CHECK(crlf.outcome == Outcome::classified && crlf.at == m.size() + 3, "CRLF " << m << " SP");
				const Decision tab = classify_bytes(bytes(std::string(m) + "\t"));
				CHECK(tab.outcome == Outcome::rejected && tab.at == m.size() + 1, m << " HTAB is rejected at the HTAB");
			}
			CHECK(classify_bytes(bytes("get /")).outcome == Outcome::rejected, "methods are case-sensitive");
			CHECK(classify_bytes(bytes("PRI ")).outcome == Outcome::more, "PRI waits for h2c");
			const Decision pr = classify_bytes(bytes("PRX"));
			CHECK(pr.outcome == Outcome::rejected && pr.at == 3, "PRX: HTTP/1.1 out at 2, h2c at 3");
			const Decision two = classify_bytes(bytes("\r\n\r\nGET "));
			CHECK(two.outcome == Outcome::rejected && two.at == 3, "two leading CRLFs are rejected at the third byte");
			const Decision lf = classify_bytes(bytes("\nGET "));
			CHECK(lf.outcome == Outcome::rejected && lf.at == 1, "a bare LF is no first byte");
			const Decision cr = classify_bytes(bytes("\rG"));
			CHECK(cr.outcome == Outcome::rejected && cr.at == 2, "CR without LF");
			CHECK(classify_bytes(bytes("O")).at == 8, "after O the least is OPTIONS SP, 8 bytes");
			CHECK(classify_bytes(bytes("P")).at == 4, "after P the least is PUT SP, 4 bytes");
			CHECK(classify_bytes(bytes("\r")).at == 6, "after CR the least is CRLF GET SP");
			return std::nullopt;
		}

		Result tls()
		{
			for (unsigned minor = 0; minor < 256; ++minor)
			{
				const Decision d = classify_bytes(bytes({0x16, 0x03, static_cast<int>(minor), 0x00, 0x10, 0x01}));
				CHECK(d.outcome == Outcome::classified && d.proto == Proto::tls && d.at == 6, "record version 03 " << minor);
			}
			CHECK(classify_bytes(bytes({0x16, 0x03, 0x01, 0x40, 0x00, 0x01})).outcome == Outcome::classified, "a record of 2^14");
			const Decision over = classify_bytes(bytes({0x16, 0x03, 0x01, 0x40, 0x01}));
			CHECK(over.outcome == Outcome::rejected && over.at == 5, "2^14 + 1 is rejected at byte 5");
			const Decision high = classify_bytes(bytes({0x16, 0x03, 0x01, 0x41}));
			CHECK(high.outcome == Outcome::rejected && high.at == 4, "a high length byte above 0x40 is rejected at byte 4");
			const Decision not_hello = classify_bytes(bytes({0x16, 0x03, 0x01, 0x00, 0x10, 0x02}));
			CHECK(not_hello.outcome == Outcome::rejected && not_hello.at == 6, "byte 5 must be client_hello");
			const Decision major = classify_bytes(bytes({0x16, 0x02}));
			CHECK(major.outcome == Outcome::rejected && major.at == 2, "byte 1 must be 0x03");
			const Decision zero = classify_bytes(bytes({0x16, 0x03, 0x01, 0x00, 0x00, 0x01}));
			CHECK(zero.outcome == Outcome::classified, "a record length of 0 is within the frozen bound (design/status.md)");
			return std::nullopt;
		}

		Result mqtt()
		{
			const std::array<std::vector<int>, 4> lengths{{{0x0C}, {0x80, 0x01}, {0x80, 0x80, 0x01}, {0x80, 0x80, 0x80, 0x01}}};
			for (const auto& rl : lengths)
			{
				for (const int level : {4, 5})
				{
					std::vector<int> v{0x10};
					v.insert(v.end(), rl.begin(), rl.end());
					v.insert(v.end(), {0x00, 0x04, 'M', 'Q', 'T', 'T', level});
					Buf b;
					for (const int x : v) b.push_back(static_cast<std::byte>(x));
					const Decision d = classify_bytes(b);
					CHECK(d.outcome == Outcome::classified && d.proto == Proto::mqtt && d.at == b.size(),
					      "a Remaining Length of " << rl.size() << " bytes, level " << level);
					b.back() = std::byte{3};
					const Decision l3 = classify_bytes(b);
					CHECK(l3.outcome == Outcome::rejected && l3.at == b.size(), "level 3 is rejected at the level byte");
				}
			}
			const Decision five = classify_bytes(bytes({0x10, 0x80, 0x80, 0x80, 0x80}));
			CHECK(five.outcome == Outcome::rejected && five.at == 5, "a fifth length byte is rejected");
			const Decision isdp = classify_bytes(bytes({0x10, 0x0E, 0x00, 0x06, 'M', 'Q', 'I', 's', 'd', 'p'}));
			CHECK(isdp.outcome == Outcome::rejected && isdp.at == 4, "MQIsdp is rejected at its name length");
			CHECK(classify_bytes(bytes({0x10})).at == 9, "after 0x10 the least is 9 bytes");
			CHECK(classify_bytes(bytes({0x10, 0x80})).at == 10, "after one continued length byte the least is 10 bytes");
			return std::nullopt;
		}

		Result ssh_and_h2c()
		{
			const Decision ssh = classify_bytes(bytes("SSH-"));
			CHECK(ssh.outcome == Outcome::classified && ssh.proto == Proto::ssh && ssh.at == 4, "SSH-");
			const Decision under = classify_bytes(bytes("SSH_"));
			CHECK(under.outcome == Outcome::rejected && under.at == 4, "SSH_");
			const Buf preface = bytes(kH2Preface);
			for (std::size_t len = 1; len < preface.size(); ++len)
			{
				CHECK(classify_bytes(Buf(preface.begin(), preface.begin() + static_cast<std::ptrdiff_t>(len))).outcome == Outcome::more,
				      "the preface's first " << len << " bytes are undecided");
			}
			const Decision d = classify_bytes(preface);
			CHECK(d.outcome == Outcome::classified && d.proto == Proto::h2c && d.at == 24, "the preface");
			return std::nullopt;
		}

		Result proxy_v1()
		{
			const ProxyResult tcp4 = proxy(bytes("PROXY TCP4 192.0.2.10 198.51.100.20 4711 443\r\nGET"));
			CHECK(tcp4.verdict == ProxyVerdict::done && tcp4.at == 46 && tcp4.version == 1, "TCP4 line, then bytes after it");
			CHECK(tcp4.source.port == 4711 && tcp4.source.addr[0] == 192 && tcp4.source.addr[3] == 10, "TCP4 source");
			const ProxyResult six = proxy(bytes("PROXY TCP6 ::1 ::2 1 2\r\n"));
			CHECK(six.verdict == ProxyVerdict::done && six.source.family == ProxyFamily::inet6 && six.source.addr[15] == 1, "TCP6 ::1");
			CHECK(proxy(bytes("PROXY UNKNOWN whatever\r\n")).verdict == ProxyVerdict::done, "UNKNOWN ignores the rest of the line");
			const char* bad[] = {
				"PROXY TCP4 256.0.2.10 198.51.100.20 4711 443\r\n", "PROXY TCP4 192.0.2.010 198.51.100.20 4711 443\r\n",
				"PROXY TCP4 192.0.2.10 198.51.100.20 65536 443\r\n", "PROXY TCP4 192.0.2.10  198.51.100.20 4711 443\r\n",
				"PROXY TCP5 192.0.2.10 198.51.100.20 4711 443\r\n", "PROXY TCP4 192.0.2.10 198.51.100.20 4711\r\n",
				"PROXY TCP6 1::2::3 ::1 1 2\r\n",                     "PROXY TCP4 192.0.2.10 198.51.100.20 4711 443\rX",
				"PROXYTCP4 1.2.3.4 1.2.3.4 1 2\r\n",
			};
			for (const char* b : bad)
			{
				const ProxyResult r = proxy(bytes(b));
				CHECK(r.verdict == ProxyVerdict::no && r.reason == ProxyReason::malformed, "malformed v1 accepted: " << b);
			}
			const ProxyResult g = proxy(bytes("G"));
			CHECK(g.verdict == ProxyVerdict::no && g.reason == ProxyReason::prefix && g.at == 1, "a first byte of neither version");
			const std::string_view prefix = "PROXY";
			for (std::size_t i = 1; i < prefix.size(); ++i)
			{
				const ProxyResult r = proxy(bytes(std::string(prefix.substr(0, i)) + "x"));
				CHECK(r.verdict == ProxyVerdict::no && r.reason == ProxyReason::prefix && r.at == i + 1, "v1 prefix mismatch at " << i + 1);
			}
			CHECK(proxy(bytes("PROXY")).verdict == ProxyVerdict::more && proxy(bytes("PROXY")).at == 8, "v1 needs 8 bytes");
			std::string longest = "PROXY UNKNOWN ";
			longest.resize(kProxyV1Max, 'x');
			const ProxyResult too_long = proxy(bytes(longest));
			CHECK(too_long.verdict == ProxyVerdict::no && too_long.reason == ProxyReason::too_long && too_long.at == kProxyV1Max,
			      "107 bytes without CRLF are too long");
			std::string fits = "PROXY UNKNOWN ";
			fits.resize(kProxyV1Max - 2, 'x');
			fits += "\r\n";
			CHECK(proxy(bytes(fits)).verdict == ProxyVerdict::done, "a 107-byte line fits");
			return std::nullopt;
		}

		Buf v2(int ver_cmd, int fam, std::size_t len, std::size_t body)
		{
			Buf b;
			for (const std::uint8_t x : kProxyV2Sig) b.push_back(static_cast<std::byte>(x));
			b.push_back(static_cast<std::byte>(ver_cmd));
			b.push_back(static_cast<std::byte>(fam));
			b.push_back(static_cast<std::byte>(len >> 8));
			b.push_back(static_cast<std::byte>(len & 0xFF));
			b.resize(16 + body, std::byte{0});
			return b;
		}

		Result proxy_v2()
		{
			for (std::size_t i = 0; i < kProxyV2Sig.size(); ++i)
			{
				Buf in;
				for (std::size_t k = 0; k <= i; ++k) in.push_back(static_cast<std::byte>(kProxyV2Sig[k]));
				in[i] = static_cast<std::byte>(std::to_integer<unsigned>(in[i]) ^ 0x01);
				const ProxyResult r = proxy(in);
				CHECK(r.verdict == ProxyVerdict::no && r.reason == ProxyReason::prefix && r.at == i + 1, "v2 signature mismatch at " << i + 1);
			}
			const ProxyResult v1 = proxy(v2(0x11, 0x11, 12, 12));
			CHECK(v1.verdict == ProxyVerdict::no && v1.reason == ProxyReason::prefix && v1.at == 13, "version 1 in byte 13");
			const ProxyResult cmd = proxy(v2(0x22, 0x11, 12, 12));
			CHECK(cmd.verdict == ProxyVerdict::no && cmd.reason == ProxyReason::malformed && cmd.at == 13, "command 2");
			const ProxyResult fam = proxy(v2(0x21, 0x41, 12, 12));
			CHECK(fam.verdict == ProxyVerdict::no && fam.reason == ProxyReason::malformed && fam.at == 14, "family 4");
			CHECK(proxy(v2(0x21, 0x11, 520, 520)).verdict == ProxyVerdict::no, "a v2 header of 536 bytes with zero TLV bytes is malformed TLVs");
			Buf ok = v2(0x21, 0x11, 520, 520);
			ok[28] = std::byte{0x04};  // one NOOP TLV over the rest: 508 = 3 + 505
			ok[29] = std::byte{0x01};
			ok[30] = std::byte{0xF9};
			const ProxyResult at_limit = proxy(ok);
			CHECK(at_limit.verdict == ProxyVerdict::done && at_limit.at == kProxyV2Max, "536 bytes with a NOOP TLV");
			const ProxyResult over = proxy(v2(0x21, 0x11, 521, 0));
			CHECK(over.verdict == ProxyVerdict::no && over.reason == ProxyReason::too_long && over.at == 16, "537 bytes are rejected at the length field");
			const ProxyResult short_addr = proxy(v2(0x21, 0x21, 12, 12));
			CHECK(short_addr.verdict == ProxyVerdict::no && short_addr.reason == ProxyReason::malformed, "an IPv6 block of 12 bytes");
			const ProxyResult local = proxy(v2(0x20, 0x00, 0, 0));
			CHECK(local.verdict == ProxyVerdict::done && local.source.family == ProxyFamily::local, "LOCAL");
			const ProxyResult unspec = proxy(v2(0x21, 0x00, 4, 4));
			CHECK(unspec.verdict == ProxyVerdict::done && unspec.source.family == ProxyFamily::unspec && unspec.at == 20, "AF_UNSPEC skips its block");
			Buf six = v2(0x21, 0x21, 36, 36);
			six[16] = std::byte{0x20};
			six[48] = std::byte{0x12};
			six[49] = std::byte{0x67};
			const ProxyResult r6 = proxy(six);
			CHECK(r6.verdict == ProxyVerdict::done && r6.source.family == ProxyFamily::inet6 && r6.source.addr[0] == 0x20 && r6.source.port == 4711, "IPv6");
			const Buf full(corpus::kProxyV2Tcp4.begin(), corpus::kProxyV2Tcp4.end());
			for (std::size_t len = 1; len < full.size(); ++len)
			{
				const ProxyResult r = proxy(Buf(full.begin(), full.begin() + static_cast<std::ptrdiff_t>(len)));
				CHECK(r.verdict == ProxyVerdict::more && r.at > len, "split at " << len);
			}
			Buf overrun = v2(0x21, 0x11, 16, 16);
			overrun[28] = std::byte{0x04};
			overrun[30] = std::byte{0x09};  // a TLV of 9 bytes in a block of 4
			CHECK(proxy(overrun).verdict == ProxyVerdict::no, "a TLV past the header");
			return std::nullopt;
		}

		Result budgets()
		{
			std::uint32_t most = 0;
			for (const Matcher& m : kTable) most = std::max(most, m.need_max);
			CHECK(most == kBDec, "B_dec is the largest need (h2c, 24)");
			CHECK(kPeekWindow == 536 + 24, "the peek window is the longest v2 header and B_dec");
			return std::nullopt;
		}

	}  // namespace

	void register_detect_tests(Registry& r)
	{
		r["detect.corpus_splits"] = corpus_splits;
		r["detect.first_bytes"] = first_bytes;
		r["detect.order"] = order;
		r["detect.hc16"] = hc16;
		r["detect.http1_methods"] = http1_methods;
		r["detect.tls"] = tls;
		r["detect.mqtt"] = mqtt;
		r["detect.ssh_h2c"] = ssh_and_h2c;
		r["detect.proxy_v1"] = proxy_v1;
		r["detect.proxy_v2"] = proxy_v2;
		r["detect.budgets"] = budgets;
	}

}  // namespace oneport::test
