#!/usr/bin/env python3
"""The unattended night launcher of W (M6b, the coordinator's task of 2026-10-03): after a delay, it
tries the frequency retest (wfreq.py --control cap --require-quiet, design/w-procedure.md section
4 as revised) and the W A/A job (wjob.py run ... waa.py, dedicated mode only), each through its own
checks, and tries again later while W is not quiet. It weakens nothing: the quiet check, its
thresholds and every other check are the scripts' own; it never elevates and never ends a process
by its name.

    wnight.py --dir DIR --src SRC --build BUILD --freq-src FREQSRC [--first-delay-s 600] [--retry-s 600]
              [--settle-s 120] [--no-aa-after 2026-10-04T05:00] [--no-start-after 2026-10-04T07:45]
              [--cutoff 2026-10-04T08:00] [--aa-dir C:\\Users\\alext\\lab\\p3\\w-aa] [--aa-name waa2]
              [--freq-out DIR] [--wjob PATH] [--waa PATH] [--wfreq PATH]

Files in DIR: wnight.pid (this process), wnight.log (JSON lines, one event each), wnight.done (how
it ended, JSON), and the stop file wnight.stop, which makes it exit at the next loop (checked also
during its sleeps). A job already running is stopped with `wjob.py stop --dir AA_DIR --name AA_NAME`,
not by the stop file.

Each loop, after the first delay:
1. The retest, if it has not completed and has not failed, and no later than --no-start-after:
   wfreq.py exits 0 when it ran its three phases (completed, whatever its verdict), 3 when its own
   quiet check refused (logged with the reasons, the top processes and each CPU's idle; tried again
   next loop), anything else is a failure (logged; not tried again). The active plan is read after
   it; if it is not Alex's plan, `wpower.py restore` sets Alex's plan back.
2. The A/A job, if it has not run, and no later than --no-aa-after: `wjob.py run --dir AA_DIR --name
   AA_NAME -- python waa.py --build BUILD --out AA_DIR\\AA_NAME --job AA_NAME` with the 12 cells, 6
   sessions, seed 861 and K_SRC 16. A refusal by the quiet check (exit 90) or by an update installing
   (exit 92) is logged with the preflight's reasons, top processes and each CPU's idle; the refused
   attempt's files are renamed AA_NAME-refused<N>.*, and it is tried again next loop. Any other exit
   means the job ran or cannot run; it is not started again. While the job runs this process waits
   for it; at --cutoff it asks the job to stop (wjob.py stop) and waits for it.
3. If a step was refused, sleep --retry-s; after the A/A job ended, sleep --settle-s; then loop.
It exits when nothing is left to try, at the stop file, or at --cutoff.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ALEX_PLAN = "00acab9f-6807-4927-af55-c72a4c589dad"
CELLS = ("churn:http1,churn:h2c,churn:tls,churn:mqtt,keepalive:http1,keepalive:h2c,keepalive:tls,keepalive:mqtt,"
         "open:http1,open:h2c,open:tls,open:mqtt")
SESSIONS = 6
SEED = 861
K_SRC = 16
RETRY_EXITS = (90, 92)  # wjob.py: W not quiet; an update installing
FREQ_SKIPPED = 3        # wfreq.py --require-quiet: W not quiet, no plan switched
STOP_WAIT_S = 300.0     # after wjob.py stop at the cutoff (its own grace is 120 s)
TICK_S = 5.0
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def now() -> datetime:
    return datetime.now().astimezone()


def stamp() -> str:
    return now().strftime("%Y-%m-%dT%H:%M:%S%z")


def local_time(text: str) -> datetime:
    """An ISO time; without an offset it is W's local time."""
    return datetime.fromisoformat(text).astimezone()


class Night:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.dir: Path = a.dir
        self.log_path = self.dir / "wnight.log"
        self.stop_path = self.dir / "wnight.stop"
        self.retest = "pending"   # pending, completed, failed, out_of_time
        self.aa = "pending"       # pending, ran, cannot_run, out_of_time
        self.aa_refusals = 0

    # ---- records

    def log(self, event: str, **kw) -> None:
        rec = {"t": stamp(), "event": event, **kw}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def sleep(self, seconds: float, why: str) -> str | None:
        """Sleeps up to `seconds`, waking at the stop file or the cutoff; returns why it woke early."""
        self.log("sleep", seconds=seconds, why=why)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stop_requested():
                return "stop file"
            if now() >= self.a.cutoff:
                return "cutoff"
            time.sleep(min(TICK_S, max(0.0, end - time.monotonic())))
        return None

    # ---- the power plan

    def active_plan(self) -> dict:
        p = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = GUID_RE.search(p.stdout or "")
        return {"guid": m.group(0).lower() if m else None, "text": (p.stdout or p.stderr or "").strip()}

    def check_plan(self, after: str) -> None:
        plan = self.active_plan()
        self.log("plan", after=after, active=plan)
        if plan["guid"] != ALEX_PLAN:
            r = subprocess.run([sys.executable, str(self.a.wpower), "restore"], capture_output=True, text=True)
            self.log("plan_restore", exit=r.returncode, output=(r.stdout + r.stderr).strip()[-500:], active=self.active_plan())

    # ---- the retest

    def run_retest(self) -> bool:
        """One attempt; True if it was refused by its quiet check (worth another try)."""
        out: Path = self.a.freq_out
        out.mkdir(parents=True, exist_ok=True)
        before = set(out.glob("freq-*.json"))
        cmd = [sys.executable, str(self.a.wfreq), "--out", str(out), "--control", "cap", "--require-quiet"]
        self.log("retest_start", cmd=cmd)
        r = subprocess.run(cmd, capture_output=True, text=True)
        new = sorted(p for p in set(out.glob("freq-*.json")) - before if not p.name.endswith(".plan.json"))
        rec: dict = {}
        if new:
            try:
                rec = json.loads(new[-1].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                rec = {"read_error": repr(e)}
        q = rec.get("quiet") or {}
        quiet = {"quiet": q.get("quiet"), "reasons": q.get("reasons"), "idle_percent_mean": q.get("idle_percent_mean"),
                 "cpu_idle_percent": q.get("cpu_idle_percent"), "top_processes": (q.get("top_processes") or [])[:8]}
        base = {"exit": r.returncode, "record": str(new[-1]) if new else None, "quiet_check": quiet}
        refused = False
        if r.returncode == 0 and "verdict" in rec:
            self.retest = "completed"
            phases = [{"phase": p.get("phase"), "pp_mean": (p.get("% Processor Performance") or {}).get("mean"),
                       "af_mean": (p.get("Actual Frequency") or {}).get("mean"), "work_rate": p.get("work_rate")}
                      for p in rec.get("phases", [])]
            self.log("retest_completed", **base, cap_plan=rec.get("cap_plan"), verdict=rec.get("verdict"),
                     verdict_actual_frequency=rec.get("verdict_actual_frequency"), outcome=rec.get("outcome"),
                     outcome_actual_frequency=rec.get("outcome_actual_frequency"), phases=phases)
        elif r.returncode == FREQ_SKIPPED and rec.get("skipped"):
            refused = True
            self.log("retest_refused", **base)
        else:
            self.retest = "failed"
            self.log("retest_failed", **base, output=(r.stdout + r.stderr)[-2000:])
        self.check_plan("retest")
        return refused

    # ---- the A/A job

    def aa_files(self) -> list[Path]:
        d, n = self.a.aa_dir, self.a.aa_name
        return [d / f"{n}{s}" for s in (".pid", ".start", ".preflight.json", ".done", ".log", ".plan.json")]

    def aa_cmd(self) -> list[str]:
        d, n = self.a.aa_dir, self.a.aa_name
        return [sys.executable, str(self.a.wjob), "run", "--dir", str(d), "--name", n, "--",
                sys.executable, str(self.a.waa), "--build", str(self.a.build), "--out", str(d / n), "--job", n,
                "--cells", CELLS, "--sessions", str(SESSIONS), "--seed", str(SEED), "--k-src", str(K_SRC)]

    def run_aa(self) -> str:
        """One attempt: "refused" (try again), "ran", "cannot_run" or "stopped_at_cutoff"."""
        d, n = self.a.aa_dir, self.a.aa_name
        d.mkdir(parents=True, exist_ok=True)
        done = d / f"{n}.done"
        if done.exists():
            self.log("aa_skip", why=f"{done} exists from an earlier run", done=json.loads(done.read_text(encoding="utf-8")))
            return "cannot_run"
        cmd = self.aa_cmd()
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.log("aa_start", pid=p.pid, cmd=cmd)
        stopped = False
        while p.poll() is None:
            if not stopped and now() >= self.a.cutoff:
                r = subprocess.run([sys.executable, str(self.a.wjob), "stop", "--dir", str(d), "--name", n], capture_output=True, text=True)
                self.log("aa_stop_at_cutoff", exit=r.returncode, output=(r.stdout + r.stderr).strip()[-500:])
                stopped = True
                try:
                    p.wait(timeout=STOP_WAIT_S)
                except subprocess.TimeoutExpired:
                    self.log("aa_still_running", pid=p.pid, waited_s=STOP_WAIT_S)
                    return "stopped_at_cutoff"
                break
            time.sleep(TICK_S)
        try:
            info = json.loads(done.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            info = {"read_error": repr(e)}
        if info.get("exit") in RETRY_EXITS and info.get("refused"):
            self.aa_refusals += 1
            try:
                pre = json.loads((d / f"{n}.preflight.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pre = {}
            q = pre.get("quiet") or {}
            self.log("aa_refused", attempt=self.aa_refusals, exit=info.get("exit"), refused=info.get("refused"),
                     reasons=q.get("reasons"), idle_percent_mean=q.get("idle_percent_mean"),
                     idle_percent_samples=q.get("idle_percent_samples"), cpu_idle_percent=q.get("cpu_idle_percent"),
                     top_processes=(q.get("top_processes") or [])[:8], update_installing=pre.get("update_installing"))
            moved = []
            for f in self.aa_files():
                if f.exists():
                    to = f.with_name(f.name.replace(n, f"{n}-refused{self.aa_refusals}", 1))
                    f.rename(to)
                    moved.append(to.name)
            self.log("aa_refused_files", moved=moved)
            return "refused"
        self.log("aa_end", exit=p.returncode, done=info, stopped_at_cutoff=stopped)
        return "stopped_at_cutoff" if stopped else ("ran" if info.get("exit") not in (91, 95, 96, 1, None) else "cannot_run")

    # ---- the loop

    def main(self) -> str:
        a = self.a
        self.log("start", pid=os.getpid(), python=sys.executable, first_attempt_at=a.first_at.isoformat(timespec="seconds"),
                 no_aa_after=a.no_aa_after.isoformat(timespec="seconds"), no_start_after=a.no_start_after.isoformat(timespec="seconds"),
                 cutoff=a.cutoff.isoformat(timespec="seconds"), retry_s=a.retry_s, settle_s=a.settle_s, aa_cmd=self.aa_cmd(),
                 wfreq=str(a.wfreq), freq_out=str(a.freq_out), plan=self.active_plan())
        woke = self.sleep(max(0.0, (a.first_at - now()).total_seconds()), "first delay")
        if woke:
            return woke
        while True:
            if self.stop_requested():
                return "stop file"
            t = now()
            if t >= a.cutoff:
                return "cutoff"
            if self.retest == "pending" and t >= a.no_start_after:
                self.retest = "out_of_time"
            if self.aa == "pending" and t >= a.no_aa_after:
                self.aa = "out_of_time"
            if self.retest != "pending" and self.aa != "pending":
                return "nothing left"
            refused = False
            if self.retest == "pending":
                refused = self.run_retest()
                if self.stop_requested():
                    return "stop file"
            if self.aa == "pending" and now() < a.no_aa_after:
                res = self.run_aa()
                if res == "refused":
                    refused = True
                else:
                    self.aa = res
                    self.check_plan("aa")
                    if res == "stopped_at_cutoff":
                        return "cutoff"
                    if res == "ran" and self.retest == "pending":
                        woke = self.sleep(a.settle_s, "settle after the A/A job")
                        if woke:
                            return woke
                        continue
            if refused:
                woke = self.sleep(a.retry_s, "a step was refused")
                if woke:
                    return woke


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--src", type=Path, required=True, help="the A/A job's source copy (its bench/run scripts)")
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--freq-src", type=Path, required=True, help="a copy with the retest code (wfreq.py --require-quiet)")
    ap.add_argument("--first-delay-s", type=float, default=600.0)
    ap.add_argument("--retry-s", type=float, default=600.0)
    ap.add_argument("--settle-s", type=float, default=120.0)
    ap.add_argument("--no-aa-after", default="2026-10-04T05:00")
    ap.add_argument("--no-start-after", default="2026-10-04T07:45")
    ap.add_argument("--cutoff", default="2026-10-04T08:00")
    ap.add_argument("--aa-dir", type=Path, default=Path(r"C:\Users\alext\lab\p3\w-aa"))
    ap.add_argument("--aa-name", default="waa2")
    ap.add_argument("--freq-out", type=Path, default=Path(r"C:\Users\alext\lab\p3\m6b\freq"))
    ap.add_argument("--wjob", type=Path, help="default: SRC\\bench\\run\\wjob.py")
    ap.add_argument("--waa", type=Path, help="default: SRC\\bench\\run\\waa.py")
    ap.add_argument("--wfreq", type=Path, help="default: FREQ_SRC\\bench\\run\\wfreq.py")
    ap.add_argument("--wpower", type=Path, help="default: FREQ_SRC\\bench\\run\\wpower.py")
    a = ap.parse_args(argv)
    a.wjob = a.wjob or a.src / "bench" / "run" / "wjob.py"
    a.waa = a.waa or a.src / "bench" / "run" / "waa.py"
    a.wfreq = a.wfreq or a.freq_src / "bench" / "run" / "wfreq.py"
    a.wpower = a.wpower or a.freq_src / "bench" / "run" / "wpower.py"
    a.no_aa_after = local_time(a.no_aa_after)
    a.no_start_after = local_time(a.no_start_after)
    a.cutoff = local_time(a.cutoff)
    a.dir.mkdir(parents=True, exist_ok=True)
    a.first_at = datetime.fromtimestamp(time.time() + a.first_delay_s).astimezone()
    (a.dir / "wnight.pid").write_text(str(os.getpid()))
    night = Night(a)
    reason = None
    try:
        reason = night.main()
    except BaseException as e:  # noqa: BLE001 - recorded in the done file, then raised
        reason = f"error: {e!r}"
        night.log("error", error=repr(e))
        raise
    finally:
        done = {"end": stamp(), "reason": reason, "retest": night.retest, "aa": night.aa,
                "aa_refusals": night.aa_refusals, "plan": night.active_plan()}
        (a.dir / "wnight.done").write_text(json.dumps(done))
        night.log("exit", **done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
