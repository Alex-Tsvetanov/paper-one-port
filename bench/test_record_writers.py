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
   here, and against that script too where the Papers repo is checked out around this one.
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


def expect(name: str, ok: bool) -> None:
    global failures
    print(("ok: " if ok else "FAIL: ") + name)
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
    for line in ("==4711==WARNING: MemorySanitizer: use-of-uninitialized-value",
                 "==4711==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000011",
                 "WARNING: ThreadSanitizer: data race (pid=4711)",
                 "src/a.cpp:12:5: runtime error: signed integer overflow"):
        expect(f"a report line matches: {line[:40]}", m.REPORT.search(line) is not None)
    expect("a clean line does not match", m.REPORT.search("100% tests passed out of 87") is None)


def write_record(tmp: Path, summary: str, ctest_exit: int = 0, build_exit: int = 0, inputs: bool = True,
                 extra: dict | None = None) -> dict:
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
           "--pins", str(PINS)]
    subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(rec.read_text(encoding="utf-8"))


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


def main() -> int:
    parsers()
    pattern()
    with tempfile.TemporaryDirectory() as t:
        end_to_end(Path(t))
    print(f"{failures} failed" if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
