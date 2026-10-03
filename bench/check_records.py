#!/usr/bin/env python3
"""The sanitizer gate of a measured oneport build: do green records cover what this build compiled?

    check_records.py --records DIR --host L|W [--inputs BUILD.inputs.json [--compiler ID]]
                     [--harnesses BUILD.json] [--coverage bench/coverage.json] [--pins bench/cmake/pins.cmake]
                     [--accept-dry-run] [--out gate.json]

Copied from paper-typed-routing bench/check_records.py and t1/check_h6_records.py at commit
7c1e248, same author, with the paths and names of this repository. The rules are
bench/gate_lib.py's (the Papers repo's rule D5; hypotheses.md, section 11): for every target of
the build and every sanitizer the host needs (L: ASan+UBSan, TSan, MSan; W: ASan), a green record
made on that host compiled the same first-party inputs, with the same compiler, the same
configuration and the same pins (the sha256 of the pins.cmake the build used, --pins, and every
archive both fetched with the same URL and hash). A gap is allowed only where the "targets" section
of coverage.json declares it for that target; its "declared_gaps" section describes what the
records cannot see and allows nothing. Section 11: "Every measured build is gated: the server and
backend, the generators, the holder and the harnesses."

Two kinds of measured build, one or both per call:
- --inputs: the oneport CMake build, hashed by bench/build_inputs.py (every first-party target:
  the server, the generators, the holder, the suite and the libraries they link), against the
  records oneport-*-<host>-<san>.json (bench/sanitize_oneport.sh), with the build's CMake compiler
  identification from the inputs file, or --compiler. The build's executables (build_inputs.BINARIES), read from the
  build directory the inputs file names, are hashed into the gate's output.
- --harnesses: the in-process libraries' harnesses as bench/competitors/build_harnesses.sh built
  them for a measured run (the release flavour), from its build.json: each harness is the target
  harness_<name> of coverage.json, with its inputs hash (harness_inputs.py) and its toolchain
  (build.json's "tools") as the compiler, against the records harness_<name>-*-L-<san>.json
  (bench/sanitize_harness.sh). The Java harnesses have no record; coverage.json declares their gap
  whole. Each harness's output sha256 goes into the gate's output.

The output (stdout or --out) names the host, what was gated, the records used, the partial
coverage allowed by declared gaps, and "binaries", {name: sha256}, which bench/check_rows.py
matches each row's binaries against. "passed" is true; a gate that fails writes nothing and exits
1 with the reason. --accept-dry-run lets the drivers' dry run exercise the matching on dry-run
records; its output is marked "dry_run" and check_rows.py refuses it, so it is never citable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from build_inputs import BINARIES
from gate_lib import SANITIZERS_BY_HOST, GateError, config_of, fetched_of, file_sha256, load, target_coverage

BUILD = "oneport"
PATTERN = "oneport-*.json"


def harness_target(name: str) -> str:
    return "harness_" + name.replace("-", "_")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_binaries(build_dir: Path, host: str) -> tuple[dict, list[str]]:
    """The measured executables of a oneport build, by name: their sha256, and those missing."""
    found, missing = {}, []
    for name, rel in BINARIES[host].items():
        p = build_dir / rel
        if p.is_file():
            found[name] = sha256_file(p)
        else:
            missing.append(str(p))
    return found, missing


def gate_oneport(a, declared: dict, pins: str) -> dict:
    try:
        info = load(a.inputs)["builds"][BUILD]
        hashes = {t: v["inputs_hash"] for t, v in info["targets"].items()}
    except KeyError as e:
        raise GateError(f"{a.inputs} has no {e} (expected builds.{BUILD}.targets.<target>.inputs_hash)")
    config = config_of(info)
    compiler = a.compiler or info.get("compiler")
    if not compiler:
        raise GateError(f"{a.inputs} names no compiler (bench/build_inputs.py writes it); give --compiler")
    coverage, partial, used = target_coverage(a.records, PATTERN, hashes, config, compiler, declared,
                                              host=a.host, pins=pins, fetched=fetched_of(info),
                                              accept_dry_run=a.accept_dry_run)
    binaries, missing = build_binaries(Path(info.get("build_dir", ".")), a.host)
    return {"compiler": compiler, "fetched": fetched_of(info), "inputs_hash": hashes, "config": config,
            "coverage": coverage, "partial": partial, "records": used, "binaries": binaries, "binaries_missing": missing}


def gate_harnesses(a, declared: dict, pins: str) -> dict:
    built = load(a.harnesses)
    out: dict = {"inputs_hash": {}, "compiler": {}, "coverage": {}, "partial": {}, "records": [], "binaries": {}}
    for name, entry in sorted(built.items()):
        if entry.get("flavour") != "release":
            raise GateError(f"{a.harnesses}: {name} is the {entry.get('flavour')} flavour; a measured harness is release")
        target = harness_target(name)
        compiler = " ".join(str(entry.get("tools", "")).split())
        hashes = {target: entry["inputs_hash"]}
        coverage, partial, used = target_coverage(a.records, f"{target}-*.json", hashes, {}, compiler, declared,
                                                  host=a.host, pins=pins, fetched={}, accept_dry_run=a.accept_dry_run)
        out["inputs_hash"].update(hashes)
        out["compiler"][target] = compiler
        out["coverage"].update(coverage)
        out["partial"].update(partial)
        out["records"] += used
        out["binaries"][target] = entry.get("output_sha256")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--host", required=True, choices=sorted(SANITIZERS_BY_HOST), help="the host the build runs on")
    ap.add_argument("--inputs", type=Path, help="the oneport build's inputs file (bench/build_inputs.py)")
    ap.add_argument("--compiler", help="the oneport build's CMake compiler identification (default: the inputs file's, "
                                       "which bench/build_inputs.py writes)")
    ap.add_argument("--harnesses", type=Path, help="build_harnesses.sh's build.json of the measured harnesses")
    ap.add_argument("--coverage", type=Path, default=Path(__file__).with_name("coverage.json"))
    ap.add_argument("--pins", type=Path, default=Path(__file__).with_name("cmake") / "pins.cmake",
                    help="the pins.cmake the build used (default: this tree's)")
    ap.add_argument("--accept-dry-run", action="store_true",
                    help="the drivers' dry run: dry-run records count, and the output is marked and never citable")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if not args.inputs and not args.harnesses:
        sys.exit("check_records: give --inputs, --harnesses or both")
    declared = load(args.coverage).get("targets") or {}
    pins = file_sha256(args.pins)
    gate: dict = {"host": args.host, "pins_sha256": pins, "passed": True, "dry_run": args.accept_dry_run,
                  "citable": not args.accept_dry_run, "records_dir": str(args.records)}
    try:
        if args.inputs:
            gate["oneport"] = gate_oneport(args, declared, pins)
        if args.harnesses:
            gate["harnesses"] = gate_harnesses(args, declared, pins)
    except GateError as e:
        sys.exit(f"check_records: {e}")
    gate["binaries"] = {**(gate.get("oneport") or {}).get("binaries", {}), **(gate.get("harnesses") or {}).get("binaries", {})}
    text = json.dumps(gate, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
