#!/usr/bin/env python3
"""One window in WL7's layout (hypotheses.md, section 3, WL7; section 7): the ophold window that
K_BASE is made of, and the frame every B3 window will use.

Phases, from WL7 (each a design choice of the frozen text):
  - before t = 0: fresh processes (the holder on CPU 14), the probe (its client closes by reset),
    a baseline reading;
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

    b3.py --build DIR --out DIR --job NAME [--case silent] [--n 10000]
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

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


def run(build: Path, out: Path, job: str, case: str, n: int, blocks_file: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    row: dict = {"job": job, "kind": "ophold", "case": case, "n_pend": n, "development": True, "system_cpus": SYSTEM_CPUS,
                 "opcase_cpus": OPCASE_CPUS, "port": OPHOLD_PORT, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    row["gap_wait_s"] = wait_after_other_windows(blocks_file)
    row["conntrack_wait_s"], _ = window.wait_conntrack()
    row["time_wait_wait_s"], row["time_wait_before"] = wait_time_wait_zero()
    row["fingerprint"] = window.pin_fingerprint()
    ns0 = window.nstat()
    hold = subprocess.Popen(["taskset", "-c", ",".join(map(str, SYSTEM_CPUS)), str(build / "bench" / "cases" / "ophold"), "--port",
                             str(OPHOLD_PORT), "--backlog", str(n)], stdout=subprocess.PIPE, start_new_session=True)
    hold_out = window.Lines(hold)
    reasons: list[str] = []
    try:
        if not hold_out.until(lambda ln: ln.startswith("ophold: listening"), 10.0):
            raise window.WindowError(f"ophold did not start: {hold_out.lines}")
        probe = subprocess.run(["taskset", "-c", ",".join(map(str, OPCASE_CPUS)), str(build / "bench" / "cases" / "opcase"), "probe-reset",
                                "--port", str(OPHOLD_PORT)], capture_output=True, text=True, timeout=10)
        row["probe_exit"] = probe.returncode
        if probe.returncode != 0:
            reasons.append("probe failed")
        time.sleep(0.5)  # the probe's reset reaches the holder before the baseline
        base = fp.read([hold.pid], OPHOLD_PORT)
        opener = subprocess.Popen(["taskset", "-c", ",".join(map(str, OPCASE_CPUS)), str(build / "bench" / "cases" / "opcase"), "open",
                                   "--port", str(OPHOLD_PORT), "--case", case, "--n", str(n), "--close-at-ms", str(int(T_CLOSE * 1000))],
                                  stdout=subprocess.PIPE)
        op_out = window.Lines(opener)
        if not op_out.until(lambda ln: ln.startswith("T0 "), 10.0):
            raise window.WindowError("opcase printed no T0")
        t0_ns = int(op_out.lines[-1].split()[1])  # CLOCK_MONOTONIC, the clock of time.monotonic_ns()

        def at(t: float) -> None:
            left = t0_ns / 1e9 + t - time.monotonic_ns() / 1e9
            if left > 0:
                time.sleep(left)

        at(T_SAMPLE1)
        s1 = fp.read([hold.pid], OPHOLD_PORT)
        at(T_SAMPLE2)
        s2 = fp.read([hold.pid], OPHOLD_PORT)
        op_lines = op_out.rest(T_CLOSE + 30)
        opener.wait(timeout=30)
        row["opcase_exit"] = opener.returncode
        row["opcase"] = json.loads(op_lines[-1]) if op_lines and op_lines[-1].startswith("{") else None
        if opener.returncode != 0:
            reasons.append(f"opcase exit {opener.returncode}")
    finally:
        if hold.poll() is None:
            os.killpg(hold.pid, signal.SIGTERM)
        hold_lines = hold_out.rest(10)
        hold.wait(timeout=10)
    row["ophold_lines"] = hold_lines[-2:]
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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--case", default="silent", choices=("silent", "partial-hello"))
    ap.add_argument("--n", type=int, default=fp.N_PEND)
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    a = ap.parse_args(argv)
    row = run(a.build, a.out, a.job, a.case, a.n, a.blocks)
    with open(a.out / "windows.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    f2 = row["footprint"]["sample2"]
    print(f"ophold {a.case}: valid={row['valid']} {'; '.join(row['invalid_reasons'])}")
    print(f"  U {f2['U']:.1f}  Kq {f2['Kq']:.1f}  Ks {f2['Ks']:.1f}  W {f2['W']:.1f} bytes per pending connection; "
          f"established {f2['established']}; skb growth {f2['skb_growth']}; shared cache growth {f2['shared_growth']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
