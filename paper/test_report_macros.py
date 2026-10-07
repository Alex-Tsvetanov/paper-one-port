"""Tests of paper/report_macros.py.

    python -m pytest paper/test_report_macros.py

The committed outputs must be what the generator writes from the committed results files; every
macro a table cites must be defined by one of the macro files main.tex loads; the counts must agree
with summary.json's; and a reason or verdict the generator does not know must stop it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import report_macros as R  # noqa: E402

DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"


@pytest.fixture(scope="module")
def outputs() -> dict[Path, str]:
    return R.build()


def defined() -> set[str]:
    names: set[str] = set()
    for p in (R.MACROS, R.HARDCASE, R.DESIGN, R.OUT):
        names |= R.macro_names(p)
    return names


def test_committed_outputs_are_current(outputs):
    for p, text in outputs.items():
        assert p.exists(), p
        assert p.read_text(encoding="utf-8") == text, p


def test_every_cited_macro_is_defined(outputs):
    names = defined()
    for p, text in outputs.items():
        if p == R.OUT:
            continue
        for n in re.findall(r"\\([A-Za-z]+)", text):
            if n in ("multicolumn", "le", "times"):
                continue
            assert n in names, (p.name, n)


def test_names_are_letters_and_unique(outputs):
    text = outputs[R.OUT]
    names = re.findall(r"\\newcommand\{\\([^}]*)\}", text)
    assert all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    assert len(names) == len(set(names))
    others = R.macro_names(R.MACROS) | R.macro_names(R.HARDCASE) | R.macro_names(R.DESIGN)
    assert not set(names) & others


def test_no_dash_in_any_output(outputs):
    for p, text in outputs.items():
        assert not any(c in text for c in DASHES), p
        assert "--" not in text, p


def test_counts_agree_with_summary(outputs):
    s = R.read_json(R.SUMMARY)
    text = outputs[R.OUT]

    def value(name: str) -> int:
        m = re.search(r"\\newcommand\{\\" + name + r"\}\{([\d{},]+)\}", text)
        assert m, name
        return int(m.group(1).replace("{,}", ""))

    assert value("CountHolmCOne") + value("CountHolmCTwo") + value("CountHolmCThree") == s["families"]["C"]["m"]
    assert value("CountPassCOne") + value("CountPassCTwo") + value("CountPassCThree") == s["families"]["C"]["passed"]
    assert value("CountHolmBThree") == s["families"]["B3"]["m"]
    assert value("CountPassBThree") == s["families"]["B3"]["passed"]
    assert value("CountHolmMOne") + value("CountHolmMTwo") + value("CountHolmMThree") == s["families"]["M"]["m"]
    assert value("CountPassMOne") + value("CountPassMTwo") + value("CountPassMThree") == s["families"]["M"]["passed"]


def test_every_family_cell_is_in_its_table(outputs):
    dec = R.read_decisions()
    for fam, name in (("C", "cost.tex"), ("B3", "b3.tex"), ("M", "mechanism.tex")):
        rows = [l for l in outputs[R.TABLES / name].splitlines() if l.endswith("\\\\")]
        assert len(rows) == sum(r["family"] == fam for r in dec), name


def test_invalid_windows_agree_with_the_macros(outputs):
    """The table's windows per cell sum to analysis/macros.py's InvalidWindows count."""
    macros = R.MACROS.read_text(encoding="utf-8")
    per_cell: dict[str, int] = {}
    for line in outputs[R.TABLES / "invalid.tex"].splitlines():
        if not line.endswith("\\\\"):
            continue
        cell, _, n, _ = [x.strip() for x in line[:-2].split(" & ")]
        per_cell[cell.replace("\\_", "_")] = per_cell.get(cell.replace("\\_", "_"), 0) + int(n)
    for cell, n in per_cell.items():
        name = R.AM.word(cell) + "InvalidWindows"
        m = re.search(r"\\newcommand\{\\" + name + r"\}\{(\d+)\}", macros)
        assert m and int(m.group(1)) == n, cell


def test_an_unknown_reason_stops_the_run():
    with pytest.raises(ValueError):
        R.label("a reason no runner writes")
    assert R.label("5 connects failed") == "connects failed"
    assert R.label("errors 8.827% > 0.1%") == "error share above its bound"


def test_verdict_head():
    assert R.verdict_head("equivalent within [0.98, 1.02]") == "equivalent within [0.98, 1.02]"
    assert R.verdict_head("equivalence not shown; a measured cost (the 95% interval lies wholly outside the margin)") \
        == "equivalence not shown; a measured cost"
    assert R.verdict_head("shown: the competitor held at least 1.10 times the server's counted footprint") == "shown"
    assert R.verdict_head("not resolved at R <= 32") == "not resolved at R $\\le$ 32"
    assert "%" not in R.verdict_head("not shown; loss (the 95% interval of Q lies wholly below 1.00)")
