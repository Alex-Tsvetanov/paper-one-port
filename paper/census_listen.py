#!/usr/bin/env python3
"""Ask the kernel how many listening sockets the gated oneport binary holds.

This is not a timing run. Nothing connects. The server binds 127.0.0.1 only.
On Windows the count is netstat's LISTENING rows for that process, and
GetExtendedTcpTable (TCP_TABLE_OWNER_PID_LISTENER) must list the same
addresses. On Linux, over SSH to the lab laptop, the count is ss -Hltnp
for that process. The server's own "listening" lines are stored and are
not the count.

    python paper/census_listen.py --windows results/census-w.json
    python paper/census_listen.py --linux results/census-l.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W_BIN = Path(r"C:\Users\alext\lab\p3\m7g\records-ff2679c-W\build-release\bench\server\oneport.exe")
W_SHA = "749d0209c112fb8fa2689b632f635f32364d46827de243c28398ab647adf328c"
L_BIN = "/home/alex/lab/p3/m7g/records-ff2679c/build-release/bench/server/oneport"
L_SHA = "4c64edc25f7689dab95c90218ae50d3d7e92960d3e4e08bb826b1239e252b179"
L_HOST = "alex@192.168.1.62"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def split_endpoint(text: str) -> tuple[str, int]:
    host, port = text.rsplit(":", 1)
    return host.strip("[]"), int(port)


def netstat_listen(pid: int) -> list[dict]:
    out = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True, encoding="oem", errors="replace")
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP" or parts[-2] != "LISTENING" or parts[-1] != str(pid):
            continue
        addr, port = split_endpoint(parts[1])
        rows.append({"local": f"{addr}:{port}", "state": "LISTENING", "pid": pid})
    return rows


def api_listen(pid: int) -> list[dict]:
    import ctypes
    from ctypes import wintypes

    iphlpapi = ctypes.WinDLL("iphlpapi")
    dword = wintypes.DWORD
    size = dword(0)
    af_inet = 2
    table_class = 3  # TCP_TABLE_OWNER_PID_LISTENER
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, af_inet, table_class, 0)
    rows = []
    for _ in range(5):
        buf = ctypes.create_string_buffer(size.value + 65536)
        size = dword(len(buf))
        rc = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, af_inet, table_class, 0)
        if rc != 0:
            if rc != 122:
                raise OSError(rc, "GetExtendedTcpTable")
            continue
        raw = buf.raw
        n = int.from_bytes(raw[0:4], "little")
        stride = 24
        for i in range(n):
            off = 4 + stride * i
            state = int.from_bytes(raw[off:off + 4], "little")
            local = int.from_bytes(raw[off + 4:off + 8], "little")
            local_port = int.from_bytes(raw[off + 8:off + 12], "little")
            owner = int.from_bytes(raw[off + 20:off + 24], "little")
            if owner != pid or state != 2:
                continue
            addr = ".".join(str((local >> (8 * b)) & 0xFF) for b in range(4))
            port = socket.ntohs(local_port & 0xFFFF)
            rows.append({"local": f"{addr}:{port}", "state": "LISTEN", "pid": pid})
        return rows
    raise OSError(122, "GetExtendedTcpTable: the table kept growing")


def stop_windows(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenEventW(0x0002, False, f"Local\\oneport-stop-{pid}")
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenEventW")
    if not kernel32.SetEvent(handle):
        kernel32.CloseHandle(handle)
        raise OSError(ctypes.get_last_error(), "SetEvent")
    kernel32.CloseHandle(handle)


def wait_ready(path: Path, proc: subprocess.Popen, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if "oneport: connection state" in text or "oneport: listening " in text:
            return text
        if proc.poll() is not None:
            return text
        time.sleep(0.05)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def run_windows(mode: str, port: int) -> dict:
    if sha256(W_BIN) != W_SHA:
        raise SystemExit(f"Windows binary hash is not the gate's: {W_BIN}")
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="census-w-"))
    out = tmp / "stdout.txt"
    err = tmp / "stderr.txt"
    cmd = [str(W_BIN), "--mode", mode, "--detect", "replay", "--dispatch", "inproc",
           "--backend", "IOCP", "--listener", "shared", "--workers", "1", "--port", str(port)]
    with out.open("w", encoding="utf-8") as stdout, err.open("w", encoding="utf-8") as stderr:
        proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
        try:
            text = wait_ready(out, proc, 15)
            if proc.poll() is not None or "oneport: listening " not in text:
                raise RuntimeError(f"server did not listen ({mode}): {err.read_text(encoding='utf-8', errors='replace')[:500]}")
            time.sleep(0.2)
            kernel = netstat_listen(proc.pid)
            api = api_listen(proc.pid)
        finally:
            if proc.poll() is None:
                try:
                    stop_windows(proc.pid)
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=10)
    kernel_set = sorted(row["local"] for row in kernel)
    api_set = sorted(row["local"] for row in api)
    return {
        "mode": mode,
        "backend": "IOCP",
        "listener": "shared",
        "workers": 1,
        "port": port,
        "pid": proc.pid,
        "command": cmd,
        "server_lines": [ln for ln in text.splitlines() if ln.startswith("oneport: listening ")],
        "netstat": kernel,
        "get_extended_tcp_table": api,
        "kernel_listen_count": len(kernel),
        "agree": kernel_set == api_set,
    }


def windows(path: Path) -> None:
    runs = [run_windows("one-port", 19080), run_windows("dedicated", 19100)]
    doc = {
        "host": "W",
        "tool": "netstat -ano -p tcp",
        "cross_check": "GetExtendedTcpTable TCP_TABLE_OWNER_PID_LISTENER",
        "binary": str(W_BIN),
        "binary_sha256": W_SHA,
        "load": False,
        "bind": "127.0.0.1",
        "date": time.strftime("%Y-%m-%d"),
        "runs": runs,
    }
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    if any(not run["agree"] for run in runs):
        raise SystemExit(f"netstat and GetExtendedTcpTable disagree: {path}")


def linux(path: Path) -> None:
    script = r"""
set -u
BIN=__BIN__
expect=__SHA__
got=$(sha256sum "$BIN" | awk '{print $1}')
if [ "$got" != "$expect" ]; then
  echo "hash $got" >&2
  exit 1
fi
python3 - <<'PY'
import json, os, signal, socket, subprocess, time
BIN = "__BIN__"
runs = []

def one(mode, backend, listener, workers, port):
    cmd = [BIN, "--mode", mode, "--detect", "replay", "--dispatch", "inproc",
           "--backend", backend, "--listener", listener, "--workers", str(workers), "--port", str(port)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    text = ""
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            text += line
            if line.startswith("oneport: connection state"):
                break
        time.sleep(0.2)
        ss = subprocess.check_output(["ss", "-Hltnp"], text=True)
        rows = []
        for ln in ss.splitlines():
            if f"pid={proc.pid}," in ln or f"pid={proc.pid})" in ln:
                parts = ln.split()
                local = parts[3] if len(parts) > 3 else ""
                rows.append({"line": ln, "local": local})
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    err = proc.stderr.read() if proc.stderr else ""
    if "oneport: listening " not in text:
        raise SystemExit("server did not listen: " + mode + " " + backend + " " + err[:400])
    runs.append({
        "mode": mode, "backend": backend, "listener": listener, "workers": workers, "port": port,
        "pid": proc.pid, "command": cmd,
        "server_lines": [ln.strip() for ln in text.splitlines() if ln.startswith("oneport: listening ")],
        "ss": rows, "kernel_listen_count": len(rows), "agree": True,
    })

one("one-port", "epoll", "shared", 1, 19080)
one("dedicated", "epoll", "shared", 1, 19100)
one("one-port", "epoll", "reuseport", 2, 19200)
one("one-port", "io_uring", "shared", 1, 19300)
one("dedicated", "io_uring", "shared", 1, 19400)
print(json.dumps({"runs": runs}))
PY
"""
    script = script.replace("__BIN__", L_BIN).replace("__SHA__", L_SHA)
    script = script.replace("\r\n", "\n").replace("\r", "\n")
    remote = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", L_HOST, "bash", "-s"],
        input=script.encode("utf-8"), capture_output=True, check=False)
    if remote.returncode != 0:
        err = remote.stderr.decode("utf-8", "replace")
        out = remote.stdout.decode("utf-8", "replace")
        raise SystemExit(err[-2000:] or out[-2000:])
    payload = json.loads(remote.stdout.decode("utf-8"))
    doc = {
        "host": "L",
        "tool": "ss -Hltnp",
        "binary": L_BIN,
        "binary_sha256": L_SHA,
        "ssh": L_HOST,
        "load": False,
        "bind": "127.0.0.1",
        "date": time.strftime("%Y-%m-%d"),
        "runs": payload["runs"],
    }
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=Path)
    parser.add_argument("--linux", type=Path)
    args = parser.parse_args()
    if not args.windows and not args.linux:
        parser.error("name --windows or --linux")
    if args.windows:
        windows(args.windows)
    if args.linux:
        linux(args.linux)
    return 0


if __name__ == "__main__":
    sys.exit(main())
