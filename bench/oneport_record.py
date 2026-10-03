#!/usr/bin/env python3
"""Write the sanitizer record of a oneport build from a work directory.

    oneport_record.py --work DIR --record FILE --repo URL --commit SHA --repo-head SHA --sanitizer asan|tsan|msan
                      --cmake-args ARGS --options OPTS --host UNAME --host-tag L|W --build-exit N --ctest-exit N
                      --seconds N --pins bench/cmake/pins.cmake [--logs-archive F --logs-sha256 H] [--dry-run]

Copied from paper-typed-routing t1/h6_record.py and bench/regexmatcher_record.py at commit
7c1e248, same author, with the paths and names of this repository. In oneport the whole suite of
hypotheses.md, section 11, runs under CTest, so a record has two steps, the build and the suite.

The work directory holds build.log (configure and build), ctest.log (ctest -V) and
build.inputs.json (lab/bin/inputs_hash.py in project mode, build name oneport). The record names
the repo, the commit, the host, the compiler, the sanitizer and its runtime options, the CMake
arguments, what each target compiled (inputs_hash, the configuration, third_party with each
fetched archive's URL and hash as used), and the sha256 of the pins.cmake the build used
(pins_sha256, which the gate matches with a measured build's, bench/gate_lib.py). Green means the
build succeeded, CTest ran and every test passed, the inputs were hashed, and no log or standard
error file of the work directory holds a sanitizer report; reports are copied into the record.

--dry-run marks the record ("dry_run": true): a test of the records driver, never citable. Records
match builds by inputs hash, not by commit, so a record made before the code freeze would gate the
freeze's build wherever a target's inputs did not change; the gate refuses a dry-run record found
among the records (bench/gate_lib.py), and the drivers never write one into lab/sanitizer-records.
The build inputs come from bench/build_inputs.py (the targets, configuration keys and root label
the gate hashes a measured build with).
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from gate_lib import SANITIZERS_BY_HOST, file_sha256

# The first line of every sanitizer report and every SUMMARY line; the same text as the Papers
# repo's lab/bin/sanitize.sh, checked by its lab/bin/test_report_pattern.sh.
REPORT = re.compile(r"ERROR: (Address|Memory|Leak|Thread)Sanitizer|WARNING: (Memory|Thread)Sanitizer|"
                    r"SUMMARY: [A-Za-z]+Sanitizer|runtime error:")
COMPILER_ID = re.compile(r"^-- The CXX compiler identification is (.+?)\s*$", re.MULTILINE)
# CTest's summary line: "P% tests passed, F tests failed out of T"; CTest 4 writes
# "100% tests passed out of T" when none failed (found on L, CTest 4.4.3, 2026-09-30).
CTEST_LINE = re.compile(r"(\d+)% tests passed(?:, (\d+) tests failed)? out of (\d+)")
BUILD = "oneport"


def ctest_summary(text: str) -> tuple[int, int] | None:
    """(total, failed) from the last CTest summary line of TEXT (failed 0 when the line has no
    failed clause), or None if there is none."""
    found = CTEST_LINE.findall(text)
    if not found:
        return None
    _, failed, total = found[-1]
    return int(total), int(failed) if failed else 0


def blocks(text: str) -> list[str]:
    lines = text.splitlines()
    return ["\n".join(lines[i:i + 30]) for i, line in enumerate(lines) if REPORT.search(line)]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("work", "record", "repo", "commit", "repo-head", "sanitizer", "cmake-args", "options", "host"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--host-tag", required=True, choices=sorted(SANITIZERS_BY_HOST), help="the host part of the record name")
    for k in ("build-exit", "ctest-exit", "seconds"):
        ap.add_argument(f"--{k}", type=int, required=True)
    ap.add_argument("--pins", required=True, help="the pins.cmake the build used")
    ap.add_argument("--logs-archive", default="", help="the logs packed, under ~/lab/records-logs")
    ap.add_argument("--logs-sha256", default="", help="the sha256 of --logs-archive")
    ap.add_argument("--dry-run", action="store_true", help="a test of the driver: the record is marked and never citable")
    a = ap.parse_args()
    work = Path(a.work)
    build_log = read(work / "build.log")
    m = COMPILER_ID.search(build_log)
    compiler = m.group(1) if m else "unknown"
    inputs: dict = {"inputs_error": "no build.inputs.json (the build failed?)"}
    if (work / "build.inputs.json").exists():
        b = json.loads(read(work / "build.inputs.json"))["builds"][BUILD]
        inputs = {"inputs_hash": {t: v["inputs_hash"] for t, v in b["targets"].items()},
                  "inputs_files": {t: v["files"] for t, v in b["targets"].items()},
                  "config": next((v for k, v in b.items() if k == "config" or k.endswith("_config")), None),
                  "third_party": b.get("third_party")}

    presets = [{"preset": "build", "status": "green" if a.build_exit == 0 else "red", "detail": f"exit {a.build_exit}",
                "compiler": compiler}]
    total, failed = ctest_summary(read(work / "ctest.log")) or (0, -1)
    presets.append({"preset": "ctest", "status": "green" if a.ctest_exit == 0 and total > 0 and failed == 0 else "red",
                    "detail": f"exit {a.ctest_exit}, {total} tests, {failed} failed"})
    reports = []
    for f in [work / "build.log", work / "ctest.log", *sorted(work.rglob("*.err"))]:
        reports += [f"{f.relative_to(work)}:\n{b}" for b in blocks(read(f))]
    green = all(p["status"] == "green" for p in presets) and not reports and "inputs_hash" in inputs
    rec = {"repo": a.repo, "commit": a.commit, "repo_head": a.repo_head,
           "date": datetime.now().astimezone().isoformat(timespec="seconds"), "host": a.host, "host_tag": a.host_tag,
           "green": green, "compiler": compiler, **inputs, "pins_sha256": file_sha256(Path(a.pins)),
           "pins_file": "bench/cmake/pins.cmake", "presets": presets, "tool": BUILD, "sanitizer": a.sanitizer,
           "cmake_args": a.cmake_args, "sanitizer_options": a.options, "build_exit": a.build_exit,
           "ctest_exit": a.ctest_exit, "tests_total": total, "tests_failed": failed, "seconds": a.seconds,
           "sanitizer_reports": len(reports), "report_blocks": reports[:20],
           "logs_archive": a.logs_archive, "logs_archive_sha256": a.logs_sha256, "dry_run": a.dry_run,
           "note": "oneport's CMake project built under the sanitizer, then its whole CTest suite (hypotheses.md, section 11)."
                   + (" A dry run of the records driver: never citable, refused by the gate." if a.dry_run else "")}
    Path(a.record).parent.mkdir(parents=True, exist_ok=True)
    Path(a.record).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"record": a.record, "green": green, "sanitizer": a.sanitizer, "reports": len(reports), "dry_run": a.dry_run}))
    for p in presets:
        if p["status"] != "green":
            print(f"  {p['preset']}: {p['status']} ({p['detail']})")
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
