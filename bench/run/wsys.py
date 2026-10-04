#!/usr/bin/env python3
"""W's readings for the W window runner (design/w-procedure.md; design/status-m6b.md), through
Windows' documented APIs by ctypes; Python's standard library only. Nothing here changes a
setting of W: every call reads, except the affinity of a process this runner started and the stop
event of a server it started.

- Core layout (section 6): GetLogicalProcessorInformationEx(RelationProcessorCore).
- Timer resolution (section 3): NtQueryTimerResolution, read only.
- Performance counters (sections 4 and 5): PDH with English counter paths
  (PdhAddEnglishCounterW), so the paths do not depend on W's display language. A rate counter's
  formatted value is its mean over the interval between two collections, so one query collected
  at the window's two markers gives the window's mean busy share and performance of each CPU.
- Processes: CPU time (GetProcessTimes) and working set (K32GetProcessMemoryInfo) of a process
  the runner started; its affinity, set while it is suspended (CREATE_SUSPENDED,
  SetProcessAffinityMask, ResumeThread), so it never runs outside its CPUs.
- TCP: GetTcpStatisticsEx's counters and the TIME-WAIT entries of GetExtendedTcpTable.
- Defender and Windows Update: one read-only PowerShell call (Get-MpComputerStatus, the Windows
  Update Agent's IUpdateInstaller.IsBusy and ISystemInformation.RebootRequired, service states).

The pure helpers (parsers, rules) run on every platform; the readings only on Windows.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

# Section 1 of design/w-procedure.md (read on W on 2026-10-03): six cores, core k holding logical
# processors 2k and 2k + 1, one group, one efficiency class.
EXPECTED_CORES = [(2 * k, 2 * k + 1) for k in range(6)]
# Section 6: the server on logical CPU 10 (core 5), its sibling 11 idle; opgen on cores 1 to 4
# (logical CPUs 2 to 9); core 0 (logical CPUs 0 and 1) for the system, the driver and the samplers.
SERVER_CPUS = (10,)
SERVER_SIBLINGS = (11,)
GEN_CPUS = tuple(range(2, 10))
HOUSEKEEPING = (0, 1)


def mask(cpus) -> int:
    m = 0
    for c in cpus:
        m |= 1 << c
    return m


def check_core_layout(cores: list[dict]) -> list[str]:
    """Problems of a core layout (core_layout()'s list) against section 1's; empty when it holds."""
    problems = []
    if len(cores) != len(EXPECTED_CORES):
        problems.append(f"{len(cores)} cores, expected {len(EXPECTED_CORES)}")
    got = sorted(tuple(c["cpus"]) for c in cores)
    if got != sorted(EXPECTED_CORES):
        problems.append(f"logical processors per core {got}, expected {EXPECTED_CORES}")
    groups = {c["group"] for c in cores}
    if groups != {0}:
        problems.append(f"processor groups {sorted(groups)}, expected only group 0")
    classes = {c["efficiency_class"] for c in cores}
    if len(classes) != 1:
        problems.append(f"efficiency classes {sorted(classes)}, expected one")
    return problems


# ---------------------------------------------------------------- the quiet check (section 5)

QUIET_TOTAL_IDLE_MIN = 95.0  # P1's rule: mean CPU idle at least 95% over 10 s
QUIET_CPU_IDLE_MIN = 95.0    # design choice (section 5): each logical CPU the window uses
QUIET_PROCESS_MAX = 5.0      # design choice (section 5): no process above 5% of one logical CPU
QUIET_CPUS = tuple(range(2, 11))  # the CPUs a window uses: the generator's 2 to 9 and the server's 10
QUIET_SECONDS = 10


def quiet_verdict(total_idle_samples: list[float], cpu_idle: dict[int, float], processes: list[dict], cpus=QUIET_CPUS,
                  exclude_pids=()) -> dict:
    """Section 5's rules over one 10 s reading: the mean of the per-second total idle samples is at
    least 95% (P1's check); the idle of each CPU in `cpus` over the interval is at least 95%; no
    process (other than `exclude_pids`, the check's own) is above 5% of one logical CPU over it.
    `processes` holds {name, pid, cpu_percent} with cpu_percent in units of one logical CPU."""
    reasons = []
    mean_idle = sum(total_idle_samples) / len(total_idle_samples) if total_idle_samples else 0.0
    if mean_idle < QUIET_TOTAL_IDLE_MIN:
        reasons.append(f"mean CPU idle {mean_idle:.1f}% < {QUIET_TOTAL_IDLE_MIN:.0f}% over the check")
    for c in cpus:
        v = cpu_idle.get(c)
        if v is None:
            reasons.append(f"CPU {c}: no idle reading")
        elif v < QUIET_CPU_IDLE_MIN:
            reasons.append(f"CPU {c} idle {v:.1f}% < {QUIET_CPU_IDLE_MIN:.0f}%")
    others = [p for p in processes if p.get("pid") not in exclude_pids]
    busy = [p for p in others if p["cpu_percent"] > QUIET_PROCESS_MAX]
    for p in busy:
        reasons.append(f"process {p['name']} (pid {p.get('pid')}) at {p['cpu_percent']:.1f}% of one CPU > {QUIET_PROCESS_MAX:.0f}%")
    top = sorted(others, key=lambda p: p["cpu_percent"], reverse=True)[:5]
    return {"idle_percent_samples": total_idle_samples, "idle_percent_mean": mean_idle, "cpu_idle_percent": cpu_idle,
            "top_processes": top, "quiet": not reasons, "reasons": reasons,
            "rules": {"total_idle_min": QUIET_TOTAL_IDLE_MIN, "cpu_idle_min": QUIET_CPU_IDLE_MIN, "cpus": list(cpus),
                      "process_max_percent_of_one_cpu": QUIET_PROCESS_MAX}}


# ---------------------------------------------------------------- Defender and Windows Update

STATE_PS = r"""
$ErrorActionPreference = 'Stop'
$o = [ordered]@{ read_at = (Get-Date -Format o) }
try {
  $s = Get-MpComputerStatus
  $o.defender = [ordered]@{ real_time_protection = $s.RealTimeProtectionEnabled; antivirus = $s.AntivirusEnabled;
    am_service = $s.AMServiceEnabled; behavior_monitor = $s.BehaviorMonitorEnabled; on_access = $s.OnAccessProtectionEnabled;
    ioav = $s.IoavProtectionEnabled; tamper_protected = $s.IsTamperProtected; am_running_mode = "$($s.AMRunningMode)" }
} catch { $o.defender = [ordered]@{ error = $_.Exception.Message } }
try { $o.defender_exclusion_path = @((Get-MpPreference).ExclusionPath) } catch { $o.defender_exclusion_path = @("error: " + $_.Exception.Message) }
try { $o.update_installer_busy = (New-Object -ComObject Microsoft.Update.Installer).IsBusy } catch { $o.update_installer_busy = $null; $o.update_installer_error = $_.Exception.Message }
try { $o.update_reboot_required = (New-Object -ComObject Microsoft.Update.SystemInfo).RebootRequired } catch { $o.update_reboot_required = $null }
$o.services = @(Get-Service -Name wuauserv, UsoSvc, TrustedInstaller -ErrorAction SilentlyContinue | ForEach-Object { [ordered]@{ name = $_.Name; status = "$($_.Status)" } })
$o.update_processes = @(Get-Process -Name TiWorker, TrustedInstaller, MoUsoCoreWorker, wuauclt, usoclient -ErrorAction SilentlyContinue | ForEach-Object { [ordered]@{ name = $_.ProcessName; id = $_.Id; cpu_s = $_.CPU } })
$o | ConvertTo-Json -Depth 4 -Compress
"""


def defender_and_update() -> dict:
    """Defender's real-time state and whether Windows Update is installing, read only (Alex's
    decision 3 of 2026-10-03: never changed by the harness)."""
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", STATE_PS], capture_output=True, text=True, timeout=120)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": (p.stderr or p.stdout).strip()[-400:]}
    return out


def update_installing(state: dict) -> bool | None:
    """Whether an update is installing: the Windows Update Agent's installer reports itself busy.
    None when that could not be read."""
    v = state.get("update_installer_busy")
    return None if v is None else bool(v)


# ---------------------------------------------------------------- Windows only

if IS_WINDOWS:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    pdh = ctypes.WinDLL("pdh")
    psapi_ok = hasattr(kernel32, "K32GetProcessMemoryInfo")
    iphlpapi = ctypes.WinDLL("iphlpapi")

    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL

    kernel32.OpenProcess.restype = HANDLE
    kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
    kernel32.CloseHandle.argtypes = [HANDLE]
    kernel32.GetProcessTimes.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.SetProcessAffinityMask.argtypes = [HANDLE, ctypes.c_size_t]
    kernel32.GetProcessAffinityMask.argtypes = [HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    kernel32.GetCurrentProcess.restype = HANDLE
    kernel32.OpenThread.restype = HANDLE
    kernel32.OpenThread.argtypes = [DWORD, BOOL, DWORD]
    kernel32.ResumeThread.argtypes = [HANDLE]
    kernel32.ResumeThread.restype = DWORD
    kernel32.CreateToolhelp32Snapshot.restype = HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [DWORD, DWORD]
    kernel32.OpenEventW.restype = HANDLE
    kernel32.OpenEventW.argtypes = [DWORD, BOOL, wintypes.LPCWSTR]
    kernel32.SetEvent.argtypes = [HANDLE]
    kernel32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
    kernel32.WaitForSingleObject.restype = DWORD
    kernel32.GetLogicalProcessorInformationEx.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(DWORD)]
    if psapi_ok:
        kernel32.K32GetProcessMemoryInfo.argtypes = [HANDLE, ctypes.c_void_p, DWORD]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_SET_INFORMATION = 0x0200
    PROCESS_VM_READ = 0x0010
    SYNCHRONIZE = 0x00100000
    THREAD_SUSPEND_RESUME = 0x0002
    EVENT_MODIFY_STATE = 0x0002
    TH32CS_SNAPTHREAD = 0x00000004
    CREATE_SUSPENDED = 0x00000004
    CREATE_NO_WINDOW = 0x08000000
    INVALID_HANDLE = HANDLE(-1).value

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", DWORD), ("cntUsage", DWORD), ("th32ThreadID", DWORD), ("th32OwnerProcessID", DWORD),
                    ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long), ("dwFlags", DWORD)]

    kernel32.Thread32First.argtypes = [HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32Next.argtypes = [HANDLE, ctypes.POINTER(THREADENTRY32)]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", DWORD), ("PageFaultCount", DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    def _err(what: str) -> OSError:
        e = ctypes.get_last_error()
        return OSError(e, f"{what}: {ctypes.FormatError(e).strip()}")

    # ---- core layout and timer resolution

    def core_layout() -> list[dict]:
        """Each physical core: its logical processors, group and efficiency class."""
        size = DWORD(0)
        kernel32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not kernel32.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
            raise _err("GetLogicalProcessorInformationEx")
        raw = buf.raw
        cores, off = [], 0
        while off < size.value:
            rel = int.from_bytes(raw[off:off + 4], "little")
            n = int.from_bytes(raw[off + 4:off + 8], "little")
            if rel == 0:  # RelationProcessorCore: PROCESSOR_RELATIONSHIP at offset 8
                eff = raw[off + 9]
                group_count = int.from_bytes(raw[off + 30:off + 32], "little")
                cpus, groups = [], []
                for g in range(group_count):
                    base = off + 32 + 16 * g  # GROUP_AFFINITY: KAFFINITY Mask, WORD Group, WORD Reserved[3]
                    m = int.from_bytes(raw[base:base + 8], "little")
                    grp = int.from_bytes(raw[base + 8:base + 10], "little")
                    groups.append(grp)
                    cpus += [i for i in range(64) if m >> i & 1]
                cores.append({"cpus": cpus, "group": groups[0] if len(groups) == 1 else groups, "efficiency_class": eff,
                              "smt": bool(raw[off + 8] & 1)})
            off += n
        return cores

    def timer_resolution() -> dict:
        """NtQueryTimerResolution, in ms: the coarsest, the finest, and the current resolution
        (the finest any process has asked for), read only."""
        mx, mn, cur = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
        st = ntdll.NtQueryTimerResolution(ctypes.byref(mx), ctypes.byref(mn), ctypes.byref(cur))
        if st != 0:
            return {"error": f"NTSTATUS {st & 0xFFFFFFFF:#x}"}
        return {"coarsest_ms": mx.value / 1e4, "finest_ms": mn.value / 1e4, "current_ms": cur.value / 1e4}

    # ---- processes

    def open_process(pid: int, access: int = PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE) -> int:
        h = kernel32.OpenProcess(access, False, pid)
        if not h:
            raise _err(f"OpenProcess({pid})")
        return h

    def close_handle(h) -> None:
        if h:
            kernel32.CloseHandle(h)

    def process_cpu_s(h) -> float:
        """User plus kernel time of a process, in seconds (WL4's utime + stime)."""
        c, e, k, u = (ctypes.c_ulonglong() for _ in range(4))
        if not kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            raise _err("GetProcessTimes")
        return (k.value + u.value) / 1e7

    def process_memory(h) -> dict:
        """The working set and its peak, in kB (WL4's resident memory and its peak)."""
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        if not psapi_ok or not kernel32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return {}
        return {"working_set_kb": pmc.WorkingSetSize // 1024, "peak_working_set_kb": pmc.PeakWorkingSetSize // 1024}

    def set_affinity(pid_or_handle, cpus, is_handle: bool = False) -> None:
        h = pid_or_handle if is_handle else open_process(pid_or_handle, PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION)
        try:
            if not kernel32.SetProcessAffinityMask(h, mask(cpus)):
                raise _err("SetProcessAffinityMask")
        finally:
            if not is_handle:
                close_handle(h)

    def affinity(pid: int | None = None) -> int:
        h = kernel32.GetCurrentProcess() if pid is None else open_process(pid)
        try:
            pm, sm = ctypes.c_size_t(), ctypes.c_size_t()
            if not kernel32.GetProcessAffinityMask(h, ctypes.byref(pm), ctypes.byref(sm)):
                raise _err("GetProcessAffinityMask")
            return pm.value
        finally:
            if pid is not None:
                close_handle(h)

    def set_own_affinity(cpus) -> None:
        if not kernel32.SetProcessAffinityMask(kernel32.GetCurrentProcess(), mask(cpus)):
            raise _err("SetProcessAffinityMask (self)")

    def resume_process(pid: int) -> int:
        """Resumes every thread of a process started suspended; returns how many."""
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if snap == INVALID_HANDLE:
            raise _err("CreateToolhelp32Snapshot")
        resumed = 0
        try:
            te = THREADENTRY32()
            te.dwSize = ctypes.sizeof(te)
            ok = kernel32.Thread32First(snap, ctypes.byref(te))
            while ok:
                if te.th32OwnerProcessID == pid:
                    th = kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, te.th32ThreadID)
                    if th:
                        if kernel32.ResumeThread(th) != 0xFFFFFFFF:
                            resumed += 1
                        close_handle(th)
                ok = kernel32.Thread32Next(snap, ctypes.byref(te))
        finally:
            close_handle(snap)
        return resumed

    def start_pinned(cmd: list[str], cpus, **popen) -> subprocess.Popen:
        """Starts `cmd` suspended, without a console window, sets its affinity to `cpus` and resumes
        it, so it never runs outside them."""
        flags = popen.pop("creationflags", 0) | CREATE_SUSPENDED | CREATE_NO_WINDOW
        proc = subprocess.Popen(cmd, creationflags=flags, **popen)
        try:
            set_affinity(proc.pid, cpus)
            if resume_process(proc.pid) < 1:
                raise OSError("no thread resumed")
        except Exception:
            proc.kill()
            proc.wait()
            raise
        return proc

    def set_named_event(name: str) -> bool:
        """Sets an existing named event; False if it cannot be opened."""
        h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
        if not h:
            return False
        try:
            return bool(kernel32.SetEvent(h))
        finally:
            close_handle(h)

    def set_stop_event(pid: int) -> bool:
        """Sets the server's stop event Local\\oneport-stop-<pid> (bench/server/main.cpp); False if
        it cannot be opened."""
        return set_named_event(f"Local\\oneport-stop-{pid}")

    def job_stop_name(pid: int) -> str:
        """The event that asks a W job's process to stop (wjob.py), named by its process id."""
        return f"Local\\oneport-wjob-stop-{pid}"

    kernel32.CreateEventW.restype = HANDLE
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, BOOL, BOOL, wintypes.LPCWSTR]

    def watch_stop(on_stop=None) -> threading.Thread:
        """Creates this process's stop event (job_stop_name) and a thread that waits on it; when it
        is set, `on_stop` runs, by default an interrupt of the main thread (KeyboardInterrupt), so
        the finally blocks run and stop what this process started."""
        import _thread
        h = kernel32.CreateEventW(None, True, False, job_stop_name(os.getpid()))
        if not h:
            raise _err("CreateEventW")

        def wait() -> None:
            if kernel32.WaitForSingleObject(h, 0xFFFFFFFF) == 0:
                (on_stop or _thread.interrupt_main)()

        t = threading.Thread(target=wait, daemon=True)
        t.start()
        return t

    # ---- PDH

    PDH_FMT_DOUBLE = 0x00000200
    PDH_FMT_NOCAP100 = 0x00008000
    PDH_MORE_DATA = 0x800007D2

    class PDH_FMT_COUNTERVALUE(ctypes.Structure):
        _fields_ = [("CStatus", DWORD), ("doubleValue", ctypes.c_double)]  # the union, aligned at 8

    class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
        _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", PDH_FMT_COUNTERVALUE)]

    pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(HANDLE)]
    pdh.PdhAddEnglishCounterW.argtypes = [HANDLE, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(HANDLE)]
    pdh.PdhCollectQueryData.argtypes = [HANDLE]
    pdh.PdhGetFormattedCounterValue.argtypes = [HANDLE, DWORD, ctypes.POINTER(DWORD), ctypes.POINTER(PDH_FMT_COUNTERVALUE)]
    pdh.PdhGetFormattedCounterArrayW.argtypes = [HANDLE, DWORD, ctypes.POINTER(DWORD), ctypes.POINTER(DWORD), ctypes.c_void_p]
    pdh.PdhCloseQuery.argtypes = [HANDLE]
    for _f in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData", "PdhGetFormattedCounterValue",
               "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
        getattr(pdh, _f).restype = ctypes.c_ulong

    class Pdh:
        """One PDH query over English counter paths. collect() samples every counter; values()
        gives each counter's formatted value over the interval between the last two collections
        (None where PDH has no valid value); array() a wildcard counter's instances."""

        def __init__(self, paths: list[str]):
            self.q = HANDLE()
            st = pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q))
            if st != 0:
                raise OSError(st, f"PdhOpenQueryW {st:#x}")
            self.counters: dict[str, HANDLE] = {}
            for p in paths:
                h = HANDLE()
                st = pdh.PdhAddEnglishCounterW(self.q, p, 0, ctypes.byref(h))
                if st != 0:
                    pdh.PdhCloseQuery(self.q)
                    raise OSError(st, f"PdhAddEnglishCounterW({p}) {st:#x}")
                self.counters[p] = h
            self.collected_at: list[float] = []

        def collect(self) -> float:
            st = pdh.PdhCollectQueryData(self.q)
            t = time.monotonic()
            if st != 0:
                raise OSError(st, f"PdhCollectQueryData {st:#x}")
            self.collected_at.append(t)
            return t

        def value(self, path: str) -> float | None:
            v = PDH_FMT_COUNTERVALUE()
            st = pdh.PdhGetFormattedCounterValue(self.counters[path], PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, None, ctypes.byref(v))
            if st != 0 or v.CStatus not in (0, 1):
                return None
            return v.doubleValue

        def values(self) -> dict[str, float | None]:
            return {p: self.value(p) for p in self.counters}

        def array(self, path: str) -> dict[str, float]:
            size, count = DWORD(0), DWORD(0)
            st = pdh.PdhGetFormattedCounterArrayW(self.counters[path], PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size),
                                                  ctypes.byref(count), None)
            if st != PDH_MORE_DATA:
                return {}
            buf = ctypes.create_string_buffer(size.value)
            st = pdh.PdhGetFormattedCounterArrayW(self.counters[path], PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size),
                                                  ctypes.byref(count), buf)
            if st != 0:
                return {}
            items = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
            out: dict[str, float] = {}
            for i in range(count.value):
                it = items[i]
                if it.FmtValue.CStatus in (0, 1):
                    out[it.szName] = it.FmtValue.doubleValue
            return out

        def close(self) -> None:
            if self.q:
                pdh.PdhCloseQuery(self.q)
                self.q = HANDLE()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def cpu_path(cpu: int, counter: str) -> str:
        return f"\\Processor Information(0,{cpu})\\{counter}"

    # The counters read per CPU at the window's markers (sections 4 and 7): busy share, the
    # frequency counter of section 4 and the actual frequency beside it, and the interrupt and DPC
    # shares.
    MARKER_COUNTERS = ("% Processor Time", "% Processor Performance", "Actual Frequency", "% Interrupt Time", "% DPC Time",
                       "Interrupts/sec")
    SAMPLER_COUNTERS = ("% Processor Performance", "Actual Frequency", "% Processor Time")

    class MarkerReadings:
        """One query over every CPU's MARKER_COUNTERS, collected at MEASURE_START and MEASURE_END:
        each value is that CPU's mean over the window (a rate counter over its two samples)."""

        def __init__(self, cpus=range(12)):
            self.cpus = list(cpus)
            self.pdh = Pdh([cpu_path(c, k) for c in self.cpus for k in MARKER_COUNTERS])

        def start(self) -> float:
            return self.pdh.collect()

        def end(self) -> dict:
            t = self.pdh.collect()
            vals = self.pdh.values()
            span = t - self.pdh.collected_at[-2] if len(self.pdh.collected_at) >= 2 else None
            out = {"span_s": span, "cpus": {}}
            for c in self.cpus:
                out["cpus"][str(c)] = {k: vals[cpu_path(c, k)] for k in MARKER_COUNTERS}
            self.pdh.close()
            return out

    class Sampler(threading.Thread):
        """Section 4's per-window sampler: every `period_s` it collects SAMPLER_COUNTERS of the given
        CPUs, from a thread of the runner, which runs on CPUs 0 and 1. Each sample is the mean over
        the last period."""

        def __init__(self, cpus, period_s: float = 1.0):
            super().__init__(daemon=True)
            self.cpus = list(cpus)
            self.period = period_s
            self.samples: list[dict] = []
            self.error: str | None = None
            self._stop_ev = threading.Event()

        def run(self) -> None:
            try:
                with Pdh([cpu_path(c, k) for c in self.cpus for k in SAMPLER_COUNTERS]) as q:
                    t0 = q.collect()
                    n = 1
                    while not self._stop_ev.wait(max(0.0, t0 + n * self.period - time.monotonic())):
                        t = q.collect()
                        n += 1
                        vals = q.values()
                        self.samples.append({"t": t, "cpus": {str(c): {k: vals[cpu_path(c, k)] for k in SAMPLER_COUNTERS} for c in self.cpus}})
            except Exception as e:  # noqa: BLE001 - recorded, never swallowed
                self.error = repr(e)

        def stop(self) -> list[dict]:
            self._stop_ev.set()
            self.join(timeout=5)
            return self.samples

    def quiet_check(seconds: int = QUIET_SECONDS, cpus=QUIET_CPUS) -> dict:
        """Section 5: one 10 s reading. Per second, `\\Processor(_Total)\\% Idle Time` (P1's
        Win32_PerfFormattedData_PerfOS_Processor PercentIdleTime); over the whole interval, each
        CPU's `% Idle Time` and each process's `% Processor Time` (in units of one logical CPU)."""
        per_cpu = Pdh([cpu_path(c, "% Idle Time") for c in range(12)] + ["\\Process(*)\\% Processor Time", "\\Process(*)\\ID Process"])
        total = Pdh(["\\Processor(_Total)\\% Idle Time"])
        try:
            per_cpu.collect()
            total.collect()
            samples = []
            t0 = time.monotonic()
            for i in range(1, seconds + 1):
                time.sleep(max(0.0, t0 + i - time.monotonic()))
                total.collect()
                v = total.value("\\Processor(_Total)\\% Idle Time")
                samples.append(v if v is not None else 0.0)
            per_cpu.collect()
            cpu_idle = {c: per_cpu.value(cpu_path(c, "% Idle Time")) for c in range(12)}
            cpu_pct = per_cpu.array("\\Process(*)\\% Processor Time")
            pids = per_cpu.array("\\Process(*)\\ID Process")
        finally:
            per_cpu.close()
            total.close()
        procs = [{"name": n, "pid": int(pids[n]) if n in pids else None, "cpu_percent": v} for n, v in cpu_pct.items()
                 if n not in ("_Total", "Idle")]
        out = quiet_verdict(samples, {c: v for c, v in cpu_idle.items() if v is not None}, procs, cpus, exclude_pids=(os.getpid(),))
        out["date"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        out["seconds"] = seconds
        out["own_pid_excluded"] = os.getpid()
        return out

    # ---- TCP

    class MIB_TCPSTATS(ctypes.Structure):
        _fields_ = [(n, DWORD) for n in ("dwRtoAlgorithm", "dwRtoMin", "dwRtoMax", "dwMaxConn", "dwActiveOpens", "dwPassiveOpens",
                                         "dwAttemptFails", "dwEstabResets", "dwCurrEstab", "dwInSegs", "dwOutSegs", "dwRetransSegs",
                                         "dwInErrs", "dwOutRsts", "dwNumConns")]

    TCP_STAT_KEYS = ("ActiveOpens", "PassiveOpens", "AttemptFails", "EstabResets", "CurrEstab", "RetransSegs", "InErrs", "OutRsts",
                     "NumConns")

    def tcp_stats() -> dict[str, int]:
        """GetTcpStatisticsEx(AF_INET): W has no counter of listen overflows or drops (section 7
        reads nstat on L); a refused or dropped SYN shows as a failed connect."""
        s = MIB_TCPSTATS()
        if iphlpapi.GetTcpStatisticsEx(ctypes.byref(s), 2) != 0:
            return {}
        return {k: getattr(s, "dw" + k) for k in TCP_STAT_KEYS}

    def time_wait_count() -> int:
        """IPv4 TCP entries in TIME-WAIT (GetExtendedTcpTable, TCP_TABLE_BASIC_ALL)."""
        size = DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 2, 0)
        for _ in range(5):
            buf = ctypes.create_string_buffer(size.value + 65536)
            size = DWORD(len(buf))
            rc = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 2, 0)
            if rc == 0:
                raw = buf.raw
                n = int.from_bytes(raw[0:4], "little")
                return sum(1 for i in range(n) if int.from_bytes(raw[4 + 20 * i:8 + 20 * i], "little") == 11)
            if rc != 122:  # ERROR_INSUFFICIENT_BUFFER
                raise OSError(rc, "GetExtendedTcpTable")
        raise OSError(122, "GetExtendedTcpTable: the table kept growing")


def main(argv=None) -> int:
    """`wsys.py layout|timer|quiet|state|spin SECONDS`: prints one reading as JSON (spin: keeps one
    logical CPU busy for SECONDS, the known load of the frequency check)."""
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(main.__doc__)
        return 2
    what = args[0]
    if what == "spin":
        end = time.perf_counter() + float(args[1])
        x = 0
        while time.perf_counter() < end:
            x += 1
        print(json.dumps({"spun_s": float(args[1]), "iterations": x}))
        return 0
    if not IS_WINDOWS:
        print("wsys.py reads W; this is not Windows", file=sys.stderr)
        return 2
    if what == "layout":
        cores = core_layout()
        print(json.dumps({"cores": cores, "problems": check_core_layout(cores)}))
    elif what == "timer":
        print(json.dumps(timer_resolution()))
    elif what == "quiet":
        print(json.dumps(quiet_check()))
    elif what == "state":
        print(json.dumps(defender_and_update()))
    else:
        print(main.__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
