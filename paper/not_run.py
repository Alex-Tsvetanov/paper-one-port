#!/usr/bin/env python3
"""The cells not run or short of R, with their logged reasons (results/not-run.json).

    python paper/not_run.py --summary results/summary.json --not-run not-run-JOB.json [...] \
                            --rows windows.jsonl [...] [--out results/not-run.json]

summary.json gives such a cell only as "0 valid sessions, fewer than R" (or "untested: ..."): the
reasons are in the runners' not-run-<job>.json files, in the revision log and in design/status.md
(status.md, "The confirmatory analysis on W, 2026-10-07", section 5, item 7). This file lists, per
cell that summary.json has short of its R, in a family or in section 10:
  - whether it ran (rows) or was not run (a not-run file's reason, copied as written);
  - for a cell that ran, its windows, valid windows and sessions per arm, and its invalid windows'
    reasons with every number written N, counted, and its workloads;
  - the logged entries that give the reason: revision-log headings and status.md sections, each
    checked to exist, and quotes copied from them, each checked to occur exactly once.
Nothing is typed in as a value: the cells come from summary.json, the counts from the rows, the
reasons from the not-run files, and every quote below is checked against its source. Every input
is named by its sha256. It decides nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HYP = ROOT / "hypotheses.md"
STATUS = ROOT / "design" / "status.md"
B1_ENTRY = "2026-10-06: The B1 count of the mixed cell (a later change under section 8)"
W_ENTRY = "2026-10-04: W before the code freeze"
M7E_ENTRY = "2026-10-04: The job's warm-up and W's runners (M7e), before the code freeze"
M7C_ENTRY = "2026-10-04: M7c's open items, before the code freeze"
SSLH_ENTRY = "2026-10-03: sslh-ev's stalled exchanges, before the code freeze"
COST_L = "L after the cost family, 2026-10-05"
SL3 = "L's section 10 job sl3, 2026-10-07"
ANALYSIS = "The confirmatory analysis on W, 2026-10-07"


def H(title: str, where: str) -> dict:
    return {"source": "hypotheses.md", "entry": title, "where": where}


def S(section: str, sub: str, where: str = "") -> dict:
    return {"source": "design/status.md", "section": section, "subsection": sub, "where": where}


# (cell pattern, logged references, quotes as (source, text)); every matching row applies.
LOGGED: list[tuple[str, list[dict], list[tuple[str, str]]]] = [
    (r"^C1\.W\.IOCP\.(h2c|mqtt)$", [H(W_ENTRY, "item 1"), H(M7E_ENTRY, "item 2")], []),
    (r"^M2\.L\.(epoll|io_uring)\.tls$", [H(W_ENTRY, "item 2"), H(M7C_ENTRY, "item 6"),
                                         H("2026-10-05: M2's rates (M2_RATE), after the pilot entry", "item 2")], []),
    (r"\.resumption$", [H(M7C_ENTRY, "item 5")], []),
    (r"^S\.two-cores\.C1\.W\.IOCP\.two-cores$", [H(W_ENTRY, "item 7"), H(M7E_ENTRY, "item 3")], []),
    (r"sslh-ev", [H(SSLH_ENTRY, "the note before item 1, and items 1 to 3")],
     [("hypotheses.md", "In M4a's development windows 0.60% to 0.67% of sslh-ev's exchanges timed out at opgen's 1 s, "
                        "with no connect failure, no reset and no listen overflow, so every sslh-ev window of M3 fails "
                        "section 7's 0.1% error rule.")]),
    (r"^S\..*sslh-ev$", [S(SL3, "3. The seven cells short of R")], []),
    (r"^S\.m-ttfb\..*sslh-ev$", [S(ANALYSIS, "5. The review", "item 6")], []),
    (r"^S\.ssh\.C2\.L\.", [S(SL3, "3. The seven cells short of R")], []),
    (r"^S\.ssh\.C2\.W\.", [S("W's section 10 job ws1, 2026-10-07", "2. Per cell: 600 rows against 576 planned")], []),
    (r"^S\.ssh\.C2\.", [S(COST_L, "4. Stopped: what needs Alex", "item 3"), H(B1_ENTRY, "item 5")],
     [("design/status.md", "`opgen --load keepalive` refuses `--proto ssh` (\"--load keepalive serves http1, h2c, tls and mqtt "
                           "(WL3)\"; exit 2), and the SSH handler closes after one line, so WL3 has no SSH form."),
      ("hypotheses.md", "section 10's SSH C2 cells unable to run")]),
    (r"^S\.mixed\.C1\.L\.io_uring$", [S(COST_L, "4. Stopped: what needs Alex", "item 2"), H(B1_ENTRY, "item 5"),
                                      S(SL3, "3. The seven cells short of R")],
     [("design/status.md", "**The mixed cell on io_uring starves its churn, in both modes.**"),
      ("hypotheses.md", "the mixed cell on io_uring starving its churn in both modes")]),
    (r"^B3\.partial-hello\.cmux\.epoll$", [S("L after bs1, 2026-10-07", "1. bs1 and bk1: counts")],
     [("design/status.md", "**B3.partial-hello.cmux.epoll did not**: 20 sessions (16 base and the 4 reruns of its cap, "
                           "4.1's ceil(R/4) at R = 16), 15 valid, 5 invalid (each by the TIME-WAIT rule at both samples). "
                           "No treatment is proposed here.")]),
]
SOURCES = {"hypotheses.md": HYP, "design/status.md": STATUS}
CROSS_HOST = re.compile(r"^[LW]'s cells?, run by [LW]'s runner")


class InputRefused(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources_commit() -> dict:
    """The one-port commit whose hypotheses.md and design/status.md the references and quotes were
    read from, and whether the working tree differed from it in those two files."""
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "files": sorted(SOURCES),
            "changed_in_working_tree": bool(git("status", "--porcelain", "--", *(str(p.relative_to(ROOT)) for p in SOURCES.values())))}


def normalised(text: str) -> str:
    return " ".join(text.split())


def check_reference(ref: dict, texts: dict[str, str]) -> None:
    lines = texts[ref["source"]].splitlines()
    if ref["source"] == "hypotheses.md":
        if sum(1 for ln in lines if ln == f"### {ref['entry']}") != 1:
            raise InputRefused(f"hypotheses.md has no single entry headed {ref['entry']!r}")
        return
    tops = [i for i, ln in enumerate(lines) if ln == f"## {ref['section']}"]
    if len(tops) != 1:
        raise InputRefused(f"status.md has no single section {ref['section']!r}")
    end = next((i for i in range(tops[0] + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    if sum(1 for ln in lines[tops[0]:end] if ln == f"### {ref['subsection']}") != 1:
        raise InputRefused(f"status.md, {ref['section']!r}, has no single subsection {ref['subsection']!r}")


def logged_for(cell: str, texts: dict[str, str]) -> tuple[list[dict], list[dict]]:
    refs, quotes = [], []
    for pattern, rs, qs in LOGGED:
        if not re.search(pattern, cell):
            continue
        for r in rs:
            check_reference(r, texts)
            refs.append(r)
        for src, q in qs:
            n = normalised(texts[src]).count(q)
            if n != 1:
                raise InputRefused(f"the quote {q[:50]!r}... occurs {n} times in {src}, not once")
            quotes.append({"source": src, "text": q})
    return refs, quotes


def short_cells(summary: dict) -> dict[str, dict]:
    """Every cell that summary.json has short of its R, with where it is listed and what it says."""
    out: dict[str, dict] = {}
    for fam, f in summary["families"].items():
        for x in f["cells"]:
            if x["valid_sessions"] < x["R"]:
                e = out.setdefault(x["cell"], {"R": x["R"], "valid_sessions": x["valid_sessions"], "listed_in": [], "summary_says": []})
                e["listed_in"].append(f"family {fam}")
                e["summary_says"].append(x["verdict"])
    for x in summary["secondary"]:
        why = x.get("why") or ""
        if x["valid_sessions"] < x["R"] and x.get("interval") is not None:
            raise InputRefused(f"{x['cell']}: an interval with {x['valid_sessions']} valid sessions, fewer than R")
        if x["valid_sessions"] < x["R"]:
            e = out.setdefault(x["cell"], {"R": x["R"], "valid_sessions": x["valid_sessions"], "listed_in": [], "summary_says": []})
            if e["R"] != x["R"] or e["valid_sessions"] != x["valid_sessions"]:
                raise InputRefused(f"{x['cell']}: R or valid sessions differ between its entries in summary.json")
            e["listed_in"].append(f"section 10, {x['bullet']}, {x['metric']}")
            if why not in e["summary_says"]:
                e["summary_says"].append(why)
    return out


def number_free(reason: str) -> str:
    """Every number of a reason written N, so that reasons count together; digits inside a word
    (http1, h2c) stay."""
    return re.sub(r"(?<![A-Za-z_])\d+(?:\.\d+)?", "N", reason)


def workload(r: dict) -> str:
    m = r.get("metric") or {}
    rate = "no rate" if r.get("rate") is None else "a rate"
    return f"workload {r.get('workload')}, {rate}, metric {m.get('name') if isinstance(m, dict) else None}"


def row_counts(rows: list[dict]) -> dict:
    arms: dict[str, dict] = {}
    for r in rows:
        a = arms.setdefault(str(r.get("arm")), {"windows": 0, "valid_windows": 0})
        a["windows"] += 1
        a["valid_windows"] += int(bool(r.get("valid")))
    reasons = Counter(number_free(x) for r in rows if not r.get("valid") for x in (r.get("invalid_reasons") or []))
    return {"jobs": sorted({str(r.get("job")) for r in rows}), "windows": len(rows), "valid_windows": sum(1 for r in rows if r.get("valid")),
            "sessions": len({(r.get("job"), r.get("session")) for r in rows}), "by_arm": arms,
            "invalid_reasons_numbers_as_N": dict(sorted(reasons.items())), "workloads": dict(Counter(workload(r) for r in rows))}


def build(summary_path: Path, not_run_paths: list[Path], rows_paths: list[Path]) -> dict:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("synthetic") is not False:
        raise InputRefused("summary.json is synthetic")
    texts = {k: p.read_text(encoding="utf-8") for k, p in SOURCES.items()}
    reasons: dict[str, dict[str, list[str]]] = {}
    for p in not_run_paths:
        for cell, why in json.loads(p.read_text(encoding="utf-8")).items():
            if not CROSS_HOST.match(why):
                reasons.setdefault(cell, {}).setdefault(why, []).append(p.name)
    if len({p.resolve() for p in rows_paths}) != len(rows_paths) or len({p.resolve() for p in not_run_paths}) != len(not_run_paths):
        raise InputRefused("a file is given twice")
    by_cell: dict[str, list[dict]] = {}
    keys: set[tuple] = set()
    for p in rows_paths:
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r.get("development") is not False:
                raise InputRefused(f"{p.name}: a row that is not of a frozen run ({r.get('cell')}, {r.get('session')})")
            key = (r.get("job"), r.get("cell"), r.get("session"), r.get("arm"), r.get("position"), r.get("tag"))
            if r.get("cell") is not None and key in keys:   # rows without a cell (K_BASE's windows) are not read
                raise InputRefused(f"{p.name}: two rows of {key}")
            keys.add(key)
            by_cell.setdefault(r.get("cell"), []).append(r)
    cells = []
    for cell, e in short_cells(summary).items():
        ran, logged = cell in by_cell, cell in reasons
        if ran == logged:
            raise InputRefused(f"{cell}: {'both rows and a not-run reason' if ran else 'neither rows nor a not-run reason'}")
        refs, quotes = logged_for(cell, texts)
        if not refs:
            raise InputRefused(f"{cell}: no logged entry names its reason (paper/not_run.py, LOGGED)")
        item = {"cell": cell, **e, "status": "ran, short of R" if ran else "not run"}
        if ran:
            item["rows"] = row_counts(by_cell[cell])
        else:
            item["not_run_reason"] = [{"text": why, "files": files} for why, files in reasons[cell].items()]
        item["logged_in"] = refs
        item["quotes"] = quotes
        cells.append(item)
    notes = []
    for c in cells:
        if (c["cell"].startswith("S.m-ttfb.") and c["status"] == "ran, short of R"
                and all(r.get("rate") is None for r in by_cell[c["cell"]])):
            prefix = c["cell"].rsplit(".", 1)[0].rsplit(".", 1)[0] + "."
            others = Counter(workload(r) for k, rs in by_cell.items() if k and k.startswith(prefix) and k != c["cell"]
                             and k not in {x["cell"] for x in cells} for r in rs)
            notes.append({"cell": c["cell"], "windows": c["rows"]["windows"], "sessions": c["rows"]["sessions"],
                          "valid_sessions": c["valid_sessions"], "its_workloads": c["rows"]["workloads"],
                          "other_cells": {"prefix": prefix, "workloads": dict(others)}})
    return {"what": "P3 (one-port): every cell that results/summary.json has short of its R, in a family or in section 10, "
                    "with the reason its not-run file or its logged entries give; descriptive, it decides nothing",
            "made_by": "paper/not_run.py",
            "inputs": [{"file": p.name, "role": role, "sha256": sha256_file(p)} for role, ps in
                       (("summary", [summary_path]), ("not-run", not_run_paths), ("rows", rows_paths)) for p in ps],
            "logged_entries_read_at": sources_commit(),
            "cells": sorted(cells, key=lambda c: c["cell"]),
            "m_ttfb_cells_that_ran_without_a_rate": notes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--not-run", type=Path, action="append", default=[])
    ap.add_argument("--rows", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "not-run.json")
    a = ap.parse_args(argv)
    try:
        out = build(a.summary, a.not_run, a.rows)
    except InputRefused as e:
        print(f"not_run.py: refused: {e}", file=sys.stderr)
        return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=1, ensure_ascii=True) + "\n")
    print(f"not-run: {len(out['cells'])} cells to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
