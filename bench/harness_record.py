#!/usr/bin/env python3
"""Write the sanitizer record of one in-process library's harness from a work directory.

    harness_record.py --work DIR --harness cmux|hyper-util --sanitizer asan|tsan --record FILE --repo URL
                      --commit SHA --host UNAME --host-tag L --build-exit N --check-exit N --seconds N
                      --pins bench/cmake/pins.cmake [--logs-archive F --logs-sha256 H] [--dry-run]

hypotheses.md, section 11: "The Go and Rust harnesses get ASan with UBSan and TSan records; only
their MSan gap is declared." A harness is built outside CMake (bench/competitors/build_harnesses.sh),
so its inputs are named in bench/competitors/harness_inputs.py, whose hash build_harnesses.sh
writes into its build.json; the record's target is named as bench/coverage.json names it
(harness_cmux, harness_hyper_util). The work directory holds build.json and build.log (the
flavour's build) and check/ (the harness's probe and route checks under the sanitizer, with every
log the harness wrote). The record names the harness's inputs hash, its toolchain (build.json's
"tools": go and clang, or rustc and cargo), the flavour, the environment the flavour ran with
(hyper-util's TSan: TSAN_OPTIONS=suppressions=<its tsan.supp>, the coordinator's decision of
2026-10-03), and the sha256 of pins.cmake. Green means the build and the checks exited 0, build.json
holds the harness in this flavour, no log of the work directory holds a sanitizer report (the
lab's shared pattern, bench/oneport_record.py's REPORT, or Go's race report, "WARNING: DATA RACE",
which go build -race prints instead of ThreadSanitizer's own first line), and every run of the
harness in the checks ended through its SIGTERM handler.

The exit checks (M7). The checks stop each harness with SIGTERM (competitors.py, stop). Since M7
both harnesses handle it and exit normally (cmux/main.go, hyper-util's src/main.rs), printing
"<name>: stopped by SIGTERM" on their standard output, so LeakSanitizer's check at exit and the
race detector's exit status run, and their reports land in the run's stderr.log, which the scan
reads. Before M7 the default action ended each harness before them. A run whose stdout.log says
"<name>: listening" and not "<name>: stopped by SIGTERM" ended some other way (killed after the
grace period, or a crash), so its exit checks did not run: the record is not green.
--dry-run marks the record, as oneport_record.py does.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from gate_lib import file_sha256
from oneport_record import REPORT

GO_RACE = re.compile(r"WARNING: DATA RACE|Found \d+ data race")
FLAVOURS = {"asan": "asan", "tsan": "tsan"}  # the record's sanitizer -> build_harnesses.sh's flavour
HARNESSES = ("cmux", "hyper-util")  # section 11: the Go and Rust harnesses; the Java ones have no record


def target_name(harness: str) -> str:
    """The target's name as bench/coverage.json gives it."""
    return "harness_" + harness.replace("-", "_")


def toolchain(tools: str) -> str:
    """build.json's tools text on one line, white space collapsed: the record's compiler."""
    return " ".join(tools.split())


def blocks(text: str) -> list[str]:
    lines = text.splitlines()
    return ["\n".join(lines[i:i + 30]) for i, line in enumerate(lines) if REPORT.search(line) or GO_RACE.search(line)]


def runs_without_exit_check(work: Path, harness: str) -> tuple[int, list[str]]:
    """The harness's runs in the checks (each started process's stdout.log under check/ that says
    "<harness>: listening"), and those that did not end through the SIGTERM handler."""
    started = f"{harness}: listening"
    stopped = f"{harness}: stopped by SIGTERM"
    runs, missing = 0, []
    for f in sorted((work / "check").rglob("stdout.log")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if started in text:
            runs += 1
            if stopped not in text:
                missing.append(str(f.relative_to(work)))
    return runs, missing


def scan(work: Path) -> list[str]:
    """Reports in the build's log and in every log of the checks (check/: the probe's and the route
    checks' output, and each harness process's stdout.log and stderr.log); the build trees are not
    read."""
    files = [work / "build.log"] + sorted(p for p in (work / "check").rglob("*")
                                         if p.is_file() and p.suffix in (".log", ".err", ".jsonl", ".txt"))
    reports = []
    for f in files:
        if f.is_file():
            reports += [f"{f.relative_to(work)}:\n{b}" for b in blocks(f.read_text(encoding="utf-8", errors="replace"))]
    return reports


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("work", "record", "repo", "commit", "host"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--harness", required=True, choices=HARNESSES)
    ap.add_argument("--sanitizer", required=True, choices=sorted(FLAVOURS))
    ap.add_argument("--host-tag", required=True, choices=["L"], help="the harnesses run on L only")
    for k in ("build-exit", "check-exit", "seconds"):
        ap.add_argument(f"--{k}", type=int, required=True)
    ap.add_argument("--pins", required=True, help="the pins.cmake the build used")
    ap.add_argument("--logs-archive", default="")
    ap.add_argument("--logs-sha256", default="")
    ap.add_argument("--dry-run", action="store_true", help="a test of the driver: the record is marked and never citable")
    a = ap.parse_args()
    work = Path(a.work)
    target = target_name(a.harness)
    problems: list[str] = []
    entry: dict = {}
    bj = work / "build.json"
    if bj.exists():
        entry = json.loads(bj.read_text(encoding="utf-8")).get(a.harness) or {}
    if not entry:
        problems.append(f"build.json holds no {a.harness}")
    elif entry.get("flavour") != FLAVOURS[a.sanitizer]:
        problems.append(f"build.json's {a.harness} is flavour {entry.get('flavour')}, not {FLAVOURS[a.sanitizer]}")
    reports = scan(work)
    runs, unchecked = runs_without_exit_check(work, a.harness)
    if runs == 0:
        problems.append(f"no run of {a.harness} in the checks (no stdout.log says '{a.harness}: listening')")
    if unchecked:
        problems.append(f"{len(unchecked)} of {runs} runs did not end through the SIGTERM handler, so their exit checks did not run: "
                        + ", ".join(unchecked[:5]))
    green = a.build_exit == 0 and a.check_exit == 0 and not problems and not reports and "inputs_hash" in entry
    rec = {"repo": a.repo, "commit": a.commit, "repo_head": a.commit,
           "date": datetime.now().astimezone().isoformat(timespec="seconds"), "host": a.host, "host_tag": a.host_tag,
           "green": green, "tool": "harness", "harness": a.harness, "sanitizer": a.sanitizer,
           "flavour": entry.get("flavour"), "compiler": toolchain(entry.get("tools", "")), "config": {},
           "inputs_hash": {target: entry["inputs_hash"]} if "inputs_hash" in entry else {},
           "inputs_files": {target: len(entry.get("inputs", []))}, "inputs": entry.get("inputs", []),
           "run_env": entry.get("run_env", {}), "build_command": entry.get("command"),
           "output_sha256": entry.get("output_sha256"), "third_party": {"fetched": {}},
           "pins_sha256": file_sha256(Path(a.pins)), "pins_file": "bench/cmake/pins.cmake",
           "build_exit": a.build_exit, "check_exit": a.check_exit, "seconds": a.seconds, "problems": problems,
           "sanitizer_reports": len(reports), "report_blocks": reports[:20],
           "harness_runs": runs, "harness_runs_without_exit_check": len(unchecked),
           "logs_archive": a.logs_archive, "logs_archive_sha256": a.logs_sha256, "dry_run": a.dry_run,
           "note": ("The harness built in its sanitizer flavour (bench/competitors/build_harnesses.sh), then its probe in "
                    "its cases kinds and its route checks at both timer settings (bench/competitors/probe.py, "
                    "cases_check.py), as M4b-2's development checks ran (hypotheses.md, section 11). Each run ended "
                    "through the harness's SIGTERM handler, a normal exit, so the sanitizers' exit checks ran "
                    "(LeakSanitizer's at exit; the race detector's exit status).")
                   + (" A dry run of the records driver: never citable, refused by the gate." if a.dry_run else "")}
    Path(a.record).parent.mkdir(parents=True, exist_ok=True)
    Path(a.record).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"record": a.record, "green": green, "harness": a.harness, "sanitizer": a.sanitizer,
                      "reports": len(reports), "problems": problems, "dry_run": a.dry_run}))
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
