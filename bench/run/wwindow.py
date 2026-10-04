#!/usr/bin/env python3
"""One timed window of a cost cell on W (IOCP), as hypotheses.md section 4.1 lays it out, the W side
of window.py (design/w-procedure.md; design/status-m6b.md).

A window starts fresh processes (the server on its CPU), checks one exchange of the cell's protocol
(the probe, `opgen --probe`), then runs `opgen` for a 1 s warm-up and a 5 s measured window. At
opgen's MEASURE_START and MEASURE_END markers the runner reads the server's CPU time (user plus
kernel, WL4) and working set, and collects one PDH query over every CPU (busy share, the frequency
counter of section 4, interrupts and DPCs), so each is the window's mean. A sampler on CPU 0 reads
the frequency counter of the server's CPU and the generator's CPUs at 1 s through the window
(section 4). The server is stopped through its event Local\\oneport-stop-<pid>, after opgen exits,
and its counters (I29) are read from what it prints. One JSON row per window, with full provenance
and the validity rules W can compute.

M3's rule holds on W too: no window times one-port mode against dedicated mode before the pilot
entry (section 8, step 2); this runner starts the server only in dedicated mode (window.guard_mode).

Placement on W (section 4.1; w-procedure section 6): the server on logical CPU 10 (core 5), its
sibling 11 idle; opgen on CPUs 2 to 9 (cores 1 to 4); CPUs 0 and 1 for the system, this runner and
its samplers. Each process is started suspended and given its CPUs before it runs.
"""
from __future__ import annotations

import json
import os
import queue
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import window  # noqa: E402  (shared: SourceBlocks, parse_counters, guard_mode, the frozen values)
import wpower  # noqa: E402
import wsys  # noqa: E402

# Section 4.1 and WL1 (frozen).
WARMUP_MS = window.WARMUP_MS
DURATION_MS = window.DURATION_MS
CONNS_PER_CORE = window.CONNS_PER_CORE
# Section 4.1 on W (w-procedure section 6).
SERVER_CPUS = list(wsys.SERVER_CPUS)
SERVER_IDLE_SIBLINGS = list(wsys.SERVER_SIBLINGS)
GEN_CPUS = list(wsys.GEN_CPUS)
HOUSEKEEPING = list(wsys.HOUSEKEEPING)
# Design choices of M6b, as M3's on L (window.OPEN_GEN_THREADS): in an open-loop window one opgen
# worker per physical core of the generator's CPUs, on the first sibling of each; closed-loop
# windows a worker on each of the eight.
OPEN_GEN_THREADS = [2, 4, 6, 8]
# Design choice of M6b: an open-loop worker polls the last 1.5 ms before each due time. On W a
# high-resolution waitable timer woke 0.3 to 0.5 ms late at the median, at most about 1.3 ms
# (design/status-m6b.md), against Linux's timer slack of 1 ns behind M3's 200 us.
OPEN_SPIN_US = 1500
# Section 7 (frozen; the rules of lab/t1/t1.py, applied on W as design/status-m6b.md reads section
# 7's "on W, the rules of W's procedure that can be computed there").
MAX_ERROR_SHARE = window.MAX_ERROR_SHARE
MAX_GEN_BUSY_PCT = window.MAX_GEN_BUSY_PCT
MIN_COMPLETED_SHARE = window.MIN_COMPLETED_SHARE
FREQ_DRIFT = 0.02
# The frequency rule of w-procedure section 4 is applied only if its counter passed the test against
# a known load; on 2026-10-03 it did not (design/status-m6b.md), so W windows are validated without
# it and the paper says so (hypotheses.md section 9.1). The counter is recorded in every row.
FREQ_RULE = os.environ.get("ONEPORT_W_FREQ_RULE", "off") == "on"
TIMEOUT_MS = window.TIMEOUT_MS
# Design choices of M6b: before a window the runner waits until the host holds at most TW_START_MAX
# TIME-WAIT entries, at most TW_WAIT_MAX_S (TcpTimedWaitDelay is 30 s on W), so each window starts
# from an empty TIME-WAIT table, as each window on L starts from an empty connection-tracking table.
TW_START_MAX = 1000
TW_WAIT_MAX_S = 40.0
PROTOS = ("http1", "h2c", "tls", "mqtt", "ssh", "tls-stub")
LISTENER = window.LISTENER
WORKLOADS = window.WORKLOADS
STATE_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "lab" / "p3"


class WindowError(RuntimeError):
    pass


# ---------------------------------------------------------------- processes


class ThreadLines:
    """A process's standard output, read line by line by a thread (select() takes no pipes on
    Windows); `until` sees each line as it arrives. The C runtime's CR is stripped."""

    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self.q: queue.Queue = queue.Queue()
        self.lines: list[str] = []
        self.eof = False
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self) -> None:
        for raw in iter(self.proc.stdout.readline, b""):
            self.q.put(raw.decode(errors="replace").rstrip("\r\n"))
        self.q.put(None)

    def until(self, pred, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0 or self.eof:
                return False
            try:
                ln = self.q.get(timeout=min(left, 0.2))
            except queue.Empty:
                continue
            if ln is None:
                self.eof = True
                return False
            self.lines.append(ln)
            if pred(ln):
                return True

    def rest(self, timeout: float) -> list[str]:
        self.until(lambda _: False, timeout)
        return self.lines


def server_cmd(build: Path, port: int) -> list[str]:
    cmd = [str(build / "bench" / "server" / "oneport.exe"), "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc",
           "--backend", "IOCP", "--port", str(port)]
    window.guard_mode(cmd)
    return cmd


def start_server(build: Path, port: int, log_dir: Path, tag: str) -> tuple[subprocess.Popen, ThreadLines, dict[str, int]]:
    proc = wsys.start_pinned(server_cmd(build, port), SERVER_CPUS, stdout=subprocess.PIPE, stderr=open(log_dir / f"{tag}.server.err", "wb"),
                             cwd=log_dir)
    out = ThreadLines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        stop_server(proc, out)
        raise WindowError(f"the server did not start: {out.lines[-3:]}")
    ports = {}
    for ln in out.lines:
        if ln.startswith("oneport: listening "):
            name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
            ports[name] = int(addr.rsplit(":", 1)[1])
    return proc, out, ports


def stop_server(proc: subprocess.Popen, out: ThreadLines, grace: float = 15.0) -> tuple[int | None, list[str], str]:
    """Sets the server's stop event (only a server this runner started), then reads its output to
    EOF and its exit status. If the event cannot be opened or the server does not end within the
    grace, it is ended with TerminateProcess, which is recorded."""
    how = "event"
    if proc.poll() is None and not wsys.set_stop_event(proc.pid):
        how = "event not opened"
    lines = out.rest(grace)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        how += "; terminated"
        proc.kill()
        proc.wait()
    return proc.returncode, lines, how


def opgen_cmd(build: Path, proto: str, port: int, base: int, k: int) -> list[str]:
    return [str(build / "bench" / "gen" / "opgen.exe"), "--port", str(port), "--proto", proto, "--src-base", window.dotted(base),
            "--k-src", str(k), "--timeout-ms", str(TIMEOUT_MS)]


def probe(build: Path, proto: str, port: int, base: int, k: int) -> dict:
    p = wsys.start_pinned(opgen_cmd(build, proto, port, base, k) + ["--probe"], GEN_CPUS, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        so, se = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        so, se = p.communicate()
    try:
        rep = json.loads(so.decode().strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        rep = {}
    return {"exit": p.returncode, "detail": rep.get("probe_detail", se.decode(errors="replace").strip()[-200:]),
            "connect_failures": rep.get("connect_failures", -1)}


def gen_threads(cfg: dict) -> list[int]:
    return cfg.get("gen_threads") or (OPEN_GEN_THREADS if cfg.get("workload") == "open" else GEN_CPUS)


def wait_time_wait(limit: int = TW_START_MAX, max_wait: float = TW_WAIT_MAX_S) -> tuple[float, int]:
    t0 = time.monotonic()
    while True:
        n = wsys.time_wait_count()
        if n <= limit or time.monotonic() - t0 >= max_wait:
            return time.monotonic() - t0, n
        time.sleep(1.0)


def server_snapshot(h) -> dict:
    snap = {"t": time.monotonic(), "cpu_s": wsys.process_cpu_s(h), "cycles": wsys.process_cycles(h)}
    snap.update(wsys.process_memory(h))
    return snap


# ---------------------------------------------------------------- one window


def run_window(cfg: dict, session: dict, arm: str, position: int, blocks: window.SourceBlocks, raw: Path) -> dict:
    """A driver fault becomes an invalid row (t1.py's rule), never a lost window."""
    try:
        return _run_window(cfg, session, arm, position, blocks, raw)
    except Exception as e:  # noqa: BLE001 - recorded in the row, never swallowed
        return {"job": session["job"], "session": session["id"], "cell": cfg["cell"], "arm": arm, "position": position, "host": "W",
                "development": True, "functional_check": bool(cfg.get("functional")), "valid": False,
                "invalid_reasons": [f"driver error: {e!r}"]}


def _run_window(cfg: dict, session: dict, arm: str, position: int, blocks: window.SourceBlocks, raw: Path) -> dict:
    build: Path = cfg["build"]
    workload, proto = cfg["workload"], cfg["proto"]
    port = cfg["ports"][arm]
    functional = bool(cfg.get("functional"))
    warmup_ms = cfg.get("warmup_ms", WARMUP_MS) if functional else WARMUP_MS
    duration_ms = cfg.get("duration_ms", DURATION_MS) if functional else DURATION_MS
    tag = f"{session['id']}-{cfg['cell']}-p{position}-{arm}"
    raw.mkdir(parents=True, exist_ok=True)
    spin = cfg.get("spin_us", OPEN_SPIN_US if workload == "open" else None)
    row: dict = {
        "job": session["job"], "session": session["id"], "cell": cfg["cell"], "workload": workload, "proto": proto, "backend": "IOCP",
        "host": "W", "arm": arm, "position": position, "development": True, "functional_check": functional, "mode": "dedicated",
        "port": port, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "warmup_ms": warmup_ms, "duration_ms": duration_ms,
        "conns": CONNS_PER_CORE, "rate": cfg.get("rate"), "k_src": cfg["k_src"], "server_cpus": SERVER_CPUS,
        "generator_thread_cpus": gen_threads(cfg), "spin_us": spin, "server_idle_siblings": SERVER_IDLE_SIBLINGS,
        "generator_cpus": GEN_CPUS, "housekeeping_cpus": HOUSEKEEPING, "tag": tag, "freq_rule_applied": FREQ_RULE,
    }
    base = blocks.take(cfg["k_src"])
    row["src_block"] = {"base": window.dotted(base), "k": cfg["k_src"]}
    reasons: list[str] = []
    t_start = time.monotonic()
    row["time_wait_before_wait"] = wsys.time_wait_count()
    row["time_wait_wait_s"], _ = wait_time_wait(cfg.get("tw_start_max", TW_START_MAX))
    row["time_wait_start"] = wsys.time_wait_count()
    row["timer_resolution_start"] = wsys.timer_resolution()
    row["power_plan_start"] = wpower.active()
    tcp0 = wsys.tcp_stats()
    srv, srv_out, ports = start_server(build, port, raw, tag)
    sampler = wsys.Sampler(SERVER_CPUS + GEN_CPUS, 1.0)  # through the probe and the window (section 4)
    sampler.start()
    row["server_pid"] = srv.pid
    row["server_affinity"] = hex(wsys.affinity(srv.pid))
    row["conn_state_bytes"] = next((int(ln.split()[-2]) for ln in srv_out.lines if ln.startswith("oneport: connection state")), None)
    target = ports.get(LISTENER[proto])
    gen_report = None
    snaps: dict = {}
    markers = None
    h = None
    try:
        if target is None:
            raise WindowError(f"no {LISTENER[proto]} listener in {sorted(ports)}")
        row["target_port"] = target
        h = wsys.open_process(srv.pid)
        row["probe"] = probe(build, proto, target, base, cfg["k_src"])
        if row["probe"]["exit"] != 0:
            reasons.append(f"probe failed: {row['probe']['detail']}")
        out_json = raw / f"{tag}.opgen.json"
        cmd = opgen_cmd(build, proto, target, base, cfg["k_src"]) + [
            "--cpus", ",".join(map(str, gen_threads(cfg))), "--conns", str(CONNS_PER_CORE), "--warmup-ms", str(warmup_ms),
            "--duration-ms", str(duration_ms), "--out", str(out_json)]
        if workload == "keepalive":
            cmd += ["--load", "keepalive"]
        if workload == "open":
            cmd += ["--rate", repr(float(cfg["rate"]))]
        if spin is not None:
            cmd += ["--spin-us", str(spin)]
        row["opgen_cmd"] = cmd
        markers = wsys.MarkerReadings(range(12))
        gen = wsys.start_pinned(cmd, GEN_CPUS, stdout=subprocess.PIPE, stderr=open(raw / f"{tag}.opgen.err", "wb"))
        row["opgen_affinity"] = hex(wsys.affinity(gen.pid))
        gen_out = ThreadLines(gen)

        def marker(line: str) -> bool:
            if line.startswith("MEASURE_START"):
                snaps["s0"] = server_snapshot(h)
                snaps["m0"] = markers.start()
            elif line.startswith("MEASURE_END"):
                snaps["s1"] = server_snapshot(h)
                snaps["cpus"] = markers.end()
                return True
            return False

        gen_out.until(marker, (warmup_ms + duration_ms) / 1000 + 30)
        gen_out.rest(30)
        try:
            gen.wait(timeout=30)
        except subprocess.TimeoutExpired:
            gen.kill()  # a process this runner started
            gen.wait()
        row["opgen_exit"] = gen.returncode
        if out_json.exists():
            gen_report = json.loads(out_json.read_text())
        else:
            err = (raw / f"{tag}.opgen.err").read_text(errors="replace")[-300:]
            reasons.append(f"opgen wrote no report (exit {gen.returncode}): {err}")
    finally:
        exit_code, rest, how = stop_server(srv, srv_out)
        if h is not None:
            wsys.close_handle(h)
        if markers is not None and "cpus" not in snaps:
            markers.pdh.close()
        blocks.release(base)
        row["frequency_samples"] = sampler.stop()
        row["frequency_sampler_error"] = sampler.error
    row["server_exit"] = exit_code
    row["server_stopped_by"] = how
    row["server_counters"] = window.parse_counters(rest)
    row["time_wait_end"] = wsys.time_wait_count()
    row["timer_resolution_end"] = wsys.timer_resolution()
    row["power_plan_end"] = wpower.active()
    tcp1 = wsys.tcp_stats()
    row["tcp_stats_delta"] = {k: tcp1[k] - tcp0[k] for k in tcp0 if k in tcp1 and k != "CurrEstab"}
    row["window_overhead_s"] = time.monotonic() - t_start
    finish(row, gen_report, snaps, session, reasons)
    return row


def cpu_mean(cpus_reading: dict, cpus, counter: str) -> float | None:
    vals = [(cpus_reading.get(str(c)) or {}).get(counter) for c in cpus]
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def finish(row: dict, g: dict | None, snaps: dict, session: dict, reasons: list[str]) -> dict:
    """The row's metrics and the validity rules on W: section 7's general rules, t1.py's error and
    generator rules as W computes them, W's procedure (the lab plan active and the core layout as
    read), and the frequency rule only where FREQ_RULE is on."""
    if row.get("server_exit") not in (0,):
        reasons.append(f"server exit {row.get('server_exit')}")
    if g is None or not g.get("ok"):
        reasons.append(f"opgen failed: {(g or {}).get('error', 'no report')}")
        row.update(valid=False, invalid_reasons=reasons)
        return row
    keep = ("measure", "warmup", "wall_s", "error_share", "connect_failures", "connects_run", "all_completed", "due", "due_completed",
            "due_errors", "due_unfinished", "completed_share", "ttfb_ns", "ttfb_connect_ns", "exchange_ns", "issue_lag_ns", "cpu",
            "peak_concurrency_per_worker", "measure_start_ns", "measure_end_ns", "threads")
    row["opgen"] = {k: g[k] for k in keep if k in g}
    wall = g["wall_s"]
    completed = g["measure"]["completed"]
    workload = row["workload"]
    if workload == "churn":
        row["metric"] = {"name": "conn_per_s", "value": completed / wall if wall > 0 else 0.0}
    elif workload == "keepalive":
        row["metric"] = {"name": "req_per_s", "value": completed / wall if wall > 0 else 0.0}
    else:
        row["metric"] = {"name": "ttfb_median_us", "value": g["ttfb_ns"]["median"] / 1000.0}
    exchanges = g["due_completed"] if workload == "open" else completed
    if "s0" in snaps and "s1" in snaps and "cpus" in snaps:
        s0, s1, cpus = snaps["s0"], snaps["s1"], snaps["cpus"]["cpus"]
        row["server_cpu_s"] = s1["cpu_s"] - s0["cpu_s"]  # WL4: user + kernel time of the server process
        row["cpu_us_per_exchange"] = 1e6 * row["server_cpu_s"] / exchanges if exchanges else None
        if "cycles" in s0 and "cycles" in s1:
            # The server's cycles (wsys.process_cycles), beside GetProcessTimes' server_cpu_s, which
            # moves in 15.625 ms ticks and so is a sample at a low load (M6c).
            row["server_cycles"] = s1["cycles"] - s0["cycles"]
            row["cycles_per_exchange"] = row["server_cycles"] / exchanges if exchanges else None
            # W's WL4 value is the cycles (revision log, "W before the code freeze", item 4); in time,
            # through the session's cycle rate (wsys.cycle_rate). A ratio of two arms needs neither.
            rate = (session.get("cycle_rate") or {}).get("cycles_per_s")
            if rate and row["cycles_per_exchange"] is not None:
                row["cycles_us_per_exchange"] = 1e6 * row["cycles_per_exchange"] / rate
        row["rss_kb"], row["peak_rss_kb"] = s1.get("working_set_kb"), s1.get("peak_working_set_kb")
        row["marker_span_s"] = snaps["cpus"]["span_s"]
        row["cpu_readings"] = cpus
        busy = cpu_mean(cpus, SERVER_CPUS, "% Processor Time")
        row["server_cores_busy"] = busy / 100.0 if busy is not None else None
        sib = cpu_mean(cpus, SERVER_IDLE_SIBLINGS, "% Processor Time")
        row["server_sibling_busy"] = sib / 100.0 if sib is not None else None
        row["gen_cpus_busy_pct"] = cpu_mean(cpus, GEN_CPUS, "% Processor Time")
        hk = cpu_mean(cpus, HOUSEKEEPING, "% Processor Time")
        row["housekeeping_busy"] = hk / 100.0 if hk is not None else None
        span = snaps["cpus"]["span_s"] or 0.0
        row["irq_server"] = (cpu_mean(cpus, SERVER_CPUS, "Interrupts/sec") or 0.0) * span * len(SERVER_CPUS)
        row["irq_server_sibling"] = (cpu_mean(cpus, SERVER_IDLE_SIBLINGS, "Interrupts/sec") or 0.0) * span
        row["irq_generator"] = (cpu_mean(cpus, GEN_CPUS, "Interrupts/sec") or 0.0) * span * len(GEN_CPUS)
        row["freq_window"] = cpu_mean(cpus, SERVER_CPUS, "% Processor Performance")
        row["actual_frequency_mhz_window"] = cpu_mean(cpus, SERVER_CPUS, "Actual Frequency")
    else:
        reasons.append("no window markers")
    c = row.get("server_counters", {})
    acc = c.get("accepted", 0)
    if acc:
        row["per_connection"] = {k: v / acc for k, v in c.items() if isinstance(v, int)}
        if workload == "keepalive" and g.get("all_completed"):
            n = g["all_completed"] + 1  # the probe's exchange
            row["per_request"] = {k: v / n for k, v in c.items() if isinstance(v, int)}
    # The frequency counter against the session's reading (w-procedure section 4).
    sess_freq = (session.get("frequency") or {}).get("server_mean")
    if row.get("freq_window") is not None and sess_freq:
        row["freq_session"] = sess_freq
        row["freq_drift"] = abs(row["freq_window"] - sess_freq) / sess_freq
        if FREQ_RULE and row["freq_drift"] > FREQ_DRIFT:
            reasons.append(f"frequency counter drift {100 * row['freq_drift']:.2f}% > 2%")
    # W's procedure: the lab plan active at the window's start and end (section 2).
    lab = session.get("lab_plan")
    for k in ("power_plan_start", "power_plan_end"):
        if lab and (row.get(k) or {}).get("guid") != lab:
            reasons.append(f"{k.replace('_', ' ')} is {row.get(k)}, not the lab plan")
    if completed == 0:
        reasons.append("no exchange completed")
    if g["error_share"] > MAX_ERROR_SHARE and completed > 0:
        reasons.append(f"errors {100 * g['error_share']:.3f}% > 0.1%")
    failures = g["connect_failures"] + max(0, row.get("probe", {}).get("connect_failures", 0))
    if failures > 0:
        reasons.append(f"{failures} connects failed")
    row["gen_cpu_pct_rule"] = max(g["cpu"]["pct"], row.get("gen_cpus_busy_pct") or 0.0)
    if workload != "open" and row["gen_cpu_pct_rule"] > MAX_GEN_BUSY_PCT:
        reasons.append(f"generator CPU {row['gen_cpu_pct_rule']:.1f}% > 90% in a saturation cell")
    if workload == "open" and g["completed_share"] < MIN_COMPLETED_SHARE:
        reasons.append(f"open loop: {100 * g['completed_share']:.2f}% of the exchanges due completed, below 99%")
    row["valid"] = not reasons
    row["invalid_reasons"] = reasons
    return row


# ---------------------------------------------------------------- the session's readings


def session_frequency(seconds: int = 3) -> dict:
    """The session's reading of the frequency counter (w-procedure section 4), taken with the host
    idle at the session's start, as pin.sh's mean MHz on L: % Processor Performance of the
    server's CPU and the mean over the generator's CPUs, `seconds` samples at 1 s."""
    s = wsys.Sampler(SERVER_CPUS + GEN_CPUS, 1.0)
    s.start()
    deadline = time.monotonic() + seconds + 3
    while len(s.samples) < seconds and time.monotonic() < deadline:
        time.sleep(0.1)
    samples = s.stop()[:seconds]
    srv = [x["cpus"][str(SERVER_CPUS[0])]["% Processor Performance"] for x in samples]
    srv = [v for v in srv if v is not None]
    gen = [statistics.fmean(v for v in (x["cpus"][str(c)]["% Processor Performance"] for c in GEN_CPUS) if v is not None) for x in samples]
    return {"server_mean": statistics.fmean(srv) if srv else None, "generator_mean": statistics.fmean(gen) if gen else None,
            "samples": samples, "error": s.error}


def fingerprint() -> dict:
    """Section 7's per-session record on W: the power plan read back (the active plan and section 2's
    values), the timer resolution, Defender's and Windows Update's state, the core layout check,
    the frequency counter's session reading, and the cycle counter's rate on the server's CPU."""
    lab = wpower.lab_plan_guid()
    fp = {"host": os.environ.get("COMPUTERNAME", "W"), "lab_plan": lab, "functional_job": os.environ.get("ONEPORT_W_FUNCTIONAL") == "1",
          "job": os.environ.get("ONEPORT_W_JOB")}
    if lab:
        rb = wpower.readback(lab)
        problems = wpower.check_values(rb["settings"])
        if rb["active"]["guid"] != lab:
            problems.append("the lab plan is not active")
    else:
        rb = {"active": wpower.active(), "settings": None}
        problems = ["no lab plan"]
    fp["power"] = {"active": rb["active"], "settings": rb["settings"], "problems": problems}
    fp["timer_resolution"] = wsys.timer_resolution()
    fp["state"] = wsys.defender_and_update()
    cores = wsys.core_layout()
    fp["core_problems"] = wsys.check_core_layout(cores)
    fp["frequency"] = session_frequency()
    try:
        fp["cycle_rate"] = wsys.cycle_rate(SERVER_CPUS)
    except (OSError, subprocess.SubprocessError) as e:
        fp["cycle_rate"] = {"error": repr(e)}
    fp["pinned"] = not fp["power"]["problems"] and not fp["core_problems"]
    return fp
