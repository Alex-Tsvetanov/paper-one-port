#!/usr/bin/env python3
"""W's lab lock, the counterpart of L's lab/bin/lablock (flock -w 14400 ~/lab/.lab.lock): one job on
W at a time, so that two jobs never overlap.

The lock is a byte-range lock (msvcrt.locking) on the file %USERPROFILE%\\lab\\.lab.lock, held by the
process for the job's length and released when it closes the file or ends, however it ends (Windows
releases a dead process's locks). A job waits for it at most 4 hours, as lablock does, then fails
without running.

    wlock.py COMMAND [ARGS...]     runs COMMAND holding the lock (exit 1 if it was not had in 4 h)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

LOCK_PATH = Path(os.environ.get("ONEPORT_WLOCK", str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "lab" / ".lab.lock")))
WAIT_S = 4 * 3600  # lablock's 14400 s


class LockTimeout(RuntimeError):
    pass


class WLock:
    """`with WLock():` holds W's lab lock; waits at most `wait_s` for it."""

    def __init__(self, path: Path = LOCK_PATH, wait_s: float = WAIT_S, poll_s: float = 1.0):
        self.path = path
        self.wait_s = wait_s
        self.poll_s = poll_s
        self.f = None
        self.waited_s = 0.0

    def acquire(self) -> "WLock":
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+b")
        t0 = time.monotonic()
        while True:
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.waited_s = time.monotonic() - t0
                return self
            except OSError:
                if time.monotonic() - t0 >= self.wait_s:
                    self.f.close()
                    self.f = None
                    raise LockTimeout(f"W's lab lock {self.path} not had within {self.wait_s:.0f} s")
                time.sleep(self.poll_s)

    def release(self) -> None:
        if self.f is None:
            return
        import msvcrt
        try:
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()
        self.f = None

    def __enter__(self) -> "WLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    try:
        with WLock():
            return subprocess.run(args).returncode
    except LockTimeout as e:
        print(f"wlock: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
