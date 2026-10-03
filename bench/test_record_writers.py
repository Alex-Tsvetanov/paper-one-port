#!/usr/bin/env python3
"""Tests of the record writer that reads a CTest summary: bench/oneport_record.py.

    python bench/test_record_writers.py      (exit 0 when every check passes)

Copied from paper-typed-routing bench/test_record_writers.py at commit 7c1e248, same author, with
the paths and names of this repository. CTest writes its summary as "P% tests passed, F tests
failed out of T" up to version 3, and from version 4 on as "100% tests passed out of T" when no
test failed (CTest 4.4.3 on L, 2026-09-30). Checks:
1. the parser reads both forms (failed 0 when the clause is absent) and a summary with failures;
2. the writer run end to end on synthetic logs makes a green record from either passing form, and
   a red one from a summary with a failed test (even with CTest's exit code 0), from a log without
   a summary, from a failed build, from a log or error file with a sanitizer report, and from a
   work directory without build.inputs.json;
3. the record carries the sha256 of the pins.cmake it was given (the gate's pin rule), its inputs
   hashes and configuration, and its host tag;
4. the writer's report pattern is, text for text, the shared one of the Papers repo's
   lab/bin/test_report_pattern.sh, which does not list this writer: the copy below is checked
   here, and against that script too where the Papers repo is checked out around this one;
5. --dry-run marks the record (the gate refuses it, bench/test_gates.py);
6. bench/harness_record.py, the harnesses' writer, on synthetic work directories: green from a
   clean build and checks, with the target named as coverage.json names it, the inputs hash and
   the run environment from build.json and the toolchain on one line; red from a sanitizer report
   or Go's race report in a harness's log, from a build.json of another flavour or without the
   harness, and from a failed check; since M7 also red from a run of the harness that did not end
   through its SIGTERM handler (so its exit checks did not run), from checks that ran no harness,
   and from LeakSanitizer's report at a clean exit.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gate_lib import file_sha256  # noqa: E402

WRITER = HERE / "oneport_record.py"
HARNESS_WRITER = HERE / "harness_record.py"
PINS = HERE / "cmake" / "pins.cmake"
SHARED_PATTERN = ("ERROR: (Address|Memory|Leak|Thread)Sanitizer|WARNING: (Memory|Thread)Sanitizer|"
                  "SUMMARY: [A-Za-z]+Sanitizer|runtime error:")
PATTERN_TEST = HERE.parent.parent.parent / "lab" / "bin" / "test_report_pattern.sh"
OLD = "100% tests passed, 0 tests failed out of 87"
NEW = "100% tests passed out of 87"
FAILED = "95% tests passed, 4 tests failed out of 87"
CONFIG = {"CMAKE_BUILD_TYPE": "Release"}
failures = 0
runs = iter(range(1000))
printed: list[str] = []


def expect(name: str, ok: bool) -> None:
    """Prints one result line. A record scans the CTest log (ctest -V) for the report pattern, so
    no line printed here may match it; main() checks that."""
    global failures
    line = ("ok: " if ok else "FAIL: ") + name
    printed.append(line)
    print(line)
    failures += not ok


def module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ctest_log(summary: str) -> str:
    return ("Test project /x/build\n  1/87 Test  #1: a ....   Passed    0.01 sec\n\n" + summary +
            "\n\nTotal Test time (real) =  28.22 sec\n")


def parsers() -> None:
    m = module(WRITER)
    expect("CTest 3 form, none failed", m.ctest_summary(ctest_log(OLD)) == (87, 0))
    expect("CTest 4 form, none failed", m.ctest_summary(ctest_log(NEW)) == (87, 0))
    expect("a summary with failures", m.ctest_summary(ctest_log(FAILED)) == (87, 4))
    expect("no summary", m.ctest_summary("no tests were found\n") is None)
    expect("the last summary counts", m.ctest_summary(ctest_log(NEW) + ctest_log(FAILED)) == (87, 4))


def pattern() -> None:
    m = module(WRITER)
    expect("the writer's REPORT is the shared pattern", m.REPORT.pattern == SHARED_PATTERN)
    if PATTERN_TEST.exists():
        found = re.search(r"^want='(.*)'$", PATTERN_TEST.read_text(encoding="utf-8").replace("\r\n", "\n"), re.MULTILINE)
        expect("the shared pattern equals lab/bin/test_report_pattern.sh's",
               found is not None and found.group(1) == SHARED_PATTERN)
    else:
        print(f"skip: {PATTERN_TEST} (the Papers repo is not checked out around this one)")
    samples = ("==4711==WARNING: MemorySanitizer: use-of-uninitialized-value",
               "==4711==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000011",
               "WARNING: ThreadSanitizer: data race (pid=4711)",
               "src/a.cpp:12:5: runtime error: signed integer overflow")
    for i, line in enumerate(samples, 1):
        expect(f"report sample {i} of {len(samples)} matches", m.REPORT.search(line) is not None)
    expect("a clean line does not match", m.REPORT.search("100% tests passed out of 87") is None)


def write_record(tmp: Path, summary: str, ctest_exit: int = 0, build_exit: int = 0, inputs: bool = True,
                 extra: dict | None = None, dry_run: bool = False) -> dict:
    work = tmp / f"w-{next(runs)}"
    work.mkdir(parents=True)
    (work / "build.log").write_text("-- The CXX compiler identification is Clang 22.1.8\n", encoding="utf-8")
    (work / "ctest.log").write_text(ctest_log(summary) if summary else "no summary\n", encoding="utf-8")
    if inputs:
        (work / "build.inputs.json").write_text(json.dumps({"builds": {"oneport": {"targets": {
            "oneport": {"inputs_hash": "s", "files": 3}, "oneport_tests": {"inputs_hash": "t", "files": 2}},
            "config": CONFIG, "third_party": {"fetched": {}}}}}), encoding="utf-8")
    for name, text in (extra or {}).items():
        (work / name).write_text(text, encoding="utf-8")
    rec = work / "record.json"
    cmd = [sys.executable, str(WRITER), "--work", str(work), "--record", str(rec), "--repo", "r", "--commit", "c",
           "--repo-head", "c", "--sanitizer", "asan", "--cmake-args", "a", "--options", "o", "--host", "h",
           "--host-tag", "L", "--build-exit", str(build_exit), "--ctest-exit", str(ctest_exit), "--seconds", "1",
           "--pins", str(PINS)] + (["--dry-run"] if dry_run else [])
    subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(rec.read_text(encoding="utf-8"))


FRONT = "check/cases/raw/hyper-util-cases-matched/front"
LISTENING = "hyper-util: listening 24000 (backlog tokio's default)\n"
STOPPED = "hyper-util: stopped by SIGTERM\n"


def write_harness_record(tmp: Path, flavour: str = "tsan", sanitizer: str = "tsan", check_exit: int = 0,
                         logs: dict | None = None, harness_in_build: bool = True, dry_run: bool = False,
                         stdout: str | None = LISTENING + STOPPED) -> dict:
    work = tmp / f"h-{next(runs)}"
    (work / FRONT).mkdir(parents=True)
    (work / "build.log").write_text("build_harnesses: hyper-util (tsan) built\n", encoding="utf-8")
    (work / "check" / "probe-cases.log").write_text("hyper-util cases: ok\n", encoding="utf-8")
    if stdout is not None:  # the harness's run, as competitors.start writes it
        (work / FRONT / "stdout.log").write_text(stdout, encoding="utf-8")
    entry = {"flavour": flavour, "inputs_hash": "hh", "inputs": ["a\tx", "b\ty"], "tools": "rustc 1.98.1 (x)\nbinary: rustc\ncargo 1.98.1",
             "run_env": {"TSAN_OPTIONS": "suppressions=/x/tsan.supp"}, "command": "cargo build", "output_sha256": "o1"}
    (work / "build.json").write_text(json.dumps({"hyper-util": entry} if harness_in_build else {}), encoding="utf-8")
    for rel, text in (logs or {}).items():
        (work / rel).write_text(text, encoding="utf-8")
    rec = work / "record.json"
    cmd = [sys.executable, str(HARNESS_WRITER), "--work", str(work), "--harness", "hyper-util", "--sanitizer", sanitizer,
           "--record", str(rec), "--repo", "r", "--commit", "c", "--host", "h", "--host-tag", "L", "--build-exit", "0",
           "--check-exit", str(check_exit), "--seconds", "1", "--pins", str(PINS)] + (["--dry-run"] if dry_run else [])
    subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(rec.read_text(encoding="utf-8"))


def harness_writer(tmp: Path) -> None:
    rec = write_harness_record(tmp)
    expect("harness: green from a clean build and clean checks", rec["green"] is True)
    expect("harness: the target is named as coverage.json names it, with build.json's inputs hash",
           rec.get("inputs_hash") == {"harness_hyper_util": "hh"} and rec.get("inputs_files") == {"harness_hyper_util": 2})
    expect("harness: the toolchain on one line is the record's compiler", rec.get("compiler") == "rustc 1.98.1 (x) binary: rustc cargo 1.98.1")
    expect("harness: the run environment and the pins are recorded",
           rec.get("run_env") == {"TSAN_OPTIONS": "suppressions=/x/tsan.supp"} and rec.get("pins_sha256") == file_sha256(PINS))
    report = "check/cases/raw/hyper-util-cases-matched/front/stderr.log"
    expect("harness: red from a sanitizer report in a harness's log",
           write_harness_record(tmp, logs={report: "WARNING: ThreadSanitizer: data race (pid=1)\n"})["green"] is False)
    go_race = "WARNING: DATA" + " RACE\n"
    expect("harness: red from Go's race report in a harness's log", write_harness_record(tmp, logs={report: go_race})["green"] is False)
    expect("harness: red from a build of another flavour", write_harness_record(tmp, flavour="asan")["green"] is False)
    expect("harness: red when build.json lacks the harness", write_harness_record(tmp, harness_in_build=False)["green"] is False)
    expect("harness: red from a failed check", write_harness_record(tmp, check_exit=1)["green"] is False)
    expect("harness: --dry-run marks the record", write_harness_record(tmp, dry_run=True).get("dry_run") is True)
    # M7: the exit checks run only if each run ended through the harness's SIGTERM handler.
    expect("harness: the runs and those without an exit check are counted",
           (rec.get("harness_runs"), rec.get("harness_runs_without_exit_check")) == (1, 0))
    rec = write_harness_record(tmp, stdout=LISTENING)
    expect("harness: red from a run that did not end through its SIGTERM handler",
           rec["green"] is False and rec.get("harness_runs_without_exit_check") == 1)
    expect("harness: red when the checks ran no harness", write_harness_record(tmp, stdout=None)["green"] is False)
    leak = "==4711==ERROR: Leak" + "Sanitizer: detected memory leaks\n"
    expect("harness: red from LeakSanitizer's report at a clean exit",
           write_harness_record(tmp, flavour="asan", sanitizer="asan", logs={report: leak})["green"] is False)


def end_to_end(tmp: Path) -> None:
    expect("green from the CTest 3 form", write_record(tmp, OLD)["green"] is True)
    expect("green from the CTest 4 form", write_record(tmp, NEW)["green"] is True)
    expect("red from a summary with a failed test, CTest exit 0", write_record(tmp, FAILED)["green"] is False)
    expect("red from a summary with a failed test, CTest exit 8", write_record(tmp, FAILED, 8)["green"] is False)
    expect("red without a summary", write_record(tmp, "")["green"] is False)
    expect("red from a failed build", write_record(tmp, NEW, build_exit=1)["green"] is False)
    expect("red without build.inputs.json", write_record(tmp, NEW, inputs=False)["green"] is False)
    rec = write_record(tmp, NEW, extra={"ctest.log": ctest_log(NEW) + "==4711==WARNING: MemorySanitizer: use-of-uninitialized-value\n"})
    expect("red from a sanitizer report in a passing CTest log", rec["green"] is False and rec["sanitizer_reports"] >= 1)
    rec = write_record(tmp, NEW, extra={"probe.err": "WARNING: ThreadSanitizer: data race (pid=1)\n"})
    expect("red from a sanitizer report in an error file", rec["green"] is False)
    rec = write_record(tmp, NEW)
    expect("the record carries the pins' sha256", rec.get("pins_sha256") == file_sha256(PINS))
    expect("the record carries the inputs hashes", rec.get("inputs_hash") == {"oneport": "s", "oneport_tests": "t"})
    expect("the record carries the configuration", rec.get("config") == CONFIG)
    expect("the record carries the compiler and host tag", rec.get("compiler") == "Clang 22.1.8" and rec.get("host_tag") == "L")
    expect("a record is not a dry run unless asked", rec.get("dry_run") is False)
    expect("--dry-run marks the record", write_record(tmp, NEW, dry_run=True).get("dry_run") is True)


def main() -> int:
    parsers()
    pattern()
    with tempfile.TemporaryDirectory() as t:
        end_to_end(Path(t))
        harness_writer(Path(t))
    report = re.compile(SHARED_PATTERN)
    expect("no line this test printed matches the report pattern", not any(report.search(p) for p in printed))
    print(f"{failures} failed" if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
