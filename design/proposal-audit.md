# Audit of the P3 design proposal

Audited: `design/proposal.md` at commit c6d7671 of `paper-one-port`. Written 2026-10-02 by an
adversarial reviewer, before the freeze. Nothing here is a result. Read beside the proposal:
`CLAUDE.md` (rules D1 to D9), `design/competitor-survey.md`, P2's frozen
`papers/typed-routing/hypotheses-round2.md`, P1's `papers/wake-defect/design/minimal-loop.md`,
`lab/README.md` and `lab/t1/t1.py`.

Method:
- Every load-bearing technical claim was checked against a primary source fetched on
  2026-10-02 (section "Technical claims"). Kernel claims were read in the v7.2 source, the
  kernel L runs (7.2.3).
- The margin rule of ST13 was simulated (Appendix A). The model, the seed and the script are
  given there. Its outputs are computations under a stated model, not lab results.
- Every time figure below is arithmetic on the proposal's own counts and its 6.63 s per window.

Counts: 2 BLOCKER, 13 MAJOR, 16 MINOR. Verdict: freeze after fixes, with section 5 re-audited
once ST13 is replaced (see "Verdict").

## Findings

### F1. BLOCKER. ST13: the margin rule is ill-defined, and per cell it reduces to the pilot's largest deviation

What is wrong.
1. "every cell of x on h passes both computations ... in at least 80% of 1,000 simulated runs"
   has two readings. Per cell: each cell passes in at least 80% of its own runs. Joint: all
   cells of x on h pass together in at least 80% of runs. The text also does not say whether a
   simulated run draws the cells together or apart.
2. The simulation uses B = 2,000 resamples; the confirmatory analysis uses B = 10,000 (ST6).
   Under TOST the BCa p-value has a floor that depends on B and on the bias correction z0. With
   acceleration 0 (P2's result for the median of an even number of sessions), the lower test's
   p is Φ(Φ⁻¹(s_low) − 2z0) and the upper test's is Φ(Φ⁻¹(s_up) + 2z0), each share clipped to
   at least 1/(2B). The cell's p is the larger, so it is at least Φ(Φ⁻¹(1/(2B)) + 2|z0|).
   - To pass at α/m_C = 0.025/36 = 6.94e-4 (Φ⁻¹ = −3.198): at B = 10,000 (Φ⁻¹(5e-5) = −3.891)
     the run needs |z0| < (3.891 − 3.198)/2 = 0.347; at B = 2,000 (Φ⁻¹(2.5e-4) = −3.481) it
     needs |z0| < 0.142.
   - Simulation (Appendix A): resampled pilot sets had |z0| ≥ 0.142 in 16.8% of 1,000 cases,
     so 13.5% to 19.4% of simulated runs could never pass at any δ (100 pilots). Fresh samples
     at B = 10,000 never reached |z0| ≥ 0.347 in 1,000 cases. The 80% target therefore sits
     close to infeasible inside the simulation for a reason the real test does not have.
   - Under the joint reading over the 8 cells of a metric on L, no δ existed in 10 of 10
     simulated trials: 74% to 79% of simulated runs contained a cell that could never pass.
3. Under the per-cell reading, the rule is a disguised order statistic. A simulated run draws 16
   of the 16 pilot sessions, so it can never contain a value beyond the pilot's extremes.
   - If every pilot session lies inside the margin, every simulated run passes the sign test
     with p = 2^-16. The pass rate is then limited only by the BCa floor of item 2 (about 83% in
     the simulation), which clears 80%.
   - If one pilot session lies outside on one side, a simulated run passes only if it draws
     that session at most once: (15/16)^16 + 16 × (1/16) × (15/16)^15 = 0.3561 + 0.3798 =
     0.7359, below 0.80.
   - So δ is the smallest multiple of 0.005 beyond the largest |deviation| among the pilot's
     sessions, taken over every cell of x on h. In the simulation the unrounded δ equalled the
     pilot's maximum in 100 of 100 pilots.
4. Consequences, from the simulation (log session ratios iid normal, σ = 0.01, R = 16):
   - At one true σ, δ ranged from 0.010 to 0.035 across pilots (41 pilots at 0.020, 40 at
     0.025). The margin depends on one extreme draw.
   - The δ that gives 80% power on fresh runs is 0.0184 (1.82 σ). The rule's realized power had
     median 0.987, but 7 of 100 pilots gave power below 0.5 (minimum 0.059).
   - Per host the margin is set by the noisiest cell. With 8 cells of equal noise on L, δ is the
     maximum of 128 sessions. Its median under the normal model solves
     (1 − 2(1 − Φ(t)))^128 = 0.5: t = Φ⁻¹(0.9973) = 2.78 σ, against 1.82 σ needed per cell. For
     one cell (16 sessions) the same formula gives 2.03 σ, which matches the simulated median of
     the unrounded δ (0.02035 at σ = 0.01).
5. "This is the smallest margin the lab can resolve with the design's power" (ST13 step 2) is
   therefore false. It is the pilot's largest single-session deviation, rounded up.

Evidence: ST13 text; P2's acceleration argument (`hypotheses-round2.md` section 5); Appendix A.

Fix.
- Preferred: reverse the logic. Fix δ per metric a priori from relevance (`CAP_C1` to
  `CAP_C3`, set by Alex before any development comparison, F4). Then size R per host from the
  A/A pilot so that each cell has at least 80% power at δ, using a parametric formula on the log
  session ratios (σ from the pilot, pooled per metric and host, taken at an upper confidence
  bound), and the exact sign-test pass rule of F3. If the R needed exceeds the time budget, the
  metric on that host moves to the secondary results before the freeze.
- If the pilot rule is kept: define it per cell; use the confirmatory B (10,000) inside the
  simulation (with B = 10,000 the share of resampled sets with |z0| ≥ 0.347 was 3.2% to 4.3%,
  Appendix A); replace the plug-in resampling by a parametric or smoothed model so that δ is not
  the pilot's maximum; state that one δ per host is set by its noisiest cell.

### F2. BLOCKER. B3: the memory metric is biased toward the server, and the runs cannot start as configured

What is wrong.
1. Connection limits. N_PEND = 10,000 (WL7) exceeds nginx's default `worker_connections 512`,
   a count that includes connections to proxied servers. nginx with one worker cannot hold the
   pending set. HAProxy derives its global `maxconn` from the descriptor limit, and a
   frontend's default is the global value. sslh v2.3.1 calls `listen(sockfd, 50)` on TCP. The
   proposal raises no limit, names no pacing for opening 10,000 connections, and records no
   listen-queue overflow.
2. The kernel's per-socket baseline is left out. The kernel part is `r` plus `f` of `ss -tm`.
   ss(8) defines `r` as memory allocated for received packets and `f` as memory the socket holds
   as cache, not yet used. Neither counts the socket structures, which every system pays alike.
   Leaving a shared constant out of both numerator and denominator pushes every ratio further
   from one. The claim "below 1.00" then measures the systems' user-space overhead, and the ratio
   overstates it. `f` is reserved, not used, memory; counting it is a choice to state.
3. RSS growth on garbage-collected runtimes measures heap policy, not live state. A JVM or Go
   heap can hold memory beyond the live data until a collection runs. RK9 names this and then
   uses defaults anyway.
4. JVM ergonomics on one CPU. Oracle's JDK 25 GC tuning guide: G1 on server-class machines,
   Serial otherwise; a machine is server-class with two or more processors and at least 1792 MB.
   B pins every competitor to the server's one core (section 6), so Netty and Jetty may run with
   the Serial collector. That is not their documented deployment. Whether the JVM counts the
   affinity mask as its processors must be checked at the freeze with the pinned JDK
   (unverified).
5. "after a settling time" has no value or rule, and ℓ (the announced ClientHello length) is not
   given.

Evidence:
- nginx core module docs: default `worker_connections 512`; the count covers connections to
  proxied servers too. https://nginx.org/en/docs/ngx_core_module.html
- HAProxy v3.4.6 configuration.txt: global `maxconn` (line 3951) is computed from the descriptor
  limits when unset; a frontend's `maxconn` (line 9717) defaults to zero, which means the global
  value; `backlog` (line 6383) passes the frontend's maxconn to listen().
  https://git.haproxy.org/?p=haproxy-3.4.git;a=blob_plain;f=doc/configuration.txt;hb=refs/tags/v3.4.6
- sslh v2.3.1 common.c line 152: `res = listen (sockfd, 50);`
  https://raw.githubusercontent.com/yrutschle/sslh/v2.3.1/common.c
- ss(8) `skmem` fields. https://man7.org/linux/man-pages/man8/ss.8.html
- JDK 25 ergonomics. https://docs.oracle.com/en/java/javase/25/gctuning/ergonomics.html

Fix.
- Primary statistic: the paired difference in bytes per pending connection (competitor minus
  server), tested for superiority against a relevance margin, with both absolute values and the
  ratio reported. Report the kernel's per-socket baseline separately (for example from slab
  accounting) so that the reader sees the whole footprint.
- Raise every competitor's connection and descriptor limits to at least N_PEND with its
  documented directive (nginx `worker_connections` and `worker_rlimit_nofile`, HAProxy
  `maxconn`), each line with its reason. Open the connections at a paced rate and make a window
  invalid unless the listen-overflow counters (`nstat` TcpExtListenOverflows, ListenDrops) did
  not change.
- For the JVM and Go: force a collection before sampling (the harness calls the runtime's
  collector, or `jcmd <pid> GC.run`), and report the runtime's own live-heap figure beside RSS.
  Choose and state the JVM collector explicitly, with the reason.
- Define the settling rule (for example, two RSS samples a fixed interval apart differ by less
  than a stated amount) and ℓ.

### F3. MAJOR. At R = 16 the exact sign test, not the median's precision, sets the cost family's resolution

What is wrong. TOST with two exact sign tests is valid: each one-sided test is exact at its null
boundary, a tie counts against, and the larger p of the two is a valid intersection-union
p-value. But at Holm's first threshold for m_C = 36 (6.94e-4), a cell passes only with at most
one session outside the margin on each side: one out gives 17/65536 = 2.59e-4, two out give
137/65536 = 2.09e-3. Power under a normal model of the log session ratio with SD σ (A/A truth),
with q the probability that a session falls outside on one side:
- P(pass) = (1 − 2q)^16 + 32q(1 − 2q)^15 + 240q²(1 − 2q)^14. At q = 0.034 this is 0.806; at
  q = 0.035 it is 0.797. So 80% power needs δ at about the 96.6th percentile, about 1.82 σ.
- The BCa alone would need about 1.43 σ (simulation, Appendix A: 1.432 σ).
- R = 24 allows 3 out per side (P(X ≥ 21) = 2325/2^24 = 1.39e-4; 4 out gives 7.72e-4). Margin
  for 80% power: 1.43 σ.
- R = 32 allows 6 out per side (P(X ≥ 26) = 1,149,017/2^32 = 2.67e-4; 7 out gives 1.05e-3).
  Margin for 80% power: 1.14 σ (BCa alone 1.00 σ).
- Cost in windows at 6.63 s: R = 24 adds 1,152 windows, 7,637.76 s = 2 h 7 min 18 s (W share
  384 windows, 42 min 26 s); R = 32 adds 2,304 windows, 15,275.52 s = 4 h 14 min 36 s (W share
  768 windows, 1 h 24 min 52 s).

Evidence: binomial sums above; Appendix A (`r32.py`).

Fix. Choose R for the cost family by the procedure of F1 (R from the pilot at the fixed δ),
allowing R above 16. State in the methods that the sign test is the binding computation.

### F4. MAJOR. The caps and the design growth can be chosen after seeing one-port data

What is wrong. The A/A pilot itself holds no one-port data. But rule E1 allows development runs
of one-port against dedicated before the freeze. Alex sets the caps (Q2) and step 3 decides
whether windows or sessions grow or a metric is demoted. Nothing orders these decisions before
the development comparisons. E1's sentence "The equivalence margins cannot be tuned to them"
holds only for the mechanical part.

Evidence: I31 E1; ST13 steps 3 and 4; Q2.

Fix. Alex sets `CAP_C1` to `CAP_C3` now, committed with a date, before any development run
that times one-port against dedicated. The pilot runs once, with its seed logged; a rerun needs a
revision-log entry with the reason. One-port against dedicated development timing waits until
the caps and R are committed.

### F5. MAJOR. A failed superiority test is read as equivalence, and "no measurable cost" hides δ

What is wrong.
- 5.8: "M1 and M2: ... A loss is a finding about the mechanism, for example that peek costs
  nothing extra on one backend". A cell that fails a superiority test shows only that the
  difference was not shown. It does not show "nothing extra".
- 5.8 and A2 say "no measurable cost". The test shows a ratio inside [1/(1 + δ), 1 + δ]. With
  δ chosen as in ST13, "measurable" means "beyond this lab's largest pilot deviation".

Fix. Word M1 and M2 losses as "not shown", or add an equivalence test for them with its own
margin. Every cost claim quotes δ: "equivalent within ±δ on metric x, host h".

### F6. MAJOR. Kernel state carries from window to window, and the A/A pilot does not mirror the A/B structure

What is wrong.
- TIME-WAIT lasts 60 s (`TCP_TIMEWAIT_LEN (60*HZ)`, include/net/tcp.h line 140 at v7.2). A
  window takes about 6.63 s, so roughly nine earlier windows' TIME-WAIT sockets are present at
  the start of each window (60/6.63 = 9.05).
- Loopback reuse needs the TIME-WAIT socket to be older than `tcp_tw_reuse_delay`, default
  1000 ms (tcp_ipv4.c line 3465 at v7.2). `tcp_max_tw_buckets` is `ehash_entries / 2` (line
  3434), so it depends on the hash size on L and is not known.
- One-port and dedicated arms use different server ports. In X Y Y X the middle arm has two
  back-to-back windows on its own port, the outer arm does not. The draw of X randomizes this,
  so it adds variance, not bias. But in the A/A pilot both arms use the same port, so every
  transition is same-port. The pilot's noise structure differs from the confirmatory one, and
  the margins of ST13 come from the pilot.
- `opgen` binds explicit 127/8 sources (I30). Without `IP_BIND_ADDRESS_NO_PORT`, bind() with
  port 0 reserves an ephemeral port before the destination is known, so ports cannot be shared
  across destinations by 4-tuple.

Evidence: v7.2 sources above; docs.kernel.org ip-sysctl (`tcp_tw_reuse` default 2,
`tcp_tw_reuse_delay` default 1000 ms, `tcp_max_tw_buckets` text); IP_BIND_ADDRESS_NO_PORT(2const),
Linux 4.2: with it, bind() with port 0 reserves no port, and connect() picks one that may be
shared as long as the 4-tuple is unique.
https://man7.org/linux/man-pages/man2/IP_BIND_ADDRESS_NO_PORT.2const.html

Fix. Give each window a fresh block of 127/8 source addresses, so no 4-tuple recurs within
60 s. Set `IP_BIND_ADDRESS_NO_PORT` on every generator socket that binds a source. Record per
window the TIME-WAIT count at start and end, TcpExtListenOverflows, and the TIME-WAIT overflow
counter. Read `tcp_max_tw_buckets` at the freeze. Run the A/A pilot with the second start on a
port offset, so that its transitions match the A/B design.

### F7. MAJOR. Every cost cell carries one protocol, so the one listener is never shared under load

What is wrong. Each cost cell sends one protocol to one port. In dedicated mode only one of the
six listeners is active. So the cost family never tests what distinguishes one listener: several
protocols, pending undecided connections and slow clients sharing one accept queue and one
detection path. The claim "no measurable cost" would extend to a situation the design does not
contain.

Fix. Either scope the claim to single-protocol load in the hypotheses and the title, or add a
mixed cell: for example HTTP/1.1 churn plus a fixed background of TLS, MQTT and silent
connections, the same background in both modes (dedicated mode spreads it over its ports).

### F8. MAJOR. The peek path has four design gaps (I11)

1. io_uring peek into a shared scratch buffer races. I11 reads peeks "into a per-worker scratch
   buffer". On io_uring the copy happens inside `sock_recvmsg` when the request is issued or
   retried (`io_recv`, io_uring/net.c line 1263 at v7.2). With `POLL_FIRST`, the retry runs as
   task work inside the worker's own `io_uring_enter`, so several peeks can copy into the same
   buffer before any completion is reaped. The bytes the matcher sees are then another
   connection's. Fix: peek with buffer select from a provided-buffer ring, recycled after the
   matcher runs (to be pinned by a test with `MSG_PEEK`); this keeps I15's "no buffer while
   waiting".
2. The `SO_RCVLOWAT` value. I11 sets it to "the byte count the matcher still needs". Peeked
   bytes stay queued, and readiness counts every unread byte: `tcp_epollin_ready` compares
   `rcv_nxt − copied_seq` with the target (include/net/tcp.h lines 1823 to 1833 at v7.2). A
   low-water mark equal to the bytes still missing is already met by the queued bytes, so the
   socket reports readable at once and the peek spins. Fix: set it to the total the matcher
   needs (queued plus missing), and count the extra `setsockopt` that resets it before the
   handler reads.
3. IOCP has no way to wait for more bytes. Windows does not support `SO_RCVLOWAT`: the docs say
   the Windows TCP/IP provider does not support it, and setsockopt fails with WSAEINVAL. After an
   undecided peek, the bytes stay queued, and a new zero-byte `WSARecv` is expected to complete
   at once (derived from its role as a readiness signal; to be pinned by a test). So the IOCP peek
   spins until T_dec on every split arrival (HC2 to HC4). Fix: state the mechanism, for example
   switch that connection to replay after the first undecided peek, or re-arm after a timer; count
   its cost in M1 on IOCP; or drop IOCP peek from M1 and report it as a limitation of the API.
4. Half-close in peek mode on io_uring and IOCP. After a FIN with a partial signature, the
   socket stays readable (`tcp_poll` sets `EPOLLIN | EPOLLRDNORM | EPOLLRDHUP` on
   `RCV_SHUTDOWN`, net/ipv4/tcp.c lines 583 to 584 at v7.2), the poll of a `POLL_FIRST` receive
   fires, and the peek returns the same bytes as before. Nothing in the receive result reports the
   FIN, so the peek loops until T_dec, while HC21 expects "closed at once". epoll is fine: the
   event carries `EPOLLRDHUP`. Fix: on io_uring, wait with `IORING_OP_POLL_ADD` for
   `POLLIN | POLLRDHUP` and read the mask from the completion, then peek synchronously (RK4's
   fallback); on IOCP, define and test how a half-close is seen during a peek wait.

Evidence: https://raw.githubusercontent.com/torvalds/linux/v7.2/io_uring/net.c ,
https://raw.githubusercontent.com/torvalds/linux/v7.2/include/net/tcp.h ,
https://raw.githubusercontent.com/torvalds/linux/v7.2/net/ipv4/tcp.c ,
https://learn.microsoft.com/en-us/windows/win32/winsock/sol-socket-socket-options

### F9. MAJOR. M3 fairness: logging, accept settings, splice and route tables are not matched

What is wrong.
1. Logging. sslh v2.3.1 logs every forwarded connection by default: `verbose-connections`
   default 3 (sslhconf.cfg line 35), where bit 1 writes to stderr and bit 2 to syslog (log.c,
   `MSG_STDOUT 1`, `MSG_SYSLOG 2`), each protocol's `log_level` defaults to 1, and
   `connect_queue` calls `log_connection` for every backend connection (tcp-listener.c line
   200). At churn rates sslh-ev would write one line per connection to stderr and syslog. The
   others are quiet by
   default: nginx stream `access_log off`; caddy-l4 logs connections at Debug (layer4/server.go
   lines 192 and 210); HAProxy logs only with `log` lines; Envoy writes access logs only when
   configured. Running sslh as is makes it a straw man.
2. Envoy's FAQ also says to disable `generate_request_id` and `dynamic_stats` (HTTP only), to
   consider disabling all stats with `reject_all` when measuring overhead, to prefer open-loop
   load generators, and never to measure latency at maximum load. CP3 takes four of its items,
   and WL2 and I33 one each; the stats advice and the open-loop preference are left out. M3's
   headline is closed-loop throughput.
3. Accept settings. sslh's listen backlog is 50, hard-coded, against C = 64 connecting slots.
   nginx defaults to `multi_accept off`, while the server drains the accept queue per readiness
   (I5). HAProxy passes `maxconn` as the backlog. The server's own backlog is not stated.
4. Splice. If rule E picks `splice` for the relay, HAProxy's documented counterpart is `option
   splice-auto`, which is "not enabled by default". nginx, Envoy and caddy-l4 have none.
5. "Like for like" (I17) holds for topology only. nginx tells TLS from "not TLS"; the server
   runs its whole table. "Every system holds the same routes" contradicts "SSH to a third where
   the system can detect SSH": route tables differ in size.
6. The TLS exchange of M3 is not specified: what the stub's fixed reply is, who closes first,
   and whether `opgen` builds a fresh ClientHello (an X25519 key per connection) for a backend
   that never handshakes.
7. The server's relay buffer size is not stated beside the proxies' defaults.

Evidence: https://raw.githubusercontent.com/yrutschle/sslh/v2.3.1/sslhconf.cfg ,
https://raw.githubusercontent.com/yrutschle/sslh/v2.3.1/log.c ,
https://raw.githubusercontent.com/yrutschle/sslh/v2.3.1/tcp-listener.c ,
https://nginx.org/en/docs/stream/ngx_stream_log_module.html ,
https://raw.githubusercontent.com/mholt/caddy-l4/v0.1.2/layer4/server.go ,
https://www.envoyproxy.io/docs/envoy/v1.39.2/faq/performance/how_to_benchmark_envoy ,
HAProxy configuration.txt v3.4.6 lines 11720 (`option splice-auto`) and 6383 (`backlog`).

Fix. Turn per-connection logging off in every system (sslh: `verbose-connections: 0`), each line
with its reason. State Envoy's stats setting and the server's counters as the matched
bookkeeping. Record listen overflows per window for every arm and report them beside each loss.
Set `multi_accept on` for nginx or state why not. Give HAProxy `splice-auto` if the server
splices. Give every system the same route table, or report the table size beside each cell.
Specify M3's TLS exchange; `opgen` can send one recorded ClientHello for the stub. Say that M3's
closed-loop throughput departs from the FAQ's open-loop advice, and point to the open-loop
secondary.

### F10. MAJOR. B3 against JVM and Go libraries compares runtimes, not detection

What is wrong. A minimal C++ server against Netty, Jetty (JVM) and cmux (goroutines and bufio)
on memory per pending connection has a foregone direction. A reviewer would call those cells a
straw man for a detection claim. Together with F2's ratio bias, B3 can pass in all 34 cells
without saying anything about the detection design.

Fix. Word B3's claim as "whole-system footprint per pending connection, as configured". Either
keep the JVM and Go cells descriptive (outside Holm), or keep them with the F2 fixes and say in
the text that they measure the runtime as much as the detector.

### F11. MAJOR. M2's rate rule assumes the relay is the slower arm, which is doubtful for TLS

What is wrong. WL6 takes M2's open-loop rate from "the relay arm, the slower arm by design". In
M2's TLS cells, the in-process arm terminates TLS on one core, while the relay arm terminates it
in the backend on two cores (LB2). The in-process arm may saturate at the relay's rate. Open-loop
windows also have no validity rule for the offered load: `t1.py` only writes a note when less
than 99% of it is achieved. The placement of `opgen` for M2's in-process arm (12 or 8 threads)
is not stated.

Fix. Set each M2 cell's rate from the smaller capacity of its two arms. Make an open-loop window
invalid when less than 99% of the offered load is achieved. Use one placement for both arms of a
cell (the hand-off layout, with CPUs 10 to 13 idle in the in-process arm).

### F12. MAJOR. The server-speaks-first boundary lacks a tie rule, a guard band and a half-close rule (S6)

What is wrong.
- S6(b), "A connection that delivers any byte before T_fb expires", does not say whether
  "delivers" means arrival in the kernel or observation by the loop, nor which wins when the
  expiry and the bytes are handled in one pass. On IOCP a pending zero-byte receive may be
  complete but not yet dequeued when the timer is checked.
- HC7's two clients send "after T_fb" and "before T_fb" with no offset. Without a guard band
  larger than the timer lateness, B1 is not deterministic.
- B2(a) "never early" needs the loop to re-read the clock after every wait and wait again if
  early. On W this is not optional: the Wait Functions page says that a time-out between one and
  two clock ticks can end after one tick, so a wait can end before its timeout.
- HC21 ("closed at once, undecided") is a rule that S6 does not contain.

Evidence: https://learn.microsoft.com/en-us/windows/win32/sync/wait-functions ; S6; HC7; HC21.

Fix. Define (b) on the loop's observation, and before a fallback dispatch make one non-blocking
check for bytes (peek or a zero-length test) whose result wins. Give HC7 offsets of T_fb ± G,
with G a named placeholder set in the pilot above the 99th percentile of B2's lateness on each
backend. State the clock re-check in I13. Add S6(h) for a peer that shuts down writing before a
decision.

### F13. MAJOR. W has no validity rules to apply

What is wrong. ST10's 2% CPU MHz drift rule is implemented in `t1.py` from `/proc/cpuinfo` and
`/sys` (Linux). `pin.sh` turns boost off on L; W has no counterpart (LB3), and its boost state is
not stated. W's cost cells (12) and M1's IOCP cells (2) would be judged by rules that cannot be
computed there.

Fix. Before the freeze, define W's procedure: boost policy, power plan, timer resolution, and a
frequency check from a Windows counter named and tested in engineering. If no check exists,
declare that W windows are validated on fewer rules, and say so in the paper.

### F14. MAJOR. The time plan omits most of the grid

What is wrong. The table reproduces correctly (section "Time arithmetic"), but it leaves out:
hard cases (at least 48 min of waiting for the server alone), competitors' case runs at defaults
(83 s of waiting per replicate of one silent case, and three systems that never time out),
B3's window length, the secondary runs (at least 2,240 windows that can be counted, about
4 h 7 min 31 s, plus B3 in the other mode, 2,176 windows), reruns (up to 896 windows, about
1 h 39 min) and rule E (at least 144 windows, about 16 min). It gives no total and no plan for
W's quiet windows (at least 3 h 3 min 52 s of primary and pilot windows). The 4-core secondary
leaves 3 physical cores (6 logical CPUs) for `opgen`, 1.5 per server core against 12 in the
primary cells, so the generator rule of ST10 will likely invalidate it.

Fix. Complete the table with these rows and a total per host. Cut secondaries until the total
fits the time Alex grants (Q11, Q8, new Q21).

### F15. MAJOR. The sanitizer plan (D5) has holes

What is wrong.
1. Z2 does not name dedicated mode or stub mode. Both are measured arms (C, M3, B). The records
   gate by inputs hash, so they would "cover" code paths the suite never ran under a sanitizer.
2. W's record: how OpenSSL and nghttp2 are built for MSVC ASan is not said. I23's "the same
   configure options" on L and W is not possible (different targets; NASM per Q6).
3. OpenSSL under TSan is "to be checked in engineering". If it cannot be built, that is a gap
   to declare now.
4. Z6 declares that MSan misses OpenSSL's assembly. ASan and TSan do not instrument assembly
   either; that gap is undeclared.
5. Z6's io_uring mitigation unpoisons "the res bytes of each completion". For receives into a
   provided buffer (replay mode, and the peek of F8.1) the bytes to unpoison are in the selected
   buffer, not in the completion. Say so.
6. "MSVC 19.51.36246 or clang-cl" must become one compiler at the freeze, because the gate
   matches the compiler.

Fix. Add both modes to Z2; specify the W third-party builds; settle OpenSSL under TSan or
declare it; extend the assembly gap to ASan and TSan; name the provided-buffer unpoisoning; pick
one W compiler.

### F16. MINOR. TLS settings: "no tickets" needs a call the proposal does not name; the choices lack a source

What is wrong.
- OpenSSL 3.5.9: under TLS 1.3, `SSL_OP_NO_TICKET` only switches to a stateful ticket, which is
  still sent; to send none, call `SSL_CTX_set_num_tickets` with 0. The default is 2 tickets.
- The suite, the curve and the signature have a source the proposal does not cite: RFC 8446
  s9.1 makes TLS_AES_128_GCM_SHA256 and ecdsa_secp256r1_sha256 MUST, P-256 key exchange MUST
  and X25519 SHOULD.
- OpenSSL 3.5's `DEFAULT` group list predicts a key share for X25519MLKEM768. X25519 alone
  departs from the library's default and gives a much smaller ClientHello, which matters for
  HC20 and B_CH.

Evidence: https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.9/doc/man3/SSL_CTX_set_options.pod ,
https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.9/doc/man3/SSL_CTX_set_num_tickets.pod ,
https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.9/doc/man3/SSL_CTX_set1_curves.pod ,
https://www.rfc-editor.org/rfc/rfc8446.txt (s9.1).

Fix. Name `SSL_CTX_set_num_tickets(ctx, 0)` and `SSL_SESS_CACHE_OFF`; cite RFC 8446 s9.1; state
that the group choice departs from OpenSSL's default and why.

### F17. MINOR. The Windows peek has a documented basis the proposal does not cite; IOCP options are unstated

The WSARecv page says `MSG_PEEK` "is valid only for nonoverlapped sockets", and AcceptEx sockets
are overlapped. The same page also says that a call with both `lpOverlapped` and
`lpCompletionRoutine` NULL treats the socket as nonoverlapped. That statement, not the recv page,
is the documented basis for a synchronous peek on an IOCP socket. Cite it. Also state
whether the server sets `FILE_SKIP_COMPLETION_PORT_ON_SUCCESS` (libuv v1.53.0 does, src/win/tcp.c
line 189), since it changes the operation counts of I29.

### F18. MINOR. The AcceptEx claim is an inference stated as fact (I5)

The AcceptEx docs verify that with a receive buffer the operation completes only once a
connection is accepted and data is read, that `SO_CONNECT_TIME` returns seconds, and that
closing such sockets is recommended. They do not say that the server cannot send on the socket
before completion. Reword I5 as "the documented remedy is to close the socket; the server
therefore does not use the receive buffer on fallback listeners".

### F19. MINOR. The epoll claim is half right (I11)

`EPOLLRDHUP` (since 2.6.17) is needed: a peek never returns 0 while bytes are queued, and
`tcp_poll` reports `EPOLLRDHUP` on `RCV_SHUTDOWN`. But "a level-triggered peek would busy-loop"
holds only without `SO_RCVLOWAT`. With it set, select, poll and epoll report readable only when
that many bytes are available (socket(7), since 2.6.28; `tcp_poll` uses `sock_rcvlowat`, tcp.c
line 589 at v7.2). Edge-triggered mode is nginx's condition, not a necessity of this design.
Reword.

### F20. MINOR. 5.6's smallest BCa p holds only at z0 = 0

5.6 says the smallest BCa p is about 5.0e-5. P2 gave that value "with z0 and the acceleration
at 0". Under TOST the floor is Φ(Φ⁻¹(1/(2B)) + 2|z0|) (F1). At B = 10,000 a cell can pass
Holm's first threshold only if |z0| < 0.347; the simulation never saw that exceeded on fresh
samples. State the condition.

### F21. MINOR. Orders and hosts (ST9, section 9)

"All sessions of a family's cells run in one shuffled order" cannot hold when a family spans L
and W (cost, and M1's IOCP cells). The time table counts all 20 mechanism cells as if on one
host. Define one order per family and host; split the table.

### F22. MINOR. The two modes differ on invalid input (I20, I8)

The detector closes on two leading CRLFs or an unlisted method. The dedicated HTTP handler's
grammar for these is not stated; if it answers 400, the modes differ. I20's "That is the whole
difference" then needs an exception. State the handler's grammar and test both modes on these
inputs.

### F23. MINOR. Cells that are near-certain to pass take Holm budget

C2 measures keep-alive after classification, where both modes run the same code (I3), and RK6
says the TLS cells are close to certain to pass. C2 adds 12 of m_C = 36. Without C2,
m_C = 24 and Holm's first threshold is 0.025/24 = 1.04e-3, so two sessions out (2.09e-3) still
fail but power for the informative cells rises slightly. Keep C2 if Alex wants it, with the
reason stated, or move it to the secondary results.

### F24. MINOR. Small misuses of the survey

- S3: "Every system in the survey serves [HTTP/1.1]". PostgreSQL (survey 2.25) does not.
- A4 gives sslh-ev's fallback as "yes: on-timeout". Survey 2.8 found no `ev_timer` covering
  probing connections in sslh-ev ("Runtime behaviour: not verified"), and RK10 repeats it. A4
  should say "not verified for sslh-ev".
- A4 marks cmux's SSH as "cfg". cmux has no configuration language; `PrefixMatcher` is Go code.
  The Netty, Jetty, cmux and hyper-util harnesses are new code too, against A4's "nothing they
  would need new code for is run". Reword A4's rule as "only built-in matchers or the project's
  own example, wired by a minimal harness".
- A4's "h2c as HTTP" for sslh has no source in the survey.
- The survey's robustness framing and gap 2 include banner-first hand-off (sshttp's SMTP mode);
  the proposal drops it without a reason.

### F25. MINOR. HC16's expected outcome depends on the replacement byte

"rejected at byte k" fails for some replacements at k = 0: 0x16 routes to the TLS matcher and is
rejected at byte 1. Specify the replacement values and the expected byte per value.

### F26. MINOR. Competitor runs at defaults need a cap and a replicate count

cmux, hyper-util and the Netty example have no detection timer, so a silent case at defaults
never ends. The proposal gives no observation cap and no replicate count for competitor case
runs. Add both as named placeholders.

### F27. MINOR. Numbers without a source that are not placeholders or pilot outputs

- ST4: "at most 4 times per cell".
- ST13: the 0.005 grid, the 80% target, 1,000 simulated runs, 2,000 resamples.
- ST10: "a backend core was more than 90% busy" (by analogy with the generator rule, not from
  `t1.py`).
- WL7: 60 s (called a design choice, in Q10); N_PEND = 10,000 (proposed, in Q10); "the first
  ℓ/2 bytes" (ℓ not given); "twice N_PEND" for the open-file limit (whose limit: the server
  process, the generator, or the host?).
- 4.2: 16 replicates for deterministic cases.
- HC23: 4 KiB.
- I24: the TLS suite, group and certificate (sourced by F16's RFC section, not cited).

Every other number checked traces to a source or to arithmetic that reproduces.

### F28. MINOR. Wording that reaches past the paper

The working title "One listener for every protocol" claims more than client-first TCP protocols
plus a timeout fallback. I4's "is not the one-listener design" defines a thesis-level term in a
paper's design. Scope the title (for example to client-first TCP protocols) and leave the
thesis's wording to the thesis.

### F29. MINOR. IOCP accept depth is not fixed per mode

Dedicated mode posts AcceptEx requests on six listeners, one-port mode on one. State the number
of outstanding AcceptEx requests on the active listener, the same in both modes.

### F30. MINOR. An item marked unverified can now be quoted

HAProxy v3.4.6 configuration.txt line 3115: on platforms with CPU affinity, `nbthread` defaults
to the number of CPUs the process is bound to at startup, so `taskset` sets it. CP2's open item
can be closed with this text.

### F31. MINOR. B3's superiority bound of 1.00 has no relevance margin

A ratio of 0.999 in every session passes "below 1.00". With F2's fix (difference in bytes), set
a relevance margin, or report the effect size beside each pass.

## Technical claims

| Claim | Verdict | Source |
|---|---|---|
| `MSG_PEEK` in WSARecv is valid only for non-overlapped sockets | Verified, quote exact. Also verified: a WSARecv with NULL `lpOverlapped` and NULL `lpCompletionRoutine` treats the socket as non-overlapped (F17). `recv` lists `MSG_PEEK` without the restriction | https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-wsarecv ; https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-recv |
| An undecided io_uring peek, sent again, completes again at once | Verified by the source as a derivation: `io_recv` passes the submission's `msg_flags` to `sock_recvmsg` with no special case for `MSG_PEEK` (net.c lines 836 and 1263 at v7.2) | https://raw.githubusercontent.com/torvalds/linux/v7.2/io_uring/net.c |
| Remedy: `IORING_RECVSEND_POLL_FIRST` plus `SO_RCVLOWAT` | Consistent with the source, not yet tested. Verified: POLL_FIRST arms poll before any receive, since 5.19 (`io_uring_prep_recv(3)`); `io_recv` returns -EAGAIN before the first poll when POLL_FIRST is set (net.c lines 1225 to 1227); `tcp_poll` uses `sock_rcvlowat` (tcp.c line 589); `tcp_data_ready` wakes only at the low-water mark (tcp_input.c lines 5601 to 5605); `tcp_set_rcvlowat` calls `tcp_data_ready` at once (tcp.c lines 1841 to 1842). Wrong as worded: the value must be the total, not the bytes still needed (F8.2). Missing: half-close (F8.4) and the shared buffer (F8.1) | https://raw.githubusercontent.com/axboe/liburing/master/man/io_uring_prep_recv.3 ; v7.2 tcp.c, tcp_input.c, tcp.h |
| Multishot accept since 5.19; no `IORING_CQE_F_MORE` ends it | Verified | https://raw.githubusercontent.com/axboe/liburing/master/man/io_uring_prep_accept.3 |
| AcceptEx with a receive buffer cannot serve a silent-client fallback | Partly verified. Doc text: with a buffer it completes only after data; `SO_CONNECT_TIME` gives seconds; closing is recommended. With length 0 it "completes as soon as a connection arrives". "Cannot greet" is an inference (F18) | https://learn.microsoft.com/en-us/windows/win32/api/mswsock/nf-mswsock-acceptex |
| epoll peek needs edge-triggered mode plus `EPOLLRDHUP` | Half right. `EPOLLRDHUP` since 2.6.17, needed. Edge-triggered not needed once `SO_RCVLOWAT` is set (F19). `EPOLLEXCLUSIVE` since 4.5: verified | https://man7.org/linux/man-pages/man2/epoll_ctl.2.html ; https://man7.org/linux/man-pages/man7/socket.7.html |
| `SO_RCVLOWAT` respected by select, poll and epoll since 2.6.28 | Verified | socket(7), man-pages 6.19 |
| TLS: 1.3 only, TLS_AES_128_GCM_SHA256, X25519, ECDSA P-256, no tickets | Choices valid by RFC 8446 s9.1. "No tickets" incomplete: needs `SSL_CTX_set_num_tickets(0)`. X25519 alone departs from OpenSSL 3.5's default (F16) | RFC 8446; OpenSSL 3.5.9 man3 pages |
| `SO_RCVLOWAT` on Windows (not claimed; needed by F8.3) | Not supported; setsockopt fails with WSAEINVAL | https://learn.microsoft.com/en-us/windows/win32/winsock/sol-socket-socket-options |
| Windows waits can end before the timeout (needed by F12) | Verified | https://learn.microsoft.com/en-us/windows/win32/sync/wait-functions |
| libuv's zero-byte `WSARecv` (`UV_HANDLE_ZERO_READ`); AcceptEx with 0 receive bytes | Verified (src/win/tcp.c lines 500, 551) | https://raw.githubusercontent.com/libuv/libuv/v1.53.0/src/win/tcp.c |
| Envoy FAQ items in CP3 | Verified: release binary, `--concurrency`, circuit breaking, comparable filter chains, every line motivated. Not taken: open-loop preference, stats, latency below the knee (F9) | https://www.envoyproxy.io/docs/envoy/v1.39.2/faq/performance/how_to_benchmark_envoy |
| nginx: `worker_processes` "a good start"; event method chosen by nginx | Not re-read (survey and proposal sources). Read instead: `worker_connections` default 512, `multi_accept` default off (F2, F9) | https://nginx.org/en/docs/ngx_core_module.html |
| `tcp_tw_reuse` default 2, loopback only | Verified; also `tcp_tw_reuse_delay` default 1000 ms | https://docs.kernel.org/networking/ip-sysctl.html |

Not re-verified here, taken from the survey or the proposal's own sources: release versions and
dates (OpenSSL 3.5.9 and its end of life, nghttp2 v1.70.0, the competitor pins), the Go
GOMAXPROCS text, Netty's native-transport text.

## Time arithmetic

Basis: 6.63 s per window (P2 H6), as the proposal uses it. A window here also starts a backend
and, in M3, a proxy, so this rate is a floor.

Reproduced from section 9 (all match the proposal to the minute):
- Cost on L: 24 × 16 × 4 = 1,536 windows; 1,536 × 6.63 = 10,183.68 s = 2 h 49 min 44 s.
- Cost on W: 12 × 16 × 4 = 768 windows; 5,091.84 s = 1 h 24 min 52 s.
- A/A pilot: 36 × 16 × 4 = 2,304 windows; 15,275.52 s = 4 h 14 min 36 s (L 1,536, W 768).
- Mechanism: 20 × 16 × 4 = 1,280 windows; 8,486.40 s = 2 h 21 min 26 s. Of these, M1's two IOCP
  cells are on W: 128 windows, 848.64 s = 14 min 9 s; L has 1,152 windows, 2 h 7 min 18 s.
- Sum of these four: 5,888 windows, 39,037.44 s = 10 h 50 min 37 s. L: 4,224 windows,
  28,005.12 s = 7 h 46 min 45 s. W: 1,664 windows, 11,032.32 s = 3 h 3 min 52 s.

Missing from section 9, computed where the proposal gives counts:
- B3: 34 × 16 × 4 = 2,176 windows. The window length is not given (opening N_PEND, settling,
  sampling). Each second of window length costs 2,176 s = 36 min 16 s over B3.
- Hard cases, timer waits only, server only, one replicate at a time: six cases wait at least
  3 s (HC4, HC5, HC6, HC7's late client, HC12, HC15). Each runs on 5 backend and dispatch
  combinations (in-process on 3 backends, relay on 2) × 2 detection modes × 16 replicates = 160
  runs. 6 × 160 × 3 s = 2,880 s = 48 min (L 768 runs, 38 min 24 s; W 192 runs, 9 min 36 s).
  HC7's early twin also waits close to T_fb, depending on G (F12).
- Competitors at defaults, one silent-client case: nginx 30 s + Envoy 15 s + Jetty 30 s + sslh
  5 s + caddy-l4 3 s = 83 s per replicate (survey defaults); at 16 replicates 1,328 s =
  22 min 8 s. HAProxy decides at once; cmux, hyper-util and the Netty example never time out.
- Secondary runs that have cell counts, at R = 16 if run like primary cells: SSH cost cells
  (3 hypotheses × 3 backends = 9 cells, 576 windows); the relay on io_uring against the proxies
  (10 cells, 640 windows); TTFB at a fixed load for M1 and M3 (16 cells, 1,024 windows). Total
  2,240 windows, 14,851.20 s = 4 h 7 min 31 s. B3 in the other detection mode adds 2,176 windows
  at B3's unknown length. Resumption, ALPN h2, 2 and 4 cores, `SO_REUSEPORT`, the IOCP variants
  and descriptor hand-off have no cell counts.
- Reruns (ST4), non-B3 confirmatory cells: at most 56 cells × 4 sessions × 4 windows = 896
  windows, 5,940.48 s = 1 h 39 min 0 s. B3: at most 544 more windows.
- Rule E: 6 choices (3 default modes, 1 IOCP receive form, 2 relay copies) × at least 6 sessions
  × 4 windows = 144 windows, 954.72 s = 15 min 55 s.

## Verdict

Freeze after fixes. The three-family structure is sound: the families do not mix, the arms are
one binary, Holm and the dual computation follow P2, m and the Holm table are right
(m_C = 36, m_B = 34, m_M = 20; 2^-11 = 4.88e-4 < 6.94e-4 and 7.35e-4; 2^-10 = 9.77e-4 <
1.25e-3), the hypothesis and question counts agree with the body, and the proposal names no
private library and contains no em or en dash. The two blockers are definitional. ST13 must be
replaced, not patched: fix δ from relevance and size R from the pilot (F1, F3, F4). B3's metric
and limits must be redefined (F2). The peek-path gaps (F8) are engineering items with known
remedies. None needs a new architecture. Because the F1 fix changes how the cost family is
sized, section 5 should get a short second audit before the freeze.

## Questions only Alex can decide, merged with the proposal's

| Q | Question | Needs Alex? | Default if not |
|---|---|---|---|
| Q1 | Order in which framings give way, and which framing leads | Yes: the paper's lead | |
| Q2 | `CAP_C1` to `CAP_C3`, the widest margin he still calls "no measurable cost" | Yes, and now, before any one-port against dedicated timing (F4) | |
| Q3 | MQTT or PostgreSQL as the sixth protocol | No | MQTT (S3, S4 reasons) |
| Q4 | OpenSSL 3.5 LTS or 4.0 | No | 3.5 LTS, latest 3.5 release at the freeze |
| Q5 | Tools and downloads on frozen L (Perl, make, headers, JDK, Maven, Go modules, crates, perf, ss; with Q15 and Q18 below) | Yes: downloads need his yes | |
| Q6 | W: Perl and NASM; W's pinning and frequency check (F13); quiet windows | Yes for installs and windows | Procedure: coordinator drafts it for his approval |
| Q7 | Copy P1's loop; P1's publicity and licence | Yes for publicity and licence | Citation: none unless P1's text bears on a claim (D8); attribution in code |
| Q8 | Descriptor hand-off | No | Drop (F14) |
| Q9 | `RATE_FRAC` = 0.5 | No | 0.5, with M2's rate from the slower arm (F11) |
| Q10 | 3 s timers; 60 s for B3; N_PEND = 10,000 | No | Keep, with competitors' limits raised (F2) |
| Q11 | 2 and 4 cores, `SO_REUSEPORT` | No | Drop 4 cores (F14); keep 2 only if time allows |
| Q12 | SSH secondary or primary | No | Secondary |
| Q13 | Copy P2's gate or move it to `lab/bin/` | No | Copy into this repository |
| Q14 | The nine HTTP methods | No | The nine (RFC 9110 and PATCH) |
| Q15 | Envoy release binary or source build | Only the download (Q5) | Release binary, as the FAQ says |
| Q16 (new) | R for the cost family, sized from the pilot at fixed δ (F1, F3) | Only through Q21's time | Size R from the pilot, at most 32 |
| Q17 (new) | Mixed-protocol cell, or claim scoped to single-protocol load (F7) | No | Scope the claim, add the mixed cell as secondary |
| Q18 (new) | JDK pin and JVM collector for B3 (F2) | Only the download (Q5) | Latest LTS JDK at the freeze; collector stated explicitly |
| Q19 (new) | B3's statistic, and JVM and Go cells in Holm or descriptive (F2, F10) | No | Difference in bytes as primary; JVM and Go cells descriptive |
| Q20 (new) | Logging off in every system, backlogs as each system sets them, overflows recorded (F9) | No | As stated |
| Q21 (new) | Total machine time on L, and W quiet-window hours (F14) | Yes | |

Truly needs Alex: Q1, Q2, Q5 (with the Envoy and JDK downloads), Q6 (installs and quiet
windows), Q7 (publicity and licence), Q21 (time budget).

## Appendix A. Simulation of ST12 and ST13

Model: one cell; log session ratios iid normal with mean 0 (A/A truth) and SD σ = 0.01; R = 16;
both computations of ST12 at Holm's first threshold α* = 0.025/36. BCa as P2 runs it for the
median of an even number of sessions: acceleration 0, ties as half in z0, shares clipped to
[1/(2B), 1 − 1/(2B)]. The sign test counts a tie against. The median is taken on the log scale,
an approximation to the median of ratios. Seeds: 20261002 for the 100-pilot run, 20261003 for
the oracle and the joint reading, 20261004 for the B = 10,000 check on resampled sets, 7 for the
R = 16, 24 and 32 margins (σ = 1 there). numpy 2.5.0, Python 3.14.5, `statistics.NormalDist`
for Φ, as P2.

For each run the script finds d_min, the smallest log margin at which the run passes both
computations, or infinity when the BCa floor forbids a pass:
- sign test: d > max(−x₍₂₎, x₍₁₅₎) on the sorted log ratios;
- BCa lower test: with s* = Φ(z(α*) + 2z0), need #(bootstrap medians < −d) ≤ ⌊s*B⌋; the upper
  test likewise with Φ(z(α*) − 2z0); if either s* < 1/(2B), no d passes.

ST13 per cell: δ is the smallest multiple of 0.005 with d_min < log(1 + δ) in at least 80% of
1,000 simulated runs, each 16 draws with replacement from the 16 pilot sessions, B = 2,000.
Realized power: the share of 1,000 fresh runs (B = 10,000) with d_min < log(1 + δ).

Outputs:

| Quantity | Value |
|---|---|
| \|z0\| limit for a TOST pass at α*: B = 10,000 / B = 2,000 | 0.3468 / 0.1419 |
| Fresh samples, B = 10,000: share with \|z0\| ≥ 0.347 | 0.000 (1,000 samples) |
| Resampled pilot sets, B = 2,000: share with \|z0\| ≥ 0.142 | 0.168 (1,000 sets) |
| Resampled pilot sets, B = 10,000: share with \|z0\| ≥ 0.347 | 0.032, 0.039, 0.043 (three pilots, 1,000 sets each) |
| Simulated runs that can never pass (100 pilots) | 0.135 to 0.194, median 0.169 |
| Unrounded δ equal to the pilot's largest deviation | 100 of 100 pilots |
| Rounded δ across 100 pilots | 0.010 (1), 0.015 (6), 0.020 (41), 0.025 (40), 0.030 (8), 0.035 (4) |
| Unrounded δ: min, median, max | 0.0099, 0.0204, 0.0337 |
| δ for 80% power on fresh runs (oracle) | 0.0184, 1.822 σ on the log scale |
| Realized power of the rule's δ | median 0.987; 7 of 100 pilots below 0.5; minimum 0.059 |
| Joint reading over 8 cells: a δ exists | 0 of 10 trials (74% to 79% of simulated runs contain a cell that can never pass) |
| 80%-power margin, R = 16 / 24 / 32 (both computations; sign test alone; BCa alone), in σ | 1.814, 1.814, 1.432 / 1.426, 1.426, 1.148 / 1.139, 1.139, 0.999 |

The scripts (`st13_sim.py`, `r32.py`) were run in the auditor's scratch directory and are not
committed. Their logic is fully given above; the coordinator can ask for them to be added to
`analysis/` if the F1 fix keeps any part of the pilot rule.
