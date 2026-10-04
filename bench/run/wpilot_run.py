#!/usr/bin/env python3
"""The A/A pilot on W (hypotheses.md 4.6 step 1, 8 step 4): pilot_run.py's pilot on W's 12 cost
cells (6.1, c = 9 to 12, 21 to 24 and 33 to 36), on the frozen binary, in dedicated mode only, then
the timer part and the split part on IOCP. It writes the rows analysis/pilot.py reads, in the same
files and form as L's (windows.jsonl, parts.jsonl).

    wpilot_run.py --build DIR --out DIR --job NAME [--parts sessions,timer,split]
                  (--seeds SEEDS.json --code-freeze SHA --gate gate-W.json | --development --dev-seed N)

Run it inside a W lab job (bench/run/wjob.py run ... -- python wpilot_run.py ...). What it runs:
- sessions: wwindow.run_window (waa.py's window, which starts the server in dedicated mode only and
  refuses any other mode), arm A on aa.PORT_A, arm B PORT_OFFSET above it, X Y Y X, the order
  shuffled with SEED_PILOT_W, the C1 and C2 cells and their reruns before the C3 cells, each C3
  cell at lambda by analysis/pilot.py's own rates() over the C1 sessions (the M7c entry, item 2).
  W's churn h2c and churn MQTT run here, as every cost cell does (4.6 step 1): they are outside the
  confirmatory family (the revision log's entry "W before the code freeze", item 1), their C1
  sessions give WL2's lambda for the C3 cells of h2c and MQTT on W, and each row keeps the window's
  CPU shares, the evidence that they are generator-bound (the M7e entry). The job's warm-up phase
  (bench/run/sessions.py) runs before the first session;
- timer: on IOCP, 128 runs, one connection at a time, of HC12's script against the dedicated
  HTTP/1.1 port with PROXY on, T_hdr = 3 s, one server with --record on CPU 10, opcase on CPUs 2 to
  9; lateness = wait_return - deadline of the run's T_hdr event (the M7c entry, item 3);
- split: on IOCP, HC2's HTTP/1.1 script split after its first byte, 16 replicates at each gap of 5,
  10, 20, 50 and 100 ms, one fresh server per replicate; recv_data = recv_calls - recv_eof -
  recv_again (the M7c entry, item 4).
The parts are pilot_run.py's timer_part and split_part, with W's process functions (PartProcs).
A frozen run needs the freeze guard up to CODE_FREEZE with W's gate, the seeds entry, the entries
W's runners apply, the W job's context and W's ports outside its excluded ranges.
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

import aa  # noqa: E402
import pilot_run  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402
import wcellwin  # noqa: E402
import wrunlib  # noqa: E402
import wsys  # noqa: E402
import wwindow  # noqa: E402

BACKENDS_W = ("IOCP",)
PORTS = {"A": aa.PORT_A, "B": aa.PORT_A + aa.PORT_OFFSET}
USED_PORTS = [(aa.PORT_A, aa.PORT_A + 5), (aa.PORT_A + aa.PORT_OFFSET, aa.PORT_A + aa.PORT_OFFSET + 5),
              (pilot_run.PART_PORT, pilot_run.PART_PORT + 5)]
RUNNER = "wpilot_run"


# ---------------------------------------------------------------- the parts' processes on W


def start_part_server(build: Path, backend: str, proxy: bool, raw: Path, tag: str, record: Path | None):
    cmd = [str(build / wcellwin.ONEPORT), "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc", "--backend", backend,
           "--port", str(pilot_run.PART_PORT), "--t-hdr-ms", str(pilot_run.T_HDR_MS)]
    if proxy:
        cmd += ["--proxy", "on"]
    if record is not None:
        cmd += ["--record", str(record)]
    window.guard_mode(cmd)
    proc = wcellwin.start_err(raw / f"{tag}.server.err", cmd, wwindow.SERVER_CPUS, stdout=subprocess.PIPE, cwd=raw)
    out = wwindow.ThreadLines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        wwindow.stop_server(proc, out)
        raise window.WindowError(f"the server did not start: {out.lines[-3:]}")
    ports = {}
    for ln in out.lines:
        if ln.startswith("oneport: listening "):
            name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
            ports[name] = int(addr.rsplit(":", 1)[1])
    return proc, out, ports, cmd


def opcase_run(build: Path, port: int, hc: int, variant: str, extra: list[str], proxy_port: int | None = None) -> tuple[int, dict | None, str]:
    cmd = [str(build / wcellwin.OPCASE), "case", "--port", str(port), "--hc", str(hc), "--id", variant, "--replicates", "1",
           "--wait-ms", str(pilot_run.PART_WAIT_MS)] + extra
    if proxy_port is not None:
        cmd += ["--proxy-port", str(proxy_port)]
    p = wsys.start_pinned(cmd, wwindow.GEN_CPUS, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        so, se = p.communicate(timeout=pilot_run.PART_WAIT_MS / 1000 + 30)
    except subprocess.TimeoutExpired:
        p.kill()  # a process this runner started
        so, se = p.communicate()
    text = so.decode(errors="replace")
    line = next((json.loads(ln) for ln in text.splitlines() if ln.startswith("{")), None)
    return p.returncode, line, se.decode(errors="replace").strip()[-300:]


def stop_part_server(proc, out) -> tuple[int | None, list[str]]:
    code, lines, _how = wwindow.stop_server(proc, out)
    return code, lines


def priority(pid: int) -> dict:
    """W records no nice or timer slack (L's M7c fields); the timer resolution is in each session's
    fingerprint and each window's row."""
    return {"pid": pid, "nice": None, "timerslack_ns": None, "timer_resolution": wsys.timer_resolution() if sys.platform == "win32" else None}


W_PARTS = pilot_run.PartProcs(start_part_server, opcase_run, stop_part_server, priority)


def run_parts(a: argparse.Namespace, prov: dict, clearance) -> None:
    out = a.out
    raw = out / "raw-parts"
    raw.mkdir(parents=True, exist_ok=True)
    parts_path = out / "parts.jsonl"
    prior = SS.read_rows(parts_path)
    pprov = wrunlib.arm_provenance(prov, a.build, ("oneport", "opcase"))
    if clearance is not None:
        pprov["freeze"] = clearance.record

    def emit(row: dict, meta: bool = False) -> None:
        if meta:
            with open(raw / f"meta-{a.job}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            return
        row.update(job=a.job, development=a.development, provenance=pprov, runner=RUNNER, host="W")
        with open(parts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{row['part']} {row['backend']} {row.get('run', row.get('gap_ms'))}/{row.get('replicate', '')}: valid={row['valid']} "
              f"{row.get('lateness_ns', row.get('recv_data', ''))} {'; '.join(row['invalid_reasons'])}", flush=True)

    if "timer" in a.parts:
        done = {(r["backend"], r["run"]) for r in prior if r.get("part") == "timer"}
        for b in BACKENDS_W:
            pilot_run.timer_part(a.build, b, a.timer_runs, done, raw, emit, a.job, procs=W_PARTS)
    if "split" in a.parts:
        done = {(r["backend"], r["gap_ms"], r["replicate"]) for r in prior if r.get("part") == "split"}
        for b in BACKENDS_W:
            pilot_run.split_part(a.build, b, tuple(a.split_gaps), a.split_replicates, done, raw, emit, a.job, procs=W_PARTS)


def main(argv=None) -> int:
    wrunlib.install_stop()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    wrunlib.common_args(ap, needs_pilot=False)
    ap.add_argument("--parts", default="sessions,timer,split", help="which parts to run, in this order")
    ap.add_argument("--timer-runs", type=int, default=pilot_run.TIMER_RUNS)
    ap.add_argument("--split-replicates", type=int, default=pilot_run.SPLIT_REPLICATES)
    ap.add_argument("--split-gaps", type=lambda s: [int(x) for x in s.split(",")], default=list(pilot_run.GAPS_MS))
    a = ap.parse_args(argv)
    a.parts = a.parts.split(",")
    runlib.check_mode_args(a)
    if not a.development and (a.timer_runs != pilot_run.TIMER_RUNS or a.split_replicates != pilot_run.SPLIT_REPLICATES
                              or tuple(a.split_gaps) != pilot_run.GAPS_MS):
        raise runlib.InputRefused("--timer-runs, --split-replicates and --split-gaps change frozen values: development only")
    job_ctx = wrunlib.check_job_context(a.development)
    ports = wrunlib.check_ports(USED_PORTS)
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_PILOT_W")
    prov = wrunlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = wrunlib.freeze_check(a, prov, ("oneport", "opgen", "opcase"), need_pilot=False)
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(dict(prov, job_context=job_ctx, ports=ports), indent=1))
    if "sessions" in a.parts:
        cells = runlib.only_cells(a, pilot_run.pilot_cells(a.dev_r, host="W"))
        blocks = window.SourceBlocks(a.blocks)

        def win(cell: SS.Cell, arm: str, session: dict, position: int, _clearance) -> dict:
            p = cell.run_params(arm)
            if p.get("workload") == "open" and p.get("rate") is None:
                raise window.WindowError(f"{cell.id}: no lambda (no valid C1 pilot session of its protocol and backend)")
            cfg = dict(p, build=a.build, k_src=a.k_src, ports=PORTS, cell=cell.id)
            return wwindow.run_window(cfg, wrunlib.w_session(session), arm, position, blocks, a.out / "raw")

        def before_group(gi: int, eng: SS.Engine) -> None:
            if gi == 1:
                rates = pilot_run.c3_rates(eng.rows(), runner=RUNNER)
                for c in eng.cells:
                    if c.group == 1:
                        c.shared["rate"] = rates.get(c.id)
                (a.out / f"rates-{a.job}.json").write_text(json.dumps(rates, indent=1))

        eng = SS.Engine(RUNNER, a.job, a.out, cells, SS.make_plan(cells, seed), win,
                        lambda c, arm: wrunlib.arm_provenance(prov, a.build, ("oneport", "opgen")), a.development, clearance,
                        fingerprint=wrunlib.fingerprint, before_group=before_group, stop_after_sessions=a.max_sessions)
        summ = eng.run()
        print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    if "timer" in a.parts or "split" in a.parts:
        run_parts(a, prov, clearance)
    print(f"done {time.strftime('%Y-%m-%dT%H:%M:%S%z')}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, wrunlib.freeze_guard.FreezeRefused) as e:
        print(f"wpilot_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
