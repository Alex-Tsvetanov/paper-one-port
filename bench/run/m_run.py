#!/usr/bin/env python3
"""The mechanism family's runner on L (hypotheses.md 5.3, 6.3, WL1, WL6, 4.1, 4.7; 9.3's M2_RATE).

    m_run.py --build DIR --out DIR --job NAME [--part cells|m2-rate]
             --seeds SEEDS.json --code-freeze SHA --gate gate-L.json --pilot PILOT.json --rule-e RULE_E.json
             [--m2-rates M2_RATES.json]
    m_run.py ... --development --dev-seed N [--only CELL,...] [--dev-r R] [--dev-m2-rate R]

Part cells: L's 18 cells of 6.3 (M1 on epoll and io_uring, M2, M3), R_M = 16 each, in one order
shuffled with SEED_ORDER_M_L (4.7; W's M1 cells run on W):
- M1 (in-process churn, WL1, section 4.1's in-process placement): arm A the default detection mode
  of rule E, arm B the other; both one-port mode, in-process dispatch (bench/run/cellwin.py);
  rows family "M1", detect per arm (analysis/rows.py: the default is the numerator);
- M2 (WL6 at M2_RATE, open loop, both arms in the hand-off placement): arm A the server in one-port
  mode with in-process dispatch alone on CPU 14, arm B the server's relay on CPU 14 in front of a
  server in dedicated mode, on the cell's backend, on CPUs 10 and 12 (the backend that terminates
  TLS, 5.3), its two workers' listener layout M2_BACKEND_LISTENER (--dev-backend-listener in
  development; M7d), with rule E's relay copy; rows family "M2", metric {"name": "wl6_cpu_us_per_conn"}:
  the CPU time of the front and the backend together (the server alone in-process) per exchange
  due in the window that completed (bench/run/handoff.py);
- M3 (WL1 churn through one front core, the stub backend): arm A the server's relay on epoll with
  rule E's default detection mode and relay copy, arm B the proxy in its M3 configuration (HAProxy
  with option splice-auto where rule E chose splice); rows family "M3" (handoff.py's).
Listen overflows invalidate an M1 or M2 window and are recorded beside the M3 cells (section 7).

Part m2-rate (9.3, WL6): M2_RATE per M2 cell is RATE_FRAC x the smaller of its two arms' median
closed-loop connections per second over 6 development sessions on the frozen binary after the pilot
entry; each arm's value in a session is the mean of its two windows, over the valid sessions. Its
rows are development data (development: true) in any mode; it writes m2_rates.json, with a rate of
null for a cell where an arm has no valid session (section 7 invalidates every relay window whose
backend core is more than 90% busy, as in M2's TLS cells in e2e1).

An M2 cell whose rate is null is not run in part cells (a design choice of the revision log's entry
"M7c's open items, before the code freeze", 2026-10-04, item 6): no open-loop window can be defined
without its rate, and section 9 allows no rate by another rule, so the cell has no valid session,
cannot be tested and enters Holm with p = 1 (4.1, 4.2), "a difference was not shown" (section 12).
The runner lists it in not-run-<job>.json with why, and starts no window for it.
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

sys.path.insert(0, str(runlib.REPO / "analysis"))
import cells as C  # noqa: E402

R_M = C.R_M
M2_RATE_SESSIONS = 6  # WL6: "measured in 6 development sessions per cell"
INPROC_PORTS = {"A": 20000, "B": 20100}  # aa.py's blocks (design choices of M3)
# The listener layout of M2's dedicated backend (two workers on CPUs 10 and 12): a SO_REUSEPORT
# group, one socket per worker (a design choice of M7d, the revision log's entry "The pre-freeze
# items on L (M7d), before the code freeze", item 1: in M7d's development comparison the shared
# listener left one io_uring worker with every TLS handshake, and the group split the connections
# evenly on both backends). --dev-backend-listener shared exists for development comparisons only;
# a frozen run of either part takes the group and checks that the entry is logged.
M2_BACKEND_LISTENER = "reuseport"
OTHER = {"replay": "peek", "peek": "replay"}


def m2_not_run(m2_rates: dict[str, float | None] | None) -> dict[str, str]:
    """Part cells: the M2 cells whose M2_RATE is null in the m2-rate part's file (see the module's
    docstring), each with why."""
    if m2_rates is None:
        return {}
    return {cid: ("not run: no M2_RATE (an arm of the m2-rate part had no valid session; section 9 allows no rate by another "
                  "rule), so the cell has no valid session and enters Holm with p = 1 (4.1, 4.2); revision log, \"M7c's open items, "
                  "before the code freeze\", item 6")
            for cid, rate in m2_rates.items() if rate is None}


def m_cells(r: int, rule_e: dict, m2_rates: dict[str, float] | None, part: str = "cells", m2_sessions: int = M2_RATE_SESSIONS,
            backend_listener: str = M2_BACKEND_LISTENER) -> list[SS.Cell]:
    out = []
    skip = m2_not_run(m2_rates) if part == "cells" else {}
    for c in C.m_cells():
        if c.host != "L":
            continue
        if c.hyp == "M1" and part == "cells":
            d = rule_e["default"][c.backend]
            arm = lambda det: {"family": "M1", "workload": "churn", "proto": c.proto, "backend": c.backend, "mode": "one-port",  # noqa: E731
                               "dispatch": "inproc", "detect": det, "run": {"detect": det}}
            out.append(SS.Cell(c.id, r, {"A": arm(d), "B": arm(OTHER[d])},
                               shared={"kind": "inproc", "workload": "churn", "proto": c.proto, "backend": c.backend, "mode": "one-port"}))
        elif c.hyp == "M2":
            if c.id in skip:
                continue
            d = rule_e["default"][c.backend]
            rc = rule_e["relay_copy"][c.backend]
            rate = None if part == "m2-rate" else (m2_rates or {}).get(c.id)
            fam = "M2" if part == "cells" else "M2-rate"
            a = {"family": fam, "proto": c.proto, "backend": c.backend, "dispatch": "inproc", "system": handoff.SERVER_INPROC,
                 "detect": d, "run": {"system": handoff.SERVER_INPROC}}
            b = {"family": fam, "proto": c.proto, "backend": c.backend, "dispatch": "relay", "system": handoff.SERVER, "detect": d,
                 "relay_copy": rc, "run": {"system": handoff.SERVER}}
            out.append(SS.Cell(c.id, m2_sessions if part == "m2-rate" else r, {"A": a, "B": b},
                               shared={"kind": "handoff", "proto": c.proto, "backend": c.backend, "detect": d, "relay_copy": rc,
                                       "backend_kind": "dedicated", "backend_listener": backend_listener, "rate": rate,
                                       "overflow_invalidates": True, "m2_metric": part == "cells"}))
        elif c.hyp == "M3" and part == "cells":
            d = rule_e["default"]["epoll"]
            rc = rule_e["relay_copy"]["epoll"]
            a = {"family": "M3", "proto": c.proto, "system": C.SERVER_RELAY, "backend": "epoll", "detect": d, "relay_copy": rc,
                 "run": {"system": handoff.SERVER}}
            b = {"family": "M3", "proto": c.proto, "system": c.system, "backend": "epoll", "run": {"system": c.system}}
            out.append(SS.Cell(c.id, r, {"A": a, "B": b},
                               shared={"kind": "handoff", "proto": c.proto, "backend": "epoll", "detect": d, "relay_copy": rc,
                                       "backend_kind": "stub", "rate": None, "overflow_invalidates": False}))
    return out


def window_fn(a: argparse.Namespace, blocks: window.SourceBlocks):
    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        if p["kind"] == "inproc":
            return cellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src, port=INPROC_PORTS[arm]), session, arm, position,
                               blocks, a.out / "raw", clr)
        if cell.id.startswith("M2.") and p.get("m2_metric") and not p.get("rate"):
            raise window.WindowError(f"{cell.id}: no M2_RATE")
        cfg = {"build": a.build, "proto": p["proto"], "k_src": a.k_src, "cell": cell.id, "arms": {arm: p["system"]},
               "ports": dict(handoff.PORTS), "backend": p["backend"], "detect": p["detect"], "relay_copy": p["relay_copy"],
               "backend_kind": p["backend_kind"], "backend_listener": p.get("backend_listener", "shared"), "rate": p.get("rate"),
               "overflow_invalidates": p["overflow_invalidates"], "family": cell.arms[arm]["family"]}
        row = handoff.run_window(cfg, session, arm, position, blocks, a.out / "raw")
        if p.get("m2_metric"):
            row["window_metric"] = row.get("metric")
            v = row.get("wl6_cpu_us_per_exchange")
            row["metric"] = {"name": C.M2_METRIC, "value": v}
            if v is None and row.get("valid"):
                row["valid"] = False
                row.setdefault("invalid_reasons", []).append("no WL6 CPU time per connection")
        return row
    return win


def binaries_for(cell: SS.Cell, arm: str) -> tuple[str, ...]:
    return ("oneport", "opgen")  # the server (front, backend or stub) and the generator; a proxy is not first-party


def m2_rates_from(rows: list[dict], cells: list[SS.Cell]) -> dict[str, dict]:
    """WL6: RATE_FRAC x the smaller of the two arms' median closed-loop connections per second."""
    st = SS.states(rows)
    out = {}
    for c in cells:
        per_arm: dict[str, list[float]] = {"A": [], "B": []}
        for s in st.values():
            if s.cell != c.id or not s.valid:
                continue
            for arm in ("A", "B"):
                v = [float(r["metric"]["value"]) for r in s.rows if r.get("arm") == arm]
                if len(v) == 2:
                    per_arm[arm].append(sum(v) / 2)
        med = {arm: statistics.median(v) if v else None for arm, v in per_arm.items()}
        slower = min((m for m in med.values() if m is not None), default=None) if all(med.values()) else None
        out[c.id] = {"sessions": {arm: len(v) for arm, v in per_arm.items()}, "median_conn_per_s": med,
                     "rate": runlib.RATE_FRAC * slower if slower is not None else None}
    return out


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    runlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path)
    ap.add_argument("--part", default="cells", choices=("cells", "m2-rate"))
    ap.add_argument("--m2-rates", type=Path, help="m2_rates.json of the m2-rate part, as the revision log records it")
    ap.add_argument("--dev-m2-rate", type=float, help="development mode: one open-loop rate for every M2 cell")
    ap.add_argument("--dev-backend-listener", choices=handoff.BACKEND_LISTENERS,
                    help=f"development mode: the listener layout of M2's dedicated backend (default {M2_BACKEND_LISTENER})")
    a = ap.parse_args(argv)
    if a.part == "m2-rate" and not a.development:
        # Development sessions on the frozen binary after the pilot entry (WL6): the rows say
        # development and the order is a development seed's, but the run needs the guard.
        if a.dev_seed is None:
            raise runlib.InputRefused("the m2-rate part's sessions are development sessions: give --dev-seed")
        for flag in ("seeds", "code_freeze", "pilot", "rule_e"):
            if getattr(a, flag) is None:
                raise runlib.InputRefused(f"the m2-rate part on the frozen binary needs --{flag.replace('_', '-')}")
        if not a.gate:
            raise runlib.InputRefused("the m2-rate part on the frozen binary needs --gate")
        for flag in ("dev_r", "max_sessions", "only", "dev_backend_listener"):
            if getattr(a, flag) is not None:
                raise runlib.InputRefused(f"--{flag.replace('_', '-')} is for development runs only")
    else:
        runlib.check_mode_args(a)
    a.out.mkdir(parents=True, exist_ok=True)
    seed = a.dev_seed if (a.development or a.part == "m2-rate") else runlib.order_seed(a, "SEED_ORDER_M_L")[0]
    runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    m2_rates = None
    if a.part == "cells":
        if a.m2_rates is not None:
            m2_rates = {k: v["rate"] for k, v in json.loads(a.m2_rates.read_text()).items()}
        elif a.development and a.dev_m2_rate is not None:
            m2_rates = {c.id: a.dev_m2_rate for c in C.m_cells() if c.hyp == "M2"}
        elif not a.development:
            raise runlib.InputRefused("a frozen M run reads M2's rates (--m2-rates)")
    not_run = m2_not_run(m2_rates) if a.part == "cells" else {}
    if a.dev_backend_listener is not None and not a.development:
        raise runlib.InputRefused("--dev-backend-listener is for development runs only")
    listener = a.dev_backend_listener or M2_BACKEND_LISTENER
    cells = runlib.only_cells(a, m_cells(a.dev_r or R_M, rule_e, m2_rates, a.part, a.dev_r or M2_RATE_SESSIONS, listener))
    prov = runlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, pilot=a.pilot, rule_e=a.rule_e,
                                       m2_rates=a.m2_rates if a.part == "cells" else None,
                                       binaries=runlib.binaries_of(prov, ("oneport", "opgen")),
                                       entries=(freeze_guard.M7C_ITEMS, freeze_guard.M7D_ITEMS) if a.part == "cells"
                                       else (freeze_guard.M7D_ITEMS,))
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, m2_rates=m2_rates, part=a.part, not_run=not_run),
                                                               indent=1))
    if a.part == "cells":
        (a.out / f"not-run-{a.job}.json").write_text(json.dumps(not_run, indent=1))
    blocks = window.SourceBlocks(a.blocks)
    eng = SS.Engine("m_run" if a.part == "cells" else "m_run.m2-rate", a.job, a.out, cells, SS.make_plan(cells, seed),
                    window_fn(a, blocks), lambda c, arm: runlib.arm_provenance(prov, a.build, binaries_for(c, arm)),
                    a.development or a.part == "m2-rate", clearance, fingerprint=window.pin_fingerprint,
                    stop_after_sessions=a.max_sessions)
    summ = eng.run()
    if a.part == "m2-rate":
        rates = m2_rates_from(eng.rows(), cells)
        (a.out / "m2_rates.json").write_text(json.dumps(rates, indent=1, sort_keys=True) + "\n")
        print(json.dumps(rates), flush=True)
    print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, freeze_guard.FreezeRefused) as e:
        print(f"m_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
