#!/usr/bin/env python3
"""The development end-to-end check of the frozen runners (M7c): their rows fed to analysis/, and
their binaries bound to a dry run's records. Development data only: whatever it binds is never
citable, and it says so in its output.

    devcheck.py --gate DRYRUN/gate-L.json --seeds DEV_SEEDS.json [--rule-e RULE_E.json]
                --pilot-rows W.jsonl --parts P.jsonl --rows W.jsonl [...] [--hardcases H.jsonl] --out DEVCHECK.json

What it checks:
- every row is development data (development: true), none a dry run or synthetic
  (analysis/rows.py's refuse_flags with frozen=False: the CLIs refuse development rows, so this
  check calls the library functions; numpy's version is not checked by them, analysis/versions.py);
- the gate: bench/check_rows.py's rule against the dry run's gate (load_gates with
  accept_dry_run, M7c), every row that ran a binary bound to the gate's sha256; a development stub
  row (bench/run/sessions.py: the one-port arm of a cell that pairs it with dedicated mode, which
  ran nothing and names no binary) is counted apart and must say stub, valid false, no binaries;
- the pilot: analysis/pilot.py's pilot_entry on the pilot's rows and parts (the order seed of
  every row checked against the seeds file's SEED_PILOT_L);
- the analysis: analysis/analyse.py's analyse() on every family's rows (cost, B3 with K_BASE's
  ophold windows, M, section 10), with the pilot entry made above and rule E's choices;
- the hard cases: the rows' kinds, and every run's checks named.
Exit 0 when the analysis accepts every input and every row that ran a binary binds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(REPO / "analysis"))

import check_rows  # noqa: E402

import analyse as AN  # noqa: E402
import pilot as PL  # noqa: E402
import rows as RW  # noqa: E402


def read(paths: list[Path]) -> list[dict]:
    return RW.read_rows([p for p in paths if Path(p).exists()])


def gate_check(rows: list[dict], gate: Path) -> dict:
    covered, left = check_rows.load_gates([gate], accept_dry_run=True)
    g = json.loads(gate.read_text(encoding="utf-8"))
    stubs = [r for r in rows if r.get("stub")]
    bad_stubs = [r for r in stubs if r.get("valid") or (r.get("provenance") or {}).get("binaries")]
    ran = [r for r in rows if not r.get("stub")]
    refused = check_rows.check(ran, covered)
    return {"gate": str(gate), "gate_dry_run": bool(g.get("dry_run")), "gate_citable": g.get("citable"), "citable": False,
            "rows": len(rows), "bound": len(ran) - len(refused), "refused": refused[:10], "refused_count": len(refused),
            "stub_rows": len(stubs), "stub_rows_wrong": len(bad_stubs), "left_out": left,
            "binaries_seen": sorted({f"{n} {s[:12]}" for r in ran for n, s in ((r.get("provenance") or {}).get("binaries") or {}).items()})}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gate", type=Path, required=True)
    ap.add_argument("--seeds", type=Path, required=True)
    ap.add_argument("--rule-e", type=Path)
    ap.add_argument("--pilot-rows", type=Path, action="append", default=[])
    ap.add_argument("--parts", type=Path, action="append", default=[])
    ap.add_argument("--rows", type=Path, action="append", default=[])
    ap.add_argument("--hardcases", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    seeds = json.loads(a.seeds.read_text(encoding="utf-8"))
    # Without a rule E file, the proposed defaults (bench/run/runlib.py's PROPOSED_RULE_E).
    rule_e = json.loads(a.rule_e.read_text(encoding="utf-8")) if a.rule_e else {
        "default": {"epoll": "replay", "io_uring": "replay", "IOCP": "replay"},
        "relay_copy": {"epoll": "user-space", "io_uring": "user-space"}, "iocp_receive": "zero-byte"}
    out: dict = {"citable": False, "development": True, "what": "M7c's end-to-end check of the runners on development rows"}
    ok = True
    pilot_rows, parts, rows = read(a.pilot_rows), read(a.parts), read(a.rows)
    hard = read(a.hardcases)
    everything = pilot_rows + parts + rows + hard
    try:
        RW.refuse_flags(everything, frozen=False, allow_synthetic=False)
        out["flags"] = {"rows": len(everything), "all_development": all(r.get("development") is True for r in everything)}
        ok &= out["flags"]["all_development"]
    except RW.RowsRefused as e:
        out["flags"] = {"refused": str(e)}
        ok = False
    out["gate"] = gate_check(everything, a.gate)
    ok &= out["gate"]["refused_count"] == 0 and out["gate"]["stub_rows_wrong"] == 0
    pilot = None
    if pilot_rows:
        try:
            pilot = PL.pilot_entry(pilot_rows, parts, seeds, n_sim=PL.N_SIM)
            out["pilot"] = {k: pilot[k] for k in ("complete", "incomplete", "R_C", "m_C", "resolved", "rates", "G", "gap_split")}
            out["pilot"]["cells"] = [{k: c.get(k) for k in ("cell", "sessions", "valid_sessions", "ratios", "why_not_simulated")}
                                     for c in pilot["cells"] if c["sessions"]]
        except (RW.RowsRefused, RW.RowError) as e:
            out["pilot"] = {"refused": str(e)}
            ok = False
    if rows:
        if pilot is None:
            pilot = {"R_C": 31, "m_C": 0, "resolved": [], "joint_powers": [], "rates": {}}
        try:
            summ = AN.analyse(rows, pilot=pilot, rule_e=rule_e, seeds=seeds)
            fams = {f: {"cells_with_sessions": sum(1 for x in summ["families"][f]["cells"] if x["sessions"]),
                        "sessions": sum(x["sessions"] for x in summ["families"][f]["cells"]),
                        "tested": sum(1 for x in summ["families"][f]["cells"] if x["tested"]),
                        "verdicts": sorted({x["verdict"] for x in summ["families"][f]["cells"] if x["sessions"]})} for f in summ["families"]}
            sec = [x for x in summ["secondary"] if x.get("valid_sessions")]
            out["analysis"] = {"accepted": True, "families": fams, "secondary_with_valid_sessions": [(x["bullet"], x["cell"], x["valid_sessions"])
                                                                                                     for x in sec],
                               "k_base": summ["k_base"], "b1_failures": summ["b1_failures"]}
        except (RW.RowsRefused, RW.RowError) as e:
            out["analysis"] = {"accepted": False, "refused": str(e)}
            ok = False
    if hard:
        runs = [r for r in hard if r.get("kind") == "hardcase"]
        comp = [r for r in hard if r.get("kind") == "competitor-case"]
        out["hardcases"] = {"runs": len(runs), "passed": sum(1 for r in runs if r.get("passed")),
                            "failed": [{k: r.get(k) for k in ("entry", "id", "replicate", "b1", "b2_failed")} for r in runs if not r.get("passed")][:20],
                            "servers": [{k: r.get(k) for k in ("entry", "server", "ok", "problems")} for r in hard if r.get("kind") == "hardcase-servers"],
                            "competitor_runs": len(comp),
                            "competitor_as_expected": sum(1 for r in comp if r.get("reply_as_the_server_table_expects"))}
    out["ok"] = bool(ok)
    a.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": out["ok"], "gate": {k: out["gate"][k] for k in ("bound", "refused_count", "stub_rows", "citable")},
                      "analysis": (out.get("analysis") or {}).get("accepted"), "pilot": (out.get("pilot") or {}).get("R_C")}), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
