#!/usr/bin/env python3
"""The sanitizer gate of a measured oneport build: do green records cover what this build compiled?

    check_records.py --records DIR --inputs BUILD.inputs.json --compiler ID --host L|W
                     [--coverage bench/coverage.json] [--pins bench/cmake/pins.cmake] [--out gate.json]

Copied from paper-typed-routing bench/check_records.py and t1/check_h6_records.py at commit
7c1e248, same author, with the paths and names of this repository. The rules are
bench/gate_lib.py's (the Papers repo's rule D5; hypotheses.md, section 11): for every target of
the build (the oneport build of BUILD.inputs.json, lab/bin/inputs_hash.py in project mode: the
server, the generators, the holder, the test suite and the libraries they link, since a target's
hash covers its own translation units only) and every sanitizer the host needs (L: ASan+UBSan,
TSan, MSan; W: ASan), a green record made on that host (oneport-*-<host>-<san>.json) compiled the
same first-party inputs, with the same compiler, the same configuration and the same pins (the
sha256 of the pins.cmake the build used, --pins, and every archive both fetched with the same URL
and hash). A gap is allowed only where the "targets" section of coverage.json declares it for that
target; its "declared_gaps" section describes what the records cannot see and allows nothing.

Prints one "covered" line per target on stderr and the gate as JSON on stdout or to --out; exits 1
with the reason if the records do not cover the build. A row is citable only from a build this
gate passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gate_lib import SANITIZERS_BY_HOST, GateError, config_of, fetched_of, file_sha256, load, target_coverage

BUILD = "oneport"
PATTERN = "oneport-*.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--inputs", type=Path, required=True, help="the build's <build>.inputs.json (lab/bin/inputs_hash.py)")
    ap.add_argument("--compiler", required=True, help="the build's CMake compiler identification")
    ap.add_argument("--host", required=True, choices=sorted(SANITIZERS_BY_HOST), help="the host the build runs on")
    ap.add_argument("--coverage", type=Path, default=Path(__file__).with_name("coverage.json"))
    ap.add_argument("--pins", type=Path, default=Path(__file__).with_name("cmake") / "pins.cmake",
                    help="the pins.cmake the build used (default: this tree's)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    try:
        info = load(args.inputs)["builds"][BUILD]
        hashes = {t: v["inputs_hash"] for t, v in info["targets"].items()}
    except KeyError as e:
        sys.exit(f"check_records: {args.inputs} has no {e} (expected builds.{BUILD}.targets.<target>.inputs_hash)")
    config = config_of(info)
    declared = load(args.coverage).get("targets") or {}
    pins = file_sha256(args.pins)
    try:
        coverage, partial, used = target_coverage(args.records, PATTERN, hashes, config, args.compiler, declared,
                                                  host=args.host, pins=pins, fetched=fetched_of(info))
    except GateError as e:
        sys.exit(f"check_records: {e}")
    gate = {"host": args.host, "compiler": args.compiler, "pins_sha256": pins, "fetched": fetched_of(info),
            "inputs_hash": hashes, "config": config, "coverage": coverage, "partial": partial, "records": used}
    text = json.dumps(gate, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
