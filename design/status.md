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
| M3 | Harness and A/A-noise engineering, in dedicated mode only | next |
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

## Follow-ups outside this repository

- `lab/bin/test_report_pattern.sh` lists the record writers by path. Done: Papers commit cf80eea
  added `papers/one-port/bench/oneport_record.py` to it.
- The Papers repo's submodule pointer for `papers/one-port` (the coordinator's commit).
- The readings of the frozen text are in the revision log of hypotheses.md: M1's (c8a0525), M2a's
  with the coordinator's three decisions (30b5be4), and M2b's with the rule of I29 (89a96c5).

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
