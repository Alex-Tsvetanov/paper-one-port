#!/usr/bin/env python3
"""The quick-benchmark plans of P3 (quick-plan.md; decisions d006 and d007, option E): 22 plans under
bench/run/plans/quick/, each one campaign of at most 600 s.

    quick_plans.py            write the plans to bench/run/plans/quick/
    quick_plans.py --check    exit 1 if a file there differs from what this script makes

A plan names its host, kind, cells, arms, R, the job warm-up and the worst-case seconds. quick_run.py runs
a plan only when the sha256 given on its command line equals the plan file's, and only when the plan is
what this script makes (quick_guard.py). Standard library only, apart from sessions.py (also standard
library).

Sizing. The session engine (sessions.py) runs a job warm-up of JOB_WARMUP_S before the first session; the
window that runs when the time is up completes, so the warm-up costs at most JOB_WARMUP_S plus one window. A
session is four windows (X Y Y X). The frozen rule allows ceil(R/4) reruns of invalid sessions per cell
(sessions.rerun_cap). So a campaign of c cells at R fits when

    job warm-up + one window + fingerprint + c * (R + ceil(R/4)) * session <= 600 s        (the worst case)
    job warm-up + one window + fingerprint + c * R * session           <= 600 s        (no rerun, always smaller)

R is the largest count for which the worst case fits. A window is the 1 s warm-up and the 5 s measured
window plus start, probe and stop: 6.3 s on both OSes (design/status.md, 47 consecutive windows, 294 s on L;
the laptop's W probe minimum is 6.19 s). A session also reads its fingerprint (7.27 s on W, hypotheses.md section 12), once per
session and once before the warm-up. Cells that need a pilot value take it from the committed pilot entry output
(lab/analysis-inputs), read only.

The hard-case plans run no sessions. Their time is the measured time of the long runs scaled to the
replicates and entries chosen, with the fixed runs of each variant counted (hard_case_worst_case_s).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sessions  # noqa: E402

PLANS = HERE / "plans"
OUT = PLANS / "quick"
SCHEMA = 1
CAMPAIGN_S = 600.0
JOB_WARMUP_S = float(sessions.JOB_WARMUP_S)
WARMUP_MS = 1000
DURATION_MS = 5000
WINDOWS_PER_SESSION = 4
# A window's length in seconds: 1 s + 5 s, and the start, the probe and the stop.
WINDOW_S = {"L": 6.3, "W": 6.3}
# The session's fingerprint (hypotheses.md section 12): sessions.py reads it once per session and once before the warm-up.
# On L pin.sh is quick; on W it takes 7.27 s.
FINGERPRINT_S = {"L": 0.0, "W": 7.27}
PROTOS = ("http1", "h2c", "tls", "mqtt")
M1_PROTOS = ("http1", "h2c")
HOSTS = {"L": "linux", "W": "windows"}
# rule E's proposed defaults (runlib.PROPOSED_RULE_E), the same in both committed rule_e.json files.
DETECT = "replay"
OTHER_DETECT = "peek"
BACKEND_NAME = {"epoll": "epoll", "uring": "io_uring", "iocp": "IOCP"}
SEED_NAMES = {("cost", "L"): "SEED_ORDER_C_L", ("cost", "W"): "SEED_ORDER_C_W", ("m1", "L"): "SEED_ORDER_M_L",
              ("aa", "L"): "SEED_PILOT_L", ("aa", "W"): "SEED_PILOT_W"}

# The hard cases (hypotheses.md 5.2, Appendix A): 25 cases, 164 variants per entry, 16 replicates in the long
# design. Measured long runs: L's hl1, 4,850 s for 8 entries (design/status.md, 14:35:23 less 13:14:33); W's wh1,
# 1,475 s for 2 entries (02:53:16 less 02:28:41). The gap84 queue files expect 2,500 s for L's 4 io_uring entries
# (625 s per entry) and 1,400 s for W's 2. The larger per-entry figure is used.
HARD_LONG_R = 16
HARD_FIXED_RUNS = 2   # a variant's dedicated reference runs (its reply and its HTTP/1.1 reply): at most 2 beyond its replicates
HARD_VARIANTS_PER_ENTRY = 164
HARD_LONG_S_PER_ENTRY = {"L": max(4850 / 8, 2500 / 4), "W": max(1475 / 2, 1400 / 2)}
HARD_ENTRIES = {
    "L": ("epoll.replay.inproc", "epoll.peek.inproc", "io_uring.replay.inproc", "io_uring.peek.inproc"),
    "W": ("IOCP.replay.inproc", "IOCP.peek.inproc"),
}
# G and GAP_SPLIT come from the committed pilot entry output, read only (tests check these copies against it).
HARD_PILOT = {
    "L": {"source": "lab/analysis-inputs/pilot.json", "G_ms": 4, "hc7_runs": True, "gap_split_ms": 5},
    "W": {"source": "lab/analysis-inputs/laptop-w/pilot.json", "G_ms": 16, "hc7_runs": True, "gap_split_ms": 5},
}


def window_s(host: str) -> float:
    return WINDOW_S[host]


def session_s(host: str) -> float:
    return WINDOWS_PER_SESSION * window_s(host) + FINGERPRINT_S[host]


def warmup_cost_s(host: str) -> float:
    """The job warm-up at its longest: JOB_WARMUP_S, the window that completes after it and the fingerprint read before it."""
    return JOB_WARMUP_S + window_s(host) + FINGERPRINT_S[host]


def worst_case_s(host: str, cells: int, r: int) -> float:
    """The warm-up plus every cell's R sessions and its full allowance of reruns."""
    return warmup_cost_s(host) + cells * (r + sessions.rerun_cap(r)) * session_s(host)


def nominal_s(host: str, cells: int, r: int) -> float:
    """The warm-up plus R sessions per cell, no rerun."""
    return warmup_cost_s(host) + cells * r * session_s(host)


def fit_r(host: str, cells: int = 1) -> int:
    r = 1
    while worst_case_s(host, cells, r + 1) <= CAMPAIGN_S:
        r += 1
    if worst_case_s(host, cells, r) > CAMPAIGN_S:
        raise ValueError("not even one session fits")
    return r


def hard_case_worst_case_s(host: str, entries: int, r: int) -> float:
    """The long run's time per entry, scaled by (R + fixed runs) / (16 + fixed runs). Each variant costs its
    R replicate runs and at most HARD_FIXED_RUNS reference runs, and a fixed run is not smaller than the
    others in its variant, so (R + f) / (16 + f) with f = HARD_FIXED_RUNS is an upper bound for the shorter run."""
    return entries * HARD_LONG_S_PER_ENTRY[host] * (r + HARD_FIXED_RUNS) / (HARD_LONG_R + HARD_FIXED_RUNS)


def fit_hard_r(host: str, entries: int) -> int:
    r = 0
    while hard_case_worst_case_s(host, entries, r + 1) <= CAMPAIGN_S:
        r += 1
    if r < 1:
        raise ValueError("not even one replicate fits")
    return r


def _common(host: str, kind: str, name: str, about: str, uring: bool) -> dict:
    return {"schema": SCHEMA, "name": name, "host": host, "os": HOSTS[host], "kind": kind, "uring_job": uring, "about": about}


def _sessions_block(host: str, cells: int, r: int) -> dict:
    return {
        "r": r, "rerun_cap": sessions.rerun_cap(r), "session_order": "X Y Y X", "arms_order": "a new random order each round (sessions.make_plan)",
        "job_warmup_s": JOB_WARMUP_S, "warmup_ms": WARMUP_MS, "duration_ms": DURATION_MS, "window_s": window_s(host),
        "session_s": round(session_s(host), 3), "sessions_no_rerun": cells * r,
        "sessions_worst_case": cells * (r + sessions.rerun_cap(r)),
        "expected_no_rerun_s": round(nominal_s(host, cells, r), 3), "expected_worst_case_s": round(worst_case_s(host, cells, r), 3),
        "limit_s": CAMPAIGN_S,
    }


def cost_plan(host: str, key: str, backend: str, hyp: str, proto: str) -> tuple[str, dict]:
    stem = f"quick-{host}-{key}-{hyp.lower()}-{proto}"
    cell = f"{hyp}.{host}.{backend}.{proto}"
    r = fit_r(host)
    workload = "churn" if hyp == "C1" else "keepalive"
    about = (f"Quick {hyp} {workload}, {backend} on {host}, {proto}: one-port mode against dedicated mode, in-process dispatch "
             f"(quick-plan.md, decisions d006 and d007). R {r}, job warm-up {int(JOB_WARMUP_S)} s.")
    plan = _common(host, "cost", stem, about, backend == "io_uring")
    plan.update(backend=backend, hyp=hyp, workload=workload, proto=proto, detect=DETECT, dispatch="inproc",
                cells=[{"id": cell, "r": r}],
                arms={"A": f"one-port mode, detection mode {DETECT} (rule E's proposed default for {backend}), in-process dispatch",
                      "B": "dedicated mode, the same binary, in-process dispatch"},
                seed_name=SEED_NAMES[("cost", host)])
    plan.update(_sessions_block(host, 1, r))
    return stem, plan


def m1_plan(proto: str) -> tuple[str, dict]:
    host, backend = "L", "epoll"
    stem = f"quick-L-epoll-m1-{proto}"
    r = fit_r(host)
    about = (f"Quick M1, epoll on L, {proto} churn: the default detection mode against the other, both one-port mode, "
             f"in-process dispatch (quick-plan.md). R {r}, job warm-up {int(JOB_WARMUP_S)} s.")
    plan = _common(host, "m1", stem, about, False)
    plan.update(backend=backend, hyp="M1", workload="churn", proto=proto, detect=DETECT, dispatch="inproc",
                cells=[{"id": f"M1.L.{backend}.{proto}", "r": r}],
                arms={"A": f"one-port mode, detection mode {DETECT} (rule E's proposed default for epoll)",
                      "B": f"one-port mode, detection mode {OTHER_DETECT} (the other)"},
                seed_name=SEED_NAMES[("m1", host)])
    plan.update(_sessions_block(host, 1, r))
    return stem, plan


def aa_plan(host: str) -> tuple[str, dict]:
    backend = "epoll" if host == "L" else "IOCP"
    stem = f"quick-{host}-aa"
    r = fit_r(host)
    about = (f"Quick A/A noise run, {host}: HTTP/1.1 keep-alive on {backend}, dedicated mode against dedicated mode, the same binary "
             f"on ports 20000 and 20100 (the arms of aa.py and waa.py) (quick-plan.md). R {r}, job warm-up {int(JOB_WARMUP_S)} s.")
    plan = _common(host, "aa", stem, about, False)
    plan.update(backend=backend, hyp="AA", workload="keepalive", proto="http1", detect=DETECT, dispatch="inproc",
                cells=[{"id": f"AA.{host}.{backend}.http1.keepalive", "r": r}],
                arms={"A": "dedicated mode, ports from 20000", "B": "dedicated mode, the same binary, ports from 20100"},
                seed_name=SEED_NAMES[("aa", host)])
    plan.update(_sessions_block(host, 1, r))
    return stem, plan


def hard_plan(host: str) -> tuple[str, dict]:
    stem = f"quick-{host}-hard"
    entries = HARD_ENTRIES[host]
    r = fit_hard_r(host, len(entries))
    worst = hard_case_worst_case_s(host, len(entries), r)
    about = (f"Quick hard cases (B1 and B2), {host}: all 25 cases, {len(entries)} entries, {r} replicates "
             f"(quick-plan.md). Worst case {worst:.0f} s by the scaling of the long run's measured time.")
    plan = _common(host, "hard", stem, about, False)
    plan.update(backend=("IOCP" if host == "W" else "epoll and io_uring"), cases=list(range(1, 26)), entries=list(entries), r=r,
                replicates=r, long_replicates=HARD_LONG_R, fixed_runs=HARD_FIXED_RUNS,
                variants_per_entry=HARD_VARIANTS_PER_ENTRY, long_s_per_entry=round(HARD_LONG_S_PER_ENTRY[host], 3),
                long_basis=("L: hl1 4,850 s for 8 entries and the gap84 expectation 2,500 s for 4; "
                            "W: wh1 1,475 s for 2 entries and the gap84 expectation 1,400 s; the larger per-entry figure"),
                pilot=HARD_PILOT[host], detect_default=DETECT, relay_copy="user-space",
                expected_worst_case_s=round(worst, 3), expected_no_rerun_s=round(worst, 3), limit_s=CAMPAIGN_S, job_warmup_s=0)
    return stem, plan


def build_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key, host, backend in (("L-epoll", "L", "epoll"), ("L-uring", "L", "io_uring"), ("W-iocp", "W", "IOCP")):
        hyps = ("C2", "C1") if key == "L-epoll" else ("C2",)
        for hyp in hyps:
            for proto in PROTOS:
                k = key.split("-", 1)[1]
                stem, plan = cost_plan(host, k, backend, hyp, proto)
                out[stem] = plan
    for proto in M1_PROTOS:
        stem, plan = m1_plan(proto)
        out[stem] = plan
    for host in ("L", "W"):
        stem, plan = aa_plan(host)
        out[stem] = plan
    for host in ("L", "W"):
        stem, plan = hard_plan(host)
        out[stem] = plan
    return out


def render(plan: dict) -> str:
    return json.dumps(plan, indent=1) + "\n"


def sha256_of(plan: dict) -> str:
    return hashlib.sha256(render(plan).encode("utf-8")).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    plans = build_all()
    OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    for name, plan in plans.items():
        path = OUT / f"{name}.json"
        text = render(plan)
        if args.check:
            if not path.exists() or path.read_bytes() != text.encode("utf-8"):
                print(f"differs: {path}")
                bad += 1
        else:
            path.write_bytes(text.encode("utf-8"))
        print(f"{name}: R {plan['r'] if plan['kind'] == 'hard' else plan['cells'][0]['r']}, "
              f"no rerun {plan['expected_no_rerun_s']:.0f} s, worst case {plan['expected_worst_case_s']:.0f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
