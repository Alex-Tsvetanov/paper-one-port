#!/usr/bin/env python3
"""Section 10's untimed windows with `perf trace -s` on L (hypotheses.md, section 10: "system calls
per connection for the proxies, from perf trace -s over untimed windows. On L, one untimed window
per cost cell checks the server's system-call counters against perf trace -s"). They time nothing
and are not windows of any cell (the frozen text's Words: "Unit tests and untimed counter checks
are not windows"); each row holds counts, never a rate or a latency.

Two kinds:
  proxy  a front of M3 (a proxy in its M3 configuration, or the server's one-port relay) in front of
         the stub, in section 4.1's hand-off placement (bench/run/handoff.py); perf trace -s on the
         front's process group; the system calls per connection, by name, over the connections the
         stub accepted (every connection the front passed on), with the front's counters checked
         too when the front is the server.
  cost   the server alone in a cost cell's arm (one-port or dedicated mode, in-process dispatch,
         the cell's backend, replay unless --detects names peek too), in section 4.1's in-process
         placement; perf trace -s on its process; each counter of I29 that names a system call is
         compared with perf trace's count. With --repeat N each cell runs its modes N times,
         interleaved, so the run-to-run spread of the counters that depend on timing (the waits, an
         accept or a read that finds nothing) is seen beside one-port's difference from dedicated
         (bench/run/counterdelta.py, M5's criterion 1).

perf trace attaches after the system listens and before the probe, and stops before the system
does, so both count the same connections, except the calls the server makes while it starts (its
listeners' epoll_ctl, the ring's first submissions), which its counters hold and perf cannot see.
An idle pass of the same arm first (start, attach, IDLE_S with no load, stop) measures that
start-up offset per check. A wait in progress when perf attaches or stops can fall on either side,
which WAIT_SLACK allows for the loop's wait calls. Beside perf trace, `perf stat` counts the entry
tracepoints of the same system calls (counters, no ring buffer), so a shortfall of perf trace
itself shows as stat_minus_trace. Section 10's check is read as the comparison with perf stat's
count of the same system calls' entry tracepoints (the coordinator's decision of 2026-10-03,
hypotheses.md revision log): a row's `agrees_with_perf_stat` is section 10's check; `agrees`, the
same check against perf trace -s, is its cross-check, and `trace_shortfall_max_share` reports perf
trace's largest shortfall against perf stat as a share of a call's count. The load (design choices of M4b-1): churn and open loop at
TRACE_RATE exchanges per second for TRACE_MS after a TRACE_WARM_MS warm-up, open loop;
keep-alive with TRACE_KA_CONNS connections for TRACE_KA_MS. perf trace's "LOST" lines are
recorded, and a lost event fails the check.

The server's detection mode (dedicated mode ignores it): replay, the proposed default until rule E
(section 2.1), or peek; --detects for the cost rows, --detect for the server's relay in the proxy
rows.

    systrace.py --build DIR --out DIR --job NAME --kind proxy --systems nginx,...,one-port-relay [--protos tls-stub,http1]
                [--detect replay|peek]
    systrace.py --build DIR --out DIR --job NAME --kind cost --cells churn:http1:epoll,... [--modes dedicated,one-port]
                [--detects replay,peek] [--repeat N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "competitors"))

import competitors as comp  # noqa: E402
import window  # noqa: E402

TRACE_RATE = 2000.0
TRACE_WARM_MS = 500
TRACE_MS = 2000
TRACE_KA_CONNS = 2
TRACE_KA_MS = 500
ATTACH_S = 3.0
IDLE_S = 2.0
WAIT_SLACK = 2  # per worker: a wait in progress at attach and at detach
PERF = ["sudo", "-n", "taskset", "-c", "0,1", "perf"]
# perf trace's ring buffer in pages (its -m); 0 keeps perf's default. SYSTRACE_MMAP_PAGES sets it
# for a run.
TRACE_MMAP_PAGES = int(os.environ.get("SYSTRACE_MMAP_PAGES", "0"))
MODES = ("dedicated", "one-port")
DETECTS = ("replay", "peek")
PROXY_PROTOS = ("tls-stub", "http1")
PORTS = {"cost": 24000, "proxy": 24100}  # design choices of M4b-1, off the ephemeral range; the stub 10 above

# I29's counters that name system calls, and those calls (bench/server, bench/loop): the label,
# the counters summed, the calls summed, whether the loop's wait slack applies, and the backends
# on which the counters are system calls. On io_uring the receives and accepts are ring operations
# (IORING_OP_RECV with provided buffers, the multishot accept), so only the synchronous peek and
# check of 1(b) are recvfrom calls there; the send is synchronous on both (design/status.md, M3).
CHECKS = (
    ("accept", ("accept_calls",), ("accept4", "accept"), False, ("epoll",)),
    ("recv", ("recv_calls", "peek_calls", "check_calls"), ("recvfrom",), False, ("epoll",)),
    ("recv (peek and check)", ("peek_calls", "check_calls"), ("recvfrom",), False, ("io_uring",)),
    ("send", ("send_calls",), ("sendto",), False, ("epoll", "io_uring")),
    ("setsockopt", ("setsockopt_calls",), ("setsockopt",), False, ("epoll", "io_uring")),
    ("epoll_ctl", ("epoll_ctl_calls",), ("epoll_ctl",), False, ("epoll",)),
    ("wait", ("epoll_wait_calls",), ("epoll_pwait2", "epoll_pwait", "epoll_wait"), True, ("epoll",)),
    ("io_uring_enter", ("io_uring_enter_calls",), ("io_uring_enter",), True, ("io_uring",)),
    ("connect", ("connect_calls",), ("connect",), False, ("epoll", "io_uring")),
    ("shutdown", ("shutdown_calls",), ("shutdown",), False, ("epoll", "io_uring")),
    ("splice", ("splice_calls",), ("splice",), False, ("epoll", "io_uring")),
)
STAT_CALLS = tuple(dict.fromkeys(c for check in CHECKS for c in check[2]))

ROW = re.compile(r"^\s+([a-z_][a-z_0-9]*)\s+(\d+)\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+%?\s*$")
LOST = re.compile(r"LOST (\d+) events")


def parse_summary(text: str) -> tuple[dict[str, dict[str, int]], int]:
    """perf trace -s's summary: per system call, its calls and errors summed over every thread
    block; and the events perf reports lost."""
    out: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            d = out.setdefault(m.group(1), {"calls": 0, "errors": 0})
            d["calls"] += int(m.group(2))
            d["errors"] += int(m.group(3))
    lost = sum(int(m.group(1)) for m in LOST.finditer(text))
    return out, lost


def parse_stat(text: str) -> dict[str, int | None]:
    """perf stat -x , on the syscalls:sys_enter_* tracepoints: the count of each call (None where
    perf could not count it)."""
    out: dict[str, int | None] = {}
    for line in text.splitlines():
        p = line.split(",")
        if len(p) >= 3 and p[2].startswith("syscalls:sys_enter_"):
            out[p[2][len("syscalls:sys_enter_"):]] = int(p[0]) if p[0].isdigit() else None
    return out


def check_counters(counters: dict, calls: dict[str, dict[str, int]], backend: str, workers: int,
                   offsets: dict[str, int] | None = None, stat: dict[str, int | None] | None = None) -> list[dict]:
    """Each counter of CHECKS against perf trace's calls, on the backends where they are system
    calls: equal after the start-up offset of the idle pass (calls the counters hold that perf,
    attached later, cannot see), or within WAIT_SLACK per worker for the loop's waits. perf stat's
    count is reported beside each."""
    out = []
    for label, cs, ss, slack, backends in CHECKS:
        if backend not in backends:
            continue
        mine = sum(int(counters.get(c, 0)) for c in cs)
        seen = sum(calls.get(s, {}).get("calls", 0) for s in ss)
        off = (offsets or {}).get(label, 0)
        tol = WAIT_SLACK * workers if slack else 0
        row = {"check": label, "counters": list(cs), "calls": list(ss), "server": mine, "perf": seen, "startup_offset": off,
               "difference": seen - (mine - off), "tolerance": tol, "agrees": abs(seen - (mine - off)) <= tol}
        if stat is not None:
            st = [stat.get(s) for s in ss]
            row["stat"] = None if any(v is None for v in st) else sum(st)
            row["stat_minus_trace"] = None if row["stat"] is None else row["stat"] - seen
            row["stat_agrees"] = row["stat"] is not None and abs(row["stat"] - (mine - off)) <= tol
        out.append(row)
    return out


def startup_offsets(counters: dict, calls: dict[str, dict[str, int]], backend: str) -> dict[str, int]:
    """From an idle pass: per check, the calls the counters hold that perf did not see."""
    return {c["check"]: c["server"] - c["perf"] for c in check_counters(counters, calls, backend, 1)}


class Perf:
    """perf trace -s and perf stat on the same processes, from attach to stop."""

    def __init__(self, pids: list[int], base: Path):
        self.base = base
        target = ["-p", ",".join(map(str, pids))]
        mmap = ["-m", str(TRACE_MMAP_PAGES)] if TRACE_MMAP_PAGES else []
        self.trace = subprocess.Popen(PERF + ["trace", "-s"] + mmap + target + ["-o", str(self.path("trace.txt"))],
                                      stdout=subprocess.DEVNULL, stderr=open(self.path("trace.err"), "wb"))
        events = ",".join(f"syscalls:sys_enter_{c}" for c in STAT_CALLS)
        self.stat = subprocess.Popen(PERF + ["stat", "-x", ",", "-e", events] + target + ["-o", str(self.path("stat.txt"))],
                                     stdout=subprocess.DEVNULL, stderr=open(self.path("stat.err"), "wb"))
        time.sleep(ATTACH_S)
        for name, p in (("trace", self.trace), ("stat", self.stat)):
            if p.poll() is not None:
                self.stop()
                raise window.WindowError(f"perf {name} exited at once: {self.path(name + '.err').read_text(errors='replace')[-300:]}")

    def path(self, suffix: str) -> Path:
        return self.base.parent / f"{self.base.name}.{suffix}"

    def stop(self) -> dict:
        codes = {}
        for name, p in (("trace", self.trace), ("stat", self.stat)):
            subprocess.run(["sudo", "-n", "kill", "-INT", str(p.pid)], check=False)  # sudo passes SIGINT on to perf
            try:
                codes[name] = p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                subprocess.run(["sudo", "-n", "kill", "-KILL", str(p.pid)], check=False)
                codes[name] = p.wait()
        return codes

    def results(self) -> tuple[dict[str, dict[str, int]], int, dict[str, int | None]]:
        calls, lost = parse_summary(self.path("trace.txt").read_text(errors="replace"))
        stat = parse_stat(self.path("stat.txt").read_text(errors="replace"))
        return calls, lost, stat


def load_cmd(build: Path, proto: str, port: int, base: int, k: int, workload: str, gen: tuple[int, ...], out: Path) -> list[str]:
    cmd = ["taskset", "-c", ",".join(map(str, gen))] + window.opgen_cmd(build, proto, port, base, k) + ["--cpus", ",".join(map(str, gen))]
    if workload == "keepalive":
        return cmd + ["--load", "keepalive", "--conns", str(TRACE_KA_CONNS), "--warmup-ms", "0", "--duration-ms", str(TRACE_KA_MS),
                      "--out", str(out)]
    return cmd + ["--conns", str(window.CONNS_PER_CORE), "--rate", repr(TRACE_RATE), "--warmup-ms", str(TRACE_WARM_MS),
                  "--duration-ms", str(TRACE_MS), "--out", str(out)]


def counts_only(g: dict | None) -> dict | None:
    """opgen's report without any time: completed exchanges and errors only."""
    if not g:
        return None
    return {"ok": g.get("ok"), "warmup": (g.get("warmup") or {}).get("completed"), "measure": (g.get("measure") or {}).get("completed"),
            "errors": (g.get("measure") or {}).get("errors"), "connect_failures": g.get("connect_failures")}


def run_load(build: Path, proto: str, port: int, blocks: window.SourceBlocks, workload: str, gen: tuple[int, ...], raw: Path,
             tag: str) -> tuple[dict, dict | None]:
    base = blocks.take(16)
    try:
        probe = window.probe(build, proto, port, base, 16, gen)
        out = raw / f"{tag}.opgen.json"
        p = subprocess.run(load_cmd(build, proto, port, base, 16, workload, gen, out), capture_output=True, text=True, timeout=120)
        g = json.loads(out.read_text()) if out.exists() else None
        return {"probe_exit": probe["exit"], "opgen_exit": p.returncode}, g
    finally:
        blocks.release(base)


def start_server(build: Path, mode: str, backend: str, port: int, raw: Path, tag: str, detect: str = "replay"):
    """The server alone in a cost cell's arm, on the in-process placement's core."""
    if mode not in MODES or detect not in DETECTS:
        raise ValueError(f"{mode} {detect}")
    cmd = [str(build / "bench" / "server" / "oneport"), "--mode", mode, "--detect", detect, "--dispatch", "inproc", "--backend", backend,
           "--port", str(port)]
    proc = subprocess.Popen(["taskset", "-c", ",".join(map(str, window.SERVER_CPUS))] + cmd, stdout=subprocess.PIPE,
                            stderr=open(raw / f"{tag}.server.err", "wb"), start_new_session=True, cwd=raw)
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


def idle_pass(build: Path, mode: str, backend: str, raw: Path, tag: str, detect: str = "replay") -> dict:
    """The arm started, perf attached, IDLE_S without load, perf stopped, the arm stopped: the
    start-up offset of each check."""
    proc, out, _, _ = start_server(build, mode, backend, PORTS["cost"], raw, tag, detect)
    perf = None
    try:
        perf = Perf([proc.pid], raw / tag)
        time.sleep(IDLE_S)
    finally:
        if perf is not None:
            perf.stop()
        _, lines = window.stop_process(proc, out)
    calls, _, _ = perf.results()
    counters = window.parse_counters(lines)
    return {"offsets": startup_offsets(counters, calls, backend), "server_counters": counters, "perf_calls": calls}


def trace_shortfall(checks: list[dict]) -> float | None:
    """perf trace -s's largest shortfall against perf stat over a row's checks, as a share of perf
    stat's count; None where no check has both."""
    shares = [c["stat_minus_trace"] / c["stat"] for c in checks if c.get("stat") and c.get("stat_minus_trace") is not None]
    return max(shares) if shares else None


def finish_checks(row: dict, g: dict | None, extra: list[str]) -> dict:
    """`agrees_with_perf_stat`: section 10's check, the counters against perf stat's count of the
    entry tracepoints (the coordinator's reading of 2026-10-03). `agrees`: the cross-check, the same
    counters against perf trace -s (found in M4b-1: on L perf trace -s fell short of perf stat by up
    to 0.42% of a call's count with no lost event reported, also with a larger ring buffer, while
    perf stat matched the counters exactly); `trace_shortfall_max_share`: that shortfall's largest
    share over the row's checks, (stat - trace) / stat."""
    reasons = [f"{c['check']}: perf {c['perf']}, counters {c['server']} less {c['startup_offset']} at start-up"
               for c in row.get("checks", []) if not c["agrees"]] + extra
    if row.get("perf_lost"):
        reasons.append(f"perf trace lost {row['perf_lost']} events")
    if not (g or {}).get("ok"):
        reasons.append("opgen failed")
    row["agrees"] = not reasons
    row["agrees_with_perf_stat"] = all(c.get("stat_agrees") for c in row.get("checks", [])) if row.get("checks") else None
    row["trace_shortfall_max_share"] = trace_shortfall(row.get("checks", []))
    row["problems"] = reasons
    return row


def cost_row(build: Path, cell: dict, mode: str, blocks: window.SourceBlocks, raw: Path, job: str, detect: str = "replay",
             repeat: int = 0) -> dict:
    tag = f"{job}-{cell['workload']}.{cell['proto']}.{cell['backend']}-{detect}-{mode}" + (f"-r{repeat}" if repeat else "")
    row: dict = {"job": job, "kind": "cost", "untimed": True, "development": True, "cell": f"{cell['workload']}.{cell['proto']}.{cell['backend']}",
                 "mode": mode, "detect": detect, "repeat": repeat, "tag": tag, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    row["conntrack_wait_s"], _ = window.wait_conntrack()
    row["idle"] = idle_pass(build, mode, cell["backend"], raw, tag + ".idle", detect)
    proc, out, ports, cmd = start_server(build, mode, cell["backend"], PORTS["cost"], raw, tag, detect)
    row["command"] = cmd
    target = PORTS["cost"] if mode == "one-port" else ports.get(window.LISTENER[cell["proto"]])
    perf = None
    g = None
    try:
        if target is None:
            raise window.WindowError(f"no {window.LISTENER[cell['proto']]} listener in {sorted(ports)}")
        perf = Perf([proc.pid], raw / tag)
        row["load"], g = run_load(build, cell["proto"], target, blocks, cell["workload"], tuple(window.OPEN_GEN_THREADS) if
                                  cell["workload"] != "keepalive" else tuple(window.GEN_CPUS[:2]), raw, tag)
        time.sleep(0.5)
    finally:
        row["perf_exit"] = perf.stop() if perf is not None else None
        code, lines = window.stop_process(proc, out)
        row["server_exit"] = code
    counters = window.parse_counters(lines)
    calls, lost, stat = perf.results()
    row["opgen"] = counts_only(g)
    row["server_counters"] = counters
    row["perf_calls"] = calls
    row["perf_lost"] = lost
    row["perf_stat"] = stat
    row["checks"] = check_counters(counters, calls, cell["backend"], 1, row["idle"]["offsets"], stat)
    acc = counters.get("accepted", 0)
    row["calls_per_connection"] = {k: v["calls"] / acc for k, v in calls.items()} if acc else None
    return finish_checks(row, g, [f"server exit {row['server_exit']}"] if row["server_exit"] != 0 else [])


def relay_idle_pass(build: Path, port: int, raw: Path, tag: str, detect: str = "replay", backend: str = "epoll") -> dict:
    """The server's relay and its stub started, perf on the front for IDLE_S without load: the
    front's start-up offsets."""
    import handoff
    stub, stub_out = handoff.start_stub(build, port + 10, raw, tag)
    front = perf = None
    lines: list[str] = []
    try:
        front = handoff.Front(window.ONE_PORT_RELAY, build, port, port + 10, raw, tag, "m3", backend, detect)
        perf = Perf(comp.group_pids(front.pgid), raw / tag)
        time.sleep(IDLE_S)
    finally:
        if perf is not None:
            perf.stop()
        if front is not None:
            _, lines = front.stop()
        window.stop_process(stub, stub_out)
    calls, _, _ = perf.results()
    counters = window.parse_counters(lines)
    return {"offsets": startup_offsets(counters, calls, backend), "server_counters": counters, "perf_calls": calls}


def proxy_row(build: Path, system: str, proto: str, blocks: window.SourceBlocks, raw: Path, job: str,
              detect: str = "replay", backend: str = "epoll") -> dict:
    import handoff
    relay = system == window.ONE_PORT_RELAY
    backend = backend if relay else "epoll"  # the server's relay on either backend (section 10); the proxies as they run
    tag = f"{job}-{system}-{proto}" + (f"-{detect}" if relay and detect != "replay" else "") + (f"-{backend}" if relay and backend != "epoll" else "")
    port = PORTS["proxy"]
    row: dict = {"job": job, "kind": "proxy", "untimed": True, "development": True, "system": system, "proto": proto, "tag": tag,
                 "detect": detect if relay else None, "backend": backend if relay else None,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    row["conntrack_wait_s"], _ = window.wait_conntrack()
    if relay:
        row["idle"] = relay_idle_pass(build, port, raw, tag + ".idle", detect, backend)
    stub, stub_out = handoff.start_stub(build, port + 10, raw, tag)
    front = perf = g = None
    front_lines: list[str] = []
    try:
        front = handoff.Front(system, build, port, port + 10, raw, tag, "m3", backend, detect)
        row["command"] = front.command
        pids = comp.group_pids(front.pgid)
        row["front_pids"] = pids
        perf = Perf(pids, raw / tag)
        row["load"], g = run_load(build, proto, port, blocks, "churn", handoff.PL.open_gen_threads, raw, tag)
        time.sleep(0.5)
    finally:
        row["perf_exit"] = perf.stop() if perf is not None else None
        if front is not None:
            row["front_exit"], front_lines = front.stop()
        _, stub_lines = window.stop_process(stub, stub_out)
    calls, lost, stat = perf.results()
    stub_counters = window.parse_counters(stub_lines)
    row["opgen"] = counts_only(g)
    row["perf_calls"] = calls
    row["perf_lost"] = lost
    row["perf_stat"] = stat
    row["stub_accepted"] = acc = stub_counters.get("accepted", 0)
    row["calls_per_connection"] = {k: v["calls"] / acc for k, v in calls.items()} if acc else None
    if system == window.ONE_PORT_RELAY:
        counters = window.parse_counters(front_lines)
        row["server_counters"] = counters
        row["checks"] = check_counters(counters, calls, backend, 1, row["idle"]["offsets"], stat)
    return finish_checks(row, g, [] if acc else ["the stub accepted no connection"])


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--kind", required=True, choices=("cost", "proxy"))
    ap.add_argument("--cells", default="", help="cost: workload:proto:backend,...")
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--detects", default="replay", help="cost: the server's detection modes, replay and/or peek")
    ap.add_argument("--repeat", type=int, default=1, help="cost: each cell's modes this many times, interleaved")
    ap.add_argument("--detect", default="replay", choices=DETECTS, help="proxy: the server's relay's detection mode")
    ap.add_argument("--backend", default="epoll", choices=("epoll", "io_uring"), help="proxy: the server's relay's backend")
    ap.add_argument("--systems", default=",".join(comp.ORDER + (window.ONE_PORT_RELAY,)))
    ap.add_argument("--protos", default=",".join(PROXY_PROTOS))
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    a = ap.parse_args(argv)
    raw = a.out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    blocks = window.SourceBlocks(a.blocks)
    rows: list[dict] = []
    if a.kind == "cost":
        modes = [m for m in a.modes.split(",") if m]
        detects = [d for d in a.detects.split(",") if d]
        if not detects or not set(detects) <= set(DETECTS):
            raise SystemExit(f"--detects {a.detects!r}: replay and/or peek")
        for spec in [c for c in a.cells.split(",") if c]:
            workload, proto, backend = spec.split(":")
            for detect in detects:
                for rep in range(1, a.repeat + 1):
                    for mode in modes:
                        rows.append(cost_row(a.build, {"workload": workload, "proto": proto, "backend": backend}, mode, blocks, raw,
                                             a.job, detect, rep if a.repeat > 1 else 0))
    else:
        for system in [s for s in a.systems.split(",") if s]:
            for proto in [p for p in a.protos.split(",") if p]:
                rows.append(proxy_row(a.build, system, proto, blocks, raw, a.job, a.detect, a.backend))
    fp = window.pin_fingerprint()
    with open(a.out / "trace.jsonl", "a") as f:
        for r in rows:
            r["fingerprint"] = fp
            f.write(json.dumps(r) + "\n")
    for r in rows:
        name = r.get("cell", r.get("system"))
        lost = {c["check"]: c["stat_minus_trace"] for c in r.get("checks", []) if c.get("stat_minus_trace")}
        print(f"{r['kind']} {name} {r.get('mode', r.get('proto'))} {r.get('detect') or ''}: agrees={r['agrees']} "
              f"agrees_with_perf_stat={r['agrees_with_perf_stat']} {'; '.join(r['problems'])}"
              + (f" [perf stat minus perf trace: {lost}]" if lost else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
