#!/usr/bin/env python3
"""One timed window of a cost cell, as hypotheses.md section 4.1 lays it out, on L.

A window starts fresh processes (the server on its core), checks one exchange of the cell's
protocol (the probe, `opgen --probe`), then runs `opgen` for a 1 s warm-up and a 5 s measured
window. The host is read at opgen's MEASURE_START and MEASURE_END markers: the server's CPU time
(utime + stime of /proc/<pid>/stat, WL4) and run time, the per-CPU counters of /proc/stat, the
mean CPU MHz of the window's CPUs. The server is stopped with SIGTERM after opgen exits and its
counters (I29) are read from what it prints. One JSON row per window, with full provenance and
section 7's validity rules.

M3 rule: no window times one-port mode (section 8, step 2; design/status.md, M3). The runner
starts the server only in dedicated mode and refuses any other mode.

Placement on L (section 4.1, in-process cells): the server on CPU 14 (its sibling CPU 15 idle),
opgen on CPUs 2 to 13, CPUs 0 and 1 for the system and this driver.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import select
import signal
import statistics
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
LAB_BIN = Path(os.environ.get("ONEPORT_LAB_BIN", str(Path.home() / "lab" / "Papers" / "lab" / "bin")))

# Section 4.1 and WL1 (frozen).
WARMUP_MS = 1000
DURATION_MS = 5000
CONNS_PER_CORE = 64
SERVER_CPUS = [14]
SERVER_IDLE_SIBLINGS = [15]
GEN_CPUS = list(range(2, 14))
# Design choice of M3 (design/status.md, the open loop's generator): in an open-loop window opgen
# runs one worker per physical core of its CPUs, on the first sibling of each (2, 4, ... 12), the
# other siblings idle, and polls the last 200 us before each due time (opgen's --spin-us default);
# workers on both siblings of a core slowed the client's own work. Closed-loop windows, which
# must saturate the server, keep a worker on each of the twelve.
OPEN_GEN_THREADS = [2, 4, 6, 8, 10, 12]
HOUSEKEEPING = [0, 1]
# Section 7 (frozen; the rules of lab/t1/t1.py).
MAX_ERROR_SHARE = 0.001
MAX_GEN_BUSY_PCT = 90.0
MAX_MHZ_DRIFT = 0.02
MIN_COMPLETED_SHARE = 0.99
# opgen's per-exchange timeout: lab/t1/t1.py's default (--timeout-ms 1000), a design choice of M3.
TIMEOUT_MS = 1000
# Connection tracking on L (design/status.md, M3): Docker's NAT rules make the kernel track every
# connection, loopback included, and each closed connection keeps its entry 120 s
# (nf_conntrack_tcp_timeout_time_wait), in a table of 262,144 (nf_conntrack_max): about one churn
# window's connections. Design choices of M3: before a window the runner waits until the table
# holds at most CT_START_MAX entries, at most CT_WAIT_MAX_S, so every window starts from an empty
# table; the count and the drop counters are recorded at the window's start and end.
CT_START_MAX = 2000
CT_WAIT_MAX_S = 180.0
PROTOS = ("http1", "h2c", "tls", "mqtt", "ssh", "tls-stub")
# The dedicated listener of each protocol, in the order of I20 (listening lines' names).
LISTENER = {"http1": "HTTP/1.1", "h2c": "h2c", "tls": "TLS", "mqtt": "MQTT", "ssh": "SSH", "tls-stub": "TLS"}
WORKLOADS = ("churn", "keepalive", "open")


class WindowError(RuntimeError):
    pass


# ---------------------------------------------------------------- host readings


def cpu_times() -> dict[int, list[int]]:
    out = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu") and line[3].isdigit():
                parts = line.split()
                out[int(parts[0][3:])] = [int(x) for x in parts[1:]]
    return out


def clk_tck() -> int:
    """USER_HZ, the unit of /proc/stat and of utime and stime in /proc/<pid>/stat."""
    return os.sysconf("SC_CLK_TCK")


def busy_seconds(t0: dict, t1: dict, cpus: list[int], hz: int) -> tuple[float, float]:
    """Non-idle and softirq seconds over a CPU set (lab/t1/t1.py): user, nice, system, irq,
    softirq and steal; softirq separately, since loopback's receive path runs there."""
    busy = soft = 0
    for c in cpus:
        d = [b - a for a, b in zip(t0[c], t1[c])]
        busy += d[0] + d[1] + d[2] + d[5] + d[6] + d[7]
        soft += d[6]
    return busy / hz, soft / hz


def cpu_mhz(cpus: list[int]) -> float:
    vals, cur = [], None
    with open("/proc/cpuinfo") as f:
        for line in f:
            if line.startswith("processor"):
                cur = int(line.split(":")[1])
            elif line.startswith("cpu MHz") and cur in cpus:
                vals.append(float(line.split(":")[1]))
    return statistics.fmean(vals) if vals else float("nan")


def proc_snapshot(pid: int) -> dict:
    """utime + stime ticks (/proc/<pid>/stat, WL4), the threads' run time (schedstat), VmRSS and
    VmHWM."""
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rindex(")") + 2:].split()
    snap = {"t": time.monotonic(), "cpu_ticks": int(fields[11]) + int(fields[12]), "run_ns": 0}
    for task in glob.glob(f"/proc/{pid}/task/*"):
        try:
            snap["run_ns"] += int(Path(task, "schedstat").read_text().split()[0])
        except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
            pass
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith(("VmHWM", "VmRSS")):
            snap[line.split(":")[0]] = int(line.split()[1])
    return snap


NSTAT_KEYS = ("TcpExtListenOverflows", "TcpExtListenDrops", "TcpExtTCPTimeWaitOverflow")


def parse_nstat(text: str) -> dict[str, int]:
    out = {k: 0 for k in NSTAT_KEYS}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in out:
            out[parts[0]] = int(parts[1])
    return out


def nstat() -> dict[str, int]:
    # -a absolute, -s keep the history file as it is, -z zero counters too.
    p = subprocess.run(["nstat", "-asz", *NSTAT_KEYS], capture_output=True, text=True, check=True)
    return parse_nstat(p.stdout)


def parse_interrupts(text: str) -> dict[int, dict[str, int]]:
    """/proc/interrupts: per CPU, the count of each interrupt line (numbered device lines by
    number, the rest by their name, LOC, RES, CAL, TLB...)."""
    lines = text.splitlines()
    cpus = [int(c[3:]) for c in lines[0].split()]
    out: dict[int, dict[str, int]] = {c: {} for c in cpus}
    for ln in lines[1:]:
        name, _, rest = ln.partition(":")
        vals = rest.split()
        for i, c in enumerate(cpus):
            if i < len(vals) and vals[i].isdigit():
                out[c][name.strip()] = int(vals[i])
    return out


def interrupts() -> dict[int, dict[str, int]]:
    return parse_interrupts(Path("/proc/interrupts").read_text())


def irq_delta(a: dict[int, dict[str, int]], b: dict[int, dict[str, int]], cpus: list[int]) -> dict[str, int]:
    """The interrupts over a CPU set between two readings, by line, the lines that moved."""
    out: dict[str, int] = {}
    for c in cpus:
        for k, v in b.get(c, {}).items():
            d = v - a.get(c, {}).get(k, 0)
            if d:
                out[k] = out.get(k, 0) + d
    return out


CT_STAT_KEYS = ("invalid", "insert_failed", "drop", "early_drop")


def parse_ct_stat(text: str) -> dict[str, int]:
    """/proc/net/stat/nf_conntrack: a header of names, then one line of hex values per CPU; the
    per-CPU counters summed (the first column, entries, is the table's count on every line)."""
    lines = [ln.split() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {}
    names = lines[0]
    out = {k: 0 for k in CT_STAT_KEYS}
    for vals in lines[1:]:
        for k in CT_STAT_KEYS:
            if k in names:
                out[k] += int(vals[names.index(k)], 16)
    return out


def conntrack() -> dict | None:
    """The table's count and size and the summed drop counters, or None without conntrack."""
    base = Path("/proc/sys/net/netfilter")
    try:
        out = {"count": int((base / "nf_conntrack_count").read_text()), "max": int((base / "nf_conntrack_max").read_text())}
        out.update(parse_ct_stat(Path("/proc/net/stat/nf_conntrack").read_text()))
        return out
    except OSError:
        return None


def wait_conntrack(limit: int = CT_START_MAX, max_wait: float = CT_WAIT_MAX_S) -> tuple[float, int | None]:
    """Waits until the table holds at most `limit` entries; returns the wait and the count."""
    t0 = time.monotonic()
    while True:
        ct = conntrack()
        if ct is None:
            return 0.0, None
        if ct["count"] <= limit or time.monotonic() - t0 >= max_wait:
            return time.monotonic() - t0, ct["count"]
        time.sleep(1.0)


def time_wait_count() -> int:
    p = subprocess.run(["ss", "-Htan", "state", "time-wait"], capture_output=True, text=True, check=True)
    return len([ln for ln in p.stdout.splitlines() if ln.strip()])


def pin_fingerprint() -> dict:
    p = subprocess.run(["bash", str(LAB_BIN / "pin.sh")], capture_output=True, text=True)
    try:
        fp = json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise WindowError(f"pin.sh printed no fingerprint: {p.stdout!r} {p.stderr!r}")
    fp["pin_exit"] = p.returncode
    return fp


# ---------------------------------------------------------------- source-address blocks


class SourceBlocks:
    """Each window takes the next unused block of K_SRC addresses of 127.0.0.0/8, never reused
    within 60 s (section 2.4). The state lives in a file on the host, so blocks stay unique across
    lab jobs; lablock serialises the jobs. Blocks run from 127.0.1.0 upward and wrap before
    127.255.255.255; a block whose addresses another window released less than REUSE_S ago is
    refused, never silently taken."""

    FIRST = 0x7F000100
    LAST = 0x7FFFFFFE
    REUSE_S = 60.0

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"next": self.FIRST, "recent": []}

    def take(self, k: int, now: float | None = None) -> int:
        now = time.time() if now is None else now
        st = self._load()
        base = st["next"]
        if base + k - 1 > self.LAST:
            base = self.FIRST
        for r in st["recent"]:
            overlap = base < r["base"] + r["k"] and r["base"] < base + k
            if overlap and (r.get("released") is None or now - r["released"] < self.REUSE_S):
                raise WindowError(f"source block {base:#x}+{k} would reuse addresses within {self.REUSE_S:.0f} s")
        st["recent"] = [r for r in st["recent"] if r.get("released") is None or now - r["released"] < 2 * self.REUSE_S]
        st["recent"].append({"base": base, "k": k, "taken": now, "released": None})
        st["next"] = base + k
        self.path.write_text(json.dumps(st))
        return base

    def release(self, base: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        st = self._load()
        for r in st["recent"]:
            if r["base"] == base and r.get("released") is None:
                r["released"] = now
        self.path.write_text(json.dumps(st))


def dotted(a: int) -> str:
    return f"{a >> 24}.{(a >> 16) & 255}.{(a >> 8) & 255}.{a & 255}"


# ---------------------------------------------------------------- processes


NL = b"\n"


class Lines:
    """A process's standard output, read line by line from the raw descriptor, so lines that
    arrive together are never held in a buffer that select() cannot see."""

    def __init__(self, proc: subprocess.Popen):
        self.fd = proc.stdout.fileno()
        self.proc = proc
        self.buf = b""
        self.lines: list[str] = []
        self.eof = False

    def until(self, pred, timeout: float) -> bool:
        """Reads until pred(line) holds for a new line (True), or EOF or the timeout (False)."""
        deadline = time.monotonic() + timeout
        while True:
            while NL in self.buf:
                line, self.buf = self.buf.split(NL, 1)
                text = line.decode(errors="replace")
                self.lines.append(text)
                if pred(text):
                    return True
            if self.eof:
                return False
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            r, _, _ = select.select([self.fd], [], [], min(left, 0.2))
            if not r:
                continue
            chunk = os.read(self.fd, 65536)
            if not chunk:
                self.eof = True
                if self.buf:
                    self.buf += NL
                continue
            self.buf += chunk

    def rest(self, timeout: float) -> list[str]:
        """Everything until EOF (or the timeout)."""
        self.until(lambda _: False, timeout)
        return self.lines


def counter_value(text: str) -> int | str:
    """A counter's value: an integer, or the text as printed (a flag such as "false")."""
    try:
        return int(text)
    except ValueError:
        return text


def parse_counters(lines: list[str]) -> dict:
    """The server's "counter <name> [<sub>] <value>" lines (counters.cpp describe()), matched by
    key, never by position, so lines added later (such as M6's) change nothing read here; every
    other line of the server's output is ignored."""
    out: dict = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 3 or parts[0] != "counter":
            continue
        if len(parts) == 3:
            out[parts[1]] = counter_value(parts[2])
        else:
            sub = out.setdefault(parts[1], {})
            if isinstance(sub, dict):
                sub[" ".join(parts[2:-1])] = counter_value(parts[-1])
    return out


def start_server(build: Path, backend: str, port: int, log_dir: Path, tag: str, no_aslr: bool = False) -> tuple[subprocess.Popen, "Lines", dict[str, int]]:
    cmd = [str(build / "bench" / "server" / "oneport"), "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc",
           "--backend", backend, "--port", str(port)]
    guard_mode(cmd)
    # no_aslr: the server process without address-space randomisation (util-linux setarch -R), so
    # every start lays out its memory alike; a per-process setting, the host unchanged.
    prefix = ["setarch", "x86_64", "-R"] if no_aslr else []
    proc = subprocess.Popen(prefix + ["taskset", "-c", ",".join(map(str, SERVER_CPUS))] + cmd, stdout=subprocess.PIPE,
                            stderr=open(log_dir / f"{tag}.server.err", "wb"), start_new_session=True, cwd=log_dir)
    out = Lines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        stop_process(proc, out)
        raise WindowError(f"the server did not start: {out.lines[-3:]}")
    ports = {}
    for ln in out.lines:
        if ln.startswith("oneport: listening "):
            name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
            ports[name] = int(addr.rsplit(":", 1)[1])
    return proc, out, ports


def guard_mode(cmd: list[str]) -> None:
    """M3: never a timed window in one-port mode (section 8 step 2; design/status.md)."""
    if "--mode" not in cmd or cmd[cmd.index("--mode") + 1] != "dedicated":
        raise WindowError("M3 times dedicated mode only")


def stop_process(proc: subprocess.Popen, out: "Lines", grace: float = 10.0) -> tuple[int | None, list[str]]:
    """SIGTERM to the process group, then its output to EOF and its exit status."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    lines = out.rest(grace)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    return proc.returncode, lines


def gen_threads(cfg: dict) -> list[int]:
    """The CPUs that carry one opgen worker each: the cell's override, else OPEN_GEN_THREADS in
    open loop and all of GEN_CPUS in closed loop."""
    return cfg.get("gen_threads") or (OPEN_GEN_THREADS if cfg.get("workload") == "open" else GEN_CPUS)


def opgen_cmd(build: Path, proto: str, port: int, base: int, k: int) -> list[str]:
    return [str(build / "bench" / "gen" / "opgen"), "--port", str(port), "--proto", proto, "--src-base", dotted(base),
            "--k-src", str(k), "--timeout-ms", str(TIMEOUT_MS)]


def probe(build: Path, proto: str, port: int, base: int, k: int) -> dict:
    cmd = ["taskset", "-c", ",".join(map(str, GEN_CPUS))] + opgen_cmd(build, proto, port, base, k) + ["--probe"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        rep = json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        rep = {}
    return {"exit": p.returncode, "detail": rep.get("probe_detail", p.stderr.strip()[-200:]),
            "connect_failures": rep.get("connect_failures", -1)}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- one window


def run_window(cfg: dict, session: dict, arm: str, position: int, blocks: SourceBlocks, raw: Path) -> dict:
    """A driver fault becomes an invalid row (t1.py's rule), never a lost window."""
    try:
        return _run_window(cfg, session, arm, position, blocks, raw)
    except Exception as e:  # noqa: BLE001 - recorded in the row, never swallowed
        return {"job": session["job"], "session": session["id"], "cell": cfg["cell"], "arm": arm, "position": position,
                "development": True, "valid": False, "invalid_reasons": [f"driver error: {e!r}"]}


def _run_window(cfg: dict, session: dict, arm: str, position: int, blocks: SourceBlocks, raw: Path) -> dict:
    build: Path = cfg["build"]
    workload, proto, backend = cfg["workload"], cfg["proto"], cfg["backend"]
    port = cfg["ports"][arm]
    tag = f"{session['id']}-{cfg['cell']}-p{position}-{arm}"
    raw.mkdir(parents=True, exist_ok=True)
    row: dict = {
        "job": session["job"], "session": session["id"], "cell": cfg["cell"], "workload": workload, "proto": proto,
        "backend": backend, "arm": arm, "position": position, "development": True, "mode": "dedicated",
        "port": port, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "warmup_ms": WARMUP_MS, "duration_ms": DURATION_MS,
        "conns": CONNS_PER_CORE, "rate": cfg.get("rate"), "k_src": cfg["k_src"], "server_cpus": SERVER_CPUS,
        "generator_thread_cpus": gen_threads(cfg), "spin_us": cfg.get("spin_us"),
        "server_idle_siblings": SERVER_IDLE_SIBLINGS, "generator_cpus": GEN_CPUS, "housekeeping_cpus": HOUSEKEEPING,
        "tag": tag,
    }
    base = blocks.take(cfg["k_src"])
    row["src_block"] = {"base": dotted(base), "k": cfg["k_src"]}
    reasons: list[str] = []
    waited, _ = wait_conntrack()
    ct0 = conntrack()
    row["conntrack_wait_s"] = waited
    tw0 = time_wait_count()
    ns0 = nstat()
    srv, srv_out, ports = start_server(build, backend, port, raw, tag, bool(cfg.get("server_no_aslr")))
    row["server_no_aslr"] = bool(cfg.get("server_no_aslr"))
    row["server_pid"] = srv.pid
    row["conn_state_bytes"] = next((int(ln.split()[-2]) for ln in srv_out.lines if ln.startswith("oneport: connection state")), None)
    target = ports.get(LISTENER[proto])
    if target is None:
        stop_process(srv, srv_out)
        raise WindowError(f"no {LISTENER[proto]} listener in {sorted(ports)}")
    row["target_port"] = target
    gen_report = None
    snaps: dict = {}
    mhz: list[float] = []
    try:
        row["probe"] = probe(build, proto, target, base, cfg["k_src"])
        if row["probe"]["exit"] != 0:
            reasons.append(f"probe failed: {row['probe']['detail']}")
        out_json = raw / f"{tag}.opgen.json"
        cmd = ["taskset", "-c", ",".join(map(str, GEN_CPUS))] + opgen_cmd(build, proto, target, base, cfg["k_src"]) + [
            "--cpus", ",".join(map(str, gen_threads(cfg))), "--conns", str(CONNS_PER_CORE), "--warmup-ms", str(WARMUP_MS),
            "--duration-ms", str(DURATION_MS), "--out", str(out_json)]
        if workload == "keepalive":
            cmd += ["--load", "keepalive"]
        if workload == "open":
            cmd += ["--rate", repr(float(cfg["rate"]))]
        if cfg.get("spin_us") is not None:
            cmd += ["--spin-us", str(cfg["spin_us"])]
        row["opgen_cmd"] = cmd
        all_cpus = SERVER_CPUS + GEN_CPUS
        gen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=open(raw / f"{tag}.opgen.err", "wb"))
        gen_out = Lines(gen)

        def marker(line: str) -> bool:
            if line.startswith("MEASURE_START"):
                snaps["s0"] = proc_snapshot(srv.pid)
                snaps["stat0"] = cpu_times()
                snaps["irq0"] = interrupts()
                mhz.append(cpu_mhz(all_cpus))
            elif line.startswith("MEASURE_END"):
                snaps["s1"] = proc_snapshot(srv.pid)
                snaps["stat1"] = cpu_times()
                snaps["irq1"] = interrupts()
                mhz.append(cpu_mhz(all_cpus))
                return True
            return False

        gen_out.until(marker, (WARMUP_MS + DURATION_MS) / 1000 + 30)
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
            err = (raw / f"{tag}.opgen.err").read_text(errors="replace")[-300:]
            reasons.append(f"opgen wrote no report (exit {gen.returncode}): {err}")
    finally:
        exit_code, rest = stop_process(srv, srv_out)
        blocks.release(base)
    row["server_exit"] = exit_code
    counters = parse_counters(rest)
    row["server_counters"] = counters
    row["time_wait_start"] = tw0
    row["time_wait_end"] = time_wait_count()
    ns1 = nstat()
    row["nstat_delta"] = {k: ns1[k] - ns0[k] for k in NSTAT_KEYS}
    ct1 = conntrack()
    row["conntrack"] = {"start": ct0, "end": ct1}
    if ct0 and ct1:
        row["conntrack_delta"] = {k: ct1[k] - ct0[k] for k in CT_STAT_KEYS}
    finish(row, gen_report, snaps, mhz, session, reasons)
    return row


def finish(row: dict, g: dict | None, snaps: dict, mhz: list[float], session: dict, reasons: list[str], hz: int | None = None) -> dict:
    """The row's metrics and section 7's validity rules. `hz` is USER_HZ (the host's, by default)."""
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
    if "s0" in snaps and "s1" in snaps:
        s0, s1 = snaps["s0"], snaps["s1"]
        hz = hz or clk_tck()
        span = s1["t"] - s0["t"]
        row["server_cpu_s"] = (s1["cpu_ticks"] - s0["cpu_ticks"]) / hz  # WL4: utime + stime
        row["server_run_s"] = (s1["run_ns"] - s0["run_ns"]) / 1e9
        row["cpu_us_per_exchange"] = 1e6 * row["server_cpu_s"] / exchanges if exchanges else None
        row["run_us_per_exchange"] = 1e6 * row["server_run_s"] / exchanges if exchanges else None
        row["rss_kb"], row["peak_rss_kb"] = s1.get("VmRSS"), s1.get("VmHWM")
        busy, soft = busy_seconds(snaps["stat0"], snaps["stat1"], SERVER_CPUS, hz)
        row["server_cores_busy"] = busy / span
        row["server_softirq_s"] = soft
        sib, _ = busy_seconds(snaps["stat0"], snaps["stat1"], SERVER_IDLE_SIBLINGS, hz)
        row["server_sibling_busy"] = sib / span
        gbusy, gsoft = busy_seconds(snaps["stat0"], snaps["stat1"], GEN_CPUS, hz)
        row["gen_cpus_busy_pct"] = 100.0 * gbusy / (span * len(GEN_CPUS))
        row["gen_softirq_s"] = gsoft
        hk, _ = busy_seconds(snaps["stat0"], snaps["stat1"], HOUSEKEEPING, hz)
        row["housekeeping_busy"] = hk / (span * len(HOUSEKEEPING))
        if "irq0" in snaps and "irq1" in snaps:
            row["irq_server"] = irq_delta(snaps["irq0"], snaps["irq1"], SERVER_CPUS)
            row["irq_server_sibling"] = irq_delta(snaps["irq0"], snaps["irq1"], SERVER_IDLE_SIBLINGS)
            row["irq_generator"] = irq_delta(snaps["irq0"], snaps["irq1"], GEN_CPUS)
    else:
        reasons.append("no window markers")
    # Operations and copies per connection (WL5): I29's counters over the server's lifetime (the
    # probe, the warm-up, the window and the drain), per accepted connection; in keep-alive also
    # per request.
    c = row.get("server_counters", {})
    acc = c.get("accepted", 0)
    if acc:
        per = {k: v / acc for k, v in c.items() if isinstance(v, int)}
        per["io_uring_submissions"] = {k: v / acc for k, v in c.get("io_uring_submissions", {}).items() if isinstance(v, int)}
        row["per_connection"] = per
        if workload == "keepalive" and g.get("all_completed"):
            n = g["all_completed"] + 1  # the probe's exchange
            row["per_request"] = {k: v / n for k, v in c.items() if isinstance(v, int)}
    # Section 7.
    if len(mhz) == 2:
        row["mhz_window"] = statistics.fmean(mhz)
        row["mhz_session"] = session["mhz"]
        row["mhz_drift"] = abs(row["mhz_window"] - session["mhz"]) / session["mhz"]
        if row["mhz_drift"] > MAX_MHZ_DRIFT:
            reasons.append(f"CPU MHz drift {100 * row['mhz_drift']:.2f}% > 2%")
    if completed == 0:
        reasons.append("no exchange completed")
    if g["error_share"] > MAX_ERROR_SHARE and completed > 0:
        reasons.append(f"errors {100 * g['error_share']:.3f}% > 0.1%")
    failures = g["connect_failures"] + max(0, row.get("probe", {}).get("connect_failures", 0))
    if failures > 0:
        reasons.append(f"{failures} connects failed")
    # The generator rule: the larger of its own CPU share and its CPUs' busy share (t1.py), in a
    # saturation (closed-loop) cell.
    row["gen_cpu_pct_rule"] = max(g["cpu"]["pct"], row.get("gen_cpus_busy_pct") or 0.0)
    if workload != "open" and row["gen_cpu_pct_rule"] > MAX_GEN_BUSY_PCT:
        reasons.append(f"generator CPU {row['gen_cpu_pct_rule']:.1f}% > 90% in a saturation cell")
    if workload == "open" and g["completed_share"] < MIN_COMPLETED_SHARE:
        reasons.append(f"open loop: {100 * g['completed_share']:.2f}% of the exchanges due completed, below 99%")
    nd = row.get("nstat_delta", {})
    if nd.get("TcpExtListenOverflows", 0) or nd.get("TcpExtListenDrops", 0):
        reasons.append(f"listen overflows {nd.get('TcpExtListenOverflows')} or drops {nd.get('TcpExtListenDrops')} during the window")
    row["valid"] = not reasons
    row["invalid_reasons"] = reasons
    return row
