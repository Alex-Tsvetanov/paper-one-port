#!/usr/bin/env python3
"""The hard cases on L: B1's table and B2's checks (hypotheses.md 5.2, Appendix A, WL8), and the
competitors' hard-case table (section 10, descriptive).

    hardcase_run.py --build DIR --out DIR --job NAME [--part server|competitors]
                    --seeds SEEDS.json --code-freeze SHA --gate gate-L.json --pilot PILOT.json --rule-e RULE_E.json
    hardcase_run.py ... --development [--cases 1,12] [--entries epoll.replay.inproc,...] [--replicates R]
                    [--dev-g-ms G --dev-gap-split-ms GAP]

Part server (B1, B2). "Each case runs on every backend, in both detection modes, with in-process
and relay dispatch where it applies, 16 replicates" (Appendix A): on L, epoll and io_uring, replay
and peek, inproc and relay (relay to a server in dedicated mode on the same backend with PROXY off;
M2b reading 6), 8 entries. The timers are section 1's 3 s; G (G_L) and GAP_SPLIT are the pilot
entry's; HC7 is not run where the pilot entry says G is not below T_fb or no timer run was valid
(9.2); rule E's relay copy. Each one-port server runs the measured binary with --record (WL8's
decision record; never in a measured window, and these runs are not windows), one per listener
setup the variants need (plain, SMTP fallback, PROXY, both), on CPU 14, the relay's backend on CPUs
10 and 12, opcase on CPUs 2 to 9 (section 4.1). Every run is `opcase case --id ID --replicates 1`
against the one-port server; its connection's record lines are matched by the client's local port
once the server has recorded the connection's close. The expectations come from `opcase case
--list`, the frozen table compiled into the binary (bench/cases/cases.cpp), and the judge is
tests/case_tests.cpp's check_run, check_reply and check_route, ported line for line:
  B1: the outcome, the class, the deciding byte, the PROXY source and refusal reason, the reply
      (the transcript equal to the same script's against the dedicated port, TLS compared after
      decryption with what the handshake negotiated; a 200, a 400, a close; a TLS flight), the
      dedicated HTTP/1.1 port's reply where the grammar is checked there too, and in relay the
      route (by class to the backend's port of the class, TLS by its SNI, B_CH);
  B2: (a, b) a timed event never early and handled in the first pass whose wait returned at or after
      its deadline, its deadline its timer after its start, and from below on the client's clock;
      (c) a classification in the pass of its deciding byte; (d) the payload bytes a pending
      connection held in user space within its mode's bound and no data buffer without a byte
      (pass-through: the ClientHello's records in replay, nothing in peek); (e) a half-close closed
      in the pass that observed it.
Each run is one row (kind "hardcase") with every check's result, the lateness of a timed event and
the decision time against opcase's write times (B2's distributions, reported, not tested). At the
end of an entry each server's counters give one row (kind "hardcase-servers"): every connection
closed, none left open, no buffer outstanding, one outcome per connection, no budget exceeded, no
failed connect to the relay's backend. hardcases-table-<job>.json counts, per variant and entry,
the replicates that passed and those whose detection woke more than once (HC2, HC3, HC10, HC20:
GAP_SPLIT's share when 9.2's fallback applies).

Part competitors (section 10): each proxy and library in its cases configuration ("cases", and
"cases-fallback" where it has a fallback), at matched timers and at its defaults, its PROXY
listener where it reads the header (bench/competitors/competitors.py), the proxies in front of the
server in dedicated mode with PROXY off (bench/competitors/cases_check.py's backend); every variant
whose listener setup the system covers, R_COMP_CASES = 3 replicates, each observed for at most
T_OBS = 60 s ("no decision within T_OBS" when the client waited that long). Rows (kind
"competitor-case") record the transcript and, descriptively, whether the reply equals what the
server's frozen table expects of the server (the reference transcript of the server's dedicated
port); nothing is judged against the server's outcome.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "competitors"))

import cellwin  # noqa: E402
import competitors as comp  # noqa: E402
import freeze_guard  # noqa: E402
import runlib  # noqa: E402
import window  # noqa: E402

REPLICATES = 16          # 5.2, B1
R_COMP_CASES = 3         # section 10
T_OBS_MS = 60_000        # section 10
TIMER_MS = 3000          # section 1
SERVER_WAIT_MS = 20_000  # opcase's limit on a wait in the server's runs: HC4's drip (2 T_dec) and T_dec (a design choice of M7c)
CLOSE_WAIT_S = 10.0      # the suite's wait for the server's close of a connection (tests/case_tests.cpp)
SYSTEM_CPUS = (14,)
BACKEND_CPUS = (10, 12)
OPCASE_CPUS = tuple(range(2, 10))
# Ports (design choices of M7c, off the ephemeral range and apart from the other runners'): the
# one-port servers per setup, the dedicated reference servers, the relay's backend.
SETUP_PORTS = {"plain": 26000, "SMTP fallback": 26010, "PROXY": 26020, "PROXY, SMTP fallback": 26030}
DEDICATED_PORTS = {False: 26100, True: 26110}
RELAY_BACKEND_PORT = 26200
ENTRIES = tuple(f"{b}.{d}.{p}" for b in ("epoll", "io_uring") for d in ("replay", "peek") for p in ("inproc", "relay"))
SPLIT_CASES = (2, 3, 10, 20)
EXPECT_HANDED = ("classified", "fallback")


# ---------------------------------------------------------------- opcase


def opcase(build: Path, args: list[str], timeout: float) -> tuple[int, list[dict], str]:
    cmd = ["taskset", "-c", ",".join(map(str, OPCASE_CPUS)), str(build / "bench" / "cases" / "opcase"), "case"] + args
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, [json.loads(ln) for ln in p.stdout.splitlines() if ln.startswith("{")], p.stderr.strip()[-300:]


def timer_args(g_ms: int, gap_ms: int) -> list[str]:
    return ["--t-fb-ms", str(TIMER_MS), "--t-dec-ms", str(TIMER_MS), "--t-hdr-ms", str(TIMER_MS), "--gap-split-ms", str(gap_ms),
            "--g-ms", str(g_ms)]


def list_variants(build: Path, hc: int, g_ms: int, gap_ms: int) -> tuple[dict, list[dict]]:
    rc, lines, err = opcase(build, ["--list", "--hc", str(hc)] + timer_args(g_ms, gap_ms), 60)
    if rc != 0 or not lines or "constants" not in lines[0]:
        raise window.WindowError(f"opcase case --list failed (exit {rc}): {err}")
    return lines[0]["constants"], lines[1:]


def run_variant(build: Path, v: dict, port: int, g_ms: int, gap_ms: int, wait_ms: int) -> tuple[dict | None, str]:
    args = ["--port", str(port), "--hc", str(v["hc"]), "--id", v["id"], "--replicates", "1", "--wait-ms", str(wait_ms)] + timer_args(g_ms, gap_ms)
    if v.get("needs_proxy"):
        args += ["--proxy-port", str(port)]
    try:
        rc, lines, err = opcase(build, args, wait_ms / 1000 + 60)
    except subprocess.TimeoutExpired:
        return None, "opcase did not end"
    line = next((ln for ln in lines if ln.get("id") == v["id"]), None)
    return line, ("" if line is not None else f"opcase printed no run (exit {rc}): {err}")


# ---------------------------------------------------------------- servers


class Server:
    """A oneport process on its CPUs, with --record, its listening ports by name, its counters at
    the stop."""

    def __init__(self, build: Path, args: list[str], cpus: tuple[int, ...], raw: Path, tag: str, record: bool = True):
        self.tag = tag
        self.record = raw / f"{tag}.record.jsonl" if record else None
        cmd = [str(build / "bench" / "server" / "oneport")] + args + (["--record", str(self.record)] if record else [])
        self.cmd = cmd
        self.proc = cellwin.popen_err(raw / f"{tag}.err", ["taskset", "-c", ",".join(map(str, cpus))] + cmd, stdout=subprocess.PIPE,
                                      start_new_session=True, cwd=raw)
        self.out = window.Lines(self.proc)
        if not self.out.until(lambda ln: ln.startswith("oneport: connection state"), 15.0):
            window.stop_process(self.proc, self.out)
            raise window.WindowError(f"{tag}: the server did not start: {self.out.lines[-3:]}")
        self.ports: dict[str, int] = {}
        for ln in self.out.lines:
            if ln.startswith("oneport: listening "):
                name, addr = ln[len("oneport: listening "):].rsplit(" ", 1)
                self.ports[name] = int(addr.rsplit(":", 1)[1])
        self.offset = 0
        self.pending: list[dict] = []

    def alive(self) -> bool:
        return self.proc.poll() is None

    def read_record(self) -> None:
        if self.record is None or not self.record.exists():
            return
        data = self.record.read_bytes()
        new = data[self.offset:]
        cut = new.rfind(b"\n") + 1
        self.pending += [json.loads(ln) for ln in new[:cut].decode().splitlines() if ln.strip()]
        self.offset += cut

    def take(self, peer_port: int, limit_s: float = CLOSE_WAIT_S) -> tuple[bool, list[dict], list[dict]]:
        """Waits for the record of the connection's close; returns (closed, detections, routes)
        and drops them from the pending lines."""
        t0 = time.monotonic()
        while True:
            self.read_record()
            if any(x.get("event") == "closed" and x.get("peer_port") == peer_port for x in self.pending):
                break
            if time.monotonic() - t0 > limit_s:
                break
            time.sleep(0.02)
        mine = [x for x in self.pending if x.get("peer_port") == peer_port]
        self.pending = [x for x in self.pending if x.get("peer_port") != peer_port]
        closed = any(x.get("event") == "closed" for x in mine)
        return closed, [x for x in mine if x.get("event") == "detection"], [x for x in mine if x.get("event") == "relayed"]

    def stop(self) -> tuple[int | None, dict]:
        code, lines = window.stop_process(self.proc, self.out)
        return code, window.parse_counters(lines)


# ---------------------------------------------------------------- the judge (tests/case_tests.cpp, ported)


def hexb(s: str | None) -> bytes:
    return bytes.fromhex(s or "")


def same_tls(t: dict, d: dict) -> str | None:
    if not t.get("tls") or not d.get("tls"):
        return "a TLS exchange has no TLS result"
    for r in (t["tls"], d["tls"]):
        if not r.get("handshake"):
            return f"a handshake did not complete: {r.get('error')}"
        if (r.get("version"), r.get("cipher"), r.get("group")) != ("TLSv1.3", "TLS_AES_128_GCM_SHA256", "x25519"):
            return f"negotiated {r.get('version')}, {r.get('cipher')}, {r.get('group')}"
        if r.get("sigalg") != "ecdsa_secp256r1_sha256":
            return f"the server signed with {r.get('sigalg')}"
        if not r.get("verified"):
            return "the server's certificate did not verify for oneport.test"
        if r.get("resumable"):
            return "a session ticket arrived (num_tickets is 0)"
    if t["tls"].get("alpn") != d["tls"].get("alpn"):
        return f"ALPN {t['tls'].get('alpn')} against the dedicated port's {d['tls'].get('alpn')}"
    if t["tls"].get("plain_hex") != d["tls"].get("plain_hex"):
        return "the decrypted transcript differs from the dedicated port's"
    if t["tls"].get("close_notify") != d["tls"].get("close_notify"):
        return "close_notify in one exchange only"
    return None


def check_reply(want: str, t: dict, ded: dict | None, k: dict) -> str | None:
    got = hexb(t.get("received_hex"))
    if want == "dedicated":
        if ded is None:
            return "no dedicated transcript"
        if t.get("tls") or ded.get("tls"):
            bad = same_tls(t, ded)
            if bad:
                return bad
        elif got != hexb(ded.get("received_hex")):
            return f"the transcript differs from the dedicated port's: {len(got)} bytes against {len(hexb(ded.get('received_hex')))}"
        if not (t.get("eof") and not t.get("reset") and ded.get("eof") and not ded.get("reset")):
            return "both must end with the server's EOF"
        return None
    if want == "tls_flight":
        if len(got) < 10:
            return f"no TLS record came back ({len(got)} bytes)"
        if not (got[0] == 0x16 and got[1] == 0x03 and got[5] == 0x02):
            return "the first record is not a ServerHello"
        return None if (t.get("eof") or t.get("reset")) else "the connection was not closed"
    if want == "http200":
        return None if got == hexb(k["response200_hex"]) and t.get("eof") else f"no 200 then EOF: {len(got)} bytes"
    if want == "http400":
        return None if got == hexb(k["response400_hex"]) and t.get("eof") else f"no 400 then EOF: {len(got)} bytes"
    if want == "closed":
        if got:
            return f"a reply of {len(got)} bytes where none is expected"
        return None if (t.get("eof") or t.get("reset")) else "the connection was not closed"
    if want == "any":
        return None
    return f"unknown reply {want!r}"


def dedicated_is_real(proto: str, v: dict, d: dict, k: dict) -> str | None:
    got = hexb(d.get("received_hex"))
    if proto == "HTTP/1.1" and got != hexb(k["response200_hex"]):
        return "the dedicated HTTP/1.1 port did not answer 200"
    if proto == "h2c" and not (len(got) > 9 and got[3] == 0x04 and b"Hello, World!" in got):
        return "the dedicated h2c port did not begin with SETTINGS and send its body"
    if proto == "TLS" and not ((d.get("tls") or {}).get("handshake") and hexb((d.get("tls") or {}).get("plain_hex")) == hexb(k["response200_hex"])):
        return "the dedicated TLS port did not complete the handshake and answer 200"
    if proto == "MQTT" and not (got.startswith(b"\x20\x02\x00\x00") or got.startswith(b"\x20\x03\x00\x00\x00")):
        return "the dedicated MQTT port did not answer CONNACK"
    if proto == "SSH" and got != hexb(k["ssh_banner_hex"]):
        return "the dedicated SSH port did not send its line alone"
    if proto == "SMTP":
        if not got.startswith(hexb(k["smtp_greeting_hex"])):
            return "the dedicated SMTP port did not greet"
        if v["id"] == "HC07.late" and hexb(k["smtp_unknown_hex"]) not in got:
            return "the request got no 500"
    return None


def check_timed(ev: dict, t_ms: int) -> list[str]:
    out = []
    if int(ev["deadline_ns"]) - int(ev["start_ns"]) != t_ms * 1_000_000:
        out.append(f"{ev['kind']}: deadline is not start + T (B2 a)")
    if not int(ev["prev_wait_return_ns"]) < int(ev["deadline_ns"]):
        out.append(f"{ev['kind']}: the previous pass's wait returned after the deadline (B2 b)")
    if not int(ev["deadline_ns"]) <= int(ev["wait_return_ns"]):
        out.append(f"{ev['kind']}: handled in a pass whose wait returned before the deadline (B2 a)")
    if not int(ev["wait_return_ns"]) <= int(ev["handled_at_ns"]):
        out.append(f"{ev['kind']}: handled before its pass's wait returned")
    return out


def judge(v: dict, t: dict, reps: list[dict], relays: list[dict], ded: dict | None, detect: str, relay: bool,
          backend_ports: dict[str, int], k: dict) -> dict:
    """One replicate of a variant against the one-port server: B1 and B2 (check_run, check_route)."""
    b1: list[str] = []
    b2: dict[str, list[str]] = {"a": [], "b": [], "c": [], "d": [], "e": []}
    out = {"b1": b1, "b2": b2}
    if len(reps) != 1:
        b1.append(f"{len(reps)} detection reports for one connection")
        return out
    r = reps[0]
    out.update(outcome=r.get("outcome"), proto=r.get("proto"), at=r.get("at"), wakeups=r.get("wakeups"), timed=r.get("timed"),
               max_user_bytes=r.get("max_user_bytes"))
    if r.get("outcome") != v["expect"]:
        b1.append(f"outcome {r.get('outcome')}, expected {v['expect']}")
    if v["expect"] in EXPECT_HANDED and r.get("proto") != v["proto"]:
        b1.append(f"class {r.get('proto')}, expected {v['proto']}")
    if v.get("at") is not None and r.get("at") != v["at"]:
        b1.append(f"decided at byte {r.get('at')}, expected {v['at']}")
    if v.get("source") is not None and not (r.get("has_proxy") and r.get("proxy") == v["source"]):
        b1.append("the recorded source is not the PROXY header's")
    if v.get("proxy_reason") is not None and r.get("proxy_reason") != v["proxy_reason"]:
        b1.append("the PROXY header was refused for another reason")
    bad = check_reply(v["reply"], t, ded, k)
    if bad:
        b1.append(bad)
    writes = [int(x) for x in t.get("write_ns") or []]
    anchor = writes[v["header_write"]] if v.get("header_write") is not None and v["header_write"] < len(writes) else int(t["before_connect_ns"])
    ev = r.get("timed")
    when = v["when"]
    if when == "at_once":
        if ev:
            b1.append(f"ended by {ev.get('kind')}, expected at once")
        if v["expect"] in ("classified", "rejected", "proxy_rejected") and r.get("end_pass") != r.get("last_read_pass"):
            b2["c"].append(f"decided in pass {r.get('end_pass')}, the deciding bytes came in pass {r.get('last_read_pass')}")
        if v["expect"] in ("undecided", "silent") and not (r.get("observe_pass") and r.get("end_pass") == r.get("observe_pass")):
            b2["e"].append(f"closed in pass {r.get('end_pass')}, the half-close was observed in pass {r.get('observe_pass')}")
    else:
        kind = {"t_fb": "T_fb", "t_dec": "T_dec", "t_hdr": "T_hdr"}[when]
        if not ev or ev.get("kind") != kind or (when == "t_fb" and ev.get("result") != "fallback"):
            b1.append(f"not ended by {kind}" + (" with a fallback" if when == "t_fb" else ""))
        else:
            for x in check_timed(ev, TIMER_MS):
                b2["b" if "(B2 b)" in x else "a"].append(x)
            out["lateness_ns"] = int(ev["wait_return_ns"]) - int(ev["deadline_ns"])
        ref = t.get("first_byte_ns") if when == "t_fb" else t.get("end_ns")
        if ref is None or int(ref) - anchor < TIMER_MS * 1_000_000:
            b2["a"].append(f"{'the fallback spoke' if when == 't_fb' else 'closed'} before {kind} on the client's clock")
    if v["expect"] == "classified" and r.get("end_pass") != r.get("last_read_pass"):
        b2["c"].append(f"classified in pass {r.get('end_pass')}, not in the pass of its byte")
    bound = k["recv_buf"] if detect == "replay" else 0
    if int(r.get("max_user_bytes") or 0) > bound:
        b2["d"].append(f"held {r.get('max_user_bytes')} payload bytes in user space while pending; the bound is {bound}")
    if r.get("buffer_while_silent"):
        b2["d"].append("held a data buffer while no byte had arrived")
    if r.get("has_proxy") and when in ("t_fb", "t_dec") and not int(r.get("timers_start_ns", 0)) > int(r.get("accept_ns", 0)):
        b1.append("the timers did not wait for the PROXY header")
    if relay:
        handed = r.get("outcome") in EXPECT_HANDED
        if not handed and relays:
            b1.append("a connection whose detection ended was relayed")
        elif handed:
            if len(relays) != 1:
                b1.append(f"{len(relays)} route reports for one relayed connection")
            else:
                rr = relays[0]
                tls = r.get("proto") == "TLS"
                if rr.get("route") != ("by_sni" if tls else "by_class"):
                    b1.append(f"routed {rr.get('route')}")
                if rr.get("backend_port") != backend_ports.get(r.get("proto")):
                    b1.append(f"relayed to port {rr.get('backend_port')}, not the backend's {r.get('proto')} port")
                if tls:
                    if not (0 < int(rr.get("hello_len") or 0) <= k["b_ch"] and int(rr.get("hello_records") or 0) >= 1):
                        b1.append("the ClientHello was not reassembled within B_CH")
                    if v["id"] == "HC20" and rr.get("hello_records") != 2:
                        b1.append(f"HC20's ClientHello came in {rr.get('hello_records')} records, not 2")
                    hb = int(rr.get("hello_len") or 0) + 5 * int(rr.get("hello_records") or 0) if detect == "replay" else 0
                    if int(rr.get("held_max") or 0) > hb:
                        b2["d"].append(f"held {rr.get('held_max')} bytes waiting for the ClientHello; the bound is {hb}")
    end = r.get("end_ns")
    before = [w for w in writes if end is not None and w <= int(end)]
    if end is not None and before:
        out["decision_ns_after_last_write"] = int(end) - max(before)
    return out


# ---------------------------------------------------------------- part server


class Entry:
    """The servers of one entry (backend, detection mode, dispatch), started when a variant first
    needs them, as the suite's Servers."""

    def __init__(self, build: Path, backend: str, detect: str, dispatch: str, relay_copy: str, raw: Path, tag: str):
        self.build, self.backend, self.detect, self.dispatch, self.relay_copy, self.raw, self.tag = build, backend, detect, dispatch, relay_copy, raw, tag
        self.one_port: dict[str, Server] = {}
        self.dedicated: dict[bool, Server] = {}
        self.backend_server: Server | None = None

    def base(self, mode: str, port: int, proxy: bool) -> list[str]:
        args = ["--mode", mode, "--detect", self.detect, "--dispatch", "inproc", "--backend", self.backend, "--port", str(port),
                "--t-fb-ms", str(TIMER_MS), "--t-dec-ms", str(TIMER_MS), "--t-hdr-ms", str(TIMER_MS)]
        if proxy:
            args += ["--proxy", "on"]
        return args

    def relay_backend(self) -> Server:
        if self.backend_server is None:
            self.backend_server = Server(self.build, self.base("dedicated", RELAY_BACKEND_PORT, False), BACKEND_CPUS, self.raw,
                                         f"{self.tag}-relay-backend", record=False)
        return self.backend_server

    def server(self, setup: str) -> Server:
        if setup not in self.one_port:
            args = self.base("one-port", SETUP_PORTS[setup], "PROXY" in setup)
            if "fallback" in setup:
                args += ["--fallback", "SMTP"]
            if self.dispatch == "relay":
                args[args.index("--dispatch") + 1] = "relay"
                args += ["--relay-port", str(self.relay_backend().ports["HTTP/1.1"]), "--relay-copy", self.relay_copy]
            self.one_port[setup] = Server(self.build, args, SYSTEM_CPUS, self.raw, f"{self.tag}-{setup.replace(', ', '-').replace(' ', '-')}")
        return self.one_port[setup]

    def dedicated_server(self, proxy: bool) -> Server:
        if proxy not in self.dedicated:
            self.dedicated[proxy] = Server(self.build, self.base("dedicated", DEDICATED_PORTS[proxy], proxy), SYSTEM_CPUS, self.raw,
                                           f"{self.tag}-dedicated{'-proxy' if proxy else ''}", record=False)
        return self.dedicated[proxy]

    def stop(self) -> list[dict]:
        out = []
        for name, s in [(f"one-port {k}", v) for k, v in self.one_port.items()] + [(f"dedicated{' PROXY' if k else ''}", v) for k, v in
                                                                                      self.dedicated.items()]:
            code, c = s.stop()
            out.append(server_checks(name, code, c, name.startswith("one-port"), self.dispatch == "relay" and name.startswith("one-port")))
        if self.backend_server is not None:
            code, c = self.backend_server.stop()
            out.append(server_checks("relay backend", code, c, False, False))
        return out


def server_checks(name: str, code: int | None, c: dict, one_port: bool, relays: bool) -> dict:
    """The suite's stop_and_check on a server's counters at its stop."""
    bad = []
    if code != 0:
        bad.append(f"exit {code}")
    if c.get("accepted") != c.get("closed"):
        bad.append(f"accepted {c.get('accepted')}, closed {c.get('closed')}")
    for k in ("conns_open", "buffers_outstanding"):
        if c.get(k):
            bad.append(f"{k} {c.get(k)}")
    outcomes = c.get("outcome") or {}
    if (outcomes.get("rejected_budget") or 0) != 0:
        bad.append("a budget was exceeded")
    if one_port and sum(v for v in outcomes.values() if isinstance(v, int)) != c.get("accepted"):
        bad.append(f"outcomes {sum(v for v in outcomes.values() if isinstance(v, int))} for {c.get('accepted')} connections")
    if relays and c.get("relay_connect_errors"):
        bad.append(f"{c.get('relay_connect_errors')} connects to the backend failed")
    return {"server": name, "exit": code, "ok": not bad, "problems": bad,
            "counters": {k: c.get(k) for k in ("accepted", "closed", "conns_open", "buffers_outstanding", "relay_connect_errors", "timed_events")},
            "outcomes": outcomes}


def part_server(a: argparse.Namespace, pilot: dict, rule_e: dict, prov: dict, clearance, emit) -> dict:
    g = (pilot.get("G") or {}).get("L") or {}
    gap = (pilot.get("gap_split") or {}).get("GAP_SPLIT_ms")
    g_ms = g.get("G_ms")
    hc7 = bool(g.get("hc7_runs"))
    if a.development:
        g_ms = a.dev_g_ms if a.dev_g_ms is not None else g_ms
        gap = a.dev_gap_split_ms if a.dev_gap_split_ms is not None else gap
        hc7 = g_ms is not None and g_ms < TIMER_MS
    if gap is None:
        raise runlib.InputRefused("GAP_SPLIT is not in the pilot entry's output")
    if g_ms is None and hc7:
        raise runlib.InputRefused("G_L is not in the pilot entry's output")
    prior = {(r["entry"], r["id"], r["replicate"]) for r in a.rows_prior if r.get("kind") == "hardcase"}
    table: dict = {}
    for entry in a.entries:
        backend, detect, dispatch = entry.split(".")
        e = Entry(a.build, backend, detect, dispatch, rule_e["relay_copy"][backend], a.out / "raw", f"{a.job}-{entry}")
        try:
            for hc in a.cases:
                if hc == 7 and not hc7:
                    emit({"kind": "hardcase-skipped", "entry": entry, "hc": 7, "why": "9.2: no valid timer run on L, or G not below T_fb"})
                    continue
                k, variants = list_variants(a.build, hc, g_ms or 1, gap)
                for v in variants:
                    todo = [rep for rep in range(1, a.replicates + 1) if (entry, v["id"], rep) not in prior]
                    if not todo:
                        continue
                    ded, ded_bad = None, None
                    try:
                        if v["reply"] == "dedicated":
                            d = e.dedicated_server(bool(v["needs_proxy"]))
                            ded, why = run_variant(a.build, v, d.ports[v["dedicated"]], g_ms or 1, gap, SERVER_WAIT_MS)
                            ded_bad = why or dedicated_is_real(v["dedicated"], v, ded, k)
                        if not ded_bad and v.get("dedicated_http_reply"):
                            d = e.dedicated_server(bool(v["needs_proxy"]))
                            dt, why = run_variant(a.build, v, d.ports["HTTP/1.1"], g_ms or 1, gap, SERVER_WAIT_MS)
                            ded_bad = why or (check_reply(v["dedicated_http_reply"], dt, None, k) and
                                              "dedicated mode: " + check_reply(v["dedicated_http_reply"], dt, None, k))
                        srv = e.server(v["setup"])
                    except Exception as ex:  # noqa: BLE001 - the replicates record it
                        ded_bad = f"driver error: {ex!r}"
                        srv = None
                    for rep in todo:
                        row = {"kind": "hardcase", "entry": entry, "backend": backend, "detect": detect, "dispatch": dispatch, "hc": hc,
                               "id": v["id"], "replicate": rep, "expect": v["expect"], "coverage": v["coverage"], "setup": v["setup"]}
                        if ded_bad or srv is None:
                            row.update(passed=False, b1=[ded_bad or "no server"], b2={}, infrastructure=srv is None)
                            emit(row)
                            continue
                        if not srv.alive():
                            row.update(passed=False, b1=[f"the one-port server exited ({srv.proc.returncode})"], b2={})
                            emit(row)
                            continue
                        t, why = run_variant(a.build, v, srv.ports["one-port"], g_ms or 1, gap, SERVER_WAIT_MS)
                        if t is None or not t.get("connected") or t.get("timed_out"):
                            row.update(passed=False, b1=[why or ("connect failed" if t and not t.get("connected") else "the client waited past its limit")],
                                       b2={}, transcript=t)
                            emit(row)
                            continue
                        closed, reps, relays = srv.take(int(t["local_port"]))
                        if not closed:
                            row.update(passed=False, b1=["the server did not close the connection"], b2={})
                            emit(row)
                            continue
                        bports = e.relay_backend().ports if dispatch == "relay" else {}
                        res = judge(v, t, reps, relays, ded, detect, dispatch == "relay", bports, k)
                        failed_b2 = {x: y for x, y in res["b2"].items() if y}
                        row.update(res, passed=not res["b1"] and not failed_b2, b2_failed=sorted(failed_b2),
                                   transcript={x: t.get(x) for x in ("local_port", "before_connect_ns", "after_connect_ns", "write_ns", "sent",
                                                                     "first_byte_ns", "end_ns", "eof", "reset", "client_reset")})
                        emit(row)
                        key = f"{entry}|{v['id']}"
                        tb = table.setdefault(key, {"entry": entry, "id": v["id"], "hc": hc, "runs": 0, "passed": 0, "woke_twice": 0})
                        tb["runs"] += 1
                        tb["passed"] += int(row["passed"])
                        tb["woke_twice"] += int((res.get("wakeups") or 0) >= 2)
        finally:
            for chk in e.stop():
                emit(dict(chk, kind="hardcase-servers", entry=entry))
    return table


# ---------------------------------------------------------------- part competitors


def covered(system: str, setup: str) -> str | None:
    """The cases kind of a system that has a variant's listener setup, or None."""
    fb = "fallback" in setup
    px = "PROXY" in setup
    if fb and system not in comp.FALLBACK_SYSTEMS:
        return None
    if px and system not in comp.PROXY_SYSTEMS:
        return None
    return "cases-fallback" if fb else "cases"


def part_competitors(a: argparse.Namespace, pilot: dict, emit) -> None:
    import cases_check  # noqa: PLC0415 - bench/competitors/cases_check.py: the dedicated backend of the proxies
    gap = (pilot.get("gap_split") or {}).get("GAP_SPLIT_ms") or a.dev_gap_split_ms
    g = ((pilot.get("G") or {}).get("L") or {}).get("G_ms") or a.dev_g_ms or 1
    if gap is None:
        raise runlib.InputRefused("GAP_SPLIT is not in the pilot entry's output")
    raw = a.out / "raw"
    prior = {(r["system"], r["cases_kind"], r["timers"], r["id"], r["replicate"]) for r in a.rows_prior if r.get("kind") == "competitor-case"}
    ref_entry = Entry(a.build, "epoll", "replay", "inproc", "user-space", raw, f"{a.job}-reference")
    try:
        for system in a.systems:
            for timers in comp.TIMERS:
                for kind in comp.CASES_KINDS:
                    if kind == "cases-fallback" and system not in comp.FALLBACK_SYSTEMS:
                        continue
                    run_dir = raw / f"{a.job}-{system}-{kind}-{timers}"
                    backend = None
                    running = None
                    try:
                        if system in comp.ORDER:
                            run_dir.mkdir(parents=True, exist_ok=True)
                            backend = cases_check.start_backend(a.build, run_dir)
                        running = comp.start(system, kind, cases_check.PORT, cases_check.BACKEND, list(SYSTEM_CPUS), run_dir / "front",
                                             timers, harness=comp.harness_dir(a.build) if system in comp.LIBRARIES else None)
                    except Exception as ex:  # noqa: BLE001 - recorded
                        emit({"kind": "competitor-start", "system": system, "cases_kind": kind, "timers": timers, "ok": False, "why": repr(ex)})
                        if backend is not None:
                            window.stop_process(backend[0], backend[1])
                        continue
                    try:
                        for hc in a.cases:
                            k, variants = list_variants(a.build, hc, g, gap)
                            for v in variants:
                                if covered(system, v["setup"]) != kind:
                                    continue
                                ded = None
                                if v["reply"] == "dedicated":
                                    d = ref_entry.dedicated_server(bool(v["needs_proxy"]))
                                    ded, _ = run_variant(a.build, v, d.ports[v["dedicated"]], g, gap, SERVER_WAIT_MS)
                                port = cases_check.PORT + comp.PROXY_PORT_OFFSET if v["needs_proxy"] else cases_check.PORT
                                for rep in range(1, R_COMP_CASES + 1):
                                    if (system, kind, timers, v["id"], rep) in prior:
                                        continue
                                    t, why = run_variant(a.build, v, port, g, gap, T_OBS_MS)
                                    row = {"kind": "competitor-case", "system": system, "cases_kind": kind, "timers": timers, "hc": hc,
                                           "id": v["id"], "replicate": rep, "setup": v["setup"], "server_expects": v["expect"]}
                                    if t is None:
                                        row.update(observed=False, why=why)
                                    else:
                                        got = hexb(t.get("received_hex"))
                                        row.update(observed=True, connected=t.get("connected"), received_bytes=len(got),
                                                   first_line=got.split(b"\r\n", 1)[0][:80].decode("latin-1"),
                                                   eof=t.get("eof"), reset=t.get("reset"), timed_out=t.get("timed_out"),
                                                   end_ms=(int(t["end_ns"]) - int(t["before_connect_ns"])) / 1e6 if t.get("end_ns") else None,
                                                   first_byte_ms=(int(t["first_byte_ns"]) - int(t["before_connect_ns"])) / 1e6 if t.get("first_byte_ns") else None,
                                                   tls={x: (t.get("tls") or {}).get(x) for x in ("handshake", "alpn", "error")} if t.get("tls") else None,
                                                   no_decision_within_t_obs=bool(t.get("timed_out")),
                                                   reply_as_the_server_table_expects=check_reply(v["reply"], t, ded, k) is None)
                                    emit(row)
                    finally:
                        code = comp.stop(running)
                        emit({"kind": "competitor-start", "system": system, "cases_kind": kind, "timers": timers, "ok": True, "exit": code})
                        if backend is not None:
                            window.stop_process(backend[0], backend[1])
    finally:
        ref_entry.stop()


# ---------------------------------------------------------------- main


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    runlib.common_args(ap)
    ap.add_argument("--rule-e", type=Path)
    ap.add_argument("--part", default="server", choices=("server", "competitors"))
    ap.add_argument("--cases", type=lambda s: [int(x) for x in s.split(",")], default=list(range(1, 26)))
    ap.add_argument("--entries", type=lambda s: s.split(","), default=list(ENTRIES))
    ap.add_argument("--replicates", type=int, default=REPLICATES)
    ap.add_argument("--systems", type=lambda s: s.split(","), default=list(comp.ORDER) + list(comp.LIBRARIES))
    ap.add_argument("--dev-g-ms", type=int, help="development mode: G without a pilot entry")
    ap.add_argument("--dev-gap-split-ms", type=int, help="development mode: GAP_SPLIT without a pilot entry")
    a = ap.parse_args(argv)
    if a.development and a.dev_seed is None:
        a.dev_seed = 0  # the hard cases have no order to draw
    runlib.check_mode_args(a)
    full = (sorted(a.cases) == list(range(1, 26)) and a.entries == list(ENTRIES) and a.replicates == REPLICATES
            and a.dev_g_ms is None and a.dev_gap_split_ms is None)
    if not a.development and not full and a.part == "server":
        raise runlib.InputRefused("--cases, --entries, --replicates and the --dev values narrow the frozen run: development only")
    if any(e not in ENTRIES for e in a.entries):
        raise runlib.InputRefused(f"entries are {ENTRIES}")
    a.out.mkdir(parents=True, exist_ok=True)
    pilot = runlib.load_pilot(a.pilot, a.development)
    rule_e = runlib.load_rule_e(a.rule_e, a.development)
    prov = runlib.job_provenance(a.build, a.tools, a.out, a.job)
    clearance = None
    if not a.development:
        clearance = freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, pilot=a.pilot, rule_e=a.rule_e,
                                       binaries=runlib.binaries_of(prov, ("oneport", "opcase")))
    path = a.out / ("hardcases.jsonl" if a.part == "server" else "competitor_cases.jsonl")
    a.rows_prior = runlib_rows(path)
    rprov = runlib.arm_provenance(prov, a.build, ("oneport", "opcase"))
    if clearance is not None:
        rprov["freeze"] = clearance.record

    def emit(row: dict) -> None:
        row.update(job=a.job, development=a.development, runner="hardcase_run", provenance=rprov,
                   recorded=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        if row.get("kind") in ("hardcase", "competitor-case"):
            print(f"{row.get('entry', row.get('system'))} {row['id']} r{row['replicate']}: "
                  f"{'pass' if row.get('passed') else row.get('b1') or row.get('first_line')}", flush=True)

    if a.part == "server":
        table = part_server(a, pilot, rule_e, prov, clearance, emit)
        (a.out / f"hardcases-table-{a.job}.json").write_text(json.dumps(table, indent=1, sort_keys=True))
        failed = sum(1 for v in table.values() if v["passed"] != v["runs"])
        print(f"hard cases: {len(table)} variant-entries, {failed} with a failing run", flush=True)
    else:
        part_competitors(a, pilot, emit)
    return 0


def runlib_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runlib.InputRefused, freeze_guard.FreezeRefused) as e:
        print(f"hardcase_run.py: refused: {e}", file=sys.stderr)
        sys.exit(2)
