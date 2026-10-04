# P3 engineering status

The state of the engineering phase (hypotheses.md, section 8, step 2). Started 2026-10-02 with
M0. Nothing in this file is a result: builds and tests here are not measurements, and no window
has run.

## Milestones

| Id | Milestone | State |
|---|---|---|
| M0 | Foundations | done, 2026-10-02 (below) |
| M1 | epoll server with the detection table, the HTTP/1.1 handler and the 25-case generator as a deterministic test suite under every sanitizer | done, 2026-10-02 (below) |
| M2a | h2c, TLS, PROXY, SSH, MQTT and SMTP handlers on epoll in-process; the pinned OpenSSL and nghttp2; the recorded ClientHello; every hard case full on epoll in-process | done, 2026-10-02 (below) |
| M2b | relay mode and stub mode, the pass-through ClientHello routing, and io_uring | done, 2026-10-02 (below) |
| M3 | Harness and A/A-noise engineering, in dedicated mode only | done, 2026-10-03 (below) |
| M4 | Competitors | M4a (the five proxies, the hand-off runner, step 0's host change and NOTRACK) done, 2026-10-03 (below); M4b-1 and M4b-2 (the cases configurations, the libraries' harnesses) done, 2026-10-03 (below) |
| M5 | Iterate until it wins | done, 2026-10-03, two rounds (below): criteria 1, 3 and 5 met; 2 met against four proxies, not against sslh-ev (out of reach by construction); 4 met at the end |
| M6 | Windows | M6a (the dependencies and the IOCP backend) done, 2026-10-03, merged into main in bbd13f7 (below); M6b (the Windows harness) merged into main at its 74dc539 in fa8be6d, 2026-10-04 (below, "M7c follow-up"; `design/status-m6b.md`); W's runners open |
| M7 | Code freeze | preparation done, 2026-10-03 (below: the route without ALPN, M5's readings 1 and 5 logged, the records drivers and their dry run, the M7 checklist); the coordinator's five fixes done, 2026-10-03 (below, "M7 fixes"); the frozen runners done, 2026-10-03 (below, "M7c"); M7c's follow-up done, 2026-10-04 (below: the merge of `m6b-windows`, M7c's open items logged, `ANALYSIS_COMMIT`); M7d and M7e done, 2026-10-04; the freeze session stopped in W's checks, 2026-10-04 (below, "M7 freeze session": a test fix, 7a4063c; W in use); the code freeze declared, 2026-10-05: CODE_FREEZE = ff2679c (below, "M7 freeze night") |

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

## M1, 2026-10-02

### Commits (papers/one-port)

| Commit | Message |
|---|---|
| 6b0cb58 | feat: the detection table, pure and constexpr, checked at compile time over its corpus |
| f01ab4a | test: the detection table at run time, at every split, and the PROXY parser |
| e9ef952 | feat: the HTTP/1.1 handler's parser, with the detector's grammar in both modes |
| 51f64a7 | feat: the epoll loop registers sockets and returns each wait's events |
| 6a1016a | feat: oneport serves on epoll: detection, timers, in-process dispatch and the handlers |
| 35f4ffa | feat: opcase, the case generator: the 25 hard cases as scripts with their frozen outcomes |
| 1521c10 | test: the hard-case suite (B1, B2) and the server's functional tests on epoll |

This file is committed after them, then 857fa60 (test: the structural test of I21 checks its own
pattern before it scans) and an amendment of this file. Each of the seven commits builds alone on L (Debug, clang 22.1.8, Ninja)
with no warning and passes its own suite (38, 49, 54, 54, 57, 57 and 275 CTest entries); the
logs are in `~/lab/p3/m1-check/commits/<sha>/`. Nothing is pushed to origin; the `lab` remote has
every commit.

### What M1 built

**The detection table** (`bench/server/detect.hpp`, `detect_corpus.hpp`). Pure and free of I/O.
- The five matchers of hypotheses.md section 1, in the frozen order (TLS, h2c, HTTP/1.1, SSH,
  MQTT). Each is a `constexpr` function over the bytes received so far. It returns yes (with
  its decision length), no (with the byte that ruled it out) or more (with the fewest bytes in
  all with which it could still say yes).
- The first-byte sets are derived from the matchers, and a `static_assert` checks them against
  the frozen table. The 256-entry bucket array puts the smaller `need` first.
- `classify()` checks the empty candidate set, then runs the candidates until one says yes.
- The PROXY v1 and v2 parser of I9, strict. A v2 header is checked at 16 bytes with its first 13
  matching, a v1 line at 8 bytes with its first 5 equal to "PROXY". A prefix that cannot match
  closes the connection. A v2 header longer than 536 bytes is rejected at its length field, and
  a v1 line longer than 107 bytes is rejected.
- The checks of proposal I7 are `static_assert`s over a corpus built from the specifications'
  shapes:
  - each sample is accepted by its own matcher within its `need`;
  - no matcher accepts any prefix of another protocol's sample;
  - the bucket order and its reverse give the same decision on every prefix;
  - every `need` maximum is at most B_dec;
  - HC16's derivation holds;
  - the PROXY samples parse as expected.
- They also build under MSVC.

**The HTTP/1.1 parser** (`bench/server/http1.hpp`). It returns I26's fixed 200. In both modes the
request line first runs the table's HTTP/1.1 matcher. So two CRLFs, an unlisted method or a
second SP close without a response in dedicated mode as in one-port mode. Other malformed
requests get 400.

**The server** (`bench/server/`):
- Files:
  - `server.cpp`: the sockets and `Server`;
  - `worker.hpp`, `worker.cpp`: connection state, the pass, accept, the PROXY header, detection
    and timers;
  - `handlers.cpp`: the handlers, output and connection lifecycle;
  - `counters.cpp`;
  - `listeners.cpp`: the only reader of `Config::mode` besides the parser.
- Workers and listeners. One epoll worker per thread. Sockets are edge-triggered with
  EPOLLRDHUP in both modes. The listener is shared by all workers through EPOLLEXCLUSIVE, or a
  SO_REUSEPORT group gives one socket per worker.
- Replay mode reads into the handler's buffer, taken on the first readiness.
- Peek mode copies at most B_dec bytes with `MSG_PEEK` into a per-worker scratch buffer. When the
  table is undecided, it sets `SO_RCVLOWAT` to the matcher's `more` total, and resets it to 1
  before the handler reads.
- On a PROXY listener the header comes first. Peek mode consumes it with an exact `recv`; replay
  mode and dedicated listeners skip it in the buffer.
- Timers (I13). One FIFO deadline list per listener and timer (T_hdr, T_fb, T_dec). A pass:
  - waits with `epoll_pwait2` until the earliest deadline;
  - re-reads the clock;
  - handles all readiness events;
  - then handles every expiry at or before that reading.
  T_hdr starts at accept. T_fb and T_dec start at accept, or when the PROXY header is complete.
- The check of 1(b) is a one-byte `MSG_PEEK | MSG_DONTWAIT` receive before each fallback
  dispatch. A byte wins, and the bytes decide the connection in that pass.
- Outcomes (a) to (h) are counted per class. The counters of I29 are per worker, without atomics,
  and each timed event's deadline, wait return, previous wait return and pass are recorded
  (`Counters::timed`). The binary prints them at SIGTERM.
- Handlers:
  - HTTP/1.1: the real handler of I26, with keep-alive, pipelining and `Connection: close`;
  - h2c, TLS, MQTT, SSH and SMTP: clearly marked M1 stubs (below), which M2 replaces.
- `--backend io_uring`, `--dispatch relay` and `--mode stub` exit 3 with "not served in M1"; on W,
  IOCP does the same.
- The connection state is 400 bytes (`sizeof`, L, clang 22.1.8). The binary prints it at start
  (I15).

**opcase** (`bench/cases/`), named as hypotheses.md section 2.4 names it. In M1 it is a library
that the suite runs in-process.
- Each of the 25 hard cases of Appendix A expands into variants, 164 in all. Each variant is a
  script of writes and gaps, sent with `TCP_NODELAY` and one write per chunk.
- Write times are recorded on CLOCK_MONOTONIC, the server's clock.
- Each variant carries its frozen expected outcome: the class or end, what ends it (at once,
  T_fb, T_dec, T_hdr), the reply, and where frozen the deciding byte, the PROXY source and the
  rejection reason.
- The ClientHello is built from RFC 8446's structure. The recorded one of I18 is M2's.

**The suite** (`tests/`):
- `tests/case_tests.cpp` runs every variant 16 times against a one-port server, once per
  detection mode. It checks B1 and B2 on each run.
  - The outcome and class are checked.
  - The transcript must equal the same script's transcript against the dedicated port of the
    expected class (I20, Z2).
  - B2(a) and (b) are checked exactly from the server's record: prev_wait_return < deadline <=
    wait_return <= handled_at, and deadline = start + T.
  - B2(c): the classification happens in the pass of the receive or peek that brought its byte.
  - B2(d): the payload held in user space while pending is at most the handler's buffer in
    replay and none in peek, and no data buffer is held while no byte has arrived.
  - B2(e): a half-close closes in the pass that observed it.
  - Each timer is also checked from below on the client's clock. The client takes its reference
    time before connect, so it is no later than the server's accept.
- `tests/server_tests.cpp` covers the server's functions:
  - keep-alive and pipelining in both modes;
  - the six dedicated ports;
  - T_hdr on a dedicated PROXY port (the pilot timer part's path);
  - the `SO_RCVLOWAT` drip: peek wakes exactly twice, and replay wakes on the drips (at least
    three times);
  - the kernel behaviour peek rests on, pinned on L's kernel. With edge-triggered epoll, setting
    the mark at or below the queued bytes raises an event, a mark above them raises none, data
    below the mark raises none, reaching the mark raises one, and a half-close is reported above
    the mark;
  - the check of 1(b) with a byte that arrives in the pass of the expiry, through a hook between
    a pass's events and its expiries, in both modes: the byte won, check_found_byte 1, no
    fallback;
  - two workers on the shared listener and on SO_REUSEPORT, in both modes, 200 connections each;
  - all 96 flag combinations M1 serves;
  - a stop with a pending connection;
  - the binary itself: start, an HTTP/1.1 exchange, SIGTERM, exit 0 and its counters.
- `tests/check_mode_readers.cmake` is the structural test of I21.

### Flag combinations after M1

- Served, and run by `server.flag_matrix` (all 96, each with an HTTP/1.1 exchange, the fallback
  of a silent client where one is named, and the SMTP port in dedicated mode):
  - `--mode` one-port or dedicated;
  - `--detect` replay or peek;
  - `--dispatch inproc --backend epoll`;
  - `--proxy` off or on;
  - `--fallback` none, SMTP or SSH;
  - `--listener` shared or reuseport;
  - `--workers` 1 or 2.
- The timer flags take the suite's values. `--iocp-receive` and `--relay-copy` are accepted and
  have no effect on epoll with in-process dispatch, so the matrix does not vary them.
- Refused with exit 3 (the `cli.not_served_*` tests): io_uring (M2), relay (M2), stub mode (M2);
  IOCP (M6, on W).

### Design choices of M1

Every number here is a design choice of M1, not a frozen value.

| Name | Value | Where | Reason |
|---|---|---|---|
| Receive buffer (I27) | 4096 bytes, every handler | `server.hpp` `kRecvBuf` | one page on L (read 2026-10-02); holds HC23's 4,096 bytes in one read. One size for all handlers, since replay reads before the class is known |
| Events per wait | 64 | `loop.hpp` `kMaxEvents` | WL1's 64 connection slots per server core |
| Peek window, PROXY stage | 560 bytes | `detect.hpp` `kPeekWindow` | the longest v2 header (536) and B_dec (24), so one peek covers the header and the table; derived from frozen constants |
| Trigger mode | edge-triggered, EPOLLRDHUP | `worker.cpp` | I11 leaves it to engineering; the M1 brief fixes it. A short read counts as drained; after a half-close the read goes on to EOF |
| Low-water mark | the fewest bytes in all with which some candidate could still say yes | `detect.hpp` | see reading 1 below |
| Outcome names beyond the frozen ones | `rejected_budget`, `proxy_rejected`, `proxy_timeout`, `reset`, `stopped` | `server.hpp` | ends the frozen text does not name |
| 400 response | `HTTP/1.1 400 Bad Request`, `Content-Length: 0`, `Connection: close`, then close | `http1.hpp` | I26 names the status, not its bytes |
| HTTP/1.1 parser | the request-target is visible ASCII; the version is `HTTP/1.1` or `HTTP/1.0`, case-sensitive; header lines are name ":" OWS value OWS CRLF, without folding; HTTP/1.1 needs exactly one Host; no body (any Content-Length other than 0, or any Transfer-Encoding, gets 400); HTTP/1.0 closes after the response; a request that does not fit in the buffer gets 400 | `http1.hpp` | minimal, and the same in both modes |
| M1 stub handlers | at entry, `oneport M1 stub <class>` and CRLF; at the client's EOF, `oneport M1 stub <class> received <n> bytes fnv1a64 <16 hex digits>` and CRLF; then close | `handlers.cpp` | lets the client see that the handler got every byte from the first, in replay and in peek. Replaced in M2 |
| Listening address | 127.0.0.1 | `server.cpp` | loopback only |
| Ports without `--port` | the first free run of consecutive ports, at most 100 tries | `server.cpp` | a test convenience |

The suite's stand-ins and parameters, not the frozen values:

| Name | Value | Reason |
|---|---|---|
| T_fb, T_dec, T_hdr | 300 ms | "short test timeouts" (section 11); the frozen value is 3 s |
| GAP_SPLIT stand-in | 10 ms | HC2, HC10, HC20; the pilot sets GAP_SPLIT (9.2) |
| G stand-in | 100 ms | HC7; the pilot sets G_L and G_W (9.2) |
| Drip gap (HC3) | 5 ms | 24 bytes take 120 ms, inside T_dec |
| Slow drip (HC4) | the first d - 1 bytes of the sample, d its decision length, one per write, spread over 2 × T_dec | still incomplete at T_dec |
| HC24 Remaining Lengths | 12, 128, 16,384 and 2,097,152 | HC1's CONNECT, then the smallest values that need 2, 3 and 4 bytes |
| HC14 headers | ALPN and AUTHORITY TLVs; 536 bytes in all; 537 bytes | at most 536, and one longer |
| Replicates | 16 | the frozen count (B1) |
| Server tests | flag matrix timers 100 ms; peek drip gaps 30 ms; T_hdr 200 ms in the dedicated PROXY test; 8 threads × 25 connections per two-worker test | functional, untimed |

### The suite on L at 1521c10

275 CTest entries: 125 run and pass, 150 are skipped as pending, and none fails.

| Group | Entries | Result |
|---|---|---|
| `flags.*` | 14 | pass |
| `loop.{epoll,io_uring}.*` | 18 | pass |
| `detect.*`, `http.*` | 11, 5 | pass |
| `structure.mode_readers` | 1 | pass |
| `server.*` | 18 | pass |
| `case.HCnn.epoll.inproc.{replay,peek}` | 50 | pass |
| `cli.*` | 6 | pass |
| `gate.*` | 2 | pass |
| `case.HCnn.epoll.relay.*` | 50 | pending M2: relay dispatch |
| `case.HCnn.io_uring.{inproc,relay}.*` | 100 | pending M2: the io_uring backend |

The hard cases on epoll with in-process dispatch, per detection mode (the same in replay and
peek): 164 variants, each run 16 times. 97 pass in full, 66 pass with an M1 stub handler, 1
passes in part, and none fails. Labels: `full`, `stub`, `partial`.

| Case | Variants | M1 checks | Pending |
|---|---|---|---|
| HC1 | 6 | HTTP/1.1 in full. h2c, TLS, MQTT 3.1.1, MQTT 5.0 and SSH: classified, transcript equal to the dedicated port's (an M1 stub's) | the exchanges (nghttp2, OpenSSL, CONNACK, the SSH line): M2 |
| HC2 | 62 | as HC1, every k from 1 to the matcher's largest need minus 1 | as HC1; GAP_SPLIT is a stand-in |
| HC3 | 6 | as HC1 | as HC1 |
| HC4 | 6 | full: undecided at T_dec | |
| HC5 | 1 | fallback at T_fb; the transcript equals the dedicated SMTP port's (an M1 stub's) | the SMTP exchange (220, 250, 221): M2 |
| HC6 | 1 | full: silent at T_dec | |
| HC7 | 2 | twin: full, HTTP/1.1. Late: fallback at T_fb, transcript equal to the dedicated SMTP port's | the 500 from the SMTP handler: M2; G is a stand-in |
| HC8 | 1 | full: rejected at byte 1 | |
| HC9 | 1 | full: the source recorded is the header's; 200 | |
| HC10 | 27 | full, every k inside the 28-byte header | GAP_SPLIT is a stand-in |
| HC11 | 1 | full: closed at once (the PROXY prefix) | |
| HC12 | 1 | full: closed at T_hdr | |
| HC13 | 1 | full: TLS | |
| HC14 | 3 | full: MQTT after TLVs and after a 536-byte header; 537 bytes rejected at the length field | |
| HC15 | 1 | fallback at T_fb after the header completed (client-side bound from the header's write) | the greeting is the SMTP handler's 220: M2 |
| HC16 | 24 | full: rejected at byte k + 1 | |
| HC17 | 2 | full, in one-port and in dedicated mode | |
| HC18 | 1 | full: SSH | |
| HC19 | 2 | full: TLS | |
| HC20 | 1 | partial: classified TLS from the first record | the handshake (TLS termination) and the SNI routing (relay): M2 |
| HC21 | 4 | full: undecided and silent at once, also on a fallback listener | |
| HC22 | 2 | full: reset; state freed and counters consistent after the entry | |
| HC23 | 2 | full: rejected at bytes 4 and 1, no budget exceeded; closed without a response in dedicated mode | |
| HC24 | 5 | full: MQTT for the four Remaining Lengths, MQIsdp rejected | |
| HC25 | 1 | full: HTTP/1.1, 400, in both modes | |

After each entry the servers are stopped and checked:
- every accepted connection was closed, and no connection or buffer is left;
- every one-port connection had exactly one outcome;
- no budget was exceeded;
- every timed event meets B2(a) and (b).

### Sanitizer checks on L (development checks, not records)

Work tree `~/lab/p3/one-port` at 1521c10, clang 22.1.8, Ninja; build trees and logs in
`~/lab/p3/m1-check/`; `ctest -V -j 8`. "Report lines" counts the lines of the ctest log that
match the shared report pattern.

| Build | CMake | Build | CTest | Report lines |
|---|---|---|---|---|
| Debug | `-DCMAKE_BUILD_TYPE=Debug` | 0 warnings | 125 passed, 150 skipped, 0 failed | 0 |
| ASan+UBSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address+undefined` | 0 warnings | the same | 0 |
| TSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=thread` | 0 warnings | the same | 0 |
| MSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=memory`, the libc++ 22.1.8 at `~/opt/libcxx-msan-gcc` | 0 warnings | the same | 0 |

- Options:
  - ASan runs with M0's `ASAN_OPTIONS` and `UBSAN_OPTIONS`;
  - TSan and MSan use the runtime defaults, as `lab/bin/sanitize.sh` does.
- Each run takes about 30 s; the timers dominate.
- Instrumentation, as checked:
  - the test binary of each build defines the runtime's symbols (`nm`: 324 `__asan_`, 173
    `__tsan_`, 64 `__msan_`);
  - the MSan binaries load `libc++` and `libc++abi` from `~/opt/libcxx-msan-gcc/lib`.
- TSan runs the two-worker tests on the shared listener and on SO_REUSEPORT.
- A stress run of the same four builds at the same time, each with `ctest -V -j 16` (64 tests on
  16 CPUs), also passed with 0 report lines (`stress-*-1521c10.ctest.log`).

Log sha256:

    1c91c2e88059778289326bbb0305e51bc7db4abe817e3a41a4fe184836b8cb45  debug-1521c10.build.log
    f366abe0801c2ab49cfead531ba64833496ca8e3738d26f5e7b7290958e983e5  debug-1521c10.ctest.log
    2a12d0ec600f73257aad78ea0e27034490f7b5b893e8e508452bc309cc81617a  asan-1521c10.build.log
    b6f1aea5cd2d3f0c0771915c7a139d8d8836c47609bf775216f8a430c159cc7c  asan-1521c10.ctest.log
    a7dc7804f09c2c8738df69803322ebcf99d948ce582c1d684bf406fa1eccd24d  tsan-1521c10.build.log
    ceb6ee361ad3e6bce14f6d8a00a2ae196182769a3b66f066e67072a55e32d13d  tsan-1521c10.ctest.log
    753ce0e313291a2707ee6e6c2216996faa73c2ac073237d5367a578f198b25d8  msan-1521c10.build.log
    e2d1fd234156d75871cfd55b9e0c5f15595956c10d408b681570aa0cfe81988a  msan-1521c10.ctest.log
    9840fa4c62536bd58f84bfa31e62811334cf6740061b3c71be37a8940a1bdafa  stress-debug-1521c10.ctest.log
    ec34d58b946e686f623c51a308d8fa31f6ec27b0fb718cdc5b41c6b384f1f08b  stress-asan-1521c10.ctest.log
    cd0d4064988b92358963bf5f4927960456988c1ea7c9d466ac2dbffbed9a7ffb  stress-tsan-1521c10.ctest.log
    48ab204b5695a0e1e49a71c91950a59885312060aa6d3ba5b1094a79cadd18d9  stress-msan-1521c10.ctest.log

Also on W, as a compile check before M6 (as in M0):
- a Debug build with MSVC 19.51.36246.0 (Build Tools 18.6.2, Ninja), out of tree in a scratch
  directory, of 857fa60, built with no warning, so
  the compile-time checks of the table also hold under MSVC;
- 96 CTest entries: 46 passed (14 flags, 9 `loop.IOCP`, 16 pure, 1 structure, 4 cli, 2 gate),
  and 50 IOCP case entries were skipped as pending M6.

The structural test checks its own pattern. Before scanning, `tests/check_mode_readers.cmake`
runs its reader pattern on three lines it must match and five it must not, so a pattern that
CMake's regex engine reads otherwise cannot pass with nothing found. Checked by hand once: a copy
of `bench/` with a planted `config.mode` read in `handlers.cpp` fails it. After that commit,
`structure.mode_readers` passed again in the four build trees on L.

### Where the frozen text was read one way

Each item may need a revision-log entry of hypotheses.md. The frozen text is not edited.

1. "The number of bytes still needed" (proposal I6) and the low-water mark of peek mode (I11):
   - Read as: the fewest bytes in all with which some remaining candidate could still say yes.
   - So in peek mode, an impossible byte that leaves the queue below the mark is not "delivered"
     (section 1: observed by the loop) until the mark is met, the peer shuts down, or T_dec.
   - A connection that sends "P" and later "X" is then closed at T_dec as undecided (1 d), where
     replay rejects it when "X" arrives (1 e).
   - No hard case does this: HC16 and HC23 are single writes.
2. T_dec on a silent connection of a fallback listener does not close it; T_fb decides, since
   1(a) says such a connection is "never closed or routed elsewhere instead". With the frozen
   T_fb = T_dec the two fall due together and T_fb is handled first, so this matters only when
   T_dec < T_fb.
3. HC2's "every k from 1 to the matcher's need minus 1", for the matchers whose need varies
   (HTTP/1.1 at most 10, MQTT 9 to 12): k runs to the largest need minus 1. Splits after the
   sample's decision point are therefore included. HC3 drips the first largest-need bytes.
4. HC4's "slow drip": the first d - 1 bytes of the signature, spread over 2 × T_dec, so that the
   drip is still running at T_dec.
5. HC7's "written at T_fb + G" and "at T_fb - G", on a clock the client shares with the server:
   - the late write is at the client's connect return + T_fb + G;
   - the twin is at the client's time just before connect + T_fb - G;
   - so each lies at least G from the server's deadline, whatever the accept delay.
6. HC10's "split after every byte k inside it, then HTTP/1.1": two writes, the header's first k
   bytes, then the rest of the header with the request.
7. TLS "a record length of at most 2^14" is read literally: a length of 0 is accepted.
8. MQTT "a Remaining Length of 1 to 4 bytes": only its length is checked, not its value or a
   minimal encoding.
   - HC24's 4-byte case cannot be a well-formed CONNECT, since no payload reaches 2,097,152 bytes.
   - The case sends that Remaining Length with filler after a 65,535-byte client identifier.
   - Its frozen outcome, MQTT, is the classification.
9. HTTP/1.1's "exactly one SP": the matcher decides at the method and its SP, so within its 10
   bytes. The handler closes a second SP without a response, in both modes, as I26 says.
10. PROXY v2's "first 13 matching": the 13th byte matches when its version is 2. A command other
    than LOCAL or PROXY is malformed and closes too.
11. 1(h) on a PROXY listener:
    - a half-close during an incomplete header with bytes is "undecided", and with no byte
      "silent";
    - after a complete header with no application byte it is "silent".
12. "Pending M2" for IOCP: the M1 brief lists IOCP among the pending M2 items, but the milestone
    list above puts Windows in M6. The suite marks IOCP entries "pending M6", and only on W; L
    lists none.
13. HC1, HC2, HC3, HC13, HC18, HC19 and HC24 state an outcome ("classified", "TLS", "SSH",
    "MQTT"). For HC13, HC18, HC19 and HC24, which name only the class, M1 counts the check as
    full. For HC1 to HC3, whose outcome includes the dedicated port's transcript, it counts as
    stub, since that transcript is an M1 stub's.

### Not in M1

- The io_uring backend, relay dispatch, stub mode and IOCP.
- The handlers of h2, TLS, MQTT, SSH and SMTP (M1 stubs stand in), and the recorded ClientHello.
- `opgen` and `ophold`.
- The sanitizer driver and the records: at the code freeze, by the M1 brief.
- K_SRC (M3, as M0 says).
- A per-connection decision record for hard-case runs against a server in its own process
  (WL8's decision time against `opcase`'s write times). In M1 the suite reads it through
  in-process hooks; M3 needs it from the binary.
- Nothing was installed on L or W.

## M2a, 2026-10-02

### Step 0: M1's readings in the revision log

c8a0525 appends one entry to the revision log of `hypotheses.md`, "Readings fixed during
engineering (M1), before the code freeze", with M1's 13 items one line each; nothing above the
log changed (`git diff` showed additions after line 1035 only). Items 1 to 3 say why each follows
from the frozen text. Two notes for the coordinator:
- Item 1 (peek mode's low-water mark) is the reading closest to the line. It changes the counted
  class in a scenario no hard case covers: in peek mode a connection that sends "P" and later an
  impossible byte is closed at T_dec as "undecided", where replay rejects it at once. The entry
  logs it as a reading because section 1 states every fallback rule over delivered bytes
  ("observed by the server's loop"), sets no value for the mark, and gives yes-lengths in its
  "Decides at" column.
- Item 12 reads the M1 brief and the milestone plan, not a frozen rule. The entry includes it so
  that all 13 items are listed, and its line says it reads no frozen rule and changes nothing.
No item was found to contradict the frozen text.

### Commits (papers/one-port)

| Commit | Message |
|---|---|
| c8a0525 | docs: hypotheses.md revision log, the readings fixed during engineering (M1), before the code freeze |
| 6cb621d | build: pin OpenSSL 3.5.9 and nghttp2 1.70.0 (URL and sha256) and the script that builds them per sanitizer flavour |
| f490ffb | feat: the TLS settings of I24 shared by the server and its clients (bench/tls), the labelled test certificate, and the pinned OpenSSL and nghttp2 per sanitizer flavour in CMake |
| c9ff08a | feat: the recorded ClientHello of I18 (captured from OpenSSL 3.5.9 with the settings of I24), its recorder, and the ClientHello reader of pass-through (SNI, ALPN, B_CH) |
| 85b1a6e | fix: OpenSSL's ASan+UBSan flavour leaves -fsanitize=function out of crypto/stack/stack.c alone, where OpenSSL calls typed free functions through OPENSSL_sk_freefunc |
| 45b21eb | chore: build_deps.sh builds one library when ONEPORT_LIBS names it |
| d71ae06 | feat: the handlers of I26 replace the M1 stubs (h2c and h2 on nghttp2, TLS terminated on OpenSSL through the worker's BIO, MQTT, SSH, SMTP); opcase runs a live TLS client and replays the recorded ClientHello; the hard cases on epoll are all full |
| 42c4509 | fix: the OpenSSL ignore list matches the relative path its Makefile compiles crypto/stack/stack.c by |
| 4aa547d | fix: OpenSSL's ASan+UBSan flavour leaves the function check out of all of OpenSSL (a second site, crypto/pem/pem_oth.c, comes from the same header macros); bench/coverage.json declares the gap |
| 4e814f2 | test: opcase's live TLS client writes the recorded ClientHello but for its random, session id and key share |

This file is committed after them. 6cb621d's type, "build", is not in
the list of conventional types this repository uses; it is left as pushed. Each code commit was
built alone on L (Debug, clang 22.1.8, Ninja) from a fresh clone of the `lab` remote and passed
its own suite with no warning: f490ffb 275 CTest entries, c9ff08a 277, d71ae06 293 (logs in
`~/lab/p3/m2a-check/commits/<sha>/`); 4e814f2 is the final code commit, checked below. The other
commits change no compiled file. Nothing is pushed to origin; the `lab` remote has every
commit.

### Pins and the libraries on L

`bench/cmake/pins.cmake` holds each library's version, archive URL and sha256, and
`bench/third_party/build_deps.sh` reads them from there. Both archives were downloaded on L on
2026-10-02, and each computed sha256 equals the value the release publishes beside it.

| Library | Version | URL | sha256 (computed = published) | Published in |
|---|---|---|---|---|
| OpenSSL | 3.5.9 | https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz | 603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a | the release asset `openssl-3.5.9.tar.gz.sha256` |
| nghttp2 | 1.70.0 | https://github.com/nghttp2/nghttp2/releases/download/v1.70.0/nghttp2-1.70.0.tar.xz | e05cb1388eaca3830aded4ccf20044b6e1ac1a61411dcca11b0437c4285c8bc2 | the release asset `checksums.txt` |

- OpenSSL 3.5.9 is the latest release of the 3.5 LTS series on 2026-10-02: the GitHub releases
  API lists openssl-3.5.9 published 2026-09-29T14:10:08Z (the same day as 3.6.5 and 4.0.3), and
  openssl-library.org/source lists `openssl-3.5.9.tar.gz`. The pin is read again at the code
  freeze.
- nghttp2 v1.70.0 is the version hypotheses.md section 2.1 names; the releases API lists it
  published 2026-07-29T12:31:43Z and still the latest on 2026-10-02.
- Nothing was installed through pacman, and no system tool was missing: curl, perl, make, cmake,
  ninja and clang 22.1.8 were present.

Four flavours of each library, one prefix each in `~/opt`, built by build_deps.sh with clang
22.1.8 from a fresh copy of the source under `~/opt/build` (logs `~/opt/build/logs/`). The
exact command lines, from the logs:

| Flavour | OpenSSL: `CC=clang ./Configure linux-x86_64-clang no-shared no-module no-tests no-docs` and | nghttp2: CMake Release, `ENABLE_LIB_ONLY=ON BUILD_SHARED_LIBS=OFF BUILD_STATIC_LIBS=ON ENABLE_DOC=OFF BUILD_TESTING=OFF`, and `CMAKE_C_FLAGS` |
|---|---|---|
| release (Debug and Release builds of oneport) | (nothing more; keeps the `openssl` program) | empty |
| asan (ASan+UBSan) | `no-apps enable-asan enable-ubsan -fsanitize-ignorelist=~/lab/p3/one-port/bench/third_party/openssl-ubsan.ignorelist` | `-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer -g` |
| tsan | `no-apps -fsanitize=thread -fno-omit-frame-pointer -g` | `-fsanitize=thread -fno-omit-frame-pointer -g` |
| msan | `no-apps enable-msan -fsanitize-memory-track-origins=2` | `-fsanitize=memory -fsanitize-memory-track-origins=2 -fno-omit-frame-pointer -g` |

Every flavour also passes `--prefix=~/opt/<lib>-<version>-<flavour>` (OpenSSL with
`--openssldir=<prefix>/ssl --libdir=lib`; nghttp2 with `CMAKE_INSTALL_LIBDIR=lib`). OpenSSL's
TLS features are its defaults in every flavour; `no-apps` selects no feature. Checked after the
builds:
- Instrumentation, by `nm` (undefined runtime symbols): asan flavour libcrypto 9211 `__asan_`
  and 2805 `__ubsan_`, libssl 1274 and 313, libnghttp2 269 and 78; tsan flavour libcrypto 7145
  `__tsan_`, libssl 919, libnghttp2 199; msan flavour libcrypto 4766 `__msan_`, libssl 666,
  libnghttp2 121; the release flavour none.
- Assembly: `OPENSSL_NO_ASM` is defined only in the msan flavour's `configuration.h`
  (`enable-msan` turns it off, Configure line 707 at 3.5.9); the other three hold the assembly
  (for example 31 `aesni_` and `x25519_fe64` functions in libcrypto).
- `CMakeLists.txt` picks the flavour from `ONEPORT_SANITIZER` and links the static libraries;
  the prefixes used are kept in the cache as `ONEPORT_OPENSSL_USED` and `ONEPORT_NGHTTP2_USED`,
  for the record driver's found keys at M7. On W the libraries are not looked for (M6).

Library sha256 (`~/opt`, as linked by the checks below):

| Flavour | libssl.a | libcrypto.a | libnghttp2.a |
|---|---|---|---|
| release | d0676fd432ddb5c7f19b377b8d1f40b01d902c6372ebe74a892e1f2e35eeda4c | 1933fff02e159bdb8b666a22e999aea491d43b42daa725e61320c3759996af32 | 3be408486f87b0ed4dd93a6671ae8b286e0c7d2c3318dadf28db6e9614248cb1 |
| asan | 42bf1f1164eef2f9fa546c6b34f4f4cef9379b4077c26c69c957c201a3dd8ff4 | a40abfbccc9d0d9d84640ec7f67e462f882c7439074845859b964cd30ed017c3 | 9f941941e1355d23bd3f6b95c1af2d40c8ddbb90d41a5a28e476484ced20cf64 |
| tsan | 7056c9578045ab77a59eac4d3a2dba0956aa596dd27e0f165c1f4de7617d30af | 60243f0df08c090f8211a601d61432b389492fa4e6b18907db84371e36c3e0da | 64d9fda6b1f373161c1d3c5c4be301724e70fd283c1524fb7059c1d57e485a3d |
| msan | 7d02bf1fead9f48e199e19016888aa82f0f8e1e46a12c0afd8debca15efacd71 | 368fbb43c5d270b40ab8b91b3603ea6fc44f4e615f5ca490d988c7c61ddecf7c | fb4eee58373b92ed3dbaa88c9277820e0b0d2338a72c9fb3cc1ed846485c4be2 |

The asan OpenSSL is the third build of that flavour (after 4aa547d); the instrumentation counts
above were read before it, and the counts after it are in the next paragraph.

UBSan in OpenSSL. The first ASan+UBSan run reported 150 lines, all one site in OpenSSL:
`OPENSSL_sk_pop_free` (crypto/stack/stack.c line 440 at 3.5.9) calls each element's typed free
function, here `pd_free(OSSL_PROPERTY_DEFINITION *)` from crypto/property/property_parse.c line
400, through `OPENSSL_sk_freefunc`, `void (*)(void *)`, which clang 22's `-fsanitize=function`
reports. With that file left out of the check (85b1a6e, and 42c4509 for its relative path), the
next run met a second site, crypto/pem/pem_oth.c line 31, where `PEM_ASN1_read_bio` calls
`d2i_X509` through `d2i_of_void` (from `PEM_read_bio_X509`). UBSan stops at the first report, so
each run shows one site, and the sites come from macros of OpenSSL's public headers
(`DEFINE_STACK_OF`, `IMPLEMENT_PEM_read`, `DEFINE_LHASH_OF`), so they are as many as those
macros' uses. A list of the sites this suite meets today would fail on the next path opgen or the
relay takes. So the asan flavour of OpenSSL is built with
`bench/third_party/openssl-ubsan.ignorelist`, which leaves the function check out of all of
OpenSSL (4aa547d); every other UBSan check stays on in OpenSSL, and oneport's own code and
nghttp2 keep the function check. `bench/coverage.json` declares the gap. The superseded asan
builds were moved, not deleted, to `~/opt/superseded/`.

Checked after the rebuild, by `nm` (undefined-symbol entries, one per object and symbol):
libcrypto.a and libssl.a have none for `__ubsan_handle_function_type_mismatch`, 2,499 for the
other UBSan handlers and 10,484 for `__asan_`; in the test build, `handlers.cpp.o` still calls the function-type check and
`apps.cpp.o` calls 108 UBSan handlers, so the exclusion did not reach first-party code.

OpenSSL under TSan. The tsan flavour is OpenSSL instrumented with TSan, and the suite passed
under it with 0 report lines (below). The gap of Z3 stays declared in `bench/coverage.json`: Z3
withdraws it through the revision log when "the suite passes", and the passes that count are the
records of the code freeze, not these development checks.

### TLS (I22 to I24)

`bench/tls/` (`oneport_tls`) holds the settings once, for the server, opcase and later opgen:
- TLS 1.3 only (min and max version); `SSL_CTX_set_ciphersuites` TLS_AES_128_GCM_SHA256;
  `SSL_CTX_set1_groups_list` X25519; `SSL_CTX_set1_sigalgs_list` ecdsa_secp256r1_sha256;
  `SSL_CTX_set_num_tickets(ctx, 0)` on the server; `SSL_SESS_CACHE_OFF`;
  `SSL_CTX_set_max_early_data(ctx, 0)`. The test `handlers.tls_context` reads them back from the
  server's context; the suites left for negotiation are exactly TLS_AES_128_GCM_SHA256.
- The test certificate and key, `tests/fixtures/tls/test-cert.pem` and `test-key.pem`: an
  ECDSA P-256 key and a self-signed certificate, CN and SAN `oneport.test`, valid 2026-10-02 to
  2126-09-08, SHA-256 fingerprint
  B8:2B:5C:2B:AE:57:D6:3D:38:D4:D7:94:E5:D4:E4:7C:C2:89:A1:52:96:46:F3:99:F4:AA:55:FE:C6:95:EA:68.
  Each file begins with a "TEST MATERIAL ... never a secret" label and the commands that made
  it, with the pinned OpenSSL 3.5.9, before the PEM block (PEM readers skip those lines; checked
  with `openssl x509` and `openssl pkey` on the labelled files). CMake embeds both at configure
  time, so the binary takes no path or flag for them.
- In-process the server terminates TLS through a BIO of its own: OpenSSL reads the bytes the
  worker received from the connection's receive buffer and writes into the worker's output, so
  the loop owns the socket on every backend (I22). Decrypted bytes go to a second buffer of the
  same pool, from which the HTTP/1.1 or h2 handler reads.
- SNI and ALPN, as the frozen text has them. In-process (section 2.1: "TLS is terminated in the
  server"), ALPN chooses the handler: the first of the client's protocols that is `http/1.1` or
  `h2`; no ALPN gives HTTP/1.1; ALPN with neither gets the fatal alert no_application_protocol
  (RFC 7301 s3.2). There is one certificate, so SNI selects nothing in-process. Routing by SNI and
  ALPN is the relay's pass-through (section 2.1, "Dispatch"), which M2b builds on the reader below.
- The ClientHello reader of pass-through, `bench/server/clienthello.hpp`: it reassembles the
  handshake bytes of the records that carry a ClientHello, up to B_CH = 16384, and reads its
  SNI, ALPN list and X25519 key share. Pure and allocation-free; tested on the recording, on a
  re-fragmented copy and on partial input (`clienthello.*`). M2a does not route with it yet.

The recorded ClientHello (I18), `tests/fixtures/tls/clienthello.hex`:
- How it was recorded: `bench/cases/record_clienthello.cpp` makes a client `SSL` from
  `tls::client_ctx()` (the settings above), sets SNI `oneport.test` and ALPN `http/1.1`, and
  calls `SSL_do_handshake` with memory BIOs and no peer; OpenSSL writes its first flight, one
  record holding the ClientHello, and the program prints it as hex under a comment header. It
  ran once on L, at 2026-10-02T18:43:42Z, linked against the pinned OpenSSL 3.5.9 (release
  flavour), and its output was committed as it is (sha256 of the fixture
  b553d6d76d8be29b2054ec762f2c01546ff92f1610214874048e15ee5ef222b2).
- 211 bytes: a record header `16 03 01 00 ce`, then the ClientHello. ℓ (WL7, the length the
  record header announces) is 206; recorded here as measured, and in the revision log at the
  code freeze (section 9.1). Extensions, in order: server_name, ec_point_formats,
  supported_groups (x25519), session_ticket (empty), ALPN (http/1.1), encrypt_then_mac,
  extended_master_secret, signature_algorithms (ecdsa_secp256r1_sha256), supported_versions
  (TLS 1.3), psk_key_exchange_modes, key_share (x25519). These are what OpenSSL 3.5.9 sends with
  I24's settings; nothing was edited.
- Where opcase uses it: wherever a case needs a ClientHello's bytes and no handshake: HC4's slow
  drip, HC13 after the PROXY v1 line, and HC19 with each record version (and later B3's
  partial-ClientHello openings and M3's stub exchange). The synthetic ClientHello of M1 is gone.
- Where a frozen outcome includes a completed handshake (HC1 to HC3 for TLS, and HC20
  in-process), opcase runs a live OpenSSL client with the same settings
  (`bench/cases/script.hpp`, `TlsPlan`): its ClientHello is cut and timed as the case says, and
  the rest of the handshake and the request follow as the server answers.
  `handlers.clienthello_live` checks that this client's ClientHello has the recording's length and
  equals it in every byte but the 96 that each connection draws afresh (random, session id,
  X25519 key share).

### The handlers (I26)

The M1 stubs are gone. Every handler is the same code in both modes; entry differs (accept,
classification, or T_fb for the fallback) and so does where the first bytes are (in the buffer
after replay, in the socket after peek), and nothing after it.

| Handler | Where | What it does |
|---|---|---|
| HTTP/1.1 | `apps.cpp` (`http1.hpp`'s parser) | as in M1; now a step that every input source shares, plain or decrypted |
| h2 (h2c, and TLS with ALPN h2) | `h2.cpp`, nghttp2 1.70.0 | `nghttp2_session_server_new` with memory send and receive; every request stream that ends gets 200, Content-Type text/plain, Content-Length 13, "Hello, World!" |
| TLS | `handlers.cpp`, `bench/tls` | the handshake on OpenSSL through the worker's BIO, then HTTP/1.1 or h2 by ALPN on the decrypted bytes; close_notify before the server closes |
| MQTT | `apps.cpp` | CONNECT read to its end, then CONNACK accepted (`20 02 00 00` at level 4, `20 03 00 00 00` at level 5); PINGREQ gets PINGRESP; DISCONNECT closes; anything else closes |
| SSH | `apps.cpp` | `SSH-2.0-oneport` CRLF on entry; the client's line read up to its LF, at most 255 bytes; then close |
| SMTP | `apps.cpp` | 220 on entry; EHLO 250, QUIT 221 then close, anything else 500 |

- SSH's banner timing (I28) is entry's timing: at accept in dedicated mode, at classification in
  one-port mode (after the client's `SSH-`), at T_fb on a listener with `--fallback SSH`.
  `handlers.ssh_banner_timing` checks all three on the client's clock.
- MQTT and SSH apply the detector's grammar to their first bytes in both modes, as I26 has the
  HTTP/1.1 handler do, so input that one-port mode rejects is closed without a response in
  dedicated mode too.
- PROXY v1 and v2: the parser and the exact consumption are M1's; the inner protocol is now served
  by the real handlers on both listener kinds (HC9 to HC15).
- Output. A handler step appends to the worker's output (for TLS, OpenSSL encrypts it), and one
  `send` sends it. What the socket does not take is copied into the connection's own queue and
  sent on EPOLLOUT; while the queue holds bytes the connection reads nothing more, and the read
  resumes after the flush. `handlers.output_backpressure` drives this with 200,000 pipelined
  requests behind an 8 KiB client receive buffer (15.6 MB of responses, above L's largest send
  buffer, `tcp_wmem` 4 MB), and with 1,000 over TLS, in each mode.
- The connection state is 352 bytes (`sizeof`, L, clang 22.1.8; M1's was 400, which held the
  stub's 96-byte trailer).
- One defect was found and fixed before d71ae06: a union's `{}` sets only its first member, so a
  reused connection's MQTT state could keep a stale "connected" flag and close a CONNECT. The
  hard-case suite caught it on the dedicated PROXY MQTT port when 24 copies ran at once. Each
  handler now sets its own member at entry.

### Design choices of M2a

Every number here is a design choice of M2a, not a frozen value.

| Name | Value | Where | Reason |
|---|---|---|---|
| SMTP replies | `220 oneport.test ESMTP`, `250 oneport.test`, `221 oneport.test closing`, `500 syntax error, command unrecognized` | `apps.hpp` | RFC 5321's codes with plain texts |
| SMTP commands | the verb case-insensitive; EHLO alone or before a space; QUIT alone; every other CRLF-terminated line, the empty one included, gets 500 | `apps.cpp` | RFC 5321 s2.4 (verbs are case-insensitive) |
| SMTP line limit | 512 bytes with its CRLF; a longer line gets 500 and the connection closes | `apps.cpp` | RFC 5321 s4.5.3.1.4 and s4.2.2 |
| SSH line end | the first LF (a CR before it is not required); 255 bytes without LF also end it | `apps.cpp` | the 255 is RFC 4253 s4.2's; accepting a bare LF reads every line a CRLF would end |
| MQTT packets after CONNACK | PINGREQ and DISCONNECT only; a CONNECT whose Remaining Length is below 7 closes | `apps.cpp` | I26: no sessions, no publish; 7 bytes hold the name and level |
| h2 SETTINGS | one setting, MAX_CONCURRENT_STREAMS 100; queued at the session's start, sent with the first output | `h2.cpp` | RFC 9113 s6.5.2 advises no less than 100; no byte leaves before the client's first bytes in either mode |
| h2 messaging | nghttp2's HTTP checks on | `h2.cpp` | the library's default |
| ALPN | the client's first of `http/1.1` and `h2`; none offered: HTTP/1.1; neither: no_application_protocol | `tls.cpp` | RFC 7301 s3.2 |
| TLS buffers | ciphertext in the connection's receive buffer (4096 bytes); plaintext in a second buffer of the same pool, taken at the first decrypted byte and returned when empty | `handlers.cpp` | one buffer size for every handler (I27) |
| Output queue | the unsent tail copied into a per-connection vector; no read while it holds bytes | `handlers.cpp` | the ordering of responses, and bounded input per connection |
| Test certificate | ECDSA P-256, self-signed, CN and SAN oneport.test, 36,500 days | `tests/fixtures/tls` | I24's one P-256 certificate; outlives the paper |
| opcase h2c request | GET `/` in static-table fields, `:authority oneport.test` as a literal without indexing, then GOAWAY | `fixtures.cpp` | proposal I30's static-table fields; nghttp2 checks for :authority or Host |
| HC20's first record | 40 handshake bytes | `cases.cpp` | M1's split, kept: inside the ClientHello, before its extensions |
| Backpressure test | 200,000 requests plain, 1,000 over TLS; client SO_RCVBUF 4096 | `handler_tests.cpp` | above `tcp_wmem`'s 4 MB; a TLS client that writes before it reads must not fill the server's receive buffer |

### Readings of the frozen text in M2a

Not yet in the revision log; each may need a line there.
1. "The transcript equals the dedicated port's" for TLS (HC1 to HC3, HC20 in-process) is
   compared after decryption: both handshakes complete with TLS 1.3, TLS_AES_128_GCM_SHA256,
   x25519, ecdsa_secp256r1_sha256, a verified certificate and no session ticket; the same ALPN;
   the same decrypted bytes; close_notify in both or neither. A handshake's wire bytes differ on
   every connection (the server's random, key share and signature), in either mode, so a byte
   comparison could never hold.
2. HC13 and HC19, whose outcome is only "TLS": the class is checked, and the server's first
   record must be a ServerHello; the flight is not compared with the dedicated port's (it is
   drawn afresh, as in 1).
3. I18's recorded ClientHello serves where a case needs a ClientHello's bytes and no handshake;
   where the outcome needs the handshake to complete, a live client with the same settings sends
   its own ClientHello, cut as the case says. The recording cannot finish a handshake: its key
   share's private key is not kept.
4. HC7's "its request gets 500 from the SMTP handler": each CRLF-terminated line of the request
   gets one 500, the empty line included, so four 500s.
5. The h2c exchange of the hard cases is written without reading (opcase scripts do not react):
   preface, SETTINGS, HEADERS with END_STREAM and GOAWAY in the case's writes, then the client
   shuts down writing. WL1's order (read to END_STREAM, then GOAWAY) is opgen's.
6. In-process, SNI selects nothing (one certificate), and ALPN chooses HTTP/1.1 or h2 as in the
   design choices above.

### The suite on L at 4e814f2

294 CTest entries in every build: 144 run and pass, 150 are skipped as pending, and none fails.

| Group | Entries | Result |
|---|---|---|
| `flags.*` | 14 | pass |
| `loop.{epoll,io_uring}.*` | 18 | pass |
| `detect.*`, `http.*` | 11, 5 | pass |
| `apps.*` (the protocol steps, pure) | 7 | pass |
| `clienthello.*` (the reader on the recording, pure) | 2 | pass |
| `structure.mode_readers` | 1 | pass |
| `server.*` | 18 | pass |
| `handlers.*` (TLS settings and exchange, ALPN h2, refusals, the live ClientHello, h2c, MQTT, SSH timing, SMTP, backpressure) | 10 | pass |
| `case.HCnn.epoll.inproc.{replay,peek}` | 50 | pass, every case full |
| `cli.*` | 6 | pass |
| `gate.*` | 2 | pass |
| `case.HCnn.epoll.relay.*` | 50 | pending M2b: relay dispatch |
| `case.HCnn.io_uring.{inproc,relay}.*` | 100 | pending M2b: the io_uring backend |

The hard cases on epoll with in-process dispatch, per detection mode (the same in replay and
peek): 164 variants, each run 16 times; all 164 pass in full, none fails. What changed from M1:

| Case | M1 | M2a |
|---|---|---|
| HC1, HC2, HC3 | stub for h2c, TLS, MQTT 3.1.1, MQTT 5.0 and SSH | full: nghttp2's response, a completed handshake with the request answered (live client), CONNACK, the SSH line; each transcript equal to the dedicated port's, and each dedicated transcript checked against what its handler sends |
| HC5 | stub | full: 220, 250, 221 |
| HC7 | late variant stub | full: 220, then 500 for each of the request's four lines; G is still the suite's stand-in |
| HC13 | full (class) | full: TLS from the recorded ClientHello after a PROXY v1 line; a ServerHello comes back |
| HC14 | full (class) | full: CONNACK after the TLVs and after a 536-byte header |
| HC15 | stub | full: the 220 greeting T_fb after the header completed |
| HC18 | full (class) | full: the SSH line, equal to the dedicated port's |
| HC19 | full (class) | full: the recorded ClientHello with record version 03 01 and 03 03; a ServerHello comes back |
| HC20 | partial | full in-process: the ClientHello in two records, two writes, the handshake completes and the request is answered; pass-through (routed by SNI) is the relay entries', pending M2b |
| HC24 | full (class) | full: CONNACK for the four Remaining Lengths, the 2,097,152-byte CONNECT streamed through a 4096-byte buffer |

The other cases are as in M1. The suite's stand-ins (timers 300 ms, GAP_SPLIT 10 ms, G 100 ms)
are M1's.

### Sanitizer checks on L (development checks, not records)

Fresh clone at 4e814f2 in `~/lab/p3/m2a-check/final/`, clang 22.1.8, Ninja, `ctest -V -j 8`;
each build links the OpenSSL and nghttp2 of its flavour (`ONEPORT_OPENSSL_USED`,
`ONEPORT_NGHTTP2_USED`). "Report lines" counts the lines of the ctest log that match the lab's
shared report pattern (`lab/bin/sanitize.sh`).

| Build | CMake | Libraries | Build | CTest | Report lines |
|---|---|---|---|---|---|
| Debug | `-DCMAKE_BUILD_TYPE=Debug` | release | 0 warnings | 144 passed, 150 skipped, 0 failed | 0 |
| ASan+UBSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address+undefined` | asan | 0 warnings | the same | 0 |
| TSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=thread` | tsan | 0 warnings | the same | 0 |
| MSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=memory`, the libc++ 22.1.8 at `~/opt/libcxx-msan-gcc` | msan | 0 warnings | the same | 0 |

- Options as in M1: ASan with `ASAN_OPTIONS=detect_leaks=1:detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1`
  and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`; TSan and MSan with the runtime defaults.
- Each run takes about 32 s.
- Instrumentation, as checked: the test binary of each build defines the runtime's symbols
  (`nm`: 324 `__asan_`, 173 `__tsan_`, 64 `__msan_`), and the MSan binary loads `libc++` and
  `libc++abi` from `~/opt/libcxx-msan-gcc/lib`. The libraries are instrumented as listed above.
- Declared gaps that apply: OpenSSL's assembly (the msan OpenSSL has none, the others keep it
  uninstrumented); UBSan's function check in OpenSSL (above); OpenSSL under TSan, still declared
  although this run used a TSan-built OpenSSL and passed (above).
- A stress run of the same four builds at the same time, each with `ctest -V -j 16`, also passed
  with 0 report lines (`stress-*-4e814f2.ctest.log`).
- Before the exclusion, the ASan+UBSan run at d71ae06 failed 75 entries on OpenSSL's reports
  (logs kept as `asan-d71ae06*.ctest.log` in `~/lab/p3/m2a-check/`); Debug, TSan and MSan at
  d71ae06 passed with 0 report lines.

Also on W, as a compile check before M6 (as in M0 and M1): a Debug build of 63b3b5f with MSVC
19.51.36246.0 (Build Tools 18, Ninja), out of tree in a scratch directory, had no warning; 105
CTest entries, 55 passed (14 flags, 9 `loop.IOCP`, 25 pure, among them the new `apps.*` and
`clienthello.*`, 1 structure, 4 cli, 2 gate) and the 50 IOCP case entries were skipped as pending
M6. The third-party libraries are not built on W yet.

Log sha256:

    ebc6e0485f0e2272cb738a2966097d8011e1ef20ddc00e2c23ae1bfa4e334305  debug-4e814f2.build.log
    a237856262984b1563c61c683516a1d399b69f215d807d8c3f133ab15ad96288  debug-4e814f2.ctest.log
    f4fa84aae2d04e6a22cc0b7402301b028e61311b03cbad7787824963ff76191f  asan-4e814f2.build.log
    0d34865b2a022232a25fe8b3028cc91b468cbf32d051770cbf24618e180bad37  asan-4e814f2.ctest.log
    0460ce8b9c69e772c874613481e5a7c7ae005048b555d7cb80423ad8b92b8909  tsan-4e814f2.build.log
    47c6020a0a076dce4a097d47bbddba66eb32a8c8def661a77873de6e3d02b862  tsan-4e814f2.ctest.log
    85f7f0eb2ceea5bf0495ec650562a4271da7f1e94b733e345d09ea9ef751b4a8  msan-4e814f2.build.log
    f93c76c9ccd086a4be7bfdb15fb94896feecc509b0a2e75118369d56b3d84f57  msan-4e814f2.ctest.log
    5eacfaacd4d4d2244dba15840cd6d1b08de58ffb81ccff61bfa4c9f00f85ed7b  stress-debug-4e814f2.ctest.log
    eed98c87e2b4a6d7999e0e61c254995af586a12de5810886b8d5dcbdc905d1f6  stress-asan-4e814f2.ctest.log
    870634f4f9ca00a2ef3c18b195c477c44a66422780123e022e67607ffbd337bd  stress-tsan-4e814f2.ctest.log
    be0d1799bd7627206bb8e7952878c5d41de1d66373cbe6aa0efe34ab32bf3f24  stress-msan-4e814f2.ctest.log

### Not in M2a

- Relay dispatch and stub mode, with the pass-through routing by SNI and ALPN (HC20's other
  half) and the relay copy of rule E: M2b.
- The io_uring backend: M2b.
- IOCP: M6. On W the third-party libraries are not built yet.
- `opgen` and `ophold`; the sanitizer driver and the records (M7).

## M2b, 2026-10-02

### Step 0: M2a's readings in the revision log

30b5be4 appends one entry to the revision log of `hypotheses.md`, "Readings fixed during
engineering (M2a), before the code freeze": M2a's six readings, one line each with why it follows
from the frozen text, and the coordinator's three decisions (UBSan's function check off for
OpenSSL alone in the ASan+UBSan build, declared in `bench/coverage.json`; the live OpenSSL client
of the TLS hard cases, its ClientHello checked against the recording; TLS transcripts compared
after decryption). Nothing above the log changed (`git diff` showed additions after line 1055
only). No reading was found to contradict the frozen text: HC1 to HC3 say "the transcript", and
"the byte transcript" is 1(c)'s, for the fallback only; HC13 and HC19 name only a class; the gap
list of section 11 feeds `bench/coverage.json` and is not closed.

### Commits (papers/one-port)

| Commit | Message |
|---|---|
| 30b5be4 | docs: hypotheses.md revision log, the readings fixed during engineering (M2a), before the code freeze, and the coordinator's three decisions |
| feaaadf | feat: the io_uring loop submits and reaps the server's operations: multishot accept, receive into a buffer or a provided buffer, poll, connect, splice and cancel; provided-buffer rings; the non-waiting reap of 1(b); io_uring_enter calls and submissions by opcode |
| 107237b | test: the io_uring peek path's kernel behaviour pinned before use (RK4): a poll re-armed after an undecided peek does not complete at once, the low-water mark completes it, a half-close completes it above the mark; and buffer select, ENOBUFS, EOF and multishot accept |
| f3c83ce | feat: the server on io_uring (multishot accept, receives into provided buffers, the peek path's polls and the non-waiting reap of 1(b)), relay dispatch to a backend with both relay copies and pass-through routing by SNI and ALPN, stub mode, and --relay-port |
| 3cd91c4 | test: the suite on both Linux backends: every hard case in both detection modes with in-process and relay dispatch (HC20 routed by its SNI), the server and handler tests on io_uring, and relay, pass-through, stub-mode and binary relay tests |
| 1535db1 | chore: .clangd at the repository root: C++23 and, per source directory, the include directories its CMake target uses |
| ee569f6 | fix: a server without --port takes a run of free consecutive ports below the ephemeral range, probing each without SO_REUSEPORT, so tests in parallel neither run out of ports nor join another process's group |
| affccf0 | test: the case suite keeps a server only once it has started, so a server that cannot start fails its variant instead of leaving a null entry |
| 0290a2d | docs: bench/coverage.json, the io_uring MSan gap names the code that unpoisons each receive's completion and the tests that check res against the bytes used |

Then 89a96c5 (docs: the second revision-log entry, M2b's readings) and this file. Each code commit
was built alone on L (Debug, clang 22.1.8, Ninja) from a fresh clone of the `lab` remote and passed
its own suite with no warning and no failure (logs in `~/lab/p3/m2b-check/commits/<sha>/`): feaaadf
294 CTest entries (144 run, 150 pending), 107237b 296 (146 run, 150 pending), f3c83ce 294 (144 run,
150 pending), 3cd91c4 339, ee569f6 339 and affccf0 339 (all run). The other commits change no
compiled file.
Nothing is pushed to origin; the `lab` remote has every commit.

### The io_uring peek path, pinned before use (RK4)

Proposal I11 rests io_uring's peek on `IORING_OP_POLL_ADD` completing only at `SO_RCVLOWAT`,
which the audit derived from the source, and RK4 asks for a test before use. 107237b adds it,
`server.kernel_rcvlowat_uring`, on the extended loop of feaaadf and before any server code used
the poll. On a loopback pair: 10 queued bytes complete a poll for `POLLIN | POLLRDHUP` at once,
with `POLLIN`, and a `MSG_PEEK` sees them; with the mark set to 30, as an undecided peek sets it,
a poll armed again does not complete within a 200 ms bounded wait; 20 bytes complete nothing in
another 200 ms; the 30th byte completes it with `POLLIN` and without `POLLRDHUP`; with the mark at
100, a half-close completes a new poll with `POLLRDHUP`; after a reset of the mark to 1 the reader
gets the 30 bytes, then the EOF. It passed on L (kernel 7.2.3-arch1-2), and 20 times in a row
(`ctest --repeat until-fail:20`), before the backend was built; it passes in every build below.
So io_uring keeps the low-water mark, and RK4's fallback (IOCP's switch to replay) is not needed.

The same commit pins what the backend's receives rest on (`server.kernel_uring_recv_select`): a
receive that selects a provided buffer completes nothing until data arrives and then names the
buffer, whose bytes are the ones sent; with the ring empty it fails with `ENOBUFS` and the bytes
stay queued for the next receive; at EOF it returns 0 and names no buffer; a multishot accept
completes once per connection with `IORING_CQE_F_MORE`. The provided-buffer ring registered
under L's `RLIMIT_MEMLOCK` of 8192 kB.

### What M2b built

**The loop** (`bench/loop`, feaaadf). `UringLoop` queues submissions in the shared ring and
`wait()` submits them with its wait in one `io_uring_enter`; it reaps every completion into a
buffer the worker reads. Added: multishot accept, receive into a buffer or into a provided buffer
(`IOSQE_BUFFER_SELECT`), single-shot poll, connect, splice, cancel; provided-buffer rings
(`IORING_REGISTER_PBUF_RING`); `reap_now()`, the non-waiting reap of 1(b) (`io_uring_enter` with
`GETEVENTS` and no minimum, which runs the ring's deferred task work); `drain()` for stop; the
counters of I29 (`io_uring_enter` calls, submissions by opcode). The ring is created with
`SUBMIT_ALL` and a completion queue of its own size, and flushes the kernel's overflow list if it
is ever used.

**The server on io_uring** (`bench/server/uring.cpp`, f3c83ce). The detection, timers, handlers
and output are the epoll worker's code; what differs is how bytes reach it.
- Accept: one multishot accept per listener and worker (I4), armed again when a completion comes
  without `IORING_CQE_F_MORE`.
- Replay: a receive into a buffer the kernel selects from the worker's provided-buffer ring when
  data arrives, so a pending receive holds no buffer (I15); once the connection holds a buffer,
  into the room after its bytes. Each buffer the ring gives a connection is replaced at once from
  the pool, so the ring holds a fixed count.
- Peek: a poll for `POLLIN | POLLRDHUP`, then the synchronous `MSG_PEEK` of the epoll worker;
  an undecided peek sets `SO_RCVLOWAT` and polls again (I11, pinned above).
- The check of 1(b): in replay, the non-waiting reap; every completion it reaps is handled then,
  and if this connection's receive was among them its bytes (or its end) decide it. In peek, the
  one-byte `MSG_PEEK`, as on epoll.
- Handlers: receives as in replay, in both detection modes and in dedicated mode.
- Output: the synchronous `send` of the epoll worker; what the socket does not take waits in the
  connection's queue for a `POLLOUT` poll.
- A closed connection cancels what it has in flight and keeps its buffers until the last
  completion arrives; only then is its slot reused. At stop every operation is cancelled and
  drained, then the ring's buffers return to the pool.
- MemorySanitizer: each receive's completion unpoisons exactly its `res` bytes at the buffer it
  names (the provided buffer by its id, the room after the connection's bytes, or pass-through's
  ClientHello storage); `bench/coverage.json` says so (0290a2d). No check is disabled.

**Relay dispatch** (`bench/server/relay.cpp`, f3c83ce), on both backends. A connection classified
on a one-port listener with `--dispatch relay`, or dispatched to the fallback at T_fb, goes to the
backend port of its class: `--relay-port` names the backend's first port, and its six listeners
follow in the order of I20. The front connects, sends the bytes replay read, then copies both
ways.
- The backends (I18): a server in dedicated mode (M2's), or in stub mode (M3's and B3's). Stub
  mode is the dedicated layout with one difference, marked on its listeners in `listeners.cpp`:
  its TLS port reads one whole TLS record (a 5-byte header, content type 22, major version 3, a
  length of at most 2^14, then that many bytes), writes the 13-byte body of I26 and closes; it
  never handshakes. Its other five ports run the handlers of I26.
- The relay copy, both built in as flag values (rule E): `--relay-copy user-space` receives into
  buffers of `RELAY_BUF` bytes per direction and sends from them; `--relay-copy splice` moves
  bytes through a pipe per direction with `splice(2)` on epoll and `IORING_OP_SPLICE` (after a
  poll, `SPLICE_F_NONBLOCK`) on io_uring. The bytes replay read are sent from user space first in
  both.
- Ends: a direction's end is passed on as a half-close (the destination's writing shut down), and
  the connection closes when both directions have ended; an error closes both, and a reset on one
  side closes the other by reset.
- Pass-through (I17, I22): a TLS connection is classified at byte 6, as in-process, and then waits
  for its whole ClientHello. The records are reassembled by `bench/server/clienthello.hpp` up to
  B_CH message bytes; in replay they are held as received, in the receive buffer, or once they
  outgrow it in storage of their own; in peek they stay in the socket and `SO_RCVLOWAT` waits for
  the record bytes the reassembly needs next (the reader now reports that count). The route
  table: SNI oneport.test, with no ALPN or an ALPN list that offers http/1.1 or h2, goes to the
  backend's TLS port; any other ClientHello, a malformed one, one longer than B_CH, or an end
  before it is whole, is closed and counted `route_rejected`.
- PROXY: the front consumes the header (I9) and does not pass it on; the backend runs with
  `--proxy off`, and the source the server records is the front's.
- Timers: the detection timers of section 1 until dispatch, as in-process; none after it.
- Counters: `relayed`, `routed_by_sni`, `route_rejected`, `relay_connect_errors`,
  `connect_calls`, `splice_calls`, `bytes_spliced`, `shutdown_calls`, and `out_waits` (output that
  waited for writability, on every path).

**Flags.** `--relay-port` (1 to 65535) is the one new flag; `--mode one-port --dispatch relay`
without it is refused at parse time (exit 2). Dedicated and stub mode accept `--dispatch relay` and
relay nothing, as M0's rule for flags that do not apply has it. `not_served()` now names IOCP alone.

**The connection state** is 368 bytes (`sizeof`, L, clang 22.1.8; M2a's was 352): it gained its
slot, the io_uring bookkeeping and a pointer to the relay's state. The relay's state, 128 bytes,
is made at dispatch, so a pending connection holds none of it.

**Ports in tests** (ee569f6). A server started without `--port` (the tests) took a free run of
consecutive ports from the kernel's ephemeral range. With four sanitizer builds running the
larger suite at once, the clients' connections and TIME-WAIT sockets held enough of that range
that runs failed to start ("no run of free consecutive ports"), and the case harness then crashed
on a null server (affccf0 fixes the harness). It now picks a random run below the ephemeral range
(10000 to 32767 on L), where no client's connect takes a port, and probes each port without
`SO_REUSEPORT` first, so a reuseport group of another test process is never joined by chance. A
server with `--port` is unchanged.

### I29: bytes copied in user space, the rule

Settled for every mode and both backends, and applied where they share code:

> A payload byte is counted in `bytes_copied` each time the server's own code moves it from one
> user-space place to another (a memmove, a memcpy, a vector's insert or assign): a receive
> buffer's compaction (an incomplete tail moved to the start); output that the socket did not
> take, copied into the connection's queue; output appended behind a queue that holds bytes; a
> pass-through ClientHello moved from the receive buffer into storage of its own. A byte that a
> system call moves is counted only by the boundary counters, by direction: `bytes_received` and
> `bytes_peeked` in, `bytes_sent` out. Producing a byte is not a copy: a handler writing its
> reply, OpenSSL writing records or plaintext, nghttp2 writing frames; nor are a library's own
> internal copies.
>
> Rule E's relay copy maps onto the counters so. The user-space option receives into a buffer
> and sends from the same bytes: each relayed byte crosses the boundary twice, once in and once
> out, and is copied in user space zero times (a pass-through ClientHello moved as above
> excepted). The splice option moves the bytes inside the kernel: they count in `bytes_spliced`
> and in neither of the above, except the bytes replay had read before the dispatch, which are
> sent from user space.

What changed: M2a counted the compaction only; the queue's copies (in `emit`) now count too,
for every mode at once, since dedicated, one-port and stub mode run the same `emit`. The
`relay.exchanges.*` tests check the mapping: the front's `bytes_copied` is 0 with either copy, the
user-space relay's boundary counters hold every relayed byte, and splice's `bytes_spliced` holds
the 2 MB upload and the pipelined responses. "Payload bytes ... copied in user space" is a frozen
definition (section 2.1), so the rule is also a line of the revision log (89a96c5, item 7).

### Design choices of M2b

Every number here is a design choice of M2b, not a frozen value.

| Name | Value | Where | Reason |
|---|---|---|---|
| Submission and completion entries | 256 and 4096 | `loop.hpp` | a full submission queue is submitted early, never refused; 4096 completions hold a pass of WL1's 64 connections or of B3's batches without the kernel's overflow list |
| Provided buffers in the ring | 128 per worker, 4096 bytes each | `worker.hpp` `kRingBuffers` | twice WL1's 64 connection slots per server core; a receive that finds the ring empty fails with ENOBUFS and is posted again (`recv_retries`); each buffer taken is replaced at once, so the ring's buffers are a fixed count allocated at start |
| `RELAY_BUF` | 4096 bytes per direction | `worker.hpp` `kRelayBuf` | the handlers' receive buffer (I27): in relay mode replay reads into the buffer the relay sends from; one pool for both directions. Recorded in the revision log at the code freeze (section 9.1) |
| Splice request | 65536 bytes | `kSpliceChunk` | the default pipe capacity, 16 pages of 4096 bytes on L |
| Pass-through hold | at most 6 × B_CH record bytes | `kHelloWireMax` | every record carries at least one handshake byte behind its 5-byte header, so a ClientHello of at most B_CH message bytes fits |
| Pass-through route table | SNI oneport.test; no ALPN, or http/1.1 or h2 offered | `relay.cpp` | the one name and the two protocols the frozen settings serve (I24); M3's TLS route |
| Stub TLS port | one record of content type 22, version 3.x, length at most 2^14; then the 13-byte body; close | `apps.cpp` `stub_tls` | I18's "reads one whole TLS record ... writes the fixed 13-byte body ... closes"; the record checks are the detector's |
| Stub's other ports | the handlers of I26 | `listeners.cpp`, `handlers.cpp` | "the least work that completes an exchange" (I18) for those classes |
| Relay's ends | half-close passed on; both ended: close; error: both closed; reset: the other side reset | `relay.cpp` | see the readings below |
| TCP_NODELAY | on both relayed sockets | `relay.cpp` | nginx's stream module sets it by default, for client and proxied connections (`tcp_nodelay on`), so a write is passed on at once |
| PROXY in relay | consumed by the front, not passed on | `relay.cpp` | I17 has the front write "any replayed bytes"; see the readings |
| Output on io_uring | synchronous `send`, `POLLOUT` poll for the queue | `handlers.cpp` | one output path and one count on both backends; `IORING_OP_SEND` is an M5 option |
| Peer address on io_uring | `getpeername` only when a test hook is set | `uring.cpp` | a multishot accept gives none per connection; the server needs none, the tests key their reports by it |
| Stop | every operation cancelled, then drained for at most 5 s | `uring.cpp` | far above a cancellation's cost; a worker that reaches it reports an error |
| io_uring check of 1(b) when the receive found no buffer | the byte wins | `worker.cpp` | `ENOBUFS` means data arrived; the receive posted again brings it, and the bytes decide one pass later |
| Ports without `--port` | a random run below the ephemeral range, 200 tries, then the kernel's | `server.cpp` | a test convenience (above) |

### Readings of the frozen text in M2b

Each is in the second revision-log entry of `hypotheses.md` (89a96c5); none changes a hard
case's outcome.
1. Relay's "relays both ways" (section 2.1; proposal I17 adds "until one side closes") is read per
   direction: one side's end is passed on as a half-close and the other direction goes on; the
   connection closes when both have ended, or at an error. Why: HC1's h2c client shuts down writing before it reads
   ("Closes first: client" in WL1), so closing both at the first end would lose the response the
   frozen outcome requires ("the transcript equals the dedicated port's").
2. PROXY in relay: the front consumes the header (proposal I9: "the header is consumed exactly") and
   writes the bytes after it, so the backend runs without PROXY and the source the server records
   (HC9) is the front's. Why: section 2.1 has the front write "any replayed bytes", and the header
   is not application data.
3. B_CH bounds the reassembled ClientHello message, and the records that carry it are held as
   received: in replay at most the message plus 5 bytes per record, in peek nothing (B2 d). Why:
   section 1 defines B_CH as "bytes for a ClientHello reassembled in pass-through", and 2.1's bound
   "the partial ClientHello, at most B_CH" is of the ClientHello, not of its record headers;
   bounding the wire bytes would refuse a 16380-byte ClientHello in one record, which the text
   accepts.
4. No timer bounds the wait for the whole ClientHello in pass-through. Why: 1(d) closes at T_dec
   only "a connection with at least one byte that no matcher has decided", and the TLS matcher
   decides at byte 6, as in-process, where the TLS handler too waits for the rest without a timer.
   A connection whose ClientHello has no route is closed and counted apart (`route_rejected`); its
   detection outcome stays "classified".
5. Stub mode's ports for h2c, MQTT, SSH and SMTP run the handlers of I26, "the least work that
   completes an exchange" for those classes; section 2.1 spells out only HTTP/1.1 and TLS.
6. "With in-process and relay dispatch where it applies" (Appendix A) is read as every case in
   relay too, with the relay's backend a server in dedicated mode (M2's backend, PROXY off), and
   HC20's relay outcome is "pass-through: routed by its SNI": the route is by SNI to the backend's
   TLS port, reassembled from both records, and the transcript through the terminating backend
   equals the dedicated port's.
7. I29's "payload bytes copied in user space": the rule above.

### The suite on L at affccf0

339 CTest entries in every build; all run and all pass. None is pending on L any more.

| Group | Entries | Result |
|---|---|---|
| `flags.*` | 14 | pass |
| `loop.{epoll,io_uring}.*` | 18 | pass |
| `detect.*`, `http.*`, `apps.*`, `clienthello.*` (pure) | 25 | pass |
| `structure.mode_readers` | 1 | pass |
| `server.*.{epoll,io_uring}` (keep-alive, dedicated ports and PROXY, the peek drip, the check of 1(b) with a byte in the pass of the expiry, two workers shared and reuseport, the flag matrix, stop with a pending connection, the binary) | 32 | pass |
| `server.kernel_rcvlowat_et`, `server.kernel_rcvlowat_uring`, `server.kernel_uring_recv_select`, `server.not_served` | 4 | pass |
| `handlers.*.{epoll,io_uring}` (TLS, ALPN h2, refusals, the live ClientHello, h2c, MQTT, SSH timing, SMTP, backpressure), and `handlers.tls_context` | 19 | pass |
| `relay.*.{epoll,io_uring}` (exchanges with each copy and detection mode, a refused backend, pass-through in each detection mode, stub mode, the front's flag matrix, the binary as backend and front) | 20 | pass |
| `case.HCnn.{epoll,io_uring}.{inproc,relay}.{replay,peek}` | 200 | pass, every case full |
| `cli.*` | 4 | pass |
| `gate.*` | 2 | pass |

The hard cases: 164 variants per entry, each run 16 times, on 8 entries per case (2 backends,
2 dispatch modes, 2 detection modes); every variant passes in full on every entry. The 150 entries
M2a left pending (`case.*.epoll.relay.*` and `case.*.io_uring.*`) run. In relay entries every
connection the front classifies or sends to the fallback must also report one route, by class to
its class's backend port, or for TLS by SNI to the TLS port (HC13, HC19, HC20, and the TLS openings
of HC1 to HC3), and in replay hold at most the ClientHello and its record headers while it waits;
HC20's ClientHello is reassembled from 2 records. A few results on io_uring, from the server
tests: in `server.check_byte_wins.replay.io_uring` the byte sent in the pass of the expiry is
found by the non-waiting reap (one check, which found the byte; no fallback); in
`server.peek_lowat.peek.io_uring` the peek path wakes exactly twice (16 bytes, then the 24th),
with `SO_RCVLOWAT` set once and reset once.

`cli.not_served_io_uring`, `cli.not_served_relay` and `cli.not_served_stub` are gone (all three are
served); `cli.relay_needs_port` checks the new refusal. The server, handler and relay tests carry
their backend as the last part of the name.

### Sanitizer checks on L (development checks, not records)

Fresh clone at affccf0 in `~/lab/p3/m2b-check/final2/`, clang 22.1.8, Ninja, `ctest -V -j 8`,
the four builds at once (`~/lab/p3/sancheck.sh`); each links the OpenSSL and nghttp2 of its
flavour (`ONEPORT_OPENSSL_USED`, `ONEPORT_NGHTTP2_USED`, read from each build's cache). "Report
lines" counts the lines of the ctest log that match the lab's shared report pattern.

| Build | CMake | Libraries | Build | CTest | Report lines |
|---|---|---|---|---|---|
| Debug | `-DCMAKE_BUILD_TYPE=Debug` | release | 0 warnings | 339 passed, 0 skipped, 0 failed | 0 |
| ASan+UBSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address+undefined` | asan | 0 warnings | the same | 0 |
| TSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=thread` | tsan | 0 warnings | the same | 0 |
| MSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=memory`, the libc++ 22.1.8 at `~/opt/libcxx-msan-gcc` | msan | 0 warnings | the same | 0 |

- Options as in M1 and M2a: ASan with `ASAN_OPTIONS=detect_leaks=1:detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1`
  and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`; TSan and MSan with the runtime defaults.
- Each run takes about 95 s of ctest time.
- Instrumentation, as checked: the test binary of each build defines the runtime's symbols (`nm`:
  316 `__asan_`, 173 `__tsan_`, 63 `__msan_`), and the MSan binary loads `libc++` and `libc++abi`
  from `~/opt/libcxx-msan-gcc/lib`.
- io_uring runs under every sanitizer, MSan included, as proposal Z6 asks of P3's L records. The
  MSan blind spot is declared in `bench/coverage.json` (0290a2d names the code). A negative check
  shows the mitigation does the work: in a scratch copy (`~/lab/p3/m2b-check/msan-negative/`, not
  committed) with the unpoisoning of receive completions in `bench/server/uring.cpp` turned into a
  no-op, the MSan build reports a use of uninitialized value in `detect::classify`, reached from
  the io_uring completion path, on `server.http_keepalive.oneport_replay.io_uring` (2 report lines),
  while the same test on epoll passes with 0. With the unpoisoning, 0.
- TSan runs two workers on the shared listener and on SO_REUSEPORT, on both backends, and two
  workers in the relay's front.
- Declared gaps that apply: as in M2a (OpenSSL's assembly; UBSan's function check in OpenSSL;
  OpenSSL under TSan, still declared although these runs used a TSan-built OpenSSL and passed),
  and the io_uring MSan blind spot above.

The first attempt, at 3cd91c4 (`~/lab/p3/m2b-check/final/`), did not pass, and its logs are
kept. The suite is larger than M2a's (relay gives a connection a second socket pair, and every
server, handler and case test now runs on two backends), and four builds at `-j 8` at once took
enough of L's ephemeral ports that servers failed to start ("no run of free consecutive ports on
127.0.0.1"); the case harness then called a member of a null server. Every report line of that
attempt is that call: in ASan+UBSan 114 lines, 57 of UBSan's "member call on null pointer" at
`tests/case_tests.cpp` lines 131 and 140 and their 57 summaries; in TSan 156 and in MSan 122
lines, the SEGV of the same call in `Running::stop_and_check` (`tests/harness.hpp` line 182) and
their summaries. None is in the server's code. ee569f6 and affccf0 fix the cause and the harness. One more failure
of that attempt is not explained: in its Debug build `handlers.output_backpressure.epoll` failed
in 0.41 s with "one-port replay: 0 bytes for 200000 responses". It did not recur in the four
builds of the second attempt, nor in 40 runs of that test, 4 at a time, beside the case suite at
`-j 12` on the development tree. It is recorded here as seen once, cause not established.

Also on W, as a compile check before M6 (as in M0 to M2a): a Debug build of 0290a2d with MSVC
19.51.36246.0 (Build Tools 18, Ninja), out of tree in a scratch directory, had no warning; 105
CTest entries, 55 passed and the 50 IOCP case entries were skipped as pending M6.

Log sha256:

    9addc8b63ee479aeadc8659bc915a5e55b0630d1a8e16308a168c71629b399ab  debug-affccf0.build.log
    1c6a0eb85629cf82b72b99296d40a2127c2e7c02e8c51290f4abf5ab9c526b36  debug-affccf0.ctest.log
    06777f2ebd7fb13c6161aa71a85c092d2d24ec99350a0afdb7fd55e6f665883e  asan-affccf0.build.log
    a7d492b0fa7f97bb0cfc75270507898cdb70051ef736612a13c32ce1a4ca0035  asan-affccf0.ctest.log
    d5acca4ac6cce55aa3a0c14082a178ccda4c0d7e291575576d205eee011577c8  tsan-affccf0.build.log
    cd046831192a604d49b1d6d65212c993e310e20d1d04d4106eddae2fa0798803  tsan-affccf0.ctest.log
    cab1a12fb0245462e29889598a0e13cbaa6d79f97f40df4b3d4a8bdb3b937664  msan-affccf0.build.log
    a66eb0480a332be7d4909e4efcf882eb794e7a35d38d6abcb15a8c8ceb28aca8  msan-affccf0.ctest.log

(The run was started with the tag "TAG" by mistake; the eight logs were renamed to the commit
afterwards, unchanged.)

### Not in M2b

- IOCP: M6.
- `opgen`, `ophold`, the harnesses, the sanitizer driver and the records (M3, M7).
- Rule E's choices (default detection mode, relay copy): after the pilot entry; both options of
  each are flag values.

## M3, 2026-10-03

### Commits (papers/one-port)

| Commit | Message |
|---|---|
| edf2e38 | fix: T_dec bounds pass-through's wait for the whole ClientHello (one still incomplete at T_dec is closed, route timed_out, counted route_timeouts, its detection outcome still classified), and setsockopt_calls counts every setsockopt on a connection's socket (the relay's SO_LINGER on a close by reset); test relay.pass_through_tdec on both backends in both detection modes |
| 3f7b578 | test: handlers.output_backpressure reports the server's side of a failure (whether it saw the client's port, how detection ended, its counters, a worker error) and whether the client's descriptor still names its socket |
| 058a578 | docs: hypotheses.md revision log, the readings fixed during engineering (M3), before the code freeze: T_dec bounds pass-through's wait (superseding item 4 of the M2b entry), every setsockopt counted, TTFB's first byte, the open loop's due time, keep-alive's requests, WL5 and WL4 as read, section 7's generator and MHz rules, and a note on L's connection tracking |
| 370c88b | feat: opgen, the load generator (bench/gen): churn in closed and open loop and keep-alive for HTTP/1.1, h2c, TLS, MQTT, SSH and the TLS stub exchange, source-address blocks with IP_BIND_ADDRESS_NO_PORT, raw counts over the measured window classified after the workers join, exact TTFB quantiles, each worker's CPU time, and the probe |
| d3a4833 | feat: opcase as a program (WL7's openings, 25 connections every 25 ms, silent or the partial recorded ClientHello, all closed by reset; and the reset probe) and ophold, the holder that accepts and never reads or polls |
| 0a21e7c | test: opgen's loads and protocols against the server on both backends, the open loop's schedule count, the probe, the source block, connect failures and timeouts, and the opgen, opcase and ophold programs (gen.*) |
| 0727dad | feat: the window runner (bench/run): one cost-cell window as section 4.1 lays it out in dedicated mode only, A/A sessions, WL7's readers and the ophold window, full provenance per row, the lab-job wrapper, the wait for an empty connection-tracking table, the K_SRC sweep, the journal line, and their tests on samples recorded on L |
| cd7c61e | fix: opgen counts a connect that has not completed by the exchange's timeout (a SYN never answered) as a failed connect, as section 7's "any connect failed" reads, not as a timeout |
| a9a3ff2 | feat: opgen --spin-us, and the window runner's open loop on one worker per physical core of the generator's CPUs (2, 4, ... 12) polling the last 200 us before each due time (the generator's median issue lag 65.6 us at first, 2.1 us now); the generator tests open few connections, since L tracks every connection for 120 s |
| ef536a1 | refactor: drop opgen's spin constant, which Options::spin (--spin-us) replaces |
| b9f5810 | feat: footprint.k_base, WL7's K_BASE as the median of Ks at sample 2 over 16 valid ophold windows (section 9.3), refused with fewer |
| 1af8eab | feat: the window runner can start the server without address-space randomisation (setarch -R, a per-process setting; aa.py --server-no-aslr), recorded per row |
| 446055b | docs: hypotheses.md revision log, K_SRC = 16 in the M3 entry (item 9): no connect failed at any block size tried, the server sets the rate from K = 4, four times that block, and a later failure before the freeze needs a new entry |
| 0420da0 | fix: opgen stamps a TLS exchange's first byte when the socket read inside OpenSSL returns it (a callback on the socket BIO), as the plain path stamps it after recv, not at the epoll event that reported it; a later step of the same event could read the server's flight first and leave a completed exchange without a TTFB (gen.churn.tls.io_uring in the Debug suite of the four-suite check of 446055b) |
| 21938c5 | test: handlers.output_backpressure builds its 200,000 requests before connecting; built after, they took the client about 150 ms of CPU at -O0, and under four suites at once it stayed silent past T_dec, which closed the connection as silent by design; a failure now prints how detection ended and how long after its connect the client first sent |

Each code commit was built alone (a clone of the lab remote, Debug, clang 22.1.8, Ninja, no
warning in any) and ran its own suite (`ctest -j 6`), one at a time under the lab lock (jobs post3
and post4, `~/lab/p3/m3-aa/post_job.sh`; `~/lab/p3/m3-check/commits/<sha>/`): every suite passed,
343 tests at edf2e38, 3f7b578, 370c88b and d3a4833, 372 at 0a21e7c, 373 from 0727dad to 21938c5.
058a578 and 446055b change no code. Nothing is pushed to origin; the `lab` remote has every commit.

### Step 0: M2b's three open items

**1. Pass-through's wait for the whole ClientHello (M2b's reading 4): superseded, T_dec bounds it.**
The frozen text supports reading pass-through's decision as complete only once the ClientHello is
parsed and routed:
- section 1, "Budgets": "A connection that exceeds a budget while undecided is rejected", and
  B_CH is "bytes for a ClientHello reassembled in pass-through", a budget only this wait can
  exceed, so the text holds the wait to be part of the undecided phase;
- section 2.1 counts "in pass-through, the partial ClientHello" among the memory of a pending
  connection;
- section 1 sets every detection timer to 60 s in B3 "so that no pending connection expires before
  the last sample", where the server runs in relay mode against partial ClientHellos;
- Appendix B matches to the server's timers the proxies' timers that bound this same wait
  (nginx `preread_timeout`, HAProxy `inspect-delay`, Envoy `listener_filters_timeout`).
M2b's reading rested on 1(d) alone, which names the matcher's decision.

Implemented in edf2e38: `dispatch()` leaves T_dec armed for a TLS connection on a relaying
listener; `relay_connect()` disarms it when the route is chosen; `expire_dec()` on a connection
still in the route stage records the timed event (closed), counts `route_timeouts`, reports the
route `timed_out` and closes it, with no second detection outcome (it stays "classified", as M2b's
item 3 counts a ClientHello longer than B_CH). The test `relay.pass_through_tdec.{replay,peek}`
(both backends): WL7's partial-ClientHello opening (the record header and the first
floor(206/2) = 103 bytes of the recorded ClientHello) then silence is classified TLS at byte 6,
closed at T_dec with route `timed_out`, its timed event meets B2(a) and (b), the client sees the
close no earlier than T_dec after its connect, nothing is held in peek, and the same ClientHello in
two writes 30 ms apart is routed. Revision log of `hypotheses.md`, M3 entry, item 1 (058a578),
superseding item 4 of the M2b entry. Consequence for B3 (M4 on): the server's B3 windows must run
with `--t-dec-ms 60000` (and T_fb, T_hdr at 60 s), as section 1 asks, since its pending
partial-ClientHello connections are now timer-bound; in-process TLS is unchanged.

**2. `setsockopt_calls`.** The comment in `server.hpp` now names all three sources (each
`SO_RCVLOWAT` set and reset; the two `TCP_NODELAY` of a relayed connection; the `SO_LINGER` of a
side the relay closes by reset). The two `SO_LINGER` calls in `handlers.cpp` were not counted and
now are, so the counter counts every `setsockopt` on a connection's socket (edf2e38). Revision log,
M3 item 2: section 2.1 lists the operations by kind, and section 10 checks the counters against
`perf trace -s`, which counts every call.

**3. `handlers.output_backpressure`, "0 bytes".** Cause found: the test's client was silent for
longer than T_dec, and the server closed it as designed. The test is fixed (21938c5); the server is
unchanged.
- Reproduction: the four suites of M2b's first attempt (its 3cd91c4 build trees, kept in
  `~/lab/p3/m2b-check/final`) run at once, `ctest -j 8` each, under the lab lock. Over four series
  (5, 3, 3 and 5 rounds, the second and third stopped at their first diagnosed failure; logs in
  `~/lab/p3/m3-dev/repro/`) the test failed 8 times, and once more in the Debug suite of the
  four-suite check of 446055b (below), always the same way: the first arm (one-port replay),
  "0 bytes for 200000 responses" after about 0.4 s, on epoll and on io_uring, in Debug and MSan
  builds. A full connection-tracking table alone did not cause it: `bench/run/ct_full_check.sh`
  filled the table with one HTTP/1.1 burst (262,144 entries) and ran the test 6 times from the
  burst on and 6 times after it drained, with no failure.
- What the two ends showed (the diagnostic of 3f7b578, four failures): the server accepted one
  connection, from the client's local port, and its detection ended "silent" with 0 bytes
  received; the client wrote 524,288 bytes, then `send` failed with `EPIPE`, and its receive ended
  at EOF. In the 446055b failure, the first with the inode check, the client's descriptor still
  named the same socket at the end, so no descriptor was closed and reused.
- The reading. Linux sets `EPIPE`, not `ECONNRESET`, on a socket reset in CLOSE_WAIT, so the client
  had received the server's FIN before the reset. The server's close sends a FIN, not a reset, only
  when nothing unread is queued. So the client had sent nothing when the server closed: "silent"
  was T_dec (300 ms in the tests) expiring before any byte (`expire_dec()`, no fallback on that
  listener), and the client's bytes then met a closed socket. The earlier text of this item said
  the server saw "a half-close before any byte" and "a FIN that no write of the client preceded";
  that was wrong: the client never half-closes, and the FIN was the server's.
- Why the client was silent: its writer thread built all 200,000 requests (7.6 MB) after the
  connect and before its first send. At `-O0` that takes 150 to 160 ms of CPU on L (a copy of the
  loop, measured unloaded; `~/lab/p3/m3-dev/repro/buildtime/`), half of T_dec; four suites at
  `ctest -j 8` each on L's 16 CPUs can stretch it past 300 ms. Only the first arm was ever seen
  failing because a failed `CHECK` ends the test, so the later arms did not run; whether the first
  arm, the first large allocation of a fresh process, is also slower under load was not isolated
  (three builds in one process took the same time unloaded).
- Demonstrated (job cpu1, `~/lab/p3/m3-dev/repro/cpu1/`, under the lab lock): the test pinned to one
  CPU with two busy loops on the same CPU, so the writer thread gets about a third of it. The
  446055b Debug binary failed 10 runs of 10 (5 per backend), each with the same signature
  (silent, 0 bytes received, 524,288 bytes sent, `EPIPE`, EOF); the fixed binary passed 10 of 10.
- The fix (21938c5): the test builds every request before the connect, and on a failure prints how
  detection ended (by which timer, after how many wake-ups, how long after accept) and how long
  after its connect the client first sent.

### What M3 built

**opgen, the load generator** (`bench/gen/`, proposal I30, I33; section 2.4). C++23 on the event loop
of `bench/loop` (epoll) and the TLS settings of `bench/tls`; a library (`opgen_core`, which the
tests run in-process) and the binary `opgen`. Files: `opgen.hpp` (options, report), `opgen.cpp`
(the run and its classification), `options.cpp` (command line, JSON), `worker.{hpp,cpp}` (one
worker per generator CPU), `parse.cpp` (the readers of the server's bytes), `exchange.{hpp,cpp}`
(the exchanges' bytes).
- Loads: churn in closed loop (WL1, C slots, each connect, one exchange, close), churn in open loop
  (WL2, `--rate`: exchanges fall due on one global schedule n / rate from the run's start, thread k
  taking n mod threads = k; each due exchange gets a new connection whether or not earlier ones
  completed), keep-alive (WL3, C connections, one request in flight each).
- Exchanges, WL1's table: HTTP/1.1 GET with `Connection: close`, read to the server's close; h2c
  preface, empty SETTINGS and one HEADERS with END_STREAM in static-table fields (opcase's), read to
  END_STREAM on stream 1, then GOAWAY and close; TLS with HTTP/1.1 (full handshake, SNI
  oneport.test, ALPN http/1.1, the certificate verified, then GET with close, read to
  close_notify); MQTT 3.1.1 CONNECT (HC1's), CONNACK, DISCONNECT, close; SSH identification line,
  read the server's, then its close; the TLS stub exchange (the recorded ClientHello, read the 13
  bytes to EOF). Keep-alive: HTTP/1.1 GET; h2 one stream at a time (stream 1, 3, 5 ...; the server's
  SETTINGS acknowledged; WINDOW_UPDATE for the connection after 32,768 DATA bytes); MQTT PINGREQ
  after one CONNECT; HTTP/1.1 over one TLS connection. Every response is checked (status 200,
  `Content-Length: 13`, `Hello, World!`; `:status` 200 and the 13-byte body; CONNACK accepted;
  PINGRESP; an `SSH-2.0-` line; the stub's body).
- Counting: every exchange is recorded with its due time (open loop), its start just before
  `connect`, the first byte the server sent, and its end, and how it ended. The main thread takes
  `CLOCK_MONOTONIC` after the warm-up and after the window and prints `MEASURE_START <ns>` and
  `MEASURE_END <ns>` at once; after the workers join it classifies the records by those two
  readings: closed loop by end, open loop by due time. So a count never depends on when a worker
  saw the phase change. The report holds raw counts over the measured wall time: completed, errors
  by kind (connect, timeout, reset, early EOF, protocol, TLS), connect failures over the whole
  run, the exchanges due in the window (counted from the schedule, so one never started counts
  against the 99% rule) and how many of them completed, exact quantiles of TTFB, exchange time and
  (open loop) the issue lag, and each worker's CPU time over the window
  (`pthread_getcpuclockid`). No rate is computed from anything else.
- Saturation: the report's `cpu.pct` is the workers' CPU time over (wall time x threads); the
  window runner applies section 7's rule to the larger of it and the busy share of the generator's
  CPUs from `/proc/stat` (lab/t1/t1.py's `gen_cpu_pct_rule`).
- Source addresses (section 2.4): every connection binds base + (n mod K_SRC) with
  `IP_BIND_ADDRESS_NO_PORT`; the block must lie in 127.0.0.2 to 127.255.255.254.
- `--probe`: one exchange of the protocol, exit 0 if it completed (the window's probe).
- Placement: `--cpus` pins one worker per CPU; the runner also starts it under `taskset`.

**opcase as a program and ophold** (`bench/cases/opcase_main.cpp`, `bench/cases/ophold.cpp`).
`opcase open` runs WL7's opening (N_PEND connections in batches of 25 every 25 ms, the silent or
partial-ClientHello bytes, one write, `TCP_NODELAY`; all closed by reset at t = 30 s) and prints
`T0`, `OPENED`, `CLOSED` and a JSON line of counts; `opcase probe-reset` is the probe that closes by
reset. `ophold` listens with backlog N_PEND (it prints the backlog the kernel's somaxconn cap
leaves), accepts in a blocking loop on the listener alone, and holds every descriptor unread and
unpolled until SIGTERM.

**The window runner** (`bench/run/`, Python 3, stdlib only):
- `window.py`: one cost-cell window as section 4.1 lays it out: the conntrack wait (below), a
  source block, the server started fresh on CPU 14 in dedicated mode (any other mode is refused:
  `guard_mode`), its "listening" lines read, the probe (`opgen --probe`), then opgen on CPUs 2 to
  13 (1 s warm-up, 5 s window, C = 64); at its markers the server's `utime + stime` and run time,
  `/proc/stat` per CPU, `/proc/cpuinfo` MHz and `/proc/interrupts`; the server stopped with SIGTERM
  and its counters read from what it prints; TIME-WAIT count and nstat at start and end. One JSON
  row: metric (conn/s, req/s or median TTFB), CPU per exchange (WL4), counters per connection and
  per request (WL5), the generator rule's inputs, interrupts on the server's CPU, its sibling and
  the generator's CPUs, conntrack at start and end, and section 7's validity with reasons.
- `aa.py`: A/A sessions (X Y Y X, X drawn per session from a recorded seed), both arms dedicated,
  arm B's ports 100 above arm A's; churn and keep-alive sessions in one shuffled order, then the
  open-loop sessions at RATE_FRAC x this job's churn median (or an earlier job's, `--rates`);
  provenance once per job (below); the summary of session ratios per cell. Engineering options:
  `--gen-threads`, `--spin-us`, `--server-no-aslr`. `ksrc_sweep.py`: single windows at several
  block sizes.
- `b3.py`: one window in WL7's layout for ophold (the frame of B3's windows): 60 s after the last
  other window, ophold on CPU 14, the reset probe, the baseline, opcase's opening on CPUs 2 to 9,
  readings at t = 20 s and 25 s, close by reset at 30 s, and section 7's B3 rules.
- `footprint.py`: WL7's readers (below). `journal.py`: one lab-journal line per job.
  `lab_job.sh`: one lab job under the lock, with pid, start, log and done files.
  `ct_full_check.sh`: step 0's conntrack check.
- Provenance in every row: the source and build directories, the commit and whether the tree is
  dirty, build type, sanitizer, compiler and its version, the OpenSSL and nghttp2 prefixes, the
  sha256 of the oneport and opgen binaries, of `bench/cmake/pins.cmake` and of `pin.sh`, the inputs
  hash of oneport and opgen (`lab/bin/inputs_hash.py`, project mode, its own sha256 recorded), the
  host fingerprint (`pin.sh`), the placement, the port, the source block, the seed, the lab job.

**The lab lock and pin.sh.** The runner uses L's Papers checkout read-only:
`~/lab/Papers/lab/bin/lablock` (its content equals the Papers repo's `lab/bin/lablock` at 1896ce5
once CR is stripped) and `~/lab/Papers/lab/bin/pin.sh` (byte-identical, sha256
c04c9eae91a336a643f0ea36e6a007ab013045175657c3c977706e42f501045b). L's checkout is at 6697a81,
older than the project mode of `inputs_hash.py`, so that file is a copy from the Papers repo at
1896ce5 in `~/lab/p3/tools/` (sha256
f9d526641e3ba34311ff80e395644eb26305a3266ce35629e3a1c0c7409908e7). Nothing in `~/lab/Papers` was
changed. Every job on L ran under the lock: the long ones through `lab_job.sh` (pid, start, log
and done files), started with `setsid nohup` and polled by their done file; the short ones (builds,
the two smoke sessions) in the foreground of an ssh session under `lablock`. Two queued jobs were
stopped (to settle the open loop's design first) by their process group, taken from their pid
files; no `pgrep -f` or `pkill -f`. `lablock` waits at most 4 h for the lock: a job queued behind
a longer one gave up (exit 1, nothing run) and was started again.

### The tests

The suite on L grows from 339 to 373 CTest entries (clang 22.1.8, Debug, every entry run, all
pass):
- `relay.pass_through_tdec.{replay,peek}.{epoll,io_uring}` (4): step 0, item 1.
- `gen.options`, `gen.quantiles` (pure, every platform): opgen's command line (every flag, and
  the refusals: no port or protocol, SSH or the stub with keep-alive, an open loop with
  keep-alive, a block holding 127.0.0.1 or 127.255.255.255 or outside 127.0.0.0/8, a backward CPU
  range, --threads against --cpus, a flag twice, rate 0, an empty window, an unknown flag), the
  dotted forms, and the exact quantiles (median of an even count, nearest-rank p99 and p99.9).
- `gen.churn.{http1,h2c,tls,mqtt,ssh,tls-stub}.{epoll,io_uring}`,
  `gen.keepalive.{http1,h2c,tls,mqtt}.{epoll,io_uring}`: each load and protocol for a short window
  (0.02 s warm-up, 0.1 s window, 2 slots on 2 workers, so a test opens few connections) against an
  in-process server in dedicated mode (stub mode for the stub
  exchange): markers printed, exchanges completed, no error of any kind in the window or the
  warm-up, a TTFB per exchange, the workers' CPU time; churn: the server accepted exactly the
  connects opgen made; keep-alive: exactly C connections.
- `gen.open_loop.{epoll,io_uring}`: 1,000 exchanges per second; the count due in the window equals
  the schedule's (within one), every one completed, one TTFB, issue lag and connect-relative TTFB
  per exchange, and TTFB from the due time at least TTFB from connect.
- `gen.probe.{epoll,io_uring}`: the probe of each of the six protocols is one connection and
  completes.
- `gen.source_block`: against a recording listener, every source address is one of the block's
  three.
- `gen.failures`: a refused port counts connect failures only; a server that accepts and never
  answers counts timeouts.
- `gen.binaries`: the programs: opgen's probe and a short window against the oneport program (its
  JSON report, no connect failure, markers), then for each case ophold holding opcase's 100
  connections (the reset probe first), `OPENED 100`, `CLOSED 100`, 0 or 108 bytes per connection.
- `run.test_runner` (Python, every platform; 24 checks): WL7's parsers on samples recorded on L on
  2026-10-02 (`bench/run/samples/`: `/proc/slabinfo`, `/sys/kernel/slab` links, the merged cache's
  attributes, `/proc/meminfo`, nstat), `ss -tm` on a loopback sample, the footprint of synthetic
  readings with known growth, the settle rule at its 2% and 8 B edges, the TIME-WAIT, established,
  co-tenant and unreadable-cache rules; the server's counter lines read by key (a later
  non-numeric line such as M6's changes nothing); nstat; the conntrack drop counters;
  `/proc/interrupts`; the source blocks and their 60 s rule; the refusal of one-port mode; the
  generator's worker CPUs per workload; K_BASE's median over 16 valid ophold windows; a cost
  window's metric, CPU per exchange, counters per connection and per request, and each of section
  7's rules; the A/A spread and the margin's edges (a ratio at a bound counts against).

On W (MSVC 19.51.36246.0, Build Tools 18, Ninja, Debug, out of tree; a full build at ef536a1 and an
incremental one at 21938c5, the code commits between changing Python and Linux-only sources): no
warning; 108 CTest entries, the 50 IOCP case entries skipped as pending
M6, the other 58 pass (`gen.options`, `gen.quantiles` and `run.test_runner` among them). opgen's
engine, opcase's program and ophold are Linux only until M6; opgen's command line and report build
on W.

### L's connection tracking: a host condition for every churn window (a decision for Alex)

Found by the runner's second smoke session (2026-10-03, 00:2x): its first window ran clean
(44,777 conn/s), the next three timed out, the probe included, and ssh from W to L timed out for
about two minutes.
- Docker is active on L, and its NAT rules (`table ip nat`, chains DOCKER, PREROUTING, OUTPUT,
  POSTROUTING) load connection tracking, which then tracks every connection, loopback included
  (read-only: `nft list ruleset`, `lsmod`, `/proc/sys/net/netfilter`).
- The table holds 262,144 entries (`nf_conntrack_max`, `nf_conntrack_buckets`); each closed TCP
  connection keeps its entry 120 s (`nf_conntrack_tcp_timeout_time_wait`).
- One HTTP/1.1 churn window on epoll opens about 270,000 connections (1 s warm-up and 5 s at about
  45,000 per second) and leaves about 166,000 entries at its end (median of aa1's 24 windows; 179,000
  on io_uring at about 53,000 per second, aa3; an entry is reused when a client port is), an
  open-loop window about 110,000, a keep-alive window at most 1,900. A second churn window started
  at once fills the table, and the kernel then drops new SYNs ("nf_conntrack: table full, dropping
  packet" in the kernel log; the drop counter of `/proc/net/stat/nf_conntrack`): smoke2's second
  window had most of its connects time out. A burst that started with 109,684 entries already in
  the table lost 64 exchanges near its end (`ct_full_check.sh`'s filler).
- What the harness does (design choices of M3): before each window the runner waits until the
  table holds at most 2,000 entries (`CT_START_MAX`), at most 180 s (`CT_WAIT_MAX_S`), and records
  the count and the drop counters at the window's start and end. Every window then starts from an
  empty table: the median wait before a churn or open-loop window was 122 s to 126 s (by job, aa1
  to aa5), before a keep-alive window following another keep-alive window 0 s. No window run with
  the wait lost a packet to the table (the drop counter unchanged in every row of every job).
- The cost, for the time plan (proposal section 9, which decides nothing): about 125 s per churn or
  open-loop window. C1 and C3 are 16 of L's 24 cost cells: at R_C = 11, 704 such windows, 24.4 h
  added (88,000 s); at R_C = 31, 1,984 windows, 68.9 h. The pilot: 1,024 windows, 35.6 h. The
  mechanism family on L (M1 and M3 churn, M2 open loop): 1,152 windows, 40.0 h. The cost reruns at
  most: 6.7 h (R_C = 11) to 17.8 h (R_C = 31). Against the plan's L total of 44 h to 48 h.
- Recorded, deciding nothing: tracking adds a per-packet cost to both arms alike; and
  `tcp_max_tw_buckets` (65,536) is reached about 1.5 s into every HTTP/1.1 churn window, after
  which the server's closes create no TIME-WAIT socket (`TcpExtTCPTimeWaitOverflow`, 140,916 per
  window, median of aa1), so that transition lies inside every measured window; both are equal
  across windows, since each starts from an empty table and no TIME-WAIT socket.
- The test suite opens about 53,000 connections (the full suite, Debug, after M3 shrank the
  generator tests; 80,282 before), so the four sanitizer suites run at once, as every milestone
  has run them, can fill the table: 249,537 entries were read during the backpressure
  reproductions (step 0, item 3).
- Options, each a host change outside my authority and outside what the frozen text reads at the
  freeze, for Alex: a `notrack` rule for `lo` in a raw table; stopping Docker for the length of
  each lab job; a larger `nf_conntrack_max`; a shorter `nf_conntrack_tcp_timeout_time_wait`. None
  was made. Without one, the harness's wait stands and the time plan grows by the hours above.

### K_SRC

`K_SRC` = 16, recorded in the revision log (M3 entry, item 9). Section 9.1's rule ("so that no
connect fails in the development runs") is met at every block size tried: no connect failed in any
M3 window run after the table wait, at K = 1, 4, 16 or 64. The fastest cells whose clients close
first, and so keep a TIME-WAIT socket per connection, are MQTT and h2c churn on epoll
(`ksrc_sweep.py`, one window each, `~/lab/p3/m3-aa/ksrc2`):

| Cell | K | Conn/s | Connect failures | Server busy | Generator rule | Busiest worker |
|---|---|---|---|---|---|---|
| churn MQTT epoll | 1 | 16,301 | 0 | 0.566 | 74.9% | 69.5% |
| churn MQTT epoll | 4 | 32,507 | 0 | 1.000 | 23.2% | 13.4% |
| churn MQTT epoll | 16 | 32,632 | 0 | 1.000 | 23.4% | 14.2% |
| churn MQTT epoll | 64 | 32,761 | 0 | 1.000 | 22.1% | 12.8% |
| churn h2c epoll | 1 | 16,068 | 0 | 0.622 | 70.5% | 65.8% |
| churn h2c epoll | 4 | 28,846 | 0 | 1.000 | 21.2% | 12.6% |
| churn h2c epoll | 16 | 28,633 | 0 | 1.000 | 20.5% | 12.2% |
| churn h2c epoll | 64 | 28,940 | 0 | 1.000 | 20.0% | 12.1% |

At K = 1 the generator, not the server, set the rate (the kernel's search for a free port among
one address's TIME-WAIT sockets): the server was 57% or 62% busy while section 7's generator rule
read 70% to 75%, below its 90%. So the frozen rule alone would allow K = 1 and would not mark those
windows. From K = 4 the server is saturated. K_SRC = 16 is four times that smallest block, a design
choice. In the HTTP/1.1 cells, whose server closes first, the clients keep no TIME-WAIT socket and
K does not bind. A connect failure in any later development run before the code freeze requires a
new revision-log entry. The window runner records the block of every window and refuses one that
would reuse an address within 60 s (`SourceBlocks`, state in `~/lab/p3/src-blocks.json`).

### A/A noise: dedicated against dedicated, development data

Section 8, step 2 allows dedicated mode to be timed against anything before the code freeze, as
development data (design/status.md, "Does section 8 allow A/A development windows?"). Every window
here ran the server in dedicated mode (`window.py` refuses any other mode; no one-port window ran
in M3, timed or not, outside the functional test suite), under the lab lock, in section 4.1's
layout (fresh processes, the probe, 1 s warm-up, 5 s window; the server on CPU 14, its sibling 15
idle; opgen on CPUs 2 to 13), from a fresh source block of K_SRC addresses, after the
connection-tracking wait. A session is X Y Y X of arms A and B (both dedicated, B's ports 100
above A's); the session ratio is B / A of the arms' window means; per cell, the ratios' median,
range, log standard deviation, and how many lie outside the cost family's margin [0.98, 1.02]
(a ratio at a bound counts as outside, section 4.3). Every job is journaled as development.

The final runs (jobs aa2 to aa5, from a clone of the lab remote at ef536a1, Release, clang
22.1.8, K_SRC 16) and the epoll jobs of the engineering phase (aa1, the development tree; its open
loop had the generator's first design):

| Cell (workload, protocol, backend) | Job | Sessions | Median | Range | Log SD | Outside | Metric per window |
|---|---|---|---|---|---|---|---|
| churn, HTTP/1.1, epoll | aa1 | 6 | 1.0013 | 0.9976 to 1.0032 | 0.0020 | 0 | 44,495 to 44,949 conn/s |
| keep-alive, HTTP/1.1, epoll | aa1 | 6 | 0.9998 | 0.9968 to 1.0049 | 0.0034 | 0 | 138,684 to 140,474 req/s |
| open loop, HTTP/1.1, epoll (first generator design) | aa1 | 6 | 0.9993 | 0.9982 to 1.0046 | 0.0027 | 0 | 124.2 to 125.1 us median TTFB |
| open loop, HTTP/1.1, epoll | aa2 | 6 | 1.0005 | 0.9972 to 1.0036 | 0.0022 | 0 | 57.1 to 57.6 us median TTFB |
| churn, HTTP/1.1, io_uring | aa3 | 6 | 1.0007 | 0.9968 to 1.0042 | 0.0028 | 0 | 52,776 to 53,372 conn/s |
| keep-alive, HTTP/1.1, io_uring | aa3 | 6 | 1.0018 | 0.9887 to 1.0103 | 0.0085 | 0 | 147,963 to 154,125 req/s |
| open loop, HTTP/1.1, io_uring | aa3 | 6 | 0.9981 | 0.9964 to 1.0058 | 0.0037 | 0 | 50.0 to 50.5 us median TTFB |
| keep-alive, h2c, epoll | aa4 | 8 | 1.0010 | 0.9946 to 1.0071 | 0.0045 | 0 | 117,139 to 119,061 req/s |
| keep-alive, h2c, io_uring | aa4 | 8 | 0.9994 | 0.9931 to 1.0066 | 0.0047 | 0 | 124,726 to 128,062 req/s |
| keep-alive, TLS, epoll | aa4 | 8 | 0.9947 | 0.9914 to 1.0085 | 0.0076 | 0 | 98,411 to 101,193 req/s |
| keep-alive, TLS, io_uring | aa4 | 8 | 0.9998 | 0.9823 to 1.0197 | 0.0108 | 0 | 104,153 to 107,781 req/s |
| keep-alive, MQTT, epoll | aa4 | 8 | 0.9996 | 0.9971 to 1.0024 | 0.0019 | 0 | 141,870 to 143,429 req/s |
| keep-alive, MQTT, io_uring | aa4 | 8 | 1.0026 | 0.9913 to 1.0124 | 0.0074 | 0 | 151,667 to 156,506 req/s |
| churn, h2c, epoll | aa5 | 3 | 1.0000 | 0.9959 to 1.0036 | 0.0039 | 0 | 28,611 to 28,981 conn/s |
| churn, TLS, epoll | aa5 | 3 | 1.0023 | 1.0019 to 1.0047 | 0.0015 | 0 | 3,800 to 3,839 conn/s |
| churn, MQTT, epoll | aa5 | 3 | 1.0029 | 0.9998 to 1.0034 | 0.0020 | 0 | 32,275 to 32,613 conn/s |

All 396 windows of jobs aa1 to aa5 were valid by section 7's rules: no connect failed, no error
share above 0.1%, the connection-tracking table dropped nothing, `pin.sh` reported the host pinned
in every session, the mean CPU MHz drifted at most 0.57% from the session's value, and in every
closed-loop window the server's core was at least 99.6% busy while the generator rule read at most
41.5%. CPU per exchange (WL4) in the same sessions: the session ratios' log standard deviation lies
between 0.0013 (MQTT keep-alive, io_uring) and 0.0082 (TLS keep-alive, epoll), every ratio between
0.9900 and 1.0127.

The widest cells are keep-alive on io_uring (HTTP/1.1, MQTT) and TLS keep-alive on both backends:
log SD 0.0074 to 0.0108, every session ratio still inside the margin (the extremes 0.9823 and
1.0197, TLS on io_uring). Their windows vary more from one fresh process to the next: the
coefficient of variation of the window metric is 0.99% (HTTP/1.1, io_uring, aa3), 0.80% (MQTT,
io_uring), 0.73% and 0.83% (TLS, epoll and io_uring), against 0.31% (HTTP/1.1, epoll, aa1) and
0.27% (MQTT, epoll). In TLS keep-alive that variation follows the server's CPU per request
(correlation -0.95 on epoll, -0.80 on io_uring, the CPU per request varying 0.77%); in MQTT on
io_uring it hardly does (correlation -0.46, the CPU per request varying 0.27% while the metric
varied 0.80%). One explanation tested and rejected: the server's
address-space randomisation (each fresh process lays out its ring and buffers differently). Job
aslr1 ran io_uring HTTP/1.1 keep-alive 8 sessions as usual and 8 with the server started under
`setarch -R`: log SD 0.0061 and 0.0063, window variation 0.61% and 0.62%; the default is unchanged
(the option stays in the runner, 1af8eab). The cause is open; for the pilot these are the cells
whose R_C the noise will set.

What the harness's engineering changed, and what it measured before changing it:
- The connection-tracking wait (above) made churn and open-loop windows valid at all: without it
  the second window of a session failed.
- The open loop's generator. Its first design (12 workers sleeping between due times with the
  default 50 us timer slack, each exchange's socket made at its due time) put a median 65.6 us
  (p99 75 us) of issue lag between the due time and `connect`, so 53% of the C3 metric (124.7 us)
  was the generator's. That lag is the same in both arms, so it pulls every C3 ratio toward 1: a
  difference between the arms is diluted, which favours "equivalent". The timer slack at 1 ns,
  the socket made before the due time, a 200 us poll before each due time, and one worker per
  physical core (job variants1, one A/A session per variant, open loop HTTP/1.1 epoll at aa1's
  22,362 per second; medians of four windows):

  | Generator | TTFB from due | Issue lag (p99) | TTFB from connect | A/A ratio |
  |---|---|---|---|---|
  | 12 workers, sleep, 50 us slack (aa1) | 124.7 us | 65.6 us (75.0) | 56.3 us | (6 sessions above) |
  | 12 workers, sleep, 1 ns slack | 78.4 us | 10.5 us (14.9) | 67.5 us | 0.9996 |
  | 12 workers, 200 us poll | 74.8 us | 2.8 us (5.1) | 71.9 us | 1.0050 |
  | 6 workers, one per core, sleep | 64.8 us | 7.6 us (11.5) | 57.1 us | 1.0010 |
  | 6 workers, one per core, 200 us poll (chosen) | 57.4 us | 2.1 us (4.3) | 55.3 us | 1.0009 |

  Workers on both SMT siblings of a core lengthened the client's own work after `connect` by 10 to
  16 us; one worker per core with the poll leaves 2.1 us of the 57.4 us to the generator. aa2 then
  measured the chosen design over 6 sessions (above).
- Interrupts on the server's CPU (`/proc/interrupts` at the markers): in saturated windows only its
  local timer (about 1,000 per second; at most 25 other interrupts in a window); in open-loop
  windows also function-call IPIs, the remote wake-ups of the server's idle CPU (median per
  window 6,278 in aa1, 22,221 in aa2 on epoll, 55,603 in aa3 on io_uring), the same in both arms. No device interrupt reached CPUs 14 or 15, so IRQ affinity was
  left as it is (changing it would be a host change).
- The idle sibling CPU 15 was at most 1.4% busy, CPUs 0 and 1 at most 1.8%, and the mean CPU MHz
  drifted at most 0.57% from the session's value (`pin.sh` reported boost off, governor performance, mains
  power, pinned, in every session).
- K_SRC: below 4 the generator, not the server, set the rate of client-closes-first churn
  (above).
- Not changed: the window layout (section 4.1), C = 64, the warm-up, the placement.

The spread measured is the harness's at R = 6 (aa5: 3) sessions per cell, development data. It
enters no rule: the pilot (section 4.6) sizes R_C on the frozen binary from its own sessions.

### WL7's readers and the ophold window

`bench/run/footprint.py` reads, per WL7: U from the `VmRSS` of each of the system's processes;
Kq as the mean `r` (rmem_alloc) of `ss -tmn state established ( sport = :port )` over the
system's accepted sockets, with `f` beside it, not added; Ks from `Slab` of `/proc/meminfo`
less the growth of the three skb caches, read from `/proc/slabinfo` through `sudo -n` (the file
is 0400), each cache's size its num_slabs x pagesperslab x the page size. The fast-clone cache is
found by following `/sys/kernel/slab/skbuff_fclone_cache` (`:0000512` on L, read again on
2026-10-03); its co-tenants are every name linked to that directory (`pool_workqueue`,
`sgpool-16`, `skbuff_fclone_cache`), its size comes from the one of them `/proc/slabinfo` lists
(`pool_workqueue`), and its `slabs` and `objects` from that directory (first integer, through
`sudo -n`). Also the host's TIME-WAIT count and the established count. Section 7's B3 rules are
`window_problems()`: the settle rule (W at the two samples apart by more than the larger of 2% of
sample 2's W and SETTLE_ABS = 8 bytes per pending connection), the TIME-WAIT count at either sample
against the baseline's, fewer than N_PEND established, and a cache or the shared cache that cannot
be found or read, or co-tenants that differ from the baseline's. K_BASE is the median over 16
ophold windows of Ks, after the pilot entry (section 9.3); `b3.py` runs one such window and
`footprint.k_base()` takes the median over 16 valid ones (b9f5810), refusing fewer.

Two development ophold windows (silent case, N_PEND = 10,000; never K_BASE):
- f1 (development tree): opened 10,000, no connect or write failed, held 10,001 (the reset probe
  too), settled (W 7,417.9 then 7,418.3 bytes per pending connection, tolerance 148 B),
  10,000 established at both samples, U 7.8 B, Kq 0, Ks 7,410.5 B, no growth of the skb caches or
  the shared cache, no listen overflow. Invalid by one rule: the host's TIME-WAIT count was 12 at
  the baseline and 10 at the samples, sockets left by step 0's test runs, which the 60 s gap after
  the last window did not cover. So `b3.py` now waits until the host holds no TIME-WAIT socket
  before the baseline (a design choice, above).
- ophold2 (ef536a1, after the TIME-WAIT wait): valid. Opened 10,000 (no connect or write failed),
  held 10,001; ophold's backlog 4,096 after the kernel's somaxconn cap; the host held no TIME-WAIT
  socket at the baseline nor at either sample; settled (W 7,240.9 then 7,242.1 bytes per pending
  connection); 10,000 established at both samples; U 8.2 B, Kq 0, Ks 7,233.9 B, W 7,242.1 B per
  pending connection; no growth of the skb caches or the shared cache; the shared cache's
  co-tenants as WL7 names them at all three readings; no listen overflow. Development data, not
  K_BASE.

### Counters for the mechanism family

Exactly as section 2.1 and I29 count them: the server's in-code counters (per worker, plain
integers, every build and mode), printed once at SIGTERM as `counter <name> [<sub>] <value>` lines
and read by key (`window.parse_counters`). Per window the runner gives them per accepted connection
(WL5; M3 reading 6) and, for keep-alive, per request; CPU per exchange is `utime + stime` of the
server process between the generator's markers over the exchanges completed in the window (WL4;
reading 7), with the threads' run time from `schedstat` beside it. In the final A/A windows, per
connection (dedicated mode, the HTTP/1.1 port):

Medians over each cell's windows. Per connection for churn and the open loop, per request for
keep-alive; "-" where the backend has no such call. Operations are calls; bytes are payload bytes
received, sent, and copied in user space (I29's rule).

| Cell | Job | Per | CPU us (WL4) | accept | recv | send | epoll_wait | epoll_ctl | io_uring_enter | setsockopt | Bytes in, out, copied |
|---|---|---|---|---|---|---|---|---|---|---|---|
| churn HTTP/1.1 epoll | aa1 | connection | 14.97 | 1.016 | 1.000 | 1.000 | 0.031 | 1.000 | - | 0 | 57, 78, 0 |
| churn HTTP/1.1 io_uring | aa3 | connection | 11.67 | 1.000 | 1.000 | 1.000 | - | - | 0.032 | 0 | 57, 78, 0 |
| open HTTP/1.1 epoll | aa2 | connection | 25.31 | 1.974 | 1.000 | 1.000 | 1.949 | 1.000 | - | 0 | 57, 78, 0 |
| open HTTP/1.1 io_uring | aa3 | connection | 20.21 | 1.000 | 1.000 | 1.000 | - | - | 1.987 | 0 | 57, 78, 0 |
| churn h2c epoll | aa5 | connection | 22.71 | 1.016 | 2.999 | 1.000 | 0.032 | 1.000 | - | 0 | 76, 70, 0 |
| churn TLS epoll | aa5 | connection | 245.62 | 1.031 | 2.000 | 2.000 | 0.047 | 1.000 | - | 0 | 354, 913, 0 |
| churn MQTT epoll | aa5 | connection | 18.95 | 1.016 | 2.999 | 1.000 | 0.032 | 1.000 | - | 0 | 16, 4, 0 |
| keep-alive HTTP/1.1 epoll | aa1 | request | 4.73 | 0 | 1.000 | 1.000 | 0.016 | 0 | - | 0 | 38, 78, 0 |
| keep-alive HTTP/1.1 io_uring | aa3 | request | 4.28 | 0 | 1.000 | 1.000 | - | - | 0.016 | 0 | 38, 78, 0 |
| keep-alive h2c epoll | aa4 | request | 5.92 | 0 | 1.000 | 1.000 | 0.016 | 0 | - | 0 | 26, 38, 0 |
| keep-alive h2c io_uring | aa4 | request | 5.44 | 0 | 1.000 | 1.000 | - | - | 0.016 | 0 | 26, 38, 0 |
| keep-alive TLS epoll | aa4 | request | 7.46 | 0 | 1.000 | 1.000 | 0.016 | 0 | - | 0 | 60, 100, 0 |
| keep-alive TLS io_uring | aa4 | request | 6.90 | 0 | 1.000 | 1.000 | - | - | 0.016 | 0 | 60, 100, 0 |
| keep-alive MQTT epoll | aa4 | request | 4.58 | 0 | 1.000 | 1.000 | 0.016 | 0 | - | 0 | 2, 2, 0 |
| keep-alive MQTT io_uring | aa4 | request | 4.14 | 0 | 1.000 | 1.000 | - | - | 0.016 | 0 | 2, 2, 0 |

On io_uring each churn or open-loop connection's receive is one `IORING_OP_RECV` submission (the
counter's opcode table), and the multishot accept adds none per connection.

These are dedicated mode's own costs, recorded as the runner reports them; no contrast is drawn
from them in M3. Section 10's check of the system-call counters against `perf trace -s` in an
untimed window per cost cell is not built yet (M4 or M5).

### Design choices of M3

Every number here is a design choice of M3, not a frozen value.

| Name | Value | Where | Reason |
|---|---|---|---|
| opgen's exchange timeout | 1000 ms from the exchange's start (keep-alive: from the request's send; a connection's first request includes its setup) | `opgen.hpp` `Options::timeout`; `window.py` `TIMEOUT_MS` | lab/t1/t1.py's default (`--timeout-ms 1000`) |
| A connect not complete at the timeout | a failed connect, not a timeout | `worker.cpp` `pass()` | section 7's "any connect failed": a SYN never answered is one (cd7c61e) |
| Generator sockets | `TCP_NODELAY`, `IP_BIND_ADDRESS_NO_PORT`, non-blocking | `worker.cpp` `make_socket()` | the write of a request is sent at once; section 2.4 for the address |
| h2c in churn | no SETTINGS ACK; GOAWAY after END_STREAM, then close | `parse.cpp` | WL1's exchange as frozen |
| h2 in keep-alive | the server's SETTINGS acknowledged; one WINDOW_UPDATE for the connection after 32,768 DATA bytes | `parse.cpp` | a long connection must keep h2's flow-control window open; half the default window |
| MQTT CONNECT | level 4, empty client identifier, Remaining Length 12 | `exchange.cpp` | the hard cases' CONNECT (HC1) |
| SSH line | `SSH-2.0-opgen_1.0` CRLF | `exchange.cpp` | RFC 4253 s4.2 |
| Responses checked | status 200, Content-Length 13 and `Hello, World!`; h2 `:status` 200 as static index 8 and the 13-byte body; CONNACK accepted; PINGRESP; an `SSH-2.0-` line; the stub's 13 bytes | `exchange.cpp`, `parse.cpp` | an exchange counts only if the server answered as I26 says |
| Quantiles | exact: median the mean of the middle two for an even count; p99 and p99.9 nearest rank | `options.cpp` | C3 compares medians at a 2% margin; no histogram error |
| TLS's first byte | stamped when the socket read inside OpenSSL returns it (a callback on the socket BIO), as the plain path stamps it after `recv`; before 0420da0, at the epoll event that reported it | `worker.cpp` `on_bio()`, `note_tls_read()` | reading 3; an event stamp misses bytes a later step of the same event reads (the sanitizer checks, below) |
| Open loop's schedule | one global schedule origin + n / rate; worker k takes n mod threads = k; the exchanges due in the window counted from the schedule | `worker.cpp`, `opgen.cpp` | an exchange the generator never started counts against the 99% rule |
| Open loop's workers | one per physical core of opgen's CPUs: 2, 4, 6, 8, 10, 12 (the siblings 3 to 13 idle) | `window.py` `OPEN_GEN_THREADS` | workers on both siblings of a core slowed the client's own work by 10 to 16 us per exchange (below) |
| Open loop's spin | the last 200 us before each due time are spent polling, not asleep; the next exchange's socket is made and bound before it falls due | `opgen --spin-us`, `worker.cpp` | the generator's issue lag fell from a median of 65.6 us to 2.1 us (below) |
| Timer slack of the workers | 1 ns (`PR_SET_TIMERSLACK`) | `worker.cpp` | a timed wait ends at its time, not up to the default 50 us later |
| Reserved room | 131,072 records and 256 open-loop slots per worker | `worker.hpp` | no reallocation inside a window |
| Closed-loop workers | one per CPU of 2 to 13 (12) | `window.py` `GEN_CPUS` | the saturation cells need the generator's whole share |
| Arm ports | arm A from 20000, arm B from 20100 (offset 100); ophold on 21000 | `aa.py`, `b3.py` | below the ephemeral range; every change of arm changes port (section 4.6, step 1) |
| Source blocks | from 127.0.1.0 upward, wrapping before 127.255.255.255; a block refused if any of its addresses was released less than 60 s before | `window.py` `SourceBlocks` | section 2.4 |
| K_SRC | 16 | `aa.py --k-src` | four times the smallest block at which the server set the rate (above) |
| Connection-tracking wait | at most 2,000 entries before a window, waited for at most 180 s | `window.py` `CT_START_MAX`, `CT_WAIT_MAX_S` | every window starts from an empty table (above) |
| WL7 window: TIME-WAIT | the host holds no TIME-WAIT socket before the baseline, waited for at most 70 s | `b3.py` | sockets of any earlier activity, not only windows, expire within 60 s and would move the count |
| WL7 window: probe | `opcase probe-reset` (connect, then close by reset), 0.5 s before the baseline | `b3.py` | WL7's probe for a system that answers nothing |
| opcase's batch connect | each connect of a batch completes within 1 s or counts as failed | `opcase_main.cpp` | a batch must not delay the pace |
| A/A order | churn and keep-alive sessions shuffled with a recorded seed, then the open-loop sessions; X drawn per session from the same generator | `aa.py` | the pilot's order rule (C1 and C2 before C3), for development jobs |
| A/A open-loop rate | RATE_FRAC x the median over the job's churn sessions of their mean conn/s (or an earlier job's, `--rates`) | `aa.py` | WL2's rule, applied to development sessions as a stand-in |

### Readings of the frozen text in M3

In the revision log of `hypotheses.md`, M3 entry (058a578, and item 9 later): 1. T_dec bounds
pass-through's wait (step 0); 2. every `setsockopt` on a connection's socket is counted (step 0);
3. TTFB ends at the first byte the server sends on the connection (TLS: its handshake flight; h2c:
its first frame; SSH in dedicated mode: its identification line at accept); 4. in open loop TTFB
runs from the due time, the connect-relative time recorded beside it; 5. keep-alive counts requests
only, not a connection's setup; 6. WL5's counters per connection are the window's server process's
counters over its life, per accepted connection, and per request for keep-alive; 7. WL4's CPU time
is `utime + stime` between the generator's two markers, per exchange completed in the window; 8.
section 7's generator rule takes the larger of the generator's own CPU share and its CPUs' busy
share and applies to closed-loop windows, and the MHz rule compares with `pin.sh`'s mean at the
session's start; 9. K_SRC. And a note on L's connection tracking.

### Sanitizer checks on L (development checks, not records)

A clone of the lab remote at 21938c5 (`~/lab/p3/m3-final/src`), built in `~/lab/p3/m3-check/final/`,
clang 22.1.8, Ninja, `ctest -V -j 8`, the four builds at once (`~/lab/p3/sancheck.sh`, run by
`~/lab/p3/m3-aa/post_job.sh` as job post4 under the lab lock); each links the OpenSSL 3.5.9 and
nghttp2 1.70.0 of its flavour (`ONEPORT_OPENSSL_USED`, `ONEPORT_NGHTTP2_USED`, read from each
build's cache). "Report lines" counts the lines of the ctest log that match the lab's shared report
pattern.

| Build | CMake | Libraries | Build | CTest | Report lines |
|---|---|---|---|---|---|
| Debug | `-DCMAKE_BUILD_TYPE=Debug` | release | 0 warnings | 373 passed, 0 skipped, 0 failed | 0 |
| ASan+UBSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address+undefined` | asan | 0 warnings | the same | 0 |
| TSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=thread` | tsan | 0 warnings | the same | 0 |
| MSan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=memory`, the libc++ at `~/opt/libcxx-msan-gcc` | msan | 0 warnings | the same | 0 |

- Options as in M1 to M2b. Each run took 94 to 100 s of ctest time.
- Instrumentation, as checked: the test binary and `opgen` of each build define the runtime's
  symbols (`nm`: 316 `__asan_`, 173 `__tsan_`, 63 `__msan_` in each).
- The 29 generator tests (`gen.*`) and `run.test_runner` ran in every build, so opgen's TLS runs
  under TSan and MSan against the OpenSSL of that flavour.
- Declared gaps that apply: as in M2b.

The first check, at 446055b (job post3, the same layout, logs `*-446055b.*`), did not pass.
ASan+UBSan, TSan and MSan passed 373 with 0 report lines; the Debug suite failed 2 of 373 (its ctest
log's sha256 40e603b7fee29e493ac1590a16c238397e754e37a0a6d83398a918f71a9c0eb5):
- `handlers.output_backpressure.epoll`: step 0's item 3, whose cause and fix (21938c5) are above.
- `gen.churn.tls.io_uring`, "a TTFB per completed exchange": a TLS exchange completed with no first
  byte. opgen stamped TLS's first byte only at an epoll event whose mask held EPOLLIN. The event
  that completes a connect drives the handshake twice, in `connected()`, which sends the
  ClientHello, and again in the TLS branch of `on_event()`. When the server's flight arrives
  between the two calls, the second reads it under a mask without EPOLLIN; the exchange was then
  stamped late, at a later EPOLLIN event, or not at all when the rest of it was read the same way.
  0420da0 stamps the first byte when the socket read inside OpenSSL returns it (design choices,
  above); a handshake cannot complete without such a read, so no completed exchange lacks one.
  The race was not reproduced on purpose: job cpu1 ran each TLS churn test 5 times per backend on
  one CPU beside two busy loops, and both binaries passed. In Release the two calls are
  microseconds apart, so the flight meets that gap only when the client is preempted there. Each of
  the 532 window rows of M3's jobs with an opgen report (Release, the earlier stamp) has one TTFB per
  completed exchange, and no figure in this file is a TLS TTFB (the TLS cells report conn/s and req/s).

Log sha256 (21938c5):

    ccf5ce70b2a8e0d0fcce0a3127db3fc576308e7b5ff6a85c06ac89cda76762b4  debug-21938c5.build.log
    aecc5984a3ad50a2e587156b24c3c7cb5efcfa37fa561c32dd9107214462b591  debug-21938c5.ctest.log
    7464b36d15b6106e4018842e60ffb938d2d77c2e97d75a5bc8f970aaa9ffdfd0  asan-21938c5.build.log
    b4789763cfb39ccb38d276639c5522d7d9bed3e2605b5b56796113ec00b72149  asan-21938c5.ctest.log
    b8eade898eac3a6410a7ca867d1cacab18f3323d565f0fa584a8e17e2cbd9eff  tsan-21938c5.build.log
    6f178aaaaad966374fa4c889ac638d9402ff2752ace7a638c8abd549826f1431  tsan-21938c5.ctest.log
    753ea679dcf48ea2342ae4820c83715de6e00776310ab932fbc678be8de6cafb  msan-21938c5.build.log
    7e81fc7a7b989331a821c0b458227d64348b0f03a5199df2cb6aad96f35926b4  msan-21938c5.ctest.log

### Lab journal and raw data

Every lab job of M3 that ran windows is one line of the Papers repo's `lab/journal.jsonl` (Papers
commit 4fa459a, local, not pushed; 19 lines): `run` marks it development, `code_commit` names the
commit (empty for the jobs of the uncommitted development tree, whose binaries' sha256 the line
carries), `cells` lists every window with its validity, and `summary` the spread per cell. The
jobs: smoke1, smoke2, aa1, f1-ksrc1, ksrc2, aa2-stopped, variants1 (four lines), aa2, aa3, aa4,
aa5, aslr1 (three lines), and the two ophold windows (f1-ophold, ophold2). Not windows, so not
journaled: step 0's reproductions (test suites, `~/lab/p3/m3-dev/repro/`), the conntrack check
(`~/lab/p3/m3-aa/f1/ctfull/`) and the test checks. The rows (`windows.jsonl`, `summary.json`,
`provenance.json` and each window's raw opgen report and server log) stay on L under
`~/lab/p3/m3-aa/<job>/`, archived in `~/lab/runs-archive/p3-m3-20261003T092018.tar.gz` (sha256
5588ca17f2cf23889e90a78bc871a711ebb7be790605f968d161f66e715b9778, beside it in a `.sha256` file;
made under the lab lock), with step 0's reproduction logs and the check logs of
`~/lab/p3/m3-check/`; build trees, source clones and scratch binaries are left out.

## M6a (Windows), 2026-10-03

M6a (Windows: the dependencies and the IOCP backend) ran on W on 2026-10-03, on branch
`m6-windows` from b0438e1, beside M3 on L, and was written up in `design/status-m6.md` on the
branch so that the two milestones would not conflict. The branch was merged into main in bbd13f7
(below, "The merge into main"); that file's text is this section, and the file now only points
here. Nothing in this section is a result: no window ran on W, and the sanitizer runs are
development checks, not records.

### Commits (m6-windows)

| Commit | Message (first line, shortened) |
|---|---|
| 2957c40 | chore: build_deps.ps1 builds the pinned OpenSSL 3.5.9 and nghttp2 1.70.0 on W with MSVC, release and asan flavours |
| a126467 | feat: the IOCP loop dequeues up to 64 completions per wait with GetQueuedCompletionStatusEx, reaps without waiting (1(b)), drains after stop, associates sockets, counts its calls |
| ec09504 | feat: --iocp-accept no-buffer\|buffer, the AcceptEx form of hypotheses.md section 10; flag tests |
| 372dcc5 | feat: the server on IOCP (Windows) |
| 519b818 | test: the suite on IOCP |

design/status-m6.md (now this section) and design/w-procedure.md are committed after them
(6d55c1e, 3b1774b). Each code commit was built alone on
W from an exported copy (`git archive`, not a worktree), Debug, MSVC 19.51.36246, Ninja, with no
warning, and passed its own suite: a126467 and ec09504 105 CTest entries (55 run, 50 pending),
372dcc5 106 (56 run, 50 pending), 519b818 133 (all run). Logs in
`C:\Users\alext\lab\p3\m6a-check\commits\<sha>\`. Nothing was pushed from the branch; the merge is
on the `lab` remote.

### Tools (Alex's approval of 2026-10-02)

Installed at user level under `%USERPROFILE%\opt` (C:\Users\alext\opt) from portable zips; no
installer ran, nothing system-wide changed, and nothing else was installed.

| Tool | Version | URL | sha256 | Published hash |
|---|---|---|---|---|
| Strawberry Perl (portable) | 5.42.3.1, 64-bit UCRT, released 2026-08-17 | https://github.com/StrawberryPerl/Perl-Dist-Strawberry/releases/download/SP_54231_64bit/strawberry-perl-5.42.3.1-64bit-portable.zip | 6a081a811781c30aca51dbc036afd93092af91e3297901f02c17043795a10690 | equal to strawberryperl.com/releases.json (entry "Aug 2026 / 5.42.3.1 / 64bit", portable) and to the GitHub release asset's digest |
| NASM | 3.02 (the stable release named on www.nasm.us, 2026-06-29) | https://www.nasm.us/pub/nasm/releasebuilds/3.02/win64/nasm-3.02-win64.zip | 161d0bfaff53c2f9e9f3e69fd0672323ebabafd1268976a5cec11be92a19aee7 | none found: the release directories (releasebuilds/3.02/ and its win64/) list no checksum file, and the GitHub project netwide-assembler/nasm has no releases. The value is computed only |

- Unpacked to `C:\Users\alext\opt\strawberry-perl-5.42.3.1` and `C:\Users\alext\opt\nasm-3.02`; the
  archives are in `C:\Users\alext\opt\src`. `perl -v`: v5.42.3, MSWin32-x64-multi-thread;
  `nasm -v`: "NASM version 3.02 compiled on Jun 28 2026".
- Only `perl\bin` goes on PATH for the builds, not Strawberry's `c\bin` (a MinGW toolchain).
  Git's MSYS perl is not used.
- Two nghttp2 build directories of a first attempt (below) were moved, not deleted, to
  `C:\Users\alext\opt\superseded\`.

### The dependency builds

Script: `bench/third_party/build_deps.ps1` (2957c40), the Windows counterpart of build_deps.sh. It
reads the versions, URLs and sha256 from bench/cmake/pins.cmake, checks each archive's sha256
(both equal the pins), checks the compiler (cl 19.51.36246, Build Tools 18, from its vcvars64.bat),
puts Strawberry's perl and NASM first on PATH, and builds each library and flavour in a fresh
copy of the source, logging to `C:\Users\alext\opt\build\logs\<lib>-<flavour>.log`.

The exact commands, from the logs (each also passes the prefix):

| Flavour | OpenSSL 3.5.9 | nghttp2 1.70.0 (CMake, Ninja, cl, Release, ENABLE_LIB_ONLY=ON BUILD_SHARED_LIBS=OFF BUILD_STATIC_LIBS=ON ENABLE_DOC=OFF BUILD_TESTING=OFF CMAKE_INSTALL_LIBDIR=lib) |
|---|---|---|
| release | `perl Configure VC-WIN64A no-shared no-module no-tests no-docs --prefix=... --openssldir=<prefix>\ssl --libdir=lib`, then `nmake`, `nmake install_sw` | `CMAKE_C_FLAGS_RELEASE=/MD /O2 /Ob2 /DNDEBUG /Zl` |
| asan | the same with `no-apps /fsanitize=address` | `CMAKE_C_FLAGS_RELEASE=/MD /O2 /Ob2 /DNDEBUG /Zl /fsanitize=address /Z7` |

- The options that select features are L's (no-shared, no-module, no-tests, no-docs; no-apps in
  the sanitizer flavour). The target and toolchain differ by host, as proposal I23 says:
  VC-WIN64A here, linux-x86_64-clang on L.
- ASan in OpenSSL: L's `enable-asan` adds the gcc-style `-fsanitize=address`, which cl does not
  take, so the flag is MSVC's, passed to Configure as an argument (Configure at 3.5.9 hands every
  argument that begins with "/" to the compiler). MSVC has no UBSan, so W's flavour is ASan only
  (hypotheses.md section 11). MSVC's AddressSanitizer built OpenSSL and nghttp2, so no library
  needs declaring under section 11's Windows clause.
- `configuration.h` of the asan flavour defines `OPENSSL_NO_ASAN`, since `enable-asan` is not
  used. In OpenSSL 3.5.9's sources only test/memleaktest.c reads it, and tests are not built.
- Runtime: OpenSSL compiles its static libraries `/MT /Zl` (Configurations/10-main.conf line 1580
  at 3.5.9), so they name no C runtime. nghttp2 gets `/Zl` for the same reason, so oneport's Debug
  (/MDd) and Release (/MD) builds link both without a runtime conflict. The flags go in
  `CMAKE_C_FLAGS_RELEASE`: a first attempt put them in `CMAKE_C_FLAGS`, where CMake's compiler
  check (a Debug executable) failed, since /Zl leaves it without a C runtime and /RTC1 refuses
  /fsanitize=address.
- Assembly: NASM builds OpenSSL's assembly in both flavours (`AES_ASM`, `X25519_ASM` and others in
  the compile lines); AddressSanitizer does not instrument it (the declared gap "OpenSSL's
  assembly").
- `openssl version -a` (release): "OpenSSL 3.5.9 29 Sep 2026", platform VC-WIN64A, compiler
  `cl /Zi /Fdossl_static.pdb /MT /Zl /GF /Gy /W3 /wd4090 /nologo /O2 ...`.
- nghttp2's own build has one warning (C4244 at lib/nghttp2_hd.c line 1888); oneport's builds have
  none. nghttp2's MSVC configure defines `ssize_t` as `int` in its config.h; its public header
  uses `ssize_t` for its deprecated callbacks, so bench/server/h2.cpp defines it from the SDK's
  `SSIZE_T` before the header on MSVC. oneport calls only the nghttp2_ssize ("2") functions.
- Instrumentation, by `dumpbin /symbols` (lines naming `__asan_`): asan libcrypto.lib 60,893,
  libssl.lib 11,229, nghttp2.lib 1,416; the release libraries 0.
- CMakeLists.txt finds them on W as on L: `ONEPORT_OPT` (default `%USERPROFILE%/opt`), the
  flavour from `ONEPORT_SANITIZER` (release, or asan for address), the prefixes kept in the cache
  (`ONEPORT_OPENSSL_USED`, `ONEPORT_NGHTTP2_USED`).

Library sha256 (`C:\Users\alext\opt`, as linked by the checks below):

| Flavour | libssl.lib | libcrypto.lib | nghttp2.lib |
|---|---|---|---|
| release | 61186638c85a2da05895153da29667f2c3b921959c339ea17d97b0550489e253 | 642385081561608320dfcf2469d893c9b069b28642d7e9fcaf09e1afb80664e1 | 791c9745689027711c04e177546d0057e82962ed437ba169b40eca5fb0271b5e |
| asan | 7704eb34b0bd61788995b08064939159a1c3246faf71afa42244bd24fbc55cb4 | a98937f5b5b5b5df26fa08fb722854b640d2bcef0d6078c65432d076eb5c3df1 | 5f6fe60535b99295a6723ad9c69ab0dfd8edf0bd4cac05d68df0fd89cd0ffecb |

Build logs: openssl-release.log 16f6a2bb33cf1031abc5d5f1ce1c242c02c7451dcbf110f4e3c081240e7b6bd5,
openssl-asan.log 17da5a219db7cd554539dc5f7faf9377fe915b233d0ee97db37ab5191721f82a,
nghttp2-release.log 98573b4b3ba9aa422da8c19b76d8b8355ca767bf6675e36fd646463f15b44fc9,
nghttp2-asan.log 2fb48711be0c43bd51cb8afb49496b61da08aa166f8639eb50ea1d05fdf793e8. The OpenSSL
builds ran from the script before its nghttp2 flags and its argument binding were fixed; the
OpenSSL part is the committed one, unchanged.

### The IOCP backend (372dcc5)

What was built, beside the shared detection, timers, handlers and output:
- **Loop** (`bench/loop/src/iocp.cpp`): one port per worker; each wait is one
  `GetQueuedCompletionStatusEx` of at most 64 completions, the bound rounded up to whole
  milliseconds; `reap_now()` dequeues without waiting; `drain()` after stop; `associate()`.
- **Accept**: N_ACCEPTEX = 64 AcceptEx requests outstanding per listener, each with its own
  socket, posted again as each completes. The default form has no receive buffer
  (`dwReceiveDataLength` = 0); `--iocp-accept buffer` posts the handler's buffer (one-port
  listeners without a fallback). An accepted socket gets `SO_UPDATE_ACCEPT_CONTEXT`, non-blocking
  mode, the worker's port and `FILE_SKIP_COMPLETION_PORT_ON_SUCCESS` (I5).
- **Receive forms (rule E)**: `--iocp-receive zero-byte` (default): a zero-byte `WSARecv`, then a
  synchronous `recv` into the handler's buffer on its completion. `--iocp-receive posted`: a
  `WSARecv` with the handler's buffer posted at once, which a pending connection then holds
  (I15). The form governs detection in replay, the handlers, and dedicated and stub mode alike.
- **Peek (I11)**: the zero-byte `WSARecv` as readiness, then a synchronous `recv(MSG_PEEK)` into
  the worker's scratch. Windows refuses `SO_RCVLOWAT`, so an undecided peek switches the
  connection to replay for the rest of its detection: the queued bytes are read into the
  handler's buffer at once and matching goes on there (`peek_to_replay`). A peek of 0 bytes after
  the zero-byte completion is the half-close with no byte; after a switch a half-close is a read
  of 0 bytes, as in replay. The PROXY header's peek switches the same way.
- **The check of 1(b)**: a one-byte `MSG_PEEK` in the zero-byte form and on the peek path; in the
  posted form in replay, a non-waiting reap of the port (`GetQueuedCompletionStatusEx`, timeout 0),
  every reaped completion handled; the byte wins if the connection's receive was among them with
  bytes.
- **Immediate completions**: with `FILE_SKIP_COMPLETION_PORT_ON_SUCCESS` an operation that
  completes at once queues no packet; it is queued in the worker and handled in the same pass,
  in order (`settle()`), as a dequeued one would be.
- **Output**: the synchronous `send` of the epoll worker. What the socket does not take waits in
  the connection's queue for an overlapped `WSASend` of it (`out_waits`); output emitted while that
  send is in flight waits behind it in `pend_more`, a copy counted by I29's rule.
- **Close and stop**: closing a socket cancels its operations, whose completions still arrive, so
  a closed connection keeps its OVERLAPPEDs, buffers and queue until the last (`finalize`), as on
  io_uring. At stop every connection is closed, every AcceptEx cancelled (`CancelIoEx`), and the
  completions drained (at most 5 s). A worker that reaches the 5 s limit reports an error; on that
  error path only, the worker's destructor then frees its AcceptEx requests while a cancelled one
  might still complete. No test reached the limit.
- **Server and binary** (`server_win.cpp`, `main.cpp`): Winsock 2.2 per server; listeners on
  127.0.0.1 with `SO_EXCLUSIVEADDRUSE` (Windows' `SO_REUSEADDR` would let another socket take the
  port) and backlog `SOMAXCONN` (I5). The binary prints its listening lines and runs until Ctrl+C,
  Ctrl+Break or its named event `Local\oneport-stop-<pid>`, then prints its counters.
- **Not served on IOCP**: relay dispatch (Linux only, section 2.1; refused by the parser and by
  `not_served`), and more than one worker (below).
- Counters on IOCP (I29): `accept_calls` (AcceptEx calls), `recv_calls` (synchronous `recv`s and
  posted `WSARecv`s), `peek_calls`, `zero_byte_recv_calls`, `send_calls` (synchronous `send`s and
  the queue's `WSASend`s), `check_calls`, `gqcs_calls`, `peek_to_replay`, `out_waits`, and the byte
  counters as on Linux. `accept_calls` includes the N_ACCEPTEX requests posted at start, before
  any connection: 64 per listener, so 64 in one-port mode and 384 in dedicated and stub mode. That
  is a constant offset per server start, which per-connection operation counts (WL5) must subtract.
- The connection state is 544 bytes on W (`sizeof`, MSVC 19.51.36246, Release layout, read from the
  ASan binary's start line; 568 in the Debug build, whose standard containers are larger); on L it
  was 368 bytes in M2b. It adds three OVERLAPPED blocks and two vectors on Windows.

#### Design choices of M6a

Every number here is a design choice of M6a, not a frozen value.

| Name | Value | Where | Reason |
|---|---|---|---|
| N_ACCEPTEX | 64 per listener, the same in both modes | `worker.hpp` `kAcceptEx` | WL1's 64 connection slots per server core: every slot of a closed loop finds an AcceptEx posted when it reconnects. Recorded in the revision log at the code freeze (section 9.1) |
| Completions per wait | 64 | `loop.hpp` `IocpLoop::kMaxEntries` | as epoll's `kMaxEvents`, WL1's 64 slots |
| Buffer form's data length | 4032 bytes (`kRecvBuf` - 2 x (sizeof(sockaddr_in) + 16)) | `iocp.cpp` | AcceptEx writes the two addresses after the data in the same buffer, the handler's |
| Drain at stop | at most 5 s | `iocp.cpp` `kDrainLimit` | as io_uring's |
| Listener option | `SO_EXCLUSIVEADDRUSE` | `server_win.cpp` | Windows' `SO_REUSEADDR` lets another socket bind an address in use |
| Socket handles | kept in the shared code's `int fd` | `worker.hpp` `sock`, `fd_of` | a kernel handle's lower 32 bits are significant, and -1 stays "closed"; `fd_of` refuses a handle that does not fit |
| Stop of the binary | `Local\oneport-stop-<pid>`, Ctrl+C, Ctrl+Break | `main.cpp` | a harness stops the server without sharing its console |
| Workers | 1 | `listeners.cpp` `not_served` | below |
| Test ports | a random run from 10000 to 65535, each port probed by its bind | `server_win.cpp` | W's dynamic range is 1025 to 65535, so no range is free of clients' ports (w-procedure.md section 1) |
| Test client's waits | the last 20 ms of each wait in steps of at most 1 ms on a high-resolution waitable timer | `bench/cases/script.cpp` | see "HC03" below |

### The IOCP pins (tested before use, proposal I11)

All in `tests/iocp_tests.cpp`, each on a loopback pair set up as the worker sets its sockets.
All pass on W (Windows 11 Pro N, 10.0.26200).

| Test | What it pins |
|---|---|
| `iocp.pin_rcvlowat` | `setsockopt(SO_RCVLOWAT)` is refused. W returned WSAENOPROTOOPT (10042); the SOL_SOCKET options documentation says WSAEINVAL on Windows Vista and later and WSAENOPROTOOPT before (https://learn.microsoft.com/en-us/windows/win32/winsock/sol-socket-socket-options, read 2026-10-03), and proposal I11 cites WSAEINVAL. Either is the refusal the design needs; the test takes both |
| `iocp.pin_zero_byte` | a zero-byte `WSARecv` stays pending with nothing queued (200 ms), completes with 0 bytes when 10 bytes arrive; `MSG_PEEK` then returns them twice without taking them; with bytes queued a zero-byte `WSARecv` completes at once and, in skip mode, queues no packet; the socket is non-blocking |
| `iocp.pin_zero_byte_half_close` | a half-close completes a pending zero-byte `WSARecv`; with no byte, `MSG_PEEK` and `recv` return 0; with 2 bytes first, `MSG_PEEK` returns 2, `recv` 2, then 0 |
| `iocp.pin_zero_byte_reset` | a reset completes it with an error, `WSAECONNRESET` by `WSAGetOverlappedResult` |
| `iocp.pin_peek_beside_zero_byte` | a one-byte `MSG_PEEK` finds a byte that arrived while the zero-byte `WSARecv` was pending, before its completion is dequeued, and leaves it; the completion is still queued |
| `iocp.pin_close_completes` | closing a socket completes its pending operation with an error, and the packet arrives |
| `iocp.pin_acceptex` | AcceptEx without a buffer completes at the connect; with a 256-byte buffer it does not complete within 300 ms of a silent connect, and completes with the 3 bytes the client then sends |

### The suite on W at 519b818

133 CTest entries; all run, all pass, none pending.

| Group | Entries |
|---|---|
| `flags.*` | 14 |
| `loop.IOCP.*` | 9 |
| `detect.*`, `http.*`, `apps.*`, `clienthello.*` (pure) | 25 |
| `structure.mode_readers` | 1 |
| `handlers.*.IOCP` (TLS settings and exchange, ALPN h2, refusals, the live ClientHello, h2c, MQTT, SSH timing, SMTP, backpressure) and `handlers.tls_context` | 10 |
| `iocp.pin_*` | 7 |
| `iocp.*` server tests: `receive_forms`, `check_byte_wins.{replay_zero_byte,replay_posted,peek}`, `peek_switch`, `accept_forms`, `stub_mode`, `stop_with_pending`, `not_served`, `binary_smoke` | 10 |
| `case.HCnn.IOCP.inproc.{replay,peek}` | 50 |
| `cli.*` (print_config, usage_error, help, not_served_iocp_workers, relay_refused_iocp) | 5 |
| `gate.*` | 2 |

- The hard cases: 164 variants per entry, each run 16 times; every variant passes in full on both
  entries of every case. The suite's stand-ins are M1's (timers 300 ms, GAP_SPLIT 10 ms, G 100 ms).
  The 50 entries pending since M0 (`oneport_tests pending ... M6`) are gone.
- What the server tests add on IOCP:
  - `receive_forms`: both receive forms in one-port replay, one-port peek and dedicated mode, each
    with three pipelined HTTP/1.1 requests, a TLS exchange, h2c, SMTP (the fallback or its port)
    and SSH.
  - `check_byte_wins.*`: the check of 1(b) in both forms with a request that reaches the socket
    in the pass of the expiry, through the `before_expiries` hook: the byte wins, one check found
    it, no fallback. The posted form's case is the non-waiting reap.
  - `peek_switch`: a request whose first write leaves the peek undecided is switched once, read
    into the handler's buffer and answered; also during a PROXY v2 header; no switch in replay;
    `SO_RCVLOWAT` never set.
  - `accept_forms`: with `--iocp-accept buffer`, in both detection modes, the first bytes come with
    the accept and decide the connection in one wakeup; a split request and a TLS handshake follow.
  - `stub_mode`: the stub's TLS port answers one record with the 13-byte body; its HTTP/1.1 port 200.
  - `stop_with_pending`: a stop with connections pending (silent, with bytes, mid-request) in both
    forms: each closed, its operations cancelled and drained, no connection or buffer left.
  - `binary_smoke`: the binary started with a pipe on stdout answers 200, stops on its event,
    exits 0 and prints its counters.
- `handlers.output_backpressure.IOCP`: 200,000 pipelined requests behind a 4 KiB client receive
  buffer in each mode: the queue waited for its overlapped `WSASend` (`out_waits` > 0) and every
  response arrived in order; and 1,000 over TLS.

Two failures of the first full run, both fixed before the commits:
- **HC21 in peek mode** ("closed in pass 34, the half-close was observed in pass 0"): IOCP has no
  RDHUP event, so the pass that observes a half-close is the one whose peek returns 0; `peek()` now
  records it.
- **HC03.h2c in both modes** (undecided at T_dec): HC3 drips 24 bytes 5 ms apart, 120 ms inside
  the suite's 300 ms T_dec. The test client waited with `WSAPoll`, whose timeout ends on the
  process's timer tick; a test process that does not call `timeBeginPeriod` gets the default
  15.625 ms, so the drip took about 375 ms. This was the client's timing, not the server's: the
  client now waits the last 20 ms of each wait on a high-resolution waitable timer
  (`CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`, Windows 10 1803 and later), process-local.

### Sanitizer checks on W (development checks, not records)

MSVC 19.51.36246 (Build Tools 18, toolset 14.51.36231), Ninja, `ctest -V -j 4`, from the
exported copy of 519b818 (`C:\Users\alext\lab\p3\m6a-check\`). "Report lines" counts the lines
of the ctest log that match the shared report pattern (bench/oneport_record.py, the same text as
lab/bin/sanitize.ps1).

| Build | CMake | Libraries | Build | CTest | Report lines |
|---|---|---|---|---|---|
| Debug | `-DCMAKE_BUILD_TYPE=Debug` | release | 0 warnings | 133 passed, 0 skipped, 0 failed | 0 |
| ASan | `-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address` | asan | 0 warnings | the same | 0 |

- ASan ran with `ASAN_OPTIONS=detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1`,
  the options P1 and P2 used on W (papers/wake-defect/bench/sanitize_wakeprobe.ps1,
  papers/typed-routing/bench/sanitize_regexmatcher.ps1): L's without `detect_leaks`, which MSVC's
  runtime does not offer. The tests ran in the vcvars64 environment, whose PATH holds MSVC's
  `clang_rt.asan_dynamic-x86_64.dll`.
- Instrumentation, as checked: the ASan test binary imports `clang_rt.asan_dynamic-x86_64.dll`
  (`dumpbin /dependents`); `iocp.cpp.obj` and `worker.cpp.obj` reference `__asan_` (202 and 159
  symbol lines); the libraries as above.
- Negative control (not committed): a one-past-the-end write to a 16-byte vector, built with
  `cl /O2 /MD /Zi /fsanitize=address` and run with the same options, printed
  "ERROR: AddressSanitizer: heap-buffer-overflow" and its SUMMARY line, both of which the report
  pattern matches.
- A stress run of the Debug and ASan suites at the same time, `-j 6` each, also passed with 0
  report lines.
- Only ASan is required on W (section 11); TSan and MSan stay declared gaps for W in
  bench/coverage.json, unchanged.

Log sha256 (`C:\Users\alext\lab\p3\m6a-check\`):

    2aae37091d7e72c4f8e6210d06f1c9f1001c2aa039cf1578076de3b00fa78233  commits/519b818/debug-519b818.build.log
    932fddd581d186b32d01b10c137af6e83e07a5b532c51142b6a1d4ba3467f111  commits/519b818/debug-519b818.ctest.log
    1a4e2587d309f1d59cc42f00d5fdb276d3498657f514068d1a91a8cb1ada9924  final/asan-519b818.build.log
    b1b492f27ae78b3d0ab81f6d1ed482de11b6fc11aaa678af4d939dc9e2c2360a  final/asan-519b818.ctest.log
    c823b73c055f6eb07d4a0d26f327b7dd219f641be248c8d8558613784e6a0de7  final/stress-debug-519b818.ctest.log
    8e1eaa3b3f5d7f2a30adde28197287e46376d528d4e3bd9b246e6163dcc51592  final/stress-asan-519b818.ctest.log
    3558eca840787c71e0feff80e440e832e5ec16f04da936b028d99434bba6d882  commits/a126467/debug-a126467.build.log
    cc6f1863dd2a0967339388e8c6819ae63eedb41f34304edf03545cd854903c2f  commits/a126467/debug-a126467.ctest.log
    5f2315d6dba3ce4ff7a2ebed364c7525cdfcd2f162f9ddde9eab741f928d6465  commits/ec09504/debug-ec09504.build.log
    b60147edcaa8f687b6190283c52b17620d4d83784026c1b8c4b957ffb81c984c  commits/ec09504/debug-ec09504.ctest.log
    d938b3dabbce98f13b03bc1865062b7efd133837fd6756f828379a29ac7b68ac  commits/372dcc5/debug-372dcc5.build.log
    bd2a25609b5be05790182bb4daef1799f65fa807427a6148d826f6e2fdc013b0  commits/372dcc5/debug-372dcc5.ctest.log

### Linux: not compiled in M6a

M6a could not build on L (M3 works there) and did not use W's WSL. The coordinator must build
the merged tree on L (Debug and the three sanitizer builds) and run the suite before the merge is
taken as green. Done, and green (below, "The merge into main").

What M6a did instead. Every edit to a file Linux compiles is a block for `_WIN32` (or a guard
line that adds `_WIN32` to `__linux__`), and no Linux line was retyped, with these exceptions,
all portable and checked on W:
- the flag `--iocp-accept` (config.hpp, config.cpp) and its flag tests (tests/unit_tests.cpp);
  on Linux too, `--print-config` and `describe()` now print the line `iocp-accept no-buffer`
  after `iocp-receive`, which M3's harness should know if it parses that output;
- the field `DetectionReport::replayed` (server.hpp), false on Linux;
- `bench/cases/CMakeLists.txt`: `record_clienthello` is built only where `WIN32` is false.
A script (not committed) evaluated only the `__linux__` and `_WIN32` conditionals of each changed
C++ file as Linux does and compared the result, comments and blank lines dropped, with the same
treatment of b0438e1: every file is identical but for the three items above and the guard line
of tests/handler_tests.cpp, which has the same truth value on Linux. The CMake changes add
`elseif(WIN32)` and `if(WIN32)` branches and leave the Linux branches as they were.

### Readings for the revision log

Readings 1 to 6 are in the revision log of hypotheses.md (the M6a entry, with why each follows from
the frozen text). Reading 7 is not logged: it lets the B2(d) audit pass a silent connection that
holds the handler's buffer, which exempts the posted form from B2(d)'s "one that has received no
byte holds no data buffer" rather than reading it, so it stays open (below, "Open for the
coordinator"). Items 8 and 9 are, as M6a wrote, not readings: 8 is a note in the same entry, and
N_ACCEPTEX is recorded at the code freeze (section 9.1).

Each is a reading of the frozen text met while building IOCP; none changes a hard case's outcome.
1. Appendix A's "with in-process and relay dispatch where it applies": on IOCP only in-process
   applies, since section 2.1 says "Relay (Linux only)". The IOCP entries are the 25 cases in both
   detection modes with in-process dispatch: 50.
2. Section 2.1's "an undecided peek switches the connection to replay": the switch happens at the
   first undecided peek, and the queued bytes are read into the handler's buffer at once (the
   connection's next receive); matching continues there. From then on the connection is in
   replay, so B2(d)'s bound for it is replay's, the handler's buffer (section 2.1: "with replay,
   the handler's buffer from the first byte"). The case suite applies replay's bound to a
   connection whose report says it switched. The PROXY header's peek switches by the same rule.
3. 1(h) on IOCP: the pass that observes a half-close is the one in which a peek returns 0 after the
   zero-byte completion (proposal I11), or, after the switch, the read that returns 0.
4. Section 2.1's counter "`GetQueuedCompletionStatus` calls" counts `GetQueuedCompletionStatusEx`
   calls, each of which dequeues up to 64 completions, as an `epoll_wait` returns up to 64 events;
   every wait, every non-waiting reap of 1(b) and every drain at stop is one.
5. 1(b) on IOCP: "the zero-byte WSARecv on IOCP" takes the one-byte MSG_PEEK, and so does a peek-mode
   connection whatever the receive form, since its detection waits with the zero-byte WSARecv;
   "IOCP's posted-buffer form" takes the non-waiting reap of the port, every reaped completion
   handled, and the byte wins if the connection's receive was among them with bytes.
6. Section 10's "AcceptEx with a receive buffer", on "a listener without a fallback": the form
   applies to one-port listeners only (the cell's listener) and the parser refuses it with a
   fallback (proposal I5); dedicated and stub listeners keep AcceptEx without a buffer, since their
   SSH and SMTP ports speak first and would not complete it. The bytes it receives are the
   connection's first read, in the handler's buffer, and detection runs on them as in replay in
   either detection mode, since they are no longer in the socket to peek; that is not counted as a
   switch. It receives at most 4032 bytes, the buffer's last 64 holding the two addresses.
7. Proposal I15, "if rule E chooses the posted-buffer form on IOCP, the paper reports the buffer it
   holds": in the posted form a pending connection holds the handler's buffer from accept; the
   suite's B2(d) audit does not flag it as held while silent, since a receive writes into it (as
   io_uring's receive into the connection's own buffer). The case suite runs the default form.
8. Not a reading: proposal I11 says `setsockopt(SO_RCVLOWAT)` fails with WSAEINVAL on Windows; W
   returns WSAENOPROTOOPT (10042). The documentation says WSAEINVAL from Vista on. The design rests
   only on the refusal, which holds.
9. Not a reading, a value for section 9.1 at the code freeze: N_ACCEPTEX = 64.

### Open for the coordinator

- **Decided (2026-10-03):** the coordinator's decision is in the revision log ("The coordinator's
  decision on M6a's reading 7"): rule E may choose only B2(d)-conforming forms, so the posted form
  leaves rule E and stays section 10's secondary, descriptive cell (M4a, step 0, 2). The item as M6a
  wrote it:
- **Rule E's posted form and "no data buffer while no byte has arrived".** Section 2.1 states, as a
  design property, "no data buffer while no byte has arrived, on every backend", and B2(d) tests
  it. Rule E's posted form holds the handler's buffer from accept by construction; only the
  proposal (I15) carries the caveat that the paper then reports the buffer it holds. So this is a
  tension between the frozen 2.1 and B2(d) and a rule-E option the frozen binary must carry, not
  an audit detail (reading 7). The 50 IOCP case entries run the default zero-byte form only. If
  rule E chooses the posted form before the W pilot, B1 and B2(d) will not have been checked on
  the measured form: the W record's suite then needs the case entries under the posted form too
  (a second CTest dimension, or the form as an override), with B2(d)'s "no buffer while silent"
  read per I15 for that form. The server tests already run both forms (`iocp.receive_forms`,
  `iocp.check_byte_wins.*`, `iocp.stop_with_pending`).
- **More than one worker on IOCP is not built.** Proposal I4 has "one completion port, shared by
  the worker threads, with AcceptEx requests posted on the socket". A socket is associated with one
  port, so with a shared port any thread may dequeue any connection's completion, which the
  per-worker connection state, deadline lists and atomics-free counters (section 2.1) do not allow
  as built; a worker per port cannot share one listener's AcceptEx completions. The primary cells
  use one core; the frozen consumer is section 10's "2 server cores: C1 HTTP/1.1 on each backend",
  one IOCP cell. Options: (a) build the shared port with each connection pinned to the worker that
  accepted it and completions routed to it; (b) a port per worker, with the worker that takes an
  AcceptEx completion handing the socket to a worker's port (a change of I4's accept model,
  logged); (c) leave the IOCP 2-core cell out and say why. Until then `not_served` refuses
  `--workers` above 1 on IOCP (exit 3).
- **Timer resolution** (w-procedure.md section 3): the binary keeps the default; Alex decides.
- **RK2 on W**: W's dynamic range is 1025 to 65535 and `TcpTimedWaitDelay` is 30 s, both
  different from Windows' defaults; the pilot reads them again (proposal LB5, RK2).
- The proposal's "Not verified, to be read at the freeze: ... OpenSSL's Windows build notes on
  NASM": NOTES-WINDOWS.md at 3.5.9 names NASM as the only supported assembler (from
  https://www.nasm.us) and recommends Strawberry Perl.

### What M6b needs

- The Windows side of the harness that M3 defines on L: a window runner on W with the placement,
  the quiet check and the frequency check of design/w-procedure.md (after Alex's approval), the
  server's stop by `Local\oneport-stop-<pid>`, the per-window records of section 7 (power plan,
  timer resolution, TIME-WAIT, listen drops).
- `opgen`'s Windows backend (proposal I30: "a backend for Windows chosen in engineering"). Windows
  has no `IP_BIND_ADDRESS_NO_PORT`; how source addresses of 127.0.0.0/8 are taken per window on W,
  and how `K_SRC` applies there, is open (RK2).
- The W sanitizer record driver (after lab/bin/sanitize.ps1 and bench/oneport_record.py):
  `oneport-<commit>-W-asan`, built as above, with the ASan runtime on PATH.
- The answer to "more than one worker on IOCP" above, before section 10's 2-core IOCP cell.
- Everything M6a built is in place on W: the tools, both library flavours, and green Debug and
  ASan suites at 519b818.

### The merge into main (bbd13f7)

`git merge --no-ff m6-windows` on main at d27d3fe (M3's last commit) gave the merge commit bbd13f7.
Three files conflicted; each was resolved keeping both sides:
- `tests/test_support.hpp`: M3's `register_gen_tests` and M6a's `register_iocp_tests` (Windows).
- `tests/unit_tests.cpp`: both registrations, and M3's test arguments (`a.size() >= 2`,
  `binary_path` from the third argument, `extra_paths` from the fourth on).
- `tests/handler_tests.cpp`, `handlers.output_backpressure`: the 200,000 requests are built before
  the connect for the Linux client and for M6a's Winsock client alike (M3's fix, 21938c5). M3's
  failure diagnostics stay on Linux as they were; the Winsock client now reports the same on a
  failure (its first send after its connect, its local port, the bytes sent, the WSA error of its
  send and of its receive, how its receive ended). The server's side of a failure (whether it saw
  the client's port closed, how detection ended, its counters, a worker error) is one helper,
  `server_side_of()`, for both.

Two semantic conflicts that the textual merge did not show, found by building the merged tree on
W, fixed in the merge commit:
- `bench/gen/CMakeLists.txt` built opgen's engine (Linux headers, epoll) wherever `oneport_tls`
  exists, which since M6a includes W. The engine is now built on Linux only, as M3 intended (its
  note: the command line and the report build everywhere).
- `bench/server/worker.cpp`: `expire_dec()`'s route branch (M3's edf2e38, T_dec bounding
  pass-through) calls `relay_report()` from `relay.cpp`, which is Linux only, so W failed to link.
  The branch is now Linux only; no connection on IOCP reaches the route stage, since relay
  dispatch is Linux only (section 2.1) and refused on IOCP.

Checks of bbd13f7 (development checks, not records). "Report lines" counts the lines of the ctest
log that match the shared report pattern (`bench/oneport_record.py`, the same text as
`lab/bin/sanitize.ps1` and `~/lab/p3/sancheck.sh`).

| Host | Build | Libraries | Build | CTest | Report lines |
|---|---|---|---|---|---|
| W | Debug, MSVC 19.51.36246 | release | 0 warnings | 136 passed, 0 skipped, 0 failed | 0 |
| W | ASan (`-DCMAKE_BUILD_TYPE=Release -DONEPORT_SANITIZER=address`) | asan | 0 warnings | the same | 0 |
| L | Debug, clang 22.1.8 | release | 0 warnings | 373 passed, 0 skipped, 0 failed | 0 |
| L | ASan+UBSan | asan | 0 warnings | the same | 0 |
| L | TSan | tsan | 0 warnings | the same | 0 |
| L | MSan | msan | 0 warnings | the same | 0 |

- W: from an exported copy of bbd13f7 (`git archive`, `C:\Users\alext\lab\p3\merge-check\src-bbd13f7`),
  built in `C:\Users\alext\lab\p3\merge-check\bbd13f7\` by `check.cmd` there, Ninja, `ctest -V -j 4`,
  ASan with M6a's `ASAN_OPTIONS` in the vcvars64 environment. 136 entries: M6a's 133 and M3's three
  that build on W (`gen.options`, `gen.quantiles`, `run.test_runner`). The ASan test binary and
  `oneport.exe` import `clang_rt.asan_dynamic-x86_64.dll`; `iocp.cpp.obj` and `worker.cpp.obj`
  reference `__asan_` in 202 and 159 symbol lines, as in M6a. A trial Debug build of the work tree
  before the commit also passed 136.
- L: the work tree `~/lab/p3/one-port` at bbd13f7 (pushed to `lab`, pulled with `--ff-only`), built
  in `~/lab/p3/merge-check/bbd13f7/` by `~/lab/p3/sancheck.sh`, `ctest -V -j 8`, two suites at a
  time (Debug with ASan+UBSan, then TSan with MSan; M2b exhausted L's ephemeral ports with four at
  once), as one lab job under the lab lock (`~/lab/p3/merge-check/check.sh`, job merge-bbd13f7
  through `bench/run/lab_job.sh`). 373 entries, as at M3's end. Each pair took about 134 s, ctest
  94 to 100 s per suite. The test binary and `opgen` of each sanitizer build define the runtime's
  symbols (`nm`: 316 `__asan_`, 173 `__tsan_`, 63 `__msan_`, as in M3). The connection-tracking
  table held 105,081 entries after the first pair (the two suites' connections).

Log sha256 (W, `C:\Users\alext\lab\p3\merge-check\bbd13f7\`; L, `~/lab/p3/merge-check/bbd13f7/`):

    739f0eaf144d78cbcd1d3c42e0a0098ecc0a287c08c4f859641bdf31f4d3919e  W debug-bbd13f7.build.log
    8c38d1b054a7fa4f36245581bb8dc544b40c3eaddf5eb1d86deeba54cd8f0f2d  W debug-bbd13f7.ctest.log
    c3115aaa78722b22cfebff100054c7db6250af7fcc99cffe765e125e83ca2781  W asan-bbd13f7.build.log
    3ec4923624aecd9318168644bf9f2d979476d4a0c301123775067e098bdf92ce  W asan-bbd13f7.ctest.log
    560dede348b5cceb6bf209d8f23dd752bb6e187e0c58d677358e3852da852a70  L debug-bbd13f7.build.log
    628859b2688697b957180b18a0aa8ee81b82aed01f24573ffe9fb3d008014016  L debug-bbd13f7.ctest.log
    0109012140083162e14c16a343188c18e469b026d5eff38ead24ffe01a50ba77  L asan-bbd13f7.build.log
    a04205cf91e9d07a9247e6d7a2a30613c5705c6f9c315c10c637d33bc06d2674  L asan-bbd13f7.ctest.log
    f168859bcdbc8df801dfdd69556978626789ee9f1c51e907145544c033964dcb  L tsan-bbd13f7.build.log
    d7f77c213fb43b1c520c03dbd5c6bbff9b616bc56220634e7358f953f366eca1  L tsan-bbd13f7.ctest.log
    ec65c74c8aeb81ff23535aaaad4c179358a8e757ad4fbc7211be8e2c9e67dd87  L msan-bbd13f7.build.log
    092f0512278507bbb8b3d224e5bcd0569c4af2b1c63356d24b26a9b2e434c081  L msan-bbd13f7.ctest.log

After these checks the worktree `D:\Dev\GitHub\Papers\papers\one-port-m6` was removed and the
branch `m6-windows`, fully merged, was deleted.

## L's connection tracking: NOTRACK for loopback, 2026-10-03

Alex approved on 2026-10-03 the first option of M3's list (above, "L's connection tracking"): raw
table NOTRACK rules for loopback for the length of each lab job. Built in 367e0b0; on L's running
kernel the rules cannot be added, so no job has run with them, and the A/A re-check did not run.

### What was built (367e0b0)

- `bench/run/notrack.sh RECORD COMMAND...`: inside the lab lock, adds exactly
  `-t raw -A PREROUTING -i lo -j NOTRACK` and `-t raw -A OUTPUT -o lo -j NOTRACK` with
  `iptables-nft`, runs the job, and removes exactly those two when the job ends, however it ends (an
  EXIT trap; INT, TERM and HUP end the script so that the trap runs). It then checks that both are
  gone (`-C`) and that the ruleset (`nft -s list ruleset`) equals the one read before the job; a base
  chain of the raw table that the first rule had to create (on L, OUTPUT) is deleted again once
  empty, which nft refuses for a chain that holds a rule. It refuses to run the job if a rule is
  already present (exit 91: a rule it did not add is not its to remove), or if a rule cannot be
  added (exit 93, naming the kernel and whether its module tree is installed). `ONEPORT_NOTRACK=off`
  runs the job with loopback tracked, and says so in the record; nothing falls back to it alone.
  RECORD (JSON): whether NOTRACK was in effect and why not, the iptables version, the kernel, the
  ruleset before, the rules added and when, the connection-tracking count at the job's start and
  end, the removal check, the job's exit status.
- `bench/run/lab_job.sh` runs every job as `lablock bash notrack.sh DIR/NAME.notrack.json COMMAND...`,
  so the rules are added only once the lock is held and never meet another job's. Before taking the
  lock it refuses (exit 93, with its done file) a job that notrack.sh would refuse because the
  running kernel has no module tree, so that a queued job does not fail hours later (241ca80;
  tested on L as t4, and as t5 with `ONEPORT_NOTRACK=off`).
- `window.py`: `notrack_state()` reads the two rules with `sudo -n iptables-nft -t raw -S`
  (`parse_notrack()` also takes the target printed as `CT --notrack`: iptables-nft says "The NOTRACK
  target is converted into CT target in rule listing and saving"); `pin_fingerprint()` records it,
  so every session's fingerprint says whether the rules were in place; every window row has
  `conntrack_count` (before the wait, at the window's start, at its end) beside M3's readings. The
  wait for an empty table stays as a safety check. `aa.py` prints a session whose loopback is
  tracked; `journal.py` counts the windows run with NOTRACK and takes `--milestone`.
- `run.test_runner` has 25 checks (the new one: the parser on rule listings with both rules, one,
  none, the CT form, and lookalike rules).

### What L showed (read-only, 2026-10-03)

- `iptables -V`: "iptables v1.8.13 (nf_tables)"; `/usr/bin/iptables` links to `xtables-nft-multi`.
  Docker 29.7.2's chains (DOCKER, DOCKER-BRIDGE, DOCKER-CT, DOCKER-FORWARD, DOCKER-INTERNAL,
  DOCKER-USER) are in iptables-nft's `nat` and `filter` tables, so Docker uses iptables-nft. The
  legacy variant cannot load its tables (`ip_tables` is not available, below).
- The raw table (`table ip raw`) held one empty base chain, PREROUTING, policy accept, and no
  OUTPUT chain; no Docker chain is in it. The two rules would be appended to the base chains and
  touch no Docker chain.
- No container exists (`docker ps -a` lists none). Docker's nat OUTPUT jump excludes 127.0.0.0/8,
  and the filter INPUT policy is ACCEPT with no connection-state rule, so untracked loopback packets
  would pass as before. While the rules are in place, a container port published on a local
  address other than 127.0.0.0/8 and reached from the host would lose its DNAT; there is none.

### The blocker: the running kernel cannot load the module NOTRACK needs

The first append failed, with iptables' "Warning: Extension CT revision 0 not supported, missing
kernel module?" and "RULE_APPEND failed (No such file or directory): rule in chain PREROUTING".
- iptables-nft implements NOTRACK with the CT target, the kernel module `xt_CT`; nft's own
  `notrack` needs `nft_ct`. In the running kernel's configuration both are modules
  (`CONFIG_NETFILTER_XT_TARGET_CT=m`, `CONFIG_NFT_CT=m`, `/proc/config.gz`), and neither is loaded.
- The running kernel is 7.2.3-arch1-2, booted 2026-09-12 13:32. pacman upgraded `linux` from
  7.2.3.arch1-2 to 7.2.6.arch2-1 on 2026-09-16 (`/var/log/pacman.log`), and `/lib/modules` holds
  only 7.2.5-hardened1-1-hardened and 7.2.6-arch2-1. So no module that is not already loaded can be
  loaded until L boots an installed kernel.
- A reboot is outside my authority, and restoring the old module tree is a system change outside
  the install policy. I stopped there, as the brief says for a rule that cannot be added.

Tests of the scripts on L, under the lab lock (`~/lab/p3/notrack-test/`, copies byte-identical to
367e0b0's `notrack.sh` and `lab_job.sh`; `probe.sh` lists the raw rules, opens and closes 200
loopback connections, and reads the table's count around them):
- t2, the default: the first append failed, the job did not run (exit 93), no rule was left, the
  ruleset was the same before and after (`nft -s list ruleset`, md5 cd1e03c3f23767a4f7df31cb05c9b314
  both times), and the record says `notrack: false` with the reason, kernel 7.2.3-arch1-2, its
  module tree missing.
- t3, `ONEPORT_NOTRACK=off`: the job ran; its 200 loopback connections took the table from 3 to 203
  entries, so loopback is tracked; the record says `notrack: false`, reason `ONEPORT_NOTRACK=off`.
- Not run, since no rule can be added: the add path, the removal after a successful add (with the
  OUTPUT chain's deletion), the refusal of a rule already present, and a job stopped by a signal
  with the rules in place. They must run once, on a job with no window, before the first job that
  relies on them.

sha256: `t2.notrack.json` 42328e03928219046887362016b3a0278ba0123ec5a5f948a78020ae09e2103c, `t2.log`
1407df53157bd0cb58be466172611eeb68de19d0942f0d5f4e9c7fccb613890f, `t3.notrack.json`
e92a918eed154ac44b17a2bde90e11ce5683fbf4465693eb2e4e338e249723ac, `t3.log`
a43330f32255f2195548dfd3b46f279d2549c07a50fe568535ee1c216dc8a588, `probe.sh`
4b51aa4da456332acb3ea92cadb729c5e89d339cf39c781c1d2733db5c460d8f.

### The A/A re-check: not run

The re-check (churn HTTP/1.1 on epoll and io_uring, keep-alive TLS on io_uring, dedicated mode)
was to measure the spread and the time per window with NOTRACK. Without the rules it would repeat
M3's conditions, so it was not run: no window ran, and nothing was journaled. There is no spread
with NOTRACK and no time per window with NOTRACK to report; the figures of M3 (above) stand,
with about 125 s of table wait before each churn or open-loop window. No window timed one-port
mode.

### For Alex: a reboot of L

NOTRACK needs L to boot an installed kernel. What that decides beyond NOTRACK:
- Every development number so far (M0 to M3, and the merge checks of bbd13f7) ran on
  7.2.3-arch1-2. The installed kernels are 7.2.6-arch2-1 and 7.2.5-hardened1-1-hardened; which one
  boots is Alex's choice (the bootloader's default was not read). Engineering numbers before the
  code freeze may change with it; the freeze's records and the pilot run on whichever kernel then
  runs.
- The frozen text cites Linux v7.2 source lines (WL7) and has the skb caches read again at the code
  freeze (section 9.1); both installed kernels are 7.2 releases. `K_BASE` and every B3 window must
  run on one kernel.
- B3: WL7's Ks is the host-wide growth of `Slab`. With loopback tracked, each pending connection
  also holds a connection-tracking entry, an `nf_conntrack` slab object of 256 bytes (`objsize` in
  `/proc/slabinfo`, read 2026-10-03), which is in Ks for every system and for `K_BASE` alike. M3's
  two ophold windows ran tracked. Once NOTRACK works, every B3 window and `K_BASE` must run in one
  state, all with it or all without.
- Until the reboot, any kernel feature on L that needs a module not already loaded is
  unavailable.
- Until then, a job through `lab_job.sh` stops with exit 93 unless it is started with
  `ONEPORT_NOTRACK=off`; with it the job runs tracked, the wait applies, and the time plan of M3
  holds.

## M4a, 2026-10-03

M4a: step 0 (the host change, the coordinator's decision on M6a's reading 7, NOTRACK's first run on
kernel 7.2.6 and the A/A re-check), then the five proxies of M3 and B3: their installation, their M3
and B3 configurations, a probe per proxy, the hand-off runner, and a few development windows of the
server's one-port relay against them. Nothing in this section is a result: every window is
development data, journaled as such, and the suites are development checks, not records.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| 76ebac2 | fix: notrack.sh writes its record when it refuses a job (exit 90, 91), and lab_job.sh writes the done file of a job stopped by a signal to its process group |
| d1d7665 | fix: the B2(d) audit reports a pending connection that holds a data buffer while no byte has arrived in IOCP's posted receive form; test iocp.silent_buffer |
| 55b2cb8 | chore: pin the five proxies of section 2.3 in pins.cmake, and bench/competitors/install.sh |
| e528256 | feat: the proxies' M3 and B3 configurations, competitors.py, probe.py, the hand-off runner, guard_pair, stop_on_signals; tests run.test_competitors |
| 7001e91 | docs: hypotheses.md revision log, the host change before the code freeze, and the coordinator's decision on M6a's reading 7 |
| c357f3a | feat: journal.py --kind m3 journals a hand-off job |
| 097cec4 | test: gen.failures holds its refused port bound and not listening while opgen connects to it |
| 7c75628 | docs: hypotheses.md revision log, the host-change entry's MHz drift range corrected (2.9% to 58%) |

Checks (below): each code commit up to e528256 built alone from a clone of the lab remote on L
(Debug, clang 22.1.8, Ninja, no warning) and passed its own suite; 7c75628's suites on L (Debug and
ASan+UBSan, green), after 7001e91's ASan+UBSan suite failed twice beside its Debug suite, a test race
that 097cec4 fixes; 7001e91's suites on W (Debug, ASan, green). After 7001e91 the code changes only in
`bench/run/journal.py` (no test runs it) and in the Linux-only part of `tests/gen_tests.cpp`, so W's
result stands for 7c75628. Nothing is pushed to origin; the `lab` remote has every commit.

### Step 0, 1: the host change (revision log)

L moved from 7.2.3-arch1-2 to 7.2.6-arch2-1 by kexec at 2026-10-03 11:30:41 (Alex's decision; boot
-1 ended 11:30:36). The revision-log entry "Host change before the code freeze" (7001e91) holds what
was read after the switch (the merged skb cache `:0000512` with `pool_workqueue` and `sgpool-16`,
aliases 2, listed as `pool_workqueue`; `skbuff_head_cache` and `skbuff_small_head` under their own
names; `CONFIG_SLUB_DEBUG=y`, `CONFIG_SLAB_MERGE_DEFAULT=y`; `kernel.io_uring_disabled` 0; page size
4096; the command line unchanged), the split of data by kernel, and the check of every cited v7.2
line at v7.2.6:
- `patch-7.2.6.xz` (sha256 2aef3c30a571ed806c69e90428b229409a43c235aa2540a24593b7e7a8b126cf) equals
  its line in kernel.org's `sha256sums.asc`, whose signature verified good (autosigner key B886 8C80
  BA62 A1FF FAF5 FDA9 632D 3A06 589D A6B1, fetched by WKD into a scratch keyring on W). A script
  parsed every hunk of the six files it touches; the six files were also fetched at both tags from
  the stable tree and their 31 cited slices (the frozen text's and the proposal's) compared: all
  equal. Line numbers move only in `net/core/skbuff.c` (+2 from line 5176), `mm/slub.c` (+6) and
  `kernel/workqueue.c` (line 7995 at 8025).

**Found: section 7's MHz rule fails every window on 7.2.6 (open, for the coordinator and Alex).**
Between 7.2.3 and 7.2.6 `drivers/cpufreq/amd-pstate.c` changed the floor it sets for the
performance policy: MinPerf was the nominal performance and is now the BIOS's minimum where one
exists (both files fetched from git.kernel.org; the diff's comment: "When bios_min_perf is
available, users have profiled their workloads to understand the best idling frequency. Use that
instead."). On L now (amd-pstate-epp, active, the performance governor, boost off):
`scaling_min_freq` 1,102,866 kHz (= `amd_pstate_lowest_nonlinear_freq`), `scaling_max_freq`
3,201,000 kHz; an idle CPU's `cpu MHz` reads 1102.9, a loaded one about 3169. `pin.sh`'s
`mean_mhz`, which `window.py` takes as the session's value (t1.py's rule; M3 reading 8), is read
with the host idle, so it reads 2,006 to 2,522 MHz, and each of M4a's 108 windows drifts 2.9% to 58%
from it (the least in sslh-ev's windows, whose CPUs were partly idle, so their own mean read low). In
M3 on 7.2.3 the same reading gave 3,172 to 3,186 MHz against 3,165.9 to 3,184.3 MHz loaded. Within
any A/A session of the re-check (aa-nt3), whose windows load every CPU they read, the windows' MHz
moved at most 0.016%, and the throughput is M3's (below).
Options, none taken: (a) restore 7.2.3's floor for the length of each lab job by writing
`scaling_min_freq` = `scaling_max_freq` on the used CPUs (a non-persistent sysfs write, as `pin.sh`
writes the governor; a change of the lab procedure, Alex's); (b) a reading that takes the session's
value as the loaded MHz of the session's first window; (c) leave it, and no window on L is valid.
The floor also matters beyond the rule: in open-loop cells (C3, the M family's TTFB) the server's
core idles between exchanges, so its frequency now ramps up from 1.1 GHz, which it did not on 7.2.3.

### Step 0, 2: the coordinator's decision on M6a's reading 7

In the revision log (7001e91): rule E may choose only IOCP receive forms that satisfy B2(d), so the
posted form leaves rule E, rule E has nothing to choose on IOCP (the zero-byte form stays), section 8
step 4 runs no sessions for it, section 9.2 names the zero-byte form, and section 10's secondary cell
"the receive form rule E did not choose" is the posted form, descriptive, its B2(d) violation stated.
M6a's "Open for the coordinator" item on it is closed by that entry.

Code and tests (d1d7665):
- `Worker::audit_pending` (handlers.cpp): its exemption for an empty buffer that a posted receive
  writes into (written for io_uring's receive into the room of a buffer the connection holds) now
  needs a byte received (`bytes_received > 0`). io_uring takes such a buffer only after bytes arrived,
  so Linux behaviour is unchanged (the L suites pass, below). The IOCP worker audits a posted-form
  connection right after posting its receive (`pending_io`), the state it waits in; before, the audit
  ran only after a read, so a silent posted-form connection was never audited.
- `iocp.silent_buffer`: a silent connection closed at T_dec in each receive form and detection mode;
  the zero-byte form holds no data buffer (replay and peek), the posted form in replay is reported
  holding the handler's buffer (`buffer_while_silent`), in peek no buffer is posted during
  detection. Passed on W in the work tree's trial build (88 IOCP entries, 0 warnings) and in 7001e91's
  checks.
- Comments: `config.hpp`, `iocp.cpp`, `worker.hpp`, `harness.hpp`, `iocp_tests.cpp` no longer call the
  posted form a rule E option. The flag stays.

### Step 0, 3: NOTRACK's first run on 7.2.6

After the kexec the raw table did not exist at all (before it, it held an empty PREROUTING chain), so
the add creates the table and both base chains and the teardown must delete all three: a path never
run before. One lab job with no window per path (`~/lab/p3/notrack-726/`, scripts of e005709):
- n1, add and removal: both rules added (`iptables-nft -t raw -S` listed them during the job), 200
  loopback connections left the conntrack count at 10 (loopback untracked), and the teardown removed
  both rules and deleted OUTPUT, PREROUTING and the table; `rules_gone` and `ruleset_restored` true.
- n2, refusal: the job's command was a second `notrack.sh`, which found the outer rules and refused
  (exit 91) without touching them; the outer one then removed them.
- n3, a signal: SIGTERM to the job's process group (`kill -TERM -- -PGID`, the pid file's) while the
  rules were in place. `notrack.sh` ran its teardown (job_exit 143, rules gone, ruleset restored).
  During the job the lock file was open in flock, `notrack.sh` and the job (inherited descriptor), so
  the lock outlives flock's death until the teardown ends; the lock was free after.
- In each, `nft -s list ruleset`, Docker's four tables (`ip nat`, `ip filter`, `ip6 nat`, `ip6 filter`)
  and the table list were byte-identical before and after.
Two gaps found and fixed (76ebac2): the refusal wrote no record (now it does, with its reason), and
`lab_job.sh` killed by SIGTERM wrote no done file (now it traps the signal, waits at most 60 s for the
record to name the removal, and writes `{"exit": 143, "signal": "TERM"}`). Both fixes ran again on L
before the commit (`~/lab/p3/notrack-726/fix/`, n2 and n3: the inner record names its refusal; the
done file is written). Every window and probe job of M4a ran through `lab_job.sh` with NOTRACK on
(aa-nt1 to aa-nt3, probes1 to probes3, m3dev1, checks1, rerun1, checks2), and each record shows both
rules removed and the ruleset restored; the downloads, the installs and one test run used the lock alone.

Record sha256 (first run, then the fix's): n1.notrack.json
903592caf63f250400599062978e2bb7c4c40eb6817dc7926a18300ecd090c1f, n2.notrack.json
0c696ddecada381a20967a0dd203ccc8871c8166caaa236b321ff13f42565304, n3.notrack.json
e959d03faa2a3c126195b48e59f09b417d28e85b8d557059418b08852566f0a8; fix/n2-inner.notrack.json
ca0333cd7d91af91749b7b5ee84fef9163b84372ed97a02d23205de1e4454db5, fix/n2.notrack.json
1ef5ae44446918efb4f8926715f100b2df1a0e96abc8b9de5c360b73639970c6, fix/n3.notrack.json
5948b36a47b993d7822facf6d96901c01b6df2c21e65479a2efe473cf22bb34f, fix/n3.done
040dafe7d1db633f1abe3669d9629ea8849b7f0b67e2ff61fd9444a3ff2b1fc5.

### Step 0, 3: the A/A re-check with NOTRACK

Dedicated against dedicated only, from a clone of the lab remote at 76ebac2 (Release, clang 22.1.8),
`aa.py` with K_SRC 16, under the lock, `pin.sh` and NOTRACK, journaled as development (Papers
52d39da). Three jobs: aa-nt1 (seed 801), stopped after 16 windows once every window showed the MHz
failure; aa-nt2 (seed 802), stopped after 9 windows: its arm-B servers could not bind, because aa-nt1's
arm-B server was still running (below); aa-nt3 (seed 803), complete: 4 sessions per cell, 48 windows.

All 48 of aa-nt3's windows are invalid by the MHz rule and by nothing else (step 0, 1). Ignoring that
rule, development data:

| Cell | Job | Sessions | Median | Range | Log SD | Outside [0.98, 1.02] | Metric per window |
|---|---|---|---|---|---|---|---|
| churn, HTTP/1.1, epoll | aa-nt3 | 4 | 1.0026 | 0.9954 to 1.0040 | 0.0040 | 0 | 44,270 to 44,887 conn/s |
| churn, HTTP/1.1, epoll | M3 aa1 | 6 | 1.0013 | 0.9976 to 1.0032 | 0.0020 | 0 | 44,495 to 44,949 conn/s |
| churn, HTTP/1.1, io_uring | aa-nt3 | 4 | 0.9988 | 0.9971 to 1.0008 | 0.0015 | 0 | 52,392 to 53,242 conn/s |
| churn, HTTP/1.1, io_uring | M3 aa3 | 6 | 1.0007 | 0.9968 to 1.0042 | 0.0028 | 0 | 52,776 to 53,372 conn/s |
| keep-alive, TLS, io_uring | aa-nt3 | 4 | 0.9960 | 0.9924 to 1.0047 | 0.0054 | 0 | 106,075 to 108,665 req/s |
| keep-alive, TLS, io_uring | M3 aa4 | 8 | 0.9998 | 0.9823 to 1.0197 | 0.0108 | 0 | 104,153 to 107,781 req/s |

- With 4 sessions the spreads are within M3's order (churn epoll wider, the other two narrower); the
  throughput per window is M3's. Nothing here enters a rule.
- NOTRACK in every session's fingerprint; the conntrack wait took at most 0.0003 s before any window,
  the table held at most 7 entries at any window's start or end, and nothing was dropped.
- Time per window: consecutive windows started 6 s or 7 s apart (whole-second timestamps), 294 s for
  the 47 intervals, 6.3 s per window (1 s warm-up and 5 s window, and the start, probe and stop). In M3 a churn or open-loop
  window waited a median 122 s to 126 s for the table first (about 125 s per window, M3's time plan).
- Every window saturated the server: its core at least 99.6% busy, the generator rule at most 39.3%.

**Found and fixed: a stopped job left its servers running.** The window runner starts each server in
a session of its own, so a SIGTERM to the job's process group (how jobs are stopped) never reached
it, and Python's default SIGTERM ended the runner before its `finally` blocks stopped the server.
aa-nt1's arm-B server (port 20100) and aa-nt2's arm-A server (20000) kept running; they were found
with `ss` and stopped by their pids. `window.stop_on_signals()` (e528256) turns SIGTERM, SIGINT and
SIGHUP into `SystemExit`, so the `finally` blocks run; `aa.py`, `b3.py`, `ksrc_sweep.py`,
`handoff.py` and `probe.py` install it. Tested on L at 835bb44 (job sigtest1, no row written): an
`aa.py` job stopped by SIGTERM to its process group during its first window left no listener on
ports 20000 to 20105, its done file reads exit 143 and signal TERM, and its NOTRACK record shows both
rules removed and the ruleset restored (sigtest1.notrack.json sha256
ecd62a66968d33014da18428fb61adfb319039fb474519a51dcb2d046067c232; made after the archive below, its
files stay in `~/lab/p3/m4a/`).

### The proxies: installation

Downloaded on L into `~/opt/src` from the official release URLs (`~/lab/p3/m4a/fetch.log`, under the
lock); every sha256 pinned in `bench/cmake/pins.cmake` (55b2cb8), which changes the pins file's hash
the gate reads (no record exists yet). `bench/competitors/install.sh` checks each archive against its
pin and builds into `~/opt` (`~/opt/build/logs/<system>.log`); it ran under the lock. No package was
added: libev 4.33-5, libconfig 1.8.2-2, pcre2 10.48-1 and their headers, gcc 16.2.1 and go1.27.1 were
on L.

| System | Version | Archive sha256 | Published check | Build | Binary sha256 |
|---|---|---|---|---|---|
| nginx | 1.30.5 (nginx.org tarball) | 6c20565aa2325cb82216ae804f4a4ff1875179014759a381c42ddc8e11c4906d | none published; the `.asc` verified good, Sergey Kandaurov's key (nginx.org/keys/pluknet.key, D678 6CE3 03D9 A902 2998 DC6C C846 4D54 9AF7 5C0A) | `--with-stream --with-stream_ssl_preread_module --without-http --with-cc-opt=-O2`, gcc 16.2.1 | 8ba2ed7e23259003c2ab52f6b8555e5c5f8e899d9ea3b42e88c6f8316fb36f7e |
| HAProxy | 3.4.6-56332c5 (2026/09/28) | 791e1815f8af6e8b850a227a9a0a190f3d3478c9e8d38a0f51c98b7f4bfe368b | `.sha256` beside it, equal | `make TARGET=linux-glibc` (CFLAGS `-O2 -g -fwrapv`), no OPTIONS | 1b7923189364126e77499899674dd6e1dcd289d598acf77828ef13e0a7851a16 |
| Envoy | 1.39.2 (018f6bf0, RELEASE, BoringSSL) | d2f1a9f4f19b7fc064e75b4e52d191754c49a4de1ae2145462c0c7e19a860e1b | `checksums.txt.asc` and the GitHub asset digest, equal; signature good ("Envoy maintainers", 0AFC E836 BA4D 1D35 763C 8523 D8CD C375 0181 F31F, from keyserver.ubuntu.com, no trust path) | the release binary as it is | the archive's |
| caddy-l4 | v0.1.2 = 42db5690 on Caddy v2.11.4 | (Go modules: go.sum, sha256 2e01b4677445cdd6cfa9360d90a0a4162c9b4450a3af1ff5a2019b709b11d5ab) | the Go checksum database (GOSUMDB sum.golang.org, GOPROXY proxy.golang.org) | xcaddy 0.4.7, go1.27.1, `GOTOOLCHAIN=local`; xcaddy's `-ldflags -w -s -trimpath -tags nobadger,nomysql,nopgx`; the commit resolved to the v0.1.2 tag | fcbeb330bb90245947ad21aed77ea64074ae14b2432bd3fe4ea388275a2bbe6c |
| xcaddy | 0.4.7 (latest, 2026-08-17) | e6d2882fb751b9697cdb73b0da8b8a7393f0d7f2cb47afa79a23982c4c61d2d4 | `checksums.txt` (SHA-512) and the GitHub digest, equal | unpacked | |
| sslh-ev | 2.3.1 (tag d39388d1) | 51a5516ec5cb01823633b4d8cacdeee4efa0c56ef620d1c996d4f52ca51a601b | none published; the author's tarball's tree equals the tag archive's (`diff -r`) | `./configure; make sslh-ev` (ENABLE_REGEX, LIBCONFIG, libev, `-O2`; links libcap and libbsd, found by configure) | 3ec886cb943b08750ac9d72aa679fa924b858a13710bda863a907f47547fe92e |

- nginx's level: its `auto/cc/gcc` defaults to `-O`; nginx.org's own Linux package of 1.30.5
  (`nginx_1.30.5-1~trixie_amd64.deb`, its `nginx -V`) builds with `-O2` (and hardening flags), and
  HAProxy's and sslh's Makefiles default to `-O2`, so the three proxies built from source share `-O2`.
  The modules: stream and ssl_preread, the only ones the configurations use.
- caddy-l4's build: `bench/competitors/caddy-l4/go.mod` (sha256
  e2b2552c3b2b75442c061535c94818ea5396d6cc3409833d7d33411087f11b54) and `go.sum` (581 lines) are the
  build's own, the record of every module used. Caddy v2.11.4's and caddy-l4's `go.mod` ask go 1.25.1.
  `caddy list-modules` shows the layer4 tls, http, ssh and regexp matchers and the sni and alpn
  handshake matchers Appendix B's cases need.

### The proxies: configurations

`bench/competitors/<system>/m3.*` and `b3.*` (e528256), rendered per run by `competitors.py`. Every
non-default setting carries a comment citing Appendix B, section 1 or 5.3, WL7, the proposal or the
system's own documents; plumbing (pid file, logs, foreground) is marked as such. Highlights:

| System | M3 | B3 adds |
|---|---|---|
| nginx | `worker_processes 1`, `worker_cpu_affinity` CPU 14, `multi_accept on`, `ssl_preread on`, `map $ssl_preread_server_name` (oneport.test to the TLS stub, default to the HTTP stub), `preread_timeout 3s`, no access log, backlog default (511) | `worker_connections` and `worker_rlimit_nofile` 20,000, `listen ... backlog=10000`, `preread_timeout 60s`; buffers kept |
| HAProxy | `mode tcp`, `inspect-delay 3s`, `accept if { req.ssl_hello_type 1 }` and `accept if HTTP`, `use_backend` on `req.ssl_sni`, `default_backend` HTTP stub, no log, one thread from taskset, timeouts unset (the startup warning "missing timeouts" for the frontend and each backend, seen in the probes' stderr), no splice | global `maxconn 20000` (also the backlog), `inspect-delay 60s`, `option use-small-buffers` in both backends |
| Envoy | `--concurrency 1`, `--disable-hot-restart`, tls_inspector, a chain by `server_names` and `transport_protocol: tls`, the default chain to the HTTP stub, tcp_proxy, `listener_filters_timeout 3s`, circuit breaking off (the FAQ's 1000000000 at both priorities), no admin and no access log, default statistics | `tcp_backlog_size 10000`, `listener_filters_timeout 60s`, `per_connection_buffer_limit_bytes 32768` on the listener and both clusters, tls_inspector `initial_read_buffer_size 256` |
| caddy-l4 | Caddyfile: `matching_timeout 3s` (its default too), `@tls tls sni oneport.test` to the TLS stub, a route with no matcher to the HTTP stub, admin on a run port, log level default (INFO); GOMAXPROCS 1 from taskset; Caddy's adaptation to JSON kept per run (`adapted.json`) | `matching_timeout 60s` |
| sslh-ev | `verbose-connections 0`, `numeric: true`, `log_level 0` on both protocols, `timeout 3`, `on-timeout "http"`, tls with `sni_hostnames` then http last | `timeout 60`; `max_connections` unset |

Every process of a front runs on CPU 14 (taskset; nginx's master and worker, Envoy's and Go's
threads), with the soft open-file limit raised to the hard one (524,288), in M3 as in B3 and for both
arms alike. The stub behind every front, the server's included, is `oneport --mode stub --backend
epoll --workers 2` on CPUs 10 and 12.

### The proxies: probes

`bench/competitors/probe.py` with a `probe.sh` per proxy (e528256): fresh stub and front per check, as
a window starts them. Routes: `opgen --probe` through the front with the TLS stub exchange and with
HTTP/1.1, and the stub must have accepted exactly those two. Silent and partial: a client that sends
nothing, or WL7's 108-byte partial ClientHello, watched 6 s (M3) or 32 s (B3) for the front's close and
for a new socket on the stub's ports (`/proc/net/tcp`, sockets present before the watch excluded), which
must agree with the stub's accept count. The expected behaviour per system comes from the survey; where
it says nothing (sslh-ev in M3) the probe records only. Job probes3 (~/lab/p3/m4a/probes, the development
tree that became e528256), all twelve runs exit 0:

| Front | M3 routes | M3 silent (3 s timer) | M3 partial | B3 routes | B3 silent and partial (60 s) |
|---|---|---|---|---|---|
| server's relay | both, stub 2 | closed at 3.044 s, not routed | closed at 3.025 s, not routed | both | held 32 s, not routed |
| nginx | both, stub 2 | closed at 3.016 s, not routed | closed (reset) at 3.053 s | both | held |
| HAProxy | both, stub 2 | routed to the HTTP stub at 3.075 s, held | routed at 3.059 s, the client closed at 3.016 s | both | held |
| Envoy | both, stub 2 | closed at 3.001 s, not routed | closed (reset) at 3.007 s | both | held |
| caddy-l4 | both, stub 2 | closed at 3.000 s | closed at 3.001 s | both | held |
| sslh-ev | both, stub 2 | held 6 s, not routed (observed only) | held, not routed (observed only) | both | held |

- sslh-ev, at runtime: with `timeout 3` neither the silent nor the partial client was closed or routed
  in 6 s, which confirms the survey's reading of its code (2.8: the probe timeout is checked only on
  read activity; "Runtime behaviour: not verified").
- An earlier run judged the server's B3 partial check "routed at 0.001 s" with no accept: a TIME-WAIT
  socket of HAProxy's M3 partial check on the same port block. The probe now ignores sockets present
  before the watch and requires the two observations to agree.

### Runner integration

- `bench/run/handoff.py` (e528256): a hand-off window in section 4.1's placement, and sessions X Y Y X
  of the server's one-port relay (arm A, ports 22000, stub 22010) against one proxy (arm B, 22100,
  stub 22110). Per window: the source block, the conntrack wait, the stub and the front started fresh
  (pid files), the probe through the front, opgen on CPUs 2 to 9 (8 workers, C = 64), at the markers
  the CPU time of the front's whole process group and of the stub, `/proc/stat`, MHz, interrupts; the
  front stopped by its process group, the stub's counters. The row: conn/s; CPU per connection of the
  front, of the backend and of both (WL6); the backend cores' busy share with section 7's 90% rule;
  listen overflows recorded, not a rule in M3; section 7's other rules through `window.finish` with the
  hand-off placement. The session ratio is server / proxy.
- `window.py`: `Placement` (in-process and hand-off), taken by `finish()` and `probe()`;
  `guard_pair`, checked per session: dedicated against dedicated, or the one-port relay against a
  proxy, and nothing else (one-port against dedicated refused; in M4a dedicated against a competitor
  refused too, so no FC5 pair can arise); `stop_on_signals`.
- `competitors.py`: rendering, start under taskset in a session of its own with the open-file limit
  raised and a pid file, readiness read from `/proc/net/tcp` (no connection, which HAProxy would route
  to its default backend at the end of its inspect-delay), stop by process group.
- `journal.py --kind m3` (c357f3a).
- Not built in M4a: B3 with a proxy as the system (`b3.py`: U over the proxy's processes, the stub left
  out, the partial case), caddy-l4's heap profile before each sample, and section 10's untimed
  `perf trace -s` windows.

### Development windows: the server's relay against the proxies

Job m3dev1 (seed 811): one session of each of the ten M3 cells, the server in one-port mode with relay
dispatch on epoll (replay, the user-space relay copy, timers 3 s) against each proxy in its M3
configuration, from a clone at 7001e91 (Release, clang 22.1.8), NOTRACK on, journaled as development
(Papers 52d39da). Only one-port mode was timed against the proxies; dedicated mode never was, so no
FC5 pair exists. All 40 windows are invalid by the MHz rule; the sslh-ev windows also by the error rule.
Ratios over windows invalid by the MHz rule alone, server / proxy, one session each:

| Cell | Server's relay, conn/s | Proxy, conn/s | Ratio | Proxy CPU per connection (front) |
|---|---|---|---|---|
| TLS by SNI, nginx | 12,919 and 12,953 | 12,616 and 12,637 | 1.0245 | 49.7 to 49.9 us (relay 48.3 to 48.6) |
| TLS by SNI, HAProxy | 12,921 and 12,917 | 12,378 and 12,504 | 1.0384 | 54.1 to 54.8 us |
| TLS by SNI, Envoy | 12,839 and 12,889 | 6,081 and 6,129 | 2.1071 | 129.6 to 130.9 us |
| TLS by SNI, caddy-l4 | 12,863 and 12,854 | 6,547 and 6,532 | 1.9663 | 119.4 to 119.5 us |
| TLS by SNI, sslh-ev | 12,925 and 12,787 | 9,215 and 9,518 | none (errors) | 68.3 to 68.8 us |
| HTTP/1.1, nginx | 13,007 and 12,917 | 12,787 and 12,697 | 1.0173 | 49.0 to 49.3 us |
| HTTP/1.1, HAProxy | 12,952 and 12,901 | 12,145 and 12,331 | 1.0563 | 55.3 us |
| HTTP/1.1, Envoy | 12,942 and 12,991 | 6,245 and 6,350 | 2.0590 | 124.1 to 126.8 us |
| HTTP/1.1, caddy-l4 | 12,982 and 12,928 | 6,808 and 6,802 | 1.9038 | 114.0 to 114.4 us |
| HTTP/1.1, sslh-ev | 12,891 and 12,970 | 10,131 and 10,256 | none (errors) | 60.6 to 60.8 us |

- Every front was saturated (CPU 14 at least 99.6% busy) except sslh-ev (92.8% to 96.2%); the backend
  cores 2% to 38% busy; the generator rule at most 17.1%; no connect failed and no listen overflow in
  any window. WL6 (front and backend) per connection: the relay 70.1 to 70.7 us; nginx 70.9 to 71.8;
  HAProxy 77.4 to 79.0; caddy-l4 137.5 to 143.0; Envoy 146.5 to 152.6; sslh-ev 84.5 to 92.5.
- nginx is within 2.5% of the relay in this one session; the margin of the frozen M3 test is 1.00, and
  16 sessions decide it. Development data; no claim.
- **sslh-ev loses exchanges at saturation (open).** In each of its four windows 309 or 310 exchanges
  (0.60% to 0.67%) timed out at opgen's 1 s with no connect failure, no reset and no listen overflow or
  drop; the others were fast (median TTFB 0.15 ms). Each stalled exchange holds a client slot for 1 s,
  about 62 of the 64 slots on average, which is what sets sslh-ev's rate. sslh-ev logged nothing
  (verbosity 0). The cause was not isolated. As configured, every sslh-ev window is invalid by section
  7's 0.1% error rule, so both sslh-ev cells of M3 would have no valid session (M5).
- Time per window: 6.2 s for the relay's windows, 6.5 s to 7.5 s for the proxies' (their start), apart
  from the job's first, which waited for 30,648 tracked entries left by a test run made under the lock
  outside `lab_job.sh` (so tracked) to expire.

### Tests

- `run.test_competitors` (`bench/competitors/test_competitors.py`; 18 checks): every configuration
  renders with every field filled and holds its kind's settings (timers, WL7's limits and buffers in B3
  only, M3's settings); the command lines; the affinity mask; the LISTEN reader; `guard_pair`'s allowed
  and refused pairs; the partial opening (108 bytes); the probe's judgement (early, late, routed,
  disagreeing observations); the TIME-WAIT exclusion; the hand-off row's backend rule and WL6; the
  session ratio. On Linux with `--build`: the probe of the server's relay (routes, silent and partial
  closed at 3 s) and one short hand-off window of the relay per M3 protocol (stub, front, probe, opgen,
  readings, the row). On W it runs the pure checks.
- `iocp.silent_buffer` (W, above).

### Checks

| Host | Build | Commit | Build | CTest | Report lines |
|---|---|---|---|---|---|
| L | Debug, clang 22.1.8 | d1d7665, alone | 0 warnings | 373 passed | 0 |
| L | Debug | 55b2cb8, alone | 0 warnings | 373 passed | 0 |
| L | Debug | e528256, alone | 0 warnings | 374 passed | 0 |
| L | Debug | 7001e91, beside ASan+UBSan | 0 warnings | 374 passed | 0 |
| L | ASan+UBSan | 7001e91, beside Debug | 0 warnings | 372 passed, 2 failed (`gen.failures`, `server.kernel_uring_recv_select`) | 0 |
| L | ASan+UBSan | 7001e91, alone | the same build | 374 passed; each of the two 10 of 10 alone, and 10 of 10 in Debug | 0 |
| L | Debug | 7c75628, beside ASan+UBSan | 0 warnings | 374 passed | 0 |
| L | ASan+UBSan | 7c75628, beside Debug | 0 warnings | 374 passed | 0 |
| W | Debug, MSVC 19.51.36246 | 7001e91 | 0 warnings | 138 passed | 0 |
| W | ASan | 7001e91 | 0 warnings | 138 passed | 0 |

- W: an exported copy of 7001e91 (`C:\Users\alext\lab\p3\m4a-check\`), MSVC 19.51.36246, Ninja,
  `ctest -V -j 4`, ASan with M6a's `ASAN_OPTIONS`; 138 entries (M6a's and M3's, plus `iocp.silent_buffer`
  and `run.test_competitors`).
- L: each code commit from a clone (`~/lab/p3/m4a-check/commits/<sha>/`, `ctest -j 6`), then the work
  tree with `~/lab/p3/sancheck.sh` (Debug and ASan+UBSan at once, `ctest -V -j 8`), as lab jobs
  (checks1 at 7001e91, rerun1, checks2 at 7c75628; NOTRACK on).
- The two failures of 7001e91's ASan+UBSan suite were one race between two tests run at once (tests
  160 and 164 finished one after the other): `gen.failures` bound a loopback port, closed it, and sent
  14,747 connects to it in 200 ms, expecting each refused; `server.kernel_uring_recv_select`'s loopback
  pair was given that freed port for its listener, so it accepted opgen's connections (its receive
  completed before any byte of its own, "a receive completed with no data") and opgen's connects
  succeeded ("refused: completed 0, connect failures 14747", with other errors beside them). The race
  is M3's (0a21e7c's `refused_port()`), not M4a's code; 097cec4 keeps the refused port bound and not
  listening while opgen runs, which still refuses every connect and holds the port.

Log sha256 (L, `~/lab/p3/m4a-check/`; W, `C:\Users\alext\lab\p3\m4a-check\7001e91\`):

    995a28441c1d4bd96b0c274c205c3704e50a2ee8ee45a670ddf7b2f1e12ab058  L commits/d1d7665/debug-d1d7665.ctest.log
    305e73aadd4c145bb4d7a5ed6486d20baf956c1bd86ffffbeef1c953fab8bc21  L commits/55b2cb8/debug-55b2cb8.ctest.log
    75ea275353af121b219fc5ab6d445cd89d6a13ea2227b588fe5c8220f8db87b6  L commits/e528256/debug-e528256.ctest.log
    1726db753e90eaead9eefc91eb3d868a0d7d4461a325d890b634123c96c5e44d  L 7001e91/debug-7001e91.ctest.log
    2c15b5d77e17b57023df7a2a2e2262b92cc1e7c4999566eb3bbfa2511eb2b569  L 7001e91/asan-7001e91.ctest.log
    e1917de8e250b4bcf4e46a56086601cfa92b8863770646d137b90d5e9f6452d2  L 7001e91/asan-alone.ctest.log
    36b246ba8ad78ad10d3c353a0c35aaa4278f4332f3e4ede2ec92aa2ea54456e4  L 7c75628/debug-7c75628.build.log
    43fcc5d4198bed48c4dbb4984f834222095c68fd57928540eef59970a875f42a  L 7c75628/debug-7c75628.ctest.log
    276e476f446216292cc19340d015a0f315db0208092e79fc58c009323018a477  L 7c75628/asan-7c75628.build.log
    acfc8e79295b944b149bb3e6887a5b66d3dac98abda23e084a3b97ac466c5334  L 7c75628/asan-7c75628.ctest.log
    58709a849f0ec74dbaec81541bed04090485defb9a407d46f9037dcf41866382  W debug-7001e91.build.log
    ce1a5b68b8707e66de548eaacc5ed1a3de038bd71bf9c033d0286d74ec22994c  W debug-7001e91.ctest.log
    477b1cc5562bbbe3ea1edeaad7fd8fb48f65b7792cd9ac9eca604e33ab34fed7  W asan-7001e91.build.log
    2248124a1422086394ea107e69723febc084dc892e35185caf066f007a140930  W asan-7001e91.ctest.log

### Readings of the frozen text in M4a (for the revision log)

Choices the configurations and the runner make where the frozen text leaves room; each is in the
files' comments. For the coordinator to accept or overrule, and to log at M4b's step 0:
1. M3's TLS route is "by SNI" (section 5.3): the proxies' M3 and B3 configurations match the SNI
   oneport.test only. The server's own route table also checks ALPN (absent, or offering http/1.1 or h2);
   the cell's ClientHello offers http/1.1, so it passes both. ALPN routing belongs to the cases
   configurations (Envoy's `application_protocols`, Appendix B).
2. Appendix B's Envoy line names tls_inspector and http_inspector: M3 and B3 configure tls_inspector
   alone, since no M3 route reads HTTP (the benchmarking FAQ: filter chains reflecting the compared
   features); http_inspector belongs to the cases configuration.
3. HAProxy's `tcp-request content accept if HTTP` (Appendix B's `req.proto_http`) in M3 and B3: without
   it plaintext HTTP/1.1 waits the whole inspect-delay before `default_backend`.
4. HAProxy's client, server and connect timeouts stay unset (HAProxy's default, infinite, accepted with
   a startup warning), since no value is documented for this use and the client timeout must cover the
   inspection delay.
5. "Connection logging is off" (5.3) for sslh-ev is `verbose-connections 0` (Appendix B) plus `numeric:
   true` and `log_level 0` on each protocol, both documented: without them sslh resolves the backend's
   address for its connect-try message on every connect whatever the verbosity.
6. sslh-ev's `on-timeout` names the HTTP route, M3's "everything else"; its default names a protocol
   M3 does not configure.
7. M3's timers are matched to the server's 3 s T_dec, as Appendix B matches them in the cases
   configurations.
8. WL7's raise of the soft open-file limit applies to every process the hand-off runner and the probe
   start, in M3 too, both arms alike.
9. A front's every process and thread runs on the front core (taskset), including nginx's master,
   Envoy's non-worker threads and Go's runtime threads.
10. The M3 stub behind every front is the server's stub mode on epoll with two workers on CPUs 10 and 12.
11. M3's C = 64 is per front core (one), with opgen's eight closed-loop workers on CPUs 2 to 9.

### Design choices of M4a

| Name | Value | Where | Reason |
|---|---|---|---|
| Hand-off ports | arm A 22000, arm B 22100; the stub 10 above; caddy-l4's admin 50 above | `handoff.py`, `competitors.fields` | off the ephemeral range; every change of arm changes port |
| Probe ports | routes 23000, silent 23100, partial 23200 (each with its stub 10 above); test 23500 | `probe.py`, `test_competitors.py` | one block per check |
| Probe watch | 6 s (M3), 32 s (B3) | `probe.WATCH_S` | past the 3 s timer; past B3's 30 s window |
| "At the timer" | from 50 ms before to 1 s after | `probe.EARLY_S`, `LATE_S` | the loop's grain; coarse timer wheels |
| Stub | stub mode, epoll, 2 workers, CPUs 10 and 12 | `handoff.start_stub` | section 4.1's backend CPUs |
| Readiness | LISTEN in `/proc/net/tcp`, at most 20 s | `competitors.wait_port` | no connection reaches a front before its window |
| Done file after a signal | waits at most 60 s for the record's removal | `lab_job.sh` | the teardown is sub-second |
| nginx build | stream and ssl_preread only, `-O2` | `install.sh` | nginx.org's package level; the modules the configurations use |

### Lab journal and raw data

Four lines in the Papers repo's `lab/journal.jsonl` (Papers 52d39da, local, not pushed): aa-nt1, aa-nt2,
aa-nt3 and m3dev1, each marked development. The rows, raw opgen reports, logs, rendered
configurations, probe results and the NOTRACK records stay on L under `~/lab/p3/m4a/` and
`~/lab/p3/notrack-726/`, archived in `~/lab/runs-archive/p3-m4a-20261003T125207.tar.gz` (sha256
7678260defe3f01db40f4fff0c1c8ebcdd140989326443d251fe41227381d1e0, beside it in a `.sha256` file; 1,055
members; made under the lab lock); build trees, source clones, extracted sources and scratch keyrings are
left out.

## M4b-1, 2026-10-03

M4b-1: step 0 (the clock floor on kernel 7.2.6, the coordinator's option (a), and the revision log),
step 1 (sslh-ev's stalled exchanges), step 2 (what M4a left unbuilt for the proxies: their cases
configurations, B3 with a relay system as the measured system, section 10's untimed `perf trace`
windows). Nothing in this section is a result: every window and check is development data,
journaled as such, and the suites are development checks, not records.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| e49cb63 | feat: clockfloor.sh holds every CPU's scaling_min_freq at its scaling_max_freq for a lab job and sets each back; lab_job.sh runs it; the session fingerprint's clock_floor; tests |
| b77dd44 | docs: hypotheses.md revision log, the host clock floor, M4a's nine readings and the two accepted deviations, the note on sslh-ev's stalled exchanges |
| f0ec965 | feat: b3.py runs WL7's window with a relay system as the measured system; tests |
| cdb9068 | feat: systrace.py, section 10's untimed windows with perf trace -s; tests |
| f1f87f3 | fix: b3.py leaves no TIME-WAIT socket of its own after the baseline |
| 5975446 | feat: the proxies' cases configurations, cases_check.py, diag/ (the sslh-ev stall diagnostic); tests |
| e790f0c | fix: systrace.py's start-up offsets (idle pass), perf stat beside perf trace, 3 s attach |
| ebef0bc | fix: diag/'s three scripts in LF |
| ee8be62 | fix: the cases configurations as cases_check found them (nginx without PCRE, sslh-ev without PROXY, HAProxy's defaults recorded) |
| 7865f4c | feat: systrace.py's perf trace buffer from SYSTRACE_MMAP_PAGES |
| 279b410 | feat: systrace.py's agrees_with_perf_stat beside the check against perf trace -s |

Papers: no `lab/bin` change (`pin.sh` is byte-identical; the floor is a P3 wrapper), so no Papers
commit for it; one Papers commit for the lab journal (below). Nothing is pushed to origin; the `lab`
remote has every one-port commit.

### Step 0: the clock floor

**The cause, found before any change: the hardware floor did not move; the reported idle value did.**
M4a's reading (amd-pstate's performance floor moved from nominal to the BIOS minimum) does not hold
on L. Read under the lab lock (`~/lab/p3/m4b1/clock/`, `clock_probe.sh`, `state.py`):
- The CPPC request register of every CPU (MSR 0xC00102B3, read only, as root) holds MinPerf = MaxPerf
  = 119, EPP 0, DesPerf 0, before, during and after every change; `acpi_cppc/nominal_perf` is 119
  (3,201 MHz), `lowest_nonlinear_perf` 41, `lowest_perf` 15.
- amd-pstate.c at v7.2.6 (fetched from the stable tree; sha256 985a694c...0e02): under the performance
  policy `amd_pstate_update_min_max_limit` (line 693) takes the BIOS minimum if there is one, else the
  nominal performance, and ignores `scaling_min_freq`. A BIOS minimum would have to be 119 (the
  register says so), and then `amd_pstate_verify` (line 662) would set the policy minimum to its
  frequency, 3,201,000 kHz. It reads 1,102,866 kHz = `lowest_nonlinear_freq`, which `verify` sets
  only without a BIOS minimum. So there is none on this boot, and the floor is the nominal performance,
  as 7.2.3's code gives.
- An idle CPU's `cpu MHz` is the policy's current value, not a clock: /proc/cpuinfo (proc.c line 89)
  takes APERF/MPERF only from a sample at most 20 ms old (aperfmperf.c lines 504 to 535), else
  `cpufreq_quick_get`, which returns `policy->cur` for a driver without `get`; the EPP driver sets
  `policy->cur = policy->min` (line 2049).
- The active clock, cycles over task clock of a process on CPU 14 (`perf stat`): busy throughout
  3,169.0 MHz; 0.3 ms bursts after 5 ms sleeps 3,091.4 MHz; after 50 ms sleeps 3,106.3 MHz. With the
  floor set: 3,169.0, 3,091.5 and 3,107.0 MHz. The floor changes the report, not the clock.
- Why 7.2.3's idle reading was near the loaded one is not established; the same code implies a policy
  minimum near 3,201,000 kHz then (a BIOS minimum at that cold boot). No cpufreq shutdown hook was
  found in cpufreq.c at v7.2.6 to tie its loss to the kexec, so that stays open.
- The brief's other controls were not needed: EPP is 0 and under the performance policy only 0 is
  accepted (`store_energy_performance_preference`); `amd_pstate_floor_freq` does not exist on L (the
  docs show it only with CPPC performance priority). The driver's mode was not touched.

**The change (option (a)): a P3 wrapper, `bench/run/clockfloor.sh` (e49cb63).** Chosen over an
opt-in flag of the shared `lab/bin/pin.sh`: the floor must be set back at the job's end, also on a
signal, which needs a process that lives as long as the job (as `notrack.sh` does), while `pin.sh`
runs once per session and exits. `pin.sh` is byte-identical, so P1 and P2 are untouched and there is
no Papers `lab/bin` commit. `lab_job.sh` runs `clockfloor.sh` inside the lock and outside
`notrack.sh`; it writes each CPU's `scaling_max_freq` into `scaling_min_freq`, runs the job, and writes
the values it read back on EXIT (INT, TERM and HUP end it so the trap runs); exit 95 if a floor
cannot be set (the job does not run), 96 if a floor does not come back. Its record
`<job>.clock.json` holds, per CPU, the floor, ceiling, governor, EPP and the CPPC request before, set
and after. `lab_job.sh` waits after a signal for both records to name their teardowns.
`window.pin_fingerprint()` adds `clock_floor` to each session's fingerprint: the floors before the job
(from the record, through `ONEPORT_CLOCK_RECORD`) and the floor and ceiling now, and `held`. Writing
the read value back leaves a user frequency request at 1,102,866 kHz where the driver's default was;
it reads the same. `ONEPORT_CLOCK_FLOOR=off` runs a job without it, said in the record.

**The check.**

| Check | Result |
|---|---|
| Idle host, `pin.sh` `mean_mhz` (clock_probe, lock) | 2,263 before; 3,181 with the floor; 2,135 after it was set back |
| Idle host, mean `cpu MHz` 2 s after | 2,006.1; 3,188.5; 1,877.6 |
| Job c1 (lab_job.sh, a session's fingerprint) | `mean_mhz` 3,180; `clock_floor.held` true; 16 floors at 3,201,000, back at 1,102,866 after |
| Job c2, SIGTERM to its process group after 6 s | done file exit 143, signal TERM; record `restored` true; floors back; NOTRACK rules gone, ruleset restored; lock free |
| A/A set aa-floor1 (e49cb63, Release, seed 821, 2 sessions x 3 cells, NOTRACK, lock) | 24 of 24 windows valid; MHz drift 0.32% to 0.53% (sessions 3,179 to 3,185 MHz, windows 3,168.2 to 3,168.8 MHz) |

aa-floor1's cells, development data:

| Cell | Session ratios (B / A) | Per window |
|---|---|---|
| churn, HTTP/1.1, epoll | 1.0032, 1.0001 | 44,655 to 44,980 conn/s |
| churn, HTTP/1.1, io_uring | 1.0015, 1.0002 | 53,000 to 53,245 conn/s |
| keep-alive, TLS, io_uring | 0.9934, 0.9960 | 106,404 to 108,453 req/s |

Record sha256 (`~/lab/p3/m4b1/`): aa-floor1.clock.json
7cc67deff016729beed6081b99b029165fb3c3528a1d31766fb7f38f346e8be1, aa-floor1.notrack.json
030573fd913e2c8712b0810c43bcf7cb2d9bbc23a3f43a8a7401ba53b59e3e8d, aa-floor1.done
b9df9f5b598b608552a1e88c71e299f542b0164b4cc1ff5b62552a1513fe4971, aa/aa-floor1/windows.jsonl
2e76d76685d85a21910f086077dad887fff06601366024086d7ceaa9ad2cbd2c; floorjobs/c1.clock.json
ee9254e1defa9ca708ccb632ffe56cb8b33064c2e34f6bd616f09492aadb379f, floorjobs/c2.clock.json
877200e546bd5161196b9bc11b7dcc8d13951845c59b1ee579d5a24d4b22f395, floorjobs/c2.done
d02ab5c0c56ec41b69d41d05e9e7a52b0e6b3a1a642a0ef7ddf4e97855f2da21.

### Step 0: the revision log (b77dd44)

Three entries, after the coordinator's decision on M6a's reading 7:
- "Host clock floor before the code freeze": the cause above (superseding the mechanism of the
  host-change entry's item 4, whose readings stand), the change and the check.
- "Readings fixed during engineering (M4a)": M4a's readings 3 to 11 as items 1 to 9, each with why it
  follows; then the coordinator's two accepted deviations as items 10 and 11: TLS by SNI alone in M3
  and B3 (section 5.3), and Envoy without http_inspector. Appendix B's Envoy line names
  http_inspector without saying in which configuration, so item 11 records leaving it out as a
  reading of the line's own "filter chains only for the compared features" (the benchmarking FAQ):
  no M3 route reads HTTP. No reading contradicts the frozen text.
- "sslh-ev's stalled exchanges": a note, not a reading (step 1).

### Step 1: sslh-ev's stalled exchanges: an sslh defect

**Cause.** sslh-ev keeps one libev watcher per descriptor number and calls `ev_io_init` only the first
time it sees that number (`watchers_add_read`, sslh-ev.c lines 92 to 103 at v2.3.1; unchanged on
sslh's master on 2026-10-03, and 2.3.1 is the latest tag). libev's manual (ev(3) of libev 4.33-5 on
L, "The special problem of disappearing file descriptors") says libev treats a descriptor as new only
when `ev_io_set` or `ev_io_init` is called. When one loop pass closes a connection (`tidy_connection`)
and then accepts a new one onto the same number, no `epoll_ctl` is issued for it: the kernel dropped
the old one from the epoll set at close, and libev believes nothing changed. sslh never reads that
connection, never closes it (it stays in CLOSE_WAIT after the client gives up), and the client times
out. Not a configuration issue: sslh has no setting for it; the configuration stays as frozen, and
sslh-ev's M3 cells stand as section 7 decides them (the 0.1% error rule), with the narrowing order of
section 12 (M3 first).

**Evidence**, development diagnostics (`bench/competitors/diag/stall_run.py`), sslh-ev's M3
configuration in front of the stub, handoff placement, C = 64, 1 s warm-up and 2 s measure, under
`lab_job.sh` (lock, floor, NOTRACK), from the e49cb63 build:

| Job | Protocol, libev backend, tool | Timeouts (measure) | Other | Census after opgen |
|---|---|---|---|---|
| sslhdiag2 | HTTP/1.1, epoll, tcpdump | 124 of 17,613 (0.70%) | 545,645 packets, 0 dropped by the kernel | |
| sslhdiag3 | HTTP/1.1, epoll, none | 124 | no listen overflow | 186 CLOSE_WAIT on sslh's port; listen queue 0; sslh holds 192 descriptors; no backend socket |
| sslhdiag4 | HTTP/1.1, epoll, strace | 117 (strace slows sslh: 16 listen drops, 5 connect failures) | strace: 176 accepts onto a number closed earlier in the same pass, none with `epoll_ctl`, none read, all open at the end; 5,276 other accepts each registered, read, closed | 176 CLOSE_WAIT |
| sslhdiag5 | HTTP/1.1, poll (`LIBEV_FLAGS=2`), strace | 0 (22 connect failures, 33 listen drops: strace) | every accepted descriptor read and closed | 0 CLOSE_WAIT |
| sslhdiag6 | TLS stub, epoll, none | 124 | | 185 CLOSE_WAIT |
| sslhdiag7 | HTTP/1.1, poll (`LIBEV_FLAGS=2`), none | 0 | 12,244 exchanges per second; 40 listen overflows and drops, 22 connect failures | 0 CLOSE_WAIT |

- The capture (sslhdiag2, `diag/pcap_flows.py`): each stalled exchange's request (57 bytes) is
  acknowledged by the kernel and nothing follows from sslh, not even after the client's FIN at about
  1 s (the kernel acknowledges that too, 40 ms later). The connect had completed: opgen counts a
  deadline during connect as a connect error, and there were none.
- The m3dev1 rows already showed the stall's shape: every error "timeout", none in the warm-up, 309
  or 310 per 5 s window, no listen overflow or drop. The count is structural: with a stall
  probability p per exchange and a 1 s timeout nearly every slot sits in a stall, so a window's
  timeouts come to about 64 x 5 x 0.97 whatever p is.
- libev's poll backend polls each descriptor by number every pass, so the defect does not arise
  (sslhdiag5, sslhdiag7). It is libev's environment variable, not sslh's configuration, and it moves
  sslh-ev off epoll (section 5.3: "the accept model all five use"); and with the stalls gone sslh's
  hard-coded backlog of 50 overflows under M3's 64 slots (sslhdiag7: 22 connect failures in 2 s),
  which section 7's connect rule would invalidate anyway. So it is not applied.
- tcpdump 4.99.6-1 was installed for the capture (`sudo pacman -S --needed tcpdump`, the install
  policy; libpcap 1.11.0-1 was present; `/usr/bin/tcpdump` sha256
  6070c59b7dfe43e16b43078e00aecf7cc53c54fa82bcce71fd3bed7fc573b5de).

### Step 2: the proxies' cases configurations

`bench/competitors/<system>/cases.*` (5975446, fixed in ee8be62), one file per system, rendered by
`competitors.py` in two kinds and two timer settings:
- kinds: "cases", no fallback; "cases-fallback", the SMTP fallback, for the three systems that have
  one (HAProxy's `default_backend`, Envoy's default chain with `continue_on_listener_filters_timeout`,
  sslh's `on-timeout` naming its "timeout" entry). A line that starts with the field FALLBACK is a
  comment in "cases".
- timers (section 10: "at matched timers and at their defaults"): "matched", every detection timer at
  the server's 3 s; "default", the timer lines left out. A line that starts with the field MATCHED is a
  comment at the defaults.
- routes, every one each system's features cover (Appendix B; the survey), to a backend that is the
  server in dedicated mode with PROXY off (M2b reading 6), its listeners from BACKEND in the order of
  I20: TLS for oneport.test whose ALPN offers h2 or http/1.1 (the server's pass-through route table
  less its no-ALPN route, which no hard case sends), h2c, HTTP/1.1, SSH, MQTT 3.1.1 and 5.0.
- a second listener, PORT + 1, that requires the PROXY header (v1 and v2), on the four systems that
  read it.

| System | Routes (judged) | PROXY listener | Fallback | Timers matched / default |
|---|---|---|---|---|
| nginx | TLS by SNI and ALPN; everything else to HTTP/1.1 | `listen ... proxy_protocol` | none | `preread_timeout`, `proxy_protocol_timeout` 3s / 30s |
| HAProxy | TLS, h2c (the preface by `req.payload(0,24)`), HTTP/1.1, SSH, MQTT (`mqtt_is_valid`) | `accept-proxy` | `default_backend` | `tcp-request inspect-delay`, `timeout client-hs` 3s / none (no delay; client-hs falls back to the unset client timeout) |
| Envoy | TLS (`server_names`, `application_protocols` h2, http/1.1), h2c and HTTP/1.x (http_inspector's `application_protocols`) | proxy_protocol listener filter | default chain | `listener_filters_timeout` 3s / 15s |
| caddy-l4 | TLS (sni, alpn), SSH, MQTT (regexp on the hex of 12 bytes), h2c (`http protocol http/2`), HTTP/1.1 | `proxy_protocol` matcher, handler, subroute | none | `matching_timeout`, the handler's `timeout` 3s / 3s and zero |
| sslh-ev | TLS (`sni_hostnames`, `alpn_protocols`), SSH, MQTT (regex), HTTP | none | `on-timeout` "timeout", last | `timeout` 3 / 5 |

Found on L and fixed (ee8be62):
- nginx's route first used a `map` regex; the pinned build has no PCRE (`--without-http`: configure's
  "PCRE library is not used"), so the key was matched as a literal and TLS went to the HTTP/1.1 port.
  A throwaway stream server that returned the variables for the recorded ClientHello read
  `name=[oneport.test] alpn=[http/1.1]`, and every regex key failed while the literal key matched.
  The route now lists the ALPN lists as strings: http/1.1, h2, and both in either order.
- sslh-ev refused to start with a PROXY listener: "Uses proxyprotocol, but libproxyprotocol support
  was not compiled in" (the pinned build of install.sh). Appendix B names no PROXY for sslh, so its
  cases configuration has no PROXY listener and the PROXY cases are not covered for sslh-ev.
- HAProxy at its defaults has no inspect delay and decides on the bytes at hand, which its documents
  call racy; in the check it did not route TLS there (and in one run not MQTT). Its routes at the
  defaults are recorded, not judged.

`bench/competitors/cases_check.py` (the route check): per system, kind and timer setting, fresh
processes (the backend on CPUs 10 and 12, the system on CPU 14), `opgen --probe` for HTTP/1.1, h2c,
TLS, MQTT and SSH on the plain listener, a PROXY v1 and a PROXY v2 header each followed by an
HTTP/1.1 request on the PROXY listener, and in cases-fallback a silent client that must get the SMTP
greeting. Job casecheck2 (ee8be62, lab job, NOTRACK, floor): every judged check passed.

| System, kind | Matched: routes / PROXY / fallback | Default: routes / PROXY / fallback |
|---|---|---|
| nginx, cases | HTTP/1.1, TLS (h2c, MQTT, SSH to HTTP/1.1: not covered) / v1, v2 | the same |
| HAProxy, cases | all five / v1, v2 | all but TLS (recorded) / v1, v2 |
| HAProxy, cases-fallback | all five / v1, v2 / SMTP at 3.02 s | HTTP/1.1, h2c, SSH (recorded) / v1, v2 / SMTP at 0.00 s |
| Envoy, cases | HTTP/1.1, h2c, TLS / v1, v2 | the same |
| Envoy, cases-fallback | the same / v1, v2 / SMTP at 3.00 s | the same / SMTP at 15.00 s |
| caddy-l4, cases | all five / v1, v2 | the same |
| sslh-ev, cases | HTTP/1.1, TLS, MQTT, SSH (h2c to HTTP/1.1) | the same |
| sslh-ev, cases-fallback | the same / silent client held, no greeting (recorded: the probe timeout runs only on read activity) | the same |

The competitors' hard cases themselves (section 10, `R_COMP_CASES` = 3 replicates per case and
setting) run after the pilot entry; `opcase` runs the cases in-process in the suite and has no mode
for a system by port yet, which that run needs.

### Step 2: B3 with a relay system as the measured system

`bench/run/b3.py --system` (f0ec965, fixed in f1f87f3): ophold as before, or a relay system, a proxy
in its B3 configuration or the server's one-port relay with its timers at 60 s, in front of the stub:
- the stub on CPUs 10 and 12 (left out of U, WL7), the front on CPU 14 (section 4.1);
- U over the front's process group (nginx's master and worker), Kq and the established count on the
  front's port;
- the probe: one TLS stub exchange through the front (the recorded ClientHello, the stub's 13 bytes
  to EOF), the client closing by reset; the stub closes first, so a TIME-WAIT socket of the probe's
  stub connection can exist, and the baseline waits until the host's TIME-WAIT count has held 2 s;
- caddy-l4: a heap profile with gc=1 at its admin endpoint a second before each reading, the
  baseline included, on an HTTP/1.1 connection closed by reset.

Functional windows, job b3dev1 (f0ec965, lab job, NOTRACK, floor; development data):

| System | Case | Valid | W at sample 1 and 2 (bytes per pending connection) | U, Kq, Ks at sample 2 | Invalid by |
|---|---|---|---|---|---|
| nginx | silent | no | 14,801.7; 16,010.4 | 8,232.1; 0.0; 7,778.3 | settling (U grew) |
| nginx | partial | no | 15,859.5; 17,031.3 | 8,377.5; 1,068.0; 7,585.8 | settling (U grew) |
| HAProxy | silent | no | 10,661.1; 10,670.1 | 3,133.8; 0.0; 7,536.2 | TIME-WAIT 1, then 2 (the probe's) |
| HAProxy | partial | no | 15,816.3; 16,873.9 | 9,445.0; 0.0; 7,428.9 | settling (U grew) |
| Envoy | silent | yes | 17,453.5; 17,462.9 | 10,087.6; 0.0; 7,375.3 |  |
| Envoy | partial | yes | 18,855.7; 18,868.8 | 10,503.0; 1,068.0; 7,297.8 |  |
| caddy-l4 | silent | no | 20,191.6; 20,209.7 | 12,910.2; 0.0; 7,299.5 | TIME-WAIT 2, 3, 4 (the heap profile requests) |
| caddy-l4 | partial | no | 22,070.1; 22,285.1 | 15,061.4; 0.0; 7,223.7 | TIME-WAIT 2, 3, 4 (the same) |
| sslh-ev | silent | yes | 7,691.5; 7,644.0 | 399.8; 0.0; 7,244.2 |  |
| sslh-ev | partial | yes | 7,653.0; 7,657.5 | 524.3; 0.0; 7,133.2 |  |
| server's relay | silent | yes | 7,534.2; 7,622.2 | 407.1; 0.0; 7,215.1 |  |
| server's relay | partial | yes | 11,767.0; 11,773.1 | 4,670.7; 0.0; 7,102.5 |  |

- The runner's own TIME-WAIT sockets made three windows invalid: caddy-l4's heap profile requests
  closed normally (one TIME-WAIT socket per reading: 2, 3, 4), and one of HAProxy's probe connections
  closed after the baseline (1, then 2). Both fixed in f1f87f3. Section 7's TIME-WAIT rule counts the
  whole host, so nothing else may open a TCP connection on L during a B3 window, an ssh session to
  L included; in M4b-1 status polls ran over one held ssh session while windows ran.
- Every probe passed (the stub's 13 bytes, then EOF), every window held 10,000 established
  sockets at both samples, and no listen overflow or drop occurred. Kq is 1,068 bytes per pending
  connection where the front leaves the partial ClientHello in the socket (nginx's and Envoy's peek
  paths, survey 2.1 and 2.5) and 0 where it reads it.
- The settling failures are the host's: the fronts' RSS rises in steps while every connection is
  idle (open, "B3 on L and transparent huge pages"). b3diag2 and b3diag3 (5975446, 7865f4c) ran nginx
  silent and HAProxy partial again with a sampler of the front's RSS, AnonHugePages and accept queue
  every second: the accept queue stayed 0 (both accept at once), and each RSS step came with a step
  of AnonHugePages about 10 s apart (khugepaged's interval). In b3diag2 both windows settled (the
  steps fell outside 20 s to 25 s); in b3diag3 nginx did not (W 13,733.9, then 14,943.0), HAProxy did.
- f1f87f3 checked: job b3dev2 (279b410) ran caddy-l4's two windows again; both valid, TIME-WAIT 1 at
  the baseline and at both samples (the probe's stub connection, inside the baseline after a 2.0 s
  steady wait), every heap profile request answered 200 (3,281 to 8,348 bytes), none left a
  TIME-WAIT socket. W at sample 2: 20,006.5 (silent) and 22,007.8 (partial) bytes per pending
  connection, development data.
- B3's timing (section 8, step 7) runs later; these windows only show that the runner works for
  every relay system.

### Step 2: section 10's untimed perf trace windows

The frozen text defines them for the proxies and for the cost cells (section 10: "system calls per
connection for the proxies, from `perf trace -s` over untimed windows. On L, one untimed window per
cost cell checks the server's system-call counters against `perf trace -s`"). `bench/run/systrace.py`
(cdb9068; e790f0c, 7865f4c, 279b410):
- kind proxy: a front of M3 (a proxy in its M3 configuration, or the server's relay) in front of the
  stub, hand-off placement; `perf trace -s` and `perf stat` on the front's process group; system calls
  per connection, over the connections the stub accepted; for the server's relay its counters are
  checked too;
- kind cost: the server alone in a cost cell's arm (one-port or dedicated, in-process, replay, the
  cell's backend), in-process placement; I29's counters that name a system call against perf's
  counts: accept4, recvfrom (receive, peek and 1(b)'s check), sendto, setsockopt, epoll_ctl,
  epoll_pwait2, connect, shutdown, splice on epoll; sendto, setsockopt, the synchronous peek and check,
  io_uring_enter on io_uring (its receives and accepts are ring operations);
- untimed: churn at an open-loop 2,000 exchanges per second for 2 s after 0.5 s, keep-alive with two
  connections for 0.5 s; rows hold counts only (opgen's completed and errors), never a rate or a time.
  Untimed counter checks are not windows (the frozen text's Words), so one-port mode runs here.

What the functional runs found:
- tracedev1 (cdb9068): every check differed. Two causes. (1) Start-up: the counters include calls
  made while the server starts, which perf, attached after the listeners are up, cannot see: epoll_ctl
  by the number of listeners (6 in dedicated mode, 1 in one-port), io_uring_enter by 3. e790f0c
  measures that offset per arm in an idle pass (start, attach, 2 s with no load, stop). (2) A
  shortfall of perf trace itself.
- tracedev2 (e790f0c), with perf stat on the same system calls' entry tracepoints beside perf trace:
  after the start-up offsets, perf stat equals the server's counters in all 178 checks (22 rows:
  the relay on two protocols, and churn HTTP/1.1, h2c, TLS and MQTT and keep-alive HTTP/1.1 on epoll
  and io_uring, each arm), while perf trace -s agrees in 146; it falls short of perf stat by at most
  0.31% of a call's count, and reports no lost event (no "LOST" line in its output or its stderr).
- tracedev3 (7865f4c), the worst rows again with perf trace's ring buffer at `-m 8192`: perf stat
  agrees in 86 of 86 checks, perf trace in 57, short by at most 0.42%. A larger buffer does not remove
  it.
So the counters are exact; `perf trace -s` (perf 7.2.6 on L) undercounts at these rates without
saying so. Each row now holds `agrees` (section 10's check, against perf trace -s) and
`agrees_with_perf_stat` (279b410). Which one section 10's check is read as is open (below). The
proxies' rows (system calls per connection, all five and the relay, both protocols) are in
`~/lab/p3/m4b1/trace/tracedev2/trace.jsonl`; their perf trace counts carry the same shortfall, which
perf stat beside them measures.

### Tests

New or changed, all in `run.test_runner` and `run.test_competitors` (CTest):
- `ClockFloor` (5): the fingerprint's `clock_floor`; `read_floors`; clockfloor.sh on a copy of the
  cpufreq tree: the floor held and restored, a SIGTERM to its group restores (exit 143), a floor that
  cannot be set refuses the job (exit 95) and sets back the ones it set, and ONEPORT_CLOCK_FLOOR=off.
- `B3Relay` (4): the exchange probe against a stand-in stub (13 bytes, then EOF; a wrong reply fails),
  caddy-l4's heap profile request against a stand-in admin endpoint, the systems list.
- `Trace` (4): the perf trace -s summary parser (two thread blocks, a LOST line), the counter checks
  per backend with the wait slack, the start-up offset, perf stat's parser and `stat_agrees`, counts
  without time.
- `Cases` (6) in test_competitors: timers matched and at the defaults, every route and the PROXY
  listener per system, ALPN where a system routes by it, the fallback only in its kind, sslh's list
  well formed in both kinds, the check's PROXY headers.
On W (Python 3, the pure parts): run.test_runner 39 checks, run.test_competitors 24 (2 skipped,
Linux).

### Checks

| Host | Build | Commit | Build | CTest | Report lines |
|---|---|---|---|---|---|
| L | Debug, clang 22.1.8 | 279b410 | 0 warnings | 374 passed | 0 |
| L | ASan+UBSan | 279b410 | 0 warnings | 374 passed | 0 |
| W | Python 3 (pure parts) | 279b410's tree | | run.test_runner 39, run.test_competitors 24 (2 skipped) | |

- L: lab job checks279 (`~/lab/p3/sancheck.sh` from a clone of the lab remote at 279b410, Debug and
  ASan+UBSan at once, `ctest -V -j 8`; NOTRACK and the clock floor on). The suite's integration part
  of run.test_competitors (the probe of the server's relay and a short hand-off window per M3
  protocol) ran in both. The C++ code is unchanged since b3d41a6, so the binaries' tests are M4a's.
- Log sha256 (L, `~/lab/p3/m4b1/check/279b410/`): debug-279b410.build.log
  5882e2cf13b2c6a801711dba901264e7f59bc6b437119e6abb6613c4f00875cd, debug-279b410.ctest.log
  4cb5a6a9e7b04c163f5d081e0c5265dfa6b30884559d740a9ca10a69c5d48ed8, asan-279b410.build.log
  31e1edb1f518e8c30017b7e348db358655b639b92667061b5a50f1676238d97b, asan-279b410.ctest.log
  c4dc3b77bb06b7324ef6c15f9a6229a15570350427985af66b3d38d23b3f9be5.

### Readings of the frozen text in M4b-1 (for the coordinator)

1. B3 with a relay system: U over the front's process group (nginx's master and worker), the stub left
   out (WL7: "The stub backend of the relay systems holds no pending connection and is left out"); Kq
   and the established count on the front's port.
2. WL7's probe for a relay system is one TLS stub exchange through the front whose client closes by
   reset (section 4.1: "checks one exchange of each protocol the cell uses"; WL7: "The probe's client
   closes by reset"); the stub closes its side first, so the probe can leave one TIME-WAIT socket on
   the stub's connection, and the baseline waits until the host's count holds 2 s.
3. caddy-l4's heap profile with gc=1 "before each sample" also precedes the baseline, a second ahead
   of each reading, on a connection closed by reset (no TIME-WAIT socket).
4. The cases configurations' TLS route is SNI oneport.test with an ALPN list that offers h2 or
   http/1.1; the server's route also takes a ClientHello without ALPN, which no hard case sends.
5. "At their defaults" (section 10) is each system's own timer defaults; HAProxy's is no inspect delay,
   with which it decides on the bytes at hand (its documents: racy, not recommended), so its routes
   there are recorded, not judged.
6. The fallback lives in a second kind of the cases configuration, cases-fallback (HAProxy, Envoy,
   sslh-ev), since HC5, HC7 and HC15 use a listener with a fallback and HC6 one without.
7. A second listener requires the PROXY header (nginx, HAProxy, Envoy, caddy-l4). sslh's pinned build
   cannot read it (no libproxyprotocol) and Appendix B names no PROXY for sslh: its PROXY cases are not
   covered.
8. HAProxy's cases route h2c by its preface (`req.payload(0,24)`), a route its features cover beyond
   Appendix B's list.
9. Section 10's untimed windows: churn at 2,000 exchanges per second open loop, keep-alive with two
   connections; the start-up offset from an idle pass is subtracted before the comparison.

### Open for the coordinator and Alex

- **Section 10's check against `perf trace -s` (a question about the frozen text, not logged):** on L
  perf trace -s undercounts system calls by up to 0.42% at these rates with no lost event reported,
  also with a larger buffer, while perf stat on the same tracepoints matches the counters exactly
  (264 of 264 checks in tracedev2 and tracedev3). Read literally, the check fails on perf's side.
  Options: read section 10's perf trace -s as its tracepoint counts (perf stat), or keep perf trace -s
  with a stated tolerance, or lower the rate until perf trace loses nothing (not found yet).
- **B3 on L and transparent huge pages (a host condition):** L runs THP `enabled=always`,
  khugepaged every 10 s (`scan_sleep_millisecs` 10000, `pages_to_scan` 4096, `max_ptes_none` 511). In
  B3 windows the fronts' RSS rose in steps of 7 to 12 MB about 10 s apart with every connection idle,
  each step with a step of AnonHugePages (b3diag3: nginx 62 to 74 MB as huge pages went 10 to 26 MB,
  then 74 to 85 MB, 26 to 42 MB; HAProxy 85 to 92, 2 to 14 MB, then 92 to 102, 14 to 30 MB). A step
  between t = 20 s and 25 s fails section 7's settling rule (b3dev1: nginx in both cases, HAProxy
  partial; b3diag3: nginx), and every step adds to U memory the system never touched. It will weigh
  more on the JVM and Go systems of M4b-2. Like the clock floor, a per-job setting (THP `madvise` or
  khugepaged paused for the job, restored after) would be a change of the lab procedure, Alex's
  decision; nothing was changed.
- **sslh-ev's M3 cells:** invalid by the error rule as configured (step 1, the revision-log note).
- From before: the per-connection decision record WL8 needs against a server in its own process;
  `RELAY_BUF`, `IORING_OP_SEND` and splice's worker threads (M5); more than one worker on IOCP (M6b).

### Design choices of M4b-1

| Name | Value | Where | Reason |
|---|---|---|---|
| Clock floor exits | 95 (not set; the job does not run), 96 (not restored) | `clockfloor.sh` | beside notrack.sh's 90 to 93 |
| B3 front port | 21100; the stub 10 above; caddy-l4's admin 50 above | `b3.B3_PORT` | off the ephemeral range, apart from ophold's 21000 and the hand-off ports |
| TIME-WAIT steady before the baseline | held 2 s, at most 10 s | `b3.TW_STEADY_S`, `TW_STEADY_MAX_S` | a probe connection closed late lands in the baseline |
| caddy-l4's collector lead | 1 s before each reading | `b3.COLLECT_LEAD_S` | the collection ends before the reading |
| Untimed load | churn open loop 2,000 per s, 0.5 s and 2 s; keep-alive 2 connections, 0.5 s | `systrace.TRACE_*` | low enough for perf; counts only |
| perf attach, idle pass | 3 s; 2 s | `systrace.ATTACH_S`, `IDLE_S` | perf trace's start-up on L takes over 1.5 s |
| Wait slack | 2 per worker | `systrace.WAIT_SLACK` | a wait in progress at attach and at stop |
| Trace ports | cost 24000, proxy 24100 (stub 10 above) | `systrace.PORTS` | off the ephemeral range |
| Cases ports | front 25000, PROXY listener 25001, backend 25010 | `cases_check` | off the ephemeral range |
| Fallback check | the system's timer + 2 s | `cases_check.FALLBACK_LATE_S` | a timer wheel's grain |
| Cases PROXY listener | the front port + 1 | `competitors.PROXY_PORT_OFFSET` | one configuration serves both kinds of case |

### Lab journal and raw data

Six lines in the Papers repo's `lab/journal.jsonl` (Papers b651c97 and a7d99c0, local, not pushed),
each marked development: aa-floor1 (the A/A set), b3dev1, b3diag2, b3diag3 and b3dev2 (B3 windows),
and the sslh-ev diagnostics (sslhdiag2 to sslhdiag7). No line for the host checks (clock_probe, c1, c2), the
route checks (casecheck1, casecheck2), the untimed trace runs (tracedev1 to tracedev3) or the nginx
map debug: no window ran. b3diag1 ran no window (its job script had CRLF line ends). Everything
stays on L under `~/lab/p3/m4b1/`, archived in `~/lab/runs-archive/p3-m4b1-20261003T141726.tar.gz` (sha256
a6bfbfb2f0a47ad3a0b4694fea00b07221583181812e22a8ce97a01bff2f0cbe, beside it in a `.sha256` file; 1,377
members; made under the lab lock); build trees, source clones and extracted sources are left out.
b3dev2's files: `~/lab/runs-archive/p3-m4b1-b3dev2-20261003T142217.tar.gz` (sha256
5b439cfe4c40d1fddf630a9f019aef4d78bef75d951ee02f1a9a9de982d73289, 27 members).

## M4b-2, 2026-10-03

M4b-2: step 0 (transparent huge pages at `madvise` for every lab job, Alex's decision; section 10's
check read against `perf stat`, the coordinator's decision; both logged), step 1 (the toolchains of
the in-process libraries), step 2 (the libraries' harnesses, configurations, probes, runner
integration, cases configurations and B3 functional windows), step 3 (the checks). Nothing in this
section is a result: every window and check is development data, journaled where a window ran.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| 373695e | feat: thp.sh (THP at madvise for a lab job, set back at its end); lab_job.sh runs it; the fingerprint's thp; b3.py's memory sampler; tests |
| a67e1de | docs: revision log, section 10's check against perf stat (the coordinator's decision); systrace.py names it and reports perf trace's shortfall; tests |
| 9bd2bec | docs: revision log, transparent huge pages before the code freeze (cause, change, check) |
| 7e1c4e6 | fix: opgen accepts HPACK dynamic table size updates before :status 200 (RFC 7541 s4.2, s6.3); hpack.hpp; test gen.h2_status |
| 985f708 | feat: the four libraries' harnesses, their cases and B3 configurations, jvm.args, the jar locks, go.sum, Cargo.lock; the pins; install.sh (jdk, netty, jetty); build_harnesses.sh |
| b61b71b | feat: the runner takes the libraries (competitors.py, probe.py, cases_check.py, b3.py's in-process systems and collector steps); tests |
| c61a8e8 | feat: coverage.json names the harnesses as targets, with their gaps; UBSan's gap in Go and Rust |
| 8288b70 | fix: build_harnesses.sh sets the Rust target before the flags that name it |
| a83263d | feat: the hyper-util harness's TSan suppression (one entry in tokio's I/O driver) |
| 85e9dd0 | fix: b3.py's TLS probe closes by reset through the TLS socket; test against a local TLS stand-in |
| 595eded | fix: test_runner.py's TLS probe test (two byte strings broken across lines in 85e9dd0) |

Papers (local, not pushed): 5341785 and 5846aaf, the lab journal (below). Every one-port commit is on
the `lab` remote; nothing is pushed to origin.

### Step 0: transparent huge pages (Alex's decision)

**The change: a second wrapper, `bench/run/thp.sh` (373695e), beside `clockfloor.sh`, which is
unchanged.** `lab_job.sh` now runs lablock, then `clockfloor.sh`, then `thp.sh`, then `notrack.sh`,
then the job. `thp.sh` writes `madvise` to `/sys/kernel/mm/transparent_hugepage/enabled` for the
job's length and writes the value it read back at the end, also on INT, TERM and HUP (an EXIT trap,
as `clockfloor.sh`). It parses the bracketed word of the sysfs file, and a bare word in the tests'
copy of the tree. `defrag` is written only when a job names a value in `ONEPORT_THP_DEFRAG`; none
does, since the check found no collapse under `madvise` (`defrag` reads `madvise` on L anyway and
governs the page-fault path, not khugepaged; Documentation/admin-guide/mm/transhuge.rst at v7.2.6,
sha256 2c76af67...1d13, fetched from the stable tree into `~/lab/p3/m4b2/thp/`). Exit 97: a setting
cannot be made, the job does not run, every value written is set back; exit 98: a setting did not
come back. `ONEPORT_THP=off` runs a job without it, said in the record. Its record
`<job>.thp.json` holds `enabled`, `defrag`, `khugepaged/defrag`, AnonHugePages, the host's
`thp_fault_alloc` and `thp_collapse_alloc`, and khugepaged's `pages_collapsed` and `full_scans`,
before, while and after. `lab_job.sh`'s signal path waits for the record's `restored_at`, as it does
for the other two. `window.pin_fingerprint()` adds `thp` (the settings now, `held` when `enabled`
reads `madvise`, the settings before the job from the record through `ONEPORT_THP_RECORD`). `b3.py`
records every second the system's summed VmRSS and AnonHugePages (`smaps_rollup`) and the host's two
THP counters (`memory_sampler`, with a summary), and the counters at the baseline and each sample
(`thp_counters`); they decide nothing.

**The check.**

| Check | Result |
|---|---|
| Job b3thp1 (373695e, Release; lock, floor, NOTRACK, THP at madvise): nginx and HAProxy in their B3 configurations, both cases, 2 windows each | 8 of 8 valid by section 7; W moved between the samples by 2.1 to 83.1 bytes per pending connection |
| The fronts' memory from t = 11 s to sample 2, 1 s samples | VmRSS the same to the kB in every window; AnonHugePages 0 throughout |
| The host's counters over the whole job | `thp_collapse_alloc` 1,465 before and after; `pages_collapsed` 68,807 before and after, while khugepaged's `full_scans` went 927 to 974 |
| U at sample 2, the two windows of each | nginx 4,939.0 and 4,939.0 (silent), 5,307.6 and 5,307.6 (partial); HAProxy 3,087.6 and 3,087.6, 7,306.0 and 7,306.0 bytes per pending connection (b3dev1 under `always`: 8,232.1, 8,377.5, 3,133.8, 9,445.0) |
| After the job | `enabled` reads `always`; the record's `restored` true |
| Job t1, SIGTERM to its process group 6 s after its start | done file exit 143, signal TERM; THP record `restored` true, `enabled` back at `always`; the floors and the NOTRACK rules set back too |
| Job b3lib2 (below), the in-process systems | no system held AnonHugePages, the JVMs and Go included; the host's `thp_collapse_alloc` 1,563 before and after the job |

b3thp1's windows, development data:

| System | Case | W at sample 1 and 2 | U, Kq, Ks at sample 2 |
|---|---|---|---|
| nginx | silent | 12,109.4; 12,117.2 / 11,968.9; 11,971.0 | 4,939.0; 0.0; 7,178.2 / 4,939.0; 0.0; 7,032.0 |
| nginx | partial | 13,494.9; 13,503.0 / 13,367.1; 13,378.5 | 5,307.6; 1,068.0; 7,127.4 / 5,307.6; 1,068.0; 7,002.9 |
| HAProxy | silent | 10,154.0; 10,160.9 / 10,060.6; 10,069.2 | 3,087.6; 0.0; 7,073.4 / 3,087.6; 0.0; 6,981.6 |
| HAProxy | partial | 14,340.5; 14,352.8 / 14,236.1; 14,319.2 | 7,306.0; 0.0; 7,046.8 / 7,306.0; 0.0; 7,013.2 |

Record sha256 (`~/lab/p3/m4b2/`): b3thp1.thp.json
d827f7e615ce7903603e59fa81d08050f13477f32b2b5b0ffed1ea4b82645556, b3thp1.clock.json
dc553b4ad6340afea7cb1f77dbc10e615d1ee6de96e7ea4568dd4148449d0e7c, b3thp1.notrack.json
d8d8626c818a910a8a59d12352dba69a8dd3c519da8a9b3a99fa54c54170b74a, b3thp1.done
344af53895ea262f0515888733f61cf43e2b66cacc0c9424844fde1dcc392081, b3/b3thp1/windows.jsonl
5bb87ea7fd17ff3cbbaad4de0ba5ce8e1a61813cecb82445e912155090ebd853; thpjobs/t1.thp.json
f815dc13fd9ab8955410f1262b9d324ff9cbc02703f158b04b9e7ad3b7dbd373, thpjobs/t1.done
b753ce1b0ba2c1e5f68c88156e637dd8d5ce109b16b99d1f77aa696fc510dcba.

### Step 0: the revision log (a67e1de, 9bd2bec)

- "Section 10's check of the server's system-call counters": the coordinator's decision, logged as a
  reading. The check compares the counters with `perf stat`'s count of the same calls' entry
  tracepoints; `perf trace -s` is the cross-check, its shortfall reported per row. Evidence: 264 of
  264 checks agree with `perf stat` (tracedev2 178, tracedev3 86); `perf trace -s` agreed in 146 of
  178 and 57 of 86, short by at most 0.31% and 0.42%, no lost event reported. The proxies' system
  calls per connection stay `perf trace -s`'s (section 10 names it for them), with `perf stat`'s
  count of the checked calls beside it. `systrace.py`: `agrees_with_perf_stat` is section 10's
  check, `agrees` the cross-check, and `trace_shortfall_max_share` the largest shortfall per row.
  Rows keep both fields.
- "Transparent huge pages before the code freeze": the cause (M4b-1's b3dev1 and b3diag3), the
  change and the check above.

### Step 1: the toolchains

| Tool | Vendor and version | Source | sha256 and its check |
|---|---|---|---|
| JDK | Eclipse Temurin 25.0.4.1+1 (25 is the latest LTS: Adoptium's API, `most_recent_lts` 25; 25.0.4.1+1 its latest GA build, published 2026-08-21; 25.0.5 is due later in October, so the freeze reads it again) | https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/OpenJDK25U-jdk_x64_linux_hotspot_25.0.4.1_1.tar.gz | dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e, equal to the asset's `.sha256.txt` and the API's checksum; PGP signature good (Adoptium key 3B04 D753 C905 0D9A 5D34 3F39 843C 48A5 65F8 F04B, keyserver.ubuntu.com, no trust path). In `~/opt/jdk-25.0.4.1+1` (install.sh jdk) |
| Netty | 4.2.18.Final, 13 jars (the native epoll transport's linux-x86_64 jar among them) | Maven Central, `bench/competitors/netty/maven.lock` | every jar's sha256 in the lock, equal to Central's `.sha1`, `.sha256` and `.sha512`; in `~/opt/netty-4.2.18.Final/lib` |
| Jetty | 12.1.13, 8 jars (slf4j-api 2.0.17 among them) | Maven Central, `bench/competitors/jetty/maven.lock` | the same; slf4j-api has only `.sha1` published; in `~/opt/jetty-12.1.13/lib` |
| Maven, Gradle | not used | | the closures are small and read from the POMs (profiles and test scopes left out); `javac` and `java` confirm them |
| Rust | Arch's rust 1:1.98.1-1 (rustc 1.98.1, 48a229cea 2026-09-01, LLVM 22.1.8), installed before; hyper-util 0.1.21's `rust-version` is 1.85 | L's package | package sha256 a0e72c52cf8b8cbc9a16a82fca439e6fe502c6dc4a27b7c1d805f0399ad709ba |
| rust-src | 1:1.98.1-1, for `-Zbuild-std` in the sanitizer builds | `sudo pacman -S --needed rust-src` (no `-y`), 2026-10-03 | package sha256 68f5e4b1592418cf68e816a71f4490bd26963394055485e369e90072f691641c |
| Go | go1.27.1 (Arch's go 2:1.27.1-1), `GOTOOLCHAIN=local` | L | cmux v0.1.5, x/net c7110b5ffcbb (cmux's own pin) and x/text v0.3.3 by `bench/competitors/cmux/go.sum` |
| Rust crates | 37 crates (Cargo locked 37 packages; Cargo.lock has 38 entries, the harness included), among them hyper 1.11.1, h2 0.4.19, tokio 1.53.2, http-body-util 0.1.5, bytes 1.12.1 | crates.io | `bench/competitors/hyper-util/Cargo.lock`; every build `--locked` |

A nightly Rust is not needed: P2's records built their Rust arms with `-Zsanitizer=address` on the
stable rustc with `RUSTC_BOOTSTRAP=1`, and the same rustc with rust-src at its own version rebuilds
the standard library for ThreadSanitizer, so the measured and the sanitizer builds share one
compiler (the gate matches the compiler).

### Step 2: the harnesses

Each in `bench/competitors/<name>/`: the program, `cases.args` and `b3.args` (Appendix B: cases and
B3; one argument and its value per line, each with its reason, rendered by `competitors.py` with
MATCHED and FALLBACK lines as the proxies' cases files), `probe.sh`. First-party, so built per
checkout into `<build>/harness` by `build_harnesses.sh` (release; asan and tsan for cmux and
hyper-util), with `build.json` (sources' and outputs' sha256, commands, tools). Every reply is the
server's: 200, `Content-Length: 13`, `Hello, World!`. The test certificate and key of
`tests/fixtures/tls`, TLS 1.3 only.

| Library | What it serves | Configuration highlights (source) | B3 |
|---|---|---|---|
| Netty 4.2.18.Final (`NettyHarness.java`) | TLS by SniHandler, then the decrypted bytes detected again; h2c (prior knowledge or Upgrade) and HTTP/1.1 by CleartextHttp2ServerUpgradeHandler and the HTTP codec; a second listener with HAProxyMessageDecoder first (PROXY required) | after the PortUnificationServerHandler example (5 bytes read without consuming; "PR" added for the h2c preface); the native epoll transport, `MultiThreadIoEventLoopGroup(1, EpollIoHandler)` with `Epoll.ensureAvailability()` (Appendix B; the Netty wiki); ReadTimeoutHandler and SniHandler's handshake timeout at the matched 3 s (SniHandler sets its SslHandler's to the same, SniHandler.newSslHandler at the tag); at the defaults ReadTimeoutHandler is left out and SniHandler keeps 10 s; the JDK's TLS provider, TLS_AES_128_GCM_SHA256, ALPN h2 and http/1.1 | timers 60 s; `SO_BACKLOG` 10000; no PROXY listener |
| Jetty 12.1.13 (`JettyHarness.java`) | one ServerConnector: DetectorConnectionFactory over SslConnectionFactory and ProxyConnectionFactory, then HTTP/1.1 with HTTP2CServerConnectionFactory; the PROXY cases' listener has the same factories | the programming guide's "Choosing ConnectionFactory via Bytes Detection"; idle timeout matched 3 s (default 30 s); the KeyStore built in memory from the PEM fixtures; TLS 1.3, TLS_AES_128_GCM_SHA256; no ALPN module (the frozen line has TLS then HTTP/1.1); no SLF4J provider, so no logging | idle timeout 60 s; `acceptQueueSize` 10000 |
| cmux v0.1.5 with Go net/http (`main.go`) | HTTP2(), HTTP1Fast(), TLS() (crypto/tls, then HTTP/1.1 or h2 by ALPN), PrefixMatcher("SSH-") to the server's SSH handler; Any() last to the server's SMTP handler in the fallback kind | `SetReadTimeout` matched 3 s (none at the defaults); `http.Server.Protocols` with UnencryptedHTTP2; TLS 1.3, X25519, no session tickets (crypto/tls fixes the TLS 1.3 suites); `ErrorLog` discarded (no per-connection logging); GOMAXPROCS 1 from the affinity mask; Go's collector defaults; on SIGUSR1 `debug.FreeOSMemory` and one line with HeapInuse | timer 60 s; Any() kept; backlog from `net.core.somaxconn` |
| hyper-util 0.1.21 (`main.rs`) | `server::conn::auto`: HTTP/1.1 and h2c | a tokio runtime with one worker thread (`new_multi_thread().worker_threads(1)`), the accept loop in `block_on` as hyper-util's examples; no detection timer and none added; cargo's default release profile | `TcpSocket::listen` with backlog 10000 |

The JVM's flags, `bench/competitors/jvm.args`, each with its reason: `-XX:+UseG1GC` (under taskset on
one CPU the pinned JDK chose Serial); `-Xms253755392 -Xmx4037017600`, the guide's 1/64 and 1/4 of
physical memory as the pinned JDK computes and aligns them on L (`-XX:+PrintFlagsFinal`, MemTotal
15,766,196 kB); `-Djava.net.preferIPv4Stack=true` (found on L: both harnesses listened in
`/proc/net/tcp6`, IPv6 sockets taking IPv4-mapped connections, while every other system opens IPv4
ones, so B3's Ks would compare different socket objects); `--enable-native-access=ALL-UNNAMED`
(JDK 25's JEP 472 warning at Netty's JNI load); the JSSE properties for X25519,
ecdsa_secp256r1_sha256 and no stateless session tickets.

Netty's allocators, read on L from the first accepted connection of the pinned version (the
proposal's CP6 row: "Which allocator the native epoll transport uses is read at the code freeze"):
`io.netty.buffer.AdaptiveByteBufAllocator` and `io.netty.channel.AdaptiveRecvByteBufAllocator`.

opgen (7e1c4e6): Jetty's first h2 header block starts with an HPACK dynamic table size update
(`3f e1 1f`, 4096) before `:status 200`; RFC 7541 puts such updates at the start of a block
(s4.2, s6.3), and opgen required 0x88 at the first byte, so it failed Jetty's h2c exchange as a
protocol error. opgen now skips size updates first (`bench/gen/hpack.hpp`, header-only, test
`gen.h2_status`, a pure test on every platform). No other server's first byte changes.

**Runner integration (b61b71b, 85e9dd0).**
- `competitors.py`: the four libraries in `SYSTEMS` (`library`, kinds cases, cases-fallback for cmux,
  b3; no m3), `LIBRARIES`, `JVM_SYSTEMS`; `start(..., harness=)` with `harness_dir(build)`; the
  command: the pinned JDK's `java`, `jvm.args`, `-cp <harness.jar>:~/opt/<lib>-<v>/lib/*` and the
  class, or the Go or Rust binary, then the rendered arguments; started directly under `taskset`,
  so the pid file names the JVM or the binary (never a shell); new fields `REPO` and `TIMER_MS`.
  `PROXY_SYSTEMS` adds Netty and Jetty, `FALLBACK_SYSTEMS` cmux.
- `probe.py --system <library> --kind cases|cases-fallback|b3`: the harness alone on CPU 14;
  `routes` by `opgen --probe` for each protocol it serves (LIB_PROTOS); the silent and
  partial-ClientHello watches judged against `EXPECT_LIB` ("close", "hold", "greet" for cmux's
  fallback, "reject"), from the survey and Appendix B.
- `cases_check.py`: the libraries with COVERS (Netty and Jetty: HTTP/1.1, h2c, TLS; cmux: those and
  SSH; hyper-util: HTTP/1.1 and h2c), no backend, the PROXY listener for Netty and Jetty, cmux's
  fallback judged at matched timers only (at its defaults no read timeout, so Any() is never
  reached: recorded).
- `b3.py --system netty|jetty|cmux|hyper-util|one-port-inproc [--backend epoll|io_uring]`: an
  in-process system on CPU 14, no stub (section 5.2), U over its process group, Kq and the
  established count on its port. The server's arm: one-port mode, in-process dispatch, replay, every
  timer 60 s, on either backend (`--backend` also reaches the relay arm). The probe: HTTP/1.1 with
  keep-alive, and a TLS 1.3 handshake (SNI oneport.test, the certificate verified, ALPN http/1.1,
  X25519) then HTTP/1.1 where the system terminates TLS (not hyper-util); each client closes by
  reset. WL7's collector steps, the baseline included: `jcmd <pid> GC.run` then `GC.heap_info` with
  the pinned JDK's jcmd on CPUs 0 and 1, 3 s before each reading (the attach socket is a Unix one, no
  TCP); SIGUSR1 to the cmux harness 1 s before, its HeapInuse line read from its stdout; caddy-l4's
  step unchanged. A failed step invalidates the window.

**Probes and route checks** (job libsetup3, 8288b70, Release; untimed):

| Library | cases (matched timers) | cases-fallback | B3 (watch 32 s) |
|---|---|---|---|
| Netty | routes HTTP/1.1, h2c, TLS pass; silent closed at 3.04 s; partial closed at 3.21 s | | routes pass; both held |
| Jetty | routes pass; silent closed at 3.36 s; partial closed at 3.46 s | | routes pass; both held |
| cmux | routes HTTP/1.1, h2c, TLS, SSH pass; silent closed at 3.00 s; partial held (TLS() matches the record header and clears the deadline) | routes pass; the SMTP greeting at 3.00 s; partial held | routes pass; both held |
| hyper-util | routes HTTP/1.1, h2c pass; silent held; partial closed at once | | routes pass; silent held past 32 s; partial closed at once |

Every probe judged its expectation and passed. `cases_check.py`, matched and default timers: every
judged route passes (TLS with SNI oneport.test and ALPN http/1.1), PROXY v1 and v2 on Netty's and
Jetty's PROXY listener pass at both settings, cmux's fallback greets at 3.00 s at matched timers and
not at its defaults (recorded). MQTT is covered by none of the four.

**Sanitizer development checks of the Go and Rust harnesses** (not records; libsetup3, then
tsancheck1 at a83263d): the ASan and TSan builds of `build_harnesses.sh`, each harness's probe in its
cases kinds and its route checks at both timer settings, every harness log searched with the lab's
report pattern plus Go's race report:
- ASan (cmux `go build -asan`; hyper-util `-Zsanitizer=address -Zbuild-std`): 0 report lines in 15
  harness logs, every probe and route check passing.
- TSan, cmux (`go build -race`): 0.
- TSan, hyper-util (`-Zsanitizer=thread -Zbuild-std`): 10 reports, 2 per process in each of 5,
  every one with tokio's `RegistrationSet::allocate` as the earlier access: the main thread
  initialises the listener's `ScheduledIo` and adds it to epoll, and the worker thread reads and locks
  it after `epoll_wait` returns its token. The order is the kernel's, which ThreadSanitizer does not
  see. `bench/competitors/hyper-util/tsan.supp` holds one entry for that frame, with its reason; with
  it (tsancheck1) 0 reports in 5 logs, every check passing. For the coordinator: whether the Rust
  harness's TSan record may run with this suppression (open, below).
- The harnesses end by SIGTERM in these checks, so LeakSanitizer's exit check did not run.

**B3 functional windows of the in-process systems** (job b3lib2, 595eded, Release, the harnesses
built at the same commit; lock, floor, NOTRACK, THP at madvise; development data):

| System | Case | Backend | Valid | W at sample 1 and 2 | U, Kq, Ks at sample 2 | Collector |
|---|---|---|---|---|---|---|
| Netty | silent | | yes | 8,876.9; 8,885.5 | 1,712.5; 0.0; 7,172.9 | jcmd 0.42, 0.35, 0.32 s |
| Netty | partial | | yes | 9,470.4; 9,476.5 | 2,331.4; 0.0; 7,145.1 | 0.41, 0.36, 0.33 s |
| Jetty | silent | | yes | 12,825.8; 12,832.4 | 5,732.4; 0.0; 7,100.0 | 0.40, 0.35, 0.31 s |
| Jetty | partial | | yes | 38,805.1; 38,896.4 | 32,122.1; 0.0; 6,774.4 | 0.42, 0.38, 0.40 s |
| cmux | silent | | yes | 10,482.1; 10,489.9 | 3,718.8; 0.0; 6,771.1 | SIGUSR1 0.02 to 0.04 s |
| cmux | partial | | yes | 19,420.4; 19,427.7 | 12,528.8; 0.0; 6,898.9 | 0.02 to 0.06 s |
| hyper-util | silent | | yes | 9,334.4; 9,340.9 | 2,432.2; 0.0; 6,908.7 | none |
| hyper-util | partial | | no | 2,786.5; 2,789.4 | 7.4; 0.0; 2,782.0 | none |
| server, in-process | silent | epoll | yes | 7,358.1; 7,361.7 | 402.2; 0.0; 6,959.5 | none |
| server, in-process | partial | epoll | yes | 56,666.1; 56,668.2 | 49,746.3; 0.0; 6,921.8 | none |
| server, in-process | silent | io_uring | yes | 8,002.8; 8,005.6 | 402.2; 0.0; 7,603.4 | none |
| server, in-process | partial | io_uring | yes | 57,248.2; 57,254.7 | 49,742.6; 0.0; 7,512.1 | none |

- hyper-util's partial-ClientHello window is invalid by the established count (0 of 10,000 at both
  samples): hyper-util reads 0x16, which is not the h2 preface, hands the bytes to its HTTP/1 parser,
  and closes the connection at once (its probe: "closed at once"). It is not a pending connection;
  section 6.2 has no such cell ("hyper-util serves no TLS"). Not a runner failure.
- Every probe passed (TLS 1.3, TLS_AES_128_GCM_SHA256; ALPN http/1.1 except Jetty, which has no ALPN
  module and selected none), TIME-WAIT 0 at the baseline and both samples, no listen overflow.
- No system held AnonHugePages at any 1 s sample, the JVMs and Go included, and the host's
  `thp_collapse_alloc` did not move (1,563 before and after the job). From t = 11 s to sample 2
  the JVMs' VmRSS moved by more than 100 kB in a 1 s sample only in the 2 s after the first
  in-window `GC.run` (t about 17 s): up 14.8 and 20.2 MB (Netty, silent and partial), 16.7 and
  1.3 MB (Jetty), and in Jetty's partial window 0.9 MB more after the second (t about 22 s); cmux's
  fell 3.0 MB after one `FreeOSMemory` (t about 19 s) and otherwise moved by at most 60 kB;
  hyper-util's and the server's did not move.
- The JVMs' heap after each `GC.run`: about 7 MB used at the baseline, 22 to 27 MB (Netty) and 24 MB
  (Jetty silent) to 274 MB (Jetty partial) at sample 2 (`GC.heap_info`, in the rows).
- The server in-process with a partial ClientHello holds 49.7 kB of U per pending connection on
  both backends: by design (section 2.1, "with replay, the handler's buffer from the first byte"),
  the TLS handler takes the connection at byte 6, and its OpenSSL state for an unfinished handshake
  is held from then on. Netty holds 2.3 kB (SniHandler buffers the ClientHello and makes no TLS
  engine until it is complete), cmux 12.5 kB, Jetty 32.1 kB. These are B3's descriptive cells
  (6.2), but under rule D2 this is engineering for M5 (below). In the silent case the server's W
  (7,362 on epoll, 8,006 on io_uring) is below every library's.
- Job b3lib1 (a83263d) ran no window: its TLS probe reset a socket that `wrap_socket` had already
  taken over (Errno 9) before any opening; stopped by SIGTERM, every setting set back; fixed in
  85e9dd0 with a test against a local TLS stand-in.

Record sha256 (`~/lab/p3/m4b2/`): b3lib2.thp.json
f377f7b03dc43095ef014e8ab9c6efe8524fdc2c9ee47bbf516a5474d96c4287, b3lib2.clock.json
12b7a9a5c5dbd57443b1298cc50e9f52dad352a01361cb471601cab097edc019, b3lib2.notrack.json
bcd00a05961c1beb2396940cad1da21cb5bcd049c67e0e9147293f2a5ed85568, b3lib2.done
3e0a93e60d7968da58276adfb521415186f03de33316f994c654f492adada922, b3/b3lib2/windows.jsonl
548737608ee12bf42678533953cb4f94966b214d4964d47b0e26c2f25818f1e8; libsetup3.log
8172d1e705e8191f0c18f395e911a03df8af7271f3a4259e935b93656a8e2c72, lib/libsetup3/cases/cases_check.jsonl
eafbd55fef326ae8be4ea826421b33a293f4763342646d0e202b2698cca8d5c0, tsancheck1.log
f29b97d2b921fa0d065b38e7b6fb541b0b120dc68f03aeaf74f2fe99375cca0e.

### Sanitizer coverage of the harnesses (c61a8e8, a83263d)

`bench/coverage.json`'s `targets` now names the harnesses (the records driver of the code freeze
must name them the same): `harness_cmux` and `harness_hyper_util` without MSan,
`harness_netty` and `harness_jetty` without any sanitizer, each with its reason; a declared gap
"UBSan in the Go and Rust harnesses" (section 11 says "ASan with UBSan"; UBSan has no Go or Rust
form, so their ASan records are ASan alone). The decisions:
- Go: ASan by `go build -asan`, TSan by `go build -race`, both with `CC=clang` (clang 22.1.8), as
  P2's Go arms; MSan declared (`go build -msan` only lets Go code interoperate with C code built with
  MSan; the harness has no C code of its own and Go zero-initialises what it allocates).
- Rust: ASan and TSan by `-Zsanitizer=address|thread` on the stable rustc with `RUSTC_BOOTSTRAP=1`
  (P2's precedent) and `-Zbuild-std` from rust-src 1.98.1, `--target` given so build scripts are not
  instrumented; MSan declared (rustc's `-Zsanitizer=memory` exists, unstable, and was not attempted,
  as the frozen text declares the gap). TSan with the one suppression above, pending the
  coordinator.
- JVM: no sanitizer applies (bytecode on a pinned, uninstrumented runtime); declared whole.
`bench/test_gates.py` already checks a Go harness's declared MSan gap and passes with the new file.

### Step 3: checks

| Host | Build | Commit | Build | CTest | Report lines |
|---|---|---|---|---|---|
| L | Debug, clang 22.1.8 | 595eded | 0 warnings | 375 passed | 0 |
| L | ASan+UBSan | 595eded | 0 warnings | 375 passed | 0 |
| L | Python 3 (runner and competitor tests) | 595eded | | run.test_runner 54, run.test_competitors 31 (2 skipped) | |
| W | Python 3 (pure parts) | 595eded's tree | | run.test_runner 54 (12 skipped, Linux), run.test_competitors 31 (2 skipped) | |

- L: lab job checks595 (`~/lab/p3/sancheck.sh` from a fresh clone of the lab remote at 595eded,
  Debug and ASan+UBSan at once, `ctest -V -j 8`; NOTRACK, the clock floor and THP at madvise on).
  375 is M4b-1's 374 and `gen.h2_status`. The suite's integration part of run.test_competitors (the
  probe of the server's relay and a short hand-off window per M3 protocol) ran in both;
  run.test_runner's Linux tests (thp.sh on a copy of the sysfs tree, its signal and refusal paths;
  the cmux collector's signal step and jcmd's step against stand-in processes; the TLS probe against
  a local TLS stand-in) ran in both.
- Log sha256 (L, `~/lab/p3/m4b2/check/595eded/`): debug-595eded.build.log
  860a9a7830f10f01d335ee433d773e02b4584b739de1c1f2083822b17fec1c43, debug-595eded.ctest.log
  a0268c59a8c8c7eaf0e08952649a8a0a3a78bbf6679bcb579e0b525402049c35, asan-595eded.build.log
  9b33bf0098ba6c12fcda4e840f5f12b929fd78a9c78bc555e3b6b60e3a9a9e63, asan-595eded.ctest.log
  48686343d2f0a1d2c75addec72b67d9fb28c122739246bfe4f59e5babc007b96.
- Probes: every probe of the four libraries passes in every kind (step 2), and the B3 functional
  windows pass section 7's settling rule with THP at madvise: 8 of 8 for nginx and HAProxy
  (b3thp1), 11 of 11 for the in-process systems whose cases are B3 cells or their server arm
  (b3lib2).

### Readings of the frozen text in M4b-2 (for the coordinator)

1. Jetty: Appendix B puts ProxyConnectionFactory inside the DetectorConnectionFactory of the one
   connector, so the PROXY header is detected, not required (survey 2.16), and its next protocol is
   HTTP/1.1. The PROXY cases run on a second listener with the same factories; there HC11 (no header)
   is served as HTTP/1.1 and a PROXY header followed by a ClientHello (HC13) goes to HTTP/1.1.
2. cmux: Appendix B lists Any() unconditionally, while HC6 needs a listener without a fallback. The
   cases configuration has two kinds, as HAProxy's, Envoy's and sslh-ev's: "cases" without Any(),
   "cases-fallback" with it. B3 starts from Appendix B's line, with Any() last; within a 30 s window
   at a 60 s timer no silent connection reaches it.
3. Netty's and Jetty's B3 configurations have no PROXY listener: B3's openings send no PROXY header
   and a window reads one listener ("B3 starting from its case configuration").
4. The JVM's `-Djava.net.preferIPv4Stack=true`: every system then opens IPv4 sockets for
   127.0.0.1, as the server and the proxies do.
5. Section 2.1's TLS settings ("the same settings in the server, the backend and the generator") are
   applied to the libraries that terminate TLS as far as each allows: TLS 1.3 only everywhere;
   TLS_AES_128_GCM_SHA256 where configurable (Netty, Jetty; crypto/tls fixes its TLS 1.3 suites);
   X25519 and ecdsa_secp256r1_sha256 (the JSSE properties; Go by its curve list and the certificate);
   no session tickets (JSSE's stateless ticket extension off; Go's `SessionTicketsDisabled`).
6. Netty's ReadTimeoutHandler bounds silence for the connection's life (Netty's handler, as
   documented), not detection alone; SniHandler's handshake timeout takes the same value. At the
   defaults ReadTimeoutHandler is left out (it has no default).
7. The in-process B3 probe checks one exchange of each protocol the system serves among B3's:
   HTTP/1.1, and TLS with HTTP/1.1 where it terminates TLS (WL7's "probe"; section 4.1).
8. WL7's collector steps run a fixed lead before each reading, the baseline included: 3 s for the
   two jcmd calls, 1 s for cmux's signal, 1 s for caddy-l4 (M4b-1).
9. hyper-util's partial-ClientHello window has no pending connection to measure (closed at once),
   consistent with 6.2's "hyper-util serves no TLS".
10. The server's B3 arm against the libraries is one-port mode, in-process dispatch, its default
    detection mode (replay), every timer 60 s, on epoll and on io_uring (5.2, 6.2).
11. Netty's receive allocator, which the proposal reads at the code freeze: on 4.2.18.Final with the
    native epoll transport, AdaptiveRecvByteBufAllocator, with Netty 4.2's default
    AdaptiveByteBufAllocator; Appendix B's Buffers row ("adaptive, 64 to 65536 bytes, starting at
    2048") names the receive allocator, which is kept.

### Open for the coordinator and Alex

- **The Rust harness's TSan record:** with `bench/competitors/hyper-util/tsan.supp` (one entry,
  tokio's registration through epoll, a false positive by the evidence above), or a declared TSan
  gap instead. Decide before the records of the code freeze.
- **The server's in-process footprint with a partial ClientHello** (49.7 kB of U per pending
  connection, above Netty, cmux and Jetty in development windows): B3's descriptive cells only, but
  rule D2 asks for engineering. A candidate for M5: create the TLS state only once the ClientHello is
  complete (as Netty's SniHandler does), within section 2.1's bounds (the handler's buffer from the
  first byte).
- From before: sslh-ev's M3 cells (invalid by the error rule as configured); the per-connection
  decision record WL8 needs against a server in its own process; the competitors' hard cases need an
  `opcase` mode against a system by port (M4b-1); `RELAY_BUF`, `IORING_OP_SEND` and splice's worker
  threads (M5); more than one worker on IOCP (M6b).

### Design choices of M4b-2

| Name | Value | Where | Reason |
|---|---|---|---|
| THP wrapper exits | 97 (not set; the job does not run), 98 (not restored) | `thp.sh` | beside notrack.sh's 90 to 93 and clockfloor.sh's 95, 96 |
| Wrapper order | lablock, clockfloor.sh, thp.sh, notrack.sh, the job | `lab_job.sh` | each host setting outside the next; the floor unchanged |
| Memory sampler | 1 s | `b3.SAMPLER_S` | M4b-1's diagnostic's period |
| Collector leads | JVM 3 s, cmux 1 s (caddy-l4 1 s) | `b3.COLLECT_LEAD_S` | two jcmd calls each start a JVM (0.3 to 0.4 s each on L) |
| jcmd and Go collector timeouts | 60 s, 10 s | `b3.JCMD_TIMEOUT_S`, `GO_COLLECT_TIMEOUT_S` | a failed step invalidates the window rather than hanging it |
| Harness location | `<build>/harness` | `competitors.harness_dir` | first-party code built per checkout, beside the C++ build |
| HPACK integer bound | 5 bytes after the prefix | `opgen hpack.hpp` | a 32-bit value needs at most 5 (RFC 7541 s5.1) |
| Library probe watch | 6 s in the cases kinds, 32 s in B3 | `probe.WATCH_S` | as the proxies' M3 and B3 watches |

### Lab journal and raw data

Two lines in the Papers repo's `lab/journal.jsonl` (Papers 5341785 and 5846aaf, local, not pushed),
each marked development: b3thp1 and b3lib2. No line for the jobs that ran no window: t1 (the SIGTERM
check), libsetup1 to libsetup3 (installs, builds, probes, route checks, sanitizer checks; libsetup1
and libsetup2 stopped at a build error and a mistyped commit before any check), tsancheck1, b3lib1
(no opening ran), checks595. Everything stays on L under `~/lab/p3/m4b2/`, archived in
`~/lab/runs-archive/p3-m4b2-20261003T154225.tar.gz` (sha256
fa1877066a006d8c29381aff88a54e84f760a034ca8b3bfee6bf2aa33885cb88, beside it in a `.sha256` file; 642
members; made under the lab lock); build trees, source clones, the sanitizer harness builds, the
discovery directory and the check builds are left out.

## M5 exit criteria (set by the coordinator before M5)

Written before any engineering of M5. M5 ends when all five hold, or when criterion 5 stops it.

1. **Untimed counter deltas, one-port against dedicated**, checked with section 10's untimed counter
   checks (`bench/run/systrace.py`), never with windows. Replay mode: 0 extra system calls and 0
   extra user-space copies per connection. Peek mode: exactly the MSG_PEEK (or poll) operations the
   design adds, and nothing else. This holds for every protocol, backend and dispatch.
2. **B3 in relay against each of the five proxies**, both cases, both backends: the server's W at
   least 1.25 times below the proxy's (W_proxy / W_srv at least 1.25), in development windows. The
   frozen bound is 1.10; 1.25 is headroom.
3. **M3, the relay against nginx and against HAProxy**: ratio (server / proxy) at least 1.05 in at
   least three development sessions each. Otherwise record that the margin is thin, and let the
   frozen narrowing order speak.
4. **The suite green under all four sanitizers** (Debug, ASan+UBSan, TSan, MSan) after every change.
   Every engineering timing journaled as development.
5. **A cap of two engineering rounds.** If a criterion is still unmet after round two, M5 stops,
   this file records the gap, and the paper narrows per the frozen order (section 12: M3, then B3,
   then the cost family per backend).

Note on criterion 2, written by M5 before any engineering (development data and a bound derived
from it, not a result). In every B3 window so far (b3dev1, b3thp1, b3lib2), every system's Ks lies
between 6,771.1 and 7,778.3 bytes per pending connection, most of it the kernel's two loopback
socket ends that `K_BASE` will measure; the server's relay had Ks 7,215.1 (silent) and 7,102.5
(partial ClientHello), and sslh-ev had W 7,644.0 and 7,657.5 with U 399.8 and 524.3 (b3dev1). The
server's W is at least its own Ks, which no change to the server can bring below a bare held
socket's. Even at the lowest Ks any system has shown and U = Kq = 0, W_sslh / W_srv would be at
most 7,657.5 / 6,771.1 = 1.13; at the relay's own Ks it is at most 7,657.5 / 7,102.5 = 1.08, and
with the server's connection state (U about 400 bytes in the silent case) it stays near 1.0. So
criterion 2 is out of reach against sslh-ev by construction, and so is the frozen 1.10 unless the
server's Ks and U together fell below 6,961 bytes (7,657.5 / 1.10), under every Ks the relay has
shown. M5's rounds go to the other four proxies.
There, in those windows, the server's relay on epoll was ahead of nginx by 11,971.0 / 7,622.2 = 1.57
(silent) and 13,378.5 / 11,773.1 = 1.14 (partial), and of HAProxy by 1.32 and 1.22 (b3thp1 for the
proxies under THP at `madvise`, b3dev1 for the relay under `always`, so not the same day); the
relay on io_uring had not run in B3.

## M5, 2026-10-03

M5: step 0 (the exit criteria above, the revision log, tokio's TSan suppression), then two
engineering rounds against the exit criteria: round 1 (2127a8a to deaabfe: the TLS handler's
deferred OpenSSL state, the relay's parked ClientHello and its system calls, and the two carried
items) and round 2 (e69e860 to ac84f2d: io_uring's receives as `IORING_OP_READ`, the receive
counters split by result, the relay's drained-source rule, and three fixes of tests). Nothing in
this section is a result: every window, session, profile and check is development data, journaled
where it times anything; one-port mode was timed only against the competitors and against its other
option, and dedicated mode was never timed, so no FC5 pair exists.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| e06fa82 | docs: status.md, M5 exit criteria, with the bound development B3 data puts on sslh-ev's cells |
| d166e44 | docs: hypotheses.md revision log, M4b-2's eleven readings |
| 6057afa | feat: the harnesses' named inputs and inputs hash (harness_inputs.py), hyper-util's tsan.supp among them; build.json; coverage.json records the suppression; tests |
| 2847315 | feat: the runners take the detection mode; systrace.py's repeats; counterdelta.py; every slab cache in each B3 reading; journal.py --kind b3; tests |
| 6bb6484 | feat: perfrec.py, a profile of a front of M3 under its load |
| 2734b19 | fix: perfrec.py's perf report (-f); systrace.py's relay on either backend; journal.py --kind perf |
| 2127a8a | feat: the TLS handler makes OpenSSL's state only once the ClientHello is complete (both arms); clienthello::scan; tls_states; tests |
| 23eae82 | perf: the relay's footprint and system calls (one-port relay only): the parked ClientHello; TCP_NODELAY from the listener; no SO_ERROR on success; no speculative reads; the half-close's short read; close() for the last direction; tests |
| deaabfe | feat: the binary's decision record for WL8 (--record) and opcase case (hard cases by port); tests |
| e69e860 | feat: the receive counters split by result (recv_eof, recv_again; both arms) |
| c8e588a | fix: handlers.tls_deferred's last input passes the detector; a range-loop copy |
| 666a6b7 | perf: io_uring's receives are IORING_OP_READ, not IORING_OP_RECV (both arms) |
| 333d846 | perf: the relay takes a short read as the source drained (one-port relay only) |
| 0aa639e | fix: the relay remembers a side's reported half-close (333d846 left a FIN unseen) |
| ac84f2d | fix: the runner's tests when two suites run at once (ports by build tree; the signal tests wait for the job) |
| 681c58e | fix: systrace.py checks the connect counter on epoll only (the relay's connect on io_uring is a ring operation) |

Papers (local, not pushed): the lab journal (below). Every one-port commit is on the `lab` remote;
nothing is pushed to origin.

### Step 0

- **Exit criteria** (e06fa82): written above, under "M5 exit criteria (set by the coordinator before
  M5)", before any engineering, with the bound that development B3 data puts on sslh-ev's cells.
- **Revision log** (d166e44): "Readings fixed during engineering (M4b-2), before the code freeze",
  M4b-2's eleven readings, one line each with why it follows. The two that change what runs are
  supported by the frozen lines, and each says why: Jetty's PROXY header is detected because
  Appendix B puts `ProxyConnectionFactory` inside the one `DetectorConnectionFactory`, which falls
  through to the next protocol when no detector recognises the bytes (the survey, section 2.16,
  says so of the frozen structure); cmux's `Any()` stays in B3 because Appendix B lists it without
  a condition and starts B3 from the case configuration, and only the hard cases' "cases" kind
  leaves it out, because HC6 asks for a listener without a fallback. Not logged by M5, and not
  M5's: M4b-1's nine readings ("Readings of the frozen text in M4b-1") are still not in the
  revision log.
- **tokio's TSan suppression** (6057afa), the coordinator's decision (allowed, one entry, scoped to
  tokio's internals):
  - `bench/competitors/harness_inputs.py` names each harness's inputs (its sources and lock files;
    the hyper-util harness's `tsan.supp` among them, since a suppression decides what a TSan
    record reports) and hashes them as `lab/bin/inputs_hash.py` does (the sorted lines
    "<path>\t<sha256>", CRLF read as LF). `build_harnesses.sh` records the list, the hash and the
    environment each flavour runs with in `build.json` (hyper-util's TSan:
    `TSAN_OPTIONS=suppressions=<checkout>/bench/competitors/hyper-util/tsan.supp`). Editing the file
    changes the hash, so a record made with another suppression no longer covers the harness. The
    run configurations (`cases.args`, `b3.args`) and the probe scripts are not inputs.
  - `bench/coverage.json`: `targets.harness_hyper_util.suppressions` records the file, its one entry,
    the run environment, the decision and the evidence (10 reports without it in libsetup3, 2 per
    process in each of 5, all with `RegistrationSet::allocate` as the earlier access, the order
    epoll gives and TSan cannot see; 0 with it in tsancheck1); the gate reads only `not_covered_by`
    and `reason` of a target (`bench/gate_lib.py`), so the new key changes no gate decision
    (`bench/test_gates.py` passes).
  - Tests (`run.test_competitors`, `HarnessInputs`): every input exists; `tsan.supp` is one of
    hyper-util's and holds exactly the one entry; a copy of the inputs hashes the same, CRLF hashes
    the same, an added line changes the hash, a missing input is an error.

### The engineering, round by round

**Before (6bb6484).** The runners first learned to take the server's detection mode (handoff.py,
b3.py, systrace.py: replay, the proposed default of section 2.1 until rule E, or peek) and
systrace.py to repeat each cost cell's arms, interleaved; `counterdelta.py` computes one-port
against dedicated per connection from section 10's untimed rows, after each arm's idle pass; every
B3 reading keeps the size of every slab cache (`slab_all`), deciding nothing, so Ks's growth can be
attributed to caches; `perfrec.py` profiles a front of M3 under its load. The before data:
m5b3a and m5b3a2 (B3), m5perf1 and m5perf2 (profiles), m5m3a (M3 sessions), m5tr1 (counters).

**Round 1** (2127a8a, 23eae82, deaabfe; measured as deaabfe: m5b3b, m5perf3, m5m3b, m5tr2):
- The TLS handler (in-process dispatch; both arms, since dedicated mode's TLS port runs the same
  handler) makes OpenSSL's state only once the ClientHello is complete in the handler's buffer, or
  cannot complete there: malformed, not a ClientHello, needing more record bytes than the buffer
  has room for, or the peer has ended. `clienthello::scan` gives the reassembler's verdict without
  its copy (test `clienthello.scan`: the same verdict, need, lengths and record count as
  `reassemble` on every prefix of six inputs). Until then a pending TLS connection holds its bytes
  in the handler's buffer (section 2.1's replay bound) and no OpenSSL state. OpenSSL then reads the
  bytes it would have read piecemeal, with the frozen settings, so its replies and alerts are the
  same; the counter `tls_states` counts the states made (`handlers.tls_deferred`, each arm: half a
  ClientHello then a reset makes none; two writes make one with the second; half then the peer's
  end makes one; a ClientHello too long to be one gets OpenSSL's alert).
- The relay (one-port relay dispatch only; dedicated mode has no relay, so no cost contrast is
  touched):
  - pass-through in replay parks a ClientHello still incomplete after a read in storage of its own,
    sized to the record bytes the reassembly needs next (5 plus the length its record header
    announces), with one counted copy of the bytes held, and gives the 4,096-byte receive buffer
    back; a ClientHello whole in its first read is routed from the receive buffer as before, with no
    copy (the relay test's `bytes_copied == 0` over whole ClientHellos still holds). Tests:
    `relay.pass_through` and `relay.pass_through_tdec` check that no receive buffer is held while
    the ClientHello is incomplete and that the storage never outgrows the records it needs;
  - per relayed connection: TCP_NODELAY is set once on the relaying listener and inherited by every
    accepted socket (pinned on L: `server.kernel_nodelay_inherited`), the backend's set before its
    connect, so one `setsockopt` instead of two; a connect that epoll reports with EPOLLOUT and no
    error is not asked for SO_ERROR; a side is read when the copy starts only if it may hold bytes
    (a read that filled its room, a peek, a seen end, a client event while the connect was
    pending, or a backend connect reported with EPOLLIN); a short read after a reported half-close
    ends its source without a second read; the direction that ends last is closed by `close()`,
    whose FIN passes its end on, with no `shutdown()` first (M2b's reading 1 still holds: each
    end is passed on, and the connection closes when both have ended).
- The carried items (below): `--record` and `opcase case`.

**Round 2** (e69e860, c8e588a, 666a6b7, 333d846, 0aa639e, ac84f2d; measured as ac84f2d: m5b3c,
m5m3c, m5tr3):
- io_uring's receives are `IORING_OP_READ` on the socket, not `IORING_OP_RECV` (both arms: every
  io_uring receive, the handlers' in dedicated mode too). At v7.2.6 every RECV allocates its
  `io_async_msghdr` at preparation (io_uring/net.c, `io_recvmsg_prep_setup`), which L serves from
  kmalloc-512; an armed READ allocates an `io_async_rw` (io_uring/rw.c, `io_rw_alloc_async`). In
  every io_uring window with an armed receive in m5b3a, m5b3a2 and m5b3b, kmalloc-512 grew by 236
  to 532 bytes per pending connection, and in no epoll window was it among the six caches that grew
  most. The receive is the same: `sock_read_iter` calls `sock_recvmsg` with
  MSG_DONTWAIT at offset 0, which a socket, a stream file, always has (net/socket.c); the same
  provided buffers; 0 at EOF. A READ that took a buffer and returned 0 names it, and the buffer goes
  back to the pool (the pin `server.kernel_uring_recv_select` now pins READ and allows that).
  Section 1(b)'s form for io_uring replay, a receive posted with a buffer and its non-waiting reap,
  is unchanged. The sources (io_uring/net.c, net.h, rw.c, rw.h, net/socket.c) were read at the
  v7.2.6 tag of the stable tree.
- The receive counters split by result (`recv_eof`: the peer's end; `recv_again`: no byte without an
  end or an error, EAGAIN or the ring's ENOBUFS), so the receives that returned bytes, which do not
  depend on when a FIN or the next bytes arrive, compare exactly between arms (`recv_data` in
  counterdelta.py). Counter increments only, in the shared read paths, so both arms alike. IOCP's
  receives are not split (iocp.cpp was not touched: M6b works there).
- The relay's user-space copy takes a short read as the source drained (333d846), as the handlers'
  reads do; found by round 1's counters (m5tr2: the relay in peek mode read the client again into
  EAGAIN, 5.0 receives per connection against replay's 3.2). Its first form left a FIN that had
  arrived before the short read unseen (no later edge reports it), and `case.HC13` and `case.HC19`
  in relay peek on epoll waited past their limit in every build (m5chk3); 0aa639e remembers a side's
  reported half-close from any event (the route stage's included) or an end already read, so the
  short read after it ends the source. One-port relay dispatch only.
- Tests fixed: `handlers.tls_deferred`'s last input in round 1 had byte 5 changed, so the
  detector rejected it in one-port mode before any handler (c8e588a: the handshake length's top
  byte instead); two suites run at once met in the runner's tests (ac84f2d: `test_competitors`'
  integration ports move with the build tree; the clock floor's and THP's signal tests wait for
  the wrapper's job to start, since a TERM between a wrapper's record and its fork of the job is
  honoured only when the job ends, which the loaded host made happen).

### Criterion 1: the counters, one-port against dedicated

Section 10's untimed counter checks (`systrace.py --kind cost`): each cost cell's two arms, in-process
dispatch, in both detection modes (dedicated mode ignores the mode, so its rows are A/A repeats),
three times each, interleaved; churn at 2,000 exchanges per second for 2 s after 0.5 s and
keep-alive with two connections for 0.5 s (counts only; never a window). `counterdelta.py` takes each
row's counters less its idle pass's, per connection (keep-alive: per request), and compares the arms:
"equal" (every row the same), "within the spread" (the arms' ranges over the repeats overlap) or
"differs". Jobs m5tr1 (6bb6484), m5tr2 (deaabfe), m5tr3 (ac84f2d, the final code, below). Every
counter that names a system call agreed with `perf stat`'s count of its entry tracepoint in all
120 cost rows of m5tr3 (`perf trace -s`, the cross-check, in 53, short by at most 1.1% of a call's
count).

At ac84f2d, per connection, one-port less dedicated, for HTTP/1.1, h2c, TLS and MQTT churn on epoll
and io_uring and HTTP/1.1 keep-alive on both (per request):
- **Replay: no extra system call and no extra copy.** Equal in every cell: sends, `setsockopt` (0),
  `epoll_ctl` (1), connects, shutdowns and splices (0), peeks and checks (0), io_uring's READ
  submissions, the receives that returned bytes (`recv_data`), and `bytes_copied` (0 in every row
  of both arms). What differs, differs within the dedicated arm's own spread over its three
  repeats, and depends on when bytes or a FIN arrive, not on the mode: the accept that ends a
  batch with EAGAIN (2.0 per connection in both arms, within 0.0004), the loop's waits
  (`epoll_wait`, `io_uring_enter`, at most 0.0011 apart), and the receives that found the peer's end
  (`recv_eof`: MQTT on epoll +0.0118, h2c on epoll +0.0079, the arms' ranges overlapping; the
  dedicated arm's own ranges are 0.9486 to 0.9842 and 0.956 to 0.9868). Before the split of e69e860 the same effect showed as
  `recv_calls`: at 6bb6484 MQTT on epoll was 2.8774 to 2.981 receives per connection in dedicated
  mode and 2.9846 to 2.985 in one-port mode (m5tr1), whether the client's FIN came with its
  DISCONNECT or after it, and at deaabfe (m5tr2) the arms overlapped.
- **Peek: exactly the operations the design adds.** On epoll, one `recv(MSG_PEEK)` per connection
  (24 bytes peeked for HTTP/1.1, h2c and TLS, 14 for MQTT; keep-alive 0.0001 per request, one per
  connection), and nothing else structural. On io_uring, one `IORING_OP_POLL_ADD`, one peek, and
  one more `io_uring_enter` per connection (2.0 to 3.0 for HTTP/1.1, 3.0 to 4.0 for the others):
  the poll's completion comes back through the ring before the handler's receive can be posted,
  so at this load, where every step is its own wait, the poll costs a round of the ring. The
  receives, sends and copies are the replay counts. One timing difference lies just outside the
  spread: MQTT on epoll in peek, `recv_eof` +0.0035 (0.9772 to 0.9812 against 0.9826 to 0.9836),
  receives that found the end only, with `recv_data` equal.
- **The relay** (relay dispatch, which dedicated mode does not have; `systrace.py --kind proxy`, one
  row per mode, backend and protocol, per relayed connection; `bytes_copied` 0 in every row):

| Relay row (ac84f2d, m5tr3) | System calls per connection | Peek less replay |
|---|---|---|
| HTTP/1.1, epoll, replay | 20.6: accept4 2, epoll_ctl 2, recvfrom 3.22 (2.0 returned bytes), sendto 2, setsockopt 1, socket 1, connect 1, shutdown 1, close 2, epoll_pwait2 5.4 | |
| HTTP/1.1, epoll, peek | 22.4 | +1 peek; `recv_data` equal; `recv_eof` +0.27 and waits +0.55 (when the FIN came) |
| TLS by SNI, epoll, replay | 21.1 | |
| TLS by SNI, epoll, peek | 23.0 | +2 peeks (detection's 24 bytes, then the route's whole ClientHello); `recv_data` equal; `recv_eof` -0.12 |
| HTTP/1.1, io_uring, replay | 13.0: io_uring_enter 6, sendto 2, setsockopt 1, socket 1, shutdown 1, close 2 (accept, connect and receives are ring operations) | |
| HTTP/1.1 and TLS, io_uring, peek | 15.0 and 16.0 | +1 POLL_ADD, +1 io_uring_enter, +1 peek (TLS +2) |

  Round 1's relay changes took the epoll relay from 25.0 system calls per connection (m5tr1) to
  20.6 (m5tr2), and round 2's drained-source rule took peek's from 24.0 (m5tr2: it read the client
  again into EAGAIN, and its EOF reads followed) to 22.4. nginx makes 22.1 to 22.4 and HAProxy 44.0
  to 44.2 per connection at the same rate (m5tr3).
- **Criterion 1: met**, with the two kinds of timing difference named above (the loop's waits and the
  reads of a FIN, which fall within the dedicated arm's spread except MQTT's +0.0035 per
  connection in peek) and, on io_uring in peek, the poll's extra `io_uring_enter`, which the brief
  asked to report rather than fold into "the poll the design adds": it is the poll's round trip
  through the ring.
- `systrace.py`'s check of the relay on io_uring compared the `connect` counter with `connect(2)`,
  which the relay on io_uring never calls (its connect is `IORING_OP_CONNECT`): the four io_uring
  relay rows of m5tr3 disagreed on that check alone (681c58e makes the check epoll's only).

### Criterion 2: B3 in relay against each proxy

W at sample 2 in bytes per pending connection, replay (the proposed default), development windows
(WL7's layout, all valid by section 7). Q is the proxy's W over the relay's. Before and after round
1 the proxies' W is m5b3a's (the same day, earlier in the day) and the relay's comes from other
jobs (m5b3a2 or m5b3a before, m5b3b after); after round 2 (m5b3c) each proxy ran twice around the
relay on both backends (proxy, relay on epoll, relay on io_uring, proxy), and Q uses the mean of
its two windows. Within m5b3c every system's Ks fell steadily through the job, from 7,173 to 6,451
(TCP's and the inode caches' growth per connection falling as their slabs fill), so a Q across jobs
carries a few hundred bytes of the host's drift; the interleaved Q of m5b3c does not.

| Case | Proxy | Proxy W (m5b3a / m5b3c) | Q, epoll: before / round 1 / round 2 | Q, io_uring: before / round 1 / round 2 |
|---|---|---|---|---|
| silent | nginx | 11,941.9 / 11,957.5 | 1.586 / 1.530 / 1.597 | 1.475 / 1.458 / 1.545 |
| silent | HAProxy | 10,092.1 / 9,940.2 | 1.340 / 1.293 / 1.372 | 1.247 / 1.232 / 1.320 |
| silent | Envoy | 17,063.5 / 16,747.3 | 2.266 / 2.186 / 2.368 | 2.108 / 2.084 / 2.296 |
| silent | caddy-l4 | 17,895.8 / 17,707.2 | 2.377 / 2.293 / 2.479 | 2.211 / 2.185 / 2.392 |
| silent | sslh-ev | 7,220.0 / 6,960.1 | 0.959 / 0.925 / 1.000 | 0.892 / 0.882 / 0.964 |
| partial | nginx | 13,424.8 / 13,286.8 | 1.146 / 1.660 / 1.718 | 1.068 / 1.591 / 1.661 |
| partial | HAProxy | 14,273.7 / 14,068.1 | 1.218 / 1.765 / 1.859 | 1.135 / 1.692 / 1.800 |
| partial | Envoy | 18,460.0 / 18,201.8 | 1.576 / 2.283 / 2.458 | 1.468 / 2.188 / 2.352 |
| partial | caddy-l4 | 20,672.1 / 20,440.3 | 1.764 / 2.556 / 2.739 | 1.644 / 2.450 / 2.664 |
| partial | sslh-ev | 7,324.1 / 7,064.8 | 0.625 / 0.906 / 0.957 | 0.583 / 0.868 / 0.927 |

The server's relay itself (W; U; Ks):

| Case, backend | Before (6bb6484) | Round 1 (deaabfe, m5b3b) | Round 2 (ac84f2d, m5b3c: the five windows' range) |
|---|---|---|---|
| silent, epoll | 7,529.7; 407.1; 7,122.5 | 7,804.5; 407.1; 7,397.4 | 6,962.8 to 7,486.7; 407.1; 6,555.6 to 7,079.5 |
| silent, io_uring | 8,095.3; 407.1; 7,688.2 | 8,189.5; 407.1; 7,782.4 | 7,218.8 to 7,738.2; 407.1; 6,811.6 to 7,331.0 |
| partial, epoll | 11,715.8; 4,670.7; 7,045.1 | 8,086.3; 791.3; 7,295.0 | 7,381.0 to 7,732.8; 791.3; 6,589.6 to 6,941.5 |
| partial, io_uring | 12,571.9; 4,671.9; 7,900.0 | 8,436.9; 791.3; 7,645.6 | 7,616.8 to 8,000.7; 791.3; 6,826.8 to 7,209.4 |

- Round 1's parked ClientHello cut the relay's U with a partial ClientHello from 4,670.7 to 791.3
  bytes per pending connection on both backends (the 4,096-byte receive buffer gone; the
  connection's state, the relay's, and storage of 5 + l bytes remain).
- Round 2's `IORING_OP_READ` removed the kmalloc-512 growth that every io_uring window with an armed
  receive showed before it (236 to 532 bytes per pending connection in m5b3a, m5b3a2 and m5b3b, one
  `io_async_msghdr` each); in m5b3c io_uring's Ks exceeded epoll's in the adjacent window by 211
  to 335 bytes (io_kiocb about 195, and an `io_async_rw` from kmalloc-256 about 170 where it
  shows); within m5b3a2 and m5b3b, before it, the gap was 351 to 566 bytes.
- Peek, the other option, after round 1 (m5b3b): relay silent 7,560.4 (epoll) and 7,527.6
  (io_uring); partial 8,725.1 and 8,804.9 (Kq 1,068.0: the bytes stay in the socket; U 567.3).
- **Criterion 2: met against nginx, HAProxy, Envoy and caddy-l4, in both cases on both backends**
  (the smallest Q is HAProxy's silent case on io_uring, 1.320); **not met against sslh-ev** (Q 0.927
  to 1.000), as the note under the exit criteria derived before any engineering: sslh-ev's W is
  its sockets' Ks and 400 to 524 bytes of U, and the server's Ks alone is as large.

### Item 3: the in-process footprint with a partial ClientHello

| System | Case | W | U | Job |
|---|---|---|---|---|
| server, epoll | partial, before | 56,524.0 | 49,746.3 | m5b3a (6bb6484) |
| server, io_uring | partial, before | 57,162.5 | 49,742.2 | m5b3a |
| server, epoll | partial, round 1 | 11,458.2 | 4,521.2 | m5b3b (deaabfe) |
| server, io_uring | partial, round 1 | 11,778.0 | 4,522.8 | m5b3b |
| server, epoll | partial, round 2 | 11,057.6 | 4,521.2 | m5b3c (ac84f2d) |
| server, io_uring | partial, round 2 | 11,266.0 | 4,522.8 | m5b3c |
| server, epoll and io_uring | partial, peek, round 1 | 11,345.9; 11,681.4 | 4,521.2; 4,522.8 | m5b3b |
| Netty | partial | 8,837.9 | 2,340.5 | m5b3c |
| Jetty | partial | 38,744.9 | 32,165.1 | m5b3c |
| cmux | partial | 18,981.3 | 12,530.5 | m5b3c |
| server, epoll and io_uring | silent, round 2 | 6,941.9; 7,172.9 | 402.2; 402.2 | m5b3c |

The deferred OpenSSL state took 45,225 bytes of U per pending connection away (49,746.3 to
4,521.2): a pending TLS connection now holds its state (368 bytes) and the handler's 4,096-byte
buffer with the 108 bytes received. Netty, which buffers the ClientHello in a growing buffer and
makes no engine until it is complete, holds 2,340.5; the server is below Jetty and cmux and above
Netty in this case (Q of Netty over the server 0.80 on epoll, 0.78 on io_uring). Going below Netty
would mean holding the incomplete ClientHello in storage smaller than the handler's buffer, a copy
in the handler, which dedicated mode runs too; not done (section 2.1 names the handler's buffer as
replay's bound, and the cells are descriptive). Peek does not change it: in-process, the handler
reads the bytes into its buffer at classification in either mode.

### Criterion 3: M3 against nginx and HAProxy

The server's one-port relay on epoll (replay, the user-space copy) against each proxy in its M3
configuration, sessions X Y Y X in hand-off placement, every window valid by section 7 (48 of 48 in
each job). Session ratio, server / proxy:

| Cell | Before (6bb6484, m5m3a, seed 851) | Round 1 (deaabfe, m5m3b, seed 853) | Round 2 (ac84f2d, m5m3c, seed 857) |
|---|---|---|---|
| HTTP/1.1, nginx | 1.0210, 1.0237, 1.0174 | 1.0738, 1.0744, 1.0745 | 1.0764, 1.0773, 1.0812 |
| HTTP/1.1, HAProxy | 1.0511, 1.0562, 1.0522 | 1.1206, 1.1080, 1.1119 | 1.1086, 1.1226, 1.1102 |
| TLS by SNI, nginx | 1.0243, 1.0239, 1.0265 | 1.0763, 1.0860, 1.0810 | 1.0932, 1.0793, 1.1142 |
| TLS by SNI, HAProxy | 1.0355, 1.0327, 1.0364 | 1.0964, 1.0956, 1.0943 | 1.0906, 1.0999, 1.1006 |

- Every front was the bottleneck (CPU 14 saturated). The relay's CPU per connection (front) fell
  from 48.0 to 48.9 us (m5m3a) to 44.2 to 45.0 us (m5m3c); nginx's stayed 48.7 to 50.1 us (one
  m5m3c window of nginx, TLS, 53.2 us, which makes that session's 1.1142), HAProxy's 54.1 to 56.0
  us. WL6 (front and stub) per connection: the relay 69.9 to 70.7 us before, 66.1 to 67.0 us after.
- Where it came from. `perf record` of the relay under M3's load (m5perf2, a profiling build):
  about 91% of its samples in the kernel, 3.3 to 3.6% in nf_tables (the loopback NOTRACK rules and
  Docker's), and under 3% in oneport and libc together (oneport 1.6%); nginx's profile (m5perf1)
  is about 88.6% kernel. So the user-space code was never the cost; the system calls were. At
  section 10's untimed rate (2,000 per second, so every step is its own wait) the relay made 25.0
  system calls per connection before (m5tr1: accept4 2, recvfrom 5, epoll_pwait2 5, sendto 2,
  setsockopt 2, shutdown 2, close 2, epoll_ctl 2, connect, socket, getsockopt) against nginx's 22.4
  (its epoll_wait 4.4, recvfrom 4, writev 2, ioctl and getsockopt 1 each) and HAProxy's 44.1 (16
  of them clock_gettime); after round 1, 20.6 (HTTP/1.1; m5tr2: recvfrom 3.2, setsockopt 1,
  shutdown 1, no getsockopt) and after round 2, 20.6 and 21.1 (HTTP/1.1 and TLS, replay; m5tr3).
- **Criterion 3: met.** Every session of round 1 and round 2 is at least 1.05 against both proxies
  in both protocols (the smallest, 1.0738, HTTP/1.1 against nginx in round 1; 1.0764 in round 2).
  The margin over nginx is about 7.4 to 11%, over HAProxy about 9 to 12%, in development sessions;
  section 4.4's test at R_M = 16 decides.

### Criterion 4: the suite under the four builds

Each check is a lab job (`checks_job.sh`: a fresh clone of the lab remote at the commit, then
`~/lab/p3/sancheck.sh` with Debug and ASan+UBSan at once, then TSan and MSan at once; clang 22.1.8,
`ctest -V -j 8`; report lines counted with the lab's shared pattern). Development checks, not
records.

| Job | Commit | Debug | ASan+UBSan | TSan | MSan | Warnings, report lines |
|---|---|---|---|---|---|---|
| m5chk1 | deaabfe (round 1) | 381 of 383 | 381 of 383 | 381 of 383 | 381 of 383 | 1 (a range-loop copy in a test), 0 |
| m5chk2 | 666a6b7 | 383 of 383 | 383 of 383 | 383 of 383 | 381 of 383 | 0, 0 |
| m5chk3 | 333d846 | 380 of 383 | 381 of 383 | 381 of 383 | 380 of 383 | 0, 0 |
| m5chk4 | ac84f2d (round 2, measured) | 383 of 383 | 383 of 383 | 383 of 383 | 383 of 383 | 0, 0 |
| m5chk5 | 681c58e (systrace.py's connect check) | 383 of 383 | 383 of 383 | 383 of 383 | 383 of 383 | 0, 0 |

- m5chk1: `handlers.tls_deferred` failed on both backends in every build: its last input changed
  byte 5, so one-port mode's detector rejected it before any handler (a test error; c8e588a). The
  code measured as round 1 is unchanged by the fix.
- m5chk2 (MSan) and m5chk3 (Debug, MSan): `run.test_runner` (the THP signal test: the wrapper's TERM
  landed before its fork of the job) and `run.test_competitors` (the integration probe's stub did
  not start: the other build of the pair held its fixed port), failures of two suites run at once
  (ac84f2d).
- m5chk3: `case.HC13.epoll.relay.peek` and `case.HC19.epoll.relay.peek` in every build: 333d846's
  short read left a FIN unseen (0aa639e). That commit was never measured: chain c4, which would
  have measured it, was stopped by SIGTERM before its first window.
- 383 tests: M4b-2's 375 and `clienthello.scan`, `handlers.tls_deferred` (two backends),
  `server.kernel_nodelay_inherited`, `server.binary_record` (two backends), `server.cases_by_port`
  (two backends).
- Log sha256 (L, `~/lab/p3/m5/check/681c58e/`): debug-681c58e.build.log
  42bedaf9f94915266715cd2753fd31806055e9462df0006b4e61dd7ffb5438cc, debug-681c58e.ctest.log
  926b25de097389b177b33032aa00048b00eb4484aca437a5a7da02c0a5174b3a, asan-681c58e.build.log
  27612d2d187d08f669bf4c7eacd8bd70651516d78941b72560c95ce3b05030d6, asan-681c58e.ctest.log
  749b54943879994ec0bd210c9443f3167300db685251bbef1500f963c3ff552a, tsan-681c58e.build.log
  94e5916e8ab8426ca56e9b0e594a5c2832ceb65b6562b3c0cd9d320f2e7f16dd, tsan-681c58e.ctest.log
  8f794042bc5266eb94826e99c9d1b23441ed0a725ddf2e91dd713fdcde30009e, msan-681c58e.build.log
  6729b9fb2623376b99e683fc00d1494bae94f3d6363f1b48505e9c72775abdd6, msan-681c58e.ctest.log
  9ca9314f1967a1b876f5e0fe75553acac6ed3c1af263d8d2d2ebb00b8cd10bec.
- Log sha256 (L, `~/lab/p3/m5/check/ac84f2d/`): debug-ac84f2d.build.log
  ed9e56e0ae80548ad4fd553a0a57289a6bc008a053a94bc157fc8bd0bae99c92, debug-ac84f2d.ctest.log
  da86841400dfa90988661954bbbee8212af5aa872bca281749e06faa40b359fb, asan-ac84f2d.build.log
  b62e7126cec10ee248ed32ac3d41249fe896449ee33a19a77c5435fe955f9a7e, asan-ac84f2d.ctest.log
  61d3819ea097fc9fe4e7fb7bd0afcb1831cbb3f0a74966d0d87a6c090ff42c07, tsan-ac84f2d.build.log
  3a2e148719889e1c5d6a7809550109299ef65acfbef0bb750617cd48ecb55d2c, tsan-ac84f2d.ctest.log
  6b032200ff64008b58ffdc735187c164f31ba100dccfc3da2166236111c77c52, msan-ac84f2d.build.log
  52c825d369f7ce7cd4837348a4d418ef97e87b5f5aed303d347a987fd09649c3, msan-ac84f2d.ctest.log
  06d1d65ead56d2a906e37300c888a6b782239033946339ff99809a1cea5d95b8.
- W: not built or run in M5. `handlers.cpp` (the TLS deferral and the receive counters) and
  `bench/cases` (opcase case's library code) compile on W too; M6b's merge of `m6b-windows` with
  main must build them and run W's suite.
- **Criterion 4: met at the end, not after every change.** ac84f2d, the code of round 2's
  measurements, and 681c58e, the last commit, are green in all four builds (383 of 383, 0
  warnings, 0 report lines). Three
  intermediate commits were not: deaabfe (round 1's measured code) failed a test whose input was
  wrong, not the product; 666a6b7 failed a runner test of two suites at once; 333d846 broke the
  relay in peek mode and was never measured. The suite ran on four commits; 2127a8a, 23eae82,
  e69e860, c8e588a and 0aa639e were checked only as parts of the commits after them. Every
  engineering timing is journaled as development (below).

### Both detection modes stay engineered

Both modes remain flag values of the one binary, and no default is written into the code or decided
by M5: the runners take `--detect`, with replay as the proposed default of section 2.1 until rule E
picks per backend on the frozen binary after the pilot entry. Peek was measured only option against
option, as development data that decides nothing: in B3 (m5b3a2, m5b3b: the relay silent 7,560.4 on
epoll and 7,527.6 on io_uring, partial 8,725.1 and 8,804.9, where replay held 7,804.5, 8,189.5,
8,086.3 and 8,436.9; in-process partial 11,345.9 and 11,681.4) and in the untimed counters (above).
It was not timed in M3, and nothing of peek against replay was timed under load. Every change of M5
was made in both modes' paths where they share code, and the relay's changes were checked in both
(the counters, and `case.*.relay.peek` in every build).

### Carried items

- **WL8's per-connection record** (deaabfe). `oneport --record PATH` writes one JSON line per event
  of the server's test hooks: each connection's end of detection (outcome, class, deciding byte,
  the passes of accept, end, last read and half-close, accept, timer start and end times, bytes
  seen and held, wakeups, SO_RCVLOWAT sets and resets, the PROXY source, the timed event with its
  deadline, wait return and pass), each relayed connection's route, and each close, every time in
  nanoseconds of the server's steady clock, which on L is CLOCK_MONOTONIC, the clock of `opcase`'s
  write times. A hard-case run against the server in its own process matches them to `opcase`'s
  transcripts by the client's local port. Without `--record` no hook is set and nothing changes;
  it is never set in a measured window. `describe()` prints `record`. Test `server.binary_record`
  (both backends): the binary with `--record`, one HTTP/1.1 exchange, SIGTERM; the record holds the
  connection's detection line (classified, HTTP/1.1) keyed by the client's port, its accept no
  earlier than the client's connect began and its decision no earlier than its write, and its close
  line.
- **`opcase case`** (deaabfe, `bench/cases/run_cases.cpp`): the hard cases of Appendix A against
  any system by port. `--hc K` runs case K's variants in their fixed order (`--variant` selects by
  id prefix), `--replicates R` times each, a variant whose setup needs the PROXY header against
  `--proxy-port`, every other against `--port`; the timers default to section 1's 3 s, GAP_SPLIT
  and G to the suite's stand-ins until the pilot entry sets them (`--gap-split-ms`, `--g-ms`), and
  every wait to `T_OBS` = 60 s (`--wait-ms`). One JSON line per run: the variant, its frozen
  expectation (setup, outcome, class, when, reply, deciding byte) and the transcript (local port,
  connect times, each write's time, bytes sent, the reply's bytes, first byte and end, EOF or reset,
  the TLS result), every time on CLOCK_MONOTONIC. It judges nothing; section 10's runner, which
  starts each system in the setup a variant names and judges the outcome, comes after the pilot
  entry. Test `server.cases_by_port`: HC1's HTTP/1.1 variant against the server, its line.
- **sslh-ev's M3 cells**, as the frozen rules decide them: no M5 work and no M5 window. Every
  sslh-ev window of M3 fails section 7's 0.1% error rule as configured (sslh 2.3.1's defect with
  libev's reused descriptors; revision log, "sslh-ev's stalled exchanges"), so both cells will
  have fewer than R_M valid sessions, enter Holm with p = 1 (section 4.1) and be "not shown"
  (section 12), and the narrowing order puts M3 first. sslh-ev's B3 cells are the subject of the
  note under the exit criteria.

### The exit criteria, after round 2

| Criterion | State | Figures (development data) |
|---|---|---|
| 1. Counter deltas | met | replay: 0 extra system calls and 0 extra copies per connection in every cell; peek: +1 MSG_PEEK on epoll, +1 POLL_ADD, +1 MSG_PEEK and +1 `io_uring_enter` on io_uring; timing-dependent counts inside the dedicated arm's spread but one (MQTT, epoll, peek: EOF reads +0.0035) |
| 2. B3 relay at 1.25 | met against nginx, HAProxy, Envoy, caddy-l4 (both cases, both backends; least 1.320); not met against sslh-ev (0.927 to 1.000) | the server's W cannot fall below its Ks, which sslh-ev's W barely exceeds (the note under the criteria) |
| 3. M3 at 1.05 against nginx and HAProxy | met | every session of round 2: nginx 1.0764 to 1.1142, HAProxy 1.0906 to 1.1226 |
| 4. Four sanitizers after every change | met at the end, not after every change | ac84f2d (m5chk4) and 681c58e (m5chk5) green in all four builds; deaabfe, 666a6b7 and 333d846 were not |
| 5. Two rounds | used both | round 1 (deaabfe), round 2 (ac84f2d) |

M5 stops here with one gap, recorded: criterion 2 against sslh-ev, out of reach by construction.
The frozen order decides what follows from the confirmatory runs, not from these data: if sslh-ev's
four B3 cells fail section 4.4's test, B3 narrows (section 12) to the competitors and cases the
server beats; M3 comes first in that order, and these development data give it no sign of needing
to narrow against nginx and HAProxy.

### Readings, and changes against the proposal's text (for the coordinator)

None of these changes a frozen rule; each is listed so the code freeze can log what it needs.
1. Criterion 1 for relay dispatch. Dedicated mode has no relay (only a detecting listener relays,
   `enter_handler`), so the relay has no one-port against dedicated delta. Its rows are given per
   relayed connection in each detection mode, and peek against replay is the check of "exactly the
   MSG_PEEK (or poll) operations the design adds".
2. The revision log's M3 entry, item 2, lists "the two `TCP_NODELAY` of a relayed connection" among
   the `setsockopt` calls counted. Its rule (every `setsockopt` on a connection's socket is counted;
   a listener's options, set once at start, are not) stands; since 23eae82 a relayed connection
   makes one, its backend's, and the relaying listener's is set once at start and inherited. The
   example list is now out of date; the code freeze's entry can say so.
3. Proposal I11 and I15 name `IORING_OP_RECV` for io_uring's receives; since 666a6b7 they are
   `IORING_OP_READ` on the socket (why, above). The frozen text names no opcode: section 2.1 counts
   "submissions by opcode", and section 1(b) and section 11 speak of a receive posted with a
   provided buffer, which READ is. For the coordinator to accept, or to send back.
4. Section 2.1's memory bounds hold as frozen: in-process with replay the handler's buffer from the
   first byte (the TLS handler's state now comes later, the buffer does not change); in
   pass-through the partial ClientHello, at most B_CH, now in storage sized to the records it needs
   next (at most the message and 5 bytes per record, M2b's reading 3).
5. M2b's reading 1 (the relay passes each side's end on as a half-close and closes when both have
   ended) holds: the end that comes last is passed on by `close()`'s FIN rather than by a
   `shutdown()` before it; the bytes either peer sees do not change.

### Design choices of M5

| Name | Value | Where | Reason |
|---|---|---|---|
| Counter repeats | 3 per cell and mode, interleaved | `trace_job2.sh` (`systrace.py --repeat`) | the dedicated arm's own spread beside one-port's distance from it |
| Integration test ports | shifted by 400 times (CRC-32 of the build tree mod 16) | `test_competitors.port_shift` | two suites at once do not bind each other's ports |
| Profile | perf record -g at 4999 Hz for 4 s after 1.5 s of load | `perfrec.py` | about 20,000 samples of the front's one core |
| Profile port | 24200, the stub 10 above | `perfrec.PORT` | off the ephemeral range, apart from the other runners' ports |
| B3 development order | per proxy and case: the proxy, the relay on epoll, on io_uring, the proxy | `c5.sh` (m5b3c) | the host's drift within a job falls on both arms |
| Parked ClientHello storage | the record bytes the reassembly needs next | `Worker::hello_room` | the records a pending connection has, no more |

### How the jobs ran, and what went wrong

- Every job ran under `lab_job.sh` (the lab lock, the clock floor, THP at `madvise`, NOTRACK), from
  `~/lab/p3/m5/src`, a clone of the lab remote, in chains of jobs (`c1.sh` to `c5.sh`, kept in
  `~/lab/p3/m5/`). Each chain's results came back over one ssh session opened before its B3
  windows, so no new TCP connection reached L while a B3 window measured (section 7's TIME-WAIT
  rule counts the host); two ssh calls during m5b3c's build came before its first baseline, which
  waits until the host holds no TIME-WAIT socket.
- Chain c1 was launched with its arguments typed into L's login shell, zsh, whose history modifiers
  (`$R:s...`, `$R:h...`) ate every argument written as `$R:...`: m5b3a and m5perf1 ran their proxy
  windows and profiles but lost most of the server's; m5b3a2 and m5perf2 ran them again. Every later
  chain is a bash script.
- Chain c3 (666a6b7) was stopped after its checks, before any window, to add 333d846; chain c4
  (333d846) was stopped by SIGTERM to its process group during its B3 job's start, before any
  window, when its checks failed. Every setting came back (the records' `restored` true). Chain c5
  (ac84f2d) ran to its end.

### Lab journal and raw data

Ten lines in the Papers repo's `lab/journal.jsonl` (Papers 0c4d67d and 6b82bb0, local, not pushed),
each marked development: m5b3a, m5perf1, m5b3a2, m5perf2, m5m3a (before, 6bb6484), m5b3b, m5perf3,
m5m3b (round 1, deaabfe), m5b3c and m5m3c (round 2, ac84f2d). No line for the untimed counter checks
(m5tr1 to m5tr3: counts, never a time or a rate), the checks (m5chk1 to m5chk4), or the stopped
chains (no window ran). Everything stays on L under `~/lab/p3/m5/`, archived in
`~/lab/runs-archive/p3-m5-20261003T194756.tar.gz` (sha256
0ca57c74b29e2d8d5998a0531e89a2426a63b0ea560fc17187cb8f1b1aa0a182, beside it in a `.sha256` file;
5,993 members; made under the lab lock, job m5arch); build trees, source clones and the check
builds are left out.

## M7 preparation, 2026-10-03

The preparation of the code freeze, not the freeze: M4b-1's reading 4 fixed in the configurations
instead of logged; M5's readings in the revision log; the records drivers, written and tried in a
dry run that makes no citable record; and the checklist of the freeze (next section). Nothing here
is a result. No window ran: `cases_check.py`, the reassembler check and the drivers' dry run are
functional and untimed, so no lab-journal line was written. `m6b-windows` and W were not touched.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| f7d62a2 | feat: the route for a ClientHello without ALPN in the five proxies' cases configurations; cases_check.py checks it |
| 785b66b | feat: the code freeze's records drivers, prepared and not run for records |
| b701194 | fix: build_inputs.py finds L's inputs_hash.py in ~/lab/p3/tools and records the tool's sha256 |
| e68087f | fix: the integration tests' port shift is a multiple of 600 (two suites at once collided at 400) |
| 3627355 | fix: test_competitors.py's Linux-only decorator moves to class Integration (e68087f broke the file) |
| 9afccbc | fix: sanitize_oneport.ps1 names cl as the C++ compiler |
| c644ffd | docs: hypotheses.md revision log, M5's readings 1 and 5; reading 4 reported |
| 6795407 | fix: the integration tests bind their ports below 10000, apart from the in-process servers' random ports |
| 8e01e1d | fix: the integration tests fail on a sanitizer report in their started processes' files |
| 49e4bb3 | docs: test_competitors.py's comment on the port move (dryrun3's cause is likely, not proven) |

Then this section (the commit after these). Papers 53b929a (local, not
pushed): `lab/bin/test_report_pattern.sh`'s list of record writers held a literal `\n` where a
line continuation was meant, so the loop also took a token `n` and printed "skip: n" (the one-port
writer after it was still checked); fixed. A copy of the fixed script on L, with sanitize.sh,
sanitize.ps1 and oneport_record.py beside it as in the Papers tree, prints PASS and no "skip: n".

### M4b-1's reading 4: the route for a ClientHello without ALPN, added

The server's pass-through route table (`bench/server/relay.cpp`, `routable`) sends a ClientHello
for oneport.test with no ALPN, or with an ALPN list that offers http/1.1 or h2, to the backend's
TLS port. The proxies' cases configurations held only the ALPN part. Appendix B asks for "every
route its features cover", so the route without ALPN is now in each (f7d62a2):

| System | How | Exact? |
|---|---|---|
| nginx | map key `"oneport.test "`: `$ssl_preread_alpn_protocols` is empty without the extension | yes |
| HAProxy | `use_backend tls_backend if { req.ssl_sni -m str oneport.test } !tls_has_alpn`, with `acl tls_has_alpn req.ssl_alpn -m found`: the fetch returns no sample without the extension (src/payload.c, `smp_fetch_ssl_hello_alpn`, v3.4.6) | yes |
| Envoy | a second chain, `server_names` and `transport_protocol: tls`, no `application_protocols`: FilterChainMatch has no form for "none", so the chain without the field takes any list the ALPN chain does not | no: also takes ALPN lists that offer neither h2 nor http/1.1 |
| caddy-l4 | a route `tls { sni oneport.test }` after the ALPN route, on both listeners: the alpn matcher matches only a protocol the client offers (modules/l4tls/alpn_matcher.go, v0.1.2) | no: as Envoy |
| sslh-ev | a second `tls` entry with `sni_hostnames` alone: with both lists set, a ClientHello without the extension does not match (tls.c lines 207 to 209, v2.3.1) | no: as Envoy |

- The brief named four proxies. By their features and sources all five can carry the route, two
  of them exactly, so all five carry it; this is for the coordinator, and leaving one out is a
  small revert of that system's file and of `cases_check.NOALPN_SYSTEMS`.
- What else changes, in Envoy, caddy-l4 and sslh-ev only: a ClientHello for oneport.test whose
  ALPN offers neither h2 nor http/1.1 now reaches the backend's TLS port, where the server refuses
  it with no_application_protocol (M2a's reading 6), instead of the path a ClientHello without
  ALPN took before (the control below). No hard case of Appendix A sends one.
- `cases_check.py` checks the route on every proxy (`routes["tls-noalpn"]`, with `exact`): a TLS
  1.3 handshake for oneport.test without the ALPN extension against the test certificate
  (`b3.tls_probe`, which now takes the offered ALPN list), then HTTP/1.1; it passes only if the
  backend's TLS port answered 200 with the 13-byte body and no protocol was selected. Judged at
  matched timers, and at the defaults where routes are judged (not HAProxy's, M4b-1's reading 5).
- Tests: `test_competitors.Configurations.test_no_alpn_route` (the five rendered configurations),
  `test_runner.test_tls_probe_without_alpn` (the probe against a local TLS stand-in).

The check on L, job casecheck1 (f7d62a2, lab_job.sh: lock, clock floor, THP at madvise, NOTRACK;
a Release build; `ctest -L run` 2 of 2 passed, the runner's and the competitors' tests with their
integration part; then `cases_check.py` on the five proxies, both kinds, both timer settings).
Every judged check passed (exit 0):

| System, kind | Matched: routes / no ALPN / PROXY / fallback | Default: routes / no ALPN |
|---|---|---|
| nginx, cases | HTTP/1.1, TLS / ok / v1, v2 | the same / ok |
| HAProxy, cases | all five / ok / v1, v2 | all but TLS / no (both recorded, not judged) |
| HAProxy, cases-fallback | all five / ok / v1, v2 / SMTP at 3.00 s | the same as cases / no (recorded); SMTP at 0.00 s |
| Envoy, cases | HTTP/1.1, h2c, TLS / ok / v1, v2 | the same / ok |
| Envoy, cases-fallback | the same / ok / v1, v2 / SMTP at 3.00 s | the same / ok; SMTP at 15.00 s |
| caddy-l4, cases | all five / ok / v1, v2 | the same / ok |
| sslh-ev, cases | HTTP/1.1, TLS, MQTT, SSH / ok / none | the same / ok |
| sslh-ev, cases-fallback | the same / ok / none / no greeting (recorded, as M4b-1) | the same / ok |

The control, job casecontrol1: the same `cases_check.py` against the five configurations as they
were at 9853131, matched timers. The no-ALPN check failed on every proxy in every kind: the
connection closed or reset (nginx, HAProxy, Envoy and caddy-l4 in "cases", sslh-ev's), or the SMTP
greeting came back (every "cases-fallback"). So the check tells the route apart.

Raw data on L, `~/lab/p3/m7prep/`: casecheck1/cases_check.jsonl
8848cb61fe989aa5262d495ac158853cc8162ce060f68635fd7137e4f7646c73, casecheck1.log
5acd1b152d8c09a588cb1e1ae8de95184f0e221f1836cd22cd9cd8783f99b8cf, casecontrol1/cases_check.jsonl
3387f2fd262661ee6f84e878f023e3724aea5086e5e10d048603d57e267b0124, casecontrol1.log
eb57c93b8ff93680cf9df432d77b3fb45a6159579f592aced71b170daa90b1cc.

### M5's readings in the revision log

The entry "Readings fixed during engineering (M5), before the code freeze" logs readings 1 (relay
dispatch has no dedicated counterpart, so the relay's operations are given per detection mode)
and 5 (M2b's reading 1 holds with `close()` for the last direction), one line each with why it
follows. Readings 2 and 3 were logged by the coordinator's entry after M5. Reading 4 is not
logged (below). A note in the same entry says M4b-1's reading 4 no longer describes the
configurations (f7d62a2).

### For the coordinator: M5's reading 4 does not hold for every record framing

Reading 4 says section 2.1's bounds hold as frozen, the pass-through ClientHello "now in storage
sized to the records it needs next (at most the message and 5 bytes per record, M2b's reading
3)". That holds when each record ends with the ClientHello. It does not when a record header
announces more payload than the ClientHello can still take:
- `clienthello::reassemble` returns "more" with `need` = the bytes so far, 5 and the length the
  incomplete record's header announces (clienthello.hpp lines 64 to 68); it refuses a record that
  would take the message past B_CH only once that record is whole (line 69).
- In replay, `try_route` sizes the ClientHello's storage to `need` (relay.cpp lines 241 and 253;
  `hello_room`, capped at `kHelloWireMax` = 6 × B_CH, worker.hpp line 111), and the resize writes
  zeros, so the storage is memory the pending connection holds. In peek, `SO_RCVLOWAT` is set to
  the same `need` (relay.cpp line 236); the kernel then holds only what arrived.

A check of the pure function at f7d62a2 (job helloroom1; `~/lab/p3/m7prep/hello-room/need.cpp`,
sha256 7741b32a41c8d4d8a185f72b465f8d83b2d2c29b9ea8e9de22d59a54692818b2; log
ddc2d4a9fe1a73946ec733fb9d9a129878b9ca26b3220c16c54c1e8870d7b225):

| Framing | Received | need | The message and 5 bytes per record |
|---|---|---|---|
| A: a 512-byte ClientHello in one record, its first 9 bytes | 9 | 517 | 517 |
| B: a 104-byte ClientHello in a record whose header announces 16,384 | 9 | 16,389 | 109 |
| C: a 16,384-byte ClientHello, record 1 whole with 16,000 bytes, record 2's header announcing 16,384 | 16,010 | 32,394 | 16,394 |

B3's partial ClientHello is A's shape (the recorded ClientHello in one record), so no development
B3 window was affected. Two readings of the frozen text meet here: B2(d) bounds the "user-space
payload bytes" a pending connection holds, and the bytes received stay within reading 3's bound;
section 2.1 bounds the "memory held by a pending connection", and in C the storage is about twice
B_CH. A candidate fix, not made: `reassemble` and `scan` return "no" at a record header whose
length would take the message past B_CH (`got + len > cap`), the verdict that record gets once
whole, only earlier; the storage then stays within B_CH and 5 bytes per record. B (a record longer
than the short ClientHello it carries, within B_CH) would remain; bounding it by the message
needs the message's length from a partial record. Either change is first-party code, so it must
land before `CODE_FREEZE` and before the records.

### The records drivers (785b66b, b701194, e68087f)

Prepared for the freeze; no citable record was made. Each follows P2's drivers (same author) and
the Papers repo's rule D5.

| File | What it does |
|---|---|
| `bench/build_inputs.py` | Hashes a oneport build the one way the records and the gate share: every first-party target per host (L: oneport, oneport_server, oneport_config, oneport_loop, oneport_tls, opcase, opcase_bin, ophold, record_clienthello, opgen, opgen_core, oneport_tests; W the same less opcase_bin, ophold and record_clienthello), checked against the compile database first (a target compiled but not listed, or listed and not compiled, stops it); config keys `CMAKE_BUILD_TYPE` and `ONEPORT_BACKENDS`; root label `oneport`. Adds the compiler identification, the host and the inputs_hash.py used (path, sha256). Names the measured binaries per host. |
| `bench/sanitize_oneport.sh` | L: one record of oneport per sanitizer (ASan+UBSan, TSan, MSan with the MSan libc++), Release, from a clean checkout: build, inputs hash, `ctest -V` (M5's green options), logs kept and packed (`keep_record_logs.sh`), `oneport-<commit>-L-<san>.json` by `oneport_record.py`. Each sanitizer's suite gets its own port block (`ONEPORT_TEST_PORT_SHIFT`). |
| `bench/sanitize_oneport.ps1` | W: the same with MSVC ASan from a vcvars x64 shell, M6a's ASan options. Untested and not even parsed: W was in use, and nothing ran there. Run it only with Alex's yes. |
| `bench/sanitize_harness.sh`, `bench/harness_record.py` | L: one record of the Go or Rust harness per sanitizer (ASan, TSan): the flavour's build (`build_harnesses.sh`), then its probe in its cases kinds and its route checks at both timer settings, in the environment its flavour runs with (`run_env` of build.json: hyper-util's TSan with its tsan.supp), as M4b-2's development checks ran. The record names the target as `coverage.json` does (`harness_cmux`, `harness_hyper_util`), the inputs hash of `harness_inputs.py`, the toolchain as its compiler, and counts the lab's report pattern and Go's race report. |
| `bench/records_job.sh` | L: every record in order in one lab job: a Release build and the release harnesses; oneport ASan and TSan at once (two suites at most), then MSan; the four harness records one at a time (fixed ports); then the gate of the Release build, into `gate-L.json`, and the inputs hash and sha256 of every measured binary into `measured-L.json`. Stops at the first record that is not green. |
| `bench/keep_record_logs.sh` | P2's, unchanged: logs in `~/lab/records-logs/<record>/`, packed, with a sha256. |
| `bench/gate_lib.py`, `bench/check_records.py` | The gate also refuses a dry-run record found among the records; `--accept-dry-run` lets one count and marks the output never citable. `--harnesses build.json` gates the measured harnesses (release flavour) against their records, with `coverage.json`'s declared gaps (Netty and Jetty whole, MSan for cmux and hyper-util). The output holds `binaries`, the sha256 of the measured executables and harness outputs. |
| `bench/check_rows.py` | A row is refused unless every first-party binary its provenance names (aa.py and handoff.py write `binaries`) has the same name and sha256 in a gate that passed and is citable. |

Dry runs: `DRY_RUN=1` names every record `...-dryrun`, marks it, refuses to write into
`lab/sanitizer-records`, and keeps the logs under the job's directory, so the citable records'
log directories stay free. Records match builds by inputs hash, not commit, so a dry-run record
must never gate the freeze's build; the gate refuses one, and `check_rows.py` refuses a gate made
with `--accept-dry-run`.

Tests: `gate.test_gates` (new: a dry-run record stops the gate; `--accept-dry-run` marks the output;
the harnesses' gate, covered, missing TSan, another toolchain, other inputs, a sanitizer flavour
as the measured build; the gate's binaries; `check_rows.py` passes a covered row and refuses a row
whose binary has no matching green record, a row with no binary, a row whose only gate is a dry
run or did not pass; `build_inputs`' target check), `gate.test_record_writers` (new: `--dry-run`;
`harness_record.py` green and red cases), `run.test_competitors` (new: `PortShifts`, the port
blocks of two shifts never overlap and lie below the in-process servers' random ports;
`ChildReports`, the scan of the started processes' files). On L before the dry run (job unit1, the patch of 785b66b on f7d62a2):
test_gates and test_record_writers all checks passed, test_competitors 35 checks passed (2 skipped,
no build); `bash -n` found the quoting fault fixed in 785b66b before its commit.

### The drivers' dry run

`DRY_RUN=1 bench/records_job.sh`, one lab job each (lab_job.sh: lock, clock floor, THP at madvise,
NOTRACK), from a clone of the lab remote, the records and their logs under
`~/lab/p3/m7prep/dryrun<n>/`. None is citable, and none was copied anywhere.

| Job | Commit | What happened |
|---|---|---|
| dryrun1 | b701194 | ASan's suite red (382 of 383): `run.test_competitors`, a hand-off stub that did not start. Two suites at once at port shifts 3200 and 3600: TSan's probe front (23100 + 3600) took ASan's hand-off port (23500 + 3200); the stride of 400 was less than the tests' block of 516 ports (fixed in e68087f). TSan green. |
| dryrun2 | e68087f | Both suites red: e68087f broke `test_competitors.py` (a decorator above the new constants; fixed in 3627355). |
| dryrun3 | 9afccbc | ASan green, TSan red: the probe's stub for the silent case (port 24910) exited at once although the two suites' blocks were apart. The C++ tests' in-process servers take random runs of free ports from 10000 up to the ephemeral range (`server.cpp`, `bind_all`), so with two suites' C++ tests running one could hold it; the stub's standard error was in the test's temporary directory, gone, so the cause is not proven. Alone, the same stub started 20 times of 20 and the same probe passed 6 times of 6. 6795407 moves the integration tests below 10000; dryrun4 and dryrun5 then passed. |
| dryrun4 | 6795407 | Every step green (below). |
| dryrun5 | 8e01e1d | The three oneport records again, after the integration tests learned to fail on a sanitizer report in their processes' files (8e01e1d): all three green, 383 of 383 tests each, 0 report lines, `run.test_competitors` passing in each with ASan and TSan at once (records sha256 95ea5bdf..., 7e39d1b4..., 7b3458d4...; records.log b538d76e52ef22df1be603028baa3d030eed489a5eba09a83fc0f9ec42c30957). |

dryrun4, every record a dry run (`-dryrun`, `"dry_run": true`):

| Record | Green | What it ran | Seconds |
|---|---|---|---|
| oneport ASan+UBSan | yes | 383 of 383 tests, 0 report lines; 12 targets hashed | 154 (with TSan beside it) |
| oneport TSan | yes | 383 of 383, 0 | 148 (with ASan beside it) |
| oneport MSan | yes | 383 of 383, 0 | 146 |
| harness_cmux ASan (`go build -asan`) | yes | probe in cases and cases-fallback, route checks at both timer settings, 0 reports | 36 |
| harness_cmux TSan (`go build -race`) | yes | the same, 0 reports or races | 34 |
| harness_hyper_util ASan | yes | probe in cases, route checks, 0 | 54 |
| harness_hyper_util TSan | yes | the same, with `TSAN_OPTIONS=suppressions=<checkout>/bench/competitors/hyper-util/tsan.supp`, 0 | 50 |

- The gate (`check_records.py --accept-dry-run`): passed, marked `"dry_run": true` and
  `"citable": false`. It matched the Release build's 12 targets (inputs hash of `oneport`
  d10d4f45b353, config `CMAKE_BUILD_TYPE` Release, `ONEPORT_BACKENDS` epoll;io_uring, compiler
  Clang 22.1.8, pins 2d49d03bacf8) to the three oneport records, and the release harnesses to
  their four records, with Netty and Jetty allowed by their declared gap and the harnesses' MSan
  by theirs. `measured-L.json` holds the inputs hash of 16 targets (12 and the four harnesses) and
  the sha256 of 8 binaries (oneport, opgen, opcase, ophold and the four harness outputs).
- The refusals, on the same build (job gateneg, under the lock): without `--accept-dry-run` the
  gate refuses the dry-run records ("is a dry run of the records driver"); with no records it
  refuses the build ("oneport ... has no green asan, tsan, msan record"); `check_rows.py` refuses
  all 48 rows of M5's job m5m3c and a row naming this build's oneport and opgen, since the only
  gate is a dry run. The Release oneport and opgen of 6795407 have the same sha256 as m5m3c's at
  ac84f2d (2f2d9d35582e, 0c0f3457a34c): no compiled input changed between them, and the build
  reproduced the same bytes. The unit tests cover a passing row and a row whose binary differs.
- Seen in passing: in dryrun2's ASan suite `run.test_runner` passed but printed a thread's
  exception from its stand-in stub (`B3Relay.serve_once`: `ENOTCONN` at its `shutdown`, the
  client having reset first); it matches no report pattern.

dryrun4's files (sha256): gate-L.json
b35c4271fd1345c6229bceb6dbf81fef47a9672d0739ee65f44c85345a1c7ba6, measured-L.json
6c6c67904685e0ec95efbfdf7aa33a4ef6cfaa9c86a102467648f1ab66a4c607, release.inputs.json
4fe72ec3d5a68a1c90efcf1f2b84388bd1ecf770efb46c3019052a800fc509dc, records.log
cd2994a12f2b16d1e30ed8af621420c2c847ad35720649d0166cd23d43786fcc.

## M7 fixes, 2026-10-03

The coordinator's five decisions after the M7 preparation, done before the freeze. Nothing here
is a result. Every job on L was untimed (scratch builds, unit and integration tests, the leak
checks, the suite in four builds, the records drivers' dry run) and ran under `lab_job.sh` (the
lab lock, the clock floor, THP at madvise, NOTRACK), from fresh clones of the lab remote; no
window ran, so no lab-journal line was written. `m6b-windows`, `m7-analysis` and W were not
touched. Scripts and logs on L: `~/lab/p3/m7fix/`.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| d15e775 | fix: the pass-through ClientHello's storage stays within B_CH and 5 bytes per record (M5's reading 4) |
| c1b4283 | feat: b3.py's rows name the binaries they ran, so check_rows.py binds them |
| 3382bb8 | docs: hypotheses.md revision log: the route without ALPN; N_BG_TLS = N_BG_MQTT = N_BG_SILENT = 64 |
| 97a5363 | fix: the Go and Rust harnesses end on SIGTERM by a normal exit, so the sanitizers' exit checks run |

Then this section (the commit after these).

### 1. The route without ALPN in all five proxies

Logged as decided, one line: item 1 of the revision-log entry "The code freeze's preparation
(M7)". The configurations are f7d62a2's, unchanged.

### 2. M5's reading 4: the ClientHello reassembler, fixed (d15e775)

Not logged as a reading, as decided.
- The refusal. `clienthello::reassemble` and `scan` refuse a record at its header when the
  length it announces would take the reassembled handshake bytes past B_CH (`got + len > cap`),
  the verdict that record got before once whole, only earlier. The relay then closes the
  connection and counts it `route_rejected`, the frozen outcome of a ClientHello longer than B_CH
  (M2b's reading 3, M3's reading 1). Every whole stream gets the verdict it got before.
- The bound. With the refusal, what the reassembly asks for while the verdict is "more" is at
  most B_CH and 5 bytes for each record that carries the bytes so far, the incomplete one
  included (`need <= B_CH + 5 * (records + 1)`). The relay sizes the storage to it in replay and
  `SO_RCVLOWAT` in peek, so the cap of the brief falls out with no change to either backend's
  I/O path. `hello_room` now reserves exactly that size: libc++'s `resize()` had grown the
  storage from 16,005 to 32,010 bytes in shape C even with the refusal (control2r, below).
- The reading of the bound, for the coordinator: B_CH for the handshake bytes and 5 bytes per
  record, as M2b's reading 3 counts them ("at most the message and 5 bytes per record"), with
  B_CH as the message's bound. Shape B, a 104-byte ClientHello in a record that announces 16,384,
  still asks for 16,389 bytes: B_CH and one record's 5, the bound itself, not past it. Bounding B
  by its own message (109 bytes) would need the ClientHello to complete before its last record is
  whole, which changes when a route is chosen; not done.
- Both arms. `scan()` runs in the in-process TLS handler (`tls_step`) in one-port and in
  dedicated mode, so the change is compiled into both arms of every TLS cost cell. There the
  early "no" can only replace a "more" whose need exceeded the handler's buffer (`kRecvBuf`,
  4,096 bytes; the refusal needs more than B_CH), where the handler already made OpenSSL's state,
  so its behaviour does not change in either arm. `reassemble()` serves pass-through, which runs
  in one-port mode with relay dispatch only (`config.cpp`).

helloroom1's shapes, what the reassembly asks for:

| Shape | Received | Before (f7d62a2) | Now |
|---|---|---|---|
| A: a 512-byte ClientHello in one record | 9 | more, 517 | more, 517 |
| B: a 104-byte ClientHello in a record announcing 16,384 | 9 | more, 16,389 | more, 16,389 (= B_CH + 5) |
| C: record 1 whole with 16,000 bytes of a 16,384-byte ClientHello, record 2's header announcing 16,384 | 16,010 | more, 32,394 | no (refused at record 2's header) |

Tests: `clienthello.helloroom1` (the three shapes, with the numbers before the fix from a copy of
the old reader kept in the test); `clienthello.refusal` (every prefix of C's whole stream: never
"yes", "more" as before until record 2's header is whole, "no" from then on; the old reader also
refused the whole stream; the boundary, a record 2 of exactly the 384 bytes the message lacks, is
accepted, 16,394 bytes on the wire); `clienthello.need_bound` (every prefix of nine framings, the
long ones near each record boundary and every 61st byte: the bound, `scan()` equal to
`reassemble()`, and no verdict other than an earlier "no" against the old reader);
`relay.pass_through_storage.{replay,peek}` on both backends (A and B close at T_dec in storage of
exactly 517 and 16,389 bytes; C is rejected at once, its storage at most 16,394 bytes; counters).

On L, scratch jobs (`try_job.sh`, a patch on a clone at adbc041, ASan+UBSan):

| Job | What | Result |
|---|---|---|
| try2a | the fix and the tests | 52 of 53: `need_bound`'s count of prefixes checked was set too high (6,030, not above 10,000); lowered to 5,000 |
| try2b | the same, the count fixed | 20 of 20 (`clienthello` and `pass_through`), 0 report lines |
| control2 | the tests on the code before | 7 failed, exactly the new tests: C's need 32,394; C not refused at 16,010; C's route timed out, not rejected |
| control2r | the fix without the exact allocation | C's storage 32,010 bytes in replay, on both backends |

Logs (sha256): try2b.log a099497e967d52bf904bbe5ce1a1bc7547de9dfea51046acc80144311c61c97a,
try2b/ctest.log 15b00d2d802857cb29dbb9e88682cd081c2144b704f49f3a90f57a2905b80345, control2.log
503c51d642db57c852764dabcacc23142a263a377b6c4c28411b1ee90d87ceee, control2/ctest.log
c142aae9c6670c72a19d9d69da4fd3f83a94aa5c7e87e8399b259334c4d7045f, control2r.log
fd21cce50439ae7a2d46d768abe32aa04367dc8f7315f8ede744d9667b02d412, control2r/ctest.log
fe12578c8142a8e56ac122d670a8e06a20e4e5030b5c01dfc644d77775f0829a.

### 3. b3.py's rows name their binaries (c1b4283)

Each B3 row's `provenance` is aa.py's (commit, build, compiler, pins) with:
- `binaries`, {name: sha256} of the first-party executables the window ran, under a gate's names
  (`build_inputs.BINARIES` and `harness_<name>`): `opcase` always; `ophold` in its windows;
  `oneport` for the server's arms and, as the stub, behind every relay system; `harness_<name>`
  (the file at `<build>/harness` that ran) for a library. This is what `check_rows.py` binds.
- `binary_paths`; `inputs_hash_gate`, every target's inputs hash as the gate hashes the build
  (`build_inputs.py`), with its configuration and compiler; aa.py's development `inputs_hash`
  stays beside it.
- For a library, `harness`: build.json's entry (target, inputs hash, flavour, tools, recorded
  output sha256) and `same_as_build_json`, whether the file run is that output.
- For a proxy, `competitors`: its binary's path and sha256 and its B3 configuration's sha256.
  Proxies are not first-party and never appear under `binaries`.
Tests (`run.test_runner`, class `B3Provenance`, a stand-in build tree, runs anywhere): the names
per system, all among a gate's names; rows of seven systems pass `check_rows.py` against a
passing, citable gate of the tree's binaries; a gate without the cmux harness refuses that row
alone; a binary rebuilt after the gate is refused; a row without provenance, as before, is
refused; a harness that differs from its build.json is marked.

On L, job b3prov1 (`b3prov_job.sh`, untimed, no window, nothing started), against the dry run
dryrun6's Release build and harnesses (below): `b3.provenance` for each of the 12 systems names
the binaries above; every row's binaries equal the dry-run gate's (0 of 12 refused, matched
directly, since `check_rows.py` refuses the dry-run gate itself as never citable, which it did);
each row's inputs hash per target equals `measured-L.json`'s for all 12 targets; every harness
file is its build.json's output. Log sha256
6e1d7bb3c285d3ff5e77255de13785425d6095df4d01234c0f4637a5b1edca93.

### 4. The harnesses' leak checks (97a5363)

Both harnesses now end on SIGTERM by a normal exit and print `<name>: stopped by SIGTERM`:
cmux closes its listener and its HTTP server and returns from main (it does not wait for
connections still being matched, which cmux's `Serve` would, up to their read timeout); the
hyper-util harness's handler writes one byte to a socket pair (glibc's `signal(2)` and
`write(2)`, declared in main.rs, so no crate is added and Cargo.toml and Cargo.lock are
unchanged), its accept loop returns, and the runtime is dropped with its tasks and threads. The
JVM harnesses are unchanged; their gap is declared. `coverage.json` declares no gap for the
harnesses' leak check, so nothing there changes (the checklist's alternative, item 7, is not
needed).

`harness_record.py` makes a record green only if every run of the harness in the checks ended
through the handler (each `stdout.log` that says `<name>: listening` also says
`<name>: stopped by SIGTERM`), and not if the checks ran none; its docstring and each record's
note now say the exit checks run. Tests in `gate.test_record_writers`: the counts, red from a run
that did not end through the handler, red from checks with no run, red from LeakSanitizer's
report at a clean exit.

The deliberate leak, job leak1 (`leak_job.sh`, scratch clones at c1b4283 with the patch of
97a5363; build_harnesses.sh's asan flavour; each harness started, sent SIGTERM once listening,
waited for):

| Harness | Variant | Exit | Stop line | LeakSanitizer |
|---|---|---|---|---|
| cmux | new | 0 | yes | none |
| cmux | new, with a leak (a C `malloc` of 4096 bytes whose only pointer is cleared) | 1 | yes | 4096 bytes in 1 allocation |
| cmux | before (adbc041), with the same leak | 143 (SIGTERM) | no | none |
| hyper-util | new | 0 | yes | none |
| hyper-util | new, with a leak (`std::mem::forget` of a 4096-byte Vec) | 1 | yes | 4096 bytes in 1 allocation |
| hyper-util | before (adbc041), with the same leak | 143 (SIGTERM) | no | none |

So the handler is what lets the exit check run. Files (sha256): leak1/summary.txt
c1241a850ea556e4c8677af0f1d360b4de4688662018256b2b08587bf9893aa5, leak1/cmux-new-leak.stderr
aa2659abeb15c2084a19cf2247a185dd5aea5379d9c8942a334e55f04cb60924,
leak1/hyper-util-new-leak.stderr
0cddf176cecab848b6a0023be0e07cf1f14cc784826b761de67455d620090cdd, leak1.log
e1a87ba96e0412a97f47be3cd2d27466aa9ef85f9ff26490b38e4320d9e0b225, leak_job.sh
889aa04d2e25e369bbd2101da153f2006c3f1ace4857bbdd83177e0e775016c2.

### 5. N_BG_TLS, N_BG_MQTT, N_BG_SILENT: 64 each (3382bb8)

- The frozen text. Section 9.1's row names them "the background of the secondary mixed-protocol
  cell" and gives no rule beyond that; section 10 makes the background "fixed", of TLS
  keep-alive, MQTT keep-alive and silent connections, "the same in both modes"; section 9 says
  each value "is never chosen after data that could favour a value"; the proposal (5.7, E3) says
  only that they are set in engineering before the freeze.
- So they are a design choice, set with no measurement: a window run to choose them could later
  be read as a choice after data. No window of the mixed cell has run (it has no runner).
- The value: 64 each. C = 64, WL1's connection slots per server core and WL3's connections, is
  the only count of connections per core the frozen text fixes for a cost cell; each kind of
  background then holds as many connections as the churn has slots, and equal counts weigh no
  kind above another.
- The revision log: section 8 step 3 records the values engineering sets at the code freeze.
  They are logged now as well (item 2 of the entry "The code freeze's preparation (M7)"), as
  `K_SRC` was, which fixes them before any mixed-cell code exists; the freeze's entry names them
  again.
- For the coordinator, before the mixed cell's runner is written: how the background is held
  in a 5 s window. In one-port mode a silent connection is closed at T_dec (1 f) on a listener
  without a fallback, or handed to the fallback at T_fb (1 a), both 3 s, while dedicated mode has
  no detection timer; so "fixed" needs a rule (the generator opens a closed silent connection
  again, or the listener names a fallback), and whether the keep-alive background sends requests,
  and at what rate, is not set either. opgen takes one protocol and one load per process and
  opcase holds silent connections without opening them again, so the background can be made of
  several processes of the existing generators, or needs a generator change, which must land
  before `CODE_FREEZE`.

### The suite in four builds

Job chk1 (`checks_job.sh`, at 97a5363, a fresh clone of the lab remote): Debug and ASan+UBSan at
once, then TSan and MSan at once, each `ninja -j 5` and `ctest -V -j 8`, as M5's `sancheck.sh`
ran them, with one change: each build's integration tests get their own port block
(`ONEPORT_TEST_PORT_SHIFT` 0, 600, 1200, 1800), as `sanitize_oneport.sh` gives them, since two
suites run at once.

| Build | Warnings | Tests | Report lines |
|---|---|---|---|
| Debug | 0 | 390 of 390 | 0 |
| ASan+UBSan | 0 | 390 of 390 | 0 |
| TSan | 0 | 390 of 390 | 0 |
| MSan | 0 | 390 of 390 | 0 |

390 is M5's 383 and the 7 new entries (`clienthello.helloroom1`, `.refusal`, `.need_bound`, and
`relay.pass_through_storage.{replay,peek}` on two backends). Seen in passing, as in dryrun2: in
three of the four logs `run.test_runner` passed but printed a thread's exception from its
stand-in stub (`B3Relay.serve_once`: `ENOTCONN` at its `shutdown`, the client having reset
first); it matches no report pattern, and the test is older than this work.

Logs (sha256): debug build 1b29f2127009a5e6720264afa1e64096ffd3b3ca0969e65539a1a3cf5b30f58e,
ctest bd184b57532085e7645ea23389974039ce79e94958f7ab6c3e0b52d6a78cec35; asan build
d79861281373ae703693f67505e2c89a85819f1e814f30e29501573c17102d86, ctest
a614332f87203968e40e7f5025efc1d9e045259adbae4e8754b6ab6659a8a686; tsan build
46d5c50aae6b476e8f061f2aab1eef76e90cfcc57bea8be82a95aa80dd5da7d0, ctest
1461ebdd4be17f6bc80b884b44005933511efcb7065fbcba013ac861fa28033e; msan build
b7070f4fb3b0279e643f4113a191d80d409599fbc2036f463e7a2238e0db5577, ctest
98975a6dfb13bc59a4e98e4804294d27a6d6e64a20b28089b9f66a6e1ef44ec7 (all in
`~/lab/p3/m7fix/check/97a5363/`).

### The records drivers' dry run

Job dryrun6: `DRY_RUN=1 bench/records_job.sh` at 97a5363 from a fresh clone of the lab remote
(`~/lab/p3/m7fix/dry-src`), one lab job, every record named `-dryrun` and marked, never citable,
nothing copied anywhere. Every step exited 0:

| Step | Green | What it ran | Seconds |
|---|---|---|---|
| release | yes | the Release build and the release harnesses | 35 |
| oneport ASan+UBSan | yes | 390 of 390 tests, 0 report lines | 153 (with TSan beside it) |
| oneport TSan | yes | 390 of 390, 0 | 153 (with ASan beside it) |
| oneport MSan | yes | 390 of 390, 0 | 147 |
| harness_cmux ASan | yes | probe and route checks, 0 reports; 10 harness runs, each ended through its SIGTERM handler | 37 |
| harness_cmux TSan | yes | the same, 0 reports or races; 10 runs, each so ended | 44 |
| harness_hyper_util ASan | yes | the same, 0 reports; 5 runs, each so ended | 54 |
| harness_hyper_util TSan | yes | the same, with tsan.supp, 0; 5 runs, each so ended | 50 |
| gate | passed, `dry_run` true, `citable` false | the Release build's 12 targets and the 4 release harnesses against the 7 records | 0 |

So the harnesses' ASan records now include LeakSanitizer's check at exit, and none reported a
leak. The gate's binaries (sha256, first 12): oneport 8a72e37da73b, opgen 0c0f3457a34c (as at
6795407: no input of opgen changed), opcase da382a7e821c, ophold 3f405ac29c62, harness_cmux
8b4f12a1edb5, harness_hyper_util d6e52b94e88c, harness_netty b469789ec32c, harness_jetty
9937e7f0a0fc. `measured-L.json` holds 16 inputs hashes (12 targets and 4 harnesses); config
`CMAKE_BUILD_TYPE` Release, `ONEPORT_BACKENDS` epoll;io_uring.

Files (sha256), `~/lab/p3/m7fix/dryrun6/`: gate-L.json
68e1bf7b06d8274822725947aa8621880a829b13341cddf6a076b499e1b11e98, measured-L.json
113259e968a3fed4aac8dfc9b47755f42e15dd81b39c92f3797bbf73953d6a54, release.inputs.json
0a7b89abb55fe40b16af0a0ffd899e8ba98aa4044316abeea72ed8ac8c02d954, records.log
03a6d4836ec565760062fcfb034b67000b02fdf5c72c4e62d36393298eab507f.

### What the freeze still needs

In the M7 checklist's order (below), after these fixes:
1. `ANALYSIS_COMMIT`: the merge of the analysis branch (`m7-analysis`, another agent's) with the
   code that runs 4.6 and its tests, committed before the code freeze (section 8 step 2).
2. The final merge of `m6b-windows` into main, and W's checks with Alex's yes when W is free
   (Debug and MSVC ASan, the whole suite). W has not built any of these fixes: the new pure tests
   (`clienthello.helloroom1`, `.refusal`, `.need_bound`) and the changed `clienthello.hpp`
   compile on W; the relay, the harnesses and `b3.py` are Linux only. Then `build_inputs.py`'s
   `TARGETS["W"]` and `BINARIES["W"]` against the merged tree, and the L suite again on the merged
   tree.
3. The pins read again on the freeze's day (the JDK, 25.0.5 if published; OpenSSL 3.5, nghttp2,
   the competitors, caddy-l4's commit, xcaddy, the Rust toolchain; Netty's allocators).
4. The `/sys/kernel/slab/` re-read on L.
5. The seeds entry (every seed of 4.7, checked against the lab journal).
6. For the coordinator: how the mixed cell holds its background ("M7 fixes", item 5). If the
   frozen generators cannot hold it as decided, the generator change lands before the freeze.
   With it, the runners still to write (the mixed cell's; the competitors' hard-case table of
   section 10, "What M7 starts from"): checklist item 8 freezes the Python half of the suite with
   the tests, so a runner written after `CODE_FREEZE` would need the coordinator's reading of
   whether a new runner, as against a changed test, is a later change.
7. The freeze: the `CODE_FREEZE` commit with the final `coverage.json`, the records at that
   commit (L: `records_job.sh` with `REPO_URL` set; W: `sanitize_oneport.ps1` with Alex's yes),
   the gates and `measured-L.json`, and the freeze's revision-log entry with every value of
   section 9.1.

## M7c, 2026-10-03: the frozen runners

The runners that will produce the frozen data, written before the code freeze. Nothing here is a
result: every window below is development data, journaled as such, and every number is a
development reading. Every job on L ran under `lab_job.sh` (the lab lock, the clock floor, THP at
madvise, NOTRACK) from fresh clones of the lab remote under `~/lab/p3/m7c/`. `m6b-windows` and W
were not touched. Two first-party changes land before the freeze: opcase's holder of the mixed
cell's silent background with `opcase case --list`, and `--record` writing each line through. One
change of `analysis/`: rule E's relay copy is one choice per backend that relays.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| 0b63d62 | feat(opcase): the mixed-protocol cell's silent background and the hard cases' expectations for a judge |
| 7364fbb | fix(analysis): rule E's relay copy is one choice per backend that relays |
| 6f19094 | feat(gate): check_rows.load_gates(accept_dry_run=True) for a development check |
| 7f3e41b | feat(run): the frozen runners: the A/A pilot, the cost family, B3, M1 to M3, rule E, section 10 and the hard cases |
| af99cd3 | feat(run): the runners record their own commit; development options for K_BASE's window count and devcheck's gate-only rows |
| c5f324f | fix(run): rule E's decide takes the proposed default, with a note, for a choice whose development sessions did not run (development only) |
| beed996 | fix(server): --record writes each line through to its file at once |
| 81e1216 | fix(run): the hard cases' raw directory, printable first lines in the competitors' rows; --dev-r sizes the m2-rate part |
| 071b0f9 | docs: status.md, M7c; hypotheses.md revision log, M7c's five readings |
| 7d0a92d | fix(run): a frozen section 10 run refuses to start without --silent-ports (the check could not fire); a test |
| f8734a2 | fix(run): a lab job runs at nice 0 (lab_job.sh refuses any other; the nice in every fingerprint and timer row) |

Then this section's update (the commit after these). In the Papers repo, 4af4be6 and 3cb0bcd
(local, not pushed): 18 lab-journal lines, one per runner of each end-to-end job, every one marked
development. The submodule pointer is the coordinator's.

### The runners (`bench/run/`)

Every runner writes rows in the contract of `analysis/rows.py`, each with job, session, position,
arm, cell (analysis/cells.py's id), `development` (false unless `--development`), the order's
seed, the session's fingerprint (`pin.sh` with the notrack, clock-floor and THP states), and a
provenance that names every first-party binary the window ran (`binaries`, {name: sha256}, the
gate's names), the build's inputs hash per target as the gate hashes it (`inputs_hash_gate`), the
build's commit and the runner's own (`runner_commit`). Every runner stops cleanly on SIGTERM,
SIGINT and SIGHUP (window.py's `stop_on_signals`: every finally block stops the processes it
started; the window cut short gets an invalid row naming the signal, then the job ends).

| Runner | What it runs | Rows |
|---|---|---|
| `pilot_run.py` | 8 step 4 on L, dedicated mode only: P = 16 sessions of every cost cell of L (aa.py's windows; `window.run_window` refuses any other mode, and no flag of the runner names one), SEED_PILOT_L's order, the C1 and C2 cells and their reruns before the C3 cells; the timer part (per backend 128 runs of HC12 against the dedicated HTTP/1.1 port with PROXY on, one server with `--record`, lateness = wait_return - deadline); the split part (per backend 16 replicates of HC02.HTTP.k01 at each gap of 5, 10, 20, 50, 100 ms, one fresh server per replicate, `recv_data` = recv_calls - recv_eof - recv_again). Failed part runs are rows with valid false and the reason, never run again on their own. | `windows.jsonl` (aa.py's rows), `parts.jsonl` (pilot.py's timer and split rows) |
| `cost_run.py` | 5.1 on L: the 24 cost cells at R_C (resolved or not), one-port (arm A, aa.PORT_A) against dedicated (arm B, PORT_OFFSET above), in-process, rule E's default detection mode in both arms' flags, SEED_ORDER_C_L, each C3 cell at the pilot entry's lambda passed unchanged. Refuses a frozen start unless the freeze guard passes with the pilot entry and rule E's file. | family C |
| `b3_run.py` | 5.2 and 6.2 on L: the 18 Holm and 16 descriptive cells and section 10's 4 cells of the other detection mode, R_B = 16, one order with SEED_ORDER_B_L; b3.py's windows with rule E's default detection mode and relay copy (HAProxy with `option splice-auto` where the relay splices); the part `kbase`: ophold windows until 16 are valid, at most 4 more, never more than 16 valid. `--other-mode-system` has no default (below). | b3.py's (kind b3, family B3 or S/b3-other-mode), ophold's (kind ophold) |
| `m_run.py` | 5.3 and 6.3 on L: M1 (default against other detection mode, in-process churn), M2 (in-process against relay to a server in dedicated mode on the cell's backend, open loop at M2_RATE, WL6's CPU per connection of front and backend together), M3 (the relay against each proxy, closed loop), R_M = 16, SEED_ORDER_M_L; the part `m2-rate`: 6 development sessions per M2 cell, closed loop, M2_RATE = RATE_FRAC x the smaller arm's median, written to `m2_rates.json`. | families M1, M2, M3 |
| `rule_e.py` | Rule E on L after the pilot entry: per Linux backend 6 development sessions of HTTP/1.1 churn for the detection mode (replay against peek, one-port in-process) and for the relay copy (user space against splice, the relay in front of the stub); `decide` writes rule E's file (format below). | family rule-e (development), `rule_e_evidence_L.json` |
| `s_run.py` | Section 10 on L, R = 16, SEED_ORDER_S_L: SSH C1 to C3 (C3 after the C1 sessions, at RATE_FRAC x the slower arm's median), the mixed cell, the two-core cells (one-port against dedicated; the SO_REUSEPORT group against the shared listener), the relay on io_uring against each proxy, M1's and M3's TTFB at a fixed load (lambda from the M runner's closed-loop rows). The TLS variants are listed as not runnable (below). | family S with the bullet |
| `hardcase_run.py` | B1 and B2 on L: the 25 cases, epoll and io_uring, replay and peek, in-process and relay (8 entries), 16 replicates, the frozen timers (3 s), G_L and GAP_SPLIT from the pilot entry, HC7 skipped where 9.2 says so, rule E's relay copy; the measured binary with `--record`, one server per listener setup per entry, `opcase case --id` per run, the run's record lines matched by the client's port once the close is recorded; the judge is `tests/case_tests.cpp`'s check_run, check_reply and check_route ported line for line (the expectations come from `opcase case --list`); the part `competitors`: each proxy and library in its cases configurations at matched timers and at its defaults, R_COMP_CASES = 3, T_OBS = 60 s, descriptive rows. | `hardcases.jsonl` (kind hardcase, one per run with every B1 and B2 check; kind hardcase-servers at each entry's end), `hardcases-table-<job>.json`, `competitor_cases.jsonl` |
| `devcheck.py` | The development end-to-end check (below). | `devcheck.json` |

Shared: `sessions.py` (the session engine), `freeze_guard.py` (a frozen run's preconditions),
`runlib.py` (the command line, provenance, the input files), `cellwin.py` (the in-process window in
either mode, with the mixed cell's background). `lab_job.sh` now refuses a job that runs at any
nice but 0 (exit 92; below, "A lab job's priority"), and every session's fingerprint records the
runner's nice and timer slack (`priority`). `handoff.py` and `b3.py` gained the options the
runners need (rule E's relay copy, a dedicated backend, an in-process front, an open-loop rate,
WL6 over the exchanges due that completed in open loop); their earlier behaviour is the default.
`competitors.py` fills HAProxy's new field `SPLICE_AUTO` (in `defaults`, where HAProxy takes the
option). `journal.py` has a kind `runner`.

### The session engine

- The order is drawn before the first window from the runner's seed (Python's
  `random.Random(seed)`, a design choice): the base sessions shuffled group by group (the pilot's
  C1 and C2 cells, then its C3 cells; section 10's SSH C3 cells after the rest), then X per base
  session in run order, then X per rerun slot, cell by cell, ceil(R/4) slots each. No draw depends
  on which sessions fail, so a job that stops and a later job that resumes it run the same order.
- A session with an invalid window, or with fewer than four windows, runs again at the end of its
  group as a new session (`<cell>.r<k>`), in the order the invalid sessions ran, while the cell has
  slots left; never more than R valid sessions (analysis/ refuses more).
- A job resumes from every row already in the output's `windows.jsonl`, whichever job wrote it:
  a session with a row is never run again under its id, and the rerun slots used are counted
  across jobs.
- A window that crashes, or that a signal cuts short, still gives a row: invalid, the reason, the
  arm's identity fields (so analysis/rows.py takes its cell from them) and its provenance (so
  check_rows.py binds it). A session of four fault rows still names its cell.

### What a frozen run checks, and how the entries must be written

`freeze_guard.py` runs before any window of a frozen run (no `--development`) and gives a
Clearance whose record goes into every row. None of the entries exists yet; the runners find them
by these tokens, which the coordinator's entries must carry:
- CODE_FREEZE: a revision-log line holding the word `CODE_FREEZE` and the commit's full
  40-character hash. The commit must be an ancestor of HEAD, `git diff CODE_FREEZE HEAD -- bench
  tests CMakeLists.txt` empty, and the working tree clean there (the M7 checklist's item 8).
- The seeds entry: the sha256 of the seeds JSON file (the 14 names of 4.7, as analysis/ reads it)
  on a line holding the word "seed".
- The pilot entry: the sha256 of `pilot.py`'s output on a line holding "pilot", added by a commit
  that descends from CODE_FREEZE (and is not it); the output complete (both hosts), not synthetic,
  at N_SIM = 1,000.
- Rule E's file and M2's rates: each file's sha256 on a line holding "rule E" or "M2_RATE", added by
  a commit that descends from the pilot entry's.
- `hypotheses.md` committed and unchanged in the working tree.
- The build: the sha256 of every binary the runner will start must be in a gate that passed, is
  not a dry run and is citable (check_rows.py's rule, before the first window).
The pilot runner needs CODE_FREEZE and the seeds; every other frozen runner also needs the pilot
entry (section 8 step 7). The guard's tests run on a temporary git repository (below).

### Rule E's file and how rule E is computed

The file (`rule_e.json`), exactly the three keys `analysis/analyse.py` reads:
`{"default": {"epoll": "replay"|"peek", "io_uring": ..., "IOCP": ...}, "relay_copy": {"epoll":
"user-space"|"splice", "io_uring": ...}, "iocp_receive": "zero-byte"}`. `rule_e.py run` writes the
evidence per backend and choice (`rule_e_evidence_L.json`: each session's option / default ratio,
whether every valid session favours the option, each arm's operations per connection, the choice);
`rule_e.py decide` writes the file from L's evidence and W's (the IOCP detection mode, from W's
sessions by W's runner, in the same form), and refuses without W's in a frozen decision.
- IOCP's receive form is decided (the coordinator's decision of 2026-10-03: the zero-byte form is
  rule E's only candidate; no session runs, and it governs dedicated mode on W before W's pilot).
- The detection mode and the relay copy exist only in one-port mode and are decided after the
  pilot entry: per Linux backend, 6 development sessions of HTTP/1.1 churn each, X Y Y X, arm A the
  proposed default, arm B the option, invalid sessions run again by 4.1's rule (at most 2). The
  detection sessions run in-process; the relay-copy sessions run M3's arrangement (the server's
  relay on CPU 14 in front of the stub on CPUs 10 and 12; section 4.1's hand-off placement).
- The option replaces the default when the backend has at least 6 valid sessions, the option's
  connections per second (the mean of its two windows) are strictly above the default's in every
  one, and the option's operations per connection are not higher: the sum of the server's call
  counters by kind (accept, receive, peek, zero-byte receive, send, setsockopt, the check of 1(b),
  epoll_wait, epoll_ctl, io_uring_enter, GetQueuedCompletionStatus, connect, splice, shutdown) and
  io_uring's submissions by opcode, over each window's server process, per accepted connection
  (WL5; the M3 entry's item 6), averaged over the arm's valid windows. These are readings and
  design choices for the coordinator (below).

### The mixed cell's background (M7b's open item 6)

What the frozen text defines: section 10, "C1's HTTP/1.1 churn with a fixed background of TLS
keep-alive, MQTT keep-alive and silent connections, the same in both modes", and section 9.1's
counts N_BG_TLS = N_BG_MQTT = N_BG_SILENT = 64 (logged). "Fixed" is met by holding each count:
- Silent connections: `opcase hold` (bench/cases/hold.hpp, a generator change, in 0b63d62) holds
  64 silent connections and keeps the count by one policy in both arms: a connection the peer
  closes (EOF or reset seen) is closed and opened again at once to the same port, in the pass that
  saw it close; a failed or slow connect (1 s) is counted and made again; bytes a port sends (the
  SSH line, the SMTP greeting of a dedicated port) are read and discarded; at the stop every
  connection is closed by reset. In one-port mode T_dec closes a silent connection (1 f, no
  fallback on the cell's listener) and the holder opens it again, so the server keeps 64 pending
  silent connections and handles about 64 / T_dec closes per second; in dedicated mode no
  connection is closed and the policy never fires. The holder counts what the policy did
  (`closed_by_peer`, `reopened`, `held_min`, `connect_failures`) and the window keeps it.
- TLS and MQTT keep-alive: WL3 is the frozen text's only definition of keep-alive ("C connections
  established before the window, one request in flight per connection": HTTP/1.1 GET over one TLS
  connection; MQTT PINGREQ after one CONNECT), so each background is opgen's `--load keepalive`
  with 64 connections, as a process of its own. This is a reading for the coordinator (below):
  it makes the background a closed-loop load, not idle connections.
- The background starts before the probe, is established (opgen's MEASURE_START, opcase's HOLD)
  before the cell's opgen starts, and must still run when the cell's window ends; its connect
  failures count as the window's (section 7), and its generators' error share is held to 0.1%.
  `misclassified` on the one-port arm counts every class outside {HTTP/1.1, TLS, MQTT} and any
  classified beyond the connections each generator opened (the probe included).
- Open, for the coordinator (not in the frozen text): where the silent connections go in
  dedicated mode (`--silent-ports http1` or `spread`, no default; the proposal's "dedicated mode
  spreads it over its ports" is not frozen); the placement (a design choice of M7c: the cell's
  opgen on CPUs 2 to 9, the TLS background on 10 and 11, the MQTT background and the holder on 12
  and 13; section 4.1 names none).
- Shown untimed: `gen.hold.{epoll,io_uring}` (one-port mode with T_dec = 200 ms: every close is
  reopened and the server's silent outcomes equal the closes seen; the policy off as a control;
  dedicated ports close none, the SSH lines discarded) and `gen.binaries` (opcase hold against the
  oneport program in one-port mode, at least 3 reopened in 700 ms). In the end-to-end check the
  background ran in the dedicated arm only (the one-port arm is a stub there).

### No one-port window against dedicated mode, and how the check kept it

Three locks, the first two in code and tested:
1. `sessions.py`: for a cell marked `pairs_one_port_with_dedicated` (cost, SSH, mixed, two-core
   two-cores), the engine calls the window of the one-port arm only with the freeze guard's
   clearance, which only a frozen run that passed with the pilot entry gets. Without it, in
   development, it writes a stub row (mode one-port, valid false, `stub` true, no binaries,
   nothing started); a frozen run without it raises before the window.
2. `cellwin.py`: the in-process window raises before any process starts when asked for a one-port
   window of such a cell without a clearance that names the pilot entry.
3. Test `NoOnePortAgainstDedicated` (test_frozen.py): with every process start recorded and
   refused, a development session of two cost cells through cost_run's real window function never
   starts a server with `--mode one-port`, every start it attempts is `--mode dedicated`, and
   every one-port window is a stub.
In the end-to-end jobs: the cost cell and section 10's SSH and mixed cells ran their dedicated
arms and stubbed their one-port arms; and no one-port in-process window of the job shares a
protocol and backend with a dedicated window of the job: the dedicated in-process windows ran on
epoll (the pilot's and the cost cell's MQTT, the SSH and mixed cells' dedicated arms), every
one-port in-process window on io_uring (M1 h2c, M2 HTTP/1.1, the reuseport cell, M1's TTFB), and
rule E's detection sessions (one-port HTTP/1.1 in-process) did not run. One-port windows ran
against one-port (M1, M2, the reuseport cell, rule E's relay copy) and against a competitor (M3,
B3, the relay on io_uring), which section 8 step 2 allows before the code freeze; no dedicated
window ran against a competitor (FC5). The dedicated windows timed alone (beside stubs) are
dedicated timing as the A/A exception of the engineering constraints, journaled.

### Tests

- `bench/run/test_frozen.py` (run.test_frozen, 35 checks): each runner's rows written through the
  engine with a stand-in window that sets the real window's fields, assembled by
  `analysis/rows.py` and accepted by `analyse()` or `pilot_entry()` (cost, the cost stubs, the
  pilot and its parts, B3 with the other-mode cells, M1 to M3, section 10's bullets, rule E's
  file); the engine (the order fixed by the seed, resumption across jobs, the rerun cap, a rerun
  after one invalid session, fault rows, a signal's row then a rerun); the guarantee above; the
  freeze guard on a temporary git repository (it passes, and refuses: a short hash, an unlogged or
  incomplete pilot output, a binary outside the gate, a dry-run gate, an uncommitted
  hypotheses.md, a change under bench after CODE_FREEZE, a pilot logged in the CODE_FREEZE commit,
  rule E logged before the pilot entry; and cost_run refuses before any window); rule E's choice
  (each way it can fail), M2_RATE, the slower arm's rate, the pilot's lambda through pilot.py's
  rates(); the hard cases' judge (a pass, B1 failures, B2(a) to (e), the route and TLS); HAProxy's
  splice-auto in `defaults`; a frozen section 10 run without `--silent-ports` refused; on Linux,
  `lab_job.sh` refusing a job at nice 5 and running it with ONEPORT_ALLOW_NICE=1, and
  `priority_state`.
- C++: `gen.hold.{epoll,io_uring}` (above); `gen.binaries` also runs `opcase hold` and `opcase
  case --list`; `server.binary_record.{epoll,io_uring}` checks that the close line reaches the
  record file while the server runs.
- `bench/test_gates.py`: `load_gates` leaves a dry run's gate out by default and binds to it with
  `accept_dry_run`.
- `analysis/`: `test_rule_e_relay_copy_per_backend`. The analysis suite on the pinned numpy
  (2.5.0, in a venv under `~/opt/analysis-numpy-2.5.0` from PyPI's wheel, sha256 checked; L's
  system numpy is 2.5.3, which the command-line tools refuse): 70 passed, 1 skipped (the slow
  Appendix A test); SciPy's cross-check ran with L's SciPy and passed.

### The suite in four builds

`checks_job.sh` (M7 fixes' script, the paths moved to `~/lab/p3/m7c/check/`): Debug and
ASan+UBSan at once, then TSan and MSan at once, each `ninja -j 5` and `ctest -V -j 8`, each
build's integration tests in their own port block. Three times: chk1 at 7f3e41b (the runners'
first commit), chk2 at 81e1216 (the recorder's flush), and chk3 at f8734a2, the last commit that
changes code (every later commit is docs). chk1 and chk2 ran at nice 5 (below); chk3 at nice 0.

| Build | chk1 (7f3e41b) | chk2 (81e1216) | chk3 (f8734a2) |
|---|---|---|---|
| Debug | 0 warnings, 393 of 393, 0 report lines | the same | the same |
| ASan+UBSan | the same | the same | the same |
| TSan | the same | the same | the same |
| MSan | the same | the same | the same |

393 is M7 fixes' 390 and `gen.hold.epoll`, `gen.hold.io_uring` and `run.test_frozen`. As before
M7c, three of the four logs show a thread's exception from `run.test_runner`'s stand-in stub
(`B3Relay.serve_once`), which passed; it matches no report pattern and the test is older than M7c.
chk3's logs (sha256), `~/lab/p3/m7c/check/f8734a2/`: debug build
f8b5a52afa8f873dbd4144dad5173efd9ec6552ceab637dd488a93529aa973cf, ctest
a4318fca10e0c2b2fef0677b46c5e65d13c2371b9f910f3eb6d3dfea2c5ec7d4; asan build
4a5acf96064db54cd040d4b93ec7094fb5856027b2eeba5903d27f27a5fd03cf, ctest
001bb40e54f383b24380c6f397d8d1f78e3b6e95dfb68f54211e2c4e95b07cbc; tsan build
a6ba9df8b2ad6c496c7ff511c1506f6ba3194b2d5247f5190d55585c7a88d18e, ctest
595b99a7d9b3b482b1c26e656f5f13171c15c910607f7641d5a3361c4766fae2; msan build
fa80fe88d38aba2ef804c3e0003ff1b5a81e0511e85e91bea9102080ed7a6389, ctest
7ef0c39f7926fe31a3f70b489afd8298f5106ae815f9161c622e64ee90b37a35. chk2's (81e1216): ctest debug
4c57aa98cf2aceb355a39453557377955fedbfc2e3cea90490391cf39238f499, asan
3be057c5f062e74395f3fa058280f9a41b15dd7c610c08c3542ca968cac48f57, tsan
0c078be7fb574eae8bd52eacbeb2d2c8fbb612df63823f57001b7c3c29e83323, msan
dd5feca0867b382884dfb134c259065cfcd5cf43c25ddb5e3beb2a4b0d0f7780.
Before them, a scratch ASan job (try1, 0b63d62) built the C++ change with 0 warnings and passed
`gen.hold`, `gen.binaries`, the CLI tests and three hard-case entries with 0 report lines.

### The records drivers' dry runs

Two dry runs of the records drivers (`DRY_RUN=1 bench/records_job.sh`, one lab job each, from a
fresh clone; every record named `-dryrun` and marked, never citable, nothing copied anywhere),
each because a first-party input changed: dryrun7 at 7f3e41b (opcase's holder and listing) and
dryrun8 at 81e1216 (the recorder's flush). Every step exited 0 in both:

| Step | dryrun7 (s) | dryrun8 (s) |
|---|---|---|
| release | 37 | 35 |
| oneport ASan+UBSan, TSan (at once) | 156 | 158 |
| oneport MSan | 149 | 148 |
| harness_cmux ASan, TSan | 37, 44 | 37, 45 |
| harness_hyper_util ASan, TSan | 54, 50 | 53, 50 |
| gate | passed, `dry_run` true, `citable` false | the same |

dryrun8's gate binaries (sha256, first 12): oneport 4c64edc25f76 (the recorder's flush), opgen
0c0f3457a34c and ophold 3f405ac29c62 (unchanged since dryrun6), opcase 5fb264f876c9 (the holder
and the listing; dryrun7's too), harness_hyper_util d6e52b94e88c; harness_cmux cfb13c2ae891,
harness_netty 2ebcb736fee7 and harness_jetty 9541acf60827 differ from dryrun7's (f12b041f3f38,
fe9039d2f637, eb9278b80984) with no input of theirs changed: they are not reproduced across build
directories, as the M7 checklist's item 10 already says of the Rust harness, so the frozen runs
must use the records job's own harnesses. Files (sha256), `~/lab/p3/m7c/dryrun8/`: gate-L.json
b919e16267a87ca9cede26e742005af3f715856588a674129cffddd93257b26f, measured-L.json
90a5b3d11106526050777ee7dc5e4c9521486569618508b14047ad9585d93714, records.log
bfcacb78b96232f6fa18b733201ced3866434a2471b7f0e3b965394722d898a3.

### End to end, development mode

`~/lab/p3/m7c/e2e_job.sh SRC BUILD OUT` (sha256
775b89e81a03aa3d5ab750a741fb6a8552a39621262340f09f506cbabbad2f50), one lab job: every runner in
development mode on a tiny configuration (one cell or a few, one session, `--dev-r 1`) on a dry
run's `build-release`, then `devcheck.py`: the rows fed to `analysis/` through its library
functions (`refuse_flags` with development rows allowed, `pilot_entry`, `analyse`; the command
lines refuse development rows and L's numpy), and every row that ran a binary bound to the dry
run's gate (`load_gates(accept_dry_run=True)`; the output says `citable: false`). Development
seeds 7701 to 7714 (one per name of 4.7), 7801 and 7802, journaled, so the seeds entry must not
reuse them.

e2e1 (runner code c5f324f, dryrun7's build) ran every step and found five things:
1. The timer part found no T_hdr line for any run: `--record` was flushed only at the stop.
   Fixed in beed996 (each line written through), with a test.
2. The hard cases' server part never created its raw directory, so every run was a driver fault.
   Fixed in 81e1216.
3. The competitors' rows printed a TLS reply's raw bytes into the log. Fixed in 81e1216.
4. M2's closed-loop rate sessions for TLS on io_uring: in every relay window one of the
   dedicated backend's two cores was 92.6% to 100.4% busy (one worker took the handshakes), so
   section 7's backend rule made all 8 sessions invalid and M2_RATE was not computable for the
   cell (for the coordinator, below).
5. One B3 window was invalid by section 7's TIME-WAIT rule (1 at both samples, 0 at the
   baseline); I had opened ssh sessions to L during the B3 windows, which b3.py's docstring warns
   against; its rerun was valid. e2e2 kept every ssh session out of the job's span.
devcheck: rows accepted, 203 bound, 12 stubs, 0 refused.

e2e2 (runner code and binaries 81e1216, dryrun8's build), every step exit 0:

| Step | s | What ran, development data |
|---|---|---|
| pilot | 70 | C1 and C3 of MQTT on epoll, one A/A session each, all 8 windows valid; lambda for C3 from the C1 session by pilot.py's rates(); timer part 3 runs per backend, all valid, lateness on epoll 15.26 to 15.30 ms, on io_uring 0.25 to 0.39 ms; split part 2 replicates at 5 and 100 ms per backend, all valid, each with 2 receives that returned payload |
| rule_e | 50 | the relay-copy sessions on epoll and io_uring, one each, valid; `decide`: user space on both (fewer than 6 sessions), the detection modes and IOCP's the proposed defaults, each with its note |
| cost | 26 | C1 MQTT on epoll: a session and its rerun, 4 dedicated windows valid, 4 stubs |
| m2rate | 25 | M2 HTTP/1.1 on io_uring, one session valid; M2_RATE written |
| m | 76 | M1 h2c on io_uring, M2 HTTP/1.1 on io_uring at that rate (open loop, WL6 metric), M3 HTTP/1.1 against nginx: one session each, all valid |
| s | 147 | SSH C1 on epoll and the mixed cell on epoll (a session and a rerun each, dedicated arms valid, one-port arms stubs; the mixed cell's background established before every window, 64 silent connections held at every pass, none reopened in dedicated mode, `--silent-ports spread`); the reuseport cell on io_uring, the relay on io_uring against nginx, M1 h2c's TTFB on io_uring at the rate from e2e2's M1 session: one session each, all valid |
| b3 | 285 | one ophold window and one session of B3 silent against nginx on epoll, all valid |
| hard | 13 | HC1, HC12, HC20 and HC21 on epoll replay in-process and io_uring peek relay, 2 replicates: 48 of 48 runs passed B1 and B2; every server's check at the end passed |
| comp | 100 | nginx's cases configuration at matched timers and at its defaults, HC1 and HC6, 3 replicates: 42 runs recorded, 18 with the reply the server's table expects of the server (nginx routes only HTTP/1.1 and TLS) |
| devcheck | 1 | ok: 188 rows, all development; 176 bound to dryrun8's gate (a dry run, not citable), 0 refused; 12 stub rows, each valid false with no binary; the pilot entry made (R_C 31, m_C 0: no cell has P = 16 sessions; GAP_SPLIT not computable without W's rows, as pilot.py says); `analyse()` accepted every family (no cell tested, each with fewer than R sessions); K_BASE not computed (1 of 16 ophold windows) |

Files (sha256), `~/lab/p3/m7c/e2e2/`: devcheck.json
7426df3f8b76384800e0826beb90029810c472c70148f43800e170dda0762c33, e2e2.log
51817e3da53750b80a73995b9d69e7a5bcfcb1691483a5fbbe530850408df112, pilot/windows.jsonl
9e401073f4ab897def4aa887058fe49fba4ea9c1ec75f841312d7d846a78189f, pilot/parts.jsonl
4cf2cfa615e0d5b42f19f0abb75d87b50250fd34b878e7f3073d70d8693ccd6c, cost/windows.jsonl
ea478f5ed2777e092a2342eb58e64001eefc3be5070b44d9daa46c3a4234a08f, m/windows.jsonl
8c057552b905b1001963a7b0f96c8e3cfb355ed696d1b0723eb99b028fa63b7a, s/windows.jsonl
21968a4aa0c6842a85ceca800efd87f97ae1f59b650d2bffbd562f80463e325e, b3/windows.jsonl
b9612080aa7194a98ec514b56d08d30906ce7de673580ebb4835c800460656b1, hard/hardcases.jsonl
c725161dc3d794d994b50acb3b5c573bbbc5c738362d9066c0d8f5306e043c5b, hard/competitor_cases.jsonl
af07a9fb31c7a6788442a9bc7b04b1fab56c983dede5283c40aa447a3a5e7119.

The timer part's 15.3 ms on epoll is explained below ("A lab job's priority"). A development
reading for the coordinator, not a result: in the mixed cell's dedicated arm, with the WL3 background, the cell's HTTP/1.1 churn ran at 17,536 to 17,662
connections per second while the TLS and the MQTT background each completed 443,778 to 448,970
requests over its run; dedicated HTTP/1.1 churn alone on epoll ran at 44,655 to 44,980 in job
aa-floor1 (the revision log's entry "Host clock floor", item 3). So read as WL3's closed loop,
the background takes most of the server's core.

e2e3 (runner code f8734a2, dryrun8's build: no compiled input changed since; launched from bash,
nice 0; `~/lab/p3/m7c/e2e3_job.sh`, sha256
37e9c63eca09d5264a5c4e902ba7c1a6ddbe8481adec7cb8bdb3722509961dc3): what e2e2 exercised least.

| Step | s | What ran, development data |
|---|---|---|
| timer | 19 | the timer part, 3 runs per backend, all valid, the server at nice 0: lateness on epoll 3.26 to 3.31 ms, on io_uring 0.05 to 0.30 ms |
| hard | 91 | all 25 cases (164 variants) on epoll replay in-process and io_uring peek relay, one replicate: 328 of 328 runs passed B1 and B2, every branch of the judge reached (the PROXY source and reason, the TLS flight, 400, the dedicated HTTP/1.1 reply, the SMTP fallback's transcript, HC7 at a G of 100 ms, HC4's drip, HC16, HC22's reset, the header write's anchor); 13 servers checked at the entries' ends, all passed |
| comp | 2 | HAProxy and cmux in "cases" and "cases-fallback" at matched timers and at their defaults, HC1, HC11 and HC21, 3 replicates: 126 runs recorded (HAProxy's PROXY listener 6, the fallback kinds 24), 69 with the reply the server's table expects of the server; every system started and stopped (HAProxy's exit is SIGTERM's) |
| devcheck | 1 | ok: 481 rows, all development, all bound to dryrun8's gate (not citable) |

Files (sha256), `~/lab/p3/m7c/e2e3/`: devcheck.json
e028821f85eb5ffc8d8ea6a8e7205d155d6d737a2ea78997c5e53f1340b3e78c, pilot/parts.jsonl
14dcb556a66ea5cc95485249dd6ada96af8b89159ddfb72c8e3c9407d76a27bf, hard/hardcases.jsonl
4cb6e4b61dad3895bd0e7b87dee535156999323b7ccf5ecd34578590336c564b, hard/competitor_cases.jsonl
2eb91deef5f91d319472824e79bf905e03454d144ce3b69398980ae8a7667390. The server's timer slack could
not be read from its `/proc` entry by the runner (the field is None in the rows); its nice was.

### A lab job's priority (found in M7c, fixed in f8734a2)

e2e2's timer part handled every T_hdr deadline on epoll about 15.3 ms late, e2e3's about 3.3 ms.
The cause: a job launched as `(setsid nohup bash lab_job.sh ... &)` from L's login shell, zsh, runs
at nice 5, since zsh lowers every background job's priority (its BG_NICE option, on by default);
shown on L: the same line from zsh gave a process at nice 5, from bash at nice 0. epoll_pwait2's
timeout takes the kernel's slack from `select_estimate_accuracy` (fs/select.c): 0.1% of the time
left at nice 0 and 0.5% above it, capped at 100 ms, so a 3 s wait may end about 3 ms or about 15
ms after its deadline; io_uring's timeout does not take that slack, which fits its 0.05 to 0.39 ms.
So G_L, "the smallest whole number of milliseconds above the largest lateness" (9.2), would be 16
ms from a pilot at nice 5 and about 4 ms at nice 0, and every process of a job at nice 5 competes
at a lower priority than the host's own. M7c's jobs e2e1, e2e2, dryrun7, dryrun8, chk1, chk2 and
try1 ran at nice 5 (none timed anything that a rule uses); e2e3 and chk3 at nice 0. Earlier
milestones' jobs launched the same way from zsh will have run at nice 5 too; no job recorded its
nice before f8734a2, and all of them are development data. The fix: `lab_job.sh` refuses a job at
any nice but 0 (exit 92, unless ONEPORT_ALLOW_NICE=1) and says how to launch from bash; every
session's fingerprint records the runner's nice and timer slack, and each timer row the server's
nice. The timer part's lateness and G_L are B2's reported distributions and 9.2's G; the
coordinator may want the slack named in the methods.

### Analysis changes

One: `analyse.check_rule_e` takes `relay_copy` as one choice per backend that relays, {"epoll",
"io_uring"} (7364fbb), with a test. Section 8 gives rule E "three choices per backend" and section
2.1 has the relay on Linux only; the contract held one value. Nothing else in `analysis/` reads it.
`design/status-m7a.md`'s line on the rule E file names the old form; this entry supersedes it.

### Readings logged in the revision log (entry "Readings fixed during engineering (M7c)")

1. Rule E's relay copy is chosen per backend that relays; HAProxy's `option splice-auto` follows
   the server's relay copy in the same cell.
2. The pilot's C1 and C2 cells, with their reruns, end before its first C3 session; section 10's SSH
   cells likewise.
3. The timer part's lateness is wait_return - deadline of the T_hdr event, one connection at a time.
4. A split replicate runs against a fresh server, so its counters are its one connection's.
5. "The slower arm's median" and WL6's "the smaller of its two arms' median": each arm's session
   value the mean of its two windows, the median over the valid sessions, the smaller of the two.

### For the coordinator (not logged: each chooses what runs, or is open)

1. The mixed cell's keep-alive background as WL3's closed loop (above); where its silent
   connections go in dedicated mode (`--silent-ports`, no default); its placement.
2. Section 10's B3 cells of the other detection mode name no dispatch: `b3_run.py
   --other-mode-system one-port-relay|one-port-inproc` has no default, and a frozen B3 run refuses
   without it.
3. Section 10's TLS variants cannot run on the frozen binaries: opgen offers only ALPN http/1.1
   and never resumes a session, and the server issues no ticket and keeps no session cache
   (section 2.1's settings, which the frozen text fixes for every TLS endpoint). Running them needs
   generator (and, for resumption, server) changes before CODE_FREEZE, or the 6 cells are reported
   as not run. `s_run.py` lists them as not runnable.
4. Rule E's computation as above (at least 6 valid sessions; strictly higher in every one; the
   operations summed; the relay-copy sessions in M3's arrangement).
5. M2: the relay arm's backend (a server in dedicated mode) runs the cell's backend; the in-process
   arm is the server alone on CPU 14 in the hand-off placement. Found in e2e1: in M2's closed-loop
   rate sessions for TLS on io_uring, one of the backend's two cores was 92.6% to 100.4% busy in
   every relay window (one worker took the handshakes), so section 7's backend rule invalidated
   every relay window and M2_RATE was not computable for that cell from valid sessions as the
   runner reads WL6. HTTP/1.1 on io_uring (e2e2): one session valid in e2e2, both arms (no backend core above 90%), so the rule bites in TLS only so far.
6. The cost family's dedicated arm gets the default detection mode's flag too (it does nothing in
   dedicated mode; section 2.1 names the flags both modes share).
7. Design choices: K_BASE's ophold windows at most 4 beyond 16; the hard cases' runs wait at most
   20 s for a script (HC4's drip and T_dec), one server per listener setup per entry, one reference
   transcript per variant and entry; the competitors' rows say whether the reply equals what the
   server's table expects of the server, descriptively; the development stub sessions are rerun
   like any invalid session.
8. The entries' tokens the frozen runners look for (above, "What a frozen run checks").
9. `runlib.HOST` is L: W's pilot, cost, M1 and section 10 cells need W's runner (M6b), which
   should write the same rows; `window.py` and `cellwin.py` read `/proc`.

### What the freeze still needs

In the M7 checklist's order, after M7c:
1. The coordinator's decisions on M7c's items above (before item 8: the runners are frozen with the
   tests), and `ANALYSIS_COMMIT` after 7364fbb (`analysis/` changed in M7c).
2. The final merge of `m6b-windows` and W's checks: W has built none of M7c's C++ (`hold.cpp`,
   `run_cases.cpp`'s listing, `record.cpp`'s flush, `gen_tests.cpp`, `server_tests.cpp`); W's
   runners (W's pilot and its parts, the cost cells on IOCP, M1 on IOCP, rule E's IOCP detection
   sessions and W's evidence file, section 10's W cells, the IOCP forms, the hard cases on IOCP)
   do not exist and must write the same rows; `runlib.HOST`, `window.py` and `cellwin.py` are L's.
3. The pins, the slab re-read, the seeds entry (avoiding the development seeds above), the values of
   section 9.1, the final `coverage.json`, `CODE_FREEZE`, the records at it and the gates, as the
   checklist says; each entry written with the tokens the runners look for (above); every lab
   job launched at nice 0 (from bash, as `lab_job.sh` now requires).
4. Then, in order: `pilot_run.py` on L (frozen: `--seeds --code-freeze --gate`) and W's pilot;
   `pilot.py` on the pinned numpy; the pilot entry; `rule_e.py run` and W's IOCP sessions, then
   `rule_e.py decide`, logged; `m_run.py --part m2-rate`, logged; `b3_run.py` (K_BASE first);
   then `cost_run.py`, `m_run.py`, `s_run.py`, `hardcase_run.py` (both parts), each family in its
   own order.

## M7c follow-up, 2026-10-04

The coordinator's follow-up of M7c: the merge of `m6b-windows` at 74dc539, the suite on L, the
pushes, M7c's open items settled against the frozen text and logged, `ANALYSIS_COMMIT`. Nothing
here is a result: every window below is development data, journaled as such. Every job on L ran
under `lab_job.sh` at nice 0, launched from bash (`bash -c '(setsid nohup bash ... &)'`), from
fresh clones of the lab remote under `~/lab/p3/m7c/`. The `one-port-m6b` work tree and W were not
used for any build, job or timing; on W (this session's own host) only `run.test_frozen` and
`run.test_wrunner` ran as pure Python, about 10 s, after W's night A/A job had ended (02:31).

### Commits (papers/one-port)

| Commit | Message (first line) |
|---|---|
| fa8be6d | chore: merge m6b-windows at 74dc539 into main |
| 236ee3c | feat(gen): opgen's tls-h2, section 10's TLS variant with ALPN h2 |
| 8e77e28 | feat(run): section 10's ALPN h2 cells, the logged choices of M7c's open items |
| 3623df6 | fix(run): the mixed cell's rows keep each background generator's CPU time (cpus, cpu) in the background report; a test |
| 13004bc | docs: hypotheses.md revision log, M7c's open items, before the code freeze |
| d16d8b4 | docs: hypotheses.md revision log, ANALYSIS_COMMIT = 7364fbb... |

Then this section's update. Papers: 4af4be6 and 3cb0bcd pushed; 2ce46ec bumps `papers/one-port`
to fa8be6d (pushed); ae30f03, e2e4's lab-journal line (development); then a second bump to this
section's commit. `main` went to `origin` at fa8be6d once chk4 had passed, and to `lab` before it
(the fresh clones of the suite come from the lab remote, as in M7c); everything after is pushed
to both with this section.

### The merge (fa8be6d)

`m6b-windows` merged at exactly 74dc539 (the branch's head then; later commits of the branch are
not in). The brief expected a conflict in `bench/server/record.cpp`; there was none: git merged
main's write-through (beed996) and M6b's `_MSC_VER`-only pragma around `fopen` (2b6aed0) on its
own, both kept. Two files conflicted, both kept on both sides:
- `bench/cases/run_cases.cpp`: M6b renamed the JSON helper `quoted` to `json_quoted` (MSVC's
  `std::quoted` won argument-dependent lookup); main had added `variant_line` and the TLS fields
  group, sigalg, verified and resumable with the old name. The merge keeps main's fields and gives
  every use the new name (no `quoted(` call is left).
- `tests/CMakeLists.txt`: main's `run.test_frozen` and M6b's `run.test_wrunner`, both registered.
`bench/build_inputs.py`'s `TARGETS["W"]` and `BINARIES["W"]` hold for the merged tree: no target
was added or removed (M7c's `hold.cpp` is in the `opcase` library, Linux-only by its own guard;
M6b's `worker_win.cpp` is in `opgen_core`).

### The suite in four builds

`~/lab/p3/m7c/checks_job.sh` (M7c's script, sha256
387d87734f8a693dcd248df2931fa88135c1efd2bcff3a4584cc4cc1301988ff), Debug and ASan+UBSan at once,
then TSan and MSan at once; report lines counted with the lab's shared pattern.

| Build | chk4 (fa8be6d, the merge) | chk5 (8e77e28, the follow-up's code) |
|---|---|---|
| Debug | 0 warnings, 394 of 394, 0 report lines | 0 warnings, 398 of 398, 0 report lines |
| ASan+UBSan | the same | the same |
| TSan | the same | the same |
| MSan | the same | the same |

394 is chk3's 393 and `run.test_wrunner` (pure on Linux). 398 adds `gen.churn.tls-h2` and
`gen.tls_h2_one_port` on both backends. As in M7c, logs of `run.test_runner` show a thread's
exception from its stand-in stub, which passed (chk4: four logs; chk5: three); it matches no
report pattern. After
3623df6 and 13004bc, which change only `bench/run/*.py` and docs, the suite's Python tests ran
again from a fresh clone at 13004bc (job py1): `test_frozen` 40 of 40 (on L none skipped),
`test_runner` 63 of 63, `test_wrunner` 19 of 19, `test_gates` and `test_record_writers` passed.
Logs (sha256), `~/lab/p3/m7c/check/`: fa8be6d debug build
fdf88874393f073998dae8bf79dddfb3fe9367ceaef88553f01344c7cc753183, ctest
b404b6a3b5beec1011c6bcc75a24a9a54cd0d8801219ccb7b42f356878b9b511; asan build
68c95dcdb7344f12afcaa77812b6b86c8cb3eb7e34b68c31ee38976ca974c919, ctest
91a121f281af4121c1f47f88299c1194a2c1dff3813e4a4d94905fbd787411dd; tsan build
51567c88f65a5730bb63f0486182d8c62ccde7e080443a2c9859d34ecb0cb6da, ctest
ff77a9497db3ac192a6dce9202a83512f6c4e356b2446950021c0eea6ab66d66; msan build
83ba5a555121d6a6d911944d50b3c0dbf6c13975456127c1c5afb7d1007a70bb, ctest
4a09dabfe08ea1b619b353912b4bfecf62d7e820aea62431448c164dd0258b5b. 8e77e28 debug build
53536889ca9af2a0c37ba4c84394e0287bf5ba7ca90f8d1fe3cfbbcbc8d2c24b, ctest
0bf0180a453ac6a7f3983721a96cd0e47e0196c45ef384c92f83bf06ab5fae88; asan build
3c0db3a5184446c751054a7081b4aa3f7a63b3cb020b45ea78174db9031ac01d, ctest
94bfcf5366c33dd17411f841ec8b2535b1a3305aa8ad9f455eeaa3a246424125; tsan build
c764d16db0c0a0a333cb58dc594e6b2ee0b731c323905358970483d771cd612a, ctest
342b000c0049440af989cb128970a660ef08f725f52b2974da20fc2a65e82f98; msan build
c657fcdf88043f40d155d23ed70dccb46ce613f46ad59130cfaff2858d314600, ctest
b5724e94023de259d0c598d897cd357e60f44774869a3a0f5220cb01ed770455.

### M7c's open items (revision log, entry "M7c's open items, before the code freeze")

Logged as one entry (13004bc), eight items, each labelled; the entry gives every reason in full.
The runners apply items 2 to 6, and a frozen run of the section 10, B3 or M runner refuses to start
without the entry's heading (`freeze_guard.M7C_ITEMS`).

| Item | Label | What | Code |
|---|---|---|---|
| 1 | reading | The mixed cell's TLS and MQTT keep-alive background is WL3 with C = 64 each, a closed loop: WL3 is the text's only keep-alive, 9.1 sizes the background by counts alone, and a fixed rate would need a λ with no rule. Consequence (e2e2): the cell's churn about 17.6k against about 44.7k alone; the background generators 15.5% to 30.1% busy, so the server set the background's rate | unchanged; 3623df6 keeps the generators' CPU in the row |
| 2 | design choice | Silent connections of the dedicated arm on the HTTP/1.1 port: the listener of the measured load, as in one-port mode; spread would add the SSH and SMTP ports' first lines, which the one-port arm never sends a silent connection | `s_run.py` default http1, frozen run refuses spread |
| 3 | reading (silent case: design choice) | B3's other-mode cells in relay: WL7 says the peek side of these cells leaves bytes queued, which in the partial-ClientHello case only pass-through does; in-process the handler reads the bytes at byte 6 in either mode (m5b3b: the same U in replay and peek) | `b3_run.py` default one-port-relay, frozen run refuses in-process |
| 4 | reading | TLS with ALPN h2 runs: 2.1's ALPN http/1.1 is scoped to the cost cells (6.1), which section 10's variants are not; the exchange composed from WL1's TLS and h2c rows | 236ee3c (opgen), 8e77e28 (runner) |
| 5 | reading | TLS with session resumption is not run (3 cells): 2.1 fixes no tickets and no session cache for every endpoint, unscoped, and TLS 1.3 resumes only from a ticket; section 10 decides nothing, so no claim changes | `s_run.py` lists them as not run, with why |
| 6 | reading and design choice | An M2 cell whose rate 9.3 cannot compute has no rate (section 9), so no valid session, p = 1 in Holm (4.1, 4.2), "a difference was not shown" (section 12); the runner starts none of its windows (design choice) | `m_run.py`, `not-run-<job>.json` |
| 7 | design choice (M7c's) | The mixed cell's placement: cell opgen 2 to 9, TLS background 10 and 11, MQTT background and holder 12 and 13 | unchanged |
| 8 | reading | Section 7's generator rule in the mixed cell reads the cell's generator only; the background generators' CPU is recorded | unchanged |

The brief's tokens: the frozen runners find the later entries by a word and a file's sha256
(CODE_FREEZE, the seeds, the pilot, rule E, M2_RATE; M7c, "What a frozen run checks"). This entry
names no file by its sha256, so it can match none of them; the one token a runner looks for in it
is its heading, "M7c's open items, before the code freeze".

### What was implemented (item 4, and the runners' choices)

- `opgen --proto tls-h2` (236ee3c): the full handshake offering ALPN `h2` alone; after it, the
  negotiated protocol must be `h2` or the exchange fails (counted as a TLS failure); then h2c's WL1
  exchange inside TLS (preface, SETTINGS and HEADERS with END_STREAM, read to END_STREAM, GOAWAY),
  close_notify, close. Churn and open loop; keep-alive refused by the parser. Linux and Windows
  share the code (`over_tls()` replaces the TLS-only checks, `worker_win.cpp` included); W has not
  built it.
- Tests: `gen.options` (the protocol, open loop, keep-alive refused); `gen.churn.tls-h2.<backend>`
  and `gen.probe.<backend>` against dedicated mode; `gen.tls_h2_one_port.<backend>` against
  one-port mode (every connection classified TLS, the probe); registered for IOCP too.
- `s_run.py` (8e77e28): the ALPN h2 cells on epoll and io_uring (rows `proto` tls, `variant`
  alpn-h2, opgen's tls-h2 through `cellwin.py`'s `gen_proto`), pairing one-port with dedicated
  mode, so their one-port arms are stubs in development; resumption listed as not run on every
  host; `--silent-ports` defaults to http1 and a frozen run refuses spread.
- `b3_run.py`: `--other-mode-system` defaults to one-port-relay; a frozen run refuses
  one-port-inproc. `m_run.py`: an M2 cell with a null rate is not run, listed in
  `not-run-<job>.json`. `freeze_guard.py`: `check(entries=...)`; the section 10, B3 and M runners
  refuse a frozen run whose revision log lacks the heading "M7c's open items, before the code
  freeze". `window.py`: `stop_on_signals` sets SIGHUP only where it exists, so `run.test_frozen`
  passes on Windows (it failed there on `signal.SIGHUP`, found running it on W; W's suite registers
  it since the merge).
- `test_frozen.py`: 39 checks (35 before): the ALPN h2 cells' rows accepted by `analysis/` and their
  window (the probe and opgen run tls-h2 on the dedicated TLS port, or on the one-port listener
  with a clearance and never without), the resumption cells not run, the silent ports and the
  other-mode system with their frozen refusals, an M2 cell without a rate (not run; `analyse()`
  leaves it untested with 0 sessions), the guard's entry check.

### The records drivers' dry run and the development check

`~/lab/p3/m7c/e2e4_job.sh` (sha256 e55beef8c89466b5c1647627fd733b9493270fb53b11732eed28d683f115cff7),
one lab job at 8e77e28 (opgen and opcase changed): `DRY_RUN=1 bench/records_job.sh` (dryrun9),
then on its `build-release` the section 10 runner in development mode, then `devcheck.py`.

| Step | s | What ran |
|---|---|---|
| dryrun9 | 526 | release 36 s; oneport ASan+UBSan and TSan 156 s; MSan 149 s; cmux ASan 36 s, TSan 45 s; hyper-util ASan 53 s, TSan 50 s; gate passed, `dry_run` true, `citable` false |
| s | 95 | the mixed cell on epoll and the ALPN h2 cells on epoll and io_uring, a session and its rerun each (dev seed 7956, `--dev-r 1`): every one-port window a stub (nothing started), all 12 dedicated windows valid |
| devcheck | 0 | ok: 24 rows; 12 bound to dryrun9's gate (a dry run, not citable), 0 refused; 12 stubs; `analyse()` accepted the rows |

Development readings, not results, dedicated arms only: the mixed cell's churn 17,676.6 to
17,727.8 connections per second, each background 444,894 to 449,500 requests per 10 s run, the 64
silent connections held on the HTTP/1.1 port throughout (closed 0, reopened 0, bytes received 0,
64 connects); TLS with ALPN h2 3,435.6 to 3,463.0 connections per second on epoll and 3,657.8 to
3,684.2 on io_uring, 0 failed exchanges in every warm-up and window. dryrun9's gate binaries
(sha256, first 12): oneport 4c64edc25f76 (byte for byte dryrun8's: the server did not change),
opgen a25faa11e47f (tls-h2), opcase 49cb3c049250 (the merge's `json_quoted` rename in
`run_cases.cpp`), ophold 3f405ac29c62, harness_cmux 8c98565a3247, harness_hyper_util d6e52b94e88c,
harness_jetty 54034332a39d, harness_netty a74b43885186 (the harnesses again differ from dryrun8's
with no input of theirs changed, as M7c found). Files (sha256), `~/lab/p3/m7c/`: dryrun9/gate-L.json
b262681b446bfa2557f6ba17a931aff6efffe5881337d62f29b1ef3de193f931, dryrun9/measured-L.json
2d6bf33259105f869d999296429bd1ab9e63345100b2d4d304da8ec2e8de7c94, dryrun9/records.log
3e3774b1cd482e58c010a06970288c338ab0ad0b8864c46303eff15dd7bd22c8, e2e4/s/windows.jsonl
53c7fce000cc6a24a6f798962d6f86c606ee350f35ba452acb146b6126130321, e2e4/s/not-run-e2e4-s.json
8f1aecbc013f868884935a125ac6170d73a32f40fd5691cbf202e9d0d38cce8b, e2e4/devcheck.json
98bcb18a88bebe00f45d4b116697e94d27eae2f24961f6283d1f5c8531c5251b. No one-port window ran against
dedicated mode, and no window against a competitor. Lab journal: one line (Papers ae30f03).

### ANALYSIS_COMMIT

Logged (d16d8b4): `ANALYSIS_COMMIT` = 7364fbbbf356e22bb0d6a74b0b9bc29b62c3534b, the last
commit that changed `analysis/`; nothing in `analysis/` was left to change (the rows of every
cell this follow-up touched are forms it reads, `test_frozen.py`). The tests, from fresh clones on
L, in `~/opt/analysis-numpy-2.5.0/venv` (numpy 2.5.0, Python 3.14.7):
`~/lab/p3/m7c/ana_job.sh` (sha256 10890a8f1c40951c498d32b8b18d52f964d3985bbf66f618a6f3cc5271e662d2,
job ana1) at 7364fbb and at 8e77e28: 70 passed, 1 skipped each (logs
75a2c66cf2b7f3ee087cd3e1e22a152a462b4ec0c86fe36e4eae5704c6ad4193 and
9b6ef09d75e9d27df497d040826220c177539f95195ff1f5f02d54922824032a); the skipped Appendix A test
alone with `ONEPORT_SLOW=1` (`ana_slow_job.sh`, sha256
8d43d0c1efd6d9b3ad2217f8b0f38eb887b5f1ecd57b24a21a9db4df0aa2b178, job ana2) at 7364fbb: 2 passed
in 119 s (log af3b9364d090f9ae9e8b7b06f113062f4ddbf1e0cbc77b27562f52d0914906de). The seeds entry
was not written (the brief).

### For the coordinator

1. M2's TLS cells. If the frozen rate sessions behave as e2e1's, both enter Holm with p = 1 and
   M2's claim narrows to HTTP/1.1 (item 6). e2e1's rows show the cause: the backend (dedicated
   mode, two workers on CPUs 10 and 12) shares one listener, and in 15 of 16 relay windows one
   worker took nearly every connection (core 12 92.6% to 100.4%, core 10 at most 7.6%); in the
   one window where both took a share (41.2% and 59.2%) the window was valid at the same rate.
   The frozen text fixes the backend's cores (4.1) and one worker per core (2.1), not its
   listener; dedicated mode already accepts `--listener reuseport` on epoll and io_uring. A
   backend in an SO_REUSEPORT group might keep each core under 90% and make the rate computable.
   That is a design choice for the coordinator before CODE_FREEZE (`handoff.py`'s backend
   command, then development rate sessions to check it); it was not made here. M2's TLS cell on
   epoll has not run rate sessions.
2. Resumption (item 5) is a reading against the proposal's intent (I24: "Session resumption is a
   secondary cell"), not against the frozen text; 3 secondary cells are reported as not run.
   Alex may want to know.
3. W: the ALPN h2 IOCP cell and every W cell need W's runner. W has built none of M7c's C++, of
   the merge, or of 236ee3c (`worker_win.cpp` changed; `gen.churn.tls-h2.IOCP` and
   `gen.tls_h2_one_port.IOCP` are registered), and `run.test_frozen` is now in W's suite (it
   passed on W as pure Python after 8e77e28's SIGHUP fix; the other agent's work tree was not
   touched). `m6b-windows` is merged at 74dc539 only; later commits of the branch need another
   merge before CODE_FREEZE.
4. M7c's "For the coordinator" items 4 (rule E's computation), 6 (the cost family's dedicated arm
   gets the detection flag), 7 (M7c's design choices: K_BASE's 4 extra windows, the hard cases'
   20 s wait, one server per listener setup, the competitors' rows, stub sessions rerun) and 9
   (`runlib.HOST` is L) were not in this follow-up's brief and are not logged.
5. Development seeds used so far, which the seeds entry must avoid: 7701 to 7714, 7801, 7802
   (M7c), 7951 to 7964 (e2e4), 861 and 20261003 (W, M6b).

### What the freeze still needs

In the M7 checklist's order:
1. The coordinator's answer to item 1 above (or none), and to M7c's unlogged items 4, 6, 7 and 9;
   any change lands before item 8, since the runners are frozen with the tests.
2. W's half of checklist item 2: Debug and MSVC ASan of the merged tree, the whole suite, with
   Alex's yes when W is free (W has built neither M7c's C++ nor 236ee3c); any later
   `m6b-windows` commits merged first. W's runners (W's pilot and its parts, the cost cells on
   IOCP, M1 on IOCP, rule E's IOCP evidence, section 10's W cells including ALPN h2 on IOCP, the
   IOCP forms, the hard cases on IOCP) do not exist and must write the same rows.
3. The pins re-read (item 3), the slab re-read (item 4), the seeds entry (item 5, avoiding the
   development seeds above), the values of section 9.1 (item 6), the final `coverage.json` (item
   7), `CODE_FREEZE` (item 8), the records at it on L and W (item 9), the gates (item 10) and the
   code freeze's entry (item 11), each entry with the tokens the runners look for; every lab job
   at nice 0.

## M7d, 2026-10-04: the pre-freeze items on L

The M7 checklist's items that need L only, before the code freeze: M2's backend listener, M7c's
open items 4, 6, 7 and 9, the pins re-read, the slab re-read, section 9.1's values, the final
`bench/coverage.json`, and the seeds entry. CODE_FREEZE is not declared. Nothing here is a result:
the one timed job (m2l) is development data, journaled as such. Every job on L ran under
`lab_job.sh` at nice 0, launched from bash, from fresh clones of the lab remote under
`~/lab/p3/m7d/`; the reads (pins, slab, scans, the draw) ran under the lab lock. The
`one-port-m6b` work tree was not touched, and W (this session's host) ran no build, job or
timing: git, editing, and two short read-only Python scans of the lab journal's seeds.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| 64f4c98 | feat(run): M2's dedicated backend takes a listener layout (shared or a SO_REUSEPORT group); --dev-backend-listener for a development comparison (the rule of the choice in its message, before the comparison ran) |
| 1bc1e53 | feat(run): M2's dedicated backend runs its two workers in a SO_REUSEPORT group; a frozen M run checks the M7d entry; a test |
| 9d7aa15 | docs: hypotheses.md revision log, the pre-freeze items on L (M7d) |
| 8057e52 | chore: coverage.json drops the declared gap "OpenSSL under TSan"; build_deps.sh's comment on the UBSan ignorelist |
| 45d8b03 | docs: hypotheses.md revision log, the seeds of section 4.7 (M7d): the procedure, written before the draw |
| 2e6b539 | docs: hypotheses.md revision log, the seeds: the draw on L and its values; design/seeds.json |

Then this section's commit. Papers: 7a838e6, the lab journal's 2 lines for job m2l (development),
then the bump of `papers/one-port`.

### 1. M2's backend listener (revision log, entry "The pre-freeze items on L (M7d)", item 1)

What the frozen text says: section 4.1 puts the hand-off backend on CPUs 10 and 12, section 2.1
runs one worker per server core, and 5.3 gives M2's relay arm "a backend that terminates" TLS.
No line names the backend's listener. The Words give dedicated mode "one listening socket per
protocol", but section 10 calls the `SO_REUSEPORT` group "one-port mode", whose Words are "one
listening TCP socket per process", so the text counts a group on one port as that port's
listening socket. Section 11's "two workers on the shared listener" is the TSan suite's setting.
So the choice is open (a reading, logged with the choice).

Which cells use which backend (`handoff.start_stub`):
- the dedicated-mode backend, two workers: M2's relay arm only, in both parts of the M runner;
- the stub, two workers: M3, B3's relay systems, section 10's relay cells on io_uring, rule E's
  relay-copy sessions, perfrec and systrace; fixed by the M4a entry, item 8, and unchanged;
- the hard cases' relay backend: one worker (`hardcase_run.py`, no `--workers`), so no layout.
So the choice touches no competitor's cell. The stub's balance in earlier development rows (e2e1's and
e2e2's M3 against nginx and relay on io_uring against nginx, e2e2's rule E relay copy): its two
cores were 1.6% to 38.8% busy, uneven but far below section 7's 90%; an observation only.

The rule, fixed in 64f4c98's message before the job: adopt the group if the text leaves the
listener open and the group balances the backend's two workers; report validity and the
closed-loop rate beside it; never read WL6's CPU per connection (M2's metric).

Job m2l (`~/lab/p3/m7d/m2l_job.sh`, sha256
57e73a538b27414ec604fee5f75b86f8dcb844565cbd6c4bcbf9ba2b72157b1c; one-port 64f4c98 on dryrun9's
`build-release`, oneport 4c64edc2 and opgen a25faa11, the dry-run gate's): the m2-rate part, the
four M2 cells of L, 6 sessions each with the runner's reruns (at most 2), 112 windows per layout,
first the shared listener (dev seed 8101), then the group (dev seed 8102). Both arms are one-port
fronts (in-process against relay), so no one-port window against dedicated mode and no window
against a competitor. devcheck: 224 rows bound to dryrun9's gate (a dry run, not citable), 0
refused. Summary (`m2l_summary.py`, sha256
14974de01d4dec13784fb9934e233e2373a8e6a9f79e7affe2b62f54426cf64e; output
5276f87e7e6f8e9235bb5993f1bd16bf314c02ddf377688b9c6572058e90afd0), relay windows only for the
backend; "share" is core 10's share of the two backend cores' busy time:

| Cell | Layout | Valid sessions | Share | Busier backend core | Relay arm, conn/s | In-process arm, conn/s |
|---|---|---|---|---|---|---|
| HTTP/1.1, epoll | shared | 6 of 6 | 0.009 to 0.626 | at most 43.0% | 13,627.6 to 13,753.2 | 43,834.2 to 44,211.6 |
| HTTP/1.1, epoll | group | 6 of 6 | 0.487 to 0.509 | at most 24.4% | 13,759.6 to 13,836.6 | 44,139.1 to 44,413.3 |
| HTTP/1.1, io_uring | shared | 6 of 6 | 0.217 to 0.763 | at most 29.6% | 14,842.2 to 14,994.8 | 51,652.6 to 52,325.2 |
| HTTP/1.1, io_uring | group | 6 of 6 | 0.486 to 0.512 | at most 22.4% | 14,809.4 to 14,935.6 | 51,845.3 to 52,366.4 |
| TLS, epoll | shared | 0 of 8 | 0.401 to 0.501 | 99.2% to 99.8% | 6,330.9 to 7,628.9 | 3,817.0 to 3,855.8 |
| TLS, epoll | group | 0 of 8 | 0.492 to 0.499 | 99.0% to 100.0% | 7,448.7 to 7,558.1 | 3,827.2 to 3,866.6 |
| TLS, io_uring | shared | 0 of 8 | 0.000 to 0.010 | 99.4% to 100.4% | 3,926.0 to 3,974.7 | 3,902.8 to 3,940.6 |
| TLS, io_uring | group | 0 of 8 | 0.493 to 0.500 | 99.2% to 100.0% | 7,640.5 to 7,739.3 | 3,900.0 to 3,952.8 |

In the HTTP/1.1 cells the relay arm is front-bound (the front 99.6% to 100.2% busy) and slower
than the in-process arm, so it sets M2_RATE (development values: 6,840.8 and 7,447.1 with the
shared listener, 6,900.5 and 7,434.2 with the group, epoll and io_uring). In the TLS cells every
relay window was invalid by section 7's backend rule under both layouts (with the group both
cores 96.8% to 100.0% busy), every in-process window was valid, and no session was valid, so
`m2_rates.json` has no rate for either TLS cell under either layout.

Decision: the group balances the workers, so it is adopted (1bc1e53), labelled a design choice:
`m_run.M2_BACKEND_LISTENER = "reuseport"` in both parts; `--dev-backend-listener` stays for
development comparisons and a frozen run refuses it; a frozen M run, in either part, refuses to
start unless the revision log holds the entry "The pre-freeze items on L (M7d), before the code
freeze" (`freeze_guard.M7D_ITEMS`); rows name `backend_listener` and the backend's command. Test:
`test_m2_backend_listener` (test_frozen.py, now 41 checks): the M2 cells carry the group in both
parts and M3's the stub with the shared listener, the window hands the layout to the backend,
`start_stub` refuses the group for the stub and any other layout, and both frozen parts refuse
`--dev-backend-listener`. From a fresh clone at 1bc1e53 on L: test_frozen 41 of 41, test_runner
63 of 63.

### 2. M7c's open items 4, 6, 7 and 9 (same entry, items 2 to 5)

| M7c item | Label | Settled as |
|---|---|---|
| 4, rule E's computation | reading | "favours" is strictly above in every one of at least 6 valid sessions (a tie counts against, as in 4.2); at most 2 reruns (⌈6/4⌉); "its operations per connection" the sum over section 2.1's kinds per accepted connection, averaged over the arm's valid windows, an equal sum not higher; detection in the in-process placement, the relay copy in the hand-off placement |
| 6, the detection flag in dedicated mode | design choice | both arms get rule E's default; inert in dedicated mode (`Worker::peeks` reads it only for a listener that detects, and no dedicated listener detects); keeps the cost and pilot command lines equal but for mode and port (5.1 "same binary", 4.6 "same binary and flags") |
| 7, M7c's design choices | each labelled | (a) K_BASE's 4 extra windows: reading with a design choice, no B3 decision depends on K_BASE; (b) the 20 s script wait (`SERVER_WAIT_MS`), (c) one server per listener setup per entry, (d) one reference transcript per variant and entry, (f) stub sessions rerun (development only): design choices; (e) the competitors' rows' field: reading of section 10's descriptive table |
| 9, `runlib.HOST` is L | neither | a statement of what the L runners cover; W's runner is the open half of checklist item 2 |

### 3. Pins, slab, section 9.1's values, coverage.json (same entry, items 6 to 9)

Files on L, `~/lab/p3/m7d/` (sha256): `pins_read.sh` 9cddd1dde42efe5daf13fddbb48ecae125b7216198d78c241baa83259e155c73,
its log 07a6739109270e4b919ec3802119d23a5158dc9f609ebd69ac72221a47560fa8; `pins_read2.sh`
7a53ec0a41499a89b075414ed9c6472802ba3cfdc4839493967445a911ea5d92, its log
f0baa971d8a85a2ec769ec0dd0f03ef94c4cdc3661789818daa60a0fce1e68c1; `slab_read.sh`
9a2d4e95113212ecbb93c3c900de9fb3928664a7510bfc635c80f41666af7acc, its log
cd73e15c2e1bbf8106cef142a4da5c44914c19a7347590850c5c6f2d584f2dcf; `ksrc_scan2.py`
64ecf61529077b98499b6806a08575b75fe4684bd7a4ad124567fd4b8b557577, its log
577efee64acc804c3a007a61d71267a52afae47c1ba083ddbef203acf7b346f4; `ossl_check.sh`
72701e05c1a91ecd0516044d7329c73a07b05b855c5093afc46171d83133256a, its log
8da18fb0a4be326e3cdc3b36b5aa6faa4580d1e15cb6e1bd1d7cad9b495ed142; `rustpkg.log`
97218de79b6bfc0c50c9e9c0d217a77f886d53ab55f579ae0bf4bd7e5942828b. (A first scan, `ksrc_scan.py`,
matched every key holding "connect", counts of connects included; its second pass reads only the
keys that record a failed connect.)

- Pins (read 2026-10-04 04:48 and 04:49 +0300): no pin changes. Every pinned version is still the
  latest of its line (OpenSSL 3.5.9, nghttp2 v1.70.0, nginx stable 1.30.5, HAProxy 3.4.6, Envoy
  1.39.2, xcaddy 0.4.7, caddy-l4 v0.1.2 at 42db5690 and master's head, sslh v2.3.1, Netty
  4.2.18.Final, Jetty 12.1.13, cmux v0.1.5, hyper-util 0.1.21); Temurin 25's latest GA build is
  still 25.0.4.1+1 (25.0.5 not published), so the checklist's rule stands: read again on the
  freeze day. Two readings logged: Caddy v2.11.6 and v2.11.7 do not move caddy-l4's pin (Caddy's
  version is the one caddy-l4 v0.1.2's go.mod requires, and the text named v2.11.4 a day after
  v2.11.6 came out); Rust 1.99.0 does not move the toolchain's pin (section 9.1 has no "latest"
  rule for it). No competitor's configuration changed.
- Slab (read 04:50 +0300, as root, read only): as WL7 and the 12:11 re-read of 2026-10-03.
- Section 9.1's values for the code freeze's entry: `K_SRC` 16 (no failed connect in 3,528 rows of
  129 row files since the M3 entry), `N_ACCEPTEX` 64, `RELAY_BUF` 4096, `N_BG_*` 64, ℓ 206.
- coverage.json: "OpenSSL under TSan" removed (8057e52) after the revision log recorded that
  OpenSSL ran under TSan (954 object files of the tsan flavour's `libcrypto.a` and 90 of its
  `libssl.a` call `__tsan_func_entry`; chk5's TSan build linked them and passed 398 of 398). Every
  other gap read true; the Windows gap waits for W's build of the merged tree.

### 4. The seeds entry (revision log, "The seeds of section 4.7 (M7d), before the code freeze")

The procedure was committed (45d8b03) before the draw; the draw ran once on L at 05:29:12 +0300
(`seeds/draw_seeds.py` 4d0e205f4c361e029428e3faf950de2e7597d21e4264e045af6f97af30ed82aa, its log
84412a89fb561959b55285af0b4fbd8fe026cfa2972174b503265f2c2f38e1a5): `secrets.randbits(32)` per name
in 4.7's order, excluding every integer of the Papers journal at 7a838e6 and of one-port's four
status files at 45d8b03 (5,634 integers with the named development seeds); each first call was
kept. `design/seeds.json` (2e6b539), sha256
3a2dd43623aa96190b5b3fac737d96af5a8fabed9853a82233c3a3c9f4c35b3e, equal byte for byte to the
draw's file. Checked on L from a fresh clone at 2e6b539: `runlib.load_seeds` and
`analysis/cells.check_seeds` accept it (14 names), `freeze_guard.lines_with` finds its sha256 on
exactly one revision-log line with "seed", and `check_entries` finds both entry headings the M
runner needs. No run uses these seeds before CODE_FREEZE.

### The suite in four builds

`~/lab/p3/m7d/checks_job.sh` (M7c's script, the paths moved to `~/lab/p3/m7d/check/`; sha256
68d4fbf1c5723bbf77230cc8df52385b38d04457408c31832f7135c8a2e2f24f), job chk6 at 2e6b539, which holds
M7d's three commits that change code or the suite's inputs (64f4c98, 1bc1e53, 8057e52): Debug,
ASan+UBSan, TSan and MSan each built with 0 warnings and passed 398 of 398 tests with 0 report
lines. 398 is chk5's count: `run.test_frozen` is one test, now of 41 checks (41 of 41 in every
build). As before, three logs (ASan+UBSan, TSan, MSan) show a thread's exception from
`run.test_runner`'s stand-in stub, which passed; it matches no report pattern. Logs (sha256),
`~/lab/p3/m7d/check/2e6b539/`: debug build
05a3ddf92e3d40c41223ef0fac0b7359bce4b02ff20aeebd4ded7d5b7277bf96, ctest
f50487127cb3edbe55b8ba62572f0437c310b57f705c8e3fc45174fde650fd14; asan build
4f810344ad570cce5c691b4a694caa33f7d999b76585df2b62a847c6e721993a, ctest
72cf542aab430bc6d4c9c5cdd8de93ba7b64dd44988d5228c53398c0e0b7ca4b; tsan build
3f62f0320d6e7799e45d6a881063377aa7d615a75fb8f74ec2204b4d7e2540cc, ctest
3034a5961b85d871b63ef227241777d18997619d39c8c7d0fb513251d4f0d2a6; msan build
7a0daa0216982ba486a35b25e178aa89ad92f13317a370208e243dd4b9f62fd6, ctest
d98706c79dab0ace1def253af063b734c35e94a8016d0a277847c508d0f94044.

### For the coordinator and Alex

1. M2's TLS cells. The listener was not the cause: with the backend balanced, both of its cores
   are 96.8% to 100.0% busy in every closed-loop relay window, because the backend that
   terminates TLS is the relay arm's limit (the relay arm then runs about twice the in-process
   arm's rate). So under section 7's backend rule no TLS rate session is valid on either backend,
   `M2_RATE` cannot be computed by 9.3's rule as read (M7c's reading 5: valid sessions), and the
   follow-up's item 6 applies to both TLS cells: not run, p = 1, M2's claim narrows to HTTP/1.1.
   Changing that needs a decision on how the rate sessions apply section 7 (for example, whether
   WL6's "the smaller of its two arms' median" may take the in-process arm's valid windows when
   every relay window is invalid only by the backend rule). It changes what M2 can claim, so it
   was not decided here.
2. The Caddy reading (revision log, M7d item 6 (a)) keeps caddy-l4 on Caddy v2.11.4. The other
   reading would move Caddy to v2.11.7 under section 2.3's rule; v2.11.6's notes list breaking
   changes from security hardening (default idle read and write timeouts among them), and whether
   any reaches the layer4 app was not established, so that reading would need caddy-l4 rebuilt
   and its probes, route checks and B3 feasibility run again.
3. Proposal I4 says the `SO_REUSEPORT` layout "is measured only in the secondary 2-core cells".
   That sentence is not in the frozen text, and M2's relay arm now measures its backend's CPU in
   a group (M7d item 1), as M7c's item 5 flagged I24.
4. L: Arch's `rust` is now 1:1.99.0-1. A `pacman -Syu` on L before the records would replace the
   pinned 1:1.98.1-1 (its package is still in pacman's cache).
5. Development seeds used in M7d: 8101 and 8102 (job m2l), excluded from the drawn seeds.

### What the freeze still needs

In the M7 checklist's order:
1. The coordinator's answer on M2's TLS cells (item 1 above), or none: then they stay not run.
2. W's half of checklist item 2: any later `m6b-windows` commits merged; Debug and MSVC ASan of
   the merged tree with the whole suite (W has built none of M7c's C++, of the merge or of
   236ee3c), with Alex's yes when W is free; W's runners, writing the same rows; the Windows
   coverage gap settled by that build.
3. On the day of the freeze, before its commit: the pins read again (the JDK first: 25.0.5, if
   published by then, is pinned by the checklist's rule, with the Java harnesses rebuilt, their
   probes and route checks, and the heap bounds; Netty's allocator read again with it), every
   change logged.
4. `CODE_FREEZE` (item 8), the records at it on L and W (item 9), the gates (item 10), and the code
   freeze's entry (item 11) naming section 9.1's values as M7d item 8 lists them, the slab as
   M7d item 7 read it (or a re-read that day), and the pins as frozen.
5. Then the pilot on L and W with `design/seeds.json`, and the rest in section 8's order.

## M7e, 2026-10-04: W's frozen-row runners and the job's warm-up

The last engineering before CODE_FREEZE: the analysis ingestion check for W's rows, a job-level
warm-up in the session engine, the coordinator's two decisions on W, and W's frozen-row runners on
the shared engine. Nothing here is a result. No window ran on any host: W (Alex's, in use) ran no
job, no functional check and no timing; on W this session ran git, file edits, read-only reads of
waa2's and waa3's rows and of W's excluded port ranges (`netsh`), the pure Python tests, and one
Windows compile check (below). Every job on L ran under `lab_job.sh` at nice 0, launched from bash,
from fresh clones of the lab remote under `~/lab/p3/m7e/`. The `one-port-m6b` work tree was not
used.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| 141e516 | fix(analysis): W's WL4 is its cycles per exchange; the cost cells outside the family never set R_C |
| 9de26d6 | style(analysis): cells.py with LF line endings again |
| ed15f97 | feat: W's frozen-row runners, opcase case and hold on Windows, the job's warm-up phase (M7e) |
| 2055e63 | docs: hypotheses.md revision log, ANALYSIS_COMMIT moved (M7e) and the job's warm-up and W's runners (M7e) |

Then this section's commit. Papers: the bump of `papers/one-port`.

### 1. The analysis ingestion check (revision log, entry "ANALYSIS_COMMIT moved (M7e), before the code freeze")

(a) At 7364fbb `analysis/rows.py` read WL4's CPU per exchange from `cpu_us_per_exchange` for
every row, and `analysis/cells.py` named no CPU field by host. W's rows fill that field from
`GetProcessTimes`, the tick-based value the entry "W before the code freeze" (item 4) sets aside,
so section 10's CPU intervals of W's cost cells and of M1's IOCP cells would have been taken on
it. Changed: `cells.CPU_FIELD` = {L: `cpu_us_per_exchange`, W: `cycles_per_exchange`};
`rows.window_value(row, "cpu")` reads the field of the row's host (W: backend IOCP or host W); a W
row without cycles has no CPU value. L's rows read as before. `analysis/synth.py`'s W rows carry
cycles.

(b) `analysis/pilot.py` computed R_C over a list in the code, 6.1's 36 cells
(`cells.cost_cells()`): every cell with P = 16 valid sessions was simulated and, at a power of at
least 0.80 at 31, resolved, so W's churn h2c and churn MQTT, which run in the pilot, could have
been resolved and could have driven R_C and m_C. Changed: `cells.COST_OUTSIDE_FAMILY` holds the
two cells with the reason (the entry "W before the code freeze", item 1); `pilot.decide` never
resolves them (it still simulates them: 9.2 records Power_c(R) for every cost cell); the pilot
entry's output names them (`outside_family`); `analyse.check_pilot` refuses a pilot entry that
resolves one; their verdict is the reason. WL2's λ for C3 h2c and MQTT on W still comes from their
C1 pilot sessions.

`ANALYSIS_COMMIT` = 9de26d614c85b606fb5169ed16528b7189a87ac4 (logged in 2055e63). 141e516 wrote
`analysis/cells.py` with CRLF line endings; 9de26d6 gives the file its LF endings back and changes
no other byte, so against 7364fbb the diff of `analysis/` is the change alone (7 files, 137 lines
added, 15 removed). Tests, from fresh clones on L, numpy 2.5.0 and Python 3.14.7 in
`~/opt/analysis-numpy-2.5.0/venv` (`~/lab/p3/m7e/ana_job.sh`, sha256
46cab7b799ae8aff72cdbaca6da3b706e9b7d6a79c065464f4ddfc2f7857f5f1; the suite, then the slow
Appendix A test alone with `ONEPORT_SLOW=1`):

| Job | Commit | Suite | Slow test | Logs (sha256) |
|---|---|---|---|---|
| ana1 | 141e516 | 73 passed, 1 skipped | 2 passed (115 s) | b5ce60ba2ff954a74b378257db6ffa754b4928092189fe9d135f361690260df2, 33b42a857b5e6d0e33f703d181eec423752a1f8b679d9c0edf23c50536d63e79 |
| ana2 | 9de26d6 | 73 passed, 1 skipped | 2 passed (119 s) | febf4f9a5b47fff2d0e6c720899b6aeb2476e2de2489b5d5f0e4b59ab7a61b83, 310aafa7ab79e0aa2d0cacff16d6c14e7ecae89cdbdc45577adfbfba48961abc |

73 is 70 and three new tests (a W row's CPU is its cycles, never its ticks; the two cells are
never resolved and leave R_C unchanged; a pilot entry resolving one is refused); three earlier
tests now check the change too. On W (numpy 2.5.0, Python 3.14.5): 72 passed, 2 skipped.

### 2. The job's warm-up (same session's entry "The job's warm-up and W's runners (M7e)", item 1)

The evidence, from waa2's and waa3's rows (read only, `C:\Users\alext\lab\p3\w-aa\`), each window's
metric over its cell's median in the job:

| Job | The slow windows | Their ratio to the cell's median | The next window | The cell's later windows | Span |
|---|---|---|---|---|---|
| waa2 (seed 861) | keep-alive h2c, s02, positions 0 to 2 (00:25:19 to 00:25:31) | 0.931, 0.917, 0.935 | s02 position 3, 0.987; then churn TLS (another cell), 0.999 | 0.984 to 1.030 | 18.5 s |
| waa3 (seed 7901) | keep-alive h2c, s04 positions 0 to 3, s06 position 0 (12:04:27 to 12:04:58) | 0.940, 0.936, 0.918, 0.923, 0.688 (cycles per request 1.063 to 1.175 of the median) | s06 position 1, 1.045 | 0.989 to 1.047 | 37.7 s |

Span: from the first window's warm-up start to the end of the last slow window's measured period,
by opgen's clock in the rows. In both jobs the same cell's later sessions were not slow, so the
slowness was the job's, not the cell's or a session's; in waa3 it crossed a session boundary. In
both, the job's first cell was keep-alive h2c and no other cell ran inside the slow span, so
whether it crosses a cell boundary was not observed (not refuted either). The cause is not
established.

The phase (`bench/run/sessions.py`, `Engine.warm_up`), a design choice: before the first session
a job runs, windows of that session's cell, arms X then Y alternating, back to back, by the
runner's own window function, until `JOB_WARMUP_S` = 80 s of wall time have passed (the window
running then completes). Rule: at least twice the longest slow start seen (37.7 s), rounded up to
a whole 10 s. No row, no metric; its record `warmup-<runner>-<job>.json` (start, end, cell, arms,
each window's start, length and fault, the phase's own fingerprint); the first session's
fingerprint is read after it. The plan is untouched. It goes through the stub check, so a
development cost job warms up on its dedicated arm only. Two driver faults in a row end it; a
resumed job with nothing left runs none; a signal ends it with its record. Every engine runner,
L's too (symmetry), takes it; L's frozen runners now also check the M7e entry's heading
(`freeze_guard.M7E_ITEMS`). Not covered: `b3_run.py`'s K_BASE windows, the pilot's timer and
split parts, the hard cases (outside the engine). Tests (`test_frozen.py`, class `JobWarmUp`, 7
checks): before the first session and no row; the order and rows unchanged; never a stub; two
faults; a resumed job; a signal; the runners never set the length. A job is about 80 s to 120 s
longer on W (keep-alive windows are 6.3 s; a churn or open-loop window waits up to 30 s for W's
TIME-WAIT table first).

### 3. The decisions and choices logged (same entry, items 2 to 6)

| Item | Label | What |
|---|---|---|
| 2 | the coordinator's decision | W's churn h2c and MQTT in the dedicated-only pilot only, not in the confirmatory cost runs; the evidence from the pilot's rows: `server_cores_busy`, `gen_cpus_busy_pct`, `opgen.cpu.pct`, and now `cpu_shares` (server CPU busy, the server process's share from its cycles, generator CPUs busy, opgen's share) |
| 3 | the coordinator's decision | the 2-core IOCP cell not run in P3 (one IOCP worker; multi-worker IOCP is a new threading model days before the freeze; it belongs to the portable I/O core paper); both section 10 runners list it as not run |
| 4 | design choice | the mixed cell on W: cell opgen CPUs 2 to 5, TLS background 6 and 7, MQTT background and holder 8 and 9 |
| 5 | reading, with a design choice | the IOCP forms: both arms one-port, in-process, listener without a fallback, rule E's detection mode; arm A the form (AcceptEx with a buffer; the posted receive), arm B the default; workload C1's HTTP/1.1 churn (the design choice) |
| 6 | record | opcase on Windows (case, hold), the holder on Winsock, the judge's IOCP bound, the W job's context and ports |

### 4. W's frozen-row runners (`bench/run/w*.py`)

Each is L's runner on the shared engine with host "W": the same cells (L's cell builders now take
a host: `pilot_run.pilot_cells`, `cost_run.cost_cells`, `m_run.m_cells`, `s_run.s_cells`), the same
order and rerun rules, the same rows. What differs: the window (`wcellwin.py`, W's in-process window
in either mode, mirroring `cellwin.py`; the pilot keeps `wwindow.run_window`, dedicated only), the
fingerprint (`wwindow.fingerprint`, with the cycle rate), the provenance (`wrunlib.job_provenance`:
`build_inputs.py --host W`, W's binaries oneport.exe, opgen.exe, opcase.exe), the stop
(`waa.stop_on_signals`, `wsys.watch_stop`: `wjob.py stop` ends the runner through SystemExit).

| Runner | What it runs | Seed | Rows |
|---|---|---|---|
| `wpilot_run.py` | 8 step 4 on W: W's 12 cost cells A/A (churn h2c and MQTT included), C1 and C2 then C3 at pilot.py's λ; the timer part on IOCP (128 runs of HC12, PROXY on, `--record`); the split part (16 replicates at 5, 10, 20, 50, 100 ms), both by `pilot_run`'s code with W's process functions (`PartProcs`) | SEED_PILOT_W | windows.jsonl, parts.jsonl |
| `wcost_run.py` | 5.1 on W: 10 cost cells at R_C, one-port against dedicated; churn h2c and MQTT listed in `not-run-<job>.json` | SEED_ORDER_C_W | family C |
| `wm_run.py` | M1 on IOCP (HTTP/1.1, h2c), R_M = 16 | SEED_ORDER_M_W | family M1 |
| `wrule_e.py` | rule E's IOCP detection sessions (6, replay against peek, one-port in-process), `rule_e_evidence_W.json` for `rule_e.py decide --evidence-w` | a development seed | family rule-e |
| `ws_run.py` | section 10 on W: SSH C1 to C3, the mixed cell, TLS with ALPN h2, the two IOCP forms, M1's TTFB on IOCP (from W's M rows); the 2-core IOCP cell and resumption listed as not run | SEED_ORDER_S_W | family S |
| `whardcase_run.py` | B1 and B2 on IOCP, replay and peek, in-process (2 entries), 25 cases, 16 replicates, G_W and GAP_SPLIT; `hardcase_run`'s judge (`CaseProcs` for W's processes; replay's bound after IOCP's switch, as `check_run`'s _WIN32 branch) | none | hardcases.jsonl |

A frozen W run checks, before any window: the freeze guard as on L (CODE_FREEZE, the seeds file's
sha256 on a "seed" line, the pilot entry, rule E's file, the binaries in W's citable gate), the
headings "W before the code freeze" and "The job's warm-up and W's runners (M7e), before the code
freeze" (`wrunlib.ENTRIES`; section 10 also "M7c's open items"), the W job's context (inside
`wjob.py run`, which holds W's lab lock, runs the quiet check and switches to the lab plan and
back; not a functional job), and its ports outside W's excluded TCP ranges (read on W:
5357, 31064 to 31363, 50000 to 50059, 60905 to 61204; the runners' ports 20000 to 20105, 24000 to
24005, 26000 to 26115 are outside). WL4 in W's rows: `cycles_per_exchange` (WL4),
`cycles_us_per_exchange` (through the session's cycle rate), `cpu_us_per_exchange`
(GetProcessTimes, beside it), and `cpu_shares`.

C++ (one-port ed15f97): `opcase` builds on Windows with `case` and `hold` (`open` and
`probe-reset` stay Linux only); `hold.cpp` has a Winsock form of the holder (WSAPoll,
`SO_REUSE_UNICASTPORT`, reset close), stopped by its event `Local\oneport-stop-<pid>`;
`bench/build_inputs.py` names `opcase_bin` for W and `opcase.exe` among W's binaries; the
program's PDB is named `opcase_bin` (MSVC would otherwise give the program and the library's
compile PDB one name). W's suite: `gen.hold.IOCP` (the Linux test, now on both platforms) and
`gen.binaries` with opcase (its case listing, the holder stopped by its event, `open` refused).
Neither runs before W's suite runs (W's records at the freeze run it). `bench/records_job_w.ps1`:
W's records job (the Release build, the ASan record by `sanitize_oneport.ps1`, `gate-W.json` and
`measured-W.json`), checked only by PowerShell's parser. The W ASan driver itself was complete
(M6b's dry run).

Tests: `bench/run/test_wfrozen.py` (24, registered as `run.test_wfrozen`, every platform): W's
cells, W's rows through the engine against `analysis/` (the pilot entry with the two cells never
resolved and λ from their C1 sessions; the cost cell's CPU interval on the cycles; M1; section 10
with the IOCP forms' roles; rule E's IOCP evidence and `decide`), the pilot's parts with injected
processes, the hard cases' IOCP bound and G_W, the W window's command lines and guard, the job
context, the ports, the entries. `test_wrunner.py`: `cpu_shares` (22 checks). A second reader
(a code-review agent) read the change before the compile: it found a PDB name clash in the W
Debug and ASan builds, a test that patched a Windows-only function (an error on Linux), the
mixed cell's background left running on a stop during its start (L's `cellwin.py` had the same,
fixed in both), and a refusal naming G_L on W; all fixed in ed15f97.

### 5. Checks

W, the one Windows compile check (the brief allowed one Release build): a clone at ed15f97 in
`C:\Users\alext\lab\p3\m7e\src-ed15f97`, `compile.cmd` (MSVC 19.51.36246, Build Tools 18,
Ninja at -j 2, Release, no test run; sha256
9cfb55c25393c15eb9222e2206570ea7c4e94341331f3c72eec2ff491ed8ef8e): 54 of 54 steps, 0 warnings, 55 s
(log sha256 31fdf3f3b09d0949d681043744c4140cb46c8475c249c20328cb6a45bc859da7); `build_inputs.py
--host W`: 10 targets, no mismatch (opcase_bin among them). The binaries (sha256): oneport.exe
2b8d5d1bed2d3c5f9892b91b918aba544c25216f152d629e26675fb41740aba4, opgen.exe
b8d7fed89a1ec076b22e8ce1b64de663bcd191bc78be2854019603eea1f8a9e9, opcase.exe
8be1476c029b80250f15bf797276e64568feed2883f698cbb183a1ff9bcc894c. Python on W (pure):
`test_frozen` 46 passed, 2 skipped; `test_wfrozen` 24; `test_wrunner` 22; `test_runner` 63 (13
skipped); `test_gates`, `test_record_writers` passed.

L, the four builds: job chk8 (`~/lab/p3/m7e/checks_job.sh`, M6d's script with the paths moved,
sha256 9ccf4e3fcbfa12e30c1483e70f7bfc2d68c45ef883ce8be58952bd138d770211) from a fresh clone of the
lab remote at 2055e63, which holds every M7e change to code (ed15f97); 13:52:48 to 13:58:00 +0300,
exit 0, under the lab lock with the clock floor, THP at madvise and NOTRACK, each set back.

| Build | Warnings | CTest | Report lines |
|---|---|---|---|
| Debug | 0 | 399 of 399 | 0 |
| ASan+UBSan | 0 | 399 of 399 | 0 |
| TSan | 0 | 399 of 399 | 0 |
| MSan | 0 | 399 of 399 | 0 |

399 is 398 and `run.test_wfrozen`; the Python tests run in every build (`test_frozen`, `test_wfrozen`,
`test_runner`, `test_wrunner`, the gates). Report lines recounted with the shared pattern (the
script's own line prints "0" then "NA", from its `grep -c || echo NA`). As before, three logs show a
thread's exception from `run.test_runner`'s stand-in stub (test 395), which passed; it matches no
report pattern. Logs (sha256), `~/lab/p3/m7e/check/2055e63/`: debug build
9e5449023f2ce13b3c385a5d71fbf73a85946675d6e5153dea38da54fde9e1e1, ctest
9e0fe890db272966bdcfa5a7257168e70b85ba2dffe3b85477a443a097afbd70; asan build
bbc9f8e98072aa3d4b6c2ba853f27dca344b4f9e8b192731e4cd48fbe910e45d, ctest
47f162b8a32ac4ddc6c409333d0b688497890f38aafbb16564c6aca917f5cb34; tsan build
0ddbada8cac2dae4eede6f5ad0d4cbf97384f6e962b0cfb8035445c4c053a291, ctest
daaa28ad19b3cd4ff4064c66dcebaf8e26897328ba330f42544b1a938adf2da8; msan build
a3cfc38ddca938a0b5e4bd5cdbe64ff155ae94b20e44e9d207c3a5f4bc7d1a62, ctest
139e3999b32e531f7bbd475f0e9b83b3c76c5f5fce2b0d4c9f2671b3f8404392.

### 6. W's functional check, for the coordinator when W is free

Development only, dedicated windows only (every one-port arm is a stub: nothing is started for
it), on the compile check's build, from its clone, each runner its own W lab job, one after the
other. Development seeds 8201, 8202 and 8203 (unused: not in the Papers journal, the status files
or `design/seeds.json`; to be journaled). With `--allow-noisy` the job runs as a functional check if
W is not quiet (the rows say development either way); without it a busy W refuses the job.

    set PY=C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe
    set SRC=C:\Users\alext\lab\p3\m7e\src-ed15f97
    set BLD=C:\Users\alext\lab\p3\m7e\build-ed15f97
    set OUT=C:\Users\alext\lab\p3\m7e\wfunc
    %PY% %SRC%\bench\run\wjob.py run --dir %OUT% --name wf1 -- %PY% %SRC%\bench\run\wpilot_run.py --build %BLD% --out %OUT%\pilot --job wf1 --development --dev-seed 8201 --dev-r 1 --only C1.W.IOCP.http1,C1.W.IOCP.mqtt,C2.W.IOCP.tls,C3.W.IOCP.mqtt --timer-runs 3 --split-replicates 2 --split-gaps 5,100
    %PY% %SRC%\bench\run\wjob.py run --dir %OUT% --name wf2 -- %PY% %SRC%\bench\run\wcost_run.py --build %BLD% --out %OUT%\cost --job wf2 --development --dev-seed 8202 --dev-r 1 --only C1.W.IOCP.http1
    %PY% %SRC%\bench\run\wjob.py run --dir %OUT% --name wf3 -- %PY% %SRC%\bench\run\ws_run.py --build %BLD% --out %OUT%\s --job wf3 --development --dev-seed 8203 --dev-r 1 --only S.mixed.C1.W.IOCP,S.ssh.C1.W.IOCP,S.tls-variants.C1.W.IOCP.alpn-h2

A job is stopped with `%PY% %SRC%\bench\run\wjob.py stop --dir %OUT% --name wfN`; each writes
`%OUT%\wfN.pid`, `.preflight.json`, `.plan.json`, `.log` and `.done`. What each exercises: wf1 the
warm-up, W's fingerprint, the pilot's windows and λ from a C1 session (C3 MQTT), opcase.exe in the
timer part (3 runs) and the split part (2 replicates at 5 and 100 ms); wf2 W's cost window
(`wcellwin`) on its dedicated arm, the stubbed one-port arm, a rerun; wf3 the mixed cell's
background (two keep-alive opgens and `opcase hold`, stopped by its event) on the dedicated arm,
SSH's dedicated port, opgen's tls-h2. Not in it, since each starts one-port servers: `wm_run.py`,
`wrule_e.py` (one-port against one-port, timed) and `whardcase_run.py` (one-port servers, untimed);
the coordinator decides whether to check them before the freeze.

Expected length, an estimate from M6b's measured parts (func2b: a full window 6 s and 0.26 s to
0.35 s of overhead; the TIME-WAIT wait after a churn or open-loop window 24.8 s to 30.1 s; a
session's fingerprint 3.8 s to 4.8 s, and in waa3, with the cycle rate's busy loop, about 7 s from a
session's last window to the next session's first; the job's start 11 s): wf1
16 windows (7 to 12 minutes with its warm-up and parts), wf2 4 windows after a warm-up of about
3 windows (about 4 to 5 minutes), wf3 12 windows with the background (about 9 to 11 minutes); about
20 to 30 minutes in all, longer if a session is invalid and runs again.

### What the freeze still needs

1. The coordinator's answers: M2's TLS cells (still "not run", M7d); whether W's functional check
   (above) runs before the freeze, and whether it also covers `wm_run.py`, `wrule_e.py` and
   `whardcase_run.py`.
2. W's suite on the merged tree with M7e's C++ (Debug and MSVC ASan, the whole suite with
   `gen.hold.IOCP` and opcase in `gen.binaries`), with Alex's yes when W is free; until then only
   the compile check above has seen the Windows holder.
3. On the day of the freeze, before its commit: the pins read again (the JDK first).
4. `CODE_FREEZE` (checklist item 8), the records at it on L (`records_job.sh`) and on W
   (`records_job_w.ps1`, or `sanitize_oneport.ps1` and the gate by hand), the gates `gate-L.json`
   and `gate-W.json` (item 10), and the code freeze's entry (item 11) with section 9.1's values,
   the slab and the pins.
5. Then the pilot on L (`pilot_run.py`) and on W (`wpilot_run.py`, inside `wjob.py run`), with
   `design/seeds.json`; `pilot.py` on the pinned numpy at ANALYSIS_COMMIT 9de26d6; the pilot entry;
   then section 8 step 7 in its order, on L and W.

## M7 freeze session, 2026-10-04: W's checks (stopped: W in use), the code freeze not declared

This session was to run W's checks and then the code freeze. It stopped in Part 1: W's suite
failed one check of a test, which is fixed (7a4063c), and the run of W's suite at the fix, the W
records driver's dry run and W's functional checks never started, because W's quiet check refused
every attempt from 17:33 to 20:37 (36 attempts) while W was in use. CODE_FREEZE is not declared,
no record was made, and the pins were not read for the freeze. Nothing here is a result: no window
ran on either host. Every job on L ran under `lab_job.sh` at nice 0, launched from bash, from fresh
clones of the lab remote under `~/lab/p3/m7f/`. On W the builds ran from clean clones of `origin`
under `C:\Users\alext\lab\p3\m7f\`. The `one-port-m6b` work tree was not used.

### Commits (papers/one-port)

| Commit | Message (first line) |
|---|---|
| 7a4063c | fix(tests): test_wrunner's cycle-rate check reads the server's CPU and runs alone |

Then this section's commit. Papers: the bump of `papers/one-port`. No lab-journal line: no window
ran.

### 1. W's suite at 91f2f77 (run 1)

From a clean clone of `origin` at 91f2f77 (`m7f\src-91f2f77`), `m7f\check.cmd` (M6b's check.cmd
with the paths as arguments; sha256 5fd7fe26aa849ca8ee3832b2e45e616362d6c9028578c4c75d67b0061ce603f9):
MSVC 19.51.36246.0, Build Tools 18, Ninja; Debug with the release libraries, then ASan
(`-DONEPORT_SANITIZER=address`), which linked `openssl-3.5.9-asan` and `nghttp2-1.70.0-asan` (its
configure lines; both flavours were built with `/fsanitize=address` by `build_deps.ps1`, exit 0);
then `ctest -V -j 4`, ASan with `detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1`.
Started at 17:01, not inside a W lab job (as M6d's suite checks). Warnings: lines of the build log
holding "warning", none. Report lines: the shared pattern (`bench/oneport_record.py`, `REPORT`;
`m6d\reportlines.py`).

| Build (91f2f77) | Steps | Warnings | CTest | Test time | Report lines |
|---|---|---|---|---|---|
| Debug | 54 of 54 | 0 | 164 of 165 | 67.69 s | 0 |
| ASan | 54 of 54 | 0 | 164 of 165 | 73.21 s | 0 |

165 is M6d's 163 and the two tests M7e registered on W: `gen.hold.IOCP` passed (2.69 s, 3.00 s),
its first run on W, and `run.test_wfrozen` passed; `gen.binaries`, now with opcase's listing, its
holder stopped by its event and `open` refused, passed. So M7e's Windows C++ (`opcase` on Windows,
its holder) built and ran its tests in both builds. The test that failed in both:
`run.test_wrunner`, 21 of its 22 checks passed; `cycle_rate_reading` failed. Its busy loop, pinned
to CPU 0, held the CPU for 0.328 s (Debug) and 0.344 s (ASan) of a 0.5 s span, where the check asks
0.85 to 1.15 of it; its cycles per second of wall time read 2.40e9 and 2.45e9, where W's sessions
read 3.90e9 to 3.94e9 (M6d). Run alone three times right after, the check passed once and failed
twice (0.375 s each). W was in use: a game (`TFTClient-Win64-Shipping`, started 17:02:52, during
the Debug suite; the League client since 14:56:37), and CPU 0 read 61% idle with 13%
DPC and 5.5% interrupt time (a 2 s reading, read only).

Logs (sha256), `m7f\check\91f2f77\`: debug build
40024d50db485445cc2f2eec5713ed117b2f084a6754cfa1021cf5840656b585, ctest
fd20627f9d8c68da75ab2e79a9c67697347986aa3b87ea61179ddf1cb2e0aba8; asan build
704d0e2f5f37ded5c238534ce501fc5bdf5553a22550ec6fb202eaabaf935711, ctest
81ed512ff47e0c7c119662e0a36a15fffce1107289b41471d4a3109be857e784.

### 2. The fix (7a4063c)

Why it is a fault of the test and not only of the load: W's quiet check reads CPUs 2 to 10
(`wsys.QUIET_CPUS`), so CPU 0, where Windows takes most interrupts and DPCs, is outside it, and the
check could fail on a W that passed it; for example in the suite of W's ASan record, where
`records_job_w.ps1` stops at a record that is not green and its driver never runs again over
existing logs. CPU 0 had no stated reason (4af5714's message names none). The fix: the loop runs on
`wsys.SERVER_CPUS` (CPU 10), where the runners read the rate and which the quiet check covers; and
`run.test_wrunner` is `RUN_SERIAL` in `tests/CMakeLists.txt`, so no other test's process takes that
CPU during the span. The band 0.85 to 1.15 is unchanged. No compiled input changed. The fix
changes `bench/` and `tests/CMakeLists.txt`, so CODE_FREEZE cannot be older than 7a4063c. It has
not run on W yet (below).

### 3. The suite on L at 91f2f77 and at 7a4063c

`~/lab/p3/m7f/checks_job.sh` (M7e's script, the paths moved to `~/lab/p3/m7f/check/`; sha256
a38e9da2404d3623984dd89c844554f111502752087b58b08b4071d1345577c4), lab_job.sh from a clone at
91f2f77 (`~/lab/p3/m7f/jobsrc`), each job from a fresh clone of the lab remote, under the lab lock
with the clock floor, THP at madvise and NOTRACK, each set back (the job logs say so).

| Build | chk9 (91f2f77, 17:01:22 to 17:06:35) | chk10 (7a4063c, 17:32:32 to 17:37:44) |
|---|---|---|
| Debug | 0 warnings, 399 of 399, 0 report lines | 0 warnings, 399 of 399, 0 report lines |
| ASan+UBSan | the same | the same |
| TSan | the same | the same |
| MSan | the same | the same |

Report lines recounted with the shared pattern (`lab/bin/sanitize.sh`'s `report_re`). As before,
logs show a thread's exception from `run.test_runner`'s stand-in stub (test 395), which passed (chk9:
four logs; chk10: three); it matches no report pattern. On L `cycle_rate_reading` is skipped (not
Windows). Logs (sha256): chk9, `check/91f2f77/`: debug build
29bd0185ecea344177d39d044d2282a23e87990ab91315e048f66e07739d485a, ctest
cee233cff68539c111e22498b6b1b5f1ab182efbff2629c25c7f9b5fb6fbb68d; asan build
f26e07937c795ac63dde75602776246db8f3f008ba6252e6014c8a659a7973a4, ctest
31d5a24a674111acd0fa0caaffd1556690450c8a1f311d7ccf9d1f19507864f5; tsan build
8dd1d6d60b9e30fc6439ee69a65688a95a083d3ad35a104edd19d6f621a474b1, ctest
e931b971d6e90c9a3ba323451ca34d0009ef5575d51448ebe845350f3d2882c4; msan build
26d97c267742eb6332927812f55738ffdf143f1672d65945063e0701de4f4beb, ctest
1550a6fc07bd5f6281a48da49f4c14a7ae6e689c32bc1694fcf8d4fb38b97eb1. chk10, `check/7a4063c/`: debug
build 541ea01f4076c65e201a94b00cfc5d359e1e602adbc5ee63b2f408093cfb7e4c, ctest
e32de312b2d83b6bfa5de5aebc7ee68af841841790ac202755e1af43b854f076; asan build
9c95e5ac56d7f36b7319336e67e3f121febfb8f49625c7cdec9cee03da446342, ctest
dddb998e1b31fddce74fa8735f352b59ea458f3405666e48dec88b5576433f7c; tsan build
c9ff26186c0191a8f59b33149c5105abb62986301e7f092cc165ea8bee41600d, ctest
f01b58d56194845acd6d197a8a1b47e320b61832c4f4e552f0c15d791078886a; msan build
eede1dd98df47fd83e6776f7e982709d74e508606622f772f66ccea04d38b16f, ctest
1c83765cbc5dff315c2d66b57eb882489d7623b789ccc8da9f2e8125dd3a41fe.

### 4. W's chain of jobs: refused by the quiet check every time

What was to run, in order, each a W lab job inside `wjob.py run` without `--allow-noisy`, from a
clean clone of `origin` at 7a4063c (`m7f\src-7a4063c`), started by `m7f\chain.py` (a launcher after
M6b's wnight.py, not committed; it runs the jobs one after the other, tries a job again 300 s after
wjob refuses it for W not being quiet or an update installing, renames a refused job's files
NAME-refusedK.*, stops at a required job that fails, and ends at its stop file `chain.stop`), with
`m7f\steps.json`:
1. `suite1` (required): `m7f\checkj.cmd` (check.cmd's builds and suites, exiting non-zero when a
   build or a suite fails), Debug and ASan at 7a4063c into `m7f\check\7a4063c\`;
2. `dry1` (required): `bench\records_job_w.ps1 -DryRun -Out m7f\dryrun -Records m7f\dryrun\records
   -LabBin D:\Dev\GitHub\Papers\lab\bin`: the first run of W's records driver (written in M7e,
   checked only by PowerShell's parser), a dry-run `gate-W.json` to bind the functional rows, and
   the Release build (`m7f\dryrun\build-release`) the functional checks use;
3. `wf1`, `wf2`, `wf3`: M7e's functional checks as M7e lists them (dedicated only, development
   seeds 8201, 8202, 8203, every other argument as listed), on that build and the 7a4063c clone,
   `--out` under `m7f\wfunc\`;
4. `wf4`: `whardcase_run.py --development --entries IOCP.replay.inproc,IOCP.peek.inproc
   --replicates 2 --dev-g-ms 100 --dev-gap-split-ms 10` (all 25 cases; e2e3's development G and
   gap); untimed, one-port servers, B1 and B2.

Launched at 17:33:31 through WMI (`m6b\wlaunch.ps1`, pid 26040, `m7f\launches.txt`), cutoff 21:00.
The quiet check refused `suite1` on all 36 attempts, 17:33:32 to 20:37:19: mean idle 24.4% to
81.6% over the 10 s check (it asks at least 95%); every refusal named `LeagueClient` among the
processes above 5% of one CPU, which the check refuses, and the refusals also named
`LeagueClientUx`, `dwm`, `System`, `vgc`, `audiodg`, `MsMpEng`, `chrome` and others; the game
`TFTClient-Win64-Shipping` was among the top five processes in 15 refusals (games started at
17:02:52, 17:37:48 and 18:16:02, and one ran at 20:37). No update was installing and the core layout held in every preflight. No
job passed the preflight, so no plan switch happened; Alex's plan "ChrisTitus - Ultimate Power Plan"
was active when read at 16:56 and at 20:40. Nothing was weakened. The chain was stopped by its stop file
at 20:39:28 (`chain.done`: "stopped by chain.stop"); its pid 26040 and every wjob pid of the 36
attempts (`suite1-refused1.pid` to `suite1-refused36.pid`) had ended. `chain.py` now counts a
refused job's files on from an earlier launch's highest number (a relaunch would otherwise fail to
rename onto `suite1-refused1.*`), checked with a stub wjob.

Files (sha256), `C:\Users\alext\lab\p3\m7f\`: `chain.py`
4a4faa11f122488fc769bffcd8b55e52d7f3655271e2620836afb2063253c11d, `steps.json`
2677df0262ba658706b6e0a16e7d9d4e13084cad622e581e40b9efa5aef64169, `checkj.cmd`
e974ebb0998353274d458869978dbedd49f51e5decbc1a9899d1eeaaf6b564b9, `chain.log`
84e7740bf1092edc54fb6ee3523b7edc36ad09c2f9857ca73d55b3a0e1303918; for the checks after the chain,
`dev-seeds-w.json` 2a0c95a851ead7297c755cb58ba8554165130dcb0adb26c3c785a79dd430166e (devcheck's
seeds: `SEED_PILOT_W` 8201, `SEED_ORDER_C_W` 8202, `SEED_ORDER_S_W` 8203, and 8204 to 8214 for the
other eleven names in 4.7's order; 8204 to 8214 appear in no journal line or status file and are
reserved as development seeds, none used yet) and `ksrc_scan_w.py`
d9b57309f61fcc0c3a5c8efa0caa9da7aff6399bf52da25908c02f5373a63710 (M7d's `ksrc_scan2.py` with its
root moved to W's lab directory, for the K_SRC rule over W's rows).

### 5. Not run, and why

- W's suite at 7a4063c, the records driver's dry run, wf1 to wf4: the quiet check (above).
- `wm_run.py` and `wrule_e.py`: not run, and they would not have run had W been quiet. Their only
  window is `wcellwin.run`'s, the server in one-port mode with a 1 s warm-up and a 5 s measured
  window that records connections per second; neither has a form that records no metric, so each
  would time one-port mode on W before the pilot entry.
- The rows' checks of the brief's item 3 (validity, `cpu_shares`, `cycles_per_exchange`, the 80 s
  warm-up record, `analysis/rows.py` at 9de26d6 in development mode through `devcheck.py`): no row
  exists.
- Part 2 (the pins read for the freeze, the slab re-read, CODE_FREEZE, the records, the gates, the
  code freeze's entry): not started, since Part 1 is not green. One read-only look at Adoptium's API
  at 17:01 (not the freeze day's read): Temurin 25's latest GA build was still jdk-25.0.4.1+1
  (2026-08-19), most_recent_lts 25.

### 6. To resume

W must pass section 5's quiet check: the League client closed (it alone holds a process above 5%
of one CPU), nothing else above 5%, W locked or its display off. Then, from any console on W:

    powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\alext\lab\p3\m6b\wlaunch.ps1 -Dir C:\Users\alext\lab\p3\m7f -CommandLine "C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe C:\Users\alext\lab\p3\m7f\chain.py --dir C:\Users\alext\lab\p3\m7f --steps C:\Users\alext\lab\p3\m7f\steps.json --retry-s 300 --cutoff <ISO time>"

It is stopped by creating `C:\Users\alext\lab\p3\m7f\chain.stop` (delete it before the next
launch). After it: `devcheck.py` with the dry run's gate and `dev-seeds-w.json`, `ksrc_scan_w.py`,
the rows read for the brief's item 3, the lab journal's lines for wf1 to wf4; then Part 2.
W time the chain needs, from measured parts where there are any: `suite1` about 5 min (run 1: both
builds 17:01:00 to 17:02:35, suites 68 s and 73 s); `dry1` not measured as a whole (`records_job_w.ps1`
has never run; its parts are a Release build, 55 s in M7e's compile check at -j 2, and the ASan
record, 80 s in M6b's dry run of `sanitize_oneport.ps1`, then the gate); wf1 to wf3 20 to 30 min (M7e's
estimate from M6b's measured parts); wf4 not measured on W (e2e3 on L: 328 runs in 91 s; wf4 has
656). Then Part 2's W record, about `dry1`'s length again.

### For the coordinator and Alex

1. W was not free: Alex played from 17:02 to at least 20:37 with the League client open
   throughout. W's checks need the client closed and W left alone (locked or display off) for about
   an hour, longer with Part 2's W record. The harness never weakened its check and never touched
   his processes.
2. 7a4063c is a test fix found by W's suite (above); it moves CODE_FREEZE's earliest commit to
   7a4063c. L is green at it (chk10); W's Debug and ASan suites at it are the chain's first job.

## M7 freeze night, 2026-10-05

The night's coordinator (one session, unattended; Alex asleep) resumed the M7 freeze session: W's
checks, then the code freeze, the A/A pilots and what the frozen text allows after them. This
section is written as the night goes and says where it stands. Nothing here is a result: no
window of the frozen code has run yet. Every L job runs under `lab_job.sh` at nice 0, launched
from bash, from clones of the lab remote under `~/lab/p3/m7g/`; W's jobs run under `wjob.py`
from clean clones of `origin` under `C:\Users\alext\lab\p3\m7f\`.

### Commits (papers/one-port)

| Commit | Message (first line, shortened) |
|---|---|
| 1fca359 | fix(bench): W's job-start quiet gate at 90% mean idle, 90% per CPU and 10% per process (Alex's decision), logged before any pilot data |
| 20c01b9 | fix(tests): on IOCP the suite waits 250 ms after a server's start before its first client; coverage.json: no third-party library needs a Windows gap |
| ddd9d6a | fix(tests): on Windows the generator tests check the form of the workers' CPU time |
| ff2679c | fix(bench): records_job_w.ps1's gate step runs its Python steps inside cmd.exe (CODE_FREEZE) |
| c5b1dd9 | docs: the code freeze's entry (revision log) and this section |
| f185a8a | docs: the record of W's frozen runs in Python's UTF-8 mode (revision log) |

### 1. W's quiet check, 00:20 to 00:46

The chain of the M7 freeze session (`m7f\chain.py`, pid 8100, launched 2026-10-04 20:45, run 2)
was still refused at 00:20 with the League client running (attempt 78). It had closed by 00:24.
Attempts 79 to 83 (00:25 to 00:46) were refused without it: mean idle 93.4%, 95.4%, 98.1%, 95.2%
and 83.9%; CPU 10 at 79.8%, 93.9%, 94.8%, 89.5% and 71.9% idle; above 5% of one CPU, `dwm` (15.3%,
9.5%, 9.8%, 13.9%), `System` (6.7%, 6.2%, 9.1%, 21.7%), and in attempt 83 `MsMpEng` (13.3%) and
`msedgewebview2` (17.3%). This session's own window (the Claude app, in the foreground and
redrawing while the session worked) was on screen during attempts 79 and 80; it was minimized at
00:33 (a window state, no setting), and `dwm` still read 9.8% and 13.9% in attempts 82 and 83. The
display stays on: Alex's plan never turns it off on AC (`powercfg`, read only). At the new gate
(part 3) attempt 81 would have passed and the other four would not.

### 2. Alex's decision, part 1: the checks run as functional checks

At 00:50 the coordinator relayed Alex's decision ("At this point, just lower the threshold") in two
parts. Part 1: the chain's steps are tests, a dry run and functional checks, not measurements, so
they run with `wjob.py run --allow-noisy` (a functional check, recorded as one). The chain (run 2)
was stopped by its stop file at 00:50:31 while it slept between attempts (no job was running); its
files are `chain-run2.log` (sha256 3a9c55639d2a54b780abdab3ec2475014056418ebc6407cef5cb4c3c504e60ec)
and `chain-run2.done`. `chain.py` takes an optional `wjob_args` per step (sha256 now
b77fea4f3b3c86905d7b4fe7642b012bae38f68bef89d41f13d44c7287ffe934; the old one kept as
`chain-run2.py`), and every step of `steps.json` has `["--allow-noisy"]`. Run 3 (pid 17632,
00:51:01) started `suite1` at once as a functional check: its preflight read a mean idle of 84.6%,
`quiet` false, `functional_check` true. wjob sets the lab plan in a functional check too, so the
plan was active from 00:51:13; that is not a passed quiet check. A correction from the coordinator,
sent after the relaunch, read attempt 84 as having passed the quiet check; it had not
(`suite1-run3.preflight.json`), and no job was stopped while it ran.

### 3. Part 2: W's job-start gate at 90%, 90% and 10% (1fca359)

`bench/run/wsys.py`: `QUIET_TOTAL_IDLE_MIN` 90 (was 95), `QUIET_CPU_IDLE_MIN` 90 (was 95),
`QUIET_PROCESS_MAX` 10 (was 5); `run.test_wrunner`'s `quiet_rules` pins them and their bounds.
Logged as Alex's decision, before any pilot data: hypotheses.md, revision log, "W's quiet gate
lowered (Alex's decision), before the code freeze". The per-window validity rules and the
per-window CPU sampler do not change; `--allow-noisy` is used for no pilot window and no
measurement. `design/w-procedure.md` section 5 carries a dated note; its approved text is kept.

### 4. W's suite at 7a4063c: one failure, a race in the suite (20c01b9)

Run 3's `suite1` (Debug and ASan at 7a4063c, `check\7a4063c\`): Debug 165 of 165; ASan 164 of 165.
The failure: `case.HC22.IOCP.inproc.replay`, "HC22.partial IOCP inproc replay: replicate 1: ... the
server did not close the connection" (the collector saw no close report within 10 s). The chain
stopped there (`chain-run3.done`: "stopped: required step suite1 exited 6", 00:54:31).

Diagnosis (on W, no job running): at 7a4063c, `ctest -R "^case.HC22.IOCP.inproc.replay$" --repeat
until-fail:30` in the ASan build failed at its 14th run, the same check, again replicate 1. In both
failures it was the first connection to a freshly started one-port server. `Server::start()` on
Windows (`bench/server/server_win.cpp`) returns once the worker threads are spawned, and each
worker posts its listeners' AcceptEx requests itself (`bench/server/iocp.cpp`, `run_iocp`); the
suite's first client connects within microseconds of `start()`. HC22's partial variant writes "GE"
and resets 10 ms later, the only script that resets that early; a connection reset before a
request is posted either never reaches one or completes one with an error, which `on_accept_entry`
closes without a report (the likely mechanism; not established). The server meets HC22's frozen
outcome either way (state freed, counters consistent); the test's expectation of a close report
for every client is what races.

The fix, test only (20c01b9): `tests/harness.hpp`'s `Running` waits 250 ms (`kIocpStartWait`) after
`start()` on Windows before the test's first client. No measured binary's input changes (oneport,
opgen, opcase, ophold); the suite target's does. The same commit settles `bench/coverage.json`'s
Windows gap (checklist item 7): no third-party library is declared, since OpenSSL 3.5.9 and nghttp2
1.70.0 are built with `/fsanitize=address` in their asan flavour and W's ASan build links them.
Validation, a clean clone at 20c01b9 (`m7f\src-20c01b9`), its ASan build (0 warnings; 165 s with the
runs): HC22 on IOCP in-process, 100 of 100 runs in replay and 100 of 100 in peek (`m7f\val22\`).

For Alex: the frozen hard-case runner on W (`whardcase_run.py`) starts its servers as processes and
its clients from other processes after the server's lines, so its first client comes tens of
milliseconds after `start()`; the window above is far shorter in practice, but it exists. A wait in
`Server::start()` until every worker has posted its requests would close it; that is a server
change and was not made.

### 5. L: the suite at 1fca359 and 20c01b9, the pins and the slab

| Job | Commit | Debug | ASan+UBSan | TSan | MSan |
|---|---|---|---|---|---|
| chk11 (00:55:31 to 01:00:44) | 1fca359 | 0 warnings, 399 of 399, 0 report lines | the same | the same | the same |
| chk12 (01:05:45 to 01:10:58) | 20c01b9 | 0 warnings, 399 of 399, 0 report lines | the same | the same | the same |

As before, the logs show `run.test_runner`'s stand-in thread exception (test 395), which passed.
chk11's logs (sha256), `~/lab/p3/m7g/check/1fca359/`: debug build
d37464b2602115fdbe3fbbfc29da1c1424f07c918b4c18693d164d425f7697bf, ctest
bfa3f79621d0e70503ad79983fd565d2a960ed4a2802276b10d58998e916e0bb; asan build
0059c41803c6eda73bb6f10057be43a694729d8947dd19ac6250b84e85eeb69f, ctest
5905c3c60276f6b7edc3518cd2c0ab004c38afa0e4bba5fe7d49a9996bdc224d; tsan build
a17050a78fb8669801da7d0ebe52de169a2266928441aa675b93ddb2df1ef22c, ctest
48513af0692b235f8abec8ebbd80738a3f3da9cc6204ff42dd0b4b1c78b25f54; msan build
c04eaea83a3b10c7b05f0ab07a836e37d8cdf01b0df059fcfc28578b09f364c5, ctest
33dde637c8f149683b77ce82c01b539f411b3dda403481b0404979ab673a935f. `checks_job.sh` is M7f's with its
paths in `~/lab/p3/m7g/` (sha256 491f816240cc3614093806ee065317e7a9804e889b2a026628fb4f19da53c660)). chk12's logs (sha256), `check/20c01b9/`: debug build
2a97b6778c9c6f30f3e066078168718c02099168b4e3fe00dbcac66bba03be97, ctest
5299784441230db312cf2affd0e0572636eb1bd6e42387bda3ea8db6cd3b779e; asan build
97d549343bc2aa279ebfb009582c0409e74d39d000f46cdb3917c552ad7cea72, ctest
11c43e16ae7a46f5a0c4579e2e3baab66551e21e61a4f77b8369f15e0dae631e; tsan build
2baa30ce9007f72f8d722b8ce4d56421bedd846bede5263693ea2ac7e3ac17b0, ctest
6517ffe8c302c7f953adee58ba21cbeb926919fa81ffd674b5cb90cff38fc9ce; msan build
0504775656fb0e44cb29e5e670a0c17efc3430e767d7258da1abc08a32fcbb23, ctest
0ab21c84ec2429093e57cbc333880d6d9a5b8a1997a0d29425aae2eba2f551d0.

The pins, read again on the freeze day (2026-10-05 00:54:18 and 00:54:28 +0300; M7d's
`pins_read.sh` and `pins_read2.sh`, unchanged; logs sha256
748a822d754aa95b870ba3f8cab75f681278e5da62b4db6fe1ba80545089d9cc and
50a028440dd413d2dfd12e5eb24377aebf8b0a356ee7053968d8643a0d915469): Temurin 25's latest GA build is
still jdk-25.0.4.1+1 (most_recent_lts 25, the archive's sha256 as pinned); OpenSSL 3.5.9 is still
the latest 3.5 release; nghttp2 v1.70.0, Envoy v1.39.2, xcaddy v0.4.7, caddy-l4 v0.1.2 at 42db5690
(also master's head), sslh v2.3.1, cmux v0.1.5, hyper-util 0.1.21, Netty 4.2.18.Final, Jetty
12.1.13, nginx stable 1.30.5 and HAProxy 3.4.6 are each still the latest of the pinned line; Caddy
v2.11.7 and Rust 1.99.0 are what M7d's two readings already cover; go1.27.1 on L. No pin changes.

The skb caches, read again as root, read only (00:55:22; M7d's `slab_read.sh`, log sha256
95917c5e2dcc1710aecbabb8a921c668a0364e1957edc82fa9df857ade45c5b5): kernel 7.2.6-arch2-1, its command
line without `slab_nomerge`, `CONFIG_SLUB_DEBUG=y`, `CONFIG_SLAB_MERGE_DEFAULT=y`, no
`CONFIG_SLUB_DEBUG_ON`; `/proc/slabinfo` exists; "skbuff_head_cache" and "skbuff_small_head" are
directories of their own (`aliases` 0) listed under their own names; `skbuff_fclone_cache` links
to `:0000512` (`aliases` 2; linked names pool_workqueue, sgpool-16, skbuff_fclone_cache), which
`/proc/slabinfo` lists as pool_workqueue; page size 4096. Unchanged from WL7's reading.

### 6. Two more fixes found by W's checks (ddd9d6a, ff2679c)

W's chain, run 4 (pid 21168, 01:09:12, at 20c01b9): `suite1` passed the new gate (mean idle 96.6%);
Debug 165 of 165, ASan 164 of 165: `gen.keepalive.tls.IOCP` failed its check "the workers' CPU
time" (`tests/gen_tests.cpp`, `r.cpu_s > 0`). opgen reads each worker's CPU time with
`GetThreadTimes` (`bench/gen/opgen.cpp`, `clock_s`), which advances on the clock tick (15.625 ms)
and charges each tick to the thread that runs then; over the test's 100 ms window two keep-alive
workers that mostly wait, beside the server's worker in the same process, can read 0. HC22 passed
at 20c01b9 in both builds. The fix, test only (ddd9d6a): on Windows the check asks for the form
(two values, a sum of at least 0); Linux's check is unchanged. W's chain, run 5 (pid 12672, 01:15:03,
at ddd9d6a): `suite1` Debug 165 of 165 and ASan 165 of 165 (0 warnings, 0 report lines; logs in
`m7f\check\ddd9d6a\`); then `dry1` stopped at the gate step: `records_job_w.ps1` ran
`build_inputs.py` from PowerShell with `$ErrorActionPreference` "Stop", and the summary line that
`build_inputs.py` writes to standard error became a terminating error. The fix (ff2679c): the gate
step's three Python steps run inside cmd.exe, as the release step's build does; tested at once on
the dry run's output (`-DryRun -Only gate`: `gate-W.json` written, every one of the 10 targets
covered by the dry-run record, `citable` false). No compiled input changed in ff2679c.

### 7. W's functional checks (run 6) and the rows' checks

W's chain, run 6 (pid 30860, 01:22:28 to 01:48:09; steps wf1 to wf4 at ddd9d6a on the dry run's
build, `dryrun-ddd9d6a\build-release`; each step's preflight passed the 90/90/10 gate, so none ran
as a functional check by wjob's rule, and each was launched with `--allow-noisy` all the same):

| Step | What | Outcome |
|---|---|---|
| wf1 | `wpilot_run.py`, dev seed 8201, C1 HTTP/1.1, C1 MQTT, C2 TLS, C3 MQTT, one session each; timer part 3 runs; split part 2 replicates at 5 and 100 ms | 16 of 16 windows valid; the warm-up 4 windows, 113.9 s; λ for C3 MQTT from the C1 session; 3 timer runs valid (lateness 8.65 to 12.82 ms); 4 split replicates valid, each with 2 receives that returned payload |
| wf2 | `wcost_run.py`, dev seed 8202, C1 HTTP/1.1 | the dedicated windows valid (17,021 to 17,096 connections per second), every one-port window a development stub, the session and its rerun |
| wf3 | `ws_run.py`, dev seed 8203, the mixed cell, SSH C1, TLS with ALPN h2 | SSH and ALPN h2 dedicated windows valid; the mixed cell's 4 dedicated windows invalid by section 7's generator rule (below) |
| wf4 | `whardcase_run.py`, IOCP replay and peek in-process, 2 replicates, development G 100 ms and gap 10 ms | 328 variant entries, 0 with a failing run |

`devcheck.py` (from `src-ddd9d6a`) over every row of wf1 to wf4 with the dry run's `gate-W.json` and
`dev-seeds-w.json`: ok; 707 rows bound to the gate, 0 refused, 16 stub rows, the analysis accepted
every family's rows, and the pilot check ran on 31 rows (`m7f\devcheck-ddd9d6a\devcheck.json`, sha256
ea0493d953adc339976c98417b54f192feec647b645d45d26647e69f973774a0). `ksrc_scan_w.py`: 22 row files,
2,468 rows since 2026-10-03 08:36:23, no failed connect (log sha256
bffb73150c8040281f92d6dc9c99c621bad12b746c98cc534d2a61da2a896bbb). Every valid row that ran a binary
carries `cycles_per_exchange` and `cpu_shares`; each job's warm-up record shows 80 s and no fault.
Row files (sha256), `m7f\wfunc\`: pilot windows
acc219d4782123f19a01aa3afb599c2c9836d065da9d8b92712ee28bbf32821c, parts
78f93e62286b7ccbf02a47e0614fbb96d0fe490a0ea4a9c43bda3ac4ad215554; cost
5909046ac90a32d6cad48c58248e6657db8bcc208044dc459946de8fdb8fb809; s
2cba70011732f2a5dcc73ac4f4e1a13ce78763fb1c4ebe0608fca2df6c6fc6dc; hard
32c05211641e3c6a167b7718cc4b6651ab9c535c1a7ff270a5f4c0bd496e44ce.

For Alex (not changed tonight): on W the mixed cell's own generator, on CPUs 2 to 5 by M7e's
placement (the entry "The job's warm-up and W's runners (M7e)", item 4), was 97.5% to 99.1% busy
(opgen's own share 98.5%), with the server's CPU 100% busy, so every dedicated window of the cell
was invalid by section 7's generator rule. The cell is secondary (section 10) and decides nothing;
as it stands, its W cell will report invalid windows with this reason. A wider generator placement
would be a new design choice, logged; it was not made.

### 8. The code freeze

On L, lab job frz2 (`~/lab/p3/m7g/freeze_l.sh`, sha256
0643e23c12f76cbba7d428c4c4a3e4e79be505e6966d5878065b461b0522681b: `checks_job.sh` at the commit,
then, if every build is green, `records_job.sh` from a fresh clone with `REPO_URL` the paper's
repository), at ff2679c, 01:23:11 to 01:37:10: the suite in four builds (0 warnings, 399 of 399, 0
report lines each; logs in `check/ff2679c/`, sha256: debug build
dd48dd1072bf363efd7340cf926d3975e6a99f50fb5e7a48d21d4a7b7e71732e, ctest
847ac710a4c2225cdbcd068ee027504a4e9630ed58118e3f7f30030188b51dbf; asan build
aa71a0409bad746dbe944d276dabbada9391f2aea6a14d44e5517f60648d89ac, ctest
b798a66b098aaf777e6483c9265e53a40de7b5fa4d180a443440412bf6b3be26; tsan build
8516c6226b457858038b39cb0dbbe6fc0037059cf8e9b8faa1e30a048adcae1b, ctest
8ccc57675663ff88cfdaf966000287ca3be0732b5cbadd3df78ddb6cb6040aaf; msan build
791880cd2c5b48ba6c5e7cc9e4de94d4e7ca0054d2745f4a1bcb3e67cecb17fb, ctest
9e4a3c7bdd4da497602fe6bcfa98f953b61c503a98595c1d8870fed61b8e90da), then the seven records, all
green, and the gate (`records-ff2679c/`). Earlier the same night: rec1, the records at 20c01b9
(01:12:00 to 01:20:48, all seven green), superseded because ddd9d6a changed the suite target's
inputs hash; and frz1 at ddd9d6a, stopped by SIGTERM to its process group 3 minutes in (01:23:06, exit
143; the clock floor, THP and NOTRACK set back) when ff2679c moved the freeze. Found then: two
servers that a Python test of the Debug suite had started in sessions of their own (pids 543858 and
543861, ports 4200 and 4210 to 4215) outlived the process group's SIGTERM; they were stopped by
their pids before frz2's Debug suite reached their ports. A suite stopped this way can leave such
servers; the next job should check `ss -ltnp` for `oneport` first.

On W, W lab job recw1 (`records_job_w.ps1` at ff2679c from a clean clone `m7f\src-ff2679c`, 01:49:41
to 01:51:41, passed the 90/90/10 gate at a mean idle of 96.9%): the Release build (22 s), the MSVC
ASan record `oneport-ff2679cc8-W-asan` (green; 0 warnings, 165 of 165, 0 report lines), and the gate
(`gate-W.json`, every target covered, citable). W's binaries are not byte for byte those of the dry
run's build at ddd9d6a (oneport 749d0209c112 against 3d85ac13fcac), as MSVC embeds the build's
paths; the pilot and every frozen W run use `m7g\records-ff2679c-W\build-release`.

Netty's allocators, read again (lab job netty1, `probe.py --system netty --kind b3` on the frozen
Release build; `nettyprobe.sh` sha256 0499b529c3683738698c5af72cf966dfa38d355a9efb4b2ea69170d3d448bd61):
AdaptiveByteBufAllocator and AdaptiveRecvByteBufAllocator, unchanged. `lab/bin/test_report_pattern.sh`
passes on the Papers repo with the new records.

CODE_FREEZE = ff2679c, logged with section 9.1's values, the records and the gates in the revision
log's entry "The code freeze".

### 9. The A/A pilots (section 8 step 4), started

Rule E's IOCP receive form has nothing to choose (the coordinator's decision on M6a's reading 7), so
it ran no session, and both pilots started on the frozen binaries, in dedicated mode only.

L: lab job pl1 (`~/lab/p3/m7g/pilot_l.sh`, sha256
ff4c725af3d6d6566d78dbdebdd4e15f22198c3ec7a4c72902a76ba7fd9e2d96; lab_job pid 571104), from bash at
nice 0 under the lab lock with the clock floor, THP at madvise and NOTRACK, from a fresh clone at
c5b1dd9 (`~/lab/p3/m7g/pilot-src`): `pilot_run.py --build ~/lab/p3/m7g/records-ff2679c/build-release
--out ~/lab/p3/pilot-L --job pl1 --seeds design/seeds.json --code-freeze ff2679c... --gate
~/lab/p3/m7g/records-ff2679c/gate-L.json`, started 01:56:43; the freeze guard passed (the warm-up
began). 86 windows were written by 02:07, all valid so far. Expected end, from that rate (about 8.6
windows a minute) for 1,024 windows and the timer and split parts: about 04:30.

W, first start (01:57:27, W lab job wp1 from a clone at c5b1dd9): stopped in the freeze guard before
any window. `freeze_guard.git()` reads `git show HEAD:hypotheses.md` with the locale's encoding,
cp1252 on W, which cannot decode hypotheses.md's UTF-8 (byte 0x81): UnicodeDecodeError in the reading
thread, then AttributeError on the missing text. No row was written; the run's directory held only
its inputs file (kept as `C:\Users\alext\lab\p3\pilot-W-crash1`), and the job's files are
`m7g\wpilot\wp1-crash.*` (log sha256 3f44486160ec4b344859b8f21f7b43c47c0ff5a695f9fbd5b3659d898d03184b).
Not a code change: every frozen W run now runs in Python's UTF-8 mode (`PYTHONUTF8=1` set in the
starting process only), checked first (the guard with the run's arguments gave its clearance; W's
Python tests passed in UTF-8 mode; the development job wdev1, dev seed 8216, 4 of 4 windows, the
timer run and the split replicate valid), and recorded in the revision log (f185a8a: "W's frozen
runs in Python's UTF-8 mode (a record), after the code freeze"). The guard's fix (an explicit
encoding in `freeze_guard.git()`) is a change of the frozen code, left to Alex.

W, the run (W lab job wp1, chain pid 28764 started by `m7g\wpilot\run_chain.cmd` through WMI, sha256
de1337fec7b64ea3eac711e0b25087c8af2e915993901d757b889b734c577dc0; `steps.json`
158a8ede8ac466688147ae22df8fbcb58ba2b09fd308993e96b67a639c79aee3, no `--allow-noisy`; a clean clone at
f185a8a, `m7g\pilot-src2`): `wpilot_run.py --build m7g\records-ff2679c-W\build-release --out
C:\Users\alext\lab\p3\pilot-W --job wp1 --seeds ...\design\seeds.json --code-freeze ff2679c...
--gate m7g\records-ff2679c-W\gate-W.json`, started 02:06:40 after W's job-start check (mean idle
97.0%); the guard passed in UTF-8 mode (`utf8.txt`: 1) and the warm-up began. The chain starts no
attempt after 09:20. The morning rule (no new W session after 09:30; Alex uses W in the morning):
`m7g\stopat.py` (sha256 da14a2bfc157ff8da44ac7ce50f5baa50bb25a7ad9bdf3616004cd4d07febfd8; pid 27600),
not committed, watches the run's rows from 09:27 and, at the first session end or parts row after
it, asks the job to stop (`wjob.py stop`); the engine then stops before the next session's first
window, and the next job resumes from the rows. Expected length, from M6b's measured parts (about
29 s of TIME-WAIT wait before each of 512 churn and open-loop windows, 6.3 s per window, the
session fingerprints, the warm-up, the timer part's 128 runs and the split part's 80 replicates):
about 6 h without reruns, so near 08:15 at the earliest.

To resume W's run in the next quiet W window, if it stopped at 09:27 or later (same `--out`, a new
`--job` name, no `--allow-noisy`, UTF-8 mode):

    set PYTHONUTF8=1
    C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe C:\Users\alext\lab\p3\m7g\pilot-src2\bench\run\wjob.py run --dir C:\Users\alext\lab\p3\m7g\wpilot --name wp2 -- C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe C:\Users\alext\lab\p3\m7g\pilot-src2\bench\run\wpilot_run.py --build C:\Users\alext\lab\p3\m7g\records-ff2679c-W\build-release --out C:\Users\alext\lab\p3\pilot-W --job wp2 --seeds C:\Users\alext\lab\p3\m7g\pilot-src2\design\seeds.json --code-freeze ff2679cc89d23e08a817308c9aeba7901e056fef --gate C:\Users\alext\lab\p3\m7g\records-ff2679c-W\gate-W.json

The pilot entry needs both hosts' pilots (section 8 step 6: R_C and m_C span L and W), so the
simulation, `pilot.py` and the entry wait for W's run to end; no one-port window of any kind runs
before the entry is committed.

Lab journal: five development lines (wf1 to wf4 and wdev1), Papers bc3338a.

### 10. Where it stands

CODE_FREEZE = ff2679c. Running: L's A/A pilot (pl1, expected end about 04:30) and W's (wp1, about
6 h, near 08:15 at the earliest; stopped between sessions from 09:27 if not done). Next: when both
have ended, the simulation and `pilot.py` at ANALYSIS_COMMIT 9de26d6 on the pinned numpy, then the
pilot entry; then section 8 step 7.

## M7 checklist

The code freeze needs these, in this order. Where the order differs from the list the coordinator
gave, the reason is in the item. Each item names what decides it.

1. **Open decisions that block the freeze** (the coordinator's, or Alex's where named). All are
   resolved ("M7 fixes, 2026-10-03"; "M7c follow-up, 2026-10-04"), except what the follow-up's
   "For the coordinator" leaves open:
   - Resolved (d15e775): M5's reading 4. The reassembler refuses at a record header that would
     take the handshake bytes past B_CH, and the storage stays within B_CH and 5 bytes per
     record; case B sits at that bound (the reading is in "M7 fixes", item 2, for the coordinator).
   - Resolved (d16d8b4): `ANALYSIS_COMMIT` = 7364fbbbf356e22bb0d6a74b0b9bc29b62c3534b, logged,
     with its tests on the pinned numpy ("M7c follow-up", "ANALYSIS_COMMIT"). Moved (2055e63):
     `ANALYSIS_COMMIT` = 9de26d614c85b606fb5169ed16528b7189a87ac4, W's WL4 on the cycles and W's
     churn h2c and MQTT never resolved ("M7e", item 1).
   - Resolved (97a5363): the harnesses' LeakSanitizer. Both end on SIGTERM by a normal exit, and
     a harness record is green only if every run ended so; no gap is declared.
   - Resolved (3382bb8): the route without ALPN stays in all five proxies, logged.
   - Resolved (c1b4283): `b3.py`'s rows name the binaries they ran, so `check_rows.py` binds them.
   - Resolved (3382bb8): `N_BG_TLS` = `N_BG_MQTT` = `N_BG_SILENT` = 64, logged. How the mixed cell
     holds its background: the generator change landed (0b63d62, `opcase hold`, M7c); the
     keep-alive background as WL3's closed loop, the silent connections on the dedicated HTTP/1.1
     port and the placement logged (13004bc, items 1, 2, 7 and 8).
   - Resolved (13004bc): M7c's items 1, 2, 3 and 5 for the coordinator (the mixed cell, B3's
     other-mode dispatch, the TLS variants, M2's rate), logged as the entry "M7c's open items,
     before the code freeze", the runners changed to match.
   - Resolved (9d7aa15, 1bc1e53): M7c's items 4, 6, 7 and 9, and M2's backend listener (a
     `SO_REUSEPORT` group), logged as the entry "The pre-freeze items on L (M7d)" ("M7d"). Open:
     M2's TLS cells, whose rate sessions are invalid under either listener ("M7d", "For the
     coordinator and Alex", item 1), before item 8.
2. **The final merge of `m6b-windows`** into main, then the build of the merged tree:
   - Merged at 74dc539 (fa8be6d, "M7c follow-up"); a later commit of the branch needs another
     merge.
   - L: Debug, ASan+UBSan, TSan and MSan, the whole suite in each (as `checks_job.sh` ran M5's).
     Done: chk4 at fa8be6d (394 of 394) and chk5 at 8e77e28 (398 of 398), 0 warnings and 0 report
     lines in each build.
   - W: Debug and MSVC ASan, the whole suite, with Alex's yes when W is free. Open: W has built
     none of M7c's C++, of the merge or of 236ee3c. Since then: M6d's suite on W at 330c961 (163 of
     163); M7e's C++ (opcase and its holder on Windows) only compiled (one Release build, 0
     warnings), its suite on W still open. M7 freeze session: at 91f2f77 Debug and ASan built
     with 0 warnings and passed 164 of 165 with 0 report lines (`gen.hold.IOCP` and opcase in
     `gen.binaries` passed); `run.test_wrunner`'s cycle-rate check failed (CPU 0, outside the
     quiet check, while W was in use), fixed in 7a4063c; W's suites at 7a4063c not run (W's quiet
     check refused every attempt). L at 7a4063c: chk10, 399 of 399 in four builds.
   - Check `bench/build_inputs.py`'s `TARGETS["W"]` and `BINARIES["W"]` against the merged tree
     (M6b built opgen on Windows): a compiled target added or removed stops the hash until the
     list is right. Done: they hold (no target added or removed).
3. **The pins, re-read before the records**, since every record carries the sha256 of
   `bench/cmake/pins.cmake` and the gate refuses a build whose pins differ from its records':
   - The JDK. Section 2.3: Netty and Jetty "on the latest LTS JDK at the code freeze"; section
     9.1: the JDK (latest LTS) is pinned "by archive URL and sha256"; section 2.3: "each change is
     recorded in the revision log then". The rule: on the day of the freeze, before its commit,
     read Adoptium's Temurin 25 releases. If a build newer than 25.0.4.1+1 (25.0.5 is due in
     October) is published, pin it (URL and the published sha256, checked against the archive),
     install it (`install.sh jdk`), build the Java harnesses again, run their probes and route
     checks, write out the heap bounds again from L's MemTotal with it (M4b-2's list), and log
     the change. If none is published by the freeze commit, 25.0.4.1+1 stays: "at the code freeze"
     is fixed by that commit, and a JDK released after it changes nothing; adopting one later
     would be a later change under section 8 (new records, the runs of the old build archived).
   - The others of section 9.1's row, the same way: OpenSSL (the latest 3.5 release at the freeze,
     section 2.1), nghttp2, every competitor (section 2.3: a newer release at the freeze replaces
     the survey's), caddy-l4's commit (Appendix B: "read again at the code freeze"), xcaddy, the
     Rust toolchain; Netty's allocators read again (M4b-2's reading 11). A changed library is
     rebuilt in every flavour (`build_deps.sh` on L, `build_deps.ps1` on W) before item 9.
   - Read on 2026-10-04 at 04:48 +0300 (M7d, logged in its entry, item 6): no pin changes;
     Temurin 25.0.5 not published; Caddy's v2.11.6 and v2.11.7 and Rust 1.99.0 do not move a pin
     (two readings). Read again on the freeze day, the JDK first. (M7 freeze session: one
     read-only look at Adoptium's API at 17:01, jdk-25.0.4.1+1 still the latest GA build; not the
     freeze day's read, which did not run.)
4. **The `/sys/kernel/slab/` re-read on L** (section 9.1): as root, read only: that
   `/proc/slabinfo` exists; for skbuff_head_cache, skbuff_fclone_cache and skbuff_small_head, the
   name `/proc/slabinfo` lists each under and the co-tenants of a merged one (the links in
   `/sys/kernel/slab/`, `aliases`); the page size. Compared with WL7's reading and the re-read of
   2026-10-03 12:11 (the entry "Host change before the code freeze", item 1); a difference is
   handled by WL7's rule for merged caches and logged. Done on 2026-10-04 at 04:50 +0300 (M7d,
   its entry's item 7): unchanged.
5. **The seeds entry** (sections 4.7, 8 step 2 and 9.1): one revision-log entry fixing every seed,
   `SEED_ORDER_C_L`, `SEED_ORDER_C_W`, `SEED_ORDER_B_L`, `SEED_ORDER_M_L`, `SEED_ORDER_M_W`,
   `SEED_ORDER_S_L`, `SEED_ORDER_S_W`, `SEED_BOOT_C`, `SEED_BOOT_B`, `SEED_BOOT_M`,
   `SEED_BOOT_S`, `SEED_PILOT_L`, `SEED_PILOT_W` and `SEED_SIM`, each checked against the Papers
   repo's `lab/journal.jsonl` as used by no earlier run, committed before the code-freeze commit
   and never changed after. Done (M7d): the entry "The seeds of section 4.7 (M7d)", its procedure
   in 45d8b03 before the draw, its values and `design/seeds.json` in 2e6b539.
6. **The values engineering set**, ready for the code freeze's entry (section 9.1): `K_SRC` = 16
   (logged, M3 entry item 9), `N_ACCEPTEX` = 64 (M6a), `RELAY_BUF` = 4096 bytes per direction
   beside each proxy's default, the three background counts, 64 each (logged, entry "The code
   freeze's preparation (M7)", item 2), ℓ from `tests/fixtures/tls/clienthello.hex`, and the pins
   as item 3 leaves them. Read in M7d (its entry's item 8): `K_SRC` 16 holds (no failed connect
   since the M3 entry), `N_ACCEPTEX` 64, `RELAY_BUF` 4096, the counts 64, ℓ 206.
7. **The final `bench/coverage.json`**, in the freeze commit: every declared gap of section 11 as
   now, plus what item 2 decides (any third-party library W cannot build with MSVC's ASan, which
   section 11 asks to declare "before the code freeze"); the harnesses' leak check runs since
   97a5363, so it needs no gap. One
   gap may go: OpenSSL's tsan flavour is built with `-fsanitize=thread` (`build_deps.sh`), so if
   the TSan record is green, section 11 lets the revision log record that OpenSSL ran under TSan
   and the gap "OpenSSL under TSan" is removed. Done in M7d (its entry's item 9; 8057e52): the
   suite passed under TSan with the instrumented OpenSSL, the gap is removed, every other gap read
   true; the Windows gap waits for item 2's W build.
8. **The code-freeze commit, `CODE_FREEZE`** (section 8 step 3): one commit of the server, the
   generators, the holder, the harnesses, the pins and the tests, with the suite passing on L
   (four builds) and W (Debug, ASan). From then on no commit may touch a first-party input
   (anything a target compiles, a harness input, `pins.cmake`): records match by inputs hash, so
   a commit of docs only (hypotheses.md, status.md) keeps them, and any other is a later change
   under section 8. The gate sees compiled targets and harness inputs only, not the Python half
   of the suite (`bench/*.py`, `bench/run/*.py`, `bench/competitors/*.py`) or `coverage.json`,
   which section 8 freezes with "the tests" too: before any frozen run, `git diff
   CODE_FREEZE..HEAD -- bench tests CMakeLists.txt` must show nothing, checked by hand.
9. **The sanitizer records at `CODE_FREEZE`** (section 11, rule D5), for every first-party input,
   on every platform:
   - L, one lab job from a fresh clone at `CODE_FREEZE`:
     `setsid nohup bash <clone>/bench/run/lab_job.sh <dir> records bash <clone>/bench/records_job.sh <OUT> <RECORDS>`.
     It makes oneport's ASan+UBSan and TSan records at once, then MSan (the server, opgen,
     opcase, ophold, the suite and the libraries they link, on epoll and io_uring); then the Go
     harness's ASan (`go build -asan`) and race (`go build -race`) records and the Rust harness's
     ASan and TSan records, TSan with tokio's suppression (`tsan.supp`, the coordinator's
     decision); the JVM harnesses have none, their gap declared whole. Every record must be
     green; the job stops at the first that is not. Logs: `~/lab/records-logs/<record>/` and its
     `.tar.gz` with a sha256. Set `REPO_URL` to the paper's repository URL, as P2's records name
     theirs; unset, a record names the clone's origin, L's bare repository path.
   - W: `bench/sanitize_oneport.ps1 -Records <dir>` at `CODE_FREEZE`, MSVC 19.51.36246 ASan,
     the server, opgen and the suite, with Alex's yes when W is free.
   - The records go into the Papers repo's `lab/sanitizer-records/`, committed there (pushed only
     with Alex's yes). `lab/bin/test_report_pattern.sh` passes on the Papers repo.
10. **The gate and the inputs hash of every measured binary**: `records_job.sh`'s gate step writes
    `gate-L.json` and `measured-L.json` (every target's inputs hash, the harnesses', and the
    sha256 of oneport, opgen, opcase, ophold and each harness output); on W,
    `build_inputs.py --host W` on the measured Release build, then `check_records.py --host W`.
    Every runner's rows name the binaries they ran, and `check_rows.py` passes them against these
    gates before any number is cited. The pilot and every frozen run use the binaries and
    harnesses of the records job's `build-release` (or show equal sha256 before any window): the
    C++ binaries reproduced byte for byte across build directories (dryrun4 against m5m3c), but
    the Rust harness's release profile may embed its checkout path, so a harness built elsewhere
    can differ and `check_rows.py` would refuse its rows.
11. **The code freeze's revision-log entry** (section 8 step 3, section 9.1): `CODE_FREEZE`, the
    values of item 6, the pins as frozen, the slab re-read of item 4, the records' names and the
    gates' sha256. Then section 8 step 4, on the frozen binary in dedicated mode only.


- `lab/bin/test_report_pattern.sh` lists the record writers by path. Done: Papers commit cf80eea
  added `papers/one-port/bench/oneport_record.py` to it.
- The Papers repo's submodule pointer for `papers/one-port` (the coordinator's commit).
- M3's lab journal: 19 lines in the Papers repo's `lab/journal.jsonl`, Papers commit 4fa459a
  (local, not pushed), every one marked development.
- The readings of the frozen text are in the revision log of hypotheses.md: M1's (c8a0525), M2a's
  with the coordinator's three decisions (30b5be4), and M2b's with the rule of I29 (89a96c5).
- No lab-journal line for the merge or for NOTRACK: no window ran.
- M4a's lab journal: 4 lines in the Papers repo's `lab/journal.jsonl`, Papers commit 52d39da (local,
  not pushed), every one marked development.
- M4a's readings of the frozen text (M4a, "Readings of the frozen text in M4a") and the open MHz rule
  on kernel 7.2.6 are for the coordinator.
- M4b-1's lab journal: 6 lines in the Papers repo's `lab/journal.jsonl`, Papers commits b651c97 and
  a7d99c0 (local, not pushed), every one marked development. M4a's readings and the two accepted deviations are
  logged (b77dd44), with the host clock floor and the note on sslh-ev.
- M4b-1's open items for the coordinator and Alex: section 10's check against perf trace -s; THP on L
  and B3's settling rule (M4b-1, "Open for the coordinator and Alex").
- M4b-1's two open items are decided and logged (M4b-2, step 0): THP at madvise for every lab job
  (Alex), section 10's check against perf stat (the coordinator).
- M4b-2's lab journal: 2 lines in the Papers repo's `lab/journal.jsonl`, Papers commits 5341785 and
  5846aaf (local, not pushed), each marked development.
- M4b-2's readings of the frozen text and its open items (the Rust harness's TSan suppression; the
  server's in-process footprint with a partial ClientHello) are for the coordinator (M4b-2).
- M5's lab journal: 10 lines in the Papers repo's `lab/journal.jsonl`, Papers commits 0c4d67d and
  6b82bb0 (local, not pushed), each marked development.
- M5's items for the coordinator: proposal I11's and I15's `IORING_OP_RECV`, now `IORING_OP_READ`; the
  revision log's M3 item 2 example list; M4b-1's readings still unlogged (M5, "Readings, and changes
  against the proposal's text").
- M7 preparation: Papers 53b929a (local, not pushed) fixes `lab/bin/test_report_pattern.sh`'s
  writer list. No lab-journal line: no window ran. The submodule pointer is the coordinator's.
  For the coordinator: M5's reading 4 (not logged), the five proxies against the brief's four, and
  the blockers at the top of the M7 checklist.
- M7 fixes: no lab-journal line, since no window ran (builds, tests, the leak checks and the dry
  run are untimed). No Papers commit. The submodule pointer is the coordinator's. For the
  coordinator: the bound's reading for case B, and how the mixed cell holds its background
  ("M7 fixes", items 2 and 5).
- M7c: 16 lab-journal lines (the end-to-end jobs e2e1 and e2e2, one line per runner, each marked
  development), Papers commit 4af4be6 (local, not pushed). The submodule pointer is the
  coordinator's. For the coordinator: M7c's items ("M7c", "For the coordinator"); five readings
  logged (the revision log's entry "Readings fixed during engineering (M7c)").
- M7c follow-up: Papers 4af4be6 and 3cb0bcd pushed; 2ce46ec bumps the submodule to fa8be6d;
  ae30f03, 1 lab-journal line (e2e4, development); then a bump to this section's commit. Logged:
  the entries "M7c's open items, before the code freeze" and "ANALYSIS_COMMIT, before the code
  freeze". For the coordinator: "M7c follow-up", "For the coordinator".
- M7d: Papers 7a838e6, 2 lab-journal lines (job m2l, development); then a bump to this section's
  commit. Logged: the entries "The pre-freeze items on L (M7d), before the code freeze" and "The
  seeds of section 4.7 (M7d), before the code freeze". For the coordinator and Alex: "M7d", "For
  the coordinator and Alex".
- M7e: no lab-journal line, since no window ran (the analysis tests, the suite and one Windows
  compile check are untimed); then a bump to this section's commit. Logged: the entries
  "ANALYSIS_COMMIT moved (M7e), before the code freeze" and "The job's warm-up and W's runners
  (M7e), before the code freeze". For the coordinator: "M7e", its "What the freeze still needs"
  and W's functional check (its section 6).
- M7 freeze session: no lab-journal line, since no window ran (the suites on W and L only); then a
  bump to this section's commit. Nothing logged in hypotheses.md. For the coordinator and Alex: "M7
  freeze session", its last part.

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
  under `~/lab/records-logs/`. M1 makes the first records. (Changed by the M1 brief: M1's
  sanitizer runs are development checks, and records are made at the code freeze, M7. M1 did not
  write the driver.)
- The 25 hard cases of Appendix A of hypotheses.md as a deterministic CTest suite, run under every
  sanitizer.
- On L: the work tree `~/lab/p3/one-port` and the `lab` remote; push, then
  `git -C ~/lab/p3/one-port pull --ff-only`.

## What M2 starts from

- The server on epoll:
  - `bench/server/worker.{hpp,cpp}` and `handlers.cpp`, with the outcome counters and the timed
    events;
  - the deadline lists, which the io_uring wait uses through its timeout argument;
  - the listener setup in `listeners.cpp`, where `not_served_in_m1()` lists what M2 opens.
- io_uring:
  - the multishot accept;
  - replay into provided buffers;
  - peek by `IORING_OP_POLL_ADD` with `POLLRDHUP` and a synchronous `MSG_PEEK`;
  - the check of 1(b) as a non-waiting reap where a receive is posted with a buffer;
  - the RK4 pin test (the poll completes only at `SO_RCVLOWAT`), after
    `server.kernel_rcvlowat_et`;
  - the counters of `io_uring_enter` calls and submissions by opcode.
  `UringLoop` has only `start`, `wait` and `stop` so far.
- Handlers. Replace the M1 stubs in `handlers.cpp` with:
  - h2 (nghttp2);
  - TLS (OpenSSL through memory BIOs, the settings of I24);
  - MQTT, SSH and SMTP (I26).
  Then in `bench/cases/cases.cpp`, the stub variants of HC1 to HC3, HC5, HC7 and HC15 become
  full: their `Reply::dedicated` stays, and the transcripts become the real ones. HC7's 500 and
  HC20's handshake become checkable.
- Relay and stub mode:
  - the front's loopback connection and the copy of rule E (user-space with `RELAY_BUF`, or
    `splice`);
  - the pass-through ClientHello parser with B_CH and its SNI and ALPN routing (HC20);
  - stub mode (I18).
  The pending entries `case.*.epoll.relay.*` and `case.*.io_uring.*` then become run entries.
- Prerequisites on L. Nothing was installed in M1; each goes into `~/opt` with a sha256 under the
  rules above:
  - OpenSSL from the 3.5 LTS series, built from its pinned tarball (L has 3.6.4);
  - nghttp2 v1.70.0 from its pinned source, built with each sanitizer's flags (Z3), MSan against
    the MSan libc++;
  - then the recorded ClientHello of I18, from that OpenSSL with the settings of I24, replacing
    the synthetic one of `opcase`.
- Nothing blocks M2 beyond these prerequisites.

## What M2b starts from

- The handlers are backend-neutral above the socket: the protocol steps (`apps.cpp`, `h2.cpp`)
  take bytes and append output, and TLS reads and writes through the worker's BIO, never a
  socket. What is epoll's is the read (`read_into`), the send and the EPOLLOUT queue (`emit`,
  `flush`) in `handlers.cpp`. io_uring needs its own forms of those three: a receive into a
  provided buffer, a send, and the queue's wait for writability, with the same rule that a
  connection reads nothing while its queue holds bytes.
- io_uring, as M1 listed it: the multishot accept; replay into provided buffers; peek by
  `IORING_OP_POLL_ADD` with `POLLRDHUP` and a synchronous `MSG_PEEK`; the check of 1(b) as a
  non-waiting reap where a receive is posted with a buffer; the RK4 pin test; the counters of
  `io_uring_enter` calls and submissions by opcode.
- Relay and stub mode:
  - the front's loopback connection to the backend chosen by class, the replayed bytes first,
    then the copy both ways, user-space with `RELAY_BUF` or `splice`, both as flag values
    (rule E);
  - pass-through routing by SNI and ALPN with `bench/server/clienthello.hpp`, reassembling up
    to B_CH: HC20's other half;
  - stub mode (I18): the TLS stub reads one record and writes the 13-byte body; the recorded
    ClientHello is what opgen will send to it.
  The pending entries `case.*.epoll.relay.*` and `case.*.io_uring.*` (150) then become run
  entries.
- I29's "payload bytes copied in user space": the HTTP/1.1 and SMTP compaction counts in
  `bytes_copied`, the output tail copied into a connection's queue does not yet. Both modes run
  the same code, so no cost contrast is touched; M2b's relay copy should settle one rule for all
  three and apply it.
- On L everything M2b needs is installed: OpenSSL 3.5.9 and nghttp2 1.70.0 in four flavours in
  `~/opt`, the test certificate, the recorded ClientHello. Nothing blocks M2b.

## What M3 starts from

- The binary serves every Linux arm: `--mode one-port`, `dedicated` or `stub`; `--detect replay` or
  `peek`; `--dispatch inproc` or `relay` (with `--relay-port` and `--relay-copy`); `--backend
  epoll` or `io_uring`. With `--port` its listeners take fixed consecutive ports; it prints one
  "listening" line per port and the connection state's size, and its counters (I29, now with
  io_uring's `io_uring_enter` calls and submissions by opcode, the relay's, and `out_waits`) at
  SIGTERM. M3's A/A work runs dedicated mode only, on both backends.
- `opgen` is M3's to write (I30): the exchanges of WL1 to WL3 per protocol, with the same OpenSSL
  build and settings (`bench/tls`), static-table h2 frames, `IP_BIND_ADDRESS_NO_PORT` and one block
  of `K_SRC` addresses of 127.0.0.0/8 per window. `K_SRC` is set from its development runs (M0's
  note). For M3's stub exchange the recorded ClientHello (`opcase::recorded_client_hello()`,
  `tests/fixtures/tls/clienthello.hex`) is what `opgen` sends; stub mode answers one record with
  the 13-byte body and closes.
- `ophold` (B3's kernel baseline) and the per-connection decision record of the binary that WL8
  needs against a server in its own process (M1's note) are still to build.
- Engineering options left for M5, not results: io_uring's output is a synchronous `send`
  (`IORING_OP_SEND` is the alternative); `RELAY_BUF` is 4096 bytes, to be reported beside each
  proxy's default; whether `IORING_OP_SPLICE` runs in the kernel's worker threads on L was not
  measured, only tested to work.
- For the coordinator: the seven readings of M2b are in the second revision-log entry; reading 4
  (no timer on pass-through's wait for the whole ClientHello) leaves a relayed TLS connection with
  a partial ClientHello open until its peer ends it, as in-process TLS is. B3's partial-ClientHello
  windows close every connection by reset at 30 s, so they are not affected.
- Nothing blocks M3.

## What M4 starts from

- The harness: `opgen` for every cost, M1, M2 and M3 load (HTTP/1.1, h2c, TLS, MQTT, SSH, the TLS
  stub exchange; churn closed and open, keep-alive), `opcase open` and `ophold` for WL7, and the
  window runner (`bench/run`): `window.py` for one window, `aa.py` for sessions, `b3.py` for WL7's
  layout, `footprint.py` for WL7's readings, `lab_job.sh` for jobs under the lock.
- What the runner does not do yet, for M4 and M5:
  - competitors: starting a proxy or library under its configuration (Appendix B) instead of the
    server; `window.py` starts only `oneport` in dedicated mode and refuses any other mode
    (`guard_mode`), which M4 relaxes for the competitors and M5 for one-port windows against them
    (section 8 step 2: one-port against a competitor, never against dedicated mode);
  - hand-off cells: the front on CPU 14, the backend on CPUs 10 and 12, opgen on 2 to 9; WL6's CPU
    of the front and the backend together; the backend's 90% rule;
  - B3: the server or a competitor as the system in `b3.py` (U over its processes, the stub
    backend left out), the partial-ClientHello case against them, the collectors' steps (`jcmd`,
    `FreeOSMemory`, caddy's heap profile), and the server's timers at 60 s (step 0, item 1);
  - M3's listen overflows recorded per window, not a validity rule;
  - section 10's untimed `perf trace -s` window per cost cell.
- The A/A spread on L (above) says the harness's noise is far inside the 2% margin for the cells
  measured; the pilot (section 4.6) sizes R_C on the frozen binary, and nothing here enters it.
- M6a is merged (bbd13f7): the IOCP backend, the Windows dependency builds and the suite on IOCP
  are in main, green on W (Debug, ASan) and on L (Debug and the three sanitizer builds). What M6b
  needs is in the M6a section.
- Open for the coordinator and Alex:
  - L's connection tracking: NOTRACK for loopback is approved and built (367e0b0), and cannot run
    until L boots an installed kernel (a reboot, Alex's decision; "L's connection tracking: NOTRACK
    for loopback", above). Until then lab jobs run with `ONEPORT_NOTRACK=off`, the table wait and
    the longer time plan; the first job after the reboot tests the add and removal path on a job
    with no window;
  - M6a's reading 7, not logged: rule E's posted receive form holds the handler's buffer from accept,
    against B2(d) and section 2.1's "no data buffer while no byte has arrived"; to be decided before
    rule E chooses the IOCP receive form, which comes before the W pilot (M6a, "Open for the
    coordinator");
  - the per-connection decision record of the binary that WL8 needs against a server in its own
    process (M1's note) is still to build;
  - `RELAY_BUF`, `IORING_OP_SEND` and splice's worker threads: M2b's engineering options for M5.
- Nothing blocks M4's competitor builds; their windows inherit the connection-tracking wait, and
  their lab jobs need `ONEPORT_NOTRACK=off` until the reboot.

## What M4b starts from

- The proxies are installed in `~/opt` on L (`bench/competitors/install.sh`, the pins of 55b2cb8), each
  with its M3 and B3 configuration and a probe that passes (M4a). The hand-off runner
  (`bench/run/handoff.py`) times the server's one-port relay against them; `window.guard_pair` refuses
  one-port against dedicated, and in M4a dedicated against a competitor.
- For M4b, the libraries of section 2.3 (Netty, Jetty, cmux, hyper-util): their pins (the JDK, the Rust
  toolchain), harnesses with cases and B3 configurations, their Go and Rust harnesses' ASan+UBSan and
  TSan records (section 11), and a probe each; `probe.py`'s expectations take new systems.
- Not built yet: the proxies' cases configurations (every route their features cover, the matched
  timers, the fallback; Appendix B), which section 10's competitor hard cases need; B3 with a
  competitor as the system in `b3.py` (U over its processes, the stub left out, the partial case, the
  collectors' steps, caddy-l4's heap profile); section 10's untimed `perf trace -s` windows.
- Open for the coordinator and Alex:
  - section 7's MHz rule on kernel 7.2.6: every window on L fails it (revision log, "Host change before
    the code freeze", item 4; M4a, step 0, 1). Until it is decided, no window on L is valid;
  - sslh-ev loses 0.6% of exchanges at M3's saturation (timeouts at 1 s), so its M3 windows fail the
    0.1% error rule as configured; the cause is not isolated (M4a, "Development windows");
  - M4a's eleven readings of the frozen text, for the revision log;
  - from before: the per-connection decision record WL8 needs against a server in its own process;
    `RELAY_BUF`, `IORING_OP_SEND` and splice's worker threads (M5); more than one worker on IOCP (M6b).
- M5 can time the server's relay against nginx, HAProxy, Envoy and caddy-l4 as soon as the MHz rule is
  settled; in one development session each (m3dev1) the relay was ahead of all four, nginx by the least
  (ratios 1.017 and 1.025).

## What M4b-2 starts from

- Every lab job runs with the clock floor (clockfloor.sh inside lab_job.sh); section 7's MHz rule
  passes again on 7.2.6 (aa-floor1). The proxies have their cases configurations (both kinds, both
  timer settings) and a route check that passes; b3.py takes a relay system; systrace.py runs
  section 10's untimed windows.
- For the in-process libraries of section 2.3 (Netty 4.2.18.Final, Jetty 12.1.13, cmux v0.1.5 with Go
  net/http on go1.27.1, hyper-util 0.1.21):
  - pins: L has OpenJDK 26.0.2.1 from its packages, which is not an LTS release; section 2.3 asks for
    the latest LTS JDK at the code freeze (25 on 2026-10-03), so a pinned JDK goes into `~/opt` under
    the install policy. Rust is Arch's 1.98.1 (cargo 1.98.1) with no rustup; section 11's ASan+UBSan
    and TSan records of the Rust harness need a sanitizer-capable (nightly) toolchain, pinned. go1.27.1
    is on L.
  - harnesses with their cases and B3 configurations (Appendix B: one each, B3 starting from cases),
    each with a probe; `probe.py`'s expectations and `cases_check.py`'s COVERS take the new systems.
  - b3.py: an in-process system (no stub; the server in-process against it, section 5.2) and the
    collectors' steps of WL7 (`jcmd <pid> GC.run` and `GC.heap_info` for the JVM systems,
    `debug.FreeOSMemory` and `HeapInuse` in the cmux harness); caddy-l4's step is built.
  - section 11's records for the Go and Rust harnesses (ASan with UBSan, TSan), their MSan gap
    declared in `bench/coverage.json`; the Java harnesses' gap declared whole.
- Open, from M4b-1 (above): section 10's check against perf trace -s; THP on L and B3's settling rule
  (it will weigh most on the JVM and Go heaps, so it is worth deciding before their B3 windows);
  sslh-ev's M3 cells.
- Nothing in M4b-1 blocks M4b-2's builds.

## What M5 starts from

- Every lab job runs with the clock floor, THP at `madvise` and NOTRACK (`lab_job.sh`), each set back
  at the job's end; each session's fingerprint records all three. B3 windows of the proxies settle
  (b3thp1).
- The in-process libraries are pinned (Temurin 25.0.4.1+1, Netty 4.2.18.Final, Jetty 12.1.13, cmux
  v0.1.5 on go1.27.1, hyper-util 0.1.21 on rustc 1.98.1), their third-party parts in `~/opt` on L
  (`install.sh jdk netty jetty`), their harnesses built per checkout (`build_harnesses.sh <build>/harness
  release`), each with a cases and a B3 configuration and a probe that passes. `b3.py` runs every B3
  system of section 6.2, the server's relay and in-process arms on either backend, with WL7's
  collector steps; `cases_check.py` checks the libraries' routes.
- Development B3 data (b3lib2) puts the server's in-process footprint with a partial ClientHello at
  49.7 kB of U per pending connection, above Netty (2.3 kB), cmux (12.5 kB) and Jetty (32.1 kB):
  their cells are descriptive, but rule D2 makes it engineering for M5 (M4b-2, "Open"). In the
  silent case the server's in-process W is below every library's (7,362 on epoll, 8,006 on io_uring).
- Engineering options left for M5, as before: `RELAY_BUF`, `IORING_OP_SEND`, splice's worker threads.
- Open for the coordinator and Alex (M4b-2, "Open"): the Rust harness's TSan suppression; sslh-ev's M3
  cells; the competitors' hard cases need an `opcase` mode against a system by port; the
  per-connection decision record WL8 needs; more than one worker on IOCP (M6b).
- The code freeze (M7) must: name the harness targets in its records driver as `coverage.json` does;
  read the JDK's latest LTS build again (25.0.5 is due in October); write out the heap bounds again
  from L's MemTotal with the pinned JDK; read caddy-l4's pin and Netty's allocators again.
- Nothing in M4b-2 blocks M5.

## What M7 starts from

- The code at 681c58e (ac84f2d's server, generators and harnesses; 681c58e changed only
  `systrace.py`'s check), green in all four builds on L (m5chk5). M5's exit criteria stand as in
  M5's table: 1, 3 and 5 met; 2 met against nginx, HAProxy, Envoy and caddy-l4, not against
  sslh-ev (out of reach by construction, recorded); 4 met at the end.
- For the coordinator before the freeze (M5, "Readings, and changes against the proposal's text"):
  io_uring's receives are `IORING_OP_READ` where proposal I11 and I15 say `IORING_OP_RECV`; the
  revision log's M3 item 2 still says "the two `TCP_NODELAY` of a relayed connection" (now one,
  the listener's inherited); and M4b-1's nine readings are still not in the revision log.
- M7 must still: write the records driver with the harness targets as `coverage.json` names them,
  each harness's inputs hash from `bench/competitors/harness_inputs.py` and hyper-util's TSan run
  with `TSAN_OPTIONS=suppressions=` its `tsan.supp`; fix the seeds of section 4.7 and
  `ANALYSIS_COMMIT` (section 8, step 2); record the values engineering set (`K_SRC`, `N_ACCEPTEX`,
  `RELAY_BUF`, the background counts, l, the pins); read the JDK's latest LTS build again (25.0.5),
  the heap bounds, the slab caches in sysfs, caddy-l4's pin and Netty's allocators (M4b-2's list).
- W: M5 changed `bench/server/handlers.cpp` (the TLS deferral, the receive counters), which IOCP
  compiles, and added `bench/cases/run_cases.cpp` and `bench/server/record.cpp` to libraries W
  builds; none of it was built or run on W. M6b's merge with main must build them and run W's suite.
- Not done in M5, as before: `RELAY_BUF` beside each proxy's default, `IORING_OP_SEND`, and whether
  `IORING_OP_SPLICE` runs in the kernel's worker threads (rule E's relay copy stays user space as
  proposed); more than one worker on IOCP (M6b).
- Ready for the runs after the pilot entry: `oneport --record` and `opcase case` for WL8's hard-case
  runs and the competitors' descriptive table (section 10), whose runner, which starts each system
  in the setup a variant names and judges the outcome, is still to write.
- Nothing in M5 blocks M7.
