#!/usr/bin/env python3
"""The inputs of each first-party harness of the in-process libraries, and their inputs hash
(rule D5; hypotheses.md, section 11; design/status.md, M4b-2 and M5).

A harness is built outside CMake (bench/competitors/build_harnesses.sh), so lab/bin/inputs_hash.py
cannot see what it compiles. Its inputs are named here instead: the files that select the code its
build makes (its sources, and the lock files that pin what it links) and the files that select
what a sanitizer record of it can report. The hyper-util harness's ThreadSanitizer suppression
file is one of those: a suppression decides which reports a TSan run prints, so it is a
code-selecting input of the harness's TSan record (the coordinator's decision of 2026-10-03:
one entry, scoped to tokio's internals). Editing it changes the harness's inputs hash, so a
record made with another suppression file no longer covers the harness.

The hash is lab/bin/inputs_hash.py's: the sha256 of the sorted lines "<path>\\t<sha256 of the
file>\\n", each path relative to the repository's root with forward slashes, each file read with
CRLF as LF. The configurations a harness runs with (cases.args, b3.args) and its probe script are
not inputs: they select no compiled code and no report.

    harness_inputs.py [NAME ...]    prints {name: {"inputs": [...], "inputs_hash": ..., "run_env": {...}}}
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Per harness, its inputs relative to bench/competitors/<name>/.
INPUTS: dict[str, tuple[str, ...]] = {
    "netty": ("src/oneport/NettyHarness.java", "maven.lock"),
    "jetty": ("src/oneport/JettyHarness.java", "maven.lock"),
    "cmux": ("main.go", "go.mod", "go.sum"),
    "hyper-util": ("src/main.rs", "Cargo.toml", "Cargo.lock", "tsan.supp"),
}

# The environment a sanitizer flavour of a harness runs with, by (harness, flavour), {dir} being
# the harness's source directory: the hyper-util harness's TSan runs read its suppression file.
RUN_ENV: dict[tuple[str, str], dict[str, str]] = {
    ("hyper-util", "tsan"): {"TSAN_OPTIONS": "suppressions={dir}/tsan.supp"},
}


def input_paths(name: str, root: Path = REPO) -> list[Path]:
    """The harness's input files, under `root` (the repository)."""
    if name not in INPUTS:
        raise ValueError(f"no harness {name!r}; harnesses: {', '.join(INPUTS)}")
    return [root / "bench" / "competitors" / name / rel for rel in INPUTS[name]]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def input_lines(name: str, root: Path = REPO) -> list[str]:
    """The sorted "<path>\\t<sha256>" lines of the harness's inputs; a missing input is an error."""
    lines = []
    for p in input_paths(name, root):
        if not p.is_file():
            raise FileNotFoundError(f"{name}: input {p} is missing")
        lines.append(f"{p.relative_to(root).as_posix()}\t{file_digest(p)}")
    return sorted(lines)


def inputs_hash(name: str, root: Path = REPO) -> str:
    return hashlib.sha256("".join(line + "\n" for line in input_lines(name, root)).encode()).hexdigest()


def run_env(name: str, flavour: str, root: Path = REPO) -> dict[str, str]:
    """The environment a flavour of the harness runs with (empty for most)."""
    d = (root / "bench" / "competitors" / name).as_posix()
    return {k: v.format(dir=d) for k, v in RUN_ENV.get((name, flavour), {}).items()}


def describe(name: str, flavour: str = "release", root: Path = REPO) -> dict:
    return {"inputs": input_lines(name, root), "inputs_hash": inputs_hash(name, root), "run_env": run_env(name, flavour, root)}


def main(argv: list[str]) -> int:
    flavour = "release"
    names = []
    for a in argv:
        if a.startswith("--flavour="):
            flavour = a.split("=", 1)[1]
        else:
            names.append(a)
    print(json.dumps({n: describe(n, flavour) for n in (names or list(INPUTS))}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
