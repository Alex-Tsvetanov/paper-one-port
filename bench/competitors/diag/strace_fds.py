#!/usr/bin/env python3
"""sslh-ev's descriptors in an strace -f -tt log: each descriptor that accept() or socket()
returned, whether an epoll_ctl names it before it is closed (or the log ends), and whether the
same number was closed earlier in the same loop pass (the calls since the last epoll_wait).

    strace_fds.py strace.txt
"""
import re
import sys
from collections import Counter

CALL = re.compile(r"^\d+\s+\S+\s+(\w+)\((.*)\)\s+=\s+(-?\d+)")


def main() -> int:
    passes = 0
    closed_this_pass: set[int] = set()
    live: dict[int, dict] = {}   # fd -> {"kind", "pass", "reused", "ctl", "read"}
    done: list[dict] = []
    for ln in open(sys.argv[1], errors="replace"):
        m = CALL.match(ln)
        if not m:
            continue
        name, args, ret = m.group(1), m.group(2), int(m.group(3))
        if name in ("epoll_wait", "epoll_pwait"):
            passes += 1
            closed_this_pass = set()
            continue
        first = args.split(",", 1)[0].strip()
        if name in ("accept", "accept4", "socket") and ret >= 0:
            live[ret] = {"fd": ret, "kind": "accept" if name.startswith("accept") else "socket", "pass": passes,
                         "reused": ret in closed_this_pass, "ctl": 0, "read": 0}
        elif name == "epoll_ctl":
            fd = int(args.split(",")[2])
            if fd in live:
                live[fd]["ctl"] += 1
        elif name == "read" and first.isdigit():
            fd = int(first)
            if fd in live:
                live[fd]["read"] += 1
        elif name == "close" and first.isdigit():
            fd = int(first)
            closed_this_pass.add(fd)
            if fd in live:
                rec = live.pop(fd)
                rec["closed"] = True
                done.append(rec)
    for rec in live.values():
        rec["closed"] = False
        done.append(rec)
    c = Counter()
    for r in done:
        c[(r["kind"], "reused in pass" if r["reused"] else "fresh", "epoll_ctl" if r["ctl"] else "no epoll_ctl",
           "closed" if r["closed"] else "open at end", "read" if r["read"] else "never read")] += 1
    print(f"loop passes {passes}, descriptors {len(done)}")
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print(f"  {v:6d}  {', '.join(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
