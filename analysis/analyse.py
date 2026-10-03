#!/usr/bin/env python3
"""Every decision of hypotheses.md from the archived runs (section 13): summary.json and
decisions.csv, from which analysis/macros.py writes results/macros.tex.

    analyse.py --seeds SEEDS.json --pilot PILOT.json --rule-e RULE_E.json --gate GATE.json [...]
               --rows WINDOWS.jsonl [...] --out DIR

Per family (2.2, never mixed), per cell, the frozen tests and the dual rule (4.2):
- C (5.1): the two one-sided tests at [0.98, 1.02] (4.3) on the pilot entry's resolved cells at
  R_C, Holm over m_C; the cells the pilot did not resolve are reported as "not resolved at
  R <= 32", with intervals from the family's draws (section 10);
- B3 (5.2): superiority of Q against 1.10, Holm over the 18 cells of 6.2; the 16 descriptive cells
  with the same statistic, deciding nothing; D = W_comp - W_srv with its 95% interval; the parts
  of each footprint and K_BASE (WL7);
- M (5.3): M1 and M3 against 1.00 from below, M2 from above (4.4), Holm over the 20 cells of 6.3;
- section 10's intervals, from SEED_BOOT_S in its order (analysis/cells.py), marked secondary;
- section 12's wording of each outcome; B1 failures read from measured windows (5.2, section 7).

What it reads: only rows that bench/check_rows.py accepts against the given gates (rule D5), each
marked development: false, none a dry run (analysis/rows.py states the whole contract). Synthetic
rows only with --allow-synthetic, and then never an output under results/.

Not produced here, and why: B1's hard-case table and B2's checks come from the hard-case runs,
whose runner is still to be written (design/status.md, "What M7 starts from"); the server's
bounds beside B3 (5.2) are engineering constants of the server, not outputs of the runs; the
competitors' outcomes on the hard cases and B2's distributions are descriptive tables of those
runs; section 10's operations and system calls per connection are counts of untimed windows.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cells as C  # noqa: E402
import rows as RW  # noqa: E402
import stats as S  # noqa: E402
import versions  # noqa: E402

sys.path.insert(0, str(HERE.parent / "bench" / "run"))
import footprint as FP  # noqa: E402  bench/run/footprint.py: K_BASE's rule (WL7), unchanged

COST_CANDIDATES = (11, 15, 18, 22, 25, 28, 31)   # 4.6 step 4: R_C is one of them
RULE_E_KEYS = ("default", "relay_copy", "iocp_receive")


class AnalysisRefused(RW.RowsRefused):
    pass


def fnum(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


# ---------------------------------------------------------------- inputs


def check_rule_e(rule_e: dict) -> dict:
    """Rule E's choices (section 8, 9.3): the default detection mode per backend, the relay copy
    and the IOCP receive form (the zero-byte form, the coordinator's decision of 2026-10-03)."""
    if sorted(rule_e) != sorted(RULE_E_KEYS):
        raise AnalysisRefused(f"rule E: keys {sorted(rule_e)}, not {sorted(RULE_E_KEYS)}")
    d = rule_e["default"]
    if sorted(d) != sorted(C.COST_BACKENDS) or any(v not in ("replay", "peek") for v in d.values()):
        raise AnalysisRefused(f"rule E: default detection modes {d}")
    if rule_e["relay_copy"] not in ("user-space", "splice") or rule_e["iocp_receive"] not in ("zero-byte", "posted"):
        raise AnalysisRefused("rule E: relay_copy or iocp_receive")
    return rule_e


def check_pilot(pilot: dict, synthetic: bool) -> dict:
    if bool(pilot.get("synthetic")) != synthetic:
        raise AnalysisRefused("the pilot entry and the rows disagree on being synthetic")
    if not pilot.get("complete"):
        raise AnalysisRefused(f"the pilot entry is incomplete: {pilot.get('incomplete')}")
    if pilot.get("R_C") not in COST_CANDIDATES:
        raise AnalysisRefused(f"R_C = {pilot.get('R_C')!r} is not a candidate of 4.6 step 4")
    ids = [c.id for c in C.cost_cells()]
    res = list(pilot.get("resolved") or [])
    if any(r not in ids for r in res) or res != sorted(res, key=ids.index) or len(res) != pilot.get("m_C"):
        raise AnalysisRefused("the pilot entry's resolved list and m_C do not fit the cost cells of 6.1")
    return pilot


# ---------------------------------------------------------------- one cell's computations


def boot_report(values: list[float], draws: np.ndarray, clusters: list | None = None) -> tuple[S.Boot, dict]:
    boot = S.bca_fit(values, draws, clusters)
    iv = S.bca_interval(boot, S.LEVEL_95)
    return boot, {"median": boot.theta, "ci95": [fnum(iv.low), fnum(iv.high)], "z0": boot.z0, "a": boot.a}


def family_test(cell: C.Cell, values: list[float], boot: S.Boot) -> dict:
    """Both computations of the cell's test: 4.3 (tost), 4.4 (greater, less)."""
    if cell.test == "tost":
        st = S.sign_tost(values)
        pl, ph, pb = S.bca_tost(boot)
        return {"p_sign": float(st.p), "p_boot": pb, "sign_x_low": st.low.x, "sign_x_high": st.high.x,
                "p_sign_low": float(st.low.p), "p_sign_high": float(st.high.p), "p_boot_low": pl.p, "p_boot_high": ph.p,
                "degenerate": pl.degenerate or ph.degenerate}
    if cell.test == "greater":
        st = S.sign_greater(values, cell.bound)
        bp = S.p_lower(boot, cell.bound)
    else:
        st = S.sign_less(values, cell.bound)
        bp = S.p_upper(boot, cell.bound)
    return {"p_sign": float(st.p), "p_boot": bp.p, "sign_x": st.x, "degenerate": bp.degenerate}


def cell_values(cell: C.Cell, sessions: list[RW.Session]) -> list[float | None]:
    if cell.family == "B3":
        return [RW.session_ratio(s, cell.num, cell.den, "W", q_rule=True) for s in sessions]
    return [RW.session_ratio(s, cell.num, cell.den, "metric", cell.metric) for s in sessions]


def b3_parts(cell: C.Cell, sessions: list[RW.Session], k_base: float | None) -> dict:
    """5.2: both W and their parts U, Kq and Ks - K_BASE; the skb caches' growth and the shared
    cache's; f; the co-tenants seen. Per arm, the median over the valid sessions of the arm's
    mean of its two windows."""
    out = {}
    for role in (cell.den, cell.num):
        parts = {}
        for key in ("U", "Kq", "Ks", "W", "f_mean", "skb_growth", "shared_growth"):
            per = []
            for s in sessions:
                ws = s.by_role(role)
                vals = [((w.get("footprint") or {}).get("sample2") or {}).get(key) for w in ws]
                if len(vals) == 2 and all(v is not None for v in vals):
                    per.append((float(vals[0]) + float(vals[1])) / 2)
            parts[key] = statistics.median(per) if per else None
        parts["Ks_minus_K_BASE"] = parts["Ks"] - k_base if parts["Ks"] is not None and k_base is not None else None
        tenants = sorted({t for s in sessions for w in s.by_role(role)
                          for t in ((((w.get("readings") or {}).get("sample2") or {}).get("fclone_cotenants")) or [])})
        parts["shared_cache_cotenants"] = tenants
        out[role] = parts
    return out


def overflows(sessions: list[RW.Session], roles: tuple[str, str]) -> dict:
    """M3: listen overflows recorded per window and reported beside each cell (5.3, section 7)."""
    out = {}
    for role in roles:
        out[role] = sum(int(((w.get("nstat_delta") or {}).get("TcpExtListenOverflows") or 0))
                        for s in sessions for w in s.by_role(role))
    return out


def run_family(fam: str, by_cell: dict[str, list[RW.Session]], r_of: dict[str, int], rng: np.random.Generator,
               in_holm: dict[str, bool], k_base: float | None) -> list[dict]:
    """One family: each cell in the order of section 6 draws once when it has R valid sessions
    (4.7), then Holm per computation over the family's Holm cells (4.2)."""
    out = []
    for cell in C.FAMILY_LISTS[fam]():
        r = r_of[cell.id]
        ss = by_cell.get(cell.id, [])
        good = sorted((s for s in ss if s.valid), key=lambda s: (s.job, s.id))
        if len(good) > r:
            raise AnalysisRefused(f"{cell.id}: {len(good)} valid sessions, more than R = {r}")
        row = {"family": fam, "hyp": cell.hyp, "cell": cell.id, "number": cell.number, "holm": in_holm[cell.id], "R": r,
               "sessions": len(ss), "valid_sessions": len(good), "invalid_windows": RW.invalid_windows(ss),
               "tested": False, "why_untested": None}
        if len(good) == r:
            draws = S.draw_clusters(rng, r)
            values = cell_values(cell, good)
            row["values"] = [fnum(v) for v in values]
            if any(v is None for v in values):
                row["why_untested"] = "a valid session has no ratio (a non-positive or missing arm value)"
            else:
                boot, rep = boot_report(values, draws)
                row.update(rep)
                row.update(family_test(cell, values, boot))
                row["tested"] = not row["degenerate"]
                if row["degenerate"]:
                    row["why_untested"] = "the BCa map does not reach the bound"
                row["_boot"] = boot
                if fam == "B3":
                    d = [RW.arm_mean(s.by_role("competitor"), "W") - RW.arm_mean(s.by_role("server"), "W") for s in good]
                    _, drep = boot_report(d, draws)
                    row["D"] = {"median": drep["median"], "ci95": drep["ci95"], "values": d}
        else:
            row["why_untested"] = f"{len(good)} valid sessions, fewer than R = {r} (4.1)"
        if fam == "B3":
            row["parts"] = b3_parts(cell, good, k_base)
        if cell.hyp == "M3":
            row["listen_overflows"] = overflows(ss, (cell.num, cell.den))
        out.append(row)
    holm_rows = [x for x in out if x["holm"]]
    duals = S.dual_rule([x.get("p_boot") if x["tested"] else None for x in holm_rows],
                        [x.get("p_sign") if x["tested"] else None for x in holm_rows])
    levels = S.holm_levels([x.get("p_boot") if x["tested"] else 1.0 for x in holm_rows])
    for x, d, (j, aj) in zip(holm_rows, duals, levels, strict=True):
        x.update(p_boot_holm=d.p_boot_holm, p_sign_holm=d.p_sign_holm, pass_boot=d.pass_boot, pass_sign=d.pass_sign,
                 passes=d.passes, disagree=d.disagree, holm_rank=j, holm_alpha=aj)
        if x["tested"] and fam in ("C", "B3"):
            iv = S.bca_interval(x["_boot"], 1 - 2 * aj)
            x["ci_holm"] = [fnum(iv.low), fnum(iv.high)]
        x["m"] = len(holm_rows)
    for x in out:
        x.pop("_boot", None)
        x["verdict"] = verdict(x)
    return out


# ---------------------------------------------------------------- section 12's words


def verdict(x: dict) -> str:
    fam, hyp = x["family"], x["hyp"]
    ci = x.get("ci95") or [None, None]
    lo, hi = ci
    if fam == "C":
        if not x["holm"]:
            return "not resolved at R <= 32"
        if x.get("passes"):
            return "equivalent within [0.98, 1.02]"
        words = "equivalence not shown"
        if x["tested"] and lo is not None and hi is not None:
            higher_is_better = hyp in ("C1", "C2")
            below, above = hi < S.COST_LOW, lo > S.COST_HIGH
            if (below and higher_is_better) or (above and not higher_is_better):
                words += "; a measured cost (the 95% interval lies wholly outside the margin, against one-port mode)"
            elif below or above:
                words += "; the 95% interval lies wholly outside the margin, in one-port mode's favour"
        return words + qualifiers(x)
    if fam == "B3":
        if not x["holm"]:
            return "descriptive"
        if x.get("passes"):
            return "shown: the competitor held at least 1.10 times the server's counted footprint per pending connection, by B3's test"
        loss = x["tested"] and hi is not None and hi < 1.0
        return ("not shown; loss (the 95% interval of Q lies wholly below 1.00)" if loss else "not shown") + qualifiers(x)
    if x.get("passes"):
        return "shown"
    if hyp == "M3":
        loss = x["tested"] and hi is not None and hi < 1.0
        return ("not shown; loss (the 95% interval of the ratio lies wholly below 1.00)" if loss else "not shown") + qualifiers(x)
    return "a difference was not shown" + qualifiers(x)


def qualifiers(x: dict) -> str:
    q = []
    if not x["tested"]:
        q.append(f"untested: {x['why_untested']}")
    elif x.get("disagree"):
        q.append("the two computations disagree")
    return "".join(f"; {s}" for s in q)


def cost_claims(c_rows: list[dict], pilot: dict) -> list[dict]:
    """Section 12: "no measurable cost" only where C1, C2 and C3 all pass, per protocol, backend
    and host, with the joint power of the pilot entry and the intervals at Holm's level."""
    by = {x["cell"]: x for x in c_rows}
    jp = {(j["backend"], j["proto"]): j for j in pilot.get("joint_powers") or []}
    out = []
    for backend in C.COST_BACKENDS:
        for proto in C.COST_PROTOS:
            trio = [by[f"{h}.{C.host_of(backend)}.{backend}.{proto}"] for h in C.COST_HYPS]
            if all(t.get("passes") for t in trio):
                j = jp.get((backend, proto)) or {}
                out.append({"host": C.host_of(backend), "backend": backend, "proto": proto,
                            "joint_power": j.get("power"), "ci_holm": {t["hyp"]: t.get("ci_holm") for t in trio}})
    return out


# ---------------------------------------------------------------- section 10 (SEED_BOOT_S)


def secondary(by_cell: dict[str, list[RW.Session]], r_c: int, rng: np.random.Generator, rule_e: dict) -> list[dict]:
    fam_cells = C.all_family_cells()
    sec_cells = {s.id: s for s in C.secondary_cells()}
    out = []
    for d in C.secondary_draws():
        r = d.r if d.r is not None else r_c
        ss = by_cell.get(d.source, [])
        good = sorted((s for s in ss if s.valid), key=lambda s: (s.job, s.id))
        if len(good) > r:
            raise AnalysisRefused(f"{d.source}: {len(good)} valid sessions, more than R = {r}")
        entry = {"bullet": d.bullet, "cell": d.source, "metric": d.metric, "R": r, "valid_sessions": len(good),
                 "clustered_by_job": d.clustered, "secondary": True}
        if d.source in sec_cells:
            entry["invalid_windows"] = RW.invalid_windows(ss)
        if len(good) != r:
            entry["interval"] = None
            entry["why"] = f"{len(good)} valid sessions, fewer than R = {r}: no draw (4.7)"
            out.append(entry)
            continue
        if d.clustered:
            cell = fam_cells[d.source]
            jobs = [s.job for s in good]
            k = len(dict.fromkeys(jobs))
            draws = S.draw_clusters(rng, k)
            values = cell_values(cell, good)
            entry["jobs"] = k
            if any(v is None for v in values) or k < 2:
                entry["interval"] = None
                entry["why"] = "fewer than 2 lab jobs" if k < 2 else "a valid session has no ratio"
            else:
                boot, rep = boot_report(values, draws, jobs)
                entry.update(rep)
                entry.update({k2: v for k2, v in family_test(cell, values, boot).items() if k2.startswith("p_boot") or k2 == "degenerate"})
                entry["interval"] = rep["ci95"]
            out.append(entry)
            continue
        draws = S.draw_clusters(rng, r)
        if d.source in fam_cells:
            cell = fam_cells[d.source]
            values = [RW.session_ratio(s, cell.num, cell.den, d.metric) for s in good]
        else:
            sc = sec_cells[d.source]
            if sc.metric == "W":
                values = [RW.session_ratio(s, sc.num, sc.den, "W", q_rule=True) for s in good]
            else:
                names = {(w.get("metric") or {}).get("name") for s in good for w in s.windows}
                if sc.metric is None and len(names) != 1:
                    raise AnalysisRefused(f"{sc.id}: the arms carry metrics {sorted(map(str, names))}")
                values = [RW.session_ratio(s, sc.num, sc.den, "metric", sc.metric) for s in good]
                entry["metric_name"] = sc.metric or next(iter(names))
        if any(v is None for v in values):
            entry["interval"] = None
            entry["why"] = "a valid session has no ratio"
        else:
            _, rep = boot_report(values, draws)
            entry.update(rep)
            entry["interval"] = rep["ci95"]
        entry["values"] = [fnum(v) for v in values]
        out.append(entry)
    return out


# ---------------------------------------------------------------- the whole analysis


def k_base_of(rows: list[dict]) -> dict:
    hold = [r for r in rows if r.get("kind") == "ophold"]
    try:
        return {"K_BASE": FP.k_base(hold), "ophold_windows": len(hold), "why": None}
    except ValueError as e:
        return {"K_BASE": None, "ophold_windows": len(hold), "why": str(e)}


def b1_failures(rows: list[dict]) -> list[dict]:
    """5.2 and section 7: a connection classified other than as its script's protocol in any
    measured window of any family is a failure of B1."""
    return [{"job": r.get("job"), "session": r.get("session"), "position": r.get("position"), "misclassified": r["misclassified"]}
            for r in rows if int(r.get("misclassified") or 0) > 0]


def roles_for(kind: str, cid: str) -> tuple[str, str]:
    fam = C.all_family_cells()
    if cid in fam:
        return fam[cid].num, fam[cid].den
    sec = {s.id: s for s in C.secondary_cells()}
    if cid in sec:
        return sec[cid].num, sec[cid].den
    raise AnalysisRefused(f"session of cell {cid}, which no list of section 6 or 10 holds")


def analyse(rows: list[dict], *, pilot: dict, rule_e: dict, seeds: dict) -> dict:
    rule_e = check_rule_e(rule_e)
    seeds = C.check_seeds(seeds)
    sessions = RW.assemble(rows, lambda r: RW.row_info(r, rule_e), roles_for)
    by_cell: dict[str, list[RW.Session]] = {}
    for s in sessions:
        by_cell.setdefault(s.cell, []).append(s)
    r_c = int(pilot["R_C"])
    resolved = set(pilot["resolved"])
    kb = k_base_of(rows)
    fams = {}
    for fam in C.FAMILY_ORDER:
        cells = C.FAMILY_LISTS[fam]()
        r_of = {c.id: (r_c if c.r is None else c.r) for c in cells}
        in_holm = {c.id: (c.id in resolved) if fam == "C" else c.holm for c in cells}
        rng = np.random.default_rng(seeds[C.FAMILY_BOOT_SEED[fam]])
        fams[fam] = run_family(fam, by_cell, r_of, rng, in_holm, kb["K_BASE"])
    sec = secondary(by_cell, r_c, np.random.default_rng(seeds["SEED_BOOT_S"]), rule_e)
    summary = {
        "constants": {"alpha": S.ALPHA, "resamples": S.B_RESAMPLES, "cost_margin": [S.COST_LOW, S.COST_HIGH],
                      "b3_bound": S.B3_BOUND, "m_bound": S.M_BOUND, "R_C": r_c, "R_B": C.R_B, "R_M": C.R_M,
                      "R_secondary": C.R_SECONDARY},
        "seeds": seeds,
        "rule_e": rule_e,
        "pilot": {"R_C": r_c, "m_C": pilot["m_C"], "resolved": pilot["resolved"], "joint_powers": pilot.get("joint_powers")},
        "families": {f: {"m": sum(1 for x in fams[f] if x["holm"]),
                         "passed": sum(1 for x in fams[f] if x.get("passes")),
                         "passed_boot": sum(1 for x in fams[f] if x.get("pass_boot")),
                         "passed_sign": sum(1 for x in fams[f] if x.get("pass_sign")),
                         "disagree": sum(1 for x in fams[f] if x.get("disagree")),
                         "cells": fams[f]} for f in C.FAMILY_ORDER},
        "claims": {"C": cost_claims(fams["C"], pilot),
                   "B3": [x["cell"] for x in fams["B3"] if x.get("passes")],
                   "M": [x["cell"] for x in fams["M"] if x.get("passes")]},
        "k_base": kb,
        "b1_failures": b1_failures(rows),
        "secondary": sec,
        "not_produced": ["B1's hard-case table and B2's checks (the hard-case runs)",
                         "the server's bounds beside B3 (engineering constants)",
                         "the competitors' hard-case outcomes and B2's distributions (descriptive tables)",
                         "operations and system calls per connection (untimed windows)"],
    }
    return summary


# ---------------------------------------------------------------- outputs


DECISION_COLUMNS = ("family", "hyp", "number", "cell", "holm", "R", "sessions", "valid_sessions", "tested", "median", "ci95_low",
                    "ci95_high", "holm_rank", "holm_alpha", "ci_holm_low", "ci_holm_high", "p_boot", "p_sign", "p_boot_holm",
                    "p_sign_holm", "pass_boot", "pass_sign", "passes", "disagree", "verdict", "invalid_windows")


def decisions_csv(summary: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(DECISION_COLUMNS)
    for f in C.FAMILY_ORDER:
        for x in summary["families"][f]["cells"]:
            ci = x.get("ci95") or [None, None]
            ch = x.get("ci_holm") or [None, None]
            inv = sum(len(v) for v in x["invalid_windows"].values())
            vals = {**x, "ci95_low": ci[0], "ci95_high": ci[1], "ci_holm_low": ch[0], "ci_holm_high": ch[1], "invalid_windows": inv}
            w.writerow(["" if vals.get(k) is None else repr(vals[k]) if isinstance(vals.get(k), float) else vals[k]
                        for k in DECISION_COLUMNS])
    return buf.getvalue()


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=True, allow_nan=False) + "\n"


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=Path, required=True)
    ap.add_argument("--pilot", type=Path, required=True, help="pilot.py's output, as the pilot entry records it")
    ap.add_argument("--rule-e", type=Path, required=True, help="rule E's choices (section 8)")
    ap.add_argument("--gate", type=Path, action="append", default=[])
    ap.add_argument("--rows", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True, help="a directory: summary.json and decisions.csv")
    ap.add_argument("--allow-synthetic", action="store_true", help="synthetic rows only (tests); never under results/")
    a = ap.parse_args(argv)
    versions.require()
    if a.allow_synthetic:
        versions.refuse_results_path(a.out)
    rows = RW.read_rows(a.rows)
    RW.refuse_flags(rows, frozen=True, allow_synthetic=a.allow_synthetic)
    gate = RW.apply_gate(rows, a.gate)
    pilot = check_pilot(json.loads(a.pilot.read_text(encoding="utf-8")), a.allow_synthetic)
    summary = analyse(rows, pilot=pilot, rule_e=json.loads(a.rule_e.read_text(encoding="utf-8")),
                      seeds=json.loads(a.seeds.read_text(encoding="utf-8")))
    summary["synthetic"] = bool(a.allow_synthetic)
    summary["gate"] = gate
    summary["inputs"] = {p.name: RW.sha256_file(p) for p in a.rows + [a.pilot, a.rule_e, a.seeds]}
    summary["versions"] = versions.current()
    a.out.mkdir(parents=True, exist_ok=True)
    write_text(a.out / "summary.json", dumps(summary))
    write_text(a.out / "decisions.csv", decisions_csv(summary))
    tag = " SYNTHETIC: never under results/" if a.allow_synthetic else ""
    for f in C.FAMILY_ORDER:
        fam = summary["families"][f]
        print(f"{f}: {fam['passed']} of {fam['m']} Holm cells pass under both computations{tag}")
    return 0


def cli() -> int:
    try:
        return main()
    except (RW.RowsRefused, RW.RowError) as e:
        print(f"{Path(__file__).name}: refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
