#!/usr/bin/env python3
"""Ask the kernel how many listening sockets the gated oneport binary holds (P3's kernel census).

This replays, on the laptop, the census of the revision-log entry "2026-10-22: Computer
Communications, and the kernel listening-descriptor census" (item 2, on the branch
dev/alex-tsvetanov/comcom-manuscript, bb473a4), with the rows of that entry's tool,
paper/census_listen.py at bb473a4. The measured Release binary, found by the sha256 its host's gate
names, is started with no client and no load. It binds 127.0.0.1 only. The count is the kernel's:

- Linux: the rows of `ss -Hltnp` for the server's process. A second kernel source checks them:
  the rows of /proc/net/tcp and /proc/net/tcp6 in state 0A (LISTEN) whose inode is a socket of
  the process (/proc/<pid>/fd).
- Windows: netstat's LISTENING rows for the process (`netstat -ano -p tcp`, and `-p tcpv6`, which
  must hold none). GetExtendedTcpTable (TCP_TABLE_OWNER_PID_LISTENER, AF_INET and AF_INET6) must
  list the same addresses.

The server's own "listening" lines are stored beside the count and are not the count.

Read-only on the host: no setting is changed, nothing is installed, no connection is opened, and
the only process started is the gated binary, which is stopped at the end of each run (SIGTERM on
Linux; on Windows its stop event "Local\\oneport-stop-<pid>"). Nothing is timed. Standard library
only. Every file it writes is under --out: census.json and raw/ (each run's stdout and stderr, and
the kernel tools' raw text). A run outside a lab job (no LAB_JOB_ID) is marked a functional test,
and paper/laptop_w/census_lw.py refuses it.

    python3 -I paper/laptop_w/census_host.py linux --binary B --gate G --gate-sha256 S --out DIR
    python -I paper\\laptop_w\\census_host.py windows --binary B --gate G --gate-sha256 S --out DIR

Exit 0: every run listened and its two kernel sources agree. Exit 2: refused before any run (the
binary or the gate is not the expected one, or the wrong OS). Exit 3: a run failed or its sources
disagree. census.json is written in every case.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = {"linux": "L", "windows": "W"}
LOOPBACK = "127.0.0.1"
READY_LINE = "oneport: connection state"
LISTEN_LINE = "oneport: listening "
READY_TIMEOUT_S = 15.0
SETTLE_S = 0.2
STOP_TIMEOUT_S = 10.0
KILL_TIMEOUT_S = 5.0
TOOL_TIMEOUT_S = 20.0
DEDICATED_PORTS = 6  # HTTP/1.1, h2c, TLS, MQTT, SSH and SMTP, on consecutive ports


@dataclass(frozen=True)
class Run:
    mode: str
    backend: str
    listener: str
    workers: int
    port: int

    def ports(self) -> list[int]:
        n = DEDICATED_PORTS if self.mode == "dedicated" else 1
        return [self.port + i for i in range(n)]


# The rows of paper/census_listen.py at bb473a4, with its ports.
RUNS = {
    "linux": (
        Run("one-port", "epoll", "shared", 1, 19080),
        Run("dedicated", "epoll", "shared", 1, 19100),
        Run("one-port", "epoll", "reuseport", 2, 19200),
        Run("one-port", "io_uring", "shared", 1, 19300),
        Run("dedicated", "io_uring", "shared", 1, 19400),
    ),
    "windows": (
        Run("one-port", "IOCP", "shared", 1, 19080),
        Run("dedicated", "IOCP", "shared", 1, 19100),
    ),
}


class Refused(Exception):
    """A check before any run failed: nothing was started."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read_head(root: Path) -> str | None:
    """The clone's HEAD commit, read from its files (git may not be on PATH in a lab job)."""
    try:
        dot = root / ".git"
        gitdir = dot
        if dot.is_file():
            gitdir = (root / dot.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        common = gitdir
        if (gitdir / "commondir").is_file():
            common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
        for base in (gitdir, common):
            if (base / ref).is_file():
                return (base / ref).read_text(encoding="utf-8").strip()
        for line in (common / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    except (OSError, IndexError):
        return None
    return None


def check_gate(os_name: str, binary: Path, gate: Path, gate_sha256: str) -> dict:
    """The gate's sha256, host and verdict, and the binary's sha256 against the gate's oneport."""
    if not gate.is_file():
        raise Refused(f"no gate file at {gate}")
    got_gate = sha256_file(gate)
    if got_gate != gate_sha256:
        raise Refused(f"the gate {gate} has sha256 {got_gate}, not {gate_sha256}")
    doc = json.loads(gate.read_text(encoding="utf-8"))
    if doc.get("host") != HOST[os_name]:
        raise Refused(f"the gate names host {doc.get('host')!r}, not {HOST[os_name]}")
    if doc.get("passed") is not True or doc.get("citable") is not True or doc.get("dry_run") is not False:
        raise Refused("the gate is not a passed, citable, non-dry-run gate")
    names = {doc.get("binaries", {}).get("oneport"), doc.get("oneport", {}).get("binaries", {}).get("oneport")}
    names.discard(None)
    if len(names) != 1:
        raise Refused(f"the gate names {len(names)} different oneport binaries, not one")
    want = names.pop()
    if not binary.is_file():
        raise Refused(f"no binary at {binary}")
    got = sha256_file(binary)
    if got != want:
        raise Refused(f"the binary {binary} has sha256 {got}, not the gate's oneport {want}")
    return {"gate": str(gate), "gate_sha256": got_gate, "gate_host": doc["host"],
            "gate_records_dir": doc.get("records_dir"), "binary": str(binary), "binary_sha256": got,
            "gate_oneport_sha256": want}


def tool(cmd: list[str], raw: Path, encoding: str = "utf-8") -> str:
    """Run a read-only tool, keep its text in raw/, and return it."""
    p = subprocess.run(cmd, capture_output=True, timeout=TOOL_TIMEOUT_S, check=False)
    text = p.stdout.decode(encoding, errors="replace")
    raw.write_text(f"$ {' '.join(cmd)}\n# exit {p.returncode}\n{text}", encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} exited {p.returncode}: {p.stderr.decode(encoding, errors='replace')[:400]}")
    return text


def norm_local(text: str) -> str:
    """127.0.0.1:19080 or [::1]:19080, with an interface suffix (%lo) removed."""
    host, port = text.rsplit(":", 1)
    host = host.strip("[]").split("%", 1)[0]
    addr = ipaddress.ip_address(host)
    return f"[{addr}]:{int(port)}" if addr.version == 6 else f"{addr}:{int(port)}"


# ---- Linux ----------------------------------------------------------------------------------

def parse_ss(text: str, pid: int) -> list[dict]:
    """The rows of `ss -Hltnp` whose process field names the pid."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        pids = {int(x) for x in re.findall(r"pid=(\d+),", line)}
        if pid not in pids:
            continue
        parts = line.split()
        rows.append({"line": line, "state": parts[0], "local": norm_local(parts[3])})
    return rows


def decode_proc_addr(field: str) -> str:
    """0100007F:4A38 -> 127.0.0.1:19000; the 32-digit IPv6 form likewise (each 32-bit word in host order)."""
    hexaddr, hexport = field.split(":")
    raw = bytes.fromhex(hexaddr)
    words = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    addr = ipaddress.ip_address(words)
    port = int(hexport, 16)
    return f"[{addr}]:{port}" if addr.version == 6 else f"{addr}:{port}"


def parse_proc_net(text: str, inodes: set[int]) -> list[dict]:
    """Rows of /proc/net/tcp or tcp6 in state 0A (LISTEN) whose inode is one of the process's sockets."""
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 10 or parts[3] != "0A":
            continue
        inode = int(parts[9])
        if inode in inodes:
            rows.append({"local": decode_proc_addr(parts[1]), "inode": inode})
    return rows


def socket_inodes(pid: int) -> set[int]:
    out = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    for fd in fd_dir.iterdir():
        try:
            m = re.fullmatch(r"socket:\[(\d+)\]", os.readlink(fd))
        except OSError:
            continue
        if m:
            out.add(int(m.group(1)))
    return out


def read_linux(pid: int, raw: Path, tag: str) -> dict:
    ss_text = tool(["ss", "-Hltnp"], raw / f"{tag}.ss.txt")
    inodes = socket_inodes(pid)
    v4 = Path("/proc/net/tcp").read_text(encoding="utf-8")
    v6 = Path("/proc/net/tcp6").read_text(encoding="utf-8") if Path("/proc/net/tcp6").exists() else ""
    (raw / f"{tag}.proc-net-tcp.txt").write_text(v4, encoding="utf-8")
    (raw / f"{tag}.proc-net-tcp6.txt").write_text(v6, encoding="utf-8")
    ss_rows = parse_ss(ss_text, pid)
    proc_rows = parse_proc_net(v4, inodes) + parse_proc_net(v6, inodes)
    return {"ss": ss_rows, "proc_net_tcp": proc_rows, "socket_inodes": len(inodes),
            "kernel_listen_count": len(ss_rows),
            "v6_rows": [r for r in ss_rows if r["local"].startswith("[")],
            "agree": sorted(r["local"] for r in ss_rows) == sorted(r["local"] for r in proc_rows)}


# ---- Windows --------------------------------------------------------------------------------

def parse_netstat(text: str, pid: int) -> tuple[list[dict], list[dict]]:
    """netstat -ano's TCP rows of the pid: (LISTENING rows, every other row of the pid)."""
    listening, other = [], []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 5 or parts[0] != "TCP" or parts[4] != str(pid):
            continue
        row = {"local": norm_local(parts[1]), "foreign": parts[2], "state": parts[3]}
        (listening if parts[3] == "LISTENING" else other).append(row)
    return listening, other


def parse_tcp_table(raw: bytes, af: int, pid: int) -> list[dict]:
    """MIB_TCPTABLE_OWNER_PID (AF_INET, 24-byte rows) or MIB_TCP6TABLE_OWNER_PID (AF_INET6, 56-byte
    rows): the rows of the pid in state MIB_TCP_STATE_LISTEN (2)."""
    n = int.from_bytes(raw[0:4], "little")
    rows = []
    for i in range(n):
        if af == 2:
            off = 4 + 24 * i
            state = int.from_bytes(raw[off:off + 4], "little")
            addr = ipaddress.IPv4Address(raw[off + 4:off + 8])
            port = int.from_bytes(raw[off + 8:off + 10], "big")
            owner = int.from_bytes(raw[off + 20:off + 24], "little")
            local = f"{addr}:{port}"
        else:
            off = 4 + 56 * i
            addr6 = ipaddress.IPv6Address(raw[off:off + 16])
            port = int.from_bytes(raw[off + 20:off + 22], "big")
            state = int.from_bytes(raw[off + 48:off + 52], "little")
            owner = int.from_bytes(raw[off + 52:off + 56], "little")
            local = f"[{addr6}]:{port}"
        if owner == pid and state == 2:
            rows.append({"local": local, "state": "LISTEN"})
    return rows


def tcp_table(af: int) -> bytes:
    import ctypes
    from ctypes import wintypes

    iphlpapi = ctypes.WinDLL("iphlpapi")
    fn = iphlpapi.GetExtendedTcpTable
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG,
                   ctypes.c_int, wintypes.ULONG]
    fn.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    fn(None, ctypes.byref(size), False, af, 3, 0)  # 3: TCP_TABLE_OWNER_PID_LISTENER
    for _ in range(5):
        buf = ctypes.create_string_buffer(size.value + 65536)
        size = wintypes.DWORD(len(buf))
        rc = fn(buf, ctypes.byref(size), False, af, 3, 0)
        if rc == 0:
            return buf.raw
        if rc != 122:  # ERROR_INSUFFICIENT_BUFFER
            raise OSError(rc, "GetExtendedTcpTable")
    raise OSError(122, "GetExtendedTcpTable: the table kept growing")


def read_windows(pid: int, raw: Path, tag: str) -> dict:
    v4_text = tool(["netstat", "-ano", "-p", "tcp"], raw / f"{tag}.netstat-tcp.txt", "oem")
    v6_text = tool(["netstat", "-ano", "-p", "tcpv6"], raw / f"{tag}.netstat-tcpv6.txt", "oem")
    v4, v4_other = parse_netstat(v4_text, pid)
    v6, v6_other = parse_netstat(v6_text, pid)
    api = parse_tcp_table(tcp_table(2), 2, pid) + parse_tcp_table(tcp_table(23), 23, pid)
    netstat_rows = v4 + v6
    return {"netstat": netstat_rows, "netstat_other_rows": v4_other + v6_other,
            "get_extended_tcp_table": api, "kernel_listen_count": len(v4),
            "v6_rows": v6 + [r for r in api if r["local"].startswith("[")],
            "agree": (not v4_other and not v6_other
                      and sorted(r["local"] for r in netstat_rows) == sorted(r["local"] for r in api))}


def excluded_ranges() -> list[list[int]]:
    """netsh's excluded IPv4 TCP port ranges (read only)."""
    p = subprocess.run(["netsh", "int", "ipv4", "show", "excludedportrange", "protocol=tcp"],
                       capture_output=True, timeout=TOOL_TIMEOUT_S, check=False)
    text = p.stdout.decode("oem", errors="replace")
    return [[int(a), int(b)] for a, b in re.findall(r"^\s*(\d+)\s+(\d+)\s*\*?\s*$", text, re.M)]


def stop_windows(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenEventW.restype = wintypes.HANDLE
    k32.SetEvent.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenEventW(0x0002, False, f"Local\\oneport-stop-{pid}")  # EVENT_MODIFY_STATE
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenEventW")
    try:
        if not k32.SetEvent(handle):
            raise OSError(ctypes.get_last_error(), "SetEvent")
    finally:
        k32.CloseHandle(handle)


# ---- one run --------------------------------------------------------------------------------

def wait_ready(out: Path, proc: subprocess.Popen) -> str:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        if READY_LINE in text or proc.poll() is not None:
            return text
        time.sleep(0.05)
    return out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""


def stop(os_name: str, proc: subprocess.Popen) -> str:
    """Stop the server as its harnesses do; kill it only if that fails. Returns how it stopped."""
    if proc.poll() is not None:
        return "exited by itself"
    try:
        if os_name == "windows":
            stop_windows(proc.pid)
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=STOP_TIMEOUT_S)
        return "stop event" if os_name == "windows" else "SIGTERM"
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        proc.wait(timeout=KILL_TIMEOUT_S)
        return "killed"


def one_run(os_name: str, binary: Path, run: Run, raw: Path, reader, launcher: tuple[str, ...] = ()) -> dict:
    """Start the binary for one row, read the kernel once it is ready, stop it. launcher is for tests
    only (an interpreter in front of a stand-in script); a lab job never sets it."""
    tag = f"{run.backend}-{run.mode}-{run.listener}-{run.workers}"
    out, err = raw / f"{tag}.stdout.txt", raw / f"{tag}.stderr.txt"
    cmd = [*launcher, str(binary), "--mode", run.mode, "--detect", "replay", "--dispatch", "inproc",
           "--backend", run.backend, "--listener", run.listener, "--workers", str(run.workers),
           "--port", str(run.port)]
    rec = {"mode": run.mode, "backend": run.backend, "listener": run.listener, "workers": run.workers,
           "port": run.port, "ports": run.ports(), "command": cmd, "started": now()}
    kernel, problem = None, None
    with open(out, "w", encoding="utf-8") as so, open(err, "w", encoding="utf-8") as se:
        proc = subprocess.Popen(cmd, stdout=so, stderr=se, stdin=subprocess.DEVNULL)
        rec["pid"] = proc.pid
        try:
            text = wait_ready(out, proc)
            if proc.poll() is not None or READY_LINE not in text:
                problem = "the server did not reach its ready line"
            else:
                time.sleep(SETTLE_S)
                kernel = reader(proc.pid, raw, tag)
        except Exception as e:  # recorded, never swallowed: the run fails and the job exits 3
            problem = f"{type(e).__name__}: {e}"
        finally:
            rec["stopped_by"] = stop(os_name, proc)
    rec["exit_code"] = proc.returncode
    text = out.read_text(encoding="utf-8", errors="replace")
    rec["server_lines"] = [ln.strip() for ln in text.splitlines() if ln.startswith(LISTEN_LINE)]
    rec["server_listening_lines"] = len(rec["server_lines"])
    rec["server_stop_output"] = [ln for ln in text.splitlines() if not ln.startswith(("oneport: listening", READY_LINE))]
    rec["stderr"] = err.read_text(encoding="utf-8", errors="replace")[-2000:]
    rec["ended"] = now()
    if kernel is not None:
        rec.update(kernel)
        locals_ = {r["local"] for r in kernel.get("ss", kernel.get("netstat", []))}
        if not locals_ <= {f"{LOOPBACK}:{p}" for p in run.ports()}:
            problem = f"listening addresses outside {LOOPBACK} and the run's ports: {sorted(locals_)}"
        elif not kernel["agree"]:
            problem = "the two kernel sources disagree"
        elif kernel["v6_rows"]:
            problem = "the process holds IPv6 listening sockets"
    rec["problem"] = problem
    rec["ok"] = problem is None and rec["stopped_by"] in ("SIGTERM", "stop event") and proc.returncode == 0
    return rec


def write_json(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def census(os_name: str, binary: Path, gate: Path, gate_sha256: str, out_dir: Path,
           runs=None, reader=None, skip_os_check: bool = False, launcher: tuple[str, ...] = ()) -> int:
    """The census of one host into out_dir/census.json. runs, reader, skip_os_check and launcher are
    for tests only; main() never sets them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "census.json"
    if target.exists():
        print(f"census: {target} exists; nothing is overwritten", file=sys.stderr)
        return 2
    raw = out_dir / "raw"
    raw.mkdir(exist_ok=True)
    job = os.environ.get("LAB_JOB_ID") or None
    doc = {
        "what": "P3's kernel census: listening sockets of the gated oneport binary, no client, no load",
        "definition": "revision-log entry '2026-10-22: Computer Communications, and the kernel listening-descriptor census', item 2 (bb473a4); rows of paper/census_listen.py at bb473a4",
        "host": HOST[os_name], "os": os_name, "job": job, "functional_test": job is None,
        "lab_phase": os.environ.get("LAB_PHASE"), "src_commit": read_head(ROOT),
        "tool": "ss -Hltnp" if os_name == "linux" else "netstat -ano -p tcp",
        "cross_check": ("/proc/net/tcp and /proc/net/tcp6 rows in state 0A whose inode is a socket of the process"
                        if os_name == "linux" else
                        "GetExtendedTcpTable TCP_TABLE_OWNER_PID_LISTENER, AF_INET and AF_INET6"),
        "load": False, "bind": LOOPBACK, "date": dt.date.today().isoformat(), "started": now(),
        "platform": platform.platform(), "release": platform.release(), "python": sys.version.split()[0],
        "runs": [], "complete": False,
    }
    if launcher or runs is not None or reader is not None or skip_os_check:
        doc["functional_test"] = True
    rc = 0
    try:
        if not skip_os_check and sys.platform != ("win32" if os_name == "windows" else "linux"):
            raise Refused(f"this is {sys.platform}, not {os_name}")
        doc.update(check_gate(os_name, binary, gate, gate_sha256))
        runs = RUNS[os_name] if runs is None else runs
        if os_name == "windows":
            doc["excluded_port_ranges"] = excluded_ranges()
            hit = [p for r in runs for p in r.ports() for a, b in doc["excluded_port_ranges"] if a <= p <= b]
            if hit:
                raise Refused(f"ports inside an excluded range: {hit}")
        reader = reader or (read_windows if os_name == "windows" else read_linux)
        for run in runs:
            doc["runs"].append(one_run(os_name, binary, run, raw, reader, launcher))
            write_json(target, doc)
        doc["complete"] = all(r["ok"] for r in doc["runs"])
        rc = 0 if doc["complete"] else 3
    except Refused as e:
        doc["refused"] = str(e)
        rc = 2
    doc["ended"] = now()
    write_json(target, doc)
    for r in doc["runs"]:
        print(f"census {doc['host']}: {r['backend']} {r['mode']} {r['listener']} x{r['workers']}: "
              f"kernel {r.get('kernel_listen_count')}, server lines {r['server_listening_lines']}, "
              f"ok {r['ok']}" + (f" ({r['problem']})" if r["problem"] else ""))
    if doc.get("refused"):
        print(f"census refused: {doc['refused']}", file=sys.stderr)
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("os", choices=sorted(RUNS))
    ap.add_argument("--binary", type=Path, required=True, help="the measured Release oneport binary")
    ap.add_argument("--gate", type=Path, required=True, help="the gate JSON that names its sha256")
    ap.add_argument("--gate-sha256", required=True, help="the gate file's own sha256")
    ap.add_argument("--out", type=Path, required=True, help="a new folder for census.json and raw/")
    a = ap.parse_args(argv)
    return census(a.os, a.binary, a.gate, a.gate_sha256.lower(), a.out)


if __name__ == "__main__":
    raise SystemExit(main())
