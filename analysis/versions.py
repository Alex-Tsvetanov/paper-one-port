"""The pinned library versions (hypotheses.md 4.6 step 3: "The code is the analysis code at
ANALYSIS_COMMIT, which pins its library versions"), and the guard that keeps synthetic outputs
out of results/.

The pins are those of design/proposal.md, Appendix A (Python 3.14.5, numpy 2.5.0), the versions
on which appendix_a_r_rule.py reproduced it; analysis/requirements.txt names the same. The random
streams (numpy's PCG64 through default_rng, Generator.integers and Generator.normal) and the
medians are numpy's, so the same inputs and seeds give the same bytes only on the same numpy. The
command-line tools refuse to run on another numpy or another Python minor version; the library
functions and the tests do not check, so the tests also run where SciPy's cross-check needs
another numpy.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

import numpy as np

PINNED_NUMPY = "2.5.0"
PINNED_PYTHON = (3, 14)
PINNED_PYTHON_SEEN = "3.14.5"

HERE = Path(__file__).resolve().parent
RESULTS = (HERE.parent / "results").resolve()


def analysis_commit() -> dict:
    """The commit the analysis code ran at, and whether analysis/ differed from it (the pilot entry
    names ANALYSIS_COMMIT, section 9.2)."""
    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(HERE), *a], capture_output=True, text=True)
    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--", ".")
    if head.returncode != 0 or dirty.returncode != 0:
        return {"analysis_commit": None, "analysis_dirty": None}
    return {"analysis_commit": head.stdout.strip(), "analysis_dirty": bool(dirty.stdout.strip())}


def current() -> dict:
    return {"python": platform.python_version(), "numpy": np.__version__, **analysis_commit()}


def require() -> None:
    if np.__version__ != PINNED_NUMPY or sys.version_info[:2] != PINNED_PYTHON:
        raise SystemExit(f"the analysis is pinned to numpy {PINNED_NUMPY} on Python {PINNED_PYTHON[0]}.{PINNED_PYTHON[1]} "
                         f"(analysis/requirements.txt); this is numpy {np.__version__} on Python {platform.python_version()}")


def under_results(path: Path) -> bool:
    p = Path(path).resolve()
    return p == RESULTS or RESULTS in p.parents


def refuse_results_path(path: Path) -> None:
    """Synthetic data is never written under results/ (the paper's numbers come only from
    results/macros.tex, section 13)."""
    if under_results(path):
        raise SystemExit(f"{path}: synthetic data is never written under results/")
