#!/usr/bin/env python3
"""The preconditions of a frozen run (hypotheses.md section 8), checked before any window starts.

Section 8 orders the steps: the seeds and ANALYSIS_COMMIT (step 2), CODE_FREEZE (step 3), the A/A
pilot on the frozen binary in dedicated mode only (step 4), the pilot entry, "committed before any
one-port window of the frozen code" (step 6), then rule E's choices, M2's rates, K_BASE and every
confirmatory, secondary and hard-case run (step 7). The revision log is where each step is
recorded, so a frozen runner reads it. None of these entries exists yet (M7c), so what a runner
looks for in them is fixed here and stated in design/status.md:
- CODE_FREEZE: a line of the revision log that holds the word CODE_FREEZE and the commit's full
  40-character hash. The commit must be an ancestor of HEAD, and `git diff CODE_FREEZE HEAD --
  bench tests CMakeLists.txt` must show nothing, nor may the working tree change those paths (the
  M7 checklist's item 8: the gate does not see the Python half of the suite).
- The seeds entry: the sha256 of the seeds file (the 14 seeds of 4.7, as analysis/ reads them) on
  a revision-log line that holds the word "seed".
- The pilot entry: the sha256 of pilot.py's output on a revision-log line that holds the word
  "pilot", added by a commit that descends from CODE_FREEZE; the output complete (both hosts), not
  synthetic, at N_SIM = 1,000.
- Rule E's file and M2's rates: each file's sha256 on a revision-log line that holds "rule E" or
  "M2_RATE", added by a commit that descends from the pilot entry's.
- hypotheses.md committed and unchanged in the working tree, so every line read is committed.
- The binaries the runner will start: each one's sha256 in a gate of bench/check_records.py that
  passed, is not a dry run and is citable (bench/check_rows.py's rule, applied before the first
  window rather than after the last).
- The entries whose choices a runner applies: the heading of each, as a revision-log heading line
  (`### ` and the title). The section 10, B3 and M runners apply the entry "M7c's open items,
  before the code freeze" (2026-10-04: the mixed cell's silent ports, B3's other-mode cells in
  relay, the TLS variants, an M2 cell without a rate), so a frozen run of theirs refuses to start
  if the log does not hold it.
A run that passes gets a Clearance, whose record goes into every row's provenance. The session
engine (bench/run/sessions.py) starts the one-port arm of a cell that pairs one-port with dedicated
mode only with a clearance that names the pilot entry; development mode never has one.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))

import check_rows  # noqa: E402  (bench/check_rows.py)

N_SIM = 1_000  # 4.6 step 2
# The title of the revision-log entry whose choices the section 10, B3 and M runners apply.
M7C_ITEMS = "M7c's open items, before the code freeze"
FROZEN_PATHS = ("bench", "tests", "CMakeLists.txt")
HEX40 = re.compile(r"\b[0-9a-f]{40}\b")


class FreezeRefused(Exception):
    """A frozen run may not start; the message says which precondition failed."""


@dataclass
class Clearance:
    """Issued by check() only; its record goes into every row of the run."""
    record: dict = field(default_factory=dict)

    @property
    def pilot_entry(self) -> bool:
        return bool(self.record.get("pilot"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise FreezeRefused(f"git {' '.join(args)}: {p.stderr.strip()[-300:]}")
    return p.stdout


def is_ancestor(repo: Path, a: str, b: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0


def revision_log(text: str) -> str:
    at = text.find("\n## Revision log")
    if at < 0:
        raise FreezeRefused("hypotheses.md has no revision log")
    return text[at:]


def lines_with(log: str, word: str, token: str) -> list[str]:
    w = word.lower()
    return [ln for ln in log.splitlines() if token in ln and w in ln.lower()]


def adding_commit(repo: Path, token: str) -> str:
    """The oldest commit that added `token` to hypotheses.md."""
    out = git(repo, "log", "--format=%H", "-S", token, "--", "hypotheses.md").split()
    if not out:
        raise FreezeRefused(f"no commit added {token[:16]} to hypotheses.md")
    return out[-1]


def check_code_freeze(repo: Path, log: str, code_freeze: str) -> dict:
    if not HEX40.fullmatch(code_freeze or ""):
        raise FreezeRefused(f"CODE_FREEZE {code_freeze!r} is not a full 40-character commit hash")
    if not lines_with(log, "CODE_FREEZE", code_freeze):
        raise FreezeRefused(f"the revision log names no CODE_FREEZE {code_freeze[:12]} (section 8 step 3)")
    head = git(repo, "rev-parse", "HEAD").strip()
    if not is_ancestor(repo, code_freeze, head):
        raise FreezeRefused(f"CODE_FREEZE {code_freeze[:12]} is not an ancestor of HEAD {head[:12]}")
    diff = git(repo, "diff", "--name-only", code_freeze, head, "--", *FROZEN_PATHS).split()
    if diff:
        raise FreezeRefused(f"{len(diff)} files under bench, tests or CMakeLists.txt changed since CODE_FREEZE: {diff[:5]}")
    dirty = git(repo, "status", "--porcelain", "--", *FROZEN_PATHS).splitlines()
    if dirty:
        raise FreezeRefused(f"the working tree changes frozen paths: {dirty[:5]}")
    return {"code_freeze": code_freeze, "head": head}


def check_file_entry(repo: Path, log: str, path: Path, word: str, after: str, what: str) -> dict:
    digest = sha256_file(path)
    if not lines_with(log, word, digest):
        raise FreezeRefused(f"the revision log names no {what} with sha256 {digest[:16]} (a line with '{word}' and the file's sha256)")
    commit = adding_commit(repo, digest)
    if not is_ancestor(repo, after, commit) or commit == after:
        raise FreezeRefused(f"{what} ({digest[:16]}) was logged in {commit[:12]}, which does not come after {after[:12]}")
    return {"file": str(path), "sha256": digest, "logged_in": commit}


def check_pilot_file(pilot: Path) -> dict:
    p = json.loads(Path(pilot).read_text(encoding="utf-8"))
    if p.get("synthetic"):
        raise FreezeRefused("the pilot entry's output is synthetic")
    if not p.get("complete"):
        raise FreezeRefused(f"the pilot entry's output is incomplete: {p.get('incomplete')} (it needs both hosts, 8 step 6)")
    if p.get("n_sim") != N_SIM:
        raise FreezeRefused(f"the pilot ran N_SIM = {p.get('n_sim')}, not {N_SIM}")
    return p


def check_binaries(binaries: dict[str, str], gates: list[Path]) -> dict:
    """bench/check_rows.py's rule on the binaries a run will start, before its first window."""
    covered, left_out = check_rows.load_gates([Path(g) for g in gates])
    refused = check_rows.check([{"provenance": {"binaries": binaries}}], covered)
    if refused:
        raise FreezeRefused(f"the build is not the gated one: {refused[0]['why']} (gates left out: {left_out})")
    return {"gates": sorted(Path(g).name for g in gates), "binaries": binaries}


def check_entries(log: str, titles: tuple[str, ...]) -> list[str]:
    heads = [ln for ln in log.splitlines() if ln.startswith("### ")]
    for t in titles:
        if not any(t in h for h in heads):
            raise FreezeRefused(f"the revision log has no entry \"{t}\", whose choices this runner applies")
    return list(titles)


def check(*, repo: Path = REPO, code_freeze: str, seeds: Path, gates: list[Path], binaries: dict[str, str],
          pilot: Path | None = None, rule_e: Path | None = None, m2_rates: Path | None = None,
          need_pilot: bool = True, entries: tuple[str, ...] = ()) -> Clearance:
    """Every precondition of a frozen run; raises FreezeRefused at the first that fails."""
    hyp = repo / "hypotheses.md"
    if git(repo, "status", "--porcelain", "--", "hypotheses.md").strip():
        raise FreezeRefused("hypotheses.md has changes that are not committed")
    log = revision_log(git(repo, "show", "HEAD:hypotheses.md"))
    if hyp.read_text(encoding="utf-8").replace("\r\n", "\n") != git(repo, "show", "HEAD:hypotheses.md").replace("\r\n", "\n"):
        raise FreezeRefused("hypotheses.md differs from HEAD's")
    rec: dict = {"freeze": check_code_freeze(repo, log, code_freeze)}
    if entries:
        rec["entries"] = check_entries(log, entries)
    s = sha256_file(seeds)
    if not lines_with(log, "seed", s):
        raise FreezeRefused(f"the revision log names no seeds file with sha256 {s[:16]} (section 8 step 2)")
    rec["seeds"] = {"file": str(seeds), "sha256": s}
    if need_pilot:
        if pilot is None:
            raise FreezeRefused("this run comes after the pilot entry (section 8 step 7): give the pilot entry's output")
        check_pilot_file(pilot)
        rec["pilot"] = check_file_entry(repo, log, pilot, "pilot", code_freeze, "the pilot entry")
        if rule_e is not None:
            rec["rule_e"] = check_file_entry(repo, log, rule_e, "rule E", rec["pilot"]["logged_in"], "rule E's choices")
        if m2_rates is not None:
            rec["m2_rates"] = check_file_entry(repo, log, m2_rates, "M2_RATE", rec["pilot"]["logged_in"], "M2's rates")
    rec["gate"] = check_binaries(binaries, gates)
    return Clearance(rec)
