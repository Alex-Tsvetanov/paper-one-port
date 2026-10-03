#!/usr/bin/env python3
"""Hand-off windows on L (hypotheses.md section 4.1): the mechanism family's M3 cells, the server's
relay against each proxy, as development data before the code freeze (section 8, step 2; M4a).

A window starts fresh processes: the stub backend (`oneport --mode stub`, I18), two workers on CPUs
10 and 12; then the front on CPU 14, either the server in one-port mode with relay dispatch (its
default detection mode, replay; rule E's proposed default relay copy, user space; epoll, the
accept model all five proxies use, section 5.3) or a proxy in its M3 configuration
(bench/competitors). Then the probe (`opgen --probe` through the front), and opgen on CPUs 2 to 9
for a 1 s warm-up and a 5 s window with C = 64 slots (WL1, one front core). At opgen's markers the
runner reads the CPU time of the front (its whole process group: nginx's master and worker) and of
the backend, /proc/stat, the CPU MHz and /proc/interrupts. One row per window: connections per
second (M3's metric), CPU per connection of the front, of the backend and of both (WL6), the
backend cores' busy share (section 7: a hand-off window is invalid if a backend core was more than
90% busy), listen overflows recorded beside the cell (section 7: not a rule in M3), and section 7's
other rules (window.finish).

A session is X Y Y X of the server's relay (arm A) and one proxy (arm B), X drawn per session;
`window.guard_pair` refuses any other pairing. The session ratio is server / proxy (section 5.3).
Every row is development data, journaled as such.

    handoff.py --build DIR --out DIR --job NAME --competitors nginx,haproxy --protos tls-stub,http1
               --seed N --k-src 16 [--sessions 1]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "competitors"))

import aa  # noqa: E402
import competitors as comp  # noqa: E402
import window  # noqa: E402

PL = window.HANDOFF
BACKEND_CPUS = (10, 12)
BACKEND_IDLE_SIBLINGS = (11, 13)
MAX_BACKEND_CORE_BUSY = 0.90  # section 7, hand-off cells (a design choice of the frozen text)
STUB_WORKERS = len(BACKEND_CPUS)
# Design choices of M4a (design/status.md): each arm's ports, off the ephemeral range, one block
# per arm so that every change of arm changes port (section 4.6, step 1). The front listens on the
# first port; the stub's six listeners start 10 above it (I20's order); caddy-l4's admin endpoint
# is 50 above it (competitors.fields).
PORTS = {"A": 22000, "B": 22100}
STUB_OFFSET = 10
SERVER = window.ONE_PORT_RELAY
# M3's two protocols (section 6.3): TLS routed by SNI is the stub exchange of WL1 (the recorded
# ClientHello, the stub's 13 bytes to EOF); plaintext HTTP/1.1 is WL1's HTTP/1.1 exchange.
M3_PROTOS = ("tls-stub", "http1")


# ---------------------------------------------------------------- processes


def group_snapshot(pgid: int) -> dict:
    """window.proc_snapshot over a process group: utime + stime and the threads' run time of every
    process (nginx: master and worker), and the summed VmRSS and VmHWM."""
    snap = {"t": time.monotonic(), "cpu_ticks": 0, "run_ns": 0, "VmRSS": 0, "VmHWM": 0, "pids": comp.group_pids(pgid)}
    for pid in snap["pids"]:
        try:
            s = window.proc_snapshot(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue
        for k in ("cpu_ticks", "run_ns", "VmRSS", "VmHWM"):
            snap[k] += s.get(k, 0)
    return snap


def start_stub(build: Path, port: int, raw: Path, tag: str, backend: str = "epoll"):
    cmd = [str(build / "bench" / "server" / "oneport"), "--mode", "stub", "--detect", "replay", "--dispatch", "inproc",
           "--backend", backend, "--workers", str(STUB_WORKERS), "--port", str(port)]
    proc = subprocess.Popen(["taskset", "-c", ",".join(map(str, BACKEND_CPUS))] + cmd, stdout=subprocess.PIPE,
                            stderr=open(raw / f"{tag}.stub.err", "wb"), start_new_session=True, cwd=raw,
                            preexec_fn=comp.raise_nofile)
    out = window.Lines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        window.stop_process(proc, out)
        raise window.WindowError(f"the stub did not start: {out.lines[-3:]}")
    return proc, out


def server_front_cmd(build: Path, port: int, stub_port: int, kind: str = "m3", backend: str = "epoll") -> list[str]:
    """The server's front in M3: one-port mode, relay dispatch to the stub, its default detection
    mode (replay) and rule E's proposed relay copy (user space); B3 sets every timer to 60 s
    (section 1)."""
    cmd = [str(build / "bench" / "server" / "oneport"), "--mode", "one-port", "--detect", "replay", "--dispatch", "relay",
           "--relay-copy", "user-space", "--backend", backend, "--port", str(port), "--relay-port", str(stub_port)]
    if kind == "b3":
        cmd += ["--t-fb-ms", "60000", "--t-dec-ms", "60000", "--t-hdr-ms", "60000"]
    return cmd


class Front:
    """The front of a hand-off window: the server's relay or a competitor, on PL.server."""

    def __init__(self, arm_name: str, build: Path, port: int, stub_port: int, raw: Path, tag: str, kind: str = "m3",
                 backend: str = "epoll"):
        self.name = arm_name
        self.port = port
        self.lines: list[str] = []
        self.out = None
        self.running = None
        if arm_name == SERVER:
            cmd = server_front_cmd(build, port, stub_port, kind, backend)
            self.proc = subprocess.Popen(["taskset", "-c", ",".join(map(str, PL.server))] + cmd, stdout=subprocess.PIPE,
                                         stderr=open(raw / f"{tag}.front.err", "wb"), start_new_session=True, cwd=raw,
                                         preexec_fn=comp.raise_nofile)
            (raw / f"{tag}.front.pid").write_text(f"{self.proc.pid}\n")
            self.out = window.Lines(self.proc)
            if not self.out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
                window.stop_process(self.proc, self.out)
                raise window.WindowError(f"the server's front did not start: {self.out.lines[-3:]}")
            self.command = cmd
        else:
            self.running = comp.start(arm_name, kind, port, stub_port, list(PL.server), raw / f"{tag}.front")
            self.proc = self.running.proc
            self.command = self.running.command

    @property
    def pgid(self) -> int:
        return self.proc.pid

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> tuple[int | None, list[str]]:
        if self.running is not None:
            code = comp.stop(self.running)
            return code, []
        code, lines = window.stop_process(self.proc, self.out)
        return code, lines


# ---------------------------------------------------------------- one window


def run_window(cfg: dict, session: dict, arm: str, position: int, blocks: window.SourceBlocks, raw: Path) -> dict:
    """A driver fault becomes an invalid row, never a lost window (t1.py's rule)."""
    try:
        return _run_window(cfg, session, arm, position, blocks, raw)
    except Exception as e:  # noqa: BLE001 - recorded in the row
        return {"job": session["job"], "session": session["id"], "cell": cfg["cell"], "arm": arm, "position": position,
                "system": cfg["arms"][arm], "development": True, "valid": False, "invalid_reasons": [f"driver error: {e!r}"]}


def _run_window(cfg: dict, session: dict, arm: str, position: int, blocks: window.SourceBlocks, raw: Path) -> dict:
    build: Path = cfg["build"]
    proto = cfg["proto"]
    system = cfg["arms"][arm]
    port = cfg["ports"][arm]
    stub_port = port + STUB_OFFSET
    tag = f"{session['id']}-p{position}-{arm}"
    raw.mkdir(parents=True, exist_ok=True)
    row: dict = {
        "job": session["job"], "session": session["id"], "cell": cfg["cell"], "workload": "churn", "proto": proto,
        "backend": cfg.get("backend", "epoll"), "arm": arm, "system": system, "position": position, "development": True,
        "family": "M3", "port": port, "stub_port": stub_port, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "warmup_ms": window.WARMUP_MS, "duration_ms": window.DURATION_MS, "conns": window.CONNS_PER_CORE,
        "k_src": cfg["k_src"], "front_cpus": list(PL.server), "front_idle_siblings": list(PL.server_siblings),
        "backend_cpus": list(BACKEND_CPUS), "backend_idle_siblings": list(BACKEND_IDLE_SIBLINGS), "generator_cpus": list(PL.gen),
        "housekeeping_cpus": list(PL.housekeeping), "tag": tag,
    }
    t_start = time.monotonic()
    base = blocks.take(cfg["k_src"])
    row["src_block"] = {"base": window.dotted(base), "k": cfg["k_src"]}
    reasons: list[str] = []
    ct_before = window.conntrack()
    row["conntrack_wait_s"], _ = window.wait_conntrack()
    ct0 = window.conntrack()
    tw0 = window.time_wait_count()
    ns0 = window.nstat()
    stub, stub_out = start_stub(build, stub_port, raw, tag, cfg.get("stub_backend", "epoll"))
    front = None
    gen_report = None
    snaps: dict = {}
    mhz: list[float] = []
    front_alive = False
    stub_lines: list[str] = []
    front_lines: list[str] = []
    try:
        front = Front(system, build, port, stub_port, raw, tag, "m3", cfg.get("backend", "epoll"))
        row["front_command"] = front.command
        row["probe"] = window.probe(build, proto, port, base, cfg["k_src"], PL.gen)
        if row["probe"]["exit"] != 0:
            reasons.append(f"probe failed: {row['probe']['detail']}")
        out_json = raw / f"{tag}.opgen.json"
        cmd = ["taskset", "-c", ",".join(map(str, PL.gen))] + window.opgen_cmd(build, proto, port, base, cfg["k_src"]) + [
            "--cpus", ",".join(map(str, PL.gen)), "--conns", str(window.CONNS_PER_CORE), "--warmup-ms", str(window.WARMUP_MS),
            "--duration-ms", str(window.DURATION_MS), "--out", str(out_json)]
        row["opgen_cmd"] = cmd
        all_cpus = list(PL.server) + list(BACKEND_CPUS) + list(PL.gen)
        gen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=open(raw / f"{tag}.opgen.err", "wb"))
        gen_out = window.Lines(gen)

        def marker(line: str) -> bool:
            if line.startswith("MEASURE_START"):
                snaps["s0"] = group_snapshot(front.pgid)
                snaps["b0"] = window.proc_snapshot(stub.pid)
                snaps["stat0"] = window.cpu_times()
                snaps["irq0"] = window.interrupts()
                mhz.append(window.cpu_mhz(all_cpus))
            elif line.startswith("MEASURE_END"):
                snaps["s1"] = group_snapshot(front.pgid)
                snaps["b1"] = window.proc_snapshot(stub.pid)
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
    finally:
        if front is not None:
            front_alive = front.alive()
            code, front_lines = front.stop()
            row["front_exit"] = code
        _, stub_lines = window.stop_process(stub, stub_out)
        row["stub_exit"] = stub.returncode
        blocks.release(base)
    # The front's own exit status after the runner's SIGTERM differs by system; what section 7 asks
    # is that the front did not fail, so a front alive until the runner stopped it counts as exit 0.
    row["server_exit"] = 0 if front_alive else row.get("front_exit")
    row["server_counters"] = window.parse_counters(front_lines) if system == SERVER else {}
    row["backend_counters"] = window.parse_counters(stub_lines)
    row["time_wait_start"] = tw0
    row["time_wait_end"] = window.time_wait_count()
    ns1 = window.nstat()
    row["nstat_delta"] = {k: ns1[k] - ns0[k] for k in window.NSTAT_KEYS}
    ct1 = window.conntrack()
    row["conntrack_count"] = {"before_wait": (ct_before or {}).get("count"), "start": (ct0 or {}).get("count"),
                              "end": (ct1 or {}).get("count")}
    if ct0 and ct1:
        row["conntrack_delta"] = {k: ct1[k] - ct0[k] for k in window.CT_STAT_KEYS}
    if row["stub_exit"] != 0:
        reasons.append(f"backend exit {row['stub_exit']}")
    window.finish(row, gen_report, snaps, mhz, session, reasons, placement=PL, overflow_invalidates=False)
    finish_handoff(row, snaps, gen_report)
    row["window_wall_s"] = time.monotonic() - t_start
    return row


def finish_handoff(row: dict, snaps: dict, g: dict | None, hz: int | None = None) -> dict:
    """The backend's part of a hand-off row: its CPU time, WL6's CPU per connection of front and
    backend together, and section 7's backend rule (a backend core more than 90% busy)."""
    if "b0" not in snaps or "b1" not in snaps or "stat0" not in snaps or g is None or not g.get("ok"):
        return row
    hz = hz or window.clk_tck()
    span = snaps["b1"]["t"] - snaps["b0"]["t"]
    row["backend_cpu_s"] = (snaps["b1"]["cpu_ticks"] - snaps["b0"]["cpu_ticks"]) / hz
    exchanges = g["measure"]["completed"]
    if exchanges:
        row["backend_cpu_us_per_exchange"] = 1e6 * row["backend_cpu_s"] / exchanges
        if row.get("server_cpu_s") is not None:
            row["wl6_cpu_us_per_exchange"] = 1e6 * (row["server_cpu_s"] + row["backend_cpu_s"]) / exchanges
    per_core = {}
    for c in BACKEND_CPUS:
        busy, _ = window.busy_seconds(snaps["stat0"], snaps["stat1"], [c], hz)
        per_core[str(c)] = busy / span if span > 0 else 0.0
    row["backend_core_busy"] = per_core
    sib, _ = window.busy_seconds(snaps["stat0"], snaps["stat1"], list(BACKEND_IDLE_SIBLINGS), hz)
    row["backend_sibling_busy"] = sib / (span * len(BACKEND_IDLE_SIBLINGS)) if span > 0 else 0.0
    over = {c: b for c, b in per_core.items() if b > MAX_BACKEND_CORE_BUSY}
    if over:
        row["invalid_reasons"].append("backend core " + ", ".join(f"{c} {100 * b:.1f}%" for c, b in over.items()) + " busy > 90%")
        row["valid"] = False
    return row


# ---------------------------------------------------------------- sessions


def session_ratio(rows: list[dict]) -> float | None:
    """Server / proxy (section 5.3), each arm the mean of its two windows; None unless all four
    are valid."""
    if len(rows) != 4 or not all(r.get("valid") for r in rows):
        return None
    a = [r["metric"]["value"] for r in rows if r["arm"] == "A"]
    b = [r["metric"]["value"] for r in rows if r["arm"] == "B"]
    if len(a) != 2 or len(b) != 2 or statistics.fmean(b) <= 0:
        return None
    return statistics.fmean(a) / statistics.fmean(b)


def parse_list(spec: str, allowed: tuple[str, ...], what: str) -> list[str]:
    items = [x for x in spec.split(",") if x]
    bad = [x for x in items if x not in allowed]
    if bad or not items:
        raise SystemExit(f"bad {what}: {bad or spec!r}; allowed {allowed}")
    return items


def main(argv=None) -> int:
    window.stop_on_signals()  # its finally blocks stop the processes it started
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--competitors", required=True)
    ap.add_argument("--protos", default=",".join(M3_PROTOS))
    ap.add_argument("--sessions", type=int, default=1)
    ap.add_argument("--seed", type=int, required=True, help="the development order's seed, recorded in the journal")
    ap.add_argument("--k-src", type=int, required=True)
    ap.add_argument("--tools", type=Path, default=Path.home() / "lab" / "p3" / "tools")
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    a = ap.parse_args(argv)
    systems = parse_list(a.competitors, comp.ORDER, "competitors")
    protos = parse_list(a.protos, M3_PROTOS, "protocols")
    for s in systems:
        window.guard_pair(SERVER, s, comp.ORDER)
        if not comp.SYSTEMS[s].binary_path().exists():
            raise SystemExit(f"{s}: no binary at {comp.SYSTEMS[s].binary_path()} (bench/competitors/install.sh)")
    a.out.mkdir(parents=True, exist_ok=True)
    prov = aa.provenance(a.build, a.tools)
    prov["competitors"] = {s: {"binary": str(comp.SYSTEMS[s].binary_path()), "sha256": window.sha256_file(comp.SYSTEMS[s].binary_path()),
                               "m3_config_sha256": window.sha256_file(comp.SYSTEMS[s].template("m3"))} for s in systems}
    (a.out / "provenance.json").write_text(json.dumps(prov, indent=1))
    blocks = window.SourceBlocks(a.blocks)
    rng = random.Random(a.seed)
    order = [(s, p, n) for s in systems for p in protos for n in range(1, a.sessions + 1)]
    rng.shuffle(order)
    rows_path = a.out / "windows.jsonl"
    rows: list[dict] = []
    for system, proto, n in order:
        cell = f"m3.{proto}.{system}"
        cfg = {"build": a.build, "proto": proto, "k_src": a.k_src, "cell": cell, "arms": {"A": SERVER, "B": system},
               "ports": dict(PORTS)}
        window.guard_pair(cfg["arms"]["A"], cfg["arms"]["B"], comp.ORDER)
        fp = window.pin_fingerprint()
        sid = f"{cell}-s{n:02d}"
        x = rng.choice(["A", "B"])
        y = "B" if x == "A" else "A"
        session = {"job": a.job, "id": sid, "mhz": fp["mean_mhz"], "fingerprint": fp, "x": x}
        for pos, arm in enumerate([x, y, y, x]):
            r = run_window(cfg, session, arm, pos, blocks, a.out / "raw")
            r.update(provenance=prov, fingerprint=fp, seed=a.seed)
            rows.append(r)
            with open(rows_path, "a") as f:
                f.write(json.dumps(r) + "\n")
            print(f"{sid} p{pos} {arm} {r.get('system')}: {r.get('metric', {}).get('value', 0):.1f} valid={r.get('valid')} "
                  f"{'; '.join(r.get('invalid_reasons', []))}", flush=True)
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["session"], []).append(r)
    summary: dict[str, dict] = {}
    for sid, rs in sorted(by.items()):
        rs.sort(key=lambda r: r["position"])
        c = summary.setdefault(rs[0]["cell"], {"sessions": 0, "ratios": [], "ratios_ignoring_mhz": [], "invalid_windows": []})
        c["sessions"] += 1
        q = session_ratio(rs)
        if q is not None:
            c["ratios"].append(q)
        # Development aid, deciding nothing: the ratio over windows invalid by the MHz rule alone
        # (design/status.md, M4a: kernel 7.2.6's idle frequency floor).
        relaxed = [dict(r, valid=r.get("valid") or (r.get("invalid_reasons") and all("CPU MHz drift" in x for x in r["invalid_reasons"])))
                   for r in rs]
        q2 = session_ratio(relaxed)
        if q2 is not None:
            c["ratios_ignoring_mhz"].append(q2)
        c["invalid_windows"] += [{"tag": r.get("tag"), "reasons": r.get("invalid_reasons")} for r in rs if not r.get("valid")]
    (a.out / "summary.json").write_text(json.dumps({"job": a.job, "cells": summary}, indent=1))
    for cell, c in summary.items():
        print(f"{cell}: sessions {c['sessions']} ratios {[round(x, 4) for x in c['ratios']]} "
              f"ignoring the MHz rule {[round(x, 4) for x in c['ratios_ignoring_mhz']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
