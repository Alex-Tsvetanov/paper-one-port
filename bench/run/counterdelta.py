#!/usr/bin/env python3
"""The server's counters per connection, one-port mode against dedicated mode, from section 10's
untimed counter checks (bench/run/systrace.py --kind cost): M5's criterion 1 (design/status.md,
"M5 exit criteria"). Untimed: no rate, no time, never a window.

Per row, the counters of the load alone are the row's counters less those of its idle pass (the
same arm started, attached, stopped with no load: the listeners' registrations, the ring's first
submissions and the stop's cancels), divided by the connections the server accepted (for
keep-alive also by the requests: opgen's completed requests and the probe's one). Per cell and
detection mode, one-port's mean per connection less dedicated's is each counter's delta. A counter
is "equal" when every row of both arms has the same value per connection; "within the spread" when
the two arms' ranges over the repeats overlap (the counters that depend on timing: a read or an
accept that finds nothing, a read on to EOF when the peer's FIN came with its last bytes, a wait
that serves several connections); "differs" otherwise. The server's relay (--kind proxy rows of
one-port-relay) has no dedicated counterpart, since only a detecting listener relays: its rows
compare peek with replay per relayed connection instead.

The counters: the system calls I29 counts (accept, recv, peek, the check of 1(b), send,
setsockopt, epoll_ctl, connect, shutdown, splice), the loop's waits (epoll_wait, io_uring_enter),
io_uring's submissions by opcode ("ring:<op>"), and the payload bytes copied in user space
(bytes_copied); beside them SO_RCVLOWAT's sets and resets, the receive retries and the waits for
writability.

    counterdelta.py TRACE.jsonl [TRACE.jsonl ...] [--out FILE.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

SYSCALLS = ("accept_calls", "recv_calls", "peek_calls", "check_calls", "send_calls", "setsockopt_calls", "epoll_ctl_calls",
            "connect_calls", "shutdown_calls", "splice_calls")
WAITS = ("epoll_wait_calls", "io_uring_enter_calls")
COPIES = ("bytes_copied",)
BESIDE = ("lowat_sets", "lowat_resets", "recv_retries", "out_waits", "bytes_received", "bytes_peeked", "bytes_sent")
COUNTERS = SYSCALLS + WAITS + COPIES + BESIDE


def load_counters(row: dict) -> dict[str, float]:
    """A row's counters less its idle pass's, with io_uring's submissions by opcode as ring:<op>."""
    full = row.get("server_counters") or {}
    idle = (row.get("idle") or {}).get("server_counters") or {}
    out: dict[str, float] = {}
    for k in COUNTERS + ("accepted",):
        out[k] = float(full.get(k, 0) or 0) - float(idle.get(k, 0) or 0)
    ops = set((full.get("io_uring_submissions") or {})) | set((idle.get("io_uring_submissions") or {}))
    for op in sorted(ops):
        out[f"ring:{op}"] = float((full.get("io_uring_submissions") or {}).get(op, 0)) - float((idle.get("io_uring_submissions") or {}).get(op, 0))
    return out


def requests(row: dict) -> float | None:
    """Keep-alive: the requests opgen completed and the probe's one."""
    g = row.get("opgen") or {}
    if g.get("warmup") is None or g.get("measure") is None:
        return None
    return float(g["warmup"]) + float(g["measure"]) + 1.0


def per_unit(row: dict, unit: str = "connection") -> dict[str, float] | None:
    c = load_counters(row)
    n = c.get("accepted", 0.0) if unit == "connection" else (requests(row) or 0.0)
    if n <= 0:
        return None
    return {k: v / n for k, v in c.items() if k != "accepted"}


def compare(a_rows: list[dict], b_rows: list[dict], unit: str = "connection") -> dict[str, dict]:
    """Per counter: arm b's mean per unit less arm a's, each arm's values over its rows, and the
    verdict (equal, within the spread, differs)."""
    pa = [p for p in (per_unit(r, unit) for r in a_rows) if p is not None]
    pb = [p for p in (per_unit(r, unit) for r in b_rows) if p is not None]
    out: dict[str, dict] = {}
    if not pa or not pb:
        return out
    keys = sorted(set().union(*pa, *pb), key=lambda k: (k.startswith("ring:"), k))
    for k in keys:
        va = [p.get(k, 0.0) for p in pa]
        vb = [p.get(k, 0.0) for p in pb]
        delta = statistics.fmean(vb) - statistics.fmean(va)
        if len(set(round(v, 9) for v in va + vb)) == 1:
            verdict = "equal"
        elif min(vb) <= max(va) and min(va) <= max(vb):
            verdict = "within the spread"
        else:
            verdict = "differs"
        out[k] = {"a": va, "b": vb, "delta": delta, "verdict": verdict}
    return out


def cost_report(rows: list[dict]) -> dict:
    """One-port against dedicated per cell and detection mode."""
    groups: dict[tuple[str, str], dict[str, list[dict]]] = {}
    for r in rows:
        if r.get("kind") != "cost":
            continue
        groups.setdefault((r["cell"], r.get("detect") or "replay"), {}).setdefault(r["mode"], []).append(r)
    out = {}
    for (cell, detect), arms in sorted(groups.items()):
        if "dedicated" not in arms or "one-port" not in arms:
            continue
        entry = {"cell": cell, "detect": detect, "rows": {m: len(v) for m, v in arms.items()},
                 "accepted": {m: [load_counters(r).get("accepted") for r in v] for m, v in arms.items()},
                 "per_connection": compare(arms["dedicated"], arms["one-port"])}
        if cell.startswith("keepalive."):
            entry["per_request"] = compare(arms["dedicated"], arms["one-port"], "request")
        out[f"{cell}.{detect}"] = entry
    return out


def relay_report(rows: list[dict]) -> dict:
    """The server's relay, peek against replay, per connection the relay accepted."""
    groups: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        if r.get("kind") == "proxy" and r.get("system") == "one-port-relay":
            groups.setdefault(f"{r['proto']}.{r.get('backend') or 'epoll'}", {}).setdefault(r.get("detect") or "replay", []).append(r)
    return {f"relay.{key}": {"proto": key.split(".")[0], "backend": key.split(".")[1], "rows": {d: len(v) for d, v in arms.items()},
                             "per_connection": compare(arms.get("replay", []), arms.get("peek", []))}
            for key, arms in sorted(groups.items()) if arms.get("replay") and arms.get("peek")}


def relay_alone(rows: list[dict]) -> dict:
    """The relay's counters per relayed connection, each detection mode alone (no comparison)."""
    out = {}
    for r in rows:
        if r.get("kind") == "proxy" and r.get("system") == "one-port-relay":
            p = per_unit(r)
            if p:
                out.setdefault(f"relay.{r['proto']}.{r.get('backend') or 'epoll'}.{r.get('detect') or 'replay'}", []).append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("traces", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    rows = [json.loads(ln) for t in a.traces for ln in t.read_text().splitlines() if ln.strip()]
    report = {"cost": cost_report(rows), "relay": relay_report(rows), "relay_alone": relay_alone(rows)}
    if a.out:
        a.out.write_text(json.dumps(report, indent=1))
    for name, e in {**report["cost"], **report["relay"]}.items():
        unit = "per_request" if "per_request" in e else "per_connection"
        print(f"== {name} rows {e['rows']} ({unit.replace('_', ' ')}; a dedicated or replay, b one-port or peek)")
        for k, v in e[unit].items():
            if v["verdict"] != "equal" or abs(v["delta"]) > 0:
                print(f"   {k:24s} delta {v['delta']:+.4f}  {v['verdict']:18s} a {[round(x, 4) for x in v['a']]} b {[round(x, 4) for x in v['b']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
