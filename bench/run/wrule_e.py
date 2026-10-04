#!/usr/bin/env python3
"""Rule E's IOCP detection sessions on W (hypotheses.md section 8, rule E; 9.3) and W's evidence
file, which rule_e.py decide reads on L (--evidence-w).

    wrule_e.py --build DIR --out DIR --job NAME --dev-seed N
               (--seeds SEEDS.json --code-freeze SHA --gate gate-W.json --pilot PILOT.json | --development)

After the pilot entry, on the frozen binary: 6 development sessions of HTTP/1.1 churn (WL1),
in-process, the server in one-port mode on IOCP, arm A replay (the proposed default), arm B peek
(the option); X Y Y X, X drawn per session from the development seed; a session with an invalid
window runs again (4.1's rule, at most 2), as rule_e.py's detection sessions on L (the M7d entry,
item 2, reads rule E's test). The window is bench/run/wcellwin.py's; every row is development data
(family "rule-e"). The IOCP receive form is decided (the coordinator's decision of 2026-10-03: the
zero-byte form), so no session runs for it. rule_e_evidence_W.json holds rule_e.py's evidence for
IOCP's detection mode in the form rule_e.py decide reads: {"host": "W", "evidence": {"IOCP":
{"detect": {...}}}}. The job's warm-up phase runs before the first session (bench/run/sessions.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rule_e  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402
import wcellwin  # noqa: E402
import wrunlib  # noqa: E402

RUNNER = "wrule_e"
INPROC_PORTS = rule_e.INPROC_PORTS
USED_PORTS = [(INPROC_PORTS["A"], INPROC_PORTS["A"] + 5), (INPROC_PORTS["B"], INPROC_PORTS["B"] + 5)]


def w_rule_e_cells(r: int) -> list[SS.Cell]:
    """Rule E's detection choice on IOCP, as rule_e.rule_e_cells builds it for the Linux backends."""
    d, o = rule_e.CHOICES["detect"]

    def arm(det: str) -> dict:
        return {"family": "rule-e", "choice": "detect", "workload": "churn", "proto": "http1", "backend": "IOCP", "mode": "one-port",
                "dispatch": "inproc", "detect": det, "run": {"detect": det}}

    return [SS.Cell("rule-e.detect.IOCP", r, {"A": arm(d), "B": arm(o)},
                    shared={"kind": "inproc", "workload": "churn", "proto": "http1", "backend": "IOCP", "mode": "one-port"})]


def main(argv=None) -> int:
    wrunlib.install_stop()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    wrunlib.common_args(ap)
    a = ap.parse_args(argv)
    if a.dev_seed is None:
        raise runlib.InputRefused("rule E's sessions are development sessions: give --dev-seed")
    if not a.development:
        for flag in ("seeds", "code_freeze", "pilot"):
            if getattr(a, flag) is None:
                raise runlib.InputRefused(f"rule E's sessions on the frozen binary need --{flag.replace('_', '-')}")
        if not a.gate:
            raise runlib.InputRefused("rule E's sessions on the frozen binary need --gate")
    elif a.code_freeze is not None:
        raise runlib.InputRefused("--development takes no --code-freeze")
    job_ctx = wrunlib.check_job_context(a.development)
    ports = wrunlib.check_ports(USED_PORTS)
    a.out.mkdir(parents=True, exist_ok=True)
    cells = runlib.only_cells(a, w_rule_e_cells(a.dev_r or rule_e.SESSIONS))
    prov = wrunlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = wrunlib.freeze_check(a, prov, ("oneport", "opgen"))
    blocks = window.SourceBlocks(a.blocks)

    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        return wcellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src, port=INPROC_PORTS[arm]), session, arm, position, blocks,
                            a.out / "raw", clr)

    eng = SS.Engine(RUNNER, a.job, a.out, cells, SS.make_plan(cells, a.dev_seed), win,
                    lambda c, arm: wrunlib.arm_provenance(prov, a.build, ("oneport", "opgen")), True, clearance,
                    fingerprint=wrunlib.fingerprint, stop_after_sessions=a.max_sessions)
    eng.run()
    ev = rule_e.evidence(eng.rows(), cells)
    doc = {"host": "W", "development_sessions": True, "frozen_binary": not a.development, "evidence": ev, "job_context": job_ctx,
           "ports": ports, "provenance": {k: prov.get(k) for k in ("commit", "inputs_hash_gate")},
           "freeze": clearance.record if clearance else None}
    (a.out / "rule_e_evidence_W.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({b: {c: v["choice"] for c, v in e.items()} for b, e in ev.items()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, wrunlib.freeze_guard.FreezeRefused) as e:
        print(f"wrule_e.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
