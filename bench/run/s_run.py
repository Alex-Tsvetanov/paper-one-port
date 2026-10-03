#!/usr/bin/env python3
"""Section 10's cells with sessions of their own, on L (hypotheses.md section 10, 4.1, 4.7), each at
R = 16, in one order per host shuffled with SEED_ORDER_S_L (4.7: "The other secondary cells run in
one order per host"; B3's secondary cells run in B3's order, bench/run/b3_run.py).

    s_run.py --build DIR --out DIR --job NAME --silent-ports http1|spread --m-rows M_WINDOWS.jsonl
             --seeds SEEDS.json --code-freeze SHA --gate gate-L.json --pilot PILOT.json --rule-e RULE_E.json
    s_run.py ... --development --dev-seed N [--only CELL,...] [--dev-r R]

Cells (analysis/cells.py's secondary_cells, L's; rows family "S" with the bullet):
- ssh: C1 to C3 of SSH on epoll and io_uring, one-port against dedicated mode (bench/run/cellwin.py);
  the C1 and C2 sessions first, then the C3 sessions at RATE_FRAC x the slower arm's median
  connections per second in the C1 sessions (section 10), each arm's value the mean of its two
  windows, over the valid sessions;
- mixed: C1's HTTP/1.1 churn with the fixed background (bench/run/cellwin.py, bench/cases/hold.hpp),
  one-port against dedicated mode. Where the silent connections go in dedicated mode the frozen text
  does not say (the proposal's "dedicated mode spreads it over its ports" is not in it): --silent-ports
  has no default, every row names it, and the choice is the coordinator's;
- two-cores: C1's HTTP/1.1 churn with 2 workers on CPUs 12 and 14, one-port against dedicated mode;
  and the SO_REUSEPORT group (arm A) against the shared listener (arm B), both one-port mode;
- relay-io_uring: the server's relay on io_uring (arm A) against each proxy (arm B), M3's
  arrangement otherwise (bench/run/handoff.py);
- m-ttfb: for M1 and M3, TTFB at a fixed load, open loop at RATE_FRAC x the slower arm's median
  connections per second in the cell's closed-loop sessions (section 10), read from the M runner's
  rows (--m-rows);
- tls-variants (TLS with session resumption, TLS with ALPN h2): not run. The frozen binaries cannot
  run them: opgen offers only ALPN http/1.1 and never resumes a session, and the server, by section
  2.1's settings, issues no session ticket and keeps no session cache. Listed as not run, with why.
- iocp-forms: W's cells (W's runner).
Every one-port window of a cell that pairs it with dedicated mode (ssh, mixed, two-cores) needs the
freeze guard's clearance; in development mode that arm is a stub (bench/run/sessions.py).
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

R_S = C.R_SECONDARY
INPROC_PORTS = {"A": 20000, "B": 20100}
NOT_RUN = {"tls-variants": "the frozen generator offers only ALPN http/1.1 and never resumes a TLS session, and the server issues no "
                           "session ticket and keeps no session cache (section 2.1's settings): neither variant can run",
           "iocp-forms": "W's cells, run by W's runner"}


def inproc_arm(bullet: str, hyp: str, proto: str, backend: str, mode: str, detect: str, extra: dict | None = None) -> dict:
    wl = C.HYP_WORKLOAD[hyp]
    f = {"family": "S", "bullet": bullet, "workload": wl, "proto": proto, "backend": backend, "mode": mode, "detect": detect,
         "dispatch": "inproc"}
    f.update(extra or {})
    f["run"] = {"mode": mode, "listener": f.get("listener", "shared")}
    return f


def s_cells(r: int, rule_e: dict, silent_ports: str | None) -> tuple[list[SS.Cell], dict[str, str]]:
    out, skipped = [], {}
    for s in C.secondary_cells():
        if s.host != "L":
            skipped.setdefault(s.id, NOT_RUN.get(s.bullet, "W's cell"))
            continue
        if s.bullet in NOT_RUN:
            skipped[s.id] = NOT_RUN[s.bullet]
            continue
        if s.bullet in ("b3-other-mode",):
            continue  # B3's order (b3_run.py)
        d = rule_e["default"].get(s.backend, "replay")
        if s.bullet == "ssh":
            hyp = s.key[0]
            shared = {"kind": "inproc", "workload": C.HYP_WORKLOAD[hyp], "proto": "ssh", "backend": s.backend, "detect": d,
                      "pairs_dedicated": True}
            out.append(SS.Cell(s.id, r, {"A": inproc_arm("ssh", hyp, "ssh", s.backend, "one-port", d),
                                         "B": inproc_arm("ssh", hyp, "ssh", s.backend, "dedicated", d)},
                               group=1 if hyp == "C3" else 0, shared=shared, pairs_one_port_with_dedicated=True))
        elif s.bullet == "mixed":
            if silent_ports is None:
                skipped[s.id] = "not run: --silent-ports (where silent connections go in dedicated mode) was not given"
                continue
            shared = {"kind": "inproc", "workload": "churn", "proto": "http1", "backend": s.backend, "detect": d, "pairs_dedicated": True,
                      "background": {"silent_ports": silent_ports}}
            extra = {"silent_ports": silent_ports}
            out.append(SS.Cell(s.id, r, {"A": inproc_arm("mixed", "C1", "http1", s.backend, "one-port", d, extra),
                                         "B": inproc_arm("mixed", "C1", "http1", s.backend, "dedicated", d, extra)},
                               shared=shared, pairs_one_port_with_dedicated=True))
        elif s.bullet == "two-cores":
            variant = s.key[2]
            shared = {"kind": "inproc", "workload": "churn", "proto": "http1", "backend": s.backend, "detect": d, "workers": 2,
                      "placement": "two-cores", "pairs_dedicated": variant == "two-cores"}
            if variant == "two-cores":
                arms = {"A": inproc_arm("two-cores", "C1", "http1", s.backend, "one-port", d, {"variant": variant}),
                        "B": inproc_arm("two-cores", "C1", "http1", s.backend, "dedicated", d, {"variant": variant})}
            else:
                arms = {"A": inproc_arm("two-cores", "C1", "http1", s.backend, "one-port", d, {"variant": variant, "listener": "reuseport"}),
                        "B": inproc_arm("two-cores", "C1", "http1", s.backend, "one-port", d, {"variant": variant, "listener": "shared"})}
            out.append(SS.Cell(s.id, r, arms, shared=shared, pairs_one_port_with_dedicated=variant == "two-cores"))
        elif s.bullet == "relay-io_uring":
            proto, system = s.key
            rc = rule_e["relay_copy"]["io_uring"]
            a = {"family": "S", "bullet": "relay-io_uring", "proto": proto, "system": C.SERVER_RELAY, "backend": "io_uring",
                 "detect": rule_e["default"]["io_uring"], "relay_copy": rc, "run": {"system": handoff.SERVER}}
            b = {"family": "S", "bullet": "relay-io_uring", "proto": proto, "system": system, "backend": "io_uring", "run": {"system": system}}
            out.append(SS.Cell(s.id, r, {"A": a, "B": b}, shared={"kind": "handoff", "proto": proto, "backend": "io_uring",
                                                                  "detect": rule_e["default"]["io_uring"], "relay_copy": rc, "rate": None,
                                                                  "overflow_invalidates": False}))
        elif s.bullet == "m-ttfb-cpu":
            mid = s.key[0]
            mc = next(c for c in C.m_cells() if c.id == mid)
            if mc.hyp == "M1":
                arm = lambda det: {"family": "S", "bullet": "m-ttfb", "hyp": "M1", "workload": "open", "proto": mc.proto,  # noqa: E731
                                   "backend": mc.backend, "mode": "one-port", "dispatch": "inproc", "detect": det, "run": {"detect": det}}
                other = {"replay": "peek", "peek": "replay"}[rule_e["default"][mc.backend]]
                out.append(SS.Cell(s.id, r, {"A": arm(rule_e["default"][mc.backend]), "B": arm(other)},
                                   shared={"kind": "inproc", "workload": "open", "proto": mc.proto, "backend": mc.backend, "mode": "one-port",
                                           "m_cell": mid}))
            else:
                rc = rule_e["relay_copy"]["epoll"]
                a = {"family": "S", "bullet": "m-ttfb", "hyp": "M3", "proto": mc.proto, "system": C.SERVER_RELAY, "backend": "epoll",
                     "detect": rule_e["default"]["epoll"], "relay_copy": rc, "workload": "open", "run": {"system": handoff.SERVER}}
                b = {"family": "S", "bullet": "m-ttfb", "hyp": "M3", "proto": mc.proto, "system": mc.system, "backend": "epoll",
                     "workload": "open", "run": {"system": mc.system}}
                out.append(SS.Cell(s.id, r, {"A": a, "B": b}, shared={"kind": "handoff", "proto": mc.proto, "backend": "epoll",
                                                                      "detect": rule_e["default"]["epoll"], "relay_copy": rc,
                                                                      "overflow_invalidates": False, "m_cell": mid}))
    return out, skipped


def slower_median_rate(rows: list[dict], cell: str) -> dict:
    """RATE_FRAC x the slower arm's median connections per second over the cell's valid
    closed-loop sessions (section 10), each arm's value the mean of its two windows."""
    st = SS.states([r for r in rows if r.get("cell") == cell])
    per: dict[str, list[float]] = {}
    for s in st.values():
        if not s.valid:
            continue
        for arm in ("A", "B"):
            v = [float(r["metric"]["value"]) for r in s.rows if r.get("arm") == arm and (r.get("metric") or {}).get("name") == "conn_per_s"]
            if len(v) == 2:
                per.setdefault(arm, []).append(sum(v) / 2)
    med = {arm: statistics.median(v) for arm, v in per.items() if v}
    rate = runlib.RATE_FRAC * min(med.values()) if len(med) == 2 else None
    return {"cell": cell, "sessions": {k: len(v) for k, v in per.items()}, "median_conn_per_s": med, "rate": rate}


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    runlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path)
    ap.add_argument("--silent-ports", choices=("http1", "spread"), help="the mixed cell's silent connections in dedicated mode (no default)")
    ap.add_argument("--m-rows", type=Path, action="append", default=[], help="the M runner's windows.jsonl (m-ttfb's rates)")
    ap.add_argument("--dev-rate", type=float, help="development mode: the open-loop rate of every m-ttfb cell without M rows")
    a = ap.parse_args(argv)
    runlib.check_mode_args(a)
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_ORDER_S_L")
    runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    cells, skipped = s_cells(a.dev_r or R_S, rule_e, a.silent_ports)
    cells = runlib.only_cells(a, cells)
    if not a.development and a.silent_ports is None:
        raise runlib.InputRefused("a frozen section 10 run holds the mixed cells: give --silent-ports")
    m_rows = [r for p in a.m_rows for r in SS.read_rows(p)]
    rates = {}
    for c in cells:
        if "m_cell" in c.shared:
            rr = slower_median_rate(m_rows, c.shared["m_cell"])
            if rr["rate"] is None and a.development and a.dev_rate is not None:
                rr = dict(rr, rate=a.dev_rate, development_rate=True)
            c.shared["rate"] = rr["rate"]
            rates[c.id] = rr
    prov = runlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        if not a.m_rows:
            raise runlib.InputRefused("a frozen section 10 run reads the M runner's rows for m-ttfb's rates (--m-rows)")
        clearance = freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, pilot=a.pilot, rule_e=a.rule_e,
                                       binaries=runlib.binaries_of(prov, ("oneport", "opgen", "opcase")))
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, not_run=skipped, m_ttfb_rates=rates), indent=1))
    blocks = window.SourceBlocks(a.blocks)

    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        if p.get("workload") == "open" and p.get("rate") is None:
            raise window.WindowError(f"{cell.id}: no open-loop rate (the closed-loop sessions it is taken from)")
        if p["kind"] == "inproc":
            return cellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src, port=INPROC_PORTS[arm]), session, arm, position,
                               blocks, a.out / "raw", clr)
        cfg = {"build": a.build, "proto": p["proto"], "k_src": a.k_src, "cell": cell.id, "arms": {arm: p["system"]},
               "ports": dict(handoff.PORTS), "backend": p["backend"], "detect": p["detect"], "relay_copy": p["relay_copy"],
               "backend_kind": "stub", "rate": p.get("rate"), "overflow_invalidates": p["overflow_invalidates"], "family": "S"}
        return handoff.run_window(cfg, session, arm, position, blocks, a.out / "raw")

    def before_group(gi: int, eng: SS.Engine) -> None:
        if gi == 1:
            got = {}
            for c in eng.cells:
                if c.id.startswith("S.ssh.C3."):
                    c1 = c.id.replace("S.ssh.C3.", "S.ssh.C1.")
                    rr = slower_median_rate(eng.rows(), c1)
                    c.shared["rate"] = rr["rate"]
                    got[c.id] = rr
            (a.out / f"ssh-rates-{a.job}.json").write_text(json.dumps(got, indent=1))

    def binaries(cell: SS.Cell, arm: str) -> tuple[str, ...]:
        return ("oneport", "opgen", "opcase") if "background" in cell.shared else ("oneport", "opgen")

    eng = SS.Engine("s_run", a.job, a.out, cells, SS.make_plan(cells, seed), win,
                    lambda c, arm: runlib.arm_provenance(prov, a.build, binaries(c, arm)), a.development, clearance,
                    fingerprint=window.pin_fingerprint, before_group=before_group, stop_after_sessions=a.max_sessions)
    summ = eng.run()
    summ["not_run"] = skipped
    (a.out / f"not-run-{a.job}.json").write_text(json.dumps(skipped, indent=1))
    print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, freeze_guard.FreezeRefused) as e:
        print(f"s_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
