#!/usr/bin/env python3
"""K_SRC's development runs (section 9.1: "set so that no connect fails in the development runs"):
single dedicated-mode windows of the client-closes-first churn cells, whose clients keep a
TIME-WAIT socket per connection, at several block sizes, recording connect failures, the server's
busy share and the generator's CPU. Development data; every window is one of `window.py`.

    ksrc_sweep.py --build DIR --out DIR --job NAME --cells churn:mqtt:epoll,... --k 1,4,16,64
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aa  # noqa: E402
import window  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--cells", required=True)
    ap.add_argument("--k", required=True)
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    prov = aa.provenance(a.build, Path.home() / "lab" / "p3" / "tools")
    blocks = window.SourceBlocks(a.blocks)
    for c in aa.parse_cells(a.cells):
        for k in (int(x) for x in a.k.split(",")):
            cfg = dict(c, build=a.build, k_src=k, ports={"A": aa.PORT_A})
            fp = window.pin_fingerprint()
            session = {"job": a.job, "id": f"{c['cell']}-k{k}", "mhz": fp["mean_mhz"], "fingerprint": fp}
            r = window.run_window(cfg, session, "A", 0, blocks, a.out / "raw")
            r["provenance"] = prov
            r["fingerprint"] = fp
            with open(a.out / "windows.jsonl", "a") as f:
                f.write(json.dumps(r) + "\n")
            o = r.get("opgen", {})
            print(f"{c['cell']} K={k}: {r.get('metric', {}).get('value', 0):.0f}/s valid={r.get('valid')} "
                  f"connect failures {o.get('connect_failures')} server busy {r.get('server_cores_busy', 0):.3f} "
                  f"generator rule {r.get('gen_cpu_pct_rule', 0):.1f}% max thread {o.get('cpu', {}).get('max_thread_pct', 0):.1f}% "
                  f"{'; '.join(r.get('invalid_reasons', []))}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
