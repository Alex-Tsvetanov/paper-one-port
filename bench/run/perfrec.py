#!/usr/bin/env python3
"""A profile of a front of M3 under its load (M5, item 4: "Profile the relay path"): the server's
one-port relay or a proxy in its M3 configuration, in front of the stub, in section 4.1's hand-off
placement, with opgen's closed loop at C = 64 (WL1) for a warm-up and then PERF_S seconds of
`perf record -g` on the front's processes. Development data, journaled as such: it profiles, it
times no cell, and its rate is recorded only beside the profile (perf slows what it samples).

Build the server with frame pointers for the call chains (a profiling build, never a measured
one): CMAKE_CXX_FLAGS_RELEASE="-O3 -DNDEBUG -g -fno-omit-frame-pointer".

    perfrec.py --build DIR --out DIR --job NAME --system one-port-relay|nginx|... --proto http1|tls-stub
               [--detect replay|peek] [--seconds 4]
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

import competitors as comp  # noqa: E402
import handoff  # noqa: E402
import window  # noqa: E402

PL = window.HANDOFF
PORT = 24200  # a design choice of M5, off the ephemeral range and apart from the other runners' ports; the stub 10 above
WARM_S = 1.5
FREQ = 4999
PERF = ["sudo", "-n", "taskset", "-c", "0,1", "perf"]


def report(data: Path, out: Path) -> None:
    """perf report's flat profile by symbol and by shared object, as text beside perf.data."""
    for name, sort in (("by_symbol", "sym"), ("by_dso", "dso"), ("by_dso_symbol", "dso,sym")):
        with open(out / f"{data.stem}.{name}.txt", "w") as f:
            subprocess.run(PERF + ["report", "-f", "--stdio", "-i", str(data), "--no-children", "--percent-limit", "0.3",
                                       "--sort", sort], stdout=f, stderr=subprocess.STDOUT, check=False)
    with open(out / f"{data.stem}.callers.txt", "w") as f:
        subprocess.run(PERF + ["report", "-f", "--stdio", "-i", str(data), "--children", "--percent-limit", "2",
                                   "--sort", "sym", "-G"], stdout=f, stderr=subprocess.STDOUT, check=False)


def main(argv=None) -> int:
    window.stop_on_signals()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--system", required=True, choices=(window.ONE_PORT_RELAY,) + comp.ORDER)
    ap.add_argument("--proto", required=True, choices=handoff.M3_PROTOS)
    ap.add_argument("--detect", default="replay", choices=handoff.DETECTS)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--k-src", type=int, default=16)
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    tag = f"{a.job}-{a.system}-{a.proto}" + (f"-{a.detect}" if a.system == window.ONE_PORT_RELAY and a.detect != "replay" else "")
    row: dict = {"job": a.job, "kind": "perf record", "development": True, "system": a.system, "proto": a.proto,
                 "detect": a.detect if a.system == window.ONE_PORT_RELAY else None, "tag": tag, "freq": FREQ, "seconds": a.seconds,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "fingerprint": window.pin_fingerprint()}
    blocks = window.SourceBlocks(a.blocks)
    base = blocks.take(a.k_src)
    row["conntrack_wait_s"], _ = window.wait_conntrack()
    stub, stub_out = handoff.start_stub(a.build, PORT + 10, a.out, tag)
    front = None
    data = a.out / f"{tag}.perf.data"
    try:
        front = handoff.Front(a.system, a.build, PORT, PORT + 10, a.out, tag, "m3", "epoll", a.detect)
        row["front_command"] = front.command
        row["probe"] = window.probe(a.build, a.proto, PORT, base, a.k_src, PL.gen)
        dur_ms = int((WARM_S + a.seconds + 1.5) * 1000)
        out_json = a.out / f"{tag}.opgen.json"
        gen = subprocess.Popen(["taskset", "-c", ",".join(map(str, PL.gen))] + window.opgen_cmd(a.build, a.proto, PORT, base, a.k_src) + [
            "--cpus", ",".join(map(str, PL.gen)), "--conns", str(window.CONNS_PER_CORE), "--warmup-ms", "0", "--duration-ms", str(dur_ms),
            "--out", str(out_json)], stdout=subprocess.DEVNULL, stderr=open(a.out / f"{tag}.opgen.err", "wb"))
        time.sleep(WARM_S)
        pids = comp.group_pids(front.pgid)
        rec = subprocess.run(PERF + ["record", "-g", "-F", str(FREQ), "-p", ",".join(map(str, pids)), "-o", str(data), "--", "sleep",
                                     str(a.seconds)], capture_output=True, text=True, timeout=a.seconds + 60)
        row["perf_record_exit"] = rec.returncode
        row["perf_record_stderr"] = rec.stderr[-600:]
        gen.wait(timeout=dur_ms / 1000 + 30)
        row["opgen_exit"] = gen.returncode
        g = json.loads(out_json.read_text()) if out_json.exists() else {}
        m = g.get("measure") or {}
        wall = g.get("wall_s") or 0
        row["opgen"] = {"ok": g.get("ok"), "completed": m.get("completed"), "errors": (m.get("errors") or {}).get("total"),
                        "per_s_under_perf": m.get("completed", 0) / wall if wall else None}
    finally:
        if front is not None:
            _, lines = front.stop()
            row["front_counters"] = window.parse_counters(lines) if a.system == window.ONE_PORT_RELAY else None
        window.stop_process(stub, stub_out)
        blocks.release(base)
    if data.exists():
        subprocess.run(["sudo", "-n", "chown", f"{Path.home().owner()}:", str(data)], check=False)
        report(data, a.out)
    with open(a.out / "perf.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    print(f"{tag}: perf exit {row.get('perf_record_exit')} opgen {row.get('opgen')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
