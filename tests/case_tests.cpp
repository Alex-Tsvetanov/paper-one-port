// The hard cases (hypotheses.md, Appendix A) as a deterministic suite: B1's conformance table and
// B2's bounds (section 5.2), per CTest entry on one backend (epoll or io_uring), one dispatch mode
// (in-process, or relay to a backend server in dedicated mode) and one detection mode.
//
// For each variant of a case: the script runs `replicates` times against a one-port server with
// the variant's listener setup; each run's outcome, transcript and server report are checked
// against the frozen expectation (bench/cases/cases.cpp), and the B2 bounds against the report:
//   (a, b) a timed event is never early and is handled in the first pass whose wait returned at or
//          after its deadline (prev_wait_return < deadline <= wait_return);
//   (c)    a classification happens in the pass of the receive or peek that brought its byte;
//   (d)    a pending connection held at most its mode's bytes in user space (replay: the handler's
//          buffer; peek: none) and no data buffer while it had no byte;
//   (e)    a half-close before a decision closed the connection in the pass that observed it.
// The client side checks each timer from below on the same clock: an end that came "at T" came no
// sooner than T after the client's own reference, which precedes the server's.
//
// Transcripts. "The transcript equals the dedicated port's" is checked byte for byte, except for
// TLS: a handshake's wire bytes differ on every connection, so a TLS exchange is compared after
// decryption, with what the handshake negotiated (design/status.md, M2a readings). Each dedicated
// transcript is also checked against what its handler sends (I26), so the two cannot agree on a
// wrong exchange.
//
// Relay dispatch (proposal I17): the one-port server relays to a server in dedicated mode on the
// same backend, with PROXY off (the front consumes the header, design/status.md M2b). The
// reference transcript is the same script against a dedicated server with the variant's PROXY
// setting, so it is the client's view of the dedicated port either way. Every connection the
// front classifies, or dispatches to the fallback, must report one route: by class to the
// backend port of its class, or for TLS by its ClientHello's SNI (pass-through; HC20's "routed by
// its SNI"), holding in replay no more than the ClientHello's records and in peek nothing.
//
// Output: one line per variant (PASS, or PASS-PARTIAL with a part pending), then a summary.
// Nothing received is printed beyond counts and printable first lines.
#include "test_support.hpp"

#if defined(__linux__) || defined(_WIN32)

#include "apps.hpp"
#include "cases.hpp"
#include "harness.hpp"
#include "http1.hpp"

#include <algorithm>
#include <cstdio>
#include <map>
#include <memory>

namespace oneport::test
{

	namespace
	{

		using namespace std::chrono_literals;
		using opcase::Coverage;
		using opcase::Expect;
		using opcase::Reply;
		using opcase::Setup;
		using opcase::Variant;
		using opcase::When;

		server::Outcome outcome_of(Expect e)
		{
			switch (e)
			{
				case Expect::classified: return server::Outcome::classified;
				case Expect::rejected: return server::Outcome::rejected;
				case Expect::undecided: return server::Outcome::undecided;
				case Expect::silent: return server::Outcome::silent;
				case Expect::fallback: return server::Outcome::fallback;
				case Expect::proxy_rejected: return server::Outcome::proxy_rejected;
				case Expect::proxy_timeout: return server::Outcome::proxy_timeout;
				case Expect::reset: return server::Outcome::reset;
			}
			return server::Outcome::stopped;
		}

		bool proxy_of(Setup s) { return s == Setup::proxy || s == Setup::proxy_fallback_smtp; }
		bool fallback_of(Setup s) { return s == Setup::fallback_smtp || s == Setup::proxy_fallback_smtp; }

		/// The servers of one entry, started when a variant first needs them.
		class Servers
		{
		public:
			Servers(Detect detect, const opcase::SuiteParams& p, Backend backend, Dispatch dispatch)
				: detect_(detect), p_(p), backend_(backend), dispatch_(dispatch)
			{
			}

			bool relays() const { return dispatch_ == Dispatch::relay; }

			/// The relay's backend: a server in dedicated mode with PROXY off.
			Running& relay_backend() { return dedicated(false); }

			/// The servers are kept only once started: a server that cannot start throws, and no
			/// entry is left behind for stop_and_check().
			Running& one_port(Setup s)
			{
				if (const auto it = one_port_.find(s); it != one_port_.end()) return *it->second;
				ServerArgs a = base();
				a.mode = Mode::one_port;
				a.proxy = proxy_of(s) ? Proxy::on : Proxy::off;
				a.fallback = fallback_of(s) ? Fallback::smtp : Fallback::none;
				if (relays())
				{
					a.dispatch = Dispatch::relay;
					a.relay_port = relay_backend().port(0);
				}
				auto started = std::make_unique<Running>(a);
				return *one_port_.emplace(s, std::move(started)).first->second;
			}

			Running& dedicated(bool proxy)
			{
				if (const auto it = dedicated_.find(proxy); it != dedicated_.end()) return *it->second;
				ServerArgs a = base();
				a.mode = Mode::dedicated;
				a.proxy = proxy ? Proxy::on : Proxy::off;
				auto started = std::make_unique<Running>(a);
				return *dedicated_.emplace(proxy, std::move(started)).first->second;
			}

			/// Stops every server and checks each (harness.hpp); the fronts first, then their backend.
			Result stop_and_check()
			{
				for (auto& [s, r] : one_port_)
				{
					if (auto bad = r->stop_and_check()) return "one-port server (" + std::string(opcase::name(s)) + "): " + *bad;
					if (relays())
					{
						const server::Counters t = r->server->totals();
						CHECK(t.relay_connect_errors == 0, "one-port server (" << opcase::name(s) << "): " << t.relay_connect_errors << " connects to the backend failed");
					}
				}
				for (auto& [proxy, r] : dedicated_)
				{
					if (auto bad = r->stop_and_check()) return std::string("dedicated server") + (proxy ? " (PROXY)" : "") + ": " + *bad;
				}
				return std::nullopt;
			}

		private:
			ServerArgs base() const
			{
				ServerArgs a;
				a.detect = detect_;
				a.backend = backend_;
				a.t_fb = p_.t_fb;
				a.t_dec = p_.t_dec;
				a.t_hdr = p_.t_hdr;
				return a;
			}

			Detect detect_;
			opcase::SuiteParams p_;
			Backend backend_;
			Dispatch dispatch_;
			std::map<Setup, std::unique_ptr<Running>> one_port_;
			std::map<bool, std::unique_ptr<Running>> dedicated_;
		};

		/// Runs a script against a port and waits for the server to close the connection.
		Result run_one(Running& srv, const opcase::Script& s, std::uint16_t port, opcase::Transcript& t, std::vector<server::DetectionReport>& reps,
		               std::vector<server::RelayReport>* relays = nullptr)
		{
			t = opcase::run(s, port);
			CHECK(t.connected, "connect failed");
			CHECK(!t.timed_out, "the client waited past its limit");
			CHECK(srv.collector.wait_close(t.local_port, 10000ms, reps, relays), "the server did not close the connection");
			return std::nullopt;
		}

		/// Relay dispatch: the route of a connection the front classified or sent to the fallback.
		Result check_route(const Variant& v, Detect detect, const server::DetectionReport& r, const std::vector<server::RelayReport>& relays, Running& backend)
		{
			const bool handed = r.outcome == server::Outcome::classified || r.outcome == server::Outcome::fallback;
			if (!handed)
			{
				CHECK(relays.empty(), "a connection whose detection ended was relayed");
				return std::nullopt;
			}
			CHECK(relays.size() == 1, relays.size() << " route reports for one relayed connection");
			const server::RelayReport& rr = relays[0];
			const bool tls = r.proto == detect::Proto::tls;
			CHECK(rr.route == (tls ? server::Route::by_sni : server::Route::by_class),
			      "routed " << server::name(rr.route) << "; " << (tls ? "TLS passes through by its SNI" : "a class goes to its port"));
			CHECK(rr.backend_port == backend.port_of(r.proto), "relayed to port " << rr.backend_port << ", not the backend's " << detect::name(r.proto) << " port");
			if (tls)
			{
				CHECK(rr.hello_len > 0 && rr.hello_len <= detect::kBCh && rr.hello_records >= 1, "the ClientHello was not reassembled within B_CH");
				if (v.id == "HC20") CHECK(rr.hello_records == 2, "HC20's ClientHello came in " << rr.hello_records << " records, not 2");
				// B2(d) in pass-through: the partial ClientHello's records in replay, nothing in peek.
				const std::uint32_t bound = detect == Detect::replay ? rr.hello_len + 5 * rr.hello_records : 0;
				CHECK(rr.held_max <= bound, "held " << rr.held_max << " bytes waiting for the ClientHello; the bound is " << bound << " (B2 d)");
			}
			return std::nullopt;
		}

		/// Two TLS exchanges agree: both handshakes completed with the frozen settings, the same
		/// ALPN, and the same decrypted bytes.
		Result same_tls(const opcase::Transcript& t, const opcase::Transcript& d)
		{
			CHECK(t.tls && d.tls, "a TLS exchange has no TLS result");
			for (const opcase::TlsResult* r : {&*t.tls, &*d.tls})
			{
				CHECK(r->handshake, "a handshake did not complete: " << r->error);
				CHECK(r->version == "TLSv1.3" && r->cipher == "TLS_AES_128_GCM_SHA256" && r->group == "x25519",
				      "negotiated " << r->version << ", " << r->cipher << ", " << r->group);
				CHECK(r->sigalg == "ecdsa_secp256r1_sha256", "the server signed with " << r->sigalg);
				CHECK(r->verified, "the server's certificate did not verify for oneport.test");
				CHECK(!r->resumable, "a session ticket arrived (num_tickets is 0)");
			}
			CHECK(t.tls->alpn == d.tls->alpn, "ALPN " << t.tls->alpn << " against the dedicated port's " << d.tls->alpn);
			CHECK(t.tls->plain == d.tls->plain, "the decrypted transcript differs from the dedicated port's: " << t.tls->plain.size() << " bytes ('"
			                                                                                                  << opcase::first_line(t.tls->plain) << "') against "
			                                                                                                  << d.tls->plain.size());
			CHECK(t.tls->close_notify == d.tls->close_notify, "close_notify in one exchange only");
			return std::nullopt;
		}

		/// A TLS server flight: the first record is a handshake record holding a ServerHello.
		Result tls_flight(const opcase::Transcript& t)
		{
			const auto& b = t.received;
			CHECK(b.size() >= 10, "no TLS record came back (" << b.size() << " bytes)");
			CHECK(std::to_integer<int>(b[0]) == 0x16 && std::to_integer<int>(b[1]) == 0x03 && std::to_integer<int>(b[5]) == 0x02,
			      "the first record is not a ServerHello");
			CHECK(t.eof || t.reset, "the connection was not closed");
			return std::nullopt;
		}

		bool starts_with(const opcase::Bytes& b, std::string_view prefix)
		{
			return b.size() >= prefix.size() && std::equal(prefix.begin(), prefix.end(), b.begin(), [](char c, std::byte x) { return static_cast<unsigned char>(c) == std::to_integer<unsigned char>(x); });
		}

		bool contains(const opcase::Bytes& b, std::string_view needle)
		{
			const opcase::Bytes n = opcase::text(needle);
			return std::search(b.begin(), b.end(), n.begin(), n.end()) != b.end();
		}

		/// What the dedicated port of class `p` must have sent for the variant's script (I26).
		Result dedicated_is_real(detect::Proto p, const Variant& v, const opcase::Transcript& d)
		{
			using detect::Proto;
			switch (p)
			{
				case Proto::http1:
					CHECK(d.received == opcase::text(http1::kResponse200), "the dedicated HTTP/1.1 port did not answer 200");
					break;
				case Proto::h2c:
					CHECK(d.received.size() > 9 && std::to_integer<int>(d.received[3]) == 0x04, "the dedicated h2c port did not begin with SETTINGS");
					CHECK(contains(d.received, "Hello, World!"), "the dedicated h2c port sent no body");
					break;
				case Proto::tls:
					CHECK(d.tls && d.tls->handshake, "the dedicated TLS port did not complete the handshake");
					CHECK(d.tls->plain == opcase::text(http1::kResponse200), "the dedicated TLS port did not answer 200");
					break;
				case Proto::mqtt:
					CHECK(starts_with(d.received, std::string_view("\x20\x02\x00\x00", 4)) || starts_with(d.received, std::string_view("\x20\x03\x00\x00\x00", 5)),
					      "the dedicated MQTT port did not answer CONNACK: " << d.received.size() << " bytes, eof " << d.eof << ", reset " << d.reset
					                                                            << ", write failed " << d.write_failed);
					break;
				case Proto::ssh:
					CHECK(d.received == opcase::text(apps::kSshBanner), "the dedicated SSH port did not send its line alone");
					break;
				case Proto::smtp:
					CHECK(starts_with(d.received, apps::kSmtpGreeting), "the dedicated SMTP port did not greet");
					if (v.id == "HC07.late") CHECK(contains(d.received, apps::kSmtpUnknown), "the request got no 500");
					break;
			}
			return std::nullopt;
		}

		Result check_reply(Reply want, const opcase::Transcript& t, const opcase::Transcript* dedicated)
		{
			switch (want)
			{
				case Reply::dedicated:
					CHECK(dedicated != nullptr, "no dedicated transcript");
					if (t.tls || dedicated->tls)
					{
						if (auto bad = same_tls(t, *dedicated)) return bad;
					}
					else
					{
						CHECK(t.received == dedicated->received, "the transcript differs from the dedicated port's: " << t.received.size() << " bytes ('"
						                                                                                              << opcase::first_line(t.received) << "') against "
						                                                                                              << dedicated->received.size());
					}
					CHECK(t.eof && !t.reset && dedicated->eof && !dedicated->reset, "both must end with the server's EOF");
					return std::nullopt;
				case Reply::tls_flight: return tls_flight(t);
				case Reply::http200:
					CHECK(t.received == opcase::text(http1::kResponse200) && t.eof, "no 200 then EOF: " << t.received.size() << " bytes");
					return std::nullopt;
				case Reply::http400:
					CHECK(t.received == opcase::text(http1::kResponse400) && t.eof, "no 400 then EOF: " << t.received.size() << " bytes");
					return std::nullopt;
				case Reply::closed:
					CHECK(t.received.empty(), "a reply of " << t.received.size() << " bytes ('" << opcase::first_line(t.received) << "') where none is expected");
					CHECK(t.eof || t.reset, "the connection was not closed");
					return std::nullopt;
				case Reply::any: return std::nullopt;
			}
			return std::nullopt;
		}

		/// One replicate of a variant against the one-port server: B1 and B2.
		Result check_run(const Variant& v, Detect detect, const opcase::SuiteParams& p, Running& srv, const opcase::Transcript& t,
		                 const std::vector<server::DetectionReport>& reps, const opcase::Transcript* dedicated)
		{
			CHECK(reps.size() == 1, reps.size() << " detection reports for one connection");
			const server::DetectionReport& r = reps[0];
			// B1: the outcome, the class and the transcript.
			CHECK(r.outcome == outcome_of(v.expect), "outcome " << server::name(r.outcome) << ", expected " << opcase::name(v.expect));
			if (v.expect == Expect::classified || v.expect == Expect::fallback)
			{
				CHECK(r.proto == v.proto, "class " << detect::name(r.proto) << ", expected " << detect::name(v.proto));
			}
			if (v.at) CHECK(r.at == *v.at, "decided at byte " << r.at << ", expected " << *v.at);
			if (v.source) CHECK(r.has_proxy && r.proxy == *v.source, "the recorded source is not the PROXY header's");
			if (v.proxy_reason) CHECK(r.proxy_reason == *v.proxy_reason, "the PROXY header was refused for another reason");
			if (auto bad = check_reply(v.reply, t, dedicated)) return bad;
			// When it ended, from the server's record and, for timers, from the client's clock.
			const server::TimePoint anchor = v.header_write ? t.write_times.at(*v.header_write) : t.before_connect;
			switch (v.when)
			{
				case When::at_once:
					CHECK(!r.timed, "ended by " << server::name(r.event.kind) << ", expected at once");
					if (v.expect == Expect::classified || v.expect == Expect::rejected || v.expect == Expect::proxy_rejected)
					{
						CHECK(r.end_pass == r.last_read_pass, "decided in pass " << r.end_pass << ", the deciding bytes came in pass " << r.last_read_pass << " (B2 c)");
					}
					if (v.expect == Expect::undecided || v.expect == Expect::silent)
					{
						CHECK(r.observe_pass != 0 && r.end_pass == r.observe_pass, "closed in pass " << r.end_pass << ", the half-close was observed in pass "
						                                                                         << r.observe_pass << " (B2 e)");
					}
					break;
				case When::t_fb:
					CHECK(r.timed && r.event.kind == server::TimerKind::t_fb && r.event.result == server::TimerResult::fallback, "not dispatched by T_fb");
					if (auto bad = srv.check_timed(r.event)) return bad;
					CHECK(t.first_byte && *t.first_byte - anchor >= p.t_fb, "the fallback spoke before T_fb on the client's clock");
					break;
				case When::t_dec:
					CHECK(r.timed && r.event.kind == server::TimerKind::t_dec, "not closed by T_dec");
					if (auto bad = srv.check_timed(r.event)) return bad;
					CHECK(t.end && *t.end - anchor >= p.t_dec, "closed before T_dec on the client's clock");
					break;
				case When::t_hdr:
					CHECK(r.timed && r.event.kind == server::TimerKind::t_hdr, "not closed by T_hdr");
					if (auto bad = srv.check_timed(r.event)) return bad;
					CHECK(t.end && *t.end - anchor >= p.t_hdr, "closed before T_hdr on the client's clock");
					break;
			}
			if (v.expect == Expect::classified) CHECK(r.end_pass == r.last_read_pass, "classified in pass " << r.end_pass << ", not in the pass of its byte (B2 c)");
			// B2 (d): user-space payload while pending, and no buffer without a byte.
#if defined(_WIN32)
			// IOCP: after an undecided peek switched the connection to replay (I11), replay's bound
			// applies to it (design/status-m6.md, readings).
			const std::uint32_t bound = (detect == Detect::replay || r.replayed) ? server::kRecvBuf : 0;
#else
			const std::uint32_t bound = detect == Detect::replay ? server::kRecvBuf : 0;
#endif
			CHECK(r.max_user_bytes <= bound, "held " << r.max_user_bytes << " payload bytes in user space while pending; the bound is " << bound << " (B2 d)");
			CHECK(!r.buffer_while_silent, "held a data buffer while no byte had arrived (B2 d)");
			// The timers start at accept, or when the PROXY header is complete.
			if (r.has_proxy && (v.when == When::t_fb || v.when == When::t_dec)) CHECK(r.timers_start > r.accept_time, "the timers did not wait for the PROXY header");
			return std::nullopt;
		}

		std::string_view coverage_word(Coverage c)
		{
			switch (c)
			{
				case Coverage::full: return "PASS";
				case Coverage::partial: return "PASS-PARTIAL";
			}
			return "?";
		}

		bool is_split_case(int hc) { return hc == 2 || hc == 3 || hc == 10 || hc == 20; }

	}  // namespace

	int run_case(int hc, std::string_view backend_name, std::string_view dispatch_name, std::string_view mode_name)
	{
		const Detect detect = mode_name == "peek" ? Detect::peek : Detect::replay;
#if defined(_WIN32)
		const Backend backend = Backend::iocp;  // the one backend Windows compiles
#else
		const Backend backend = backend_name == "io_uring" ? Backend::io_uring : Backend::epoll;
#endif
		const Dispatch dispatch = dispatch_name == "relay" ? Dispatch::relay : Dispatch::inproc;
		const std::string label = std::string(backend_name) + " " + std::string(dispatch_name) + " " + std::string(mode_name);
		const opcase::SuiteParams p;
		char hcid[8];
		std::snprintf(hcid, sizeof(hcid), "HC%02d", hc);
		std::printf("%s (%s), %s: %u replicates; suite timers %lld ms, GAP_SPLIT stand-in %lld ms, G stand-in %lld ms\n", hcid,
		            std::string(opcase::title(hc)).c_str(), label.c_str(), p.replicates, static_cast<long long>(p.t_dec.count()),
		            static_cast<long long>(p.gap_split.count()), static_cast<long long>(p.g.count()));
		std::vector<Variant> vs;
		try
		{
			vs = opcase::variants(hc, p);
		}
		catch (const std::exception& e)
		{
			std::printf("FAIL: %s: building the variants: %s\n", hcid, e.what());
			return 1;
		}
		Servers servers(detect, p, backend, dispatch);
		std::map<Coverage, int> passed;
		int failed = 0;
		for (const Variant& v : vs)
		{
			Result bad;
			unsigned split_seen = 0;
			try
			{
				// The reference transcript: the same script against the dedicated port, once.
				opcase::Transcript ded;
				std::vector<server::DetectionReport> ded_reps;
				const bool proxy = proxy_of(v.setup);
				if (v.reply == Reply::dedicated)
				{
					Running& d = servers.dedicated(proxy);
					bad = run_one(d, v.script, d.port_of(v.dedicated), ded, ded_reps);
					if (!bad) bad = dedicated_is_real(v.dedicated, v, ded);
					if (bad)
					{
						for (const auto& r : ded_reps) *bad += std::string("; the dedicated port's report: ") + std::string(server::name(r.outcome));
					}
				}
				// Z2: the HTTP/1.1 grammar on invalid input in dedicated mode too.
				if (!bad && v.dedicated_http_reply)
				{
					Running& d = servers.dedicated(proxy);
					opcase::Transcript dt;
					std::vector<server::DetectionReport> dr;
					bad = run_one(d, v.script, d.port_of(detect::Proto::http1), dt, dr);
					if (!bad)
					{
						if (auto b = check_reply(*v.dedicated_http_reply, dt, nullptr)) bad = "dedicated mode: " + *b;
					}
				}
				Running& srv = servers.one_port(v.setup);
				for (unsigned rep = 0; rep < p.replicates && !bad; ++rep)
				{
					opcase::Transcript t;
					std::vector<server::DetectionReport> reps;
					std::vector<server::RelayReport> relays;
					bad = run_one(srv, v.script, srv.port(), t, reps, &relays);
					if (!bad) bad = check_run(v, detect, p, srv, t, reps, v.reply == Reply::dedicated ? &ded : nullptr);
					if (!bad && servers.relays()) bad = check_route(v, detect, reps[0], relays, servers.relay_backend());
					if (bad) bad = "replicate " + std::to_string(rep + 1) + ": " + *bad;
					else if (reps[0].wakeups >= 2) ++split_seen;
				}
			}
			catch (const std::exception& e)
			{
				bad = std::string("exception: ") + e.what();
			}
			if (bad)
			{
				++failed;
				std::printf("FAIL: %s %s: %s\n", v.id.c_str(), label.c_str(), bad->c_str());
				continue;
			}
			++passed[v.coverage];
			std::printf("%s %s %s: %u/%u", std::string(coverage_word(v.coverage)).c_str(), v.id.c_str(), label.c_str(), p.replicates, p.replicates);
			if (is_split_case(hc)) std::printf("; detection woke %u of %u times more than once", split_seen, p.replicates);
			if (!v.pending.empty()) std::printf("; pending: %s", v.pending.c_str());
			std::printf("\n");
		}
		const Result end = servers.stop_and_check();
		if (end)
		{
			++failed;
			std::printf("FAIL: %s %s: after the runs: %s\n", hcid, label.c_str(), end->c_str());
		}
		std::printf("SUMMARY %s %s: variants %zu; full %d, partial %d; failed %d\n", hcid, label.c_str(), vs.size(), passed[Coverage::full],
		            passed[Coverage::partial], failed);
		std::fflush(stdout);
		return failed == 0 ? 0 : 1;
	}

}  // namespace oneport::test

#else

#include <cstdio>

namespace oneport::test
{
	int run_case(int, std::string_view, std::string_view, std::string_view)
	{
		std::printf("the case suite runs on Linux\n");
		return 77;
	}
}  // namespace oneport::test

#endif
