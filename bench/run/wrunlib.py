#!/usr/bin/env python3
"""What W's frozen runners share (M7e): the W side of runlib.py.

W's runners are L's, on the same session engine (bench/run/sessions.py), with the same cells
(analysis/cells.py, each L runner's cell builder with host "W"), the same order and rerun rules and
the same rows (analysis/rows.py's contract), so analysis/ reads them unchanged. What differs is the
host: the windows (bench/run/wcellwin.py, and wwindow.py for the A/A pilot), the session's
fingerprint (wwindow.fingerprint: the lab plan read back, the timer resolution, Defender and Windows
Update, the core layout, the frequency counter, the cycle rate), the provenance (bench/build_inputs.py
with --host W; W's binaries oneport.exe, opgen.exe and opcase.exe), and the job: every W run runs
inside a W lab job (bench/run/wjob.py run: W's lab lock, the checks before a session with the quiet
check, the lab plan set and read back, Alex's plan set back at the end, the pid and done files).

    wpilot_run.py  8 step 4 on W: the A/A pilot of W's 12 cost cells, its timer and split parts
    wcost_run.py   5.1 on W: the cost cells on IOCP at R_C, but W's churn h2c and churn MQTT
    wm_run.py      5.3 on W: M1's two IOCP cells
    wrule_e.py     rule E's IOCP detection sessions after the pilot entry, rule_e_evidence_W.json
    ws_run.py      section 10 on W: SSH, the mixed cell, TLS with ALPN h2, the IOCP forms, M1's TTFB
    whardcase_run.py  B1 and B2 on IOCP

A frozen W run (no --development) also needs: the job context (ONEPORT_W_JOB set by wjob.py, and
not a functional check: ONEPORT_W_FUNCTIONAL unset); the revision log's entries "W before the code
freeze" and "The job's warm-up and W's runners (M7e), before the code freeze"; and the ports it
binds outside W's excluded port ranges (read with netsh, read only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import build_inputs  # noqa: E402
import freeze_guard  # noqa: E402
import runlib  # noqa: E402
import waa  # noqa: E402
import window  # noqa: E402
import wsys  # noqa: E402
import wwindow  # noqa: E402

HOST = "W"
BLOCKS = wwindow.STATE_DIR / "src-blocks-w.json"
ENTRIES = (freeze_guard.W_ITEMS, freeze_guard.M7E_ITEMS)
InputRefused = runlib.InputRefused


# ---------------------------------------------------------------- the command line and the job


def common_args(ap: argparse.ArgumentParser, *, needs_pilot: bool = True) -> None:
    """runlib's command line, with W's defaults: the Papers repo's lab\\bin for inputs_hash.py and
    W's source-block file."""
    runlib.common_args(ap, needs_pilot=needs_pilot)
    ap.set_defaults(tools=waa.PAPERS_LAB_BIN, blocks=BLOCKS)


def check_job_context(development: bool, env: dict | None = None) -> dict:
    """A frozen W run runs inside a W lab job that passed W's quiet check: wjob.py sets
    ONEPORT_W_JOB, and ONEPORT_W_FUNCTIONAL=1 only for a job it ran as a functional check
    (--allow-noisy). A development run may run in either; its rows say development."""
    env = os.environ if env is None else env
    job = env.get("ONEPORT_W_JOB")
    functional = env.get("ONEPORT_W_FUNCTIONAL") == "1"
    if not development:
        if not job:
            raise InputRefused("a frozen W run runs inside a W lab job (bench/run/wjob.py run: the lock, the quiet check, the lab plan)")
        if functional:
            raise InputRefused("this W job did not pass the quiet check (wjob.py --allow-noisy): it runs development runs only")
    return {"job": job, "job_dir": env.get("ONEPORT_W_JOB_DIR"), "functional_check": functional}


def install_stop() -> None:
    """Ctrl+C, Ctrl+Break and SIGTERM end the runner through SystemExit (waa.stop_on_signals), and
    wjob.py stop sets this process's stop event, which interrupts the main thread the same way, so
    every finally block stops what it started (servers and holders by their events)."""
    waa.stop_on_signals()
    if sys.platform == "win32":
        wsys.watch_stop()
        wsys.set_own_affinity(wwindow.HOUSEKEEPING)  # the runner and its samplers on core 0 (CPUs 0 and 1)


# ---------------------------------------------------------------- ports


EXCLUDED_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s*\*?\s*$")


def parse_excluded(text: str) -> list[tuple[int, int]]:
    """`netsh int ipv4 show excludedportrange protocol=tcp`: one start and end port per line."""
    out = []
    for ln in text.splitlines():
        m = EXCLUDED_RE.match(ln)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def port_conflicts(excluded: list[tuple[int, int]], used: list[tuple[int, int]]) -> list[str]:
    return [f"ports {a} to {b} overlap W's excluded range {s} to {e}" for a, b in used for s, e in excluded if a <= e and s <= b]


def check_ports(used: list[tuple[int, int]]) -> dict:
    """Refuses a run whose ports lie in W's excluded TCP port ranges (read with netsh, read only):
    a server could not bind them. Each window's server binds its listeners on consecutive ports."""
    if sys.platform != "win32":
        return {"checked": False, "why": "not Windows"}
    p = subprocess.run(["netsh", "int", "ipv4", "show", "excludedportrange", "protocol=tcp"], capture_output=True, text=True)
    excluded = parse_excluded(p.stdout)
    bad = port_conflicts(excluded, used)
    if bad:
        raise InputRefused("; ".join(bad))
    return {"checked": True, "excluded": excluded, "used": used}


# ---------------------------------------------------------------- provenance


def job_provenance(build: Path, tools: Path | None, out: Path, job: str) -> dict:
    """waa.py's provenance on W (commit, dirty, build, compiler, libraries, pins, the runner
    scripts), the build's inputs hash per target as the gate hashes it (bench/build_inputs.py,
    --host W), and the sha256 of every binary of the build a window can run, under the gate's
    names (build_inputs.BINARIES["W"])."""
    p = waa.provenance(build)
    tool = Path(tools) / "inputs_hash.py" if tools is not None and (Path(tools) / "inputs_hash.py").exists() else None
    argv = ["--build", str(build), "--host", HOST, "--out", str(out / f"{job}.inputs.json")]
    if tool is not None:
        argv += ["--inputs-hash", str(tool)]
    try:
        rc = build_inputs.main(argv)
        if rc != 0:
            p["inputs_hash_error"] = f"build_inputs.py exit {rc}"
        else:
            info = json.loads((out / f"{job}.inputs.json").read_text())["builds"][build_inputs.BUILD]
            p.update(inputs_hash_gate={t: v["inputs_hash"] for t, v in info["targets"].items()},
                     inputs_hash_gate_config=info.get("config"), inputs_hash_gate_compiler=info.get("compiler"))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as e:
        p["inputs_hash_error"] = repr(e)[-300:]
    allb = {}
    for name, rel in build_inputs.BINARIES[HOST].items():
        f = Path(build) / rel
        if f.exists():
            allb[name] = window.sha256_file(f)
    p["binaries_all"] = allb
    p.pop("binaries", None)
    head = subprocess.run(["git", "-C", str(runlib.REPO), "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(runlib.REPO), "status", "--porcelain", "--", "bench", "analysis"], capture_output=True, text=True)
    p["runner_commit"] = head.stdout.strip() if head.returncode == 0 else None
    p["runner_dirty"] = bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    p["host"] = HOST
    return p


def arm_provenance(job_prov: dict, build: Path, names: tuple[str, ...]) -> dict:
    """The job's provenance with "binaries" the first-party executables this arm's windows run."""
    p = {k: v for k, v in job_prov.items() if k != "binaries_all"}
    allb = job_prov.get("binaries_all") or {}
    missing = [n for n in names if n not in allb]
    if missing:
        raise InputRefused(f"the build has no {missing} (bench/build_inputs.py's BINARIES['W'])")
    p["binaries"] = {n: allb[n] for n in names}
    p["binary_paths"] = {n: str(Path(build) / build_inputs.BINARIES[HOST][n]) for n in names}
    return p


binaries_of = runlib.binaries_of


# ---------------------------------------------------------------- the session


def fingerprint() -> dict:
    """Section 7's per-session record on W (wwindow.fingerprint)."""
    return wwindow.fingerprint()


def w_session(session: dict) -> dict:
    """The engine's session with what W's windows read from the session's fingerprint: the lab
    plan (W's procedure: active at each window's start and end), the frequency counter's session
    reading, and the cycle rate (W's WL4 in time)."""
    fp = session.get("fingerprint") or {}
    return dict(session, lab_plan=fp.get("lab_plan"), frequency=fp.get("frequency"), cycle_rate=fp.get("cycle_rate"))


def freeze_check(a: argparse.Namespace, prov: dict, names: tuple[str, ...], *, need_pilot: bool = True, rule_e: Path | None = None,
                 extra_entries: tuple[str, ...] = ()) -> freeze_guard.Clearance:
    """freeze_guard.check for a frozen W run: W's gate (gate-W.json of W's record at CODE_FREEZE),
    the binaries this run starts, and the entries W's runners apply."""
    return freeze_guard.check(code_freeze=a.code_freeze, seeds=a.seeds, gates=a.gate, need_pilot=need_pilot,
                              pilot=getattr(a, "pilot", None) if need_pilot else None, rule_e=rule_e,
                              binaries=binaries_of(prov, names), entries=ENTRIES + tuple(extra_entries))


def journal_note(a: argparse.Namespace) -> str:
    return "development data on W, never a result" if a.development else "frozen run on W"
