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

    python3 bench/test_gates.py      (exit 0 when every check passes)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gate_lib import file_sha256  # noqa: E402

PINS = HERE / "cmake" / "pins.cmake"
PINS_SHA = file_sha256(PINS)
FETCHED = {"openssl": {"url": "https://example.invalid/openssl.tar.gz", "url_hash": "SHA256=aa"},
           "nghttp2": {"url": "https://example.invalid/nghttp2.tar.gz", "url_hash": "SHA256=bb"}}
CHECK = HERE / "check_records.py"
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
    print(f"{failures} failed" if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
