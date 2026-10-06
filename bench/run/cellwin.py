#!/usr/bin/env python3
"""The in-process window of the frozen runners (M7c), on L: the cost family (5.1), M1 (5.3) and
section 10's cells that run the server in-process (SSH, the mixed-protocol cell, the two-core
cells), in either mode.

The layout is window.py's (section 4.1): fresh processes, the probe, then opgen for a 1 s warm-up
and a 5 s measured window, the host read at opgen's markers, the server stopped with SIGTERM and
its counters read; window.finish applies section 7. What this adds to window.py, which starts the
server only in dedicated mode (the pilot's and M3's A/A runs keep it):
- the server in one-port mode, with in-process dispatch and a detection mode (5.1: the default of
  rule E; M1: either). A one-port window of a cell that pairs one-port with dedicated mode starts
  only with the freeze guard's clearance (bench/run/freeze_guard.py; section 8 step 2): without
  one it raises before any process starts. The session engine never asks for one without it
  (bench/run/sessions.py writes a stub row instead), so this is the second lock of the same door;
- the server's workers and listener (section 10's two-core cells: 2 workers on CPUs 12 and 14,
  opgen on CPUs 2 to 11, 64 slots per server core; the SO_REUSEPORT group against the shared
  listener);
- the mixed-protocol cell's fixed background (section 10; 9.1's N_BG_TLS, N_BG_MQTT, N_BG_SILENT):
  TLS keep-alive and MQTT keep-alive as WL3 defines keep-alive (opgen --load keepalive: the
  connections established before the window, one request in flight on each; the revision log's
  entry "M7c's open items, before the code freeze", item 1, a reading), and silent
  connections held by opcase hold, which opens again at once each connection the server closes,
  the same policy in both modes (bench/cases/hold.hpp). The background starts before the probe,
  is established (opgen's MEASURE_START, opcase's HOLD) before the cell's generator starts, and
  must still run when the cell's window ends; its generators' connect failures count as the
  window's, and their error share is held to section 7's 0.1%;
- `misclassified` on every one-port row: the connections the server's counters classify as a
  protocol other than the scripts' (section 7, B1), the probe and the background included. In the
  mixed cell each script's class is bounded by the connects its generator reports, opgen's
  `connects_run` (expected_classes; the revision log's entry "The B1 count of the mixed cell (a
  later change under section 8)").

Placement of the mixed cell (a design choice of M7c, logged in the same entry, item 7: section 4.1
places the cell's opgen on CPUs 2 to 13 and names no background): the cell's opgen on CPUs 2 to 9,
the TLS background's on 10 and 11, the MQTT background's and the holder on 12 and 13. Section 7's
generator rule is applied to the cell's generator (item 8); each background generator's CPU time is
in the row's background report. The silent connections of the dedicated arm go to its HTTP/1.1
port (item 2; bench/run/s_run.py).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import window
from window import Placement, WindowError

HERE = Path(__file__).resolve().parent

# Section 4.1: the 2-core secondary cells, the server on CPUs 12 and 14 (siblings 13 and 15 idle),
# opgen on CPUs 2 to 11. Open-loop workers one per physical core, as M3 chose for one core.
TWO_CORES = Placement((12, 14), (13, 15), tuple(range(2, 12)), (2, 4, 6, 8, 10), (0, 1))
PLACEMENTS = {"in-process": window.IN_PROCESS, "two-cores": TWO_CORES}
# The mixed cell (M7c, a design choice; see the docstring).
MIXED_GEN = Placement((14,), (15,), tuple(range(2, 10)), (2, 4, 6, 8), (0, 1))
MIXED_BG_CPUS = {"tls": (10, 11), "mqtt": (12, 13), "silent": (12, 13)}
# The background runs past the cell's window by this much, so it covers the probe, the warm-up and
# the window with a margin (a design choice of M7c); its own warm-up is WL3's 1 s.
BG_MARGIN_MS = 4000
BG_READY_S = 20.0
# Section 9.1, set in engineering (revision log, "The code freeze's preparation (M7)", item 2).
N_BG = {"tls": 64, "mqtt": 64, "silent": 64}
# The server's class names in its counters (detect::name), by opgen's protocol.
CLASS = {"http1": "HTTP/1.1", "h2c": "h2c", "tls": "TLS", "mqtt": "MQTT", "ssh": "SSH", "tls-stub": "TLS", "tls-h2": "TLS"}
ONE_PORT_LISTENER = "one-port"


def popen_err(err: Path, cmd: list[str], **kw) -> subprocess.Popen:
    """Popen with standard error to a file; the parent's copy of the file is closed once the child
    has it, also when Popen fails, so no descriptor is left open."""
    with open(err, "wb") as f:
        return subprocess.Popen(cmd, stderr=f, **kw)


def server_cmd(build: Path, p: dict) -> list[str]:
    cmd = [str(build / "bench" / "server" / "oneport"), "--mode", p["mode"], "--detect", p.get("detect", "replay"), "--dispatch", "inproc",
           "--backend", p["backend"], "--port", str(p["port"])]
    if int(p.get("workers", 1)) != 1:
        cmd += ["--workers", str(int(p["workers"]))]
    if p.get("listener", "shared") != "shared":
        cmd += ["--listener", p["listener"]]
    return cmd


def guard(p: dict, clearance) -> None:
    """Section 8 step 2: a one-port window of a cell that pairs it with dedicated mode needs the
    freeze guard's clearance, which names the pilot entry."""
    if p["mode"] == "one-port" and p.get("pairs_dedicated") and (clearance is None or not getattr(clearance, "pilot_entry", False)):
        raise WindowError("no one-port window runs against dedicated mode before the pilot entry (section 8 step 2)")
    if p["mode"] not in ("one-port", "dedicated"):
        raise WindowError(f"mode {p['mode']!r}")


def start_server(build: Path, p: dict, pl: Placement, raw: Path, tag: str):
    cmd = server_cmd(build, p)
    proc = popen_err(raw / f"{tag}.server.err", ["taskset", "-c", ",".join(map(str, pl.server))] + cmd, stdout=subprocess.PIPE,
                     start_new_session=True, cwd=raw)
    out = window.Lines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        window.stop_process(proc, out)
        raise WindowError(f"the server did not start: {out.lines[-3:]}")
    ports = {}
    for ln in out.lines:
        if ln.startswith("oneport: listening "):
            name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
            ports[name] = int(addr.rsplit(":", 1)[1])
    return proc, out, ports, cmd


def target_port(mode: str, proto: str, ports: dict[str, int]) -> int:
    name = ONE_PORT_LISTENER if mode == "one-port" else window.LISTENER[proto]
    if name not in ports:
        raise WindowError(f"no {name} listener in {sorted(ports)}")
    return ports[name]


def run_connects(report: dict | None, what: str, unread: list[str]) -> int | None:
    """The connects of a whole opgen run, warm-up included: its report's `connects_run`
    (bench/gen/options.cpp, to_json; `measure` holds only `completed` and `errors`). None when the
    generator wrote no report, which the window's other rules already name; a report without the
    key is named in `unread`. Never 0 for a count not read."""
    if not report:
        return None
    if not isinstance(report.get("connects_run"), int):
        unread.append(f"the {what} report has no connects_run, so B1's bound for its class is not read")
        return None
    return report["connects_run"]


def expected_classes(gproto: str, gen_report: dict | None, bg_out: dict | None) -> tuple[dict[str, int | None], list[str]]:
    """The classes the server may give a one-port window's connections and, where a count is known,
    how many (misclassified() counts the rest), with the counts that could not be read. Outside the
    mixed cell (`bg_out` None): the script's class, any count. In the mixed cell (section 10): the
    churn's class at most the cell's opgen connects plus the probe's one, and TLS and MQTT each at
    most its background generator's connects (Background.finish keeps `connects_run`). A count not
    read is None, no bound."""
    if bg_out is None:
        return {CLASS[gproto]: None}, []
    unread: list[str] = []
    churn = run_connects(gen_report, "cell's opgen", unread)
    expected: dict[str, int | None] = {CLASS[gproto]: None if churn is None else churn + 1}  # + the probe's connection
    for kind in ("tls", "mqtt"):
        expected[CLASS[kind]] = run_connects((bg_out.get(kind) or {}).get("report"), f"{kind} background's", unread)
    return expected, unread


def b1_count(row: dict, counters: dict, gproto: str, gen_report: dict | None, bg_out: dict | None) -> None:
    """Section 7's misclassification rule on a one-port row, after window.finish: `misclassified`
    (a count above 0 makes the window invalid and is a failure of B1), and in the mixed cell
    (`bg_out` not None) the classes whose bound was not read, which a window cannot check
    (`misclassified_unbounded`; a report without `connects_run` also makes it invalid)."""
    expected, unread = expected_classes(gproto, gen_report, bg_out)
    row["misclassified"] = misclassified(counters, expected)
    if bg_out is not None:
        row["misclassified_unbounded"] = sorted(c for c, n in expected.items() if n is None)
    if unread:
        row["invalid_reasons"] += unread
        row["valid"] = False
    if row["misclassified"]:
        row["invalid_reasons"].append(f"{row['misclassified']} connections classified other than as their scripts' protocol (B1)")
        row["valid"] = False


def misclassified(counters: dict, expected: dict[str, int | None]) -> int:
    """Connections classified other than as their scripts' protocols: every class outside
    `expected`, and, where `expected` gives a count, the classified beyond it."""
    cl = counters.get("classified") or {}
    if not isinstance(cl, dict):
        return 0
    out = 0
    for name, n in cl.items():
        if not isinstance(n, int):
            continue
        if name not in expected:
            out += n
        elif expected[name] is not None and n > expected[name]:
            out += n - expected[name]
    return out


class Background:
    """The mixed cell's background (see the module's docstring)."""

    def __init__(self, build: Path, ports: dict[str, int], mode: str, silent_ports: list[int], blocks: window.SourceBlocks, k_src: int,
                 raw: Path, tag: str, duration_ms: int):
        self.procs: dict[str, subprocess.Popen] = {}
        self.lines: dict[str, window.Lines] = {}
        self.blocks: list[int] = []
        self.raw, self.tag = raw, tag
        try:
            self._start(build, ports, mode, silent_ports, blocks, k_src, raw, tag, duration_ms)
        except BaseException:  # a stop (SystemExit) while starting it, too
            self.stop()
            self.release(blocks)
            raise
        self.commands = {k: p.args for k, p in self.procs.items()}

    def _start(self, build: Path, ports: dict[str, int], mode: str, silent_ports: list[int], blocks: window.SourceBlocks, k_src: int,
               raw: Path, tag: str, duration_ms: int) -> None:
        for kind in ("tls", "mqtt"):
            base = blocks.take(k_src)
            self.blocks.append(base)
            port = target_port(mode, kind, ports)
            cmd = ["taskset", "-c", ",".join(map(str, MIXED_BG_CPUS[kind]))] + window.opgen_cmd(build, kind, port, base, k_src) + [
                "--load", "keepalive", "--cpus", ",".join(map(str, MIXED_BG_CPUS[kind])), "--conns", str(N_BG[kind]),
                "--warmup-ms", str(window.WARMUP_MS), "--duration-ms", str(duration_ms), "--out", str(raw / f"{tag}.bg-{kind}.json")]
            self.procs[kind] = popen_err(raw / f"{tag}.bg-{kind}.err", cmd, stdout=subprocess.PIPE)
            self.lines[kind] = window.Lines(self.procs[kind])
        base = blocks.take(k_src)
        self.blocks.append(base)
        cmd = ["taskset", "-c", ",".join(map(str, MIXED_BG_CPUS["silent"])), str(build / "bench" / "cases" / "opcase"), "hold",
               "--ports", ",".join(map(str, silent_ports)), "--n", str(N_BG["silent"]), "--src-base", window.dotted(base), "--k-src", str(k_src)]
        self.procs["silent"] = popen_err(raw / f"{tag}.bg-silent.err", cmd, stdout=subprocess.PIPE, start_new_session=True)
        self.lines["silent"] = window.Lines(self.procs["silent"])

    def wait_ready(self) -> dict:
        ready = {}
        for kind in ("tls", "mqtt"):
            ready[kind] = self.lines[kind].until(lambda ln: ln.startswith("MEASURE_START"), BG_READY_S)
        ready["silent"] = self.lines["silent"].until(lambda ln: ln.startswith("HOLD "), BG_READY_S)
        return ready

    def finish(self) -> dict:
        out: dict = {}
        for kind in ("tls", "mqtt"):
            self.lines[kind].rest(60)
            try:
                self.procs[kind].wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.procs[kind].kill()
                self.procs[kind].wait()
            f = self.raw / f"{self.tag}.bg-{kind}.json"
            rep = json.loads(f.read_text()) if f.exists() else None
            out[kind] = {"exit": self.procs[kind].returncode, "ok": bool(rep and rep.get("ok")),
                         "report": {k: rep[k] for k in ("measure", "warmup", "error_share", "connect_failures", "connects_run",
                                                         "all_completed", "measure_start_ns", "measure_end_ns", "wall_s", "cpus", "cpu")
                                    if k in rep}
                         if rep else None}
        lines, code = [], None
        if self.procs["silent"].poll() is None:
            self.procs["silent"].send_signal(15)
        lines = self.lines["silent"].rest(15)
        try:
            self.procs["silent"].wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.procs["silent"].kill()
            self.procs["silent"].wait()
        code = self.procs["silent"].returncode
        rep = next((json.loads(ln) for ln in reversed(lines) if ln.startswith("{")), None)
        out["silent"] = {"exit": code, "ok": bool(rep and rep.get("ok")), "report": rep}
        return out

    def stop(self) -> None:
        for p in self.procs.values():
            if p.poll() is None:
                p.kill()
                p.wait()

    def release(self, blocks: window.SourceBlocks) -> None:
        for b in self.blocks:
            blocks.release(b)


def background_problems(bg: dict, ready: dict, gen: dict | None) -> list[str]:
    out = []
    for kind, ok in ready.items():
        if not ok:
            out.append(f"the {kind} background was not established before the window")
    for kind in ("tls", "mqtt"):
        b = bg.get(kind) or {}
        rep = b.get("report") or {}
        if not b.get("ok"):
            out.append(f"the {kind} background's generator failed (exit {b.get('exit')})")
            continue
        if rep.get("error_share", 0) > window.MAX_ERROR_SHARE:
            out.append(f"the {kind} background's errors {100 * rep['error_share']:.3f}% > 0.1%")
        if gen and rep.get("measure_end_ns") and gen.get("measure_end_ns") and rep["measure_end_ns"] < gen["measure_end_ns"]:
            out.append(f"the {kind} background ended before the cell's window")
    s = bg.get("silent") or {}
    if not s.get("ok"):
        out.append(f"the silent background failed (exit {s.get('exit')})")
    return out


def background_connect_failures(bg: dict) -> int:
    n = 0
    for kind in ("tls", "mqtt"):
        n += int(((bg.get(kind) or {}).get("report") or {}).get("connect_failures") or 0)
    n += int(((bg.get("silent") or {}).get("report") or {}).get("connect_failures") or 0)
    return n


def run(p: dict, session: dict, arm: str, position: int, blocks: window.SourceBlocks, raw: Path, clearance=None) -> dict:
    """One window. `p`: build, cell, workload, proto, backend, mode, detect, k_src, port (this
    arm's first port), and optionally rate (open loop), workers, listener, placement
    ("in-process" or "two-cores"), background (the mixed cell: {"silent_ports": "http1" or
    "spread"}), pairs_dedicated, gen_proto (opgen's protocol where it differs from the row's
    `proto`: section 10's TLS variant with ALPN h2 is the row's "tls", opgen's "tls-h2")."""
    guard(p, clearance)
    build: Path = p["build"]
    workload, proto, mode = p["workload"], p["proto"], p["mode"]
    gproto = p.get("gen_proto") or proto
    pl = MIXED_GEN if p.get("background") else PLACEMENTS[p.get("placement", "in-process")]
    cores = len(pl.server)
    tag = f"{session['id']}-p{position}-{arm}"
    raw.mkdir(parents=True, exist_ok=True)
    row: dict = {
        "workload": workload, "proto": proto, "backend": p["backend"], "mode": mode, "detect": p.get("detect", "replay"), "dispatch": "inproc",
        "port": p["port"], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "warmup_ms": window.WARMUP_MS, "duration_ms": window.DURATION_MS,
        "conns": window.CONNS_PER_CORE * cores, "rate": p.get("rate"), "k_src": p["k_src"], "workers": int(p.get("workers", 1)),
        "listener": p.get("listener", "shared"), "placement": p.get("placement", "in-process") if not p.get("background") else "mixed",
        "server_cpus": list(pl.server), "server_idle_siblings": list(pl.server_siblings), "generator_cpus": list(pl.gen),
        "housekeeping_cpus": list(pl.housekeeping), "tag": tag,
    }
    if gproto != proto:
        row["gen_proto"] = gproto
    gthreads = list(pl.open_gen_threads) if workload == "open" else list(pl.gen)
    row["generator_thread_cpus"] = gthreads
    base = blocks.take(p["k_src"])
    row["src_block"] = {"base": window.dotted(base), "k": p["k_src"]}
    reasons: list[str] = []
    try:
        ct_before = window.conntrack()
        row["conntrack_wait_s"], _ = window.wait_conntrack()
        ct0 = window.conntrack()
        tw0 = window.time_wait_count()
        ns0 = window.nstat()
        srv, srv_out, ports, cmd = start_server(build, p, pl, raw, tag)
    except BaseException:
        blocks.release(base)
        raise
    row["server_command"] = cmd
    row["server_pid"] = srv.pid
    row["conn_state_bytes"] = next((int(ln.split()[-2]) for ln in srv_out.lines if ln.startswith("oneport: connection state")), None)
    gen_report = None
    snaps: dict = {}
    mhz: list[float] = []
    bg = None
    bg_out: dict = {}
    ready: dict = {}
    try:
        target = target_port(mode, gproto, ports)
        row["target_port"] = target
        if p.get("background"):
            spec = p["background"]
            if mode == "one-port":
                silent = [target]
            elif spec.get("silent_ports") == "http1":
                silent = [ports[window.LISTENER["http1"]]]
            elif spec.get("silent_ports") == "spread":
                silent = [ports[n] for n in ("HTTP/1.1", "h2c", "TLS", "MQTT", "SSH", "SMTP") if n in ports]
            else:
                raise WindowError(f"the silent background's ports in dedicated mode: {spec.get('silent_ports')!r}, not http1 or spread")
            duration = window.WARMUP_MS + window.DURATION_MS + BG_MARGIN_MS
            bg = Background(build, ports, mode, silent, blocks, p["k_src"], raw, tag, duration)
            row["background"] = {"n": dict(N_BG), "silent_ports": silent, "silent_port_rule": spec.get("silent_ports") if mode == "dedicated" else "one-port",
                                 "commands": bg.commands, "duration_ms": duration}
            ready = bg.wait_ready()
        row["probe"] = window.probe(build, gproto, target, base, p["k_src"], pl.gen)
        if row["probe"]["exit"] != 0:
            reasons.append(f"probe failed: {row['probe']['detail']}")
        out_json = raw / f"{tag}.opgen.json"
        gcmd = ["taskset", "-c", ",".join(map(str, pl.gen))] + window.opgen_cmd(build, gproto, target, base, p["k_src"]) + [
            "--cpus", ",".join(map(str, gthreads)), "--conns", str(window.CONNS_PER_CORE * cores), "--warmup-ms", str(window.WARMUP_MS),
            "--duration-ms", str(window.DURATION_MS), "--out", str(out_json)]
        if workload == "keepalive":
            gcmd += ["--load", "keepalive"]
        if workload == "open":
            gcmd += ["--rate", repr(float(p["rate"]))]
        row["opgen_cmd"] = gcmd
        all_cpus = list(pl.server) + list(pl.gen)
        gen = popen_err(raw / f"{tag}.opgen.err", gcmd, stdout=subprocess.PIPE)
        gen_out = window.Lines(gen)

        def marker(line: str) -> bool:
            if line.startswith("MEASURE_START"):
                snaps["s0"] = window.proc_snapshot(srv.pid)
                snaps["stat0"] = window.cpu_times()
                snaps["irq0"] = window.interrupts()
                mhz.append(window.cpu_mhz(all_cpus))
            elif line.startswith("MEASURE_END"):
                snaps["s1"] = window.proc_snapshot(srv.pid)
                snaps["stat1"] = window.cpu_times()
                snaps["irq1"] = window.interrupts()
                mhz.append(window.cpu_mhz(all_cpus))
                return True
            return False

        gen_out.until(marker, (window.WARMUP_MS + window.DURATION_MS) / 1000 + 30)
        gen_out.rest(30)
        try:
            gen.wait(timeout=30)
        except subprocess.TimeoutExpired:
            gen.kill()
            gen.wait()
        row["opgen_exit"] = gen.returncode
        if out_json.exists():
            gen_report = json.loads(out_json.read_text())
        else:
            reasons.append(f"opgen wrote no report (exit {gen.returncode})")
        if bg is not None:
            bg_out = bg.finish()
    finally:
        if bg is not None:
            bg.stop()
            bg.release(blocks)
        exit_code, rest = window.stop_process(srv, srv_out)
        blocks.release(base)
    row["server_exit"] = exit_code
    counters = window.parse_counters(rest)
    row["server_counters"] = counters
    row["time_wait_start"] = tw0
    row["time_wait_end"] = window.time_wait_count()
    ns1 = window.nstat()
    row["nstat_delta"] = {k: ns1[k] - ns0[k] for k in window.NSTAT_KEYS}
    ct1 = window.conntrack()
    row["conntrack_count"] = {"before_wait": (ct_before or {}).get("count"), "start": (ct0 or {}).get("count"), "end": (ct1 or {}).get("count")}
    if bg is not None:
        row["background"].update(result=bg_out, ready=ready)
        reasons += background_problems(bg_out, ready, gen_report)
        n = background_connect_failures(bg_out)
        if n:
            reasons.append(f"{n} connects of the background failed")
    window.finish(row, gen_report, snaps, mhz, session, reasons, placement=pl)
    if mode == "one-port":
        b1_count(row, counters, gproto, gen_report, bg_out if bg is not None else None)
    return row
