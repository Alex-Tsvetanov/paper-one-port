#!/usr/bin/env python3
"""One line of the lab journal (Papers lab/journal.jsonl) for one lab job of development windows.

The journal's fields are those of the earlier entries: date, paper, host, run, code_commit,
variant, summary, cells, note. Every window of the job is listed in `cells` with its cell, session,
arm, position, metric and validity. `run` names the job as development data (hypotheses.md,
section 8, step 2: cited only in the revision log and the journal, disclosed in the methods).

    journal.py --job-dir DIR --run TEXT --variant TEXT [--note TEXT] [--commit SHA]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def entry(job_dir: Path, run: str, variant: str, note: str, commit: str | None) -> dict:
    rows = [json.loads(ln) for ln in (job_dir / "windows.jsonl").read_text().splitlines() if ln.strip()]
    summary = json.loads((job_dir / "summary.json").read_text()) if (job_dir / "summary.json").exists() else {}
    prov = next((r["provenance"] for r in rows if "provenance" in r), {})
    cells = [{
        "tag": r.get("tag"), "cell": r.get("cell"), "session": r.get("session"), "arm": r.get("arm"),
        "position": r.get("position"), "metric": (r.get("metric") or {}).get("value"), "valid": r.get("valid"),
        "invalid_reasons": r.get("invalid_reasons"), "src_block": r.get("src_block"), "started": r.get("started"),
    } for r in rows]
    spread = {c: {k: v for k, v in s["metric"].items() if k != "ratios"} for c, s in summary.get("cells", {}).items()}
    host = next((r["fingerprint"].get("host") for r in rows if r.get("fingerprint")), "alex-laptop")
    return {
        "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "paper": "P3",
        "host": host,
        "run": f"development, M3 A/A (dedicated against dedicated): {run}",
        "code_commit": commit or prov.get("commit") or "",
        "variant": variant,
        "summary": {"windows": len(rows), "valid": sum(1 for r in rows if r.get("valid")), "spread": spread,
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
    a = ap.parse_args(argv)
    print(json.dumps(entry(a.job_dir, a.run, a.variant, a.note, a.commit), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
