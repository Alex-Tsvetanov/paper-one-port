#!/usr/bin/env python3
"""The in-process window of W's frozen runners (M7e), on IOCP: the W side of cellwin.py, for the
cost family (5.1), M1 (5.3), rule E's IOCP detection sessions and section 10's W cells (SSH, the
mixed cell, TLS with ALPN h2, the IOCP forms, M1's TTFB at a fixed load), in either mode.

The layout is wwindow.py's (section 4.1 on W; design/w-procedure.md): the TIME-WAIT wait, fresh
processes each started suspended on its CPUs, the probe, then opgen for a 1 s warm-up and a 5 s
measured window, the host read at opgen's markers (PDH over every CPU, the server's CPU time and its
cycles), the server stopped through its event, its counters read; wwindow.finish applies the rules W
computes (section 7; the revision log's entry "W before the code freeze", item 6 (b)) and records
WL4 as the server's cycles per exchange with GetProcessTimes' value beside it (the same entry,
item 4), and each window's CPU shares (M7e). What this adds to wwindow.py, which starts the server
only in dedicated mode (the A/A runs and the pilot keep it):
- the server in one-port mode, in-process, with a detection mode and, for the IOCP forms, its
  AcceptEx and receive forms (--iocp-accept, --iocp-receive). A one-port window of a cell that
  pairs one-port with dedicated mode starts only with the freeze guard's clearance that names the
  pilot entry (cellwin.guard, the same rule): without one it raises before any process starts, and
  the session engine never asks for one without it (bench/run/sessions.py writes a stub row);
- opgen's protocol where it differs from the row's (TLS with ALPN h2: opgen's tls-h2);
- the mixed cell's background on W: TLS and MQTT keep-alive (opgen --load keepalive, WL3, 64
  connections each, as on L: the revision log's entry "M7c's open items, before the code freeze",
  items 1 and 8) and 64 silent connections held by opcase hold, stopped by its event
  Local\\oneport-stop-<pid>; placement, a design choice of M7e (the M7e entry): section 4.1 gives
  W's generators CPUs 2 to 9 alone, so the cell's opgen takes CPUs 2 to 5 (cores 1 and 2), the TLS
  background CPUs 6 and 7 (core 3), the MQTT background and the holder CPUs 8 and 9 (core 4), as
  L's split gives the cell's generator the larger share and each background a core of its own;
  section 7's generator rule reads the cell's generator's CPUs (gen_cpus);
- `misclassified` on every one-port row (cellwin.misclassified, the same count).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import cellwin
import window
import wpower
import wsys
import wwindow
from window import WindowError

HERE = Path(__file__).resolve().parent

# The mixed cell on W (a design choice of M7e; see the docstring).
MIXED_GEN_CPUS = (2, 3, 4, 5)
MIXED_BG_CPUS = {"tls": (6, 7), "mqtt": (8, 9), "silent": (8, 9)}
N_BG = cellwin.N_BG
OPCASE = Path("bench") / "cases" / "opcase.exe"
ONEPORT = Path("bench") / "server" / "oneport.exe"
OPGEN = Path("bench") / "gen" / "opgen.exe"


def start_err(err: Path, cmd: list[str], cpus, **kw) -> subprocess.Popen:
    """wsys.start_pinned with standard error to a file, whose handle the parent closes once the
    child has it."""
    with open(err, "wb") as f:
        return wsys.start_pinned(cmd, cpus, stderr=f, **kw)


def server_cmd(build: Path, p: dict) -> list[str]:
    cmd = [str(build / ONEPORT), "--mode", p["mode"], "--detect", p.get("detect", "replay"), "--dispatch", "inproc", "--backend", "IOCP",
           "--port", str(p["port"])]
    if p.get("iocp_accept") is not None:
        cmd += ["--iocp-accept", p["iocp_accept"]]
    if p.get("iocp_receive") is not None:
        cmd += ["--iocp-receive", p["iocp_receive"]]
    return cmd


def start_server(build: Path, p: dict, raw: Path, tag: str):
    cmd = server_cmd(build, p)
    proc = start_err(raw / f"{tag}.server.err", cmd, wwindow.SERVER_CPUS, stdout=subprocess.PIPE, cwd=raw)
    out = wwindow.ThreadLines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        wwindow.stop_server(proc, out)
        raise WindowError(f"the server did not start: {out.lines[-3:]}")
    ports = {}
    for ln in out.lines:
        if ln.startswith("oneport: listening "):
            name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
            ports[name] = int(addr.rsplit(":", 1)[1])
    return proc, out, ports, cmd


def probe(build: Path, proto: str, port: int, base: int, k: int, cpus) -> dict:
    p = wsys.start_pinned(wwindow.opgen_cmd(build, proto, port, base, k) + ["--probe"], cpus, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        so, se = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()  # a process this window started
        so, se = p.communicate()
    try:
        rep = json.loads(so.decode().strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        rep = {}
    return {"exit": p.returncode, "detail": rep.get("probe_detail", se.decode(errors="replace").strip()[-200:]),
            "connect_failures": rep.get("connect_failures", -1)}


class Background:
    """The mixed cell's background on W (see the module's docstring)."""

    def __init__(self, build: Path, ports: dict[str, int], mode: str, silent_ports: list[int], blocks: window.SourceBlocks, k_src: int,
                 raw: Path, tag: str, duration_ms: int):
        self.procs: dict[str, subprocess.Popen] = {}
        self.lines: dict[str, wwindow.ThreadLines] = {}
        self.blocks: list[int] = []
        self.raw, self.tag = raw, tag
        try:
            self._start(build, ports, mode, silent_ports, blocks, k_src, raw, tag, duration_ms)
        except BaseException:  # a stop (SystemExit) while starting it, too
            self.stop()
            self.release(blocks)
            raise
        self.commands = {k: list(map(str, p.args)) for k, p in self.procs.items()}

    def _start(self, build: Path, ports: dict[str, int], mode: str, silent_ports: list[int], blocks: window.SourceBlocks, k_src: int,
               raw: Path, tag: str, duration_ms: int) -> None:
        for kind in ("tls", "mqtt"):
            base = blocks.take(k_src)
            self.blocks.append(base)
            port = cellwin.target_port(mode, kind, ports)
            cmd = wwindow.opgen_cmd(build, kind, port, base, k_src) + [
                "--load", "keepalive", "--cpus", ",".join(map(str, MIXED_BG_CPUS[kind])), "--conns", str(N_BG[kind]),
                "--warmup-ms", str(window.WARMUP_MS), "--duration-ms", str(duration_ms), "--out", str(raw / f"{tag}.bg-{kind}.json")]
            self.procs[kind] = start_err(raw / f"{tag}.bg-{kind}.err", cmd, MIXED_BG_CPUS[kind], stdout=subprocess.PIPE)
            self.lines[kind] = wwindow.ThreadLines(self.procs[kind])
        base = blocks.take(k_src)
        self.blocks.append(base)
        cmd = [str(build / OPCASE), "hold", "--ports", ",".join(map(str, silent_ports)), "--n", str(N_BG["silent"]),
               "--src-base", window.dotted(base), "--k-src", str(k_src)]
        self.procs["silent"] = start_err(raw / f"{tag}.bg-silent.err", cmd, MIXED_BG_CPUS["silent"], stdout=subprocess.PIPE)
        self.lines["silent"] = wwindow.ThreadLines(self.procs["silent"])

    def wait_ready(self) -> dict:
        ready = {}
        for kind in ("tls", "mqtt"):
            ready[kind] = self.lines[kind].until(lambda ln: ln.startswith("MEASURE_START"), cellwin.BG_READY_S)
        ready["silent"] = self.lines["silent"].until(lambda ln: ln.startswith("HOLD "), cellwin.BG_READY_S)
        return ready

    def finish(self) -> dict:
        out: dict = {}
        for kind in ("tls", "mqtt"):
            self.lines[kind].rest(60)
            try:
                self.procs[kind].wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.procs[kind].kill()  # a process this window started
                self.procs[kind].wait()
            f = self.raw / f"{self.tag}.bg-{kind}.json"
            rep = json.loads(f.read_text()) if f.exists() else None
            out[kind] = {"exit": self.procs[kind].returncode, "ok": bool(rep and rep.get("ok")),
                         "report": {k: rep[k] for k in ("measure", "warmup", "error_share", "connect_failures", "all_completed",
                                                         "measure_start_ns", "measure_end_ns", "wall_s", "cpus", "cpu") if k in rep}
                         if rep else None}
        holder = self.procs["silent"]
        how = "event"
        if holder.poll() is None and not wsys.set_stop_event(holder.pid):
            how = "event not opened"
        lines = self.lines["silent"].rest(15)
        try:
            holder.wait(timeout=15)
        except subprocess.TimeoutExpired:
            how += "; terminated"
            holder.kill()  # a process this window started
            holder.wait()
        rep = next((json.loads(ln) for ln in reversed(lines) if ln.startswith("{")), None)
        out["silent"] = {"exit": holder.returncode, "ok": bool(rep and rep.get("ok")), "report": rep, "stopped_by": how}
        return out

    def stop(self) -> None:
        for p in self.procs.values():
            if p.poll() is None:
                p.kill()  # a process this window started
                p.wait()

    def release(self, blocks: window.SourceBlocks) -> None:
        for b in self.blocks:
            blocks.release(b)


def server_snapshot(h) -> dict:
    return wwindow.server_snapshot(h)


def run(p: dict, session: dict, arm: str, position: int, blocks: window.SourceBlocks, raw: Path, clearance=None) -> dict:
    """One window on W. `p`: build, cell, workload, proto, mode, detect, k_src, port (this arm's
    first port), and optionally rate (open loop), gen_proto, iocp_accept, iocp_receive, background
    (the mixed cell: {"silent_ports": "http1"}), pairs_dedicated. `session` is the engine's; its
    fingerprint is W's (wrunlib.fingerprint)."""
    cellwin.guard(p, clearance)
    fp = session.get("fingerprint") or {}
    ws = dict(session, lab_plan=fp.get("lab_plan"), frequency=fp.get("frequency"), cycle_rate=fp.get("cycle_rate"))
    build: Path = p["build"]
    workload, proto, mode = p["workload"], p["proto"], p["mode"]
    gproto = p.get("gen_proto") or proto
    mixed = bool(p.get("background"))
    gen_cpus = list(MIXED_GEN_CPUS) if mixed else list(wwindow.GEN_CPUS)
    gthreads = list(wwindow.OPEN_GEN_THREADS) if workload == "open" else list(gen_cpus)
    spin = wwindow.OPEN_SPIN_US if workload == "open" else None
    tag = f"{session['id']}-p{position}-{arm}"
    raw.mkdir(parents=True, exist_ok=True)
    row: dict = {
        "workload": workload, "proto": proto, "backend": "IOCP", "host": "W", "mode": mode, "detect": p.get("detect", "replay"),
        "dispatch": "inproc", "port": p["port"], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "warmup_ms": window.WARMUP_MS,
        "duration_ms": window.DURATION_MS, "conns": window.CONNS_PER_CORE, "rate": p.get("rate"), "k_src": p["k_src"], "workers": 1,
        "listener": "shared", "placement": "mixed" if mixed else "in-process", "server_cpus": list(wwindow.SERVER_CPUS),
        "server_idle_siblings": list(wwindow.SERVER_IDLE_SIBLINGS), "generator_cpus": gen_cpus, "generator_thread_cpus": gthreads,
        "housekeeping_cpus": list(wwindow.HOUSEKEEPING), "spin_us": spin, "tag": tag, "freq_rule_applied": wwindow.FREQ_RULE,
    }
    if gproto != proto:
        row["gen_proto"] = gproto
    for k in ("iocp_accept", "iocp_receive"):
        if p.get(k) is not None:
            row[k] = p[k]
    base = blocks.take(p["k_src"])
    row["src_block"] = {"base": window.dotted(base), "k": p["k_src"]}
    reasons: list[str] = []
    t_start = time.monotonic()
    try:
        row["time_wait_before_wait"] = wsys.time_wait_count()
        row["time_wait_wait_s"], _ = wwindow.wait_time_wait()
        row["time_wait_start"] = wsys.time_wait_count()
        row["timer_resolution_start"] = wsys.timer_resolution()
        row["power_plan_start"] = wpower.active()
        tcp0 = wsys.tcp_stats()
        srv, srv_out, ports, cmd = start_server(build, p, raw, tag)
    except BaseException:
        blocks.release(base)
        raise
    row["server_command"] = cmd
    row["server_pid"] = srv.pid
    row["conn_state_bytes"] = next((int(ln.split()[-2]) for ln in srv_out.lines if ln.startswith("oneport: connection state")), None)
    sampler = wsys.Sampler(list(wwindow.SERVER_CPUS) + gen_cpus, 1.0)  # through the probe and the window (w-procedure section 4)
    sampler.start()
    gen_report = None
    snaps: dict = {}
    markers = None
    h = None
    bg = None
    bg_out: dict = {}
    ready: dict = {}
    try:
        row["server_affinity"] = hex(wsys.affinity(srv.pid))
        h = wsys.open_process(srv.pid)
        target = cellwin.target_port(mode, gproto, ports)
        row["target_port"] = target
        if mixed:
            spec = p["background"]
            if mode == "one-port":
                silent = [target]
            elif spec.get("silent_ports") == "http1":
                silent = [ports[window.LISTENER["http1"]]]
            elif spec.get("silent_ports") == "spread":
                silent = [ports[n] for n in ("HTTP/1.1", "h2c", "TLS", "MQTT", "SSH", "SMTP") if n in ports]
            else:
                raise WindowError(f"the silent background's ports in dedicated mode: {spec.get('silent_ports')!r}, not http1 or spread")
            duration = window.WARMUP_MS + window.DURATION_MS + cellwin.BG_MARGIN_MS
            bg = Background(build, ports, mode, silent, blocks, p["k_src"], raw, tag, duration)
            row["background"] = {"n": dict(N_BG), "silent_ports": silent, "silent_port_rule": spec.get("silent_ports") if mode == "dedicated" else "one-port",
                                 "commands": bg.commands, "duration_ms": duration, "cpus": {k: list(v) for k, v in MIXED_BG_CPUS.items()}}
            ready = bg.wait_ready()
        row["probe"] = probe(build, gproto, target, base, p["k_src"], gen_cpus)
        if row["probe"]["exit"] != 0:
            reasons.append(f"probe failed: {row['probe']['detail']}")
        out_json = raw / f"{tag}.opgen.json"
        gcmd = wwindow.opgen_cmd(build, gproto, target, base, p["k_src"]) + [
            "--cpus", ",".join(map(str, gthreads)), "--conns", str(window.CONNS_PER_CORE), "--warmup-ms", str(window.WARMUP_MS),
            "--duration-ms", str(window.DURATION_MS), "--out", str(out_json)]
        if workload == "keepalive":
            gcmd += ["--load", "keepalive"]
        if workload == "open":
            gcmd += ["--rate", repr(float(p["rate"]))]
        if spin is not None:
            gcmd += ["--spin-us", str(spin)]
        row["opgen_cmd"] = gcmd
        markers = wsys.MarkerReadings(range(12))
        gen = start_err(raw / f"{tag}.opgen.err", gcmd, gen_cpus, stdout=subprocess.PIPE)
        row["opgen_affinity"] = hex(wsys.affinity(gen.pid))
        gen_out = wwindow.ThreadLines(gen)

        def marker(line: str) -> bool:
            if line.startswith("MEASURE_START"):
                snaps["s0"] = server_snapshot(h)
                snaps["m0"] = markers.start()
            elif line.startswith("MEASURE_END"):
                snaps["s1"] = server_snapshot(h)
                snaps["cpus"] = markers.end()
                return True
            return False

        gen_out.until(marker, (window.WARMUP_MS + window.DURATION_MS) / 1000 + 30)
        gen_out.rest(30)
        try:
            gen.wait(timeout=30)
        except subprocess.TimeoutExpired:
            gen.kill()  # a process this window started
            gen.wait()
        row["opgen_exit"] = gen.returncode
        if out_json.exists():
            gen_report = json.loads(out_json.read_text())
        else:
            err = (raw / f"{tag}.opgen.err").read_text(errors="replace")[-300:]
            reasons.append(f"opgen wrote no report (exit {gen.returncode}): {err}")
        if bg is not None:
            bg_out = bg.finish()
    finally:
        if bg is not None:
            bg.stop()
            bg.release(blocks)
        exit_code, rest, how = wwindow.stop_server(srv, srv_out)
        if h is not None:
            wsys.close_handle(h)
        if markers is not None and "cpus" not in snaps:
            markers.pdh.close()
        blocks.release(base)
        row["frequency_samples"] = sampler.stop()
        row["frequency_sampler_error"] = sampler.error
    row["server_exit"] = exit_code
    row["server_stopped_by"] = how
    counters = window.parse_counters(rest)
    row["server_counters"] = counters
    row["time_wait_end"] = wsys.time_wait_count()
    row["timer_resolution_end"] = wsys.timer_resolution()
    row["power_plan_end"] = wpower.active()
    tcp1 = wsys.tcp_stats()
    row["tcp_stats_delta"] = {k: tcp1[k] - tcp0[k] for k in tcp0 if k in tcp1 and k != "CurrEstab"}
    row["window_overhead_s"] = time.monotonic() - t_start
    if bg is not None:
        row["background"].update(result=bg_out, ready=ready)
        reasons += cellwin.background_problems(bg_out, ready, gen_report)
        n = cellwin.background_connect_failures(bg_out)
        if n:
            reasons.append(f"{n} connects of the background failed")
    wwindow.finish(row, gen_report, snaps, ws, reasons, gen_cpus=gen_cpus)
    if mode == "one-port":
        expected: dict[str, int | None] = {cellwin.CLASS[gproto]: None}
        if bg is not None and gen_report:
            churn = int(gen_report.get("measure", {}).get("connects", 0)) + 1  # the probe's connection
            expected = {cellwin.CLASS[gproto]: churn}
            for kind in ("tls", "mqtt"):
                rep = (bg_out.get(kind) or {}).get("report") or {}
                expected[cellwin.CLASS[kind]] = int((rep.get("measure") or {}).get("connects", 0))
        row["misclassified"] = cellwin.misclassified(counters, expected)
        if row["misclassified"]:
            row["invalid_reasons"].append(f"{row['misclassified']} connections classified other than as their scripts' protocol (B1)")
            row["valid"] = False
    return row
