"""Tests of paper/w_evidence_macros.py.

    python -m pytest paper/test_w_evidence_macros.py

Its inputs are archived rows outside the repository. Where they are at hand (W's lab directory, or
the paths in ONEPORT_PILOT_W and ONEPORT_M_W), the committed file must be what the generator writes
from them; elsewhere that test is skipped. The other tests need no archive.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import w_evidence_macros as E  # noqa: E402

LAB = Path(os.path.expanduser("~")) / "lab" / "p3"
PILOT_W = Path(os.environ.get("ONEPORT_PILOT_W", LAB / "pilot-W" / "windows.jsonl"))
M_W = Path(os.environ.get("ONEPORT_M_W", LAB / "m-W" / "windows.jsonl"))


def test_the_pilot_rows_are_named_once():
    assert re.fullmatch(r"[0-9a-f]{64}", E.pilot_w_sha256())


def test_a_file_the_repository_does_not_name_is_refused(tmp_path):
    p = tmp_path / "windows.jsonl"
    p.write_text(json.dumps({"cell": "C1.W.IOCP.h2c"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        E.read_rows(p, {E.pilot_w_sha256()}, "W's pilot rows")


def test_names_do_not_clash_with_the_other_macro_files():
    text = E.OUT.read_text(encoding="utf-8")
    names = re.findall(r"\\newcommand\{\\([^}]*)\}", text)
    assert names and all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    others: set[str] = set()
    for f in ("macros.tex", "hardcase-macros.tex", "design-macros.tex", "report-macros.tex"):
        others |= set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", (E.ROOT / "results" / f).read_text(encoding="utf-8")))
    assert not set(names) & others


@pytest.mark.skipif(not (PILOT_W.exists() and M_W.exists()), reason="the archived W rows are not at hand")
def test_committed_file_is_current():
    assert E.OUT.read_text(encoding="utf-8") == E.build(PILOT_W, M_W)
