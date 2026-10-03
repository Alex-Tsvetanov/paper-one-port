# W procedure (draft for Alex's approval)

Status: DRAFT, written in M6a on 2026-10-03. Nothing in it has been applied. Every command that
changes a setting is Alex's to run; M6a ran only the read-only queries quoted in section 1.
Frozen basis: hypotheses.md sections 4.1 (placement on W), 7 (validity on W: "the rules of W's
procedure that can be computed there"; the power plan and the timer resolution recorded per
window) and 9.1 ("W's procedure | power plan, boost policy, timer resolution, and a CPU frequency
counter tested against a known load; approved by Alex. If no counter passes, W windows are
validated without the frequency rule and the paper says so"); design/proposal.md LB3 and RK2.

## 1. W as read on 2026-10-03 (read-only)

| Item | As read | How |
|---|---|---|
| OS | Windows 11 Pro N, 10.0.26200 | `Get-CimInstance Win32_OperatingSystem` |
| CPU | AMD Ryzen 5 3600 6-Core Processor; 6 cores, 12 logical processors; MaxClockSpeed 3950 | `Get-CimInstance Win32_Processor` |
| Cores | core k holds logical processors 2k and 2k+1 (k = 0 to 5); one group; one efficiency class (0) | `GetLogicalProcessorInformationEx(RelationProcessorCore)` |
| Power source | no battery reported (a desktop on mains) | `root/wmi BatteryStatus` |
| Active plan | "ChrisTitus - Ultimate Power Plan", 00acab9f-6807-4927-af55-c72a4c589dad | `powercfg /GETACTIVESCHEME` |
| Its processor settings, AC | minimum and maximum processor state 100%; performance boost mode 2 (Aggressive); core parking min cores 100%; processor idle disable 0 (idle states on); energy performance preference 0 | `powercfg /QH SCHEME_CURRENT SUB_PROCESSOR` |
| Other plans present | Balanced; Razer Cortex Power Plan; High performance (8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c); AMD Ryzen Balanced; AMD Ryzen High Performance; Power saver; Ultimate Performance | `powercfg /L` |
| Timer resolution | coarsest 15.625 ms, finest 0.5 ms, current 1.0 ms (the current value is the global one some process asked for) | `NtQueryTimerResolution` |
| Frequency counters | `\Processor Information(*)\% Processor Performance`, `Actual Frequency`, `Processor Frequency`, `% of Maximum Frequency`, `% Performance Limit`, `Performance Limit Flags` exist; one idle sample of `_Total`: % Processor Performance 99.96, Processor Frequency 3950 | `Get-Counter` |
| TCP ports | dynamic range 1025 to 65535 (64510 ports), not Windows' default; excluded ranges 5357, 31064 to 31363, 50000 to 50059 (administered), 60905 to 61204 | `netsh int ipv4 show dynamicport tcp`, `... excludedportrange protocol=tcp` |
| TIME-WAIT | `TcpTimedWaitDelay` = 0x1e (30 s) | `reg query HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters` |
| Quiet, after M6a's builds | CPU idle 95 to 98% per 1 s sample, mean 97.5% over 10 s; top process the WMI provider of the query itself (5%) | P1's quiet check (section 5) |
| Processes that may disturb a window, running | TextInputHost, SearchHost, SearchIndexer, MsMpEng (Defender), remoting_host (a remote desktop host), razer_elevation_service and razerwdl, wslservice | `Get-Process`, `Win32_PerfFormattedData_PerfProc_Process` |

Windows' own help text for the frequency counters (read on W): `% Processor Performance` is the
average performance while executing, as a percentage of nominal, and "may exceed 100%";
`Processor Frequency` and `% of Maximum Frequency` "will not accurately reflect" processors that
regulate their frequency outside Windows' control, and the text points to `% Processor
Performance` or `Actual Frequency` instead.

## 2. Power plan and frequency pinning

Aim: as on L (lab/bin/pin.sh: boost off, a fixed performance state, mains power), so that a W
window runs at one frequency.

Proposed, in a plan of its own so that the window's settings are explicit and the current plan
stays as it is:

```
powercfg /duplicatescheme 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
    (prints the new plan's GUID: <G>; recorded in the lab journal)
powercfg /changename <G> "oneport W windows"
powercfg /setacvalueindex <G> SUB_PROCESSOR be337238-0d82-4146-a960-4f3749d470c7 0   (performance boost mode: 0 Disabled)
powercfg /setacvalueindex <G> SUB_PROCESSOR PROCTHROTTLEMIN 100  (minimum processor state 100%)
powercfg /setacvalueindex <G> SUB_PROCESSOR PROCTHROTTLEMAX 100  (maximum processor state 100%)
powercfg /setacvalueindex <G> SUB_PROCESSOR 0cc5b647-c1df-4637-891a-dec35c318583 100 (core parking min cores 100%: no parking)
powercfg /setactive <G>
powercfg /getactivescheme
powercfg /QH SCHEME_CURRENT SUB_PROCESSOR                        (read back; recorded)
```

After the windows: `powercfg /setactive 00acab9f-6807-4927-af55-c72a4c589dad` restores the plan
read in section 1.

The aliases were checked on W (read-only): `powercfg /ALIASES` lists `SUB_PROCESSOR`,
`PROCTHROTTLEMIN` and `PROCTHROTTLEMAX`; boost mode and core parking are hidden settings, whose
aliases `PERFBOOSTMODE` and `CPMINCORES` only `powercfg /ALIASESH` lists, so the commands above name
them by GUID. Their values are read back with `powercfg /QH`, which shows hidden settings.

- Idle states stay on (processor idle disable 0), as on L, where pin.sh sets the governor and
  boost, not idle states. Open for Alex.
- Administrator rights: the powercfg documentation
  (https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options,
  read 2026-10-03) says "requires administrator privileges" only for its report commands
  (`/systemsleepdiagnostics`, `/systempowerreport`), and says nothing of the kind for
  `/duplicatescheme`, `/changename`, `/setacvalueindex` or `/setactive`. Who may change a given
  plan is set by the plan's security descriptor (`powercfg /getsecuritydescriptor <G>`, read-only).
  None of these commands was run in M6a. If one answers "access denied", it needs an elevated
  prompt. They change system settings, so Alex runs them in any case.
- Recorded per window (section 7 of hypotheses.md): `powercfg /getactivescheme` and the AC values
  above, read before and after the window.

## 3. Timer resolution

- The server waits in `GetQueuedCompletionStatusEx` with its bound in whole milliseconds (proposal
  I13). Since Windows 10 version 2004, `timeBeginPeriod` no longer sets a global resolution: a
  process that does not call it is not guaranteed better than the default (15.625 ms on W), and
  on Windows 11 a window-owning process that is occluded or minimized loses its request
  (https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod, read
  2026-10-03). M6a's test client met this: its 5 ms gaps lasted a default tick until it used a
  high-resolution waitable timer (design/status-m6.md).
- The binary calls neither `timeBeginPeriod` nor `timeEndPeriod`. Its timer events are handled in
  the first pass whose wait returned at or after the deadline (B2), which at the default
  resolution can be up to one tick late. Lateness is reported per backend and not tested (B2),
  and G_W comes from the timer part's lateness (section 9.2), so the default changes no rule.
- Decision for Alex, before the code freeze: (a) keep the default resolution (no change); or
  (b) the server requests 1 ms (`timeBeginPeriod(1)` at start, `timeEndPeriod(1)` at exit; a code
  change before the freeze, applied to both arms alike; the documentation warns that a higher
  resolution can reduce overall performance and power saving). The draft assumes (a).
- Recorded per window: the current resolution from `NtQueryTimerResolution` (read-only) before and
  after, and which option the binary uses.

## 4. Frequency check

Counter: `\Processor Information(0,<cpu>)\% Processor Performance` of the server's logical CPU,
with `Actual Frequency` recorded beside it (section 1: the help text names these two as the
accurate ones on such processors).

Test against a known load, once, with the plan of section 2 active (an engineering test, not a
window; to run after Alex approves this draft):
1. Idle: sample both counters of CPU 10 at 1 s for 10 s.
2. Load: a spin loop pinned to CPU 10 (`start /affinity 400 <spin program>`) for 10 s; the same
   samples.
3. Control: the same load under the plan of section 1 (boost mode Aggressive).
Pass, a design choice: with boost off, every load sample lies within 2% of the load samples' mean
(L's frequency rule is a 2% drift, hypotheses.md section 7); and with boost on, the counter's load
mean differs from the boost-off load mean by more than 2%, so the counter shows a change of
frequency at all. If it does not pass, W windows are validated without the frequency rule and
the paper says so (section 9.1).

### Revision of 2026-10-03 (Alex's addition, approved; written before the retest ran)

The first test (status-m6b.md, "The frequency check") did not pass: under Alex's plan, with boost
Aggressive, neither the counter nor the spinner's work moved, so boost mode did not move W's clock
in that test. The retest uses a control that surely moves the clock. Steps 1 and 2 stay as above.
Step 3 becomes:

3. Control: the same load under a second test plan, "oneport W cap50": the lab plan of section 2
   duplicated, with the maximum processor state capped at 50% and the minimum processor state at
   the cap (50%), created once (`wpower.py create-cap`) and switched to inside the lab plan's
   session, so the session's end and its guard set Alex's plan back, also on failure. No command
   is elevated.

Recorded in every phase: both counters (`% Processor Performance` and `Actual Frequency` of CPU 10)
and, in each load phase, the spinner's work rate (its iterations per second).

Pass: under the lab plan every load sample of the counter lies within 2% of the load mean, and under
the capped plan the counter's load mean differs from the lab plan's load mean by more than 2%.

Read beside the rule, not part of it: if the work rate falls by more than 2% under the cap and the
counter does not move, the counter is blind; if neither moves, the cap did not move the clock and
the test is inconclusive. Both mean the fallback of section 9.1 stands.

The quiet check of section 5 runs first and is recorded. The retest runs once, right before the W
A/A job and never during it, and changes nothing in that job: its runner's frequency rule stays off
and the counter is recorded in every row. Whether the rule applies to the confirmatory windows is
decided in the revision log before the code freeze.

Before and after each window: a sampler on core 0 reads the counter of the server's CPU and of
each generator CPU at 1 s through the window (WMI `Win32_PerfFormattedData_Counters_ProcessorInformation`,
whose names are not localized). Invalid, by analogy with L's rule: the server CPU's mean over the
window differs from the session's mean by more than 2%.

## 5. Quiet check

Before each session (each lab job of W):
- P1's check (papers/wake-defect/bench/run_publication.ps1): mean CPU idle at least 95% over 10 s
  (`Win32_PerfFormattedData_PerfOS_Processor`, `_Total`), the top 5 processes by CPU recorded.
  On 2026-10-03, after M6a's builds: mean 97.5%.
- Added, design choices: the idle of each logical CPU that the window uses (2 to 10) is at least
  95% over the same 10 s; and no single process is above 5% of one logical CPU over it. The
  second rule names the process: the brief for M6a records that in P2 a stuck TextInputHost
  failed the quiet gate.
- Processes to look for (running on 2026-10-03): TextInputHost, SearchHost, SearchIndexer,
  MsMpEng (Defender's real-time scan, which also scans new binaries and logs), remoting_host (an
  active remote session redraws the screen), Razer services, wslservice (and vmmem while a WSL
  distribution or Docker runs), browsers, editors, OneDrive.
- Windows Update: `Get-Service wuauserv` (read-only); a window does not start while an update
  installs. Pausing updates is a setting for Alex.
- A busy W in the middle of a session shows in the per-window CPU sampler of section 4 (another
  process's CPU time on the window's CPUs), recorded per window.

## 6. Core placement

Frozen (hypotheses.md 4.1; proposal LB3): "the server on one logical CPU of the last physical
core, its sibling idle, opgen on the cores between core 0 and the server's".
- Server: logical CPU 10 (core 5); CPU 11, its sibling, idle. Affinity mask 0x400.
- opgen (M6b): cores 1 to 4, logical CPUs 2 to 9. Affinity mask 0x3FC.
- Core 0 (logical CPUs 0 and 1): the system, the driver and the samplers, as on L.
- The harness reads the core layout at each run (`GetLogicalProcessorInformationEx`) and stops if
  it differs from section 1.
- One worker on IOCP (M6a serves one; design/status-m6.md), so the process's affinity places it.
- Stopping the server: `Local\oneport-stop-<pid>` (bench/server/main.cpp), set by the harness.

## 7. What a W window needs from Alex

1. Approve this draft, or change it; then the frequency test of section 4.
2. Free W: no interactive work; close browsers, editors, Razer software and remote sessions; no
   WSL or Docker running.
3. Run section 2's commands (and the restore after the windows).
4. Decide section 3 (timer resolution) and any Defender or Windows Update setting for the
   windows (settings only Alex changes).
5. Confirm W stays on mains power with its display on or off as he prefers (recorded).
