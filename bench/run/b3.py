#!/usr/bin/env python3
"""One window in WL7's layout (hypotheses.md, section 3, WL7; section 7): the ophold window that
K_BASE is made of, a B3 window of a relay system, a proxy of section 2.3 in its B3 configuration
(bench/competitors, Appendix B) or the server's one-port relay with its timers at 60 s (section 1),
in front of the stub (M4b-1), and a B3 window of an in-process system (M4b-2), a library's harness
in its B3 configuration or the server in one-port mode with in-process dispatch and its timers at
60 s (section 5.2: "in-process against the libraries"), with no stub.

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
the stub closes its own side first, so the probe can leave a TIME-WAIT socket on the stub's
connection; the baseline waits until the host's TIME-WAIT count has held for 2 s, so that socket
is in the baseline and lasts past sample 2 (60 s). caddy-l4 gets a heap profile request with
gc=1 at its admin endpoint a second before each reading, the baseline included (WL7's runtimes
with a collector; Appendix B), on a connection closed by reset. The TIME-WAIT rule of section 7
counts the whole host's sockets, so nothing else may open TCP connections on L during a window
(an ssh session to L included). Functional windows only before the code freeze:
B3's timing runs later (section 8, step 7).

An in-process system (M4b-2). U sums VmRSS over its process group; Kq and the established count
read its accepted sockets on its port. The probe is one exchange of each protocol it serves among
B3's (HTTP/1.1 with keep-alive; and a TLS 1.3 handshake then HTTP/1.1, where it terminates TLS),
each client closing by reset (WL7). The collector steps of WL7, a second ahead of each reading
(COLLECT_LEAD_S), the baseline included: the JVM harnesses get `jcmd <pid> GC.run` then
`jcmd <pid> GC.heap_info` (the pinned JDK's jcmd, on CPUs 0 and 1, through the attach mechanism's
Unix socket, so no TCP connection); the cmux harness gets SIGUSR1, on which it calls
debug.FreeOSMemory and prints HeapInuse. The harnesses come from <build>/harness
(bench/competitors/build_harnesses.sh).

    b3.py --build DIR --out DIR --job NAME [--system ophold|one-port-relay|one-port-inproc|nginx|...|netty|...]
          [--case silent|partial-hello] [--n 10000] [--backend epoll|io_uring]
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
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
# endpoint 50 above (competitors.fields). The collector's step goes COLLECT_LEAD_S before a
# sample, so that the collection it runs has ended when the sample is read; the JVM's two jcmd
# calls start a JVM each, so they get 3 s (design choices of M4b-2).
B3_PORT = 21100
STUB_OFFSET = 10
COLLECT_LEAD_S = {"caddy-l4": 1.0, "netty": 3.0, "jetty": 3.0, "cmux": 1.0}
JCMD_TIMEOUT_S = 60.0
GO_COLLECT_TIMEOUT_S = 10.0
SERVER = window.ONE_PORT_RELAY
# The server's in-process arm of B3 against the libraries (section 5.2).
SERVER_INPROC = "one-port-inproc"
RELAY_SYSTEMS = (SERVER,) + comp.ORDER
INPROC_SYSTEMS = (SERVER_INPROC,) + comp.LIBRARIES
SYSTEMS = ("ophold",) + RELAY_SYSTEMS + INPROC_SYSTEMS
# Section 6.2: hyper-util serves no TLS, so the probe of an in-process system checks TLS only where
# the system terminates it.
INPROC_PROBES = {SERVER_INPROC: ("http1", "tls"), "netty": ("http1", "tls"), "jetty": ("http1", "tls"),
                 "cmux": ("http1", "tls"), "hyper-util": ("http1",)}
REQUEST = b"GET / HTTP/1.1\r\nHost: oneport.test\r\n\r\n"
STUB_BODY = b"Hello, World!"  # the TLS stub's reply (bench/server/apps.hpp, kStubBody)
PROBE_TIMEOUT_S = 5.0
HEAP_TIMEOUT_S = 30.0
# Design choices of M4b-1: after the probe the baseline waits until the TIME-WAIT count has held
# for TW_STEADY_S, at most TW_STEADY_MAX_S.
TW_STEADY_S = 2.0
TW_STEADY_MAX_S = 10.0
# A design choice of M4b-2: the memory sampler's period, M4b-1's diagnostic's.
SAMPLER_S = 1.0


def group_memory_kb(pids: list[int]) -> dict[str, int]:
    """The summed VmRSS (/proc/<pid>/status) and AnonHugePages (/proc/<pid>/smaps_rollup) of a
    system's processes, in kB; a process that is gone is skipped."""
    rss = huge = 0
    for pid in pids:
        try:
            rss += fp.parse_kb_field(Path(f"/proc/{pid}/status").read_text(), "VmRSS")
            huge += fp.parse_kb_field(Path(f"/proc/{pid}/smaps_rollup").read_text(), "AnonHugePages")
        except (OSError, KeyError, ValueError):
            continue
    return {"rss_kb": rss, "anon_huge_kb": huge}


def thp_counters(text: str | None = None) -> dict[str, int]:
    """The host's huge page counters of /proc/vmstat that move when a huge page is made: at a page
    fault (thp_fault_alloc) and by khugepaged's collapse (thp_collapse_alloc)."""
    text = Path("/proc/vmstat").read_text() if text is None else text
    out = {}
    for line in text.splitlines():
        p = line.split()
        if len(p) == 2 and p[0] in ("thp_fault_alloc", "thp_collapse_alloc"):
            out[p[0]] = int(p[1])
    return out


class MemorySampler:
    """Every SAMPLER_S seconds, the system's summed VmRSS and AnonHugePages and the host's THP
    counters, from start() to stop(): recorded beside the window, deciding nothing (M4b-2: the
    check that transparent huge pages at madvise leave an idle front's memory flat, after M4b-1's
    diagnostic b3sample.py)."""

    def __init__(self, pids, t0: float):
        import threading
        self.pids = pids  # a callable: the system's processes now
        self.t0 = t0
        self.rows: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            row = {"t": round(time.monotonic() - self.t0, 2)}
            try:
                row.update(group_memory_kb(self.pids()))
                row.update(thp_counters())
            except OSError as e:
                row["error"] = repr(e)
            self.rows.append(row)
            self._stop.wait(SAMPLER_S)

    def start(self) -> "MemorySampler":
        self._thread.start()
        return self

    def stop(self) -> list[dict]:
        self._stop.set()
        self._thread.join(timeout=5)
        return self.rows


def sampler_summary(rows: list[dict]) -> dict:
    """The sampler's rows in brief: VmRSS and AnonHugePages at the first and last row, their
    largest one-step rise, and the host's collapses over the rows."""
    if not rows or "rss_kb" not in rows[0]:
        return {}
    ok = [r for r in rows if "rss_kb" in r]
    steps = [b["rss_kb"] - a["rss_kb"] for a, b in zip(ok, ok[1:])]
    out = {"rows": len(ok), "rss_kb_first": ok[0]["rss_kb"], "rss_kb_last": ok[-1]["rss_kb"],
           "anon_huge_kb_first": ok[0]["anon_huge_kb"], "anon_huge_kb_last": ok[-1]["anon_huge_kb"],
           "anon_huge_kb_max": max(r["anon_huge_kb"] for r in ok), "largest_rss_step_kb": max(steps) if steps else 0}
    if "thp_collapse_alloc" in ok[0] and "thp_collapse_alloc" in ok[-1]:
        out["thp_collapse_alloc_delta"] = ok[-1]["thp_collapse_alloc"] - ok[0]["thp_collapse_alloc"]
        out["thp_fault_alloc_delta"] = ok[-1]["thp_fault_alloc"] - ok[0]["thp_fault_alloc"]
    return out


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


def collector_ok(c: dict) -> bool:
    """A collector step that worked: caddy-l4's heap profile answered 200; jcmd's and the cmux
    harness's steps say ok."""
    return c.get("status") == 200 if "status" in c else bool(c.get("ok"))


def heap_profile(admin_port: int) -> dict:
    """caddy-l4: a heap profile with gc=1 at the admin endpoint (WL7; Caddy's profiling docs), which
    runs a collection first; the profile is discarded, its size kept. The request keeps its
    connection open (HTTP/1.1) and the client closes it by reset once the whole response is read,
    so neither end is left in TIME-WAIT, which section 7's rule would count (found in M4b-1: a
    request that closed normally added one TIME-WAIT socket per sample)."""
    t0 = time.monotonic()
    conn = http.client.HTTPConnection("127.0.0.1", admin_port, timeout=HEAP_TIMEOUT_S)
    try:
        conn.request("GET", "/debug/pprof/heap?gc=1")
        r = conn.getresponse()
        body = r.read()
        out = {"status": r.status, "bytes": len(body), "s": time.monotonic() - t0}
    except (OSError, http.client.HTTPException) as e:
        out = {"status": None, "error": repr(e), "s": time.monotonic() - t0}
    if conn.sock is not None:
        reset_close(conn.sock)
        conn.sock = None
    conn.close()
    return out


def wait_time_wait_steady(steady_s: float = TW_STEADY_S, max_wait: float = TW_STEADY_MAX_S) -> tuple[float, int]:
    """After the probe: waits until the host's TIME-WAIT count has not changed for steady_s, at most
    max_wait, so that a connection of the probe that a system closes late (found in M4b-1: one of
    HAProxy's, after the baseline) is counted in the baseline, not at a sample."""
    t0 = time.monotonic()
    last = window.time_wait_count()
    since = time.monotonic()
    while time.monotonic() - t0 < max_wait:
        time.sleep(0.25)
        n = window.time_wait_count()
        if n != last:
            last, since = n, time.monotonic()
        elif time.monotonic() - since >= steady_s:
            break
    return time.monotonic() - t0, last


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

    def __init__(self, build: Path, system: str, port: int, raw: Path, tag: str, backend: str = "epoll"):
        import handoff  # the hand-off runner's stub and front (section 4.1's placement)
        self.system = system
        self.port = port
        self.stub, self.stub_out = handoff.start_stub(build, port + STUB_OFFSET, raw, tag)
        try:
            self.front = handoff.Front(system, build, port, port + STUB_OFFSET, raw, tag, "b3", backend)
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


def read_http_response(read) -> bytes:
    """Reads one HTTP/1.1 response by its Content-Length through `read` (a recv-like callable)."""
    got = b""
    while b"\r\n\r\n" not in got:
        chunk = read(4096)
        if not chunk:
            return got
        got += chunk
        if len(got) > 16384:
            return got
    head, _, body = got.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n")[1:]:
        k, _, v = line.partition(b":")
        if k.strip().lower() == b"content-length":
            length = int(v.strip() or b"0")
    while len(body) < length:
        chunk = read(4096)
        if not chunk:
            break
        body += chunk
    return head + b"\r\n\r\n" + body


def response_ok(resp: bytes) -> bool:
    """The server's reply (section 2.1): 200 with the 13-byte body."""
    head, _, body = resp.partition(b"\r\n\r\n")
    return head.startswith(b"HTTP/1.1 200") and body == STUB_BODY


def http1_probe(port: int, timeout: float = PROBE_TIMEOUT_S) -> dict:
    """One HTTP/1.1 exchange with keep-alive, the client closing by reset (WL7)."""
    t0 = time.monotonic()
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except OSError as e:
        return {"proto": "http1", "ok": False, "detail": f"connect: {e!r}", "s": time.monotonic() - t0}
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall(REQUEST)
        resp = read_http_response(s.recv)
    except OSError as e:
        reset_close(s)
        return {"proto": "http1", "ok": False, "detail": f"exchange: {e!r}", "s": time.monotonic() - t0}
    reset_close(s)
    ok = response_ok(resp)
    return {"proto": "http1", "ok": ok, "detail": "200 with the 13-byte body" if ok else f"got {resp[:80]!r}",
            "s": time.monotonic() - t0}


def tls_probe(port: int, cert: Path, timeout: float = PROBE_TIMEOUT_S) -> dict:
    """A TLS 1.3 handshake with SNI oneport.test, the test certificate verified, ALPN http/1.1 and
    the group X25519 (section 2.1's settings, as far as Python's ssl module sets them), then one
    HTTP/1.1 exchange; the client closes by reset without close_notify (WL7)."""
    import ssl
    t0 = time.monotonic()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_verify_locations(cafile=str(cert))
    ctx.set_alpn_protocols(["http/1.1"])
    ctx.set_ecdh_curve("X25519")
    try:
        raw = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except OSError as e:
        return {"proto": "tls", "ok": False, "detail": f"connect: {e!r}", "s": time.monotonic() - t0}
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    # wrap_socket takes over the descriptor (raw is closed by it), so the reset goes through the
    # TLS socket, whose close() ends the descriptor without close_notify (found in M4b-2's job b3lib1).
    conn = raw
    try:
        conn = ctx.wrap_socket(raw, server_hostname="oneport.test")
        conn.sendall(REQUEST)
        resp = read_http_response(conn.recv)
        info = {"version": conn.version(), "cipher": (conn.cipher() or ("",))[0], "alpn": conn.selected_alpn_protocol()}
    except (OSError, ssl.SSLError) as e:
        if conn.fileno() >= 0:
            reset_close(conn)
        return {"proto": "tls", "ok": False, "detail": f"exchange: {e!r}", "s": time.monotonic() - t0}
    reset_close(conn)
    ok = response_ok(resp)
    return {"proto": "tls", "ok": ok, "detail": ("200 with the 13-byte body" if ok else f"got {resp[:80]!r}"), "tls": info,
            "s": time.monotonic() - t0}


def jvm_collect(pid: int, jcmd: Path, timeout: float = JCMD_TIMEOUT_S) -> dict:
    """WL7's step for the JVM systems: `jcmd <pid> GC.run`, then `GC.heap_info`, reported."""
    t0 = time.monotonic()
    out: dict = {"ok": False}
    try:
        run_ = subprocess.run(["taskset", "-c", "0,1", str(jcmd), str(pid), "GC.run"], capture_output=True, text=True, timeout=timeout)
        info = subprocess.run(["taskset", "-c", "0,1", str(jcmd), str(pid), "GC.heap_info"], capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        out["error"] = repr(e)
        out["s"] = time.monotonic() - t0
        return out
    out.update(ok=run_.returncode == 0 and info.returncode == 0, gc_run_exit=run_.returncode, heap_info_exit=info.returncode,
               heap_info=info.stdout.strip()[-2000:], s=time.monotonic() - t0)
    return out


def go_collect(pid: int, stdout_log: Path, timeout: float = GO_COLLECT_TIMEOUT_S) -> dict:
    """WL7's step for the cmux harness: SIGUSR1, on which it calls debug.FreeOSMemory and prints
    one line with HeapInuse to its standard output (bench/competitors/cmux/main.go)."""
    t0 = time.monotonic()
    before = stdout_log.read_text(errors="replace").count("cmux: collector ")
    os.kill(pid, signal.SIGUSR1)
    while time.monotonic() - t0 < timeout:
        lines = [ln for ln in stdout_log.read_text(errors="replace").splitlines() if ln.startswith("cmux: collector ")]
        if len(lines) > before:
            stats = json.loads(lines[-1][len("cmux: collector "):])
            return {"ok": True, "stats": stats, "heap_inuse": stats.get("heap_inuse"), "s": time.monotonic() - t0}
        time.sleep(0.02)
    return {"ok": False, "error": "no collector line", "s": time.monotonic() - t0}


class InProcessSystem:
    """An in-process system of B3 on CPU 14 (section 5.2; M4b-2): a library's harness in its B3
    configuration, or the server in one-port mode with in-process dispatch, its default detection
    mode (replay) and every timer at 60 s (section 1). No stub."""

    def __init__(self, build: Path, system: str, port: int, raw: Path, tag: str, backend: str = "epoll"):
        self.system = system
        self.port = port
        self.build = build
        self.running = None
        self.out = None
        if system == SERVER_INPROC:
            cmd = [str(build / "bench" / "server" / "oneport"), "--mode", "one-port", "--detect", "replay", "--dispatch", "inproc",
                   "--backend", backend, "--port", str(port), "--t-fb-ms", "60000", "--t-dec-ms", "60000", "--t-hdr-ms", "60000"]
            self.proc = subprocess.Popen(["taskset", "-c", ",".join(map(str, SYSTEM_CPUS))] + cmd, stdout=subprocess.PIPE,
                                         stderr=open(raw / f"{tag}.server.err", "wb"), start_new_session=True, cwd=raw,
                                         preexec_fn=comp.raise_nofile)
            (raw / f"{tag}.server.pid").write_text(f"{self.proc.pid}\n")
            self.out = window.Lines(self.proc)
            if not self.out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
                window.stop_process(self.proc, self.out)
                raise window.WindowError(f"the server did not start: {self.out.lines[-3:]}")
            self.command = cmd
        else:
            self.running = comp.start(system, "b3", port, 0, SYSTEM_CPUS, raw / f"{tag}.front", harness=comp.harness_dir(build))
            self.proc = self.running.proc
            self.command = self.running.command

    def pids(self) -> list[int]:
        return comp.group_pids(self.proc.pid)

    def probe(self, build: Path) -> dict:
        cert = HERE.parent.parent / "tests" / "fixtures" / "tls" / "test-cert.pem"
        results = [http1_probe(self.port) if p == "http1" else tls_probe(self.port, cert) for p in INPROC_PROBES[self.system]]
        ok = all(r["ok"] for r in results)
        return {"ok": ok, "detail": "; ".join(f"{r['proto']}: {r['detail']}" for r in results), "exchanges": results}

    def before_reading(self) -> dict | None:
        if self.system in comp.JVM_SYSTEMS:
            jcmd = comp.OPT / f"jdk-{comp.pin('ONEPORT_JDK_VERSION')}" / "bin" / "jcmd"
            return jvm_collect(self.proc.pid, jcmd)
        if self.system == "cmux":
            return go_collect(self.proc.pid, self.running.run_dir / "stdout.log")
        return None

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> dict:
        alive = self.alive()
        if self.running is not None:
            code = comp.stop(self.running)
            return {"exit": code, "alive_at_stop": alive, "server_counters": None}
        code, lines = window.stop_process(self.proc, self.out)
        return {"exit": code, "alive_at_stop": alive, "server_counters": window.parse_counters(lines)}


def run(build: Path, out: Path, job: str, case: str, n: int, blocks_file: Path, system: str = "ophold",
        backend: str = "epoll") -> dict:
    if system not in SYSTEMS:
        raise ValueError(f"system {system!r}, not one of {SYSTEMS}")
    out.mkdir(parents=True, exist_ok=True)
    relay = system in RELAY_SYSTEMS
    inproc = system in INPROC_SYSTEMS
    port = B3_PORT if system != "ophold" else OPHOLD_PORT
    server_arm = system in (SERVER, SERVER_INPROC)
    tag = f"{job}-{system}-{case}" + (f"-{backend}" if server_arm else "")
    row: dict = {"job": job, "kind": "b3" if system != "ophold" else "ophold", "system": system, "case": case, "n_pend": n,
                 "development": True, "placement": "relay" if relay else "in-process" if inproc else "holder",
                 "system_cpus": SYSTEM_CPUS, "opcase_cpus": OPCASE_CPUS, "port": port, "tag": tag,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if server_arm:
        row["backend"] = backend
    if relay:
        row["stub_port"] = port + STUB_OFFSET
    row["gap_wait_s"] = wait_after_other_windows(blocks_file)
    row["conntrack_wait_s"], _ = window.wait_conntrack()
    row["time_wait_wait_s"], row["time_wait_before"] = wait_time_wait_zero()
    row["fingerprint"] = window.pin_fingerprint()
    ns0 = window.nstat()
    if relay:
        sysm = RelaySystem(build, system, port, out, tag, backend)
    elif inproc:
        sysm = InProcessSystem(build, system, port, out, tag, backend)
    else:
        sysm = Holder(build, port, n)
    row["command"] = sysm.command
    reasons: list[str] = []
    collector: list[dict | None] = []
    lead = COLLECT_LEAD_S.get(system, 0.0)
    sampler: MemorySampler | None = None
    try:
        row["probe"] = sysm.probe(build)
        row["probe_exit"] = 0 if row["probe"]["ok"] else 1
        if not row["probe"]["ok"]:
            reasons.append(f"probe failed: {row['probe'].get('detail')}")
        time.sleep(0.5)  # the probe's reset reaches the system before the baseline
        row["time_wait_steady_wait_s"], row["time_wait_after_probe"] = wait_time_wait_steady()
        collector.append(sysm.before_reading())
        if lead:
            time.sleep(lead)
        sampler = MemorySampler(sysm.pids, time.monotonic()).start()
        thp = {"baseline": thp_counters()}
        base = fp.read(sysm.pids(), port)
        opener = subprocess.Popen(["taskset", "-c", ",".join(map(str, OPCASE_CPUS)), str(build / "bench" / "cases" / "opcase"), "open",
                                   "--port", str(port), "--case", case, "--n", str(n), "--close-at-ms", str(int(T_CLOSE * 1000))],
                                  stdout=subprocess.PIPE)
        op_out = window.Lines(opener)
        if not op_out.until(lambda ln: ln.startswith("T0 "), 10.0):
            raise window.WindowError("opcase printed no T0")
        t0_ns = int(op_out.lines[-1].split()[1])  # CLOCK_MONOTONIC, the clock of time.monotonic_ns()
        row["sampler_open_at_s"] = round(t0_ns / 1e9 - sampler.t0, 2)  # opcase's t = 0 on the sampler's clock

        def at(t: float) -> None:
            left = t0_ns / 1e9 + t - time.monotonic_ns() / 1e9
            if left > 0:
                time.sleep(left)

        if lead:
            at(T_SAMPLE1 - lead)
            collector.append(sysm.before_reading())
        at(T_SAMPLE1)
        s1 = fp.read(sysm.pids(), port)
        thp["sample1"] = thp_counters()
        if lead:
            at(T_SAMPLE2 - lead)
            collector.append(sysm.before_reading())
        at(T_SAMPLE2)
        s2 = fp.read(sysm.pids(), port)
        thp["sample2"] = thp_counters()
        row["memory_sampler"] = sampler.stop()
        row["memory_sampler_summary"] = sampler_summary(row["memory_sampler"])
        row["thp_counters"] = thp
        row["alive_after_samples"] = sysm.alive()
        op_lines = op_out.rest(T_CLOSE + 30)
        opener.wait(timeout=30)
        row["opcase_exit"] = opener.returncode
        row["opcase"] = json.loads(op_lines[-1]) if op_lines and op_lines[-1].startswith("{") else None
        if opener.returncode != 0:
            reasons.append(f"opcase exit {opener.returncode}")
    finally:
        if sampler is not None and "memory_sampler" not in row:
            row["memory_sampler"] = sampler.stop()
        stopped = sysm.stop()
    if lead:
        row["collector"] = collector
        if any(c is None or not collector_ok(c) for c in collector):
            reasons.append(f"{system}'s collector step failed")
    if relay:
        row["front_stop"] = {k: stopped[k] for k in ("exit", "alive_at_stop", "stub_exit")}
        row["front_counters"] = stopped.get("front_counters")
        row["stub_counters"] = stopped.get("stub_counters")
        if not row.get("alive_after_samples", False):
            reasons.append(f"{system} exited during the window")
        if stopped.get("stub_exit") != 0:
            reasons.append(f"stub exit {stopped.get('stub_exit')}")
    elif inproc:
        row["system_stop"] = {k: stopped[k] for k in ("exit", "alive_at_stop")}
        row["server_counters"] = stopped.get("server_counters")
        if not row.get("alive_after_samples", False):
            reasons.append(f"{system} exited during the window")
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
    ap.add_argument("--backend", default="epoll", choices=("epoll", "io_uring"), help="the server's backend (its two arms)")
    a = ap.parse_args(argv)
    if a.system in comp.ORDER and not comp.SYSTEMS[a.system].binary_path().exists():
        raise SystemExit(f"{a.system}: no binary at {comp.SYSTEMS[a.system].binary_path()} (bench/competitors/install.sh)")
    if a.system in comp.LIBRARIES and not comp.SYSTEMS[a.system].binary_path(comp.harness_dir(a.build)).exists():
        raise SystemExit(f"{a.system}: no harness at {comp.SYSTEMS[a.system].binary_path(comp.harness_dir(a.build))} "
                         "(bench/competitors/build_harnesses.sh)")
    row = run(a.build, a.out, a.job, a.case, a.n, a.blocks, a.system, a.backend)
    with open(a.out / "windows.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    f2 = row["footprint"]["sample2"]
    print(f"{a.system} {a.case}{' ' + a.backend if 'backend' in row else ''}: valid={row['valid']} {'; '.join(row['invalid_reasons'])}")
    print(f"  U {f2['U']:.1f}  Kq {f2['Kq']:.1f}  Ks {f2['Ks']:.1f}  W {f2['W']:.1f} bytes per pending connection; "
          f"established {f2['established']}; skb growth {f2['skb_growth']}; shared cache growth {f2['shared_growth']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
