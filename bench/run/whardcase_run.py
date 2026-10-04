#!/usr/bin/env python3
"""The hard cases on W: B1's table and B2's checks on IOCP (hypotheses.md 5.2, Appendix A, WL8),
hardcase_run.py's server part with W's processes.

    whardcase_run.py --build DIR --out DIR --job NAME
                     --seeds SEEDS.json --code-freeze SHA --gate gate-W.json --pilot PILOT.json --rule-e RULE_E.json
    whardcase_run.py ... --development [--cases 1,12] [--entries IOCP.replay.inproc] [--replicates R]
                     [--dev-g-ms G --dev-gap-split-ms GAP]

"Each case runs on every backend, in both detection modes, with in-process and relay dispatch where
it applies, 16 replicates" (Appendix A): on W, IOCP in replay and in peek, in-process only (relay is
Linux only, section 2.1; the M6a entry, item 1), so 2 entries. The timers are section 1's 3 s; G is
G_W and GAP_SPLIT the pilot entry's; HC7 is not run where the pilot entry says G_W is not below T_fb
or W had no valid timer run (9.2). Each one-port server is the measured binary with --record, on
CPU 10, opcase on CPUs 2 to 9 (section 4.1's W placement), one server per listener setup per entry
(the M7d entry, item 4 (c)); every run is `opcase case --id ID --replicates 1`; the run's record
lines are matched by the client's local port once the server has recorded its close; the
expectations come from `opcase case --list`; the judge is hardcase_run.py's, ported line for line
from tests/case_tests.cpp. Rows (kind "hardcase", "hardcase-servers", "hardcase-skipped") and
hardcases-table-<job>.json are hardcase_run.py's, with host "W". The competitors' table runs on L.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import hardcase_run as HR  # noqa: E402
import runlib  # noqa: E402
import window  # noqa: E402
import wcellwin  # noqa: E402
import wrunlib  # noqa: E402
import wsys  # noqa: E402
import wwindow  # noqa: E402

RUNNER = "whardcase_run"
ENTRIES_W = tuple(f"IOCP.{d}.inproc" for d in ("replay", "peek"))
USED_PORTS = [(min(HR.SETUP_PORTS.values()), max(HR.SETUP_PORTS.values()) + 5),
              (min(HR.DEDICATED_PORTS.values()), max(HR.DEDICATED_PORTS.values()) + 5)]


class WServer(HR.Server):
    """hardcase_run's Server on W: started suspended on its CPUs, stopped by its event."""

    def __init__(self, build: Path, args: list[str], cpus: tuple[int, ...], raw: Path, tag: str, record: bool = True):
        self.tag = tag
        self.record = raw / f"{tag}.record.jsonl" if record else None
        cmd = [str(build / wcellwin.ONEPORT)] + args + (["--record", str(self.record)] if record else [])
        self.cmd = cmd
        self.proc = wcellwin.start_err(raw / f"{tag}.err", cmd, cpus, stdout=subprocess.PIPE, cwd=raw)
        self.out = wwindow.ThreadLines(self.proc)
        if not self.out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
            wwindow.stop_server(self.proc, self.out)
            raise window.WindowError(f"{tag}: the server did not start: {self.out.lines[-3:]}")
        self.ports: dict[str, int] = {}
        for ln in self.out.lines:
            if ln.startswith("oneport: listening "):
                name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
                self.ports[name] = int(addr.rsplit(":", 1)[1])
        self.offset = 0
        self.pending: list[dict] = []

    def stop(self) -> tuple[int | None, dict]:
        code, lines, _how = wwindow.stop_server(self.proc, self.out)
        return code, window.parse_counters(lines)


def w_opcase(build: Path, args: list[str], timeout: float) -> tuple[int, list[dict], str]:
    """`opcase case ARGS` on W, on the generator's CPUs (section 4.1); a run that does not end within
    `timeout` is ended and reported as hardcase_run's opcase reports it (subprocess.TimeoutExpired)."""
    cmd = [str(build / wcellwin.OPCASE), "case"] + args
    p = wsys.start_pinned(cmd, wwindow.GEN_CPUS, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        so, se = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()  # a process this runner started
        p.communicate()
        raise
    return p.returncode, [json.loads(ln) for ln in so.decode(errors="replace").splitlines() if ln.startswith("{")], \
        se.decode(errors="replace").strip()[-300:]


W_CASES = HR.CaseProcs(w_opcase, WServer, tuple(wwindow.SERVER_CPUS), ())


def main(argv=None) -> int:
    wrunlib.install_stop()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    wrunlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path)
    ap.add_argument("--cases", type=lambda s: [int(x) for x in s.split(",")], default=list(range(1, 26)))
    ap.add_argument("--entries", type=lambda s: s.split(","), default=list(ENTRIES_W))
    ap.add_argument("--replicates", type=int, default=HR.REPLICATES)
    ap.add_argument("--dev-g-ms", type=int, help="development mode: G without a pilot entry")
    ap.add_argument("--dev-gap-split-ms", type=int, help="development mode: GAP_SPLIT without a pilot entry")
    a = ap.parse_args(argv)
    if a.development and a.dev_seed is None:
        a.dev_seed = 0  # the hard cases have no order to draw
    runlib.check_mode_args(a)
    full = (sorted(a.cases) == list(range(1, 26)) and a.entries == list(ENTRIES_W) and a.replicates == HR.REPLICATES
            and a.dev_g_ms is None and a.dev_gap_split_ms is None)
    if not a.development and not full:
        raise runlib.InputRefused("--cases, --entries, --replicates and the --dev values narrow the frozen run: development only")
    if any(e not in ENTRIES_W for e in a.entries):
        raise runlib.InputRefused(f"entries on W are {ENTRIES_W}")
    job_ctx = wrunlib.check_job_context(a.development)
    ports = wrunlib.check_ports(USED_PORTS)
    a.out.mkdir(parents=True, exist_ok=True)
    pilot = runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    prov = wrunlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = wrunlib.freeze_check(a, prov, ("oneport", "opcase"), rule_e=a.rule_e)
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, rule_e=rule_e, job_context=job_ctx, ports=ports), indent=1))
    path = a.out / "hardcases.jsonl"
    a.rows_prior = HR.runlib_rows(path)
    rprov = wrunlib.arm_provenance(prov, a.build, ("oneport", "opcase"))
    if clearance is not None:
        rprov["freeze"] = clearance.record

    def emit(row: dict) -> None:
        row.update(job=a.job, development=a.development, runner=RUNNER, host="W", provenance=rprov,
                   recorded=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        if row.get("kind") == "hardcase":
            print(f"{row.get('entry')} {row['id']} r{row['replicate']}: {'pass' if row.get('passed') else row.get('b1')}", flush=True)

    table = HR.part_server(a, pilot, rule_e, prov, clearance, emit, procs=W_CASES, host="W")
    (a.out / f"hardcases-table-{a.job}.json").write_text(json.dumps(table, indent=1, sort_keys=True))
    failed = sum(1 for v in table.values() if v["passed"] != v["runs"])
    print(f"hard cases on W: {len(table)} variant-entries, {failed} with a failing run", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, wrunlib.freeze_guard.FreezeRefused) as e:
        print(f"whardcase_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
