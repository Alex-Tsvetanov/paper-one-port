"""Tests of paper/trace_macros.py.

    python -m pytest paper/test_trace_macros.py

Its inputs are lab job st1's files outside the repository. Where they are at hand (W's copy of the
unpacked archive, or the paths in ONEPORT_ST1_TRACE, ONEPORT_ST1_CALLS and ONEPORT_ST1_CLEARANCE),
the committed files must be what the generator writes from them; elsewhere that test is skipped.
The other tests build rows of their own.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import trace_macros as T  # noqa: E402

ST1 = Path(os.path.expanduser("~")) / "lab" / "p3" / "confirm1" / "unpacked" / "st1" / "st-L"
TRACE = Path(os.environ.get("ONEPORT_ST1_TRACE", ST1 / "trace.jsonl"))
CALLS = Path(os.environ.get("ONEPORT_ST1_CALLS", ST1 / "calls-st1.jsonl"))
CLEARANCE = Path(os.environ.get("ONEPORT_ST1_CLEARANCE", ST1 / "clearance-st1.json"))


def check(agree_stat: bool = True, agree_trace: bool = True) -> dict:
    return {"check": "accept", "stat_agrees": agree_stat, "agrees": agree_trace}


def stat(n: int = 10) -> dict:
    return {k: (n if k == "accept4" else 0) for k in T.STAT_CALLS}


def cost_row(w: str, p: str, b: str, m: str) -> dict:
    return {"job": "st1", "kind": "cost", "untimed": True, "development": True, "cell": f"{w}.{p}.{b}", "mode": m, "detect": "replay", "repeat": 0,
            "tag": f"st1-{w}.{p}.{b}-replay-{m}", "checks": [check(), check(True, False)], "agrees_with_perf_stat": True,
            "agrees": False, "trace_shortfall_max_share": 0.001, "perf_lost": 0, "server_exit": 0, "opgen": {"ok": True}}


def proxy_row(s: str, p: str, b: str = "epoll", d: str = "replay") -> dict:
    relay = s == T.RELAY
    r = {"job": "st1", "kind": "proxy", "untimed": True, "development": True, "system": s, "proto": p, "backend": b if relay else None,
         "detect": d if relay else None, "tag": f"st1-{s}-{p}-{b}-{d}", "stub_accepted": 5,
         "perf_calls": {"accept4": {"calls": 9, "errors": 0}, "close": {"calls": 5, "errors": 0}}, "perf_stat": stat(10),
         "perf_lost": 0, "opgen": {"ok": True}}
    if relay:
        r["server_counters"] = {"relayed": 5, "accept_calls": 10, "recv_calls": 10, "send_calls": 10, "bytes_copied": 0,
                                "bytes_received": 285, "bytes_sent": 390, "bytes_peeked": 0, "detection_wakeups": 5,
                                "io_uring_submissions": {"READ": 5}}
        r["checks"] = [check()]
        r["agrees_with_perf_stat"] = True
    return r


def all_rows() -> list[dict]:
    rows = [cost_row(w, p, b, m) for (_, w, p, b, m) in sorted(k for k in T.expected_keys() if k[0] == "cost")]
    rows += [proxy_row(s, p, b, d) for (_, s, p, b, d) in sorted(k for k in T.expected_keys() if k[0] == "proxy")]
    return rows


def test_the_plan_has_sixty_six_rows():
    assert len(T.expected_keys()) == 66
    assert len(T.check_rows(all_rows())) == 66


def test_a_missing_a_repeated_and_a_foreign_row_are_refused():
    rows = all_rows()
    with pytest.raises(ValueError):
        T.check_rows(rows[1:])
    with pytest.raises(ValueError):
        T.check_rows(rows + [rows[0]])
    with pytest.raises(ValueError):
        T.check_rows(rows[:-1] + [dict(rows[-1], job="m5tr3")])
    with pytest.raises(ValueError):
        T.check_rows(rows[:-1] + [dict(rows[-1], untimed=False)])
    with pytest.raises(ValueError):
        T.check_rows(rows[:-1] + [dict(rows[-1], development=False)])


def test_counts_of_the_counter_check():
    mc = T.AM.Macros()
    table = T.counter_check(mc, T.check_rows(all_rows()))
    v = {n: val for n, val, _ in mc.items}
    assert len(table) == 24
    assert v["TraceCostRows"] == "48" and v["TraceCostCells"] == "24"
    assert v["TraceCostChecks"] == "96" and v["TraceCostChecksStatAgree"] == "96" and v["TraceCostChecksTraceAgree"] == "48"
    assert v["TraceCostShortfallMaxPct"] == "0.10"


def test_system_calls_per_connection():
    mc = T.AM.Macros()
    T.syscalls(mc, T.check_rows(all_rows()))
    v = {n: val for n, val, _ in mc.items}
    assert v["TraceSysNginxHttpCalls"] == "2.800"            # (9 + 5) / 5, every call
    assert v["TraceSysNginxHttpCheckedTrace"] == "1.800"     # accept4 only
    assert v["TraceSysNginxHttpCheckedStat"] == "2.000"
    assert v["TraceSysNginxHttpShortfallPct"] == "10.00"


def test_relay_operations_per_relayed_connection():
    mc = T.AM.Macros()
    T.relay_ops(mc, T.check_rows(all_rows()))
    v = {n: val for n, val, _ in mc.items}
    assert v["TraceRelayEpollHttpReplayOps"] == "7.000"      # (10 + 10 + 10 + 5) / 5
    assert v["TraceRelayEpollHttpReplayReceived"] == "57.0"
    assert v["TraceRelayRows"] == "8"


def test_a_clearance_without_the_change_commit_is_refused():
    good = {"freeze": {"code_freeze": T.CODE_FREEZE, "change_commit": T.CHANGE_COMMIT},
            "gate": {"binaries": {"oneport": "4c64edc25f7689dab95c90218ae50d3d7e92960d3e4e08bb826b1239e252b179",
                                  "opgen": "a25faa11e47f89502ae4750d3325789f59fa97f73cf8f9d715daa7f7d749140a"}}}
    T.check_clearance(good)
    with pytest.raises(ValueError):
        T.check_clearance({"freeze": {"code_freeze": T.CODE_FREEZE}, "gate": good["gate"]})
    with pytest.raises(ValueError):
        T.check_clearance(dict(good, gate={"binaries": {"oneport": "a", "opgen": "b"}}))


def test_the_untimed_load_is_read_from_systrace():
    c = T.load_constants()
    assert c["TRACE_RATE"] > 0 and c["TRACE_MS"] > 0 and c["TRACE_KA_CONNS"] >= 1


def test_perf_stat_must_count_the_checked_calls():
    r = proxy_row("nginx", "http1")
    r["perf_stat"] = dict(r["perf_stat"], accept4=None)
    with pytest.raises(ValueError):
        T.calls_of(r, T.STAT_CALLS, "stat")


def test_names_do_not_clash_with_the_other_macro_files():
    if not T.OUT.exists():
        pytest.skip("results/trace-macros.tex is not written yet")
    names = re.findall(r"\\newcommand\{\\([^}]*)\}", T.OUT.read_text(encoding="utf-8"))
    assert names and all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    assert not set(names) & T.other_names()


@pytest.mark.skipif(not (TRACE.exists() and CALLS.exists() and CLEARANCE.exists()), reason="st1's files are not at hand")
def test_committed_files_are_current():
    for path, text in T.build(TRACE, CALLS, CLEARANCE).items():
        assert path.read_text(encoding="utf-8") == text, path
