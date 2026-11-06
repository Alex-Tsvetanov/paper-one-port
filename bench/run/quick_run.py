#!/usr/bin/env python3
"""The runner of P3's quick benchmarks, on L and on W (quick-plan.md; decisions d006 and d007, option E).

    quick_run.py --plan bench/run/plans/quick/STEM.json --build DIR --out DIR --quick SHA256_OF_PLAN
                 (--seed N | --seeds design/seeds.json) [--job NAME] [--k-src 16] [--tools DIR] [--blocks FILE]

One plan is one campaign of at most 600 s. The runner refuses unless the plan lives under bench/run/plans/quick/,
its sha256 equals the --quick argument, it is what quick_plans.py makes, its host is this machine's and the build is
a Release build without a sanitizer (bench/run/quick_guard.py). It then runs the plan's cell with the code of the
frozen runners, unchanged: cost_run.py's and wcost_run.py's cost cells (C1, C2), m_run.py's M1 cell, an A/A cell
of two dedicated arms (the arms of aa.py and waa.py) and hardcase_run.py's and whardcase_run.py's part_server (B1
and B2). Sessions are X Y Y X, the order is drawn from the seed, the job warm-up and the reruns are the session
engine's (bench/run/sessions.py). Both arms of a cost cell run with rule E's proposed default detection mode for the
backend (runlib.PROPOSED_RULE_E, replay on all three).

What this runner changes against a frozen run, and nothing else:
- the freeze guard is not asked (there is no pilot entry for the new campaigns); the plan-hash gate replaces it. It lifts
  the one-port against dedicated refusal of the engine and of cellwin.guard for this plan only (QuickClearance);
- every row says development: false, as the analysis's frozen check reads it, and also quick: true, quick_plan,
  quick_plan_sha256 and campaign: "quick", and provenance.freeze names the plan and no pilot entry. `mode` stays the
  arm's mode (one-port or dedicated), which the engine and the analysis read;
- the order's seed is given on the command line (or read from the seeds file under the plan's seed name) and is in
  every row (`seed`) and in quick.json;
- the output goes to --out and nowhere else. Quick rows are not gated by bench/check_rows.py (the build is made for the
  job and has no records); the build's inputs hash and binaries' sha256 are in the rows' provenance.

The hard-case plans run no sessions: part_server runs the plan's cases and entries at the plan's replicates, with G
and GAP_SPLIT from the pilot entry output that the plan copies. On W the run needs the W lab job's context
(wjob.py run), as every W run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import quick_guard  # noqa: E402
import quick_plans  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402

RUNNER = "quick_run"
LABEL_KEYS = ("quick", "quick_plan", "quick_plan_sha256", "campaign")


class QuickEngine(SS.Engine):
    """The session engine with every row labelled as a quick row (fault rows and rows of a window that failed included)."""
    labels: dict = {}

    def finalize(self, row: dict, cell, session: dict, arm: str, position: int, order_index: int) -> dict:
        row = super().finalize(row, cell, session, arm, position, order_index)
        row.update(self.labels)
        return row


def labels_of(stem: str, sha: str) -> dict:
    return {"quick": True, "quick_plan": stem, "quick_plan_sha256": sha, "campaign": "quick"}


def aa_cell(plan: dict, ports: dict[str, int]) -> SS.Cell:
    """The A/A cell: both arms dedicated mode of the same binary, arm B's ports PORT_OFFSET above arm A's, so every change of
    arm changes port (aa.py, waa.py)."""
    c = plan["cells"][0]
    base = {"family": "AA", "workload": plan["workload"], "proto": plan["proto"], "backend": plan["backend"], "detect": plan["detect"],
            "dispatch": "inproc", "mode": "dedicated"}
    shared = {"workload": plan["workload"], "proto": plan["proto"], "backend": plan["backend"], "detect": plan["detect"]}
    return SS.Cell(c["id"], c["r"], {arm: dict(base, run={"mode": "dedicated", "port": ports[arm]}) for arm in ("A", "B")}, shared=shared)


def session_cell(plan: dict, rule_e: dict, host: str, cost_run, m_run) -> SS.Cell:
    """The plan's cell from the frozen runners' own cell builders, picked by its id."""
    want = plan["cells"][0]["id"]
    r = plan["cells"][0]["r"]
    if plan["kind"] == "aa":
        return aa_cell(plan, cost_run.PORTS)
    cells = (cost_run.cost_cells(r, rule_e, {}, host=host) if plan["kind"] == "cost" else m_run.m_cells(r, rule_e, None, "cells", host=host))
    pick = [c for c in cells if c.id == want]
    if len(pick) != 1:
        raise quick_guard.QuickRefused(f"the runners have no cell {want} on {host}")
    cell = pick[0]
    if cell.arms["A"].get("detect") != plan["detect"]:
        raise quick_guard.QuickRefused(f"{want}: arm A's detection mode is {cell.arms['A'].get('detect')}, the plan says {plan['detect']}")
    return cell


def read_seed(a: argparse.Namespace, plan: dict) -> int:
    if a.seed is not None:
        if a.seeds is not None:
            raise runlib.InputRefused("give --seed or --seeds, not both")
        return int(a.seed)
    if a.seeds is None:
        raise runlib.InputRefused("give --seed N or --seeds FILE (the plan's seed name is read from it)")
    if not plan.get("seed_name"):
        raise runlib.InputRefused("this plan has no seed name; give --seed")
    return runlib.load_seeds(a.seeds)[plan["seed_name"]]


def parse(argv) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--build", type=Path, required=True, help="the Release build to measure")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--quick", required=True, help="the sha256 of the plan file")
    ap.add_argument("--seed", type=int, help="the order's seed, recorded in every row")
    ap.add_argument("--seeds", type=Path, help="the seeds file; the plan's seed name is read from it")
    ap.add_argument("--job", help="the job's name in every row (default: the plan's stem)")
    ap.add_argument("--k-src", type=int, default=16)
    ap.add_argument("--tools", type=Path, help="where inputs_hash.py is (default: the host's)")
    ap.add_argument("--blocks", type=Path, help="the source-block file (default: the host's)")
    return ap.parse_args(argv)


def host_defaults(host: str, a: argparse.Namespace):
    """The host's module set, tools and blocks."""
    if host == "L":
        a.tools = a.tools or Path.home() / "lab" / "p3" / "tools"
        a.blocks = a.blocks or Path.home() / "lab" / "p3" / "src-blocks.json"
        return None
    import wrunlib  # noqa: PLC0415 - W only
    a.tools = a.tools or wrunlib.waa.PAPERS_LAB_BIN
    a.blocks = a.blocks or wrunlib.BLOCKS
    return wrunlib


def run_sessions(plan: dict, stem: str, sha: str, a: argparse.Namespace, host: str, clearance, wrunlib, seed: int, prov: dict,
                 rule_e: dict) -> int:
    import cost_run  # noqa: PLC0415
    import m_run  # noqa: PLC0415
    a.out.mkdir(parents=True, exist_ok=True)
    cell = session_cell(plan, rule_e, host, cost_run, m_run)
    cells = [cell]
    blocks = window.SourceBlocks(a.blocks)
    if host == "L":
        import cellwin as walker  # noqa: PLC0415
        arm_prov = lambda c, arm: runlib.arm_provenance(prov, a.build, ("oneport", "opgen"))  # noqa: E731
        fingerprint = window.pin_fingerprint
    else:
        import wcellwin as walker  # noqa: PLC0415
        arm_prov = lambda c, arm: wrunlib.arm_provenance(prov, a.build, ("oneport", "opgen"))  # noqa: E731
        fingerprint = wrunlib.fingerprint
    extra = {"port": m_run.INPROC_PORTS} if plan["kind"] == "m1" else {}

    def win(c: SS.Cell, arm: str, session: dict, position: int, clr) -> dict:
        p = dict(c.run_params(arm), build=a.build, cell=c.id, k_src=a.k_src)
        if extra:
            p["port"] = extra["port"][arm]
        return walker.run(p, session, arm, position, blocks, a.out / "raw", clr)

    eng = QuickEngine(RUNNER, a.job, a.out, cells, SS.make_plan(cells, seed), win, arm_prov, False, clearance,
                      fingerprint=fingerprint, warmup_s=float(plan["job_warmup_s"]))
    eng.labels = labels_of(stem, sha)
    summ = eng.run()
    print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    return 0


def run_hard(plan: dict, stem: str, sha: str, a: argparse.Namespace, host: str, clearance, wrunlib, prov: dict, rule_e: dict) -> int:
    import hardcase_run as HR  # noqa: PLC0415
    a.out.mkdir(parents=True, exist_ok=True)
    pil = plan["pilot"]
    pilot = {"G": {host: {"G_ms": pil["G_ms"], "hc7_runs": pil["hc7_runs"]}}, "gap_split": {"GAP_SPLIT_ms": pil["gap_split_ms"]}}
    path = a.out / "hardcases.jsonl"
    ns = argparse.Namespace(development=False, dev_g_ms=None, dev_gap_split_ms=None, entries=list(plan["entries"]), cases=list(plan["cases"]),
                            replicates=int(plan["replicates"]), rows_prior=HR.runlib_rows(path), build=a.build, out=a.out, job=a.job)
    if host == "L":
        rprov = runlib.arm_provenance(prov, a.build, ("oneport", "opcase"))
        procs, extra = None, {}
    else:
        import whardcase_run as WH  # noqa: PLC0415
        rprov = wrunlib.arm_provenance(prov, a.build, ("oneport", "opcase"))
        procs, extra = WH.W_CASES, {"host": "W"}
    rprov["freeze"] = clearance.record
    labels = labels_of(stem, sha)

    def emit(row: dict) -> None:
        row.update(job=a.job, development=False, runner=RUNNER, provenance=rprov, recorded=time.strftime("%Y-%m-%dT%H:%M:%S%z"), **extra, **labels)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        if row.get("kind") == "hardcase":
            print(f"{row.get('entry')} {row['id']} r{row['replicate']}: {'pass' if row.get('passed') else row.get('b1')}", flush=True)

    if procs is None:
        table = HR.part_server(ns, pilot, rule_e, prov, clearance, emit)
    else:
        table = HR.part_server(ns, pilot, rule_e, prov, clearance, emit, procs=procs, host=host)
    (a.out / f"hardcases-table-{a.job}.json").write_text(json.dumps(table, indent=1, sort_keys=True))
    # part_server writes a row with passed false and goes on before it updates the table, so the table can miss a failure:
    # the verdict is read from hardcases.jsonl, and a table with no failure is not a pass.
    rows = HR.runlib_rows(path)
    failed_rows = sum(1 for r in rows if r.get("kind") == "hardcase" and r.get("passed") is False)
    failed = sum(1 for v in table.values() if v["passed"] != v["runs"])
    print(f"hard cases (quick, {host}): {len(table)} variant-entries, {failed} with a failing run in the table, "
          f"{failed_rows} failing rows in hardcases.jsonl", flush=True)
    return 1 if failed_rows > 0 or not table else 0


def check_resume(out: Path, stem: str, sha: str) -> None:
    """A folder that holds rows of another plan, or of this plan at another hash, is never extended."""
    rec = out / "quick.json"
    if rec.exists():
        old = json.loads(rec.read_text(encoding="utf-8"))
        if old.get("plan_sha256") != sha or old.get("plan") != stem:
            raise runlib.InputRefused(f"{out} holds the rows of {old.get('plan')} ({old.get('plan_sha256')}), not of {stem}")
    elif any(out.glob("*.jsonl")):
        raise runlib.InputRefused(f"{out} holds rows without a quick.json: a quick run starts in a folder that has none")


def main(argv=None) -> int:
    a = parse(argv)
    plan, stem, clearance = quick_guard.check_plan(a.plan, a.quick, a.build)
    host = plan["host"]
    wrunlib = host_defaults(host, a)
    a.job = a.job or stem
    seed = None if plan["kind"] == "hard" else read_seed(a, plan)
    ports_ctx: dict = {}
    if host == "L":
        window.stop_on_signals()
    else:
        wrunlib.install_stop()
        ports_ctx = {"job_context": wrunlib.check_job_context(False)}
        import wcost_run  # noqa: PLC0415
        import whardcase_run  # noqa: PLC0415
        import wm_run  # noqa: PLC0415
        used = {"hard": whardcase_run.USED_PORTS, "m1": wm_run.USED_PORTS}.get(plan["kind"], wcost_run.USED_PORTS)
        ports_ctx["ports"] = wrunlib.check_ports(used)
    a.out.mkdir(parents=True, exist_ok=True)
    check_resume(a.out, stem, a.quick)
    rule_e = runlib.load_rule_e(None, True)  # rule E's proposed defaults, the same as both committed rule_e.json files
    prov = (runlib.job_provenance if host == "L" else wrunlib.job_provenance)(a.build, a.tools, a.out, a.job)
    record = {"plan": stem, "plan_sha256": a.quick, "kind": plan["kind"], "host": host, "seed": seed, "job": a.job, "build": str(a.build),
              "commit": prov.get("commit"), "runner_commit": prov.get("runner_commit"), "runner_dirty": prov.get("runner_dirty"),
              "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "clearance": clearance.record, "expected_worst_case_s": plan["expected_worst_case_s"]}
    (a.out / "quick.json").write_text(json.dumps(record, indent=1))
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, plan=stem, **ports_ctx), indent=1))
    if plan["kind"] == "hard":
        rc = run_hard(plan, stem, a.quick, a, host, clearance, wrunlib, prov, rule_e)
    else:
        rc = run_sessions(plan, stem, a.quick, a, host, clearance, wrunlib, seed, prov, rule_e)
    (a.out / "quick.json").write_text(json.dumps(dict(record, ended=time.strftime("%Y-%m-%dT%H:%M:%S%z"), exit=rc), indent=1))
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, quick_guard.QuickRefused) as e:
        print(f"quick_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
