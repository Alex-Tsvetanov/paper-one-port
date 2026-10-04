# P3 engineering status, M6b (the Windows side of the harness)

M6b ran on W on 2026-10-03, on branch `m6b-windows` from a522268, beside M5 on main and on L. Its
brief: opgen on Windows, the W window runner with its fingerprint, lock and pid-based stop, the
frequency check of design/w-procedure.md section 4, and the functional tests; no A/A timing window
on W. Nothing in this file is a result: no window ran on W. The frequency test is an engineering
test, the runner's checks are functional checks (short, off the frozen layout, flagged), and the
sanitizer runs are development checks, not records.

Alex's decisions of 2026-10-03, which bind this milestone: (1) the W harness switches power plans
itself, with no administrator rights, and always sets his plan back; (2) the timer resolution stays
at Windows' default and is recorded per window, read only; (3) Defender and Windows Update are his
to change; the harness reads them and never alters them.

## Commits (m6b-windows)

| Commit | Message (first line, shortened) |
|---|---|
| 52d4c6e | feat: opgen on Windows: a completion port per worker (ConnectEx, a zero-byte WSARecv as readiness, synchronous recv and send), SO_REUSE_UNICASTPORT, the open loop woken by a high-resolution waitable timer; tests on W |
| c215778 | feat: W's power plan and readings (wpower.py, wsys.py) and section 4's frequency test (wfreq.py) |
| 76d05c8 | feat: the W window runner (wwindow.py, waa.py, wjob.py, wlock.py) and run.test_wrunner |

This file is committed after them. Nothing is pushed. M6b's records outside the repository are in
`C:\Users\alext\lab\p3\m6b\` (sha256 at the end).

## The power plan (decision 1; w-procedure section 2)

`bench/run/wpower.py`. Every powercfg command ran from a shell at medium integrity, not elevated
(checked: not in the Administrators role, mandatory label Medium). None answered "access denied",
so nothing needed administrator rights and nothing was elevated. Each command's exit status and
output are checked, and an answer naming access or administrator rights stops the session
(exit 96 in wjob.py) without retrying.

**Created once**, 2026-10-03 16:45:16 +0300 (`wpower.py create`; record `plan-create.json`), with
section 2's commands in its order:

    powercfg /duplicatescheme 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
        -> Power Scheme GUID: 277bfd76-c26d-4cac-b253-a8500e6728d8  (High performance)
    powercfg /changename 277bfd76-c26d-4cac-b253-a8500e6728d8 "oneport W windows"
    powercfg /setacvalueindex 277bfd76-... SUB_PROCESSOR be337238-0d82-4146-a960-4f3749d470c7 0
    powercfg /setacvalueindex 277bfd76-... SUB_PROCESSOR PROCTHROTTLEMIN 100
    powercfg /setacvalueindex 277bfd76-... SUB_PROCESSOR PROCTHROTTLEMAX 100
    powercfg /setacvalueindex 277bfd76-... SUB_PROCESSOR 0cc5b647-c1df-4637-891a-dec35c318583 100

The lab plan is `277bfd76-c26d-4cac-b253-a8500e6728d8`, found by its name at each session (a
second plan of that name is refused). Read back with `powercfg /QH <plan> SUB_PROCESSOR`, parsed by
setting GUID: AC performance boost mode 0, minimum and maximum processor state 100%, core parking
minimum cores 100%, processor idle disable 0 (idle states on, as section 2 leaves them). Section 2
sets AC values only; the DC values stay High performance's (boost 2, minimum state 5%), which do
not apply on mains. Alex's plan, read the same way: AC boost mode 2 (Aggressive), minimum and
maximum state 100%, parking 100%, idle disable 0.

**A session** (`wpower.LabPlan`, used by wjob.py and wfreq.py): reads the active plan; refuses to
start if it is neither Alex's plan nor the lab plan (a plan Alex chose is never overwritten), and
notes it if the lab plan was left active; sets the lab plan, reads back the active plan and the four
values and stops if they differ; at the end sets Alex's plan
`00acab9f-6807-4927-af55-c72a4c589dad` and reads it back. The end runs on normal exit, on an
exception, on Ctrl+C, Ctrl+Break and SIGTERM (SystemExit), and on the console's close, log off and
shut down (SetConsoleCtrlHandler). A guard process, started at the switch, waits on the session's
process and sets Alex's plan if the record does not say it was restored (a killed process). The
record (`<job>.plan.json`) holds the plan before, the lab plan's read-back and when it was set, and
Alex's plan's read-back after and when it was restored.

**Checks of the switch and the restore** (each switch approved by decision 1):

| Check | Lab plan set | Alex's plan restored | How it ended |
|---|---|---|---|
| frequency test (`freq-20261003T164640.plan.json`) | 16:46:52, read back as set | 16:47:17, read back, `restored` true | normally |
| functional job func1 (`func1.plan.json`) | read back as set | `restored` true | normally |
| functional job stop1 | read back as set | `restored` true | `wjob.py stop` during its second window: the command stopped its server by its event (no oneport process left), the job exited 130 |
| job kill2 | 17:23:30 | 17:23:33 by the guard (`restored_by_guard_at`), read back, `restored` true | the job's process ended with TerminateProcess |

A first kill check (kill1) also ended the guard, because the check took every child of the job for
the job's command: the guard had set Alex's plan (the active plan read Alex's), but its record was
not written. kill2 is that check done right. After every check the active plan read
"ChrisTitus - Ultimate Power Plan". When a job's process is killed, its command (waa.py) keeps
running, under Alex's plan, so every later window of it is invalid by the lab-plan rule (below); a
job is stopped with `wjob.py stop`, not by ending its process.

## The frequency check (w-procedure section 4)

`bench/run/wfreq.py`, run once on 2026-10-03 at 16:46 +0300 (record `freq/freq-20261003T164640.json`,
with the plan record beside it). The sampler ran on CPU 0 (its process's affinity 0x1); the load was
`wsys.py spin`, a Python loop started suspended with affinity 0x400 (CPU 10) and resumed; samples of
CPU 10 at 1 s by PDH (`\Processor Information(0,10)\...`, English counter paths), 10 per phase, the
first sample 1.5 s after the spinner started. W was not quiet: the quiet check before the test read
a mean idle of 92.6%, and CPU 10 was 20.5% busy in the idle phase.

| Phase | `% Processor Performance` mean [min, max] | `Actual Frequency` mean | CPU 10 `% Processor Time` mean |
|---|---|---|---|
| idle, lab plan | 99.9958 [99.9712, 100.0214] | 3,949.83 MHz | 20.5 |
| load, lab plan (boost off) | 99.99917 [99.99832, 99.99967] | 3,949.97 MHz | 100.0 |
| load, Alex's plan (boost Aggressive) | 99.99912 [99.99859, 99.99977] | 3,949.97 MHz | 100.0 |

**It does not pass the draft's rule.** With boost off every load sample lies within 0.0009% of the
load mean (the first part holds), but with boost on the load mean differs from the boost-off mean by
-5.2e-7 of it, not by more than 2%, so the counter shows no change of frequency. `Actual Frequency`
judged by the same rule fails the same way.

Beside the rule, not part of it: the spinner's own work rate, a fixed loop counted over 13.5 s, was
144,817,820 iterations under the lab plan (10.73 million per second) and 142,025,518 under Alex's
plan (10.52 million per second). The work did not run faster under Aggressive boost either, so in
this test boost mode changed neither the counter nor the work. Whether the counter would show a
change that W's clock does make is therefore not established; why W's clock did not change with
boost mode was not established either (the firmware's settings were not read).

Consequence, by hypotheses.md section 9.1: "If no counter passes, W windows are validated without
the frequency rule and the paper says so." The runner records the counter in every row (each CPU's
mean over the window at the markers, the session's idle reading, and the 1 s sampler) and does not
apply the rule (`wwindow.FREQ_RULE` off; `ONEPORT_W_FREQ_RULE=on` applies it). Open for Alex: accept
that, or name another check.

## Timer resolution (decision 2)

Neither the server nor opgen calls `timeBeginPeriod`. The runner records `NtQueryTimerResolution`
(read only) at each window's start and end and in each session's fingerprint; on 2026-10-03 it read
coarsest 15.625 ms, finest 0.5 ms, current 1.0 ms throughout.

What the default means for opgen, measured with a scratch program (`timer/hrtimer.cpp`, output in
`timer/hrtimer-output.txt`; not committed; W not quiet; 60 to 300 waits each):
- `GetQueuedCompletionStatusEx` with a 1 ms timeout returned after a median 14.6 ms (p99 15.5 ms): the
  default tick, as M6a found for `WSAPoll`.
- A high-resolution waitable timer (`CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`) waited on directly woke
  a median 0.31 ms (200 us waits) to 0.52 ms (1 ms waits) late, p99 0.67 to 0.81 ms, max 1.15 ms.
- The same timer waited on by a helper thread that posts a packet to a completion port: median 0.31 to
  0.52 ms late, p99 0.65 to 0.97 ms, max 1.28 ms.
- The timer's completion routine (an APC) never reached a thread in an alertable
  `GetQueuedCompletionStatusEx` or `SleepEx` (60 of 60 waits ran to their 50 ms timeout), so that
  route is not used.

## opgen on Windows (52d4c6e)

`bench/gen/worker_win.cpp` (new), with blocks for `_WIN32` in `worker.hpp`, `worker.cpp` and
`opgen.cpp`. One worker thread per generator CPU, each with a completion port of its own:
- A connection's socket is set up as the server's IOCP worker sets an accepted one: overlapped,
  non-blocking, TCP_NODELAY, associated with the worker's port with
  `FILE_SKIP_COMPLETION_PORT_ON_SUCCESS`, so an operation that completes at once queues no packet
  and is handled where it was issued. The SOCKET is held in `Conn::fd` (an int), as the server holds
  it; a handle that does not fit is refused.
- Source addresses: `SO_REUSE_UNICASTPORT` (ws2def.h: "defer ephemeral port allocation for outbound
  connections"), then an explicit bind to the block's next address with port 0; a socket that
  refuses the option is not used (that exchange fails at connect).
- Connect: `ConnectEx`, then `SO_UPDATE_CONNECT_CONTEXT`. A connect not complete at the exchange's
  timeout counts as a failed connect, as on L (cd7c61e).
- Receive: a zero-byte `WSARecv` reports bytes or the end (the IOCP pins of M6a); then synchronous
  `recv` drains the socket as the Linux worker drains it on an edge-triggered event, and an
  exchange's first byte is stamped after the `recv` that returned it. TLS keeps OpenSSL's socket BIO,
  so its first byte is stamped in the BIO's read callback, as on L (0420da0).
- Send: synchronous `send`; what the socket does not take (WSAEWOULDBLOCK, or TLS's want-write) is
  sent again in the next pass. The client's requests are a few hundred bytes.
- Closing a socket cancels its pending operation, whose completion still arrives: each operation has
  its own OVERLAPPED from a free list, tagged with the slot and the connection's generation, and the
  completion of a closed connection only returns its operation. At a worker's end every socket is
  closed and the port drained until no operation is pending (at most 5 s; past that the storage is
  kept, never freed under the kernel, and the worker reports an error).
- Timed waits: the closed loop and keep-alive wait in `GetQueuedCompletionStatusEx` with whole
  milliseconds, which only bounds how late a timeout is seen (up to a tick). The open loop's waits
  end on the high-resolution timer through a helper thread on the worker's CPU, and the last
  `--spin-us` before each due time are spent polling the port, as on L. The main thread's sleeps
  (the warm-up's end, the window's end) use a high-resolution timer too.
- Clocks: `now_ns()` is `std::chrono::steady_clock` (QueryPerformanceCounter, the clock of the
  server's IOCP worker and of opcase on W, proposal I30); each worker's CPU time is `GetThreadTimes`
  (user plus kernel), the process's `GetProcessTimes`; both advance on the clock tick, so over a 5 s
  window they are exact to about 0.3% per thread.
- `run()` and the classification of every record are the Linux code: the Windows readings take the
  POSIX names run() uses (a thread's clock is its handle), so the counting rules are one text.

Read on W while building it, recorded for the pilot's reading of RK2:
- A connect to a loopback port that is bound and not listening is reported refused only after about
  2 s (Python's `connect`: 2.019 s, WinError 10061; opgen: one failed connect per about 2 s per slot).
  Windows sends the SYN again after the reset. In a window this is a failed connect at opgen's 1 s
  timeout.
- `SO_REUSE_UNICASTPORT` is accepted; `getsockopt` reads it back as 0; `getsockname` names a port at
  once after the bind, with or without it; a port bound on one address of 127.0.0.0/8 can be bound on
  another (each address has a port space of its own). Whether the option changes which port is chosen
  was not seen. Whether K_SRC = 16 holds on W is for W's development runs (RK2; any connect failure
  then needs a revision-log entry).

### Design choices of M6b

Every number here is a design choice of M6b, not a frozen value.

| Name | Value | Where | Reason |
|---|---|---|---|
| Completion port | one per opgen worker | `worker_win.cpp` | as the epoll set per worker on L; no completion crosses threads |
| Readiness | zero-byte `WSARecv`, then synchronous `recv` | `worker_win.cpp` | the server's default receive form; no buffer is held by the kernel, so a cancelled receive writes nothing |
| Operations | an OVERLAPPED per operation from a free list, tagged with slot and generation | `worker_win.cpp` `Io` | a closed connection's cancelled operation completes after the slot holds a new connection |
| Drain at a worker's end | at most 5 s | `worker_win.cpp` `kDrainLimitNs` | as the server's IOCP drain |
| Source-address option | `SO_REUSE_UNICASTPORT` before the explicit bind | `worker_win.cpp` `make_socket` | Windows' counterpart of `IP_BIND_ADDRESS_NO_PORT` (reading 3) |
| Open-loop wake | a high-resolution waitable timer, waited on by a helper thread that posts a packet to the port | `worker_win.cpp` | `GetQueuedCompletionStatusEx` ends on the 15.625 ms tick; the timer's APC never reached the port's wait (above) |
| Open-loop spin on W | 1,500 us | `wwindow.OPEN_SPIN_US` | above the timer's measured lateness (median 0.31 to 0.52 ms, max 1.28 ms) |
| Open-loop workers on W | one per physical core, CPUs 2, 4, 6, 8 | `wwindow.OPEN_GEN_THREADS` | M3's choice on L (one per core, the siblings idle) |
| Closed-loop workers on W | one per CPU of 2 to 9 (8) | `wwindow.GEN_CPUS` | the saturation cells need the generator's whole share, as on L |
| TIME-WAIT wait | before a window, until the host holds at most 1,000 TIME-WAIT entries, at most 40 s | `wwindow.TW_START_MAX`, `TW_WAIT_MAX_S` | each window starts from an empty TIME-WAIT table, as each window on L starts from an empty connection-tracking table; `TcpTimedWaitDelay` is 30 s on W |
| Arm ports, K_SRC, timeout | 20000 and 20100; 16; 1,000 ms | `waa.py`, `wwindow.py` | L's (aa.py, window.py); every port of 20000 to 20005 and 20100 to 20105 lies outside W's excluded ranges |
| Source blocks on W | from 127.0.1.0, never reused within 60 s, state in `%USERPROFILE%\lab\p3\src-blocks-w.json` | `window.SourceBlocks` | section 2.4, as on L |
| Session's frequency reading | the server CPU's `% Processor Performance`, 3 samples at 1 s with the host idle at the session's start | `wwindow.session_frequency` | as `pin.sh`'s idle mean MHz on L (reading 4) |
| Quiet check | section 5: mean idle at least 95% over 10 s (P1's), each of CPUs 2 to 10 at least 95%, no process above 5% of one CPU | `wsys.quiet_check` | w-procedure section 5's design choices, as written |

## The W window runner (c215778, 76d05c8)

Python 3.14.5 (the stdlib only; Windows' APIs by ctypes):
- `wsys.py`: W's readings. Core layout (`GetLogicalProcessorInformationEx`), checked against section
  1 (six cores, core k = CPUs 2k and 2k + 1, one group, one efficiency class); timer resolution; PDH
  with English counter paths (each CPU's busy share, `% Processor Performance`, `Actual Frequency`,
  interrupt and DPC shares and interrupts per second, collected at the markers so each is the window's
  mean; a 1 s sampler thread); the server's CPU time and working set; `GetTcpStatisticsEx` and the
  TIME-WAIT entries of `GetExtendedTcpTable`; Defender's state (`Get-MpComputerStatus`) and Windows
  Update's (`IUpdateInstaller.IsBusy`, `RebootRequired`, the states of wuauserv, UsoSvc and
  TrustedInstaller), one read-only PowerShell call; the quiet check; a process started suspended,
  given its CPUs (`SetProcessAffinityMask`) and resumed, so it never runs outside them.
- `wwindow.py`: one window, the W side of `window.py`. Dedicated mode only (`window.guard_mode`). The
  server on CPU 10 (0x400), opgen on CPUs 2 to 9 (0x3FC), the runner and its samplers on CPUs 0 and 1.
  The TIME-WAIT wait; the server started, its listening lines read; the probe (`opgen --probe`); opgen
  with C = 64; at MEASURE_START and MEASURE_END the server's CPU time and the PDH query; the server
  stopped through `Local\oneport-stop-<pid>` after opgen exits (TerminateProcess only for a server
  the runner started whose event cannot be opened or that does not end within 15 s, recorded), its
  counters read from what it prints. One JSON row: the metric (conn/s, req/s or median TTFB), CPU per
  exchange (WL4), counters per connection and per request (WL5), each CPU's readings, interrupts on
  the server's CPU, its sibling and the generator's CPUs, the frequency counter, TIME-WAIT at start and
  end, TCP statistics' change, the timer resolution and the active plan at start and end, both
  processes' affinity, how the server was stopped, and the validity with reasons.
- `waa.py`: A/A sessions on W (X Y Y X, X drawn per session from the seed; arm B 100 ports above arm
  A), aa.py's session ratio and summary, the open-loop rate as aa.py takes it, provenance per job
  (commit, dirty, build, compiler and its version from the CMake cache, libraries, the binaries'
  sha256, the runner scripts' sha256, the inputs hash by the Papers repo's `lab/bin/inputs_hash.py`).
  `--functional`: short windows, flagged, and a summary of validity only, no ratio. A job that did
  not pass the quiet check runs functional checks only.
- Each session's fingerprint (section 7, "on W the power plan and the timer resolution"): the active
  plan and section 2's values read back, the timer resolution, Defender's and Windows Update's state,
  the core-layout check, and the session's frequency reading.
- `wjob.py`: one W lab job, the W side of `lab_job.sh`: pid and start files, W's lab lock, the checks
  before the session (core layout, exit 91; an update installing, exit 92; the lab plan present,
  exit 95; quiet, exit 90 unless `--allow-noisy`, which makes the job a functional check), the lab
  plan around the command, its log, and a done file. `wjob.py stop` sets the job's stop event
  (`Local\oneport-wjob-stop-<pid>`), which the job passes to its command's event; the command raises
  KeyboardInterrupt in its main thread, and its finally blocks stop the server it started by its
  event. A command still running 120 s later is ended (a process the job started).
- `wlock.py`: W's lab lock, the counterpart of `lablock`: a byte-range lock on
  `%USERPROFILE%\lab\.lab.lock`, waited for at most 4 h, released when the holder ends however it ends.

Validity rules on W (`wwindow.finish`; reading 1): the server's exit, opgen's failure, no exchange
completed, the error share above 0.1%, any connect failed (the probe's included), the generator rule
in closed loop (the larger of opgen's own CPU share and the busy share of CPUs 2 to 9 above 90%), the
open loop below 99% completed, and W's procedure: the lab plan active at the window's start and end.
The frequency rule only where `FREQ_RULE` is on. Recorded, deciding nothing: TCP statistics' change
(no listen-overflow counter exists; reading 2), TIME-WAIT, the timer resolution, interrupts.

### Functional checks (not windows)

Short windows (0.2 s warm-up, 0.5 s window), one session per cell, under wjob.py with
`--allow-noisy` (W was not quiet, so the jobs were functional checks by the job's own rule), the lab
plan set and restored, the Release build of the work tree. Not journaled: they are not windows, and
no ratio was computed.
- func1 (76d05c8's runner before two fixes below): churn HTTP/1.1, keep-alive TLS, open-loop MQTT
  at a fixed 2,000 per second: 12 functional windows, all valid by the rules above; every row shows
  the server's affinity 0x400 and opgen's 0x3FC, the lab plan at both ends, the server stopped by its
  event, the timer resolution 1.0 ms. A window after a churn or open-loop window waited 25.2 to 30.2 s
  for the TIME-WAIT table (2,026 to 3,944 entries at the earlier window's end).
- func2 (76d05c8's runner; churn h2c, TLS, MQTT, keep-alive HTTP/1.1, h2c, MQTT, open loop
  HTTP/1.1 and TLS at fixed rates): stopped by `wjob.py stop` at 17:30 on the coordinator's pause
  (Alex needed W), after the 4 windows of churn h2c. The stop worked as stop1's did: exit 130,
  `plan_restored` true, no oneport or opgen process left. Two of its 4 functional windows were
  invalid by the generator rule (90.2% and 93.0%) on the busy host; this shows the rule firing, and
  says nothing about W's capacity, which a functional check does not measure.

Two fixes came from func1, before 76d05c8: the row recorded the TIME-WAIT count after the wait under
the name of the count before it; and the frequency sampler now starts after the server.

An engineering check of the open loop (`timer/spin_check.py`, output in `timer/hrtimer-output.txt`;
W not quiet; HTTP/1.1 at 2,000 per second on the four open-loop workers, 0.5 s warm-up, 3 s, twice
each): the generator's issue lag had a median of 0.8 to 0.9 us in all four runs; its p99 was 2.5 and
5.9 ms with the timer path (spin 1,500 us) and 1.3 and 1.5 ms polling throughout (spin 50,000 us);
its maximum 11 to 20 ms in both. A maximum near the 15.6 ms scheduling tick in both suggests the
generator's threads were preempted on a busy host; it was not isolated. WL2's metric is a median, but
the tail is recorded per row (`issue_lag_ns`) and is to be read again on a quiet W in the A/A job.

## Tests

On W, the suite grows from 139 entries at a522268 (the untouched work tree, Debug: 139 passed) to
156:
- `gen.churn.{http1,h2c,tls,mqtt,ssh,tls-stub}.IOCP`, `gen.keepalive.{http1,h2c,tls,mqtt}.IOCP`,
  `gen.open_loop.IOCP`, `gen.probe.IOCP`: Linux's tests of every load and protocol, the same code,
  against the in-process server on IOCP.
- `gen.source_block` (Windows): every source address of a 3-address block reaches a Winsock
  recording listener. `gen.failures` (Windows): a refused port counts connect failures only (2.6 s
  window, 4 s timeout, since W reports the refusal after about 2 s); a server that never answers
  counts timeouts. `gen.pin_reuse_unicastport`: the option is accepted, two addresses of the block
  hold the same port, and both connections arrive from their bound addresses (tested before use).
  `gen.binaries` (Windows): the oneport and opgen programs (the probe, a short window, the server
  stopped by its event and its counters); opcase's and ophold's programs are Linux only.
- `run.test_wrunner` (every platform; 18 checks): powercfg's output as W prints it (samples
  recorded on W: `bench/run/samples/W-powercfg-*.txt`), section 2's commands and values, the
  denied-access answer, the core-layout and quiet rules at their bounds, the update state, the
  frequency test's rule (W's own case fails it), a window's metric, CPU, interrupts and counters,
  every validity rule and the frequency rule on and off, the cells and the functional summary, the
  dedicated-mode guard, the placement, a process's output read by a thread; on Windows also the
  readings, a pinned start and the lab lock between two holders.

### The suite on W at 76d05c8 (development checks, not records)

From an exported copy (`git archive`) in `C:\Users\alext\lab\p3\m6b\check\`, MSVC (Build Tools 18),
Ninja, `ctest -V -j 4`, ASan with M6a's `ASAN_OPTIONS`
(`detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1`) in the vcvars64
environment. "Report lines" counts the lines of the ctest log that match the shared report pattern
(`bench/oneport_record.py`).

| Build | CMake | Libraries | Build | CTest | Report lines |
|---|---|---|---|---|---|
| Debug | `-DCMAKE_BUILD_TYPE=Debug` | release | 0 warnings | 156 passed, 0 failed | 0 |
| ASan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address` | asan | 0 warnings | 156 passed, 0 failed | 0 |

Instrumentation, as checked: `opgen.exe` and the test binary import
`clang_rt.asan_dynamic-x86_64.dll`; `worker_win.cpp.obj`, `worker.cpp.obj` and `opgen.cpp.obj`
reference `__asan_` in 148, 122 and 100 symbol lines. So the ASan suite runs opgen's Windows engine
(every `gen.*` test) instrumented.

### Linux: not compiled in M6b

M6b did not build on L (M5 works there). As in M6a, every edit to a file Linux compiles is a block
for `_WIN32`, or the `#else` of one holding the Linux text unchanged. A script
(`C:\Users\alext\lab\p3\m6b\linux_view.py`, not committed) evaluates only the conditionals that name
`__linux__` or `_WIN32`, as Linux does, drops comments and blank lines, and compares each changed
file with a522268's: `bench/gen/worker.hpp`, `worker.cpp`, `opgen.cpp`, `tests/gen_tests.cpp` (and
the unchanged `parse.cpp`, `main.cpp`, `exchange.cpp`) are identical. Against ef536a1 it reports
0420da0's change, so it sees a real difference. The CMake changes add `elseif(WIN32)` and `if(WIN32)`
branches and the Linux branches are as they were; `run.test_wrunner` is new on every platform (pure
on Linux, its Windows checks skipped). The coordinator must build the merged tree on L (Debug and the
three sanitizer builds) and run the suite.

## Readings for the revision log

Each is a reading of the frozen text met while building W's harness; none changes a hard case's
outcome or a rule.
1. Section 7's "on W, the rules of W's procedure that can be computed there": the rules that are not
   host-specific apply on W as on L (the server or probe failed, no exchange completed, any connect
   failed, the open loop below 99%); the rules section 7 lists "on L" from `lab/t1/t1.py` apply on W
   where W can compute them: the error share above 0.1% (opgen's report) and the generator's CPUs
   above 90% in a saturation cell (the larger of opgen's own CPU share and the busy share of CPUs 2
   to 9 read by PDH between the markers, in place of `/proc/stat`); the MHz rule's place is taken by
   section 4's frequency rule, which applies only if its counter passed the test against a known
   load; and W's procedure adds that the lab plan is active at the window's start and end. Why it
   follows: section 7 sends W to "the rules of W's procedure that can be computed there" and section
   9.1 makes that procedure "power plan, boost policy, timer resolution, and a CPU frequency counter
   tested against a known load", so the frequency rule is W's form of the MHz rule and the plan is
   part of the procedure; the error and generator rules are W-computable forms of t1.py's, which
   lab/t1 applied on every host P2 measured.
2. Section 7's listen-overflow rule (`TcpExtListenOverflows`, `TcpExtListenDrops`) has no counter on
   W: `GetTcpStatisticsEx` counts failed attempts and resets, not listen overflows. On W a refused
   or dropped SYN shows only as a connect that fails (W reports a refusal after about 2 s, and opgen
   counts a connect not complete at its 1 s timeout as failed), which section 7's "any connect
   failed" already makes invalid. The runner records the change of the TCP statistics per window.
3. Section 2.4's `IP_BIND_ADDRESS_NO_PORT` on W is `SO_REUSE_UNICASTPORT`, set before the explicit
   bind of each source address (ws2def.h: "defer ephemeral port allocation for outbound
   connections"; Winsock's SOL_SOCKET options name it for explicitly bound connects such as
   ConnectEx). Pinned by `gen.pin_reuse_unicastport`. As read on W, `getsockname` names a port at
   once after the bind with or without the option, and each address of 127.0.0.0/8 has a port space
   of its own, which is what a block of K_SRC addresses rests on.
4. Section 7's "the session's value" for W's frequency rule is the server CPU's `% Processor
   Performance` read with W idle at the session's start (3 samples at 1 s), as M3's reading 8 takes
   `pin.sh`'s idle mean at the session's start on L. Not applied while the counter has not passed.
5. WL4 on W: the server's CPU time is the user plus kernel time of `GetProcessTimes` between the two
   markers, Windows' counterpart of `utime + stime` (M3's reading 7), and resident memory is the
   working set and its peak (`K32GetProcessMemoryInfo`).

Notes, not readings:
- Section 9.1's W procedure: the frequency counter was tested against a known load and did not pass
  (above). Section 9.1 then has W windows validated without the frequency rule, and the paper says so.
  Alex approves the procedure (9.1); the outcome is his to accept.
- The open-loop workers on CPUs 2, 4, 6, 8, the spin of 1,500 us and the TIME-WAIT wait are design
  choices of M6b (table above), not frozen values.

## The planned W A/A job

To start as soon as Alex has paused Windows Update, added the Defender exclusion and freed W
(w-procedure section 7: no interactive work; browsers, editors, Razer software and remote sessions
closed; no WSL or Docker running). The job touches: the build directory (its `oneport.exe` and
`opgen.exe`), the job directory under `C:\Users\alext\lab\p3\` (logs and rows), the work tree's
`bench\run` scripts and the Python interpreter
(`C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe`); which of them the exclusion
covers is Alex's choice.

What runs: development data, dedicated against dedicated, the W cost cells of section 6.1 (C1
churn, C2 keep-alive, C3 open loop; HTTP/1.1, h2c, TLS, MQTT; IOCP), 6 sessions per cell (as M3's
aa1 to aa3 on L), the open-loop rate RATE_FRAC x the job's churn median per protocol:

    rem a Release build of the commit the coordinator merges, from an exported copy
    cmake -S <src> -B <build> -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release
    cmake --build <build>
    python bench\run\wjob.py run --dir C:\Users\alext\lab\p3\w-aa --name waa1 -- ^
      python bench\run\waa.py --build <build> --out C:\Users\alext\lab\p3\w-aa\waa1 --job waa1 ^
      --cells churn:http1,churn:h2c,churn:tls,churn:mqtt,keepalive:http1,keepalive:h2c,keepalive:tls,keepalive:mqtt,open:http1,open:h2c,open:tls,open:mqtt ^
      --sessions 6 --seed <a development seed, recorded> --k-src 16

wjob.py refuses to start unless W passes the quiet check, no update installs and the core layout is
as read; it sets the lab plan and restores Alex's plan at the end. `wjob.py stop --dir ... --name
waa1` stops it cleanly. The rows go to the lab journal as development (journal.py's fields; the
journal's host is W).

How long: 12 cells x 6 sessions x 4 windows = 288 windows and 72 session fingerprints. Its parts:
- each window: 6 s of the frozen layout (1 s warm-up, 5 s), at most 1.4 s of opgen's drain
  (timeout plus 0.4 s), and the start, probe, readings and stop (func1's keep-alive windows took
  1.00 to 1.06 s in all with 0.7 s of warm-up and window, so about 0.3 to 0.4 s of that);
- the TIME-WAIT wait, at most 40 s, before any window that follows a churn or open-loop window
  (in func1 25.2 to 30.2 s); keep-alive windows leave 64 connections and need none;
- each session's fingerprint: 4.8 s, timed once on a busy W (the Defender and Update reading, the
  plan's read-back, 3 s of frequency samples);
- once: the lock, the checks before the session (the quiet check is 10 s), the plan switch.
Not yet measured: a full-length window's overhead (func2 was to give more of it and was stopped;
replaced by the estimate from func2b, "The A/A job's length, from measured parts" below). An
upper bound from the parts above, every window taken with the full 40 s wait: 288 x (6 + 1.4 + 0.4
+ 40) s + 72 x 4.8 s = 14,112 s, about 3.9 h. Keep-alive windows need no wait unless they follow a
churn or open-loop window, so the job is shorter; the job can also be split in two (C1 and C2 first,
then C3 with `--rates` from the first job's rates.json).

## Open, and what blocks

- **Blocking the W A/A job:** Alex's pause of Windows Update, the Defender exclusion, and a free
  W. The coordinator asks him. (Done by Alex on 2026-10-03, as the coordinator reported; see "M6b resumed"
  below for what then stopped the job.)
- **The frequency counter** did not pass; W windows are validated without the frequency rule unless
  Alex decides otherwise (section 9.1).
- **Not in this brief, so not built:** more than one worker on IOCP (listed under M6b in
  design/status.md: options (a) to (c) of M6a stand); the W sanitizer record driver
  (`oneport-<commit>-W-asan`); a one-port path in the W runner (M1's IOCP cells time one-port
  mode against itself, which section 8 allows only after the pilot entry for the frozen binary; opgen
  already serves their loads).
- **RK2 on W:** whether K_SRC = 16 holds at W's churn rates, and the TIME-WAIT wait's cost, are for
  the A/A job to show; a connect failure in it needs a revision-log entry.
- The open loop's issue-lag tail on a busy W (above), to read again on a quiet W.
- The merged tree must be built and its suite run on L by the coordinator.

## Where M6b stopped (2026-10-03, 17:30 +0300, the coordinator's pause)

Stopped on the coordinator's instruction: Alex needed W. At the stop: func2 was stopped cleanly (as
above); Alex's plan "ChrisTitus - Ultimate Power Plan" was active and read back
(`powercfg /getactivescheme`); no oneport, opgen or spin process of M6b was left running; no build
or suite was running.

Done: every item of the brief's scope 1 to 4 (opgen on Windows; the runner with its fingerprint,
lock and pid-based stop; the frequency test, run once; the functional tests and the full suite in
Debug and ASan on W, at 76d05c8). Left, when the coordinator resumes M6b:
1. Finish func2 (a functional check of the remaining protocols and loads under wjob.py) and take the
   per-window overhead of the planned A/A job from it.
2. A review of `worker_win.cpp` by a second reader, if the coordinator wants one.
3. Nothing else of the brief; the A/A job waits for Alex (above).

## Records (C:\Users\alext\lab\p3\m6b\)

    ed282f6b41b1e7c22a64ce6db6100db3034640ba2322c21e7237480eb0f27f39  plan-create.json
    206283e95be2408970052d16466dcbff12c0c8ad55c4ca66bf450a3c8abf77de  freq\freq-20261003T164640.json
    32c92f190820cc703186df802fb7cea164a360bfdc0400a19957c909795dcc35  freq\freq-20261003T164640.plan.json
    b10e7ea092290162ce2b0d195c5efaa2bd3b7202a859ac5127226e00e54c5041  func\func1.plan.json
    c26b402643080a4deb44cab45479871b97c63fc15249b8aa620a9426d8e008d5  func\func1.preflight.json
    2b73934b6556dddef881a6146cc68d839d9806bd12d59e75bd2a9915c08e697a  func\func1.done
    ac122111841a16c87db0c6fec0d73f71eee1197d9824f01920613a03a0454efb  func\func1\windows.jsonl
    6e68920ab273c99a6c5c4d1b791fa7c44aaf02a34b931809324b16d997db2eaa  func\stop1.plan.json
    0ec716781aee6bd3adb112d53569697e8752279f663a627cb88aabc08834d08c  func\stop1.done
    fb047c96abf9debca0da7440d40ac625603289212a9e8f1a62f4a08304b3c0ad  func\kill1.plan.json
    a9023a2726b40d2a25a2f84cea4ae2f0af1e20cfe2a4af852e398f9e7ccc7dc3  func\kill2.plan.json
    8c4d25dfd07a8f43a645467b844df27f92d9c6ec23fba3218a169ea311637a43  timer\hrtimer.cpp
    72d245d5fe7459d02901d25d22cd33333779260710ae690ef630e2f92fc11c52  timer\hrtimer-output.txt
    3e02be30ca540e371ef494009eb15ee24e1e0156c2cd95cd3975a713479667e2  timer\spin_check.py
    2840cb163f00c8015e9dde9fb6091ce325be1b359af16331060020cb939812c6  linux_view.py
    511a53ab3a007d2f9cdabacbc0485da5e66a0942969356cf683ece20e25e3b1f  check\76d05c8\debug-76d05c8.build.log
    7c42321e575bb8193bca6f0c3c05606e76a3e842da7588da08a10e5bf098266f  check\76d05c8\debug-76d05c8.ctest.log
    c3d7ecf6406b1f0e0cb522ee024e47c8ff2c3f251a35f2e7a584876fad99811c  check\76d05c8\asan-76d05c8.build.log
    aa148c6399eae488476d9a2d3689fb2c0f1a199ba8b0880422acf017053bd8ad  check\76d05c8\asan-76d05c8.ctest.log

The frequency test ran with wfreq.py and wpower.py as committed in c215778, and with wsys.py before
the job's stop event was added to it (the functions the test used are unchanged).

## M6b resumed (2026-10-03, from 23:05 +0300)

### The frequency retest, as planned before it ran

Alex's addition, approved and passed on by the coordinator: retest the counter with a control that
surely moves the clock, once, right before the W A/A job and never during it. Its design is the
revision of design/w-procedure.md section 4 dated 2026-10-03: the same phases on CPU 10 (idle and
load under the lab plan), then the load under a second test plan "oneport W cap50" (the lab plan
with the minimum and maximum processor state at 50%), created once by `wpower.py create-cap` and
switched to inside the lab plan's session, so the session's end and its guard restore Alex's plan;
both counters and the spinner's work rate recorded in every phase; the quiet check first. Pass:
under the lab plan every load sample within 2% of the load mean, and under the cap the counter's
load mean more than 2% from the lab plan's. Beside the rule: work falling by more than 2% with the
counter still means a blind counter; neither moving means an inconclusive test. The A/A job runs as
briefed whatever the outcome (FREQ_RULE off, the counter in every row); the outcome is a reading
for the coordinator.

### What ran, in order

Brief of the resumed M6b: merge the last tested state of main (0567012, M7b) into `m6b-windows`, build
and run the suite on W in Debug and ASan, dry-run the W sanitizer-records driver, finish func2, take
the A/A job's per-window overhead from it, prepare the A/A job, and (the coordinator's change of
2026-10-03) start it once all of that passed, with the frequency retest right before it. Alex had
paused Windows Update until 2026-11-01 21:07 UTC, added a Defender exclusion of `C:\Users\alext\lab`
and freed W for about 4 h (the coordinator's message; this session read neither setting). L was not
used, except one `git fetch lab` at the start of this session, before the hard rule was applied to
the remote (`lab` is `alex@192.168.1.62`, L); nothing was pushed there.

| Commit | Message (first line, shortened) |
|---|---|
| 83cbb77 | chore: merge 0567012 (M7b on main) into m6b-windows |
| 2b6aed0 | fix: the merged tree builds on W with MSVC: opcase's JSON quoting helper is json_quoted; record.cpp's fopen without C4996 |
| 84c7912 | feat: the frequency retest (wpower.py create-cap, wfreq.py --control cap, the work-rate reading) |
| 0698947 | docs: w-procedure.md section 4's revision and the retest's plan, written before it ran |
| 0c1420a | feat: wfreq.py --require-quiet |

### The merge (83cbb77)

No conflicts. The two sides share one file, `tests/CMakeLists.txt`, whose hunks are apart: main's
in the Linux block and the pure tests, M6b's in the Windows block and the Python tests. Main's side
changes nothing under `bench/gen` and nothing of `window.py` or `aa.py`, which the W runner imports.

### The build on W, and what was fixed (2b6aed0)

The merged tree did not compile on W. `bench/cases/run_cases.cpp` (new on main, compiled into the
`opcase` library on every platform) failed with C2677, C2676 and C2039 at lines 110, 127 and 183:
its helper `quoted(std::string_view)` lost to `std::quoted`, which MSVC's standard headers declare
and argument-dependent lookup found for every `std::string` argument (`v.id`, the TLS fields). The
helper is now `json_quoted`, in its anonymous namespace; Linux's behaviour is unchanged. Also,
`bench/server/record.cpp` (new on main) drew warning C4996 for `std::fopen`; the warning is now
disabled around that line under `_MSC_VER` (push, disable, pop), so the open is the same call on
every platform. Nothing else of the merged tree needed a change on W.

### The suite on W (development checks, not records)

From exported copies (`git archive`) in `C:\Users\alext\lab\p3\m6b\check\`, with M6b's `check.cmd`
(MSVC 19.51.36246.0, Build Tools 18, Ninja, `ctest -V -j 4`, ASan with
`ASAN_OPTIONS=detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1` in the vcvars64
environment). Report lines: lines of the ctest log matching the shared report pattern
(`bench/oneport_record.py`, `REPORT`).

| Build | Commit | Build warnings | CTest | Test time | Report lines |
|---|---|---|---|---|---|
| Debug (release libraries) | 2b6aed0 | 0 | 160 passed, 0 failed | 52.91 s | 0 |
| ASan (`-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address`, asan libraries) | 2b6aed0 | 0 | 160 passed, 0 failed | 56.91 s | 0 |
| Release (the A/A build, below) | 0698947 | 0 | 160 passed, 0 failed | 50.77 s | not counted (no sanitizer) |

The ASan build is instrumented as M6b's was: `opgen.exe` and `oneport_tests.exe` import
`clang_rt.asan_dynamic-x86_64.dll`; `worker_win.cpp.obj`, `worker.cpp.obj` and `opgen.cpp.obj` hold
148, 122 and 100 symbol lines naming `__asan_`. W's suite grew from 156 to 160 entries: main's four
new pure tests `clienthello.scan`, `.helloroom1`, `.refusal` and `.need_bound`. 0698947 changes only
Python files against 2b6aed0 (`bench/run/wpower.py`, `wfreq.py`, `test_wrunner.py`, now 19 checks),
and its Release suite passed them.

Linux-only tests, and how W skips them:
- Not registered on W: every test that `tests/CMakeLists.txt` adds inside
  `if(CMAKE_SYSTEM_NAME STREQUAL "Linux")`: the `server.*`, `handlers.*` and `relay.*` tests per Linux
  backend (with main's new `server.cases_by_port`, `server.binary_record.*`, `handlers.tls_deferred`,
  `relay.pass_through_storage.*`), the kernel pins (`server.kernel_*`, with main's new
  `server.kernel_nodelay_inherited`), opgen's tests on epoll and io_uring, and the opcase and ophold
  programs. W registers the IOCP forms (`iocp.*`, `loop.IOCP.*`, `handlers.*.IOCP`, `gen.*.IOCP`,
  `case.HC*.IOCP.inproc.*`) instead.
- Skipped inside the Python tests: `run.test_runner` skips 13 checks (`skipUnless` Linux: bash,
  signals, `/proc`, taskset, L's cpufreq layout, the system OpenSSL); `run.test_competitors` skips 2
  (Linux only); `gate.test_record_writers` skips its comparison with the Papers repo's
  `lab/bin/test_report_pattern.sh` when the checkout is not inside the Papers repo (the exported
  copies). In the records driver's dry run, which builds from the work tree inside the Papers repo,
  the comparison ran: "ok: the shared pattern equals lab/bin/test_report_pattern.sh's".

### The W sanitizer-records driver, dry run

    powershell -ExecutionPolicy Bypass -File bench\sanitize_oneport.ps1 -DryRun ^
      -Records C:\Users\alext\lab\p3\m6b\records-dry\records -Work C:\Users\alext\lab\p3\m6b\records-dry

From the work tree at 2b6aed0 (clean). It parsed (PowerShell's parser: 0 errors) and ran green in
80 s: the whole project built with MSVC ASan, `build_inputs.py --host W` hashed 9 targets with no
mismatch against the compile database, the suite passed 160 of 160 with 0 report lines, the logs
were kept and packed with their sha256, and `oneport_record.py --dry-run` wrote
`oneport-2b6aed09b-W-asan-dryrun.json` (green, `"dry_run": true`, compiler MSVC 19.51.36246.0, config
Release and IOCP, pins 2d49d03bacf8). Never citable; nothing was written into
`lab\sanitizer-records`. Seen in passing: vcvarsall.bat printed "'vswhere.exe' is not recognized as
an internal or external command" on the driver's console (its standard error is not redirected);
the build still identified MSVC 19.51.36246.0 and the record is unaffected. Left as is.

The gate, on the A/A job's Release build (`C:\Users\alext\lab\p3\build-0698947`):
- `build_inputs.py --host W`: 9 targets, no mismatch, so `TARGETS["W"]` holds for the merged tree
  (M7 checklist item 2); `BINARIES["W"]` (`oneport.exe`, `opgen.exe`) are found and hashed.
- `check_records.py --host W` with the dry-run record among the records: refused, exit 1,
  "oneport-2b6aed09b-W-asan-dryrun.json is a dry run of the records driver: it never gates a build
  and never belongs among the records".
- With no records: refused, exit 1, "oneport (inputs d10d4f45b353) has no green asan record on W
  with compiler MSVC 19.51.36246.0, its configuration and pins 2d49d03bacf8, and no declared gap".
- With `--accept-dry-run`: passed, every one of the 9 targets covered by the dry-run record,
  output marked `"dry_run": true`, `"citable": false`. The record was built from the work tree at
  2b6aed0 and the gated build from a clone at 0698947 in another directory, and their inputs hashes
  are equal, so on W too the hash does not depend on the source path.

### func2, finished (job func2b)

The stopped func2 (76d05c8's runner, 4 windows of churn h2c) is replaced by func2b: the 9 cells of
the A/A job that func1 did not cover (churn h2c, TLS, MQTT; keep-alive HTTP/1.1, h2c, MQTT; open loop
HTTP/1.1, h2c, TLS), one session each, dedicated mode only, full-length functional windows (1 s
warm-up, 5 s window, flagged functional, no ratio), K_SRC 16, the open loop at a fixed 2,000 per
second (`--rates`), seed 20261003, from the A/A job's source copy and Release build. Launched
detached through WMI (`Win32_Process.Create`, below), under wjob.py with `--allow-noisy`.

- Start 23:26:35, end 23:42:13 +0300. The preflight's quiet check failed (mean idle 91.3%; MsMpEng
  12.8%, dwm 11.6% and System 9.4% of one CPU), so the job was a functional check by its own rule.
- 36 of 36 functional windows valid. Every row: probe exit 0, no connect failure, the server's
  affinity 0x400 and opgen's 0x3FC, the lab plan active at both ends, the server stopped by its event,
  the timer resolution 1.0 ms. The job exited 0 and Alex's plan was restored (23:42:12) and read back.
- Provenance names commit 069894782873 with `dirty` false (the source copy is a clone, so git
  answers in it) and the binaries' sha256 below.
- RK2 on W, functional only: at churn rates up to 6,064.6 connections per second in these windows
  (W not quiet), K_SRC = 16 gave no connect failure. A churn window ended with up to 40,561
  TIME-WAIT entries.
- The open loop's issue lag on a busy W: median 0.6 to 0.7 us in all 12 open-loop windows; p99 4.0
  to 63.8 us in 11 of them and 2,499.8 us in one (open HTTP/1.1, p2); maximum 200.0 us to 27,363.7
  us. Still to read again on a quiet W.

Per-window parts, measured in func2b (`C:\Users\alext\lab\p3\m6b\estimate.py`; overhead = the row's
`window_overhead_s` less its TIME-WAIT wait and the 6 s of warm-up and window, so the start, the
probe, the readings, opgen's drain and the stop):

| Part | n | Median | Min | Max |
|---|---|---|---|---|
| overhead, churn window | 12 | 0.35 s | 0.29 s | 0.42 s |
| overhead, keep-alive window | 12 | 0.26 s | 0.24 s | 0.35 s |
| overhead, open-loop window | 12 | 0.28 s | 0.26 s | 0.36 s |
| TIME-WAIT wait of a window after a churn or open-loop window | 23 | 29.07 s | 24.77 s | 30.08 s |
| gap between sessions (the session's fingerprint), from the rows' 1 s start stamps | 8 | 4.67 s | 3.76 s | 4.77 s |

A keep-alive window after a keep-alive window found 65 to 328 TIME-WAIT entries and waited 0 s. The
job's start (lock, core layout, Defender and Update read, 10 s quiet check) took 11 s before the
preflight record was written.

### The A/A job's length, from measured parts

The 3.9 h bound of "The planned W A/A job" (every window with a 40 s wait) is replaced. With seed
861, waa.py's order (replayed with the same calls on `random.Random(861)`) gives 288 windows in 72
sessions, of which 191 follow a churn or open-loop window (11 of those are keep-alive windows). Sum
of 6 s per window, the median overhead of its workload, the median wait (29.07 s) for those 191, and
the median session gap for the 72 sessions: 7,702 s, 2.14 h; with the largest measured wait (30.08
s) for each: 7,895 s, 2.19 h. A bound with a 40 s wait for each of the 191 and the largest measured
overhead and session gap: 9,820 s, 2.73 h. Measured: the overheads, the waits, the session gap and
the start; taken from the design: the 6 s per window and the 40 s bound. Not measured: the A/A job's
open-loop rates, which are RATE_FRAC (0.5) of the job's churn medians rather than 2,000 per second;
an open-loop window's wait is bounded by `TcpTimedWaitDelay` (30 s) and `TW_WAIT_MAX_S` (40 s) all
the same.

### The frequency retest: not run (W not quiet)

`wpower.py create-cap` created the control plan at 23:42:34 +0300, no command elevated: "oneport W
cap50", `ea6245cb-3cb9-491a-986c-1cb98f8a7164`, duplicated from the lab plan, read back as boost
mode 0, minimum and maximum processor state 50%, parking 100%, idle disable 0 (record
`freq\cap-create.json`). It is left in place; deleting a plan is a settings change nobody approved.

`wfreq.py --control cap --require-quiet` ran twice, and each time stopped at its quiet check before
any plan switch:
- 23:42:35: mean idle 90.3%; CPUs 2, 3, 7, 8, 9, 10 below 95% (8 to 10 at 80.9 to 81.8%);
  BackgroundDownload.exe at 57.5% of one CPU (pid 24352, Visual Studio Installer's background
  download, from `%TEMP%\lijzlvr4.ipp\...\Microsoft.VisualStudio.Setup.Service\`, started 23:41:40),
  System 16.1%, MsMpEng 5.2%. That process ended by 23:43:55; it was not touched.
- 23:44:26: mean idle 97.5%; CPU 8 idle 93.4%; System at 8.4% of one CPU.

So the counter was not retested, and section 9.1's fallback stands as after the first test.

### The W A/A job: prepared, start refused by its quiet check

Prepared:
- Source copy: `C:\Users\alext\lab\p3\src-0698947`, a clone of the work tree checked out at
  0698947 (detached, clean), not a `git archive` export: waa.py's provenance asks git for the commit
  and whether the tree is dirty in the build's source directory, and in an archive both read empty.
  bench is the same at 0c1420a except `wfreq.py`, which the job does not run.
- Release build: `C:\Users\alext\lab\p3\build-0698947`, MSVC 19.51.36246.0, Ninja,
  `-DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release` (`m6b\release.cmd`), 0 warnings, its suite 160
  of 160. sha256: `oneport.exe` b6074f485a9758f36bf782d079ddfdccf61dfd04284c53e69d61c67035155aa8,
  `opgen.exe` d3b0fc173520166c1223d94e9f9597d8b5358f3ef81e07c5141df98bd0979b0f.
- Under `C:\Users\alext\lab` as well: the job directory `C:\Users\alext\lab\p3\w-aa`, so the one
  Defender exclusion covers the source copy, the binaries, the logs and the rows. Outside it: the
  interpreter `C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe` and the Papers
  repo's `lab\bin\inputs_hash.py`, which waa.py reads once at its start.
- Development seed: 861 (the job's order and arms; no seed of that value is named in status.md or
  in the Papers repo's `lab/journal.jsonl`). func2b used 20261003. The seeds entry must avoid both.

The start command (one line; launched through WMI so that it runs in Alex's session, 1, outside the
job object of the agent's shell, and outlives that shell; from an ordinary console the same line
runs in the foreground):

    "C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe" C:\Users\alext\lab\p3\src-0698947\bench\run\wjob.py run --dir C:\Users\alext\lab\p3\w-aa --name waa1 -- "C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe" C:\Users\alext\lab\p3\src-0698947\bench\run\waa.py --build C:\Users\alext\lab\p3\build-0698947 --out C:\Users\alext\lab\p3\w-aa\waa1 --job waa1 --cells churn:http1,churn:h2c,churn:tls,churn:mqtt,keepalive:http1,keepalive:h2c,keepalive:tls,keepalive:mqtt,open:http1,open:h2c,open:tls,open:mqtt --sessions 6 --seed 861 --k-src 16

The launcher used (`C:\Users\alext\lab\p3\m6b\wlaunch.ps1`, not committed):

    powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\alext\lab\p3\m6b\wlaunch.ps1 -Dir C:\Users\alext\lab\p3\w-aa -CommandLine "<the line above>"

The stop command:

    "C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe" C:\Users\alext\lab\p3\src-0698947\bench\run\wjob.py stop --dir C:\Users\alext\lab\p3\w-aa --name waa1

Its pid file is `C:\Users\alext\lab\p3\w-aa\waa1.pid` and its done file `...\waa1.done`. A new
attempt needs another `--name` (waa2), or the waa1 files moved aside, since the pid, start, preflight
and done files of waa1 are kept.

What happened: launched at 23:45:00 +0300 (pid 16184). wjob.py refused at its preflight, exit 90
("W is not quiet", done file at 23:45:11), before any plan switch; no window ran. Its quiet check:
mean idle 96.3% (passes), but CPU 8 idle 92.2% and CPU 10 idle 92.8%, MsMpEng (pid 5780) at 5.2%
and System (pid 4) at 7.2% of one CPU. The top processes it named: System 7.2%, MsMpEng 5.2%,
CrossDeviceService 2.5%, HapticService 1.1%, and this session's own wait loop (grep, 0.5%). One of
its ten 1 s idle samples read 84.8%, the others 95.9 to 98.6%. As the coordinator's change says, the
check was not weakened and the job was not started again.

A reading right after (23:45:38 to 23:45:48, `Get-Counter`, read only): CPUs 0 to 7 idle 97.7 to
99.4%, CPUs 8 to 11 idle 94.0 to 95.1%, every CPU's interrupt and DPC shares at most 0.31%. So the
load on CPUs 8 to 11 is thread time, not interrupts; which threads was not established. Not
established either, and worth a look by the coordinator: wjob.py's preflight reads Defender's
state (`Get-MpComputerStatus`, a PowerShell call) right before its 10 s quiet check, so Defender's
own work for that query may fall into the check. MsMpEng read 5.2% in waa1's check, 12.8% in func2b's
and 0.6% in the second retest's, which also reads the state first.

### Readings for the revision log (the coordinator's; none was added to hypotheses.md)

1. The frequency counter was not retested: W failed the quiet check both times (above). Section
   9.1's fallback stands as recorded after the first test; the rule's use for confirmatory windows
   is still to be decided before the code freeze.
2. RK2 on W, functional evidence only: K_SRC = 16 gave no connect failure in func2b's 36 windows at
   churn rates up to 6,064.6 connections per second; W was not quiet, so this is not a window's
   evidence.
3. The seeds entry (M7 checklist item 5): development seeds 861 (waa1, refused before any window,
   so no order was drawn) and 20261003 (func2b) were used on W; no frozen seed may take either.
4. M7 checklist item 2, W's half: the merged tree builds on W after 2b6aed0's two fixes, and the
   suite passes in Debug and ASan (160 each, 0 report lines); `build_inputs.py`'s `TARGETS["W"]`
   and `BINARIES["W"]` hold.
5. The W records driver (`sanitize_oneport.ps1`) works as written in dry-run mode; the gate refuses
   its dry-run record and a missing record, and matches the record to a Release build in another
   directory. Seen in it: on W the record's `third_party` is empty (`fetched` and `found`), so the
   gate's pins check (`gate_lib.pins_differ`: the pins file's sha256, then each archive both
   fetched) compares the pins file only on W. Whether W needs more there is for the coordinator.

### Open, and what needs Alex

- The W A/A job did not start: W did not pass the quiet check (above). To run it, W must be quiet
  at the job's start; the start command above runs it as briefed.
- The frequency retest is still to run, right before the A/A job and with W quiet; its plan exists.
- The plan "oneport W cap50" (`ea6245cb-3cb9-491a-986c-1cb98f8a7164`) stays in W's plan list until
  Alex removes it or approves its removal.
- `m6b-windows` was pushed to `origin` only. The `lab` remote is on L, which this task did not use.

### Where M6b stopped (2026-10-03, 23:46 +0300)

At the stop: Alex's plan "ChrisTitus - Ultimate Power Plan" active (`powercfg /getactivescheme`);
none of the 39 process ids this session recorded (the two jobs, func2b's guard, its 36 servers) is
running; no build, suite or job of this session is running.

### Records (C:\Users\alext\lab\p3\)

    f59a3f8ab34c13e400417408d7e07d98a56f9c0b0382fb08655c795190e04821  m6b\records-dry\records\oneport-2b6aed09b-W-asan-dryrun.json
    61a41fd4f5d44c8e31c4f637489ffed7ad27a5d1c378994ef78e8fa20810c621  m6b\records-dry\records-logs\oneport-2b6aed09b-W-asan-dryrun.tar.gz
    877c0b2d4c3e69ba97266bef32e8dbe3012e15dabf324fba85a11c563ea6964c  m6b\gate\release-0698947.inputs.json
    2493acb5b98c0e0c8f6095f546995f7fb4608f3d0d0810c9a51ed13b9a7bd298  m6b\gate\gate-W-dryrun.json
    ce5b1f1233283f20e116f5b7c151aa7ba5990f95270e47a173f09afd1d36823c  m6b\check\2b6aed0\debug-2b6aed0.build.log
    25306ffa2efc108b9fd44517fbf76b76c560a1a60b788e1d07a55f8482b9b968  m6b\check\2b6aed0\debug-2b6aed0.ctest.log
    7ab77673b39e8f44a3edc4b41db263381a80dd619ea6b07064f650e3dd252f95  m6b\check\2b6aed0\asan-2b6aed0.build.log
    08c7c4ca67d263a33c1f4fec2cb96755a14ea4beeadeed459abceae04aeb753c  m6b\check\2b6aed0\asan-2b6aed0.ctest.log
    5732ef7702e11e9e67f4cd3f0a10c4cdbfaa2181c9a4dd7060517db53db7ebf9  m6b\release-0698947.build.log
    de05562ef55f7fee12fe0c2fe42411eab8184b7425c7df513e88e281c5434485  m6b\release-0698947.build.log.ctest
    4aff7cb81704ad9279e045a2a97945fbbb7036606f3b0fff2e2885a7bb0a9dd7  m6b\func\func2b.preflight.json
    5f6c219d4832376d85f5254fc71a833b41ae90d9a2ce5ceb331354a395bb5f6b  m6b\func\func2b.plan.json
    09118e02f6b8450dc1fd556981d2288f8a484e0e1a72e6043b51e15676e3a749  m6b\func\func2b.done
    9c0b23f581284c67cf2ea6ed0e6209b3067f8b49f08fe74e3917cefbfd59e17c  m6b\func\func2b.log
    a9b7855b1031f53b4a604249465274bf7162c3fc7d8582d3bce1542c32a623f6  m6b\func\func2b\windows.jsonl
    2b0342186e1ab029cbb5d5ef1c4fb8a83055505057a8cf6fb068c22bf8695b57  m6b\func\func2b\provenance.json
    f100affa736fdcb1c04098e66bbae9300ff34031eb3734622be08ad1b2d647b7  m6b\func\func2b\summary.json
    5103643fd24d2dfe846a2a52d46bf989e51f89977d55e52c552d2eeb19662bbc  m6b\freq\cap-create.json
    672be675fca834ce57e9f0448cceb849bece95e294b5177f119eb6f6b03ffd35  m6b\freq\freq-20261003T234235.json
    e2ce76a9d92e0b36de23b243199c6a1e6057b7de398c49364d4ec5de280a9e6f  m6b\freq\freq-20261003T234426.json
    ba6bbac1d3edf4d2e09c29e4fef858020e7e8d3db7af2681bfbb631db49fb9b5  w-aa\waa1.preflight.json
    7051dd1fce46525f8a486539cfdcafe72d3cbc1582a0884884938da458275ecd  w-aa\waa1.done
    7ff455be3f24fe96ae8b02000a0326c92499c3939c91c02b2f0c19cc4c0496b5  m6b\estimate.py
    9264a15c41688469e29b51e5aed3020367e396fa9b4fb373c8a85dbd966ef6eb  m6b\wlaunch.ps1

### The night launcher (wnight.py, 78c2ea4), started 2026-10-03 23:58:56 +0300

The coordinator's task after the refusal: an unattended, delayed, retrying launcher. Its readings
(23:53, two standalone quiet checks) did not support the Defender-read lead, so the harness is
unchanged. `bench/run/wnight.py`, copied to `C:\Users\alext\lab\p3\m6b\wnight.py` (sha256
3c916d10a42d9a52ab23cfe6e41ee9d84f69269fd7451b7c85b5ed684b8c8fb6, equal to the commit's), started
detached through WMI (`m6b\wlaunch.ps1`), pid 22372:

    "C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe" C:\Users\alext\lab\p3\m6b\wnight.py --dir C:\Users\alext\lab\p3\m6b --src C:\Users\alext\lab\p3\src-0698947 --build C:\Users\alext\lab\p3\build-0698947 --freq-src C:\Users\alext\lab\p3\src-0c1420a --first-delay-s 900 --retry-s 600 --settle-s 120 --no-aa-after 2026-10-04T05:00 --no-start-after 2026-10-04T07:45 --cutoff 2026-10-04T08:00

- First attempt 2026-10-04 00:13:56 +0300. Each loop: the retest (from `src-0c1420a`, a clone at
  0c1420a, `wfreq.py --control cap --require-quiet`, its own quiet check; the cap plan "oneport W
  cap50") unless it completed or failed; then the A/A job `wjob.py run --dir
  C:\Users\alext\lab\p3\w-aa --name waa2` with waa1's arguments (src-0698947, build-0698947, the 12
  cells, 6 sessions, seed 861, K_SRC 16; `--out ...\w-aa\waa2 --job waa2`). After a quiet refusal
  (wjob exit 90 or 92, wfreq exit 3) it logs the reasons, top processes and each CPU's idle, renames
  a refused job's files to `waa2-refusedN.*`, sleeps 600 s and loops. After the job, 120 s, then the
  retest again if it has not completed.
- No A/A start after 2026-10-04 05:00; nothing started after 07:45; at 08:00 it exits, and asks a
  job still running to stop (`wjob.py stop`) first. Nothing weakened, nothing elevated, no process
  ended by name.
- Files in `C:\Users\alext\lab\p3\m6b\`: `wnight.pid`, `wnight.log` (JSON lines), `wnight.done`;
  the stop file `wnight.stop` ends it at its next loop or sleep tick. A running job is stopped with
  `wjob.py stop --dir C:\Users\alext\lab\p3\w-aa --name waa2`.
- Tested before the launch with stub scripts and second-long times (scratch, not committed): a
  refusal of each then success; the A/A window already past; the stop file; the cutoff during a
  running job (stop asked, job exit 130); the retest refused until its no-start time; a retest that
  fails outright (not tried again).
