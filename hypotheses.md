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
4. Found after the switch, open for the coordinator and Alex (nothing was changed): between 7.2.3 and 7.2.6 the amd-pstate driver changed the floor it sets for the performance policy from the nominal performance to the BIOS's minimum where the BIOS gives one (`drivers/cpufreq/amd-pstate.c` at both tags). On L, in `pin.sh`'s state (boost off, the performance governor), `scaling_min_freq` now reads 1,102,866 kHz, the value of `amd_pstate_lowest_nonlinear_freq`, and an idle core reports that frequency, while a loaded core runs at about 3,169 MHz, as in M3. `pin.sh`'s `mean_mhz`, the session's value of section 7's MHz rule (M3 entry, item 8), is read with the host idle, so it now reads 2,006 to 2,522 MHz, and every window drifts 2.9% to 58% from it (the least in windows whose CPUs were partly idle): every development window on 7.2.6 so far fails that rule, while within any A/A session of M4a's re-check, whose windows load every CPU they read, the windows' MHz moved at most 0.016% (`design/status.md`, M4a). On 7.2.3 the floor was not read; in M3's 396 A/A windows the loaded CPUs read 3,165.9 to 3,184.3 MHz and `pin.sh`'s idle reading 3,172 to 3,186 MHz, so idle cores then reported about the loaded frequency.

### 2026-10-03: The coordinator's decision on M6a's reading 7, before the code freeze

M6a's reading 7 (the M6a entry above, which left it open) is decided by the coordinator; it is not logged as a reading.

1. The decision. IOCP's posted receive form posts the handler's buffer with a `WSARecv` at accept, so a silent pending connection holds a data buffer. That breaks B2(d) ("one that has received no byte holds no data buffer") and section 2.1 ("no data buffer while no byte has arrived, on every backend"). So rule E may choose only among IOCP receive forms that satisfy B2(d), and the posted form is excluded from rule E.
2. What follows from it. Rule E's only candidate on IOCP is the zero-byte `WSARecv` form, the proposed default, so rule E has nothing to choose on IOCP: section 8 step 4's "rule E's IOCP receive form" runs no development sessions, and section 9.2's "The IOCP receive form, named again" names the zero-byte form. Section 10 lists the posted form as a secondary variant ("the receive form rule E did not choose (the zero-byte `WSARecv` or the posted buffer), after the same AcceptEx"): that cell is the posted form, secondary and descriptive only, and the paper states its B2(d) violation beside it. Section 8's "Both options of each are built into the frozen binary as flag values" stands: `--iocp-receive posted` stays a flag value, for that cell. M6a's contingency (the IOCP case entries under the posted form, had rule E chosen it) no longer arises: the case entries run the zero-byte form, as they do.
3. The code and tests (`design/status.md`, M4a, step 0). The suite's B2(d) audit (`Worker::audit_pending`) no longer exempts a buffer a posted receive writes into unless the connection has received a byte (io_uring's receive into the room of a buffer the connection holds, which it takes only after bytes arrived); the IOCP worker audits a posted-form connection in the state it waits in. So a silent connection in the posted form is reported as holding a data buffer while no byte had arrived, the violation in the code's own terms. The test `iocp.silent_buffer` closes a silent connection at T_dec in each form and detection mode: the zero-byte form holds no data buffer in replay or peek, and the posted form in replay is reported holding the handler's buffer (in peek no receive is posted with a buffer during detection, in either form). The comments that named the posted form a rule E option now name it section 10's secondary variant.

### 2026-10-03: Host clock floor before the code freeze

The coordinator decided on 2026-10-03 (option (a) of `design/status.md`, M4a, step 0, 1) that every lab job on L holds each CPU's `scaling_min_freq` at its `scaling_max_freq`, beside what `lab/bin/pin.sh` sets (boost off, the performance governor, AC power), and sets each back at the job's end. This entry records the cause as found in M4b-1, the change and its check (`design/status.md`, M4b-1, step 0). Section 7's MHz rule is unchanged: the session's value is still `pin.sh`'s mean at the session's start (M3 entry, item 8).

1. The cause. It supersedes the mechanism in item 4 of the entry "Host change before the code freeze"; that item's readings stand. On L under 7.2.6 the CPPC request register of every CPU (MSR 0xC00102B3, read only, as root) holds MinPerf = MaxPerf = 119, the nominal performance (3,201 MHz; `acpi_cppc/nominal_perf` 119), and EPP 0, before any change and throughout. Under the performance policy `amd_pstate_update_min_max_limit` (drivers/cpufreq/amd-pstate.c at v7.2.6, line 693) takes the BIOS minimum if there is one and the nominal performance if not, and ignores `scaling_min_freq`. A BIOS minimum would have to be 119, and then `amd_pstate_verify` (line 662) would set the policy minimum to 3,201,000 kHz. It reads 1,102,866 kHz, `amd_pstate_lowest_nonlinear_freq`, which that function sets only when there is no BIOS minimum. So on this boot there is none, and the hardware floor is the nominal performance, as 7.2.3's code gives. The hardware floor did not change; the policy minimum did. An idle CPU's `cpu MHz` is not a clock reading: /proc/cpuinfo (arch/x86/kernel/cpu/proc.c line 89) takes the APERF/MPERF frequency only from a sample at most 20 ms old (aperfmperf.c, `MAX_SAMPLE_AGE` and `arch_freq_get_on_cpu`, lines 504 to 535), else `cpufreq_quick_get`, which returns the policy's current value for a driver without a `get` callback, and the EPP driver keeps that value at the policy minimum (amd-pstate.c line 2049). So a CPU idle for more than 20 ms reports 1,102.9 MHz. The active clock, measured under the lab lock as cycles over task clock of a process on CPU 14: 3,169.0 MHz busy throughout, 3,091.4 MHz in 0.3 ms bursts after 5 ms sleeps, 3,106.3 MHz after 50 ms sleeps; with the floor set, 3,169.0, 3,091.5 and 3,107.0 MHz. So the floor changes what an idle CPU reports and not the clock, and M4a's concern that a core idle between exchanges now ramps up from 1.1 GHz does not hold on L. Why idle CPUs reported about the loaded value on 7.2.3 (M3: `pin.sh` read 3,172 to 3,186 MHz) is not established from L's present state; the same code path then implies a policy minimum near 3,201,000 kHz, that is a BIOS minimum at 7.2.3's cold boot that 7.2.6 did not find after the kexec. The kernel's sources were fetched at the v7.2.6 tag from the stable tree (amd-pstate.c sha256 985a694cd70f3864486e873fa3a09a1811a9032bc1c39936f827f026765c0e02).
2. The change. `bench/run/clockfloor.sh` (one-port e49cb63), a wrapper of this paper's: `lab_job.sh` runs it inside the lab lock and outside `notrack.sh`; it writes each CPU's `scaling_max_freq` into its `scaling_min_freq`, runs the job, and writes the values it read back when the job ends, also on INT, TERM and HUP; it refuses a job whose floor cannot be set (exit 95). Its record (`<job>.clock.json`) holds every CPU's floor, ceiling, governor, EPP and CPPC request before, while and after, and each session's fingerprint holds the floors before the job and now (`clock_floor`). `lab/bin/pin.sh` is not changed, so P1 and P2 are not affected. The kernel's other controls were not needed: under the performance policy EPP accepts only 0, which it holds (amd-pstate.c, `store_energy_performance_preference`), and `amd_pstate_floor_freq`, which Documentation/admin-guide/pm/amd-pstate.rst at v7.2.6 shows only on platforms with CPPC performance priority, does not exist on L. The driver's mode is not changed.
3. The check. With the host idle, `pin.sh` read 2,263 MHz before the floor, 3,181 MHz with it and 2,135 MHz after it was set back; a job's own session read 3,180 MHz. A short A/A set, dedicated against dedicated (job aa-floor1, e49cb63, seed 821, two sessions each of HTTP/1.1 churn on epoll and on io_uring and keep-alive TLS on io_uring, NOTRACK on, lab lock, development data, journaled): all 24 windows valid, their MHz 0.32% to 0.53% from the session's value (sessions 3,179 to 3,185 MHz, windows 3,168.2 to 3,168.8 MHz), the throughput per window M3's (44,655 to 44,980 connections per second, 53,000 to 53,245, and 106,404 to 108,453 requests per second). Every job's record shows each floor back at 1,102,866 kHz, also for a job stopped by SIGTERM to its process group (exit 143). The CPPC request read 119, 119, EPP 0 before, while and after.

### 2026-10-03: Readings fixed during engineering (M4a), before the code freeze

M4a (`design/status.md`, "Readings of the frozen text in M4a") built the five proxies' M3 and B3 configurations and the hand-off runner, and read the frozen text in these places; the coordinator accepted them on 2026-10-03. Each line is a reading of the text above, not a change of a rule; nothing above this log is edited. No hard case of Appendix A changes outcome by them.

1. HAProxy accepts plaintext HTTP/1.1 at once (`tcp-request content accept if HTTP`, Appendix B's `req.proto_http`) in M3 and B3. Why it follows: Appendix B names `req.proto_http` among HAProxy's rules, and without it a request HAProxy recognises at its first bytes would wait the whole inspect delay for `default_backend`, while the server classifies HTTP/1.1 at its first bytes.
2. HAProxy's client, server and connect timeouts stay unset, HAProxy's default (infinite), which it accepts with a startup warning. Why it follows: Appendix B sets none, HAProxy documents no value for this use, and its client timeout must cover the inspection delay (configuration.txt v3.4.6 line 14540), which an infinite one does.
3. Section 5.3's "Connection logging is off" is, for sslh-ev, `verbose-connections: 0` (Appendix B) with `numeric: true` and `log_level: 0` on each protocol. Why it follows: without the last two, sslh formats the backend's address for a log message on every connect whatever the verbosity (common.c lines 428 to 430 at v2.3.1), a name lookup unless numeric, and both settings are sslh's documented ones.
4. sslh-ev's `on-timeout` names the HTTP/1.1 route in M3 and B3. Why it follows: section 5.3's second route takes everything else, and sslh's default names SSH, which M3 does not configure.
5. M3's detection timers are matched to the server's 3 s. Why it follows: section 1 sets T_dec to 3 s, section 5.3 names no other value, and Appendix B matches each proxy's timer to the server's.
6. WL7's raise of the soft open-file limit to the hard one applies to every process the hand-off runner and the probe start, in M3 too, for both arms alike. Why it follows: WL7 asks it of every process in B3, M3's 64 connections need nothing more, and one start procedure for every window keeps the arms alike.
7. Every process and thread of a front runs on the front core (`taskset`), nginx's master, Envoy's threads other than its worker and Go's runtime threads included. Why it follows: section 4.1 places the front on CPU 14, and Appendix B gives every front one core in M3.
8. The stub behind every front in M3 is the server's stub mode on epoll with two workers, on CPUs 10 and 12. Why it follows: section 2.1 names stub mode as the backend of M3, section 4.1 puts the backend on CPUs 10 and 12, and section 2.1 runs one worker per core; the stub's backend is the same for every arm.
9. M3's C = 64 is per front core, one, with opgen's eight closed-loop workers on CPUs 2 to 9. Why it follows: WL1 sets 64 slots per server core, the front is the core under test in a hand-off cell, and section 4.1 gives opgen CPUs 2 to 9 there.

Two deviations from the coordinator's M4a brief, both accepted by the coordinator:

10. The proxies' M3 and B3 configurations route TLS by SNI alone (`oneport.test`). Why: section 5.3 says "TLS by SNI to one stub port and everything else to the HTTP/1.1 stub port". The server's route table also checks ALPN (absent, `http/1.1` or `h2`); the cell's ClientHello offers `http/1.1`, so it passes both, and what each system examines to choose already differs (section 5.3). Routing by ALPN belongs to the cases configurations (Envoy's `application_protocols`, Appendix B).
11. Envoy's M3 and B3 configurations hold tls_inspector and not http_inspector. Appendix B's Envoy line names both listener filters without saying in which configuration; the same line gives the benchmarking FAQ's "filter chains only for the compared features", which is how this file reads Envoy's documented best configuration. No M3 route reads HTTP: the second route is the default chain, which takes everything that is not TLS for `oneport.test`. So http_inspector would add work to each connection that no route uses. It belongs to the cases configuration, where chains match `application_protocols`. B3 starts from M3's configuration (Appendix B), so it does not hold it either.

### 2026-10-03: sslh-ev's stalled exchanges, before the code freeze

Note, not a reading; sslh-ev's configuration stays as above. In M4a's development windows 0.60% to 0.67% of sslh-ev's exchanges timed out at opgen's 1 s, with no connect failure, no reset and no listen overflow, so every sslh-ev window of M3 fails section 7's 0.1% error rule. M4b-1 found the cause in sslh 2.3.1 (`design/status.md`, M4b-1, step 1; development diagnostics, journaled):

1. The defect. sslh-ev keeps one libev watcher per descriptor number and initialises it only the first time it sees that number (`watchers_add_read`, sslh-ev.c lines 92 to 103 at v2.3.1, the same on sslh's master on 2026-10-03); later it only starts it again. libev's manual (ev(3), libev 4.33, "The special problem of disappearing file descriptors") says libev takes a descriptor to be new only when `ev_io_set` or `ev_io_init` is called, and to be the same otherwise, while the kernel drops a closed descriptor from the epoll set. When sslh closes a connection and accepts a new one onto the same number in one pass of its loop, no `epoll_ctl` names the new descriptor, so sslh never reads it: the client's request is acknowledged by the kernel and never answered, and the socket stays open in CLOSE_WAIT after the client gives up.
2. The evidence, sslh-ev in its M3 configuration in front of the stub, as in a hand-off window, 1 s warm-up and 2 s measure, HTTP/1.1 unless named. A capture of loopback (tcpdump, no packet dropped): each stalled exchange's request is acknowledged by the kernel and nothing follows from sslh, not even after the client's FIN at about 1 s. An strace of sslh: 176 accepted descriptors whose number sslh had closed earlier in the same pass got no `epoll_ctl`, were never read and were open at the end; each of the other 5,276 accepted descriptors was registered, read and closed; after the run sslh held 176 sockets in CLOSE_WAIT on its port and its listen queue was empty. Without strace: 124 timeouts and 186 sockets in CLOSE_WAIT (HTTP/1.1), 124 and 185 (TLS against the stub).
3. Not a configuration issue. sslh has no setting for it. libev's `LIBEV_FLAGS` environment variable can select its poll backend, which polls each descriptor by number on every pass; in a diagnostic run with it no exchange timed out and no socket was left in CLOSE_WAIT, and sslh's hard-coded listen backlog of 50 (Appendix B) then overflowed with M3's 64 slots: 40 listen drops and 22 connect failures in 2 s, each of which makes a window invalid by section 7. It is a variable of libev, not sslh's documented configuration, and it moves sslh-ev off epoll, the accept model section 5.3 gives all five proxies. So sslh-ev's M3 cells stand as section 7 decides them, a cell with fewer than R_M valid sessions enters Holm with p = 1 (section 4.1), and the narrowing order of section 12 applies (M3 first). No sslh release after 2.3.1 exists on 2026-10-03.

### 2026-10-03: Section 10's check of the server's system-call counters, before the code freeze

The coordinator decided on 2026-10-03 how section 10's sentence "On L, one untimed window per cost cell checks the server's system-call counters against `perf trace -s`" is read. It is logged as a reading of the text above, not a change of a rule; nothing above this log is edited.

1. The reading. The check compares the server's counters with the counts of the same system calls' entry tracepoints (`syscalls:sys_enter_<call>`), counted by `perf stat` over the same untimed window. `perf stat` counts each event in a counter and has no ring buffer, so it drops none. `perf trace -s` stays beside it as a cross-check, and its shortfall against `perf stat` is reported with each row. Each row keeps both results: `agrees_with_perf_stat` is section 10's check, `agrees` the cross-check against `perf trace -s`, and `trace_shortfall_max_share` the largest shortfall as a share of a call's count (`bench/run/systrace.py`).
2. Why. M4b-1's untimed windows on L (`design/status.md`, M4b-1, "section 10's untimed perf trace windows"; development checks, not windows), with each arm's start-up offset taken from an idle pass: `perf stat` equalled the server's counters in all 264 checks, 178 in tracedev2 (22 rows: the relay on two protocols, and churn of HTTP/1.1, h2c, TLS and MQTT and keep-alive HTTP/1.1 on epoll and io_uring, each arm) and 86 in tracedev3 (the worst rows again, with `perf trace`'s ring buffer at `-m 8192`). `perf trace -s` (perf 7.2.6) agreed in 146 of 178 and in 57 of 86, short of `perf stat` by at most 0.31% and 0.42% of a call's count, and reported no lost event in its output or its standard error; the larger buffer did not remove the shortfall. Read literally, the check would fail on a shortfall of the tool that section 10 names for it, while the counters and the exact count of the same tracepoints agree. Section 10 asks that the counters be checked against the system calls the kernel saw; the tracepoints `perf trace -s` summarises are those `perf stat` counts, so the check keeps its object and takes the exact count of it.
3. Not changed by it: the proxies' system calls per connection (section 10, "from `perf trace -s` over untimed windows") stay `perf trace -s`'s, which counts every call a proxy makes. Their rows carry `perf stat`'s count of the calls the server's checks name beside it (accept4 and accept, recvfrom, sendto, setsockopt, epoll_ctl, epoll_pwait2, epoll_pwait and epoll_wait, io_uring_enter, connect, shutdown and splice), so `perf trace -s`'s shortfall is reported for those calls, and the paper states the shortfall measured beside the counts.

### 2026-10-03: Transparent huge pages before the code freeze

Alex decided on 2026-10-03 that every lab job on L sets transparent huge pages (THP) to `madvise` for its length and sets them back at its end. This entry records the cause as M4b-1 found it, the change and its check (`design/status.md`, M4b-1, "Open for the coordinator and Alex", and M4b-2, step 0). WL7 and section 7's settling rule are unchanged.

1. The cause. L ran THP with `enabled` at `always` (`defrag` at `madvise`, `khugepaged/defrag` 1, `khugepaged/scan_sleep_millisecs` 10000, `pages_to_scan` 4096, `max_ptes_none` 511). In M4b-1's B3 windows the fronts' VmRSS rose in steps of 7 to 12 MB about 10 s apart while every connection was idle, each step with a step of the front's AnonHugePages (job b3diag3: nginx 62 to 74 MB as its huge pages went 10 to 26 MB, then 74 to 85 MB with 26 to 42 MB; HAProxy 85 to 92 MB with 2 to 14 MB, then 92 to 102 MB with 14 to 30 MB): khugepaged collapsing the fronts' idle anonymous memory into 2 MB pages, where `max_ptes_none` 511 lets a collapse fill a 2 MB region with up to 511 pages the process never touched (Documentation/admin-guide/mm/transhuge.rst at v7.2.6, "Khugepaged controls"). A step between t = 20 s and 25 s fails section 7's settling rule (job b3dev1: nginx in both cases and HAProxy in the partial-ClientHello case; b3diag3: nginx), and every step adds to U memory the system never touched.
2. The change. `bench/run/thp.sh` (one-port 373695e), a second wrapper beside `clockfloor.sh`, which is unchanged: `lab_job.sh` runs it inside the lab lock and inside `clockfloor.sh`, outside `notrack.sh`; it writes `madvise` to `/sys/kernel/mm/transparent_hugepage/enabled` for the job's length and writes the value it read back when the job ends, also on INT, TERM and HUP; it refuses a job whose setting cannot be made (exit 97), and exits 98 if a setting does not come back. Under `madvise`, huge pages are made, at a page fault and by khugepaged, only in regions a process marks with `madvise(MADV_HUGEPAGE)` (the same document at v7.2.6, "Global THP controls"; fetched from the stable tree, sha256 2c76af6728e87b694afe571b632fbfa27d4569a8cfd3505c8cd9855e48d01d13). `defrag` governs the reclaim and compaction of the page-fault path, not khugepaged's scan (ibid., the `defrag` modes); it reads `madvise` on L and is not written, since the check below found no collapse (the wrapper writes it only when a job names a value in `ONEPORT_THP_DEFRAG`, which none does). The job's record (`<job>.thp.json`) holds `enabled`, `defrag`, `khugepaged/defrag`, AnonHugePages, the host's `thp_fault_alloc` and `thp_collapse_alloc` (`/proc/vmstat`), and khugepaged's `pages_collapsed` and `full_scans`, before, while and after; each session's fingerprint holds the settings before the job and now (`thp`). `b3.py` records every second the system's summed VmRSS and AnonHugePages and the host's two counters, and the counters at each reading, deciding nothing.
3. The check, development data, journaled: job b3thp1 (373695e, Release, under the lab lock, the clock floor, NOTRACK and THP at `madvise`), nginx and HAProxy in their B3 configurations, both cases, two windows each. All 8 windows are valid by section 7; W moved between the samples by 2.1 to 83.1 bytes per pending connection. From t = 11 s to sample 2 each front's VmRSS read the same to the kB in every 1 s sample and its AnonHugePages stayed 0; over the whole job the host's `thp_collapse_alloc` stayed at 1,465 and khugepaged's `pages_collapsed` at 68,807 while its `full_scans` went from 927 to 974. U at sample 2 was the same in both windows of each system and case: nginx 4,939.0 (silent) and 5,307.6 (partial ClientHello), HAProxy 3,087.6 and 7,306.0 bytes per pending connection, where b3dev1 under `always` read 8,232.1, 8,377.5, 3,133.8 and 9,445.0. After the job `enabled` read `always` again. A job stopped by SIGTERM to its process group 6 s after it started (t1) ended with exit 143, and its record shows the setting set back, as were the clock floors and the NOTRACK rules.

### 2026-10-03: Readings fixed during engineering (M4b-2), before the code freeze

M4b-2 (`design/status.md`, M4b-2, "Readings of the frozen text in M4b-2") built the in-process libraries' harnesses and their B3 windows and read the frozen text in these eleven places; the coordinator asked on 2026-10-03 that they be logged. Each line is a reading of the text above, not a change of a rule; nothing above this log is edited. No hard case of Appendix A changes outcome by them. Items 1 and 2 change what runs, and each says why the frozen line supports it.

1. Jetty's PROXY header is detected, not required. Appendix B puts `ProxyConnectionFactory`, with `SslConnectionFactory`, inside the one `DetectorConnectionFactory`, then HTTP/1.1 with the h2c upgrade, so a connection without the header falls through to HTTP/1.1, and the PROXY factory's next protocol is HTTP/1.1. The PROXY cases run on a second listener with the same factories: there HC11 (no header) is served as HTTP/1.1, and a PROXY header followed by a ClientHello (HC13) goes to HTTP/1.1. Why it follows: Appendix B names the factories and their nesting, and in Jetty a `DetectorConnectionFactory` asks each detecting factory in turn and, when none recognises the bytes, hands the connection to the next protocol (the programming guide's section on bytes detection, which proposal CP7 cites; the competitor survey, section 2.16: "PROXY is optional in practice, because detection falls through to the next protocol"). Why the frozen line supports what runs: a configuration that required the header would put `ProxyConnectionFactory` before the detector, outside it, which is not Appendix B's line; the line as written is what serves HC11 and sends HC13 to HTTP/1.1, and section 10 reports the competitors' outcomes on the hard cases they cover as a descriptive table, so these outcomes are recorded as Jetty's, not judged against the server's.
2. cmux's `Any()` stays in B3, and its cases configuration has two kinds: "cases" without `Any()`, "cases-fallback" with it, as HAProxy's, Envoy's and sslh-ev's have. Within a B3 window (30 s) at the 60 s read timeout no silent connection reaches `Any()`, and a partial ClientHello is matched by `TLS()` at its record header. Why it follows: HC6 (silent client, no fallback) needs a listener without a fallback, while HC5, HC7 and HC15 need one with it, and Appendix B lists `Any()` for the fallback. Why the frozen line supports what runs: Appendix B's cmux line lists `Any()` last without a condition, its B3 part adds only the backlog and `debug.FreeOSMemory`, and Appendix B says "Each library harness has two, cases and B3, its B3 configuration starting from its case configuration"; so B3 runs the line as written, `Any()` included, and only the hard cases' "cases" kind leaves it out, because a case without a fallback asks for that.
3. Netty's and Jetty's B3 configurations have no PROXY listener. Why it follows: WL7's openings send nothing or a partial ClientHello, never a PROXY header; Appendix B's B3 lines name no PROXY listener; and a B3 window reads the system's accepted sockets on one port (WL7, Kq and the established count).
4. The JVM runs with `-Djava.net.preferIPv4Stack=true`, so Netty and Jetty open IPv4 sockets for 127.0.0.1, as the server and the proxies do. Why it follows: without it both harnesses listened on IPv6 sockets that take IPv4-mapped connections (found on L, `/proc/net/tcp6`), so B3's Ks and Kq would compare different kernel socket objects between systems, while WL7 compares each system's footprint per pending connection on the same loopback; the property is the JDK's documented networking property and changes no setting Appendix B names.
5. Section 2.1's TLS settings ("the same settings in the server, the backend and the generator") are applied to the libraries that terminate TLS as far as each allows: TLS 1.3 only everywhere; TLS_AES_128_GCM_SHA256 where configurable (Netty, Jetty; Go's crypto/tls fixes its TLS 1.3 suites); X25519 and ecdsa_secp256r1_sha256 (the JSSE properties; Go by its curve list and the certificate); no session tickets (JSSE's stateless ticket extension off; Go's `SessionTicketsDisabled`). Why it follows: Appendix B names TLS termination for Netty (`SniHandler`), Jetty (`SslConnectionFactory`) and cmux (`TLS()`) and sets none of these values, while section 2.1 fixes them for every TLS endpoint of the design; where a library fixes a value itself, its value is kept and named.
6. Netty's `ReadTimeoutHandler` bounds silence for the connection's life (Netty's handler, as documented), not detection alone; `SniHandler`'s handshake timeout takes the same value, and the `SslHandler` it creates inherits it (`SniHandler.newSslHandler` at the tag); at the defaults `ReadTimeoutHandler` is left out. Why it follows: Appendix B names `ReadTimeoutHandler` matched and proposal CP6 says it has no default, so "at their defaults" (section 10) has no such handler; `SniHandler` waits for the ClientHello to choose the context, which is Netty's detection step for TLS, and Appendix B matches the detection timers.
7. The in-process B3 probe checks one exchange of each protocol the system serves among B3's: HTTP/1.1, and a TLS handshake then HTTP/1.1 where the system terminates TLS (not hyper-util). Why it follows: section 4.1's window "checks one exchange of each protocol the cell uses (the probe)", WL7 runs the probe before the baseline, B3's two cases open plain and TLS connections, and section 6.2 says "hyper-util serves no TLS".
8. WL7's collector steps run a fixed lead before each reading, the baseline included: 3 s for the two `jcmd` calls, 1 s for cmux's signal, and 1 s for caddy-l4's heap profile (M4b-1). Why it follows: WL7 gives the JVM systems `GC.run` and `GC.heap_info` and the cmux harness `debug.FreeOSMemory` "before each sample", and U is the growth over the baseline, so the baseline is read after the same step or U would hold what the step frees; a lead lets the collection end before the reading; the leads are design choices sized to the steps (each `jcmd` call starts a JVM, 0.3 to 0.4 s on L).
9. hyper-util's partial-ClientHello window has no pending connection to measure: hyper-util reads 0x16, which is not the h2 preface, hands the bytes to its HTTP/1 parser and closes the connection at once. Why it follows: WL7's footprint is per pending connection, held with the client's bytes incomplete, and section 6.2 has no hyper-util cell in the partial-ClientHello case ("hyper-util serves no TLS").
10. The server's B3 arm against the libraries is one-port mode, in-process dispatch, every timer at 60 s, on epoll and on io_uring, in its default detection mode, which is replay, the proposed default (section 2.1), until rule E decides it after the pilot entry. Why it follows: section 5.2 says "The server runs in relay mode against the proxies and in-process against the libraries, in its default detection mode"; section 1 sets every detection timer to 60 s in B3; section 6.2's cells are on both Linux backends.
11. Netty's receive allocator, which the Netty row of the proposal's buffer table leaves to the code freeze ("Which allocator the native epoll transport uses is read at the code freeze"): on 4.2.18.Final with the native epoll transport, `AdaptiveRecvByteBufAllocator`, with Netty 4.2's default `AdaptiveByteBufAllocator` as the buffer allocator (read on L from the first accepted connection). Appendix B's Buffers row ("the base default receive allocator is adaptive, 64 to 65536 bytes, starting at 2048") names the receive allocator, which is kept. Why it follows: the row keeps both `ChannelOption.RECVBUF_ALLOCATOR` and `ChannelOption.ALLOCATOR` at their defaults, and the reading finds that the native transport keeps the receive allocator the row names; it is read again at the code freeze (section 9.1, pins).

### 2026-10-03: Coordinator decisions after M5, before the code freeze

The coordinator decided these five items on 2026-10-03, after M5 (`design/status.md`, "M5, 2026-10-03", its "Readings, and changes against the proposal's text", and "What M7 starts from"). Items 1, 2 and 5 are decisions on M5's development data; item 3 corrects an example in an earlier entry; item 4 logs M4b-1's readings of the frozen text. M5's exit criteria (`design/status.md`, "M5 exit criteria (set by the coordinator before M5)") are engineering criteria of that file, not rules of this one. Each reading is a reading of the text above, not a change of a rule; nothing above this log is edited, and no rule is added. No hard case of Appendix A changes outcome by them. Every figure is development data from `design/status.md`, named by its job, not a result.

1. The io_uring peek's operations. M5's criterion 1 asks that peek mode add exactly the `MSG_PEEK` (or poll) operations the design adds and nothing else, and that replay add no system call and no copy. Section 10's untimed counter checks at one-port ac84f2d (job m5tr3: HTTP/1.1, h2c, TLS and MQTT churn on epoll and io_uring and HTTP/1.1 keep-alive on both, each cell's two arms in both detection modes, three times each, interleaved; counts only, and by the Words untimed counter checks are not windows) give per connection, one-port less dedicated: in peek on epoll, one `recv(MSG_PEEK)` (24 bytes peeked for HTTP/1.1, h2c and TLS, 14 for MQTT; keep-alive 0.0001 per request, one per connection); in peek on io_uring, one `IORING_OP_POLL_ADD`, one peek and one more `io_uring_enter` (2.0 to 3.0 per connection for HTTP/1.1, 3.0 to 4.0 for the others), with replay's receives, sends and copies. The `io_uring_enter` is the submission round trip of the poll that the design's io_uring peek path adds. That path polls with `IORING_OP_POLL_ADD` first, then peeks, and sets `SO_RCVLOWAT` when a peek is undecided (proposal I11; the frozen text does not describe the poll, and the note of the M2b entry on RK4 keeps this path on io_uring). The poll's completion comes back through the ring before the handler's receive can be posted, so at this load, where every step is its own wait, the poll costs a round of the ring. So the three together are "the operations the design adds" in peek mode, and they meet criterion 1. Replay adds 0 system calls and 0 copies per connection on both backends: in every cell the two arms are equal in sends, `setsockopt` (0), `epoll_ctl` (1), connects, shutdowns and splices (0), peeks and checks (0), io_uring's READ submissions, the receives that returned bytes (`recv_data`) and `bytes_copied` (0 in every row of both arms). What differs depends on when bytes or a FIN arrive, not on the mode, and lies within the dedicated arm's own spread over its three repeats: the accept that ends a batch with EAGAIN (2.0 per connection in both arms, within 0.0004), the loop's waits (`epoll_wait`, `io_uring_enter`, at most 0.0011 apart) and the receives that found the peer's end (`recv_eof`: MQTT on epoll +0.0118, h2c on epoll +0.0079). One such count lies just outside the spread: MQTT on epoll in peek, `recv_eof` +0.0035 per connection, with `recv_data` equal. Every counter that names a system call agreed with `perf stat`'s count of its entry tracepoint in all 120 cost rows of m5tr3, which is section 10's check as the entry "Section 10's check of the server's system-call counters" reads it.
2. io_uring's receive opcode. Since one-port 666a6b7 every io_uring receive of the server, in both arms (dedicated mode's handlers too), is `IORING_OP_READ` on the socket, not `IORING_OP_RECV`, which the proposal names in I11's table (replay on io_uring) and in WL7's paragraph on T, which cites I11 and I15. The frozen text names no opcode: section 2.1 counts "submissions by opcode", section 1(b) speaks of a receive "posted with a buffer" and its non-waiting reap (io_uring replay), section 11 of "the selected provided buffer for a receive", and WL7 of "an armed io_uring receive"; a READ on the socket is each of these. The receive is the same: at the v7.2.6 tag `sock_read_iter` calls `sock_recvmsg` with `MSG_DONTWAIT` at offset 0, which a socket, a stream file, always has (net/socket.c); the provided buffers are the same; it returns 0 at EOF, and a READ that took a buffer and returned 0 names it, and the buffer goes back to the pool (the pin `server.kernel_uring_recv_select` now pins READ). Why it changed: at v7.2.6 every RECV allocates an `io_async_msghdr` at preparation (io_uring/net.c, `io_recvmsg_prep_setup`), which L serves from kmalloc-512, and in every io_uring window with an armed receive in the B3 jobs m5b3a, m5b3a2 and m5b3b kmalloc-512 grew by 236 to 532 bytes per pending connection; an armed READ allocates an `io_async_rw` instead (io_uring/rw.c, `io_rw_alloc_async`). After the change (job m5b3c, ac84f2d) io_uring's Ks exceeded epoll's in the adjacent window by 211 to 335 bytes per pending connection, against 351 to 566 within m5b3a2 and m5b3b before it. So this is a reading of the frozen text and an engineering choice of M5. It supersedes the proposal's wording, and the proposal's revision log says the same. Section 1(b)'s form for io_uring replay, a receive posted with a buffer and its non-waiting reap, is unchanged.
3. A correction to item 2 of the entry "Readings fixed during engineering (M3)", which is not edited. Its example list counts "the two `TCP_NODELAY` of a relayed connection" among the `setsockopt` calls. Since one-port 23eae82 a relayed connection makes one: the relaying listener sets `TCP_NODELAY` once at start and every accepted socket inherits it (pinned on L by the test `server.kernel_nodelay_inherited`), and the backend's socket has its own set before its connect. The item's rule stands: every `setsockopt` on a connection's socket is counted, and a listener's options, set once at start, belong to no connection and are not counted. So the client side's `TCP_NODELAY` is no longer counted per connection. The relay's HTTP/1.1 rows of m5tr3 show one `setsockopt` per relayed connection in replay, on epoll and on io_uring. Only the example is corrected.
4. M4b-1's readings. `design/status.md` lists nine (M4b-1, "Readings of the frozen text in M4b-1"); none was logged as a reading before this entry. Eight are logged here, one line each, numbered as there; reading 3 only in part, since the rest of it is already logged. Reading 4 is not logged (the last line of this item).
   - Reading 1. In B3 with a relay system as the measured system, U is summed over the front's process group (nginx's master and worker), the stub left out, and Kq and the count of established sockets are read on the front's port. Why it follows: WL7 sums U over "the system's processes" and says "The stub backend of the relay systems holds no pending connection and is left out"; it reads Kq "over the system's accepted sockets", and section 7 counts the system's accepted sockets that are established; a front's accepted sockets are those of its listening port, while its connections to the stub are sockets it opened.
   - Reading 2. WL7's probe for a relay system is one TLS stub exchange through the front (the recorded ClientHello, then the stub's 13 bytes and EOF), whose client closes by reset. The stub closes its side first, so the probe can leave one TIME-WAIT socket on the connection between the front and the stub, and the baseline waits until the host's TIME-WAIT count has held for 2 s. Why it follows: section 4.1's probe "checks one exchange of each protocol the cell uses"; WL7 says "The probe's client closes by reset", which it does; section 2.1's TLS stub "writes the 13-byte body and closes", so on the stub's connection the stub, not the client, closes first, and no setting of the client changes that; section 7 makes a window invalid when the host's TIME-WAIT count at either sample differs from the baseline's, and WL7 takes the baseline after the probe, so a socket the probe left is counted at the baseline and at both samples (job b3dev2: TIME-WAIT 1 at the baseline and at both samples). A residual is named: section 7 also says that B3 windows "close by reset and create none"; the window's own connections do, while the probe's stub connection may leave one socket before the baseline.
   - Reading 3, in part. Its lead, caddy-l4's heap profile a second before each reading with the baseline included, is item 8 of the entry "Readings fixed during engineering (M4b-2)" and is not repeated. What it adds: the heap profile request (`gc=1`, at caddy-l4's admin endpoint) goes over an HTTP/1.1 connection closed by reset, so it leaves no TIME-WAIT socket. Why it follows: section 7 makes a B3 window invalid when the host's TIME-WAIT count at either sample differs from the baseline's, and has B3 windows close by reset and create none; requests closed normally left one TIME-WAIT socket per reading (job b3dev1: 2, 3, 4, which made caddy-l4's two windows invalid), and one-port f1f87f3 closes them by reset (job b3dev2: every request answered, none left a TIME-WAIT socket).
   - Reading 5. "At their defaults" (section 10) is each system's own default for its detection timers: the cases configuration at the defaults leaves the timer lines out. HAProxy's default is no inspect delay, with which it decides on the bytes at hand, which its documents call racy and do not recommend; in the route check at the defaults it did not route TLS (and in one run not MQTT), so its routes there are recorded, not judged. Why it follows: section 10 reports the competitors' outcomes "at matched timers and at their defaults", "their" referring to the timers that Appendix B matches; that table is descriptive and decides nothing, so what a system does at its defaults is recorded as its outcome.
   - Reading 6. The fallback lives in a second kind of the cases configuration, "cases-fallback", for the three proxies that have one (HAProxy's `default_backend`, Envoy's default chain with `continue_on_listener_filters_timeout`, sslh-ev's `on-timeout`); the kind "cases" has none. Why it follows: HC6 needs a listener without a fallback and HC5, HC7 and HC15 one with it; Appendix B sets Envoy's `continue_on_listener_filters_timeout` "true only in the fallback cases" and has sslh-ev's `on-timeout` name the fallback "in the fallback cases", so a cases configuration carries the fallback only in those cases. Item 2 of the M4b-2 entry applies the same split to cmux.
   - Reading 7. A second listener of the cases configuration, on the next port, requires the PROXY header (v1 and v2) on the four proxies that read it: nginx (`listen ... proxy_protocol`), HAProxy (`accept-proxy`), Envoy (the proxy_protocol listener filter) and caddy-l4 (the `proxy_protocol` matcher and handler). sslh-ev has none: its pinned build cannot read the header (it is built without libproxyprotocol), so its PROXY cases are not covered. Why it follows: Appendix A's PROXY cases (HC9 to HC15) run on a PROXY listener, which HC11 defines as one whose header "is required, never guessed"; Appendix B names PROXY handling for nginx (`proxy_protocol_timeout` matched) and for Envoy ("proxy_protocol in the PROXY cases"), and a cases configuration holds every route a system's features cover; Appendix B's sslh-ev line, which names the build's option (`ENABLE_REGEX`), names no PROXY; and section 10 reports the competitors' outcomes "on the hard cases they cover".
   - Reading 8. HAProxy's cases configuration also routes h2c, by its preface (`req.payload(0,24)`), a route its features cover beyond the routes Appendix B's HAProxy line lists. Why it follows: Appendix B gives each proxy's cases configuration "every route its features cover", and the same line already routes SSH by `req.payload(0,4)`, the same fetch over fewer bytes.
   - Reading 9. Section 10's untimed windows run churn in open loop at 2,000 exchanges per second (2 s after 0.5 s) and keep-alive with two connections (0.5 s), a design choice of M4b-1, low enough for perf; their rows hold counts only, never a rate or a time. Each arm's start-up offset, the calls the server makes while it starts, which perf, attached after the listeners are up, cannot see, is measured in an idle pass (start, attach, 2 s with no load, stop) and subtracted before the comparison. Item 2 of the entry "Section 10's check of the server's system-call counters" names the idle pass only as the setting of its evidence; it is logged here as a reading. Why it follows: section 10 calls them "untimed windows", and by the Words untimed counter checks are not windows, so nothing in them is timed and one-port mode may run there; the server's counters run from its start, per worker (section 2.1), while perf sees only the calls made after it attaches, so the offset is the part the two cannot share.
   - Reading 4 is not logged. It makes the cases configurations' TLS route SNI `oneport.test` with an ALPN list that offers h2 or http/1.1, and leaves out the server's route for a ClientHello without ALPN, which no hard case sends. Appendix B gives a cases configuration "every route its features cover", and every proxy's features cover a route by SNI without ALPN (their M3 and B3 configurations route TLS by SNI alone, item 10 of the M4a entry), so the reading leaves out a route the frozen line asks for. It is left open for the coordinator.
5. B3 against sslh-ev, development data. In job m5b3c (one-port ac84f2d, replay, the relay's timers at 60 s; each proxy's two windows around the relay on epoll and on io_uring), Q = W_sslh-ev / W_srv was 1.000 (silent, epoll), 0.964 (silent, io_uring), 0.957 (partial ClientHello, epoll) and 0.927 (partial ClientHello, io_uring): below B3's bound of 1.10 in both cases on both backends, sslh-ev's four Holm cells of section 6.2. In bytes per pending connection, sslh-ev's W was 6,960.1 (silent) and 7,064.8 (partial ClientHello), each the mean of its two windows; the server's relay held U 407.1 (silent) and 791.3 (partial ClientHello) and, over m5b3c's five windows, Ks 6,555.6 to 7,079.5 (silent, epoll), 6,811.6 to 7,331.0 (silent, io_uring), 6,589.6 to 6,941.5 (partial, epoll) and 6,826.8 to 7,209.4 (partial, io_uring). So the server's kernel socket memory per pending connection alone, most of it the two loopback socket ends that `K_BASE` measures, is about as large as sslh-ev's whole footprint, which is its sockets' Ks and 400 to 524 bytes of U (job b3dev1: 399.8 silent, 524.3 partial ClientHello; status.md gives sslh-ev's U from b3dev1 only). The server's W is at least its own Ks, which no change to the server can bring below a bare held socket's. The note under M5's exit criteria, written before M5's engineering from jobs b3dev1, b3thp1 and b3lib2, bounded W_sslh-ev / W_srv at 1.13 even at the lowest Ks any system had shown with the server's U and Kq at 0, at 1.08 at the relay's own Ks, and near 1.0 with the server's connection state; within m5b3c every system's Ks fell through the job, from 7,173 to 6,451, a drift that the interleaved Q above does not carry. No engineering on the server's side can close this, so these four cells are expected to fail. Section 12 words such a cell: it is "not shown", and "loss" describes it only where the 95% BCa interval of Q lies wholly below 1.00. B3 then narrows to the competitors and cases the server beats, by the frozen narrowing order of section 12 (M3 first, then B3, then the cost family per backend). This is consistent with that order and adds no rule. Against nginx, HAProxy, Envoy and caddy-l4 the same job gave Q of at least 1.320 (HAProxy, silent, io_uring).

### 2026-10-03: Readings fixed during engineering (M5), before the code freeze

M5 (`design/status.md`, "M5, 2026-10-03", "Readings, and changes against the proposal's text") listed five items. Items 2 and 3 are logged in the entry "Coordinator decisions after M5" (its items 3 and 2). Items 1 and 5 are logged here, one line each, numbered as there. Each is a reading of the text above, not a change of a rule; nothing above this log is edited. No hard case of Appendix A changes outcome by them.

1. Relay dispatch has no counterpart in dedicated mode, so section 10's operations and copies per connection for the relay are given per relayed connection in each detection mode, and what peek mode adds to the relay is read as peek against replay, not as one-port against dedicated. Why it follows: the Words define dedicated mode as one listening socket per protocol with no detection; section 2.1 has the relay's front open its connection "to the backend chosen by class", a class that only detection gives; and the cost family, the only contrast of the two modes (sections 2.2 and 5.1), uses in-process dispatch. M5's exit criterion 1, which named every dispatch, is an engineering criterion of `design/status.md`, not a rule of this file.
5. Item 1 of the M2b entry (the relay passes each side's end on as a half-close, the other direction goes on, and the connection closes when both directions have ended) stands since one-port 23eae82, where the direction that ends last is closed by `close()` alone, with no `shutdown()` before it. Why it follows: when the last direction ends, the other has already ended and every byte before its FIN was read, so the socket that `close()` ends holds no unread byte, and Linux then sends a FIN, not a reset (`tcp_close` in net/ipv4/tcp.c resets only for unread data); each peer sees the same bytes and the same end as after a `shutdown()` and a `close()`, and section 2.1 names no call.

Item 4 is not logged: it is reported to the coordinator (`design/status.md`, "M7 preparation, 2026-10-03").

Note, not a reading: M4b-1's reading 4, left open in item 4 of the entry "Coordinator decisions after M5", no longer describes the configurations. Since one-port f7d62a2 every proxy's cases configuration also holds the route for a ClientHello without ALPN, as Appendix B's "every route its features cover" asks (`design/status.md`, "M7 preparation, 2026-10-03").

### 2026-10-03: The code freeze's preparation (M7), before the code freeze

Item 1 is the coordinator's decision of 2026-10-03; item 2 records three values of section 9.1 set in engineering (`design/status.md`, "M7 fixes, 2026-10-03"). Nothing above this log is edited, and no rule is added. No hard case of Appendix A changes outcome by them.

1. The route for a ClientHello without ALPN is in all five proxies' cases configurations (one-port f7d62a2), and Envoy, caddy-l4 and sslh-ev route any other ALPN list to the TLS port by SNI alone, which no hard case sends.
2. `N_BG_TLS` = `N_BG_MQTT` = `N_BG_SILENT` = 64 (section 9.1, set in engineering, step 2), a design choice. Section 9.1 gives no rule for them beyond the cell they size, section 10 makes the background fixed and the same in both modes, and section 9 forbids a value chosen after data that could favour it: no window of the mixed-protocol cell has run, and none ran to set them. The reason: C = 64, WL1's connection slots per server core and WL3's connections, is the only count of connections per core that the text fixes for a cost cell, so each kind of background holds as many connections as the cell's churn has slots, and equal counts weigh no kind above another. The code freeze's entry names them again with the other values of section 9.1.

### 2026-10-03: Readings fixed during engineering (M7c), before the code freeze

M7c (`design/status.md`, "M7c, 2026-10-03") wrote the runners that will produce the frozen data and read the frozen text in these five places. Each line is a reading of the text above, not a change of a rule; nothing above this log is edited, and no rule is added. No hard case of Appendix A changes outcome by them.

1. Rule E's relay copy is chosen per backend that relays: one choice on epoll and one on io_uring, as the detection mode is chosen per backend and the receive form on IOCP. "If rule E chooses `splice`, HAProxy gets `option splice-auto`" applies cell by cell: HAProxy gets it where the server's relay in the same cell splices (on epoll in M3 and B3, on io_uring in section 10's relay cells). Why it follows: section 8 gives rule E "Three choices per backend", and section 2.1 has relay dispatch on Linux only ("Relay (Linux only)"), so the relay copy is a choice of each Linux backend.
2. The pilot's C1 and C2 cells, their reruns included, end before its first C3 session; the C3 sessions' own reruns come at the end. Section 10's SSH cells run the same way: their C1 sessions, reruns included, before their C3 sessions. Why it follows: section 8 step 4 runs "the C1 and C2 cells of a host before its C3 cells" and a session with an invalid window "again at the end of the pilot's order", while WL2 sets each C3 cell's rate from "the A/A pilot's sessions ... in the C1 pilot cell"; a C3 window can run at that rate only once every C1 session that sets it has run, so the end of the order is read per part. Section 10 likewise takes the SSH C3 rate from "their C1 sessions", which "run first".
3. The timer part's lateness is the time from a run's T_hdr deadline to the instant the wait of the loop pass that handled it returned (the server's decision record: `wait_return_ns` - `deadline_ns`), one connection at a time against one server per backend. Why it follows: section 8 step 4 measures "from the deadline to the start of the loop pass that handled it", and a loop pass starts when its wait returns (B2(b): "the first loop pass whose wait returned at or after it").
4. Each split-part replicate runs against a server started for it alone, so "the counters of its one connection" are that server's counters; a receive "that returned payload" is a receive less those that found the peer's end or no byte (`recv_calls` - `recv_eof` - `recv_again`). Why it follows: section 2.1 keeps the counters per worker, not per connection, so a server process with one connection makes them the connection's; and section 2.1's counters split the receives that found the end or nothing from the rest.
5. "The slower arm's median connections per second" (section 10: the SSH C3 rate, and the rate of M1's and M3's TTFB at a fixed load) and WL6's "the smaller of its two arms' median closed-loop connections per second" (`M2_RATE`) take each arm's value in a session as the mean of its two windows, its median over the cell's valid sessions, and the smaller of the two arms' medians. Why it follows: section 4.1 defines "an arm's value in a session" as "the mean of its two windows", and section 7 discards a session with an invalid window.

### 2026-10-04: M7c's open items, before the code freeze

M7c (`design/status.md`, "M7c, 2026-10-03", "For the coordinator") left items open; M7c's follow-up (`design/status.md`, "M7c follow-up, 2026-10-04") settled them against the text above. They are logged here, each labelled a reading of the text or a design choice. Nothing above this log is edited, no rule is added, and no value of section 9 is set. No hard case of Appendix A changes outcome by them. The section 10, B3 and M runners apply items 2 to 6, and a frozen run of theirs refuses to start unless the revision log holds this entry's heading (`bench/run/freeze_guard.py`, one-port 8e77e28). This entry names no file by its sha256, so it is none of the entries the frozen runners look for by a word and a sha256 (CODE_FREEZE, the seeds, the pilot, rule E, M2_RATE). Every figure below is development data, named by its job, not a result.

1. Reading. The mixed-protocol cell's "TLS keep-alive" and "MQTT keep-alive" (section 10) are WL3 with C = `N_BG_TLS` and C = `N_BG_MQTT`: that many connections established before the window, one request in flight on each (HTTP/1.1 GET over one TLS connection; MQTT PINGREQ after one CONNECT), a closed loop, each kind its own `opgen` process, the same in both modes. Why it follows: WL3 is the text's only definition of keep-alive, and sections 2.4 and 5.1 use the word for it; section 9.1 sizes the background by three counts and by nothing else, and the counts are WL3's C; so "fixed" fixes the counts and the background's make-up. A fixed rate, the sense of "a fixed load" in C3 and section 10, would need a λ that the text neither gives nor gives a rule for, and section 9 sets no value without its rule. Consequence, from job e2e2 (M7c; the mixed cell on epoll, its dedicated arm only): the cell's HTTP/1.1 churn ran at 17,536 to 17,662 connections per second while each background completed 443,778 to 448,970 requests over its 10 s run, where dedicated HTTP/1.1 churn alone on epoll ran at 44,655 to 44,980 (job aa-floor1, the entry "Host clock floor before the code freeze", item 3). So the closed-loop background takes most of the server's core. Its generators used 25.8% to 30.1% (TLS) and 15.5% to 16.3% (MQTT) of their two CPUs' time, so the server set the background's rate, not they. Each row holds the background generators' reports: requests and errors, and since one-port 3623df6 their CPU time.
2. Design choice. In dedicated mode the mixed cell's `N_BG_SILENT` silent connections go to the dedicated HTTP/1.1 port, not spread over the dedicated ports (`bench/run/s_run.py`, `--silent-ports http1`, the default; a frozen run refuses `spread`). Why: section 10 makes the background "the same in both modes", and a silent connection names no protocol, so no dedicated port is its own. The cell's load is C1's HTTP/1.1 churn, and the HTTP/1.1 port is the one dedicated listener that load uses, so with this choice the silent connections share the listener and the worker of the measured load in both modes, as they must in one-port mode, which has one listener. Spread over the ports, the dedicated SSH and SMTP ports would also send their first lines to each silent connection, output the one-port arm never sends to a silent connection on a listener without a fallback. The proposal's "dedicated mode spreads it over its ports" is not in the frozen text. Development check, job e2e4 (one-port 8e77e28; the mixed cell on epoll, its dedicated arm in a session and its rerun, development seeds 7951 to 7964): in each of the 4 windows the 64 silent connections were held on the HTTP/1.1 port from before the probe to the stop, none was closed or opened again and no byte reached them, and the cell's churn ran at 17,676.6 to 17,727.8 connections per second.
3. Reading, with a design choice for the silent case. Section 10's B3 cells of the server's other detection mode (4 cells) run the server in relay mode in front of the stub, in both cases on both Linux backends, with rule E's relay copy (`bench/run/b3_run.py`, `--other-mode-system one-port-relay`, the default; a frozen run refuses `one-port-inproc`). Why it follows: WL7 places the skb residuals with a system that leaves bytes queued, and among them names "the server only where its detection mode is peek (rule E of section 8, and the peek side of section 10's B3 cells)". In the partial-ClientHello case the server leaves bytes queued in peek mode only in pass-through, whose route waits for the whole ClientHello (the M2b entry, item 3: "in peek nothing in user space"; the M3 entry, item 1). In-process, the TLS handler reads the bytes into its buffer once TLS is classified at byte 6, in either mode: in job m5b3b the server in-process held the same U per pending connection in replay and in peek (4,521.2 and 4,521.2 bytes on epoll, 4,522.8 and 4,522.8 on io_uring; `design/status.md`, M5, item 3). So only relay dispatch gives the cells' peek side what WL7 says of it. The silent case, where no byte is queued in either dispatch, takes the same dispatch as a design choice, so a backend's two cells differ only by the case; it is also the server's dispatch in 16 of the 18 Holm cells of 6.2.
4. Reading. Section 10's "TLS with ALPN `h2`: C1 on each backend" runs. Section 2.1's "ALPN `http/1.1` in the cost cells" does not forbid it: the sentence is scoped to the cost cells, the cells of 6.1, and section 10's variants are not among them (section 10 lists "Cost cells not resolved by the pilot" as a bullet of its own). WL1's table has no row for it, so its exchange is composed from two rows: the TLS row's full handshake, with the generator offering ALPN `h2` alone and failing the exchange unless the server chose `h2`; then the h2c row's exchange inside TLS (preface, SETTINGS and one HEADERS frame with END_STREAM; read to END_STREAM; GOAWAY), with the client closing first, as in the h2c row, after close_notify (RFC 8446 s6.1). Every other TLS setting of section 2.1 holds. The cells are C1's contrast: one-port against dedicated mode, in-process dispatch, the default detection mode, WL1's metric, R = 16 (section 10), in the order of the other secondary cells (4.7). Code: `opgen --proto tls-h2` (one-port 236ee3c, tested against the server in both modes on epoll and io_uring; its IOCP tests are registered in W's suite, which has not run them) and the section 10 runner (8e77e28). The IOCP cell needs W's runner. Development check, job e2e4: the dedicated arms of both L cells, a session and its rerun each (the one-port arms development stubs), all 8 dedicated windows valid, every probe passed and no exchange of a warm-up or a window failed, so the server chose `h2` on every connection.
5. Reading. Section 10's "TLS with session resumption: C1 on each backend" (3 cells) is not run; the paper reports the cells as not run, for this reason. Section 2.1 fixes for the server, the backend and the generator alike, with no scope, "no session tickets (`SSL_CTX_set_num_tickets(ctx, 0)`), no session cache, no early data". TLS 1.3 resumes a session only with a pre-shared key from a NewSessionTicket (RFC 8446 s2.2 and s4.6.1), which the server would have to send and the generator keep, so the variant cannot run without contradicting those settings. The text itself draws the line between items 4 and 5: it scopes the ALPN setting to the cost cells and leaves the ticket and cache settings unscoped. The proposal's I24, which put "Session resumption is a secondary cell" right after the same settings, is not in the frozen text. Section 10's cells decide nothing, so no claim of section 1 changes.
6. Reading, with a design choice of the M runner. An M2 cell whose `M2_RATE` 9.3's rule cannot compute (an arm with no valid development session: the entry "Readings fixed during engineering (M7c)", item 5, takes the median over the valid sessions) has no rate, since section 9 sets no value by another rule. Without a rate no open-loop window of the cell (WL6) can run, so the cell has fewer than R_M valid sessions, cannot be tested and enters Holm with p = 1 (4.1, 4.2); m stays 20, and section 12 reports it as a difference not shown, with the reason. Design choice: the M runner starts no window for such a cell and lists it as not run, with the reason (`bench/run/m_run.py`, `not-run-<job>.json`), rather than writing a fault row for each window; no decision changes by it. Why it may apply: in job e2e1 (M7c; M2's TLS cell on io_uring, the m2-rate part, 8 sessions) 15 of the 16 relay windows were invalid by section 7's backend rule, with backend core 12 92.6% to 100.4% busy and core 10 at most 7.6% busy; the one valid relay window had core 10 41.2% and core 12 59.2% busy, at 3,940.8 connections per second, within the 3,912.9 to 3,956.6 of the invalid ones. Every session held an invalid relay window, so no rate was computable. The backend's two workers share one listener, and in those windows one worker took nearly every connection. M2's TLS cell on epoll has not run its rate sessions.
7. Design choice (M7c's, logged here). The mixed cell's placement: the server on CPU 14, its sibling idle, as in every in-process cell; the cell's `opgen` on CPUs 2 to 9; the TLS background's `opgen` on 10 and 11; the MQTT background's `opgen` and `opcase hold` on 12 and 13. Why: section 4.1 gives the in-process cells CPUs 2 to 13 for `opgen` and places no background; the background's generators are first-party generators (section 2.4), so they take CPUs from that range; the cell's generator keeps 8 CPUs, as `opgen` has in the hand-off cells, and shares none with a background thread, so section 7's generator rule reads it alone (item 8).
8. Reading. In the mixed cell, section 7's rule "the generator's CPUs were more than 90% busy in a saturation cell" applies to the cell's generator, whose rate is the cell's metric, and not to the background's generators, whose CPU time each row records (item 1; one-port 3623df6). Why it follows: the rule comes from `lab/t1/t1.py`, as P2's H6 used it, so that a saturation cell's rate is the server's and not the generator's, and the mixed cell's rate is its churn's (section 10: "C1's HTTP/1.1 churn"). In job e2e2 the background's generators were at most 30.1% busy (item 1).

### 2026-10-04: ANALYSIS_COMMIT, before the code freeze

Section 8 step 2 has "the analysis code that runs 4.6 ... committed with its tests (`ANALYSIS_COMMIT`)" before engineering ends, and section 9.1 records the commit. M7c's follow-up (`design/status.md`, "M7c follow-up, 2026-10-04") found nothing in `analysis/` still to change. Nothing above this log is edited, and no rule is added. Every figure below is a test count, not a result.

1. `ANALYSIS_COMMIT` = 7364fbbbf356e22bb0d6a74b0b9bc29b62c3534b, one-port's last commit that changed `analysis/` ("fix(analysis): rule E's relay copy is one choice per backend that relays", M7c). `analysis/` runs 4.6 and the pilot entry's values (`pilot.py`), every family's tests with Holm and section 10's intervals (`analyse.py`, `stats.py`, `cells.py`, `rows.py`), and `results/macros.tex` (`macros.py`); it pins numpy 2.5.0 on Python 3.14 (`versions.py`, `requirements.txt`), and its command lines refuse any other.
2. Its tests at that commit, from a fresh clone on L, in a venv with numpy 2.5.0 and Python 3.14.7 (lab job ana1): 70 passed, 1 skipped, the skipped one being the Appendix A test at N_SIM = 1,000, which ran alone with `ONEPORT_SLOW=1` (lab job ana2): 2 passed. Logs, sha256: ana1 75a2c66cf2b7f3ee087cd3e1e22a152a462b4ec0c86fe36e4eae5704c6ad4193, ana2 af3b9364d090f9ae9e8b7b06f113062f4ddbf1e0cbc77b27562f52d0914906de.
3. No file of `analysis/` changed after it, up to one-port 13004bc (`git diff` empty); at 8e77e28 the same tests gave the same counts (ana1). `analysis/rows.py` also reads `bench/check_rows.py`, whose only later change (6f19094) adds an option that a development check passes and is off by default. The rows of the cells that M7c's follow-up changed (the ALPN h2 cells, B3's other-mode cells in relay, an M2 cell without a rate) are forms `analysis/` already reads (`bench/run/test_frozen.py`).
4. The seeds entry, the other half of section 8 step 2, is not made here. No frozen runner reads this entry; its line holds the word `ANALYSIS_COMMIT` and the full hash, as the code freeze's line will hold `CODE_FREEZE` and its own.

### 2026-10-04: The pre-freeze items on L (M7d), before the code freeze

M7d (`design/status.md`, "M7d, 2026-10-04") settled the items of the M7 checklist that need L only, before the code freeze. Each item is labelled a reading of the text above, a design choice, or a record of what was read; nothing above this log is edited, no rule is added, and no value of section 9 is set here (the code freeze's entry names them). No hard case of Appendix A changes outcome by them. The M runner applies item 1, and a frozen run of it, in either part, refuses to start unless the revision log holds this entry's heading (`bench/run/freeze_guard.py`, one-port 1bc1e53). Every figure below is development data named by its job, or a reading of a file named by its sha256, not a result.

1. Design choice, with a reading. M2's relay arm runs its backend, the server in dedicated mode with two workers on CPUs 10 and 12, in a `SO_REUSEPORT` group (`--listener reuseport`, one socket per worker on the same ports) instead of the shared listener, in M2's cells and in the development sessions that set `M2_RATE` (`bench/run/m_run.py`, `M2_BACKEND_LISTENER`; one-port 1bc1e53). The reading: the text leaves the backend's listener open. Section 4.1 fixes the backend's cores, section 2.1 one worker per server core, and 5.3 a backend that terminates TLS; nothing names its listener. The Words give dedicated mode "one listening socket per protocol", but the text itself counts a `SO_REUSEPORT` group on one port as that port's listening socket: section 10 runs "the `SO_REUSEPORT` group against the shared listener, both in one-port mode", whose Words are "one listening TCP socket per process". Section 11's "two workers on the shared listener" is the TSan suite's setting, not the backend's. The rule of the choice was fixed before any comparison ran (one-port 64f4c98, its message): adopt the group if the text leaves the listener open and the group balances the backend's two workers; report validity and the closed-loop rate beside it; never read WL6's CPU per connection, M2's metric. Development comparison, job m2l (one-port 64f4c98, dryrun9's Release binaries, oneport 4c64edc2 and opgen a25faa11; the m2-rate part of the M runner, the four M2 cells of L, 6 sessions each with the runner's reruns, 112 windows per layout; development seeds 8101 with the shared listener, 8102 with the group; both arms one-port fronts, so no one-port window against dedicated mode and no window against a competitor; rows sha256 398296f43269edc63a7353a3975fbb6d6f87c0e8b23aa0da0b83fa4b76cbb320 and 38a8446c2c55a3f7640d65d16d2c34f43e8186caa387f77b62990c1ab76cfcc2). Balance, as core 10's share of the two backend cores' busy time in each relay window: with the shared listener 0.009 to 0.626 (HTTP/1.1, epoll), 0.217 to 0.763 (HTTP/1.1, io_uring), 0.401 to 0.501 (TLS, epoll) and 0.000 to 0.010 (TLS, io_uring: one worker took every handshake, as in job e2e1); with the group 0.486 to 0.512 in every relay window of the four cells. So the group balances the workers, and the choice is made. Validity: the HTTP/1.1 cells had 6 valid sessions under either layout (no backend core above 43.0% busy with the shared listener, none above 24.4% with the group). In both TLS cells under both layouts every relay window was invalid by section 7's backend rule: with the shared listener, on io_uring core 12 was 99.4% to 100.4% busy, and on epoll core 12 was 99.2% to 99.8% busy and core 10 66.8% to 99.8%; with the group both cores were 96.8% to 100.0% busy on both backends. The rate: in the HTTP/1.1 cells the relay arm, front-bound (the front 99.6% to 100.2% busy), ran 13,627.6 to 13,753.2 (shared) against 13,759.6 to 13,836.6 (group) connections per second on epoll and 14,842.2 to 14,994.8 against 14,809.4 to 14,935.6 on io_uring; in the TLS cells the relay arm ran 3,926.0 to 3,974.7 (shared, io_uring), 6,330.9 to 7,628.9 (shared, epoll), and 7,448.7 to 7,739.3 with the group on both backends, while the in-process arm, every window of it valid, ran 3,817.0 to 3,952.8 in every TLS session. Consequence, stated and not decided here: by 9.3's rule as read (the entry "Readings fixed during engineering (M7c)", item 5: the median over valid sessions) neither TLS cell has an `M2_RATE` under either layout, so item 6 of the entry "M7c's open items, before the code freeze" applies to both; the backend that terminates TLS is the relay arm's limit in closed loop, whatever its listener. M3's stub keeps the shared listener (the M4a entry, item 8), and so do the stub behind section 10's relay cells, rule E's relay-copy sessions and B3's relay systems; the hard cases' relay backend runs one worker, so it has no listener layout to choose. No competitor's cell uses the dedicated backend, so the choice applies to the server's arms alone.
2. Reading (M7c's open item 4). Rule E's test, as `bench/run/rule_e.py` computes it. An option favours a session when its connections per second under WL1 churn, the mean of its two windows (4.1's arm value), are strictly above the default's; a tie counts against it, as a tie counts against the hypothesis in 4.2's sign test. "Every session of at least 6 development sessions" needs at least 6 valid sessions, every one favouring the option; an invalid session runs again by 4.1's rule, at most 2 times per choice (⌈6/4⌉), so a choice left with fewer than 6 valid sessions keeps the proposed default. "Its operations per connection are not higher" compares one number per arm: the sum, over the kinds of section 2.1, of the server's operations (accept, receive, peek, zero-byte receive, send, `setsockopt`, the check of 1(b), `epoll_wait`, `epoll_ctl`, `io_uring_enter`, `GetQueuedCompletionStatus`, connect, splice, shutdown, and io_uring's submissions by opcode), over each window's server process, per connection it accepted (WL5; the M3 entry, item 6), averaged over the arm's valid windows; an equal sum is not higher. The detection sessions run in section 4.1's in-process placement; the relay-copy sessions run the server's relay on CPU 14 in front of the stub on CPUs 10 and 12, the hand-off placement. Why it follows: rule E names one quantity, "its operations per connection", over the operations section 2.1 counts by kind, so their sum is that quantity; "favours" in a comparison of two arms is the sign test's "strictly on the hypothesis side"; section 8 gives the sessions no placement of their own, so each takes the placement of the dispatch it runs, and relay dispatch exists only in the hand-off placement.
3. Design choice (M7c's open item 6). The cost family's dedicated arm, and both arms of the pilot, start the server with the detection flag of rule E's default for the backend, the same value as the one-port arm. In dedicated mode the flag acts on nothing: the server reads it only for a listener that detects (`Worker::peeks`, `bench/server/worker.hpp`), and no dedicated listener detects (the Words: dedicated mode has "no detection"). Why: section 5.1's arms are the "same binary", and section 4.6 step 1's pilot arms are "two starts of the same binary and flags"; one flag value in both arms keeps a cost window's command lines equal but for the mode and the port.
4. M7c's design choices (M7c's open item 7), each labelled. (a) Reading, with a design choice: K_BASE's `ophold` windows run until 16 are valid, at most 4 more (⌈16/4⌉), never more than 16 valid; 4.1's rerun cap read onto WL7's 16 windows, which are windows of one kind, not sessions. With fewer than 16 valid windows K_BASE is not computed and is reported missing with why (`analysis/analyse.py`, `k_base_of`); no B3 decision changes, since Q = W_comp / W_srv and W = U + Kq + Ks hold no K_BASE (WL7). (b) Design choice: `opcase` waits at most 20 s for a hard case's script in the server's runs (`bench/run/hardcase_run.py`, `SERVER_WAIT_MS`); the longest wait it covers is HC4's drip over 2 × T_dec (the M1 entry, item 4). It bounds the harness, never an outcome. (c) Design choice: one server per listener setup (plain, SMTP fallback, PROXY, both) per entry of backend, detection mode and dispatch, kept for every run of the entry, each server checked at the entry's end; Appendix A says on what each case runs, not how many servers. (d) Design choice: one reference transcript per variant and entry, from the dedicated port, against which every replicate is compared (Appendix A: "the transcript equals the dedicated port's"). (e) Reading: the competitors' rows record each outcome and say whether the reply equals what the server's frozen table expects of the server; that field decides nothing, as section 10's table is descriptive. (f) Design choice, development runs only: a development stub session (a one-port arm not started before the pilot entry) is run again like an invalid session; a frozen run has no stub.
5. Neither a reading nor a design choice (M7c's open item 9). `bench/run/runlib.py`'s host is L: the frozen runners of `bench/run/` run L's cells, and `window.py` and `cellwin.py` read L's `/proc`. W's pilot and its parts, the cost cells on IOCP, M1 on IOCP, rule E's IOCP detection sessions and section 10's W cells need W's runner, which must write the same rows. That is the open half of the M7 checklist's item 2 (`design/status.md`); no line of the text is read by it.
6. Record, with two readings: the pins re-read against their upstreams on L on 2026-10-04 at 04:48 and 04:49 +0300 (`pins_read.sh`, log sha256 07a6739109270e4b919ec3802119d23a5158dc9f609ebd69ac72221a47560fa8; `pins_read2.sh`, log sha256 f0baa971d8a85a2ec769ec0dd0f03ef94c4cdc3661789818daa60a0fce1e68c1). No pin changes. OpenSSL 3.5.9 (2026-09-29) is still the latest 3.5 release; nghttp2 v1.70.0, Envoy 1.39.2, xcaddy 0.4.7, sslh v2.3.1, cmux v0.1.5, hyper-util 0.1.21, Netty 4.2.18.Final (Maven Central's newer 5.0.0.Alpha2 is a pre-release of another major) and Jetty 12.1.13 are each still the latest release of the pinned line; nginx's latest stable is still 1.30.5 (mainline 1.31.6, which the survey spot-checked); HAProxy's 3.4 branch is still at 3.4.6; caddy-l4's latest release is still v0.1.2, and its default branch's head is still 42db5690dea199f930a6f08005fe2e4aab10dcc9. Temurin 25 is still the latest LTS (Adoptium's most_recent_lts 25), and its latest GA build is still jdk-25.0.4.1+1 with the pinned archive's sha256; 25.0.5 is not published. The M7 checklist's rule stands: read again on the day of the code freeze, before its commit. (a) Reading: Caddy published v2.11.6 (2026-10-01, 15:21 UTC) and v2.11.7 (2026-10-03) after v2.11.4. caddy-l4 is the competitor, pinned by its release and commit (Appendix B: "Pinned by commit"), and Caddy v2.11.4 is the Caddy that release's `go.mod` requires (`bench/competitors/caddy-l4/go.mod`), on which xcaddy builds it; a newer Caddy is not a newer release of caddy-l4. The text supports this: it names "on Caddy v2.11.4" though v2.11.6 had been published the day before the text was frozen. So caddy-l4 stays v0.1.2 at 42db5690 on Caddy v2.11.4. (b) Reading: Rust 1.99.0 was published (the stable channel dated 2026-10-01; Arch's `rust` 1:1.99.0-1 on 2026-10-02). Section 9.1 pins "the Rust toolchain ... by archive URL and sha256" and gives no rule of the latest release for it, as it does for OpenSSL and the JDK; section 2.3's rule covers the systems of its table, whose hyper-util 0.1.21 is unchanged. So L's `rust` 1:1.98.1-1 and `rust-src` 1:1.98.1-1 stay (both installed on L, the packages in pacman's cache; `rustpkg.log`, sha256 97218de79b6bfc0c50c9e9c0d217a77f886d53ab55f579ae0bf4bd7e5942828b).
7. Record: the skb caches on L, read again as root, read only, on 2026-10-04 at 04:50 +0300 (`slab_read.sh`, log sha256 cd73e15c2e1bbf8106cef142a4da5c44914c19a7347590850c5c6f2d584f2dcf), section 9.1's reading. Kernel 7.2.6-arch2-1, its command line without `slab_nomerge`, built with `CONFIG_SLUB_DEBUG=y` and `CONFIG_SLAB_MERGE_DEFAULT=y`, without `CONFIG_SLUB_DEBUG_ON`. `/proc/slabinfo` exists. "skbuff_head_cache" and "skbuff_small_head" are directories of their own (`aliases` 0) and `/proc/slabinfo` lists each under its own name. `/sys/kernel/slab/skbuff_fclone_cache` links to `:0000512`, whose `aliases` is 2 and whose linked names are "pool_workqueue", "sgpool-16" and "skbuff_fclone_cache"; `/proc/slabinfo` lists that cache as "pool_workqueue". The page size is 4096 bytes. This is WL7's reading and that of the entry "Host change before the code freeze", item 1, unchanged, so WL7's rule for merged caches applies as frozen.
8. Record: section 9.1's values set in engineering, as they stand for the code freeze's entry. `K_SRC` = 16 (the M3 entry, item 9) holds by its rule: in every row file written on L after that entry (one-port 446055b, 2026-10-03 08:36:23 +0300), 129 files and 3,528 rows, every field that records a failed connect (opgen's connect errors in the warm-up, the measured window and the run, opgen's, `opcase`'s and the probe's connect failures, and the mixed cell's background generators' and holder's) is 0, and no invalid reason names a failed connect (`ksrc_scan2.py`, log sha256 577efee64acc804c3a007a61d71267a52afae47c1ba083ddbef203acf7b346f4). `N_ACCEPTEX` = 64 (`kAcceptEx`, `bench/server/worker.hpp`; M6a). `RELAY_BUF` = 4096 bytes per direction (`kRelayBuf` = `kRecvBuf`, `bench/server/server.hpp`; M2b). `N_BG_TLS` = `N_BG_MQTT` = `N_BG_SILENT` = 64 (the entry "The code freeze's preparation (M7)", item 2). ℓ = 206: the record length that the header of `tests/fixtures/tls/clienthello.hex` announces (bytes `16 03 01 00 ce`, 211 record bytes; sha256 b553d6d76d8be29b2054ec762f2c01546ff92f1610214874048e15ee5ef222b2).
9. Record, as section 11 provides: OpenSSL ran under TSan. Engineering builds OpenSSL with `-fsanitize=thread` (`bench/third_party/build_deps.sh`, the tsan flavour), and the suite passed under TSan with it: the TSan build of the M7c follow-up's chk5 (one-port 8e77e28) linked `openssl-3.5.9-tsan` and `nghttp2-1.70.0-tsan` and passed 398 of 398 tests with 0 report lines (ctest log sha256 342b000c0049440af989cb128970a660ef08f725f52b2974da20fc2a65e82f98). Read on L (`ossl_check.sh`, log sha256 8da18fb0a4be326e3cdc3b36b5aa6faa4580d1e15cb6e1bd1d7cad9b495ed142): 954 object files of that build's `libcrypto.a` and 90 of its `libssl.a` call `__tsan_func_entry`, and none of the release, asan or msan flavours does. So the declared gap "OpenSSL under TSan" leaves `bench/coverage.json`. The other gaps stay, each read true: OpenSSL's assembly (`libcrypto.a` defines 24 `aesni_` functions in the release, asan and tsan flavours and none in the msan flavour, which `enable-msan` builds without assembly); UBSan's function check, left out of all of OpenSSL by `openssl-ubsan.ignorelist` (`[function]`, `src:*`) in the asan flavour alone; io_uring's kernel writes under MSan, with the mitigation `bench/coverage.json` names; the competitors' binaries and runtimes; the harnesses; UBSan in the Go and Rust harnesses; Windows, whose build of the merged tree on W is still open (the M7 checklist's item 2).

### 2026-10-04: The seeds of section 4.7 (M7d), before the code freeze

Section 8 step 2 asks for one revision-log entry, before the code freeze, that fixes every seed of 4.7, each checked against the lab journal as used by no earlier run (section 9.1), never changed after. This entry states the procedure first, in the commit that adds these lines, before the draw; the values follow below it, appended after the draw. Nothing above this log is edited, and no rule is added.

1. The names, in 4.7's order: `SEED_ORDER_C_L`, `SEED_ORDER_C_W`, `SEED_ORDER_B_L`, `SEED_ORDER_M_L`, `SEED_ORDER_M_W`, `SEED_ORDER_S_L`, `SEED_ORDER_S_W`, `SEED_BOOT_C`, `SEED_BOOT_B`, `SEED_BOOT_M`, `SEED_BOOT_S`, `SEED_PILOT_L`, `SEED_PILOT_W` and `SEED_SIM`: the 14 names the frozen runners (`bench/run/runlib.py`, `SEED_NAMES` and `load_seeds`) and `analysis/` (`cells.py`, `check_seeds`) read from the seeds file, each a non-negative integer.
2. The draw, once. On L, in one process of L's python3, for each name in that order, `secrets.randbits(32)` is called once; its value is kept unless item 3 excludes it, in which case it is discarded and `secrets.randbits(32)` is called again for the same name, until a value is kept. Every call is printed with its name, its value and whether it was kept. The draw is not repeated, whatever its values.
3. Excluded: every integer written as a run of decimal digits in the Papers repo's `lab/journal.jsonl` at Papers commit 7a838e6 (every journaled run of P1, P2 and P3, M7d's job m2l included), and in one-port's `design/status.md`, `design/status-m6.md`, `design/status-m6b.md` and `design/status-m7a.md` at the commit that adds this entry, so that every seed the journal or those files name is excluded; the development seeds named as used: 861 and 20261003 (W, M6b), 7701 to 7714, 7801 and 7802 (M7c), 7951 to 7964 (M7c's follow-up), 8101 and 8102 (M7d's job m2l); and a value already kept for an earlier name, so that the 14 values differ.
4. The output: the seeds file `design/seeds.json`, the 14 names in that order with their kept values, as the runners and `analysis/` read it; the draw's log, every call and the sha256 of each file of item 3; both kept on L under `~/lab/p3/m7d/seeds/` with their sha256. The values and the seeds file's sha256 are appended to this entry after the draw, the sha256 on one line with the word "seed" (`bench/run/freeze_guard.py`).
5. Use. No run uses these seeds before CODE_FREEZE: a frozen runner reads the seeds file only in a frozen run, which needs the CODE_FREEZE entry (`bench/run/freeze_guard.py`), and every development run takes a development seed of its own, which item 3 keeps apart from these. The seeds file is never changed after this entry.

The draw, on L on 2026-10-04 at 05:29:12 +0300 (python 3.14.7; `draw_seeds.py`, sha256 4d0e205f4c361e029428e3faf950de2e7597d21e4264e045af6f97af30ed82aa; its log `draw.log`, sha256 84412a89fb561959b55285af0b4fbd8fe026cfa2972174b503265f2c2f38e1a5). The files of item 3, by sha256: Papers `lab/journal.jsonl` at 7a838e6 51e5a6ea7d315b118d8f2d20711f7332e5e33b73bf9b7655eb4f1ec5f9961b6d; one-port at 45d8b03, `design/status.md` e77bcdceef83106b380b824a6ccbc8c382dc26a3858fbb3c85ff6bfd417146b2, `design/status-m6.md` c0e420019812fc769e9465c5dc81f07f2f9f3eb50eacc0faabd660e11d78fd22, `design/status-m6b.md` a5d55e29292137e9c76f492901195d5595cb2305a3c8065c8e448d10109e0393, `design/status-m7a.md` 33bccac0802f242fb91d5416aa5ab23b32a4a35a6ee9bd899f9e672480c0b6b2; 5,634 integers excluded in all. Each of the 14 first calls was kept; no call was discarded. The values:

6. `SEED_ORDER_C_L` = 262543012, `SEED_ORDER_C_W` = 44383881, `SEED_ORDER_B_L` = 3326063620, `SEED_ORDER_M_L` = 1245255044, `SEED_ORDER_M_W` = 1419530141, `SEED_ORDER_S_L` = 3488492621, `SEED_ORDER_S_W` = 904573355, `SEED_BOOT_C` = 788779428, `SEED_BOOT_B` = 1347884663, `SEED_BOOT_M` = 2580188195, `SEED_BOOT_S` = 1489743696, `SEED_PILOT_L` = 1546876941, `SEED_PILOT_W` = 2884574437, `SEED_SIM` = 2911323892.
7. The seeds file `design/seeds.json` has sha256 3a2dd43623aa96190b5b3fac737d96af5a8fabed9853a82233c3a3c9f4c35b3e; every frozen run and `analysis/` read the seeds from this file.

### 2026-10-04: W before the code freeze

M6b, M6c and M6d (`design/status-m6b.md`) settled W's items before the code freeze. Each item is labelled a reading of the text above, a design choice, or Alex's decision; nothing above this log is edited, no rule is added, and no value of section 9 is set here (the code freeze's entry names them). No hard case of Appendix A changes outcome by them. This entry was written and committed before any row of M6d's development job waa3 was read. Every figure below is development data named by its job, or a reading of a record named in the last paragraph, not a result.

1. Alex's decision (2026-10-04). On W, WL1's churn h2c and churn MQTT cells (c = 10 and 12 of 6.1) measure the generator, not the server, and are reported as generator-bound on W, with this evidence, outside the confirmatory cost family. The evidence (M6c, waa2's binaries): both protocols' clients close first (WL1), so each connection leaves a TIME-WAIT socket that holds a client port; Windows' bind and closesocket in opgen cost more as the host's TIME-WAIT sockets grow (MQTT churn, 8 threads: bind 237 us and closesocket 251 us per connection at 1 to 10,198 TIME-WAIT sockets, 1,353 and 1,204 us at 28,900 to 32,018, while the rate fell from 9,850 to 2,834 connections per second), and the kernel serializes these calls across opgen's threads; the server was 33% to 54% busy in waa2's churn h2c windows and 30% to 46% in churn MQTT, against 94% to 98% in churn HTTP/1.1, whose server closes first. Section 7's generator rule does not catch it, since opgen's threads wait in the kernel (45.5% and 45.8% busy in M6c's diag1). The fixes that work change frozen text: a close by reset changes what the server reads (WL1's close), and source ports chosen by opgen depart from section 2.4. What the decision does to the family: the cost family is one family over L and W (5.1, "Holm over the m_C resolved cells of C1 to C3 together"; 4.6 step 6), so the two cells leave it at the pilot entry as a cell that is not resolved leaves it (4.6 step 7), m_C is at most 34, and Holm's thresholds are α/(m_C - j + 1) over the cells that stay, none of them smaller than with the two cells in. 4.6 step 2's pass level α/36 is frozen and is not changed, so the sizing of R does not use the smaller family. 4.6 step 7's joint power is not reported for h2c and MQTT on W, since their C1 cell is not resolved. The two cells still run: every cost cell runs its sessions in the A/A pilot (4.6 step 1), and WL2 takes λ for the C3 cells of h2c and MQTT on W from those C1 sessions. Whether they also run at R_C after the pilot entry, as 4.6 step 7 runs a cell that is not resolved, is open for the coordinator. Open h2c and open MQTT on W (c = 34 and 36) stay in the family under the frozen rate rule; their λ is RATE_FRAC times a generator-bound churn median, so on W they run at a smaller share of the server's capacity than the C3 cell of HTTP/1.1 (waa2, half the churn median: 2,414 per second for h2c and 2,370 for MQTT, against 8,445 for HTTP/1.1), and the paper says so beside them.
2. Alex's decision (2026-10-04). M2's TLS cells, on epoll and on io_uring, are not run, and M2 is tested on HTTP/1.1 only. In job m2l (M7d) every relay window of both TLS cells was invalid by section 7's backend rule, with the backend in a `SO_REUSEPORT` group and with the shared listener alike: the backend that terminates TLS is the relay arm's limit in closed loop (the entry "The pre-freeze items on L (M7d)", item 1; job e2e1 of M7c, the TLS cell on io_uring, likewise). So 9.3's rule as read (the entry "Readings fixed during engineering (M7c)", item 5) computes no rate for either cell, and item 6 of the entry "M7c's open items, before the code freeze" applies as it already prescribes: a cell without a rate has no valid session, enters Holm with p = 1, m_M stays 20, the paper reports it as "a difference was not shown" with the reason, and the M runner starts none of its windows and lists it as not run.
3. Reading. W's frequency rule takes section 9.1's fallback. Section 9.1 asks for "a CPU frequency counter tested against a known load" and says "If no counter passes, W windows are validated without the frequency rule and the paper says so". The counter of design/w-procedure.md section 4 (`% Processor Performance` of the server's CPU, `Actual Frequency` beside it) did not pass. The boost test (2026-10-03 16:46, W not quiet, mean idle 92.6%): the counter's load mean under Alex's plan (boost Aggressive) differed from the lab plan's (boost off) by -5.2e-7 of it, where the rule asks for more than 2%, and a fixed loop ran 10.73 and 10.52 million iterations per second. The retest with a 50% cap (Alex's addition of 2026-10-03, w-procedure.md section 4 as revised; 2026-10-04 00:13:56, W quiet by its check, mean idle 98.5%): the counter's load mean under the cap plan differed from the lab plan's by 3.7e-7, `Actual Frequency` read 3,949.97 MHz under both, and the loop's work rate changed by -4.2e-5 (10,944,672.7 and 10,944,208.1 iterations per second). By the revision's own reading that test is inconclusive: neither the counter nor the work moved, so the cap did not move W's clock. Under three plans (the lab plan, Alex's plan and the cap plan) neither moved. No counter passed, so W's windows are validated without the frequency rule, the counter stays recorded in every row (the runner's `FREQ_RULE` off), and the paper says so. Why W's clock does not change with these plans is not established: the firmware's settings were not read, and Alex does not know them.
4. Design choice, made before any confirmatory data. W's WL4 value is the server's cycles. WL4 asks for "Server CPU time over the window per exchange". On W the server's CPU time is the change of `QueryProcessCycleTime` (the cycles of the process's threads, user and kernel) between opgen's two markers, per exchange (in open loop, per exchange due in the window that completed, as M3's reading 7 has it on L); `GetProcessTimes`' user plus kernel time is recorded beside it and decides nothing. This takes the place of M6b's reading of WL4 on W (`GetProcessTimes`, `design/status-m6b.md`), which was never logged. Why: `GetProcessTimes` moves in whole clock ticks of 15.625 ms charged to the thread that runs at each tick, so at a low server load its change over a window is a sample, not a sum. In M6c all 288 `server_cpu_s` values of job waa2 were whole multiples of the tick; `GetProcessTimes` over the cycles (both as seconds, at 3.95e9 cycles per second) read 0.841 to 1.168 in 18 open-loop runs, with the server about 20% busy, and 0.993 to 1.007 in 24 keep-alive runs, with the server busy; per exchange, open h2c's `GetProcessTimes` value spread 1.282 (max over min; CV 7.0%) against 1.138 (CV 4.0%) in cycles, and open MQTT's 1.333 (CV 11.2%) against 1.204 (CV 5.6%). Most of the spread of the tick-based value is the sampling; the rest, a CV of 4% to 6% in cycles, is real. A ratio of two arms (section 10's CPU per connection or request) is taken on cycles directly and needs no conversion. Where the paper gives an absolute value, a count of cycles becomes time through the session's cycle rate: `QueryProcessCycleTime`'s cycles per second of wall time (`QueryPerformanceCounter`) over a busy loop of 1 s pinned to the server's CPU, read at the start of each session and recorded in its fingerprint (`wsys.cycle_rate`, one-port 4af5714; the row's `cycles_us_per_exchange`). The rate is measured, not taken from a nominal clock, because the text gives no value for it; on W it read 3.93e9 per second of wall time (M6d, a development check) and 3.94e9 to 3.95e9 per second of busy process time (M6c). The paper names the counter and the conversion beside W's WL4 values. L's WL4 is unchanged.
5. Design choice: no discarded window. No W job or session starts with a discarded window. The evidence (M6c, job waa2): the job's first three windows (keep-alive h2c, its first session, started 00:25:19 to 00:25:31) ran at 0.917 to 0.935 of the cell's median requests per second, with the same operations per request as the rest; the fourth (00:25:38) ran at 0.987, inside the other 20 windows' 0.984 to 1.030. In every other session of the 12 cells the session's first window was not slower: in the cells the server bounds (churn HTTP/1.1 and TLS, the four keep-alive cells, open HTTP/1.1 and TLS), the first window's median relative to its cell's median was 0.996 to 1.014 (range 0.961 to 1.030). So this was a slow start of the job, seen once, of unknown cause, not a slow start of each session, and a discarded window per session removes nothing that was seen. One discarded window per job would not have covered it either, since it lasted three windows (about 19 s), and a longer warm-up would be fitted to one occurrence. Its direction: in a session X Y Y X a slow start lowers X's first window and both Y windows, which moves the session's ratio away from 1 (waa2's first session of keep-alive h2c, B over A 0.965); in the cost family such a session counts against equivalence, and in the A/A pilot it widens the spread and so raises R, so it never favours a claim. Each W row keeps its window's start time, so a slow start stays visible; M6d's development job waa3 records whether it recurs.
6. Readings, from the paper draft (`paper/sec-threats.tex`, the note for Alex on M6b's readings), each a reading of the text above. (a) Section 2.4's "Every source address is bound with `IP_BIND_ADDRESS_NO_PORT`" names a Linux option that Windows does not have. On W, opgen sets `SO_REUSE_UNICASTPORT` before the explicit bind of each source address (`bench/gen/worker_win.cpp`; pinned by `gen.pin_reuse_unicastport`), the option that Windows' headers describe as deferring ephemeral port allocation for outbound connections (ws2def.h) and that its SOL_SOCKET options name for explicitly bound connects such as ConnectEx. What section 2.4 asks of a window, the next unused block of `K_SRC` addresses of 127.0.0.0/8, never reused within 60 s, holds on W as written. Two facts go with it, and the paper states them: as read on W, `getsockname` names a port right after the bind with or without the option (M6b), so the port is not shown to be chosen at connect; and opgen's churn rate did not change without the option (M6c, diag3: MQTT 4,083 and h2c 4,654 connections per second). Why it follows: the text names no Windows option, and section 2.4's point is that a block of source addresses, each with its own ports, serves a window; this is Windows' option for an explicitly bound connect. (b) Section 7's rule "in the cost family, M1, M2 and B3, `TcpExtListenOverflows` or `TcpExtListenDrops` (nstat) changed during the window" cannot be computed on W, which has no counter of listen overflows or drops (`GetTcpStatisticsEx` counts failed attempts and resets, not overflows). Section 7 sends W to "the rules of W's procedure that can be computed there", so W's windows are judged without it. A SYN that W refuses or drops shows as a connect that fails (W reports a refusal after about 2 s, and opgen counts a connect not complete at its 1 s timeout as failed), which section 7's "any connect failed" makes invalid; each row records the change of W's TCP statistics. The rules W does compute are those of M6b's reading 1 (`design/status-m6b.md`): every rule of section 7 that it does not tie to a host; the error share above 0.1% and the generator's CPUs above 90% in a saturation cell, as W reads them (opgen's report, and the busy share of CPUs 2 to 9 from Windows' performance counters); the frequency rule only with a counter that passed (item 3: none did); and W's procedure's own rule, the lab plan active at each window's start and end. (c) The server closes a connection on reading MQTT's DISCONNECT, and once nghttp2 is done after an h2c GOAWAY with no stream left, without waiting for the client's FIN (M6c), on both platforms and in both modes, since the handlers are shared. The frozen text allows it: WL1's table has the client close first for h2c and MQTT, which describes the generator, whose exchange closes right after its last write; section 2.1's handlers are "h2 through nghttp2" and MQTT with "DISCONNECT"; neither says when the server closes after the client's last message. On W the client's FIN had not arrived in 67% to 91% of open-loop connections, which leaves a TIME-WAIT socket on both ends and one retransmitted FIN, outside the exchange; a diagnostic server that waited for the FIN removed those, added a receive per connection and raised open h2c's server CPU per connection, and was not adopted (M6c).
7. Reading, with a decision left open. Section 10's "2 server cores: C1 HTTP/1.1 on each backend (3 cells)" holds one IOCP cell, and the server refuses more than one worker on IOCP (`--workers` above 1 exits 3, `not_served`), while section 2.1 has "One worker thread per server core". M6a (`design/status.md`, "More than one worker on IOCP is not built") gave three options: (a) one completion port shared by the workers, each connection pinned to the worker that accepted it and its completions routed there; (b) a port per worker, the worker that takes an AcceptEx completion handing the socket to a worker's port, a change of the proposal's accept model (I4) that would be logged; (c) leave the IOCP 2-core cell out and say why. The reading: the cell is secondary (section 10: "not in any Holm family, deciding nothing"), so a cell that is not run changes no claim, as with section 10's resumption cells (the entry "M7c's open items, before the code freeze", item 5); (a) and (b) are code, so they are possible only before the code freeze (section 8 step 3); and section 4.1 gives W's placement for one server CPU only, so a 2-core cell on W would also need a placement, a design choice. Nothing was built in M6d. Whether to build (a) or (b) before the code freeze or to report the cell as not run, with the reason, is open for the coordinator.
8. Alex's decision (2026-10-03): W's procedure is approved, as section 9.1 requires ("W's procedure: power plan, boost policy, timer resolution, and a CPU frequency counter tested against a known load; approved by Alex"). Power plan and boost policy: for each session the harness switches, without administrator rights, to the lab plan "oneport W windows" (277bfd76-c26d-4cac-b253-a8500e6728d8: High performance with AC boost mode 0, minimum and maximum processor state 100%, core parking minimum cores 100%), reads it back, and at the end sets his plan "ChrisTitus - Ultimate Power Plan" (00acab9f-6807-4927-af55-c72a4c589dad) back and reads it back, also on failure (`bench/run/wpower.py`; design/w-procedure.md section 2). Timer resolution: Windows' default; neither the server nor opgen calls `timeBeginPeriod`, and each window records the resolution, read only. The frequency counter: tested against a known load (item 3); it did not pass, and section 9.1's fallback applies. Alex pauses Windows Update and adds the Defender exclusion for `C:\Users\alext\lab` before W sessions; the harness reads Defender's and Windows Update's state per session and never changes them, and its quiet check refuses a session on a busy W (w-procedure.md section 5).

The records named above, in `C:\Users\alext\lab\p3\`, by sha256: `m6b\freq\freq-20261003T164640.json` 206283e95be2408970052d16466dcbff12c0c8ad55c4ca66bf450a3c8abf77de; `m6b\freq\freq-20261004T001356.json` 97b69a4cae37537531652b581eca9c95e9729680575464d619699f69e2079738; `w-aa\waa2\windows.jsonl` 20f3f514306511f7c6946102e193babe7dcc4a98d7839f299a320022b48549b2; `w-aa\waa2\summary.json` f0461293c57f73d15af889d1dc9b50e58bffa91a159f214c7262505432b503e3. M6c's diagnostic records are listed with their sha256 in `design/status-m6b.md`. This entry names no file by its sha256 on a line that holds a word the frozen runners look for, so it is none of the entries they find by a word and a sha256.

### 2026-10-04: ANALYSIS_COMMIT moved (M7e), before the code freeze

Section 8 step 2 commits the analysis code that runs 4.6, with its tests, as `ANALYSIS_COMMIT`; the entry "ANALYSIS_COMMIT, before the code freeze" named 7364fbb. M7e (`design/status.md`, "M7e, 2026-10-04") changed `analysis/` for two items of the entry "W before the code freeze", before any confirmatory data: no pilot session has run, and no frozen run can start before CODE_FREEZE. Nothing above this log is edited, and no rule is added. Every figure below is a test count, not a result.

1. `ANALYSIS_COMMIT` = 9de26d614c85b606fb5169ed16528b7189a87ac4, one-port's last commit that changes `analysis/`. It takes the place of 7364fbbbf356e22bb0d6a74b0b9bc29b62c3534b. The change is one-port 141e516; 9de26d6 gives `analysis/cells.py` its LF line endings back, which 141e516 had written as CRLF, and changes no other byte.
2. Why, first: W's WL4. Item 4 of the entry "W before the code freeze" makes W's WL4 value the server's cycles per exchange, with `GetProcessTimes`' tick-based value recorded beside it, deciding nothing. At 7364fbb `analysis/rows.py` read every window's CPU per exchange from the field `cpu_us_per_exchange`, which W's rows fill from `GetProcessTimes`; so section 10's CPU intervals of W's cost cells and of M1's IOCP cells would have been taken on the value item 4 sets aside. Now `rows.window_value` reads WL4 by host (`cells.CPU_FIELD`): `cycles_per_exchange` for a row whose backend is IOCP or whose host is W, `cpu_us_per_exchange` on L as before; a W row without cycles has no CPU value, never the tick-based one. A ratio of two arms is taken on the cycles, as item 4 says.
3. Why, second: W's churn h2c and churn MQTT. Item 1 of the same entry puts them outside the confirmatory cost family, leaving it "as a cell that is not resolved leaves it (4.6 step 7)". At 7364fbb `analysis/pilot.py` resolved every cell of 6.1's list (in its code) that had P valid sessions and a power of at least 0.80 at 31; the two cells run in the pilot (WL2 takes λ for the C3 cells of h2c and MQTT on W from their C1 sessions), so they could have been resolved and could have set R_C and m_C. Now `pilot.decide` never resolves a cell of `cells.COST_OUTSIDE_FAMILY`, which holds these two with the reason; it still simulates them, since 9.2 records Power_c(R) for every cost cell, and the pilot entry's output names them. `analyse.check_pilot` refuses a pilot entry that resolves one, and their verdict is the reason, not "not resolved at R <= 32". The pass level α/36 of 4.6 step 2 is unchanged, as item 1 says.
4. The tests at 9de26d6, from a fresh clone of the lab remote on L, in the venv with numpy 2.5.0 and Python 3.14.7 (lab job ana2, `~/lab/p3/m7e/ana_job.sh`): 73 passed, 1 skipped; the skipped Appendix A test alone with `ONEPORT_SLOW=1`: 2 passed. Lab job ana1 at 141e516 gave the same counts. Their logs are listed by sha256 in `design/status.md`, M7e. Three of the 73 are new (a W row's CPU is its cycles and never its ticks; the two cells are never resolved and leave R_C unchanged; a pilot entry that resolves one is refused), and three earlier tests now check the change too (the whole synthetic pilot, the cost cells' verdicts, the CPU intervals of W's cells).
5. W's runners write what this code reads: every W window's row carries `cycles_per_exchange` beside `cpu_us_per_exchange` (`bench/run/wwindow.py`, since one-port 4af5714), with the host W and the backend IOCP; W's cost runner runs neither of the two cells (the next entry, item 2), and W's pilot runs both.

### 2026-10-04: The job's warm-up and W's runners (M7e), before the code freeze

M7e (`design/status.md`, "M7e, 2026-10-04") settled the items before W's frozen-row runners: the job's slow start on W, the two decisions the entry "W before the code freeze" left open (its items 1 and 7), and the choices W's runners make. Each item is labelled a design choice, the coordinator's decision, a reading of the text above, or a record. Nothing above this log is edited, no rule is added, and no value of section 9 is set here. No hard case of Appendix A changes outcome by them. Every runner on the session engine applies item 1, and W's runners apply items 2 to 5; a frozen run of each refuses to start unless the revision log holds this entry's heading (`bench/run/freeze_guard.py`, `M7E_ITEMS`), and W's also the heading "W before the code freeze". This entry names no file by its sha256 on a line that holds a word the frozen runners look for. Every figure below is development data named by its job, not a result.

1. Design choice, made before any confirmatory data: a job's warm-up phase. It supersedes item 5 of the entry "W before the code freeze" ("no discarded window"), which rested on one slow start. The evidence, from the rows of W's development jobs waa2 and waa3 (read only; their files are named by sha256 in that entry and in `design/status-m6b.md`, M6d), each window's metric against its cell's median over the job:
   - waa2 (seed 861): the job's first three windows, keep-alive h2c (session s02, positions 0 to 2, started 00:25:19, 00:25:25 and 00:25:31), ran at 0.931, 0.917 and 0.935 of the cell's median requests per second; its fourth, the same session's position 3 (00:25:38), at 0.987, inside the range of the cell's later windows (0.984 to 1.030); the next window, the first of another cell (churn TLS, 00:25:48), at 0.999 of its own cell's median. So the slow start ended inside the job's first session, 18.5 s after it began (from the first window's warm-up start to the end of the third window's measured period, by opgen's clock in the rows).
   - waa3 (seed 7901): the job's first five windows, keep-alive h2c (session s04, positions 0 to 3, then session s06, position 0; started 12:04:27 to 12:04:58), ran at 0.940, 0.936, 0.918, 0.923 and 0.688 of the cell's median, the server's CPU busy throughout, with 1.063 to 1.175 of the cell's median cycles per request; the next window (s06, position 1, 12:05:05) at 1.045, and the cell's later windows at 0.989 to 1.047. So the slow start crossed a session boundary, within one cell, and lasted 37.7 s (from the first window's warm-up start to the end of the fifth window's measured period).
   - In both jobs the same cell's later sessions were not slow, so the slowness belonged to the job's start, not to the cell or to a session: it is job-level. In both the first cell was keep-alive h2c and no other cell ran inside the slow span, so whether it crosses a cell boundary was not observed; it is not refuted either. Its cause is not established.
   The phase. Before the first session a job runs, the shared session engine (`bench/run/sessions.py`) runs discarded windows of that session's cell, its arms in the session's order X then Y, alternating, back to back, each the runner's own window function, until `JOB_WARMUP_S` = 80 s of wall time have passed since the phase began; the window running then completes, so the phase lasts at least 80 s and at most one window more. The rule: at least twice the longest slow start seen (37.7 s, waa3), rounded up to a whole 10 s. Nothing from the phase is recorded as a window: no row is written to the runner's rows and no metric is kept; the phase's own record (`warmup-<runner>-<job>.json`) holds its start and end, the cell, the arms, each window's start, length and whether it was a driver fault, and the phase's own fingerprint, read at its start, so that the first session's fingerprint is read after the phase, as every later one is. The seeded order, R and the reruns are untouched: the phase draws nothing. It passes the same check as a session's window, so an arm that would be a development stub never runs in it: a development cost job warms up on its dedicated arm alone, and a frozen one, after the pilot entry, on both arms, which section 8 step 7 allows; no one-port window runs against dedicated timing before the pilot entry, and no dedicated window against a competitor. Two driver faults in a row end the phase early, and its record says so; a job that resumes with nothing left to run runs no phase. Every engine runner takes it, on L too, by symmetry: M3's A/A jobs on L showed no slow start. Windows run outside the engine are not covered: `b3_run.py`'s K_BASE windows, the pilot's timer and split parts, and the hard cases.
2. The coordinator's decision, answering what item 1 of the entry "W before the code freeze" left open: W's churn h2c and churn MQTT (c = 10 and 12) run in the dedicated-only A/A pilot only, so that WL2 has their medians for the open-loop rates of the C3 cells of h2c and MQTT on W, and not in the confirmatory cost runs. W's cost runner (`bench/run/wcost_run.py`) lists them as not run, with the reason; the pilot entry never resolves them (the entry "ANALYSIS_COMMIT moved (M7e), before the code freeze", item 3). The paper's evidence that they are generator-bound comes from the pilot's rows: each W window's row holds the server's CPU busy (`server_cores_busy`, its CPU between the window's markers), the generator's CPUs busy (`gen_cpus_busy_pct`) and opgen's own CPU share (`opgen.cpu.pct`), and since M7e the same as named fields with the server process's own share from its cycles (`cpu_shares`).
3. The coordinator's decision, answering item 7 of the entry "W before the code freeze": section 10's 2-core cell on IOCP ("2 server cores: C1 HTTP/1.1 on each backend") is not run in P3, and the paper reports it as not run, with the reason. The server serves one IOCP worker (`--workers` above 1 exits 3); more than one worker on IOCP, by option (a) or (b) of M6a, is a new threading model days before the code freeze; and it belongs to the paper on the portable I/O core. The cell is secondary and decides nothing (section 10), so no claim changes, as with the resumption cells (the entry "M7c's open items, before the code freeze", item 5). Both section 10 runners list it as not run.
4. Design choice: the mixed-protocol cell's placement on W. Section 4.1 gives W's generators the cores between core 0 and the server's, CPUs 2 to 9, and places no background. The cell's opgen runs on CPUs 2 to 5 (cores 1 and 2), the TLS keep-alive background's opgen on CPUs 6 and 7 (core 3), and the MQTT keep-alive background's opgen with the silent connections' holder on CPUs 8 and 9 (core 4). Why: as M7c's placement on L (the entry "M7c's open items, before the code freeze", item 7), the cell's generator keeps the larger share and shares no CPU with a background, and each background has a core of its own; on W the generator's range holds 8 CPUs, not L's 12. Section 7's generator rule reads the cell's generator's CPUs (item 8 of the same entry). The background is the same as on L (items 1 and 2 of that entry): WL3 with 64 connections for TLS and for MQTT, and 64 silent connections, on the dedicated HTTP/1.1 port in dedicated mode.
5. Reading, with a design choice: section 10's IOCP forms (2 cells), "On IOCP, on a listener without a fallback, against the default form, which is AcceptEx with no receive buffer (`dwReceiveDataLength` = 0) followed by the receive form rule E chose: AcceptEx with a receive buffer; and the receive form rule E did not choose ..., after the same AcceptEx". Both arms run the server in one-port mode, in-process, with rule E's detection mode on IOCP: "a listener without a fallback" is a one-port listener (the Words: dedicated mode has no detection, so no fallback), and the M6a entry, item 6, applies AcceptEx with a buffer to one-port listeners only. Arm A is the form named, arm B the default form; the receive form rule E did not choose is the posted buffer, since rule E's only candidate is the zero-byte form (the coordinator's decision on M6a's reading 7). Section 10 names no workload; the design choice is C1's HTTP/1.1 churn (WL1), whose every connection goes through AcceptEx and the first receive, the path the two forms change; the metric is its connections per second. Both arms are one-port mode, so no window times one-port against dedicated mode.
6. Record: what W's frozen runners need beyond L's, built in M7e. `opcase` is built on Windows, its subcommands `case` and `hold` (`open` and `probe-reset` serve B3, which runs on L), so that W's pilot can run its timer and split parts and W's hard-case runner B1 and B2 on IOCP with the same case generator as L (section 2.4); W's records cover it (`bench/build_inputs.py`, `TARGETS["W"]` and `BINARIES["W"]`). The holder runs on Winsock with the same policy as on Linux, binding each source address with `SO_REUSE_UNICASTPORT` (the entry "W before the code freeze", item 6 (a)), and stops when its event `Local\oneport-stop-<pid>` is set, as the server does; W's suite gains `gen.hold.IOCP` and checks the program in `gen.binaries`. The hard cases' judge applies replay's B2(d) bound to a connection on IOCP that an undecided peek switched to replay, as the suite's `check_run` does (the M6a entry, item 2). A frozen W run starts only inside a W lab job that passed W's quiet check (`bench/run/wjob.py`: the lock, the lab plan set and Alex's plan set back), and only with every port it binds outside W's excluded port ranges.

### 2026-10-05: W's quiet gate lowered (Alex's decision), before the code freeze

Alex decided on 2026-10-05 at 00:50, in his words as the coordinator relayed them: "At this point, just lower the threshold". The decision is on W's procedure (`design/w-procedure.md` section 5, which section 9.1 has Alex approve; the entry "W before the code freeze", item 8), and it was made before any pilot data: no pilot session has run, and no frozen run can start before CODE_FREEZE. Nothing above this log is edited, no rule of the text above changes, and no value of section 9 is set here. No hard case of Appendix A changes outcome by it.

1. Alex's decision. The quiet check that a W lab job must pass before it starts (`bench/run/wjob.py`, `wsys.quiet_check`; w-procedure.md section 5) now asks for a mean CPU idle of at least 90% over its 10 s, where it asked P1's 95%; at least 90% idle on each logical CPU a window uses (2 to 10), where it asked 95%; and no process above 10% of one logical CPU, where it asked 5% (`bench/run/wsys.py`: `QUIET_TOTAL_IDLE_MIN`, `QUIET_CPU_IDLE_MIN`, `QUIET_PROCESS_MAX`). The test `run.test_wrunner` (`quiet_rules`) pins the new values and their bounds.
2. The reason, as Alex gave it through the coordinator: at night W runs the display compositor, Defender, the System process and background programs he keeps running, such as Razer's software for his peripherals' lighting, and the check refused 83 job starts from the evening of 2026-10-04 to that night. Record, from the preflight files of W's chain of checks (`design/status.md`, "M7 freeze night"): 83 refused starts from 2026-10-04 17:33 to 2026-10-05 00:46; the first 78, up to 00:20, while the League client ran; the last five, from 00:25 to 00:46, after it had closed, with a mean idle of 83.9% to 98.1% over the check, CPU 10 at 71.9% to 94.8% idle in each of them, and among the processes above 5% of one CPU the display compositor `dwm` (9.5% to 15.3%, in four) and `System` (6.2% to 21.7%, in four), and in one each Defender's `MsMpEng` (13.3%) and `msedgewebview2` (17.3%).
3. What does not change. The check gates a job's start, nothing else. Every rule by which a W window is valid or invalid is unchanged (section 7 as W computes it, the entry "W before the code freeze", item 6 (b)), among them the generator rule and the lab plan at each window's start and end; so is the per-window CPU sampler (w-procedure.md sections 4 and 5), whose readings every W row records (`server_cores_busy`, `gen_cpus_busy_pct`, `opgen.cpu.pct`, `cpu_shares`). So a busier W shows in those recorded shares and in the A/A pilot's spread, which sets R_C (4.6). A job that does not pass the check at the new bounds is still refused, and a frozen W run still starts only inside a W lab job that passed it (the entry "The job's warm-up and W's runners (M7e)", item 6). `--allow-noisy`, which runs a job as a functional check and records it as one, is not used for the pilot or for any measurement.
4. Record: the change is Python only, in `bench/run/wsys.py` and its test; it changes no compiled input and no harness input, so no inputs hash of section 11's gate moves. It is in the commit that CODE_FREEZE names, or before it, as section 8 step 3 freezes "the tests" with the code.

### 2026-10-05: The code freeze

Section 8 step 3: one commit of the server, the generators, the holder, the harnesses, the pins and the tests, with green sanitizer records (section 11) and a passing test suite, and the values engineering set (section 9.1). `design/status.md`, "M7 freeze night", holds the evidence named here. Nothing above this log is edited, and no rule is added. No hard case of Appendix A changes outcome by it. Every figure below is a test count, a reading of a file named by its sha256, or a record of what was read; none is a result.

1. The commit:
   CODE_FREEZE = ff2679cc89d23e08a817308c9aeba7901e056fef
   From the commit the entry "The job's warm-up and W's runners (M7e)" describes (ed15f97), these commits changed what this one freezes: 7a4063c (a test: `run.test_wrunner`'s cycle-rate check on the server's CPU); 1fca359 (W's job-start quiet gate, the entry "W's quiet gate lowered (Alex's decision), before the code freeze"; the change is Python only); 20c01b9 (a test: on IOCP the suite waits 250 ms after a server's start before its first client; and `bench/coverage.json`'s Windows gap, item 6); ddd9d6a (a test: on Windows the generator tests check the form of the workers' CPU time, a sample of the clock tick over their 100 ms window); ff2679c (`bench/records_job_w.ps1`: the W gate step's Python steps run inside cmd.exe). The three test changes change the suite target's inputs hash and no measured binary's input; 1fca359 and ff2679c change no compiled input. From CODE_FREEZE on, no commit changes `bench`, `tests` or `CMakeLists.txt` (`bench/run/freeze_guard.py` checks it before every frozen run).
2. The suite at the freeze. On L, the four builds at CODE_FREEZE (lab job frz2, 2026-10-05 01:23 to 01:28 +0300, from a fresh clone of the lab remote): Debug, ASan with UBSan, TSan and MSan each built with 0 warnings and passed 399 of 399 tests with 0 lines of the shared report pattern. On W, Debug and MSVC ASan at ddd9d6a, whose compiled inputs and tests equal CODE_FREEZE's (ff2679c changes only `bench/records_job_w.ps1`, which no test runs): 165 of 165 in each, 0 warnings, 0 report lines; and the suite of W's ASan record at CODE_FREEZE (item 4): 165 of 165, 0 report lines. Python's tests run in every one of these suites (`run.test_wrunner` with the new gate's values among them).
3. Section 9.1's values.
   - The seeds: the entry "The seeds of section 4.7 (M7d), before the code freeze"; `design/seeds.json` unchanged.
   - `ANALYSIS_COMMIT` = 9de26d614c85b606fb5169ed16528b7189a87ac4 (the entry "ANALYSIS_COMMIT moved (M7e), before the code freeze"); `analysis/` is the same at CODE_FREEZE (`git diff` empty).
   - `K_SRC` = 16 (the M3 entry, item 9). Its rule holds on L (the entry "The pre-freeze items on L (M7d)", item 8) and on W: in the 22 row files written on W since 2026-10-03 08:36:23 +0300, 2,468 rows, every field that records a failed connect is 0 and no invalid reason names one (`ksrc_scan_w.py`, log sha256 bffb73150c8040281f92d6dc9c99c621bad12b746c98cc534d2a61da2a896bbb).
   - `N_ACCEPTEX` = 64; `RELAY_BUF` = 4096 bytes per direction, reported beside each proxy's default in the paper; `N_BG_TLS` = `N_BG_MQTT` = `N_BG_SILENT` = 64; ℓ = 206 (`tests/fixtures/tls/clienthello.hex` unchanged, sha256 b553d6d76d8be29b2054ec762f2c01546ff92f1610214874048e15ee5ef222b2). As the entry "The pre-freeze items on L (M7d)", item 8, read them.
   - The skb caches on L, read again as root, read only, on 2026-10-05 at 00:55:22 +0300 (`slab_read.sh` of M7d, log sha256 95917c5e2dcc1710aecbabb8a921c668a0364e1957edc82fa9df857ade45c5b5): kernel 7.2.6-arch2-1 without `slab_nomerge`; `/proc/slabinfo` exists; "skbuff_head_cache" and "skbuff_small_head" are caches of their own, listed under their own names; "skbuff_fclone_cache" links to `:0000512`, whose co-tenants are "pool_workqueue" and "sgpool-16", listed as "pool_workqueue"; page size 4096 bytes. WL7's reading, unchanged, so WL7's rule for merged caches applies as frozen.
   - The pins, read again on the day of the freeze before this entry (2026-10-05 00:54:18 and 00:54:28 +0300, M7d's `pins_read.sh` and `pins_read2.sh`; logs sha256 748a822d754aa95b870ba3f8cab75f681278e5da62b4db6fe1ba80545089d9cc and 50a028440dd413d2dfd12e5eb24377aebf8b0a356ee7053968d8643a0d915469): no pin changes. Temurin 25's latest GA build is still jdk-25.0.4.1+1 (Adoptium's most_recent_lts 25), with the pinned archive's sha256; OpenSSL 3.5.9 is still the latest 3.5 release; nghttp2 v1.70.0, nginx 1.30.5 (stable), HAProxy 3.4.6, Envoy 1.39.2, xcaddy 0.4.7, caddy-l4 v0.1.2 at 42db5690dea199f930a6f08005fe2e4aab10dcc9 (also its default branch's head), sslh v2.3.1, Netty 4.2.18.Final, Jetty 12.1.13, cmux v0.1.5 and hyper-util 0.1.21 are each still the latest release of the pinned line; Caddy v2.11.7 and Rust 1.99.0 are what the readings (a) and (b) of the entry "The pre-freeze items on L (M7d)", item 6, cover. `bench/cmake/pins.cmake` has sha256 2d49d03bacf8518c1647734889b84c67ffe9db001d954d9f1d52e1770809e15e. Netty's allocators, read again on the frozen Release build (`probe.py --system netty --kind b3`, 01:51 +0300; log sha256 e74c667b6d6de481e36ed3fe98178b0eac4cd4aead02cfcddc3ef248df070d26): `io.netty.buffer.AdaptiveByteBufAllocator` and `io.netty.channel.AdaptiveRecvByteBufAllocator`, as M4b-2's reading 11 found.
   - W's procedure: approved by Alex (the entry "W before the code freeze", item 8), with its job-start gate as the entry "W's quiet gate lowered (Alex's decision), before the code freeze" sets it.
4. The records, every one green, each made at CODE_FREEZE from a fresh clone, in the Papers repo's `lab/sanitizer-records/`:
   - L (lab job frz2, `bench/records_job.sh`, clang 22.1.8; logs under `~/lab/records-logs/<record>/`, each archive's sha256 beside it): `oneport-ff2679cc8-L-asan` (ASan with UBSan; 1ff4d7a4fe650ce80f945018579330a8496c33de2bf8fe58f3ab8aa6dee67088), `oneport-ff2679cc8-L-tsan` (03aff573a9f756189582a386b0078b45309053079ab445dd39d3ba242df3f5fb), `oneport-ff2679cc8-L-msan` (e13a6dc5eb14405ba199c885b3e036f711a2d445aaed886a797f8d5473b2abc3), `harness_cmux-ff2679cc8-L-asan` (6a7cc30c1fad4fb139736a9202e26b460836861c4101dd7e5d8820594a33e66c), `harness_cmux-ff2679cc8-L-tsan` (7c1b8725a0561e97bcb793a25b361671b159f4f08ae37686697449b05d6144d7), `harness_hyper_util-ff2679cc8-L-asan` (6c0fc1f84baa887dd621fbfbc413846c76eab9225f954def6f3e710a42bb94c5), `harness_hyper_util-ff2679cc8-L-tsan` (fdfa883ab18e024cac40fa24a27af14fbcca0fd1e9ffc52be422c51a040422e4).
   - W (W lab job recw1, `bench/records_job_w.ps1`, MSVC 19.51.36246; its log directory `C:\Users\alext\lab\records-logs\oneport-ff2679cc8-W-asan\`): `oneport-ff2679cc8-W-asan` (archive sha256 6ee9a92543c72323028566056658e474e0c436b3ca4660847944ae5135ba452b).
5. The gates of the measured Release builds, each passed, not a dry run, citable: `gate-L.json` sha256 c6517177d497dc7f6951d2860926e950618a17cd6b1fc9568e0f8375ccfc1ab9 with `measured-L.json` ede490f425e7ec5781deb72cf199b71ffdff3036df0431caf8430f4511556a96 (L, `~/lab/p3/m7g/records-ff2679c/`); `gate-W.json` sha256 329d372ee7d4dc15ef6b7bac76fb9d8de35d5d048f9eea5108ae08caefc9e1fc with `measured-W.json` 82e01e6bfc348bf2794bbb299d819287228b8ba550eaade73a87f68c13299c0d (W, `C:\Users\alext\lab\p3\m7g\records-ff2679c-W\`). Every frozen run on L uses the binaries and harnesses of L's records job's `build-release`, and every frozen run on W those of W's.
6. `bench/coverage.json` at CODE_FREEZE: the declared gaps of the entry "The pre-freeze items on L (M7d)", item 9, each read true then, and the Windows gap settled: no third-party library needs one, since OpenSSL 3.5.9 and nghttp2 1.70.0 are built with MSVC's `/fsanitize=address` in their asan flavour and W's ASan build links them.
7. What comes next, by section 8 step 4: on the frozen binary, in dedicated mode only, rule E's IOCP receive form, which has nothing to choose (the coordinator's decision on M6a's reading 7: only the zero-byte form satisfies B2(d)), so it runs no session; then the A/A pilot on each host with `SEED_PILOT_L` and `SEED_PILOT_W`, with its timer and split parts.
