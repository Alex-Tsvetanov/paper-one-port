#!/usr/bin/env python3
"""The cost family's confirmatory runner on L (hypotheses.md 5.1, 4.1, 4.6 step 7): one-port mode
against dedicated mode, in-process dispatch, the default detection mode of rule E, the same binary,
every cost cell of L at R_C sessions, resolved or not.

    cost_run.py --build DIR --out DIR --job NAME --seeds SEEDS.json --code-freeze SHA --gate gate-L.json
                --pilot PILOT.json --rule-e RULE_E.json
    cost_run.py ... --development --dev-seed N [--only CELL,...] [--dev-r R]

Sessions are X Y Y X of arm A (one-port mode, on aa.PORT_A) and arm B (dedicated mode, PORT_OFFSET
above it, so every change of arm changes port, as the pilot's second start), X drawn per session
from SEED_ORDER_C_L; all sessions of L's cost cells run in one shuffled order (4.7); a session with
an invalid window runs again at the end, at most ceil(R_C/4) times per cell (4.1). R_C and each C3
cell's lambda are read from the pilot entry's output, lambda passed unchanged, so analyse.py's
check of the rates holds exactly. Both arms run with rule E's default detection mode for the
backend (the dedicated arm has no detection, so the flag acts only in the one-port arm; section
2.1: "Backend, workers, handlers, buffers and the PROXY setting are the same in both modes").

It refuses to start a frozen run unless the pilot entry exists in the revision log, is committed,
and came after CODE_FREEZE; rule E's file is logged after it; the code at HEAD is CODE_FREEZE's
under bench, tests and CMakeLists.txt; and the build's binaries are the gate's
(bench/run/freeze_guard.py). In development mode the one-port arm of every session is a stub
(bench/run/sessions.py): its rows say mode one-port, valid false and stub true, nothing is started,
and the dedicated arm's windows run, so no one-port window is ever timed against dedicated mode
before the pilot entry (section 8 step 2).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aa  # noqa: E402
import cellwin  # noqa: E402
import freeze_guard  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402

sys.path.insert(0, str(runlib.REPO / "analysis"))
import cells as C  # noqa: E402

PORTS = {"A": aa.PORT_A, "B": aa.PORT_A + aa.PORT_OFFSET}
CANDIDATES = (11, 15, 18, 22, 25, 28, 31)  # 4.6 step 4


# The coordinator's decision of M7e (the revision log's entry "The job's warm-up and W's runners
# (M7e), before the code freeze"): the cost cells outside the confirmatory family (W's churn h2c and
# churn MQTT; analysis/cells.py's COST_OUTSIDE_FAMILY) run in the A/A pilot only, never in the
# confirmatory cost runs.
NOT_RUN_OUTSIDE = ("not run in the confirmatory cost runs: {why}; it runs in the A/A pilot only, so that WL2 has its median "
                   "for the open-loop rate (the coordinator's decision, revision log, \"The job's warm-up and W's runners (M7e), "
                   "before the code freeze\")")


def cost_not_run(host: str = "L") -> dict[str, str]:
    """The cost cells of `host` that the confirmatory runs leave out, each with why."""
    return {c.id: NOT_RUN_OUTSIDE.format(why=C.COST_OUTSIDE_FAMILY[c.id]) for c in C.cost_cells()
            if c.host == host and c.id in C.COST_OUTSIDE_FAMILY}


def cost_cells(r: int, rule_e: dict, rates: dict[str, float | None], host: str = "L") -> list[SS.Cell]:
    """Every cost cell of `host` at R_C, resolved or not, but those cost_not_run names."""
    out = []
    for c in C.cost_cells():
        if c.host != host or c.id in C.COST_OUTSIDE_FAMILY:
            continue
        wl = C.HYP_WORKLOAD[c.hyp]
        detect = rule_e["default"][c.backend]
        base = {"family": "C", "workload": wl, "proto": c.proto, "backend": c.backend, "detect": detect, "dispatch": "inproc"}
        shared = {"workload": wl, "proto": c.proto, "backend": c.backend, "detect": detect, "pairs_dedicated": True}
        if c.hyp == "C3":
            shared["rate"] = rates.get(c.id)
        out.append(SS.Cell(c.id, r, {"A": dict(base, mode="one-port", run={"mode": "one-port", "port": PORTS["A"]}),
                                     "B": dict(base, mode="dedicated", run={"mode": "dedicated", "port": PORTS["B"]})},
                           shared=shared, pairs_one_port_with_dedicated=True))
    return out


def pilot_values(pilot: dict, development: bool, dev_r: int | None) -> tuple[int, dict[str, float | None]]:
    if development:
        r = dev_r if dev_r is not None else int(pilot.get("R_C", 0) or 0)
        if r <= 0:
            raise runlib.InputRefused("development mode: give --dev-r (or a development pilot output with R_C)")
    else:
        r = int(pilot["R_C"])
        if r not in CANDIDATES:
            raise runlib.InputRefused(f"R_C = {r} is not a candidate of 4.6 step 4")
    rates = {cid: (e or {}).get("rate") for cid, e in (pilot.get("rates") or {}).items()}
    return r, rates


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    runlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path, help="rule E's choices (frozen runs; development takes the proposed defaults)")
    a = ap.parse_args(argv)
    runlib.check_mode_args(a)
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_ORDER_C_L")
    pilot = runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    prov = runlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, pilot=a.pilot, rule_e=a.rule_e,
                                       binaries=runlib.binaries_of(prov, ("oneport", "opgen")), entries=(freeze_guard.M7E_ITEMS,))
    r, rates = pilot_values(pilot, a.development, a.dev_r)
    cells = runlib.only_cells(a, cost_cells(r, rule_e, rates))
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, R_C=r), indent=1))
    blocks = window.SourceBlocks(a.blocks)

    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        if p["workload"] == "open" and p.get("rate") is None:
            raise window.WindowError(f"{cell.id}: the pilot entry gives no lambda")
        return cellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src), session, arm, position, blocks, a.out / "raw", clr)

    eng = SS.Engine("cost_run", a.job, a.out, cells, SS.make_plan(cells, seed), win,
                    lambda c, arm: runlib.arm_provenance(prov, a.build, ("oneport", "opgen")), a.development, clearance,
                    fingerprint=window.pin_fingerprint, stop_after_sessions=a.max_sessions)
    summ = eng.run()
    print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, freeze_guard.FreezeRefused) as e:
        print(f"cost_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
