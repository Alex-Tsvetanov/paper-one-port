#!/usr/bin/env python3
"""Tests of W's frozen runners (M7e), pure, on any host (no server, no generator, nothing timed):
- each W runner's cells are L's runner's cells with host "W": the A/A pilot's 12 cells, W's churn
  h2c and churn MQTT included; the cost cells without those two, which are listed as not run; M1's
  two IOCP cells; section 10's W cells, the IOCP forms' arms, the 2-core IOCP cell not run; the
  mixed cell's placement inside W's generator CPUs;
- W's rows, written through the session engine with a stand-in window that sets the fields W's
  window sets (host W, WL4 in cycles beside a tick-based value), assemble into analysis/rows.py's
  sessions and cells, and analysis/ accepts them: pilot.py never resolves the two cells outside the
  family and takes lambda from their C1 sessions; analyse.py reads W's CPU from the cycles; the
  IOCP forms' roles; rule E's IOCP evidence in the form rule_e.py decide reads;
- the pilot's timer and split parts with W's process functions write the rows L's write;
- the hard cases on IOCP: replay's B2(d) bound after IOCP's switch, G_W's HC7 rule, W's entries;
- the W window's command lines and its guard; the job context, the ports, the provenance, the
  entries a frozen W run checks.

    python bench/run/test_wfrozen.py      (exit 0 when every check passes)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(REPO / "analysis"))

import analyse as AN  # noqa: E402
import cells as C  # noqa: E402
import pilot as PL  # noqa: E402
import rows as RW  # noqa: E402

import cost_run  # noqa: E402
import freeze_guard  # noqa: E402
import hardcase_run as HR  # noqa: E402
import m_run  # noqa: E402
import pilot_run  # noqa: E402
import rule_e  # noqa: E402
import runlib  # noqa: E402
import s_run  # noqa: E402
import sessions as SS  # noqa: E402
import wcellwin  # noqa: E402
import wcost_run  # noqa: E402
import whardcase_run  # noqa: E402
import wm_run  # noqa: E402
import wpilot_run  # noqa: E402
import wrule_e  # noqa: E402
import wrunlib  # noqa: E402
import ws_run  # noqa: E402
import wwindow  # noqa: E402
from test_frozen import K, RULE_E, SEEDS, Clear, fake_window, prov, report, transcript, variant  # noqa: E402

OUTSIDE = sorted(C.COST_OUTSIDE_FAMILY)
TICKS = {"A": 15.625, "B": 31.25}          # GetProcessTimes on W: whole ticks, a sample at a low load
CYCLES = {"A": 51000.0, "B": 50000.0}      # W's WL4: the server's cycles per exchange


def w_window(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
    """What W's window sets beside the stand-in window's fields: the host, WL4 in cycles and the
    tick-based value beside it, the CPU shares."""
    row = fake_window(cell, arm, session, position, clr)
    row.update(host="W", backend=row.get("backend", "IOCP"), cpu_us_per_exchange=TICKS[arm], cycles_per_exchange=CYCLES[arm],
               cpu_shares={"server_cpu_busy": 0.4, "server_process": 0.38, "generator_cpus_busy": 0.46, "generator_process": 0.45})
    return row


def run_engine(runner: str, cells: list[SS.Cell], out: Path, *, development: bool = True, clearance=None, seed: int = 11,
               win=w_window) -> list[dict]:
    eng = SS.Engine(runner, "wj", out, cells, SS.make_plan(cells, seed), win, lambda c, arm: prov(), development, clearance,
                    log=lambda s: None, warmup_s=0)
    eng.run()
    return eng.rows()


def analysed(rows: list[dict], pilot: dict | None = None) -> dict:
    RW.refuse_flags(rows, frozen=False, allow_synthetic=False)
    pilot = pilot or {"R_C": 11, "m_C": 0, "resolved": [], "joint_powers": [], "rates": {}}
    return AN.analyse(rows, pilot=pilot, rule_e=RULE_E, seeds=SEEDS)


def cells_by_id(summary: dict) -> dict:
    return {x["cell"]: x for f in summary["families"].values() for x in f["cells"]}


class WCells(unittest.TestCase):
    def test_pilot_cells(self):
        w = pilot_run.pilot_cells(16, host="W")
        self.assertEqual([c.id for c in w], [c.id for c in C.cost_cells() if c.host == "W"])
        self.assertEqual(len(w), 12)
        self.assertTrue(set(OUTSIDE) <= {c.id for c in w})       # their C1 sessions give WL2's lambda
        self.assertEqual({c.id for c in w if c.group == 1}, {c.id for c in C.cost_cells() if c.host == "W" and c.hyp == "C3"})
        self.assertTrue(all(c.arms["A"]["mode"] == c.arms["B"]["mode"] == "dedicated" for c in w))
        self.assertEqual(len(pilot_run.pilot_cells(16)), 24)      # L's, unchanged

    def test_cost_cells_leave_out_the_outside_cells(self):
        w = wcost_run.w_cost_cells(11, RULE_E, {})
        ids = [c.id for c in w]
        self.assertEqual(len(ids), 10)
        self.assertFalse(set(OUTSIDE) & set(ids))
        self.assertEqual(sorted(cost_run.cost_not_run("W")), OUTSIDE)
        self.assertTrue(all("A/A pilot only" in why for why in cost_run.cost_not_run("W").values()))
        self.assertEqual(cost_run.cost_not_run("L"), {})
        self.assertEqual(len(cost_run.cost_cells(11, RULE_E, {})), 24)
        for c in w:
            self.assertTrue(c.pairs_one_port_with_dedicated)
            self.assertEqual((c.arms["A"]["mode"], c.arms["B"]["mode"]), ("one-port", "dedicated"))
            self.assertEqual(c.arms["A"]["detect"], RULE_E["default"]["IOCP"])

    def test_m_cells(self):
        self.assertEqual([c.id for c in wm_run.w_m_cells(16, RULE_E)], ["M1.W.IOCP.http1", "M1.W.IOCP.h2c"])
        self.assertEqual(len(m_run.m_cells(16, RULE_E, None)), 18)  # L's: M1 on two backends, M2, M3

    def test_s_cells(self):
        cells, skipped = ws_run.w_s_cells(16, RULE_E, "http1")
        want = {f"S.ssh.{h}.W.IOCP" for h in C.COST_HYPS} | {"S.mixed.C1.W.IOCP", "S.tls-variants.C1.W.IOCP.alpn-h2",
                                                             "S.iocp-forms.W.IOCP.acceptex-buffer", "S.iocp-forms.W.IOCP.receive-form",
                                                             "S.m-ttfb.M1.W.IOCP.http1", "S.m-ttfb.M1.W.IOCP.h2c"}
        self.assertEqual({c.id for c in cells}, want)
        self.assertEqual(skipped["S.two-cores.C1.W.IOCP.two-cores"], s_run.TWO_CORE_IOCP_NOT_RUN)
        self.assertEqual(skipped["S.tls-variants.C1.W.IOCP.resumption"], s_run.RESUMPTION_NOT_RUN)
        self.assertTrue(skipped["S.ssh.C1.L.epoll"].startswith("L's cell"))
        l_cells, l_skipped = s_run.s_cells(16, RULE_E, "http1")
        self.assertEqual(l_skipped["S.two-cores.C1.W.IOCP.two-cores"], s_run.TWO_CORE_IOCP_NOT_RUN)
        self.assertTrue(l_skipped["S.iocp-forms.W.IOCP.acceptex-buffer"].startswith("W's cells"))
        self.assertFalse([c for c in l_cells if "IOCP" in c.id])
        mixed = next(c for c in cells if c.id == "S.mixed.C1.W.IOCP")
        self.assertEqual(mixed.shared["background"], {"silent_ports": "http1"})

    def test_iocp_form_arms(self):
        acc = s_run.iocp_form_arms("acceptex-buffer", RULE_E)
        self.assertEqual((acc["A"]["iocp_accept"], acc["B"]["iocp_accept"]), ("buffer", "no-buffer"))
        self.assertEqual((acc["A"]["iocp_receive"], acc["B"]["iocp_receive"]), ("zero-byte", "zero-byte"))
        rec = s_run.iocp_form_arms("receive-form", RULE_E)
        self.assertEqual((rec["A"]["iocp_receive"], rec["B"]["iocp_receive"]), ("posted", "zero-byte"))
        self.assertEqual((rec["A"]["iocp_accept"], rec["B"]["iocp_accept"]), ("no-buffer", "no-buffer"))
        for arms in (acc, rec):
            for a in arms.values():
                self.assertEqual((a["mode"], a["workload"], a["proto"], a["run"]["mode"]), ("one-port", "churn", "http1", "one-port"))

    def test_mixed_placement(self):
        gen = set(wcellwin.MIXED_GEN_CPUS)
        bg = {k: set(v) for k, v in wcellwin.MIXED_BG_CPUS.items()}
        self.assertEqual(len(gen), 4)
        self.assertTrue(gen | bg["tls"] | bg["mqtt"] <= set(wwindow.GEN_CPUS))
        self.assertFalse(gen & (bg["tls"] | bg["mqtt"]) or bg["tls"] & bg["mqtt"])
        self.assertEqual(bg["silent"], bg["mqtt"])


class WRowsAgainstAnalysis(unittest.TestCase):
    def test_pilot(self):
        with tempfile.TemporaryDirectory() as d:
            rows = run_engine("wpilot_run", pilot_run.pilot_cells(16, host="W"), Path(d), seed=SEEDS["SEED_PILOT_W"])
        entry = PL.pilot_entry(rows, [], SEEDS, n_sim=5)
        w_ids = [c.id for c in C.cost_cells() if c.host == "W"]
        self.assertEqual(entry["resolved"], [c for c in w_ids if c not in OUTSIDE])
        by = {e["cell"]: e for e in entry["cells"]}
        for cid in OUTSIDE:
            self.assertFalse(by[cid]["resolved"])
            self.assertEqual(by[cid]["valid_sessions"], 16)
            self.assertIn("outside_family", by[cid])
        self.assertEqual(entry["rates"]["C3.W.IOCP.mqtt"]["rate"], 500.0)   # RATE_FRAC x the C1 median, 1000
        self.assertEqual(pilot_run.c3_rates(rows, runner="wpilot_run")["C3.W.IOCP.h2c"], 500.0)
        self.assertEqual(entry["incomplete"], ["no window of host L"])

    def test_cost(self):
        cells = [c for c in wcost_run.w_cost_cells(11, RULE_E, {}) if c.id == "C1.W.IOCP.http1"]
        with tempfile.TemporaryDirectory() as d:
            stubs = run_engine("wcost_run", cells, Path(d))
        self.assertEqual(sum(1 for r in stubs if r.get("stub")), (11 + 3) * 2)   # every session invalid: 11, then ceil(11/4) reruns
        with tempfile.TemporaryDirectory() as d:
            rows = run_engine("wcost_run", cells, Path(d), development=False, clearance=Clear())
        for r in rows:
            r["development"] = False
        s = AN.analyse(rows, pilot={"R_C": 11, "m_C": 1, "resolved": ["C1.W.IOCP.http1"], "joint_powers": [], "rates": {}},
                       rule_e=RULE_E, seeds=SEEDS)
        x = cells_by_id(s)
        self.assertTrue(x["C1.W.IOCP.http1"]["tested"] and x["C1.W.IOCP.http1"]["holm"])
        cpu = next(e for e in s["secondary"] if e["bullet"] == "wl4" and e["cell"] == "C1.W.IOCP.http1" and e["metric"] == "cpu")
        self.assertAlmostEqual(cpu["median"], 51000.0 / 50000.0)   # the cycles, never the ticks (0.5)
        for cid in OUTSIDE:
            self.assertEqual(x[cid]["verdict"], C.COST_OUTSIDE_FAMILY[cid])

    def test_m1(self):
        with tempfile.TemporaryDirectory() as d:
            rows = run_engine("wm_run", wm_run.w_m_cells(16, RULE_E), Path(d))
        s = analysed(rows)
        x = cells_by_id(s)
        self.assertTrue(x["M1.W.IOCP.http1"]["tested"] and x["M1.W.IOCP.h2c"]["tested"])
        cpu = next(e for e in s["secondary"] if e["cell"] == "M1.W.IOCP.http1" and e["metric"] == "cpu")
        self.assertAlmostEqual(cpu["median"], 51000.0 / 50000.0)

    def test_s(self):
        cells, _ = ws_run.w_s_cells(16, RULE_E, "http1")
        with tempfile.TemporaryDirectory() as d:
            rows = run_engine("ws_run", cells, Path(d), development=False, clearance=Clear())
        for r in rows:
            r["development"] = False
        s = analysed(rows)
        sec = {(e["bullet"], e["cell"]): e for e in s["secondary"]}
        for cid in [c.id for c in cells if not c.id.startswith("S.m-ttfb")]:
            bullet = cid.split(".")[1]
            self.assertIsNotNone(sec[(bullet, cid)]["interval"], cid)
        forms = sec[("iocp-forms", "S.iocp-forms.W.IOCP.acceptex-buffer")]
        self.assertEqual(forms["metric_name"], "conn_per_s")
        sess = RW.assemble([r for r in rows if r.get("bullet") == "iocp-forms"], lambda r: RW.row_info(r, RULE_E), AN.roles_for)
        self.assertTrue(all(set(x.roles.values()) == {"variant", "default"} for x in sess))
        self.assertIsNotNone(sec[("m-ttfb-cpu", "S.m-ttfb.M1.W.IOCP.http1")]["interval"])

    def test_rule_e_evidence(self):
        cells = wrule_e.w_rule_e_cells(6)

        def faster_peek(cell, arm, session, position, clr):
            row = w_window(cell, arm, session, position, clr)
            row["metric"] = {"name": "conn_per_s", "value": 1010.0 if arm == "B" else 1000.0}
            row["server_counters"] = {"accepted": 100, "recv_calls": 200}
            return row

        with tempfile.TemporaryDirectory() as d:
            rows = run_engine("wrule_e", cells, Path(d), win=faster_peek)
        ev = rule_e.evidence(rows, cells)
        self.assertEqual(ev["IOCP"]["detect"]["choice"], "peek")
        rule, notes = rule_e.decide({}, {"IOCP": ev["IOCP"]}, development=True)
        self.assertEqual(rule["default"]["IOCP"], "peek")
        self.assertNotIn("IOCP", notes)


class WParts(unittest.TestCase):
    """pilot_run's timer and split parts with injected process functions write L's rows."""

    class Proc:
        pid = 4242
        returncode = 0

        def poll(self):
            return None

    def procs(self, counters: list[str]):
        def start(build, backend, proxy, raw, tag, record):
            if record is not None:
                record.write_text(json.dumps({"event": "detection", "peer_port": 5555, "outcome": "proxy_timeout",
                                              "timed": {"kind": "T_hdr", "start_ns": 10, "deadline_ns": 10 + 3_000_000_000,
                                                        "wait_return_ns": 10 + 3_000_000_000 + 700_000,
                                                        "prev_wait_return_ns": 5}}) + "\n")
            return self.Proc(), None, {"HTTP/1.1": 24000}, ["oneport.exe"]

        def opcase(build, port, hc, variant, extra, proxy_port=None):
            return 0, {"connected": True, "local_port": 5555, "write_ns": [1, 2]}, ""

        return pilot_run.PartProcs(start, opcase, lambda proc, out: (0, counters), lambda pid: {"pid": pid})

    def test_timer_and_split(self):
        rows = []
        with tempfile.TemporaryDirectory() as d:
            pilot_run.timer_part(Path(d), "IOCP", 1, set(), Path(d), lambda r, meta=False: None if meta else rows.append(r), "j",
                                 procs=self.procs([]))
            pilot_run.split_part(Path(d), "IOCP", (5,), 1, set(), Path(d), lambda r, meta=False: rows.append(r), "j",
                                 procs=self.procs(["counter accepted 1", "counter recv_calls 3", "counter recv_eof 1", "counter recv_again 0"]))
        timer = [r for r in rows if r["part"] == "timer"]
        self.assertEqual([r["lateness_ns"] for r in timer], [700_000])
        self.assertTrue(all(r["valid"] and r["b2"]["a_never_early"] and r["b2"]["b_first_pass"] for r in timer))
        split = [r for r in rows if r["part"] == "split"]
        self.assertEqual((split[0]["recv_data"], split[0]["valid"]), (2, True))
        self.assertEqual(PL.g_values(timer)["W"]["G_ms"], 1)

    def test_w_parts_are_ws(self):
        self.assertIs(wpilot_run.W_PARTS.start, wpilot_run.start_part_server)
        self.assertIs(wpilot_run.W_PARTS.opcase, wpilot_run.opcase_run)
        self.assertIs(pilot_run.LINUX_PARTS.start, pilot_run.start_part_server)


class WHardCases(unittest.TestCase):
    def test_replay_bound_after_iocp_switch(self):
        r = report(max_user_bytes=40, replayed=True)
        on_w = HR.judge(variant(), transcript(), [r], [], None, "peek", False, {}, K, iocp=True)
        self.assertFalse(on_w["b2"]["d"])
        on_l = HR.judge(variant(), transcript(), [r], [], None, "peek", False, {}, K)
        self.assertTrue(on_l["b2"]["d"])
        no_switch = HR.judge(variant(), transcript(), [report(max_user_bytes=40)], [], None, "peek", False, {}, K, iocp=True)
        self.assertTrue(no_switch["b2"]["d"])

    def test_hc7_follows_g_w(self):
        emitted = []
        a = argparse.Namespace(cases=[7], entries=["IOCP.replay.inproc"], replicates=1, rows_prior=[], job="j", development=True,
                               dev_g_ms=None, dev_gap_split_ms=5)
        with tempfile.TemporaryDirectory() as d:
            a.build, a.out = Path(d), Path(d)
            pilot = {"G": {"L": {"G_ms": 4, "hc7_runs": True}, "W": {"G_ms": None, "hc7_runs": False}}, "gap_split": {"GAP_SPLIT_ms": 5}}
            a.development = False  # the pilot entry's G_W decides
            table = HR.part_server(a, pilot, RULE_E, {}, None, emitted.append, procs=whardcase_run.W_CASES, host="W")
        self.assertEqual(table, {})
        self.assertEqual([(e["kind"], e["hc"]) for e in emitted], [("hardcase-skipped", 7)])
        self.assertIn("on W", emitted[0]["why"])

    def test_w_entries_and_procs(self):
        self.assertEqual(whardcase_run.ENTRIES_W, ("IOCP.replay.inproc", "IOCP.peek.inproc"))
        self.assertIs(whardcase_run.W_CASES.server, whardcase_run.WServer)
        self.assertIs(HR.LINUX_CASES.server, HR.Server)


class WWindowPieces(unittest.TestCase):
    def test_server_cmd(self):
        cmd = wcellwin.server_cmd(Path("b"), {"mode": "one-port", "detect": "peek", "port": 20000})
        self.assertEqual(cmd[1:], ["--mode", "one-port", "--detect", "peek", "--dispatch", "inproc", "--backend", "IOCP", "--port", "20000"])
        cmd = wcellwin.server_cmd(Path("b"), {"mode": "one-port", "port": 20000, "iocp_accept": "buffer", "iocp_receive": "zero-byte"})
        self.assertEqual(cmd[-4:], ["--iocp-accept", "buffer", "--iocp-receive", "zero-byte"])

    def test_one_port_against_dedicated_needs_the_clearance(self):
        blocks = mock.MagicMock()
        p = {"mode": "one-port", "pairs_dedicated": True, "build": Path("b"), "workload": "churn", "proto": "http1", "port": 20000, "k_src": 16}
        with mock.patch.object(wcellwin, "start_err") as started:
            with self.assertRaises(wcellwin.WindowError):
                wcellwin.run(p, {"id": "s", "fingerprint": {}}, "A", 0, blocks, Path("raw"), None)
            with self.assertRaises(wcellwin.WindowError):
                wcellwin.run(p, {"id": "s", "fingerprint": {}}, "A", 0, blocks, Path("raw"), freeze_guard.Clearance({}))
        started.assert_not_called()
        blocks.take.assert_not_called()

    def test_w_session(self):
        fp = {"lab_plan": "g", "frequency": {"server_mean": 100.0}, "cycle_rate": {"cycles_per_s": 3.9e9}}
        s = wrunlib.w_session({"id": "x", "fingerprint": fp})
        self.assertEqual((s["lab_plan"], s["frequency"], s["cycle_rate"]), ("g", fp["frequency"], fp["cycle_rate"]))

    def test_job_context(self):
        with self.assertRaises(runlib.InputRefused):
            wrunlib.check_job_context(False, {})
        with self.assertRaises(runlib.InputRefused):
            wrunlib.check_job_context(False, {"ONEPORT_W_JOB": "w1", "ONEPORT_W_FUNCTIONAL": "1"})
        self.assertEqual(wrunlib.check_job_context(False, {"ONEPORT_W_JOB": "w1"})["job"], "w1")
        self.assertTrue(wrunlib.check_job_context(True, {"ONEPORT_W_FUNCTIONAL": "1"})["functional_check"])

    def test_ports(self):
        text = ("Protocol tcp Port Exclusion Ranges\n\nStart Port    End Port      \n----------    --------      \n"
                "      5357        5357      \n     31064       31163      \n     50000       50059     *\n\n* - Administered port exclusions.\n")
        ex = wrunlib.parse_excluded(text)
        self.assertEqual(ex, [(5357, 5357), (31064, 31163), (50000, 50059)])
        used = wpilot_run.USED_PORTS + whardcase_run.USED_PORTS
        self.assertEqual(wrunlib.port_conflicts(ex, used), [])
        self.assertEqual(len(wrunlib.port_conflicts([(20003, 20010)], used)), 1)

    def test_arm_provenance(self):
        p = {"binaries_all": {"oneport": "a" * 64, "opgen": "b" * 64}, "commit": "x"}
        self.assertEqual(wrunlib.arm_provenance(p, Path("b"), ("oneport",))["binaries"], {"oneport": "a" * 64})
        with self.assertRaises(runlib.InputRefused):
            wrunlib.arm_provenance(p, Path("b"), ("oneport", "opcase"))

    def test_entries_are_logged(self):
        self.assertEqual(wrunlib.ENTRIES, (freeze_guard.W_ITEMS, freeze_guard.M7E_ITEMS))
        heads = [ln for ln in (REPO / "hypotheses.md").read_text(encoding="utf-8").splitlines() if ln.startswith("### ")]
        for title in wrunlib.ENTRIES:
            self.assertTrue(any(title in h for h in heads), title)

    def test_frozen_w_cost_run_needs_the_job(self):
        called = []
        with mock.patch.object(SS.Engine, "run", lambda self: called.append(1)), \
                mock.patch.object(wrunlib, "install_stop", lambda: None), \
                mock.patch.dict(wrunlib.os.environ, {}, clear=False) as env, \
                tempfile.TemporaryDirectory() as d:
            env.pop("ONEPORT_W_JOB", None)
            seeds = Path(d) / "seeds.json"
            seeds.write_text(json.dumps(SEEDS))
            with self.assertRaises(runlib.InputRefused):
                wcost_run.main(["--build", d, "--out", d, "--job", "j", "--seeds", str(seeds), "--code-freeze", "0" * 40,
                                "--gate", str(seeds), "--pilot", str(seeds), "--rule-e", str(seeds)])
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
