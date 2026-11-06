#!/usr/bin/env python3
"""Tests of P3's quick benchmarks (quick-plan.md; decisions d006 and d007): the plans and their sizing, the plan-hash gate, the
refusals of the frozen runners that must stand, and the quick runner's rows. Pure: no window starts, no process, no timed run.

    python3 bench/run/test_quick.py          (exit 0 when every check passes)

Needs the analysis's numpy only where the frozen runners import it (test_frozen.py's rule). The cases that start nothing run on
Windows and on Linux alike.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "analysis"))

import cellwin  # noqa: E402
import cost_run  # noqa: E402
import freeze_guard  # noqa: E402
import hardcase_run  # noqa: E402
import m_run  # noqa: E402
import quick_guard  # noqa: E402
import quick_plans as QP  # noqa: E402
import quick_run  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402

LIMIT = 600.0
PLAN_DIR = HERE / "plans" / "quick"
# Independent of quick_plans.py: the window figures the brief and design/status.md give, and the constants of the engine.
WINDOW = {"L": 6.3, "W": 6.123}


def plan_files() -> dict[str, Path]:
    return {p.stem: p for p in sorted(PLAN_DIR.glob("*.json"))}


def load(stem: str) -> dict:
    return json.loads((PLAN_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def warmup(host: str) -> float:
    return SS.JOB_WARMUP_S + WINDOW[host]


def worst(host: str, cells: int, r: int) -> float:
    return warmup(host) + cells * (r + math.ceil(r / 4)) * 4 * WINDOW[host]


def nominal(host: str, cells: int, r: int) -> float:
    return warmup(host) + cells * r * 4 * WINDOW[host]


class TestPlans(unittest.TestCase):
    def test_22_plans_and_names(self):
        files = plan_files()
        self.assertEqual(len(files), 22)
        want = ({f"quick-L-epoll-c2-{p}" for p in QP.PROTOS} | {f"quick-L-epoll-c1-{p}" for p in QP.PROTOS}
                | {f"quick-L-uring-c2-{p}" for p in QP.PROTOS} | {f"quick-W-iocp-c2-{p}" for p in QP.PROTOS}
                | {"quick-L-epoll-m1-http1", "quick-L-epoll-m1-h2c", "quick-L-aa", "quick-W-aa", "quick-L-hard", "quick-W-hard"})
        self.assertEqual(set(files), want)

    def test_files_are_what_the_generator_makes(self):
        made = QP.build_all()
        self.assertEqual(set(made), set(plan_files()))
        for stem, p in plan_files().items():
            self.assertEqual(p.read_bytes(), QP.render(made[stem]).encode("utf-8"), stem)

    def test_window_constants(self):
        self.assertEqual((QP.WARMUP_MS, QP.DURATION_MS), (window.WARMUP_MS, window.DURATION_MS))
        self.assertEqual(QP.JOB_WARMUP_S, SS.JOB_WARMUP_S)
        self.assertEqual(QP.WINDOW_S, WINDOW)
        for host in ("L", "W"):
            self.assertGreater(WINDOW[host], (window.WARMUP_MS + window.DURATION_MS) / 1000)

    def test_session_plans_fit_and_r_is_largest(self):
        for stem, plan in ((s, load(s)) for s in plan_files()):
            if plan["kind"] == "hard":
                continue
            host, cells = plan["host"], len(plan["cells"])
            r = plan["cells"][0]["r"]
            self.assertEqual(plan["r"], r, stem)
            self.assertLessEqual(nominal(host, cells, r), LIMIT, stem)
            self.assertLessEqual(worst(host, cells, r), LIMIT, stem)
            self.assertGreater(worst(host, cells, r + 1), LIMIT, f"{stem}: R {r} is not the largest that fits")
            self.assertEqual(plan["expected_worst_case_s"], round(worst(host, cells, r), 3), stem)
            self.assertEqual(plan["expected_no_rerun_s"], round(nominal(host, cells, r), 3), stem)
            self.assertEqual(plan["rerun_cap"], math.ceil(r / 4), stem)
            self.assertEqual(plan["job_warmup_s"], SS.JOB_WARMUP_S, stem)
            self.assertEqual(plan["sessions_worst_case"], cells * (r + math.ceil(r / 4)), stem)

    def test_r_16_everywhere_a_session_plan_has_one_cell(self):
        for stem, plan in ((s, load(s)) for s in plan_files()):
            if plan["kind"] != "hard":
                self.assertEqual((len(plan["cells"]), plan["cells"][0]["r"]), (1, 16), stem)

    def test_hard_case_plans_fit_and_r_is_largest(self):
        for stem, host, entries, r in (("quick-L-hard", "L", 4, 2), ("quick-W-hard", "W", 2, 5)):
            plan = load(stem)
            per_entry = plan["long_s_per_entry"]
            self.assertEqual(len(plan["entries"]), entries)
            self.assertEqual((plan["r"], plan["replicates"]), (r, r))

            def t(rr, per=per_entry, n=entries, f=plan["fixed_runs"]):
                return n * per * (rr + f) / (16 + f)
            self.assertLessEqual(t(r), LIMIT, stem)
            self.assertGreater(t(r + 1), LIMIT, f"{stem}: R {r} is not the largest that fits")
            self.assertEqual(plan["expected_worst_case_s"], round(t(r), 3))
            self.assertLessEqual(plan["expected_worst_case_s"], LIMIT)
        # the per-entry figures are the larger of the measured and the queued ones
        self.assertEqual(load("quick-L-hard")["long_s_per_entry"], 625.0)
        self.assertEqual(load("quick-W-hard")["long_s_per_entry"], 737.5)

    def test_hard_case_plans_keep_all_25_cases_and_both_detection_modes(self):
        for stem in ("quick-L-hard", "quick-W-hard"):
            plan = load(stem)
            self.assertEqual(plan["cases"], list(range(1, 26)))
            self.assertEqual({e.split(".")[1] for e in plan["entries"]}, {"replay", "peek"})
            self.assertEqual({e.split(".")[2] for e in plan["entries"]}, {"inproc"})
        self.assertEqual({e.split(".")[0] for e in load("quick-L-hard")["entries"]}, {"epoll", "io_uring"})
        self.assertEqual([e for e in load("quick-L-hard")["entries"] if e not in hardcase_run.ENTRIES], [])

    def test_hard_case_pilot_values_equal_the_committed_pilot_entry(self):
        for stem, host in (("quick-L-hard", "L"), ("quick-W-hard", "W")):
            plan = load(stem)
            pil = json.loads((REPO / plan["pilot"]["source"]).read_text(encoding="utf-8-sig"))
            self.assertEqual(plan["pilot"]["G_ms"], pil["G"][host]["G_ms"])
            self.assertEqual(plan["pilot"]["hc7_runs"], pil["G"][host]["hc7_runs"])
            self.assertEqual(plan["pilot"]["gap_split_ms"], pil["gap_split"]["GAP_SPLIT_ms"])

    def test_cells_exist_in_the_frozen_runners_and_arms_are_right(self):
        rule_e = runlib.load_rule_e(None, True)
        for stem, plan in ((s, load(s)) for s in plan_files()):
            if plan["kind"] not in ("cost", "m1"):
                continue
            host = plan["host"]
            cell = quick_run.session_cell(plan, rule_e, host, cost_run, m_run)
            self.assertEqual(cell.id, plan["cells"][0]["id"])
            self.assertEqual(cell.r, 16)
            self.assertEqual(plan["detect"], rule_e["default"][plan["backend"]])
            a, b = cell.arms["A"], cell.arms["B"]
            if plan["kind"] == "cost":
                self.assertEqual((a["mode"], b["mode"]), ("one-port", "dedicated"), stem)
                self.assertTrue(cell.pairs_one_port_with_dedicated)
                self.assertEqual({a["dispatch"], b["dispatch"]}, {"inproc"})
            else:
                self.assertEqual((a["mode"], b["mode"]), ("one-port", "one-port"), stem)
                self.assertEqual((a["detect"], b["detect"]), ("replay", "peek"))
                self.assertFalse(cell.pairs_one_port_with_dedicated)
            self.assertEqual(cell.arms["A"]["proto"], plan["proto"])
            self.assertEqual(cell.arms["A"]["workload"], plan["workload"])

    def test_no_windows_churn_and_no_dropped_cell(self):
        for stem in plan_files():
            self.assertNotIn("quick-W-iocp-c1", stem)
            self.assertNotIn("uring-c1", stem)
            self.assertNotIn("-c3-", stem)
        self.assertNotIn("quick-L-uring-m1-http1", plan_files())

    def test_aa_cells_are_dedicated_against_dedicated_on_aa_ports(self):
        for stem in ("quick-L-aa", "quick-W-aa"):
            plan = load(stem)
            cell = quick_run.aa_cell(plan, cost_run.PORTS)
            self.assertEqual({a["mode"] for a in cell.arms.values()}, {"dedicated"})
            self.assertEqual((cell.arms["A"]["run"]["port"], cell.arms["B"]["run"]["port"]), (20000, 20100))
            self.assertEqual((plan["proto"], plan["workload"]), ("http1", "keepalive"))
            self.assertFalse(cell.pairs_one_port_with_dedicated)


def fake_build(tmp: Path, build_type="Release", sanitizer="") -> Path:
    b = tmp / "build"
    b.mkdir(exist_ok=True)
    (b / "CMakeCache.txt").write_text(f"CMAKE_BUILD_TYPE:STRING={build_type}\nONEPORT_SANITIZER:STRING={sanitizer}\n")
    return b


class TestGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p3q-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stem = "quick-L-epoll-c2-http1"
        self.path = PLAN_DIR / f"{self.stem}.json"
        self.sha = quick_guard.sha256_file(self.path)
        self.build = fake_build(self.tmp)

    def check(self, **kw):
        a = dict(plan_path=self.path, sha=self.sha, build=self.build, host="L")
        a.update(kw)
        return quick_guard.check_plan(**a)

    def test_the_right_plan_and_hash_pass(self):
        plan, stem, clr = self.check()
        self.assertEqual(stem, self.stem)
        self.assertIsInstance(clr, quick_guard.QuickClearance)
        self.assertEqual(clr.quick_plan_sha256, self.sha)
        self.assertTrue(clr.record["quick"])
        self.assertIsNone(clr.record["pilot"])

    def test_a_wrong_hash_is_refused(self):
        for bad in ("0" * 64, self.sha[:-1] + ("0" if self.sha[-1] != "0" else "1"), self.sha.upper(), "", "xyz"):
            with self.assertRaises(quick_guard.QuickRefused, msg=bad):
                self.check(sha=bad)

    def test_a_plan_outside_the_quick_folder_is_refused(self):
        copy = self.tmp / f"{self.stem}.json"
        shutil.copy(self.path, copy)
        with self.assertRaises(quick_guard.QuickRefused):
            self.check(plan_path=copy, sha=quick_guard.sha256_file(copy))
        dev = HERE / "plans"
        other = sorted(dev.glob("*.json"))
        if other:
            with self.assertRaises(quick_guard.QuickRefused):
                self.check(plan_path=other[0], sha=quick_guard.sha256_file(other[0]))

    def test_an_edited_plan_with_a_fresh_hash_is_refused(self):
        with tempfile.TemporaryDirectory(dir=PLAN_DIR) as _:
            pass
        edited = PLAN_DIR / "quick-zz-edited.json"
        plan = load(self.stem)
        plan["cells"][0]["r"] = 17
        edited.write_text(json.dumps(plan, indent=1) + "\n")
        self.addCleanup(edited.unlink)
        with self.assertRaises(quick_guard.QuickRefused):
            self.check(plan_path=edited, sha=quick_guard.sha256_file(edited))

    def test_a_plan_for_the_other_host_is_refused(self):
        with self.assertRaises(quick_guard.QuickRefused):
            self.check(host="W")

    def test_only_a_release_build_without_a_sanitizer_passes(self):
        for kind, san in (("Debug", ""), ("RelWithDebInfo", ""), ("", ""), ("Release", "address"), ("Release", "address+undefined")):
            with self.assertRaises(quick_guard.QuickRefused, msg=f"{kind} {san}"):
                self.check(build=fake_build(self.tmp, kind, san))
        with self.assertRaises(quick_guard.QuickRefused):
            self.check(build=self.tmp / "nowhere")

    def test_a_missing_plan_is_refused(self):
        with self.assertRaises(quick_guard.QuickRefused):
            self.check(plan_path=PLAN_DIR / "quick-L-nothing.json")

    def test_quick_run_main_refuses_before_any_work(self):
        out = self.tmp / "out"
        argv = ["--plan", str(self.path), "--build", str(self.build), "--out", str(out), "--seed", "1"]
        with self.assertRaises(quick_guard.QuickRefused):
            quick_run.main(argv + ["--quick", "0" * 64])
        with self.assertRaises(SystemExit):   # --quick is required
            quick_run.main(argv)
        self.assertFalse(out.exists())

    def test_main_flow_writes_the_run_record_and_passes_the_seed(self):
        out = self.tmp / "out"
        argv = ["--plan", str(self.path), "--build", str(self.build), "--out", str(out), "--seed", "99", "--quick", self.sha]
        prov = {"commit": "c" * 40, "runner_commit": "d" * 40, "runner_dirty": False}
        got = {}

        def fake_sessions(plan, stem, sha, a, host, clr, wr, seed, p, rule_e):
            got.update(stem=stem, sha=sha, host=host, seed=seed, job=a.job, clr=clr)
            return 0
        with mock.patch.object(quick_guard, "this_host", lambda: "L"), mock.patch("window.stop_on_signals"),                 mock.patch.object(runlib, "job_provenance", lambda *a: prov), mock.patch.object(quick_run, "run_sessions", fake_sessions):
            self.assertEqual(quick_run.main(argv), 0)
        self.assertEqual((got["stem"], got["sha"], got["host"], got["seed"], got["job"]), (self.stem, self.sha, "L", 99, self.stem))
        rec = json.loads((out / "quick.json").read_text())
        self.assertEqual((rec["plan"], rec["plan_sha256"], rec["seed"], rec["exit"]), (self.stem, self.sha, 99, 0))
        self.assertIn("ended", rec)
        self.assertTrue(rec["clearance"]["quick"])
        # the folder is now this plan's: another plan is refused there, this plan resumes
        with mock.patch.object(quick_guard, "this_host", lambda: "L"), mock.patch("window.stop_on_signals"),                 mock.patch.object(runlib, "job_provenance", lambda *a: prov), mock.patch.object(quick_run, "run_sessions", fake_sessions):
            self.assertEqual(quick_run.main(argv), 0)
            other = PLAN_DIR / "quick-L-aa.json"
            with self.assertRaises(runlib.InputRefused):
                quick_run.main(["--plan", str(other), "--build", str(self.build), "--out", str(out), "--seed", "1",
                                "--quick", quick_guard.sha256_file(other)])

    def test_main_flow_for_a_hard_plan_needs_no_seed(self):
        out = self.tmp / "outh"
        path = PLAN_DIR / "quick-L-hard.json"
        argv = ["--plan", str(path), "--build", str(self.build), "--out", str(out), "--quick", quick_guard.sha256_file(path)]
        calls = []
        with mock.patch.object(quick_guard, "this_host", lambda: "L"), mock.patch("window.stop_on_signals"),                 mock.patch.object(runlib, "job_provenance", lambda *a: {"commit": "c"}),                 mock.patch.object(quick_run, "run_hard", lambda *a: calls.append(a) or 0):
            self.assertEqual(quick_run.main(argv), 0)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(json.loads((out / "quick.json").read_text())["seed"])


class Pair:
    """A lookalike of a clearance: not a QuickClearance, with every attribute a clearance has."""
    record = {"quick": True}
    pilot_entry = False
    quick_plan_sha256 = "x" * 64


class TestFrozenRefusalsStand(unittest.TestCase):
    P = {"mode": "one-port", "pairs_dedicated": True}

    def test_the_guard_refuses_a_one_port_window_without_a_clearance(self):
        for clr in (None, freeze_guard.Clearance({}), freeze_guard.Clearance({"pilot": None}), Pair()):
            with self.assertRaises(window.WindowError):
                cellwin.guard(dict(self.P), clr)

    def test_the_guard_passes_the_pilot_entry_and_the_quick_clearance_only(self):
        cellwin.guard(dict(self.P), freeze_guard.Clearance({"pilot": {"logged_in": "x"}}))
        cellwin.guard(dict(self.P), quick_guard.QuickClearance({"quick": True}, "x" * 64))
        cellwin.guard({"mode": "dedicated", "pairs_dedicated": True}, None)
        with self.assertRaises(window.WindowError):
            cellwin.guard({"mode": "weird"}, None)

    def test_a_frozen_engine_without_a_clearance_does_not_start_a_one_port_arm(self):
        cell = SS.Cell("C2.L.epoll.http1", 1, {"A": {"mode": "one-port"}, "B": {"mode": "dedicated"}}, pairs_one_port_with_dedicated=True)
        with tempfile.TemporaryDirectory() as d:
            eng = SS.Engine("t", "j", Path(d), [cell], SS.make_plan([cell], 1), lambda *a: self.fail("a window ran"), lambda c, a: {},
                            False, None, warmup_s=0)
            with self.assertRaises(RuntimeError):
                eng.one_window(cell, {"job": "j", "id": "s", "order_index": 0}, "A", 0)

    def test_a_development_engine_stubs_the_one_port_arm(self):
        cell = SS.Cell("C2.L.epoll.http1", 1, {"A": {"mode": "one-port"}, "B": {"mode": "dedicated"}}, pairs_one_port_with_dedicated=True)
        with tempfile.TemporaryDirectory() as d:
            eng = SS.Engine("t", "j", Path(d), [cell], SS.make_plan([cell], 1), lambda *a: self.fail("a window ran"), lambda c, a: {},
                            True, None, warmup_s=0)
            row = eng.one_window(cell, {"job": "j", "id": "s", "order_index": 0}, "A", 0)
            self.assertTrue(row["stub"])

    def test_the_frozen_mains_know_no_quick_option_and_refuse_without_the_freeze_inputs(self):
        with mock.patch("window.stop_on_signals"):
            for mod in (cost_run, m_run, hardcase_run):
                with self.assertRaises(SystemExit):
                    mod.main(["--build", "b", "--out", "o", "--job", "j", "--quick", "0" * 64])
                with self.assertRaises(runlib.InputRefused):   # no --development, no --seeds, no --code-freeze, no --gate
                    mod.main(["--build", "b", "--out", "o", "--job", "j"])

    def test_the_frozen_hard_case_main_refuses_a_narrowed_run(self):
        with tempfile.TemporaryDirectory() as d:
            argv = ["--build", d, "--out", d, "--job", "j", "--seeds", "s", "--code-freeze", "0" * 40, "--gate", "g", "--replicates", "2"]
            with mock.patch("window.stop_on_signals"), self.assertRaises(runlib.InputRefused):
                hardcase_run.main(argv)

    def test_the_freeze_guard_is_unchanged_by_a_quick_plan(self):
        import inspect
        self.assertNotIn("quick", inspect.getsource(freeze_guard).lower())
        self.assertFalse(hasattr(freeze_guard.Clearance({}), "quick_plan_sha256"))
        self.assertFalse(freeze_guard.Clearance({"quick": True}).pilot_entry)


def fake_cellwin_run(p, session, arm, position, blocks, raw, clearance=None):
    """Stands for cellwin.run and wcellwin.run: the guard first, as they do, then a valid row."""
    cellwin.guard(p, clearance)
    v = 100.0 if p["mode"] == "one-port" else 101.0
    return {"valid": True, "metric": {"name": "x", "value": v}, "mode": p["mode"], "port": p["port"]}


class TestQuickRows(unittest.TestCase):
    def run_plan(self, stem: str, host: str, warm: float = 0.0, seed: int = 4242):
        tmp = Path(tempfile.mkdtemp(prefix="p3q-run-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        plan = dict(load(stem), job_warmup_s=warm)
        sha = "a" * 64
        out = tmp / "out"
        a = mock.Mock(build=tmp / "build", out=out, job="jq", k_src=16, blocks=tmp / "blocks.json", tools=None)
        prov = {"binaries_all": {"oneport": "o" * 8, "opgen": "g" * 8}, "commit": "c" * 40}
        clr = quick_guard.QuickClearance({"quick": True, "plan": stem, "plan_sha256": sha, "pilot": None}, sha)
        mod = "cellwin" if host == "L" else "wcellwin"
        fp = "pin_fingerprint" if host == "L" else None
        patches = [mock.patch(f"{mod}.run", fake_cellwin_run)]
        if host == "L":
            patches.append(mock.patch("window.pin_fingerprint", lambda: {"mean_mhz": 3000.0}))
            wr = None
        else:
            import wrunlib
            patches.append(mock.patch("wrunlib.fingerprint", lambda: {"mean_mhz": 3000.0}))
            wr = wrunlib
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        rule_e = runlib.load_rule_e(None, True)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = quick_run.run_sessions(plan, stem, sha, a, host, clr, wr, seed, prov, rule_e)
        self.assertEqual(rc, 0)
        return [json.loads(ln) for ln in (out / "windows.jsonl").read_text().splitlines()], plan

    def check_rows(self, rows, plan, seed, arms):
        self.assertEqual(len(rows), 4 * 16)
        for r in rows:
            self.assertIs(r["development"], False)
            self.assertIs(r["quick"], True)
            self.assertEqual((r["campaign"], r["quick_plan"]), ("quick", plan["name"]))
            self.assertEqual(r["seed"], seed)
            self.assertEqual(r["cell"], plan["cells"][0]["id"])
            self.assertIs(r["provenance"]["freeze"]["quick"], True)
            self.assertIsNone(r["provenance"]["freeze"]["pilot"])
            self.assertEqual(r["mode"], arms[r["arm"]])
            self.assertNotIn("stub", r)
        sess = {}
        for r in rows:
            sess.setdefault(r["session"], {})[r["position"]] = r["arm"]
        self.assertEqual(len(sess), 16)
        for s in sess.values():   # X Y Y X
            self.assertEqual(s[1], s[2])
            self.assertEqual(s[0], s[3])
            self.assertNotEqual(s[0], s[1])

    def test_l_cost_rows_are_labelled_and_one_port_ran_under_the_gate(self):
        rows, plan = self.run_plan("quick-L-epoll-c2-http1", "L")
        self.check_rows(rows, plan, 4242, {"A": "one-port", "B": "dedicated"})

    def test_w_cost_rows(self):
        rows, plan = self.run_plan("quick-W-iocp-c2-tls", "W")
        self.check_rows(rows, plan, 4242, {"A": "one-port", "B": "dedicated"})

    def test_m1_rows(self):
        rows, plan = self.run_plan("quick-L-epoll-m1-h2c", "L")
        self.check_rows(rows, plan, 4242, {"A": "one-port", "B": "one-port"})
        self.assertEqual({r["arm"]: r["detect"] for r in rows}, {"A": "replay", "B": "peek"})
        self.assertEqual({r["arm"]: r["port"] for r in rows}, {"A": 20000, "B": 20100})

    def test_aa_rows(self):
        rows, plan = self.run_plan("quick-W-aa", "W")
        self.check_rows(rows, plan, 4242, {"A": "dedicated", "B": "dedicated"})

    def test_same_seed_same_order_and_other_seed_other_order(self):
        a, _ = self.run_plan("quick-L-aa", "L", seed=7)
        b, _ = self.run_plan("quick-L-aa", "L", seed=7)
        c, _ = self.run_plan("quick-L-aa", "L", seed=8)
        key = lambda rows: [(r["session"], r["arm"]) for r in rows]  # noqa: E731
        self.assertEqual(key(a), key(b))
        self.assertNotEqual(key(a), key(c))

    def test_a_row_without_the_quick_clearance_would_not_have_run(self):
        # the same engine and window function with no clearance: the one-port arm is not started
        cell = quick_run.session_cell(load("quick-L-epoll-c2-http1"), runlib.load_rule_e(None, True), "L", cost_run, m_run)
        with tempfile.TemporaryDirectory() as d:
            eng = quick_run.QuickEngine("t", "j", Path(d), [cell], SS.make_plan([cell], 1), fake_cellwin_run, lambda c, a: {}, False, None,
                                        warmup_s=0)
            with self.assertRaises(RuntimeError):
                eng.one_window(cell, {"job": "j", "id": "s", "order_index": 0}, "A", 0)

    def test_fault_rows_are_labelled_too(self):
        cell = quick_run.session_cell(load("quick-L-epoll-c2-http1"), runlib.load_rule_e(None, True), "L", cost_run, m_run)
        clr = quick_guard.QuickClearance({"quick": True, "pilot": None}, "b" * 64)

        def boom(*a, **k):
            raise ValueError("driver")
        with tempfile.TemporaryDirectory() as d:
            eng = quick_run.QuickEngine("t", "j", Path(d), [cell], SS.make_plan([cell], 1), boom, lambda c, a: {"binaries": {}}, False, clr,
                                        warmup_s=0)
            eng.labels = quick_run.labels_of("s", "b" * 64)
            sess = {"job": "j", "id": "s", "order_index": 0, "fingerprint": {}}
            row = eng.finalize(eng.one_window(cell, sess, "A", 0), cell, sess, "A", 0, 0)
            self.assertTrue(row["driver_fault"])
            self.assertIs(row["quick"], True)

    def test_hard_rows_are_labelled_and_get_the_plans_values(self):
        seen = {}

        def fake_part_server(ns, pilot, rule_e, prov, clearance, emit, procs=None, host="L"):
            seen.update(ns=ns, pilot=pilot, host=host, procs=procs)
            emit({"kind": "hardcase", "entry": ns.entries[0], "id": "x", "replicate": 1, "passed": True})
            return {"k": {"runs": 1, "passed": 1}}

        for stem, host in (("quick-L-hard", "L"), ("quick-W-hard", "W")):
            tmp = Path(tempfile.mkdtemp(prefix="p3q-hard-"))
            self.addCleanup(shutil.rmtree, tmp, True)
            plan = load(stem)
            a = mock.Mock(build=tmp / "b", out=tmp / "out", job="jh")
            a.out.mkdir()
            prov = {"binaries_all": {"oneport": "o", "opcase": "c"}}
            clr = quick_guard.QuickClearance({"quick": True, "pilot": None}, "c" * 64)
            with mock.patch("hardcase_run.part_server", fake_part_server):
                wr = None
                if host == "W":
                    import wrunlib
                    wr = wrunlib
                rc = quick_run.run_hard(plan, stem, "c" * 64, a, host, clr, wr, prov, runlib.load_rule_e(None, True))
            self.assertEqual(rc, 0)
            row = json.loads((a.out / "hardcases.jsonl").read_text().splitlines()[0])
            self.assertIs(row["development"], False)
            self.assertIs(row["quick"], True)
            self.assertEqual(row["quick_plan"], stem)
            self.assertIsNone(row["provenance"]["freeze"]["pilot"])
            ns = seen["ns"]
            self.assertEqual((ns.replicates, ns.entries, ns.cases, ns.development), (plan["replicates"], plan["entries"], plan["cases"], False))
            self.assertEqual(seen["pilot"]["G"][host]["G_ms"], plan["pilot"]["G_ms"])
            self.assertEqual(seen["pilot"]["gap_split"]["GAP_SPLIT_ms"], 5)
            self.assertEqual(seen["host"], host)

    def test_a_folder_of_another_plan_is_not_extended(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "quick.json").write_text(json.dumps({"plan": "quick-L-aa", "plan_sha256": "1" * 64}))
            quick_run.check_resume(out, "quick-L-aa", "1" * 64)
            with self.assertRaises(runlib.InputRefused):
                quick_run.check_resume(out, "quick-L-hard", "2" * 64)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "windows.jsonl").write_text("{}\n")
            with self.assertRaises(runlib.InputRefused):
                quick_run.check_resume(Path(d), "quick-L-aa", "1" * 64)

    def test_seed_from_the_command_line_or_the_seeds_file(self):
        plan = load("quick-L-epoll-c2-http1")
        ns = lambda **k: mock.Mock(**dict(dict(seed=None, seeds=None), **k))  # noqa: E731
        self.assertEqual(quick_run.read_seed(ns(seed=5), plan), 5)
        with self.assertRaises(runlib.InputRefused):
            quick_run.read_seed(ns(), plan)
        seeds = REPO / "design" / "seeds.json"
        self.assertEqual(quick_run.read_seed(ns(seeds=seeds), plan), json.loads(seeds.read_text())["SEED_ORDER_C_L"])


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=1)
    ok = r.result.wasSuccessful()
    print(f"{r.result.testsRun} checks, {len(r.result.failures)} failures, {len(r.result.errors)} errors")
    sys.exit(0 if ok else 1)
