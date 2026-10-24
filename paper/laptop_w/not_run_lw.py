#!/usr/bin/env python3
"""The cells not run or short of R in the laptop's analysis (results/laptop-w/not-run.json).

    python paper/laptop_w/not_run_lw.py --not-run not-run-JOB.json [...] --rows windows.jsonl [...] [--check]

paper/not_run.py, applied to results/laptop-w/summary.json: per cell that the laptop's analysis has
short of its R, in a family or in section 10, whether it ran (its rows' counts and invalid reasons,
numbers written N) or was not run (its not-run file's reason, copied as written), and the logged
entries that give the reason, each checked to exist, with quotes checked to occur exactly once.
It uses not_run.py's functions unchanged; only the table of logged references differs, for the
laptop's W cells:
  - cells 10 and 12 (W's churn h2c and churn MQTT) stay outside the family by their frozen
    treatment alone (the move's entry, item 7; the new pilot entry, item 7). The runner's not-run
    file still writes the desktop's reason, and is copied as written; the references name the two
    laptop entries beside the October decision whose treatment they keep;
  - W's SSH C2 cell is read in the laptop's validity counts (status.md, "The frozen analysis on the
    laptop's W rows, 2026-10-25", section 1), not in the desktop's job section;
  - W's two-core cell stays not run (the move's entry, item 4 (e)).
The rows are L's October row files and the laptop's (cost, M1, section 10); a row of a desktop job
stops the run, and so does a row file whose sha256 results/laptop-w/summary.json does not name.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lw_common as C  # noqa: E402
import not_run as NR  # noqa: E402  paper/not_run.py, read only: its functions

SUMMARY = C.LW / "summary.json"
OUT = C.LW / "not-run.json"
H, S = NR.H, NR.S
MOVE = "2026-10-24: W's runs on the laptop's Windows (a later change under section 8)"
PILOT_LW = "2026-10-24: The new pilot entry, with W's pilot on the laptop's Windows"
LW_STATUS = "The frozen analysis on the laptop's W rows, 2026-10-25"

LOGGED: list[tuple[str, list[dict], list[tuple[str, str]]]] = [
    (r"^C1\.W\.IOCP\.(h2c|mqtt)$", [H(NR.W_ENTRY, "item 1"), H(NR.M7E_ENTRY, "item 2"), H(MOVE, "item 7"),
                                    H(PILOT_LW, "item 7")],
     [("hypotheses.md", "Cells 10 (C1.W.IOCP.h2c) and 12 (C1.W.IOCP.mqtt) stay outside the confirmatory family, since "
                        "the move's entry, item 7, keeps their frozen treatment (`analysis/pilot.py` never resolves them)")]),
    (r"^M2\.L\.(epoll|io_uring)\.tls$", [H(NR.W_ENTRY, "item 2"), H(NR.M7C_ENTRY, "item 6"),
                                         H("2026-10-05: M2's rates (M2_RATE), after the pilot entry", "item 2")], []),
    (r"\.resumption$", [H(NR.M7C_ENTRY, "item 5")], []),
    (r"^S\.two-cores\.C1\.W\.IOCP\.two-cores$", [H(NR.W_ENTRY, "item 7"), H(NR.M7E_ENTRY, "item 3"), H(MOVE, "item 4 (e)")],
     [("hypotheses.md", "The two-core IOCP cell of section 10 stays not run")]),
    (r"sslh-ev", [H(NR.SSLH_ENTRY, "the note before item 1, and items 1 to 3")],
     [("hypotheses.md", "In M4a's development windows 0.60% to 0.67% of sslh-ev's exchanges timed out at opgen's 1 s, "
                        "with no connect failure, no reset and no listen overflow, so every sslh-ev window of M3 fails "
                        "section 7's 0.1% error rule.")]),
    (r"^S\..*sslh-ev$", [S(NR.SL3, "3. The seven cells short of R")], []),
    (r"^S\.m-ttfb\..*sslh-ev$", [S(NR.ANALYSIS, "5. The review", "item 6")], []),
    (r"^S\.ssh\.C2\.L\.", [S(NR.SL3, "3. The seven cells short of R")], []),
    (r"^S\.ssh\.C2\.W\.", [S(LW_STATUS, "1. The laptop's jobs: validity counts (rows read, no arm compared)")], []),
    (r"^S\.ssh\.C2\.", [S(NR.COST_L, "4. Stopped: what needs Alex", "item 3"), H(NR.B1_ENTRY, "item 5")],
     [("design/status.md", "`opgen --load keepalive` refuses `--proto ssh` (\"--load keepalive serves http1, h2c, tls and mqtt "
                           "(WL3)\"; exit 2), and the SSH handler closes after one line, so WL3 has no SSH form."),
      ("hypotheses.md", "section 10's SSH C2 cells unable to run")]),
    (r"^S\.mixed\.C1\.L\.io_uring$", [S(NR.COST_L, "4. Stopped: what needs Alex", "item 2"), H(NR.B1_ENTRY, "item 5"),
                                      S(NR.SL3, "3. The seven cells short of R")],
     [("design/status.md", "**The mixed cell on io_uring starves its churn, in both modes.**"),
      ("hypotheses.md", "the mixed cell on io_uring starving its churn in both modes")]),
    (r"^B3\.partial-hello\.cmux\.epoll$", [S("L after bs1, 2026-10-07", "1. bs1 and bk1: counts")],
     [("design/status.md", "**B3.partial-hello.cmux.epoll did not**: 20 sessions (16 base and the 4 reruns of its cap, "
                           "4.1's ceil(R/4) at R = 16), 15 valid, 5 invalid (each by the TIME-WAIT rule at both samples). "
                           "No treatment is proposed here.")]),
]


def sources_read() -> dict:
    """The git blobs of hypotheses.md and design/status.md that the references and quotes were read
    from (not_run.py records the commit, which moves with every later commit and would make a check
    fail although nothing it read changed), and whether the working tree differed from them."""
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(C.ROOT), *a], capture_output=True, text=True, check=True).stdout.strip()
    rels = sorted(str(p.relative_to(C.ROOT).as_posix()) for p in NR.SOURCES.values())
    return {"blobs": {r: git("rev-parse", f"HEAD:{r}") for r in rels},
            "changed_in_working_tree": bool(git("status", "--porcelain", "--", *rels))}


def logged_for(cell: str, texts: dict[str, str]) -> tuple[list[dict], list[dict]]:
    refs, quotes = [], []
    for pattern, rs, qs in LOGGED:
        if not re.search(pattern, cell):
            continue
        for r in rs:
            NR.check_reference(r, texts)
            refs.append(r)
        for src, q in qs:
            n = NR.normalised(texts[src]).count(q)
            if n != 1:
                raise NR.InputRefused(f"the quote {q[:50]!r}... occurs {n} times in {src}, not once")
            quotes.append({"source": src, "text": q})
    return refs, quotes


def read_rows(paths: list[Path], allowed: set[str]) -> tuple[dict[str, list[dict]], list[dict]]:
    if len({p.resolve() for p in paths}) != len(paths):
        raise NR.InputRefused("a row file is given twice")
    by_cell: dict[str, list[dict]] = {}
    keys: set[tuple] = set()
    inputs = []
    for p in paths:
        text, digest = C.read_checked(p, allowed, "rows")
        rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
        C.refuse_desktop_rows(rows, p.name)
        inputs.append({"file": p.name, "role": "rows", "sha256": digest})
        for r in rows:
            if r.get("development") is not False:
                raise NR.InputRefused(f"{p.name}: a row that is not of a frozen run ({r.get('cell')}, {r.get('session')})")
            key = (r.get("job"), r.get("cell"), r.get("session"), r.get("arm"), r.get("position"), r.get("tag"))
            if r.get("cell") is not None and key in keys:
                raise NR.InputRefused(f"{p.name}: two rows of {key}")
            keys.add(key)
            by_cell.setdefault(r.get("cell"), []).append(r)
    return by_cell, inputs


def build(not_run_paths: list[Path], rows_paths: list[Path]) -> str:
    summary_text = SUMMARY.read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    if summary.get("synthetic") is not False:
        raise NR.InputRefused("summary.json is synthetic")
    allowed = {i["sha256"] for i in summary["inputs"]}
    texts = {k: p.read_text(encoding="utf-8") for k, p in NR.SOURCES.items()}
    if len({p.resolve() for p in not_run_paths}) != len(not_run_paths):
        raise NR.InputRefused("a not-run file is given twice")
    reasons: dict[str, dict[str, list[str]]] = {}
    nr_inputs = []
    for p in not_run_paths:
        nr_inputs.append({"file": p.name, "role": "not-run", "sha256": C.sha256_file(p)})
        if re.search(r"not-run-(wc1|wc2|ws1|wm1)\.json$", p.name):
            raise NR.InputRefused(f"{p.name}: a desktop job's not-run file")
        for cell, why in json.loads(p.read_text(encoding="utf-8")).items():
            if not NR.CROSS_HOST.match(why):
                reasons.setdefault(cell, {}).setdefault(why, []).append(p.name)
    by_cell, row_inputs = read_rows(rows_paths, allowed)
    cells = []
    for cell, e in NR.short_cells(summary).items():
        ran, logged = cell in by_cell, cell in reasons
        if ran == logged:
            raise NR.InputRefused(f"{cell}: {'both rows and a not-run reason' if ran else 'neither rows nor a not-run reason'}")
        refs, quotes = logged_for(cell, texts)
        if not refs:
            raise NR.InputRefused(f"{cell}: no logged entry names its reason (LOGGED)")
        item = {"cell": cell, **e, "status": "ran, short of R" if ran else "not run"}
        if ran:
            item["rows"] = NR.row_counts(by_cell[cell])
        else:
            item["not_run_reason"] = [{"text": why, "files": files} for why, files in reasons[cell].items()]
        item["logged_in"] = refs
        item["quotes"] = quotes
        cells.append(item)
    notes = []
    short = {x["cell"] for x in cells}
    for c in cells:
        if (c["cell"].startswith("S.m-ttfb.") and c["status"] == "ran, short of R"
                and all(r.get("rate") is None for r in by_cell[c["cell"]])):
            prefix = c["cell"].rsplit(".", 1)[0].rsplit(".", 1)[0] + "."
            others: dict[str, int] = {}
            for k, rs in by_cell.items():
                if k and k.startswith(prefix) and k != c["cell"] and k not in short:
                    for r in rs:
                        w = NR.workload(r)
                        others[w] = others.get(w, 0) + 1
            notes.append({"cell": c["cell"], "windows": c["rows"]["windows"], "sessions": c["rows"]["sessions"],
                          "valid_sessions": c["valid_sessions"], "its_workloads": c["rows"]["workloads"],
                          "other_cells": {"prefix": prefix, "workloads": others}})
    out = {"what": "P3 (one-port), the laptop's analysis: every cell that results/laptop-w/summary.json has short of its R, "
                   "in a family or in section 10, with the reason its not-run file or its logged entries give; "
                   "descriptive, it decides nothing; no desktop row is read",
           "made_by": "paper/laptop_w/not_run_lw.py",
           "inputs": [{"file": "results/laptop-w/summary.json", "role": "summary", "sha256": C.sha256_file(SUMMARY)}]
                     + nr_inputs + row_inputs,
           "logged_entries_read_at": sources_read(),
           "cells": sorted(cells, key=lambda c: c["cell"]),
           "m_ttfb_cells_that_ran_without_a_rate": notes}
    return json.dumps(out, indent=1, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--not-run", type=Path, action="append", default=[])
    ap.add_argument("--rows", type=Path, action="append", default=[])
    ap.add_argument("--check", action="store_true", help="compare with the committed file, write nothing")
    a = ap.parse_args(argv)
    try:
        text = build(a.not_run, a.rows)
    except NR.InputRefused as e:
        print(f"not_run_lw.py: refused: {e}", file=sys.stderr)
        return 2
    rc = C.write_all({OUT: text}, a.check)
    if not a.check:
        print(f"not-run (laptop): {len(json.loads(text)['cells'])} cells to {OUT.relative_to(C.ROOT).as_posix()}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
