#!/usr/bin/env python3
"""Tests of the W window runner (bench/run/w*.py; M6b): powercfg's output as W prints it (samples
recorded on W on 2026-10-03), section 2's values, the core-layout and quiet rules, the frequency
test's rule, a window's metric and its validity rules on W, the cells, the functional summary, a
process's output read by a thread, and the dedicated-mode guard. On Windows also W's readings (core
layout, timer resolution, a PDH reading, TCP statistics), a pinned start, and the lab lock between
two holders. Pure and untimed; nothing here changes a setting of W.

    python bench/run/test_wrunner.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import waa  # noqa: E402
import wfreq  # noqa: E402
import window  # noqa: E402
import wpower  # noqa: E402
import wsys  # noqa: E402
import wwindow  # noqa: E402

SAMPLES = HERE / "samples"
LAB = "277bfd76-c26d-4cac-b253-a8500e6728d8"
CHECKS: list = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def powercfg_list():
    plans = wpower.parse_list((SAMPLES / "W-powercfg-list.txt").read_text(encoding="utf-8"))
    by = {p["guid"]: p for p in plans}
    assert len(plans) == 9, plans
    assert by[wpower.ALEX_PLAN]["name"] == wpower.ALEX_PLAN_NAME and by[wpower.ALEX_PLAN]["active"]
    assert by[LAB]["name"] == wpower.LAB_PLAN_NAME and not by[LAB]["active"]
    assert by[wpower.HIGH_PERFORMANCE]["name"] == "High performance"
    assert sum(p["active"] for p in plans) == 1


@check
def powercfg_active_and_duplicate():
    a = wpower.parse_active((SAMPLES / "W-powercfg-getactivescheme.txt").read_text(encoding="utf-8"))
    assert a == {"guid": wpower.ALEX_PLAN, "name": wpower.ALEX_PLAN_NAME}, a
    # duplicatescheme's line as W printed it on 2026-10-03 (C:\Users\alext\lab\p3\m6b\plan-create.json).
    assert wpower.parse_duplicate(f"Power Scheme GUID: {LAB}  (High performance)") == LAB
    try:
        wpower.parse_duplicate("")
        raise AssertionError("no GUID accepted")
    except wpower.PowerError:
        pass


@check
def powercfg_readback():
    qh = wpower.parse_qh((SAMPLES / "W-powercfg-qh-lab.txt").read_text(encoding="utf-8"))
    assert qh[wpower.BOOST_MODE]["ac"] == 0 and qh[wpower.BOOST_MODE]["alias"] == "PERFBOOSTMODE"
    assert qh[wpower.PROC_MIN]["ac"] == 100 and qh[wpower.PROC_MAX]["ac"] == 100 and qh[wpower.CP_MIN_CORES]["ac"] == 100
    assert qh[wpower.IDLE_DISABLE]["ac"] == 0
    assert wpower.check_values(qh) == []
    bad = json.loads(json.dumps(qh))
    bad[wpower.BOOST_MODE]["ac"] = 2
    del bad[wpower.CP_MIN_CORES]
    problems = wpower.check_values(bad)
    assert len(problems) == 2 and "boost" in problems[0] and "parking" in problems[1], problems


@check
def powercfg_denied():
    assert wpower.denied("Access is denied.\n")
    assert wpower.denied("Unable to perform operation. You may not have permission. Run as administrator.")
    assert not wpower.denied(f"Power Scheme GUID: {LAB}  (High performance)")
    assert not wpower.denied("")


@check
def section2_commands():
    # Section 2's list: boost by GUID 0, the states by alias 100, parking by GUID 100.
    assert wpower.SET_COMMANDS == [("SUB_PROCESSOR", wpower.BOOST_MODE, 0), ("SUB_PROCESSOR", "PROCTHROTTLEMIN", 100),
                                   ("SUB_PROCESSOR", "PROCTHROTTLEMAX", 100), ("SUB_PROCESSOR", wpower.CP_MIN_CORES, 100)]
    assert wpower.LAB_VALUES == {wpower.BOOST_MODE: 0, wpower.PROC_MIN: 100, wpower.PROC_MAX: 100, wpower.CP_MIN_CORES: 100}


@check
def core_layout_rule():
    good = [{"cpus": [2 * k, 2 * k + 1], "group": 0, "efficiency_class": 0} for k in range(6)]
    assert wsys.check_core_layout(good) == []
    swapped = [dict(c) for c in good]
    swapped[5] = {"cpus": [10, 9], "group": 0, "efficiency_class": 0}
    assert wsys.check_core_layout(swapped)
    assert wsys.check_core_layout(good[:5])
    two = [dict(c) for c in good]
    two[0] = dict(two[0], efficiency_class=1)
    assert wsys.check_core_layout(two)
    other_group = [dict(c) for c in good]
    other_group[3] = dict(other_group[3], group=1)
    assert wsys.check_core_layout(other_group)
    assert wsys.mask([10]) == 0x400 and wsys.mask(range(2, 10)) == 0x3FC and wsys.mask([0, 1]) == 0x3


@check
def quiet_rules():
    cpus = {c: 99.0 for c in range(12)}
    ok = wsys.quiet_verdict([95.0] * 10, cpus, [{"name": "a", "pid": 1, "cpu_percent": 5.0}])
    assert ok["quiet"], ok["reasons"]  # at the bounds: 95% idle and 5% of one CPU pass
    low = wsys.quiet_verdict([94.9] * 10, cpus, [])
    assert not low["quiet"] and "mean CPU idle" in low["reasons"][0]
    one = wsys.quiet_verdict([99.0] * 10, {**cpus, 10: 94.9}, [])
    assert not one["quiet"] and "CPU 10" in one["reasons"][0]
    outside = wsys.quiet_verdict([99.0] * 10, {**cpus, 0: 50.0, 11: 50.0}, [])
    assert outside["quiet"], "CPUs 0, 1 and 11 are not the window's"
    proc = wsys.quiet_verdict([99.0] * 10, cpus, [{"name": "TextInputHost", "pid": 7, "cpu_percent": 5.1}])
    assert not proc["quiet"] and "TextInputHost" in proc["reasons"][0]
    own = wsys.quiet_verdict([99.0] * 10, cpus, [{"name": "python", "pid": 9, "cpu_percent": 40.0}], exclude_pids=(9,))
    assert own["quiet"] and own["top_processes"] == []
    missing = wsys.quiet_verdict([99.0] * 10, {c: 99.0 for c in range(10)}, [])
    assert not missing["quiet"] and "CPU 10: no idle reading" in missing["reasons"]


@check
def update_state():
    assert wsys.update_installing({"update_installer_busy": True}) is True
    assert wsys.update_installing({"update_installer_busy": False}) is False
    assert wsys.update_installing({}) is None


@check
def frequency_rule():
    # Boost off stable within 2%, boost on 6% above: passes.
    p = wfreq.judge([100.0, 100.5, 99.6], [106.0, 106.2])
    assert p["pass"] and p["stable_within_2pct"] and p["moved_more_than_2pct"]
    # W on 2026-10-03: the counter the same with boost on and off: fails the second part.
    f = wfreq.judge([99.999, 99.998], [99.999, 99.999])
    assert not f["pass"] and f["stable_within_2pct"] and not f["moved_more_than_2pct"]
    # A boost-off sample 2.5% from the mean: fails the first part.
    u = wfreq.judge([100.0, 100.0, 105.0], [120.0])
    assert not u["pass"] and not u["stable_within_2pct"]
    assert not wfreq.judge([], [1.0])["pass"]


def report(workload: str = "churn", completed: int = 50000, errors: int = 0, connect: int = 0, cpu_pct: float = 40.0,
           completed_share: float = 1.0) -> dict:
    e = {"connect": connect, "timeout": 0, "reset": 0, "eof": 0, "protocol": 0, "tls": 0, "total": errors + connect}
    return {"ok": True, "wall_s": 5.0, "measure": {"completed": completed, "errors": e}, "warmup": {"completed": 1, "errors": e},
            "error_share": (errors + connect) / max(1, completed + errors + connect), "connect_failures": connect, "connects_run": completed,
            "all_completed": completed + 10, "due": completed, "due_completed": int(completed * completed_share), "due_errors": e,
            "due_unfinished": 0, "completed_share": completed_share, "ttfb_ns": {"median": 80000.0}, "ttfb_connect_ns": {},
            "exchange_ns": {}, "issue_lag_ns": {}, "cpu": {"pct": cpu_pct}, "peak_concurrency_per_worker": 1,
            "measure_start_ns": 1, "measure_end_ns": 2, "threads": 8}


def snaps(gen_busy: float = 50.0, server_perf: float = 100.0) -> dict:
    cpus = {str(c): {"% Processor Time": gen_busy if 2 <= c <= 9 else (99.9 if c == 10 else 1.0), "% Processor Performance": server_perf,
                     "Actual Frequency": 3950.0, "% Interrupt Time": 0.0, "% DPC Time": 0.0, "Interrupts/sec": 1000.0} for c in range(12)}
    return {"s0": {"t": 0.0, "cpu_s": 1.0, "working_set_kb": 9000}, "s1": {"t": 5.0, "cpu_s": 5.9, "working_set_kb": 9100, "peak_working_set_kb": 9200},
            "cpus": {"span_s": 5.0, "cpus": cpus}}


def row(workload: str = "churn") -> dict:
    return {"workload": workload, "server_exit": 0, "probe": {"connect_failures": 0}, "power_plan_start": {"guid": LAB},
            "power_plan_end": {"guid": LAB}, "server_counters": {"accepted": 50001, "recv_calls": 50001, "send_calls": 50001}}


SESSION = {"lab_plan": LAB, "frequency": {"server_mean": 100.0}}


@check
def window_metric_and_rules():
    r = wwindow.finish(row(), report(), snaps(), SESSION, [])
    assert r["valid"], r["invalid_reasons"]
    assert r["metric"] == {"name": "conn_per_s", "value": 10000.0}
    assert abs(r["server_cpu_s"] - 4.9) < 1e-9 and abs(r["cpu_us_per_exchange"] - 98.0) < 1e-9
    assert abs(r["server_cores_busy"] - 0.999) < 1e-9 and r["gen_cpus_busy_pct"] == 50.0 and r["gen_cpu_pct_rule"] == 50.0
    assert r["irq_server"] == 5000.0 and r["irq_generator"] == 40000.0
    assert r["per_connection"]["recv_calls"] == 1.0 and r["rss_kb"] == 9100 and r["peak_rss_kb"] == 9200
    assert r["freq_window"] == 100.0 and r["freq_drift"] == 0.0
    ka = wwindow.finish(row("keepalive"), report("keepalive"), snaps(), SESSION, [])
    assert ka["metric"]["name"] == "req_per_s" and "per_request" in ka
    op = wwindow.finish(row("open"), report("open"), snaps(), SESSION, [])
    assert op["metric"] == {"name": "ttfb_median_us", "value": 80.0} and op["valid"]


@check
def window_invalid_reasons():
    def reasons(**kw):
        rw = row(kw.pop("workload", "churn"))
        rw.update(kw.pop("row", {}))
        return wwindow.finish(rw, report(rw["workload"], **kw.pop("rep", {})), kw.pop("snaps", snaps()), kw.pop("session", SESSION), [])["invalid_reasons"]
    assert any("errors" in x for x in reasons(rep={"errors": 100}))
    assert any("connects failed" in x for x in reasons(rep={"connect": 1}))
    assert any("connects failed" in x for x in reasons(row={"probe": {"connect_failures": 1}}))
    assert any("generator CPU" in x for x in reasons(snaps=snaps(gen_busy=90.5)))
    assert any("generator CPU" in x for x in reasons(rep={"cpu_pct": 91.0}))
    assert not any("generator CPU" in x for x in reasons(workload="open", snaps=snaps(gen_busy=95.0)))
    assert any("below 99%" in x for x in reasons(workload="open", rep={"completed_share": 0.985}))
    assert any("not the lab plan" in x for x in reasons(row={"power_plan_end": {"guid": wpower.ALEX_PLAN}}))
    assert any("server exit" in x for x in reasons(row={"server_exit": 1}))
    assert any("no window markers" in x for x in reasons(snaps={}))
    assert any("no exchange completed" in x for x in reasons(rep={"completed": 0}))
    # The frequency rule: recorded always, applied only with FREQ_RULE (off since the test of
    # 2026-10-03 did not pass).
    drift = reasons(snaps=snaps(server_perf=103.0))
    assert not any("frequency" in x for x in drift) or wwindow.FREQ_RULE
    saved = wwindow.FREQ_RULE
    try:
        wwindow.FREQ_RULE = True
        assert any("frequency counter drift" in x for x in reasons(snaps=snaps(server_perf=103.0)))
        assert not any("frequency" in x for x in reasons(snaps=snaps(server_perf=101.0)))
    finally:
        wwindow.FREQ_RULE = saved
    r = wwindow.finish(row(), {"ok": False, "error": "x"}, {}, SESSION, [])
    assert not r["valid"] and "opgen failed: x" in r["invalid_reasons"]


@check
def cells_and_summary():
    cells = waa.parse_cells("churn:http1,keepalive:mqtt,open:tls")
    assert [c["cell"] for c in cells] == ["churn.http1.IOCP", "keepalive.mqtt.IOCP", "open.tls.IOCP"]
    for bad in ("churn:http1:epoll", "burst:http1", "churn:quic"):
        try:
            waa.parse_cells(bad)
            raise AssertionError(f"{bad} accepted")
        except (SystemExit, ValueError):
            pass
    s = waa.functional_summary([{"cell": "c", "valid": True}, {"cell": "c", "valid": False, "tag": "t", "invalid_reasons": ["r"]}])
    assert s == {"c": {"windows": 2, "valid": 1, "invalid": [{"tag": "t", "reasons": ["r"]}]}}


@check
def dedicated_only():
    cmd = wwindow.server_cmd(Path("build"), 20000)
    assert cmd[cmd.index("--mode") + 1] == "dedicated" and cmd[cmd.index("--backend") + 1] == "IOCP"
    try:
        window.guard_mode([c if c != "dedicated" else "one-port" for c in cmd])
        raise AssertionError("one-port mode accepted")
    except window.WindowError:
        pass


@check
def placement():
    assert wwindow.SERVER_CPUS == [10] and wwindow.SERVER_IDLE_SIBLINGS == [11] and wwindow.GEN_CPUS == list(range(2, 10))
    assert wwindow.gen_threads({"workload": "open"}) == [2, 4, 6, 8] and wwindow.gen_threads({"workload": "churn"}) == list(range(2, 10))
    assert wwindow.WARMUP_MS == 1000 and wwindow.DURATION_MS == 5000 and wwindow.CONNS_PER_CORE == 64


@check
def thread_lines():
    p = subprocess.Popen([sys.executable, "-c", "import sys,time; print('a'); sys.stdout.flush(); time.sleep(0.2); print('MEASURE_START 1'); print('b')"],
                         stdout=subprocess.PIPE)
    lines = wwindow.ThreadLines(p)
    seen = []
    assert lines.until(lambda ln: seen.append(ln) or ln.startswith("MEASURE_START"), 10)
    assert seen == ["a", "MEASURE_START 1"], seen
    assert lines.rest(10) == ["a", "MEASURE_START 1", "b"]
    p.wait()


@check
def windows_readings():
    if not wsys.IS_WINDOWS:
        return "skipped: not Windows"
    cores = wsys.core_layout()
    assert len(cores) >= 1 and all(c["cpus"] for c in cores)
    t = wsys.timer_resolution()
    assert t["finest_ms"] <= t["current_ms"] <= t["coarsest_ms"], t
    with wsys.Pdh([wsys.cpu_path(0, "% Processor Time")]) as q:
        q.collect()
        time.sleep(0.2)
        q.collect()
        v = q.value(wsys.cpu_path(0, "% Processor Time"))
        assert v is not None and 0.0 <= v <= 100.0, v
    s = wsys.tcp_stats()
    assert "ActiveOpens" in s and s["ActiveOpens"] >= 0
    assert wsys.time_wait_count() >= 0
    assert not wsys.set_named_event("Local\\oneport-test-no-such-event")


@check
def pinned_start():
    if not wsys.IS_WINDOWS:
        return "skipped: not Windows"
    p = wsys.start_pinned([sys.executable, "-c", "import time; time.sleep(1)"], [0], stdout=subprocess.DEVNULL)
    try:
        assert wsys.affinity(p.pid) == 0x1, hex(wsys.affinity(p.pid))
    finally:
        p.wait(timeout=30)
    assert p.returncode == 0


@check
def lab_lock():
    if not wsys.IS_WINDOWS:
        return "skipped: not Windows"
    import wlock
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".lab.lock"
        with wlock.WLock(path, wait_s=5):
            t0 = time.monotonic()
            try:
                wlock.WLock(path, wait_s=0.5, poll_s=0.1).acquire()
                raise AssertionError("a second holder got the lock")
            except wlock.LockTimeout:
                assert time.monotonic() - t0 >= 0.5
        second = wlock.WLock(path, wait_s=1).acquire()  # released by the first holder's exit
        second.release()


def main() -> int:
    failed = 0
    for fn in CHECKS:
        try:
            note = fn()
            print(f"PASS: {fn.__name__}" + (f" ({note})" if note else ""))
        except Exception:  # noqa: BLE001 - every check reports
            failed += 1
            print(f"FAIL: {fn.__name__}\n{traceback.format_exc()}")
    print(f"{len(CHECKS) - failed} of {len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
