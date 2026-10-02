#!/usr/bin/env python3
"""Dedicated-against-dedicated (A/A) development sessions of the cost cells on L (M3; section 8,
step 2: development data, journaled, never results), and the spread of their session ratios.

A session is four windows of a cell's two arms in mirrored order, X Y Y X (section 4.1), the arm
that is X drawn per session. Both arms are the same binary and flags in dedicated mode; arm B's
listeners start PORT_OFFSET above arm A's, so every change of arm changes port, as the pilot's
second start does (section 4.6, step 1). An arm's value is the mean of its two windows; the
session ratio is B / A. Per cell the summary reports the ratios' log standard deviation, their
range, and how many fall outside the cost family's margin [0.98, 1.02] (section 4.3).

Cells are workload:proto:backend with workload churn (WL1), keepalive (WL3) or open (WL2).
An open-loop cell's rate is RATE_FRAC x the median, over this job's sessions of the churn cell of
the same protocol and backend, of the session's mean connections per second: the pilot's rule
(WL2) applied to development sessions, a stand-in that sets no value of the design. So churn and
keep-alive sessions run first, in one shuffled order, then the open-loop sessions. With --rates
FILE (a rates.json of an earlier job) an open-loop cell takes the rate recorded there instead.

    aa.py --build DIR --out DIR --job NAME --cells churn:http1:epoll,... [--sessions 8] [--seed N]
          [--k-src K] [--port-a 20000] [--port-offset 100] [--rates FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import window  # noqa: E402

RATE_FRAC = 0.5  # WL2 (frozen)
MARGIN = (0.98, 1.02)  # section 4.3 (frozen)
# Design choices of M3, recorded in design/status.md.
PORT_A = 20000
PORT_OFFSET = 100


def cache_value(build: Path, key: str) -> str | None:
    for line in (build / "CMakeCache.txt").read_text().splitlines():
        if line.startswith(key + ":"):
            return line.split("=", 1)[1]
    return None


def provenance(build: Path, tools: Path | None) -> dict:
    src = Path(cache_value(build, "CMAKE_HOME_DIRECTORY") or ".")

    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(src), *a], capture_output=True, text=True).stdout.strip()

    p = {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "source_dir": str(src),
        "build_dir": str(build),
        "build_type": cache_value(build, "CMAKE_BUILD_TYPE"),
        "sanitizer": cache_value(build, "ONEPORT_SANITIZER"),
        "cxx_compiler": cache_value(build, "CMAKE_CXX_COMPILER"),
        "cxx_compiler_version": subprocess.run([cache_value(build, "CMAKE_CXX_COMPILER") or "c++", "--version"], capture_output=True,
                                               text=True).stdout.splitlines()[:1],
        "openssl": cache_value(build, "ONEPORT_OPENSSL_USED"),
        "nghttp2": cache_value(build, "ONEPORT_NGHTTP2_USED"),
        "binaries": {name: window.sha256_file(build / rel) for name, rel in
                     (("oneport", "bench/server/oneport"), ("opgen", "bench/gen/opgen"))},
        "pins_sha256": window.sha256_file(src / "bench" / "cmake" / "pins.cmake"),
        "lab_bin": str(window.LAB_BIN),
        "pin_sh_sha256": window.sha256_file(window.LAB_BIN / "pin.sh"),
        "uname": " ".join(os.uname()),
    }
    if tools is not None and (tools / "inputs_hash.py").exists():
        out = build.parent / f"{build.name}.inputs.json"
        r = subprocess.run([sys.executable, str(tools / "inputs_hash.py"), "--build", f"oneport={build}", "--target", "oneport",
                            "--target", "opgen", "--config-key", "CMAKE_BUILD_TYPE", "--config-key", "ONEPORT_SANITIZER",
                            "--root-label", "oneport", "--out", str(out)], capture_output=True, text=True)
        if r.returncode == 0:
            info = json.loads(out.read_text())
            p["inputs_hash"] = {t: v["inputs_hash"] for t, v in info["builds"]["oneport"]["targets"].items()} \
                if "builds" in info else info.get("inputs_hash")
            p["inputs_hash_tool_sha256"] = window.sha256_file(tools / "inputs_hash.py")
        else:
            p["inputs_hash_error"] = r.stderr[-300:]
    return p


def parse_cells(spec: str) -> list[dict]:
    cells = []
    for item in spec.split(","):
        w, p, b = item.split(":")
        if w not in window.WORKLOADS or p not in window.PROTOS or b not in ("epoll", "io_uring"):
            raise SystemExit(f"bad cell {item!r}")
        cells.append({"workload": w, "proto": p, "backend": b, "cell": f"{w}.{p}.{b}"})
    return cells


def session_ratio(rows: list[dict]) -> float | None:
    """B / A, each arm the mean of its two windows' metric; None unless all four are valid."""
    if len(rows) != 4 or not all(r.get("valid") for r in rows):
        return None
    a = [r["metric"]["value"] for r in rows if r["arm"] == "A"]
    b = [r["metric"]["value"] for r in rows if r["arm"] == "B"]
    if len(a) != 2 or len(b) != 2 or statistics.fmean(a) <= 0:
        return None
    return statistics.fmean(b) / statistics.fmean(a)


def secondary_ratio(rows: list[dict], key: str) -> float | None:
    if len(rows) != 4 or not all(r.get("valid") and r.get(key) for r in rows):
        return None
    a = [r[key] for r in rows if r["arm"] == "A"]
    b = [r[key] for r in rows if r["arm"] == "B"]
    return statistics.fmean(b) / statistics.fmean(a)


def spread(ratios: list[float]) -> dict:
    if not ratios:
        return {"n": 0}
    logs = [math.log(x) for x in ratios]
    return {
        "n": len(ratios),
        "median": statistics.median(ratios),
        "min": min(ratios),
        "max": max(ratios),
        "log_sd": statistics.stdev(logs) if len(logs) > 1 else None,
        "outside_margin": sum(1 for x in ratios if not (MARGIN[0] < x < MARGIN[1])),
        "ratios": ratios,
    }


def summarise(rows: list[dict]) -> dict:
    by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by.setdefault((r["cell"], r["session"]), []).append(r)
    cells: dict[str, dict] = {}
    for (cell, _), rs in sorted(by.items()):
        c = cells.setdefault(cell, {"ratios": [], "cpu_ratios": [], "sessions": 0, "invalid_windows": []})
        c["sessions"] += 1
        q = session_ratio(sorted(rs, key=lambda r: r["position"]))
        if q is not None:
            c["ratios"].append(q)
        cq = secondary_ratio(rs, "cpu_us_per_exchange")
        if cq is not None:
            c["cpu_ratios"].append(cq)
        c["invalid_windows"] += [{"tag": r.get("tag"), "reasons": r.get("invalid_reasons")} for r in rs if not r.get("valid")]
    return {cell: {"sessions": c["sessions"], "metric": spread(c["ratios"]), "cpu_per_exchange": spread(c["cpu_ratios"]),
                   "invalid_windows": c["invalid_windows"]} for cell, c in cells.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--cells", required=True)
    ap.add_argument("--sessions", type=int, default=8)
    ap.add_argument("--seed", type=int, required=True, help="the development order's seed, recorded in the journal")
    ap.add_argument("--k-src", type=int, required=True)
    ap.add_argument("--port-a", type=int, default=PORT_A)
    ap.add_argument("--port-offset", type=int, default=PORT_OFFSET)
    ap.add_argument("--tools", type=Path, default=Path.home() / "lab" / "p3" / "tools")
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    ap.add_argument("--rates", type=Path, help="rates.json of an earlier job: the open-loop rate per proto.backend")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    cells = parse_cells(a.cells)
    prov = provenance(a.build, a.tools)
    (a.out / "provenance.json").write_text(json.dumps(prov, indent=1))
    blocks = window.SourceBlocks(a.blocks)
    rng = random.Random(a.seed)
    first = [c for c in cells if c["workload"] != "open"]
    later = [c for c in cells if c["workload"] == "open"]
    rows_path = a.out / "windows.jsonl"
    rows: list[dict] = []

    def run_order(group: list[dict]) -> None:
        order = [(c, s) for c in group for s in range(1, a.sessions + 1)]
        rng.shuffle(order)
        for c, s in order:
            cfg = dict(c, build=a.build, k_src=a.k_src, ports={"A": a.port_a, "B": a.port_a + a.port_offset})
            if c["workload"] == "open":
                cfg["rate"] = rates[(c["proto"], c["backend"])]
            fp = window.pin_fingerprint()
            sid = f"{c['cell']}-s{s:02d}"
            x = rng.choice(["A", "B"])
            y = "B" if x == "A" else "A"
            session = {"job": a.job, "id": sid, "mhz": fp["mean_mhz"], "fingerprint": fp, "x": x}
            if not fp.get("pinned"):
                print(f"{sid}: host not pinned: {fp}", flush=True)
            srows = []
            for pos, arm in enumerate([x, y, y, x]):
                r = window.run_window(cfg, session, arm, pos, blocks, a.out / "raw")
                r["provenance"] = prov
                r["fingerprint"] = fp
                r["seed"] = a.seed
                srows.append(r)
                with open(rows_path, "a") as f:
                    f.write(json.dumps(r) + "\n")
                print(f"{sid} p{pos} {arm}: {r.get('metric', {}).get('value', 0):.1f} valid={r.get('valid')} "
                      f"{'; '.join(r.get('invalid_reasons', []))}", flush=True)
            rows.extend(srows)

    rates: dict[tuple[str, str], float] = {}
    given = {tuple(k.split(".")): v for k, v in json.loads(a.rates.read_text()).items()} if a.rates else {}
    run_order(first)
    for c in later:
        key = (c["proto"], c["backend"])
        if key in given:
            rates[key] = given[key]
            continue
        means = []
        by: dict[str, list[float]] = {}
        for r in rows:
            if r["cell"] == f"churn.{c['proto']}.{c['backend']}" and r.get("valid"):
                by.setdefault(r["session"], []).append(r["metric"]["value"])
        means = [statistics.fmean(v) for v in by.values() if len(v) == 4]
        if not means:
            raise SystemExit(f"open loop {c['cell']}: no valid churn session of {key} in this job")
        rates[key] = RATE_FRAC * statistics.median(means)
    (a.out / "rates.json").write_text(json.dumps({f"{p}.{b}": v for (p, b), v in rates.items()}))
    run_order(later)
    summary = summarise(rows)
    (a.out / "summary.json").write_text(json.dumps({"job": a.job, "rates": {f"{p}.{b}": v for (p, b), v in rates.items()},
                                                    "cells": summary}, indent=1))
    for cell, s in summary.items():
        m = s["metric"]
        if m["n"]:
            print(f"{cell}: n={m['n']} median={m['median']:.4f} range=[{m['min']:.4f}, {m['max']:.4f}] "
                  f"log_sd={m['log_sd'] if m['log_sd'] is None else round(m['log_sd'], 5)} outside={m['outside_margin']}")
        else:
            print(f"{cell}: no valid session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
