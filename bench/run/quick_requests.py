#!/usr/bin/env python3
"""The labrun jobs of P3's quick-benchmark campaigns (quick-plan.md, decisions d006 and d007).

    quick_requests.py --commit C --os L|W

prints, as a JSON list, one labrun job for each quick plan of that OS: the plans of bench/run/plans/quick/ whose host is
the OS (L: 16 plans, W: 6). Each job is shaped as the P3 jobs of lab/laptop/queues/gap84-a-q4-p3-hard-iou-l.json (L) and
gap84-w-q3-p3-cost-w2.json (W): the build phase is lab_p3.py prepare at C (the Release build, made once per OS and commit
and reused by the other jobs), the run phase is lab_p3.py quick at C for the plan. C is the full 40-character commit that
labrun deploys; it is the job's commit and the code commit alike. The quick jobs keep their own homes
(~/lab/p3/quick-L, C:\\Users\\alext\\lab\\p3\\quick-W), so no frozen state is touched.

The order's seed of a plan is the first four bytes of the sha256 of its stem, as an integer: deterministic, not chosen, and
given on the command line (recorded in every row as `seed`). The list goes into a queue file's "jobs". Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import quick_plans  # noqa: E402

HOME_L = '"$HOME/lab/p3/quick-L"'
HOME_W = r"C:\Users\alext\lab\p3\quick-W"
# As the gap84 W jobs set them: Ninja on PATH, the numpy venv of the analysis imports, no user site, C:\Python314.
W_ENV = (r'set "PATH=C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%" && '
         r'set "PYTHONPATH=C:\Users\alext\lab\p3\venv-numpy\Lib\site-packages" && set "PYTHONNOUSERSITE=1" && ')
W_PYTHON = r"C:\Python314\python.exe"
# As the gap84 L jobs export them: the wrappers' clock-floor and THP records.
L_ENV = 'export ONEPORT_CLOCK_RECORD="$IOCORE_CLOCK_RECORD" ONEPORT_THP_RECORD="$IOCORE_THP_RECORD"; '
EXPECTED_S = 600
POLL_S = 60
TIMEOUT_S = 1800
BUILD_TIMEOUT_S = {"L": 1800, "W": 3600}
QUIET_WAIT_S = 1800
OS_NAME = {"L": "linux", "W": "windows"}


def seed_of(stem: str) -> int:
    return int(hashlib.sha256(stem.encode("utf-8")).hexdigest()[:8], 16)


def plans_of(host: str) -> list[str]:
    """The stems of the quick plans of one host, in the order quick_plans.py makes them."""
    return [stem for stem, plan in quick_plans.build_all().items() if plan["host"] == host]


def job(commit: str, host: str, stem: str) -> dict:
    c12 = commit[:12]
    seed = seed_of(stem)
    if host == "L":
        build = f"python3 bench/run/lab_p3.py prepare --commit {commit} --home {HOME_L}"
        run = f'{L_ENV}cd "$LAB_SRC" && python3 bench/run/lab_p3.py quick --commit {commit} --home {HOME_L} --plan {stem} --seed {seed}'
    else:
        build = f'cd /d "%LAB_SRC%" && {W_ENV}{W_PYTHON} bench\\run\\lab_p3.py prepare --commit {commit} --home {HOME_W}'
        run = f'cd /d "%LAB_SRC%" && {W_ENV}{W_PYTHON} bench\\run\\lab_p3.py quick --commit {commit} --home {HOME_W} --plan {stem} --seed {seed}'
    out = {
        "id": f"p3-{stem}".lower(),   # labqueue ID_RE: [a-z0-9][a-z0-9-]*
        "paper": "P3",
        "os": OS_NAME[host],
        "repo": {"name": "one-port", "path": "p3-one-port/one-port"},
        "commit": commit,
        "build": build,
        "run": run,
        "outputs": ["out", "record.json"],
        "record_name": "id",
    }
    if host == "L":
        out.update({"uring": True, "cgdeleg": False})
    out.update({"quiet": True, "boost": False, "expected_s": EXPECTED_S, "poll_s": POLL_S, "timeout_s": TIMEOUT_S,
                "build_timeout_s": BUILD_TIMEOUT_S[host], "quiet_wait_s": QUIET_WAIT_S,
                "run_label": f"P3 quick benchmark {stem} at {c12}",
                "note": ("quick-plan.md, decisions d006 and d007; a campaign of at most 600 s; quick_run.py with the plan's sha256 and the seed "
                         f"{seed}; the build phase makes the commit's Release build in the quick home (reused by the other jobs)"),
                "plain": f"Run P3's quick benchmark {stem}"})
    return out


def stem_of(j: dict) -> str:
    """The plan stem a job runs (the id is lowercased for labqueue; the file name is not)."""
    return j["run"].split("--plan ", 1)[1].split(" ", 1)[0]


def jobs(commit: str, host: str) -> list[dict]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"--commit {commit!r} is not a full 40-character commit")
    if host not in OS_NAME:
        raise ValueError(f"--os {host!r} is not L or W")
    return [job(commit, host, stem) for stem in plans_of(host)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--os", required=True, dest="host", type=lambda v: {"linux": "L", "windows": "W"}.get(v.lower(), v.upper()))
    a = ap.parse_args(argv)
    try:
        out = jobs(a.commit.lower(), a.host)
    except ValueError as e:
        print(f"quick_requests: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
