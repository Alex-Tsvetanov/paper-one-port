"""Tests of paper/b2_macros.py.

    python -m pytest paper/test_b2_macros.py

Its inputs are archived rows outside the repository. Where they are at hand (W's copy of the
unpacked archives, or the paths in ONEPORT_HL1 and ONEPORT_WH1), the committed files must be what
the generator writes from them; elsewhere that test is skipped. The other tests need no archive.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import b2_macros as B  # noqa: E402

UNPACKED = Path(os.path.expanduser("~")) / "lab" / "p3" / "confirm1" / "unpacked"
HL1 = Path(os.environ.get("ONEPORT_HL1", UNPACKED / "pc1" / "hard-L" / "hardcases.jsonl"))
WH1 = Path(os.environ.get("ONEPORT_WH1", UNPACKED / "wh1" / "hard-W" / "hardcases.jsonl"))


def row(**kw) -> dict:
    base = {"kind": "hardcase", "job": "hl1", "development": False, "backend": "epoll", "timed": None,
            "decision_ns_after_last_write": 1000}
    base.update(kw)
    return base


def test_nearest_rank():
    v = list(range(1, 101))
    assert B.nearest_rank(v, 0.99) == 99
    assert B.nearest_rank(v, 0.5) == 50
    assert B.nearest_rank([7], 0.99) == 7
    assert B.nearest_rank(list(range(1, 201)), 0.99) == 198
    with pytest.raises(ValueError):
        B.nearest_rank([], 0.5)


def test_summary_of_five_values():
    s = B.summary([5, 1, 4, 2, 3])
    assert s == {"N": 5, "Min": 1, "Median": 3, "PNinetyNine": 5, "Max": 5}


def test_split_puts_each_run_in_one_distribution():
    rows = [row(), row(timed={"kind": "T_dec"}, lateness_ns=50, decision_ns_after_last_write=3_000_000),
            row(decision_ns_after_last_write=None), row(kind="hardcase-servers")]
    del rows[2]["decision_ns_after_last_write"]
    out = B.split(rows, "L", "hl1", ("epoll", "io_uring"))
    assert out["epoll"]["DecisionBytes"] == [1000]
    assert out["epoll"]["DecisionTimer"] == [3_000_000]
    assert out["epoll"]["Lateness"] == [50]
    assert len(out["epoll"]["NoWrite"]) == 1 and len(out["epoll"]["Runs"]) == 3
    assert out["io_uring"]["Lateness"] == []


def test_hc21_and_hc22_are_counted_apart_among_the_runs_no_timer_ended():
    rows = [row(id="HC21.partial", decision_ns_after_last_write=5_000_000), row(id="HC01.HTTP", decision_ns_after_last_write=20_000),
            row(id="HC22.partial", timed={"kind": "T_dec"}, lateness_ns=1, decision_ns_after_last_write=9)]
    out = B.split(rows, "L", "hl1", ("epoll", "io_uring"))
    assert out["epoll"]["Shut"] == [(5_000_000, "HC21.partial")]
    assert out["epoll"]["Other"] == [(20_000, "HC01.HTTP")]
    assert out["epoll"]["DecisionTimer"] == [9]


def test_case_list():
    assert B.case_list([]) == "none"
    assert B.case_list(["HC02.h2c.k21"]) == "HC2"
    assert B.case_list(["HC10.k04", "HC02.h2c.k21", "HC02.h2c.k20", "HC23.GETX"]) == "HC2, HC10 and HC23"
    with pytest.raises(ValueError):
        B.case_list(["H2.x"])


@pytest.mark.parametrize("bad", [
    {"job": "hc1"},
    {"development": True},
    {"backend": "IOCP"},
    {"timed": {"kind": "T_fb"}},          # a timed event without its lateness
    {"lateness_ns": 10},                  # a lateness without a timed event
])
def test_split_refuses_a_row_that_disagrees(bad):
    with pytest.raises(ValueError):
        B.split([row(**bad)], "L", "hl1", ("epoll", "io_uring"))


def test_inputs_are_those_hardcase_macros_names():
    named = B.named_inputs()
    assert set(named) == {"L", "W"} and all(re.fullmatch(r"[0-9a-f]{64}", d) for d in named.values())


def test_a_file_hardcase_macros_does_not_name_is_refused(tmp_path):
    p = tmp_path / "hardcases.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        B.read_rows(p, B.named_inputs()["L"], "L's hl1 rows")


def test_names_do_not_clash_with_the_other_macro_files():
    names = re.findall(r"\\newcommand\{\\([^}]*)\}", B.OUT.read_text(encoding="utf-8"))
    assert names and all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    assert not set(names) & B.other_names()


@pytest.mark.skipif(not (HL1.exists() and WH1.exists()), reason="the archived hard-case rows are not at hand")
def test_committed_files_are_current():
    for path, text in B.build({"L": HL1, "W": WH1}).items():
        assert path.read_text(encoding="utf-8") == text, path
