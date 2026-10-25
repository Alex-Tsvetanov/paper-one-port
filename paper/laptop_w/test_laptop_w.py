"""Tests of the laptop set's generators (paper/laptop_w/).

    python -X utf8 -m pytest -q paper/laptop_w

The test that rebuilds the design macros needs lab job a0's archive; set P3_LW_INPUTS to a folder
that holds w-read-1.tar.gz and its .sha256, or it skips and says so. The commands that write every
output are in design/status.md, "The laptop set's other generated files and the writing pack".
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lw_common as C  # noqa: E402
import design_lw  # noqa: E402
import pack_lw  # noqa: E402
import report_lw  # noqa: E402
import trace_tables_lw  # noqa: E402

INPUTS = Path(os.environ["P3_LW_INPUTS"]) if os.environ.get("P3_LW_INPUTS") else None
need_inputs = pytest.mark.skipif(INPUTS is None or not INPUTS.is_dir(), reason="P3_LW_INPUTS not set: no extracted rows")


def test_unknown_words_stop_the_run():
    with pytest.raises(ValueError):
        C.need(C.HOST, "D", "host")
    with pytest.raises(ValueError):
        C.cell_phrase("C4.L.epoll.http1")
    with pytest.raises(ValueError):
        C.family_cell_columns("M1.L.epoll.http1")


def test_every_decision_cell_has_words():
    import csv
    with open(C.LW / "decisions.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            phrase = C.cell_phrase(r["cell"])
            assert not C.printed_label_hits(phrase), (r["cell"], phrase)


def test_printed_label_scan_catches_labels():
    assert C.printed_label_hits("C1 & L, epoll & HTTP/1.1 \\\\")
    assert C.printed_label_hits("C3.W.IOCP.h2c & one-port")
    assert C.printed_label_hits("an en dash \u2013 here")
    assert not C.printed_label_hits("churn & Linux, epoll & \\COneLEpollHttpValid \\\\")


def test_no_table_prints_an_internal_label():
    tables = sorted(C.TABLES.glob("*.tex"))
    assert len(tables) == 18
    for p in tables:
        assert not C.printed_label_hits(p.read_text(encoding="utf-8")), p.name


def test_every_macro_a_table_cites_is_in_the_pack():
    defined = set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", (C.LW / "pack-macros.tex").read_text(encoding="utf-8")))
    for p in sorted(C.TABLES.glob("*.tex")):
        body = "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.startswith("%"))
        cited = set(re.findall(r"\\([A-Za-z]+)", body)) - {"multicolumn", "mu", "le"}  # TeX's own commands
        assert cited <= defined, (p.name, sorted(cited - defined)[:5])


def test_pack_is_current_and_refuses_octobers_files(monkeypatch):
    assert pack_lw.main(["--check"]) == 0
    monkeypatch.setattr(pack_lw, "SOURCES", pack_lw.SOURCES + [C.RESULTS / "macros.tex"])
    with pytest.raises(ValueError, match="October"):
        pack_lw.build_pack()


def test_pack_refuses_a_name_defined_twice(monkeypatch):
    monkeypatch.setattr(pack_lw, "SOURCES", pack_lw.SOURCES + [C.LW / "b2-macros.tex"])
    with pytest.raises(ValueError, match="defined in"):
        pack_lw.build_pack()


def test_pack_ends_with_the_census_macros_and_keeps_the_earlier_parts():
    text = (C.LW / "pack-macros.tex").read_text(encoding="utf-8")
    parts = re.findall(r"^% ---- source: (\S+) sha256 (\w+)$", text, flags=re.M)
    assert [p for p, _ in parts][-2:] == ["results/trace-macros.tex", "results/laptop-w/census-macros.tex"]
    assert len(parts) == 9
    for name in ("CensusLEpollOnePort", "CensusLEpollReuseportLines", "CensusWIocpDedicated", "CensusDateL"):
        assert "\\newcommand{\\" + name + "}" in text, name


def test_pack_holds_r_per_host_and_no_pooled_r():
    text = (C.LW / "pack-macros.tex").read_text(encoding="utf-8")
    assert "\\newcommand{\\CostRL}" in text and "\\newcommand{\\CostRW}" in text
    assert "\\newcommand{\\CostR}" not in text


def test_report_and_trace_tables_are_current():
    assert report_lw.main(["--check"]) == 0
    assert trace_tables_lw.main(["--check"]) == 0


def test_cost_cells_outside_the_family_are_worded_from_their_treatment():
    text = (C.TABLES / "cost.tex").read_text(encoding="utf-8")
    assert "generator-bound" not in text
    assert text.count("outside the family: run in the pilot only") == 2


def test_no_desktop_job_or_host_in_the_laptop_outputs():
    pat = re.compile(r"\b(wp1|wre1|wc1|wc2|wm1|wh1|ws1)\b|Ryzen 5|36246")
    for name in pack_lw.GENERATED:
        text = (C.LW / name).read_text(encoding="utf-8")
        if name == "not-run.json":
            # The runner's not-run file of the cost cells writes October's reason, copied as written.
            text = re.sub(r'"text": "[^"]*"', '"text": ""', text)
        assert not pat.search(text), name


def test_design_specs_keep_frozen_values_and_drop_the_desktop():
    names = {n for s in design_lw.laptop_specs() for n in s.names}
    assert {"WTickMs", "HeldBackMacros", "AnalysisRunShort", "QuietIdleOld"}.isdisjoint(names)
    assert {"ChangeCommit", "GuardW", "LambdaWTls", "HostWCpu", "SizingCommitL", "FwAlpha"} <= names


def test_october_results_are_unchanged():
    out = subprocess.run(["git", "-C", str(C.ROOT), "status", "--porcelain", "--", "results"],
                         capture_output=True, text=True, check=True).stdout
    changed = [ln for ln in out.splitlines() if "results/laptop-w/" not in ln]
    assert not changed, changed


@need_inputs
def test_design_macros_are_current():
    archive = INPUTS / "w-read-1.tar.gz"
    if not archive.exists():
        pytest.skip("no w-read-1.tar.gz in P3_LW_INPUTS")
    assert design_lw.main(["--w-read-archive", str(archive), "--check"]) == 0
