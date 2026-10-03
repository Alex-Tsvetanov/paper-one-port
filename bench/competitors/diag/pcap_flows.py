#!/usr/bin/env python3
"""Flows of a loopback capture (tcpdump -r FILE -nn -tt -S text on stdin): per TCP flow, its
packets; flags flows with a retransmitted SYN, SYN-ACK or data segment, or a gap over GAP_S
between two packets, and prints counts and examples. FRONT is the front's port; ports
STUB..STUB+5 are the stub's. A flow is a 4-tuple, so the connections of a reused 4-tuple fall
in one flow and show as several SYNs; a stall shows as a gap.

    tcpdump -r lo.pcap -nn -tt -S | pcap_flows.py FRONT STUB [EXAMPLES]
"""
import re
import sys
from collections import defaultdict

GAP_S = 0.2
LINE = re.compile(r"^(\d+\.\d+) IP (\S+)\.(\d+) > (\S+)\.(\d+): Flags \[([^\]]*)\](?:, seq (\d+)(?::(\d+))?)?(?:, ack (\d+))?.*?length (\d+)")


def main() -> int:
    front, stub = int(sys.argv[1]), int(sys.argv[2])
    examples = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    flows = defaultdict(list)
    n = 0
    for ln in sys.stdin:
        m = LINE.match(ln)
        if not m:
            continue
        n += 1
        t, sa, sp, da, dp, flags, seq, seq_end, ack, length = m.groups()
        sp, dp = int(sp), int(dp)
        key = tuple(sorted([(sa, sp), (da, dp)]))
        flows[key].append((float(t), (sa, sp), flags, int(seq) if seq else None, int(length)))
    kinds = {"client": [], "backend": [], "other": []}
    for key, pk in flows.items():
        ports = {key[0][1], key[1][1]}
        if front in ports:
            kinds["client"].append((key, pk))
        elif any(stub <= p <= stub + 5 for p in ports):
            kinds["backend"].append((key, pk))
        else:
            kinds["other"].append((key, pk))
    print(f"packets {n}; flows: client {len(kinds['client'])}, backend {len(kinds['backend'])}, other {len(kinds['other'])}")
    for kind in ("client", "backend"):
        stats = defaultdict(int)
        ex = []
        for key, pk in kinds[kind]:
            pk.sort(key=lambda x: x[0])
            syns = [p for p in pk if p[2] == "S"]
            synacks = [p for p in pk if p[2] == "S."]
            seen = set()
            redata = 0
            for p in pk:
                if p[4] > 0:
                    k = (p[1], p[3])
                    if k in seen:
                        redata += 1
                    seen.add(k)
            gaps = [(pk[i + 1][0] - pk[i][0], i) for i in range(len(pk) - 1) if pk[i + 1][0] - pk[i][0] > GAP_S]
            rst = sum(1 for p in pk if "R" in p[2])
            flagged = []
            if len(syns) > 1:
                flagged.append(f"SYN x{len(syns)}")
            if len(synacks) > 1:
                flagged.append(f"SYN-ACK x{len(synacks)}")
            if redata:
                flagged.append(f"data retransmitted x{redata}")
            if gaps:
                flagged.append(f"gap {max(g for g, _ in gaps):.3f}s")
            if not syns:
                flagged.append("no SYN in capture")
            if rst:
                stats["with RST"] += 1
            for f in flagged:
                stats[f.split(' x')[0].split(' 0')[0].split(' 1')[0].split(' 2')[0]] += 1
            if flagged and not (len(flagged) == 1 and flagged[0] == "no SYN in capture"):
                stats["flagged"] += 1
                if len(ex) < examples:
                    ex.append((key, pk, flagged))
        print(f"{kind}: {dict(stats)}")
        for key, pk, flagged in ex:
            t0 = pk[0][0]
            print(f"  {key} {flagged}")
            for p in pk:
                print(f"    +{p[0] - t0:9.6f} {p[1][0]}.{p[1][1]} [{p[2]}] seq {p[3]} len {p[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
