# P3 engineering status

The state of the engineering phase (hypotheses.md, section 8, step 2). Started 2026-10-02 with
M0. Nothing in this file is a result: builds and tests here are not measurements, and no window
has run.

## Milestones

| Id | Milestone | State |
|---|---|---|
| M0 | Foundations | done, 2026-10-02 (below) |
| M1 | epoll server with the detection table, the HTTP/1.1 handler and the 25-case generator as a deterministic test suite under every sanitizer | next |
| M2 | h2c, TLS, PROXY, SSH and MQTT; relay mode and io_uring | |
| M3 | Harness and A/A-noise engineering, in dedicated mode only | |
| M4 | Competitors | |
| M5 | Iterate until it wins | |
| M6 | Windows | |
| M7 | Code freeze | |

## Engineering constraints

Followed in every milestone:
- Never time one-port mode against dedicated mode before the pilot entry. During development,
  dedicated mode gets functional tests only. The one exception is dedicated-against-dedicated
  (A/A) harness-noise work in M3, journaled as development, which is not the pilot.
- The sanitizer test suite must exercise every backend, mode and flag combination, and all 25
  hard cases, so that one record per commit and platform is honest under D5.
- L packages: pinned user-space downloads into `~/opt` with a sha256, from official release URLs.
  `pacman -S` is allowed for missing tools, never `-Sy` or `-Syu`. If `pacman -S` fails because
  the mirror moved past the local sync DB, use `pacman -U` with the exact version the local DB
  names (`pacman -Si <pkg>`) from `archive.archlinux.org`. No reboot, no boot-parameter changes.
- Lab traffic uses loopback and 192.168.1.62 only. Never `pgrep -f` or `pkill -f` on L; use pid
  files. (L's login shell is zsh: loops go in bash scripts.)
- io_uring kernel writes are invisible to MSan, so that is a declared gap in `bench/coverage.json`.

### Does section 8 allow A/A development windows?

Yes, before the code freeze only. Section 8, step 2 (frozen): "Before the code freeze they may
time dedicated mode against anything, and one-port mode against the competitors or against
another one-port option. No window, on any code, times one-port mode against dedicated mode
before the pilot entry." A dedicated-against-dedicated window is "dedicated mode against
anything". The same step makes such runs development data: never results, cited only in the
revision log and the lab journal, and disclosed in the methods. Three consequences:
- M3's A/A work ends at the code freeze. After `CODE_FREEZE`, step 4 allows on the frozen binary
  only rule E's IOCP receive form and the A/A pilot in its `SEED_PILOT_*` order; no development
  A/A window runs on the frozen binary.
- The window layout is frozen (section 4.1: 1 s warm-up, 5 s measured window, sessions X Y Y X,
  the placement on L; section 7's validity rules). Harness engineering may change the harness to
  meet it, never the layout.
- Nothing measured in development A/A windows enters the pilot's rules: the simulation of step 5
  runs "on the pilot's data alone".

The engineering constraint above is narrower than the frozen text (which also lets dedicated
mode be timed against the competitors); the narrower rule is followed.

## M0, 2026-10-02

### Commits (papers/one-port)

| Commit | Message |
|---|---|
| fe1d625 | feat: event loop derived from P1's loop (bench/loop) |
| 51e4e62 | feat: oneport flags, CMake build and CTest suite (M0) |
| ea128ef | test: sanitizer records gate adapted from P2 (bench/) |
| 45023e9 | test: the record-writer test prints no line that matches the report pattern |
| 66889fa | feat: the Appendix A power simulation of the R rule (analysis/) |
| a2ba3e6 | docs: proposal Appendix A names the committed script (closes audit 2 N5's deferred item) |

This file is committed after them. Nothing is pushed to origin. The `lab` remote,
`alex@192.168.1.62:lab/p3/one-port.git`, has every commit.

### The loop: `bench/loop/`

- Directory: `bench/loop/`, beside proposal I33's `bench/server/`, because `opgen` will use the
  same loop. Library `oneport_loop`, namespace `oneport::loop`, header
  `bench/loop/include/oneport/loop.hpp`.
- Source: paper-wake-defect `loop/` at commit 0af1ac4
  (`git -C papers/wake-defect log -1 --format=%h -- loop`). Every copied file begins "Derived from
  paper-wake-defect loop/ at commit 0af1ac4, same author.", and so does the commit message.
- Kept, as proposal I2 lists: the io_uring ring on raw system calls (no liburing), created
  `SINGLE_ISSUER`, `DEFER_TASKRUN` and `R_DISABLED` and enabled by `start()` on the worker; the
  MSan rule for kernel-filled memory (value-initialise, then `kernel_wrote` unpoisons what the
  kernel reports); the eventfd stop path; the IOCP port setup; the sanitizer CMake options.
- Dropped: P1's wake path (wake eventfd, multishot wake poll, `post()`), its task queue
  (`TaskStack`) and its seeded defect (`WAKELOOP_DEFECT`). They were P1's experiment, not P3's.
  Also dropped: the `epoll_wait` fallback, since the design names `epoll_pwait2` (I13).
- Changed: the wait bound is an argument of each `wait()` (I13: each pass waits until the
  earliest deadline), `std::nullopt` blocks, and zero polls. After `stop()` every wait returns at
  once. The io_uring stop poll is single-shot, so a stopped io_uring wait polls instead of
  blocking. The M0 test `loop.io_uring.stop_is_sticky` found the case. P1 never waited after a
  stop.
- Not yet built (M1): socket registration and event dispatch, the deadline queue, the counters.

### Flags: `bench/server/config.{hpp,cpp}`

The flag names are the proposal's (`--mode`, `--detect`, `--dispatch`, `--backend`; I1, I11,
I16, I17, I20), and the values are the frozen names of hypotheses.md ("Words"). Each flag and
value has exactly one spelling, case-sensitive, with no alias. `--detection`, `iocp`,
`one_port`, `smtp` and `--mode=one-port` are all refused.

| Flag | Values | Default |
|---|---|---|
| `--mode` | `one-port`, `dedicated`, `stub` | required |
| `--detect` | `replay`, `peek` | required |
| `--dispatch` | `inproc`, `relay` | required |
| `--backend` | `epoll`, `io_uring`, `IOCP` | required |
| `--iocp-receive` | `zero-byte`, `posted` (rule E) | `zero-byte` |
| `--relay-copy` | `user-space`, `splice` (rule E) | `user-space` |
| `--proxy` | `off`, `on` (PROXY v1 and v2 on every listener) | `off` |
| `--fallback` | `none`, `SMTP`, `SSH` | `none` |
| `--listener` | `shared`, `reuseport` | `shared` |
| `--workers` | whole number, at least 1 | 1 |
| `--port` | 1 to 65535, the first listening port | unset |
| `--t-fb-ms`, `--t-dec-ms`, `--t-hdr-ms` | T_fb, T_dec, T_hdr in whole ms, at least 1 | 3000 |
| `--print-config` | none: print the parsed configuration and exit 0 | |
| `--help` | none: print the usage and exit 0 | |

- The four arm flags have no default. The pilot runs "two starts of the same binary and flags",
  and an A/B pair differs by `--mode` alone, so every arm is spelled out.
- A flag that does not apply is accepted and echoed, so one flag set serves both arms of a
  cell. For example, dedicated and stub mode accept `--detect`.
- Refused: a backend this platform does not compile; relay on IOCP (I17, Linux only);
  `reuseport` on IOCP (measured on epoll and io_uring only, section 10); a flag given twice; an
  unknown flag; a missing value.
- Exit codes: 0 for `--print-config` and `--help`; 2 for a usage error; 3 for serving, "serving is
  not implemented in M0".
- I21: only the parser, its printer and (from M1) the listener setup may read `Config::mode`.
  `main.cpp` does not read it. M1 adds the structural test.

### Build and tests

CMake 3.25 or later, C++23. Targets: `oneport_loop`, `oneport_config`, `oneport` (the binary),
and `oneport_tests` (one CTest entry per case). The CTest suite has these entries:
- `flags.*`: 14 parser cases. They pass the platform to the parser, so they run alike on L and W.
- `loop.<backend>.*`: 9 cases per compiled backend. These are construct, bounded wait (not
  early, on Linux), zero wait, stop wakes a blocked wait, stop before start, stop is sticky, a
  second start refused, wait before start refused, and a negative bound refused.
- `cli.*`: 4 entries for the binary's exit code and output (`tests/run_expect.cmake`).
- `gate.*`: the two Python test files, when a Python 3 interpreter is found.

On L that is 38 entries: 14 + 9 × 2 + 4 + 2.

### The gate: `bench/`

Copied from paper-typed-routing at commit 7c1e248 (the files were last changed there at 65817be),
same author, with the paths and names of this repository:

| File | From |
|---|---|
| `bench/gate_lib.py` | `bench/gate_lib.py` |
| `bench/check_records.py` | `bench/check_records.py` and `t1/check_h6_records.py` |
| `bench/oneport_record.py` | `t1/h6_record.py` and `bench/regexmatcher_record.py` |
| `bench/test_gates.py` | `bench/test_gates.py` |
| `bench/test_record_writers.py` | `bench/test_record_writers.py` |

- Kept: a measured build is refused unless green records cover every target by inputs hash,
  with the same compiler, configuration (the code-selecting options), pins file hash and fetched
  archives. A red record with the same inputs stops the gate. A gap must be declared per target.
- Adapted: the host is an argument. L needs ASan+UBSan, TSan and MSan; W needs ASan
  (hypotheses.md, section 11). Records are named `oneport-<commit>-<host>-<san>.json`. P2's check
  of a second, header-only dependency is gone, since oneport has none.
- `bench/coverage.json` has two sections. The gate reads `targets` (empty in M0), where a target
  may be named with `not_covered_by`. It does not read `declared_gaps`, which lists section 11's
  gaps: OpenSSL's assembly, OpenSSL under TSan, the io_uring MSan blind spot with its mitigation,
  the competitors, the harnesses, and Windows (ASan only).
- `bench/cmake/pins.cmake` pins nothing yet. It states what is pinned at the code freeze. No hash
  was invented; the pin test changes the file by one line instead of flipping a pin.
- Tests added beyond P2's: a record with another configuration; the W host, where L's records do
  not count; a gap written only in `declared_gaps` allows nothing; the writer's report pattern is
  the shared one. `bench/test_gates.py` makes 18 checks. `bench/test_record_writers.py` makes
  26 where the Papers repo surrounds this one (on W), and 25 elsewhere (on L the comparison with
  `lab/bin/test_report_pattern.sh` is skipped). All pass on L and W.
- Found on L at ea128ef and fixed at 45023e9: `test_record_writers.py` printed its sample report
  lines, which match the report pattern. A record scans the `ctest -V` log, so every record would
  have gone red. The test now prints sample numbers, and it checks that nothing it prints
  matches.

### Power simulation (audit 2 N5): `analysis/appendix_a_r_rule.py`

The scratchpad held `rrule.py`, `rrule2.py`, `timeplan.py`, `parts.py`, `chk.py` and
`st13_sim.py`. `rrule2.py` is Appendix A's script, with master seed 43, eight pilots per σ in
{0.010, 0.0125, 0.015}, and 80% and 90% bounds. It imports `rrule.py`. The others are the time
plan, the sign-test grid and the first audit's simulation. The two files are merged into one
with the numerical code unchanged.

Command, on W, with Python 3.14.5 and numpy 2.5.0 (Appendix A's versions), on 2026-10-02:

    python analysis/appendix_a_r_rule.py

Its output is identical (`diff`) to that of the original `rrule2.py`, run the same day from a
copy of the scratch files (5 min 30 s of real time on 11 worker processes):

    chi2 ppf 0.20, 0.10 at 15 df: 10.306959006625288 8.546756241704546
    factors 80%, 90%: 1.2063695181246945 1.3247836837155618
    sigma=0.01 oracle: R11=0.614 R15=0.909 R18=0.991 R22=0.996 R25=1.000 R28=1.000 R31=1.000
      pilot 0 sd=0.0084 | conf 0.80: R=15 true power=0.909 | conf 0.90: R=18 true power=0.991
      pilot 1 sd=0.0103 | conf 0.80: R=25 true power=1.000 | conf 0.90: R=28 true power=1.000
      pilot 2 sd=0.0110 | conf 0.80: R=18 true power=0.991 | conf 0.90: R=22 true power=0.996
      pilot 3 sd=0.0077 | conf 0.80: R=11 true power=0.614 | conf 0.90: R=15 true power=0.909
      pilot 4 sd=0.0117 | conf 0.80: R=22 true power=0.996 | conf 0.90: R=25 true power=1.000
      pilot 5 sd=0.0133 | conf 0.80: R=28 true power=1.000 | conf 0.90: R=None true power=nan
      pilot 6 sd=0.0103 | conf 0.80: R=18 true power=0.991 | conf 0.90: R=22 true power=0.996
      pilot 7 sd=0.0094 | conf 0.80: R=15 true power=0.909 | conf 0.90: R=18 true power=0.991
    sigma=0.0125 oracle: R11=0.296 R15=0.645 R18=0.849 R22=0.936 R25=0.978 R28=0.996 R31=0.999
      pilot 0 sd=0.0109 | conf 0.80: R=22 true power=0.936 | conf 0.90: R=25 true power=0.978
      pilot 1 sd=0.0158 | conf 0.80: R=None true power=nan | conf 0.90: R=None true power=nan
      pilot 2 sd=0.0161 | conf 0.80: R=None true power=nan | conf 0.90: R=None true power=nan
      pilot 3 sd=0.0091 | conf 0.80: R=18 true power=0.849 | conf 0.90: R=18 true power=0.849
      pilot 4 sd=0.0130 | conf 0.80: R=28 true power=0.996 | conf 0.90: R=None true power=nan
      pilot 5 sd=0.0136 | conf 0.80: R=28 true power=0.996 | conf 0.90: R=None true power=nan
      pilot 6 sd=0.0128 | conf 0.80: R=25 true power=0.978 | conf 0.90: R=28 true power=0.996
      pilot 7 sd=0.0121 | conf 0.80: R=25 true power=0.978 | conf 0.90: R=28 true power=0.996
    sigma=0.015 oracle: R11=0.109 R15=0.353 R18=0.583 R22=0.732 R25=0.857 R28=0.927 R31=0.966
      pilot 0 sd=0.0126 | conf 0.80: R=25 true power=0.857 | conf 0.90: R=31 true power=0.966
      pilot 1 sd=0.0130 | conf 0.80: R=25 true power=0.857 | conf 0.90: R=28 true power=0.927
      pilot 2 sd=0.0115 | conf 0.80: R=22 true power=0.732 | conf 0.90: R=28 true power=0.927
      pilot 3 sd=0.0144 | conf 0.80: R=None true power=nan | conf 0.90: R=None true power=nan
      pilot 4 sd=0.0114 | conf 0.80: R=22 true power=0.732 | conf 0.90: R=25 true power=0.857
      pilot 5 sd=0.0142 | conf 0.80: R=28 true power=0.927 | conf 0.90: R=31 true power=0.966
      pilot 6 sd=0.0118 | conf 0.80: R=25 true power=0.857 | conf 0.90: R=28 true power=0.927
      pilot 7 sd=0.0144 | conf 0.80: R=None true power=nan | conf 0.90: R=None true power=nan

Against Appendix A:
- The three "oracle" lines are its true-power table, digit for digit.
- At the 80% bound, over the 24 pilots, the chosen R has true power of at least 0.80 in 17
  pilots. It is below that in 3: 0.614 at sd 0.0077, and 0.732 at sd 0.0115 and 0.0114. Four
  cells are not resolved, though their true power at R = 31 is 0.999 (twice) and 0.966 (twice).
- At the 90% bound, 7 cells are not resolved, and no chosen R is below 0.80.
- The first two lines agree with section 4.6: q = 10.307 and s_U = 1.2064 s.

Appendix A now names the script (a2ba3e6), with a line in the proposal's revision log.

### K_SRC: deferred to M3

The frozen rule (section 9.1) sets `K_SRC` "so that no connect fails in the development runs".
That needs `opgen`, with `IP_BIND_ADDRESS_NO_PORT` and one fresh block of 127.0.0.0/8 per window
(section 2.4), run at each cost cell's highest connection rate. Neither exists before M3, and
neither hypotheses.md nor the proposal gives a value or a formula that would set it earlier.
So it is set in M3 and recorded in the revision log of hypotheses.md by the code freeze.

The rule will use these values, read on L on 2026-10-02:
- `net.ipv4.ip_local_port_range` 32768 to 60999;
- `net.ipv4.tcp_tw_reuse` 2 and `tcp_tw_reuse_delay` 1000;
- `net.ipv4.tcp_max_tw_buckets` 65536 and `net.ipv4.ip_local_reserved_ports` empty;
- `net.core.somaxconn` 4096;
- `RLIMIT_NOFILE` soft 1024 and hard 524288;
- TIME-WAIT lasts 60 s (`TCP_TIMEWAIT_LEN`, section 7);
- a window is 1 s of warm-up and 5 s measured (section 4.1).

No candidate value is proposed here.

### L inventory, read-only, 2026-10-02T19:28+03:00

Read over `ssh alex@192.168.1.62` by a bash script on stdin. Nothing was installed and no
pacman command changed the system: only `pacman -Q` queries ran. No `sudo` was used.

| Item | As read |
|---|---|
| Host | `alex-laptop`, AMD Ryzen 7 5800H, 16 CPUs, 2 threads per core |
| Kernel | 7.2.3-arch1-2, `#1 SMP PREEMPT_DYNAMIC Thu, 03 Sep 2026 17:55:06 +0000` |
| clang | 22.1.8 (`/usr/bin/clang`, `clang++`, `clang-22`) |
| gcc | GCC 16.2.1 20260810 |
| CMake, Ninja | 4.4.3; 1.13.2 |
| liburing headers | `/usr/include/liburing.h`, `IO_URING_VERSION` 2.15, package liburing 2.15-1. The design does not use liburing (I2). `linux-api-headers` 7.2-1. |
| OpenSSL headers | 3.6.4, "OpenSSL 3.6.4 25 Aug 2026", package openssl 3.6.4-1 |
| nghttp2 | `NGHTTP2_VERSION` "1.70.0"; libnghttp2 1.70.0-1, nghttp2 1.70.0-2 |
| perl, make, NASM | perl v5.42.2 (5.42.2-2); GNU Make 4.4.1; NASM: not installed |
| perf, strace, ss | perf 7.2.6-1 (`/usr/local/bin/perf`); strace 7.2; ss from iproute2-7.2.0; `nstat` present |
| Go | go1.27.1 (`go version go1.27.1-X:nodwarf5 linux/amd64`, package go 2:1.27.1-1) |
| Rust | cargo 1.98.1 (797e8a9bc 2026-08-05), rustc 1.98.1 (48a229cea 2026-09-01), package rust 1:1.98.1-1; no rustup |
| JDK | OpenJDK 26.0.2.1 (2026-08-18), package jdk-openjdk 26.0.2.1.u1-1, the default `java-26-openjdk` |
| Python | 3.14.7, numpy 2.5.3, scipy 1.18.1 |
| Free disk in `~` | `/home` 442G, 340G available (364795531264 bytes) |
| `skbuff_fclone_cache` | still a link to `:0000512`; the names linked to it are `skbuff_fclone_cache`, `sgpool-16` and `pool_workqueue`, as WL7 read them. `skbuff_head_cache` and `skbuff_small_head` are directories, not merged. The `aliases` file needs root and was not read. Page size 4096. |
| `~/opt` | `libcxx-msan`, `libcxx-msan-gcc` (with `include/c++/v1` and `lib`), `liburing-msan`, `quic` |
| `~/lab/p3` | absent before M0 |

What each later milestone lacks on L:
- **M1:** nothing. clang 22.1.8, CMake, Ninja, Python 3, and the MSan libc++ at
  `~/opt/libcxx-msan-gcc` are present.
- **M2:** OpenSSL from the 3.5 LTS series, built from its pinned source into `~/opt` (the system
  has 3.6.4, not the design's series). nghttp2 v1.70.0 built from its pinned source, because
  proposal Z3 builds it with each record's sanitizer flags; the system's 1.70.0 does not serve
  the sanitizer builds. NASM is absent; the design names it only for W's MSVC build of OpenSSL
  (I23, LB3).
- **M3:** nothing beyond M1; `ss`, `nstat` and `perf` are present.
- **M4:** the competitors (nginx, HAProxy, Envoy, caddy-l4 with xcaddy, sslh-ev) were not
  inventoried. The JDK installed is 26.0.2.1; whether that is the latest LTS is still open
  (proposal, "Not verified"). go1.27.1 matches the frozen version. Rust 1.98.1 is present for the
  hyper-util harness.

### Build check on L

Bare repo `~/lab/p3/one-port.git`, work tree `~/lab/p3/one-port` (a clone of it), build trees
`~/lab/p3/build-debug` and `~/lab/p3/build-asan`, logs in `~/lab/p3/m0-check/`. Nothing used
`~/lab/Papers`. Every P2 pid file under `~/lab/p2` named a dead process, and the load was 0.11,
before the first build.

At commit 45023e9, clang 22.1.8, generator Ninja:

| Build | CMake | Build | CTest | Report lines |
|---|---|---|---|---|
| Debug | `-DCMAKE_BUILD_TYPE=Debug` | exit 0, 0 warnings | 38 of 38 passed | 0 |
| ASan+UBSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address+undefined` | exit 0, 0 warnings | 38 of 38 passed | 0 |

The ASan run used `ASAN_OPTIONS=detect_leaks=1:detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1`
and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`. "Report lines" counts the lines of
`ctest -V` that match the shared report pattern. These are checks, not sanitizer records; the
first records come in M1. Log sha256:

    f744c9914a5d21fdcbda84ea7f0cb4fac468c62a8d382a4e5844fcc221bc6fe5  asan-45023e9.build.log
    62c19c7a8524261601f5b97dd045ddada73d56be53cd4a439554c8afeafdfa39  asan-45023e9.ctest.log
    a9f9b69c97f5060f0b32e37a962e3ccae5fdfeca5a5ce4ca7b5e1a3370f2436a  debug-45023e9.build.log
    7f187d123c83c9b65508c1724a107fc5ff9e000577f9ece78be3664085292da8  debug-45023e9.ctest.log

Also on W, unasked, as a compile check before M6: a Debug build with MSVC 19.51.36246.0 (Build
Tools 18.6.2, Ninja) at 45023e9 had no warnings, and 29 of 29 CTest entries passed (14 flags,
9 `loop.IOCP`, 4 cli, 2 gate).

## Follow-ups outside this repository

- `lab/bin/test_report_pattern.sh` lists the record writers by path. Add
  `papers/one-port/bench/oneport_record.py` to it. Until then, `bench/test_record_writers.py`
  checks the writer's pattern against the script's `want`.
- The Papers repo's submodule pointer for `papers/one-port` (the coordinator's commit).

## What M1 starts from

- The loop: `start()`, `wait(bound)` and `stop()` on epoll and io_uring. M1 adds socket
  registration and event dispatch on epoll, the deadline queue (I13), the check of section 1(b),
  and the counters (section 2.1).
- The flags: `oneport::Config` and its parser. M1 adds the listener setup, the only reader of
  `Config::mode`, with the structural test of I21, and replaces the "not implemented in M0" exit
  for `--mode one-port` and `dedicated` with `--backend epoll` and `--dispatch inproc`.
- The sanitizer driver, `bench/sanitize_oneport.sh`, after P2's `t1/sanitize_h6.sh` and
  `bench/keep_record_logs.sh`. It runs `lab/bin/inputs_hash.py` in project mode (build name
  `oneport`, with config keys for the code-selecting options) and writes
  `oneport-<commit>-L-{asan,tsan,msan}.json` with `bench/oneport_record.py`, keeping its logs
  under `~/lab/records-logs/`. M1 makes the first records.
- The 25 hard cases of Appendix A of hypotheses.md as a deterministic CTest suite, run under every
  sanitizer.
- On L: the work tree `~/lab/p3/one-port` and the `lab` remote; push, then
  `git -C ~/lab/p3/one-port pull --ff-only`.
