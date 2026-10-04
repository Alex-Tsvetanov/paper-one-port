#!/usr/bin/env python3
"""What a oneport build compiled, hashed the one way the records and the gate both use.

    build_inputs.py --build DIR --host L|W --out FILE [--inputs-hash PATH]

The sanitizer records (bench/sanitize_oneport.sh on L, bench/sanitize_oneport.ps1 on W) and the
gate of a measured build (bench/check_records.py) must hash a build with the same targets, the
same configuration keys and the same root label, or a record can never match the build it is
meant to cover. Both take them from here:
- TARGETS: every first-party target the build compiles, per host. hypotheses.md, section 11 names
  oneport, opgen, opcase, ophold and the test suite; a target's hash covers only its own
  translation units (lab/bin/inputs_hash.py), so the static libraries they link are named too.
  Before hashing, the build's compile database is read and every target that compiled a
  translation unit must be in the list, and every listed target must have compiled one: a target
  added later (the merge of m6b-windows, for one) stops the hash until it is named here.
- CONFIG_KEYS: the cache options that select which code is compiled. CMAKE_BUILD_TYPE (the
  records and the measured builds are Release) and ONEPORT_BACKENDS (the backends the platform
  compiles, kept in the cache for this gate, CMakeLists.txt). ONEPORT_SANITIZER is not one: the
  sanitizer is a record's own field, and a key that differs between a record and the measured
  build would let no record match (bench/run/aa.py's development provenance hashes with it, and
  its hashes are never gated).
- ROOT_LABEL "oneport": the repository root is the project root (CMakeLists.txt), labelled so.
- BINARIES: the measured executables per host, whose sha256 the gate records so that a row of a
  window can be bound to a gated build (bench/check_rows.py).

inputs_hash.py is the Papers repo's lab/bin/inputs_hash.py: --inputs-hash, else as
default_inputs_hash() finds it. Its output gets three fields under builds.oneport: "compiler",
CMake's identification of the build's compiler (the text a record's "compiler" holds), "host", and
"inputs_hash_tool" (the path and sha256 of the inputs_hash.py used). Exits 0 with the inputs file
written, 2 if the targets differ from the list, 3 if inputs_hash.py fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BUILD = "oneport"
ROOT_LABEL = "oneport"
CONFIG_KEYS = ("CMAKE_BUILD_TYPE", "ONEPORT_BACKENDS")
# Every first-party target, per host (CMakeLists.txt, bench/*/CMakeLists.txt, tests/CMakeLists.txt
# at the code freeze's preparation). W builds no record_clienthello or ophold (Linux only,
# bench/cases/CMakeLists.txt); it builds opcase_bin since M7e (the hard cases by port and the holder,
# for W's runners).
_COMMON = ("oneport", "oneport_server", "oneport_config", "oneport_loop", "oneport_tls", "opcase", "opcase_bin", "opgen",
           "opgen_core", "oneport_tests")
TARGETS: dict[str, tuple[str, ...]] = {
    "L": _COMMON + ("ophold", "record_clienthello"),
    "W": _COMMON,
}
# The executables a window runs, per host, relative to the build directory.
BINARIES: dict[str, dict[str, str]] = {
    "L": {"oneport": "bench/server/oneport", "opgen": "bench/gen/opgen", "opcase": "bench/cases/opcase",
          "ophold": "bench/cases/ophold"},
    "W": {"oneport": "bench/server/oneport.exe", "opgen": "bench/gen/opgen.exe", "opcase": "bench/cases/opcase.exe"},
}
# CMake writes each target's objects under CMakeFiles/<target>.dir/; an object rule's output ends
# in .o or .obj (lab/bin/inputs_hash.py reads the compile database the same way).
TARGET_DIR = re.compile(r"cmakefiles[/\\]([^/\\]+)\.dir[/\\]", re.IGNORECASE)
OBJECT = re.compile(r"\.(o|obj)$")


def default_inputs_hash() -> Path:
    """The Papers repo's lab/bin/inputs_hash.py: beside a Papers checkout around this repository;
    on L, P3's copy in ~/lab/p3/tools (the copy aa.py's provenance uses; equal to the Papers
    repo's file at 2435e56 on 2026-10-03), else ~/lab/Papers/lab/bin. Its sha256 goes into the
    inputs file, so a copy that differs shows."""
    for cand in (REPO.parent.parent / "lab" / "bin" / "inputs_hash.py",
                 Path.home() / "lab" / "p3" / "tools" / "inputs_hash.py",
                 Path.home() / "lab" / "Papers" / "lab" / "bin" / "inputs_hash.py"):
        if cand.is_file():
            return cand
    raise FileNotFoundError("no lab/bin/inputs_hash.py beside a Papers checkout, in ~/lab/p3/tools or in ~/lab/Papers; "
                            "give --inputs-hash")


def compiled_targets(compdb: list[dict]) -> set[str]:
    """The targets that compiled at least one translation unit, from `ninja -t compdb`."""
    out: set[str] = set()
    for entry in compdb:
        output = entry.get("output") or ""
        m = TARGET_DIR.search(output) if OBJECT.search(output) else None
        if m:
            out.add(m.group(1))
    return out


def check_targets(compiled: set[str], host: str) -> list[str]:
    """Why the compiled targets differ from the host's list (empty when they match)."""
    want = set(TARGETS[host])
    problems = []
    if compiled - want:
        problems.append(f"compiled but not listed in build_inputs.TARGETS[{host!r}]: {', '.join(sorted(compiled - want))}")
    if want - compiled:
        problems.append(f"listed but compiled nothing: {', '.join(sorted(want - compiled))}")
    return problems


def compiler_identification(build: Path) -> str:
    """The build's compiler as CMake's configure step names it ("The CXX compiler identification
    is <ID> <VERSION>", the line bench/oneport_record.py reads into a record), from
    CMakeFiles/<version>/CMakeCXXCompiler.cmake; empty if none is found."""
    for f in sorted(build.glob("CMakeFiles/*/CMakeCXXCompiler.cmake")):
        text = f.read_text(encoding="utf-8", errors="replace")
        cid = re.search(r'^set\(CMAKE_CXX_COMPILER_ID "([^"]*)"\)', text, re.M)
        ver = re.search(r'^set\(CMAKE_CXX_COMPILER_VERSION "([^"]*)"\)', text, re.M)
        if cid and ver:
            return f"{cid.group(1)} {ver.group(1)}"
    return ""


def inputs_hash_command(build: Path, host: str, out: Path, tool: Path) -> list[str]:
    cmd = [sys.executable, str(tool), "--build", f"{BUILD}={build}", "--root-label", ROOT_LABEL, "--out", str(out)]
    for t in TARGETS[host]:
        cmd += ["--target", t]
    for k in CONFIG_KEYS:
        cmd += ["--config-key", k]
    return cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True, help="a configured and built Ninja tree of this repository")
    ap.add_argument("--host", required=True, choices=sorted(TARGETS))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--inputs-hash", type=Path, help="lab/bin/inputs_hash.py (default: found as above)")
    a = ap.parse_args(argv)
    p = subprocess.run(["ninja", "-C", str(a.build), "-t", "compdb"], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"build_inputs: ninja -t compdb failed: {p.stderr.strip()[-300:]}", file=sys.stderr)
        return 3
    problems = check_targets(compiled_targets(json.loads(p.stdout)), a.host)
    if problems:
        print("build_inputs: " + "; ".join(problems), file=sys.stderr)
        return 2
    tool = a.inputs_hash or default_inputs_hash()
    r = subprocess.run(inputs_hash_command(a.build, a.host, a.out, tool), capture_output=True, text=True)
    if r.returncode != 0:
        print(f"build_inputs: {tool} failed: {r.stderr.strip()[-500:]}", file=sys.stderr)
        return 3
    # The compiler beside the hashes, so the gate reads the measured build's from the same file.
    data = json.loads(a.out.read_text(encoding="utf-8"))
    data["builds"][BUILD]["compiler"] = compiler_identification(a.build)
    data["builds"][BUILD]["host"] = a.host
    data["builds"][BUILD]["inputs_hash_tool"] = {"path": str(tool), "sha256": hashlib.sha256(tool.read_bytes()).hexdigest()}
    a.out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"build_inputs: {a.out} ({len(TARGETS[a.host])} targets, config keys {', '.join(CONFIG_KEYS)}, "
          f"compiler {data['builds'][BUILD]['compiler'] or 'not found'})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
