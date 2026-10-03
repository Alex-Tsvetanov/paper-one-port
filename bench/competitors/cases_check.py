#!/usr/bin/env python3
"""Proves that each proxy's cases configuration (Appendix B; section 10) starts and routes every
class its features cover to the right port of the backend, before the competitors' hard cases run
(section 10, after the pilot entry). Untimed, development checks on L (M4b-1).

Each check starts fresh processes: the backend, the server in dedicated mode with PROXY off (M2b
reading 6), two workers on CPUs 10 and 12, its listeners from BACKEND in the order of I20; then
the system on CPU 14 in one kind of its cases configuration ("cases", or "cases-fallback" where it
has a fallback) at matched timers or at its defaults. The checks:
  routes    opgen --probe on the plain listener for HTTP/1.1, h2c, TLS (SNI oneport.test, ALPN
            http/1.1), MQTT and SSH: each exchange completes only if the system routed it to the
            backend's port of its class;
  proxy     on the PROXY listener (competitors.PROXY_SYSTEMS), a PROXY v1 and a PROXY v2 header,
            each followed by an HTTP/1.1 request in the same write: the backend's 200 must come
            back (the header consumed);
  fallback  in cases-fallback, a client that sends nothing: the SMTP greeting must arrive within
            the system's timer and FALLBACK_LATE_S.
COVERS gives the classes each system's features cover (Appendix B; design/competitor-survey.md):
those must pass; the rest are recorded. sslh-ev's fallback is recorded only: sslh-ev checks its
probe timeout only on read activity (survey 2.8; M4a's probes). HAProxy's routes at its defaults
are recorded only: with no inspect delay it decides on the bytes at hand, which its documents call
racy (JUDGE_ROUTES_AT_DEFAULT). Exit 0 when every judged check passes.

    cases_check.py --build DIR --out DIR [--systems nginx,...] [--timers matched,default]
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))

import competitors as comp  # noqa: E402
import window  # noqa: E402

PORT, BACKEND = 25000, 25010  # design choices of M4b-1, off the ephemeral range; the PROXY listener PORT + 1
BACKEND_CPUS = (10, 12)
GEN_CPUS = (2, 3, 4, 5, 6, 7, 8, 9)
PROTOS = ("http1", "h2c", "tls", "mqtt", "ssh")
COVERS = {
    "nginx": {"http1", "tls"},                          # TLS by its ClientHello, everything else to HTTP/1.1 (survey 2.1)
    "haproxy": {"http1", "h2c", "tls", "mqtt", "ssh"},  # Appendix B's rules and the h2c preface (survey 2.3)
    "envoy": {"http1", "h2c", "tls"},                   # tls_inspector and http_inspector (survey 2.5)
    "caddy-l4": {"http1", "h2c", "tls", "mqtt", "ssh"},  # the tls, http, ssh and regexp matchers (survey 2.7)
    "sslh-ev": {"http1", "tls", "mqtt", "ssh"},         # tls, http, ssh and a regex probe; no h2c probe (survey 2.8)
}
# The defaults' timers where a fallback waits for one: HAProxy has no default inspect delay, so it
# decides at once; Envoy's listener_filters_timeout is 15 s (survey 2.5).
FALLBACK_TIMER_S = {"matched": {"haproxy": 3.0, "envoy": 3.0, "sslh-ev": 3.0}, "default": {"haproxy": 0.0, "envoy": 15.0, "sslh-ev": 5.0}}
FALLBACK_LATE_S = 2.0
JUDGE_FALLBACK = {"haproxy", "envoy"}
# At its defaults HAProxy has no inspect delay and "will immediately apply a verdict based on the
# available information ... might even be racy, so such setups are not recommended"
# (configuration.txt v3.4.6, tcp-request inspect-delay): its routes are recorded there, not judged.
JUDGE_ROUTES_AT_DEFAULT = {"nginx", "envoy", "caddy-l4", "sslh-ev"}
REQUEST = b"GET / HTTP/1.1\r\nHost: oneport.test\r\nConnection: close\r\n\r\n"


def proxy_v1() -> bytes:
    return b"PROXY TCP4 127.0.0.9 127.0.0.1 40000 25001\r\n"


def proxy_v2() -> bytes:
    """A PROXY v2 header, command PROXY, TCP over IPv4 (doc/proxy-protocol.txt section 2.2)."""
    sig = b"\x0d\x0a\x0d\x0a\x00\x0d\x0a\x51\x55\x49\x54\x0a"
    addrs = socket.inet_aton("127.0.0.9") + socket.inet_aton("127.0.0.1") + struct.pack("!HH", 40000, PORT + 1)
    return sig + bytes([0x21, 0x11]) + struct.pack("!H", len(addrs)) + addrs


def exchange(port: int, data: bytes, timeout: float = 5.0) -> bytes:
    """Writes data, reads to EOF or the timeout; returns what came back."""
    got = b""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(data)
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                got += chunk
        except socket.timeout:
            pass
    return got


def silent_until_greeting(port: int, limit: float) -> dict:
    t0 = time.monotonic()
    with socket.create_connection(("127.0.0.1", port), timeout=limit) as s:
        try:
            first = s.recv(256)
        except socket.timeout:
            return {"greeting": False, "detail": f"nothing in {limit:.1f} s"}
    dt = time.monotonic() - t0
    return {"greeting": first.startswith(b"220 "), "after_s": dt, "detail": first[:40].decode("latin-1")}


def start_backend(build: Path, raw: Path):
    cmd = [str(build / "bench" / "server" / "oneport"), "--mode", "dedicated", "--detect", "replay", "--dispatch", "inproc", "--backend", "epoll",
           "--workers", str(len(BACKEND_CPUS)), "--port", str(BACKEND)]
    proc = subprocess.Popen(["taskset", "-c", ",".join(map(str, BACKEND_CPUS))] + cmd, stdout=subprocess.PIPE,
                            stderr=open(raw / "backend.err", "wb"), start_new_session=True, cwd=raw, preexec_fn=comp.raise_nofile)
    out = window.Lines(proc)
    if not out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
        window.stop_process(proc, out)
        raise window.WindowError(f"the backend did not start: {out.lines[-3:]}")
    return proc, out


def check(build: Path, system: str, kind: str, timers: str, raw: Path, blocks: window.SourceBlocks) -> dict:
    run = raw / f"{system}-{kind}-{timers}"
    run.mkdir(parents=True, exist_ok=True)
    row: dict = {"system": system, "kind": kind, "timers": timers, "routes": {}, "proxy": {}, "development": True}
    backend, backend_out = start_backend(build, run)
    front = None
    problems: list[str] = []
    try:
        front = comp.start(system, kind, PORT, BACKEND, [14], run / "front", timers)
        base = blocks.take(16)
        try:
            for p in PROTOS:
                r = window.probe(build, p, PORT, base, 16, GEN_CPUS)
                ok = r["exit"] == 0
                row["routes"][p] = {"ok": ok, "detail": r["detail"]}
                judged = timers == "matched" or system in JUDGE_ROUTES_AT_DEFAULT
                if p in COVERS[system] and not ok and judged:
                    problems.append(f"{p} not routed: {r['detail']}")
        finally:
            blocks.release(base)
        for name, header in (("v1", proxy_v1()), ("v2", proxy_v2())) if system in comp.PROXY_SYSTEMS else ():
            try:
                got = exchange(PORT + comp.PROXY_PORT_OFFSET, header + REQUEST)
            except OSError as e:
                got = repr(e).encode()
            ok = got.startswith(b"HTTP/1.1 200") and got.endswith(b"Hello, World!")
            row["proxy"][name] = {"ok": ok, "detail": got[:60].decode("latin-1")}
            if not ok:
                problems.append(f"PROXY {name}: {got[:60]!r}")
        if kind == "cases-fallback":
            limit = FALLBACK_TIMER_S[timers][system] + FALLBACK_LATE_S
            row["fallback"] = silent_until_greeting(PORT, limit)
            row["fallback"]["limit_s"] = limit
            if system in JUDGE_FALLBACK and not row["fallback"]["greeting"]:
                problems.append(f"fallback: {row['fallback']['detail']}")
        row["front_alive"] = front.proc.poll() is None
        if not row["front_alive"]:
            problems.append("the system exited")
    except Exception as e:  # noqa: BLE001 - recorded in the row
        problems.append(f"driver error: {e!r}")
    finally:
        if front is not None:
            row["front_exit"] = comp.stop(front)
        window.stop_process(backend, backend_out)
    row["problems"] = problems
    row["ok"] = not problems
    return row


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--systems", default=",".join(comp.ORDER))
    ap.add_argument("--timers", default=",".join(comp.TIMERS))
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    a = ap.parse_args(argv)
    raw = a.out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    blocks = window.SourceBlocks(a.blocks)
    rows = []
    for system in [s for s in a.systems.split(",") if s]:
        kinds = comp.CASES_KINDS if system in comp.FALLBACK_SYSTEMS else ("cases",)
        for kind in kinds:
            for timers in [t for t in a.timers.split(",") if t]:
                r = check(a.build, system, kind, timers, raw, blocks)
                rows.append(r)
                routes = " ".join(f"{p}={'ok' if v['ok'] else 'no'}" for p, v in r["routes"].items())
                proxy = " ".join(f"{p}={'ok' if v['ok'] else 'no'}" for p, v in r["proxy"].items())
                fb = r.get("fallback")
                fbs = f" fallback={'ok' if fb['greeting'] else 'no'}" + (f" at {fb['after_s']:.2f}s" if fb.get("after_s") else "") if fb else ""
                print(f"{system} {kind} {timers}: ok={r['ok']} routes: {routes}; PROXY: {proxy};{fbs} {'; '.join(r['problems'])}", flush=True)
    with open(a.out / "cases_check.jsonl", "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
