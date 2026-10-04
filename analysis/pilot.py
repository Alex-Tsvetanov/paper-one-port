#!/usr/bin/env python3
"""The pilot entry's outputs (hypotheses.md 4.6, 8 step 5, 9.2) from the A/A pilot's rows alone.

    pilot.py --seeds SEEDS.json --gate GATE.json [--gate ...] --rows WINDOWS.jsonl [...]
             --parts PARTS.jsonl [...] --out PILOT.json [--workers N]

It computes, by the frozen rules and nothing else:
- per cost cell (6.1, c = 1 to 36): the pilot's sessions, valid and invalid, and when the cell has
  P = 16 valid sessions, Power_c(R) at each candidate R (4.6 steps 2 to 4) and its own R_c;
- the resolved list (step 5), R_C (step 6), m_C and the joint power of each protocol, backend
  and host whose C1, C2 and C3 cells are all resolved (step 7). A cell that a logged decision put
  outside the confirmatory family (cells.COST_OUTSIDE_FAMILY: W's churn h2c and churn MQTT, the
  revision log's entry "W before the code freeze", item 1) is simulated like every cost cell but
  never resolved, with its reason, so it sets neither R_C nor m_C: the entry says the two cells
  leave the family as a cell that is not resolved leaves it, and 4.6 step 6 takes R_C over the
  resolved cells;
- lambda for each C3 cell (WL2), from the C1 pilot sessions;
- G_L and G_W from the timer part, and GAP_SPLIT from the split part (8 step 4, 9.2).

What it refuses: a row in one-port mode, or of any mode but dedicated (the pilot "holds no
one-port data", 4.6 step 1); a dry-run row; a synthetic row unless --allow-synthetic; a row that
bench/check_rows.py refuses against the gates (rule D5: R_C, lambda and G are cited); a row whose
order seed is not SEED_PILOT_L or SEED_PILOT_W for its host; rows on numpy other than the pinned
version (requirements.txt). The pilot is development data (4.6 step 1, design/proposal.md ST13),
so rows marked development are taken.

The pilot's rows are bench/run/aa.py's (window.py's rows plus provenance, fingerprint and seed):
arm "A" is the first start of the binary and arm "B" the second, on the port offset; the session
ratio is B / A, as aa.py computes it (a reading: 4.6 names no direction, and aa.py's is the one
the A/A development runs used). The parts' rows are defined here, as no runner writes them yet:
  timer  {"part": "timer", "backend", "mode": "dedicated", "run", "valid", "invalid_reasons",
          "lateness_ns": the time from T_hdr's deadline to the start of the loop pass that
          handled it, from the server's counters (I29)}
  split  {"part": "split", "backend", "mode": "dedicated", "gap_ms", "replicate", "valid",
          "invalid_reasons", "recv_data": the receives of the one connection that returned
          payload}
with the gate's provenance.binaries as every row.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cells as C  # noqa: E402
import rows as RW  # noqa: E402
import stats as S  # noqa: E402
import versions  # noqa: E402

# ---------------------------------------------------------------- frozen constants (4.6, 8, 9.2)

P = 16                      # 4.6 step 1: every cost cell runs P = 16 pilot sessions
CANDIDATES = (11, 15, 18, 22, 25, 28, 31)   # 4.6 step 4
DRAWS_PER_RUN = 31          # 4.6 step 3: 31 indices with replacement, then 31 normal draws
N_SIM = 1_000               # 4.6 step 2
POWER_TARGET = Fraction(4, 5)   # 4.6 step 5: Power_c(31) >= 0.80, a design choice of the frozen text
THRESHOLD = S.ALPHA / 36    # 4.6 step 2: both p-values at most alpha/36 = 6.94e-4
CHI2_Q = 0.20               # 4.6 step 2: the 0.20 quantile of chi-square with P - 1 degrees of freedom
RATE_FRAC = 0.5             # WL2: RATE_FRAC = 0.5
T_FB_MS = 3000              # section 1: T_fb = 3 s
GAPS_MS = (5, 10, 20, 50, 100)   # 8 step 4: the tested gaps
GAP_FALLBACK_MS = 100       # 9.2: "if none does, 100 ms"
PILOT_ROLES = ("B", "A")    # aa.py: the session ratio is B / A
PILOT_ORDER_SEED = {"L": "SEED_PILOT_L", "W": "SEED_PILOT_W"}
SPLIT_BACKENDS = ("epoll", "io_uring", "IOCP")   # "every backend of L and W" (9.2)


class PilotRefused(RW.RowsRefused):
    pass


# ---------------------------------------------------------------- reading the pilot's rows


def pilot_info(row: dict) -> tuple[str, RW.Info]:
    """aa.py's rows: cell from workload, proto and backend; role = the arm label; dedicated only."""
    mode = row.get("mode")
    if mode is not None and mode != "dedicated":
        raise PilotRefused(f"{RW.where(row)}: mode {mode!r}; the pilot holds no one-port data (4.6 step 1)")
    if mode is None and row.get("valid"):
        raise PilotRefused(f"{RW.where(row)}: a valid row that names no mode")
    inf = RW.info_cost_like(row, {})
    arm = str(row.get("arm"))
    if arm not in PILOT_ROLES:
        raise PilotRefused(f"{RW.where(row)}: arm {arm!r}, not A or B")
    return "C", RW.Info(inf.fields, arm)


def check_part_rows(parts: list[dict]) -> None:
    for r in parts:
        if r.get("part") not in ("timer", "split"):
            raise PilotRefused(f"a part row with part {r.get('part')!r}")
        if r.get("mode") != "dedicated":
            raise PilotRefused(f"{r.get('part')} row {r.get('run', r.get('replicate'))}: mode {r.get('mode')!r}, "
                               "not dedicated (8 step 4)")
        C.host_of(r.get("backend"))


def check_order_seeds(rows: list[dict], seeds: dict) -> None:
    """Every window of the pilot ran in the order of SEED_PILOT_L or SEED_PILOT_W (8 step 4)."""
    for r in rows:
        backend = r.get("backend")
        if backend is None:
            continue
        want = seeds[PILOT_ORDER_SEED[C.host_of(backend)]]
        if r.get("seed") != want:
            raise PilotRefused(f"{RW.where(r)}: order seed {r.get('seed')!r}, not {PILOT_ORDER_SEED[C.host_of(backend)]}")


# ---------------------------------------------------------------- the simulation (4.6 steps 2 and 3)


def cell_model(ratios: list[float]) -> dict:
    """4.6 step 2 on the P session ratios of one cell: e_i = y_i - median(y), s, b and s_U."""
    y = np.log(np.asarray(ratios, dtype=float))
    e = y - np.median(y)
    s = float(np.std(e, ddof=1))
    if s > 0:
        b = S.silverman_factor(e, s)
        z = e / s
    else:  # every session the same ratio: the simulated sessions are all exp(0) (a design choice)
        b, z = 0.0, np.zeros_like(e)
    q = S.chi2_ppf(CHI2_Q, len(e) - 1)
    s_u = s * math.sqrt((len(e) - 1) / q)
    return {"e": e, "s": s, "b": b, "s_u": s_u, "z": z, "q": q}


def run_draws(seed_sim: int, c: int, j: int, b: float) -> tuple[np.ndarray, np.ndarray]:
    """4.6 step 3: run j of cell c draws from one stream seeded by (SEED_SIM, c, j): first 31
    indices with replacement, then 31 normal draws (standard deviation b)."""
    rng = np.random.default_rng([seed_sim, c, j])
    idx = rng.integers(0, P, size=DRAWS_PER_RUN)
    nrm = rng.normal(0.0, b, size=DRAWS_PER_RUN)
    return idx, nrm


def simulate_cell(args: tuple) -> dict[int, int]:
    """Power_c(R) as a count of passing runs out of n_sim, for each candidate R. Run j at
    candidate R takes the first R sessions of run j's draws (common random numbers), scaled by
    s_U / sqrt(1 + b^2), and is analysed by stats.cost_run_passes, the confirmatory code; its BCa
    resamples come from the stream (SEED_SIM, c, j, R)."""
    seed_sim, c, ratios, n_sim, candidates = args
    m = cell_model(ratios)
    scale = m["s_u"] / math.sqrt(1.0 + m["b"] * m["b"])
    counts = {r: 0 for r in candidates}
    for j in range(1, n_sim + 1):
        idx, nrm = run_draws(seed_sim, c, j, m["b"])
        for r in candidates:
            vals = np.exp(scale * (m["z"][idx[:r]] + nrm[:r]))

            def draws_for(r=r, j=j):
                return S.draw_clusters(np.random.default_rng([seed_sim, c, j, r]), r)

            counts[r] += S.cost_run_passes(vals, draws_for, THRESHOLD)
    return counts


def powers(cell_ratios: dict[int, list[float]], seed_sim: int, n_sim: int = N_SIM, workers: int = 1,
           candidates: tuple[int, ...] = CANDIDATES) -> dict[int, dict[int, int]]:
    """Pass counts per cell c and candidate R. The result is the same for any worker count: each
    cell's streams depend only on (SEED_SIM, c, j, R) (4.6 step 3)."""
    jobs = [(seed_sim, c, cell_ratios[c], n_sim, candidates) for c in sorted(cell_ratios)]
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            res = list(ex.map(simulate_cell, jobs))
    else:
        res = [simulate_cell(a) for a in jobs]
    return {c: r for c, r in zip(sorted(cell_ratios), res, strict=True)}


# ---------------------------------------------------------------- the rule (4.6 steps 5 to 7)


def meets(count: int, n_sim: int) -> bool:
    return Fraction(count, n_sim) >= POWER_TARGET


def outside_numbers() -> set[int]:
    """The cell numbers c of cells.COST_OUTSIDE_FAMILY (6.1's numbering: c = 10 and 12)."""
    return {c.number for c in C.cost_cells() if c.id in C.COST_OUTSIDE_FAMILY}


def decide(cells_valid: dict[int, bool], counts: dict[int, dict[int, int]], n_sim: int,
           candidates: tuple[int, ...] = CANDIDATES) -> dict:
    """Steps 5 to 7: resolved = P valid sessions and Power_c(31) >= 0.80, never a cell outside the
    family by a logged decision (cells.COST_OUTSIDE_FAMILY); R_c each resolved cell's smallest
    candidate meeting the target; R_C the smallest candidate at which every resolved cell meets it
    (31 when none is resolved); m_C the number resolved."""
    top = max(candidates)
    outside = outside_numbers()
    resolved = [c for c in sorted(counts) if cells_valid.get(c) and c not in outside and meets(counts[c][top], n_sim)]
    own = {c: next(r for r in candidates if meets(counts[c][r], n_sim)) for c in resolved}
    if resolved:
        r_c = next(r for r in candidates if all(meets(counts[c][r], n_sim) for c in resolved))
    else:
        r_c = top
    return {"resolved": resolved, "own_r": own, "R_C": r_c, "m_C": len(resolved)}


def joint_powers(resolved: list[int], counts: dict[int, dict[int, int]], r_c: int, n_sim: int) -> list[dict]:
    """Step 7: for each protocol, backend and host whose C1, C2 and C3 cells are all resolved,
    the product of their three Power_c(R_C)."""
    by_id = {c.number: c for c in C.cost_cells()}
    out = []
    for backend in C.COST_BACKENDS:
        for proto in C.COST_PROTOS:
            trio = [c.number for c in by_id.values() if c.backend == backend and c.proto == proto]
            if all(c in resolved for c in trio):
                fr = Fraction(1)
                for c in trio:
                    fr *= Fraction(counts[c][r_c], n_sim)
                out.append({"host": C.host_of(backend), "backend": backend, "proto": proto, "cells": trio,
                            "power_exact": f"{fr.numerator}/{fr.denominator}", "power": float(fr)})
    return out


# ---------------------------------------------------------------- lambda, G and GAP_SPLIT


def rates(sessions: list[RW.Session]) -> dict[str, dict]:
    """WL2: lambda = RATE_FRAC x the median, over the pilot's valid C1 sessions of the same
    protocol and backend, of the session's mean connections per second: the mean of its four
    windows, as aa.py computes it (a reading)."""
    out = {}
    for c3 in (c for c in C.cost_cells() if c.hyp == "C3"):
        c1 = f"C1.{c3.host}.{c3.backend}.{c3.proto}"
        means = [statistics.fmean(RW.metric_value(w, "conn_per_s") for w in s.windows)
                 for s in sessions if s.cell == c1 and s.valid]
        entry = {"c1_cell": c1, "sessions": len(means)}
        if means:
            med = statistics.median(means)
            entry.update(median_conn_per_s=med, rate=RATE_FRAC * med)
        else:
            entry.update(median_conn_per_s=None, rate=None)
        ran = sorted({w.get("rate") for s in sessions if s.cell == c3.id for w in s.windows if w.get("rate") is not None})
        entry["rates_the_pilot_c3_sessions_ran"] = ran
        out[c3.id] = entry
    return out


def g_values(parts: list[dict]) -> dict[str, dict]:
    """9.2: per host, the smallest whole number of milliseconds above the largest lateness of the
    timer part's valid runs over all the host's backends. No valid run, or G not below T_fb: HC7 is
    not run on that host."""
    out = {}
    for host in ("L", "W"):
        runs = [r for r in parts if r.get("part") == "timer" and C.host_of(r["backend"]) == host]
        valid = [r for r in runs if r.get("valid")]
        excluded = [{"backend": r["backend"], "run": r.get("run"), "reasons": list(r.get("invalid_reasons") or [])}
                    for r in runs if not r.get("valid")]
        entry: dict = {"runs": len(runs), "valid_runs": len(valid), "excluded": excluded,
                       "valid_runs_by_backend": {b: sum(1 for r in valid if r["backend"] == b)
                                                 for b in sorted({r["backend"] for r in runs})}}
        if not runs:
            entry.update(G_ms=None, hc7_runs=False, why="no timer run of this host in the input")
        elif not valid:
            entry.update(G_ms=None, hc7_runs=False, why="no valid timer run (8 step 4)")
        else:
            worst = max(int(r["lateness_ns"]) for r in valid)
            g = worst // 1_000_000 + 1
            entry.update(max_lateness_ns=worst, G_ms=g, hc7_runs=g < T_FB_MS,
                         why=None if g < T_FB_MS else "G is not below T_fb (9.2)")
        out[host] = entry
    return out


def gap_split(parts: list[dict]) -> dict:
    """9.2: the smallest tested gap at which every valid replicate on every backend of L and W
    shows the split read (two receives that returned payload), each backend having at least one
    valid replicate at that gap; if none does, 100 ms, and HC2, HC3 and HC10 report the share of
    their replicates that split. A host with no split row at all leaves it not computable."""
    reps = [r for r in parts if r.get("part") == "split"]
    hosts = {C.host_of(r["backend"]) for r in reps}
    table = []
    for g in GAPS_MS:
        row = {"gap_ms": g}
        ok = True
        for b in SPLIT_BACKENDS:
            at = [r for r in reps if r["backend"] == b and int(r.get("gap_ms", -1)) == g]
            v = [r for r in at if r.get("valid")]
            shows = sum(1 for r in v if int(r.get("recv_data", 0)) >= 2)
            row[b] = {"replicates": len(at), "valid": len(v), "split": shows,
                      "excluded": [{"replicate": r.get("replicate"), "reasons": list(r.get("invalid_reasons") or [])}
                                   for r in at if not r.get("valid")]}
            ok = ok and len(v) >= 1 and shows == len(v)
        row["qualifies"] = ok
        table.append(row)
    if hosts != {"L", "W"}:
        return {"GAP_SPLIT_ms": None, "computable": False, "why": f"split rows of hosts {sorted(hosts)}; both L and W are needed",
                "table": table}
    q = [r["gap_ms"] for r in table if r["qualifies"]]
    if q:
        return {"GAP_SPLIT_ms": q[0], "computable": True, "fallback": False, "table": table}
    return {"GAP_SPLIT_ms": GAP_FALLBACK_MS, "computable": True, "fallback": True,
            "why": "no tested gap qualifies; HC2, HC3 and HC10 report the share of their replicates that split", "table": table}


# ---------------------------------------------------------------- the whole entry


def cell_sessions(sessions: list[RW.Session]) -> dict[str, list[RW.Session]]:
    out: dict[str, list[RW.Session]] = {}
    for s in sessions:
        out.setdefault(s.cell, []).append(s)
    return out


def pilot_entry(rows: list[dict], parts: list[dict], seeds: dict, *, n_sim: int = N_SIM, workers: int = 1) -> dict:
    """Every output of the pilot entry that the rows determine (9.2), as one JSON-ready dict."""
    for r in rows:
        if r.get("part") is not None:
            raise PilotRefused("a part row among the windows")
    check_part_rows(parts)
    check_order_seeds(rows, seeds)
    sessions = RW.assemble(rows, pilot_info, lambda kind, cid: PILOT_ROLES)
    by_cell = cell_sessions(sessions)
    cells_out = []
    ratios: dict[int, list[float]] = {}
    valid_ok: dict[int, bool] = {}
    for cell in C.cost_cells():
        ss = sorted(by_cell.get(cell.id, []), key=lambda s: (s.job, s.id))
        good = [s for s in ss if s.valid]
        if len(good) > P:
            raise PilotRefused(f"{cell.id}: {len(good)} valid sessions, more than P = {P}")
        vals = [RW.session_ratio(s, "B", "A", "metric", cell.metric) for s in good]
        entry = {"c": cell.number, "cell": cell.id, "sessions": len(ss), "valid_sessions": len(good),
                 "invalid_windows": RW.invalid_windows(ss), "ratios": vals}
        if len(good) == P and all(v is not None and v > 0 for v in vals):
            ratios[cell.number] = vals
            valid_ok[cell.number] = True
            m = cell_model(vals)
            entry.update(s=m["s"], b=m["b"], s_u=m["s_u"])
        else:
            valid_ok[cell.number] = False
            entry["why_not_simulated"] = f"{len(good)} valid sessions with a ratio, P = {P} needed (4.6 step 5)"
        cells_out.append(entry)
    counts = powers(ratios, seeds["SEED_SIM"], n_sim=n_sim, workers=workers)
    rule = decide(valid_ok, counts, n_sim)
    for e in cells_out:
        c = e["c"]
        if c in counts:
            e["pass_counts"] = {str(r): counts[c][r] for r in CANDIDATES}
            e["power"] = {str(r): counts[c][r] / n_sim for r in CANDIDATES}
        e["resolved"] = c in rule["resolved"]
        e["R_c"] = rule["own_r"].get(c)
        if e["cell"] in C.COST_OUTSIDE_FAMILY:
            e["outside_family"] = C.COST_OUTSIDE_FAMILY[e["cell"]]
    hosts = {C.host_of(r["backend"]) for r in rows if r.get("backend")}
    incomplete = [f"no window of host {h}" for h in ("L", "W") if h not in hosts]
    resolved_ids = [e["cell"] for e in cells_out if e["resolved"]]
    return {
        "complete": not incomplete,
        "incomplete": incomplete,
        "n_sim": n_sim,
        "candidates": list(CANDIDATES),
        "threshold": THRESHOLD,
        "power_target": float(POWER_TARGET),
        "seed_sim": seeds["SEED_SIM"],
        "order_seeds": {h: seeds[n] for h, n in PILOT_ORDER_SEED.items()},
        "cells": cells_out,
        "resolved": resolved_ids,
        "outside_family": dict(C.COST_OUTSIDE_FAMILY),
        "R_C": rule["R_C"],
        "m_C": rule["m_C"],
        "joint_powers": joint_powers(rule["resolved"], counts, rule["R_C"], n_sim),
        "rates": rates(sessions),
        "G": g_values(parts),
        "gap_split": gap_split(parts),
    }


def dumps(obj) -> str:
    """Deterministic JSON: sorted keys, no non-ASCII escapes lost, newline at the end."""
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=True) + "\n"


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=Path, required=True, help="the 14 seeds of 4.7, as the revision log fixes them")
    ap.add_argument("--gate", type=Path, action="append", default=[], help="an output of bench/check_records.py")
    ap.add_argument("--rows", type=Path, action="append", required=True, help="the pilot's windows.jsonl")
    ap.add_argument("--parts", type=Path, action="append", default=[], help="the timer and split parts' rows")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=1, help="processes for the simulation; the output does not depend on it")
    ap.add_argument("--allow-synthetic", action="store_true", help="synthetic rows only (tests); never under results/")
    ap.add_argument("--n-sim", type=int, default=N_SIM, help="tests only, with --allow-synthetic; the frozen value is 1,000")
    a = ap.parse_args(argv)
    versions.require()
    if a.n_sim != N_SIM and not a.allow_synthetic:
        raise SystemExit(f"N_SIM is {N_SIM} (4.6 step 2); another value only for synthetic tests")
    seeds = C.check_seeds(json.loads(a.seeds.read_text(encoding="utf-8")))
    rows = RW.read_rows(a.rows)
    parts = RW.read_rows(a.parts)
    RW.refuse_flags(rows + parts, frozen=False, allow_synthetic=a.allow_synthetic)
    if a.allow_synthetic:
        versions.refuse_results_path(a.out)
    gate = RW.apply_gate(rows + parts, a.gate)
    entry = pilot_entry(rows, parts, seeds, n_sim=a.n_sim, workers=a.workers)
    entry["synthetic"] = bool(a.allow_synthetic)
    entry["gate"] = gate
    entry["inputs"] = [{"file": p.name, "sha256": RW.sha256_file(p)} for p in a.rows + a.parts + [a.seeds]]
    entry["versions"] = versions.current()
    write_text(a.out, dumps(entry))
    print(f"pilot: R_C = {entry['R_C']}, m_C = {entry['m_C']}, resolved {len(entry['resolved'])} of 36; "
          f"{'complete' if entry['complete'] else 'INCOMPLETE: ' + '; '.join(entry['incomplete'])}"
          + ("; SYNTHETIC" if entry["synthetic"] else ""))
    return 0


def cli() -> int:
    try:
        return main()
    except (RW.RowsRefused, RW.RowError) as e:
        print(f"{Path(__file__).name}: refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
