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
| M4 | Competitors | next |
| M5 | Iterate until it wins | |
| M6 | Windows | M6a (the dependencies and the IOCP backend) done, 2026-10-03, merged into main in bbd13f7 (below); M6b (the Windows harness) open |
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

## Follow-ups outside this repository

- `lab/bin/test_report_pattern.sh` lists the record writers by path. Done: Papers commit cf80eea
  added `papers/one-port/bench/oneport_record.py` to it.
- The Papers repo's submodule pointer for `papers/one-port` (the coordinator's commit).
- M3's lab journal: 19 lines in the Papers repo's `lab/journal.jsonl`, Papers commit 4fa459a
  (local, not pushed), every one marked development.
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
- Open for the coordinator and Alex:
  - L's connection tracking (above): a host change, or the harness's wait and the longer time plan;
  - the per-connection decision record of the binary that WL8 needs against a server in its own
    process (M1's note) is still to build;
  - `RELAY_BUF`, `IORING_OP_SEND` and splice's worker threads: M2b's engineering options for M5.
- Nothing blocks M4's competitor builds; their windows inherit the connection-tracking wait.
