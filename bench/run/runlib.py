#!/usr/bin/env python3
"""What the frozen runners share (M7c): their common command line, the job's provenance and each
arm's binaries, and the input files they read (the seeds, the pilot entry's output, rule E's
choices, M2's rates), each checked against the contract analysis/ reads.

The runners: pilot_run.py (8 step 4), cost_run.py (5.1), b3_run.py (5.2 and section 10's B3
cells), m_run.py (5.3; M2_RATE), rule_e.py (rule E), s_run.py (section 10), hardcase_run.py (B1,
B2 and the competitors' hard-case table). Each runs under bench/run/lab_job.sh (the lab lock, the
clock floor, THP at madvise, NOTRACK), stops cleanly on SIGTERM, SIGINT and SIGHUP (window.py's
stop_on_signals: every finally block stops the processes it started), and writes rows in the
contract of analysis/rows.py.

Development mode (--development): rows say development: true, the freeze guard is not asked, a
development seed is given on the command line, and no one-port window runs against dedicated
mode (bench/run/sessions.py). A frozen run (no --development) needs every precondition of
bench/run/freeze_guard.py.

Rule E's file (rule_e.json, written by rule_e.py after the pilot entry; analysis/analyse.py's
check_rule_e reads exactly its three keys):
  {"default": {"epoll": "replay"|"peek", "io_uring": ..., "IOCP": ...},
   "relay_copy": {"epoll": "user-space"|"splice", "io_uring": ...},
   "iocp_receive": "zero-byte"}
M2's rates (m2_rates.json, written by m_run.py --part m2-rate): {"M2.L.<backend>.<proto>": rate}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(REPO / "analysis"))

import aa  # noqa: E402
import build_inputs  # noqa: E402
import window  # noqa: E402

HOST = "L"
DETECTS = ("replay", "peek")
RELAY_COPIES = ("user-space", "splice")
COST_BACKENDS_L = ("epoll", "io_uring")
SEED_NAMES = ("SEED_ORDER_C_L", "SEED_ORDER_C_W", "SEED_ORDER_B_L", "SEED_ORDER_M_L", "SEED_ORDER_M_W", "SEED_ORDER_S_L",
              "SEED_ORDER_S_W", "SEED_BOOT_C", "SEED_BOOT_B", "SEED_BOOT_M", "SEED_BOOT_S", "SEED_PILOT_L", "SEED_PILOT_W", "SEED_SIM")
RATE_FRAC = 0.5  # WL2 (frozen)
# The proposed defaults of rule E (section 2.1 and section 8), in force until rule E's file exists.
PROPOSED_RULE_E = {"default": {"epoll": "replay", "io_uring": "replay", "IOCP": "replay"},
                   "relay_copy": {"epoll": "user-space", "io_uring": "user-space"}, "iocp_receive": "zero-byte"}


class InputRefused(SystemExit):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- input files


def load_seeds(path: Path) -> dict[str, int]:
    """The 14 seeds of 4.7 (analysis/cells.py's check_seeds, the same rule)."""
    seeds = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [n for n in SEED_NAMES if n not in seeds]
    extra = sorted(set(seeds) - set(SEED_NAMES))
    if missing or extra:
        raise InputRefused(f"seeds: missing {missing}, unknown {extra}")
    for n in SEED_NAMES:
        v = seeds[n]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise InputRefused(f"seed {n} = {v!r} is not a non-negative integer")
    return {n: seeds[n] for n in SEED_NAMES}


def check_rule_e(r: dict) -> dict:
    """Rule E's file, as analysis/analyse.py's check_rule_e reads it."""
    if sorted(r) != ["default", "iocp_receive", "relay_copy"]:
        raise InputRefused(f"rule E: keys {sorted(r)}")
    d, rc = r["default"], r["relay_copy"]
    if not isinstance(d, dict) or sorted(d) != ["IOCP", "epoll", "io_uring"] or any(v not in DETECTS for v in d.values()):
        raise InputRefused(f"rule E: default {d!r}")
    if not isinstance(rc, dict) or sorted(rc) != ["epoll", "io_uring"] or any(v not in RELAY_COPIES for v in rc.values()):
        raise InputRefused(f"rule E: relay_copy {rc!r}")
    if r["iocp_receive"] != "zero-byte":
        raise InputRefused("rule E: the IOCP receive form is the zero-byte form (the coordinator's decision of 2026-10-03)")
    return r


def load_rule_e(path: Path | None, development: bool) -> dict:
    """Rule E's choices. A frozen run needs the file; a development run without one takes the
    proposed defaults (replay, user space, the zero-byte receive), and its rows say so."""
    if path is None:
        if not development:
            raise InputRefused("a frozen run after the pilot entry reads rule E's file (--rule-e)")
        return json.loads(json.dumps(PROPOSED_RULE_E))
    return check_rule_e(json.loads(Path(path).read_text(encoding="utf-8")))


def load_pilot(path: Path | None, development: bool) -> dict:
    """pilot.py's output. A development run may go without (its runner then needs the values it
    would read, from its own command line)."""
    if path is None:
        if not development:
            raise InputRefused("a frozen run after the pilot entry reads the pilot entry's output (--pilot)")
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- provenance


def job_provenance(build: Path, tools: Path | None, out: Path, job: str) -> dict:
    """aa.py's provenance (commit, build, compiler, pins, the development inputs hash), the
    build's inputs hash per target the way the gate hashes it (b3.py's gate_inputs_hash), and the
    sha256 of every binary of the build a window can run, under the gate's names."""
    import b3  # noqa: PLC0415 - b3.py's gate_inputs_hash
    p = aa.provenance(build, tools)
    tool = tools / "inputs_hash.py" if tools is not None and (tools / "inputs_hash.py").exists() else None
    p.update(b3.gate_inputs_hash(build, out / f"{job}.inputs.json", tool))
    allb = {}
    for name, rel in build_inputs.BINARIES[HOST].items():
        f = build / rel
        if f.exists():
            allb[name] = window.sha256_file(f)
    p["binaries_all"] = allb
    p.pop("binaries", None)
    # The runner's own code (the Python half, frozen with the tests at CODE_FREEZE), beside the
    # build's commit that aa.py records.
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "bench", "analysis"], capture_output=True, text=True)
    p["runner_commit"] = head.stdout.strip() if head.returncode == 0 else None
    p["runner_dirty"] = bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    return p


def arm_provenance(job_prov: dict, build: Path, names: tuple[str, ...]) -> dict:
    """The job's provenance with "binaries" the first-party executables this arm's windows run."""
    p = {k: v for k, v in job_prov.items() if k != "binaries_all"}
    allb = job_prov.get("binaries_all") or {}
    missing = [n for n in names if n not in allb]
    if missing:
        raise InputRefused(f"the build has no {missing} (bench/build_inputs.py's BINARIES)")
    p["binaries"] = {n: allb[n] for n in names}
    p["binary_paths"] = {n: str(build / build_inputs.BINARIES[HOST][n]) for n in names}
    return p


def binaries_of(job_prov: dict, names: tuple[str, ...]) -> dict[str, str]:
    allb = job_prov.get("binaries_all") or {}
    return {n: allb[n] for n in names if n in allb}


# ---------------------------------------------------------------- the command line


def common_args(ap: argparse.ArgumentParser, *, needs_pilot: bool = True) -> None:
    ap.add_argument("--build", type=Path, required=True, help="the measured Release build (the records job's build-release)")
    ap.add_argument("--out", type=Path, required=True, help="the run's directory: windows.jsonl collects every job's rows")
    ap.add_argument("--job", required=True, help="this lab job's name, in every row")
    ap.add_argument("--k-src", type=int, default=16, help="K_SRC (section 9.1: 16, revision log M3 item 9)")
    ap.add_argument("--development", action="store_true", help="development data: rows say so; no freeze guard")
    ap.add_argument("--seeds", type=Path, help="the seeds file of the seeds entry (frozen runs)")
    ap.add_argument("--dev-seed", type=int, help="development mode: the order's seed")
    ap.add_argument("--code-freeze", help="CODE_FREEZE, the full commit hash (frozen runs)")
    ap.add_argument("--gate", type=Path, action="append", default=[], help="gate-L.json of the records at CODE_FREEZE (frozen runs)")
    if needs_pilot:
        ap.add_argument("--pilot", type=Path, help="pilot.py's output, as the pilot entry records it (frozen runs)")
    ap.add_argument("--tools", type=Path, default=Path.home() / "lab" / "p3" / "tools", help="where inputs_hash.py is")
    ap.add_argument("--blocks", type=Path, default=Path.home() / "lab" / "p3" / "src-blocks.json", help="the source-block file")
    ap.add_argument("--max-sessions", type=int, help="development mode: stop after this many sessions")
    ap.add_argument("--dev-r", type=int, help="development mode: sessions per cell instead of the frozen R")
    ap.add_argument("--only", help="development mode: run only these cells (comma separated cell ids)")


def check_mode_args(a: argparse.Namespace) -> None:
    if a.development:
        if a.dev_seed is None:
            raise InputRefused("--development needs --dev-seed (a development order's seed, recorded in the journal)")
        return
    for flag in ("max_sessions", "only", "dev_seed", "dev_r"):
        if getattr(a, flag, None) is not None:
            raise InputRefused(f"--{flag.replace('_', '-')} is for development runs only")
    for flag in ("seeds", "code_freeze"):
        if getattr(a, flag, None) is None:
            raise InputRefused(f"a frozen run needs --{flag.replace('_', '-')}")
    if not a.gate:
        raise InputRefused("a frozen run needs --gate (gate-L.json of the records at CODE_FREEZE)")


def order_seed(a: argparse.Namespace, name: str) -> tuple[int, dict | None]:
    """The order's seed: the seeds file's `name` in a frozen run, --dev-seed in development."""
    if a.development:
        return int(a.dev_seed), None
    seeds = load_seeds(a.seeds)
    return seeds[name], seeds


def only_cells(a: argparse.Namespace, cells: list) -> list:
    if not getattr(a, "only", None):
        return cells
    want = set(a.only.split(","))
    out = [c for c in cells if c.id in want]
    if len(out) != len(want):
        raise InputRefused(f"--only names unknown cells: {sorted(want - {c.id for c in out})}")
    return out


def journal_note(a: argparse.Namespace) -> str:
    return "development data (M7c's end-to-end check), never a result" if a.development else "frozen run"
