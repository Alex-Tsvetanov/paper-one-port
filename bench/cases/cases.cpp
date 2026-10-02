#include "cases.hpp"

#include <array>
#include <cstdio>
#include <stdexcept>

namespace oneport::opcase
{

	namespace
	{

		using detect::Proto;
		using std::chrono::milliseconds;

		/// One protocol's opening, as HC1 sends it: the whole exchange of WL1 that a script can
		/// write without reading (hypotheses.md, section 3), so the handler's reply is the
		/// transcript. TLS runs the live client of script.hpp; `bytes` is then the recorded
		/// ClientHello, which HC4 drips.
		struct Opening
		{
			std::string_view name;
			Proto proto;
			Bytes bytes;
			std::uint32_t need_max;  // the matcher's need, at most (section 1)
			std::uint32_t decision;  // where the matcher decides on these bytes
			bool shutdown;           // the client shuts down writing after its bytes
			bool live_tls;           // HC1 to HC3 run a live TLS exchange
		};

		std::vector<Opening> openings()
		{
			return {
				{"HTTP", Proto::http1, http_get(), 10, 4, false, false},
				{"h2c", Proto::h2c, h2c_opening(), 24, 24, true, false},
				{"TLS", Proto::tls, recorded_client_hello(), 6, 6, false, true},
				{"MQTT311", Proto::mqtt, cat({mqtt_connect(4, 12), mqtt_disconnect()}), 12, 9, false, false},
				{"MQTT5", Proto::mqtt, cat({mqtt_connect(5, 13), mqtt_disconnect()}), 12, 9, false, false},
				{"SSH", Proto::ssh, ssh_line(), 4, 4, false, false},
			};
		}

		/// The live TLS exchange of the TLS opening: the ClientHello cut at `cuts`, `gap` apart,
		/// then GET with Connection: close (WL1's TLS exchange).
		TlsPlan tls_plan(std::vector<std::size_t> cuts = {}, std::chrono::nanoseconds gap = {})
		{
			TlsPlan t;
			t.cuts = std::move(cuts);
			t.gap = gap;
			t.requests.push_back(http_get());
			return t;
		}

		std::string pad(unsigned k)
		{
			std::array<char, 8> b{};
			std::snprintf(b.data(), b.size(), "%02u", k);
			return b.data();
		}

		/// The variant HC1 expects of an opening: classified; the transcript equals the dedicated port's.
		Variant classified_like_hc1(const Opening& o, std::string id, Script s)
		{
			Variant v;
			v.id = std::move(id);
			if (o.shutdown) s.shutdown_write();
			v.script = std::move(s);
			v.expect = Expect::classified;
			v.proto = o.proto;
			v.when = When::at_once;
			v.reply = Reply::dedicated;
			v.dedicated = o.proto;
			v.at = o.decision;
			return v;
		}

		Variant closed(std::string id, Script s, Expect e, When w)
		{
			Variant v;
			v.id = std::move(id);
			v.script = std::move(s);
			v.expect = e;
			v.when = w;
			v.reply = Reply::closed;
			return v;
		}

		std::vector<Variant> hc01(const SuiteParams&)
		{
			std::vector<Variant> out;
			for (const Opening& o : openings())
			{
				Script s = o.live_tls ? Script{}.tls(tls_plan()) : Script{}.write(o.bytes);
				out.push_back(classified_like_hc1(o, "HC01." + std::string(o.name), std::move(s)));
			}
			return out;
		}

		std::vector<Variant> hc02(const SuiteParams& p)
		{
			std::vector<Variant> out;
			for (const Opening& o : openings())
			{
				for (std::size_t k = 1; k < o.need_max && k < o.bytes.size(); ++k)
				{
					Script s = o.live_tls ? Script{}.tls(tls_plan({k}, p.gap_split)) : Script{}.split(o.bytes, {k}, p.gap_split);
					out.push_back(classified_like_hc1(o, "HC02." + std::string(o.name) + ".k" + pad(static_cast<unsigned>(k)), std::move(s)));
				}
			}
			return out;
		}

		std::vector<Variant> hc03(const SuiteParams& p)
		{
			std::vector<Variant> out;
			for (const Opening& o : openings())
			{
				std::vector<std::size_t> cuts;
				for (std::size_t k = 1; k <= o.need_max && k < o.bytes.size(); ++k) cuts.push_back(k);
				Script s = o.live_tls ? Script{}.tls(tls_plan(cuts, p.drip_gap)) : Script{}.split(o.bytes, cuts, p.drip_gap);
				out.push_back(classified_like_hc1(o, "HC03." + std::string(o.name), std::move(s)));
			}
			return out;
		}

		/// A partial signature dripped so slowly that it is still incomplete at T_dec: the first
		/// decision - 1 bytes, one per write, spread over twice T_dec.
		std::vector<Variant> hc04(const SuiteParams& p)
		{
			std::vector<Variant> out;
			for (const Opening& o : openings())
			{
				const std::size_t n = o.decision - 1;
				const auto gap = std::chrono::duration_cast<std::chrono::nanoseconds>(2 * p.t_dec) / static_cast<long long>(n);
				Script s;
				for (std::size_t i = 0; i < n; ++i)
				{
					if (i > 0) s.gap(gap);
					s.write(slice(o.bytes, i, i + 1));
				}
				s.await_close();
				out.push_back(closed("HC04." + std::string(o.name), std::move(s), Expect::undecided, When::t_dec));
			}
			return out;
		}

		std::vector<Variant> hc05(const SuiteParams&)
		{
			Variant v;
			v.id = "HC05";
			v.script = Script{}.await_line().write(smtp_line("EHLO opcase.test")).write(smtp_line("QUIT")).shutdown_write();
			v.setup = Setup::fallback_smtp;
			v.expect = Expect::fallback;
			v.proto = Proto::smtp;
			v.when = When::t_fb;
			v.reply = Reply::dedicated;
			v.dedicated = Proto::smtp;
			return {v};
		}

		std::vector<Variant> hc06(const SuiteParams&) { return {closed("HC06", Script{}.await_close(), Expect::silent, When::t_dec)}; }

		std::vector<Variant> hc07(const SuiteParams& p)
		{
			Variant late;
			late.id = "HC07.late";
			late.script = Script{}.write_at(Anchor::after_connect, p.t_fb + p.g, http_get()).shutdown_write();
			late.setup = Setup::fallback_smtp;
			late.expect = Expect::fallback;
			late.proto = Proto::smtp;
			late.when = When::t_fb;
			late.reply = Reply::dedicated;
			late.dedicated = Proto::smtp;
			late.pending = "G is the suite's stand-in until the pilot sets G_L";
			Variant twin;
			twin.id = "HC07.twin";
			twin.script = Script{}.write_at(Anchor::before_connect, p.t_fb - p.g, http_get());
			twin.setup = Setup::fallback_smtp;
			twin.expect = Expect::classified;
			twin.proto = Proto::http1;
			twin.reply = Reply::dedicated;
			twin.dedicated = Proto::http1;
			twin.at = 4;
			twin.pending = "G is the suite's stand-in until the pilot sets G_L";
			return {late, twin};
		}

		std::vector<Variant> hc08(const SuiteParams&)
		{
			Variant v = closed("HC08", Script{}.write(smtp_line("EHLO opcase.test")), Expect::rejected, When::at_once);
			v.at = 1;
			return {v};
		}

		Variant proxy_http(std::string id, Script s)
		{
			Variant v;
			v.id = std::move(id);
			v.script = std::move(s);
			v.setup = Setup::proxy;
			v.expect = Expect::classified;
			v.proto = Proto::http1;
			v.reply = Reply::dedicated;
			v.dedicated = Proto::http1;
			v.at = 4;
			v.source = proxy_source();
			return v;
		}

		std::vector<Variant> hc09(const SuiteParams&) { return {proxy_http("HC09", Script{}.write(cat({proxy_v2(), http_get()})))}; }

		std::vector<Variant> hc10(const SuiteParams& p)
		{
			std::vector<Variant> out;
			const Bytes header = proxy_v2();
			const Bytes all = cat({header, http_get()});
			for (std::size_t k = 1; k < header.size(); ++k)
			{
				out.push_back(proxy_http("HC10.k" + pad(static_cast<unsigned>(k)), Script{}.split(all, {k}, p.gap_split)));
			}
			return out;
		}

		std::vector<Variant> hc11(const SuiteParams&)
		{
			Variant v = closed("HC11", Script{}.write(http_get()), Expect::proxy_rejected, When::at_once);
			v.setup = Setup::proxy;
			v.at = 1;
			v.proxy_reason = detect::ProxyReason::prefix;
			return {v};
		}

		std::vector<Variant> hc12(const SuiteParams&)
		{
			Variant v = closed("HC12", Script{}.write(slice(proxy_v2(), 0, 10)).await_close(), Expect::proxy_timeout, When::t_hdr);
			v.setup = Setup::proxy;
			return {v};
		}

		std::vector<Variant> hc13(const SuiteParams&)
		{
			Variant v;
			v.id = "HC13";
			v.script = Script{}.write(cat({proxy_v1(), recorded_client_hello()})).shutdown_write();
			v.setup = Setup::proxy;
			v.expect = Expect::classified;
			v.proto = Proto::tls;
			v.reply = Reply::tls_flight;  // the outcome is "TLS"; a server flight's bytes differ on every connection
			v.at = 6;
			v.source = proxy_source();
			return {v};
		}

		std::vector<Variant> hc14(const SuiteParams&)
		{
			const Bytes mqtt = cat({mqtt_connect(4, 12), mqtt_disconnect()});
			auto ok = [&mqtt](std::string id, const Bytes& header) {
				Variant v;
				v.id = std::move(id);
				v.script = Script{}.write(cat({header, mqtt})).shutdown_write();
				v.setup = Setup::proxy;
				v.expect = Expect::classified;
				v.proto = Proto::mqtt;
				v.reply = Reply::dedicated;
				v.dedicated = Proto::mqtt;
				v.at = 9;
				v.source = proxy_source();
				return v;
			};
			Variant too_long = closed("HC14.537", Script{}.write(cat({proxy_v2(537), mqtt})), Expect::proxy_rejected, When::at_once);
			too_long.setup = Setup::proxy;
			too_long.at = 16;
			too_long.proxy_reason = detect::ProxyReason::too_long;
			return {ok("HC14.tlvs", proxy_v2_alpn_authority()), ok("HC14.536", proxy_v2(detect::kProxyV2Max)), too_long};
		}

		std::vector<Variant> hc15(const SuiteParams&)
		{
			Variant v;
			v.id = "HC15";
			v.script = Script{}.write(proxy_v2()).await_line().shutdown_write();
			v.setup = Setup::proxy_fallback_smtp;
			v.expect = Expect::fallback;
			v.proto = Proto::smtp;
			v.when = When::t_fb;
			v.header_write = 0;
			v.reply = Reply::dedicated;
			v.dedicated = Proto::smtp;
			v.source = proxy_source();
			return {v};
		}

		std::vector<Variant> hc16(const SuiteParams&)
		{
			std::vector<Variant> out;
			for (unsigned k = 0; k < detect::kH2Preface.size(); ++k)
			{
				Bytes b = text(detect::kH2Preface);
				b[k] = static_cast<std::byte>(std::to_integer<unsigned>(b[k]) ^ 0xFF);
				Variant v = closed("HC16.k" + pad(k), Script{}.write(b), Expect::rejected, When::at_once);
				v.at = k + 1;
				out.push_back(v);
			}
			return out;
		}

		std::vector<Variant> hc17(const SuiteParams&)
		{
			Variant one;
			one.id = "HC17.one_crlf";
			one.script = Script{}.write(http_get("\r\n"));
			one.expect = Expect::classified;
			one.proto = Proto::http1;
			one.reply = Reply::dedicated;
			one.dedicated = Proto::http1;
			one.dedicated_http_reply = Reply::http200;
			one.at = 6;
			Variant two = closed("HC17.two_crlf", Script{}.write(http_get("\r\n\r\n")), Expect::rejected, When::at_once);
			two.at = 3;
			two.dedicated_http_reply = Reply::closed;
			return {one, two};
		}

		/// Classified, the client then shuts down writing; the transcript equals the dedicated port's.
		Variant classified_then_eof(std::string id, Script s, Proto p, std::uint32_t at)
		{
			Variant v;
			v.id = std::move(id);
			v.script = std::move(s.shutdown_write());
			v.expect = Expect::classified;
			v.proto = p;
			v.reply = Reply::dedicated;
			v.dedicated = p;
			v.at = at;
			return v;
		}

		std::vector<Variant> hc18(const SuiteParams&) { return {classified_then_eof("HC18", Script{}.write(ssh_line("a comment")), Proto::ssh, 4)}; }

		std::vector<Variant> hc19(const SuiteParams&)
		{
			// The outcome is "TLS": the recorded ClientHello with each record version; a server
			// flight's bytes differ on every connection, so its first record is checked instead.
			Variant v0301 = classified_then_eof("HC19.0301", Script{}.write(with_record_version(recorded_client_hello(), 0x01)), Proto::tls, 6);
			Variant v0303 = classified_then_eof("HC19.0303", Script{}.write(with_record_version(recorded_client_hello(), 0x03)), Proto::tls, 6);
			v0301.reply = Reply::tls_flight;
			v0303.reply = Reply::tls_flight;
			return {v0301, v0303};
		}

		std::vector<Variant> hc20(const SuiteParams& p)
		{
			// A live ClientHello in two records, the first with 40 handshake bytes (a design choice
			// of M1: inside the ClientHello, before its extensions), one write per record.
			TlsPlan t = tls_plan();
			t.fragment_at = 40;
			t.gap = p.gap_split;
			Variant v;
			v.id = "HC20";
			v.script = Script{}.tls(std::move(t));
			v.expect = Expect::classified;
			v.proto = Proto::tls;
			v.reply = Reply::dedicated;  // in-process the handshake completes, and the exchange is the dedicated port's
			v.dedicated = Proto::tls;
			v.at = 6;
			v.pending = "pass-through (routed by its SNI) is the relay's, M2b";
			return {v};
		}

		std::vector<Variant> hc21(const SuiteParams& p)
		{
			Variant partial = closed("HC21.partial", Script{}.write(text("GE")).gap(p.gap_split).shutdown_write(), Expect::undecided, When::at_once);
			Variant none = closed("HC21.none", Script{}.gap(p.gap_split).shutdown_write(), Expect::silent, When::at_once);
			Variant partial_fb = partial;
			partial_fb.id = "HC21.partial.fallback";
			partial_fb.setup = Setup::fallback_smtp;
			Variant none_fb = none;
			none_fb.id = "HC21.none.fallback";
			none_fb.setup = Setup::fallback_smtp;
			return {partial, none, partial_fb, none_fb};
		}

		std::vector<Variant> hc22(const SuiteParams& p)
		{
			Variant partial = closed("HC22.partial", Script{}.write(text("GE")).gap(p.gap_split).reset(), Expect::reset, When::at_once);
			partial.reply = Reply::any;
			Variant none = closed("HC22.none", Script{}.gap(p.gap_split).reset(), Expect::reset, When::at_once);
			none.reply = Reply::any;
			return {partial, none};
		}

		std::vector<Variant> hc23(const SuiteParams&)
		{
			Bytes getx = text("GETX");
			getx.resize(4096, std::byte{'A'});
			Variant a = closed("HC23.GETX", Script{}.write(getx), Expect::rejected, When::at_once);
			a.at = 4;
			a.dedicated_http_reply = Reply::closed;
			Variant b = closed("HC23.A", Script{}.write(Bytes(4096, std::byte{'A'})), Expect::rejected, When::at_once);
			b.at = 1;
			b.dedicated_http_reply = Reply::closed;
			return {a, b};
		}

		std::vector<Variant> hc24(const SuiteParams&)
		{
			std::vector<Variant> out;
			// 12: HC1's CONNECT; 128, 16384 and 2097152: the smallest values that need 2, 3 and 4 bytes.
			const std::array<std::uint32_t, 4> lengths{12, 128, 16384, 2097152};
			for (std::size_t i = 0; i < lengths.size(); ++i)
			{
				out.push_back(classified_then_eof("HC24.rl" + std::to_string(i + 1), Script{}.write(cat({mqtt_connect(4, lengths[i]), mqtt_disconnect()})),
				                              Proto::mqtt, static_cast<std::uint32_t>(9 + i)));
			}
			Variant isdp = closed("HC24.MQIsdp", Script{}.write(mqtt_isdp()), Expect::rejected, When::at_once);
			isdp.at = 4;
			out.push_back(isdp);
			return out;
		}

		std::vector<Variant> hc25(const SuiteParams&)
		{
			Variant v;
			v.id = "HC25";
			v.script = Script{}.write(text("GET key\r\n"));
			v.expect = Expect::classified;
			v.proto = Proto::http1;
			v.reply = Reply::http400;
			v.dedicated_http_reply = Reply::http400;
			v.at = 4;
			return {v};
		}

	}  // namespace

	std::string_view title(int hc)
	{
		static constexpr std::array<std::string_view, kCases> kTitles{
			"the whole signature in one write",
			"split signature, two writes, GAP_SPLIT apart",
			"drip: one byte per write, the whole signature before T_dec",
			"slow drip: a partial signature still incomplete at T_dec",
			"silent client, SMTP fallback, then an SMTP client script",
			"silent client, no fallback",
			"HTTP/1.1 first byte at T_fb + G (SMTP fallback), and its twin at T_fb - G",
			"SMTP client that sends EHLO before any greeting",
			"PROXY v2 header, then an HTTP/1.1 request, in one write",
			"PROXY v2 header split after every byte k inside it, then HTTP/1.1",
			"PROXY listener, no header, plain HTTP/1.1",
			"PROXY v2 header incomplete, then silence",
			"PROXY v1 line, then a TLS ClientHello",
			"PROXY v2 with TLVs, at most 536 bytes, then MQTT; and one longer than 536 bytes",
			"PROXY header complete, then silence, SMTP fallback",
			"the h2 preface with byte k complemented, k from 0 to 23",
			"one leading CRLF, then HTTP/1.1; and two leading CRLFs",
			"SSH identification line with a comment after a space",
			"ClientHello with record version 03 01, and with 03 03",
			"ClientHello fragmented across two TLS records, in two writes",
			"peer shuts down writing after a partial signature; and after no byte",
			"peer resets during detection",
			"4,096 bytes starting GETX; 4,096 bytes of A",
			"MQTT CONNECT with a Remaining Length of 1, 2, 3 and 4 bytes; MQTT 3.1 MQIsdp",
			"GET key and CRLF, as a Redis inline command",
		};
		if (hc < 1 || hc > kCases) return "?";
		return kTitles[static_cast<std::size_t>(hc - 1)];
	}

	std::vector<Variant> variants(int hc, const SuiteParams& p)
	{
		using Fn = std::vector<Variant> (*)(const SuiteParams&);
		static constexpr std::array<Fn, kCases> kCaseFns{hc01, hc02, hc03, hc04, hc05, hc06, hc07, hc08, hc09, hc10, hc11, hc12, hc13,
		                                                 hc14, hc15, hc16, hc17, hc18, hc19, hc20, hc21, hc22, hc23, hc24, hc25};
		if (hc < 1 || hc > kCases) throw std::invalid_argument("opcase: no hard case " + std::to_string(hc));
		return kCaseFns[static_cast<std::size_t>(hc - 1)](p);
	}

	std::string_view name(Setup s)
	{
		switch (s)
		{
			case Setup::plain: return "plain";
			case Setup::fallback_smtp: return "SMTP fallback";
			case Setup::proxy: return "PROXY";
			case Setup::proxy_fallback_smtp: return "PROXY, SMTP fallback";
		}
		return "?";
	}

	std::string_view name(Expect e)
	{
		switch (e)
		{
			case Expect::classified: return "classified";
			case Expect::rejected: return "rejected";
			case Expect::undecided: return "undecided";
			case Expect::silent: return "silent";
			case Expect::fallback: return "fallback";
			case Expect::proxy_rejected: return "proxy_rejected";
			case Expect::proxy_timeout: return "proxy_timeout";
			case Expect::reset: return "reset";
		}
		return "?";
	}

}  // namespace oneport::opcase
