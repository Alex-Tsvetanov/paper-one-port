#!/usr/bin/env python3
"""W's power plan for measurement sessions (design/w-procedure.md, section 2; Alex's decision 1 of
2026-10-03), with no administrator rights.

- `create`, once: duplicates High performance (8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c) into a plan
  named "oneport W windows" with exactly section 2's commands: performance boost mode 0
  (Disabled), minimum and maximum processor state 100%, core parking minimum cores 100%, each on
  AC. Refused if a plan of that name exists.
- A session (`LabPlan`, or `run -- COMMAND`): makes the lab plan active and reads it back (the
  active scheme and the four AC values, which must be as set), runs, and at its end makes Alex's
  plan "ChrisTitus - Ultimate Power Plan" (00acab9f-6807-4927-af55-c72a4c589dad) active again and
  reads that back; also on an error, on Ctrl+C or Ctrl+Break, and on the console's close. A guard
  process started at the switch restores Alex's plan if the session's process ends without having
  restored it (killed). A session refuses to start if the active plan is neither Alex's nor the lab
  plan (a plan Alex chose is never overwritten), and records which it found.
- `create-cap`, once: the frequency test's control plan "oneport W cap50" (w-procedure section 4,
  the revision of 2026-10-03), a duplicate of the lab plan with the minimum and maximum processor
  state at 50%. wfreq.py switches to it inside a lab-plan session, so the session's end and its
  guard set Alex's plan back as for the lab plan. Refused if a plan of that name exists.
- Every powercfg command's exit status and output are checked: an answer of "access denied" (or
  any failure) stops the session with AdminNeeded or PowerError and nothing is elevated.

The record (JSON, written as it goes) holds the plan found active before, the lab plan's read-back,
when it was set, Alex's plan's read-back after, and when it was restored.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
ALEX_PLAN = "00acab9f-6807-4927-af55-c72a4c589dad"
ALEX_PLAN_NAME = "ChrisTitus - Ultimate Power Plan"
LAB_PLAN_NAME = "oneport W windows"
SUB_PROCESSOR = "54533251-82be-4824-96c1-47b60b740d00"
# Section 2's settings, by GUID (boost mode and core parking are hidden settings; powercfg /QH shows
# them): name, alias, the AC value the lab plan sets.
BOOST_MODE = "be337238-0d82-4146-a960-4f3749d470c7"
PROC_MIN = "893dee8e-2bef-41e0-89c6-b55d0929964c"
PROC_MAX = "bc5038f7-23e0-4960-96da-33abaf5935ec"
CP_MIN_CORES = "0cc5b647-c1df-4637-891a-dec35c318583"
IDLE_DISABLE = "5d76a2ca-e8c0-402f-a133-2158492d58ad"
LAB_VALUES = {BOOST_MODE: 0, PROC_MIN: 100, PROC_MAX: 100, CP_MIN_CORES: 100}
SETTING_NAMES = {BOOST_MODE: "performance boost mode", PROC_MIN: "minimum processor state", PROC_MAX: "maximum processor state",
                 CP_MIN_CORES: "core parking min cores", IDLE_DISABLE: "processor idle disable"}
# Section 2's command list, in its order (the boost and parking settings by GUID, the states by alias).
SET_COMMANDS = [("SUB_PROCESSOR", BOOST_MODE, 0), ("SUB_PROCESSOR", "PROCTHROTTLEMIN", 100), ("SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
                ("SUB_PROCESSOR", CP_MIN_CORES, 100)]

# The frequency test's control plan (w-procedure section 4, the revision of 2026-10-03, approved by
# Alex): the lab plan with the maximum processor state capped at CAP_STATE and the minimum set to
# the cap, so the test's load runs at a state that surely differs from the lab plan's. Used only by
# wfreq.py, never by a window. Its states are set minimum first, so the minimum never exceeds the
# maximum on the way.
CAP_PLAN_NAME = "oneport W cap50"
CAP_STATE = 50
CAP_VALUES = {BOOST_MODE: 0, PROC_MIN: CAP_STATE, PROC_MAX: CAP_STATE, CP_MIN_CORES: 100}
CAP_SET_COMMANDS = [("SUB_PROCESSOR", "PROCTHROTTLEMIN", CAP_STATE), ("SUB_PROCESSOR", "PROCTHROTTLEMAX", CAP_STATE)]

GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
STATE_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "lab" / "p3"
PLAN_FILE = STATE_DIR / "w-plan.json"
CAP_PLAN_FILE = STATE_DIR / "w-cap-plan.json"


class PowerError(RuntimeError):
    pass


class AdminNeeded(PowerError):
    """A powercfg command answered that it needs administrator rights: stop, never elevate."""


# ---------------------------------------------------------------- parsers (every platform)


def parse_list(text: str) -> list[dict]:
    """`powercfg /L`: each plan's GUID, name and whether it is active (marked *)."""
    out = []
    for ln in text.splitlines():
        m = GUID_RE.search(ln)
        if not m or ":" not in ln:
            continue
        name = re.search(r"\((.*)\)", ln[m.end():])
        out.append({"guid": m.group(0).lower(), "name": name.group(1) if name else "", "active": ln.rstrip().endswith("*")})
    return out


def parse_active(text: str) -> dict:
    """`powercfg /getactivescheme`: the active plan's GUID and name."""
    m = GUID_RE.search(text)
    if not m:
        raise PowerError(f"no GUID in {text!r}")
    name = re.search(r"\((.*)\)", text[m.end():])
    return {"guid": m.group(0).lower(), "name": name.group(1) if name else ""}


def parse_duplicate(text: str) -> str:
    """`powercfg /duplicatescheme`: the new plan's GUID."""
    m = GUID_RE.search(text)
    if not m:
        raise PowerError(f"duplicatescheme printed no GUID: {text!r}")
    return m.group(0).lower()


def parse_qh(text: str) -> dict:
    """`powercfg /QH <plan> SUB_PROCESSOR`: per setting GUID, its name, alias and AC and DC values.
    Read by GUID and by the 0x value lines, so a reading does not rest on the setting's name."""
    out: dict[str, dict] = {}
    cur = None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("Power Setting GUID:"):
            m = GUID_RE.search(s)
            name = re.search(r"\((.*)\)", s[m.end():]) if m else None
            cur = m.group(0).lower() if m else None
            if cur:
                out[cur] = {"name": name.group(1) if name else "", "alias": None, "ac": None, "dc": None}
        elif cur and s.startswith("GUID Alias:"):
            out[cur]["alias"] = s.split(":", 1)[1].strip()
        elif cur and s.startswith("Current AC Power Setting Index:"):
            out[cur]["ac"] = int(s.split(":", 1)[1].strip(), 16)
        elif cur and s.startswith("Current DC Power Setting Index:"):
            out[cur]["dc"] = int(s.split(":", 1)[1].strip(), 16)
    return out


def check_values(qh: dict, wanted: dict = LAB_VALUES) -> list[str]:
    """Problems of a read-back against the AC values section 2 sets; empty when every one holds."""
    problems = []
    for g, v in wanted.items():
        got = (qh.get(g) or {}).get("ac")
        if got != v:
            problems.append(f"{SETTING_NAMES[g]} ({g}) reads {got}, expected {v}")
    return problems


def denied(text: str) -> bool:
    t = text.lower()
    return "access is denied" in t or "access denied" in t or "administrator" in t or "elevat" in t


# ---------------------------------------------------------------- powercfg


def powercfg(*args: str) -> str:
    # powercfg writes UTF-8 when its output is a pipe (read on W: "AMD Ryzen" plans' trademark sign).
    p = subprocess.run(["powercfg", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    text = (p.stdout or "") + (p.stderr or "")
    if denied(text):
        raise AdminNeeded(f"powercfg {' '.join(args)}: {text.strip()[-300:]}")
    if p.returncode != 0:
        raise PowerError(f"powercfg {' '.join(args)} exited {p.returncode}: {text.strip()[-300:]}")
    return p.stdout


def plans() -> list[dict]:
    return parse_list(powercfg("/L"))


def active() -> dict:
    return parse_active(powercfg("/getactivescheme"))


def processor_settings(plan: str) -> dict:
    return parse_qh(powercfg("/QH", plan, "SUB_PROCESSOR"))


def plan_guid(name: str) -> str | None:
    """A plan's GUID, found by its name; refuses two plans of that name."""
    found = sorted({p["guid"] for p in plans() if p["name"] == name})
    if len(found) > 1:
        raise PowerError(f"{len(found)} plans are named {name!r}: {found}")
    return found[0] if found else None


def lab_plan_guid() -> str | None:
    """The lab plan's GUID, found by its name; refuses two plans of that name."""
    return plan_guid(LAB_PLAN_NAME)


def cap_plan_guid() -> str | None:
    """The frequency test's control plan's GUID, found by its name; refuses two plans of that name."""
    return plan_guid(CAP_PLAN_NAME)


def create(record: Path | None = None) -> dict:
    """Section 2's commands, once. Returns what was run and read back."""
    if lab_plan_guid():
        raise PowerError(f"a plan named {LAB_PLAN_NAME!r} exists already: {lab_plan_guid()}")
    log = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "commands": []}

    def run(*a: str) -> str:
        out = powercfg(*a)
        log["commands"].append({"args": list(a), "output": out.strip()})
        return out

    g = parse_duplicate(run("/duplicatescheme", HIGH_PERFORMANCE))
    log["guid"] = g
    run("/changename", g, LAB_PLAN_NAME)
    for sub, setting, value in SET_COMMANDS:
        run("/setacvalueindex", g, sub, setting, str(value))
    qh = processor_settings(g)
    log["readback"] = {k: qh.get(k) for k in SETTING_NAMES}
    log["problems"] = check_values(qh)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_FILE.write_text(json.dumps({"guid": g, "name": LAB_PLAN_NAME, "created": log}, indent=1))
    if record:
        record.write_text(json.dumps(log, indent=1))
    if log["problems"]:
        raise PowerError(f"the new plan does not read back as set: {log['problems']}")
    return log


def create_cap(record: Path | None = None) -> dict:
    """Once: the frequency test's control plan, a duplicate of the lab plan with CAP_SET_COMMANDS.
    Refused if a plan of that name exists or the lab plan does not. Returns what was run and read
    back."""
    lab = lab_plan_guid()
    if lab is None:
        raise PowerError(f"no plan named {LAB_PLAN_NAME!r}: run `wpower.py create` once")
    if cap_plan_guid():
        raise PowerError(f"a plan named {CAP_PLAN_NAME!r} exists already: {cap_plan_guid()}")
    log = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "from": lab, "commands": []}

    def run(*a: str) -> str:
        out = powercfg(*a)
        log["commands"].append({"args": list(a), "output": out.strip()})
        return out

    g = parse_duplicate(run("/duplicatescheme", lab))
    log["guid"] = g
    run("/changename", g, CAP_PLAN_NAME)
    for sub, setting, value in CAP_SET_COMMANDS:
        run("/setacvalueindex", g, sub, setting, str(value))
    qh = processor_settings(g)
    log["readback"] = {k: qh.get(k) for k in SETTING_NAMES}
    log["problems"] = check_values(qh, CAP_VALUES)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CAP_PLAN_FILE.write_text(json.dumps({"guid": g, "name": CAP_PLAN_NAME, "created": log}, indent=1))
    if record:
        record.write_text(json.dumps(log, indent=1))
    if log["problems"]:
        raise PowerError(f"the cap plan does not read back as set: {log['problems']}")
    return log


def readback(plan: str) -> dict:
    qh = processor_settings(plan)
    return {"active": active(), "settings": {k: qh.get(k) for k in SETTING_NAMES}, "processor_subgroup": qh}


def switch_within_session(plan: str, wanted: dict) -> dict:
    """Inside a LabPlan session only (its end and its guard set Alex's plan back, whatever plan is
    active then): makes `plan` active and reads it back. Returns the read-back and its problems;
    the caller stops on a problem."""
    powercfg("/setactive", plan)
    at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    rb = readback(plan)
    problems = check_values(rb["settings"], wanted)
    if rb["active"]["guid"] != plan:
        problems.append(f"the active plan reads {rb['active']}, not {plan}")
    return {"plan": plan, "set_at": at, "active": rb["active"], "settings": rb["settings"], "problems": problems}


# ---------------------------------------------------------------- a session


class LabPlan:
    """The lab plan for the length of a `with` block: set and read back at its start, Alex's plan
    set and read back at its end, however it ends."""

    def __init__(self, record: Path, guard: bool = True):
        self.record = record
        self.guard = guard
        self.rec: dict = {}
        self.guard_proc = None
        self._restored = False

    def _write(self) -> None:
        self.record.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.record.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.rec, indent=1))
        os.replace(tmp, self.record)

    def __enter__(self) -> "LabPlan":
        g = lab_plan_guid()
        if g is None:
            raise PowerError(f"no plan named {LAB_PLAN_NAME!r}: run `wpower.py create` once")
        before = active()
        self.rec = {"lab_plan": g, "alex_plan": ALEX_PLAN, "before": before, "pid": os.getpid()}
        if before["guid"] not in (ALEX_PLAN, g):
            self.rec["refused"] = f"the active plan is {before}, neither Alex's nor the lab plan; nothing changed"
            self._write()
            raise PowerError(self.rec["refused"])
        if before["guid"] == g:
            self.rec["note"] = "the lab plan was active before the session (an earlier session did not restore it)"
        self._install_handlers()
        if self.guard:
            self._start_guard()
        try:
            powercfg("/setactive", g)
            self.rec["set_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            self._write()
            rb = readback(g)
            self.rec["lab_readback"] = rb
            problems = check_values(rb["settings"])
            if rb["active"]["guid"] != g:
                problems.append(f"the active plan reads {rb['active']}, not the lab plan")
            self.rec["lab_problems"] = problems
            self._write()
            if problems:
                raise PowerError(f"the lab plan does not read back as set: {problems}")
        except BaseException:
            self.restore()
            raise
        return self

    def restore(self) -> dict:
        if self._restored:
            return self.rec.get("after", {})
        self._restored = True
        try:
            powercfg("/setactive", ALEX_PLAN)
            self.rec["restored_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            after = readback(ALEX_PLAN)
            self.rec["after"] = after
            self.rec["restored"] = after["active"]["guid"] == ALEX_PLAN
        except Exception as e:  # noqa: BLE001 - recorded; the guard tries again
            self.rec["restore_error"] = repr(e)
            self.rec["restored"] = False
        self._write()
        return self.rec.get("after", {})

    def __exit__(self, *exc) -> None:
        self.restore()
        self._stop_guard()

    def _install_handlers(self) -> None:
        def handler(signum, _frame):
            raise SystemExit(128 + signum)
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), handler)
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            # Console close, log off and shut down: Python's signals do not see them; restore
            # within the handler, which Windows lets run for a few seconds.
            HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

            def on_ctrl(kind):
                if kind in (2, 5, 6):  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
                    self.restore()
                return False

            self._ctrl = HANDLER(on_ctrl)
            ctypes.WinDLL("kernel32").SetConsoleCtrlHandler(self._ctrl, True)

    def _start_guard(self) -> None:
        flags = 0
        if sys.platform == "win32":
            flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW
        cmd = [sys.executable, str(Path(__file__).resolve()), "guard", "--pid", str(os.getpid()), "--record", str(self.record)]
        for extra in (0x01000000, 0):  # CREATE_BREAKAWAY_FROM_JOB if the job allows it
            try:
                self.guard_proc = subprocess.Popen(cmd, creationflags=flags | extra, stdin=subprocess.DEVNULL,
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.rec["guard_pid"] = self.guard_proc.pid
                self.rec["guard_breakaway"] = bool(extra)
                return
            except OSError:
                continue

    def _stop_guard(self) -> None:
        # The guard ends by itself once this process has ended and the record says restored.
        pass


def guard(pid: int, record: Path) -> int:
    """Waits for process `pid` to end; if its record does not show Alex's plan restored, restores
    it and records that the guard did."""
    if sys.platform != "win32":
        return 2
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(ctypes.c_void_p(h), 0xFFFFFFFF)
        k32.CloseHandle(ctypes.c_void_p(h))
    try:
        rec = json.loads(record.read_text())
    except (OSError, json.JSONDecodeError):
        rec = {}
    if rec.get("restored") is True:
        return 0
    try:
        if active()["guid"] != ALEX_PLAN:
            powercfg("/setactive", ALEX_PLAN)
        rec["restored_by_guard_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        rec["after"] = readback(ALEX_PLAN)
        rec["restored"] = rec["after"]["active"]["guid"] == ALEX_PLAN
    except Exception as e:  # noqa: BLE001
        rec["guard_error"] = repr(e)
    tmp = record.with_suffix(".guard.tmp")
    tmp.write_text(json.dumps(rec, indent=1))
    os.replace(tmp, record)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="create the lab plan once (section 2)")
    c.add_argument("--record", type=Path)
    cc = sub.add_parser("create-cap", help="create the frequency test's control plan once (section 4, revision of 2026-10-03)")
    cc.add_argument("--record", type=Path)
    sub.add_parser("status", help="the plans, the active one, and the lab plan's and Alex's processor settings")
    sub.add_parser("restore", help="make Alex's plan active and read it back")
    r = sub.add_parser("run", help="run a command under the lab plan, then restore Alex's plan")
    r.add_argument("--record", type=Path, required=True)
    r.add_argument("command", nargs=argparse.REMAINDER)
    g = sub.add_parser("guard")
    g.add_argument("--pid", type=int, required=True)
    g.add_argument("--record", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "create":
            print(json.dumps(create(a.record), indent=1))
        elif a.cmd == "create-cap":
            print(json.dumps(create_cap(a.record), indent=1))
        elif a.cmd == "status":
            lab = lab_plan_guid()
            print(json.dumps({"plans": plans(), "active": active(), "lab_plan": lab,
                              "lab": {k: v for k, v in processor_settings(lab).items() if k in SETTING_NAMES} if lab else None,
                              "alex": {k: v for k, v in processor_settings(ALEX_PLAN).items() if k in SETTING_NAMES}}, indent=1))
        elif a.cmd == "restore":
            powercfg("/setactive", ALEX_PLAN)
            print(json.dumps(readback(ALEX_PLAN)["active"]))
        elif a.cmd == "run":
            cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
            with LabPlan(a.record):
                return subprocess.run(cmd).returncode
        elif a.cmd == "guard":
            return guard(a.pid, a.record)
    except AdminNeeded as e:
        print(f"wpower: needs administrator rights, stopped (nothing elevated): {e}", file=sys.stderr)
        return 96
    except PowerError as e:
        print(f"wpower: {e}", file=sys.stderr)
        return 95
    return 0


if __name__ == "__main__":
    sys.exit(main())
