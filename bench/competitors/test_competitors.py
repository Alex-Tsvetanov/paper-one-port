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
import os
import re
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))

import cases_check  # noqa: E402
import competitors as comp  # noqa: E402
import harness_inputs  # noqa: E402
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
        for name in ("NGINX", "HAPROXY", "ENVOY", "XCADDY", "SSLH", "JDK"):
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
            if s in comp.PROXY_SYSTEMS:
                self.assertIn(str(22100 + comp.PROXY_PORT_OFFSET), text, f"{s}: the PROXY listener")
            else:
                self.assertNotIn(str(22100 + comp.PROXY_PORT_OFFSET), text, f"{s}: no PROXY listener")
        self.assertIn("proxy_protocol;", live(rendered("nginx", "cases")))
        self.assertIn("accept-proxy", live(rendered("haproxy", "cases")))
        self.assertIn("envoy.filters.listener.proxy_protocol", live(rendered("envoy", "cases")))
        self.assertIn("proxy_protocol {", live(rendered("caddy-l4", "cases")))
        self.assertNotIn("proxyprotocol", live(rendered("sslh-ev", "cases")))  # not in the pinned build (libproxyprotocol)

    def test_alpn(self):
        self.assertIn("$ssl_preread_alpn_protocols", live(rendered("nginx", "cases")))
        self.assertIn("req.ssl_alpn -m str h2 http/1.1", live(rendered("haproxy", "cases")))
        self.assertIn('application_protocols: [ "h2", "http/1.1" ]', live(rendered("envoy", "cases")))
        self.assertIn('application_protocols: [ "h2c" ]', live(rendered("envoy", "cases")))
        self.assertIn("alpn h2 http/1.1", live(rendered("caddy-l4", "cases")))
        self.assertIn('alpn_protocols: [ "h2", "http/1.1" ]', live(rendered("sslh-ev", "cases")))
        self.assertIn("envoy.filters.listener.http_inspector", live(rendered("envoy", "cases")))
        self.assertNotIn("http_inspector", live(rendered("envoy", "m3")))  # M4a's reading 11: M3 and B3 hold none

    def test_no_alpn_route(self):
        # The server's route for a ClientHello without ALPN (bench/server/relay.cpp), in every
        # proxy's cases configuration (Appendix B: "every route its features cover").
        self.assertIn('"oneport.test "             tls_backend;', live(rendered("nginx", "cases")))
        h = live(rendered("haproxy", "cases"))
        self.assertIn("acl tls_has_alpn req.ssl_alpn -m found", h)
        self.assertIn("use_backend tls_backend if { req.ssl_sni -m str oneport.test } !tls_has_alpn", h)
        e = live(rendered("envoy", "cases"))
        chains = e.split("filter_chain_match:")
        self.assertTrue(any('server_names: [ "oneport.test" ]' in c and "application_protocols" not in c.split("filters:")[0]
                            for c in chains[1:]), "a TLS chain by SNI alone")
        c = live(rendered("caddy-l4", "cases"))
        self.assertEqual(c.count("@tls_no_alpn tls {"), 2)  # the plain listener and the PROXY listener's subroute
        self.assertEqual(c.count("route @tls_no_alpn {"), 2)
        self.assertLess(c.index("route @tls {"), c.index("route @tls_no_alpn {"))  # after the ALPN route
        s = live(rendered("sslh-ev", "cases"))
        self.assertIn('{ name: "tls"; host: "127.0.0.1"; port: "22112"; sni_hostnames: [ "oneport.test" ]; log_level: 0; }', s)
        self.assertLess(s.index("alpn_protocols"), s.index('sni_hostnames: [ "oneport.test" ]; log_level: 0;'))
        self.assertEqual(set(cases_check.NOALPN_SYSTEMS), set(comp.ORDER))
        self.assertLessEqual(set(cases_check.NOALPN_EXACT), set(cases_check.NOALPN_SYSTEMS))

    def test_fallback_only_in_its_kind(self):
        smtp = str(22110 + comp.STUB_OFFSET["smtp"])
        for s in (x for x in comp.FALLBACK_SYSTEMS if x in comp.ORDER):
            self.assertNotIn(smtp, live(rendered(s, "cases")), s)
            self.assertIn(smtp, live(rendered(s, "cases-fallback")), s)
        # cmux's fallback is Any() in the harness, to its own SMTP handler (no backend).
        self.assertNotIn("-fallback", comp.args_lines(rendered("cmux", "cases")))
        self.assertIn("-fallback", comp.args_lines(rendered("cmux", "cases-fallback")))
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
        self.assertEqual(set(cases_check.COVERS), set(comp.ORDER) | set(comp.LIBRARIES))

    def test_sslh_list_stays_well_formed(self):
        # The fallback entry carries its own leading comma, so the list has no trailing comma
        # whether that line is live or a comment.
        for kind in comp.CASES_KINDS:
            body = live(rendered("sslh-ev", kind))
            protocols = body[body.index("protocols:"):]
            self.assertNotRegex(protocols, r",\s*\)")


class Libraries(unittest.TestCase):
    """The in-process libraries' harnesses (M4b-2): their two configurations (Appendix B: cases and
    B3), the JVM's flags, the command lines, the jar locks, and the probe's expectations."""

    def args(self, system: str, kind: str, timers: str = "matched") -> list[str]:
        return comp.args_lines(comp.render(system, kind, 22100, 22110, 14, RUN, timers))

    def value(self, args: list[str], flag: str) -> str | None:
        return args[args.index(flag) + 1] if flag in args else None

    def test_kinds(self):
        for s in comp.LIBRARIES:
            self.assertTrue(comp.SYSTEMS[s].library)
            with self.assertRaises(ValueError):
                comp.SYSTEMS[s].template("m3")  # no M3 configuration (Appendix B)
        self.assertEqual([s for s in comp.LIBRARIES if s in comp.FALLBACK_SYSTEMS], ["cmux"])
        self.assertEqual([s for s in comp.LIBRARIES if s in comp.PROXY_SYSTEMS], ["netty", "jetty"])

    def test_timers(self):
        # Matched to the server's 3 s in the cases, 60 s in B3 (section 1); at the defaults the line is gone.
        for s, flag, matched, b3 in (("netty", "--timer-s", "3", "60"), ("jetty", "--idle-ms", "3000", "60000"),
                                     ("cmux", "-timer-s", "3", "60")):
            self.assertEqual(self.value(self.args(s, "cases"), flag), matched, s)
            self.assertIsNone(self.value(self.args(s, "cases", "default"), flag), s)
            self.assertEqual(self.value(self.args(s, "b3"), flag), b3, s)
        for kind in ("cases", "b3"):  # hyper-util has no detection timer, and none is added
            self.assertEqual(self.args("hyper-util", kind)[:2], ["--port", "22100"])

    def test_b3_limits_and_listeners(self):
        self.assertEqual(self.value(self.args("netty", "b3"), "--backlog"), "10000")
        self.assertEqual(self.value(self.args("jetty", "b3"), "--accept-queue"), "10000")
        self.assertEqual(self.value(self.args("hyper-util", "b3"), "--backlog"), "10000")
        self.assertNotIn("-backlog", self.args("cmux", "b3"))  # net.core.somaxconn (Appendix B)
        self.assertIn("-fallback", self.args("cmux", "b3"))  # Appendix B's line keeps Any() last
        for s in ("netty", "jetty"):
            self.assertEqual(self.value(self.args(s, "cases"), "--proxy-port"), "22101")
            self.assertIsNone(self.value(self.args(s, "b3"), "--proxy-port"))  # one listener in a B3 window
            self.assertTrue(self.value(self.args(s, "b3"), "--cert").endswith("tests/fixtures/tls/test-cert.pem"))

    def test_jvm_args(self):
        a = comp.jvm_args()
        self.assertIn("-XX:+UseG1GC", a)
        self.assertIn("-Xms253755392", a)  # 1/64 and 1/4 of L's memory, as the pinned JDK aligns them
        self.assertIn("-Xmx4037017600", a)
        self.assertIn("-Djava.net.preferIPv4Stack=true", a)
        self.assertFalse([x for x in a if "TransparentHugePages" in x])

    def test_commands(self):
        h = Path("/b/harness")
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "b3.args"
            cfg.write_text("--port 1\n# a comment\n")
            n = comp.SYSTEMS["netty"].command(cfg, RUN, h)
            self.assertEqual(Path(n[0]).parts[-3:], (f"jdk-{comp.pin('ONEPORT_JDK_VERSION')}", "bin", "java"))
            self.assertEqual(n[1:1 + len(comp.jvm_args())], comp.jvm_args())  # the JVM's flags before the class path
            cp = n[n.index("-cp") + 1]
            self.assertTrue(cp.startswith(str(h / "netty" / "harness.jar") + ":") and cp.endswith("lib/*"))
            self.assertEqual(n[-3:], ["oneport.NettyHarness", "--port", "1"])
            self.assertEqual(comp.SYSTEMS["cmux"].command(cfg, RUN, h), [str(h / "cmux" / "oneport-cmux"), "--port", "1"])
        with self.assertRaises(ValueError):
            comp.SYSTEMS["hyper-util"].binary_path()  # a library's harness is built per checkout

    def test_maven_locks(self):
        for s in ("netty", "jetty"):
            rows = [ln.split() for ln in (HERE / s / "maven.lock").read_text().splitlines() if ln and not ln.startswith("#")]
            self.assertTrue(rows)
            for coords, sha, url in rows:
                parts = coords.split(":")
                g, a, v = parts[:3]
                name = f"{a}-{v}" + (f"-{parts[3]}" if len(parts) > 3 else "") + ".jar"
                self.assertEqual(url, f"https://repo1.maven.org/maven2/{g.replace('.', '/')}/{a}/{v}/{name}")
                self.assertRegex(sha, r"^[0-9a-f]{64}$")
            version = comp.pin(comp.SYSTEMS[s].version_pin)
            self.assertTrue(all(v == version for _, a, v, *_ in (r[0].split(":") for r in rows) if a.startswith(s)), s)
        self.assertIn("io.netty:netty-transport-native-epoll:4.2.18.Final:linux-x86_64",
                      (HERE / "netty" / "maven.lock").read_text())  # the native epoll transport (Appendix B)

    def test_probe_expectations(self):
        for kind, systems in probe.EXPECT_LIB.items():
            for s, cases in systems.items():
                self.assertIn(s, comp.LIBRARIES)
                self.assertEqual(set(cases), {"silent", "partial"})
        self.assertEqual(set(probe.EXPECT_LIB["b3"]), set(comp.LIBRARIES))
        self.assertEqual(set(probe.LIB_PROTOS), set(comp.LIBRARIES))
        quiet = {"closed_at_s": None, "bytes_back": 0, "first_bytes_at_s": None}
        self.assertTrue(probe.judge_lib("hold", quiet, 60.0)[0])
        self.assertFalse(probe.judge_lib("hold", dict(quiet, bytes_back=3), 60.0)[0])
        self.assertTrue(probe.judge_lib("close", dict(quiet, closed_at_s=3.02), 3.0)[0])
        self.assertTrue(probe.judge_lib("greet", dict(quiet, first_bytes_at_s=3.0, bytes_back=24), 3.0)[0])
        self.assertFalse(probe.judge_lib("greet", dict(quiet, first_bytes_at_s=0.0, bytes_back=24), 3.0)[0])
        self.assertTrue(probe.judge_lib("reject", dict(quiet, closed_at_s=0.01), 3.0)[0])
        self.assertEqual(probe.judge_lib(None, quiet, 3.0), (None, "observed only"))


class HarnessInputs(unittest.TestCase):
    """The harnesses' named inputs and their inputs hash (harness_inputs.py; M5, step 0): the
    hyper-util harness's TSan suppression file is one of its inputs, so editing it changes the hash
    the records gate matches."""

    def test_every_input_exists(self):
        self.assertEqual(set(comp.LIBRARIES), set(harness_inputs.INPUTS))
        for name in harness_inputs.INPUTS:
            lines = harness_inputs.input_lines(name)
            self.assertEqual(len(lines), len(harness_inputs.INPUTS[name]), name)
            self.assertTrue(all(ln.startswith(f"bench/competitors/{name}/") for ln in lines), name)
            self.assertRegex(harness_inputs.inputs_hash(name), r"^[0-9a-f]{64}$")

    def test_suppression_is_an_input(self):
        self.assertIn("tsan.supp", harness_inputs.INPUTS["hyper-util"])
        self.assertEqual(harness_inputs.run_env("hyper-util", "release"), {})
        env = harness_inputs.run_env("hyper-util", "tsan")
        self.assertTrue(env["TSAN_OPTIONS"].endswith("bench/competitors/hyper-util/tsan.supp"))
        entries = [ln for ln in (HERE / "hyper-util" / "tsan.supp").read_text().splitlines() if ln and not ln.startswith("#")]
        self.assertEqual(entries, ["race:tokio::runtime::io::registration_set::RegistrationSet>::allocate"])  # one entry, in tokio

    def test_editing_an_input_changes_the_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in harness_inputs.INPUTS["hyper-util"]:
                p = root / "bench" / "competitors" / "hyper-util" / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((HERE / "hyper-util" / rel).read_bytes())
            same = harness_inputs.inputs_hash("hyper-util", root)
            self.assertEqual(same, harness_inputs.inputs_hash("hyper-util"))
            supp = root / "bench" / "competitors" / "hyper-util" / "tsan.supp"
            supp.write_bytes(supp.read_bytes().replace(b"\n", b"\r\n"))  # CRLF is read as LF
            self.assertEqual(harness_inputs.inputs_hash("hyper-util", root), same)
            supp.write_text(supp.read_text() + "race:tokio::runtime::task\n")
            self.assertNotEqual(harness_inputs.inputs_hash("hyper-util", root), same)
            supp.unlink()
            with self.assertRaises(FileNotFoundError):
                harness_inputs.inputs_hash("hyper-util", root)


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
# The integration tests' ports: probe.PORTS (23000, 23100, 23200) and the hand-off window's 23500,
# each with its stub's six listeners 10 to 15 above it, so the block is 23000 to 23515.
PORT_BLOCK = (23000, 23515)
# A shift is a multiple of PORT_STRIDE, more than the block's 516 ports, so the blocks of two
# different shifts never overlap. 400, the stride until the code freeze's preparation, was less:
# the dry run of the records drivers (job dryrun1) ran ASan's suite at shift 3200 and TSan's at
# 3600, and TSan's probe front (23100 + 3600) took the port of ASan's hand-off window (23500 +
# 3200), whose stub then did not start.
PORT_STRIDE = 600
PORT_SHIFTS = 16


def port_shift(build: Path, env: dict | None = None) -> int:
    """A port offset per build tree, so two suites run at once (M5's checks and the records driver
    run two sanitizer builds together) do not bind each other's ports: ONEPORT_TEST_PORT_SHIFT
    when set (bench/sanitize_oneport.sh gives each sanitizer its own), else PORT_STRIDE times the
    tree's CRC-32 modulo PORT_SHIFTS. Every port stays below L's ephemeral range (32768)."""
    env = os.environ if env is None else env
    if env.get("ONEPORT_TEST_PORT_SHIFT"):
        shift = int(env["ONEPORT_TEST_PORT_SHIFT"])
        if shift % PORT_STRIDE or not 0 <= shift < PORT_STRIDE * PORT_SHIFTS:
            raise ValueError(f"ONEPORT_TEST_PORT_SHIFT={shift}: a multiple of {PORT_STRIDE} below {PORT_STRIDE * PORT_SHIFTS}")
        return shift
    return PORT_STRIDE * (zlib.crc32(str(build.resolve()).encode()) % PORT_SHIFTS)


class PortShifts(unittest.TestCase):
    """The integration tests' port blocks of two suites at once never overlap (pure)."""

    def test_block_and_stride(self):
        self.assertEqual(PORT_BLOCK[0], min(probe.PORTS.values()))
        self.assertEqual(PORT_BLOCK[1], HANDOFF_TEST_PORT + max(comp.STUB_OFFSET.values()) + 10)
        self.assertGreater(PORT_STRIDE, PORT_BLOCK[1] - PORT_BLOCK[0])
        self.assertLess(PORT_BLOCK[1] + PORT_STRIDE * (PORT_SHIFTS - 1), 32768)  # L's ephemeral range starts there

    def test_environment_override(self):
        self.assertEqual(port_shift(Path("."), {"ONEPORT_TEST_PORT_SHIFT": "1800"}), 1800)
        for bad in ("400", "9600", "-600"):
            with self.assertRaises(ValueError):
                port_shift(Path("."), {"ONEPORT_TEST_PORT_SHIFT": bad})
        self.assertEqual(port_shift(Path("."), {}) % PORT_STRIDE, 0)


HANDOFF_TEST_PORT = 23500  # the hand-off window's front in test_one_handoff_window_each_protocol


class Integration(unittest.TestCase):
    """Real processes on this host: the server's relay as the front, the stub behind it."""

    def setUp(self):
        if BUILD is None:
            self.skipTest("no --build")
        self.shift = port_shift(BUILD)

    def test_probe_of_the_servers_relay(self):
        saved = dict(probe.PORTS)
        probe.PORTS.update({k: v + self.shift for k, v in saved.items()})
        try:
            with tempfile.TemporaryDirectory() as d:
                res = probe.run(probe.SERVER, "m3", BUILD, Path(d))
        finally:
            probe.PORTS.update(saved)
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
                           "ports": {"A": HANDOFF_TEST_PORT + self.shift}}
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
