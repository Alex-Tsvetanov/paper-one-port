#!/usr/bin/env python3
"""Tests of W's runners on the laptop's Windows (W since 2026-10-23; hypotheses.md, revision log,
the entry of that date): the power plans (verified inside a lab runner's job, never switched there),
the placement of section 4.1's rule on eight cores, the mixed cell, the job's quiet check inside a
lab runner's job, the gate made on the laptop, the deps wrapper (bench/run/wdeps.py) and the probe
of window times (bench/run/wprobe.py). Also that this branch's frozen paths differ from CODE_FREEZE
in Python files directly under bench/run alone, as a later change under section 8 must.

The powercfg outputs below are built from the format of the desktop's samples (bench/run/samples),
with the laptop's GUIDs; they were not recorded on the laptop. Pure and untimed; nothing here
changes a setting of the host, and no window runs.

    python bench/run/test_wlaptop.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import freeze_guard  # noqa: E402
import gate_lib  # noqa: E402
import wcellwin  # noqa: E402
import wdeps  # noqa: E402
import wjob  # noqa: E402
import wpower  # noqa: E402
import wprobe  # noqa: E402
import wrunlib  # noqa: E402
import wsys  # noqa: E402
import wwindow  # noqa: E402

BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
LAB = "b1bcd431-7706-4898-b26a-caeee179f68e"


def qh_text(boost: int = 0, pmin: int = 100, pmax: int = 100, parking: int = 100) -> str:
    """`powercfg /QH <plan> SUB_PROCESSOR` in the samples' format, with the four settings' AC values."""
    def setting(guid, name, alias, ac):
        return (f"    Power Setting GUID: {guid}  ({name})\n      GUID Alias: {alias}\n"
                f"      Current AC Power Setting Index: 0x{ac:08x}\n      Current DC Power Setting Index: 0x{ac:08x}\n\n")
    return (f"Power Scheme GUID: {LAB}  (lab laptop)\n  Subgroup GUID: {wpower.SUB_PROCESSOR}  (Processor power management)\n"
            + setting(wpower.BOOST_MODE, "Processor performance boost mode", "PERFBOOSTMODE", boost)
            + setting(wpower.PROC_MIN, "Minimum processor state", "PROCTHROTTLEMIN", pmin)
            + setting(wpower.PROC_MAX, "Maximum processor state", "PROCTHROTTLEMAX", pmax)
            + setting(wpower.CP_MIN_CORES, "Processor performance core parking min cores", "CPMINCORES", parking))


class FakePowercfg:
    """powercfg as the laptop would answer, with the active plan as state; records every call."""

    def __init__(self, active: str, qh: str | None = None, lab_exists: bool = True):
        self.active, self.qh, self.lab_exists, self.calls = active, qh or qh_text(), lab_exists, []

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        if args[0] == "/getactivescheme":
            name = {LAB: "lab laptop", BALANCED: "Balanced"}.get(self.active, "other")
            return f"Power Scheme GUID: {self.active}  ({name})\n"
        if args[0] == "/QH":
            if args[1] == LAB and not self.lab_exists:
                raise wpower.PowerError("powercfg /QH exited 1: Invalid Parameters")
            return self.qh
        if args[0] == "/setactive":
            self.active = args[1]
            return ""
        raise AssertionError(f"unexpected powercfg {args}")

    def switched(self) -> list:
        return [c for c in self.calls if c[0] in ("/setactive", "/setacvalueindex", "/duplicatescheme", "/changename")]


class Power(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((wpower.LAB_PLAN, wpower.ALEX_PLAN, wpower.ALEX_PLAN_NAME), (LAB, BALANCED, "Balanced"))
        self.assertEqual(wpower.LAB_VALUES, {wpower.BOOST_MODE: 0, wpower.PROC_MIN: 100, wpower.PROC_MAX: 100, wpower.CP_MIN_CORES: 100})

    def test_lab_plan_found_by_guid(self):
        with mock.patch.object(wpower, "powercfg", FakePowercfg(BALANCED)):
            self.assertEqual(wpower.lab_plan_guid(), LAB)
        with mock.patch.object(wpower, "powercfg", FakePowercfg(BALANCED, lab_exists=False)):
            self.assertIsNone(wpower.lab_plan_guid())

        def denied(*a):
            raise wpower.AdminNeeded("access denied")
        with mock.patch.object(wpower, "powercfg", denied), self.assertRaises(wpower.AdminNeeded):
            wpower.lab_plan_guid()

    def test_under_lab_runner(self):
        self.assertTrue(wpower.under_lab_runner({"LAB_JOB_ID": "a3"}))
        self.assertFalse(wpower.under_lab_runner({}))
        self.assertFalse(wpower.under_lab_runner({"LAB_JOB_ID": ""}))

    def test_verify_inside_lab_runner_changes_nothing(self):
        pc = FakePowercfg(LAB)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(wpower, "powercfg", pc), \
                mock.patch.dict(os.environ, {"LAB_JOB_ID": "a3"}):
            rec = Path(d) / "plan.json"
            lp = wpower.LabPlan(rec)
            self.assertTrue(lp.verify_only)
            with mock.patch.object(wpower.LabPlan, "_start_guard", side_effect=AssertionError("no guard")):
                with lp:
                    self.assertEqual(pc.active, LAB)
            r = json.loads(rec.read_text())
        self.assertEqual(pc.switched(), [])
        self.assertTrue(r["mode"].startswith("verify"))
        self.assertEqual(r["lab_problems"], [])
        self.assertIsNone(r["restored"])
        self.assertEqual(r["after"]["active"]["guid"], LAB)

    def test_verify_refuses_other_plan_or_values(self):
        for active, qh, why in ((BALANCED, qh_text(), "not the lab plan"), (LAB, qh_text(boost=2), "boost")):
            pc = FakePowercfg(active, qh)
            with tempfile.TemporaryDirectory() as d, mock.patch.object(wpower, "powercfg", pc):
                rec = Path(d) / "plan.json"
                with self.assertRaises(wpower.PowerError) as e:
                    with wpower.LabPlan(rec, verify_only=True):
                        pass
                self.assertIn(why, str(e.exception))
                self.assertIn("refused", json.loads(rec.read_text()))
            self.assertEqual(pc.switched(), [], why)

    def test_session_outside_lab_runner_restores_balanced(self):
        pc = FakePowercfg(BALANCED)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(wpower, "powercfg", pc), \
                mock.patch.object(wpower.LabPlan, "_install_handlers", lambda self: None):
            rec = Path(d) / "plan.json"
            with wpower.LabPlan(rec, guard=False, verify_only=False):
                self.assertEqual(pc.active, LAB)
            r = json.loads(rec.read_text())
        self.assertEqual(pc.switched(), [("/setactive", LAB), ("/setactive", BALANCED)])
        self.assertTrue(r["restored"])

    def test_no_plan_is_created(self):
        with self.assertRaises(wpower.PowerError):
            wpower.create()
        with self.assertRaises(wpower.PowerError):
            wpower.create_cap()


class Placement(unittest.TestCase):
    def test_section_4_1_on_eight_cores(self):
        # The server on the first logical CPU of the last physical core, its sibling idle, the
        # generator on the cores between core 0 and the server's (hypotheses.md, section 4.1).
        last = wsys.EXPECTED_CORES[-1]
        self.assertEqual(wsys.N_CORES, 8)
        self.assertEqual(wsys.EXPECTED_CORES, [(2 * k, 2 * k + 1) for k in range(8)])
        self.assertEqual((wsys.SERVER_CPUS, wsys.SERVER_SIBLINGS), ((last[0],), (last[1],)))
        self.assertEqual(wsys.GEN_CPUS, tuple(c for core in wsys.EXPECTED_CORES[1:-1] for c in core))
        self.assertEqual((wsys.SERVER_CPUS, wsys.GEN_CPUS, wsys.HOUSEKEEPING), ((14,), tuple(range(2, 14)), (0, 1)))
        self.assertEqual(wsys.QUIET_CPUS, tuple(range(2, 15)))
        self.assertEqual(wwindow.OPEN_GEN_THREADS, [2, 4, 6, 8, 10, 12])

    def test_mixed_cell_is_l_s(self):
        self.assertEqual(wcellwin.MIXED_GEN_CPUS, tuple(range(2, 10)))
        self.assertEqual(wcellwin.MIXED_BG_CPUS, {"tls": (10, 11), "mqtt": (12, 13), "silent": (12, 13)})


class JobQuietCheck(unittest.TestCase):
    """wjob.preflight inside a lab runner's job: the lab's job-start check, never W's own."""

    def preflight(self, env: dict, allow_noisy: bool = False):
        cores = [{"cpus": [2 * k, 2 * k + 1], "group": 0, "efficiency_class": 0} for k in range(8)]
        with mock.patch.object(wsys, "core_layout", lambda: cores), \
                mock.patch.object(wsys, "defender_and_update", lambda: {}), \
                mock.patch.object(wsys, "timer_resolution", lambda: {}), \
                mock.patch.object(wsys, "quiet_check", side_effect=AssertionError("W's own quiet check ran")), \
                mock.patch.object(wpower, "lab_plan_guid", lambda: LAB), \
                mock.patch.object(wpower, "active", lambda: {"guid": LAB, "name": "lab laptop"}), \
                mock.patch.dict(os.environ, env, clear=False) as e:
            if "LAB_QUIET" not in env:
                e.pop("LAB_QUIET", None)
            return wjob.preflight(allow_noisy)

    def test_lab_quiet_passed(self):
        rec, rc = self.preflight({"LAB_JOB_ID": "f1", "LAB_QUIET": "passed"})
        self.assertEqual(rc, 0)
        self.assertFalse(rec["functional_check"])
        self.assertEqual(rec["quiet"]["LAB_QUIET"], "passed")

    def test_no_lab_quiet_is_a_functional_check(self):
        _rec, rc = self.preflight({"LAB_JOB_ID": "a3"})
        self.assertEqual(rc, wjob.EXIT_NOT_QUIET)
        rec, rc = self.preflight({"LAB_JOB_ID": "a3", "LAB_QUIET": "off"}, allow_noisy=True)
        self.assertEqual(rc, 0)
        self.assertTrue(rec["functional_check"])


class LaptopGate(unittest.TestCase):
    def laptop_gate(self, **kw) -> dict:
        g = {"host": "W", "records_dir": r"C:\lab\jobs\a2\out\laptop-w", "passed": True,
             "oneport": {"compiler": "MSVC 19.51.36248.0", "records": ["oneport-abcdef012-W-asan.json"]}}
        g.update(kw)
        return g

    def test_desktop_gate_refused(self):
        gate = json.loads((REPO / "lab" / "gates" / "gate-W.json").read_text(encoding="utf-8"))
        problems = wrunlib.laptop_gate_problems(gate)
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("records folder" in p for p in problems) and any("compiler" in p for p in problems))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gate-W.json"
            p.write_text(json.dumps(gate))
            with self.assertRaises(wrunlib.InputRefused):
                wrunlib.check_laptop_gates([p])

    def test_laptop_gate_accepted(self):
        self.assertEqual(wrunlib.laptop_gate_problems(self.laptop_gate()), [])
        self.assertTrue(wrunlib.laptop_gate_problems(self.laptop_gate(host="L")))
        self.assertTrue(wrunlib.laptop_gate_problems(self.laptop_gate(records_dir=r"C:\lab\sanitizer-records")))
        self.assertTrue(wrunlib.laptop_gate_problems(self.laptop_gate(oneport={"compiler": "MSVC 19.51.36248.0", "records": []})))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gate-W.json"
            p.write_text(json.dumps(self.laptop_gate()))
            self.assertEqual(wrunlib.check_laptop_gates([p])[0]["compiler"], "MSVC 19.51.36248.0")

    def test_gate_reads_one_folder_alone(self):
        # A record of the desktop and one of the laptop at one commit have one name; the gate's
        # glob reads one folder and not its subfolders, so the laptop's folder holds its own alone.
        name = "oneport-ff2679cc8-W-asan.json"
        with tempfile.TemporaryDirectory() as d:
            top = Path(d)
            (top / "laptop-w").mkdir()
            (top / name).write_text("{}")
            (top / "laptop-w" / name).write_text("{}")
            self.assertEqual(gate_lib.host_records(top, "oneport-*.json", "W"), [top / name])
            self.assertEqual(gate_lib.host_records(top / "laptop-w", "oneport-*.json", "W"), [top / "laptop-w" / name])

    def test_compilers_agree(self):
        self.assertTrue(wrunlib.LAPTOP_COMPILER.startswith(f"MSVC {wdeps.LAPTOP_CL}."))


class LaterChange(unittest.TestCase):
    def test_frozen_paths_differ_in_bench_run_python_alone(self):
        """Section 8's rule as the guard reads it (freeze_guard.change_commit): between CODE_FREEZE
        and this tree only Python files directly under bench/run differ in bench, tests and
        CMakeLists.txt, committed or not."""
        cf = "ff2679cc89d23e08a817308c9aeba7901e056fef"
        out = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", "--no-renames", cf, "--", *freeze_guard.FROZEN_PATHS],
                             capture_output=True, text=True, check=True).stdout.split()
        new = subprocess.run(["git", "-C", str(REPO), "ls-files", "--others", "--exclude-standard", "--", *freeze_guard.FROZEN_PATHS],
                             capture_output=True, text=True, check=True).stdout.split()
        other = [p for p in out + new if not freeze_guard.CHANGE_PATHS.fullmatch(p)]
        self.assertEqual(other, [])
        self.assertIn("bench/run/wprobe.py", out + new)


class Deps(unittest.TestCase):
    def script(self) -> str:
        return (REPO / wdeps.SCRIPT).read_bytes().decode("utf-8").replace("\r\n", "\n")

    def test_patch_one_line(self):
        text = self.script()
        new, ch = wdeps.patch_cl(text, wdeps.LAPTOP_CL)
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(text.split("\n"), new.split("\n"))) if a != b]
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0][1:], ("$wantCl = '19.51.36246'", "$wantCl = '19.51.36248'"))
        self.assertEqual(diff[0][0] + 1, 58)  # build_deps.ps1 line 58 at CODE_FREEZE
        self.assertEqual(ch["lines_changed"], 1)
        same, ch0 = wdeps.patch_cl(text, wdeps.FROZEN_CL)
        self.assertEqual((same, ch0["lines_changed"]), (text, 0))

    def test_patch_refusals(self):
        text = self.script()
        for bad_text, cl in ((text, "19.51"), (text, "19.51.36248; rm"), (text.replace("$wantCl = '19.51.36246'", ""), wdeps.LAPTOP_CL),
                             (text + "\n$wantCl = '19.51.36246'\n", wdeps.LAPTOP_CL),
                             (text.replace("'19.51.36246'", "'19.51.30000'"), wdeps.LAPTOP_CL)):
            with self.assertRaises(wdeps.Refused):
                wdeps.patch_cl(bad_text, cl)

    def test_prepare_copies_the_frozen_files(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "w"
            rec = wdeps.prepare(work, wdeps.LAPTOP_CL)
            copy = work / "third_party" / "build_deps.ps1"
            self.assertTrue((work / "cmake" / "pins.cmake").is_file())
            self.assertEqual(rec["pins_copy"]["sha256"], rec["pins"]["sha256"])
            self.assertNotEqual(rec["copy"]["sha256"], rec["script"]["sha256"])
            a = (REPO / wdeps.SCRIPT).read_bytes().splitlines()
            b = copy.read_bytes().splitlines()
            self.assertEqual([i for i, (x, y) in enumerate(zip(a, b)) if x != y], [57])
            self.assertEqual(len(a), len(b))
            with self.assertRaises(wdeps.Refused):
                wdeps.prepare(work, wdeps.LAPTOP_CL)  # not empty

    def test_blob_check_refuses_a_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            subprocess.run(["git", "clone", "-q", "--no-checkout", str(REPO), str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "checkout", "-q", "HEAD", "--", wdeps.SCRIPT, wdeps.PINS], check=True)
            self.assertEqual(wdeps.frozen_blob_check(wdeps.SCRIPT, repo)["path"], wdeps.SCRIPT)
            with open(repo / wdeps.SCRIPT, "ab") as f:
                f.write(b"\n# changed\n")
            with self.assertRaises(wdeps.Refused):
                wdeps.frozen_blob_check(wdeps.SCRIPT, repo)

    def test_built_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            work, opt = Path(d) / "w", Path(d) / "opt"
            rec = wdeps.prepare(work, wdeps.LAPTOP_CL)
            lib = opt / "nghttp2-1.70.0-release" / "lib"
            lib.mkdir(parents=True)
            (lib / "nghttp2.lib").write_bytes(b"x")
            logs = opt / "build" / "logs"
            logs.mkdir(parents=True)
            (logs / "nghttp2-release.done").write_text("0")
            b = wdeps.built(rec, ["release"], {"ONEPORT_OPT": str(opt), "ONEPORT_LIBS": "nghttp2"})
            item = b["nghttp2-release"]
            self.assertTrue(item["exists"])
            self.assertEqual(list(item["files"]), ["lib/nghttp2.lib"])
            self.assertEqual(item["exit"], "0")


PILOT = REPO / "lab" / "analysis-inputs" / "pilot.json"
# What a window line may hold (the entry of 2026-10-23, item 6).
WINDOW_KEYS = {"kind", "phase", "index", "workload", "proto", "rate_given", "wall_start", "wall_end", "length_s", "started",
               "time_wait_wait_s", "time_wait_before_wait", "time_wait_start", "driver_error"}


def fake_row(cfg: dict, raw: Path) -> dict:
    """A row as wwindow.run_window returns it, with metrics, after writing raw files."""
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "x.opgen.json").write_text(json.dumps({"measure": {"completed": 123456}}))
    (raw / "x.opgen.err").write_text("err")
    return {"cell": cfg["cell"], "started": "2026-10-24T03:00:00+0300", "time_wait_wait_s": 33.5, "time_wait_before_wait": 9000,
            "time_wait_start": 900, "metric": {"value": 4321.0}, "valid": True, "invalid_reasons": [],
            "opgen": {"completed": 123456}, "server_cpu_s": 4.2, "conn_rate": 8000.0}


class Probe(unittest.TestCase):
    def test_parse_dynamic_port(self):
        text = ("\nProtocol tcp Dynamic Port Range\n---------------------------------\nStart Port      : 49152\n"
                "Number of Ports : 16384\n")
        self.assertEqual(wprobe.parse_dynamic_port(text), {"start": 49152, "count": 16384, "end": 65535})
        self.assertEqual(wprobe.parse_dynamic_port("nothing"), {})

    def test_pilot_rates(self):
        r = wprobe.pilot_rates(PILOT)
        self.assertEqual(sorted(r), sorted(wprobe.PROTOS))
        self.assertAlmostEqual(r["http1"], 8544.537, places=3)
        self.assertAlmostEqual(r["mqtt"], 2609.799, places=3)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pilot.json"
            p.write_bytes(PILOT.read_bytes() + b" ")
            with self.assertRaises(SystemExit):
                wprobe.pilot_rates(p)

    def test_groups(self):
        g = wprobe.groups({p: 1.0 for p in wprobe.PROTOS})
        self.assertEqual(len(g), 12)
        self.assertEqual(sum(x["windows"] for x in g), 40)
        self.assertEqual([(x["workload"], x["proto"]) for x in g[:2]], [("churn", "http1"), ("open", "http1")])
        self.assertEqual([x["workload"] for x in g[8:]], ["keepalive"] * 4)
        self.assertTrue(all((x["rate"] is not None) == (x["workload"] == "open") for x in g))

    def test_window_line_drops_every_metric(self):
        with tempfile.TemporaryDirectory() as d:
            row = fake_row({"cell": "c"}, Path(d))
        line = wprobe.window_times(row, phase="probe", index=3, group={"workload": "churn", "proto": "tls"}, t0=1.0, t1=41.5, w0=5.0, w1=45.5)
        self.assertEqual(set(line), WINDOW_KEYS)
        self.assertEqual((line["length_s"], line["time_wait_wait_s"], line["driver_error"]), (40.5, 33.5, None))
        fault = {"invalid_reasons": ["driver error: OSError()"], "valid": False}
        self.assertEqual(wprobe.window_times(fault, phase="probe", index=0, group={"workload": "open", "proto": "h2c"}, t0=0, t1=1,
                                             w0=0, w1=1)["driver_error"], "driver error: OSError()")

    def test_run_keeps_wall_time_only(self):
        seen = []

        def run_window(cfg, session, arm, position, blocks, raw):
            seen.append((cfg["workload"], cfg["proto"], cfg.get("rate"), arm, cfg["functional"]))
            time.sleep(0.02)
            return fake_row(cfg, raw)

        fp = {"lab_plan": LAB, "pinned": True, "frequency": {"server_mean": 99.0}, "cycle_rate": {"cycles_per_s": 3.2e9}}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            a = mock.Mock(out=out, job="a3", build=Path(d), k_src=16, blocks=Path(d) / "blocks.json")
            rates = wprobe.pilot_rates(PILOT)
            p = wprobe.Probe(a, rates, run_window=run_window, fingerprint=lambda: dict(fp), warmup_s=0.05)
            p.run()
            text = (out / "probe-times.jsonl").read_text(encoding="utf-8")
            files = sorted(x.name for x in out.iterdir())
        lines = [json.loads(x) for x in text.splitlines()]
        windows = [x for x in lines if x["kind"] == "window"]
        probe = [x for x in windows if x["phase"] == "probe"]
        self.assertEqual(files, ["probe-times.jsonl"])  # the raw files are gone
        self.assertEqual(len(probe), 40)
        self.assertGreaterEqual(len(windows) - len(probe), 2)  # the warm-up
        self.assertEqual(len([x for x in lines if x["kind"] == "reading"]), 13)
        self.assertTrue(all(set(x) == WINDOW_KEYS for x in windows))
        for word in ("metric", "valid", "completed", "4321", "123456", "cpu_s", "conn_rate", "frequency", "cycles"):
            self.assertNotIn(word, text)
        self.assertTrue(all(s[3] == "A" and s[4] is False for s in seen))
        self.assertEqual([s[2] for s in seen if s[0] == "open"][::4], [rates[p] for p in wprobe.PROTOS])
        s = wprobe.summarise(lines)
        self.assertEqual((s["windows"]["churn"]["count"], s["windows"]["open"]["count"], s["windows"]["keepalive"]["count"]), (16, 16, 8))
        self.assertEqual(s["windows"]["churn"]["started_above_limit"], 0)
        self.assertEqual(s["readings"]["count"], 13)

    def test_summary_flags(self):
        lines = [{"kind": "window", "phase": "probe", "workload": "open", "length_s": 47.0, "time_wait_wait_s": 40.0, "time_wait_start": 1500,
                  "driver_error": None},
                 {"kind": "window", "phase": "probe", "workload": "open", "length_s": 7.0, "time_wait_wait_s": 1.0, "time_wait_start": 10,
                  "driver_error": "driver error: x"}]
        s = wprobe.summarise(lines)["windows"]["open"]
        self.assertEqual((s["wait_at_cap"], s["started_above_limit"], s["driver_errors"]), (1, 1, 1))
        self.assertEqual(s["length_s"], {"n": 2, "sum": 54.0, "min": 7.0, "max": 47.0})

    def test_main_stops_on_a_port_conflict(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(wprobe, "readings", lambda: {"port_conflicts": ["ports 20000 to 20005 overlap W's excluded range"]}), \
                mock.patch.object(wprobe.wrunlib, "install_stop", lambda: None), \
                mock.patch.object(wprobe.waa, "provenance", lambda build: {"build_dir": str(build)}), \
                mock.patch.object(wprobe.Probe, "run", side_effect=AssertionError("a window ran")):
            out = Path(d) / "out"
            rc = wprobe.main(["--build", d, "--out", str(out), "--job", "a3", "--pilot", str(PILOT)])
            self.assertEqual(rc, wprobe.EXIT_PORTS)
            self.assertTrue((out / "probe-summary.json").is_file())

    def test_readings_are_read_only(self):
        r = wprobe.readings()
        self.assertIn("tcp_timed_wait_delay", r)
        if sys.platform == "win32":
            self.assertTrue(r["dynamic_port_tcp"]["read"])
            self.assertIn("start", r["dynamic_port_tcp"]["parsed"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
