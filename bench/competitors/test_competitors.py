#!/usr/bin/env python3
"""Tests of the competitors' configurations, the probe's judgement and the hand-off runner (M4a).

Pure (every platform): every configuration renders with every field filled and holds what
Appendix B and WL7 ask of its kind; the command lines; nginx's affinity mask; the LISTEN reader;
the session guard (window.guard_pair); the probe's openings and judgement; the hand-off row's
backend rule and ratio.

Integration (Linux, with --build DIR, the build tree of oneport and opgen): the probe of the
server's one-port relay in its M3 configuration (routes, silent and partial cases), and one short
hand-off window of the server's relay for each M3 protocol (the stub, the front, the probe, opgen,
the readings and the row). No competitor binary is needed: those probes run as lab jobs.

    python3 bench/competitors/test_competitors.py [--build DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))

import cases_check  # noqa: E402
import competitors as comp  # noqa: E402
import handoff  # noqa: E402
import probe  # noqa: E402
import window  # noqa: E402

BUILD: Path | None = None
RUN = Path("/tmp/oneport-run")  # only a string in the rendered text; nothing is written there


def rendered(system: str, kind: str, timers: str = "matched") -> str:
    return comp.render(system, kind, 22100, 22110, 14, RUN, timers)


def live(text: str) -> str:
    """A rendered configuration without its comments (# to the end of a line)."""
    return re.sub(r"#.*", "", text)


class Configurations(unittest.TestCase):
    def test_every_configuration_renders(self):
        for s in comp.ORDER:
            for k in comp.KINDS:
                if k == "cases-fallback" and s not in comp.FALLBACK_SYSTEMS:
                    with self.assertRaises(ValueError):
                        rendered(s, k)
                    continue
                text = rendered(s, k)
                self.assertIsNone(comp.TOKEN.search(text), f"{s} {k}")
                self.assertIn("22100", text, f"{s} {k}: the front port")
                self.assertIn(str(22110 + comp.STUB_OFFSET["tls"]), text, f"{s} {k}: the stub's TLS port")
                self.assertIn(str(22110 + comp.STUB_OFFSET["http1"]), text, f"{s} {k}: the stub's HTTP/1.1 port")
                self.assertIn("oneport.test", text, f"{s} {k}: the route by SNI")
                self.assertIn("Appendix B", text, f"{s} {k}: cites the frozen configuration")

    def test_timers(self):
        expect = {"nginx": "preread_timeout {}s", "haproxy": "tcp-request inspect-delay {}s", "envoy": "listener_filters_timeout: {}s",
                  "caddy-l4": "matching_timeout {}s", "sslh-ev": "timeout: {};"}
        for s, form in expect.items():
            self.assertIn(form.format(3), rendered(s, "m3"), s)
            self.assertIn(form.format(60), rendered(s, "b3"), s)

    def test_b3_limits_and_buffers(self):
        n, n2 = str(comp.N_PEND), str(2 * comp.N_PEND)
        self.assertIn(f"backlog={n}", rendered("nginx", "b3"))
        self.assertIn(f"worker_connections {n2}", rendered("nginx", "b3"))
        self.assertIn(f"worker_rlimit_nofile {n2}", rendered("nginx", "b3"))
        self.assertIn(f"maxconn {n2}", rendered("haproxy", "b3"))
        self.assertEqual(rendered("haproxy", "b3").count("option use-small-buffers"), 2)
        e = rendered("envoy", "b3")
        self.assertIn(f"tcp_backlog_size: {n}", e)
        self.assertEqual(e.count("per_connection_buffer_limit_bytes: 32768"), 3)  # the listener and both clusters
        self.assertIn("initial_read_buffer_size: 256", e)
        for s in comp.ORDER:  # M3 carries none of WL7's limits (comments aside)
            m3 = re.sub(r"#.*", "", rendered(s, "m3"))
            self.assertNotIn(n2, m3, s)
            self.assertNotIn("backlog=", m3, s)
            self.assertNotIn("tcp_backlog_size:", m3, s)
            self.assertNotIn("use-small-buffers", m3, s)
            self.assertNotIn("per_connection_buffer_limit_bytes", m3, s)

    def test_m3_settings(self):
        self.assertIn("multi_accept on", rendered("nginx", "m3"))
        self.assertIn("worker_processes 1;", rendered("nginx", "m3"))
        self.assertIn("worker_cpu_affinity 0100000000000000;", rendered("nginx", "m3"))
        self.assertNotIn("access_log", re.sub(r"#.*", "", rendered("nginx", "m3")))
        h = re.sub(r"#.*", "", rendered("haproxy", "m3"))
        self.assertIn("accept if { req.ssl_hello_type 1 }", h)
        self.assertIn("accept if HTTP", h)  # plaintext released at once, not at the delay's end
        self.assertNotIn("splice", h)
        self.assertNotIn("\n    log", h)
        e = rendered("envoy", "m3")
        self.assertIn("max_connections: 1000000000", e)
        self.assertNotIn("access_log", re.sub(r"#.*", "", e))
        self.assertNotIn("admin:", re.sub(r"#.*", "", e))
        s = rendered("sslh-ev", "m3")
        self.assertIn("verbose-connections: 0;", s)
        self.assertIn('on-timeout: "http";', s)
        self.assertEqual(s.count("log_level: 0"), 2)
        self.assertIn("admin 127.0.0.1:22150", rendered("caddy-l4", "m3"))

    def test_render_refuses(self):
        with self.assertRaises(KeyError):
            comp.render_text("x @NOPE@", {"PORT": "1"})
        with self.assertRaises(ValueError):
            comp.fields("m4", 1, 2, 14, RUN)

    def test_cpu_mask(self):
        self.assertEqual(comp.cpu_mask(14), "0100000000000000")
        self.assertEqual(comp.cpu_mask(0), "0000000000000001")
        with self.assertRaises(ValueError):
            comp.cpu_mask(16)

    def test_commands(self):
        cfg, run = Path("/x/m3.conf"), Path("/r")
        self.assertIn("-db", comp.SYSTEMS["haproxy"].command(cfg, run))
        e = comp.SYSTEMS["envoy"].command(cfg, run)
        self.assertEqual(e[e.index("--concurrency") + 1], "1")
        self.assertIn("--disable-hot-restart", e)
        self.assertEqual(comp.SYSTEMS["caddy-l4"].command(cfg, run)[1:3], ["run", "--config"])
        self.assertEqual(comp.SYSTEMS["sslh-ev"].command(cfg, run)[1:], ["-F", str(cfg)])
        n = comp.SYSTEMS["nginx"].command(cfg, run)
        self.assertEqual(n[n.index("-c") + 1], str(cfg))
        for s in comp.ORDER:
            self.assertTrue(str(comp.SYSTEMS[s].binary_path()).startswith(str(comp.OPT)), s)

    def test_pins(self):
        for name in ("NGINX", "HAPROXY", "ENVOY", "XCADDY", "SSLH"):
            self.assertRegex(comp.pin(f"ONEPORT_{name}_SHA256"), r"^[0-9a-f]{64}$", name)
        self.assertRegex(comp.pin("ONEPORT_CADDY_L4_COMMIT"), r"^[0-9a-f]{40}$")

    def test_listening(self):
        text = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
                "   0: 0100007F:55F0 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 1 1\n"
                "   1: 0100007F:55F1 0100007F:9C40 01 00000000:00000000 00:00000000 00000000  1000        0 2 1\n")
        self.assertTrue(comp.parse_listening(text, 0x55F0))
        self.assertFalse(comp.parse_listening(text, 0x55F1))  # established, not listening
        self.assertFalse(comp.parse_listening(text, 0x55F0, "127.0.0.2"))


class Cases(unittest.TestCase):
    """The cases configurations (Appendix B, section 10): every route each system's features
    cover, the PROXY listener, the fallback only in cases-fallback, matched timers or the
    system's defaults."""

    TIMER_LINES = {"nginx": ("preread_timeout 3s;", "proxy_protocol_timeout 3s;"),
                   "haproxy": ("tcp-request inspect-delay 3s", "timeout client-hs 3s"),
                   "envoy": ("listener_filters_timeout: 3s",),
                   "caddy-l4": ("matching_timeout 3s", "timeout 3s"),
                   "sslh-ev": ("timeout: 3;",)}
    # The backend's ports each system routes to (22110 + I20's offsets): HTTP/1.1 0, h2c 1, TLS 2,
    # MQTT 3, SSH 4, SMTP 5 (the fallback only).
    ROUTES = {"nginx": {0, 2}, "haproxy": {0, 1, 2, 3, 4}, "envoy": {0, 1, 2}, "caddy-l4": {0, 1, 2, 3, 4}, "sslh-ev": {0, 2, 3, 4}}

    def test_timers_matched_and_default(self):
        for s, lines in self.TIMER_LINES.items():
            m, d = live(rendered(s, "cases")), live(rendered(s, "cases", "default"))
            for line in lines:
                self.assertIn(line, m, s)
                self.assertNotIn(line, d, s)
            self.assertIn(comp.COMMENT["MATCHED"], rendered(s, "cases", "default"), s)
        with self.assertRaises(ValueError):
            comp.fields("m3", 1, 2, 14, RUN, "default")  # M3 and B3 keep their own timers

    def test_routes_and_proxy_listener(self):
        for s, offs in self.ROUTES.items():
            text = live(rendered(s, "cases"))
            for off in range(6):
                port = str(22110 + off)
                if off in offs:
                    self.assertIn(port, text, f"{s}: backend port +{off}")
                elif not (off == 5 and s in comp.FALLBACK_SYSTEMS):
                    self.assertNotIn(port, text, f"{s}: backend port +{off} has no route")
            self.assertIn(str(22100 + comp.PROXY_PORT_OFFSET), text, f"{s}: the PROXY listener")
        self.assertIn("proxy_protocol;", live(rendered("nginx", "cases")))
        self.assertIn("accept-proxy", live(rendered("haproxy", "cases")))
        self.assertIn("envoy.filters.listener.proxy_protocol", live(rendered("envoy", "cases")))
        self.assertIn("proxy_protocol {", live(rendered("caddy-l4", "cases")))
        self.assertIn("proxyprotocol: true;", live(rendered("sslh-ev", "cases")))

    def test_alpn(self):
        self.assertIn("$ssl_preread_alpn_protocols", live(rendered("nginx", "cases")))
        self.assertIn("req.ssl_alpn -m str h2 http/1.1", live(rendered("haproxy", "cases")))
        self.assertIn('application_protocols: [ "h2", "http/1.1" ]', live(rendered("envoy", "cases")))
        self.assertIn('application_protocols: [ "h2c" ]', live(rendered("envoy", "cases")))
        self.assertIn("alpn h2 http/1.1", live(rendered("caddy-l4", "cases")))
        self.assertIn('alpn_protocols: [ "h2", "http/1.1" ]', live(rendered("sslh-ev", "cases")))
        self.assertIn("envoy.filters.listener.http_inspector", live(rendered("envoy", "cases")))
        self.assertNotIn("http_inspector", live(rendered("envoy", "m3")))  # M4a's reading 11: M3 and B3 hold none

    def test_fallback_only_in_its_kind(self):
        smtp = str(22110 + comp.STUB_OFFSET["smtp"])
        for s in comp.FALLBACK_SYSTEMS:
            self.assertNotIn(smtp, live(rendered(s, "cases")), s)
            self.assertIn(smtp, live(rendered(s, "cases-fallback")), s)
        self.assertIn("default_backend smtp_backend", live(rendered("haproxy", "cases-fallback")))
        e = live(rendered("envoy", "cases-fallback"))
        self.assertEqual(e.count("continue_on_listener_filters_timeout: true"), 2)
        self.assertIn("default_filter_chain:", e)
        self.assertNotIn("continue_on_listener_filters_timeout", live(rendered("envoy", "cases")))
        self.assertIn('on-timeout: "timeout";', live(rendered("sslh-ev", "cases-fallback")))
        self.assertNotIn("on-timeout", live(rendered("sslh-ev", "cases")))

    def test_check_proxy_headers(self):
        v1, v2 = cases_check.proxy_v1(), cases_check.proxy_v2()
        self.assertTrue(v1.startswith(b"PROXY TCP4 ") and v1.endswith(b"\r\n") and len(v1) <= 107)
        self.assertEqual(v2[:12], b"\r\n\r\n\x00\r\nQUIT\n")  # the v2 signature
        self.assertEqual(v2[12:14], b"\x21\x11")  # version 2, PROXY; TCP over IPv4
        self.assertEqual(int.from_bytes(v2[14:16], "big"), 12)
        self.assertEqual(len(v2), 16 + 12)
        self.assertEqual(set(cases_check.COVERS), set(comp.ORDER))

    def test_sslh_list_stays_well_formed(self):
        # The fallback entry carries its own leading comma, so the list has no trailing comma
        # whether that line is live or a comment.
        for kind in comp.CASES_KINDS:
            body = live(rendered("sslh-ev", kind))
            protocols = body[body.index("protocols:"):]
            self.assertNotRegex(protocols, r",\s*\)")


class Guard(unittest.TestCase):
    def test_pairs(self):
        c = comp.ORDER
        window.guard_pair("dedicated", "dedicated", c)
        for s in c:
            window.guard_pair(window.ONE_PORT_RELAY, s, c)
            window.guard_pair(s, window.ONE_PORT_RELAY, c)
            with self.assertRaises(window.WindowError):
                window.guard_pair("dedicated", s, c)  # M4a: no FC5 pair can arise
        for bad in (("one-port", "dedicated"), (window.ONE_PORT_RELAY, "dedicated"), ("dedicated", "one-port-inproc"),
                    ("nginx", "haproxy"), (window.ONE_PORT_RELAY, window.ONE_PORT_RELAY), (window.ONE_PORT_RELAY, "jetty")):
            with self.assertRaises(window.WindowError, msg=str(bad)):
                window.guard_pair(*bad, c)


class Probe(unittest.TestCase):
    def test_openings(self):
        rec = probe.recorded_client_hello()
        self.assertEqual(len(rec), 211)
        self.assertEqual(rec[:5].hex(), "16030100ce")  # a handshake record announcing 206 bytes (WL7's l)
        part = probe.partial_opening()
        self.assertEqual(len(part), 5 + 206 // 2)
        self.assertEqual(part, rec[:108])

    def test_judge(self):
        quiet = {"closed_at_s": None, "close": None, "routed_at_s": None, "bytes_back": 0, "stub_accepted": 0}
        self.assertEqual(probe.judge("b3", "hold", quiet, 60.0)[0], True)
        self.assertEqual(probe.judge("m3", "close", dict(quiet, closed_at_s=3.01), 3.0)[0], True)
        self.assertEqual(probe.judge("m3", "close", dict(quiet, closed_at_s=2.5), 3.0)[0], False)   # early
        self.assertEqual(probe.judge("m3", "close", dict(quiet, closed_at_s=4.2), 3.0)[0], False)   # late
        self.assertEqual(probe.judge("m3", "close", dict(quiet, closed_at_s=3.0, routed_at_s=3.0, stub_accepted=1), 3.0)[0], False)
        self.assertEqual(probe.judge("m3", "route", dict(quiet, routed_at_s=3.2, stub_accepted=1), 3.0)[0], True)
        self.assertEqual(probe.judge("m3", "route", quiet, 3.0)[0], False)
        self.assertIsNone(probe.judge("m3", None, quiet, 3.0)[0])
        self.assertEqual(probe.judge("b3", "hold", dict(quiet, routed_at_s=10.0, stub_accepted=1), 60.0)[0], False)
        # A socket seen without an accept, or an accept without a socket, is a disagreement, never a pass.
        self.assertEqual(probe.judge("b3", "hold", dict(quiet, routed_at_s=0.001), 60.0)[0], False)
        self.assertEqual(probe.judge("m3", "close", dict(quiet, closed_at_s=3.0, stub_accepted=1), 3.0)[0], False)

    def test_stub_sockets(self):
        text = ("  sl  local_address rem_address   st\n"
                "   0: 0100007F:59E2 00000000:0000 0A 0\n"   # LISTEN on 23010: not counted
                "   1: 0100007F:59E2 0100007F:9C40 06 0\n"   # TIME-WAIT on 23010
                "   2: 0100007F:59E4 0100007F:9C41 01 0\n"   # ESTABLISHED on 23012
                "   3: 0100007F:0050 0100007F:9C42 01 0\n")  # another port
        got = probe.stub_sockets({23010, 23012}, text)
        self.assertEqual(got, {("0100007F:59E2", "0100007F:9C40"), ("0100007F:59E4", "0100007F:9C41")})

    def test_expectations(self):
        for s in (probe.SERVER,) + comp.ORDER:
            for case in ("silent", "partial"):
                self.assertEqual(probe.expectation(s, "b3", case), "hold")
                self.assertIn(probe.expectation(s, "m3", case), ("close", "route", None))
        self.assertEqual(probe.expectation("haproxy", "m3", "silent"), "route")
        self.assertIsNone(probe.expectation("sslh-ev", "m3", "silent"))


class HandoffRow(unittest.TestCase):
    def snaps(self, backend_busy_ticks: int) -> dict:
        stat0 = {c: [0] * 10 for c in range(16)}
        stat1 = {c: [0] * 10 for c in range(16)}
        for c in handoff.BACKEND_CPUS:
            stat1[c] = [backend_busy_ticks, 0, 0, 500 - backend_busy_ticks, 0, 0, 0, 0, 0, 0]
        return {"stat0": stat0, "stat1": stat1, "b0": {"t": 0.0, "cpu_ticks": 0}, "b1": {"t": 5.0, "cpu_ticks": 300}}

    def test_backend_rule(self):
        g = {"ok": True, "measure": {"completed": 100_000}}
        row = handoff.finish_handoff({"valid": True, "invalid_reasons": [], "server_cpu_s": 4.9}, self.snaps(200), g, hz=100)
        self.assertTrue(row["valid"])
        self.assertAlmostEqual(row["backend_core_busy"]["10"], 0.4)
        self.assertAlmostEqual(row["backend_cpu_s"], 3.0)
        self.assertAlmostEqual(row["wl6_cpu_us_per_exchange"], 1e6 * 7.9 / 100_000)
        row = handoff.finish_handoff({"valid": True, "invalid_reasons": [], "server_cpu_s": 4.9}, self.snaps(460), g, hz=100)
        self.assertFalse(row["valid"])  # 92% > 90% on each backend core
        self.assertIn("busy > 90%", row["invalid_reasons"][0])

    def test_session_ratio(self):
        rows = [{"arm": a, "valid": True, "metric": {"value": v}} for a, v in (("A", 110.0), ("B", 100.0), ("B", 100.0), ("A", 110.0))]
        self.assertAlmostEqual(handoff.session_ratio(rows), 1.1)  # server / proxy
        rows[1]["valid"] = False
        self.assertIsNone(handoff.session_ratio(rows))


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux only")
class Integration(unittest.TestCase):
    """Real processes on this host: the server's relay as the front, the stub behind it."""

    def setUp(self):
        if BUILD is None:
            self.skipTest("no --build")

    def test_probe_of_the_servers_relay(self):
        with tempfile.TemporaryDirectory() as d:
            res = probe.run(probe.SERVER, "m3", BUILD, Path(d))
        self.assertTrue(res["checks"]["routes"]["ok"], res["checks"]["routes"])
        self.assertEqual(res["checks"]["routes"]["front_counters"].get("routed_by_sni"), 1)
        for case in ("silent", "partial"):
            self.assertTrue(res["checks"][case]["ok"], res["checks"][case])
            self.assertEqual(res["checks"][case]["stub_accepted"], 0, case)

    def test_one_handoff_window_each_protocol(self):
        saved = (window.WARMUP_MS, window.DURATION_MS, window.wait_conntrack)
        window.WARMUP_MS, window.DURATION_MS = 100, 300
        window.wait_conntrack = lambda *a, **k: (0.0, None)  # a test, not a window: no table wait
        try:
            with tempfile.TemporaryDirectory() as d:
                blocks = window.SourceBlocks(Path(d) / "blocks.json")
                for proto in handoff.M3_PROTOS:
                    cfg = {"build": BUILD, "proto": proto, "k_src": 4, "cell": f"m3.{proto}.test", "arms": {"A": handoff.SERVER},
                           "ports": {"A": 23500}}
                    session = {"job": "test", "id": f"test-{proto}", "mhz": 1.0}
                    row = handoff.run_window(cfg, session, "A", 0, blocks, Path(d) / "raw")
                    reasons = row.get("invalid_reasons", [])
                    self.assertFalse([r for r in reasons if "driver error" in r or "probe failed" in r or "exit" in r], reasons)
                    self.assertGreater(row["metric"]["value"], 0, proto)
                    self.assertGreater(row["backend_counters"]["accepted"], 0, proto)
                    self.assertEqual(row["server_counters"]["relayed"], row["backend_counters"]["accepted"], proto)
                    self.assertIn("wl6_cpu_us_per_exchange", row, proto)
                    self.assertEqual(set(row["backend_core_busy"]), {"10", "12"})
        finally:
            window.WARMUP_MS, window.DURATION_MS, window.wait_conntrack = saved


def main() -> int:
    global BUILD
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", type=Path)
    a, rest = ap.parse_known_args()
    BUILD = a.build
    res = unittest.main(argv=[sys.argv[0]] + rest, exit=False, verbosity=1).result
    print(f"{res.testsRun} checks, {len(res.failures)} failures, {len(res.errors)} errors, {len(res.skipped)} skipped")
    return 0 if res.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
