"""A stand-in for oneport in test_census_lw.py: it prints the server's lines and waits to be stopped.

It parses the flags census_host.py passes, binds the ports it names on 127.0.0.1 (six consecutive
ports in dedicated mode, one otherwise), prints one "oneport: listening" line per port, then
"oneport: connection state", and waits: on Windows for the event "Local\\oneport-stop-<pid>", as
oneport does, elsewhere for SIGTERM. FAKE_ONEPORT=silent prints nothing and sleeps; =exit exits 1.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import time

NAMES = ("HTTP/1.1", "h2c", "TLS", "MQTT", "SSH", "SMTP")


def flag(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


def main() -> int:
    how = os.environ.get("FAKE_ONEPORT", "")
    if how == "exit":
        return 1
    if how == "silent":
        time.sleep(60)
        return 0
    port = int(flag("--port"))
    names = NAMES if flag("--mode") == "dedicated" else ("one-port",)
    ev = None
    if sys.platform == "win32":  # created before the ready line, as oneport does
        import ctypes

        k32 = ctypes.WinDLL("kernel32")
        k32.CreateEventW.restype = ctypes.c_void_p
        ev = k32.CreateEventW(None, True, False, "Local\\oneport-stop-" + str(os.getpid()))
    else:
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    socks = []
    for i, name in enumerate(names):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", port + i))
        s.listen(16)
        socks.append(s)
        print(f"oneport: listening {name} 127.0.0.1:{port + i}")
    print("oneport: connection state 64 bytes", flush=True)
    if ev is not None:
        k32.WaitForSingleObject(ctypes.c_void_p(ev), 0xFFFFFFFF)
    else:
        signal.sigwait({signal.SIGTERM})
    print("counter accepted 0", flush=True)
    for s in socks:
        s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
