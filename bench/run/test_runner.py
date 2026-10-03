#!/usr/bin/env python3
"""Tests of the window runner's pure parts (bench/run): WL7's parsers on samples recorded on L on
2026-10-02 (bench/run/samples), the footprint and section 7's B3 rules on synthetic readings with
known growth, the server's counter lines, nstat, the source-address blocks, the validity rules of
a cost window, the A/A spread, and the clock floor (clockfloor.sh on a copy of the cpufreq tree,
on Linux). Prints counts only. Run: python3 bench/run/test_runner.py"""
from __future__ import annotations

import copy
import http.server
import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aa  # noqa: E402
import b3  # noqa: E402
import counterdelta  # noqa: E402
import systrace  # noqa: E402
import footprint as fp  # noqa: E402
import window  # noqa: E402

SAMPLES = HERE / "samples"
PAGE = 4096


def sample(name: str) -> str:
    return (SAMPLES / name).read_text()


SS_LOOPBACK = """Recv-Q Send-Q Local Address:Port Peer Address:Port
0      0      127.0.0.1:20003    127.0.1.7:41234
\t skmem:(r0,rb131072,t0,tb2626560,f0,w0,o0,bl0,d0)
108    0      127.0.0.1:20003    127.0.1.8:41236
\t skmem:(r1280,rb131072,t0,tb2626560,f2816,w0,o0,bl0,d0)
0      0      127.0.0.1:20003    127.0.1.9:41238
\t skmem:(r0,rb131072,t0,tb2626560,f0,w0,o0,bl0,d0)
"""


def reading(**kw) -> fp.Reading:
    base = dict(t_ns=0, rss_kb={100: 2000}, slab_kb=500_000, caches={"skbuff_head_cache": 400_000, "skbuff_small_head": 900_000,
                "skbuff_fclone_cache": 3_000_000}, fclone_target=":0000512", fclone_cotenants=["pool_workqueue", "sgpool-16",
                "skbuff_fclone_cache"], fclone_listed_as="pool_workqueue", fclone_slabs=199, fclone_objects=2040, sockets=[],
                time_wait=10, problems=[])
    base.update(kw)
    return fp.Reading(**base)


def sockets(n: int, r: int = 0, f: int = 0) -> list[fp.SsSocket]:
    return [fp.SsSocket("127.0.0.1:20003", f"127.0.1.1:{30000 + i}", {"r": r, "f": f}) for i in range(n)]


class Parsers(unittest.TestCase):
    def test_slabinfo_on_L(self):
        s = fp.parse_slabinfo(sample("L-slabinfo.txt"))
        self.assertGreater(len(s), 100)
        self.assertEqual(s["skbuff_head_cache"]["num_slabs"], 51)
        self.assertEqual(s["skbuff_head_cache"]["pagesperslab"], 2)
        self.assertEqual(fp.cache_bytes(s["skbuff_head_cache"], PAGE), 51 * 2 * PAGE)
        self.assertEqual(fp.cache_bytes(s["pool_workqueue"], PAGE), 199 * 4 * PAGE)
        self.assertNotIn("skbuff_fclone_cache", s)  # merged on L: listed as pool_workqueue (WL7)

    def test_slabinfo_refuses_other_text(self):
        with self.assertRaises(ValueError):
            fp.parse_slabinfo("MemTotal: 1 kB\n")
        with self.assertRaises(ValueError):
            fp.parse_slabinfo("slabinfo - version: 2.1\nbroken line\n")

    def test_links_and_cotenants_on_L(self):
        links = fp.parse_slab_links(sample("L-slab_links.txt"))
        self.assertEqual(links["skbuff_fclone_cache"], ":0000512")
        co = sorted(n for n, t in links.items() if t == ":0000512")
        self.assertEqual(co, ["pool_workqueue", "sgpool-16", "skbuff_fclone_cache"])
        self.assertNotIn("skbuff_head_cache", links)  # its own directory, not merged

    def test_skb_caches_on_L(self):
        slab = fp.parse_slabinfo(sample("L-slabinfo.txt"))
        links = fp.parse_slab_links(sample("L-slab_links.txt"))
        attrs = dict(line.split(": ", 1) for line in sample("L-fclone_dir.txt").splitlines())
        sizes, target, co, listed, slabs, objects, problems = fp.skb_caches_from(slab, links, PAGE, attrs)
        self.assertEqual(problems, [])
        self.assertEqual((target, listed, slabs, objects), (":0000512", "pool_workqueue", 199, 2040))
        self.assertEqual(sizes["skbuff_fclone_cache"], 199 * 4 * PAGE)
        self.assertEqual(set(sizes), set(fp.SKB_CACHES))

    def test_skb_caches_missing(self):
        slab = fp.parse_slabinfo(sample("L-slabinfo.txt"))
        del slab["skbuff_small_head"]
        links = fp.parse_slab_links(sample("L-slab_links.txt"))
        _, _, _, _, slabs, _, problems = fp.skb_caches_from(slab, links, PAGE, {"slabs": "", "objects": ""})
        self.assertTrue(any("skbuff_small_head" in p for p in problems))
        self.assertTrue(any("unreadable" in p for p in problems))
        self.assertEqual(slabs, -1)
        # A merged cache whose co-tenants are all absent from slabinfo cannot be read.
        del slab["pool_workqueue"]
        _, _, _, _, _, _, problems = fp.skb_caches_from(slab, links, PAGE, {"slabs": "1", "objects": "1"})
        self.assertTrue(any("co-tenants" in p for p in problems))

    def test_kb_fields(self):
        self.assertEqual(fp.parse_kb_field(sample("L-meminfo.txt"), "Slab") > 0, True)
        self.assertEqual(fp.parse_kb_field("Name:\tx\nVmRSS:\t    1788 kB\n", "VmRSS"), 1788)
        with self.assertRaises(KeyError):
            fp.parse_kb_field("VmHWM: 1 kB\n", "VmRSS")

    def test_ss_tm(self):
        socks = fp.parse_ss_tm(SS_LOOPBACK)
        self.assertEqual(len(socks), 3)
        self.assertEqual([fp.local_port(s.local) for s in socks], [20003] * 3)
        self.assertEqual([s.skmem["r"] for s in socks], [0, 1280, 0])
        self.assertEqual(socks[1].skmem["f"], 2816)
        self.assertEqual(fp.parse_ss_tm("Recv-Q Send-Q Local Address:Port Peer Address:Port\n"), [])
        with self.assertRaises(ValueError):
            fp.parse_ss_tm("\t skmem:(r0,rb1)\n")
        with self.assertRaises(ValueError):
            fp.parse_ss_tm("0 0 127.0.0.1:1 127.0.0.1:2\n")

    def test_first_int(self):
        self.assertEqual(fp.parse_first_int("199 N0=199\n"), 199)
        with self.assertRaises(ValueError):
            fp.parse_first_int("N0=1")


class Footprint(unittest.TestCase):
    def test_known_growth(self):
        n = 10_000
        base = reading()
        s = reading(rss_kb={100: 2000 + 10_000}, slab_kb=500_000 + 20_000,
                    caches={"skbuff_head_cache": 400_000 + 1_024_000, "skbuff_small_head": 900_000,
                            "skbuff_fclone_cache": 3_000_000 + 1_024_000},
                    sockets=sockets(n, r=1280, f=2816))
        f = fp.footprint(base, s, n)
        self.assertAlmostEqual(f.U, 10_000 * 1024 / n)
        self.assertAlmostEqual(f.Kq, 1280)
        self.assertAlmostEqual(f.f_mean, 2816)  # reported, not added
        self.assertAlmostEqual(f.Ks, (20_000 * 1024 - 2_048_000) / n)
        self.assertAlmostEqual(f.W, f.U + f.Kq + f.Ks)
        self.assertEqual(f.shared_growth, 1_024_000)
        self.assertEqual(f.established, n)

    def test_settle_rule(self):
        n = 10_000
        base = reading()
        # W of sample 2: 1000 B per pending connection (all in U); the tolerance is 2% = 20 B.
        s2 = reading(rss_kb={100: 2000 + 1000 * n // 1024}, sockets=sockets(n))
        w2 = fp.footprint(base, s2, n).W
        ok1 = reading(rss_kb={100: s2.rss_kb[100] - 150}, sockets=sockets(n))  # 15.4 B lower
        bad1 = reading(rss_kb={100: s2.rss_kb[100] - 250}, sockets=sockets(n))  # 25.6 B lower
        self.assertEqual(fp.window_problems(base, ok1, s2, n), [])
        probs = fp.window_problems(base, bad1, s2, n)
        self.assertEqual(len(probs), 1)
        self.assertIn("not settled", probs[0])
        self.assertGreater(w2, 900)
        # Near 0 the 8 B floor rules: 7 B apart passes, 9 B fails.
        z2 = reading(sockets=sockets(n))
        self.assertEqual(fp.window_problems(base, reading(slab_kb=500_000 + 68, sockets=sockets(n)), z2, n), [])  # 6.96 B
        self.assertTrue(fp.window_problems(base, reading(slab_kb=500_000 + 88, sockets=sockets(n)), z2, n))  # 9.01 B

    def test_other_rules(self):
        n = 100
        base = reading()
        good = reading(sockets=sockets(n))
        self.assertEqual(fp.window_problems(base, good, good, n), [])
        tw = reading(sockets=sockets(n), time_wait=11)
        self.assertTrue(any("TIME-WAIT" in p for p in fp.window_problems(base, tw, good, n)))
        few = reading(sockets=sockets(n - 1))
        self.assertTrue(any("established" in p for p in fp.window_problems(base, good, few, n)))
        moved = reading(sockets=sockets(n), fclone_cotenants=["pool_workqueue", "skbuff_fclone_cache"])
        self.assertTrue(any("co-tenants" in p for p in fp.window_problems(base, good, moved, n)))
        broken = reading(sockets=sockets(n), problems=["skbuff_small_head not in /proc/slabinfo"])
        self.assertTrue(any("skbuff_small_head" in p for p in fp.window_problems(base, broken, good, n)))


class KBase(unittest.TestCase):
    def test_median_of_sixteen_valid(self):
        def row(ks, valid=True, kind="ophold"):
            return {"kind": kind, "valid": valid, "footprint": {"sample2": {"Ks": ks}}}
        rows = [row(7400.0 + i) for i in range(16)] + [row(1.0, valid=False), row(99999.0, kind="b3")]
        self.assertAlmostEqual(fp.k_base(rows), (7407.0 + 7408.0) / 2)
        with self.assertRaises(ValueError):
            fp.k_base(rows[:15])


COUNTER_LINES = """oneport: listening HTTP/1.1 127.0.0.1:20000
counter accept_calls 1200
counter recv_calls 2400
counter io_uring_submissions RECV 7
counter io_uring_submissions POLL_ADD 2
counter accepted 1000
counter outcome classified 0
counter classified http1 0
""".splitlines()


def opgen_report(**kw) -> dict:
    g = {"ok": True, "wall_s": 5.0, "measure": {"completed": 100_000, "errors": {"total": 0}}, "warmup": {"completed": 1},
         "error_share": 0.0, "connect_failures": 0, "connects_run": 100_001, "all_completed": 120_000, "due": 0, "due_completed": 0,
         "due_errors": {}, "due_unfinished": 0, "completed_share": 0.0, "ttfb_ns": {"median": 45_000.0}, "ttfb_connect_ns": {},
         "exchange_ns": {}, "issue_lag_ns": {}, "cpu": {"pct": 40.0}, "peak_concurrency_per_worker": 0, "measure_start_ns": 1,
         "measure_end_ns": 2, "threads": 12}
    g.update(kw)
    return g


def snaps(hz: int = 100) -> dict:
    stat0 = {c: [0] * 10 for c in range(16)}
    stat1 = {c: [0] * 10 for c in range(16)}
    stat1[14] = [400, 0, 90, 10, 0, 0, 0, 0, 0, 0]  # 4.9 s busy of 5 s
    for c in window.GEN_CPUS:
        stat1[c] = [100, 0, 50, 350, 0, 0, 0, 0, 0, 0]
    return {"s0": {"t": 0.0, "cpu_ticks": 0, "run_ns": 0, "VmRSS": 10, "VmHWM": 10},
            "s1": {"t": 5.0, "cpu_ticks": 490, "run_ns": 4_900_000_000, "VmRSS": 12, "VmHWM": 13},
            "stat0": stat0, "stat1": stat1}


def base_row(workload: str = "churn") -> dict:
    return {"workload": workload, "server_exit": 0, "server_counters": window.parse_counters(COUNTER_LINES),
            "nstat_delta": {"TcpExtListenOverflows": 0, "TcpExtListenDrops": 0, "TcpExtTCPTimeWaitOverflow": 0}, "probe": {"connect_failures": 0}}


class Window(unittest.TestCase):
    def test_counters(self):
        c = window.parse_counters(COUNTER_LINES)
        self.assertEqual(c["accept_calls"], 1200)
        self.assertEqual(c["io_uring_submissions"], {"RECV": 7, "POLL_ADD": 2})
        self.assertEqual(c["outcome"], {"classified": 0})

    def test_counters_by_key(self):
        # A line added later (M6 merges a flag that is false on Linux) is read by its key and
        # changes nothing else; non-counter lines are ignored.
        lines = COUNTER_LINES + ["counter iocp_flag false", "oneport: iocp-accept no-buffer", "counter accepted_extra 3"]
        c = window.parse_counters(lines)
        self.assertEqual(c["accepted"], 1000)
        self.assertEqual(c["iocp_flag"], "false")
        r = window.finish(dict(base_row(), server_counters=c), opgen_report(), snaps(), [3200.0, 3200.0], {"mhz": 3200.0}, [], hz=100)
        self.assertNotIn("iocp_flag", r["per_connection"])
        self.assertAlmostEqual(r["per_connection"]["accept_calls"], 1.2)

    def test_nstat_on_L(self):
        n = window.parse_nstat(sample("L-nstat.txt"))
        self.assertEqual(set(n), set(window.NSTAT_KEYS))
        self.assertEqual(n["TcpExtListenOverflows"], n["TcpExtListenDrops"])

    def test_conntrack_stat(self):
        text = "\n".join([
            "entries  clashres found new invalid ignore delete chainlength insert insert_failed drop early_drop icmp_error  "
            "expect_new expect_create expect_delete search_restart",
            "00000fce  00000000 00000000 00000000 00000004 00000000 00000000 00000000 00000000 000000c8 000001d8 00000000 00000000  "
            "00000000 00000000 00000000 00000000",
            "00000fce  00000000 00000000 00000000 00000004 00000000 00000000 00000000 00000000 000000a2 0000016f 00000000 00000000  "
            "00000000 00000000 00000000 00000000",
        ])
        st = window.parse_ct_stat(text)
        self.assertEqual(st, {"invalid": 8, "insert_failed": 0xc8 + 0xa2, "drop": 0x1d8 + 0x16f, "early_drop": 0})

    def test_notrack_rules(self):
        # `iptables-nft -t raw -S` with notrack.sh's two rules, with one, with none, and with the
        # target printed as its synonym; other rules (Docker's, if it adds any) change nothing.
        policies = ["-P PREROUTING ACCEPT", "-P OUTPUT ACCEPT"]
        both = "\n".join(policies + ["-A PREROUTING -i lo -j NOTRACK", "-A OUTPUT -o lo -j NOTRACK"]) + "\n"
        self.assertEqual(window.parse_notrack(both), {"prerouting_lo": True, "output_lo": True, "active": True})
        one = "\n".join(policies + ["-A PREROUTING -i lo -j NOTRACK"]) + "\n"
        self.assertEqual(window.parse_notrack(one), {"prerouting_lo": True, "output_lo": False, "active": False})
        none = "\n".join(policies + ["-A PREROUTING -d 172.17.0.2/32 ! -i docker0 -j DROP"]) + "\n"
        self.assertFalse(window.parse_notrack(none)["active"])
        ct = "-A PREROUTING -i lo -j CT --notrack\n-A OUTPUT -o lo -j CT --notrack\n"
        self.assertTrue(window.parse_notrack(ct)["active"])
        other = "-A PREROUTING -i eth0 -j NOTRACK\n-A OUTPUT -o lo -p udp -j NOTRACK\n"
        self.assertEqual(window.parse_notrack(other), {"prerouting_lo": False, "output_lo": False, "active": False})

    def test_interrupts(self):
        head = "            CPU0       CPU1       CPU14"
        t0 = [head, "  0:        135          0          0   IR-IO-APIC    2-edge      timer",
              " LOC:     100       200       300   Local timer interrupts", " RES:  5 6 7   Rescheduling interrupts"]
        t1 = [head, "  0:        135          0          0   IR-IO-APIC    2-edge      timer",
              " LOC:     110       200       350   Local timer interrupts", " RES:  5 6 9   Rescheduling interrupts"]
        a = window.parse_interrupts(chr(10).join(t0))
        b = window.parse_interrupts(chr(10).join(t1))
        self.assertEqual(a[14]["LOC"], 300)
        self.assertEqual(window.irq_delta(a, b, [14]), {"LOC": 50, "RES": 2})
        self.assertEqual(window.irq_delta(a, b, [1]), {})

    def test_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            b = window.SourceBlocks(Path(d) / "blocks.json")
            first = b.take(64, now=1000.0)
            self.assertEqual(first, window.SourceBlocks.FIRST)
            second = b.take(64, now=1001.0)
            self.assertEqual(second, first + 64)
            b.release(first, now=1002.0)
            b.release(second, now=1003.0)
            # Wrap back to the first block within 60 s of its release: refused.
            st = json.loads((Path(d) / "blocks.json").read_text())
            st["next"] = window.SourceBlocks.LAST - 10
            (Path(d) / "blocks.json").write_text(json.dumps(st))
            with self.assertRaises(window.WindowError):
                b.take(64, now=1030.0)
            self.assertEqual(b.take(64, now=1100.0), window.SourceBlocks.FIRST)  # 98 s later: free again

    def test_generator_threads(self):
        self.assertEqual(window.gen_threads({"workload": "open"}), [2, 4, 6, 8, 10, 12])
        self.assertEqual(window.gen_threads({"workload": "churn"}), list(range(2, 14)))
        self.assertEqual(window.gen_threads({"workload": "open", "gen_threads": [2, 3]}), [2, 3])

    def test_one_port_refused(self):
        with self.assertRaises(window.WindowError):
            window.guard_mode(["oneport", "--mode", "one-port"])
        with self.assertRaises(window.WindowError):
            window.guard_mode(["oneport"])
        window.guard_mode(["oneport", "--mode", "dedicated"])

    def check(self, row: dict, g: dict, mhz=(3200.0, 3200.0)) -> dict:
        return window.finish(row, g, snaps(), list(mhz), {"mhz": 3200.0}, [], hz=100)  # L's USER_HZ

    def test_valid_churn(self):
        r = self.check(base_row(), opgen_report())
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertEqual(r["metric"], {"name": "conn_per_s", "value": 20_000.0})
        self.assertAlmostEqual(r["server_cpu_s"], 4.9)
        self.assertAlmostEqual(r["cpu_us_per_exchange"], 49.0)
        self.assertAlmostEqual(r["per_connection"]["accept_calls"], 1.2)
        self.assertAlmostEqual(r["server_cores_busy"], 0.98)

    def test_rules(self):
        cases = [
            (base_row(), opgen_report(error_share=0.002), "errors"),
            (base_row(), opgen_report(connect_failures=1), "connects failed"),
            (base_row(), opgen_report(cpu={"pct": 91.0}), "generator CPU"),
            (base_row(), opgen_report(measure={"completed": 0, "errors": {"total": 0}}), "no exchange"),
            (dict(base_row(), server_exit=1), opgen_report(), "server exit"),
            (dict(base_row(), nstat_delta={"TcpExtListenOverflows": 1, "TcpExtListenDrops": 1}), opgen_report(), "listen overflows"),
        ]
        for row, g, why in cases:
            r = self.check(row, g)
            self.assertFalse(r["valid"], why)
            self.assertTrue(any(why in x for x in r["invalid_reasons"]), (why, r["invalid_reasons"]))
        r = self.check(base_row(), opgen_report(), mhz=(3200.0, 3400.0))  # a mean 3.1% above the session's
        self.assertTrue(any("MHz" in x for x in r["invalid_reasons"]))
        # The generator rule applies to saturation cells only; the 99% rule to the open loop.
        r = self.check(base_row("open"), opgen_report(cpu={"pct": 95.0}, due=1000, due_completed=995, completed_share=0.995))
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertEqual(r["metric"]["name"], "ttfb_median_us")
        r = self.check(base_row("open"), opgen_report(due=1000, due_completed=989, completed_share=0.989))
        self.assertTrue(any("99%" in x for x in r["invalid_reasons"]))
        r = self.check(base_row("keepalive"), opgen_report())
        self.assertEqual(r["metric"]["name"], "req_per_s")
        self.assertAlmostEqual(r["per_request"]["recv_calls"], 2400 / 120_001)


class Spread(unittest.TestCase):
    def rows(self, a: list[float], b: list[float], session: str, valid: bool = True) -> list[dict]:
        out = []
        for pos, (arm, v) in enumerate([("A", a[0]), ("B", b[0]), ("B", b[1]), ("A", a[1])]):
            out.append({"cell": "churn.http1.epoll", "session": session, "position": pos, "arm": arm, "valid": valid,
                        "metric": {"value": v}, "cpu_us_per_exchange": 50.0})
        return out

    def test_summary(self):
        rows = self.rows([100, 100], [101, 101], "s1") + self.rows([100, 102], [99, 99], "s2") + self.rows([100, 100], [103, 103], "s3")
        rows += self.rows([1, 1], [1, 1], "s4", valid=False)
        s = aa.summarise(rows)["churn.http1.epoll"]
        self.assertEqual(s["sessions"], 4)
        m = s["metric"]
        self.assertEqual(m["n"], 3)
        self.assertAlmostEqual(m["ratios"][0], 1.01)
        self.assertAlmostEqual(m["ratios"][1], 99 / 101)
        self.assertEqual(m["outside_margin"], 1)  # 99/101 = 0.9802 is inside; 1.03 is outside
        self.assertAlmostEqual(m["log_sd"], __import__("statistics").stdev([math.log(x) for x in m["ratios"]]))
        self.assertEqual(len(s["invalid_windows"]), 4)

    def test_margin_edges(self):
        sp = aa.spread([0.98, 1.02, 1.0])
        self.assertEqual(sp["outside_margin"], 2)  # a ratio at a bound counts against (section 4.3)


class B3Relay(unittest.TestCase):
    """b3.py's parts for a relay system that run anywhere: the exchange probe against a stand-in
    stub (the 13 bytes, then EOF) and caddy-l4's heap profile request against a stand-in admin
    endpoint."""

    def serve_once(self, reply: bytes) -> tuple[int, threading.Thread, dict]:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        seen: dict = {}

        def one() -> None:
            c, _ = srv.accept()
            seen["got"] = c.recv(4096)
            c.sendall(reply)
            c.shutdown(socket.SHUT_WR)  # the stub closes its side first
            try:
                seen["after"] = c.recv(16)
            except ConnectionResetError:
                seen["after"] = "reset"
            c.close()
            srv.close()

        t = threading.Thread(target=one, daemon=True)
        t.start()
        return srv.getsockname()[1], t, seen

    def test_exchange_probe(self):
        port, t, seen = self.serve_once(b3.STUB_BODY)
        r = b3.exchange_probe(port, b"\x16\x03\x01hello")
        t.join(5)
        self.assertTrue(r["ok"], r)
        self.assertEqual(seen["got"], b"\x16\x03\x01hello")
        self.assertIn(seen["after"], ("reset", b""))  # the client's close by reset (or its end, if it raced)

    def test_exchange_probe_wrong_reply(self):
        port, t, _ = self.serve_once(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        r = b3.exchange_probe(port, b"x")
        t.join(5)
        self.assertFalse(r["ok"])

    def test_heap_profile(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server's name
                body = b"heap profile" if self.path == "/debug/pprof/heap?gc=1" else b""
                self.send_response(200 if body else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        r = b3.heap_profile(srv.server_address[1])
        t.join(5)
        srv.server_close()
        self.assertEqual((r["status"], r["bytes"]), (200, len(b"heap profile")))

    def test_systems(self):
        self.assertEqual(b3.SYSTEMS[:2], ("ophold", window.ONE_PORT_RELAY))
        self.assertEqual(set(b3.RELAY_SYSTEMS[1:]), {"nginx", "haproxy", "envoy", "caddy-l4", "sslh-ev"})
        self.assertEqual(b3.INPROC_SYSTEMS, ("one-port-inproc", "netty", "jetty", "cmux", "hyper-util"))
        self.assertEqual(set(b3.SYSTEMS), {"ophold"} | set(b3.RELAY_SYSTEMS) | set(b3.INPROC_SYSTEMS))
        # Section 6.2: hyper-util serves no TLS; every other in-process system is probed on TLS too.
        self.assertEqual({s for s, p in b3.INPROC_PROBES.items() if "tls" not in p}, {"hyper-util"})
        self.assertEqual(set(b3.COLLECT_LEAD_S), {"caddy-l4", "netty", "jetty", "cmux"})  # WL7's runtimes with a collector
        with self.assertRaises(ValueError):
            b3.run(Path("."), Path("."), "j", "silent", 1, Path("."), system="traefik")


class B3InProcess(unittest.TestCase):
    """b3.py's parts for an in-process system: the HTTP/1.1 probe and the response reader against
    stand-ins, the collector checks, and on Linux the cmux harness's signal step and jcmd's step
    against stand-in processes."""

    def serve_http(self, chunks: list[bytes]) -> tuple[int, threading.Thread, dict]:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        seen: dict = {}

        def one() -> None:
            c, _ = srv.accept()
            seen["got"] = c.recv(4096)
            for ch in chunks:
                c.sendall(ch)
                time.sleep(0.01)
            try:
                seen["after"] = c.recv(16)  # the client's reset (keep-alive: the server does not close)
            except ConnectionResetError:
                seen["after"] = "reset"
            c.close()
            srv.close()

        th = threading.Thread(target=one, daemon=True)
        th.start()
        return srv.getsockname()[1], th, seen

    def test_http1_probe(self):
        port, th, seen = self.serve_http([b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n", b"\r\nHello, ", b"World!"])
        r = b3.http1_probe(port)
        th.join(5)
        self.assertTrue(r["ok"], r)
        self.assertTrue(seen["got"].startswith(b"GET / HTTP/1.1\r\n"))
        self.assertNotIn(b"close", seen["got"].lower())  # keep-alive: the client, not the server, ends it
        self.assertEqual(seen["after"], "reset")

    def test_http1_probe_wrong_reply(self):
        port, th, _ = self.serve_http([b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"])
        self.assertFalse(b3.http1_probe(port)["ok"])
        th.join(5)

    @unittest.skipUnless(sys.platform.startswith("linux"), "the test certificate's key with the system OpenSSL")
    def test_tls_probe(self):
        import ssl
        fixtures = HERE.parent.parent / "tests" / "fixtures" / "tls"
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(fixtures / "test-cert.pem", fixtures / "test-key.pem")
        ctx.set_alpn_protocols(["http/1.1"])
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        seen: dict = {}

        def one() -> None:
            c, _ = srv.accept()
            with ctx.wrap_socket(c, server_side=True) as s:
                seen["got"] = s.recv(4096)
                s.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!")
                try:
                    seen["after"] = s.recv(16)
                except (ConnectionResetError, ssl.SSLError) as e:
                    seen["after"] = type(e).__name__
            srv.close()

        th = threading.Thread(target=one, daemon=True)
        th.start()
        r = b3.tls_probe(srv.getsockname()[1], fixtures / "test-cert.pem")
        th.join(5)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["tls"]["version"], r["tls"]["alpn"]), ("TLSv1.3", "http/1.1"))
        self.assertTrue(seen["got"].startswith(b"GET / HTTP/1.1\r\n"))
        self.assertIn(seen["after"], ("ConnectionResetError", "SSLError", b""))  # a reset, never a close_notify

    def test_response_ok(self):
        self.assertTrue(b3.response_ok(b"HTTP/1.1 200 OK\r\ncontent-length: 13\r\n\r\nHello, World!"))
        self.assertFalse(b3.response_ok(b"HTTP/1.1 200 OK\r\ncontent-length: 5\r\n\r\nHello"))
        self.assertFalse(b3.response_ok(b"HTTP/1.0 200 OK\r\n\r\nHello, World!"))

    def test_collector_ok(self):
        self.assertTrue(b3.collector_ok({"status": 200}))
        self.assertFalse(b3.collector_ok({"status": None, "error": "x"}))
        self.assertTrue(b3.collector_ok({"ok": True, "heap_inuse": 1}))
        self.assertFalse(b3.collector_ok({"ok": False}))

    @unittest.skipUnless(sys.platform.startswith("linux"), "signals and /proc")
    def test_go_collect(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "stdout.log"
            code = ("import json, signal, sys, time\n"
                    "def h(s, f):\n"
                    "    print('cmux: collector ' + json.dumps({'heap_inuse': 4096, 'num_gc': 1}), flush=True)\n"
                    "signal.signal(signal.SIGUSR1, h)\n"
                    "print('ready', flush=True)\n"
                    "time.sleep(30)\n")
            with open(log, "w") as f:
                p = subprocess.Popen([sys.executable, "-c", code], stdout=f)
            try:
                deadline = time.monotonic() + 10
                while "ready" not in log.read_text() and time.monotonic() < deadline:
                    time.sleep(0.02)
                r = b3.go_collect(p.pid, log)
                self.assertTrue(r["ok"], r)
                self.assertEqual(r["heap_inuse"], 4096)
                self.assertTrue(b3.go_collect(p.pid, log)["ok"])  # a second step finds its own new line
            finally:
                p.kill()
                p.wait()

    @unittest.skipUnless(sys.platform.startswith("linux"), "taskset and a shell script")
    def test_jvm_collect(self):
        with tempfile.TemporaryDirectory() as d:
            jcmd = Path(d) / "jcmd"
            jcmd.write_text('#!/bin/sh\necho "$1: $2"\n[ "$2" = GC.heap_info ] && echo " garbage-first heap   total 247808K, used 1024K"\nexit 0\n')
            jcmd.chmod(0o755)
            r = b3.jvm_collect(4242, jcmd)
            self.assertTrue(r["ok"], r)
            self.assertIn("garbage-first heap", r["heap_info"])
            jcmd.write_text("#!/bin/sh\nexit 1\n")
            self.assertFalse(b3.jvm_collect(4242, jcmd)["ok"])


PERF_SUMMARY = """
 Summary of events:

 oneport (51234), 9 events, 30.0%

   syscall            calls  errors  total       min       avg       max       stddev
                                     (msec)    (msec)    (msec)    (msec)        (%)
   --------------- --------  ------ -------- --------- --------- ---------     ------
   epoll_pwait2         120      0   200.363     0.001     1.670    10.000      5.00%
   accept4              100      2     0.081     0.005     0.010     0.016     15.43%
   recvfrom             300      0     0.060     0.002     0.030     0.058     92.00%
   sendto               100      0     0.022     0.006     0.007     0.009     14.43%

 oneport (51235), 4 events, 10.0%

   syscall            calls  errors  total       min       avg       max       stddev
                                     (msec)    (msec)    (msec)    (msec)        (%)
   --------------- --------  ------ -------- --------- --------- ---------     ------
   recvfrom              20      1     0.012     0.005     0.006     0.007     10.65%
LOST 3 events!
"""


class Trace(unittest.TestCase):
    """systrace.py's parser of perf trace -s (the layout perf 7.2.6 printed on L) and its check of
    the server's counters."""

    def test_summary(self):
        calls, lost = systrace.parse_summary(PERF_SUMMARY)
        self.assertEqual(calls["recvfrom"], {"calls": 320, "errors": 1})
        self.assertEqual(calls["accept4"], {"calls": 100, "errors": 2})
        self.assertEqual(lost, 3)
        self.assertNotIn("syscall", calls)

    def test_checks(self):
        calls, _ = systrace.parse_summary(PERF_SUMMARY)
        counters = {"accept_calls": 100, "recv_calls": 300, "peek_calls": 15, "check_calls": 5, "send_calls": 100,
                    "epoll_wait_calls": 119, "epoll_ctl_calls": 0, "setsockopt_calls": 0}
        by = {c["check"]: c for c in systrace.check_counters(counters, calls, "epoll", 1)}
        self.assertTrue(by["accept"]["agrees"])
        self.assertTrue(by["recv"]["agrees"])  # 300 + 15 + 5 = 320 recvfrom
        self.assertTrue(by["wait"]["agrees"])  # 120 against 119, within the slack
        self.assertNotIn("io_uring_enter", by)
        counters["send_calls"] = 99
        self.assertFalse({c["check"]: c for c in systrace.check_counters(counters, calls, "epoll", 1)}["send"]["agrees"])
        u = {c["check"] for c in systrace.check_counters(counters, calls, "io_uring", 1)}
        self.assertIn("recv (peek and check)", u)
        self.assertNotIn("accept", u)  # a ring operation on io_uring
        self.assertNotIn("connect", u)  # so is the relay's connect (IORING_OP_CONNECT)

    def test_stat_and_startup_offset(self):
        stat = systrace.parse_stat("1,,syscalls:sys_enter_recvfrom,635543,100.00,,\n"
                                   "<not counted>,,syscalls:sys_enter_splice,0,0.00,,\n"
                                   "120,,syscalls:sys_enter_epoll_ctl,635543,100.00,,\n")
        self.assertEqual(stat, {"recvfrom": 1, "splice": None, "epoll_ctl": 120})
        calls, _ = systrace.parse_summary(PERF_SUMMARY)
        # An idle pass: the counters hold 6 epoll_ctl of the listeners that perf never saw.
        offsets = systrace.startup_offsets({"epoll_ctl_calls": 6}, {}, "epoll")
        self.assertEqual(offsets["epoll_ctl"], 6)
        counters = {"accept_calls": 100, "recv_calls": 320, "send_calls": 100, "epoll_wait_calls": 120, "epoll_ctl_calls": 106}
        calls["epoll_ctl"] = {"calls": 100, "errors": 0}
        by = {c["check"]: c for c in systrace.check_counters(counters, calls, "epoll", 1, offsets, {"epoll_ctl": 100, "recvfrom": 330})}
        self.assertTrue(by["epoll_ctl"]["agrees"])  # 106 less 6 at start-up
        self.assertTrue(by["epoll_ctl"]["stat_agrees"])
        self.assertEqual(by["recv"]["stat_minus_trace"], 10)
        self.assertFalse(by["recv"]["stat_agrees"])  # 330 against 320
        row = systrace.finish_checks({"checks": list(by.values())}, {"ok": True}, [])
        self.assertFalse(row["agrees_with_perf_stat"])
        self.assertIsNone(by["accept"]["stat"])  # no stat count for accept4 here
        self.assertAlmostEqual(row["trace_shortfall_max_share"], 10 / 330)  # recvfrom: 330 by perf stat, 320 by perf trace
        self.assertIsNone(systrace.trace_shortfall([by["accept"]]))

    def test_load_has_no_time(self):
        g = {"ok": True, "warmup": {"completed": 10}, "measure": {"completed": 90, "errors": {"total": 0}}, "connect_failures": 0,
             "ttfb_ns": {"median": 1}, "wall_s": 2.0}
        self.assertEqual(set(systrace.counts_only(g)), {"ok", "warmup", "measure", "errors", "connect_failures"})


def cost_trace_row(mode: str, detect: str, accepted: int, repeat: int = 0, idle: dict | None = None, **counters) -> dict:
    sc = {"accepted": accepted, **counters}
    return {"kind": "cost", "cell": "churn.http1.epoll", "mode": mode, "detect": detect, "repeat": repeat, "server_counters": sc,
            "idle": {"server_counters": idle or {}}, "opgen": {"warmup": 10, "measure": 89}}


class CounterDelta(unittest.TestCase):
    """counterdelta.py (M5, criterion 1): one-port against dedicated per connection, the idle pass's
    counters first taken away, and the verdict per counter."""

    def test_idle_pass_is_taken_away(self):
        ded = cost_trace_row("dedicated", "replay", 100, idle={"epoll_ctl_calls": 6}, epoll_ctl_calls=106, recv_calls=200)
        c = counterdelta.load_counters(ded)
        self.assertEqual((c["epoll_ctl_calls"], c["recv_calls"], c["accepted"]), (100.0, 200.0, 100.0))
        u = cost_trace_row("dedicated", "replay", 10, idle={"io_uring_submissions": {"ACCEPT": 6}},
                           io_uring_submissions={"ACCEPT": 6, "RECV": 20})
        c = counterdelta.load_counters(u)
        self.assertEqual((c["ring:ACCEPT"], c["ring:RECV"]), (0.0, 20.0))

    def test_verdicts(self):
        ded = [cost_trace_row("dedicated", "replay", 100, r, recv_calls=200 + r, send_calls=100, bytes_copied=0) for r in (1, 2)]
        one = [cost_trace_row("one-port", "replay", 100, r, recv_calls=201 + r, send_calls=100, bytes_copied=50) for r in (1, 2)]
        d = counterdelta.compare(ded, one)
        self.assertEqual(d["send_calls"]["verdict"], "equal")
        self.assertEqual(d["recv_calls"]["verdict"], "within the spread")  # 2.01, 2.02 against 2.02, 2.03
        self.assertEqual(d["bytes_copied"]["verdict"], "differs")
        self.assertAlmostEqual(d["bytes_copied"]["delta"], 0.5)
        rep = counterdelta.cost_report(ded + one)
        self.assertEqual(set(rep), {"churn.http1.epoll.replay"})
        self.assertEqual(rep["churn.http1.epoll.replay"]["rows"], {"dedicated": 2, "one-port": 2})

    def test_per_request(self):
        r = cost_trace_row("dedicated", "replay", 3, send_calls=100)
        self.assertAlmostEqual(counterdelta.per_unit(r, "request")["send_calls"], 1.0)  # 10 + 89 + the probe's 1

    def test_detection_mode_reaches_the_commands(self):
        import handoff
        cmd = handoff.server_front_cmd(Path("/b"), 1, 11, "b3", "io_uring", "peek")
        self.assertEqual(cmd[cmd.index("--detect") + 1], "peek")
        self.assertEqual(cmd[cmd.index("--backend") + 1], "io_uring")
        default = handoff.server_front_cmd(Path("/b"), 1, 11)
        self.assertEqual(default[default.index("--detect") + 1], "replay")  # the proposed default
        with self.assertRaises(ValueError):
            handoff.server_front_cmd(Path("/b"), 1, 11, detect="sniff")
        self.assertEqual(systrace.DETECTS, ("replay", "peek"))

    def test_slab_all_is_recorded(self):
        r = reading(slab_all={"io_kiocb": 4096, "eventpoll_epi": 8192})
        self.assertEqual(fp.reading_dict(r)["slab_all"], {"io_kiocb": 4096, "eventpoll_epi": 8192})


def wait_for_child(pid: int, comm: str, timeout: float = 20.0) -> bool:
    """Whether a child of `pid` named `comm` (the wrapper's job) appears within `timeout` s."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for d in Path("/proc").iterdir():
            if not d.name.isdigit():
                continue
            try:
                stat = (d / "stat").read_text()
            except OSError:
                continue
            name = stat[stat.index("(") + 1:stat.rindex(")")]
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
            if ppid == pid and name == comm:
                return True
        time.sleep(0.05)
    return False


CLOCKFLOOR = HERE / "clockfloor.sh"
LOW, HIGH = 1_102_866, 3_201_000  # L's scaling_min_freq and scaling_max_freq on kernel 7.2.6


def cpufreq_tree(root: Path, cpus: int = 2) -> None:
    """A copy of the cpufreq files clockfloor.sh reads and writes, as L shows them."""
    (root / "cpufreq").mkdir(parents=True)
    (root / "cpufreq" / "boost").write_text("0\n")
    for c in range(cpus):
        d = root / f"cpu{c}" / "cpufreq"
        d.mkdir(parents=True)
        for name, v in (("scaling_min_freq", LOW), ("scaling_max_freq", HIGH), ("scaling_governor", "performance"),
                        ("energy_performance_preference", "performance"), ("scaling_driver", "amd-pstate-epp")):
            (d / name).write_text(f"{v}\n")


def floor_of(root: Path, cpu: int) -> int:
    return int((root / f"cpu{cpu}" / "cpufreq" / "scaling_min_freq").read_text())


class ClockFloor(unittest.TestCase):
    """clockfloor.sh on a copy of the cpufreq tree (CLOCKFLOOR_CPU_ROOT), writing directly, and the
    session fingerprint's clock_floor (window.clock_floor_fingerprint)."""

    def test_fingerprint(self):
        record = {"clock_floor": True, "set_at": "2026-10-03T14:00:00+03:00",
                  "before": {"cpus": {"0": {"scaling_min_freq": LOW}, "1": {"scaling_min_freq": LOW}}}}
        now = {"0": {"min_khz": HIGH, "max_khz": HIGH}, "1": {"min_khz": HIGH, "max_khz": HIGH}}
        fpr = window.clock_floor_fingerprint(now, record)
        self.assertTrue(fpr["set_by_job"])
        self.assertTrue(fpr["held"])
        self.assertEqual(fpr["before_min_khz"], {"0": LOW, "1": LOW})
        now["1"]["min_khz"] = LOW
        self.assertFalse(window.clock_floor_fingerprint(now, record)["held"])
        bare = window.clock_floor_fingerprint({}, None)
        self.assertEqual((bare["set_by_job"], bare["held"], bare["before_min_khz"]), (False, False, {}))

    def test_read_floors(self):
        with tempfile.TemporaryDirectory() as d:
            cpufreq_tree(Path(d), cpus=3)
            got = window.read_floors(Path(d))
        self.assertEqual(list(got), ["0", "1", "2"])
        self.assertEqual(got["2"], {"min_khz": LOW, "max_khz": HIGH})

    def run_floor(self, root: Path, record: Path, cmd: list[str], **env) -> subprocess.CompletedProcess:
        e = dict(os.environ, CLOCKFLOOR_CPU_ROOT=str(root), CLOCKFLOOR_SUDO="", CLOCKFLOOR_MSR="off", **env)
        return subprocess.run(["bash", str(CLOCKFLOOR), str(record)] + cmd, capture_output=True, text=True, env=e, timeout=60)

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash and the cpufreq layout of L")
    def test_floor_held_and_restored(self):
        with tempfile.TemporaryDirectory() as d:
            root, rec, seen = Path(d) / "cpu", Path(d) / "job.clock.json", Path(d) / "seen"
            cpufreq_tree(root)
            p = self.run_floor(root, rec, ["bash", "-c", f'cat {root}/cpu*/cpufreq/scaling_min_freq > {seen}; '
                                                          f'echo "$ONEPORT_CLOCK_RECORD" >> {seen}; exit 7'])
            self.assertEqual(p.returncode, 7, p.stderr)
            self.assertEqual(seen.read_text().split(), [str(HIGH), str(HIGH), str(rec)])
            self.assertEqual((floor_of(root, 0), floor_of(root, 1)), (LOW, LOW))
            r = json.loads(rec.read_text())
            self.assertEqual((r["clock_floor"], r["floor_held"], r["restored"], r["job_exit"]), (True, True, True, 7))
            self.assertEqual(r["before"]["cpus"]["1"]["scaling_min_freq"], LOW)
            self.assertEqual(r["set"]["cpus"]["1"]["scaling_min_freq"], HIGH)
            self.assertEqual(r["after"]["cpus"]["1"]["scaling_min_freq"], LOW)
            self.assertIsNone(r["before"]["cpus"]["0"]["cppc_request"])
            self.assertIsNotNone(r["set_at"])
            self.assertIsNotNone(r["restored_at"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash, signals and the cpufreq layout of L")
    def test_signal_restores(self):
        with tempfile.TemporaryDirectory() as d:
            root, rec = Path(d) / "cpu", Path(d) / "job.clock.json"
            cpufreq_tree(root)
            e = dict(os.environ, CLOCKFLOOR_CPU_ROOT=str(root), CLOCKFLOOR_SUDO="", CLOCKFLOOR_MSR="off")
            p = subprocess.Popen(["bash", str(CLOCKFLOOR), str(rec), "sleep", "30"], env=e, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (rec.exists() and '"set_at": "' in rec.read_text()):
                time.sleep(0.05)
            self.assertEqual(floor_of(root, 0), HIGH)
            self.assertTrue(wait_for_child(p.pid, "sleep"), "the job did not start")
            os.killpg(p.pid, signal.SIGTERM)  # as a job is stopped: TERM to its process group
            self.assertEqual(p.wait(timeout=20), 143)
            self.assertEqual((floor_of(root, 0), floor_of(root, 1)), (LOW, LOW))
            r = json.loads(rec.read_text())
            self.assertEqual((r["restored"], r["job_exit"]), (True, 143))

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash and file modes")
    def test_refusal_when_a_floor_cannot_be_set(self):
        if os.geteuid() == 0:
            self.skipTest("root writes a read-only file")
        with tempfile.TemporaryDirectory() as d:
            root, rec, ran = Path(d) / "cpu", Path(d) / "job.clock.json", Path(d) / "ran"
            cpufreq_tree(root)
            (root / "cpu1" / "cpufreq" / "scaling_min_freq").chmod(0o444)
            p = self.run_floor(root, rec, ["touch", str(ran)])
            self.assertEqual(p.returncode, 95, p.stderr)
            self.assertFalse(ran.exists())
            self.assertEqual(floor_of(root, 0), LOW)  # the one it did set, set back
            r = json.loads(rec.read_text())
            self.assertEqual((r["floor_held"], r["restored"]), (False, True))
            self.assertIn("does not run", r["reason"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash")
    def test_off(self):
        with tempfile.TemporaryDirectory() as d:
            root, rec = Path(d) / "cpu", Path(d) / "job.clock.json"
            cpufreq_tree(root)
            p = self.run_floor(root, rec, ["bash", "-c", "exit 3"], ONEPORT_CLOCK_FLOOR="off")
            self.assertEqual(p.returncode, 3)
            self.assertEqual(floor_of(root, 0), LOW)
            r = json.loads(rec.read_text())
            self.assertEqual((r["clock_floor"], r["reason"], r["job_exit"]), (False, "ONEPORT_CLOCK_FLOOR=off", 3))


THP = HERE / "thp.sh"


def thp_tree(root: Path) -> None:
    """A copy of the THP files thp.sh reads and writes, as L shows them on 2026-10-03."""
    (root / "khugepaged").mkdir(parents=True)
    (root / "enabled").write_text("[always] madvise never\n")
    (root / "defrag").write_text("always defer defer+madvise [madvise] never\n")
    for name, v in (("defrag", 1), ("pages_collapsed", 66908), ("full_scans", 903)):
        (root / "khugepaged" / name).write_text(f"{v}\n")


def thp_word(root: Path, name: str) -> str | None:
    return window.thp_selected((root / name).read_text())


class Thp(unittest.TestCase):
    """thp.sh on a copy of the THP sysfs tree (THP_ROOT), writing directly, the session
    fingerprint's thp (window.thp_fingerprint), and b3.py's memory sampler's pure parts."""

    def test_selected(self):
        self.assertEqual(window.thp_selected("[always] madvise never\n"), "always")
        self.assertEqual(window.thp_selected("always defer defer+madvise [madvise] never"), "madvise")
        self.assertEqual(window.thp_selected("madvise\n"), "madvise")
        self.assertIsNone(window.thp_selected("\n"))

    def test_fingerprint(self):
        record = {"thp": True, "set_at": "2026-10-03T18:00:00+03:00",
                  "before": {"enabled": "always", "defrag": "madvise", "khugepaged_defrag": 1, "anon_huge_pages_kb": 45056}}
        now = {"enabled": "madvise", "defrag": "madvise", "khugepaged_defrag": "1"}
        fpr = window.thp_fingerprint(now, record)
        self.assertEqual((fpr["set_by_job"], fpr["held"]), (True, True))
        self.assertEqual(fpr["before"], {"enabled": "always", "defrag": "madvise", "khugepaged_defrag": 1})
        self.assertFalse(window.thp_fingerprint(dict(now, enabled="always"), record)["held"])
        bare = window.thp_fingerprint({"enabled": "always"}, None)
        self.assertEqual((bare["set_by_job"], bare["held"], bare["before"]), (False, False, None))
        with tempfile.TemporaryDirectory() as d:
            thp_tree(Path(d))
            self.assertEqual(window.read_thp(Path(d)), {"enabled": "always", "defrag": "madvise", "khugepaged_defrag": "1"})

    def test_sampler_summary(self):
        rows = [{"t": 0.0, "rss_kb": 62000, "anon_huge_kb": 10240, "thp_fault_alloc": 5, "thp_collapse_alloc": 100},
                {"t": 1.0, "rss_kb": 74000, "anon_huge_kb": 26624, "thp_fault_alloc": 5, "thp_collapse_alloc": 108},
                {"t": 2.0, "rss_kb": 74100, "anon_huge_kb": 26624, "thp_fault_alloc": 6, "thp_collapse_alloc": 108}]
        s = b3.sampler_summary(rows)
        self.assertEqual((s["rows"], s["largest_rss_step_kb"], s["anon_huge_kb_max"]), (3, 12000, 26624))
        self.assertEqual((s["thp_collapse_alloc_delta"], s["thp_fault_alloc_delta"]), (8, 1))
        self.assertEqual(b3.sampler_summary([]), {})
        self.assertEqual(b3.thp_counters("nr_free_pages 1\nthp_fault_alloc 55626\nthp_collapse_alloc 1465\n"
                                         "thp_collapse_alloc_failed 0\n"),
                         {"thp_fault_alloc": 55626, "thp_collapse_alloc": 1465})

    def run_thp(self, root: Path, record: Path, cmd: list[str], **env) -> subprocess.CompletedProcess:
        e = dict(os.environ, THP_ROOT=str(root), THP_SUDO="", **env)
        return subprocess.run(["bash", str(THP), str(record)] + cmd, capture_output=True, text=True, env=e, timeout=60)

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash")
    def test_madvise_held_and_restored(self):
        with tempfile.TemporaryDirectory() as d:
            root, rec, seen = Path(d) / "thp", Path(d) / "job.thp.json", Path(d) / "seen"
            thp_tree(root)
            p = self.run_thp(root, rec, ["bash", "-c", f'cat {root}/enabled {root}/defrag > {seen}; '
                                                        f'echo "$ONEPORT_THP_RECORD" >> {seen}; exit 7'])
            self.assertEqual(p.returncode, 7, p.stderr)
            got = seen.read_text().split("\n")
            self.assertEqual((window.thp_selected(got[0]), window.thp_selected(got[1]), got[2]), ("madvise", "madvise", str(rec)))
            self.assertEqual((thp_word(root, "enabled"), thp_word(root, "defrag")), ("always", "madvise"))
            r = json.loads(rec.read_text())
            self.assertEqual((r["thp"], r["held"], r["restored"], r["job_exit"]), (True, True, True, 7))
            self.assertEqual((r["before"]["enabled"], r["set"]["enabled"], r["after"]["enabled"]), ("always", "madvise", "always"))
            self.assertEqual(r["wanted"], {"enabled": "madvise", "defrag": None})
            self.assertEqual(r["before"]["khugepaged_pages_collapsed"], 66908)
            self.assertIsNotNone(r["set_at"])
            self.assertIsNotNone(r["restored_at"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash")
    def test_defrag_when_asked(self):
        with tempfile.TemporaryDirectory() as d:
            root, rec, seen = Path(d) / "thp", Path(d) / "job.thp.json", Path(d) / "seen"
            thp_tree(root)
            p = self.run_thp(root, rec, ["bash", "-c", f"cat {root}/defrag > {seen}"], ONEPORT_THP_DEFRAG="never")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(window.thp_selected(seen.read_text()), "never")
            self.assertEqual(thp_word(root, "defrag"), "madvise")
            self.assertEqual(json.loads(rec.read_text())["wanted"], {"enabled": "madvise", "defrag": "never"})

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash and signals")
    def test_signal_restores(self):
        with tempfile.TemporaryDirectory() as d:
            root, rec = Path(d) / "thp", Path(d) / "job.thp.json"
            thp_tree(root)
            e = dict(os.environ, THP_ROOT=str(root), THP_SUDO="")
            p = subprocess.Popen(["bash", str(THP), str(rec), "sleep", "30"], env=e, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (rec.exists() and '"set_at": "' in rec.read_text()):
                time.sleep(0.05)
            self.assertEqual(thp_word(root, "enabled"), "madvise")
            self.assertTrue(wait_for_child(p.pid, "sleep"), "the job did not start")
            os.killpg(p.pid, signal.SIGTERM)  # as a job is stopped: TERM to its process group
            self.assertEqual(p.wait(timeout=20), 143)
            self.assertEqual(thp_word(root, "enabled"), "always")
            r = json.loads(rec.read_text())
            self.assertEqual((r["restored"], r["job_exit"]), (True, 143))

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash and file modes")
    def test_refusal_when_a_setting_cannot_be_made(self):
        if os.geteuid() == 0:
            self.skipTest("root writes a read-only file")
        with tempfile.TemporaryDirectory() as d:
            root, rec, ran = Path(d) / "thp", Path(d) / "job.thp.json", Path(d) / "ran"
            thp_tree(root)
            (root / "enabled").chmod(0o444)
            p = self.run_thp(root, rec, ["touch", str(ran)])
            self.assertEqual(p.returncode, 97, p.stderr)
            self.assertFalse(ran.exists())
            self.assertEqual(thp_word(root, "enabled"), "always")
            r = json.loads(rec.read_text())
            self.assertEqual((r["held"], r["restored"]), (False, True))
            self.assertIn("does not run", r["reason"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "bash")
    def test_off(self):
        with tempfile.TemporaryDirectory() as d:
            root, rec = Path(d) / "thp", Path(d) / "job.thp.json"
            thp_tree(root)
            p = self.run_thp(root, rec, ["bash", "-c", "exit 3"], ONEPORT_THP="off")
            self.assertEqual(p.returncode, 3)
            self.assertEqual(thp_word(root, "enabled"), "always")
            r = json.loads(rec.read_text())
            self.assertEqual((r["thp"], r["reason"], r["job_exit"]), (False, "ONEPORT_THP=off", 3))


if __name__ == "__main__":
    out = unittest.main(exit=False, verbosity=0).result
    print(f"{out.testsRun} checks, {len(out.failures)} failures, {len(out.errors)} errors")
    sys.exit(0 if out.wasSuccessful() else 1)
