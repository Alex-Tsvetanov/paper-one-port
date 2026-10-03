#!/usr/bin/env python3
"""M4b-1 step 1, the development diagnostic of sslh-ev's stalled exchanges (not a window of any
cell; hypotheses.md revision log, "sslh-ev's stalled exchanges"): a front in its M3 configuration
in front of the stub, as handoff.py places them (front CPU 14, stub CPUs 10 and 12, opgen CPUs 2
to 9, C = 64), opgen for a 1 s warm-up and a short measure, and one of: a capture of loopback
traffic on the front's and the stub's ports (tcpdump on CPUs 0 and 1; pcap_flows.py reads it), an
strace of the front (strace_fds.py reads it), or perf trace -s. After opgen ends, a census of the
sockets left on the front's port and of the front's open descriptors. Run inside lab_job.sh (lab
lock, clock floor, NOTRACK). LIBEV_FLAGS in the environment reaches the front (libev's backend).

    stall_run.py --src DIR --build DIR --out DIR --proto http1|tls-stub --mode pcap|strace|trace|none
                 [--system sslh-ev] [--measure-ms 2000] [--opgen-timeout-ms 1000]
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--proto", default="http1", choices=("http1", "tls-stub"))
    ap.add_argument("--mode", default="pcap", choices=("pcap", "trace", "strace", "none"))
    ap.add_argument("--system", default="sslh-ev")
    ap.add_argument("--kind", default="m3")
    ap.add_argument("--measure-ms", type=int, default=2000)
    ap.add_argument("--opgen-timeout-ms", type=int, default=1000)
    a = ap.parse_args()
    sys.path.insert(0, str(a.src / "bench" / "run"))
    sys.path.insert(0, str(a.src / "bench" / "competitors"))
    import competitors as comp  # noqa: E402
    import handoff  # noqa: E402
    import window  # noqa: E402
    window.stop_on_signals()
    a.out.mkdir(parents=True, exist_ok=True)
    port, stub_port = 22100, 22110
    blocks = window.SourceBlocks(Path.home() / "lab" / "p3" / "src-blocks.json")
    base = blocks.take(16)
    res: dict = {"system": a.system, "proto": a.proto, "mode": a.mode, "src_block": window.dotted(base),
                 "fingerprint": window.pin_fingerprint(), "conntrack_wait_s": window.wait_conntrack()[0]}
    ns0 = window.nstat()
    res["time_wait_start"] = window.time_wait_count()
    stub, stub_out = handoff.start_stub(a.build, stub_port, a.out, "diag")
    front = cap = None
    try:
        front = handoff.Front(a.system, a.build, port, stub_port, a.out, "diag", a.kind)
        res["front_command"] = front.command
        res["front_pids"] = comp.group_pids(front.pgid)
        if a.mode == "pcap":
            filt = f"tcp port {port} or tcp portrange {stub_port}-{stub_port + 5}"
            cap = subprocess.Popen(["sudo", "-n", "taskset", "-c", "0,1", "tcpdump", "-i", "lo", "-nn", "-s", "128", "-B", "262144",
                                    "-w", str(a.out / "lo.pcap"), filt], stderr=open(a.out / "tcpdump.err", "wb"))
            time.sleep(1.5)
        elif a.mode == "strace":
            cap = subprocess.Popen(["sudo", "-n", "taskset", "-c", "0,1", "strace", "-f", "-tt", "-e",
                                    "trace=accept,accept4,close,epoll_ctl,epoll_wait,epoll_pwait,poll,select,socket,connect,read,write,shutdown",
                                    "-o", str(a.out / "strace.txt"), "-p", str(front.proc.pid)], stderr=open(a.out / "strace.err", "wb"))
            time.sleep(1.5)
        elif a.mode == "trace":
            pids = ",".join(map(str, comp.group_pids(front.pgid)))
            cap = subprocess.Popen(["sudo", "-n", "taskset", "-c", "0,1", "perf", "trace", "-s", "-p", pids, "-o", str(a.out / "trace.txt")],
                                   stderr=open(a.out / "trace.err", "wb"))
            time.sleep(1.5)
        gen = window.opgen_cmd(a.build, a.proto, port, base, 16)
        gen[gen.index("--timeout-ms") + 1] = str(a.opgen_timeout_ms)
        cmd = ["taskset", "-c", "2-9"] + gen + [
            "--cpus", "2,3,4,5,6,7,8,9", "--conns", "64", "--warmup-ms", "1000", "--duration-ms", str(a.measure_ms),
            "--out", str(a.out / "opgen.json")]
        res["opgen_cmd"] = cmd
        res["opgen_started"] = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        res["opgen_exit"] = p.returncode
        res["opgen_stderr"] = p.stderr[-500:]
        # The census after opgen has ended, before the front stops: sockets left on the front's port
        # and the front's open descriptors.
        time.sleep(1.0)
        census = {}
        for state in ("established", "close-wait", "syn-recv"):
            out = subprocess.run(["ss", "-Htn", "state", state, f"( sport = :{port} )"], capture_output=True, text=True).stdout
            census[state] = len([x for x in out.splitlines() if x.strip()])
        out = subprocess.run(["ss", "-Hltn", f"( sport = :{port} )"], capture_output=True, text=True).stdout
        census["listen_line"] = out.strip()
        census["backend_sockets_of_front"] = {}
        for state in ("established", "close-wait", "syn-sent"):
            out = subprocess.run(["ss", "-Htn", "state", state, f"( dport >= :{stub_port} and dport <= :{stub_port + 5} )"],
                                 capture_output=True, text=True).stdout
            census["backend_sockets_of_front"][state] = len([x for x in out.splitlines() if x.strip()])
        try:
            census["front_fds"] = {pid: len(os.listdir(f"/proc/{pid}/fd")) for pid in comp.group_pids(front.pgid)}
        except OSError as e:
            census["front_fds"] = repr(e)
        res["census"] = census
    finally:
        if cap is not None:
            time.sleep(0.5)
            subprocess.run(["sudo", "-n", "kill", "-INT", str(cap.pid)], check=False)
            # sudo's child: signal it through sudo's process (sudo relays SIGINT to its command)
            try:
                cap.wait(timeout=30)
            except subprocess.TimeoutExpired:
                subprocess.run(["sudo", "-n", "kill", "-KILL", str(cap.pid)], check=False)
        if front is not None:
            res["front_alive_at_end"] = front.alive()
            res["front_exit"] = front.stop()[0]
        window.stop_process(stub, stub_out)
        blocks.release(base)
    ns1 = window.nstat()
    res["nstat_delta"] = {k: ns1[k] - ns0[k] for k in window.NSTAT_KEYS}
    res["time_wait_end"] = window.time_wait_count()
    g = json.loads((a.out / "opgen.json").read_text()) if (a.out / "opgen.json").exists() else {}
    res["opgen"] = {k: g.get(k) for k in ("measure", "warmup", "wall_s", "error_share", "connect_failures", "ttfb_ns")}
    (a.out / "diag.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res.get(k) for k in ("system", "proto", "mode", "nstat_delta", "census", "opgen")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
