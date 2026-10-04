#!/usr/bin/env python3
"""Rule E's choices on L (hypotheses.md section 8, rule E; 9.3) and rule E's file.

    rule_e.py run    --build DIR --out DIR --job NAME --dev-seed N
                     (--seeds SEEDS.json --code-freeze SHA --gate gate-L.json --pilot PILOT.json | --development)
    rule_e.py decide --evidence-l OUT/rule_e_evidence_L.json [--evidence-w W.json | --development] --out RULE_E.json

The frozen text: "Three choices per backend: the default detection mode, the IOCP receive form ...,
and the relay copy ... An option replaces the proposed default (replay; the zero-byte receive;
user-space buffers) only if every session of at least 6 development sessions of HTTP/1.1 churn
favours it and its operations per connection are not higher." The IOCP receive form is decided
(the coordinator's decision of 2026-10-03: the zero-byte form is rule E's only candidate, so no
session runs for it); it governs dedicated mode on W and is decided before W's pilot, in dedicated
mode. The other two exist only in one-port mode and are decided after the pilot entry, before any
confirmatory window. So on L, after the pilot entry, per Linux backend:
- detection: 6 development sessions of HTTP/1.1 churn (WL1), in-process, the server in one-port
  mode, arm A replay (the proposed default), arm B peek (the option); X Y Y X, X drawn per session
  from the development seed; a session with an invalid window runs again (4.1's rule, at most 2);
- relay copy: 6 development sessions of HTTP/1.1 churn through the server's relay in front of the
  stub (M3's arrangement, section 4.1's hand-off placement), on the backend, arm A user-space
  buffers, arm B splice.
The option replaces the default when (a reading of the frozen text, design/status.md M7c): the
backend has at least 6 valid sessions; in every valid session the option's connections per second
(the mean of its two windows) are strictly higher than the default's; and the option's operations
per connection are not higher, operations being the server's counters of every call by kind
(accept, receive, peek, zero-byte receive, send, setsockopt, the check of 1(b), epoll_wait,
epoll_ctl, io_uring_enter, GetQueuedCompletionStatus, connect, splice, shutdown) plus io_uring's
submissions by opcode, over each window's server process, per connection it accepted (WL5, the M3
entry's item 6), averaged over the arm's valid windows. Every row is development data.

`decide` writes rule E's file in the form analysis/ reads (bench/run/runlib.py): the default
detection mode per backend (IOCP's from W's evidence file of the same form, made on W by W's runner;
in development mode, without it, the proposed default, and the evidence says so), the relay copy per
Linux backend, and iocp_receive "zero-byte". The file is then logged in the revision log with its
sha256 ("rule E" on the line), and the frozen runners check it (bench/run/freeze_guard.py).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cellwin  # noqa: E402
import freeze_guard  # noqa: E402
import handoff  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402

SESSIONS = 6  # rule E: "at least 6 development sessions"
CHOICES = {"detect": ("replay", "peek"), "relay": ("user-space", "splice")}  # (proposed default, option)
OP_COUNTERS = ("accept_calls", "recv_calls", "peek_calls", "zero_byte_recv_calls", "send_calls", "setsockopt_calls", "check_calls",
               "epoll_wait_calls", "epoll_ctl_calls", "io_uring_enter_calls", "gqcs_calls", "connect_calls", "splice_calls",
               "shutdown_calls")
INPROC_PORTS = {"A": 20000, "B": 20100}


def rule_e_cells(r: int) -> list[SS.Cell]:
    out = []
    for backend in runlib.COST_BACKENDS_L:
        d, o = CHOICES["detect"]
        arm = lambda det: {"family": "rule-e", "choice": "detect", "workload": "churn", "proto": "http1", "backend": backend,  # noqa: E731
                           "mode": "one-port", "dispatch": "inproc", "detect": det, "run": {"detect": det}}
        out.append(SS.Cell(f"rule-e.detect.{backend}", r, {"A": arm(d), "B": arm(o)},
                           shared={"kind": "inproc", "workload": "churn", "proto": "http1", "backend": backend, "mode": "one-port"}))
        d, o = CHOICES["relay"]
        arm = lambda rc: {"family": "rule-e", "choice": "relay", "proto": "http1", "backend": backend, "system": handoff.SERVER,  # noqa: E731
                          "detect": "replay", "relay_copy": rc, "run": {"relay_copy": rc}}
        out.append(SS.Cell(f"rule-e.relay.{backend}", r, {"A": arm(d), "B": arm(o)},
                           shared={"kind": "handoff", "proto": "http1", "backend": backend}))
    return out


def ops_per_connection(counters: dict) -> float | None:
    acc = counters.get("accepted") or 0
    if not acc:
        return None
    n = sum(int(counters.get(k) or 0) for k in OP_COUNTERS)
    n += sum(int(v) for v in (counters.get("io_uring_submissions") or {}).values() if isinstance(v, int))
    return n / acc


def evidence(rows: list[dict], cells: list[SS.Cell]) -> dict:
    """Per backend and choice: the sessions, whether every valid session favours the option, the
    operations per connection of each arm, and the choice by rule E."""
    st = SS.states(rows)
    out: dict = {}
    for c in cells:
        choice, backend = c.id.split(".")[1:]
        default, option = CHOICES[choice]
        label = {"A": default, "B": option}
        ratios, ops = [], {default: [], option: []}
        for s in sorted((s for s in st.values() if s.cell == c.id), key=lambda s: s.order_index):
            if not s.valid:
                continue
            arm_v = {}
            for arm in ("A", "B"):
                ws = [r for r in s.rows if r.get("arm") == arm]
                arm_v[arm] = statistics.fmean(float(r["metric"]["value"]) for r in ws)
                for r in ws:
                    o = ops_per_connection(r.get("server_counters") or {})
                    if o is not None:
                        ops[label[arm]].append(o)
            ratios.append(arm_v["B"] / arm_v["A"] if arm_v["A"] > 0 else None)
        mean_ops = {k: statistics.fmean(v) if v else None for k, v in ops.items()}
        favours = len(ratios) >= SESSIONS and all(x is not None and x > 1.0 for x in ratios)
        not_higher = mean_ops[option] is not None and mean_ops[default] is not None and mean_ops[option] <= mean_ops[default]
        out.setdefault(backend, {})[choice] = {
            "sessions_valid": len(ratios), "ratios_option_over_default": ratios, "every_session_favours_option": favours,
            "ops_per_connection": mean_ops, "option_ops_not_higher": not_higher, "default": default, "option": option,
            "choice": option if favours and not_higher else default}
    return out


def choice_of(ev: dict, backend: str, choice: str, development: bool, notes: dict) -> str:
    """The evidence's choice; in development mode, where the sessions did not run, the proposed
    default, and the notes say so. A frozen decision needs every choice's sessions."""
    got = (ev.get(backend) or {}).get(choice)
    if got is not None:
        return got["choice"]
    if not development:
        raise runlib.InputRefused(f"rule E: no {choice} sessions on {backend} in the evidence")
    notes[f"{backend}.{choice}"] = "development: these sessions did not run, so the proposed default stands in"
    return CHOICES[choice][0]


def decide(ev_l: dict, ev_w: dict | None, development: bool) -> tuple[dict, dict]:
    notes: dict = {}
    default = {b: choice_of(ev_l, b, "detect", development, notes) for b in runlib.COST_BACKENDS_L}
    if ev_w is not None:
        default["IOCP"] = ev_w["IOCP"]["detect"]["choice"]
    elif development:
        default["IOCP"] = "replay"
        notes["IOCP"] = "development: W's sessions did not run, so the proposed default (replay) stands in"
    else:
        raise runlib.InputRefused("rule E's IOCP detection mode comes from W's evidence (--evidence-w)")
    r = {"default": default, "relay_copy": {b: choice_of(ev_l, b, "relay", development, notes) for b in runlib.COST_BACKENDS_L},
         "iocp_receive": "zero-byte"}
    return runlib.check_rule_e(r), notes


def run(a: argparse.Namespace) -> int:
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
    a.out.mkdir(parents=True, exist_ok=True)
    cells = runlib.only_cells(a, rule_e_cells(a.dev_r or SESSIONS))
    prov = runlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, pilot=a.pilot,
                                       binaries=runlib.binaries_of(prov, ("oneport", "opgen")), entries=(freeze_guard.M7E_ITEMS,))
    blocks = window.SourceBlocks(a.blocks)

    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        if p["kind"] == "inproc":
            return cellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src, port=INPROC_PORTS[arm]), session, arm, position, blocks,
                               a.out / "raw", clr)
        cfg = {"build": a.build, "proto": "http1", "k_src": a.k_src, "cell": cell.id, "arms": {arm: handoff.SERVER},
               "ports": dict(handoff.PORTS), "backend": p["backend"], "detect": "replay", "relay_copy": p["relay_copy"],
               "backend_kind": "stub", "overflow_invalidates": True, "family": "rule-e"}
        return handoff.run_window(cfg, session, arm, position, blocks, a.out / "raw")

    eng = SS.Engine("rule_e", a.job, a.out, cells, SS.make_plan(cells, a.dev_seed), win,
                    lambda c, arm: runlib.arm_provenance(prov, a.build, ("oneport", "opgen")), True, clearance,
                    fingerprint=window.pin_fingerprint, stop_after_sessions=a.max_sessions)
    eng.run()
    ev = evidence(eng.rows(), cells)
    doc = {"host": "L", "development_sessions": True, "frozen_binary": not a.development, "evidence": ev,
           "provenance": {k: prov.get(k) for k in ("commit", "inputs_hash_gate")}, "freeze": clearance.record if clearance else None}
    (a.out / "rule_e_evidence_L.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({b: {c: v["choice"] for c, v in e.items()} for b, e in ev.items()}), flush=True)
    return 0


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    runlib.common_args(r)
    d = sub.add_parser("decide")
    d.add_argument("--evidence-l", type=Path, required=True)
    d.add_argument("--evidence-w", type=Path)
    d.add_argument("--development", action="store_true")
    d.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run(a)
    ev_l = json.loads(a.evidence_l.read_text())["evidence"]
    ev_w = json.loads(a.evidence_w.read_text())["evidence"] if a.evidence_w else None
    rule, notes = decide(ev_l, ev_w, a.development)
    a.out.write_text(json.dumps(rule, indent=1, sort_keys=True) + "\n")
    (a.out.parent / (a.out.stem + ".notes.json")).write_text(json.dumps({"notes": notes, "evidence_l": str(a.evidence_l),
                                                                          "evidence_w": str(a.evidence_w) if a.evidence_w else None},
                                                                         indent=1) + "\n")
    print(json.dumps(rule), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, freeze_guard.FreezeRefused) as e:
        print(f"rule_e.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
