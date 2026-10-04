#!/usr/bin/env python3
"""The cost family's confirmatory runner on W (hypotheses.md 5.1, 4.1, 4.6 step 7): cost_run.py's
cells and sessions on IOCP, one-port mode against dedicated mode, in-process dispatch, rule E's
default detection mode on IOCP in both arms' flags (the M7d entry, item 3), the same binary.

    wcost_run.py --build DIR --out DIR --job NAME --seeds SEEDS.json --code-freeze SHA --gate gate-W.json
                 --pilot PILOT.json --rule-e RULE_E.json
    wcost_run.py ... --development --dev-seed N [--only CELL,...] [--dev-r R]

Cells: W's cost cells of 6.1 at R_C, resolved or not (4.6 step 7), but W's churn h2c and churn
MQTT (c = 10 and 12), which a logged decision put outside the family (the revision log's entry "W
before the code freeze", item 1) and which run in the A/A pilot only (the coordinator's decision,
the M7e entry): they are listed in not-run-<job>.json with why. Sessions X Y Y X of arm A (one-port,
aa.PORT_A) and arm B (dedicated, PORT_OFFSET above), X drawn per session from SEED_ORDER_C_W, all of
W's cost sessions in one shuffled order (4.7), reruns at most ceil(R_C/4) per cell (4.1); each C3
cell at the pilot entry's lambda, passed unchanged. The window is bench/run/wcellwin.py's; its rows
are cost_run.py's (family C), with WL4 as the server's cycles per exchange and GetProcessTimes'
value beside it (the entry "W before the code freeze", item 4). The job's warm-up phase runs before
the first session (bench/run/sessions.py).

A frozen run needs the freeze guard with the pilot entry and rule E's file (W's gate), the entries
W's runners apply, the W job's context, and W's ports outside its excluded ranges. In development
mode the one-port arm of every session is a stub (bench/run/sessions.py): nothing is started for it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cost_run  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402
import wcellwin  # noqa: E402
import wrunlib  # noqa: E402

RUNNER = "wcost_run"
PORTS = cost_run.PORTS
USED_PORTS = [(PORTS["A"], PORTS["A"] + 5), (PORTS["B"], PORTS["B"] + 5)]


def w_cost_cells(r: int, rule_e: dict, rates: dict[str, float | None]) -> list[SS.Cell]:
    return cost_run.cost_cells(r, rule_e, rates, host="W")


def main(argv=None) -> int:
    wrunlib.install_stop()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    wrunlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path, help="rule E's choices (frozen runs; development takes the proposed defaults)")
    a = ap.parse_args(argv)
    runlib.check_mode_args(a)
    job_ctx = wrunlib.check_job_context(a.development)
    ports = wrunlib.check_ports(USED_PORTS)
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_ORDER_C_W")
    pilot = runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    prov = wrunlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = wrunlib.freeze_check(a, prov, ("oneport", "opgen"), rule_e=a.rule_e)
    r, rates = cost_run.pilot_values(pilot, a.development, a.dev_r)
    cells = runlib.only_cells(a, w_cost_cells(r, rule_e, rates))
    not_run = cost_run.cost_not_run("W")
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, R_C=r, not_run=not_run, job_context=job_ctx,
                                                                    ports=ports), indent=1))
    (a.out / f"not-run-{a.job}.json").write_text(json.dumps(not_run, indent=1))
    blocks = window.SourceBlocks(a.blocks)

    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        if p["workload"] == "open" and p.get("rate") is None:
            raise window.WindowError(f"{cell.id}: the pilot entry gives no lambda")
        return wcellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src), session, arm, position, blocks, a.out / "raw", clr)

    eng = SS.Engine(RUNNER, a.job, a.out, cells, SS.make_plan(cells, seed), win,
                    lambda c, arm: wrunlib.arm_provenance(prov, a.build, ("oneport", "opgen")), a.development, clearance,
                    fingerprint=wrunlib.fingerprint, stop_after_sessions=a.max_sessions)
    summ = eng.run()
    print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, wrunlib.freeze_guard.FreezeRefused) as e:
        print(f"wcost_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
