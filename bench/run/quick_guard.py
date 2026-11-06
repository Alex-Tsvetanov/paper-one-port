#!/usr/bin/env python3
"""The plan-hash gate of the quick benchmarks (quick-plan.md): the one explicit clearance under which a one-port
window may be timed against dedicated mode without the frozen design's pilot entry.

The frozen refusal stands (bench/run/freeze_guard.py, sessions.py, cellwin.guard): a one-port window of a cell
that pairs one-port with dedicated mode starts only with a clearance that names the pilot entry. This module adds
a second kind of clearance, QuickClearance, and cellwin.guard accepts it by its class (an opt-in of one line; a
frozen Clearance has no such class, and a QuickClearance names no pilot entry). It is made only by check_plan,
which refuses unless

- the plan file lives directly under bench/run/plans/quick/ of this checkout,
- its sha256 equals the one given (the --quick argument),
- the plan equals what quick_plans.py makes for its stem (so an edited plan with a fresh hash is refused),
- the plan's worst case is at most 600 s,
- the host of the plan is this machine's, and
- the build is a Release build without a sanitizer (check_release; rule 1 of the Papers repository).

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import quick_plans  # noqa: E402

QUICK_DIR = HERE / "plans" / "quick"
SHA_RE = re.compile(r"[0-9a-f]{64}")


class QuickRefused(Exception):
    """A quick run may not start; the message says which precondition failed."""


@dataclass
class QuickClearance:
    """Issued by check_plan only. Its record goes into every row's provenance under "freeze", and it says "quick"
    and names no pilot entry, so nothing that reads a frozen clearance can mistake it for one."""
    record: dict = field(default_factory=dict)
    quick_plan_sha256: str = ""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def this_host() -> str:
    return "W" if sys.platform == "win32" else "L"


def load_plan(plan_path: Path, sha: str) -> tuple[dict, str]:
    """The plan at `plan_path` if it is a quick plan with hash `sha`; (plan, stem)."""
    p = Path(plan_path)
    if not SHA_RE.fullmatch(str(sha)):
        raise QuickRefused(f"--quick {sha!r} is not a lowercase sha256")
    if not p.is_file():
        raise QuickRefused(f"the plan {p} is not a file")
    if p.resolve().parent != QUICK_DIR.resolve() or p.suffix != ".json":
        raise QuickRefused(f"the plan {p} is not a .json file directly under {QUICK_DIR}")
    have = sha256_file(p)
    if have != sha:
        raise QuickRefused(f"the plan's sha256 is {have}, not the {sha} given")
    stem = p.stem
    made = quick_plans.build_all().get(stem)
    if made is None:
        raise QuickRefused(f"quick_plans.py makes no plan named {stem}")
    plan = json.loads(p.read_text(encoding="utf-8"))
    if plan != made:
        raise QuickRefused(f"the plan {stem} differs from what quick_plans.py makes (regenerate and commit it, then give its new hash)")
    if float(plan["expected_worst_case_s"]) > quick_plans.CAMPAIGN_S:
        raise QuickRefused(f"the plan's worst case {plan['expected_worst_case_s']} s exceeds {quick_plans.CAMPAIGN_S:.0f} s")
    return plan, stem


def cache_value(build: Path, key: str) -> str | None:
    try:
        text = (Path(build) / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split("=", 1)[1]
    return None


def check_release(build: Path) -> dict:
    """Rule 1: anything measured is a Release build. Refuses a build that is not Release or has a sanitizer."""
    kind = cache_value(build, "CMAKE_BUILD_TYPE")
    san = cache_value(build, "ONEPORT_SANITIZER")
    if kind != "Release":
        raise QuickRefused(f"the build {build} is {kind!r}, not Release (a quick run is a timed run)")
    if san:
        raise QuickRefused(f"the build {build} has ONEPORT_SANITIZER={san!r}")
    return {"build_type": kind, "sanitizer": san or ""}


def check_plan(plan_path: Path, sha: str, build: Path, host: str | None = None) -> tuple[dict, str, QuickClearance]:
    """Every precondition of a quick run; raises QuickRefused at the first that fails."""
    plan, stem = load_plan(plan_path, sha)
    here = host or this_host()
    if plan["host"] != here:
        raise QuickRefused(f"the plan {stem} is for host {plan['host']}, this machine is {here}")
    rel = check_release(build)
    record = {"quick": True, "plan": stem, "plan_sha256": sha, "host": plan["host"], "kind": plan["kind"], "build": rel,
              "pilot": None, "note": "a quick benchmark (quick-plan.md): not a frozen run, no pilot entry, no freeze guard"}
    return plan, stem, QuickClearance(record, sha)
