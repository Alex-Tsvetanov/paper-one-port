#!/usr/bin/env python3
"""One line of the lab journal (Papers lab/journal.jsonl) for one lab job of development windows.

The journal's fields are those of the earlier entries: date, paper, host, run, code_commit,
variant, summary, cells, note. Every window of the job is listed in `cells` with its cell, session,
arm, position, metric and validity. `run` names the job as development data (hypotheses.md,
section 8, step 2: cited only in the revision log and the journal, disclosed in the methods).

    journal.py --job-dir DIR --run TEXT --variant TEXT [--note TEXT] [--commit SHA] [--milestone M3] [--kind aa|m3|b3]

--kind m3 names a job of handoff.py (M4a): the server's one-port relay against the proxies, whose
summary holds each cell's session ratios (server / proxy) instead of an A/A spread. --kind b3 names
a job of b3.py windows (WL7's layout; M5): each window's system, case, backend and detection mode,
its validity, W at both samples and U, Kq and Ks at sample 2, in the fields of M4b's B3 lines.
--kind perf names a job of perfrec.py profiles (M5): each profile's front, protocol and detection
mode, perf's exit and opgen's count under perf; it times no cell. --kind runner names a job of a
frozen runner (M7c: pilot_run.py, cost_run.py, b3_run.py, m_run.py, rule_e.py, s_run.py,
hardcase_run.py): every row of the job in the run's directory, a development stub marked.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


KINDS = {"aa": "A/A (dedicated against dedicated)", "m3": "M3 cells (the server's one-port relay against the proxies)",
         "b3": "B3 windows (WL7's layout)", "perf": "profiles of M3's fronts under load (perf record)",
         "runner": "a frozen runner's development run (M7c's end-to-end check)"}


def runner_entry(job_dir: Path, run: str, variant: str, note: str, commit: str | None, milestone: str, job: str | None) -> dict:
    """A job of a frozen runner (bench/run/sessions.py's rows, the pilot's parts, the hard cases):
    every window or run of the job, with its cell, session, arm and position, its metric, its
    validity, and whether it was a development stub (which ran nothing)."""
    rows: list[dict] = []
    for name in ("windows.jsonl", "parts.jsonl", "hardcases.jsonl", "competitor_cases.jsonl"):
        f = job_dir / name
        if f.exists():
            rows += [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    if job is not None:
        rows = [r for r in rows if r.get("job") == job]
    cells = []
    for r in rows:
        m = r.get("metric") or {}
        cells.append({k: v for k, v in {
            "runner": r.get("runner"), "kind": r.get("kind") or r.get("part"), "cell": r.get("cell") or r.get("id"), "session": r.get("session"),
            "arm": r.get("arm"), "position": r.get("position"), "system": r.get("system"), "mode": r.get("mode"), "detect": r.get("detect"),
            "backend": r.get("backend"), "entry": r.get("entry"), "replicate": r.get("replicate"), "metric": m.get("value") if isinstance(m, dict) else None,
            "metric_name": m.get("name") if isinstance(m, dict) else None, "valid": r.get("valid", r.get("passed")), "stub": r.get("stub"),
            "invalid_reasons": r.get("invalid_reasons") or r.get("b1"), "started": r.get("started") or r.get("recorded")}.items() if v is not None})
    fp = [r.get("fingerprint") or {} for r in rows]
    prov = next((r["provenance"] for r in rows if (r.get("provenance") or {}).get("binaries")), {})
    return {"date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "paper": "P3", "host": next((f.get("host") for f in fp if f.get("host")), "alex-laptop"),
            "run": f"development, {milestone} {KINDS['runner']}: {run}", "code_commit": commit or prov.get("commit") or "", "variant": variant,
            "summary": {"rows": len(rows), "valid": sum(1 for r in rows if r.get("valid") or r.get("passed")),
                        "stubs": sum(1 for r in rows if r.get("stub")), "seeds": sorted({r.get("seed") for r in rows if r.get("seed") is not None}),
                        "notrack_windows": sum(1 for f in fp if (f.get("notrack") or {}).get("active")), "binaries": prov.get("binaries")},
            "cells": cells, "note": note}


def perf_entry(job_dir: Path, run: str, variant: str, note: str, commit: str | None, milestone: str) -> dict:
    """A job of perfrec.py profiles: one cell per profile; nothing is a rate of a cell."""
    rows = [json.loads(ln) for ln in (job_dir / "perf.jsonl").read_text().splitlines() if ln.strip()]
    cells = [{"tag": r["tag"], "system": r["system"], "proto": r["proto"], "detect": r.get("detect"), "perf_record_exit": r.get("perf_record_exit"),
              "freq": r.get("freq"), "seconds": r.get("seconds"), "opgen": r.get("opgen"), "started": r.get("started")} for r in rows]
    fp = [r.get("fingerprint") or {} for r in rows]
    return {"date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "paper": "P3", "host": next((f.get("host") for f in fp if f.get("host")), "alex-laptop"),
            "run": f"development, {milestone} {KINDS['perf']}: {run}", "code_commit": commit or "", "variant": variant,
            "summary": {"profiles": len(rows), "notrack": sum(1 for f in fp if (f.get("notrack") or {}).get("active"))},
            "cells": cells, "note": note}


def b3_entry(rows: list[dict], run: str, variant: str, note: str, commit: str | None, milestone: str) -> dict:
    """A job of b3.py windows, in the fields of M4b's B3 lines."""
    cells = []
    for r in rows:
        f1, f2 = r["footprint"]["sample1"], r["footprint"]["sample2"]
        s = r.get("memory_sampler_summary") or {}
        cells.append({"tag": r["tag"], "system": r["system"], "case": r["case"], "backend": r.get("backend"), "detect": r.get("detect"),
                      "placement": r.get("placement"), "valid": r["valid"], "invalid_reasons": r["invalid_reasons"],
                      "W_sample1": round(f1["W"], 1), "W_sample2": round(f2["W"], 1), "U": round(f2["U"], 1), "Kq": round(f2["Kq"], 1),
                      "Ks": round(f2["Ks"], 1), "established": f2["established"], "anon_huge_kb_max": s.get("anon_huge_kb_max"),
                      "thp_collapse_alloc_delta": s.get("thp_collapse_alloc_delta"), "started": r["started"]})
    fp = [r.get("fingerprint") or {} for r in rows]
    return {"date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "paper": "P3", "host": next((f.get("host") for f in fp if f.get("host")), "alex-laptop"),
            "run": f"development, {milestone} {KINDS['b3']}: {run}", "code_commit": commit or "", "variant": variant,
            "summary": {"windows": len(rows), "valid": sum(1 for r in rows if r.get("valid")),
                        "notrack_windows": sum(1 for f in fp if (f.get("notrack") or {}).get("active")),
                        "clock_floor_held": all((f.get("clock_floor") or {}).get("held") for f in fp),
                        "thp_madvise_windows": sum(1 for f in fp if (f.get("thp") or {}).get("held"))},
            "cells": cells, "note": note}


def entry(job_dir: Path, run: str, variant: str, note: str, commit: str | None, milestone: str = "M3", kind: str = "aa",
          job: str | None = None) -> dict:
    if kind == "runner":
        return runner_entry(job_dir, run, variant, note, commit, milestone, job)
    if kind == "perf":
        return perf_entry(job_dir, run, variant, note, commit, milestone)
    rows = [json.loads(ln) for ln in (job_dir / "windows.jsonl").read_text().splitlines() if ln.strip()]
    if kind == "b3":
        return b3_entry(rows, run, variant, note, commit, milestone)
    summary = json.loads((job_dir / "summary.json").read_text()) if (job_dir / "summary.json").exists() else {}
    prov = next((r["provenance"] for r in rows if "provenance" in r), {})
    cells = [{
        "tag": r.get("tag"), "cell": r.get("cell"), "session": r.get("session"), "arm": r.get("arm"),
        "position": r.get("position"), "system": r.get("system"), "metric": (r.get("metric") or {}).get("value"), "valid": r.get("valid"),
        "invalid_reasons": r.get("invalid_reasons"), "src_block": r.get("src_block"), "started": r.get("started"),
    } for r in rows]
    if kind == "m3":
        spread = {c: {k: s[k] for k in ("sessions", "ratios", "ratios_ignoring_mhz") if k in s} for c, s in summary.get("cells", {}).items()}
    else:
        spread = {c: {k: v for k, v in s["metric"].items() if k != "ratios"} for c, s in summary.get("cells", {}).items()}
    host = next((r["fingerprint"].get("host") for r in rows if r.get("fingerprint")), "alex-laptop")
    return {
        "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "paper": "P3",
        "host": host,
        "run": f"development, {milestone} {KINDS[kind]}: {run}",
        "code_commit": commit or prov.get("commit") or "",
        "variant": variant,
        "summary": {"windows": len(rows), "valid": sum(1 for r in rows if r.get("valid")), "spread": spread,
                    "notrack_windows": sum(1 for r in rows if ((r.get("fingerprint") or {}).get("notrack") or {}).get("active")),
                    "rates": summary.get("rates", {}), "binaries": prov.get("binaries"), "inputs_hash": prov.get("inputs_hash")},
        "cells": cells,
        "note": note,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job-dir", type=Path, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--commit")
    ap.add_argument("--milestone", default="M3", help="the milestone named in `run`")
    ap.add_argument("--kind", default="aa", choices=sorted(KINDS),
                    help="aa: aa.py's A/A job; m3: handoff.py's M3 job; b3: b3.py's windows; perf: perfrec.py's profiles; runner: a frozen runner's job (M7c)")
    ap.add_argument("--job", help="--kind runner: only this job's rows")
    a = ap.parse_args(argv)
    print(json.dumps(entry(a.job_dir, a.run, a.variant, a.note, a.commit, a.milestone, a.kind, a.job), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
