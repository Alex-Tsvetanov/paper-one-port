#!/usr/bin/env python3
"""Whether every row ran gated binaries: the citable side of the Papers repo's rule D5.

    check_rows.py --gate GATE.json [--gate GATE.json ...] ROWS [ROWS ...] [--out FILE]

A number is citable only if every measured build compiled first-party inputs that green records
cover (rule D5; hypotheses.md, section 11). bench/check_records.py decides that per build and
writes the sha256 of the build's executables into its output ("binaries"). A row of a window names
the binaries it ran in its provenance (bench/run/aa.py, provenance(): "binaries", {name: sha256},
oneport and opgen; handoff.py adds the competitors, which are not first-party and are not gated).
This check refuses a row unless every first-party binary it names has the same name and sha256 in
some gate that passed, is not a dry run, and is citable. A row that names no binary is refused
too: nothing binds it to a gated build.

ROWS are JSON Lines files of rows (windows.jsonl) or JSON files of one provenance or one row.
Prints a summary as JSON (or writes --out) and exits 0 only if no row is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_gates(paths: list[Path], accept_dry_run: bool = False) -> tuple[dict[tuple[str, str], str], list[str]]:
    """(name, sha256) -> the gate file that covers it; and why gates were left out.

    accept_dry_run (M7c) lets a development check bind rows to the gate of a dry run of the
    records drivers, to show the binding works before the code freeze; whatever it binds is never
    citable, and the caller says so (bench/run/devcheck.py). Without it, as before, a dry run's
    gate covers nothing."""
    covered: dict[tuple[str, str], str] = {}
    left_out: list[str] = []
    for p in paths:
        g = json.loads(p.read_text(encoding="utf-8"))
        if g.get("passed") is not True:
            left_out.append(f"{p.name}: did not pass")
            continue
        if (g.get("dry_run") or g.get("citable") is False) and not accept_dry_run:
            left_out.append(f"{p.name}: a dry run of the records drivers, never citable")
            continue
        for name, sha in (g.get("binaries") or {}).items():
            if sha:
                covered[(name, sha)] = p.name
    return covered, left_out


def rows_of(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def binaries_of(row: dict) -> dict:
    """The first-party binaries a row names: its provenance's, or its own when the row is one."""
    prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else row
    return dict(prov.get("binaries") or {})


def check(rows: list[dict], covered: dict[tuple[str, str], str]) -> list[dict]:
    refused = []
    for i, row in enumerate(rows):
        bins = binaries_of(row)
        where = {k: row.get(k) for k in ("job", "session", "cell", "arm", "position") if k in row}
        if not bins:
            refused.append({"row": i, **where, "why": "the row names no binary, so no gate binds it to a gated build"})
            continue
        missing = [f"{n} {str(s)[:12]}" for n, s in sorted(bins.items()) if (n, s) not in covered]
        if missing:
            refused.append({"row": i, **where, "why": "no passing, citable gate covers " + ", ".join(missing)})
    return refused


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gate", type=Path, action="append", required=True, help="an output of bench/check_records.py")
    ap.add_argument("rows", type=Path, nargs="+")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    covered, left_out = load_gates(a.gate)
    rows = [r for p in a.rows for r in rows_of(p)]
    refused = check(rows, covered)
    out = {"rows": len(rows), "refused": refused, "gates_left_out": left_out,
           "covered_binaries": sorted(f"{n} {s[:12]}" for n, s in covered)}
    text = json.dumps(out, indent=1)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if refused:
        print(f"check_rows: {len(refused)} of {len(rows)} rows refused; the first: {refused[0]['why']}", file=sys.stderr)
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
