#!/usr/bin/env python3
"""Tests of the records gate (bench/check_records.py on bench/gate_lib.py) over synthetic records
and inputs files.

Copied from paper-typed-routing bench/test_gates.py at commit 7c1e248, same author, with the
paths and names of this repository, and with cases for what this gate adds: the host (L needs
ASan+UBSan, TSan and MSan; W needs ASan), the configuration (the code-selecting options), and the
two sections of coverage.json.

On L: a covered build passes; a missing sanitizer, a red record with the same inputs, another
compiler, another configuration and a record not made on L each stop the gate; a target gap the
"targets" section declares is allowed, and an undeclared one, or one written only in
"declared_gaps", is not. On W: one green ASan record per target passes; L's records do not count
there. The pin rule: a build whose bench/cmake/pins.cmake differs from the file its records were
made with is refused; so is a build whose records fetched an archive with another hash, or do not
record their pins.

Added for the code freeze's records drivers: a dry-run record among the records stops the gate,
and --accept-dry-run lets it count but marks the output, never citable; the harnesses' gate
(build_harnesses.sh's build.json: a Go harness covered by ASan and TSan with its declared MSan gap,
a Java harness declared whole, a missing TSan record, another toolchain, a sanitizer flavour as the
measured build); the gate's output holds the build's binaries; bench/check_rows.py passes a row
whose binaries a passing gate holds, and refuses a row whose binary has no matching green record
(another sha256), a row that names no binary, and a row whose only gate is a dry run; and
bench/build_inputs.py's check of the compiled targets against its list.

    python3 bench/test_gates.py      (exit 0 when every check passes)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_inputs  # noqa: E402
from build_inputs import BINARIES  # noqa: E402
from gate_lib import file_sha256  # noqa: E402

PINS = HERE / "cmake" / "pins.cmake"
PINS_SHA = file_sha256(PINS)
FETCHED = {"openssl": {"url": "https://example.invalid/openssl.tar.gz", "url_hash": "SHA256=aa"},
           "nghttp2": {"url": "https://example.invalid/nghttp2.tar.gz", "url_hash": "SHA256=bb"}}
CHECK = HERE / "check_records.py"
ROWS = HERE / "check_rows.py"
COMPILERS = {"L": "Clang 22.1.8", "W": "MSVC 19.51.36246"}
CONFIG = {"CMAKE_BUILD_TYPE": "Release"}
TARGETS = {"oneport": "s1", "oneport_config": "c1", "oneport_loop": "l1", "oneport_tests": "t1", "harness_go": "g1"}
failures = 0


def expect(name: str, ok: bool) -> None:
    global failures
    print(("ok: " if ok else "FAIL: ") + name)
    failures += not ok


def write(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


def inputs(d: Path, targets: dict, config: dict = CONFIG) -> Path:
    write(d / "b.inputs.json", {"builds": {"oneport": {"targets": {t: {"inputs_hash": h, "files": 1} for t, h in targets.items()},
                                                       "config": config, "third_party": {"fetched": FETCHED}}}})
    return d / "b.inputs.json"


def record(recs: Path, name: str, san: str, hashes: dict, green: bool = True, compiler: str = COMPILERS["L"],
           config: dict = CONFIG, pins: str | None = PINS_SHA, fetched: dict | None = None) -> None:
    r = {"sanitizer": san, "green": green, "compiler": compiler, "inputs_hash": hashes, "config": config,
         "third_party": {"fetched": FETCHED if fetched is None else fetched}}
    if pins is not None:
        r["pins_sha256"] = pins
    write(recs / name, r)


def run(inputs_file: Path, recs: Path, coverage: Path, host: str = "L", pins: Path = PINS) -> bool:
    cmd = [sys.executable, str(CHECK), "--records", str(recs), "--inputs", str(inputs_file), "--compiler", COMPILERS[host],
           "--host", host, "--pins", str(pins), "--coverage", str(coverage)]
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0


def gate(out: Path, recs: Path, coverage: Path, *extra: str) -> tuple[bool, dict]:
    """check_records.py with the given arguments; (passed, its output or {})."""
    cmd = [sys.executable, str(CHECK), "--records", str(recs), "--host", "L", "--pins", str(PINS),
           "--coverage", str(coverage), "--out", str(out), *extra]
    ok = subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    return ok, (json.loads(out.read_text(encoding="utf-8")) if ok and out.exists() else {})


def rows_ok(gates: list[Path], rows: Path) -> bool:
    cmd = [sys.executable, str(ROWS)] + [x for g in gates for x in ("--gate", str(g))] + [str(rows)]
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0


def dry_run_cases(tmp: Path) -> None:
    cov = tmp / "coverage.json"
    d = tmp / "dry"
    d.mkdir()
    recs = d / "records"
    recs.mkdir()
    inputs_file = inputs(d, TARGETS)
    for s in ("asan", "tsan", "msan"):
        hashes = dict(TARGETS) if s != "msan" else {t: h for t, h in TARGETS.items() if t != "harness_go"}
        record(recs, f"oneport-x-L-{s}-dryrun.json", s, hashes)
        r = json.loads((recs / f"oneport-x-L-{s}-dryrun.json").read_text())
        r["dry_run"] = True
        write(recs / f"oneport-x-L-{s}-dryrun.json", r)
    expect("L: a dry-run record among the records stops the gate", not run(inputs_file, recs, cov))
    ok, out = gate(d / "gate.json", recs, cov, "--inputs", str(inputs_file), "--compiler", COMPILERS["L"], "--accept-dry-run")
    expect("L: --accept-dry-run lets dry-run records count, and marks the output never citable",
           ok and out.get("dry_run") is True and out.get("citable") is False)


def harness_cases(tmp: Path) -> None:
    cov = tmp / "coverage-h.json"
    write(cov, {"targets": {"harness_cmux": {"not_covered_by": ["msan"], "reason": "Go"},
                            "harness_netty": {"not_covered_by": ["asan", "tsan", "msan"], "reason": "JVM"}}})
    go = "go version go1.27.1 linux/amd64 clang version 22.1.8"

    def built(d: Path, flavour: str = "release") -> Path:
        write(d / "build.json", {"cmux": {"flavour": flavour, "inputs_hash": "h1", "tools": "go version go1.27.1 linux/amd64\nclang version 22.1.8",
                                          "output_sha256": "c1"},
                                 "netty": {"flavour": flavour, "inputs_hash": "n1", "tools": "javac 25.0.4", "output_sha256": "j1"}})
        return d / "build.json"

    def hrec(recs: Path, san: str, h: str = "h1", tools: str = go) -> None:
        write(recs / f"harness_cmux-x-L-{san}.json", {"sanitizer": san, "green": True, "compiler": tools, "config": {},
                                                      "inputs_hash": {"harness_cmux": h}, "pins_sha256": PINS_SHA,
                                                      "third_party": {"fetched": {}}})

    def fresh(name: str) -> tuple[Path, Path]:
        d = tmp / name
        d.mkdir()
        (d / "records").mkdir()
        return d, d / "records"

    d, recs = fresh("h-pass")
    hrec(recs, "asan")
    hrec(recs, "tsan")
    ok, out = gate(d / "gate.json", recs, cov, "--harnesses", str(built(d)))
    expect("harnesses: cmux covered by ASan and TSan with its declared MSan gap, Netty declared whole, passes",
           ok and out["binaries"] == {"harness_cmux": "c1", "harness_netty": "j1"} and out.get("citable") is True)
    d, recs = fresh("h-no-tsan")
    hrec(recs, "asan")
    expect("harnesses: a missing TSan record of cmux stops the gate", not gate(d / "gate.json", recs, cov, "--harnesses", str(built(d)))[0])
    d, recs = fresh("h-toolchain")
    hrec(recs, "asan", tools="go version go1.26.0 linux/amd64 clang version 22.1.8")
    hrec(recs, "tsan", tools="go version go1.26.0 linux/amd64 clang version 22.1.8")
    expect("harnesses: records made with another toolchain do not count", not gate(d / "gate.json", recs, cov, "--harnesses", str(built(d)))[0])
    d, recs = fresh("h-inputs")
    hrec(recs, "asan", h="h2")
    hrec(recs, "tsan", h="h2")
    expect("harnesses: records of other inputs do not cover the harness", not gate(d / "gate.json", recs, cov, "--harnesses", str(built(d)))[0])
    d, recs = fresh("h-flavour")
    hrec(recs, "asan")
    hrec(recs, "tsan")
    expect("harnesses: a sanitizer flavour is not a measured build", not gate(d / "gate.json", recs, cov, "--harnesses", str(built(d, "asan")))[0])


def row_cases(tmp: Path) -> None:
    cov = tmp / "coverage.json"
    d = tmp / "rows"
    d.mkdir()
    recs = d / "records"
    recs.mkdir()
    build_dir = d / "build"
    for name, rel in BINARIES["L"].items():
        (build_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (build_dir / rel).write_bytes(name.encode())
    write(d / "b.inputs.json", {"builds": {"oneport": {"targets": {t: {"inputs_hash": h, "files": 1} for t, h in TARGETS.items()},
                                                       "config": CONFIG, "third_party": {"fetched": FETCHED},
                                                       "build_dir": str(build_dir)}}})
    for s in ("asan", "tsan", "msan"):
        hashes = dict(TARGETS) if s != "msan" else {t: h for t, h in TARGETS.items() if t != "harness_go"}
        record(recs, f"oneport-x-L-{s}.json", s, hashes)
    ok, out = gate(d / "gate.json", recs, cov, "--inputs", str(d / "b.inputs.json"), "--compiler", COMPILERS["L"])
    sha = {name: hashlib.sha256(name.encode()).hexdigest() for name in BINARIES["L"]}
    expect("the gate's output holds the sha256 of the build's binaries", ok and out["binaries"] == sha)
    good = d / "good.jsonl"
    good.write_text(json.dumps({"job": "j", "provenance": {"binaries": {"oneport": sha["oneport"], "opgen": sha["opgen"]}}}) + "\n")
    expect("rows: a row whose binaries a passing gate holds passes", rows_ok([d / "gate.json"], good))
    bad = d / "bad.jsonl"
    bad.write_text(json.dumps({"job": "j", "provenance": {"binaries": {"oneport": "0" * 64, "opgen": sha["opgen"]}}}) + "\n")
    expect("rows: a row whose binary has no matching green record is refused", not rows_ok([d / "gate.json"], bad))
    none = d / "none.jsonl"
    none.write_text(json.dumps({"job": "j", "provenance": {}}) + "\n")
    expect("rows: a row that names no binary is refused", not rows_ok([d / "gate.json"], none))
    dry = json.loads((d / "gate.json").read_text())
    dry.update(dry_run=True, citable=False)
    write(d / "gate-dry.json", dry)
    expect("rows: a row whose only gate is a dry run is refused", not rows_ok([d / "gate-dry.json"], good))
    failed = dict(json.loads((d / "gate.json").read_text()), passed=False)
    write(d / "gate-failed.json", failed)
    expect("rows: a gate that did not pass covers nothing", not rows_ok([d / "gate-failed.json"], good))


def build_inputs_cases() -> None:
    db = [{"output": "bench/server/CMakeFiles/oneport_server.dir/worker.cpp.o"},
          {"output": "bench/server/CMakeFiles/oneport.dir/main.cpp.o"},
          {"output": "bench/server/oneport"},  # a link step, not an object
          {"output": "bench\\gen\\CMakeFiles\\opgen.dir\\main.cpp.obj"}]
    expect("build_inputs: the compiled targets come from the object rules",
           build_inputs.compiled_targets(db) == {"oneport_server", "oneport", "opgen"})
    every = [{"output": f"x/CMakeFiles/{t}.dir/a.cpp.o"} for t in build_inputs.TARGETS["L"]]
    expect("build_inputs: L's list matches a build that compiled exactly it",
           build_inputs.check_targets(build_inputs.compiled_targets(every), "L") == [])
    extra = every + [{"output": "x/CMakeFiles/newtool.dir/a.cpp.o"}]
    expect("build_inputs: a target compiled but not listed stops the hash",
           any("newtool" in p for p in build_inputs.check_targets(build_inputs.compiled_targets(extra), "L")))
    expect("build_inputs: a listed target that compiled nothing stops the hash",
           any("ophold" in p for p in build_inputs.check_targets(build_inputs.compiled_targets(every[:-3]), "L")))
    expect("build_inputs: ONEPORT_SANITIZER is not a configuration key (records and measured builds must match)",
           "ONEPORT_SANITIZER" not in build_inputs.CONFIG_KEYS)


def cases(tmp: Path) -> None:
    cov = tmp / "coverage.json"
    write(cov, {"targets": {"harness_go": {"not_covered_by": ["msan"], "reason": "Go"}}, "declared_gaps": []})
    blind = tmp / "coverage-blind.json"
    write(blind, {"targets": {}, "declared_gaps": [{"gap": "harness_go", "sanitizers": ["msan"], "reason": "Go"}]})

    def fresh(name: str) -> tuple[Path, Path]:
        d = tmp / name
        d.mkdir()
        recs = d / "records"
        recs.mkdir()
        return inputs(d, TARGETS), recs

    def full(recs: Path, skip: str = "") -> None:
        for s in ("asan", "tsan", "msan"):
            if s != skip:
                hashes = dict(TARGETS) if s != "msan" else {t: h for t, h in TARGETS.items() if t != "harness_go"}
                record(recs, f"oneport-x-L-{s}.json", s, hashes)

    inputs_file, recs = fresh("pass")
    full(recs)
    expect("L: a covered build passes (with harness_go's declared MSan gap)", run(inputs_file, recs, cov))
    inputs_file, recs = fresh("undeclared")
    full(recs)
    write(tmp / "none.json", {"targets": {}})
    expect("L: an MSan gap coverage.json does not declare stops the gate", not run(inputs_file, recs, tmp / "none.json"))
    inputs_file, recs = fresh("blind")
    full(recs)
    expect("L: a gap written only in declared_gaps allows no missing record", not run(inputs_file, recs, blind))
    inputs_file, recs = fresh("missing")
    full(recs, skip="tsan")
    expect("L: a missing TSan record stops the gate", not run(inputs_file, recs, cov))
    inputs_file, recs = fresh("red")
    full(recs)
    record(recs, "oneport-z-L-asan.json", "asan", {"oneport_loop": "l1"}, green=False)
    expect("L: a red record with the same inputs stops the gate", not run(inputs_file, recs, cov))
    inputs_file, recs = fresh("compiler")
    for s in ("asan", "tsan", "msan"):
        record(recs, f"oneport-x-L-{s}.json", s, TARGETS, compiler="Clang 18.1.3")
    expect("L: records made with another compiler do not count", not run(inputs_file, recs, cov))
    inputs_file, recs = fresh("config")
    for s in ("asan", "tsan", "msan"):
        record(recs, f"oneport-x-L-{s}.json", s, TARGETS, config={"CMAKE_BUILD_TYPE": "Debug"})
    expect("L: records made with another configuration do not count", not run(inputs_file, recs, cov))
    inputs_file, recs = fresh("config-same")
    for s in ("asan", "tsan", "msan"):
        record(recs, f"oneport-x-L-{s}.json", s, TARGETS)
    expect("L: the same records with the build's configuration pass", run(inputs_file, recs, cov))
    inputs_file, recs = fresh("host")
    full(recs)
    (recs / "oneport-x-L-asan.json").rename(recs / "oneport-x-W-asan.json")
    expect("L: a record not made on L does not count", not run(inputs_file, recs, cov))
    inputs_file, recs = fresh("other-inputs")
    full(recs)
    write(recs.parent / "b.inputs.json", {"builds": {"oneport": {
        "targets": {**{t: {"inputs_hash": h, "files": 1} for t, h in TARGETS.items()}, "oneport": {"inputs_hash": "s2", "files": 1}},
        "config": CONFIG, "third_party": {"fetched": FETCHED}}}})
    expect("L: a build of other inputs is not covered by these records", not run(inputs_file, recs, cov))

    # W needs ASan only, made on W with W's compiler.
    inputs_file, recs = fresh("w-pass")
    record(recs, "oneport-x-W-asan.json", "asan", TARGETS, compiler=COMPILERS["W"])
    expect("W: one green ASan record per target passes", run(inputs_file, recs, cov, host="W"))
    inputs_file, recs = fresh("w-from-l")
    for s in ("asan", "tsan", "msan"):
        record(recs, f"oneport-x-L-{s}.json", s, TARGETS, compiler=COMPILERS["W"])
    expect("W: records made on L do not count on W", not run(inputs_file, recs, cov, host="W"))
    inputs_file, recs = fresh("w-red")
    record(recs, "oneport-x-W-asan.json", "asan", TARGETS, compiler=COMPILERS["W"])
    record(recs, "oneport-y-W-asan.json", "asan", {"oneport": "s1"}, green=False, compiler=COMPILERS["W"])
    expect("W: a red record with the same inputs stops the gate", not run(inputs_file, recs, cov, host="W"))

    # The pin rule, with the real pins.cmake and a copy of it that differs by one line.
    changed = tmp / "pins-changed.cmake"
    changed.write_text(PINS.read_text(encoding="utf-8") + "set(ONEPORT_TEST_PIN 0)\n", encoding="utf-8")
    expect("pins: the changed copy differs from pins.cmake", file_sha256(changed) != PINS_SHA)
    inputs_file, recs = fresh("pins-same")
    full(recs)
    expect("L: records made with the build's pins.cmake pass", run(inputs_file, recs, cov))
    expect("L: a build with a changed pins.cmake is refused by records made with the file as it is",
           not run(inputs_file, recs, cov, pins=changed))
    inputs_file, recs = fresh("pins-fetched")
    full(recs)
    other = {k: dict(v) for k, v in FETCHED.items()}
    other["openssl"]["url_hash"] = "SHA256=cc"
    record(recs, "oneport-x-L-tsan.json", "tsan", TARGETS, fetched=other)
    expect("L: a record that fetched an archive with another hash does not count", not run(inputs_file, recs, cov))
    inputs_file, recs = fresh("pins-none")
    full(recs)
    record(recs, "oneport-x-L-asan.json", "asan", TARGETS, pins=None)
    expect("L: a record without its pins does not count", not run(inputs_file, recs, cov))


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        cases(Path(t))
        dry_run_cases(Path(t))
        harness_cases(Path(t))
        row_cases(Path(t))
    build_inputs_cases()
    print(f"{failures} failed" if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
