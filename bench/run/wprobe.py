#!/usr/bin/env python3
"""The probe of window times on the laptop's Windows (hypotheses.md, revision log, the entry of
2026-10-23 "A probe of window times on the laptop's Windows, before the entry that moves W's runs
there (a reading)"): development data, never a result. Run it inside a W lab job (wjob.py).

1. Reads, read only, before any window: TcpTimedWaitDelay under
   HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters (absent if it is not set), and the
   output of `netsh int ipv4 show dynamicport tcp` and `netsh int ipv4 show excludedportrange
   protocol=tcp`. It changes nothing. If an excluded range overlaps the ports the server binds, it
   stops before any window (exit 4), with the readings written.
2. Runs, on IOCP, the server in dedicated mode, one arm, through W's window code
   (wwindow.run_window, its TIME-WAIT wait included): the job's warm-up, WL1 churn windows on
   HTTP/1.1 until sessions.JOB_WARMUP_S have passed; then for each protocol in the order HTTP/1.1,
   h2c, TLS, MQTT, 4 WL1 churn windows and 4 WL2 open-loop windows at the rate of that protocol's
   C3.W cell in the pilot entry's output (its key `rates`; a load only); then 2 WL3 keep-alive
   windows per protocol. Before each group of windows of one workload and protocol, the reading a W
   session takes (wwindow.fingerprint), timed.
3. Records only wall time: per window the fields of `window_times` (the workload, the protocol, the
   start and end, the length, the TIME-WAIT wait and counts, a driver error's text), per group the
   reading's length, and the summary of `summarise`. A window's row is kept in memory only to copy
   those fields; its raw files (the generator's report, the server's and the generator's error
   output) are deleted once it ends, so no metric of the probe is ever on disk. Nothing it prints
   holds a window's value either.

    wprobe.py --build DIR --out DIR --job NAME --pilot lab\\analysis-inputs\\pilot.json [--k-src 16]

Outputs in --out: probe-times.jsonl (one line per window and per reading), probe-summary.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aa  # noqa: E402  (PORT_A)
import sessions  # noqa: E402  (JOB_WARMUP_S)
import waa  # noqa: E402  (provenance)
import window  # noqa: E402  (SourceBlocks)
import wrunlib  # noqa: E402
import wwindow  # noqa: E402

# The pilot entry's output (its item 10's rates; lab/analysis-inputs/pilot.json), by its sha256.
PILOT_SHA256 = "bc48a736e97a33392b5545f2ba79e317daa19e37e3990c40a232e160f448771d"
PROTOS = ("http1", "h2c", "tls", "mqtt")
CHURN_WINDOWS = 4
OPEN_WINDOWS = 4
KEEPALIVE_WINDOWS = 2
K_SRC = 16  # section 9.1
PORT = aa.PORT_A
USED_PORTS = [(PORT, PORT + 5)]  # the dedicated server's consecutive listeners, as wcost_run's arm A
EXIT_PORTS = 4
TCPIP_KEY = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
# The only fields of a window's row that are written (item 6 of the entry).
ROW_FIELDS = ("started", "time_wait_wait_s", "time_wait_before_wait", "time_wait_start")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------------------------------------------------------------- the readings (read only)


def time_wait_delay() -> dict:
    """TcpTimedWaitDelay, read from the registry; {"set": False} when the value is absent."""
    if sys.platform != "win32":
        return {"read": False, "why": "not Windows"}
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TCPIP_KEY) as k:
            v, kind = winreg.QueryValueEx(k, "TcpTimedWaitDelay")
            return {"read": True, "set": True, "value": v, "type": kind}
    except FileNotFoundError:
        return {"read": True, "set": False}
    except OSError as e:
        return {"read": False, "error": repr(e)}


def parse_dynamic_port(text: str) -> dict:
    """`netsh int ipv4 show dynamicport tcp`: the start port and the number of ports."""
    out: dict = {}
    for ln in text.splitlines():
        key, _, val = ln.partition(":")
        k, v = key.strip().lower(), val.strip()
        if k == "start port" and v.isdigit():
            out["start"] = int(v)
        elif k == "number of ports" and v.isdigit():
            out["count"] = int(v)
    if "start" in out and "count" in out:
        out["end"] = out["start"] + out["count"] - 1
    return out


def netsh(*args: str) -> dict:
    if sys.platform != "win32":
        return {"read": False, "why": "not Windows"}
    p = subprocess.run(["netsh", *args], capture_output=True, text=True, errors="replace")
    return {"read": p.returncode == 0, "exit": p.returncode, "output": p.stdout.strip()}


def readings() -> dict:
    dyn = netsh("int", "ipv4", "show", "dynamicport", "tcp")
    exc = netsh("int", "ipv4", "show", "excludedportrange", "protocol=tcp")
    excluded = wrunlib.parse_excluded(exc.get("output", ""))
    return {"at": now(), "tcp_timed_wait_delay": time_wait_delay(),
            "dynamic_port_tcp": dict(dyn, parsed=parse_dynamic_port(dyn.get("output", ""))),
            "excluded_port_range_tcp": dict(exc, parsed=excluded),
            "port_conflicts": wrunlib.port_conflicts(excluded, USED_PORTS), "used_ports": USED_PORTS}


# ---------------------------------------------------------------- the plan and what is kept


def pilot_rates(path: Path) -> dict[str, float]:
    """The C3.W rate of each protocol from the pilot entry's output, which must be that file."""
    data = Path(path).read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != PILOT_SHA256:
        raise SystemExit(f"wprobe: {path} has sha256 {got}, not the pilot entry's {PILOT_SHA256}")
    rates = json.loads(data)["rates"]
    return {p: float(rates[f"C3.W.IOCP.{p}"]["rate"]) for p in PROTOS}


def groups(rates: dict[str, float]) -> list[dict]:
    """The probe's groups after the warm-up, in order: workload, protocol, windows, rate."""
    out = []
    for p in PROTOS:
        out.append({"workload": "churn", "proto": p, "windows": CHURN_WINDOWS, "rate": None})
        out.append({"workload": "open", "proto": p, "windows": OPEN_WINDOWS, "rate": rates[p]})
    for p in PROTOS:
        out.append({"workload": "keepalive", "proto": p, "windows": KEEPALIVE_WINDOWS, "rate": None})
    return out


def window_times(row: dict, *, phase: str, index: int, group: dict, t0: float, t1: float, w0: float, w1: float) -> dict:
    """The line written for one window: ROW_FIELDS of its row and the driver's own clock readings;
    a driver error's text if the window code raised one. Nothing else of the row."""
    line = {"kind": "window", "phase": phase, "index": index, "workload": group["workload"], "proto": group["proto"],
            "rate_given": group.get("rate"), "wall_start": w0, "wall_end": w1, "length_s": t1 - t0}
    line.update({k: row.get(k) for k in ROW_FIELDS})
    errors = [r for r in row.get("invalid_reasons") or [] if str(r).startswith("driver error")]
    line["driver_error"] = errors[0] if errors else None
    return line


def summarise(lines: list[dict]) -> dict:
    """Per phase and workload: the count, sum, minimum and maximum of the window lengths and of the
    TIME-WAIT waits, the windows whose wait reached TW_WAIT_MAX_S, those that started above
    TW_START_MAX entries and those with a driver error; and the readings' count and summed length."""
    out: dict = {"windows": {}, "readings": {"count": 0, "sum_s": 0.0}}
    for ln in lines:
        if ln.get("kind") == "reading":
            out["readings"]["count"] += 1
            out["readings"]["sum_s"] += ln["length_s"]
            continue
        key = ln["workload"] if ln["phase"] == "probe" else f"{ln['phase']}.{ln['workload']}"
        s = out["windows"].setdefault(key, {"count": 0, "length_s": [], "time_wait_wait_s": [], "wait_at_cap": 0,
                                             "started_above_limit": 0, "driver_errors": 0})
        s["count"] += 1
        s["length_s"].append(ln["length_s"])
        tw = ln.get("time_wait_wait_s")
        if tw is not None:
            s["time_wait_wait_s"].append(tw)
            if tw >= wwindow.TW_WAIT_MAX_S:
                s["wait_at_cap"] += 1
        if (ln.get("time_wait_start") or 0) > wwindow.TW_START_MAX:
            s["started_above_limit"] += 1
        if ln.get("driver_error"):
            s["driver_errors"] += 1
    for s in out["windows"].values():
        for k in ("length_s", "time_wait_wait_s"):
            v = s.pop(k)
            s[k] = {"n": len(v), "sum": sum(v), "min": min(v), "max": max(v)} if v else {"n": 0}
    return out


# ---------------------------------------------------------------- the run


class Probe:
    """Runs the probe's windows and writes what item 6 of the entry allows (see the docstring)."""

    def __init__(self, a: argparse.Namespace, rates: dict[str, float], *, run_window=None, fingerprint=None,
                 warmup_s: float = sessions.JOB_WARMUP_S):
        self.a = a
        self.rates = rates
        self.run_window = run_window or wwindow.run_window
        self.fingerprint = fingerprint or wwindow.fingerprint
        self.warmup_s = warmup_s
        self.lines: list[dict] = []
        self.times = a.out / "probe-times.jsonl"
        self.raw = a.out / "raw-scratch"
        self.blocks = window.SourceBlocks(a.blocks)

    def write(self, line: dict) -> None:
        self.lines.append(line)
        with open(self.times, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    def reading(self, gid: str) -> dict:
        t0, w0 = time.monotonic(), time.time()
        fp = self.fingerprint()
        t1 = time.monotonic()
        self.write({"kind": "reading", "group": gid, "wall_start": w0, "length_s": t1 - t0, "pinned": fp.get("pinned")})
        return {"job": self.a.job, "id": gid, "fingerprint": fp, "lab_plan": fp.get("lab_plan"),
                "frequency": fp.get("frequency"), "cycle_rate": fp.get("cycle_rate")}

    def one(self, group: dict, session: dict, phase: str, index: int, position: int) -> dict:
        cfg = {"workload": group["workload"], "proto": group["proto"], "backend": "IOCP",
               "cell": f"probe.{group['workload']}.{group['proto']}.IOCP", "build": self.a.build, "k_src": self.a.k_src,
               "ports": {"A": PORT}, "functional": False}
        if group.get("rate") is not None:
            cfg["rate"] = group["rate"]
        shutil.rmtree(self.raw, ignore_errors=True)
        t0, w0 = time.monotonic(), time.time()
        try:
            row = self.run_window(cfg, session, "A", position, self.blocks, self.raw)
        finally:
            t1, w1 = time.monotonic(), time.time()
            shutil.rmtree(self.raw, ignore_errors=True)
        line = window_times(row, phase=phase, index=index, group=group, t0=t0, t1=t1, w0=w0, w1=w1)
        self.write(line)
        tw = line.get("time_wait_wait_s")
        print(f"{phase} {index} {group['workload']} {group['proto']}: {line['length_s']:.2f} s"
              + (f", TIME-WAIT wait {tw:.1f} s" if tw is not None else "")
              + (f", {line['driver_error']}" if line["driver_error"] else ""), flush=True)
        return line

    def run(self) -> None:
        warm = {"workload": "churn", "proto": "http1", "windows": 0, "rate": None}
        session = self.reading("warmup")
        t0, i = time.monotonic(), 0
        while time.monotonic() - t0 < self.warmup_s:
            self.one(warm, session, "warmup", i, i % 4)
            i += 1
        n = 0
        for g in groups(self.rates):
            session = self.reading(f"{g['workload']}.{g['proto']}")
            for k in range(g["windows"]):
                self.one(g, session, "probe", n, k)
                n += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True, help="the laptop's Release build of CODE_FREEZE's compiled inputs")
    ap.add_argument("--out", type=Path, required=True, help="a new or empty folder")
    ap.add_argument("--job", required=True)
    ap.add_argument("--pilot", type=Path, required=True, help="the pilot entry's output (lab/analysis-inputs/pilot.json)")
    ap.add_argument("--k-src", type=int, default=K_SRC)
    ap.add_argument("--blocks", type=Path, default=wrunlib.BLOCKS)
    a = ap.parse_args(argv)
    if a.out.exists() and any(a.out.iterdir()):
        raise SystemExit(f"wprobe: {a.out} is not empty")
    a.out.mkdir(parents=True, exist_ok=True)
    rates = pilot_rates(a.pilot)
    wrunlib.install_stop()
    head = subprocess.run(["git", "-C", str(HERE.parent.parent), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    summary: dict = {"job": a.job, "started": now(), "development": True,
                     "entry": "2026-10-23: A probe of window times on the laptop's Windows (a reading)",
                     "job_context": wrunlib.check_job_context(development=True), "provenance": waa.provenance(a.build),
                     "probe_commit": head, "readings": readings(), "rates_given": rates,
                     "placement": {"server_cpus": wwindow.SERVER_CPUS, "generator_cpus": wwindow.GEN_CPUS,
                                   "open_generator_threads": wwindow.OPEN_GEN_THREADS}}
    path = a.out / "probe-summary.json"
    path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if summary["readings"]["port_conflicts"]:
        print(f"wprobe: {summary['readings']['port_conflicts']}; no window runs", file=sys.stderr)
        return EXIT_PORTS
    probe = Probe(a, rates)
    rc = 0
    try:
        probe.run()
    except (KeyboardInterrupt, SystemExit) as e:
        summary["stopped"] = repr(e)
        rc = 130
    finally:
        summary["ended"] = now()
        summary["times"] = summarise(probe.lines)
        path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
