#!/usr/bin/env python3
"""Splits row files into the rows of one backend's cells and the others (the revision log's entry of
2026-11-03, "io_uring's empty provided-buffer ring, IOCP's start, and the guard's encoding (a later
change under section 8, with new builds)", items 6 (c) and 10 (a)).

L's io_uring cells run again on the new build; October's rows of every other cell are kept and go to
the analysis with the new jobs' rows, and no October row of an io_uring cell does. This tool takes
the kept rows out of the archived files, unchanged, line for line.

A row belongs to the backend when its field `backend` names it; a row without the field (an ophold
row of K_BASE, a fault row) when a dot-separated part of its `cell` or of its hard-case `entry` names
it; any other row is kept with the others. Each output's lines are the input lines unchanged, in
their order, each ending in a newline (a last line without one gets it).

    rows_by_backend.py --backend io_uring --out-backend IO.jsonl --out-others REST.jsonl ROWS.jsonl [...]

Prints, as JSON, each input's sha256 and line count and each output's sha256 and line count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def of_backend(row: dict, backend: str) -> bool:
    """Whether the row belongs to `backend`'s cells (see the module's docstring)."""
    b = row.get("backend")
    if b:
        return b == backend
    for key in ("cell", "entry"):
        v = row.get(key)
        if isinstance(v, str) and backend in v.split("."):
            return True
    return False


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def split(paths: list[Path], backend: str) -> tuple[list[bytes], list[bytes], list[dict]]:
    """The lines of `backend`'s rows, the other lines, and a record per input."""
    mine, others, inputs = [], [], []
    if len({Path(p).resolve() for p in paths}) != len(paths):
        raise SystemExit("rows_by_backend: a file is given twice")
    for p in paths:
        data = Path(p).read_bytes()
        lines = data.splitlines(keepends=True)
        for i, ln in enumerate(lines):
            if not ln.strip():
                continue
            if not ln.endswith(b"\n"):
                ln += b"\n"
            try:
                row = json.loads(ln)
            except json.JSONDecodeError as e:
                raise SystemExit(f"rows_by_backend: {p} line {i + 1} is not JSON: {e}") from e
            if not isinstance(row, dict):
                raise SystemExit(f"rows_by_backend: {p} line {i + 1} is not a row (a JSON object)")
            (mine if of_backend(row, backend) else others).append(ln)
        inputs.append({"file": str(p), "sha256": sha256_bytes(data), "lines": sum(1 for ln in lines if ln.strip())})
    return mine, others, inputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", required=True, choices=("io_uring", "epoll", "iocp"))
    ap.add_argument("--out-backend", type=Path, required=True)
    ap.add_argument("--out-others", type=Path, required=True)
    ap.add_argument("rows", type=Path, nargs="+")
    a = ap.parse_args(argv)
    for out in (a.out_backend, a.out_others):
        if out.exists():
            raise SystemExit(f"rows_by_backend: {out} exists; it writes no file over another")
    mine, others, inputs = split(a.rows, a.backend)
    out = {"backend": a.backend, "inputs": inputs}
    for path, lines, key in ((a.out_backend, mine, "backend_rows"), (a.out_others, others, "other_rows")):
        data = b"".join(lines)
        path.write_bytes(data)
        out[key] = {"file": str(path), "sha256": sha256_bytes(data), "lines": len(lines)}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
