#!/usr/bin/env python3
"""The frequency check of design/w-procedure.md, section 4: one engineering test of the counter
against a known load (not a window). With the lab plan of section 2 active (wpower.LabPlan):
1. idle: `% Processor Performance` and `Actual Frequency` of CPU 10, sampled at 1 s for 10 s;
2. load: a spin loop pinned to CPU 10 (`wsys.py spin`), the same samples;
3. control: the same load under Alex's plan (boost mode Aggressive), after the lab plan's session
   has restored it.
The draft's pass rule (a design choice of section 4): with boost off, every load sample of the
counter lies within 2% of the load samples' mean; and with boost on, the counter's load mean
differs from the boost-off load mean by more than 2%, so the counter shows a change of frequency at
all. If it does not pass, W windows are validated without the frequency rule and the paper says so
(hypotheses.md section 9.1).

The sampler runs on CPU 0 (this process's affinity), section 4's core 0. `% Processor Time` of CPU
10 is sampled beside them, so each phase shows whether CPU 10 was idle or loaded.

    wfreq.py --out DIR [--seconds 10] [--lead 1.5]
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import wpower  # noqa: E402
import wsys  # noqa: E402

CPU = 10
COUNTER = "% Processor Performance"
BESIDE = ("Actual Frequency", "% Processor Time")
DRIFT = 0.02  # section 4's 2%, by analogy with L's frequency rule (hypotheses.md section 7)


def judge(off_load: list[float], on_load: list[float], drift: float = DRIFT) -> dict:
    """Section 4's rule over the counter's load samples with boost off and with boost on."""
    if not off_load or not on_load:
        return {"pass": False, "reason": "no samples"}
    m_off = statistics.fmean(off_load)
    m_on = statistics.fmean(on_load)
    worst = max(abs(x - m_off) / m_off for x in off_load) if m_off else float("inf")
    stable = worst <= drift
    moved = abs(m_on - m_off) / m_off > drift if m_off else False
    return {"pass": stable and moved, "boost_off_load_mean": m_off, "boost_off_worst_drift": worst, "stable_within_2pct": stable,
            "boost_on_load_mean": m_on, "on_vs_off": (m_on - m_off) / m_off if m_off else None, "moved_more_than_2pct": moved,
            "drift": drift}


def series(samples: list[dict], counter: str, cpu: int = CPU) -> list[float]:
    return [s["cpus"][str(cpu)][counter] for s in samples if s["cpus"][str(cpu)][counter] is not None]


def phase(name: str, seconds: int, load: bool, lead: float) -> dict:
    """One phase: optionally the spin load on CPU 10, then `seconds` samples at 1 s."""
    spinner = None
    out: dict = {"phase": name, "load": load, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if load:
        spinner = wsys.start_pinned([sys.executable, str(HERE / "wsys.py"), "spin", str(seconds + lead + 2)], [CPU],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out["spinner_pid"] = spinner.pid
        out["spinner_affinity"] = hex(wsys.affinity(spinner.pid))
        time.sleep(lead)
    s = wsys.Sampler([CPU], 1.0)
    s.start()
    deadline = time.monotonic() + seconds + 0.5
    while len(s.samples) < seconds and time.monotonic() < deadline + 2:
        time.sleep(0.1)
    samples = s.stop()[:seconds]
    out["sampler_error"] = s.error
    out["samples"] = samples
    if spinner is not None:
        try:
            so, _ = spinner.communicate(timeout=seconds + lead + 30)
            out["spinner"] = json.loads(so.decode().strip().splitlines()[-1])
        except (subprocess.TimeoutExpired, IndexError, json.JSONDecodeError) as e:
            spinner.kill()  # a process this test started
            spinner.wait()
            out["spinner_error"] = repr(e)
        out["spinner_exit"] = spinner.returncode
    for k in (COUNTER,) + BESIDE:
        v = series(samples, k)
        out[k] = {"values": v, "mean": statistics.fmean(v) if v else None, "min": min(v) if v else None, "max": max(v) if v else None}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--lead", type=float, default=1.5, help="seconds between the spinner's start and the first sample")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    rec: dict = {"test": "w-procedure section 4, the frequency counter against a known load (an engineering test, not a window)",
                 "cpu": CPU, "counter": COUNTER, "beside": list(BESIDE), "seconds": a.seconds, "lead_s": a.lead}
    wsys.set_own_affinity(wsys.HOUSEKEEPING[:1])  # the sampler on core 0 (CPU 0)
    rec["sampler_affinity"] = hex(wsys.affinity())
    cores = wsys.core_layout()
    rec["core_layout"] = cores
    rec["core_problems"] = wsys.check_core_layout(cores)
    rec["timer_resolution"] = wsys.timer_resolution()
    rec["state"] = wsys.defender_and_update()
    rec["quiet"] = wsys.quiet_check()
    out_path = a.out / f"freq-{stamp}.json"
    plan_record = a.out / f"freq-{stamp}.plan.json"
    phases = []
    try:
        with wpower.LabPlan(plan_record):
            phases.append(phase("idle, lab plan", a.seconds, False, a.lead))
            phases.append(phase("load, lab plan", a.seconds, True, a.lead))
        rec["control_plan"] = wpower.active()
        phases.append(phase("load, Alex's plan (control)", a.seconds, True, a.lead))
    finally:
        rec["phases"] = phases
        try:
            rec["plan_record"] = json.loads(plan_record.read_text())
        except (OSError, json.JSONDecodeError):
            rec["plan_record"] = None
        rec["active_after"] = wpower.active()
        if len(phases) == 3:
            rec["verdict"] = judge(phases[1][COUNTER]["values"], phases[2][COUNTER]["values"])
            rec["verdict_actual_frequency"] = judge(phases[1]["Actual Frequency"]["values"], phases[2]["Actual Frequency"]["values"])
        out_path.write_text(json.dumps(rec, indent=1))
    for p in phases:
        print(f"{p['phase']}: {COUNTER} mean {p[COUNTER]['mean']} [{p[COUNTER]['min']}, {p[COUNTER]['max']}]; "
              f"Actual Frequency mean {p['Actual Frequency']['mean']}; % Processor Time mean {p['% Processor Time']['mean']}")
    print(json.dumps({"verdict": rec.get("verdict"), "verdict_actual_frequency": rec.get("verdict_actual_frequency"),
                      "active_after": rec["active_after"], "record": str(out_path)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
