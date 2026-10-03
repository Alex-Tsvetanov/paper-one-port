#!/usr/bin/env python3
"""One lab job on W, the W side of lab_job.sh (design/status-m6b.md).

    wjob.py run --dir DIR --name NAME [--allow-noisy] -- COMMAND [ARGS...]
    wjob.py stop --dir DIR --name NAME

`run`:
1. writes DIR/NAME.pid (this process's id: the job is stopped by it, never by a name) and
   DIR/NAME.start;
2. takes W's lab lock (wlock.py; at most 4 h, as lablock), so two jobs never overlap;
3. the checks before a session (DIR/NAME.preflight.json): the core layout of w-procedure section
   1 (refused if it differs, exit 91); Windows Update not installing (refused if it is, exit 92;
   read only); Defender's real-time state and the timer resolution (recorded, read only); the lab
   plan exists (else exit 95); and the quiet check of section 5 (refused if W is not quiet, exit
   90, unless --allow-noisy, which runs the job as a functional check: recorded, and passed to the
   command as ONEPORT_W_FUNCTIONAL=1);
4. under the lab plan (wpower.LabPlan: set and read back; Alex's plan set and read back at the end,
   also on failure, on Ctrl+C or Ctrl+Break, on the console's close, and by a guard process if this
   process is killed), runs COMMAND with its output in DIR/NAME.log;
5. writes DIR/NAME.done with the exit status, the end time, whether it was stopped and whether
   Alex's plan was restored.
`stop` asks a running job to stop: it sets the job's stop event; the job asks its command to stop
the same way (the command's finally blocks stop the servers it started, by their events), waits for
it at most 120 s, ends it only if it is still running then (a process the job started), and
restores Alex's plan.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import wlock  # noqa: E402
import wpower  # noqa: E402
import wsys  # noqa: E402

EXIT_NOT_QUIET = 90
EXIT_CORES = 91
EXIT_UPDATING = 92
EXIT_POWER = 95
EXIT_ADMIN = 96
STOP_GRACE_S = 120.0


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def preflight(allow_noisy: bool) -> tuple[dict, int]:
    """The checks before a W session; (record, 0) or (record, a refusal's exit status)."""
    rec: dict = {"at": now()}
    cores = wsys.core_layout()
    rec["core_layout"] = cores
    rec["core_problems"] = wsys.check_core_layout(cores)
    if rec["core_problems"]:
        return rec, EXIT_CORES
    rec["state"] = wsys.defender_and_update()
    rec["update_installing"] = wsys.update_installing(rec["state"])
    if rec["update_installing"]:
        return rec, EXIT_UPDATING
    rec["timer_resolution"] = wsys.timer_resolution()
    rec["lab_plan"] = wpower.lab_plan_guid()
    rec["active_plan"] = wpower.active()
    if rec["lab_plan"] is None:
        return rec, EXIT_POWER
    rec["quiet"] = wsys.quiet_check()
    rec["functional_check"] = not rec["quiet"]["quiet"]
    if not rec["quiet"]["quiet"] and not allow_noisy:
        return rec, EXIT_NOT_QUIET
    return rec, 0


def run(a) -> int:
    a.dir.mkdir(parents=True, exist_ok=True)
    base = a.dir / a.name
    Path(f"{base}.pid").write_text(str(os.getpid()))
    Path(f"{base}.start").write_text(now())
    stopped = {"requested": False}
    child: dict = {}

    def on_stop() -> None:
        stopped["requested"] = True
        p = child.get("proc")
        if p is not None and p.poll() is None:
            wsys.set_named_event(wsys.job_stop_name(p.pid))

    wsys.watch_stop(on_stop)
    done = {"exit": None, "signal": None, "functional_check": None}
    try:
        with wlock.WLock() as lock:
            done["lock_waited_s"] = lock.waited_s
            pre, refused = preflight(a.allow_noisy)
            Path(f"{base}.preflight.json").write_text(json.dumps(pre, indent=1))
            done["functional_check"] = pre.get("functional_check")
            if refused:
                done["exit"] = refused
                done["refused"] = {EXIT_CORES: "core layout", EXIT_UPDATING: "an update is installing", EXIT_POWER: "no lab plan",
                                   EXIT_NOT_QUIET: "W is not quiet"}[refused]
                return refused
            env = dict(os.environ, ONEPORT_W_JOB=a.name, ONEPORT_W_JOB_DIR=str(a.dir))
            if pre.get("functional_check"):
                env["ONEPORT_W_FUNCTIONAL"] = "1"
            cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
            with wpower.LabPlan(Path(f"{base}.plan.json")):
                with open(f"{base}.log", "wb") as log:
                    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
                    child["proc"] = p
                    try:
                        while p.poll() is None:
                            time.sleep(0.5)
                    except BaseException:
                        on_stop()
                        raise
                    finally:
                        if p.poll() is None:
                            try:
                                p.wait(timeout=STOP_GRACE_S)
                            except subprocess.TimeoutExpired:
                                p.kill()  # the command this job started, still running after the grace
                                p.wait()
                                done["killed_after_grace"] = True
                done["exit"] = p.returncode
                if stopped["requested"]:
                    done["signal"] = "stop"
            return done["exit"]
    except wlock.LockTimeout as e:
        done["exit"] = 1
        done["error"] = str(e)
        return 1
    except wpower.AdminNeeded as e:
        done["exit"] = EXIT_ADMIN
        done["error"] = f"needs administrator rights, stopped (nothing elevated): {e}"
        return EXIT_ADMIN
    except wpower.PowerError as e:
        done["exit"] = EXIT_POWER
        done["error"] = str(e)
        return EXIT_POWER
    except (KeyboardInterrupt, SystemExit) as e:
        done["signal"] = "stop" if stopped["requested"] else repr(e)
        if done["exit"] is None:
            done["exit"] = 130
        return done["exit"]
    finally:
        try:
            plan = json.loads(Path(f"{base}.plan.json").read_text())
            done["plan_restored"] = plan.get("restored")
        except (OSError, json.JSONDecodeError):
            done["plan_restored"] = None
        done["stop_requested"] = stopped["requested"]
        done["end"] = now()
        Path(f"{base}.done").write_text(json.dumps(done))


def stop(a) -> int:
    pid = int(Path(a.dir / f"{a.name}.pid").read_text().strip())
    if wsys.set_named_event(wsys.job_stop_name(pid)):
        print(f"wjob: asked job {a.name} (pid {pid}) to stop")
        return 0
    print(f"wjob: job {a.name} (pid {pid}) has no stop event (not running?)", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dir", type=Path, required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--allow-noisy", action="store_true", help="run although W is not quiet, as a functional check (recorded)")
    r.add_argument("command", nargs=argparse.REMAINDER)
    s = sub.add_parser("stop")
    s.add_argument("--dir", type=Path, required=True)
    s.add_argument("--name", required=True)
    a = ap.parse_args(argv)
    return run(a) if a.cmd == "run" else stop(a)


if __name__ == "__main__":
    sys.exit(main())
