"""Tests of paper/design_macros.py.

    python -m pytest paper/test_design_macros.py

The design macros and analysis/macros.py's macros are loaded into one document, so no name may
be one that analysis/macros.py can emit. The committed results/design-macros.tex must be what
the generator writes from the files as they are.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "analysis"))

import design_macros as D  # noqa: E402


def items():
    return D.read_specs()


def macros_py_names() -> tuple[set[str], tuple[str, ...]]:
    """The names analysis/macros.py writes literally, and the prefixes of the names it builds
    (the family prefixes, the cell words, the seeds)."""
    src = (HERE.parent / "analysis" / "macros.py").read_text(encoding="utf-8")
    fixed = set(re.findall(r'mc\.add\("([A-Za-z]+)"', src))
    for fam in ("Cost", "BThree", "M"):
        for suffix in re.findall(r'mc\.add\(f"\{prefix\}([A-Za-z]+)"', src):
            fixed.add(fam + suffix)
    import macros as MC  # analysis/macros.py, read only
    words = tuple(MC.WORDS[k] for k in ("C1", "C2", "C3", "B3", "M1", "M2", "M3", "S"))
    host_cells = tuple(h + b for h in ("L", "W") for b in ("Epoll", "Iouring", "Iocp"))
    return fixed, words + host_cells + ("Seed",)


def test_every_pattern_matches_once_and_names_are_letters():
    got = items()
    names = [n for n, _, _ in got]
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    text = D.render(got)
    assert text.count("\\newcommand") == len(got)


def test_no_name_analysis_macros_can_emit():
    fixed, prefixes = macros_py_names()
    for name, _, _ in items():
        assert name not in fixed, name
        assert not name.startswith(prefixes), name


def test_no_dash_in_any_value():
    for name, value, note in items():
        assert not any(c in value + note for c in D.DASHES), name
        assert "--" not in value + note, name


def test_frozen_values_agree_with_pins_and_code():
    values = D.values_of(items())
    assert D.pin_disagreements(values) == []
    assert D.code_disagreements(values) == []


def test_a_missing_or_repeated_value_stops_the_run():
    spec = D.S("Probe", D.HYP, r"(Holm)")
    try:
        D.read_specs([spec])
    except D.SourceError:
        pass
    else:
        raise AssertionError("a pattern that matches more than once was accepted")
    spec = D.S("Probe", D.HYP, r"no such sentence in the frozen text")
    try:
        D.read_specs([spec])
    except D.SourceError:
        pass
    else:
        raise AssertionError("a pattern that matches nothing was accepted")


def test_the_three_analysis_commits():
    """SizingCommit sized R_C, AnalysisRunCommit ran the confirmatory analysis, AnalysisCommit wrote
    the macros. The run's commit is the one the revision log names by its short form, and its
    analysis/ tree is the sizing commit's (git, where the repository's history is at hand)."""
    values = D.values_of(items())
    assert D.run_commit_disagreements(values) == []
    assert len({values["SizingCommit"], values["AnalysisRunCommit"], values["AnalysisCommit"]}) == 3
    import shutil
    import subprocess
    if shutil.which("git") is None:
        return
    def tree(commit: str) -> str | None:
        r = subprocess.run(["git", "rev-parse", f"{commit}:analysis"], cwd=HERE.parent, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    sizing, run = tree(values["SizingCommit"]), tree(values["AnalysisRunCommit"])
    if sizing is None or run is None:
        return  # a shallow clone without these commits
    assert sizing == run


def test_a_disagreeing_run_commit_is_reported():
    values = D.values_of(items())
    values = {**values, "AnalysisRunShort": "0000000"}
    assert D.run_commit_disagreements(values) != []


def test_committed_file_is_current():
    committed = (HERE.parent / "results" / "design-macros.tex").read_text(encoding="utf-8")
    assert committed == D.render(items())
