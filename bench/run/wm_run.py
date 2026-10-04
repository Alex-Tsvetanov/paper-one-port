#!/usr/bin/env python3
"""The mechanism family's runner on W (hypotheses.md 5.3, 6.3, WL1, 4.1, 4.7): M1's two IOCP cells
(HTTP/1.1 and h2c), m_run.py's cells with host "W", R_M = 16 each, in one order shuffled with
SEED_ORDER_M_W (4.7). M2 and M3 run on L only (6.3).

    wm_run.py --build DIR --out DIR --job NAME --seeds SEEDS.json --code-freeze SHA --gate gate-W.json
              --pilot PILOT.json --rule-e RULE_E.json
    wm_run.py ... --development --dev-seed N [--only CELL,...] [--dev-r R]

M1 on IOCP: in-process churn (WL1), arm A rule E's default detection mode on IOCP, arm B the other,
both one-port mode, in-process dispatch (bench/run/wcellwin.py); on IOCP the peek mode includes the
switch to replay, which the counters report (5.3). Rows family "M1", detect per arm, as m_run.py's;
WL4 is the server's cycles per exchange (section 10's CPU per connection for every M cell). The
job's warm-up phase runs before the first session (bench/run/sessions.py). A frozen run needs the
freeze guard with the pilot entry and rule E's file (W's gate), the entries W's runners apply, the
W job's context and W's ports outside its excluded ranges.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import m_run  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402
import wcellwin  # noqa: E402
import wrunlib  # noqa: E402

RUNNER = "wm_run"
INPROC_PORTS = m_run.INPROC_PORTS
USED_PORTS = [(INPROC_PORTS["A"], INPROC_PORTS["A"] + 5), (INPROC_PORTS["B"], INPROC_PORTS["B"] + 5)]


def w_m_cells(r: int, rule_e: dict) -> list[SS.Cell]:
    return m_run.m_cells(r, rule_e, None, "cells", host="W")


def main(argv=None) -> int:
    wrunlib.install_stop()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    wrunlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path)
    a = ap.parse_args(argv)
    runlib.check_mode_args(a)
    job_ctx = wrunlib.check_job_context(a.development)
    ports = wrunlib.check_ports(USED_PORTS)
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_ORDER_M_W")
    runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    cells = runlib.only_cells(a, w_m_cells(a.dev_r or m_run.R_M, rule_e))
    prov = wrunlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = wrunlib.freeze_check(a, prov, ("oneport", "opgen"), rule_e=a.rule_e)
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, job_context=job_ctx, ports=ports), indent=1))
    blocks = window.SourceBlocks(a.blocks)

    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        return wcellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src, port=INPROC_PORTS[arm]), session, arm, position, blocks,
                            a.out / "raw", clr)

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
        print(f"wm_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
