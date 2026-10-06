#!/usr/bin/env python3
"""Tests of the frozen runners (M7c), pure, on any host with git and the analysis's numpy:
- each runner's rows, written through the session engine with a stand-in window that sets the
  fields the real window sets, assemble into analysis/rows.py's sessions and cells, and
  analysis/analyse.py (or pilot.py) accepts them, development rows allowed;
- the session engine: the order drawn before the first window, resumption across jobs, reruns at
  most ceil(R/4) per cell and never more than R valid sessions, fault rows (a crash, a signal) that
  name their cell and binaries, development stubs;
- no one-port window against dedicated mode without the freeze guard's clearance: in development
  mode the engine never calls the window for that arm, nothing started names --mode one-port, and
  the in-process window itself refuses to start one;
- the freeze guard on a temporary git repository: every precondition, each refusal;
- rule E's choice, M2's rates, section 10's rates, the pilot's lambda, the hard cases' judge,
  HAProxy's option splice-auto.

    python3 bench/run/test_frozen.py      (exit 0 when every check passes)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "competitors"))
sys.path.insert(0, str(REPO / "analysis"))

import analyse as AN  # noqa: E402
import cells as C  # noqa: E402
import pilot as PL  # noqa: E402
import rows as RW  # noqa: E402

import b3_run  # noqa: E402
import cellwin  # noqa: E402
import competitors as comp  # noqa: E402
import cost_run  # noqa: E402
import freeze_guard  # noqa: E402
import hardcase_run as HR  # noqa: E402
import m_run  # noqa: E402
import pilot_run  # noqa: E402
import rule_e  # noqa: E402
import runlib  # noqa: E402
import s_run  # noqa: E402
import sessions as SS  # noqa: E402

RULE_E = runlib.PROPOSED_RULE_E
SEEDS = {n: 7300 + i for i, n in enumerate(runlib.SEED_NAMES)}
BINS = {"oneport": "a" * 64, "opgen": "b" * 64, "opcase": "c" * 64, "ophold": "d" * 64}


def prov(names=("oneport", "opgen")) -> dict:
    return {"commit": "x", "binaries": {n: BINS[n] for n in names}}


class Clear:
    record = {"pilot": {"sha256": "p"}}
    pilot_entry = True


def frozen_inputs(d: Path) -> tuple[Path, Path, Path]:
    """The seeds, a pilot output and rule E's file that a frozen run reads before its own checks."""
    seeds, pilot, rule = d / "seeds.json", d / "pilot.json", d / "rule_e.json"
    seeds.write_text(json.dumps(SEEDS))
    pilot.write_text(json.dumps({"complete": True, "n_sim": 1000, "R_C": 11}))
    rule.write_text(json.dumps(RULE_E))
    return seeds, pilot, rule


# ---------------------------------------------------------------- stand-in windows


def fake_metric(cell_id: str, row: dict) -> dict:
    if cell_id.startswith("M2."):
        return {"name": C.M2_METRIC, "value": 100.0}
    if row.get("workload") == "open" or cell_id.startswith("S.m-ttfb"):
        return {"name": "ttfb_median_us", "value": 50.0}
    if row.get("workload") == "keepalive":
        return {"name": "req_per_s", "value": 1000.0}
    return {"name": "conn_per_s", "value": 1000.0}


def fake_window(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
    """What the real windows set beside the engine's identity fields: cellwin.run's, handoff's,
    b3.run's fields (the identity fields the engine adds are the same values)."""
    p = cell.run_params(arm)
    ident = cell.identity(arm)
    row = {"valid": True, "invalid_reasons": [], "cell": cell.id}
    if ident.get("kind") == "b3":
        row.update(kind="b3", system=ident["system"], case=ident["case"],
                   footprint={"sample1": {"W": 5000.0}, "sample2": {"W": 5000.0 if ident["system"].startswith("one-port") else 7000.0, "U": 1.0,
                                                                     "Kq": 1.0, "Ks": 4000.0, "f_mean": 0.0, "skb_growth": 0.0, "shared_growth": 0.0}})
        if ident["system"].startswith("one-port"):
            row.update(backend=ident["backend"], detect=ident["detect"])
        return row
    for k in ("workload", "proto", "backend", "mode", "detect", "dispatch", "system", "rate"):
        if k in p:
            row[k] = p[k]
    row["metric"] = fake_metric(cell.id, dict(ident, **row))
    if ident.get("mode") == "one-port":
        row["misclassified"] = 0
    return row


def engine(runner: str, cells: list[SS.Cell], out: Path, win=fake_window, development=True, clearance=None, job="j1", stop=None, seed=11,
           warmup_s: float = 0.0, clock=None, fingerprint=None):
    """The session engine as the runners build it, with no warm-up phase unless a test asks for one
    (the runners never set warmup_s, so theirs is SS.JOB_WARMUP_S)."""
    kw = {"clock": clock} if clock is not None else {}
    return SS.Engine(runner, job, out, cells, SS.make_plan(cells, seed), win, lambda c, arm: prov(), development, clearance,
                     fingerprint=fingerprint, log=lambda s: None, stop_after_sessions=stop, warmup_s=warmup_s, **kw)


def analysed(rows: list[dict], pilot: dict | None = None) -> dict:
    RW.refuse_flags(rows, frozen=False, allow_synthetic=False)
    pilot = pilot or {"R_C": 11, "m_C": 0, "resolved": [], "joint_powers": [], "rates": {}}
    return AN.analyse(rows, pilot=pilot, rule_e=RULE_E, seeds=SEEDS)


def sessions_of(rows: list[dict]) -> list[RW.Session]:
    return RW.assemble(rows, lambda r: RW.row_info(r, RULE_E), AN.roles_for)


def pilot_sessions_of(rows: list[dict]) -> list[RW.Session]:
    return RW.assemble(rows, PL.pilot_info, lambda kind, cid: PL.PILOT_ROLES)


class RowsAgainstAnalysis(unittest.TestCase):
    """Each runner's rows in the contract of analysis/rows.py."""

    def run_cells(self, runner: str, cells: list[SS.Cell], clearance=None, development=True) -> list[dict]:
        with tempfile.TemporaryDirectory() as d:
            eng = engine(runner, cells, Path(d), clearance=clearance, development=development)
            eng.run()
            return eng.rows()

    def test_cost(self):
        cells = [c for c in cost_run.cost_cells(2, RULE_E, {"C3.L.epoll.http1": 500.0}) if c.id in ("C1.L.epoll.http1", "C3.L.epoll.http1")]
        rows = self.run_cells("cost_run", cells, clearance=Clear())
        ss = sessions_of(rows)
        self.assertEqual({s.cell for s in ss}, {"C1.L.epoll.http1", "C3.L.epoll.http1"})
        self.assertTrue(all(s.valid for s in ss))
        self.assertEqual({tuple(sorted(s.roles.values())) for s in ss}, {("dedicated", "one-port")})
        self.assertTrue(all(r["family"] == "C" and r["dispatch"] == "inproc" for r in rows))
        self.assertTrue(all(r.get("rate") == 500.0 for r in rows if r["cell"].startswith("C3.")))
        s = analysed(rows)
        c1 = next(x for x in s["families"]["C"]["cells"] if x["cell"] == "C1.L.epoll.http1")
        self.assertEqual(c1["sessions"], 2)

    def test_cost_development_stubs(self):
        cells = [c for c in cost_run.cost_cells(2, RULE_E, {}) if c.id == "C1.L.io_uring.tls"]
        rows = self.run_cells("cost_run", cells)
        stubs = [r for r in rows if r.get("stub")]
        self.assertEqual(len(stubs), 6)  # two sessions and ceil(2/4) = 1 rerun, two one-port windows each
        self.assertTrue(all(r["mode"] == "one-port" and not r["valid"] and r["provenance"]["binaries"] == {} for r in stubs))
        self.assertTrue(all(r["mode"] == "dedicated" for r in rows if not r.get("stub")))
        ss = sessions_of(rows)
        self.assertTrue(all(not s.valid for s in ss))
        s = analysed(rows)
        c = next(x for x in s["families"]["C"]["cells"] if x["cell"] == "C1.L.io_uring.tls")
        self.assertEqual((c["sessions"], c["valid_sessions"]), (3, 0))

    def test_pilot(self):
        cells = [c for c in pilot_run.pilot_cells(2) if c.id in ("C1.L.epoll.mqtt", "C2.L.io_uring.h2c")]
        rows = self.run_cells("pilot_run", cells, development=True)
        for r in rows:
            r["seed"] = SEEDS["SEED_PILOT_L"]
        entry = PL.pilot_entry(rows, [], SEEDS, n_sim=PL.N_SIM)
        got = {c["cell"]: c["valid_sessions"] for c in entry["cells"] if c["sessions"]}
        self.assertEqual(got, {"C1.L.epoll.mqtt": 2, "C2.L.io_uring.h2c": 2})
        self.assertTrue(all(r["mode"] == "dedicated" and r["arm"] in ("A", "B") for r in rows))

    def test_pilot_parts(self):
        parts = [{"part": "timer", "backend": "epoll", "mode": "dedicated", "run": i, "valid": True, "invalid_reasons": [],
                  "lateness_ns": 400_000 + i, "provenance": prov(("oneport", "opcase"))} for i in range(1, 4)]
        parts += [{"part": "split", "backend": b, "mode": "dedicated", "gap_ms": 5, "replicate": 1, "valid": True, "invalid_reasons": [],
                   "recv_data": 2, "provenance": prov(("oneport", "opcase"))} for b in ("epoll", "io_uring", "IOCP")]
        PL.check_part_rows(parts)
        self.assertEqual(PL.g_values(parts)["L"]["G_ms"], 1)
        self.assertEqual(PL.gap_split(parts)["GAP_SPLIT_ms"], 5)

    def test_b3(self):
        want = ("B3.silent.nginx.epoll", "B3.partial-hello.envoy.io_uring", "B3.silent.netty.io_uring", "S.b3-other-mode.epoll.silent")
        cells = [c for c in b3_run.b3_cells(2, RULE_E, C.SERVER_RELAY) if c.id in want]
        rows = self.run_cells("b3_run", cells, clearance=Clear())
        ss = sessions_of(rows)
        self.assertEqual({s.cell for s in ss}, set(want))
        self.assertTrue(all(s.valid for s in ss))
        s = analysed(rows)
        b = next(x for x in s["families"]["B3"]["cells"] if x["cell"] == "B3.silent.nginx.epoll")
        self.assertEqual(b["sessions"], 2)
        other = [r for r in rows if r["cell"] == "S.b3-other-mode.epoll.silent"]
        self.assertEqual({r["detect"] for r in other}, {"replay", "peek"})
        self.assertTrue(all(r["family"] == "S" and r["bullet"] == "b3-other-mode" for r in other))

    def test_b3_other_mode_system(self):
        # The revision log's reading (entry "M7c's open items, before the code freeze", item 3): the relay.
        self.assertEqual(b3_run.OTHER_MODE_SYSTEM_FROZEN, C.SERVER_RELAY)
        self.assertFalse([c for c in b3_run.b3_cells(2, RULE_E, None) if c.id.startswith("S.b3-other-mode")])
        other = [c for c in b3_run.b3_cells(2, RULE_E, b3_run.OTHER_MODE_SYSTEM_FROZEN) if c.id.startswith("S.b3-other-mode")]
        self.assertEqual(len(other), 4)
        self.assertTrue(all(c.run_params(arm)["system"] == C.SERVER_RELAY for c in other for arm in ("A", "B")))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(b3_run.window, "stop_on_signals", lambda: None):
            seeds, pilot, rule = frozen_inputs(Path(d))
            frozen = ["--build", d, "--out", d, "--job", "j", "--seeds", str(seeds), "--code-freeze", "0" * 40, "--gate",
                      str(Path(d) / "gate.json"), "--pilot", str(pilot), "--rule-e", str(rule)]
            with self.assertRaises(runlib.InputRefused) as cm:  # a frozen run in-process
                b3_run.main(frozen + ["--other-mode-system", C.SERVER_INPROC])
            self.assertIn("--other-mode-system one-port-relay", str(cm.exception))

    def test_m2_without_rate_is_not_run(self):
        # A null M2_RATE (an arm of the m2-rate part without a valid session): the cell is not run,
        # listed with why, and analysis/ leaves it untested, p = 1 (4.1, 4.2).
        rates = {"M2.L.io_uring.tls": None, "M2.L.epoll.http1": 300.0}
        self.assertEqual(set(m_run.m2_not_run(rates)), {"M2.L.io_uring.tls"})
        self.assertEqual(m_run.m2_not_run(None), {})
        ids = {c.id for c in m_run.m_cells(2, RULE_E, rates)}
        self.assertNotIn("M2.L.io_uring.tls", ids)
        self.assertIn("M2.L.epoll.http1", ids)
        self.assertIn("M2.L.io_uring.tls", {c.id for c in m_run.m_cells(6, RULE_E, None, part="m2-rate")})
        cells = [c for c in m_run.m_cells(2, RULE_E, rates) if c.id == "M2.L.epoll.http1"]
        rows = self.run_cells("m_run", cells, clearance=Clear())
        s = analysed(rows)
        m = {x["cell"]: x for x in s["families"]["M"]["cells"]}
        self.assertEqual((m["M2.L.io_uring.tls"]["sessions"], m["M2.L.io_uring.tls"]["tested"]), (0, False))
        self.assertIn("fewer than R", m["M2.L.io_uring.tls"]["why_untested"])

    def test_m2_backend_listener(self):
        # The revision log's design choice (entry "The pre-freeze items on L (M7d), before the code
        # freeze", item 1): M2's dedicated backend in a SO_REUSEPORT group in both parts of the M
        # runner; M3's stub keeps the shared listener; a frozen run takes no other layout.
        self.assertEqual(m_run.M2_BACKEND_LISTENER, "reuseport")
        for part, rates in (("cells", {"M2.L.epoll.tls": 300.0}), ("m2-rate", None)):
            m2 = [c for c in m_run.m_cells(2, RULE_E, rates, part=part) if c.id.startswith("M2.")]
            self.assertTrue(m2)
            self.assertTrue(all(c.run_params(arm)["backend_kind"] == "dedicated" and c.run_params(arm)["backend_listener"] == "reuseport"
                                for c in m2 for arm in ("A", "B")))
        m3 = [c for c in m_run.m_cells(2, RULE_E, None) if c.id.startswith("M3.")]
        self.assertTrue(m3 and all(c.run_params("B")["backend_kind"] == "stub" and "backend_listener" not in c.run_params("B") for c in m3))
        # The window hands the layout to the backend: M2's cfg names the group, M3's the shared listener.
        seen: dict[str, str] = {}

        def fake_window(cfg, session, arm, position, blocks, raw):
            seen[cfg["cell"]] = cfg["backend_listener"]
            return {"metric": {"value": 1.0}, "valid": True}

        with tempfile.TemporaryDirectory() as d, mock.patch.object(m_run.handoff, "run_window", fake_window):
            a = mock.Mock(build=Path(d), k_src=16, out=Path(d))
            win = m_run.window_fn(a, None)
            m2 = next(c for c in m_run.m_cells(2, RULE_E, None, part="m2-rate") if c.id == "M2.L.io_uring.tls")
            m3 = next(c for c in m_run.m_cells(2, RULE_E, None) if c.id == "M3.L.epoll.http1.nginx")
            win(m2, "B", {"id": "s", "job": "j"}, 0, None)
            win(m3, "B", {"id": "s", "job": "j"}, 0, None)
        self.assertEqual(seen, {"M2.L.io_uring.tls": "reuseport", "M3.L.epoll.http1.nginx": "shared"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):  # the stub never takes the group
                m_run.handoff.start_stub(Path(d), 30000, Path(d), "t", "epoll", "stub", "reuseport")
            with self.assertRaises(ValueError):
                m_run.handoff.start_stub(Path(d), 30000, Path(d), "t", "epoll", "dedicated", "spread")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(m_run.window, "stop_on_signals", lambda: None):
            seeds, pilot, rule = frozen_inputs(Path(d))
            frozen = ["--build", d, "--out", d, "--job", "j", "--seeds", str(seeds), "--code-freeze", "0" * 40, "--gate",
                      str(Path(d) / "gate.json"), "--pilot", str(pilot), "--rule-e", str(rule), "--m2-rates", str(Path(d) / "r.json")]
            (Path(d) / "r.json").write_text(json.dumps({"M2.L.epoll.http1": {"rate": 300.0}}))
            with self.assertRaises(runlib.InputRefused) as cm:  # a frozen run with another layout
                m_run.main(frozen + ["--dev-backend-listener", "shared"])
            self.assertIn("development runs only", str(cm.exception))
            with self.assertRaises(runlib.InputRefused) as cm:  # the m2-rate part on the frozen binary
                m_run.main(frozen[:-2] + ["--part", "m2-rate", "--dev-seed", "9", "--dev-backend-listener", "shared"])
            self.assertIn("development runs only", str(cm.exception))

    def test_m(self):
        want = ("M1.L.io_uring.h2c", "M2.L.epoll.tls", "M3.L.epoll.tls-stub.haproxy")
        cells = [c for c in m_run.m_cells(2, RULE_E, {"M2.L.epoll.tls": 300.0}) if c.id in want]
        rows = self.run_cells("m_run", cells, clearance=Clear())
        ss = sessions_of(rows)
        self.assertEqual({s.cell for s in ss}, set(want))
        self.assertTrue(all(s.valid for s in ss))
        m1 = next(s for s in ss if s.cell == "M1.L.io_uring.h2c")
        self.assertEqual(sorted(m1.roles.values()), ["default", "other"])
        s = analysed(rows)
        self.assertEqual({x["cell"] for x in s["families"]["M"]["cells"] if x["sessions"]}, set(want))

    def test_s(self):
        cells, skipped = s_run.s_cells(2, RULE_E, s_run.SILENT_PORTS_FROZEN)
        h2 = [c for c in cells if c.id.startswith("S.tls-variants")]
        self.assertEqual({c.id for c in h2}, {"S.tls-variants.C1.L.epoll.alpn-h2", "S.tls-variants.C1.L.io_uring.alpn-h2"})
        self.assertTrue(all(c.run_params(arm)["gen_proto"] == "tls-h2" and c.identity(arm)["proto"] == "tls"
                            and c.identity(arm)["variant"] == "alpn-h2" for c in h2 for arm in ("A", "B")))
        self.assertTrue(all(c.pairs_one_port_with_dedicated for c in h2))
        res = {k: v for k, v in skipped.items() if k.startswith("S.tls-variants") and k.endswith(".resumption")}
        self.assertEqual(len(res), 3)  # epoll, io_uring and IOCP
        self.assertTrue(all("section 2.1" in v and "ticket" in v for v in res.values()))
        self.assertIn("W's runner", skipped["S.tls-variants.C1.W.IOCP.alpn-h2"])
        want = ("S.ssh.C1.L.epoll", "S.mixed.C1.L.io_uring", "S.two-cores.C1.L.epoll.two-cores", "S.two-cores.C1.L.io_uring.reuseport",
                "S.relay-io_uring.L.io_uring.http1.nginx", "S.m-ttfb.M1.L.epoll.http1", "S.m-ttfb.M3.L.epoll.tls-stub.envoy",
                "S.tls-variants.C1.L.io_uring.alpn-h2")
        cells = [c for c in cells if c.id in want]
        for c in cells:
            c.shared.setdefault("rate", 400.0)
        rows = self.run_cells("s_run", cells, clearance=Clear())
        ss = sessions_of(rows)
        self.assertEqual({s.cell for s in ss}, set(want))
        self.assertTrue(all(s.valid for s in ss))
        analysed(rows)
        h2rows = [r for r in rows if r["cell"] == "S.tls-variants.C1.L.io_uring.alpn-h2"]
        self.assertTrue(h2rows and all(r["proto"] == "tls" and r["variant"] == "alpn-h2" for r in h2rows))
        self.assertEqual({tuple(sorted(x.roles.values())) for x in ss if x.cell == "S.tls-variants.C1.L.io_uring.alpn-h2"},
                         {("dedicated", "one-port")})

    def test_s_mixed_silent_ports(self):
        # The revision log's design choice (entry "M7c's open items, before the code freeze", item 2):
        # the dedicated HTTP/1.1 port, the default; a frozen run refuses spread.
        self.assertEqual(s_run.SILENT_PORTS_FROZEN, "http1")
        cells, skipped = s_run.s_cells(2, RULE_E, None)
        self.assertFalse([c for c in cells if c.id.startswith("S.mixed.")])
        self.assertTrue(any(k.startswith("S.mixed.") for k in skipped))
        cells, _ = s_run.s_cells(2, RULE_E, s_run.SILENT_PORTS_FROZEN)
        mixed = [c for c in cells if c.id.startswith("S.mixed.")]
        self.assertEqual(len(mixed), 2)
        self.assertTrue(all(c.shared["background"]["silent_ports"] == "http1" for c in mixed))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(s_run.window, "stop_on_signals", lambda: None):
            seeds, pilot, rule = frozen_inputs(Path(d))
            frozen = ["--build", d, "--out", d, "--job", "j", "--seeds", str(seeds), "--code-freeze", "0" * 40, "--gate",
                      str(Path(d) / "gate.json"), "--pilot", str(pilot), "--rule-e", str(rule), "--m-rows", str(Path(d) / "m.jsonl")]
            with self.assertRaises(runlib.InputRefused) as cm:  # a frozen run with spread
                s_run.main(frozen + ["--silent-ports", "spread"])
            self.assertIn("--silent-ports http1", str(cm.exception))

    def test_rule_e_file_is_analysis_contract(self):
        self.assertEqual(AN.check_rule_e(json.loads(json.dumps(RULE_E))), RULE_E)


class Engine(unittest.TestCase):
    def cells(self, r: int = 4) -> list[SS.Cell]:
        """Two of the pilot's cells (A/A, dedicated mode), read by analysis/pilot.py's assembler."""
        f = {"workload": "churn", "backend": "epoll", "mode": "dedicated"}
        return [SS.Cell(f"C1.L.epoll.{p}", r, {"A": dict(f, proto=p), "B": dict(f, proto=p)},
                        shared={"workload": "churn", "proto": p, "backend": "epoll"}) for p in ("http1", "h2c")]

    def test_plan_is_fixed_by_the_seed(self):
        a, b = SS.make_plan(self.cells(), 5), SS.make_plan(self.cells(), 5)
        self.assertEqual(a.to_json(), b.to_json())
        self.assertNotEqual(a.to_json()["base"], SS.make_plan(self.cells(), 6).to_json()["base"])
        self.assertEqual(a.caps, {"C1.L.epoll.http1": 1, "C1.L.epoll.h2c": 1})
        self.assertEqual(len(a.x_rerun), 2)

    def test_resume_across_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            e1 = engine("t", self.cells(), Path(d), stop=3, job="j1")
            e1.run()
            e2 = engine("t", self.cells(), Path(d), job="j2")
            e2.run()
            rows = e2.rows()
            ids = [(r["job"], r["session"]) for r in rows]
            self.assertEqual(len({i[1] for i in ids}), 8)
            self.assertEqual(sum(1 for i in set(ids) if i[0] == "j1"), 3)
            self.assertEqual(len(rows), 32)

    def test_reruns_capped_and_never_more_than_r_valid(self):
        bad = {"n": 0}

        def flaky(cell, arm, session, position, clr):
            row = fake_window(cell, arm, session, position, clr)
            if cell.id.endswith("http1") and position == 1:
                bad["n"] += 1
                row.update(valid=False, invalid_reasons=["CPU MHz drift 3% > 2%"])
            return row

        with tempfile.TemporaryDirectory() as d:
            e = engine("t", self.cells(4), Path(d), win=flaky)
            summ = e.run()
            h = summ["cells"]["C1.L.epoll.http1"]
            self.assertEqual((h["sessions"], h["valid"], h["reruns"]), (5, 0, 1))  # 4 base + ceil(4/4) = 1 rerun
            self.assertEqual(summ["cells"]["C1.L.epoll.h2c"]["valid"], 4)
            ss = pilot_sessions_of(e.rows())
            self.assertEqual(sum(1 for s in ss if s.valid), 4)

    def test_rerun_once_a_session_is_invalid(self):
        hit = {"done": False}

        def once(cell, arm, session, position, clr):
            row = fake_window(cell, arm, session, position, clr)
            if not hit["done"] and cell.id.endswith("h2c"):
                hit["done"] = True
                row.update(valid=False, invalid_reasons=["probe failed"])
            return row

        with tempfile.TemporaryDirectory() as d:
            summ = engine("t", self.cells(4), Path(d), win=once).run()
            self.assertEqual(summ["cells"]["C1.L.epoll.h2c"]["valid"], 4)
            self.assertEqual(summ["cells"]["C1.L.epoll.h2c"]["reruns"], 1)

    def test_fault_rows_name_cell_and_binaries(self):
        def crash(cell, arm, session, position, clr):
            raise RuntimeError("the server did not start")

        with tempfile.TemporaryDirectory() as d:
            e = engine("t", self.cells(1), Path(d), win=crash, development=False, clearance=Clear())
            e.run()
            rows = e.rows()
            self.assertTrue(all(r["driver_fault"] and not r["valid"] and r["provenance"]["binaries"] for r in rows))
            self.assertTrue(all(r["mode"] == "dedicated" and r["development"] is False for r in rows))
            ss = pilot_sessions_of(rows)  # a session of four fault rows still names its cell
            self.assertEqual({s.cell for s in ss}, {"C1.L.epoll.http1", "C1.L.epoll.h2c"})

    def test_signal_writes_a_row_then_stops(self):
        def stopped(cell, arm, session, position, clr):
            if position == 2:
                raise SystemExit(143)
            return fake_window(cell, arm, session, position, clr)

        with tempfile.TemporaryDirectory() as d:
            e = engine("t", self.cells(1), Path(d), win=stopped)
            with self.assertRaises(SystemExit):
                e.run()
            rows = e.rows()
            self.assertEqual([r["position"] for r in rows], [0, 1, 2])
            self.assertIn(SS.SIGNAL_REASON, rows[-1]["invalid_reasons"])
            e2 = engine("t", self.cells(1), Path(d), job="j2")
            e2.run()
            ss = pilot_sessions_of(e2.rows())
            self.assertEqual(sum(1 for s in ss if s.valid), 2)  # the cut session is rerun


class FakeClock:
    """A clock that each window moves on by `step` seconds."""

    def __init__(self, step: float):
        self.t, self.step = 1000.0, step

    def __call__(self) -> float:
        return self.t


class JobWarmUp(unittest.TestCase):
    """The job's warm-up (bench/run/sessions.py; the revision log's entry "The job's warm-up and W's
    runners (M7e), before the code freeze"): a discarded phase of 80 s before the job's first session."""

    def cells(self, r: int = 2) -> list[SS.Cell]:
        return Engine.cells(self, r)

    def recording(self, clock: FakeClock, calls: list, fail: bool = False):
        def win(cell, arm, session, position, clr):
            calls.append((session["id"], arm, position))
            clock.t += clock.step
            if fail and session.get("warmup"):
                raise RuntimeError("the server did not start")
            return fake_window(cell, arm, session, position, clr)
        return win

    def test_runners_take_the_frozen_length(self):
        self.assertEqual(SS.JOB_WARMUP_S, 80.0)
        self.assertEqual(SS.Engine.__dataclass_fields__["warmup_s"].default, SS.JOB_WARMUP_S)
        for name in ("pilot_run", "cost_run", "b3_run", "m_run", "rule_e", "s_run", "wpilot_run", "wcost_run", "wm_run", "ws_run",
                     "wrule_e"):
            self.assertNotIn("warmup_s", (HERE / f"{name}.py").read_text(encoding="utf-8"), name)

    def test_before_the_first_session_and_no_row(self):
        clock, calls, fps = FakeClock(30.0), [], []

        def fp():
            fps.append(len(calls))
            return {"mean_mhz": 3000.0}

        with tempfile.TemporaryDirectory() as d:
            e = engine("t", self.cells(), Path(d), win=self.recording(clock, calls), warmup_s=80.0, clock=clock, fingerprint=fp)
            e.run()
            rows = e.rows()
            rec = json.loads((Path(d) / "warmup-t-j1.json").read_text())
        warm = [c for c in calls if c[0] == "warmup-j1"]
        self.assertEqual(len(warm), 3)                       # 0, 30, 60 s, then 90 >= 80 s
        self.assertEqual(calls[:3], warm)                     # before every session window
        first = SS.make_plan(self.cells(), 11).base[0]
        x = SS.make_plan(self.cells(), 11).x_base[first]
        self.assertEqual([c[1] for c in warm], [x, SS.other(x), x])
        self.assertEqual(rec["cell"], first[0])
        self.assertEqual((rec["ended_by"], len(rec["windows"]), rec["elapsed_s"]), ("length", 3, 90.0))
        self.assertEqual(fps[:2], [0, 3])                     # the phase's own fingerprint, then the first session's after it
        self.assertEqual(len(rows), 4 * 2 * 2)                # the sessions' windows only
        self.assertFalse([r for r in rows if str(r.get("session", "")).startswith("warmup")])
        self.assertNotIn("metric", json.dumps(rec["windows"]))

    def test_order_and_rows_are_unchanged(self):
        def strip(rows):
            return [{k: v for k, v in r.items() if k not in ("fingerprint",)} for r in rows]

        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            a = engine("t", self.cells(), Path(d1))
            a.run()
            clock = FakeClock(50.0)
            b = engine("t", self.cells(), Path(d2), win=self.recording(clock, []), warmup_s=80.0, clock=clock)
            b.run()
            self.assertEqual(strip(a.rows()), strip(b.rows()))
            self.assertFalse((Path(d1) / "warmup-t-j1.json").exists())

    def test_never_a_stub(self):
        clock, calls = FakeClock(30.0), []
        cells = [c for c in cost_run.cost_cells(1, RULE_E, {}) if c.id == "C1.L.epoll.http1"]
        with tempfile.TemporaryDirectory() as d:
            e = engine("cost_run", cells, Path(d), win=self.recording(clock, calls), warmup_s=80.0, clock=clock)
            e.run()
            rec = json.loads((Path(d) / "warmup-cost_run-j1.json").read_text())
        self.assertEqual(rec["arms"], ["B"])                  # the dedicated arm: arm A is one-port, a development stub
        self.assertEqual(rec["stubbed_arms"], ["A"])
        self.assertFalse([c for c in calls if c[1] == "A"])  # the window function never sees the one-port arm

    def test_two_faults_end_it_early(self):
        clock, calls = FakeClock(1.0), []
        with tempfile.TemporaryDirectory() as d:
            e = engine("t", self.cells(1), Path(d), win=self.recording(clock, calls, fail=True), warmup_s=80.0, clock=clock)
            e.run()
            rec = json.loads((Path(d) / "warmup-t-j1.json").read_text())
            self.assertEqual(len(e.rows()), 8)
        self.assertEqual(rec["ended_by"], f"{SS.JOB_WARMUP_MAX_FAULTS} driver faults in a row")
        self.assertEqual([w["fault"] for w in rec["windows"]], [True, True])

    def test_a_resumed_job_with_nothing_left_runs_none(self):
        with tempfile.TemporaryDirectory() as d:
            engine("t", self.cells(1), Path(d)).run()
            clock, calls = FakeClock(30.0), []
            e2 = engine("t", self.cells(1), Path(d), win=self.recording(clock, calls), job="j2", warmup_s=80.0, clock=clock)
            e2.run()
            self.assertEqual(calls, [])
            self.assertFalse((Path(d) / "warmup-t-j2.json").exists())

    def test_a_signal_ends_it_with_its_record(self):
        clock = FakeClock(30.0)

        def stop(cell, arm, session, position, clr):
            clock.t += clock.step
            if session.get("warmup") and position == 1:
                raise SystemExit(143)
            return fake_window(cell, arm, session, position, clr)

        with tempfile.TemporaryDirectory() as d:
            e = engine("t", self.cells(1), Path(d), win=stop, warmup_s=80.0, clock=clock)
            with self.assertRaises(SystemExit):
                e.run()
            rec = json.loads((Path(d) / "warmup-t-j1.json").read_text())
            self.assertEqual(e.rows(), [])
        self.assertEqual(rec["ended_by"], "a signal to the job")


class NoOnePortAgainstDedicated(unittest.TestCase):
    """Section 8 step 2, the guarantee of the end-to-end check."""

    def test_frozen_engine_refuses_without_clearance(self):
        cells = [c for c in cost_run.cost_cells(1, RULE_E, {}) if c.id == "C1.L.epoll.http1"]
        with tempfile.TemporaryDirectory() as d:
            e = engine("cost_run", cells, Path(d), development=False)
            with self.assertRaises(RuntimeError):
                e.run()

    def test_cellwin_refuses_one_port_without_clearance(self):
        p = {"mode": "one-port", "pairs_dedicated": True}
        with self.assertRaises(cellwin.WindowError):
            cellwin.guard(p, None)
        with self.assertRaises(cellwin.WindowError):
            cellwin.guard(p, freeze_guard.Clearance({}))  # a clearance without the pilot entry
        cellwin.guard(p, Clear())
        cellwin.guard({"mode": "one-port", "pairs_dedicated": False}, None)  # M1, reuseport: one-port against one-port
        cellwin.guard({"mode": "dedicated", "pairs_dedicated": True}, None)

    def test_development_cost_session_starts_no_one_port_server(self):
        """The real window function of cost_run (cellwin.run), every process start recorded and
        refused: the one-port arm is never called, the dedicated arm tries to start its server."""
        started: list[list[str]] = []

        def popen(argv, *a, **k):
            started.append([str(x) for x in argv])
            raise OSError("no process in this test")

        cells = [c for c in cost_run.cost_cells(2, RULE_E, {}) if c.id in ("C1.L.epoll.http1", "C2.L.io_uring.mqtt")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(cellwin.subprocess, "Popen", popen), \
                mock.patch.object(cellwin.window, "conntrack", lambda: None), \
                mock.patch.object(cellwin.window, "wait_conntrack", lambda *a, **k: (0.0, None)), \
                mock.patch.object(cellwin.window, "time_wait_count", lambda: 0), \
                mock.patch.object(cellwin.window, "nstat", lambda: {k: 0 for k in cellwin.window.NSTAT_KEYS}):
            blocks = cellwin.window.SourceBlocks(Path(d) / "blocks.json")

            def win(cell, arm, session, position, clr):
                return cellwin.run(dict(cell.run_params(arm), build=Path(d), cell=cell.id, k_src=4), session, arm, position, blocks,
                                   Path(d) / "raw", clr)

            e = engine("cost_run", cells, Path(d), win=win)
            summ = e.run()
            rows = e.rows()
        self.assertTrue(started, "the dedicated arm's server start was not reached")
        self.assertFalse([a for a in started if "one-port" in a], started)
        self.assertTrue(all(a[a.index("--mode") + 1] == "dedicated" for a in started))
        sessions = sum(c["sessions"] for c in summ["cells"].values())
        self.assertEqual(sessions, 6)  # 2 cells x (2 sessions + ceil(2/4) = 1 rerun), every session invalid
        self.assertEqual(sum(1 for r in rows if r.get("stub")), 2 * sessions)
        self.assertEqual(len(started), 2 * sessions)


class MixedBackground(unittest.TestCase):
    """The mixed cell's background report in each row keeps its generators' CPU time (the revision
    log's entry "M7c's open items, before the code freeze", items 1 and 8)."""

    def test_finish_keeps_the_generators_cpu(self):
        done = mock.Mock(returncode=0)
        done.poll.return_value = 0
        done.wait.return_value = 0
        silent_lines = mock.Mock()
        silent_lines.rest.return_value = ['HOLD 64', '{"ok": true, "reopened": 0}']
        gen_lines = mock.Mock()
        gen_lines.rest.return_value = []
        with tempfile.TemporaryDirectory() as d:
            bg = object.__new__(cellwin.Background)
            bg.raw, bg.tag = Path(d), "t"
            bg.procs = {"tls": done, "mqtt": done, "silent": done}
            bg.lines = {"tls": gen_lines, "mqtt": gen_lines, "silent": silent_lines}
            for k in ("tls", "mqtt"):
                (Path(d) / f"t.bg-{k}.json").write_text(json.dumps({"ok": True, "error_share": 0.0, "cpus": [10, 11],
                                                                     "cpu": {"pct": 25.0}, "measure": {"completed": 5}}))
            out = bg.finish()
        self.assertEqual(out["tls"]["report"]["cpu"], {"pct": 25.0})
        self.assertEqual(out["mqtt"]["report"]["cpus"], [10, 11])
        self.assertEqual(out["silent"]["report"], {"ok": True, "reopened": 0})


def opgen_json(connects_run: int, completed: int = 5) -> dict:
    """A report with the keys opgen writes (bench/gen/options.cpp, to_json): `measure` and `warmup`
    hold only `completed` and `errors`; the run's connects, warm-up included, are `connects_run`."""
    errs = {"connect": 0, "timeout": 0, "reset": 0, "eof": 0, "protocol": 0, "tls": 0, "total": 0}
    return {"tool": "opgen", "ok": True, "error": "", "load": "keepalive", "mode": "closed", "cpus": [10, 11], "measure_start_ns": 1,
            "measure_end_ns": 2, "wall_s": 5.0, "warmup": {"completed": 1, "errors": errs}, "measure": {"completed": completed, "errors": errs},
            "connects_run": connects_run, "all_completed": completed + 1, "error_share": 0.0, "connect_failures": 0, "cpu": {"pct": 25.0}}


def finished_background(tls: dict | None, mqtt: dict | None) -> dict:
    """cellwin.Background.finish on the given report files (None: the generator wrote none)."""
    done = mock.Mock(returncode=0)
    done.poll.return_value = 0
    done.wait.return_value = 0
    silent_lines = mock.Mock()
    silent_lines.rest.return_value = ['HOLD 64', '{"ok": true, "reopened": 0}']
    gen_lines = mock.Mock()
    gen_lines.rest.return_value = []
    with tempfile.TemporaryDirectory() as d:
        bg = object.__new__(cellwin.Background)
        bg.raw, bg.tag = Path(d), "t"
        bg.procs = {"tls": done, "mqtt": done, "silent": done}
        bg.lines = {"tls": gen_lines, "mqtt": gen_lines, "silent": silent_lines}
        for k, rep in (("tls", tls), ("mqtt", mqtt)):
            if rep is not None:
                (Path(d) / f"t.bg-{k}.json").write_text(json.dumps(rep))
        return bg.finish()


# Two one-port windows of the mixed cell in lab job sl1 (design/status.md, "L after the cost family",
# section 4 item 1): the cell's opgen `connects_run`, and the server's classified counts, which hold
# the churn and the probe as HTTP/1.1 and the background's 64 TLS and 64 MQTT connections.
SL1_WINDOWS = (("S.mixed.C1.L.epoll.s02", 105_736, {"HTTP/1.1": 105_737, "TLS": 64, "MQTT": 64}),
               ("S.mixed.C1.L.io_uring.s02", 752, {"HTTP/1.1": 753, "TLS": 64, "MQTT": 64}))


def classified(**over: int) -> dict:
    cl = {"TLS": 0, "h2c": 0, "HTTP/1.1": 0, "SSH": 0, "MQTT": 0, "SMTP": 0}
    cl.update(over)
    return {"classified": cl}


class MixedB1Count(unittest.TestCase):
    """B1's count in the mixed cell (section 7, section 10): each class's bound comes from the
    connects opgen reports, `connects_run`, in the cell's report and in each background report as
    Background.finish keeps it."""

    def test_sl1_windows_count_none(self):
        for session, run, counts in SL1_WINDOWS:
            with self.subTest(session):
                bg = finished_background(opgen_json(64), opgen_json(64))
                expected, unread = cellwin.expected_classes("http1", opgen_json(run), bg)
                self.assertEqual(unread, [])
                self.assertEqual(expected, {"HTTP/1.1": run + 1, "TLS": 64, "MQTT": 64})
                self.assertEqual(cellwin.misclassified(classified(**counts), expected), 0)

    def test_a_misclassified_connection_still_counts(self):
        bg = finished_background(opgen_json(64), opgen_json(64))
        expected, _ = cellwin.expected_classes("http1", opgen_json(752), bg)
        self.assertEqual(cellwin.misclassified(classified(**{"HTTP/1.1": 754}, TLS=64, MQTT=64), expected), 1)
        self.assertEqual(cellwin.misclassified(classified(**{"HTTP/1.1": 753}, TLS=63, MQTT=65), expected), 1)
        self.assertEqual(cellwin.misclassified(classified(**{"HTTP/1.1": 753}, TLS=64, MQTT=64, h2c=2), expected), 2)

    def test_outside_the_mixed_cell_any_count_of_the_scripts_class(self):
        for proto, name in cellwin.CLASS.items():
            with self.subTest(proto):
                self.assertEqual(cellwin.expected_classes(proto, opgen_json(9), None), ({name: None}, []))

    def test_a_count_not_read_is_no_bound_and_never_zero(self):
        no_key = {k: v for k, v in opgen_json(64).items() if k != "connects_run"}
        bg = finished_background(no_key, None)
        expected, unread = cellwin.expected_classes("http1", opgen_json(752), bg)
        self.assertEqual(expected, {"HTTP/1.1": 753, "TLS": None, "MQTT": None})
        self.assertEqual(len(unread), 1)
        self.assertIn("connects_run", unread[0])
        self.assertIn("tls", unread[0])
        # The cell's generator wrote no report: the background's bounds still hold.
        expected, unread = cellwin.expected_classes("http1", None, finished_background(opgen_json(64), opgen_json(64)))
        self.assertEqual((expected, unread), ({"HTTP/1.1": None, "TLS": 64, "MQTT": 64}, []))
        self.assertEqual(cellwin.misclassified(classified(**{"HTTP/1.1": 900}, TLS=64, MQTT=64), expected), 0)

    def test_the_row_of_a_mixed_window(self):
        for session, run, counts in SL1_WINDOWS:
            with self.subTest(session):
                row = {"valid": True, "invalid_reasons": []}
                cellwin.b1_count(row, classified(**counts), "http1", opgen_json(run), finished_background(opgen_json(64), opgen_json(64)))
                self.assertEqual(row, {"valid": True, "invalid_reasons": [], "misclassified": 0, "misclassified_unbounded": []})
        no_key = {k: v for k, v in opgen_json(64).items() if k != "connects_run"}
        row = {"valid": True, "invalid_reasons": []}
        cellwin.b1_count(row, classified(**{"HTTP/1.1": 753}, TLS=64, MQTT=64), "http1", opgen_json(752), finished_background(no_key, None))
        self.assertFalse(row["valid"])
        self.assertEqual(row["misclassified"], 0)
        self.assertEqual(row["misclassified_unbounded"], ["MQTT", "TLS"])
        self.assertEqual(len(row["invalid_reasons"]), 1)
        self.assertIn("connects_run", row["invalid_reasons"][0])

    def test_the_row_outside_the_mixed_cell_is_as_frozen(self):
        row = {"valid": True, "invalid_reasons": []}
        cellwin.b1_count(row, classified(**{"HTTP/1.1": 100_001}), "http1", opgen_json(100_000), None)
        self.assertEqual(row, {"valid": True, "invalid_reasons": [], "misclassified": 0})
        row = {"valid": True, "invalid_reasons": []}
        cellwin.b1_count(row, classified(**{"HTTP/1.1": 100_001}, h2c=1), "http1", opgen_json(100_000), None)
        self.assertEqual(row, {"valid": False, "misclassified": 1,
                               "invalid_reasons": ["1 connections classified other than as their scripts' protocol (B1)"]})

    def test_the_runner_takes_the_rule_from_it(self):
        text = Path(cellwin.__file__).read_text(encoding="utf-8")
        self.assertIn("b1_count(row, counters, gproto, gen_report", text.split("def run(", 1)[1])
        self.assertNotIn('get("connects"', text)


class AlpnH2Window(unittest.TestCase):
    """Section 10's TLS variant with ALPN h2 through cellwin.run: the row says proto tls, the probe
    and opgen run tls-h2, against the dedicated TLS port, or the one-port listener with a clearance."""

    def run_arm(self, mode: str, clearance) -> tuple[list, list]:
        probes, gens = [], []

        class Stop(Exception):
            pass

        def start_server(build, p, pl, raw, tag):
            return (mock.Mock(pid=1), mock.Mock(lines=[]), {"HTTP/1.1": 20000, "TLS": 20002, "one-port": 20100}, ["oneport"])

        def probe(build, proto, port, base, k, gen_cpus=None):
            probes.append((proto, port))
            return {"exit": 0, "detail": "", "connect_failures": 0}

        def popen_err(err, cmd, **k):
            gens.append(cmd)
            raise Stop()

        cell = next(c for c in s_run.s_cells(1, RULE_E, s_run.SILENT_PORTS_FROZEN)[0] if c.id == "S.tls-variants.C1.L.epoll.alpn-h2")
        arm = "A" if mode == "one-port" else "B"
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(cellwin, "start_server", start_server), \
                mock.patch.object(cellwin, "popen_err", popen_err), \
                mock.patch.object(cellwin.window, "probe", probe), \
                mock.patch.object(cellwin.window, "stop_process", lambda *a, **k: (0, [])), \
                mock.patch.object(cellwin.window, "conntrack", lambda: None), \
                mock.patch.object(cellwin.window, "wait_conntrack", lambda *a, **k: (0.0, None)), \
                mock.patch.object(cellwin.window, "time_wait_count", lambda: 0), \
                mock.patch.object(cellwin.window, "nstat", lambda: {k: 0 for k in cellwin.window.NSTAT_KEYS}):
            blocks = cellwin.window.SourceBlocks(Path(d) / "blocks.json")
            self.assertEqual(cell.arms[arm]["mode"], mode)
            with self.assertRaises(Stop):
                cellwin.run(dict(cell.run_params(arm), build=Path(d), cell=cell.id, k_src=4, port=20000), {"id": "s"}, arm, 0, blocks,
                            Path(d) / "raw", clearance)
        return probes, gens

    def test_dedicated_arm(self):
        probes, gens = self.run_arm("dedicated", None)
        self.assertEqual(probes, [("tls-h2", 20002)])
        cmd = gens[0]
        self.assertEqual((cmd[cmd.index("--proto") + 1], cmd[cmd.index("--port") + 1]), ("tls-h2", "20002"))

    def test_one_port_arm(self):
        with self.assertRaises(cellwin.WindowError):
            self.run_arm("one-port", None)  # no clearance: no one-port window against dedicated mode
        probes, gens = self.run_arm("one-port", Clear())
        self.assertEqual(probes, [("tls-h2", 20100)])
        self.assertIn("tls-h2", gens[0])


# ---------------------------------------------------------------- the freeze guard


def git(repo: Path, *a: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True, env=env).stdout.strip()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class FreezeGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.repo = Path(self.tmp.name) / "repo"
        (r / "bench").mkdir(parents=True)
        git(r.parent, "init", "-q", str(r))
        (r / "bench" / "x.py").write_text("x = 1\n")
        (r / "hypotheses.md").write_text("# H\n\n## Revision log\n")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "freeze")
        self.cf = git(r, "rev-parse", "HEAD")
        self.seeds = Path(self.tmp.name) / "seeds.json"
        self.seeds.write_text(json.dumps(SEEDS))
        self.pilot = Path(self.tmp.name) / "pilot.json"
        self.pilot.write_text(json.dumps({"complete": True, "n_sim": 1000, "synthetic": False, "R_C": 15}))
        self.rule_e = Path(self.tmp.name) / "rule_e.json"
        self.rule_e.write_text(json.dumps(RULE_E))
        self.gate = Path(self.tmp.name) / "gate-L.json"
        self.gate.write_text(json.dumps({"passed": True, "citable": True, "binaries": BINS}))
        self.log(f"- `CODE_FREEZE` = {self.cf}\n- seeds: sha256 {sha(self.seeds)}\n")
        self.log(f"- The pilot entry: pilot.json sha256 {sha(self.pilot)}\n")
        self.log(f"- rule E's choices: rule_e.json sha256 {sha(self.rule_e)}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, text: str) -> None:
        h = self.repo / "hypotheses.md"
        h.write_text(h.read_text() + text)
        git(self.repo, "commit", "-q", "-am", "log")

    def check(self, **kw):
        args = dict(repo=self.repo, code_freeze=self.cf, seeds=self.seeds, gates=[self.gate], binaries={"oneport": BINS["oneport"]},
                    pilot=self.pilot, rule_e=self.rule_e)
        args.update(kw)
        return freeze_guard.check(**args)

    def test_passes(self):
        c = self.check()
        self.assertTrue(c.pilot_entry)
        self.assertEqual(c.record["freeze"]["code_freeze"], self.cf)

    def test_refusals(self):
        refuse = freeze_guard.FreezeRefused
        with self.assertRaises(refuse):
            self.check(code_freeze=self.cf[:12])
        other = Path(self.tmp.name) / "pilot2.json"
        other.write_text(json.dumps({"complete": True, "n_sim": 1000}))
        with self.assertRaises(refuse):
            self.check(pilot=other)  # not logged
        inc = Path(self.tmp.name) / "pilot3.json"
        inc.write_text(json.dumps({"complete": False, "incomplete": ["no window of host W"], "n_sim": 1000}))
        self.log(f"- pilot sha256 {sha(inc)}\n")
        with self.assertRaises(refuse):
            self.check(pilot=inc)  # logged but incomplete
        with self.assertRaises(refuse):
            self.check(binaries={"oneport": "0" * 64})
        dry = Path(self.tmp.name) / "gate-dry.json"
        dry.write_text(json.dumps({"passed": True, "dry_run": True, "citable": False, "binaries": BINS}))
        with self.assertRaises(refuse):
            self.check(gates=[dry])
        (self.repo / "hypotheses.md").write_text((self.repo / "hypotheses.md").read_text() + "uncommitted\n")
        with self.assertRaises(refuse):
            self.check()
        git(self.repo, "checkout", "--", "hypotheses.md")
        (self.repo / "bench" / "x.py").write_text("x = 2\n")
        git(self.repo, "commit", "-q", "-am", "a change after the freeze")
        with self.assertRaises(refuse):
            self.check()

    def test_entries(self):
        title = freeze_guard.M7C_ITEMS
        with self.assertRaises(freeze_guard.FreezeRefused):
            self.check(entries=(title,))
        self.log(f"- {title}, named in an item, is not a heading\n")
        with self.assertRaises(freeze_guard.FreezeRefused):
            self.check(entries=(title,))
        self.log(f"\n### 2026-10-04: {title}\n")
        self.assertEqual(self.check(entries=(title,)).record["entries"], [title])

    def test_pilot_logged_in_the_freeze_commit_is_refused(self):
        r = self.repo
        p = Path(self.tmp.name) / "pilot-early.json"
        p.write_text(json.dumps({"complete": True, "n_sim": 1000, "x": 1}))
        h = r / "hypotheses.md"
        h.write_text(h.read_text() + f"- pilot sha256 {sha(p)}\n")
        (r / "bench" / "x.py").write_text("x = 3\n")
        git(r, "commit", "-q", "-am", "a second freeze with the pilot logged in it")
        cf2 = git(r, "rev-parse", "HEAD")
        self.log(f"- `CODE_FREEZE` = {cf2}\n")
        with self.assertRaises(freeze_guard.FreezeRefused):
            self.check(code_freeze=cf2, pilot=p, rule_e=None)

    def later_change(self, path: str = "bench/run/x.py", text: str = "x = 2\n") -> str:
        f = self.repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "a later change")
        return git(self.repo, "rev-parse", "HEAD")

    def refused(self, why: str) -> None:
        with self.assertRaisesRegex(freeze_guard.FreezeRefused, why):
            self.check()

    def test_a_later_change_runs_on_the_commit_the_log_names(self):
        """Section 8, the rule for a later change: the revision log names the change's commit by
        CHANGE_COMMIT; the runs are checked against it; the pilot entry, logged before it, counts."""
        self.assertNotIn("change_commit", self.check().record["freeze"])
        change = self.later_change()
        self.refused("changed since CODE_FREEZE")  # not logged yet
        self.log(f"- The change's commit:\n   CHANGE_COMMIT = {change}\n")
        c = self.check()
        self.assertEqual(c.record["freeze"], {"code_freeze": self.cf, "head": git(self.repo, "rev-parse", "HEAD"), "change_commit": change})
        self.assertTrue(c.pilot_entry)
        (self.repo / "bench" / "run" / "x.py").write_text("x = 3\n")
        self.refused("the working tree changes frozen paths")
        git(self.repo, "commit", "-q", "-am", "a change the log does not name")
        self.refused("changed since CHANGE_COMMIT")
        second = git(self.repo, "rev-parse", "HEAD")
        self.log(f"   CHANGE_COMMIT = {second}\n")
        self.assertEqual(self.check().record["freeze"]["change_commit"], second)  # the last one named
        self.log(f"- named again: CHANGE_COMMIT = {second}\n")
        self.assertEqual(self.check().record["freeze"]["change_commit"], second)

    def test_code_freeze_named_as_a_change_is_refused(self):
        self.log(f"   CHANGE_COMMIT = {self.cf}\n")
        self.refused("does not descend from")

    def test_a_change_off_heads_history_is_refused(self):
        git(self.repo, "checkout", "-q", "-b", "side")
        side = self.later_change()
        git(self.repo, "checkout", "-q", "-")
        self.log("- a line on HEAD's branch, so the copy below is a commit of its own\n")
        git(self.repo, "cherry-pick", side)  # the same tree on HEAD's branch, so only the order can refuse
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD"), side)
        self.log(f"   CHANGE_COMMIT = {side}\n")
        self.refused("was logged in")

    def test_a_change_line_with_two_commits_is_refused(self):
        change = self.later_change()
        self.log(f"   CHANGE_COMMIT = {change} after {self.cf}\n")
        self.refused("names 2 commits")

    def test_a_change_beyond_the_runners_python_is_refused(self):
        for path in ("bench/x.py", "bench/run/x.sh", "bench/run/sub/x.py", "tests/x.cpp", "CMakeLists.txt"):
            with self.subTest(path):
                self.tearDown()
                self.setUp()
                change = self.later_change(path)
                self.log(f"   CHANGE_COMMIT = {change}\n")
                self.refused("other than the Python of bench/run")
        with self.subTest("a frozen file moved into bench/run"):
            self.tearDown()
            self.setUp()
            (self.repo / "bench" / "run").mkdir()
            git(self.repo, "mv", "bench/x.py", "bench/run/x.py")
            git(self.repo, "commit", "-q", "-m", "a move")
            change = git(self.repo, "rev-parse", "HEAD")
            self.log(f"   CHANGE_COMMIT = {change}\n")
            self.refused("other than the Python of bench/run")

    def test_the_word_without_a_commit_names_no_change(self):
        self.log("- the freeze guard reads CHANGE_COMMIT from this log\n")
        self.assertNotIn("change_commit", self.check().record["freeze"])

    def test_rule_e_before_the_pilot_entry_is_refused(self):
        r2 = Path(self.tmp.name) / "rule_e2.json"
        r2.write_text(json.dumps(dict(RULE_E, note=1)))
        p2 = Path(self.tmp.name) / "pilot4.json"
        p2.write_text(json.dumps({"complete": True, "n_sim": 1000, "y": 2}))
        self.log(f"- rule E sha256 {sha(r2)}\n")
        self.log(f"- pilot entry sha256 {sha(p2)}\n")
        with self.assertRaises(freeze_guard.FreezeRefused):
            self.check(pilot=p2, rule_e=r2)

    def test_cost_run_checks_the_guard_before_any_window(self):
        called = []
        with mock.patch.object(freeze_guard, "check", side_effect=freeze_guard.FreezeRefused("no pilot entry")), \
                mock.patch.object(runlib, "job_provenance", lambda *a, **k: {"binaries_all": BINS}), \
                mock.patch.object(SS.Engine, "run", lambda self: called.append(1)), \
                mock.patch.object(cost_run.window, "stop_on_signals", lambda: None), \
                tempfile.TemporaryDirectory() as d:
            with self.assertRaises(freeze_guard.FreezeRefused):
                cost_run.main(["--build", d, "--out", d, "--job", "j", "--seeds", str(self.seeds), "--code-freeze", self.cf,
                               "--gate", str(self.gate), "--pilot", str(self.pilot), "--rule-e", str(self.rule_e)])
        self.assertEqual(called, [])
        with self.assertRaises(runlib.InputRefused):
            cost_run.main(["--build", ".", "--out", ".", "--job", "j", "--seeds", str(self.seeds), "--gate", str(self.gate)])


# ---------------------------------------------------------------- the rules the runners compute


def rule_rows(cell: str, sessions: list[tuple[float, float]], ops: tuple[float, float]) -> list[dict]:
    rows = []
    for i, (va, vb) in enumerate(sessions):
        for pos, arm in enumerate("ABBA"):
            v, o = (va, ops[0]) if arm == "A" else (vb, ops[1])
            rows.append({"session": f"{cell}.s{i + 1:02d}", "cell": cell, "position": pos, "arm": arm, "valid": True, "order_index": i,
                         "metric": {"name": "conn_per_s", "value": v},
                         "server_counters": {"accepted": 100, "recv_calls": int(o * 100)}})
    return rows


class Rules(unittest.TestCase):
    def test_rule_e(self):
        cells = rule_e.rule_e_cells(6)
        win = [(100.0, 101.0)] * 6
        rows = rule_rows("rule-e.detect.epoll", win, (5.0, 5.0)) + rule_rows("rule-e.relay.epoll", win, (5.0, 6.0))
        rows += rule_rows("rule-e.detect.io_uring", [(100.0, 101.0)] * 5 + [(100.0, 99.0)], (5.0, 4.0))
        rows += rule_rows("rule-e.relay.io_uring", [(100.0, 101.0)] * 5, (5.0, 4.0))
        ev = rule_e.evidence(rows, cells)
        self.assertEqual(ev["epoll"]["detect"]["choice"], "peek")            # every session favours it, ops not higher
        self.assertEqual(ev["epoll"]["relay"]["choice"], "user-space")       # ops higher
        self.assertEqual(ev["io_uring"]["detect"]["choice"], "replay")       # one session against it
        self.assertEqual(ev["io_uring"]["relay"]["choice"], "user-space")    # fewer than 6 valid sessions
        rule, notes = rule_e.decide(ev, None, development=True)
        self.assertEqual(rule["default"], {"epoll": "peek", "io_uring": "replay", "IOCP": "replay"})
        self.assertIn("IOCP", notes)
        with self.assertRaises(runlib.InputRefused):
            rule_e.decide(ev, None, development=False)
        self.assertEqual(AN.check_rule_e(rule), rule)
        part = {b: {"relay": e["relay"]} for b, e in ev.items()}  # only the relay sessions ran
        rule2, notes2 = rule_e.decide(part, None, development=True)
        self.assertEqual(rule2["default"]["epoll"], "replay")
        self.assertIn("epoll.detect", notes2)
        with self.assertRaises(runlib.InputRefused):
            rule_e.decide(part, {"IOCP": {"detect": {"choice": "replay"}}}, development=False)

    def test_m2_rate_and_section_10_rates(self):
        cells = m_run.m_cells(6, RULE_E, None, part="m2-rate")
        rows = rule_rows("M2.L.epoll.http1", [(1000.0, 800.0), (1100.0, 900.0), (900.0, 700.0)], (1, 1))
        got = m_run.m2_rates_from(rows, cells)["M2.L.epoll.http1"]
        self.assertEqual(got["median_conn_per_s"], {"A": 1000.0, "B": 800.0})
        self.assertAlmostEqual(got["rate"], 400.0)
        s = s_run.slower_median_rate(rows, "M2.L.epoll.http1")
        self.assertAlmostEqual(s["rate"], 400.0)

    def test_pilot_lambda_is_pilot_py_rates(self):
        cells = [c for c in pilot_run.pilot_cells(3) if c.id in ("C1.L.epoll.http1",)]
        with tempfile.TemporaryDirectory() as d:
            e = engine("pilot_run", cells, Path(d))
            e.run()
            rows = e.rows()
        rates = pilot_run.c3_rates(rows)
        self.assertAlmostEqual(rates["C3.L.epoll.http1"], 500.0)  # RATE_FRAC x the median of 1,000
        self.assertIsNone(rates["C3.L.io_uring.http1"])

    def test_haproxy_splice_auto(self):
        plain = comp.render("haproxy", "m3", 22000, 22010, 14, Path("."))
        spl = comp.render("haproxy", "m3", 22000, 22010, 14, Path("."), splice=True)
        b3s = comp.render("haproxy", "b3", 22000, 22010, 14, Path("."), splice=True)
        strip = lambda t: "\n".join(ln.split("#", 1)[0] for ln in t.splitlines())  # noqa: E731
        self.assertNotIn("splice", strip(plain))
        for t in (spl, b3s):
            body = strip(t)
            self.assertIn("option splice-auto", body)
            self.assertLess(body.index("defaults"), body.index("option splice-auto"))  # a proxy option, in defaults
        self.assertNotIn("SPLICE", comp.render("nginx", "m3", 22000, 22010, 14, Path("."), splice=True))


# ---------------------------------------------------------------- the hard cases' judge


K = {"response200_hex": b"HTTP/1.1 200 OK\r\n\r\nHello".hex(), "response400_hex": b"HTTP/1.1 400\r\n\r\n".hex(), "ssh_banner_hex": b"SSH-2.0-x\r\n".hex(),
     "smtp_greeting_hex": b"220 x\r\n".hex(), "smtp_unknown_hex": b"500 x\r\n".hex(), "recv_buf": 4096, "b_ch": 16384}


def variant(**kw) -> dict:
    v = {"id": "HC01.HTTP", "hc": 1, "setup": "plain", "needs_proxy": False, "expect": "classified", "proto": "HTTP/1.1", "when": "at_once",
         "reply": "http200", "dedicated": "HTTP/1.1", "dedicated_http_reply": None, "at": 4, "header_write": None, "source": None,
         "proxy_reason": None, "coverage": "full"}
    v.update(kw)
    return v


def transcript(**kw) -> dict:
    t = {"local_port": 40000, "before_connect_ns": 1_000, "after_connect_ns": 2_000, "write_ns": [3_000], "received_hex": K["response200_hex"],
         "eof": True, "reset": False, "first_byte_ns": 5_000, "end_ns": 6_000, "tls": None}
    t.update(kw)
    return t


def report(**kw) -> dict:
    r = {"event": "detection", "peer_port": 40000, "outcome": "classified", "proto": "HTTP/1.1", "at": 4, "end_pass": 3, "last_read_pass": 3,
         "observe_pass": 0, "max_user_bytes": 40, "buffer_while_silent": False, "has_proxy": False, "proxy": None, "proxy_reason": 0,
         "timed": None, "accept_ns": 1_500, "timers_start_ns": 1_500, "end_ns": 4_000, "wakeups": 1}
    r.update(kw)
    return r


class Judge(unittest.TestCase):
    def test_pass_and_b1(self):
        res = HR.judge(variant(), transcript(), [report()], [], None, "replay", False, {}, K)
        self.assertEqual((res["b1"], [k for k, v in res["b2"].items() if v]), ([], []))
        res = HR.judge(variant(), transcript(), [report(outcome="rejected")], [], None, "replay", False, {}, K)
        self.assertTrue(res["b1"])
        res = HR.judge(variant(), transcript(received_hex=""), [report()], [], None, "replay", False, {}, K)
        self.assertTrue(res["b1"])

    def test_b2(self):
        res = HR.judge(variant(), transcript(), [report(end_pass=4)], [], None, "replay", False, {}, K)
        self.assertTrue(res["b2"]["c"])
        res = HR.judge(variant(), transcript(), [report(max_user_bytes=40)], [], None, "peek", False, {}, K)
        self.assertTrue(res["b2"]["d"])
        v = variant(id="HC21.none", expect="silent", reply="closed", at=None)
        res = HR.judge(v, transcript(received_hex=""), [report(outcome="silent", observe_pass=5, end_pass=6)], [], None, "replay", False, {}, K)
        self.assertTrue(res["b2"]["e"])
        t3 = 3_000_000_000
        ev = {"kind": "T_dec", "result": "closed", "start_ns": 1_000, "deadline_ns": 1_000 + t3, "wait_return_ns": 1_000 + t3 + 500,
              "prev_wait_return_ns": 1_000 + t3 - 10, "handled_at_ns": 1_000 + t3 + 600, "pass": 9}
        v = variant(id="HC06", expect="silent", reply="closed", when="t_dec", at=None)
        ok = HR.judge(v, transcript(received_hex="", end_ns=1_000 + t3 + 900), [report(outcome="silent", timed=ev)], [], None, "replay", False, {}, K)
        self.assertEqual((ok["b1"], [k for k, x in ok["b2"].items() if x], ok["lateness_ns"]), ([], [], 500))
        early = dict(ev, wait_return_ns=1_000 + t3 - 5, handled_at_ns=1_000 + t3)
        bad = HR.judge(v, transcript(received_hex="", end_ns=1_000 + t3 + 900), [report(outcome="silent", timed=early)], [], None, "replay", False, {}, K)
        self.assertTrue(bad["b2"]["a"])
        late = dict(ev, prev_wait_return_ns=1_000 + t3 + 1)
        bad = HR.judge(v, transcript(received_hex="", end_ns=1_000 + t3 + 900), [report(outcome="silent", timed=late)], [], None, "replay", False, {}, K)
        self.assertTrue(bad["b2"]["b"])

    def test_route_and_tls(self):
        tls = {"handshake": True, "version": "TLSv1.3", "cipher": "TLS_AES_128_GCM_SHA256", "group": "x25519", "sigalg": "ecdsa_secp256r1_sha256",
               "verified": True, "resumable": False, "alpn": "http/1.1", "plain_hex": K["response200_hex"], "close_notify": False}
        v = variant(id="HC01.TLS", proto="TLS", reply="dedicated", dedicated="TLS", at=6)
        t = transcript(received_hex="1603", tls=tls)
        relay = [{"event": "relayed", "route": "by_sni", "backend_port": 26202, "hello_len": 512, "hello_records": 1, "held_max": 517}]
        res = HR.judge(v, t, [report(proto="TLS", at=6)], relay, dict(t), "replay", True, {"TLS": 26202}, K)
        self.assertEqual((res["b1"], [k for k, x in res["b2"].items() if x]), ([], []))
        res = HR.judge(v, t, [report(proto="TLS", at=6)], [dict(relay[0], held_max=600)], dict(t), "replay", True, {"TLS": 26202}, K)
        self.assertTrue(res["b2"]["d"])
        res = HR.judge(v, t, [report(proto="TLS", at=6)], [dict(relay[0], route="by_class")], dict(t), "replay", True, {"TLS": 26202}, K)
        self.assertTrue(res["b1"])
        resumed = dict(t, tls=dict(tls, resumable=True))
        res = HR.judge(v, resumed, [report(proto="TLS", at=6)], relay, dict(t), "replay", True, {"TLS": 26202}, K)
        self.assertTrue(res["b1"])

    def test_printable_first_line(self):
        self.assertEqual(HR.printable(b"HTTP/1.1 200 OK\r\nx"), "HTTP/1.1 200 OK")
        self.assertEqual(HR.printable(bytes([0x16, 0x03, 0x03, 0x41])), "...A")

    def test_competitor_coverage(self):
        self.assertEqual(HR.covered("nginx", "plain"), "cases")
        self.assertIsNone(HR.covered("nginx", "SMTP fallback"))
        self.assertEqual(HR.covered("haproxy", "PROXY, SMTP fallback"), "cases-fallback")
        self.assertIsNone(HR.covered("sslh-ev", "PROXY"))


@unittest.skipUnless(sys.platform.startswith("linux"), "the lab job wrapper and /proc are L's")
class Priority(unittest.TestCase):
    """M7c: a lab job runs at nice 0 (zsh's BG_NICE gives a background job nice 5)."""

    def test_lab_job_refuses_a_niced_job(self):
        script = HERE / "lab_job.sh"
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, ONEPORT_LABLOCK="/bin/true", ONEPORT_NOTRACK="off")
            env.pop("ONEPORT_ALLOW_NICE", None)
            p = subprocess.run(["nice", "-n", "5", "bash", str(script), d, "j1", "true"], env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 92)
            done = json.loads((Path(d) / "j1.done").read_text())
            self.assertEqual(done["exit"], 92)
            self.assertGreater(done["nice"], 0)
            self.assertIn("nice 0", (Path(d) / "j1.log").read_text())
            env["ONEPORT_ALLOW_NICE"] = "1"  # past the guard, to the lock (here /bin/true, which runs nothing)
            p = subprocess.run(["nice", "-n", "5", "bash", str(script), d, "j2", "true"], env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0)

    def test_priority_state(self):
        st = cellwin.window.priority_state()
        self.assertEqual(st["nice"], os.nice(0))
        self.assertIsInstance(st["timerslack_ns"], int)


def main() -> int:
    res = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=1).result
    print(f"{res.testsRun} checks, {len(res.failures)} failures, {len(res.errors)} errors, {len(res.skipped)} skipped")
    return 0 if res.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
