#!/usr/bin/env python3
"""Proves that a front (a proxy in its M3 or B3 configuration, or the server's one-port relay) is
up and routing every protocol its M3 and B3 cells use, before a window (M4a). Untimed, on L.

Each check starts fresh processes, as a window does (bench/run/handoff.py): the stub backend on
CPUs 10 and 12 and the front on CPU 14. The checks:
  routes    opgen --probe through the front with the TLS stub exchange (the recorded ClientHello,
            SNI oneport.test: the stub's 13 bytes back, then EOF) and with HTTP/1.1 (200 and
            Hello, World!), the two exchanges of M3's cells; the stub must have accepted exactly
            the two connections.
  silent    a client that connects and sends nothing (WL7's silent case), watched for WATCH_S
            seconds: when the front closed it, and when the front opened a connection to the stub
            (read from /proc/net/tcp), if it did.
  partial   the same after WL7's partial-ClientHello opening (the record header and the first
            floor(l/2) bytes of the recorded ClientHello, 108 bytes).
The silent and partial observations are compared with what each system's documents and code say
it does at its timer (EXPECT, from design/competitor-survey.md and Appendix B); where they say
nothing (sslh-ev, survey 2.8: "Runtime behaviour: not verified") the probe records and does not
judge. The routes check always judges. Exit 0 when every judged check passes.

An in-process library (M4b-2: Netty, Jetty, cmux, hyper-util) is probed alone on CPU 14, its
harness from <build>/harness, in its cases configuration (any kind, at matched timers) or its B3
configuration: `routes` runs opgen --probe for every protocol it serves (LIB_PROTOS; the reply is
the library's own), and `silent` and `partial` watch as above, judged against EXPECT_LIB.

    probe.py --system nginx|haproxy|envoy|caddy-l4|sslh-ev|one-port-relay --kind m3|b3 --build DIR --out DIR
    probe.py --system netty|jetty|cmux|hyper-util --kind cases|cases-fallback|b3 --build DIR --out DIR
"""
from __future__ import annotations

import argparse
import json
import select
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))

import competitors as comp  # noqa: E402
import handoff  # noqa: E402
import window  # noqa: E402

REPO = HERE.parent.parent
SERVER = window.ONE_PORT_RELAY
# Watching: past the M3 timer (3 s) by 3 s; in B3 past the window's 30 s (WL7), which the 60 s
# timers must outlast.
WATCH_S = {"m3": 6.0, "b3": 32.0, "cases": 6.0, "cases-fallback": 6.0}
# A timed event counts as "at the timer" from 50 ms before it (the clock's and the loop's grain)
# to 1 s after it (a coarse timer wheel; Envoy's and Go's timers are not exact).
EARLY_S, LATE_S = 0.05, 1.0
PORTS = {"routes": 23000, "silent": 23100, "partial": 23200}  # design choices of M4a, off the ephemeral range

# What each system does with a silent or a partial-ClientHello connection when its timer ends,
# per its documents and code (design/competitor-survey.md; Appendix B), for the M3 configuration
# (timer 3 s). "close": closed at the timer, nothing routed; "route": at the timer handed to the
# default route (the stub's HTTP/1.1 port); None: not documented, observed only. In B3 every timer
# is 60 s, so within WATCH_S every system holds the connection: "hold".
EXPECT_M3 = {
    SERVER: {"silent": "close", "partial": "close"},          # 1(f) at T_dec; pass-through's wait bounded by T_dec (M3 reading 1)
    "nginx": {"silent": "close", "partial": "close"},         # preread_timeout ends the session (survey 2.1)
    "haproxy": {"silent": "route", "partial": "route"},       # at inspect-delay's end, no rule matches: default_backend (survey 2.3)
    "envoy": {"silent": "close", "partial": "close"},         # listener_filters_timeout closes, continue_on_... false (survey 2.5)
    "caddy-l4": {"silent": "close", "partial": "close"},      # matching_timeout closes, no fallback (survey 2.7)
    "sslh-ev": {"silent": None, "partial": None},             # no ev_timer found; runtime behaviour not verified (survey 2.8)
}


# The protocols each library serves (Appendix B; design/competitor-survey.md 2.10, 2.12, 2.15, 2.16),
# each checked by opgen --probe: its exchange completes only against the server's reply.
LIB_PROTOS = {"netty": ("http1", "h2c", "tls"), "jetty": ("http1", "h2c", "tls"), "cmux": ("http1", "h2c", "tls", "ssh"),
              "hyper-util": ("http1", "h2c")}
# What each library does with a silent and a partial-ClientHello connection (the probe's two
# watches), by its documents and code, at matched timers (3 s) in its cases kinds and at 60 s in B3:
#   "close"  closed at the timer;
#   "hold"   neither closed nor answered within the watch;
#   "greet"  the fallback's first bytes (the SMTP greeting) at the timer, the connection open;
#   "reject" closed within LATE_S of the opening, whatever it was answered.
EXPECT_LIB = {
    "cases": {
        "netty": {"silent": "close", "partial": "close"},     # ReadTimeoutHandler; SniHandler's handshake timeout (survey 2.15)
        "jetty": {"silent": "close", "partial": "close"},     # the endpoint's idle timeout (survey 2.16)
        "cmux": {"silent": "close", "partial": "hold"},       # SetReadTimeout fails the reading matchers, no Any(); TLS() matches the
                                                              # record header and clears the deadline, crypto/tls has none (survey 2.10)
        "hyper-util": {"silent": "hold", "partial": "reject"},  # no timer in ReadVersion; 0x16 is not the preface, so HTTP/1 (survey 2.12)
    },
    "cases-fallback": {"cmux": {"silent": "greet", "partial": "hold"}},  # Any() after SetReadTimeout (survey 2.10)
    "b3": {
        "netty": {"silent": "hold", "partial": "hold"},
        "jetty": {"silent": "hold", "partial": "hold"},
        "cmux": {"silent": "hold", "partial": "hold"},
        # A partial ClientHello is no pending connection for hyper-util, which serves no TLS:
        # section 6.2 has no such cell.
        "hyper-util": {"silent": "hold", "partial": "reject"},
    },
}


def recorded_client_hello() -> bytes:
    text = "".join(ln for ln in (REPO / "tests" / "fixtures" / "tls" / "clienthello.hex").read_text().splitlines()
                   if not ln.startswith("#"))
    return bytes.fromhex("".join(text.split()))


def partial_opening() -> bytes:
    """WL7's partial-ClientHello case: the record header, then the first floor(l/2) bytes of the
    l the header announces (bench/cases/opcase_main.cpp)."""
    rec = recorded_client_hello()
    ell = len(rec) - 5
    return rec[:5 + ell // 2]


def stub_sockets(ports: set[int], text: str | None = None) -> set[tuple[str, str]]:
    """The (local, remote) address pairs of the sockets on the stub's ports in any state but
    LISTEN (/proc/net/tcp). A pair absent when the watch began is a connection the front routed;
    one present then (a TIME-WAIT socket of an earlier check) is not."""
    text = Path("/proc/net/tcp").read_text() if text is None else text
    out = set()
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 3 and int(parts[1].split(":")[1], 16) in ports and parts[3] != "0A":
            out.add((parts[1], parts[2]))
    return out


def watch(port: int, opening: bytes, watch_s: float, stub_ports: set[int]) -> dict:
    """Connects, writes `opening` if any, and watches: when the front closed the connection (EOF or
    reset) and when a connection to the stub first appeared. Ends by reset (no TIME-WAIT)."""
    before = stub_sockets(stub_ports)
    c = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    t0 = time.monotonic()
    if opening:
        c.sendall(opening)
    c.setblocking(False)
    obs = {"closed_at_s": None, "close": None, "routed_at_s": None, "bytes_back": 0, "first_bytes_at_s": None}
    while time.monotonic() - t0 < watch_s:
        if stub_ports and obs["routed_at_s"] is None and stub_sockets(stub_ports) - before:
            obs["routed_at_s"] = round(time.monotonic() - t0, 3)
        if obs["closed_at_s"] is None:
            r, _, _ = select.select([c], [], [], 0.02)
            if r:
                try:
                    data = c.recv(65536)
                    if data:
                        if obs["first_bytes_at_s"] is None:
                            obs["first_bytes_at_s"] = round(time.monotonic() - t0, 3)
                        obs["bytes_back"] += len(data)
                    else:
                        obs["closed_at_s"], obs["close"] = round(time.monotonic() - t0, 3), "eof"
                except ConnectionResetError:
                    obs["closed_at_s"], obs["close"] = round(time.monotonic() - t0, 3), "reset"
        else:
            time.sleep(0.02)
    c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    c.close()
    return obs


def at_timer(t: float | None, timer: float) -> bool:
    return t is not None and timer - EARLY_S <= t <= timer + LATE_S


def judge(kind: str, expect: str | None, obs: dict, timer: float) -> tuple[bool | None, str]:
    """Whether an observation is what the system's documents say (None: not judged). A route is
    seen two ways, which must agree: a new socket on the stub's ports during the watch, and the
    stub's count of accepted connections at its stop (`stub_accepted`)."""
    if expect is None:
        return None, "observed only"
    routed = obs["routed_at_s"] is not None
    if routed != ((obs.get("stub_accepted") or 0) > 0):
        return False, f"the stub's sockets (routed at {obs['routed_at_s']}) and its accept count ({obs.get('stub_accepted')}) disagree"
    if expect == "hold":
        ok = obs["closed_at_s"] is None and not routed
        return ok, "held, nothing routed" if ok else "closed or routed before the watch ended"
    if expect == "close":
        ok = at_timer(obs["closed_at_s"], timer) and not routed
        return ok, f"closed at the timer ({timer} s), nothing routed" if ok else f"expected a close at {timer} s and no route"
    if expect == "route":
        ok = at_timer(obs["routed_at_s"], timer)
        return ok, f"routed to the default route at the timer ({timer} s)" if ok else f"expected a route at {timer} s"
    raise ValueError(expect)


def judge_lib(expect: str | None, obs: dict, timer: float) -> tuple[bool | None, str]:
    """An in-process library's observation against EXPECT_LIB (no stub, so no route)."""
    if expect is None:
        return None, "observed only"
    if expect == "hold":
        ok = obs["closed_at_s"] is None and obs["bytes_back"] == 0
        return ok, "held, nothing sent" if ok else "closed or answered before the watch ended"
    if expect == "close":
        ok = at_timer(obs["closed_at_s"], timer)
        return ok, f"closed at the timer ({timer} s)" if ok else f"expected a close at {timer} s"
    if expect == "greet":
        ok = at_timer(obs["first_bytes_at_s"], timer) and obs["closed_at_s"] is None
        return ok, f"the fallback's greeting at the timer ({timer} s)" if ok else f"expected the greeting at {timer} s"
    if expect == "reject":
        ok = obs["closed_at_s"] is not None and obs["closed_at_s"] <= LATE_S
        return ok, "closed at once" if ok else "expected a close at once"
    raise ValueError(expect)


def run_library(system: str, kind: str, build: Path, out: Path) -> dict:
    """The probe of an in-process library (M4b-2): its harness alone on the front's core."""
    timer = float(comp.TIMER_S[kind])
    harness = comp.harness_dir(build)
    res: dict = {"system": system, "kind": kind, "timer_s": timer, "watch_s": WATCH_S[kind], "checks": {},
                 "harness": str(comp.SYSTEMS[system].binary_path(harness)),
                 "harness_sha256": window.sha256_file(comp.SYSTEMS[system].binary_path(harness))}
    port = PORTS["routes"]
    r = comp.start(system, kind, port, 0, list(window.HANDOFF.server), out / f"{system}-{kind}-routes", harness=harness)
    try:
        probes = {proto: window.probe(build, proto, port, 0x7F000101, 1, window.HANDOFF.gen) for proto in LIB_PROTOS[system]}
        alive = r.proc.poll() is None
    finally:
        comp.stop(r)
    res["checks"]["routes"] = {"ok": all(v["exit"] == 0 for v in probes.values()) and alive, "probes": probes, "alive": alive}
    for case, opening in (("silent", b""), ("partial", partial_opening())):
        port = PORTS[case]
        r = comp.start(system, kind, port, 0, list(window.HANDOFF.server), out / f"{system}-{kind}-{case}", harness=harness)
        try:
            obs = watch(port, opening, WATCH_S[kind], set())
            alive = r.proc.poll() is None
        finally:
            comp.stop(r)
        exp = EXPECT_LIB[kind][system][case]
        verdict, text = judge_lib(exp, obs, timer)
        res["checks"][case] = {"ok": verdict if alive else False, "expected": exp, "verdict": text if alive else "the system exited",
                               "observed": obs, "opening_bytes": len(opening), "alive": alive}
    res["ok"] = all(c["ok"] is not False for c in res["checks"].values())
    return res


def expectation(system: str, kind: str, case: str) -> str | None:
    if kind == "b3":
        return "hold"
    return EXPECT_M3[system][case]


class Pair:
    """A fresh stub and front, stopped together; the stub's counters read at its stop."""

    def __init__(self, system: str, kind: str, build: Path, port: int, raw: Path, tag: str):
        self.stub_port = port + handoff.STUB_OFFSET
        raw.mkdir(parents=True, exist_ok=True)
        self.stub, self.stub_out = handoff.start_stub(build, self.stub_port, raw, tag)
        try:
            self.front = handoff.Front(system, build, port, self.stub_port, raw, tag, kind)
        except Exception:
            window.stop_process(self.stub, self.stub_out)
            raise
        self.stub_counters: dict = {}
        self.front_counters: dict = {}
        self.front_alive = True

    def stop(self) -> None:
        self.front_alive = self.front.alive()
        _, front_lines = self.front.stop()
        self.front_counters = window.parse_counters(front_lines)
        _, lines = window.stop_process(self.stub, self.stub_out)
        self.stub_counters = window.parse_counters(lines)


def run(system: str, kind: str, build: Path, out: Path) -> dict:
    if system in comp.LIBRARIES:
        return run_library(system, kind, build, out)
    timer = float(comp.TIMER_S[kind])
    res: dict = {"system": system, "kind": kind, "timer_s": timer, "watch_s": WATCH_S[kind], "checks": {}}
    if system != SERVER:
        res["binary"] = str(comp.SYSTEMS[system].binary_path())
        res["binary_sha256"] = window.sha256_file(comp.SYSTEMS[system].binary_path())
    # routes
    p = Pair(system, kind, build, PORTS["routes"], out, f"{system}-{kind}-routes")
    try:
        probes = {proto: window.probe(build, proto, PORTS["routes"], 0x7F000101, 1, window.HANDOFF.gen) for proto in handoff.M3_PROTOS}
    finally:
        p.stop()
    accepted = p.stub_counters.get("accepted")
    ok = all(v["exit"] == 0 for v in probes.values()) and accepted == len(probes) and p.front_alive
    res["checks"]["routes"] = {"ok": ok, "probes": probes, "stub_accepted": accepted, "front_alive": p.front_alive,
                               "front_counters": {k: v for k, v in p.front_counters.items() if k in ("accepted", "relayed", "routed_by_sni")}}
    # silent and partial
    for case, opening in (("silent", b""), ("partial", partial_opening())):
        port = PORTS[case]
        p = Pair(system, kind, build, port, out, f"{system}-{kind}-{case}")
        try:
            stub_ports = {p.stub_port + comp.STUB_OFFSET["http1"], p.stub_port + comp.STUB_OFFSET["tls"]}
            obs = watch(port, opening, WATCH_S[kind], stub_ports)
        finally:
            p.stop()
        obs["stub_accepted"] = p.stub_counters.get("accepted")
        exp = expectation(system, kind, case)
        verdict, text = judge(kind, exp, obs, timer)
        res["checks"][case] = {"ok": verdict, "expected": exp, "verdict": text, "observed": obs, "opening_bytes": len(opening),
                               "stub_accepted": p.stub_counters.get("accepted"), "front_alive": p.front_alive}
    res["ok"] = all(c["ok"] is not False for c in res["checks"].values())
    return res


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", required=True, choices=(SERVER,) + comp.ORDER + comp.LIBRARIES)
    ap.add_argument("--kind", required=True, choices=comp.KINDS)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    res = run(a.system, a.kind, a.build, a.out)
    (a.out / f"probe-{a.system}-{a.kind}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
