#!/usr/bin/env python3
"""The A/A pilot on L (hypotheses.md 4.6 step 1, 8 step 4): on the frozen binary, in dedicated mode
only, every cost cell of L runs P = 16 sessions of two starts of the same binary and flags, the
second on a fixed port offset; then the timer part and the split part. It writes the rows that
analysis/pilot.py reads (windows.jsonl for the sessions, parts.jsonl for the parts).

    pilot_run.py --build DIR --out DIR --job NAME [--parts sessions,timer,split]
                 (--seeds SEEDS.json --code-freeze SHA --gate gate-L.json | --development --dev-seed N)

What it runs:
- sessions: aa.py's windows (window.run_window, which starts the server in dedicated mode only and
  refuses any other mode), arm A on aa.PORT_A, arm B PORT_OFFSET above it, both with replay (the
  proposed default: rule E's detection mode is chosen after the pilot entry and does not act in
  dedicated mode). The order is shuffled with SEED_PILOT_L, the C1 and C2 cells before the C3
  cells (8 step 4). Reruns: a session with an invalid window runs again at the end of its part
  of the order, at most ceil(P/4) = 4 times per cell; the C1 and C2 cells' reruns end before the
  first C3 session, because WL2's lambda for a C3 cell is RATE_FRAC x the median over the C1
  pilot sessions (a reading, design/status.md M7c), computed by analysis/pilot.py's own rates() on
  the rows, so the rate the pilot's C3 windows run at is the one the pilot entry records;
- timer: per backend, 128 runs, one connection at a time, of HC12's script against the dedicated
  HTTP/1.1 port with the PROXY setting on, T_hdr = 3 s; one server per backend with --record, on
  CPU 14, opcase on CPUs 2 to 9 (section 4.1's hard-case placement); each run's lateness is
  wait_return - deadline of its T_hdr event, from the deadline to the start of the loop pass that
  handled it (section 8 step 4), and the record's B2(a, b) checks are kept beside it;
- split: per backend, HC2's HTTP/1.1 script split after its first byte (HC02.HTTP.k01) against the
  dedicated HTTP/1.1 port, 16 replicates at each gap of 5, 10, 20, 50 and 100 ms, one fresh server
  per replicate so that its counters are its one connection's; recv_data = receives that returned
  payload (recv_calls - recv_eof - recv_again, counterdelta.py's count).
A timer run or split replicate whose server or opcase failed is excluded (valid false, its reason),
never run again on its own (8 step 4). The pilot refuses one-port mode: no flag of this runner
starts it, and window.run_window refuses it.

A frozen run needs the freeze guard (bench/run/freeze_guard.py) up to CODE_FREEZE and the seeds
entry; the pilot entry comes after it.
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
import cellwin  # noqa: E402
import freeze_guard  # noqa: E402
import runlib  # noqa: E402
import sessions as SS  # noqa: E402
import window  # noqa: E402

sys.path.insert(0, str(runlib.REPO / "analysis"))
import cells as C  # noqa: E402
import pilot as PL  # noqa: E402
import rows as RW  # noqa: E402

P = PL.P  # 16
TIMER_RUNS = 128           # 8 step 4: the server's runs per timer case on L
SPLIT_REPLICATES = 16      # 8 step 4: the hard cases' replicate count
GAPS_MS = PL.GAPS_MS       # 5, 10, 20, 50, 100
T_HDR_MS = 3000            # section 1
SYSTEM_CPUS = (14,)        # section 4.1: hard cases, the system on CPU 14
OPCASE_CPUS = tuple(range(2, 10))
PART_PORT = 24000          # a design choice of M7c, off the ephemeral range and apart from the other runners' ports
SPLIT_VARIANT = "HC02.HTTP.k01"
PART_WAIT_MS = 10_000      # opcase's limit on any wait of one run: T_hdr and a margin
RECORD_WAIT_S = 5.0


def pilot_cells(r: int | None = None) -> list[SS.Cell]:
    cells = []
    for c in C.cost_cells():
        if c.host != "L":
            continue
        wl = C.HYP_WORKLOAD[c.hyp]
        fields = {"workload": wl, "proto": c.proto, "backend": c.backend, "mode": "dedicated"}
        cells.append(SS.Cell(c.id, r or P, {"A": dict(fields), "B": dict(fields)}, group=1 if c.hyp == "C3" else 0,
                             shared={"workload": wl, "proto": c.proto, "backend": c.backend}))
    return cells


# ---------------------------------------------------------------- the parts


def start_part_server(build: Path, backend: str, proxy: bool, raw: Path, tag: str, record: Path | None):
    cmd = [str(build / "bench" / "server" / "oneport"), "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc",
           "--backend", backend, "--port", str(PART_PORT), "--t-hdr-ms", str(T_HDR_MS)]
    if proxy:
        cmd += ["--proxy", "on"]
    if record is not None:
        cmd += ["--record", str(record)]
    window.guard_mode(cmd)
    proc = cellwin.popen_err(raw / f"{tag}.server.err", ["taskset", "-c", ",".join(map(str, SYSTEM_CPUS))] + cmd, stdout=subprocess.PIPE,
                             start_new_session=True, cwd=raw)
    out = window.Lines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        window.stop_process(proc, out)
        raise window.WindowError(f"the server did not start: {out.lines[-3:]}")
    ports = {}
    for ln in out.lines:
        if ln.startswith("oneport: listening "):
            name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
            ports[name] = int(addr.rsplit(":", 1)[1])
    return proc, out, ports, cmd


def opcase_run(build: Path, port: int, hc: int, variant: str, extra: list[str], proxy_port: int | None = None) -> tuple[int, dict | None, str]:
    cmd = ["taskset", "-c", ",".join(map(str, OPCASE_CPUS)), str(build / "bench" / "cases" / "opcase"), "case", "--port", str(port),
           "--hc", str(hc), "--id", variant, "--replicates", "1", "--wait-ms", str(PART_WAIT_MS)] + extra
    if proxy_port is not None:
        cmd += ["--proxy-port", str(proxy_port)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=PART_WAIT_MS / 1000 + 30)
    line = next((json.loads(ln) for ln in p.stdout.splitlines() if ln.startswith("{")), None)
    return p.returncode, line, p.stderr.strip()[-300:]


def record_lines(path: Path, offset: int) -> tuple[list[dict], int]:
    if not path.exists():
        return [], offset
    data = path.read_bytes()
    new = data[offset:]
    cut = new.rfind(b"\n") + 1
    lines = [json.loads(ln) for ln in new[:cut].decode().splitlines() if ln.strip()]
    return lines, offset + cut


def timer_part(build: Path, backend: str, runs: int, done: set, raw: Path, emit, job: str) -> None:
    tag = f"timer-{backend}-{job}"
    record = raw / f"{tag}.record.jsonl"
    srv = out = None
    ports: dict = {}
    todo = [run for run in range(1, runs + 1) if (backend, run) not in done]
    if not todo:
        return
    try:
        try:
            srv, out, ports, _ = start_part_server(build, backend, True, raw, tag, record)
        except Exception as e:  # noqa: BLE001 - every run of this server is excluded, with the reason
            for run in todo:
                emit({"part": "timer", "backend": backend, "mode": "dedicated", "run": run, "valid": False,
                      "invalid_reasons": [f"the server failed to start: {e!r}"]})
            return
        port = ports[window.LISTENER["http1"]]
        prio = window.priority_state(srv.pid)  # the server's nice and timer slack (M7c)
        offset = 0
        for run in todo:
            row = {"part": "timer", "backend": backend, "mode": "dedicated", "run": run, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "server_priority": prio}
            reasons = []
            if srv.poll() is not None:
                reasons.append(f"the server exited ({srv.returncode})")
                emit(dict(row, valid=False, invalid_reasons=reasons))
                continue
            try:
                rc, line, err = opcase_run(build, port, 12, "HC12", ["--t-hdr-ms", str(T_HDR_MS)], proxy_port=port)
            except Exception as e:  # noqa: BLE001 - recorded in the row
                emit(dict(row, valid=False, invalid_reasons=[f"opcase failed: {e!r}"]))
                continue
            row["opcase_exit"] = rc
            if line is None or not line.get("connected"):
                reasons.append(f"opcase failed (exit {rc}): {err}")
                emit(dict(row, valid=False, invalid_reasons=reasons))
                continue
            row["local_port"] = line["local_port"]
            ev = None
            t0 = time.monotonic()
            got: list[dict] = []
            while time.monotonic() - t0 < RECORD_WAIT_S:
                more, offset = record_lines(record, offset)
                got += more
                ev = next((x for x in got if x.get("event") == "detection" and x.get("peer_port") == line["local_port"]), None)
                if ev is not None:
                    break
                time.sleep(0.05)
            if ev is None or not ev.get("timed") or ev["timed"].get("kind") != "T_hdr":
                reasons.append("the server's record has no T_hdr event for the run's connection")
                emit(dict(row, valid=False, invalid_reasons=reasons, record=ev))
                continue
            t = ev["timed"]
            row.update(outcome=ev.get("outcome"), timed=t, lateness_ns=int(t["wait_return_ns"]) - int(t["deadline_ns"]),
                       b2={"a_never_early": int(t["deadline_ns"]) <= int(t["wait_return_ns"]),
                           "b_first_pass": int(t["prev_wait_return_ns"]) < int(t["deadline_ns"]),
                           "deadline_is_start_plus_t_hdr": int(t["deadline_ns"]) - int(t["start_ns"]) == T_HDR_MS * 1_000_000})
            emit(dict(row, valid=True, invalid_reasons=[]))
    finally:
        if srv is not None:
            code, _ = window.stop_process(srv, out)
            emit({"part": "timer-server", "backend": backend, "server_exit": code, "record": str(record)}, meta=True)


def split_part(build: Path, backend: str, gaps: tuple[int, ...], replicates: int, done: set, raw: Path, emit, job: str) -> None:
    for gap in gaps:
        for rep in range(1, replicates + 1):
            if (backend, gap, rep) in done:
                continue
            tag = f"split-{backend}-{gap}-{rep}-{job}"
            row = {"part": "split", "backend": backend, "mode": "dedicated", "gap_ms": gap, "replicate": rep,
                   "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            reasons = []
            srv = out = None
            line = None
            try:
                srv, out, ports, _ = start_part_server(build, backend, False, raw, tag, None)
                rc, line, err = opcase_run(build, ports[window.LISTENER["http1"]], 2, SPLIT_VARIANT, ["--gap-split-ms", str(gap)])
                row["opcase_exit"] = rc
                if line is None or not line.get("connected"):
                    reasons.append(f"opcase failed (exit {rc}): {err}")
                time.sleep(0.1)  # the server closes the connection before it stops
            except Exception as e:  # noqa: BLE001 - recorded in the row
                reasons.append(f"driver error: {e!r}")
            finally:
                code, lines = (window.stop_process(srv, out) if srv is not None else (None, []))
            row["server_exit"] = code
            c = window.parse_counters(lines)
            row["server_counters"] = {k: c.get(k) for k in ("accepted", "closed", "recv_calls", "recv_eof", "recv_again", "bytes_received")}
            if code != 0:
                reasons.append(f"server exit {code}")
            if c.get("accepted") != 1 and not reasons:
                reasons.append(f"the server accepted {c.get('accepted')} connections, not the replicate's one")
            if isinstance(c.get("recv_calls"), int):
                row["recv_data"] = c["recv_calls"] - c.get("recv_eof", 0) - c.get("recv_again", 0)
            if line is not None:
                row["write_ns"] = line.get("write_ns")
            emit(dict(row, valid=not reasons, invalid_reasons=reasons))


def run_parts(a: argparse.Namespace, prov: dict, clearance) -> None:
    out = a.out
    raw = out / "raw-parts"
    raw.mkdir(parents=True, exist_ok=True)
    parts_path = out / "parts.jsonl"
    prior = SS.read_rows(parts_path)
    pprov = runlib.arm_provenance(prov, a.build, ("oneport", "opcase"))
    if clearance is not None:
        pprov["freeze"] = clearance.record

    def emit(row: dict, meta: bool = False) -> None:
        if meta:
            (raw / f"meta-{a.job}.jsonl").open("a").write(json.dumps(row) + "\n")
            return
        row.update(job=a.job, development=a.development, provenance=pprov, runner="pilot_run")
        with open(parts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{row['part']} {row['backend']} {row.get('run', row.get('gap_ms'))}/{row.get('replicate', '')}: valid={row['valid']} "
              f"{row.get('lateness_ns', row.get('recv_data', ''))} {'; '.join(row['invalid_reasons'])}", flush=True)

    backends = runlib.COST_BACKENDS_L
    if "timer" in a.parts:
        done = {(r["backend"], r["run"]) for r in prior if r.get("part") == "timer"}
        for b in backends:
            timer_part(a.build, b, a.timer_runs, done, raw, emit, a.job)
    if "split" in a.parts:
        done = {(r["backend"], r["gap_ms"], r["replicate"]) for r in prior if r.get("part") == "split"}
        for b in backends:
            split_part(a.build, b, tuple(a.split_gaps), a.split_replicates, done, raw, emit, a.job)


# ---------------------------------------------------------------- the sessions


def c3_rates(rows: list[dict]) -> dict[str, float | None]:
    """WL2: lambda per C3 cell from the C1 pilot sessions, by analysis/pilot.py's rates()."""
    try:
        sess = RW.assemble([r for r in rows if r.get("runner") == "pilot_run"], PL.pilot_info, lambda kind, cid: PL.PILOT_ROLES)
    except (RW.RowError, RW.RowsRefused) as e:
        raise runlib.InputRefused(f"the pilot's rows do not assemble into sessions: {e}") from None
    return {cid: e.get("rate") for cid, e in PL.rates(sess).items()}


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    runlib.common_args(ap, needs_pilot=False)
    ap.add_argument("--parts", default="sessions,timer,split", help="which parts to run, in this order")
    ap.add_argument("--timer-runs", type=int, default=TIMER_RUNS)
    ap.add_argument("--split-replicates", type=int, default=SPLIT_REPLICATES)
    ap.add_argument("--split-gaps", type=lambda s: [int(x) for x in s.split(",")], default=list(GAPS_MS))
    a = ap.parse_args(argv)
    a.parts = a.parts.split(",")
    runlib.check_mode_args(a)
    if not a.development and (a.timer_runs != TIMER_RUNS or a.split_replicates != SPLIT_REPLICATES
                              or tuple(a.split_gaps) != GAPS_MS):
        raise runlib.InputRefused("--timer-runs, --split-replicates and --split-gaps change frozen values: development only")
    a.out.mkdir(parents=True, exist_ok=True)
    seed, _ = runlib.order_seed(a, "SEED_PILOT_L")
    prov = runlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, need_pilot=False,
                                       binaries=runlib.binaries_of(prov, ("oneport", "opgen", "opcase")))
    (a.out / f"provenance-{a.job}.json").write_text(json.dumps(prov, indent=1))
    if "sessions" in a.parts:
        cells = runlib.only_cells(a, pilot_cells(a.dev_r))
        blocks = window.SourceBlocks(a.blocks)
        ports = {"A": aa.PORT_A, "B": aa.PORT_A + aa.PORT_OFFSET}

        def win(cell: SS.Cell, arm: str, session: dict, position: int, _clearance) -> dict:
            p = cell.run_params(arm)
            if p.get("workload") == "open" and p.get("rate") is None:
                raise window.WindowError(f"{cell.id}: no lambda (no valid C1 pilot session of its protocol and backend)")
            cfg = dict(p, build=a.build, k_src=a.k_src, ports=ports, cell=cell.id)
            return window.run_window(cfg, session, arm, position, blocks, a.out / "raw")

        def before_group(gi: int, eng: SS.Engine) -> None:
            if gi == 1:
                rates = c3_rates(eng.rows())
                for c in eng.cells:
                    if c.group == 1:
                        c.shared["rate"] = rates.get(c.id)
                (a.out / f"rates-{a.job}.json").write_text(json.dumps(rates, indent=1))

        eng = SS.Engine("pilot_run", a.job, a.out, cells, SS.make_plan(cells, seed), win,
                        lambda c, arm: runlib.arm_provenance(prov, a.build, ("oneport", "opgen")), a.development, clearance,
                        fingerprint=window.pin_fingerprint, before_group=before_group, stop_after_sessions=a.max_sessions)
        summ = eng.run()
        print(json.dumps({c: {k: v for k, v in s.items() if k != "invalid_windows"} for c, s in summ["cells"].items()}), flush=True)
    if "timer" in a.parts or "split" in a.parts:
        run_parts(a, prov, clearance)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, freeze_guard.FreezeRefused) as e:
        print(f"pilot_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
