#!/usr/bin/env python3
"""Dedicated-against-dedicated (A/A) development sessions of the cost cells on W (IOCP), the W side
of aa.py (section 8, step 2: development data, journaled, never results), and the spread of their
session ratios. Run it inside a W lab job (wjob.py: the lock, the quiet check, the lab plan).

A session is four windows of a cell's two arms in mirrored order, X Y Y X (section 4.1), the arm
that is X drawn per session. Both arms are the same binary and flags in dedicated mode; arm B's
listeners start PORT_OFFSET above arm A's. The session ratio is B / A of the arms' window means
(aa.session_ratio); per cell the summary is aa.summarise's.

Cells are workload:proto (backend IOCP) with workload churn (WL1), keepalive (WL3) or open (WL2).
An open-loop cell's rate is RATE_FRAC x the median, over this job's sessions of the churn cell of
the same protocol, of the session's mean connections per second (aa.py's stand-in for WL2's rule),
or the rate in --rates. Churn and keep-alive sessions run first, in one shuffled order, then the
open-loop sessions.

    waa.py --build DIR --out DIR --job NAME --cells churn:http1,... --sessions 6 --seed N --k-src 16
           [--functional --warmup-ms MS --duration-ms MS]   (a functional check: short, flagged, not a window)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aa  # noqa: E402  (session_ratio, summarise, RATE_FRAC, PORT_A, PORT_OFFSET)
import window  # noqa: E402
import wwindow  # noqa: E402

PAPERS_LAB_BIN = Path(os.environ.get("ONEPORT_PAPERS_LAB_BIN", r"D:\Dev\GitHub\Papers\lab\bin"))


def provenance(build: Path) -> dict:
    """The build and the host, as aa.provenance records them on L, read on W."""
    src = Path(aa.cache_value(build, "CMAKE_HOME_DIRECTORY") or ".")

    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(src), *a], capture_output=True, text=True).stdout.strip()

    p = {
        "host": "W",
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "source_dir": str(src),
        "build_dir": str(build),
        "build_type": aa.cache_value(build, "CMAKE_BUILD_TYPE"),
        "sanitizer": aa.cache_value(build, "ONEPORT_SANITIZER"),
        "cxx_compiler": aa.cache_value(build, "CMAKE_CXX_COMPILER"),
        "cxx_compiler_version": aa.cache_value(build, "CMAKE_CXX_COMPILER_VERSION"),
        "openssl": aa.cache_value(build, "ONEPORT_OPENSSL_USED"),
        "nghttp2": aa.cache_value(build, "ONEPORT_NGHTTP2_USED"),
        "binaries": {name: window.sha256_file(build / rel) for name, rel in
                     (("oneport", "bench/server/oneport.exe"), ("opgen", "bench/gen/opgen.exe"))},
        "pins_sha256": window.sha256_file(src / "bench" / "cmake" / "pins.cmake"),
        "runner_sha256": {n: window.sha256_file(HERE / n) for n in ("wwindow.py", "wsys.py", "wpower.py", "waa.py", "wjob.py", "window.py")},
        "windows": platform.platform(),
        "python": sys.version.split()[0],
    }
    tool = PAPERS_LAB_BIN / "inputs_hash.py"
    if tool.exists():
        out = build.parent / f"{build.name}.inputs.json"
        r = subprocess.run([sys.executable, str(tool), "--build", f"oneport={build}", "--target", "oneport", "--target", "opgen",
                            "--config-key", "CMAKE_BUILD_TYPE", "--config-key", "ONEPORT_SANITIZER", "--root-label", "oneport",
                            "--out", str(out)], capture_output=True, text=True)
        if r.returncode == 0:
            info = json.loads(out.read_text())
            p["inputs_hash"] = {t: v["inputs_hash"] for t, v in info["builds"]["oneport"]["targets"].items()} \
                if "builds" in info else info.get("inputs_hash")
            p["inputs_hash_tool_sha256"] = window.sha256_file(tool)
        else:
            p["inputs_hash_error"] = (r.stderr or r.stdout)[-300:]
    return p


def parse_cells(spec: str) -> list[dict]:
    cells = []
    for item in spec.split(","):
        w, p = item.split(":")
        if w not in wwindow.WORKLOADS or p not in wwindow.PROTOS:
            raise SystemExit(f"bad cell {item!r}")
        cells.append({"workload": w, "proto": p, "backend": "IOCP", "cell": f"{w}.{p}.IOCP"})
    return cells


def stop_on_signals() -> None:
    """Ctrl+C, Ctrl+Break (wjob.py sends it to stop a job) and SIGTERM end the runner through
    SystemExit, so every finally block runs and stops the server it started (by its event)."""
    import signal

    def handler(signum, _frame):
        raise SystemExit(128 + signum)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), handler)


def functional_summary(rows: list[dict]) -> dict:
    """A functional check's summary: windows and their validity per cell, no ratio (its windows
    are short and off the frozen layout, so they are not timed windows)."""
    out: dict[str, dict] = {}
    for r in rows:
        c = out.setdefault(r["cell"], {"windows": 0, "valid": 0, "invalid": []})
        c["windows"] += 1
        if r.get("valid"):
            c["valid"] += 1
        else:
            c["invalid"].append({"tag": r.get("tag"), "reasons": r.get("invalid_reasons")})
    return out


def main(argv=None) -> int:
    stop_on_signals()
    if sys.platform == "win32":
        wwindow.wsys.watch_stop()  # wjob.py stop: KeyboardInterrupt here, and each finally stops its server
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--cells", required=True)
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--seed", type=int, required=True, help="the development order's seed, recorded in the journal")
    ap.add_argument("--k-src", type=int, required=True)
    ap.add_argument("--port-a", type=int, default=aa.PORT_A)
    ap.add_argument("--port-offset", type=int, default=aa.PORT_OFFSET)
    ap.add_argument("--blocks", type=Path, default=wwindow.STATE_DIR / "src-blocks-w.json")
    ap.add_argument("--rates", type=Path, help="rates.json of an earlier job: the open-loop rate per proto.IOCP")
    ap.add_argument("--functional", action="store_true", help="a functional check: short windows, flagged, not timed windows")
    ap.add_argument("--warmup-ms", type=int, default=200)
    ap.add_argument("--duration-ms", type=int, default=500)
    a = ap.parse_args(argv)
    if os.environ.get("ONEPORT_W_FUNCTIONAL") == "1" and not a.functional:
        raise SystemExit("this W job did not pass the quiet check (wjob.py --allow-noisy): it runs functional checks only (--functional)")
    a.out.mkdir(parents=True, exist_ok=True)
    wwindow.wsys.set_own_affinity(wwindow.HOUSEKEEPING)  # the runner and its samplers on core 0 (CPUs 0 and 1)
    cells = parse_cells(a.cells)
    prov = provenance(a.build)
    prov["functional_check"] = a.functional
    (a.out / "provenance.json").write_text(json.dumps(prov, indent=1))
    blocks = window.SourceBlocks(a.blocks)
    rng = random.Random(a.seed)
    first = [c for c in cells if c["workload"] != "open"]
    later = [c for c in cells if c["workload"] == "open"]
    rows_path = a.out / "windows.jsonl"
    rows: list[dict] = []
    rates: dict[tuple[str, str], float] = {}

    def run_order(group: list[dict]) -> None:
        order = [(c, s) for c in group for s in range(1, a.sessions + 1)]
        rng.shuffle(order)
        for c, s in order:
            cfg = dict(c, build=a.build, k_src=a.k_src, ports={"A": a.port_a, "B": a.port_a + a.port_offset}, functional=a.functional,
                       warmup_ms=a.warmup_ms, duration_ms=a.duration_ms)
            if c["workload"] == "open":
                cfg["rate"] = rates[(c["proto"], c["backend"])]
            fp = wwindow.fingerprint()
            sid = f"{c['cell']}-s{s:02d}"
            x = rng.choice(["A", "B"])
            y = "B" if x == "A" else "A"
            session = {"job": a.job, "id": sid, "fingerprint": fp, "x": x, "lab_plan": fp["lab_plan"], "frequency": fp["frequency"],
                       "cycle_rate": fp.get("cycle_rate")}
            if not fp.get("pinned"):
                print(f"{sid}: host not as W's procedure sets it: power {fp['power']['problems']}, cores {fp['core_problems']}", flush=True)
            for pos, arm in enumerate([x, y, y, x]):
                r = wwindow.run_window(cfg, session, arm, pos, blocks, a.out / "raw")
                r["provenance"] = prov
                r["fingerprint"] = fp
                r["seed"] = a.seed
                rows.append(r)
                with open(rows_path, "a") as f:
                    f.write(json.dumps(r) + "\n")
                print(f"{sid} p{pos} {arm}: {r.get('metric', {}).get('value', 0):.1f} valid={r.get('valid')} "
                      f"{'; '.join(r.get('invalid_reasons', []))}", flush=True)

    given = {tuple(k.split(".")): v for k, v in json.loads(a.rates.read_text()).items()} if a.rates else {}
    run_order(first)
    for c in later:
        key = (c["proto"], c["backend"])
        if key in given:
            rates[key] = given[key]
            continue
        by: dict[str, list[float]] = {}
        for r in rows:
            if r["cell"] == f"churn.{c['proto']}.IOCP" and r.get("valid"):
                by.setdefault(r["session"], []).append(r["metric"]["value"])
        means = [statistics.fmean(v) for v in by.values() if len(v) == 4]
        if not means:
            raise SystemExit(f"open loop {c['cell']}: no valid churn session of {c['proto']} on IOCP in this job")
        rates[key] = aa.RATE_FRAC * statistics.median(means)
    (a.out / "rates.json").write_text(json.dumps({f"{p}.{b}": v for (p, b), v in rates.items()}))
    run_order(later)
    if a.functional:
        summary = functional_summary(rows)
        for cell, s in summary.items():
            print(f"{cell}: {s['valid']} of {s['windows']} functional windows valid")
    else:
        summary = aa.summarise(rows)
        for cell, s in summary.items():
            m = s["metric"]
            print(f"{cell}: sessions {s['sessions']}, valid ratios {m['n']}, invalid windows {len(s['invalid_windows'])}")
    (a.out / "summary.json").write_text(json.dumps({"job": a.job, "functional_check": a.functional,
                                                    "rates": {f"{p}.{b}": v for (p, b), v in rates.items()}, "cells": summary}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
