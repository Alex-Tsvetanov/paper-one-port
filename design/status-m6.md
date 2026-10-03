# P3 engineering status, M6a (Windows: dependencies and the IOCP backend)

M6a ran on W on 2026-10-03, on branch `m6-windows` from b0438e1, beside M3 on L. It is kept here,
not in design/status.md, so the two milestones do not conflict; the coordinator merges both.
Nothing in this file is a result: no window ran on W, and the sanitizer runs are development
checks, not records.

## Commits (m6-windows)

| Commit | Message (first line, shortened) |
|---|---|
| 2957c40 | chore: build_deps.ps1 builds the pinned OpenSSL 3.5.9 and nghttp2 1.70.0 on W with MSVC, release and asan flavours |
| a126467 | feat: the IOCP loop dequeues up to 64 completions per wait with GetQueuedCompletionStatusEx, reaps without waiting (1(b)), drains after stop, associates sockets, counts its calls |
| ec09504 | feat: --iocp-accept no-buffer\|buffer, the AcceptEx form of hypotheses.md section 10; flag tests |
| 372dcc5 | feat: the server on IOCP (Windows) |
| 519b818 | test: the suite on IOCP |

This file and design/w-procedure.md are committed after them. Each code commit was built alone on
W from an exported copy (`git archive`, not a worktree), Debug, MSVC 19.51.36246, Ninja, with no
warning, and passed its own suite: a126467 and ec09504 105 CTest entries (55 run, 50 pending),
372dcc5 106 (56 run, 50 pending), 519b818 133 (all run). Logs in
`C:\Users\alext\lab\p3\m6a-check\commits\<sha>\`. Nothing is pushed.

## Tools (Alex's approval of 2026-10-02)

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

## The dependency builds

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

## The IOCP backend (372dcc5)

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

### Design choices of M6a

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

## The IOCP pins (tested before use, proposal I11)

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

## The suite on W at 519b818

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

## Sanitizer checks on W (development checks, not records)

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

## Linux: not compiled in M6a

M6a could not build on L (M3 works there) and did not use W's WSL. The coordinator must build
the merged tree on L (Debug and the three sanitizer builds) and run the suite before the merge is
taken as green.

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

## Readings for the revision log

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

## Open for the coordinator

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

## What M6b needs

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
