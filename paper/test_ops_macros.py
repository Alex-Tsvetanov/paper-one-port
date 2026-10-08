"""Tests of paper/ops_macros.py.

    python -m pytest paper/test_ops_macros.py

Its inputs are archived rows outside the repository. Where they are at hand (W's copy of the
unpacked archives, or the paths in ONEPORT_COST_L, ONEPORT_COST_W, ONEPORT_M_L and ONEPORT_M_W), the
committed files must be what the generator writes from them; elsewhere that test is skipped.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ops_macros as O  # noqa: E402

UNPACKED = Path(os.path.expanduser("~")) / "lab" / "p3" / "confirm1" / "unpacked"
PATHS = {"cost_l": Path(os.environ.get("ONEPORT_COST_L", UNPACKED / "pc1" / "cost-L" / "windows.jsonl")),
         "cost_w": Path(os.environ.get("ONEPORT_COST_W", UNPACKED / "wc1-wc2" / "cost-W" / "windows.jsonl")),
         "m_l": Path(os.environ.get("ONEPORT_M_L", UNPACKED / "ml1" / "m-L" / "windows.jsonl")),
         "m_w": Path(os.environ.get("ONEPORT_M_W", UNPACKED / "wm1" / "m-W" / "windows.jsonl"))}


def window(**kw) -> dict:
    per = {k: 0 for k in O.OP_COUNTERS} | {"accepted": 1, "bytes_copied": 0, "bytes_received": 57, "bytes_sent": 78,
                                          "bytes_peeked": 0, "detection_wakeups": 1}
    per |= {"accept_calls": 2, "recv_calls": 1, "send_calls": 1, "io_uring_submissions": {"READ": 1.0, "ACCEPT": 0.5}}
    base = {"cell": "C1.L.io_uring.http1", "mode": "one-port", "detect": "replay", "dispatch": "inproc", "valid": True,
            "development": False, "workload": "churn", "per_connection": per, "tag": "t"}
    base.update(kw)
    return base


def test_op_counters_are_rule_e_s_fourteen():
    assert len(O.OP_COUNTERS) == 14 and "gqcs_calls" in O.OP_COUNTERS and "io_uring_enter_calls" in O.OP_COUNTERS


def test_ops_sums_the_call_counters_and_the_submissions():
    assert O.ops(window()["per_connection"]) == pytest.approx(2 + 1 + 1 + 1.5)


def test_keep_alive_is_per_request():
    w = window(workload="keepalive")
    w["per_request"] = {"accepted": 0.01, "recv_calls": 0.01, "send_calls": 0.01, "bytes_received": 0.57}
    v = O.window_values(w)
    assert v["Ops"] == pytest.approx(5.5 * 0.01) and v["Received"] == pytest.approx(0.57)


def test_keep_alive_refuses_a_per_request_that_disagrees():
    w = window(workload="keepalive")
    w["per_request"] = {"accepted": 0.01, "recv_calls": 0.5, "send_calls": 0.01, "bytes_received": 0.57}
    with pytest.raises(ValueError):
        O.window_values(w)


def test_arm_means_uses_valid_windows_only():
    rows = [window(), window(valid=False, per_connection=dict(window()["per_connection"], bytes_copied=100))]
    n, means = O.arm_means(rows, "C1.L.io_uring.http1", "mode", "one-port")
    assert n == 1 and means["Copied"] == 0


@pytest.mark.parametrize("bad", [{"development": True}, {"dispatch": "relay"}])
def test_arm_means_refuses(bad):
    with pytest.raises(ValueError):
        O.arm_means([window(**bad)], "C1.L.io_uring.http1", "mode", "one-port")


def test_a_file_summary_does_not_name_is_refused(tmp_path):
    p = tmp_path / "windows.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        O.read_rows(p, O.summary_inputs(), "pc1 cost-L")


def test_names_do_not_clash_with_the_other_macro_files():
    names = re.findall(r"\\newcommand\{\\([^}]*)\}", O.OUT.read_text(encoding="utf-8"))
    assert names and all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    assert not set(names) & O.other_names()


def test_every_table_macro_is_defined():
    names = set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", O.OUT.read_text(encoding="utf-8")))
    for t in ("ops-cost.tex", "ops-m1.tex"):
        used = set(re.findall(r"\\([A-Za-z]+)", (O.TABLES / t).read_text(encoding="utf-8")))
        assert used <= names, sorted(used - names)


@pytest.mark.skipif(not all(p.exists() for p in PATHS.values()), reason="the archived window rows are not at hand")
def test_committed_files_are_current():
    for path, text in O.build(PATHS).items():
        assert path.read_text(encoding="utf-8") == text, path
