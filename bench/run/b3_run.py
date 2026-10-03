#!/usr/bin/env python3
"""B3's session runner on L (hypotheses.md 5.2, 6.2, WL7, 4.1, 4.7; section 10's B3 cells; 9.3's
K_BASE): every window in WL7's layout through bench/run/b3.py.

    b3_run.py --build DIR --out DIR --job NAME [--parts kbase,sessions] --other-mode-system SYSTEM
              --seeds SEEDS.json --code-freeze SHA --gate gate-L.json --pilot PILOT.json --rule-e RULE_E.json
    b3_run.py ... --development --dev-seed N [--only CELL,...] [--dev-r R] [--dev-n N]

Cells, all in one order shuffled with SEED_ORDER_B_L (4.7: "B3's order also holds B3's descriptive
and secondary cells"), each at R_B = 16:
- the 18 Holm cells and the 16 descriptive cells of 6.2 (analysis/cells.py's b3_cells): arm A the
  server, in relay mode in front of the stub against a proxy and in one-port mode in-process against
  a library (5.2), on the cell's backend, in rule E's default detection mode with rule E's relay
  copy, every timer at 60 s (section 1); arm B the competitor in its B3 configuration (Appendix B),
  HAProxy with option splice-auto where the server's relay splices (rule E);
- section 10's 4 cells "B3 with the server in its other detection mode against its default mode":
  arm A the other mode, arm B the default (Q = other / default), the server's system given by
  --other-mode-system (one-port-relay or one-port-inproc). The frozen text names no dispatch for
  these cells; the flag has no default, so the choice is the coordinator's and every row names it.
Rows are b3.py's (kind "b3", footprint, readings, provenance with the binaries the window ran) with
the session fields; family "B3", or "S" with bullet "b3-other-mode".

K_BASE (part kbase): ophold windows (b3.py's, kind "ophold") until 16 are valid, at most
ceil(16/4) = 4 more (4.1's rule, a design choice for these windows), never more than 16 valid:
analysis/analyse.py refuses more. They run before the sessions, after the pilot entry (9.3).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "competitors"))

import b3  # noqa: E402
import competitors as comp  # noqa: E402
import footprint as fp  # noqa: E402
import freeze_guard  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402

sys.path.insert(0, str(runlib.REPO / "analysis"))
import cells as C  # noqa: E402

R_B = C.R_B
K_BASE_WINDOWS = fp.K_BASE_WINDOWS
OTHER = {"replay": "peek", "peek": "replay"}


def b3_cells(r: int, rule_e: dict, other_system: str | None) -> list[SS.Cell]:
    out = []
    for c in C.b3_cells():
        server = C.SERVER_RELAY if c.system in C.PROXIES else C.SERVER_INPROC
        detect = rule_e["default"][c.backend]
        rc = rule_e["relay_copy"][c.backend]
        a = {"family": "B3", "kind": "b3", "system": server, "case": c.case, "backend": c.backend, "detect": detect,
             "run": {"system": server, "backend": c.backend, "detect": detect, "relay_copy": rc}}
        b = {"family": "B3", "kind": "b3", "system": c.system, "case": c.case,
             "run": {"system": c.system, "backend": c.backend, "detect": detect, "relay_copy": rc}}
        out.append(SS.Cell(c.id, r, {"A": a, "B": b}, shared={"case": c.case}))
    for s in C.secondary_cells():
        if s.bullet != "b3-other-mode":
            continue
        if other_system is None:
            continue
        case = s.key[0]
        d = rule_e["default"][s.backend]
        rc = rule_e["relay_copy"][s.backend]
        arm = lambda det: {"family": "S", "bullet": "b3-other-mode", "kind": "b3", "system": other_system, "case": case,  # noqa: E731
                           "backend": s.backend, "detect": det,
                           "run": {"system": other_system, "backend": s.backend, "detect": det, "relay_copy": rc}}
        out.append(SS.Cell(s.id, r, {"A": arm(OTHER[d]), "B": arm(d)}, shared={"case": case}))
    return out


def all_binaries(build: Path, systems: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in sorted(systems | {"ophold"}):
        out.update(b3.binaries_provenance(build, s)["binaries"])
    return out


def run_kbase(a: argparse.Namespace, n: int, clearance, windows: int = K_BASE_WINDOWS) -> None:
    path = a.out / "windows.jsonl"
    rows = [r for r in SS.read_rows(path) if r.get("kind") == "ophold"]
    cap = windows + SS.rerun_cap(windows)
    while sum(1 for r in rows if r.get("valid")) < windows and len(rows) < cap:
        k = len(rows) + 1
        try:
            row = b3.run(a.build, a.out / "raw" / f"ophold-{k:02d}", a.job, "silent", n, a.blocks, "ophold", tools=a.tools)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001 - a crashed window is a row
            row = {"kind": "ophold", "system": "ophold", "case": "silent", "valid": False, "invalid_reasons": [f"driver error: {e!r}"],
                   "provenance": dict(b3.binaries_provenance(a.build, "ophold"))}
        row.update(job=a.job, development=a.development, runner="b3_run", ophold_window=k)
        if clearance is not None:
            row["provenance"] = dict(row.get("provenance") or {}, freeze=clearance.record)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        rows.append(row)
        print(f"ophold {k}: valid={row.get('valid')} {'; '.join(row.get('invalid_reasons') or [])}", flush=True)


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    runlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path)
    ap.add_argument("--parts", default="kbase,sessions")
    ap.add_argument("--other-mode-system", choices=(C.SERVER_RELAY, C.SERVER_INPROC),
                    help="the server's system in section 10's B3 cells of the other detection mode (no default: the frozen text names none)")
    ap.add_argument("--dev-n", type=int, help="development mode: N_PEND per window instead of 10,000")
    ap.add_argument("--dev-k-base-windows", type=int, help="development mode: valid ophold windows instead of 16")
    a = ap.parse_args(argv)
    runlib.check_mode_args(a)
    if not a.development and (a.dev_n is not None or a.dev_k_base_windows is not None):
        raise runlib.InputRefused("--dev-n and --dev-k-base-windows are for development runs only")
    parts = a.parts.split(",")
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_ORDER_B_L")
    runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    n = a.dev_n or fp.N_PEND
    cells = runlib.only_cells(a, b3_cells(a.dev_r or R_B, rule_e, a.other_mode_system))
    if not a.development and a.other_mode_system is None:
        raise runlib.InputRefused("a frozen B3 run holds section 10's other-mode cells: give --other-mode-system")
    systems = {arm["run"]["system"] for c in cells for arm in c.arms.values()}
    base = runlib.job_provenance(a.build, a.tools, a.out, a.job)
    base = {k: v for k, v in base.items() if k != "binaries_all"}
    clearance = None
    if not a.development:
        clearance = freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, pilot=a.pilot, rule_e=a.rule_e,
                                       binaries=all_binaries(a.build, systems))
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(base, rule_e=rule_e, n_pend=n), indent=1))
    for s in systems:
        if s in comp.ORDER and not comp.SYSTEMS[s].binary_path().exists():
            raise runlib.InputRefused(f"{s}: no binary at {comp.SYSTEMS[s].binary_path()}")
        if s in comp.LIBRARIES and not comp.SYSTEMS[s].binary_path(comp.harness_dir(a.build)).exists():
            raise runlib.InputRefused(f"{s}: no harness in {comp.harness_dir(a.build)}")
    if "kbase" in parts:
        run_kbase(a, n, clearance, a.dev_k_base_windows or K_BASE_WINDOWS)
    if "sessions" not in parts:
        return 0

    def win(cell: SS.Cell, arm: str, session: dict, position: int, _clr) -> dict:
        p = cell.run_params(arm)
        out = a.out / "raw" / f"{session['id']}-p{position}-{arm}"
        row = b3.run(a.build, out, a.job, p["case"], n, a.blocks, p["system"], p["backend"], p["detect"], a.tools, p["relay_copy"])
        row["n_pend"] = n
        return row

    def prov(cell: SS.Cell, arm: str) -> dict:
        return dict(base, **b3.binaries_provenance(a.build, cell.arms[arm]["run"]["system"]))

    eng = SS.Engine("b3_run", a.job, a.out, cells, SS.make_plan(cells, seed), win, prov, a.development, clearance,
                    fingerprint=window.pin_fingerprint, stop_after_sessions=a.max_sessions)
    summ = eng.run()
    print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, freeze_guard.FreezeRefused) as e:
        print(f"b3_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
