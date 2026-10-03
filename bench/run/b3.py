#!/usr/bin/env python3
"""One window in WL7's layout (hypotheses.md, section 3, WL7; section 7): the ophold window that
K_BASE is made of, and a B3 window of a relay system, a proxy of section 2.3 in its B3
configuration (bench/competitors, Appendix B) or the server's one-port relay with its timers at
60 s (section 1), in front of the stub (M4b-1).

Phases, from WL7 (each a design choice of the frozen text):
  - before t = 0: fresh processes (the holder, or the relay system's front, on CPU 14; a relay
    system's stub on CPUs 10 and 12, section 4.1), the probe (its client closes by reset), a
    baseline reading;
  - opening, t = 0 to at most 10 s: `opcase open` on CPUs 2 to 9 opens N_PEND connections, 25
    every 25 ms, each sending the case's bytes;
  - settling to t = 20 s; reading 1 at t = 20 s, reading 2 at t = 25 s (the value used);
  - closing by t = 30 s: opcase closes every connection by reset.
The first window of a lab job waits until 60 s after the last other window on L ended (section 7);
the runner takes the end of the last window from the source-block file's newest release, and
waits at least 60 s at the job's start when it cannot tell. It then waits until the host holds no
TIME-WAIT socket at all (at most 70 s), so none expires between the baseline and the samples.

K_BASE (WL7) is the median over 16 such windows of ophold's Ks, after the pilot entry (section 9.3).
A development window here proves the readers; it is never K_BASE.

A relay system (M4b-1). U sums VmRSS over the front's process group (nginx's master and worker),
the stub left out (WL7: it holds no pending connection); Kq and the established count read the
front's accepted sockets on its port. The probe is one exchange of the TLS stub's through the
front (the recorded ClientHello, then the stub's 13 bytes), the client closing by reset (WL7);
the stub closes its own side first, so the probe can leave one TIME-WAIT socket on the stub's
connection, which is in the baseline and lasts past sample 2 (60 s). caddy-l4 gets a heap
profile request with gc=1 at its admin endpoint before each reading, the baseline included
(WL7's runtimes with a collector; Appendix B). Functional windows only before the code freeze:
B3's timing runs later (section 8, step 7).

    b3.py --build DIR --out DIR --job NAME [--system ophold|one-port-relay|nginx|...]
          [--case silent|partial-hello] [--n 10000]
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "competitors"))

import competitors as comp  # noqa: E402
import footprint as fp  # noqa: E402
import window  # noqa: E402

SYSTEM_CPUS = [14]  # section 4.1: B3 and hard cases, the system or ophold on CPU 14
OPCASE_CPUS = list(range(2, 10))  # opcase on CPUs 2 to 9
T_SAMPLE1 = 20.0  # WL7
T_SAMPLE2 = 25.0
T_CLOSE = 30.0
GAP_AFTER_OTHER_S = 60.0  # section 7: the first B3 or ophold window of a job, 60 s after any other window
OPHOLD_PORT = 21000  # a design choice of M3, below the ephemeral range
# A design choice of M3: before the baseline the host must hold no TIME-WAIT socket, waited for at
# most 70 s (TCP_TIMEWAIT_LEN, 60 s, and a margin), since section 7 makes a window whose TIME-WAIT
# count moves between the baseline and a sample invalid, and sockets of any earlier activity on L
# (not only windows) expire within 60 s.
TW_WAIT_MAX_S = 70.0
# A relay system (design choices of M4b-1): the front on B3_PORT, off the ephemeral range and apart
# from ophold's and the hand-off windows' ports; its stub STUB_OFFSET above; caddy-l4's admin
# endpoint 50 above (competitors.fields). The collector's request goes COLLECT_LEAD_S before a
# sample, so that the collection it runs has ended when the sample is read.
B3_PORT = 21100
STUB_OFFSET = 10
COLLECT_LEAD_S = 1.0
SERVER = window.ONE_PORT_RELAY
SYSTEMS = ("ophold", SERVER) + comp.ORDER
STUB_BODY = b"Hello, World!"  # the TLS stub's reply (bench/server/apps.hpp, kStubBody)
PROBE_TIMEOUT_S = 5.0
HEAP_TIMEOUT_S = 30.0


def wait_time_wait_zero(max_wait: float = TW_WAIT_MAX_S) -> tuple[float, int]:
    t0 = time.monotonic()
    while True:
        n = window.time_wait_count()
        if n == 0 or time.monotonic() - t0 >= max_wait:
            return time.monotonic() - t0, n
        time.sleep(1.0)


def wait_after_other_windows(blocks_file: Path) -> float:
    """Waits until 60 s after the newest release in the source-block file (the end of the last
    timed window of any job); returns the wait."""
    t0 = time.monotonic()
    try:
        st = json.loads(blocks_file.read_text())
        last = max((r.get("released") or r.get("taken") or 0.0) for r in st.get("recent", [])) if st.get("recent") else 0.0
    except (OSError, json.JSONDecodeError, ValueError):
        last = time.time()
    left = GAP_AFTER_OTHER_S - (time.time() - last)
    if left > 0:
        time.sleep(left)
    return time.monotonic() - t0


def reset_close(s: socket.socket) -> None:
    """Close by reset: SO_LINGER on with a zero timeout (WL7's closing; no TIME-WAIT socket)."""
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()


def exchange_probe(port: int, hello: bytes, timeout: float = PROBE_TIMEOUT_S) -> dict:
    """WL7's probe of a relay system: one TLS stub exchange through the front (the recorded
    ClientHello; the stub's 13 bytes to EOF), the client closing by reset."""
    t0 = time.monotonic()
    got = b""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except OSError as e:
        return {"ok": False, "detail": f"connect: {e!r}", "s": time.monotonic() - t0}
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall(hello)
        while len(got) <= len(STUB_BODY):
            chunk = s.recv(64)
            if not chunk:
                break
            got += chunk
    except OSError as e:
        reset_close(s)
        return {"ok": False, "detail": f"exchange: {e!r}", "got": got.hex(), "s": time.monotonic() - t0}
    reset_close(s)
    ok = got == STUB_BODY
    return {"ok": ok, "detail": "the stub's body, then EOF" if ok else f"got {got!r}", "s": time.monotonic() - t0}


def heap_profile(admin_port: int) -> dict:
    """caddy-l4: a heap profile with gc=1 at the admin endpoint (WL7; Caddy's profiling docs), which
    runs a collection first; the profile is discarded, its size kept."""
    t0 = time.monotonic()
    url = f"http://127.0.0.1:{admin_port}/debug/pprof/heap?gc=1"
    try:
        with urllib.request.urlopen(url, timeout=HEAP_TIMEOUT_S) as r:
            body = r.read()
            return {"status": r.status, "bytes": len(body), "s": time.monotonic() - t0}
    except OSError as e:
        return {"status": None, "error": repr(e), "s": time.monotonic() - t0}


class Holder:
    """ophold on CPU 14 (K_BASE's windows)."""

    def __init__(self, build: Path, port: int, n: int):
        self.port = port
        self.command = [str(build / "bench" / "cases" / "ophold"), "--port", str(port), "--backlog", str(n)]
        self.proc = subprocess.Popen(["taskset", "-c", ",".join(map(str, SYSTEM_CPUS))] + self.command, stdout=subprocess.PIPE,
                                     start_new_session=True)
        self.out = window.Lines(self.proc)
        if not self.out.until(lambda ln: ln.startswith("ophold: listening"), 10.0):
            self.stop()
            raise window.WindowError(f"ophold did not start: {self.out.lines}")

    def pids(self) -> list[int]:
        return [self.proc.pid]

    def probe(self, build: Path) -> dict:
        p = subprocess.run(["taskset", "-c", ",".join(map(str, OPCASE_CPUS)), str(build / "bench" / "cases" / "opcase"), "probe-reset",
                            "--port", str(self.port)], capture_output=True, text=True, timeout=10)
        return {"ok": p.returncode == 0, "exit": p.returncode, "detail": (p.stdout + p.stderr).strip()[-200:]}

    def before_reading(self) -> dict | None:
        return None

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> dict:
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
        lines = self.out.rest(10)
        self.proc.wait(timeout=10)
        return {"exit": self.proc.returncode, "lines": lines[-2:]}


class RelaySystem:
    """A relay system of B3 on CPU 14 in front of the stub on CPUs 10 and 12: a proxy in its B3
    configuration, or the server's one-port relay with every timer at 60 s (section 1)."""

    def __init__(self, build: Path, system: str, port: int, raw: Path, tag: str):
        import handoff  # the hand-off runner's stub and front (section 4.1's placement)
        self.system = system
        self.port = port
        self.stub, self.stub_out = handoff.start_stub(build, port + STUB_OFFSET, raw, tag)
        try:
            self.front = handoff.Front(system, build, port, port + STUB_OFFSET, raw, tag, "b3")
        except Exception:
            window.stop_process(self.stub, self.stub_out)
            raise
        self.command = self.front.command

    def pids(self) -> list[int]:
        return comp.group_pids(self.front.pgid)

    def probe(self, build: Path) -> dict:
        import probe as pr  # bench/competitors/probe.py: the recorded ClientHello
        return exchange_probe(self.port, pr.recorded_client_hello())

    def before_reading(self) -> dict | None:
        return heap_profile(self.port + 50) if self.system == "caddy-l4" else None

    def alive(self) -> bool:
        return self.front.alive()

    def stop(self) -> dict:
        alive = self.front.alive()
        code, front_lines = self.front.stop()
        _, stub_lines = window.stop_process(self.stub, self.stub_out)
        return {"exit": code, "alive_at_stop": alive, "stub_exit": self.stub.returncode,
                "front_counters": window.parse_counters(front_lines) if self.system == SERVER else None,
                "stub_counters": window.parse_counters(stub_lines)}


def run(build: Path, out: Path, job: str, case: str, n: int, blocks_file: Path, system: str = "ophold") -> dict:
    if system not in SYSTEMS:
        raise ValueError(f"system {system!r}, not one of {SYSTEMS}")
    out.mkdir(parents=True, exist_ok=True)
    relay = system != "ophold"
    port = B3_PORT if relay else OPHOLD_PORT
    tag = f"{job}-{system}-{case}"
    row: dict = {"job": job, "kind": "b3" if relay else "ophold", "system": system, "case": case, "n_pend": n, "development": True,
                 "system_cpus": SYSTEM_CPUS, "opcase_cpus": OPCASE_CPUS, "port": port, "tag": tag,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if relay:
        row["stub_port"] = port + STUB_OFFSET
    row["gap_wait_s"] = wait_after_other_windows(blocks_file)
    row["conntrack_wait_s"], _ = window.wait_conntrack()
    row["time_wait_wait_s"], row["time_wait_before"] = wait_time_wait_zero()
    row["fingerprint"] = window.pin_fingerprint()
    ns0 = window.nstat()
    sysm = RelaySystem(build, system, port, out, tag) if relay else Holder(build, port, n)
    row["command"] = sysm.command
    reasons: list[str] = []
    collector: list[dict | None] = []
    lead = COLLECT_LEAD_S if relay and system == "caddy-l4" else 0.0
    try:
        row["probe"] = sysm.probe(build)
        row["probe_exit"] = 0 if row["probe"]["ok"] else 1
        if not row["probe"]["ok"]:
            reasons.append(f"probe failed: {row['probe'].get('detail')}")
        time.sleep(0.5)  # the probe's reset reaches the system before the baseline
        collector.append(sysm.before_reading())
        if lead:
            time.sleep(lead)
        base = fp.read(sysm.pids(), port)
        opener = subprocess.Popen(["taskset", "-c", ",".join(map(str, OPCASE_CPUS)), str(build / "bench" / "cases" / "opcase"), "open",
                                   "--port", str(port), "--case", case, "--n", str(n), "--close-at-ms", str(int(T_CLOSE * 1000))],
                                  stdout=subprocess.PIPE)
        op_out = window.Lines(opener)
        if not op_out.until(lambda ln: ln.startswith("T0 "), 10.0):
            raise window.WindowError("opcase printed no T0")
        t0_ns = int(op_out.lines[-1].split()[1])  # CLOCK_MONOTONIC, the clock of time.monotonic_ns()

        def at(t: float) -> None:
            left = t0_ns / 1e9 + t - time.monotonic_ns() / 1e9
            if left > 0:
                time.sleep(left)

        if lead:
            at(T_SAMPLE1 - lead)
            collector.append(sysm.before_reading())
        at(T_SAMPLE1)
        s1 = fp.read(sysm.pids(), port)
        if lead:
            at(T_SAMPLE2 - lead)
            collector.append(sysm.before_reading())
        at(T_SAMPLE2)
        s2 = fp.read(sysm.pids(), port)
        row["alive_after_samples"] = sysm.alive()
        op_lines = op_out.rest(T_CLOSE + 30)
        opener.wait(timeout=30)
        row["opcase_exit"] = opener.returncode
        row["opcase"] = json.loads(op_lines[-1]) if op_lines and op_lines[-1].startswith("{") else None
        if opener.returncode != 0:
            reasons.append(f"opcase exit {opener.returncode}")
    finally:
        stopped = sysm.stop()
    if relay:
        row["collector"] = collector if system == "caddy-l4" else None
        row["front_stop"] = {k: stopped[k] for k in ("exit", "alive_at_stop", "stub_exit")}
        row["front_counters"] = stopped.get("front_counters")
        row["stub_counters"] = stopped.get("stub_counters")
        if not row.get("alive_after_samples", False):
            reasons.append(f"{system} exited during the window")
        if stopped.get("stub_exit") != 0:
            reasons.append(f"stub exit {stopped.get('stub_exit')}")
        if system == "caddy-l4" and any(c is None or c.get("status") != 200 for c in collector):
            reasons.append("caddy-l4's heap profile request failed")
    else:
        row["ophold_lines"] = stopped.get("lines")
    ns1 = window.nstat()
    row["nstat_delta"] = {k: ns1[k] - ns0[k] for k in window.NSTAT_KEYS}
    if row["nstat_delta"]["TcpExtListenOverflows"] or row["nstat_delta"]["TcpExtListenDrops"]:
        reasons.append("listen overflows or drops during the window")
    row["readings"] = {"baseline": fp.reading_dict(base), "sample1": fp.reading_dict(s1), "sample2": fp.reading_dict(s2)}
    f1, f2 = fp.footprint(base, s1, n), fp.footprint(base, s2, n)
    row["footprint"] = {"sample1": f1.__dict__, "sample2": f2.__dict__}
    reasons += fp.window_problems(base, s1, s2, n)
    row["valid"] = not reasons
    row["invalid_reasons"] = reasons
    return row


def main(argv=None) -> int:
    window.stop_on_signals()  # its finally blocks stop the processes it started
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--system", default="ophold", choices=SYSTEMS)
    ap.add_argument("--case", default="silent", choices=("silent", "partial-hello"))
    ap.add_argument("--n", type=int, default=fp.N_PEND)
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    a = ap.parse_args(argv)
    if a.system in comp.ORDER and not comp.SYSTEMS[a.system].binary_path().exists():
        raise SystemExit(f"{a.system}: no binary at {comp.SYSTEMS[a.system].binary_path()} (bench/competitors/install.sh)")
    row = run(a.build, a.out, a.job, a.case, a.n, a.blocks, a.system)
    with open(a.out / "windows.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    f2 = row["footprint"]["sample2"]
    print(f"{a.system} {a.case}: valid={row['valid']} {'; '.join(row['invalid_reasons'])}")
    print(f"  U {f2['U']:.1f}  Kq {f2['Kq']:.1f}  Ks {f2['Ks']:.1f}  W {f2['W']:.1f} bytes per pending connection; "
          f"established {f2['established']}; skb growth {f2['skb_growth']}; shared cache growth {f2['shared_growth']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
