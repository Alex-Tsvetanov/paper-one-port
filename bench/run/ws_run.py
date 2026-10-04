#!/usr/bin/env python3
"""Section 10's cells with sessions of their own, on W (hypotheses.md section 10, 4.1, 4.7):
s_run.py's cells with host "W", each at R = 16, in one order shuffled with SEED_ORDER_S_W (4.7: "The
other secondary cells run in one order per host").

    ws_run.py --build DIR --out DIR --job NAME --m-rows M_WINDOWS.jsonl
              --seeds SEEDS.json --code-freeze SHA --gate gate-W.json --pilot PILOT.json --rule-e RULE_E.json
    ws_run.py ... --development --dev-seed N [--only CELL,...] [--dev-r R] [--dev-rate R]

Cells (analysis/cells.py's secondary_cells, W's; rows family "S" with the bullet, as s_run.py's):
- ssh: C1 to C3 of SSH on IOCP, one-port against dedicated mode; the C1 and C2 sessions first, then
  the C3 sessions at RATE_FRAC x the slower arm's median connections per second in the C1 sessions;
- mixed: C1's HTTP/1.1 churn with the fixed background on IOCP, one-port against dedicated mode, the
  silent connections of the dedicated arm on its HTTP/1.1 port (the entry "M7c's open items, before
  the code freeze", item 2), W's placement of the background (bench/run/wcellwin.py; the M7e entry);
- tls-variants: TLS with ALPN h2 on IOCP (opgen's tls-h2), one-port against dedicated mode; TLS with
  session resumption is not run (the M7c open items entry, item 5);
- iocp-forms: AcceptEx with a receive buffer, and the receive form rule E did not choose (the posted
  buffer), each against the default form, both arms one-port mode on a listener without a fallback,
  C1's HTTP/1.1 churn (the M7e entry: a reading, with the workload a design choice);
- m-ttfb: M1's TTFB at a fixed load on IOCP, open loop at RATE_FRAC x the slower arm's median
  connections per second in the cell's closed-loop sessions, read from W's M rows (--m-rows);
- two-cores on IOCP: not run in P3 (the coordinator's decision, the M7e entry), listed with why.
Every one-port window of a cell that pairs it with dedicated mode (ssh, mixed, tls-variants) needs
the freeze guard's clearance; in development mode that arm is a stub (bench/run/sessions.py). The
job's warm-up phase runs before the first session.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import freeze_guard  # noqa: E402
import runlib  # noqa: E402
import s_run  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402
import wcellwin  # noqa: E402
import wrunlib  # noqa: E402

RUNNER = "ws_run"
INPROC_PORTS = s_run.INPROC_PORTS
USED_PORTS = [(INPROC_PORTS["A"], INPROC_PORTS["A"] + 5), (INPROC_PORTS["B"], INPROC_PORTS["B"] + 5)]


def w_s_cells(r: int, rule_e: dict, silent_ports: str | None) -> tuple[list[SS.Cell], dict[str, str]]:
    return s_run.s_cells(r, rule_e, silent_ports, host="W")


def main(argv=None) -> int:
    wrunlib.install_stop()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    wrunlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path)
    ap.add_argument("--silent-ports", choices=("http1", "spread"), default=s_run.SILENT_PORTS_FROZEN,
                    help="the mixed cell's silent connections in dedicated mode (default http1; a frozen run refuses spread)")
    ap.add_argument("--m-rows", type=Path, action="append", default=[], help="W's M runner's windows.jsonl (m-ttfb's rates)")
    ap.add_argument("--dev-rate", type=float, help="development mode: the open-loop rate of every m-ttfb cell without M rows")
    a = ap.parse_args(argv)
    runlib.check_mode_args(a)
    if not a.development and a.silent_ports != s_run.SILENT_PORTS_FROZEN:
        raise runlib.InputRefused(f"a frozen section 10 run puts the mixed cell's silent connections where the revision log fixes them "
                                  f"(--silent-ports {s_run.SILENT_PORTS_FROZEN}), not {a.silent_ports}")
    job_ctx = wrunlib.check_job_context(a.development)
    ports = wrunlib.check_ports(USED_PORTS)
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_ORDER_S_W")
    runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    cells, skipped = w_s_cells(a.dev_r or s_run.R_S, rule_e, a.silent_ports)
    cells = runlib.only_cells(a, cells)
    m_rows = [r for p in a.m_rows for r in SS.read_rows(p)]
    rates = {}
    for c in cells:
        if "m_cell" in c.shared:
            rr = s_run.slower_median_rate(m_rows, c.shared["m_cell"])
            if rr["rate"] is None and a.development and a.dev_rate is not None:
                rr = dict(rr, rate=a.dev_rate, development_rate=True)
            c.shared["rate"] = rr["rate"]
            rates[c.id] = rr
    prov = wrunlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        if not a.m_rows:
            raise runlib.InputRefused("a frozen section 10 run reads W's M runner's rows for m-ttfb's rates (--m-rows)")
        clearance = wrunlib.freeze_check(a, prov, ("oneport", "opgen", "opcase"), rule_e=a.rule_e, extra_entries=(freeze_guard.M7C_ITEMS,))
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, not_run=skipped, m_ttfb_rates=rates, job_context=job_ctx,
                                                                    ports=ports), indent=1))
    blocks = window.SourceBlocks(a.blocks)

    def win(cell: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = cell.run_params(arm)
        if p.get("workload") == "open" and p.get("rate") is None:
            raise window.WindowError(f"{cell.id}: no open-loop rate (the closed-loop sessions it is taken from)")
        if p["kind"] != "inproc":
            raise window.WindowError(f"{cell.id}: W runs in-process cells only")
        return wcellwin.run(dict(p, build=a.build, cell=cell.id, k_src=a.k_src, port=INPROC_PORTS[arm]), session, arm, position, blocks,
                            a.out / "raw", clr)

    def before_group(gi: int, eng: SS.Engine) -> None:
        if gi == 1:
            got = {}
            for c in eng.cells:
                if c.id.startswith("S.ssh.C3."):
                    c1 = c.id.replace("S.ssh.C3.", "S.ssh.C1.")
                    rr = s_run.slower_median_rate(eng.rows(), c1)
                    c.shared["rate"] = rr["rate"]
                    got[c.id] = rr
            (a.out / f"ssh-rates-{a.job}.json").write_text(json.dumps(got, indent=1))

    def binaries(cell: SS.Cell, arm: str) -> tuple[str, ...]:
        return ("oneport", "opgen", "opcase") if "background" in cell.shared else ("oneport", "opgen")

    eng = SS.Engine(RUNNER, a.job, a.out, cells, SS.make_plan(cells, seed), win,
                    lambda c, arm: wrunlib.arm_provenance(prov, a.build, binaries(c, arm)), a.development, clearance,
                    fingerprint=wrunlib.fingerprint, before_group=before_group, stop_after_sessions=a.max_sessions)
    summ = eng.run()
    summ["not_run"] = skipped
    (a.out / f"not-run-{a.job}.json").write_text(json.dumps(skipped, indent=1))
    print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, wrunlib.freeze_guard.FreezeRefused) as e:
        print(f"ws_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
