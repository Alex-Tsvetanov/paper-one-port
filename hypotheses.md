# Hypotheses

Status: FROZEN 2026-10-02. Changes go into the revision log below; the text above it is never edited.

Written on 2026-10-02 from `design/proposal.md` as revised that day after the second audit, and
revised the same day after the freeze check (`design/freeze-check.md`), with the proposal, and
once more for the merged skb cache read on L that day (WL7). The proposal applies the first audit
(`design/proposal-audit.md`), the second audit (`design/proposal-audit-2.md`), the freeze check,
and the decisions of Alex and of the coordinator of 2026-10-02. It is to be frozen before any
code of the server exists. The commit that freezes it changes the status line and nothing else.
After the freeze, every value this file leaves open (section 9) and every change goes into the
revision log at the end, never into the frozen text. Nothing in this file is a result.

Words:
- "The server" is `oneport`, the paper's own minimal C++23 server, built in this repository. One
  binary has four flags: mode (one-port, dedicated, stub), detection (replay, peek), dispatch
  (inproc, relay) and backend (epoll, io_uring, IOCP).
- "One-port mode": one listening TCP socket per process. Each connection's protocol is decided
  from its first bytes ("detection") and the connection is then handed to its handler
  ("dispatch"). "Dedicated mode": one listening socket per protocol, on consecutive ports, with no
  detection, no detection timer and no detection budget. Backend, workers, handlers, buffers and
  the PROXY setting are the same in both modes. That is the whole difference between them.
- "L" is the Linux lab host, frozen at kernel 7.2.3, clang 22.1.8 and go1.27.1. "W" is the Windows
  host, with MSVC 19.51.36246. Both run on loopback. The versions are those of P2's
  `papers/typed-routing/hypotheses-round2.md`, section 1 (the L versions at its line 76; MSVC in
  its records), as the proposal's LB1 and section 6 cite them.
- A "window" is one timed run of one arm. A "session" is four windows in mirrored order
  (section 4.1). A "cell" is one contrast at one setting.
- A "one-port window" is a timed window in which the server runs in one-port mode, whatever it is
  compared with. Unit tests and untimed counter checks are not windows.
- "The code freeze" is the commit `CODE_FREEZE` of section 8. "The pilot entry" is the
  revision-log entry of section 8 step 6.
- α = 0.025, family-wise and one-sided, in every family, as in P2 (its section 5).
- "A design choice" marks a number this design picks, with its reason. It is not a measured fact.
  Names in capitals (for example `R_C`) are placeholders that a pilot or engineering fills by a
  stated rule (section 9).

## 1. Scope and claims

The claims are about the server, as measured on L and W under the conditions of this file. No
claim is worded beyond them.

- **Cost (leads the paper).** Under single-protocol load, one-port mode costs no more than
  dedicated mode. The claim is made only in the form "equivalent within [0.98, 1.02]", per
  protocol, backend and host, and only where C1, C2 and C3 all pass.
- **Robustness.** The server's detection conforms to a frozen table of hard cases (B1); its timed
  behaviour is bounded (B2); and its counted footprint per pending connection (WL7) is smaller
  than named competitors', by a ratio of at least 1.10 (B3).
- **Mechanism.** The default detection mode is cheaper than the other (M1); in-process dispatch
  costs less CPU than relay (M2); the server's relay is faster than each proxy (M3).

Transport and protocols:
- TCP only. Served directly, all client-speaks-first: HTTP/1.1; h2c with prior knowledge; TLS, by
  its ClientHello; SSH, when the client sends first; MQTT 3.1.1 and 5.0. The PROXY v1 and v2
  prefix is configured per listener and never guessed.
- Server-speaks-first protocols are served only through the fallback below. SMTP represents them,
  with a minimal handler.
- Out of scope: QUIC, UDP and HTTP/3; WebSocket and h2c by their Upgrade headers; SSLv2-compatible
  ClientHellos; MQTT 3.1 (`MQIsdp`); Redis; PostgreSQL; kernel routing mechanisms; banner-first
  hand-off.

Timers, as design choices: the silence timer T_fb, the decision deadline T_dec and the PROXY
header deadline T_hdr are 3 s. The PROXY specification asks for at least 3 s, and caddy-l4's
default `matching_timeout` is 3 s. In B3 every system with a detection timer uses 60 s, so that no
pending connection expires before the last sample.

What "correct" means for the fallback. A listener may name one fallback protocol. T_fb and T_dec
start together, at accept, or on a PROXY listener when the PROXY header is complete. "Delivered"
means observed by the server's loop: an event the loop handled, or a check that returned a byte.
- (a) A connection that has delivered no application byte when T_fb expires is dispatched to the
  fallback handler in the first loop pass that handles that expiry, never earlier, unless the
  check of (b) finds a byte. It is never closed or routed elsewhere instead.
- (b) The tie rule. Every loop pass handles all of its completions and readiness events before
  any expiry. Before every fallback dispatch the server checks for a byte without waiting: a
  non-blocking one-byte `recv` with `MSG_PEEK` where no receive was posted with a buffer (epoll;
  the zero-byte `WSARecv` on IOCP; the io_uring peek mode); a non-waiting reap of the ring's or
  the port's completions where one was (io_uring replay; IOCP's posted-buffer form). If it finds a
  byte, the byte wins and the bytes alone decide the connection. A byte that reaches the socket
  after the check came after T_fb by the server's clock, which is case (g).
- (c) After a fallback dispatch, the byte transcript in both directions equals that of the same
  client script against the fallback protocol's dedicated port. Only the timing differs.
- (d) A connection with at least one byte that no matcher has decided when T_dec expires is
  closed and counted "undecided". It never goes to the fallback.
- (e) A connection whose bytes rule out every matcher is closed at once and counted "rejected".
  No experiment names a default route.
- (f) A connection that is silent when T_dec expires, on a listener without a fallback, is closed
  and counted "silent".
- (g) A client-first client whose first byte is delivered after T_fb goes to the fallback. This is
  the defined price of the boundary, not an error.
- (h) A connection whose peer shuts down writing before a decision is closed at once: "undecided"
  if it delivered a byte, "silent" if not. It never goes to the fallback.

Detection. Matchers are `constexpr` descriptors in one table, checked at compile time over a
sample corpus from the specifications, so that the classes are prefix-disjoint over it and the
order of the table cannot change a decision on it.

| Matcher | Accepts | Decides at |
|---|---|---|
| TLS | byte 0 = 0x16; byte 1 = 0x03; byte 2 any (RFC 8446 s5.1); a record length of at most 2^14; byte 5 = 0x01 | 6 bytes |
| h2c | the 24-byte preface of RFC 9113 s3.4, exactly | 24 bytes, or the first byte that differs |
| HTTP/1.1 | at most one leading CRLF, then GET, HEAD, POST, PUT, DELETE, CONNECT, OPTIONS, TRACE or PATCH, then exactly one SP | at most 10 bytes |
| SSH | `SSH-` (RFC 4253 s4.2) | 4 bytes |
| MQTT | byte 0 = 0x10; a Remaining Length of 1 to 4 bytes; then `00 04 4D 51 54 54` and level 4 or 5 | 9 to 12 bytes |
| PROXY v1 and v2 | parsed before the table, on a configured listener only: v2 needs 16 bytes with the first 13 matching, v1 needs 8 with the first 5 equal to "PROXY"; a prefix that cannot match closes the connection; a v2 header longer than 536 bytes, the size both formats were designed to fit (survey 2.4), is rejected | then the whole header |

Budgets, compile-time constants: B_dec = 24 bytes after any PROXY header; B_CH = 16384 bytes for a
ClientHello reassembled in pass-through. A connection that exceeds a budget while undecided is
rejected. An empty candidate set after the first byte rejects at once.

## 2. What is compared

### 2.1 The server

- Backends: epoll and io_uring on L, IOCP on W; one per process. One worker thread per server core;
  the primary cells use one core.
- Detection modes. Replay: the first read goes into the buffer the handler would read into in
  dedicated mode, and the handler parses it from its start. Peek: the bytes are copied with
  `MSG_PEEK` into a per-worker scratch buffer and stay in the kernel. Each backend has one default
  mode, used by every cost and robustness cell. The proposed default is replay; rule E of
  section 8 may change it per backend after the pilot entry. On IOCP, which has no `SO_RCVLOWAT`,
  an undecided peek switches the connection to replay.
- Dispatch. In-process: the classified connection stays on its worker and its handler takes over;
  TLS is terminated in the server. Relay (Linux only): the front opens a loopback connection to the
  backend chosen by class, writes any replayed bytes, and relays both ways. For TLS the front
  routes by its own ClientHello parser (SNI and ALPN) and never terminates (pass-through).
- Stub mode, the backend of M3 and of B3 against the proxies: one port per class, the least work
  that completes an exchange. HTTP/1.1 gets the response below. TLS: the stub reads one TLS record,
  writes the 13-byte body and closes; it never handshakes.
- Handlers, the same code in both modes: HTTP/1.1 (200, `Content-Length: 13`, body
  `Hello, World!`; a request line that breaks the detector's grammar is closed in both modes);
  h2 through nghttp2 (v1.70.0, the latest release on 2026-10-02, pinned at the code freeze); TLS
  through OpenSSL, then HTTP/1.1 or h2; MQTT (CONNECT and CONNACK, PINGREQ and PINGRESP,
  DISCONNECT); SSH (sends `SSH-2.0-oneport` and CRLF on entry, reads the client's line, closes);
  SMTP (220, then 250 to EHLO, 221 to QUIT, 500 to anything else).
- TLS: OpenSSL from its 3.5 LTS series, the latest 3.5 release at the code freeze, pinned by
  archive URL and sha256 and built from source on L and W. TLS 1.3 only, TLS_AES_128_GCM_SHA256,
  ecdsa_secp256r1_sha256, group X25519 only, no session tickets (`SSL_CTX_set_num_tickets(ctx,
  0)`), no session cache, no early data; ALPN `http/1.1` in the cost cells. The same settings in
  the server, the backend and the generator.
- Memory held by a pending connection, by design: its state, fixed in size and reported; no data
  buffer while no byte has arrived, on every backend; with replay, the handler's buffer from the
  first byte; in pass-through, the partial ClientHello, at most B_CH.
- Counters, in every build and both modes, per worker, without atomics: operations by kind
  (accept, receive, peek, zero-byte receive, send, `setsockopt`, the check of (b), `io_uring_enter`
  calls, submissions by opcode, `GetQueuedCompletionStatus` calls); peek-to-replay switches; payload
  bytes across the boundary and copied in user space; wakeups per connection during detection;
  outcomes per class; and for each timed event its deadline, when its wait returned and which pass
  handled it.

### 2.2 Families

Three families, never mixed. No contrast crosses families, no proxy is compared with the server's
in-process mode, and no mechanism result supports a cost claim.
- **Cost (C).** The server in one-port mode against the server in dedicated mode: in-process
  dispatch, default detection mode, same binary, same handlers.
- **Robustness (B).** The server alone (B1, B2), and the server against the five proxies (the
  server in relay mode) and the four in-process libraries (the server in in-process mode) on memory
  per pending connection (B3).
- **Mechanism (M).** The server's modes against each other, and the server's relay against each
  proxy.

### 2.3 Competitors

Pins are the survey's versions unless a newer release exists at the code freeze; each change is
recorded in the revision log then. Configurations, with their sources, are in Appendix B.

| System | Pin | Families |
|---|---|---|
| nginx, stream module with `ssl_preread` | 1.30.5, built from the release tag | B3, M3 |
| HAProxy | 3.4.6 | B3, M3 |
| Envoy | 1.39.2, the release binary | B3, M3 |
| caddy-l4 | v0.1.2 = commit 42db5690dea199f930a6f08005fe2e4aab10dcc9, on Caddy v2.11.4, built with xcaddy and go1.27.1 | B3 (descriptive), M3 |
| sslh, the `sslh-ev` binary | 2.3.1 | B3, M3 |
| Netty | 4.2.18.Final, on the latest LTS JDK at the code freeze | B3 (descriptive) |
| Jetty | 12.1.13, on the same JDK | B3 (descriptive) |
| cmux | v0.1.5 on go1.27.1 | B3 (descriptive) |
| hyper-util | 0.1.21 | B3 |

All competitors also run the hard cases their features cover, as a descriptive table (section 10).

### 2.4 Generators and holder

First-party, each gated by its own sanitizer records:
- `opgen`, the load generator: scripted exchanges per protocol, churn and keep-alive, closed and
  open loop, time to first response byte. Every source address is bound with
  `IP_BIND_ADDRESS_NO_PORT`, and each window takes the next unused block of `K_SRC` addresses of
  127.0.0.0/8, never reused within 60 s.
- `opcase`, the case generator: runs each hard case and B3's openings as a script of writes and
  gaps, with `TCP_NODELAY` and one write per chunk, and records each write's time on the server's
  clock.
- `ophold`: accepts connections and holds them without reading or polling them, to measure the
  kernel's per-socket baseline for B3.

## 3. Workloads and metrics

- **WL1, churn, closed loop.** C = 64 connection slots per server core (the lab's T1 default).
  Each slot repeats connect, one exchange, close. Metric: connections per second, the exchanges
  completed without error per second of the measured window.

  | Protocol | Exchange | Closes first |
  |---|---|---|
  | HTTP/1.1 | GET with `Connection: close`, read the response | server |
  | h2c | preface, SETTINGS, one HEADERS frame with END_STREAM; read to END_STREAM; GOAWAY | client |
  | TLS (HTTP/1.1) | full handshake, then the HTTP/1.1 exchange | server |
  | MQTT | CONNECT, read CONNACK, DISCONNECT | client |
  | SSH (secondary) | send the identification line, read the server's | server |
  | TLS against the stub (M3) | one recorded ClientHello, the same bytes on every connection; read the stub's 13 bytes to EOF | server |

- **WL2, churn, open loop.** Exchanges fall due at rate λ = `RATE_FRAC` × (the median, over the
  A/A pilot's sessions, of the session's mean connections per second in the C1 pilot cell with the
  same protocol and backend). `RATE_FRAC` = 0.5, a design choice below saturation. Latency is
  measured from the due time. Metric: median time to first response byte (TTFB), from just before
  `connect` to the first response byte on the generator's clock. A window in which fewer than 99%
  of the exchanges due completed is invalid (99% is a design choice, from audit F11).
- **WL3, keep-alive.** C connections established before the window, one request in flight per
  connection: HTTP/1.1 GET; one h2 stream at a time; MQTT PINGREQ after one CONNECT; HTTP/1.1 GET
  over one TLS connection. Metric: requests per second.
- **WL4, CPU and memory (secondary).** Server CPU time over the window per exchange; resident
  memory at the end and its peak.
- **WL5, operations per connection (secondary).** The counters of 2.1 per connection.
- **WL6, M2's CPU per connection.** The CPU time of the front and the backend together, at an
  open-loop rate, per connection completed. The rate of each M2 cell is `RATE_FRAC` × the smaller
  of its two arms' median closed-loop connections per second, measured in 6 development sessions
  per cell on the frozen binary after the pilot entry (`M2_RATE`, section 9). Both arms use the
  hand-off placement.
- **WL7, memory per pending connection (B3).** Below.
- **WL8, hard cases.** Per case: outcome, transcript, and decision time against `opcase`'s write
  times.

WL7 in full. "Pending" means the client's bytes are still incomplete, whatever the system has
decided from them so far. Every B3 window lasts 30 s from the first connect, a design choice that
ends every sample well inside the 60 s timer of the first connection accepted. Its phases are
design choices too:
- Before t = 0: fresh processes, the probe, a baseline sample. The probe's client closes by reset.
- Opening, t = 0 to at most 10 s: `opcase` opens `N_PEND` = 10,000 connections (a design choice)
  in batches of 25, one batch every 25 ms. A batch is half of sslh's hard-coded backlog of 50, the
  smallest among the systems, so it fits the accept queue even if the previous batch is not yet
  accepted; the pace opens 1,000 connections per second, so the opening takes 10 s. Each connection
  then sends the case's bytes: nothing (silent case), or the TLS record header announcing the
  recorded ClientHello of length ℓ followed by its first ⌊ℓ/2⌋ bytes (partial-ClientHello case;
  half is a design choice, incomplete for every system).
- Settling to t = 20 s, 10 s after the last batch.
- Sample 1 at t = 20 s, sample 2 at t = 25 s. Sample 2 is the value used.
- Closing to t = 30 s: `opcase` closes every connection by reset (`SO_LINGER` on, zero timeout),
  so no TIME-WAIT socket is created.

Each sample reads:
- U: the growth over the baseline of the summed `VmRSS` of the system's processes, per pending
  connection. The stub backend of the relay systems holds no pending connection and is left out.
- Kq: the mean `r` field (rmem_alloc) of `ss -tm` over the system's accepted sockets. It is the
  sum of the truesize of the skbs queued for reading, and truesize holds the payload and also the
  skb's struct and linear head (include/net/sock.h lines 2474 to 2481, include/linux/skbuff.h
  lines 273 to 275, net/ipv4/tcp.c lines 926 to 935, all at Linux v7.2). The `f` field
  (fwd_alloc), reserved and unused memory, is reported and not added.
- Ks: the growth over the baseline of `Slab` in `/proc/meminfo`, less the growth of the skb caches
  (below), per pending connection. It is host-wide and holds both loopback ends; the client ends
  are `opcase`'s, the same for every system.
- `K_BASE`: once per host, `ophold` holds `N_PEND` silent connections in the same window layout;
  the median of its Ks, corrected in the same way, over 16 windows is `K_BASE` (16 is a design
  choice, R_B). It is the kernel slab of a bare held socket, both ends included.

The skb caches (the freeze check's FC1; the coordinator's decision). A queued skb's struct and
linear head are slab objects, so `Slab` holds them while Kq charges them too. On Linux v7.2 the
struct comes from the cache "skbuff_head_cache", or, for the fast clones that TCP's send path
allocates, from "skbuff_fclone_cache"; a linear head that fits comes from "skbuff_small_head"
(net/core/skbuff.c lines 606 to 625, 684 to 685 and 5196 to 5225). A search of every cache
created under `net/` at v7.2 finds no other that holds skb structs or heads: "skbuff_ext_cache"
(line 5176) holds skb extensions, neither a head nor data, and the payload lies in page
fragments, outside `Slab`. At the baseline and at each sample the run script reads
`/proc/slabinfo` as root (the file has mode 0400; mm/slab_common.c lines 1098 and 1226). A
cache's size is its num_slabs × pagesperslab × the page size (slabinfo(5)), a design choice: the
unit in which `Slab` counts the same pages. The growth of the three caches over the baseline is
subtracted from the growth of `Slab`, so a queued skb is counted once, in Kq. Two residuals
remain, and the paper names both:
- A head that does not fit "skbuff_small_head", or is asked for with flags that exclude it, comes
  from kmalloc (skbuff.c lines 613 to 614 and 627 to 646; include/linux/slab.h lines 745 to 748)
  and stays in Ks, so a queued skb with such a head is still counted twice. TCP's send path asks
  for a head of `MAX_TCP_HEADER` bytes with `sk_allocation`, which is `GFP_KERNEL` (tcp.c lines
  926 to 935 and 1256; net/core/sock.c line 3750), and that head fits "skbuff_small_head"
  (skbuff.c lines 106 to 116). So B3's openings are not expected to take this path, but no rule
  excludes it.
- The subtraction also removes skb-cache memory that no receive queue is charged for, such as the
  second struct of a fast-clone pair, which stays allocated while its clone is queued
  (include/linux/skbuff.h lines 1395 to 1401; skbuff.c lines 1139 to 1167), and the unused part of
  the caches' slab pages.
Both residuals sit with a system that leaves bytes queued: nginx and Envoy in the
partial-ClientHello case (their peek paths, survey 2.1 and 2.5), and the server only where its
detection mode is peek (rule E of section 8, and the peek side of section 10's B3 cells). The first
residual raises that system's W, the second lowers it. Where the competitor leaves bytes queued and
the server reads them, the first biases Q upward, in the server's favour, and the second downward;
where the server leaves them queued and the competitor reads them, both directions reverse. In the
silent case nothing is queued and neither applies.

Merged caches. The kernel may merge a cache with others of the same size (mm/slab_common.c lines
50 to 52 and 155 to 230 at v7.2), and "skbuff_fclone_cache" carries none of the flags that
prevent it (skbuff.c lines 5208 to 5212). `/proc/slabinfo` exists only in a kernel built with
`CONFIG_SLUB_DEBUG` (mm/slab_common.c lines 1097 to 1231). A cache is merged with others when
`/sys/kernel/slab/<name>` is a link to a directory whose `aliases` count is above 0 (mm/slub.c
lines 9156 to 9160 and 9641 to 9722 at v7.2). The other links to that directory name the caches
merged with it, its co-tenants, and one of their names is the one under which `/proc/slabinfo`
lists the shared cache; the merged name itself may not appear there. For a merged cache, the
whole growth of the shared cache is subtracted, and its co-tenants are named in the paper.

L, as read on 2026-10-02 (as root, read-only): kernel 7.2.3-arch1-2, built with
`CONFIG_SLUB_DEBUG` and `CONFIG_SLAB_MERGE_DEFAULT` and without `CONFIG_SLUB_DEBUG_ON`, booted
without `slab_nomerge`. `/proc/slabinfo` exists and lists "skbuff_head_cache" and
"skbuff_small_head" under their own names, so neither is merged. "skbuff_fclone_cache" is merged:
`/sys/kernel/slab/skbuff_fclone_cache` is a link to `:0000512`, whose co-tenants are
"pool_workqueue" and "sgpool-16", and `/proc/slabinfo` lists that cache only as
"pool_workqueue". ("skbuff_ext_cache" is merged into `:0000192`; it is not subtracted, so this
changes nothing.) L is not rebooted and its boot parameters do not change, so `slab_nomerge` is
not an option. Nor can the fast clones leave the subtraction: on loopback the sender's TCP
transmit skbs come from the fast-clone cache, and their clones wait in the receiver's queue
(above). So on L the fast-clone growth is read as the growth of the shared cache. At each reading
the run script finds it by following the link `/sys/kernel/slab/skbuff_fclone_cache`
(`:0000512` on 2026-10-02), reads its size from the `/proc/slabinfo` line that carries one of the
names linked to it ("pool_workqueue" on 2026-10-02), and records its `slabs` and `objects` from
`/sys/kernel/slab/` beside it.

The co-tenants' growth. "pool_workqueue" holds the per-pool queues of kernel workqueues,
allocated only when a workqueue is created, or when its attributes or the CPUs it may use change
(kernel/workqueue.c at v7.2: the cache, line 7995; its two allocation sites, lines 5313 and 5628,
reached from `__alloc_workqueue`, `apply_wqattrs_prepare` and `unbound_wq_update_pwq` at lines
5424, 5434, 5578 and 5897). "sgpool-16" holds chained scatter-gather lists, allocated only
through `sg_alloc_table_chained` (lib/sg_pool.c lines 17 to 23, 62 to 67, 112 to 138 and 146 to
158 at v7.2). Neither is a socket or an skb. Their growth over the baseline is subtracted with the
fast clones'. That lowers the window's Ks, and so its W, by that growth per pending connection;
their shrinkage raises it. So co-tenant growth in the competitor's windows lowers Q, against the
server, and in the server's windows raises Q, in the server's favour. Growth equal in both arms
leaves D unchanged and, as an amount removed from both, moves Q away from 1. `K_BASE` takes the
same correction and still cancels.
- Growth that the host causes, not the system under test, favours neither arm systematically.
  Every session runs X Y Y X, the arm that is X is drawn per session (4.1), and B3's sessions run
  in one shuffled order (4.7). So each arm has one outer and one inner window in every session,
  either arm opens a session with probability 1/2, and a drift that is linear within a session
  falls on both arms alike.
- Growth that a system itself causes goes with its arm in every session, and randomization does
  not remove it. Three things bound it, and none of them is a test. Each window's processes start
  and pass the probe before the baseline (the phases above), so what they allocate at start
  cancels. The co-tenants are neither sockets nor skbs, so a system adds to them only by making
  the kernel allocate workqueue pools or scatter-gather lists during the window. And the shared
  cache's growth is recorded at every sample (section 7) and reported per arm beside every B3
  cell (5.2). In the silent case no system leaves a byte queued, so there that growth is the
  co-tenants' growth plus any skbs in flight at the sample: a direct reading, per system, of what
  the subtraction removes beyond queued skbs.

A system's footprint per pending connection is T = U + Kq + (Ks - `K_BASE`): user memory, receive
queue, and the kernel slab the system adds beyond a bare held socket. That last term holds the
kernel objects that differ by design between systems, for example an armed io_uring receive
against an epoll registration. W = T + `K_BASE` = U + Kq + Ks is the counted footprint per pending
connection: what these readings see, with each queued skb counted once, except as named above. It
is the footprint of each system as configured, not of its detection design alone. It is not called
whole-system: outside it, and said in the paper, are the `f` field, kernel memory outside `Slab`
that no receive queue is charged for, the skb-cache memory of the second residual, and the
co-tenants' growth of a merged skb cache; and the first residual can count bytes twice. `K_BASE`
cancels from every B3 statistic and is reported as the share of each footprint that every system
pays alike.

Limits, so that every system can hold `N_PEND`: the soft `RLIMIT_NOFILE` raised to the hard limit
in every process; nginx `worker_connections` and `worker_rlimit_nofile` at 2 × `N_PEND`; HAProxy
global `maxconn` at 2 × `N_PEND`; sslh `max_connections` unset; no downstream connection limit in
Envoy or the harnesses; listen backlogs at `N_PEND` wherever a system has a setting, else
`net.core.somaxconn` (sslh's is 50, hard-coded; the pace respects it). The memory each competitor
holds per pending connection is sized by documented buffer settings, handled by the rule of
Appendix B.

Runtimes with a collector: before each sample the JVM systems get `jcmd <pid> GC.run` and report
`GC.heap_info`; the cmux harness calls `debug.FreeOSMemory` and reports `HeapInuse`; caddy-l4 gets
a heap profile request with `gc=1`. The JVM runs G1, selected with `-XX:+UseG1GC`, with the heap
bounds of the JDK guide's defaults written out as `-Xms` and `-Xmx`.

## 4. Statistics

### 4.1 Sessions

- A session is four windows of a cell's two arms in mirrored order, X Y Y X. Which arm is X is
  drawn per session from the order's generator. Each window starts fresh processes, checks one
  exchange of each protocol the cell uses (the probe), then runs a 1 s warm-up and a 5 s measured
  window (the T1 defaults of `lab/t1/t1.py`, the design of P2's H6). B3 windows have the layout of
  WL7.
- An arm's value in a session is the mean of its two windows. The session's statistic is the
  ratio of the two arms' values, in the direction each hypothesis states.
- Placement on L, as in P2's H6, the SMT sibling of every used core idle, CPUs 0 and 1 for the
  system and the driver: in-process cells, the server on CPU 14, `opgen` on CPUs 2 to 13;
  hand-off cells, the front on CPU 14, the backend on CPUs 10 and 12, `opgen` on CPUs 2 to 9; B3
  and hard cases, the system or `ophold` on CPU 14, its backend on CPUs 10 and 12, `opcase` on
  CPUs 2 to 9; the 2-core secondary cells, the server on CPUs 12 and 14, `opgen` on CPUs 2 to 11.
  On W, the server on one logical CPU of the last physical core, its sibling idle, `opgen` on the
  cores between core 0 and the server's.
- Replicates are fixed per family: R_C for the cost family (4.6), R_B = R_M = 16 (P2's reference,
  between the D9 minimum and 32, a design choice: no pilot can size a superiority family, since
  nothing in this design sets its effect size). No sequential stopping. A session with an invalid
  window (section 7) is discarded and run again at the end of the order, at most ⌈R/4⌉ times per
  cell, a design choice that bounds the time. A cell with fewer than R valid sessions cannot pass
  and enters Holm with p = 1. Beside every decision the paper reports the cell's invalid windows
  per arm, with their reasons.
- Sessions are separate process lifetimes and are treated as independent. The lab job of each
  session is recorded, and an analysis clustered by job is reported; it decides nothing.

### 4.2 The two computations

Every tested cell is decided by two computations, both pre-specified. A cell passes only if it
passes under both. If they disagree, both are reported and the cell does not pass.
- Cell statistic: the median of the R session values.
- **Clustered BCa interval**, as in P2: 10,000 resamples of the sessions with replacement, the
  session as the cluster. The bias correction z0 counts ties as half; the acceleration comes from
  the jackknife over sessions; the share of resamples beyond a bound is clipped to
  [1/(2B), 1 - 1/(2B)], B = 10,000. The one-sided p-value against a bound is the level α at which
  the bound of the two-sided 1 - 2α interval equals it.
- **Exact sign test**: X counts the sessions whose value lies strictly on the hypothesis side of
  the bound; a tie, or a session without a value, counts against. At the null's boundary X is
  binomial with R and 1/2, and p = P(X ≥ x), computed exactly. A B3 session without a ratio takes
  Q = 0 in both computations (5.2).
- **Holm's step-down** per family at family-wise α = 0.025, one-sided, run once for each
  computation. A cell that cannot be tested enters with p = 1.

Floors of the BCa p. With z0 and the acceleration at 0, the smallest BCa p is about 5.0e-5. Under
the two one-sided tests of 4.3 the floor is Φ(Φ⁻¹(1/(2B)) + 2|z0|), so a cost cell can pass α/36
only if |z0| < 0.347. These hold for even R, where the jackknife acceleration of a median is 0.
For odd R = 2k + 1 it can reach 1/(6 sqrt(k(k + 1)(2k + 1))) in magnitude; on the unfavourable
side the floor at z0 = 0 rises to 8.6e-5 at R = 11, and the |z0| limit falls to 0.289 at R = 11,
0.311 at 15, 0.330 at 25 and 0.335 at 31. The sizing simulation of 4.6 runs this code as it is.

### 4.3 Equivalence (cost family)

The margin was fixed by Alex on 2026-10-02, from relevance and before any code existed: the widest
difference he still calls "no measurable cost" is a ratio between 0.98 and 1.02, for C1, C2 and
C3, on L and on W.
- Each cell has two one-sided nulls: "the median ratio is at most 0.98" and "it is at least
  1.02". Each is tested at α = 0.025 by both computations.
- Sign test: X_low counts the sessions whose ratio is above 0.98, X_high those whose ratio is
  below 1.02; a session exactly at a bound counts against.
- BCa: the lower test uses the share of resamples below 0.98, the upper test the share above 1.02.
- A computation's p-value for the cell is the larger of its two one-sided p-values (two one-sided
  tests). Before Holm's adjustment, the BCa form passes at 0.025 exactly when the two-sided 95%
  interval lies inside [0.98, 1.02].
- Each cost cell shows, beside its 95% BCa interval, the two-sided BCa interval at level 1 - 2α_j,
  where α_j = 0.025 / (m_C - j + 1) and j is the cell's rank among the family's BCa p-values (ties
  in the family's order).
- The null of each cell is that the ratio lies outside the margin. A noisy cell, or one with too
  few valid sessions, fails. A difference that is merely not significant never counts as
  equivalence.
- In the cost family the sign test is the binding computation: at Holm's first threshold it
  allows fewer sessions beyond a bound than the BCa needs. The methods say so.

### 4.4 Superiority (B3 and the mechanism family)

Each cell has one null, on the far side of its bound from the hypothesis: for B3 "the median Q is
at most 1.10"; for M1 and M3 "the median ratio is at most 1.00"; for M2 "the median ratio is at
least 1.00". The sign test counts the sessions strictly on the hypothesis side. The BCa p is the
level α at which one end of the two-sided 1 - 2α interval equals the bound: the lower end for B3,
M1 and M3, the upper end for M2.

### 4.5 Rule D9 and the sign-test grid

D9 asks for an R at which an exact paired test can pass the family's first Holm threshold,
2^-R < α/m.

| Family | m | α/m | D9 minimum R | R |
|---|---|---|---|---|
| Cost | at most 36, fixed by the pilot entry | 6.94e-4 at m = 36 | 11 (2^-11 = 4.88e-4) | R_C in {11, 15, 18, 22, 25, 28, 31}, from the pilot (4.6) |
| Robustness (B3) | 18 | 1.39e-3 | 10 (2^-10 = 9.77e-4) | 16 |
| Mechanism | 20 | 1.25e-3 | 10 (2^-10 = 9.77e-4) | 16 |

R_B = R_M = 16 is P2's reference, between the D9 minimum and 32, a design choice (4.1).

Cost family, sessions allowed beyond each bound at α/36, with the exact one-sided p of that count
and of one more:

| R_C | Allowed beyond each bound | p at that count | p at one more |
|---|---|---|---|
| 11 | 0 | 1/2048 = 4.88e-4 | 5.86e-3 |
| 15 | 1 | 1/2048 = 4.88e-4 | 3.69e-3 |
| 18 | 2 | 43/65536 = 6.56e-4 | 3.77e-3 |
| 22 | 3 | 897/2097152 = 4.28e-4 | 2.17e-3 |
| 25 | 4 | 3819/8388608 = 4.55e-4 | 2.04e-3 |
| 28 | 5 | 61219/134217728 = 4.56e-4 | 1.86e-3 |
| 31 | 6 | 942649/2147483648 = 4.39e-4 | 1.66e-3 |

The count applies to each one-sided test separately. At R = 32 the allowed count is still 6. With
fewer cells after the pilot, Holm's thresholds only rise, and the D9 minimum for any m_C ≤ 36 is at
most 11.

B3 and the mechanism family at R = 16: the smallest exact one-sided p is 2^-16 = 1.53e-5. One
session on the wrong side of the bound gives 17/65536 = 2.59e-4, which clears α/m in every cell of
both families; two give 137/65536 = 2.09e-3, which clears α/k only for k ≤ 11; three give
697/65536 = 1.06e-2, which clears it only for k ≤ 2.

### 4.6 Sizing R_C from the A/A pilot

The pilot only sizes R; it sets no margin.
1. The pilot. Every cost cell (section 6.1) runs P = 16 sessions (a design choice, the count of P2)
   with both arms in dedicated mode: two starts of the same binary and flags, the second on a fixed
   port offset so that every window transition changes port as in the A/B design. It holds no
   one-port data. Its order and reruns are those of section 8.
2. Per cell c, with y_i the log of session i's ratio:
   - centre: e_i = y_i - median(y), so power is computed at a true ratio of 1;
   - spread: s, the standard deviation of the e_i (divisor P - 1); bandwidth factor
     b = 0.9 × min(1, IQR(e)/(1.34 s)) × P^(-1/5), Silverman's rule of thumb (Silverman 1986,
     p. 45, as cited by Wikipedia's "Kernel density estimation") divided by s; upper bound
     s_U = s × sqrt((P - 1)/q), q the 0.20 quantile of the chi-square distribution with P - 1
     degrees of freedom, the one-sided 80% upper confidence bound under normality. For P = 16,
     q = 10.307 and s_U = 1.2064 s;
   - one simulated run of R sessions: draw z_1 to z_R with replacement from the e_i / s, add to each
     an independent normal draw with standard deviation b, multiply by s_U / sqrt(1 + b²), and take
     exponentials. The simulated sessions then have a variance of 0.9375 to 0.9507 of s_U²;
   - each run is analysed by the confirmatory code itself: both computations of 4.3 at
     [0.98, 1.02], the BCa with 10,000 resamples, and the sign test. A run passes if both p-values
     are at most α/36 = 6.94e-4;
   - Power_c(R) is the share of `N_SIM` = 1,000 runs that pass (a design choice; its Monte Carlo
     standard error at 0.80 is 0.0126).
3. Random streams. The cost cells are numbered c = 1 to 36 in the order of section 6.1. Run j of
   cell c draws its sessions from one stream seeded by (`SEED_SIM`, c, j): 31 indices with
   replacement, then 31 normal draws; the run at candidate R uses the first R sessions (common
   random numbers across candidates). The BCa resamples of run j at candidate R come from one
   stream seeded by (`SEED_SIM`, c, j, R). No result depends on the order of computation. The code
   is the analysis code at `ANALYSIS_COMMIT`, which pins its library versions.
4. Candidates: R = 11, 15, 18, 22, 25, 28 and 31, the values at which the sign test's allowed count
   steps between the D9 minimum and 32 (4.5).
5. Resolved: a cell is resolved if it has P valid pilot sessions and Power_c(31) ≥ 0.80. The
   target 0.80 is a design choice. Each resolved cell's R_c, the smallest candidate with
   Power_c(R) ≥ 0.80, is reported.
6. R_C is the smallest candidate at which every resolved cell has Power_c(R) ≥ 0.80. R = 31 always
   qualifies. If no cell is resolved, R_C = 31 and m_C = 0.
7. A cell that is not resolved leaves the confirmatory family at the pilot entry, still runs at
   R_C, and is reported as "not resolved at R ≤ 32"; no equivalence is claimed for it. m_C is the
   number of resolved cells. For each protocol, backend and host whose C1, C2 and C3 cells are all
   resolved, the pilot entry reports the product of their three Power_c(R_C), the simulated joint
   power of the claim "no measurable cost" there. It is reported, not targeted.

### 4.7 Order and seeds

All sessions of one family's cells on one host run in one shuffled order, so that drift spreads
over the cells. B3's order also holds B3's descriptive and secondary cells. The other secondary
cells run in one order per host. Seeds, placeholders fixed in one revision-log entry before the
code freeze (section 8 step 2), each checked against the lab journal as used by no earlier run,
and never changed after:
- orders: `SEED_ORDER_C_L`, `SEED_ORDER_C_W`, `SEED_ORDER_B_L`, `SEED_ORDER_M_L`,
  `SEED_ORDER_M_W`, `SEED_ORDER_S_L`, `SEED_ORDER_S_W`;
- resampling: `SEED_BOOT_C`, `SEED_BOOT_B`, `SEED_BOOT_M`, `SEED_BOOT_S`, one generator per
  family. Each cell of the family's list in section 6 (B3's descriptive cells after its Holm
  cells) draws its 10,000 resamples once, in that order, whether or not it is in Holm. Every other
  interval, those of section 10, draws from `SEED_BOOT_S`, bullet by bullet in the order of
  section 10; the bullets of the cost cells not resolved and of B3's descriptive cells draw
  nothing, since those intervals come from their family's draws. Within a bullet the cells follow
  the order of 6.1 (hypothesis, host, backend, protocol), then the system in the order of 2.3; a
  case, variant or form that the bullet names comes after the protocol, in the order the bullet
  names it; within a cell, the metrics follow the order the bullet names them. A bullet that
  covers cells of section 6 (the cost cells' CPU and memory, the analyses clustered by lab job)
  takes them in the order of section 6, family by family. A cell with fewer than R valid sessions
  draws nothing;
- the pilot: `SEED_PILOT_L`, `SEED_PILOT_W` (order) and `SEED_SIM` (4.6).

## 5. Hypotheses

### 5.1 Cost family (C)

Arms: one-port mode against dedicated mode, in-process dispatch, default detection mode, same
binary. Session ratio: one-port / dedicated. Load: one protocol per cell. Margin: [0.98, 1.02].
Test: 4.3, with Holm over the m_C resolved cells of C1 to C3 together. Replicates: R_C.

- **C1. Churn throughput is equivalent.** In every resolved C1 cell, the median ratio of
  connections per second under WL1 lies inside [0.98, 1.02]: both one-sided nulls rejected by
  both computations at Holm's thresholds.
- **C2. Keep-alive throughput is equivalent.** The same, for requests per second under WL3. Both
  modes run the same code once a connection is classified, so C2 is likely to pass; it is the test
  that one-port mode leaves no cost per request.
- **C3. Latency at a fixed load is equivalent.** The same, for median TTFB under WL2.

Stated before the run: the TLS handshake dominates a TLS churn connection, so the TLS cells have
little power to show the cost of a 6-byte check, and are not read as evidence about it.

### 5.2 Robustness family (B)

- **B1. Conformance.** Deterministic, not in Holm. For every hard case of Appendix A, every
  backend, both detection modes, every dispatch mode that applies, and 16 replicates (a design
  choice: the cases are deterministic, and the replicates exercise the timing of arrival), the
  server's outcome and transcript equal the frozen table. One deviation fails B1. A connection
  classified other than as its script's protocol in any measured window of any family is also a
  failure of B1.
- **B2. Bounded behaviour.** Deterministic, not in Holm:
  - (a) never early: no fallback, close or deadline event happens before its deadline on the
    server's clock (the loop re-reads the clock after every wait);
  - (b) each deadline is handled in the first loop pass whose wait returned at or after it;
  - (c) each connection is classified in the loop pass that received its deciding byte;
  - (d) no pending connection holds more user-space payload bytes than its mode's bound (2.1), and
    one that has received no byte holds no data buffer;
  - (e) a half-close before a decision closes the connection in the pass that observes it.
  The lateness of timed events and the decision latency are reported per backend as distributions,
  and not tested.
- **B3. Footprint per pending connection.** In Holm. Counted footprints W (WL7), each system as
  configured for B3 (Appendix B), not detection designs alone. Ks in W and in `K_BASE` is net of
  the skb caches' growth, so a queued skb is counted once, in Kq; the two residuals of WL7 are
  named beside the results.
  - Margin: Alex decided on 2026-10-02, before any B3 window ran, that a cell counts as a win only
    if (T_comp + `K_BASE`) / (T_srv + `K_BASE`) is at least 1.10. By WL7 this ratio is
    W_comp / W_srv.
  - Session statistic: Q = W_comp / W_srv, each arm's W the mean of its two windows. A session
    whose W_srv is 0 or less has no ratio: it takes Q = 0 in both computations, below every bound,
    so it counts against.
  - Null per cell: "the median Q is at most 1.10". Sign test: X counts the sessions with Q strictly
    above 1.10, with X binomial with 16 and 1/2 at the boundary. BCa: p is the level at which the
    lower bound of the two-sided 1 - 2α interval equals 1.10, the share of resamples below 1.10
    clipped as in 4.2.
  - Holm over the 18 cells of section 6.2, once per computation; a cell passes only under both.
  - Reported beside each cell: both W and their parts U, Kq and Ks - `K_BASE`; the skb caches'
    growth subtracted from each Ks, and within it, per arm, the median growth of a merged cache's
    shared cache, with its co-tenants named (WL7); `f`; `K_BASE`; D = W_comp - W_srv in bytes
    per pending connection with its 95% BCa interval; the median Q with its 95% interval and its
    interval at Holm's level; the sign-test count; the server's bounds.
  - The server runs in relay mode against the proxies and in-process against the libraries, in
    its default detection mode.
  - The 16 descriptive cells (6.2) use the same statistic and are reported with their intervals
    and counts against 1.10. They decide nothing: they measure the runtime's collector as much as
    the detector.

### 5.3 Mechanism family (M)

Holm over the 20 cells of section 6.3, R_M = 16, test of 4.4.
- **M1. The default detection mode is cheaper.** In-process churn (WL1): the median ratio of
  connections per second, default mode / other mode, is above 1.00 in every cell of
  {HTTP/1.1, h2c} × {epoll, io_uring, IOCP}. Rule E fixes the default per backend after the pilot
  entry (section 8), and M1's direction follows it; M1's sessions are new data. On IOCP the peek
  mode includes the switch to replay; the counters report how often, and the paper says that M1
  on IOCP measures the API's limits as much as the idea.
- **M2. In-process dispatch costs less than relay.** The median ratio of server CPU per
  connection (WL6), in-process / relay, is below 1.00 in every cell of {HTTP/1.1, TLS} ×
  {epoll, io_uring}. The relay arm passes TLS through to a backend that terminates it, so both
  arms make one handshake per connection.
- **M3. The server's relay is faster than each proxy.** One front core, the stub backend, churn
  (WL1): the median ratio of connections per second, server / proxy, is above 1.00 in every cell
  of {TLS routed by SNI, plaintext HTTP/1.1} × {nginx, HAProxy, Envoy, caddy-l4, sslh-ev}. The
  server runs on epoll, the accept model all five use. Every system runs its M3 configuration,
  which holds exactly two routes, TLS by SNI to one stub port and everything else to the HTTP/1.1
  stub port. What each examines to choose differs (nginx tells TLS from not-TLS; the server runs
  its whole table), and the paper says so. Connection logging is off in every system; Envoy's
  statistics stay on as the server's counters do; nginx gets `multi_accept on`; HAProxy gets
  `option splice-auto` only if the server's relay splices. Listen overflows are recorded per
  window and reported beside each cell. The headline is closed-loop throughput; M3's open-loop
  TTFB is secondary.

## 6. Cell lists

### 6.1 Cost family, 36 cells at most

The order below is the family's order, used for the cell numbers c of 4.6 and for the resampling
generator. For each hypothesis (C1, then C2, then C3), the L cells come before the W cells;
backends epoll, io_uring, then IOCP; within a backend, HTTP/1.1, h2c, TLS with HTTP/1.1, MQTT.

| c | Hypothesis | Host | Backend | Protocols, in order |
|---|---|---|---|---|
| 1 to 4 | C1 | L | epoll | HTTP/1.1, h2c, TLS, MQTT |
| 5 to 8 | C1 | L | io_uring | the same |
| 9 to 12 | C1 | W | IOCP | the same |
| 13 to 16 | C2 | L | epoll | the same |
| 17 to 20 | C2 | L | io_uring | the same |
| 21 to 24 | C2 | W | IOCP | the same |
| 25 to 28 | C3 | L | epoll | the same |
| 29 to 32 | C3 | L | io_uring | the same |
| 33 to 36 | C3 | W | IOCP | the same |

The confirmatory family is the resolved subset, listed in the pilot entry; m_C is its size.

### 6.2 B3, 18 Holm cells and 16 descriptive cells, all on L

Holm cells, in the family's order (case, then system, then backend epoll before io_uring):
- silent case: nginx, HAProxy, Envoy, sslh-ev, hyper-util; each on epoll and io_uring (10);
- partial-ClientHello case: nginx, HAProxy, Envoy, sslh-ev; each on epoll and io_uring (8).
  hyper-util serves no TLS.

Descriptive cells, outside Holm: Netty, Jetty, caddy-l4 and cmux, in both cases, on both backends
(16).

### 6.3 Mechanism family, 20 cells

In the family's order:
- M1: HTTP/1.1 on epoll, io_uring, IOCP; h2c on epoll, io_uring, IOCP (6; the IOCP cells on W);
- M2: HTTP/1.1 on epoll, io_uring; TLS on epoll, io_uring (4);
- M3: TLS routed by SNI against nginx, HAProxy, Envoy, caddy-l4, sslh-ev; then plaintext HTTP/1.1
  against the same five, in the same order (10).

## 7. Validity

A window is invalid, and is listed with its reason, if:
- the server, the backend or the probe failed, or no exchange completed;
- on L, the error share exceeded 0.1%, the generator's CPUs were more than 90% busy in a
  saturation cell, or the mean CPU MHz drifted more than 2% from the session's value (the rules of
  `lab/t1/t1.py`, as P2's H6 used them);
- on W, the rules of W's procedure that can be computed there (section 9);
- any connect failed;
- any connection was classified other than as its script's protocol. This is also a failure of
  B1 (5.2), not only a reason to run the session again;
- in hand-off cells, a backend core was more than 90% busy (a design choice, by analogy with the
  generator rule);
- in an open-loop window, fewer than 99% of the exchanges due in it completed (a design choice,
  from audit F11);
- in the cost family, M1, M2 and B3, `TcpExtListenOverflows` or `TcpExtListenDrops` (nstat)
  changed during the window. In M3 the proxies keep their own backlogs, so overflows there are
  recorded and reported beside each cell instead;
- in a B3 or `ophold` window: the footprint W of WL7, with Ks net of the skb caches, changed
  between the two samples by more than the larger of 2% of sample 2's W (a design choice, a fifth
  of B3's margin) and `SETTLE_ABS` = 8 bytes per pending connection (a design choice that keeps
  the rule defined near 0: 80,000 bytes over `N_PEND`, above the 1 kB unit in which `/proc`
  reports `VmRSS` and `Slab`); or the host's TIME-WAIT count at either sample differs from the
  baseline's; or fewer than `N_PEND` of the system's accepted sockets are established at either
  sample; or, at the baseline or either sample, an skb cache or the shared cache of a merged skb
  cache cannot be found or read, or that shared cache's co-tenants differ from the baseline's.

The merged skb cache (WL7). At the baseline and at each sample of every B3 and `ophold` window,
the run script records the co-tenants present (the names linked to the shared cache's directory
in `/sys/kernel/slab/`) and the shared cache's counts (its `/proc/slabinfo` line, and its `slabs`
and `objects`). A set of co-tenants that differs from the one WL7 names is recorded in the
revision log when it is first seen and named in the paper; it does not by itself make a window
invalid.

TIME-WAIT sockets are slab objects and last 60 s (`TCP_TIMEWAIT_LEN`, include/net/tcp.h line 140
at v7.2). So B3 and `ophold` windows close by reset and create none, and the first B3 or `ophold`
window of a lab job starts at least 60 s after the last other window on L ended.

Recorded per window, deciding nothing: the TIME-WAIT count at start and end, the change of
`TcpExtTCPTimeWaitOverflow`, the source-address block, and on W the power plan and the timer
resolution.

Invalid sessions are run again by the rule of 4.1, and the pilot's by the rule of section 8.

## 8. Order of freezes and runs

Each step starts only after the one before it is committed.
1. **The hypotheses freeze.** This file is frozen before any code of the server exists.
2. **Engineering.** Development runs are development data: never results, cited only in the
   revision log and the lab journal, and disclosed in the methods. Before the code freeze they may
   time dedicated mode against anything, and one-port mode against the competitors or against
   another one-port option. No window, on any code, times one-port mode against dedicated mode
   before the pilot entry. A dedicated window and a one-port window against the same competitor,
   at the same protocol, backend and host, still give an indirect one-port against dedicated
   ratio on pre-freeze code. The competitors are the only reference both modes may share before
   the code freeze, so every such pair of development cells is listed in the revision log when it
   runs, and in the paper's methods. No rule of this file uses it. Why one-port windows are
   allowed here at all: rule D2 asks for the server to be engineered until it wins, which needs
   such timings, and the pilot must run on the frozen code, after them. They hold no cost
   contrast, and nothing they measure enters the pilot's rules.
   Before engineering ends, one revision-log entry fixes every seed of 4.7, and the analysis code
   that runs 4.6 is committed with its tests (`ANALYSIS_COMMIT`).
3. **The code freeze.** One commit, `CODE_FREEZE`, of the server, the generators, the holder, the
   harnesses, the pins and the tests, with green sanitizer records (section 11) and a passing test
   suite. The values engineering sets are recorded in the revision log then (section 9).
4. **On the frozen binary, in dedicated mode only:** rule E's IOCP receive form (below), then the
   A/A pilot on each host, then its timer and split parts.
   - The pilot's sessions run in an order shuffled with `SEED_PILOT_L` or `SEED_PILOT_W`, the C1
     and C2 cells of a host before its C3 cells.
   - Timer part, per host: on each backend, 128 runs, one connection at a time, of HC12's script
     against the dedicated HTTP/1.1 port with the PROXY setting on. Each waits for T_hdr = 3 s in
     the same deadline queue that T_fb uses in one-port mode. The statistic is each run's lateness,
     from the deadline to the start of the loop pass that handled it. 128 is a design choice, the
     server's runs per timer case on L.
   - Split part, per host: on each backend, HC2's HTTP/1.1 script split after its first byte,
     against the dedicated HTTP/1.1 port, 16 replicates (the hard cases' replicate count) at each
     tested gap of 5, 10, 20, 50 and 100 ms (a design choice, a 1-2-5 series). A replicate shows
     the split read when the counters of its one connection show two receives that returned
     payload.
   - Failed runs of the parts. A timer run or split replicate whose server or `opcase` failed is
     excluded and listed in the pilot entry. The parts run again only with the whole pilot, under
     its cap below. A host with no valid timer run has no G, and HC7 is not run on it, as when G
     is not below T_fb. A tested gap at which some backend has no valid replicate does not qualify
     for `GAP_SPLIT`.
   - Reruns. Within the pilot, a session with a window invalid by a rule of section 7 is run again
     at the end of the pilot's order, at most ⌈P/4⌉ = 4 times per cell; a cell that still lacks P
     valid sessions is not resolved. The whole pilot may be run again at most once, with the same
     seeds, and only before the simulation of step 5 starts: if an infrastructure fault stopped it
     (the host failed, the lab lock was lost, the run script crashed), or if a named failure
     forced a change of the frozen code (a failing test, a sanitizer record that is not green, the
     gate refusing a build, or a crash of a first-party program), recorded with its evidence in
     the revision log, and the new build has new records. The abandoned pilot is archived, named
     in the revision log with its reason, and not used. Once the simulation of step 5 has
     started, no pilot session runs again, for any reason.
   - If the cap is spent, or the repeat is itself stopped, the pilot entry is made from the last
     pilot: a cell without P valid sessions is not resolved, and a timer run or split replicate
     that did not take place counts as excluded (above). A further code change then follows the
     rule for a later change (below).
5. **The simulation** of 4.6, at `ANALYSIS_COMMIT`, with `SEED_SIM`, on the pilot's data alone.
6. **The pilot entry.** One revision-log entry of this file, made from the pilot's and the
   simulation's outputs alone and committed before any one-port window of the frozen code. It
   needs both hosts' pilots, since R_C and m_C span L and W. It records the values of section 9.2.
   Nothing in it is chosen: every value follows from the rules of this file.
7. **After the pilot entry:** rule E's default detection mode and relay copy; M2's rates; the B3
   feasibility windows (one window per system and case, development data); `K_BASE`; and every
   confirmatory, secondary and hard-case run, each family in its own order.

Rule E. Three choices per backend: the default detection mode, the IOCP receive form (a zero-byte
`WSARecv` then `recv` into the handler's buffer, or a `WSARecv` with the buffer posted at once),
and the relay copy (user-space buffers of `RELAY_BUF` bytes per direction, or `splice`). Both
options of each are built into the frozen binary as flag values, since in P2 a layout change of
the binary alone moved timings. An option replaces the proposed default (replay; the zero-byte
receive; user-space buffers) only if every session of at least 6 development sessions of HTTP/1.1
churn favours it and its operations per connection are not higher. Six is the smallest count at
which an exact sign test can reach p = 2^-6 = 0.0156, below 0.025. The IOCP receive form also
governs dedicated mode's reads on W, so it is decided before the W pilot, with both arms in
dedicated mode. The other two exist only in one-port mode and are decided after the pilot entry,
before any confirmatory window. Each choice is written into the revision log when made. If rule E
chooses `splice`, HAProxy gets `option splice-auto`.

A code change once the pilot has started. Before the simulation of step 5 starts, a change that a
named failure forces (step 4) needs new records and a new pilot, under the cap above. Every other
change follows the rule for a later change: a change that no named failure forces, a change once
the simulation has started, and a change once the cap is spent. Under that rule the pilot is not
run again, and its outputs go into the pilot entry or, if the entry is committed, stand; the new
build gets new records; every confirmatory window of the old build is archived and not used; the
runs start again on the new build; and the revision log records the change as a deviation. No
one-port window of either build runs before the pilot entry.

## 9. Values to be filled in

None of these has a value yet. Each is recorded in the revision log at the step named, by the rule
named, and is never chosen after data that could favour a value.

### 9.1 Before or at the code freeze (section 8 steps 2 and 3)

| Name | Rule |
|---|---|
| Every seed of 4.7, `SEED_SIM` included | fixed in one entry before the code freeze, each checked against the lab journal as used by no earlier run |
| `ANALYSIS_COMMIT` | the commit of `analysis/` that runs 4.6 and the confirmatory analysis, with its tests |
| `CODE_FREEZE` | the commit of section 8 step 3 |
| `K_SRC` | the size of each window's source-address block, set so that no connect fails in the development runs |
| `N_ACCEPTEX` | the AcceptEx requests each IOCP listener keeps outstanding, the same in both modes |
| `RELAY_BUF` | the relay's user-space buffer per direction, reported beside each proxy's default |
| `N_BG_TLS`, `N_BG_MQTT`, `N_BG_SILENT` | the background of the secondary mixed-protocol cell |
| ℓ | the length of the recorded ClientHello, measured when it is recorded |
| The skb caches on L | read on 2026-10-02 (WL7). Read again at the code freeze: that `/proc/slabinfo` exists; for "skbuff_head_cache", "skbuff_fclone_cache" and "skbuff_small_head", the name under which `/proc/slabinfo` lists each and the co-tenants of any merged one, from `/sys/kernel/slab/`; and the page size. A difference from WL7's reading is handled by WL7's rule for merged caches |
| Pins | OpenSSL (latest 3.5), nghttp2, the competitors, the JDK (latest LTS), the Rust toolchain, xcaddy; by archive URL and sha256 |
| W's procedure | power plan, boost policy, timer resolution, and a CPU frequency counter tested against a known load; approved by Alex. If no counter passes, W windows are validated without the frequency rule and the paper says so |

### 9.2 In the pilot entry (section 8 step 6)

| Name | Rule |
|---|---|
| `CODE_FREEZE` and `ANALYSIS_COMMIT`, named again | section 8 steps 2 and 3 |
| The pilot archive's sha256, its invalid windows and reruns, and its excluded timer runs and split replicates | section 8 step 4 |
| Power_c(R) for every cost cell and candidate, and each resolved cell's R_c | 4.6 steps 2 to 5 |
| The resolved list | 4.6 step 5 |
| `R_C` | 4.6 step 6 |
| `m_C` | 4.6 step 7 |
| The joint power per protocol, backend and host | 4.6 step 7 |
| λ for each C3 cell | WL2, from the C1 pilot sessions |
| `G_L`, `G_W` | per host, the smallest whole number of milliseconds above the largest lateness of the timer part's valid runs over all the host's backends, so above its 99th percentile. If the host has no valid run, or G is not below T_fb, HC7 is not run on that host, and the paper says why |
| `GAP_SPLIT` | the smallest tested gap at which every valid replicate on every backend of L and W shows the split read, each backend having at least one valid replicate at that gap; if none does, 100 ms, and HC2, HC3 and HC10 report the share of their replicates that split |
| The IOCP receive form, named again | rule E; recorded when it is made, before the W pilot |

### 9.3 After the pilot entry, before the runs that use them (section 8 step 7)

| Name | Rule |
|---|---|
| The default detection mode per backend, and the relay copy | rule E |
| `M2_RATE` per M2 cell | `RATE_FRAC` × the smaller of the two arms' median closed-loop connections per second over 6 development sessions on the frozen binary |
| `K_BASE` | WL7, 16 `ophold` windows; a measurement, reported as such |

## 10. Secondary analyses

Secondary: not in any Holm family, deciding nothing. Cells that need sessions run at R = 16, a
design choice (P2's reference). Each is reported with its 95% BCa interval where it has one.
- CPU per connection or request and resident memory for every cost cell (WL4); p99 TTFB (WL2).
- Cost cells not resolved by the pilot, at R_C.
- SSH in the cost family: C1 to C3 on three backends (9 cells). In one-port mode the server's
  identification line waits for the client's `SSH-`, while in dedicated mode it is sent at accept,
  so the message order differs by mode, and the paper says so. Their C1 sessions run first, and
  their C3 rate is `RATE_FRAC` × the slower arm's median connections per second in them.
- The mixed-protocol cell: C1's HTTP/1.1 churn with a fixed background of TLS keep-alive, MQTT
  keep-alive and silent connections, the same in both modes, on each backend (3 cells).
- TLS with session resumption, and TLS with ALPN `h2`: C1 on each backend (6 cells).
- 2 server cores: C1 HTTP/1.1 on each backend (3 cells); and on epoll and io_uring the
  `SO_REUSEPORT` group against the shared listener, both in one-port mode (2 cells).
- The server's relay on io_uring against the proxies (10 cells).
- On IOCP, on a listener without a fallback, against the default form, which is AcceptEx with no
  receive buffer (`dwReceiveDataLength` = 0) followed by the receive form rule E chose (2 cells):
  AcceptEx with a receive buffer; and the receive form rule E did not choose (the zero-byte
  `WSARecv` or the posted buffer), after the same AcceptEx.
- Operations and copies per connection for every mode and backend; system calls per connection
  for the proxies, from `perf trace -s` over untimed windows. On L, one untimed window per cost
  cell checks the server's system-call counters against `perf trace -s`.
- For M1 and M3, TTFB at a fixed load (16 cells), λ = `RATE_FRAC` × the slower arm's median
  connections per second in the cell's closed-loop sessions; for every M cell, CPU per connection.
- B3 with the server in its other detection mode against its default mode, in both cases on both
  Linux backends (4 cells), with Q = other / default; a session whose default-mode W is 0 or less
  takes Q = 0, as in B3.
- B3's 16 descriptive cells (5.2).
- The competitors' outcomes on the hard cases they cover, at matched timers and at their
  defaults: `R_COMP_CASES` = 3 replicates per case and setting, a design choice, since the table is
  descriptive. A system with no detection timer is observed for at most `T_OBS` = 60 s, twice the
  longest default timer among the others (30 s), and recorded as "no decision within `T_OBS`".
- The lateness and decision-latency distributions of B2.
- An analysis of every family clustered by lab job.

## 11. Sanitizer coverage (rule D5)

Records, made with the lab's sanitizer scripts, covering by inputs hash the targets `oneport`,
`opgen`, `opcase`, `ophold` and the test suite:
- on L, clang 22.1.8: ASan with UBSan, TSan, and MSan with an MSan-instrumented libc++;
- on W, MSVC 19.51.36246: ASan, with one compiler because the gate matches the compiler.
  clang-cl is not used: P1's design notes a clang-cl stack-use-after-return false positive (P1,
  section 4.6).

The suite in every record runs: the detection table on its corpus at every split; the whole
hard-case table at short test timeouts; every mode of the binary (one-port, dedicated, stub); both
detection modes and their peek paths; the check of 1(b) in both forms, with a byte in the pass of
the expiry; both dispatch modes with a backend; the HTTP/1.1 grammar on invalid input in both
modes; TLS handshakes; h2 sessions; MQTT, SSH and SMTP exchanges; the counters; `ophold`; and under
TSan, two workers on the shared listener. On L both Linux backends run; on W, IOCP.

The gate: a measured build is refused unless green records on the same host cover every
first-party target by inputs hash, with the same compiler, configuration, pins file hash and
fetched archives. Every measured build is gated: the server and backend, the generators, the
holder and the harnesses. Logs stay under `~/lab/records-logs/<record>/` and are archived with a
sha256; the report pattern is the lab's shared, self-tested one.

Declared gaps, for `bench/coverage.json`:
- **OpenSSL's assembly.** No sanitizer instruments it. Its MSan build turns assembly off, so MSan
  covers the C fallbacks, not the measured build's assembly paths; the ASan and TSan builds keep
  the assembly, which they do not instrument either.
- **OpenSSL under TSan**, unless engineering builds it with TSan and the suite passes, which the
  revision log then records.
- **io_uring kernel writes are invisible to MSan.** Mitigation: value-initialise every structure a
  raw call fills, and unpoison exactly the `res` bytes a completion reports, in the selected
  provided buffer for a receive; the tests check `res` against the bytes used.
- **Competitor binaries and runtimes** (nginx, HAProxy, Envoy, caddy-l4, sslh-ev, the JVM, the Go
  runtime, Rust's standard library and tokio): not first-party; pinned, not instrumented.
- **The harnesses.** The Go and Rust harnesses get ASan with UBSan and TSan records; only their
  MSan gap is declared. No sanitizer applies to the Java harnesses; that gap is declared whole.
- **Windows:** only ASan is required. A third-party library that cannot be built with MSVC's
  AddressSanitizer is declared here before the code freeze.

## 12. What counts against the claims

- **C.** A cell that fails is reported with its interval as "equivalence not shown". It is called a
  measured cost only where its 95% BCa interval lies wholly outside [0.98, 1.02]. "No measurable
  cost" is claimed only as "equivalent within [0.98, 1.02]", for single-protocol load, and only for
  the protocol, backend and host where C1, C2 and C3 all pass, quoting the joint power and the
  intervals at Holm's level. Cells not resolved by the pilot are named as such.
- **B1 and B2.** Not narrowed. A failure in any run of the frozen code is reported as a failure, and
  the robustness claim is not made.
- **B3.** Narrowed to the competitors and cases where it passes. A pass is written "the competitor
  held at least 1.10 times the server's counted footprint per pending connection, by B3's test",
  always with D and its interval, and with WL7's exclusions and residuals named. A cell that
  fails is "not shown". "Loss" is used only where the 95% BCa interval of Q lies wholly below
  1.00, as a description, not a test.
- **M1 and M2.** Reported per backend as measured. A cell that fails shows only that a difference
  was not shown, never that the mode "costs nothing extra".
- **M3.** Narrowed to the proxies and protocols where it passes. A cell that fails is "not shown";
  "loss" only where the 95% BCa interval of the ratio lies wholly below 1.00.
- **The narrowing order** (Alex, 2026-10-02). The cost family leads the paper. If a family cannot be
  won cleanly (rule D2), the claims narrow in this order: M3 first, to the proxies and protocols the
  server beats; then B3, to the competitors and cases it beats; then the cost family, per backend.

## 13. The analysis

`analysis/` computes every decision above from the archived runs and writes `summary.json`; the
paper's numbers come only from `results/macros.tex`, generated from it. Raw outputs go under
`lab/runs/` and are archived with a sha256. Nothing is run again to change a decision. Machine time
is planned in `design/proposal.md`, section 9; it decides nothing.

## Appendix A. Hard cases and their expected outcomes

Frozen with the hypotheses. Each case runs on every backend, in both detection modes, with
in-process and relay dispatch where it applies, 16 replicates. `G` is `G_L` or `G_W` (9.2).

| Id | Case | Expected outcome for the server |
|---|---|---|
| HC1 | The whole signature in one write, for HTTP/1.1, h2c, TLS, MQTT 3.1.1, MQTT 5.0 and SSH | classified; the transcript equals the dedicated port's |
| HC2 | Split signature: two writes, split after byte k, for every k from 1 to the matcher's `need` minus 1, `GAP_SPLIT` apart | as HC1 |
| HC3 | Drip: one byte per write, the whole signature arriving before T_dec | as HC1 |
| HC4 | Slow drip: a partial signature that is still incomplete at T_dec | closed at T_dec, "undecided" (1 d) |
| HC5 | Silent client, SMTP fallback configured; then an SMTP client script | greeting after T_fb; the transcript equals the dedicated SMTP port's (1 a, c) |
| HC6 | Silent client, no fallback | closed at T_dec, "silent" (1 f) |
| HC7 | HTTP/1.1 client whose first byte is written at T_fb + G, SMTP fallback; and its twin whose first byte is written at T_fb - G | the first goes to the fallback, and its request gets 500 from the SMTP handler (1 g); the twin is HTTP/1.1 |
| HC8 | SMTP client that sends EHLO before any greeting | rejected at once: no matcher starts with E (1 e) |
| HC9 | PROXY v2 header, then an HTTP/1.1 request, in one write | header consumed; the source address the server records equals the header's; HTTP/1.1 response |
| HC10 | PROXY v2 header split after every byte k inside it, then HTTP/1.1 | as HC9 |
| HC11 | PROXY listener, no header, plain HTTP/1.1 | closed at once: the header is required, never guessed |
| HC12 | PROXY v2 header incomplete, then silence | closed at T_hdr |
| HC13 | PROXY v1 line, then a TLS ClientHello | TLS |
| HC14 | PROXY v2 with TLVs, at most 536 bytes, then MQTT; and one longer than 536 bytes | MQTT; rejected |
| HC15 | PROXY header complete, then silence, SMTP fallback | greeting T_fb after the header completed |
| HC16 | The h2 preface with the byte at position k replaced by its bitwise complement (b XOR 0xFF), for every k from 0 to 23 | rejected when byte k arrives: every complement of a preface byte is at least 0x80, which no matcher's first-byte set holds, and after the first byte the HTTP/1.1 matcher has already rejected "PR" |
| HC17 | One leading CRLF, then HTTP/1.1; and two leading CRLFs | HTTP/1.1; rejected |
| HC18 | SSH identification line with a comment after a space | SSH |
| HC19 | ClientHello with record version `03 01`, and with `03 03` | TLS |
| HC20 | ClientHello fragmented across two TLS records, in two writes | in-process: the handshake completes; pass-through: routed by its SNI |
| HC21 | Peer shuts down writing after a partial signature; and after no byte | closed at once, "undecided"; closed at once, "silent" (1 h) |
| HC22 | Peer resets during detection | state freed; counters consistent; no leak under the sanitizer records |
| HC23 | 4,096 bytes starting `GETX`; 4,096 bytes of `A` (a design choice, far beyond B_dec) | rejected at the first impossible byte; no budget exceeded |
| HC24 | MQTT CONNECT with a Remaining Length of 1, 2, 3 and 4 bytes; MQTT 3.1 `MQIsdp` | MQTT for the four; rejected |
| HC25 | `GET key` and CRLF, as a Redis inline command | HTTP/1.1, answered 400 |

The references "1 a" to "1 h" are the fallback rules of section 1.

## Appendix B. Competitor configurations

Every configuration file is in `bench/competitors/`, every line with its reason. In M3 every front
gets one core; in B3 every competitor gets the server's core count. Connection logging is off in
every system. Each proxy has three configurations: cases (every route its features cover, the
matched timers, the fallback where it has one), M3 (exactly M3's two routes), and B3 (the M3
configuration plus WL7's limits, the 60 s timer and the buffer settings below). Each library
harness has two, cases and B3, its B3 configuration starting from its case configuration.

| System | Configuration |
|---|---|
| nginx | `worker_processes 1`, `worker_cpu_affinity` on the front core; the event method left to nginx (epoll with RDHUP on Linux, so its peek path); `ssl_preread on` with `map $ssl_preread_server_name`, non-TLS to the HTTP upstream; `preread_timeout` and `proxy_protocol_timeout` matched; `multi_accept on`; no access log. B3: `worker_connections` and `worker_rlimit_nofile` at 2 × `N_PEND`; `listen ... backlog=N_PEND`. |
| HAProxy | `mode tcp`; `tcp-request inspect-delay` matched; `tcp-request content accept` on `req.ssl_hello_type 1`; `use_backend` on `req.ssl_sni`, `req.proto_http`, `req.payload(0,4)` for `SSH-` and `mqtt_is_valid`; `default_backend` for the fallback; one thread, from the CPU affinity set by `taskset`; no `log` line; `option splice-auto` only if the server's relay splices. B3: global `maxconn` at 2 × `N_PEND`, which also sets the backlog. |
| Envoy | The benchmarking FAQ's advice: release binary, `--concurrency 1`, circuit breaking disabled, filter chains only for the compared features. tls_inspector and http_inspector, proxy_protocol in the PROXY cases; filter chains by `server_names`, `transport_protocol` and `application_protocols`; tcp_proxy; `listener_filters_timeout` matched; `continue_on_listener_filters_timeout` true only in the fallback cases; no access log; default statistics on. B3: `tcp_backlog_size` `N_PEND`; no downstream connection limit; `listener_filters_timeout` 60 s. |
| caddy-l4 | The layer4 app with the tls, http, ssh and regexp matchers and the proxy handler; `matching_timeout` matched; GOMAXPROCS 1 from the affinity mask; logging above Debug. B3: backlog from `net.core.somaxconn`; a heap profile with `gc=1` before each sample; `matching_timeout` 60 s. Pinned by commit, read again at the code freeze. |
| sslh-ev | Probes tls with `sni_hostnames`, http, ssh, and a regex probe for MQTT (built with `ENABLE_REGEX`); `timeout` matched in whole seconds; `on-timeout` names the fallback in the fallback cases; `verbose-connections: 0`. B3: `max_connections` unset; `timeout` 60. Its backlog is 50, hard-coded. |
| Netty | A harness after the `PortUnificationServerHandler` example with `SniHandler`, `CleartextHttp2ServerUpgradeHandler`, `HAProxyMessageDecoder` and the HTTP codec; the native epoll transport; `ReadTimeoutHandler` matched; G1 with `-XX:+UseG1GC` and the guide's default heap bounds written out. B3: `SO_BACKLOG` `N_PEND`. |
| Jetty | `DetectorConnectionFactory` with `SslConnectionFactory` and `ProxyConnectionFactory`, then HTTP/1.1 with the h2c upgrade; idle timeout matched; the collector and heap as Netty. B3: `acceptQueueSize` `N_PEND`. |
| cmux | `HTTP2()`, `HTTP1Fast()`, `TLS()`, `PrefixMatcher("SSH-")`, and `Any()` last for the fallback; `SetReadTimeout` matched; Go's collector defaults. B3: backlog from `net.core.somaxconn`; `debug.FreeOSMemory` before each sample. |
| hyper-util | `server::conn::auto` on a tokio runtime with one worker thread; no detection timer; HTTP/1.1 and h2c only. B3: `TcpSocket::listen` with backlog `N_PEND`. |

Buffers in B3. The rule, a design choice: a default is changed for B3 only where the project
documents a value for a deployment that faces many untrusted connections, or documents that the
buffer grows on demand, so that a smaller start refuses no input the default accepts. Otherwise
the default is kept.

| System | Settings that size what a pending connection holds | In B3 |
|---|---|---|
| nginx | `preread_buffer_size` 16k; `proxy_buffer_size` 16k, which also sizes reading from the client | Kept. No value for many pending connections and no growth is documented, and a full preread buffer ends the session, so a smaller one would refuse ClientHellos the default accepts. |
| HAProxy | `tune.bufsize` 16384; `tune.maxrewrite`; `option use-small-buffers` | `tune.bufsize` and `tune.maxrewrite` kept: configuration.txt v3.4.6 (line 4208) says "It is strongly recommended not to change this from the default value". `option use-small-buffers`, with no parameter, set in the backends (it cannot be set in a frontend); it acts on queued requests, L7 retries and health checks, which a pending connection does not have, so it should change nothing B3 measures. |
| Envoy | the listener's `per_connection_buffer_limit_bytes` (default 1 MiB); tls_inspector's `initial_read_buffer_size` (default: the maximum, 16 KiB; a smaller initial size doubles on demand up to it); http_inspector has none | Configured: `per_connection_buffer_limit_bytes` 32768 on the listener and the cluster, as the docs' edge page asks of TCP proxies; `initial_read_buffer_size` 256, the smallest value the proto accepts, a design choice, since the buffer doubles on demand. The edge page's admin and overload-manager items size nothing a connection holds and are not configured. |
| caddy-l4 | none: the prefetch chunk and the matching cap are code constants | Nothing to configure. |
| sslh-ev | none: probing reads into `BUFSIZ` bytes and keeps the bytes in a queue that grows with `realloc` | Nothing to configure. |
| Netty | `ChannelOption.RECVBUF_ALLOCATOR` and `ChannelOption.ALLOCATOR`; the base default receive allocator is adaptive, 64 to 65536 bytes, starting at 2048 | Kept: no Netty document read gives a value for many pending connections. |
| Jetty | `jetty.httpConfig.inputBufferSize` 8192 and the `bytebufferpool` properties; the detector's own buffer of 8192 | Kept: the modules page gives no value for many pending connections. |
| cmux | none | Nothing to configure. |
| hyper-util | none for detection: a fixed 24-byte buffer | Nothing to configure. |

The sources of every line are in `design/proposal.md`, section 6 and "Sources added beyond the
survey", and in `design/competitor-survey.md`.

## Revision log

### 2026-10-02: Readings fixed during engineering (M1), before the code freeze

M1 (`design/status.md`, "Where the frozen text was read one way") read the frozen text in these
13 places. Each line is a reading of the text above, not a change of a rule; nothing above this
log is edited. No hard case of Appendix A changes outcome by them.

1. Peek mode's low-water mark is the fewest bytes in all with which some remaining candidate could still say yes; bytes below it raise no event, so they are not delivered. Why it follows: section 1 defines "delivered" as observed by the server's loop and states the fallback rules over what the loop observes, B2(c) ties a decision to the pass that received its deciding byte, section 2.1 presupposes `SO_RCVLOWAT` on Linux (the IOCP sentence) and sets no value for it, and the detection table's "Decides at" column gives the lengths at which a matcher says yes (TLS 6, SSH 4, HTTP/1.1 at most 10), so a mark at the smallest of them delays no classification. Consequence: in peek mode a connection that sends "P" and later an impossible byte that leaves the queue below the mark is closed at T_dec as "undecided" (1 d), where replay rejects it when the byte arrives (1 e); no hard case does this (HC16 and HC23 are single writes).
2. T_dec does not close a silent connection of a fallback listener; T_fb decides it. Why it follows: 1(f) closes a silent connection at T_dec only "on a listener without a fallback", 1(d) needs "at least one byte", and 1(a) says such a connection "is never closed or routed elsewhere instead", so no rule of section 1 closes it at T_dec. With the frozen T_fb = T_dec both fall due together and T_fb is handled first; the reading matters only when T_dec < T_fb.
3. HC2's "every k from 1 to the matcher's `need` minus 1" runs k to the largest need minus 1 for the matchers whose need is a range (HTTP/1.1 at most 10, MQTT 9 to 12), and HC3 drips the first largest-need bytes. Why it follows: the detection table gives those needs as ranges, and "every k" cannot stop at the smallest need without leaving the splits inside a longer signature untested; splits after a sample's own decision point are included, and their outcome is "as HC1".
4. HC4's "slow drip" sends the first d - 1 bytes of the signature, d its decision length, one per write, spread over 2 × T_dec, so the drip is still running at T_dec.
5. HC7's "written at T_fb + G" and "at T_fb - G" are on the client's clock, which the server shares: the late write at the client's connect return + T_fb + G, the twin at the client's time just before connect + T_fb - G, so each lies at least G from the server's deadline whatever the accept delay.
6. HC10's "split after every byte k inside it, then HTTP/1.1" is two writes: the header's first k bytes, then the rest of the header with the request.
7. TLS "a record length of at most 2^14" is read literally: a length of 0 is accepted by the matcher.
8. MQTT "a Remaining Length of 1 to 4 bytes" checks only the field's length, not its value or a minimal encoding. HC24's 4-byte case cannot be a well-formed CONNECT, since no payload reaches 2,097,152 bytes, so it sends that Remaining Length with filler after a 65,535-byte client identifier; its frozen outcome, MQTT, is the classification.
9. HTTP/1.1's "exactly one SP": the matcher decides at the method and its SP, within the table's 10 bytes; a second SP is closed without a response by the handler, in both modes, as section 2.1 says of a request line that breaks the detector's grammar.
10. PROXY v2's "first 13 matching": the 13th byte matches when its version is 2; a command other than LOCAL or PROXY is malformed and closes the connection.
11. 1(h) on a PROXY listener: a half-close during an incomplete header is "undecided" if it delivered a byte and "silent" if not; after a complete header with no application byte it is "silent". Detection, T_fb and T_dec start after the header (section 1), B_dec counts "after any PROXY header", and 1(a) speaks of an "application byte", so (d), (f) and (h) describe the detection that begins after the header.
12. Not a reading of a frozen rule: the M1 brief listed IOCP among the items pending M2, while engineering's milestone plan puts Windows in M6; the suite marks the IOCP case entries "pending M6", only on W. It is listed so this entry holds all 13 items, and it changes nothing above.
13. Appendix A's outcomes that name only a class ("TLS" for HC13 and HC19, "SSH" for HC18, "MQTT" for HC24) are met by the classification; for HC1 to HC3, whose outcome includes "the transcript equals the dedicated port's", the transcript is also compared.

### 2026-10-02: Readings fixed during engineering (M2a), before the code freeze

M2a (`design/status.md`, "Readings of the frozen text in M2a") read the frozen text in six places, and the coordinator accepted three decisions on 2026-10-02. Each reading is a reading of the text above, not a change of a rule; nothing above this log is edited. No hard case of Appendix A changes outcome by them.

Readings:

1. For TLS (HC1 to HC3, and HC20 in-process), "the transcript equals the dedicated port's" is compared after decryption: both handshakes complete with TLS 1.3, TLS_AES_128_GCM_SHA256, X25519, ecdsa_secp256r1_sha256, a verified certificate and no session ticket; both negotiate the same ALPN; both carry the same decrypted bytes; and close_notify arrives in both or in neither. Why it follows: Appendix A says "the transcript", while "the byte transcript" is section 1(c)'s, for the fallback only; and a handshake's wire bytes differ on every connection in either mode (the server's random, key share and signature), so a byte comparison could never hold, and what two exchanges can share is what they negotiated and carried.
2. HC13 and HC19, whose outcome is "TLS", are met by the classification, with the server's first record checked to be a ServerHello; the server's flight is not compared with the dedicated port's. Why it follows: Appendix A names only the class for these two cases (as item 13 of the M1 entry reads HC13, HC18, HC19 and HC24), and the flight is drawn afresh on every connection, as in 1.
3. The recorded ClientHello (section 2.1; WL7) serves where a case needs a ClientHello's bytes and no handshake (HC4's slow drip, HC13, HC19); where the outcome needs a completed handshake (HC1 to HC3, and HC20 in-process), a live OpenSSL client with the settings of section 2.1 sends its own. Why it follows: section 2.1 asks for "the same settings in the server, the backend and the generator", and the frozen text names the recording only for the stub exchange of WL1 and for WL7; the recording cannot finish a handshake, because the private key of its key share is not kept.
4. HC7's "its request gets 500 from the SMTP handler": each CRLF-terminated line of the HTTP/1.1 request gets one 500, the empty line included, so four 500s. Why it follows: section 2.1's SMTP handler answers "500 to anything else", and SMTP replies once per command line (RFC 5321 s4.2).
5. The h2c exchange of the hard cases is written without reading: the preface, SETTINGS, HEADERS with END_STREAM and GOAWAY in the case's writes, then the client shuts down writing. Why it follows: section 2.4 makes `opcase` run each case "as a script of writes and gaps", which does not react to the server; WL1's order (read to END_STREAM, then GOAWAY) is `opgen`'s.
6. In-process, SNI selects nothing, since there is one certificate (section 2.1); ALPN chooses the handler: the client's first of `http/1.1` and `h2`; no ALPN gives HTTP/1.1; ALPN with neither gets the fatal alert no_application_protocol (RFC 7301 s3.2). Why it follows: section 2.1 says "TLS is terminated in the server" and "TLS through OpenSSL, then HTTP/1.1 or h2", and gives routing by SNI and ALPN to relay dispatch only ("pass-through").

Coordinator decisions, accepted on 2026-10-02:

7. UBSan's function check is left out of OpenSSL alone, in the ASan+UBSan build (`bench/third_party/openssl-ubsan.ignorelist`), and `bench/coverage.json` declares the gap. Why: OpenSSL calls typed functions through generic function-pointer types by design, in macros of its public headers (`DEFINE_STACK_OF`, `IMPLEMENT_PEM_read`, `DEFINE_LHASH_OF`), so clang 22's `-fsanitize=function` reports sites that no list of sites can close (M2a met two, one per run). Every other UBSan check stays on in OpenSSL, and oneport's own code and nghttp2 keep the function check. This adds an item to the declared gaps of section 11, whose list feeds `bench/coverage.json`; no rule changes.
8. The TLS hard cases use a live OpenSSL client with the settings of section 2.1, and its ClientHello is checked against the recording: the same length, and the same bytes except the 96 that each connection draws afresh (the random, the session id and the X25519 key share; test `handlers.clienthello_live`). Why: the outcomes of HC1 to HC3 and of HC20 in-process need a completed handshake, which the recording cannot finish (reading 3); the check keeps the live client's first flight equal to the recording in everything that the settings fix.
9. TLS transcripts are compared after decryption, as reading 1 states.

### 2026-10-02: Readings fixed during engineering (M2b), before the code freeze

M2b (`design/status.md`, "Readings of the frozen text in M2b" and "I29: bytes copied in user space, the rule") read the frozen text in these seven places while it built relay dispatch, pass-through, stub mode and the io_uring backend. Each line is a reading of the text above, not a change of a rule; nothing above this log is edited. No hard case of Appendix A changes outcome by them.

1. Relay "relays both ways" (section 2.1) passes each side's end on as a half-close, and the other direction goes on; the connection closes when both directions have ended, or at an error, and a reset on one side closes the other by reset. Why it follows: section 2.1 sets no end before both ways are done, and HC1's h2c client shuts down writing before it reads its response (WL1: "Closes first: client"), so ending both directions at the first end would lose the response that "the transcript equals the dedicated port's" requires.
2. PROXY in relay: the front consumes the header, as section 1 has every PROXY listener do ("parsed before the table"), and writes only the bytes after it, so the relay's backend runs without PROXY and "the source address the server records" (HC9) is the front's. Why it follows: section 2.1 has the front write "any replayed bytes", and the header is not application data; no rule asks the front to pass a header on.
3. B_CH bounds the reassembled ClientHello message in pass-through, and the records that carry it are held as received: in replay at most the message and 5 bytes per record, in peek nothing in user space (B2 d). A ClientHello longer than B_CH, like one with no route, closes the connection; it is counted apart, since its detection outcome is already "classified" (TLS decides at 6 bytes). Why it follows: section 1 defines B_CH as "bytes for a ClientHello reassembled in pass-through", and section 2.1 bounds "the partial ClientHello, at most B_CH", both of the ClientHello, not of its record headers; a bound on record bytes would refuse a ClientHello of 16380 bytes in one record, which the text accepts.
4. No timer bounds pass-through's wait for the whole ClientHello. Why it follows: 1(d) closes at T_dec only "a connection with at least one byte that no matcher has decided", and the TLS matcher decides at byte 6, in relay as in-process, where the TLS handler too waits for the rest of the ClientHello with no timer.
5. Stub mode's ports for h2c, MQTT, SSH and SMTP run the handlers of section 2.1. Why it follows: stub mode gives each connection "the least work that completes an exchange" and spells it out only for HTTP/1.1 and TLS; for the other classes the minimal handlers of section 2.1 are that work.
6. Appendix A's "with in-process and relay dispatch where it applies" applies every case in relay too, with the relay's backend a server in dedicated mode (the M2 backend of 5.3, which terminates TLS) and PROXY off (reading 2). HC20's relay outcome "pass-through: routed by its SNI" is checked as the route by SNI to the backend's TLS port, from a ClientHello reassembled from both records, with the transcript through the terminating backend equal to the dedicated port's. Why it follows: every other case's outcome is the front's detection, which relay dispatch shares with in-process dispatch, and only HC20 names a pass-through outcome.
7. Section 2.1's "payload bytes ... copied in user space" counts each move of a payload byte by the server's own code from one user-space place to another (a receive buffer's compaction; output the socket did not take, copied into the connection's queue; output appended behind a queue that holds bytes; a pass-through ClientHello moved from the receive buffer into storage of its own), and "across the boundary" counts what a system call moves, by direction; producing a byte (a handler's reply, OpenSSL's records or plaintext, nghttp2's frames) is not a copy. So rule E's user-space relay copy counts each relayed byte twice across the boundary and never as copied in user space, and its splice copy counts neither (it is counted as spliced), apart from the bytes replay read before the dispatch. Why it follows: section 2.1 names the two counters side by side, which only holds if one counts system calls' moves and the other the server's own, and the rule is the same in every mode because every mode runs the code that counts.

Note, not a reading: the test that proposal RK4 asks for before io_uring's peek is used passed on L's kernel (`server.kernel_rcvlowat_uring`, test commit 107237b): a poll armed again after an undecided peek does not complete until `SO_RCVLOWAT` is reached, and a half-close completes it above the mark. So io_uring keeps the peek path of section 2.1 with the low-water mark, and IOCP's switch to replay is not taken on io_uring.

### 2026-10-03: Readings fixed during engineering (M3), before the code freeze

M3 (`design/status.md`, "M3, step 0" and "Readings of the frozen text in M3") read the frozen text in these places. Each line is a reading of the text above, not a change of a rule; nothing above this log is edited. No hard case of Appendix A changes outcome by them.

1. T_dec bounds pass-through's wait for the whole ClientHello. This supersedes item 4 of the M2b entry. In relay dispatch a TLS connection is still classified at byte 6 (B2(c) unchanged); its route needs the ClientHello's SNI and ALPN (section 2.1, "Dispatch"), so the decision that T_dec, the decision deadline, bounds is complete only when the route is chosen or refused. T_dec stays armed from its start (accept, or the PROXY header's end) until then; a ClientHello still incomplete when T_dec expires is closed, as a timed event under B2(a) and (b), and counted apart (route timed out), since its detection outcome is already "classified". Why it follows: section 1's budgets apply to "a connection that exceeds a budget while undecided", and B_CH, "bytes for a ClientHello reassembled in pass-through", can be exceeded only during this wait, so the text holds the wait to be part of the undecided phase; section 2.1 counts "in pass-through, the partial ClientHello" among the memory of a pending connection; section 1 sets every detection timer to 60 s in B3 "so that no pending connection expires before the last sample", where the server runs in relay mode against partial ClientHellos; and Appendix B matches to the server's timers the proxies' timers that bound this same wait (nginx's `preread_timeout`, HAProxy's `inspect-delay`, Envoy's `listener_filters_timeout`). M2b's reading rested on 1(d) alone, which speaks of the matcher's decision, and did not weigh these passages. Consequences: B3's windows run the server with T_dec at 60 s, as section 1 asks of every system with a detection timer; in-process dispatch is unchanged, since its decision is complete at byte 6 and the TLS handler, not detection, reads the rest; item 3 of the M2b entry stands (a ClientHello longer than B_CH, or with no route, is closed and counted apart, the budget's "rejected" read as that close). The test `relay.pass_through_tdec` checks the reading on both backends in both detection modes; it is not a case of Appendix A.
2. Section 2.1's count of `setsockopt` operations counts every `setsockopt` call on a connection's socket: each `SO_RCVLOWAT` set and reset, the two `TCP_NODELAY` of a relayed connection, and the `SO_LINGER` of each side the relay closes by reset. Why it follows: section 2.1 lists the operations by kind, and section 10 checks the system-call counters against `perf trace -s`, which counts every call; the proposal's parenthesis (I29, "each `SO_RCVLOWAT` set and reset") names the calls of the in-process paths, which were the only ones when it was written. The listeners' options, set once at start, belong to no connection and are not counted.
3. "Time to first response byte" (WL1, WL2) ends at the first byte the server sends on the connection, as the generator receives it: for TLS the first byte of its handshake flight, for h2c its first frame, for SSH in dedicated mode its identification line, which it sends at accept (section 10 already notes SSH's order). Why it follows: WL1 defines TTFB from just before `connect` "to the first byte of the response", and an exchange's response is everything the server sends in it (WL1's table lists each exchange as the client's part and what it reads back); no protocol-level marker is named, and both arms of a cell send the same bytes first.
4. In open loop, TTFB runs from the exchange's due time (WL2: "Latency is measured from the due time"), so WL2's metric is the median of first-byte time minus due time; the time from just before `connect` is recorded beside it, and the two differ by the generator's issue lag, also recorded. Why it follows: WL2 names both the due time and the TTFB of WL1; measuring from the due time is what keeps a generator stall from hiding (proposal WL2, "as t1gen does").
5. Keep-alive (WL3) counts requests only: a connection's setup is not one (the TCP connect, TLS's handshake, MQTT's CONNECT and CONNACK); h2's preface and SETTINGS ride in the first request's write, and that request is counted. Why it follows: WL3 has the C connections "established before the window" and names the request per protocol ("MQTT PINGREQ after one CONNECT"; "HTTP/1.1 GET over one TLS connection").
6. WL5's counters "per connection" are I29's counters of a window's server process, which it reports once at its exit, over its whole life (the probe, the warm-up, the measured window and the drain), divided by the connections it accepted; for keep-alive they are also given per request, over every request the generator completed and the probe's. Why it follows: section 2.1 has the counters per worker, and the proposal (I29) reports them per window; every connection of a window's process runs the same exchange, so the lifetime quotient is the window's.
7. WL4's CPU time is the server process's `utime` plus `stime` from `/proc/<pid>/stat`, read when the generator marks the start and the end of the measured window, divided by the exchanges completed in it (in open loop, those due in it that completed). Why it follows: WL4 names the counters and "over the window per exchange".
8. Section 7's generator rule ("the generator's CPUs were more than 90% busy in a saturation cell", lab/t1/t1.py) takes the larger of the generator's own CPU time over (window x its CPUs) and the busy share of its CPUs in `/proc/stat` (softirq included), and applies to the closed-loop windows (WL1, WL3); the open loop has its own rule (99% completed). The MHz rule compares the mean `cpu MHz` of the server's and the generator's CPUs at the window's two markers with `pin.sh`'s mean at the session's start. Why it follows: section 7 takes these rules from `lab/t1/t1.py` as P2's H6 used them, and that is how `t1.py` computes them (`gen_cpu_pct_rule`, `mhz_drift`, a saturation cell being a closed-loop one).

9. `K_SRC` = 16 (section 9.1, set in engineering, step 2). The rule, "so that no connect fails in the development runs", is met at every block size tried: in M3's development windows on L (all with the window runner's wait for an empty connection-tracking table, below) no connect failed at K = 1, 4, 16 or 64, in the cells whose clients close first and so keep a TIME-WAIT socket per connection (MQTT and h2c churn on epoll, the fastest such cells, 32,761 and 28,940 connections per second), nor at K = 16 in any other window of M3 (among them the 396 A/A windows of jobs aa1 to aa5, churn, keep-alive and open loop on both backends, the fastest HTTP/1.1 churn on io_uring at 53,372 connections per second). The rule alone would allow K = 1, but at K = 1 the generator, not the server, set the rate of those cells: the kernel's search for a free port among one address's TIME-WAIT sockets held MQTT churn at 16,301 per second with the server 57% busy and each generator thread about 70% busy, below section 7's 90% generator rule. From K = 4 the server was 100% busy (32,507 per second for MQTT, 28,846 for h2c). The value is a design choice, four times that smallest block (design/status.md, M3). The two smoke windows run before the table wait existed had connects that timed out because the full connection-tracking table dropped their SYNs; no block size changes that, and none happened once the runner waited. A connect failure in any later development run before the code freeze requires a new entry here.

Note, not a reading: L tracks every connection, loopback included (Docker's NAT rules load connection tracking), in a table of 262,144 entries (`nf_conntrack_max`) that keeps each closed connection 120 s (`nf_conntrack_tcp_timeout_time_wait`); one HTTP/1.1 churn window opens about 270,000 connections, and a second window started at once has its SYNs dropped ("table full, dropping packet"). The window runner therefore waits before each window until the table holds at most 2,000 entries, at most 180 s (design choices of M3). Whether the host changes instead is Alex's decision (`design/status.md`, M3).

### 2026-10-03: Readings fixed during engineering (M6a), before the code freeze

M6a (`design/status.md`, "M6a (Windows), 2026-10-03", "Readings for the revision log") read the frozen text in seven places while it built the IOCP backend. Six are logged here. Each line is a reading of the text above, not a change of a rule; nothing above this log is edited. No hard case of Appendix A changes outcome by them. The seventh is not logged, since it would exempt a form from a rule rather than read one: in rule E's posted receive form a pending connection holds the handler's buffer from accept, and M6a's reading lets the suite's B2(d) audit pass such a connection while it is silent, against B2(d)'s "one that has received no byte holds no data buffer" and section 2.1's "no data buffer while no byte has arrived, on every backend". It is left open for a decision (`design/status.md`, M6a, "Open for the coordinator").

1. Appendix A's "with in-process and relay dispatch where it applies" runs each case on IOCP with in-process dispatch only, in both detection modes: 50 entries. Why it follows: section 2.1 says "Relay (Linux only)", so relay dispatch does not apply on IOCP.
2. Section 2.1's "an undecided peek switches the connection to replay" switches at the first undecided peek: the queued bytes are read at once into the handler's buffer and matching continues there, and from then on the connection is in replay, so its B2(d) bound is replay's; the peek of a PROXY header switches by the same rule. Why it follows: section 2.1 sets no condition on the switch beyond an undecided peek, and gives replay's bound as "the handler's buffer from the first byte"; without `SO_RCVLOWAT` IOCP has no way to wait in the kernel for more bytes, which is why the switch exists.
3. 1(h) on IOCP: the pass that observes a half-close is the one in which a peek returns 0 after the zero-byte `WSARecv` completes, or, after a switch to replay, the one whose read returns 0. Why it follows: section 1 defines "delivered" as observed by the server's loop and B2(e) closes in "the pass that observes it"; IOCP reports no half-close event of its own, so the completion followed by a peek or read of 0 bytes is the observation.
4. Section 2.1's count of "`GetQueuedCompletionStatus` calls" counts the server's `GetQueuedCompletionStatusEx` calls, each of which dequeues up to 64 completions: every wait, every non-waiting reap of 1(b) and every drain at stop is one. Why it follows: section 2.1 counts the loop's calls by kind, as it counts `io_uring_enter` calls; the Ex form is the batch form of the same call, as one `epoll_wait` returns up to 64 events.
5. 1(b) on IOCP: "the zero-byte WSARecv on IOCP" takes the one-byte `MSG_PEEK`, and so does a peek-mode connection in either receive form, since its detection waits with the zero-byte `WSARecv`; "IOCP's posted-buffer form" takes the non-waiting reap of the port, every reaped completion handled, and the byte wins if the connection's receive was among them with bytes. Why it follows: 1(b) chooses the check by whether a receive was posted with a buffer ("where no receive was posted with a buffer ... where one was"), and a peek-mode connection has none posted during detection.
6. Section 10's "AcceptEx with a receive buffer", "on a listener without a fallback", applies to one-port listeners without a fallback and is refused with one; dedicated and stub listeners keep AcceptEx without a buffer. The bytes it receives are the connection's first read, in the handler's buffer, and detection runs on them as in replay in either detection mode, which is not counted as a peek-to-replay switch; it receives at most 4,032 bytes, the buffer's last 64 holding the two addresses. Why it follows: section 10 names the form as a secondary option against the default form, and section 8 lets only rule E's receive form, not the AcceptEx form, govern dedicated mode's reads on W; an AcceptEx with a buffer completes only when bytes arrive, so a port whose server speaks first (the dedicated SSH and SMTP ports) would never complete it; the bytes are out of the socket when the connection is handed over, so there is nothing to peek and no peek was undecided; and the connection has then received a byte, so B2(d)'s "no byte, no buffer" is not touched.

Note, not a reading: proposal I11 says `setsockopt(SO_RCVLOWAT)` fails with WSAEINVAL on Windows; on W it fails with WSAENOPROTOOPT (10042, test `iocp.pin_rcvlowat`). The design rests only on the refusal, which holds. `N_ACCEPTEX` = 64, a design choice of M6a, is recorded at the code freeze (section 9.1).

### 2026-10-03: Host change before the code freeze

L moved on 2026-10-03 from kernel 7.2.3-arch1-2 to the installed 7.2.6-arch2-1 by kexec, Alex's decision, so that the kernel module NOTRACK needs (`xt_CT`, the CT target of iptables-nft) can load: the package upgrade of 2026-09-16 had removed the running 7.2.3 kernel's module tree (`design/status.md`, "L's connection tracking: NOTRACK for loopback"). It was a kexec, not a reboot through GRUB; the bootloader was untouched (Alex's report). What L shows of it: the journal lists the earlier boot from 2026-09-12 13:32:09 to 2026-10-03 11:30:36 and the current one from 11:30:41 (`journalctl --list-boots`); the kernel names itself 7.2.6-arch2-1, built 2026-09-14; the kernel command line is unchanged and holds no `slab_nomerge`. For L this entry supersedes three statements above: "Words" ("L ... frozen at kernel 7.2.3"), WL7's "L is not rebooted and its boot parameters do not change" (the boot parameters did not change), and, in `design/proposal.md`, LB1's "kernel 7.2.3 ... No update and no reboot".

1. Read after the switch, as root and read-only (2026-10-03 12:11): `/sys/kernel/slab/skbuff_fclone_cache` still links to `:0000512`, whose co-tenants are still `pool_workqueue` and `sgpool-16` (its `aliases` is 2), and `/proc/slabinfo` still lists that cache only as `pool_workqueue`; "skbuff_head_cache" and "skbuff_small_head" are directories of their own and are listed under their own names; the kernel is built with `CONFIG_SLUB_DEBUG=y` and `CONFIG_SLAB_MERGE_DEFAULT=y`, without `CONFIG_SLUB_DEBUG_ON`; `kernel.io_uring_disabled` is 0; the page size is 4096 bytes. So WL7's reading of the merged skb cache holds as frozen; section 9.1 reads it again at the code freeze.
2. Data by kernel. All development data before 2026-10-03 11:30 ran on 7.2.3: M0 to M3, the merge checks of bbd13f7, and NOTRACK's tests t2 to t5. All records, the pilot and every confirmatory run will run on 7.2.6. Every window row carries `pin.sh`'s fingerprint, which names the kernel, so rows separate by kernel.
3. The cited source lines. The text above cites Linux source lines at the v7.2 tag (WL7, and `TCP_TIMEWAIT_LEN` in section 7). Each was checked at the v7.2.6 tag, with kernel.org's patch from v7.2 to v7.2.6 (`patch-7.2.6.xz`, sha256 2aef3c30a571ed806c69e90428b229409a43c235aa2540a24593b7e7a8b126cf, equal to its line in kernel.org's `sha256sums.asc`, whose signature verified good with the kernel.org checksum autosigner key, fingerprint B886 8C80 BA62 A1FF FAF5 FDA9 632D 3A06 589D A6B1) and, for the six files the patch touches, by comparing the cited lines of each file fetched at both tags from the stable tree on git.kernel.org. No cited line differs in content. By file:
   - not touched by the patch, every cited line the same at the same number: `include/net/sock.h`, `include/linux/slab.h`, `net/core/sock.c`, `mm/slab_common.c`, `lib/sg_pool.c`;
   - touched elsewhere, every cited line the same at the same number: `include/linux/skbuff.h` (273 to 275, 1395 to 1401), `net/ipv4/tcp.c` (926 to 935, 1256), `include/net/tcp.h` (140);
   - touched, every cited line the same, some at new numbers: `net/core/skbuff.c`, whose lines 106 to 116, 606 to 646, 684 to 685 and 1139 to 1167 keep their numbers while from line 5176 on each lies 2 lower (5176 at 5178, 5196 to 5225 at 5198 to 5227, 5208 to 5212 at 5210 to 5214); `mm/slub.c`, 6 lower (9156 to 9160 at 9162 to 9166, 9641 to 9722 at 9647 to 9728); `kernel/workqueue.c`, whose lines 5313, 5424, 5434, 5578, 5628 and 5897 keep their numbers while line 7995 is at 8025.
   The paper cites the lines at v7.2, as the text does, and names the kernel the runs used. Arch's own patches of 7.2.6-arch2-1 on top of the tag were not compared.
4. Found after the switch, open for the coordinator and Alex (nothing was changed): between 7.2.3 and 7.2.6 the amd-pstate driver changed the floor it sets for the performance policy from the nominal performance to the BIOS's minimum where the BIOS gives one (`drivers/cpufreq/amd-pstate.c` at both tags). On L, in `pin.sh`'s state (boost off, the performance governor), `scaling_min_freq` now reads 1,102,866 kHz, the value of `amd_pstate_lowest_nonlinear_freq`, and an idle core reports that frequency, while a loaded core runs at about 3,169 MHz, as in M3. `pin.sh`'s `mean_mhz`, the session's value of section 7's MHz rule (M3 entry, item 8), is read with the host idle, so it now reads 2,006 to 2,522 MHz, and every window drifts 32% to 58% from it: every development window on 7.2.6 so far is invalid by that rule alone, while the loaded frequency moved at most 0.016% within any session (`design/status.md`, M4a). On 7.2.3 the floor was not read; in M3's 396 A/A windows the loaded CPUs read 3,165.9 to 3,184.3 MHz and `pin.sh`'s idle reading 3,172 to 3,186 MHz, so idle cores then reported about the loaded frequency.

### 2026-10-03: The coordinator's decision on M6a's reading 7, before the code freeze

M6a's reading 7 (the M6a entry above, which left it open) is decided by the coordinator; it is not logged as a reading.

1. The decision. IOCP's posted receive form posts the handler's buffer with a `WSARecv` at accept, so a silent pending connection holds a data buffer. That breaks B2(d) ("one that has received no byte holds no data buffer") and section 2.1 ("no data buffer while no byte has arrived, on every backend"). So rule E may choose only among IOCP receive forms that satisfy B2(d), and the posted form is excluded from rule E.
2. What follows from it. Rule E's only candidate on IOCP is the zero-byte `WSARecv` form, the proposed default, so rule E has nothing to choose on IOCP: section 8 step 4's "rule E's IOCP receive form" runs no development sessions, and section 9.2's "The IOCP receive form, named again" names the zero-byte form. Section 10 lists the posted form as a secondary variant ("the receive form rule E did not choose (the zero-byte `WSARecv` or the posted buffer), after the same AcceptEx"): that cell is the posted form, secondary and descriptive only, and the paper states its B2(d) violation beside it. Section 8's "Both options of each are built into the frozen binary as flag values" stands: `--iocp-receive posted` stays a flag value, for that cell. M6a's contingency (the IOCP case entries under the posted form, had rule E chosen it) no longer arises: the case entries run the zero-byte form, as they do.
3. The code and tests (`design/status.md`, M4a, step 0). The suite's B2(d) audit (`Worker::audit_pending`) no longer exempts a buffer a posted receive writes into unless the connection has received a byte (io_uring's receive into the room of a buffer the connection holds, which it takes only after bytes arrived); the IOCP worker audits a posted-form connection in the state it waits in. So a silent connection in the posted form is reported as holding a data buffer while no byte had arrived, the violation in the code's own terms. The test `iocp.silent_buffer` closes a silent connection at T_dec in each form and detection mode: the zero-byte form holds no data buffer in replay or peek, and the posted form in replay is reported holding the handler's buffer (in peek no receive is posted with a buffer during detection, in either form). The comments that named the posted form a rule E option now name it section 10's secondary variant.
