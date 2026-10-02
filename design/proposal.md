# P3 design proposal: one listener for client-first TCP protocols

Status: proposal, revised after the first audit (commit 83c4710, `design/proposal-audit.md`), the
second audit (commit 49993f5, `design/proposal-audit-2.md`) and the freeze check of
`hypotheses.md` (commit 56f90bd, `design/freeze-check.md`). Not frozen. Written 2026-10-02.
Nothing in this file is a result. Alex's decisions of 2026-10-02 and the defaults of the first
audit's question table are applied (section 11.1). Section 5 and every decision it depends on
become `hypotheses.md`. The order of freezes and runs is fixed (I31 E4): `hypotheses.md` is
frozen first, before any code of the server exists; then engineering; then the code freeze; then
the A/A pilot on the frozen code; then one revision-log entry of `hypotheses.md` that commits the
pilot's outputs; only then any one-port window of the frozen code. Later changes to this file go
into its revision log.

Paper: "One listener for client-first TCP protocols: what first-bytes demultiplexing costs under
single-protocol load" (working title, scoped to what the design measures). Venue: MDPI Future Internet. Author: Alex I.
Tsvetanov, Technical University of Sofia, sole author. Repository: `papers/one-port` (private
`Alex-Tsvetanov/paper-one-port`; it stays private until Alex decides, section 11.1).

Words used here:
- "The server" is the paper's own minimal server, `oneport`, built in this repository.
- "One-port mode" and "dedicated mode" are the server's two listener layouts, chosen by a flag
  (I20, I21).
- "Detection" decides a connection's protocol from its first bytes. "Dispatch" hands the
  classified connection to its handler.
- "L" and "W" are the lab hosts of `lab/README.md`. "The survey" is
  `design/competitor-survey.md`; "survey 2.5" is its section 2.5, "ambiguity 7" is item 7 of its
  section 3.2. "The audit" is `design/proposal-audit.md`; "audit F8.2" is item 2 of its F8.
  "Audit 2" is `design/proposal-audit-2.md`; "audit 2 N4" is its finding N4.
- A "window" is one timed run of one arm. A "session" is four windows in mirrored order (ST1).
  A "cell" is one contrast at one setting.
- A "one-port window" is a timed window in which the server runs in one-port mode, whatever it
  is compared with. Unit tests and untimed counter checks are not windows (I31 E4).
- "The freeze", without a qualifier, is the code freeze (I31 E3). "The hypotheses freeze" is the
  earlier freeze of `hypotheses.md`. "The pilot entry" is the revision-log entry of ST13 step 9.

Numbering: S scope, I implementation, A arms, WL workloads, HC hard cases, ST statistics, C, B
and M the hypotheses of the cost, robustness and mechanism families, CP competitors, Z
sanitizers, LB lab, RK risks, Q questions. Facts beyond the survey carry their source, listed
again in "Sources added beyond the survey". Named placeholders, written in capitals (for example
`R_C`), stand for values that a pilot measures or that engineering sets before the freeze, each by
a stated rule. None of them has a value yet. "A design choice" marks a number this design picks,
with its reason. It is not a measured fact.

## 1. Scope

S1. Transport: TCP only. QUIC and other UDP protocols are a later paper.

S2. The paper's claims are about the server, as measured on L and W under the conditions of
section 8. This proposal words no claim beyond the paper. The cost claims are scoped to
single-protocol load: each cost cell sends one protocol to the listener (Q17, audit F7). A
mixed-protocol cell is a secondary result (5.7). Every cost claim quotes its margin: equivalent
within the ratio interval [0.98, 1.02] on one metric and one host (ST12).

S3. Protocols served directly. All are client-speaks-first at the TCP layer (survey 3, column
"Who speaks first"):

| Member | Why it is in the set | Bytes to decide (I8) |
|---|---|---|
| HTTP/1.1 | Every system of A4 serves it. It is the default class of most sniffers (gap 6). | at most 10 |
| h2c, prior knowledge only | The one HTTP split most HTTP servers make on cleartext (gap 6). Its preface parses as an HTTP/1 request (ambiguity 2). The Upgrade path is deprecated (RFC 9113 App. B) and is not served. | 24 |
| TLS, by its ClientHello | Every proxy in the survey routes it before the handshake (survey 4). In-process it is terminated, in hand-off it is passed through by SNI and ALPN (I22). | 6 in-process; the whole ClientHello in pass-through |
| PROXY v1 and v2 prefix | Configured per listener, never guessed (survey 2.4, detection policy). It is a prefix, not a protocol. It carries ambiguity 1 and the hard case "PROXY v2 before HTTP/1". | 8 (v1) or 16 (v2), then the whole header |
| SSH | The "Both" class (survey 3.1). It is detectable when the client sends first, as OpenSSH does. `SSH-` is a legal HTTP token prefix (ambiguity 6). sslh and caddy-l4 detect it built in, HAProxy through `req.payload`; nginx and Envoy cannot (survey 2). | 4 |
| MQTT 3.1.1 and 5.0 | Binary and strictly client-first: the first packet MUST be CONNECT (MQTT 3.1.1 s3.1). Its signature sits at a variable offset (ambiguity 7). MQTT 5.0 says a multi-protocol server uses the protocol name to recognise it (survey 3). HAProxy has a built-in check, `mqtt_is_valid`; no surveyed in-process library has one (gap 5). | 9 to 12 |

S4. PostgreSQL is left out (Q3: MQTT is the sixth protocol). Its first byte, 0x00, is unique in
the set above, so it adds no ambiguity the set lacks. Its direct-TLS mode (PostgreSQL 17 and
later) adds only routing by ALPN, which the TLS member already exercises (ambiguity 10).

S5. Server-speaks-first protocols (SMTP, FTP, POP3, IMAP, MySQL, VNC; survey 3) are a declared
scope boundary. They are served only through a timeout fallback (S6). SMTP represents them in
the experiments, with a minimal handler (I26). Banner-first hand-off, where the listener speaks
first itself (sshttp's SMTP mode, survey 2.9 and gap 2), is also left out. It covers one pair of
protocols, it discards the backend's real banner, and it does not decide from the client's first
bytes. The paper names it as related work only (audit F24).

S6. The fallback, and what "correct" means for it. A listener may name one fallback protocol.
Two timers start together (I13): the silence timer T_fb and the decision deadline T_dec. They
start at accept, or, on a listener configured for PROXY, at the moment the PROXY header is
complete. "Delivered" below means observed by the server's loop: a readiness or completion event
that the loop handled, or a non-blocking check that returned a byte. The behaviour is correct
when all of these hold:
- (a) A connection that has delivered no application byte when T_fb expires is dispatched to
  the fallback handler, unless the check of (b) finds a byte. This happens in the first loop pass
  that handles that expiry (B2), never earlier. The connection is never closed or routed
  elsewhere instead.
- (b) The tie rule. Every loop pass handles all of its completions and readiness events before
  any expiry (I13). Before every fallback dispatch, the server then checks the connection for a
  byte without waiting (I11, I29):
  - on a connection with no receive posted with a buffer (epoll in both modes; the zero-byte
    `WSARecv` on IOCP; the io_uring peek mode), one non-blocking one-byte `recv` with `MSG_PEEK`;
  - on a connection whose receive was posted with a buffer (io_uring replay with a provided
    buffer; IOCP's posted-buffer form, if rule E chooses it), a non-waiting reap of the ring's or
    the port's completions, since such a receive has already moved the bytes out of the socket
    and a peek would find nothing (audit 2 N14). On io_uring the reap goes through
    `io_uring_enter` with `IORING_ENTER_GETEVENTS`, because the ring defers task work (I2). Each
    form is pinned by a test before use (Z2).
  If the check finds a byte, the byte wins: the connection is not dispatched by the silence
  timer, and its bytes alone decide it. So a connection that delivered a byte before T_fb
  expired is never dispatched by the silence timer. This settles an expiry and a byte handled in
  the same pass, and a receive that completed but was not yet reaped (audit F12). It does not
  cover a byte that reaches the socket after the check; by the server's clock that byte came
  after T_fb, which is case (g).
- (c) After a fallback dispatch, the byte transcript in both directions equals the transcript of
  the same client script against the fallback protocol's dedicated port. Only the timing
  differs, by the wait for T_fb.
- (d) A connection with at least one byte that no matcher has decided when T_dec expires is
  closed and counted "undecided". It is never dispatched to the fallback.
- (e) A connection whose bytes rule out every matcher is closed at once and counted "rejected",
  unless the listener names a default route. The experiments name none.
- (f) A connection that is silent when T_dec expires, on a listener without a fallback, is
  closed and counted "silent".
- (g) A client-first client whose first byte is delivered after T_fb is dispatched to the
  fallback. This is the defined price of the boundary, not an error. HC7 measures it with a
  guard band.
- (h) A connection whose peer shuts down writing before a decision is closed at once. It is
  counted "undecided" if it delivered at least one byte, and "silent" if it delivered none. It is
  never dispatched to the fallback. HC21 tests it (audit F12).
SSH may be the fallback instead of SMTP (sslh's code default `on-timeout` is "ssh", survey
2.8). That configuration is secondary.

S7. Timeout values (Q10, kept), as design choices: T_fb = T_dec = 3 s and T_hdr (the PROXY
header deadline) = 3 s. The value follows the PROXY spec, which asks for at least 3 s to cover a
TCP retransmit (survey 2.4), and caddy-l4's default `matching_timeout`, 3 s (survey 2.7). In the
robustness family every competitor with a matching setting gets the same value (section 6); each
also runs once at its defaults, for a descriptive table. The memory runs of B3 use 60 s in every
system that has a detection timer, so that no connection expires before the last sample (WL7).

S8. Out of scope: QUIC, UDP and HTTP/3; WebSocket by its Upgrade header (not decidable from the
first bytes, survey 3); h2c by Upgrade; SSLv2-compatible ClientHellos; MQTT 3.1 (`MQIsdp`);
Redis (ambiguity 8); kernel routing mechanisms (survey 2.26, gap 4).

## 2. The server

### 2.1 Overview and origin

I1. One C++23 program, `oneport`, built with CMake (layout in I33). Three accept backends:
epoll and io_uring on Linux, IOCP on Windows. One backend per process, chosen by `--backend`.
One worker thread per server core. The primary cells use one server core.

I2. The server derives from the minimal event loop of the author's previous paper P1
(`papers/wake-defect/loop/`, `papers/wake-defect/design/minimal-loop.md`). That loop has no
I/O, sockets or timers (its section 2.1). P3 takes these parts from it:
- the io_uring ring on raw system calls, without liburing, created with `SINGLE_ISSUER`,
  `DEFER_TASKRUN` and `R_DISABLED` and enabled on the worker (P1 2.5);
- the MSan rules for memory the kernel fills: value-initialise every structure a raw call fills,
  and unpoison each completion (P1 2.5);
- the eventfd stop path and the IOCP port setup (P1 2.4, 2.6);
- the sanitizer build options, including the MSan-instrumented libc++ (P1 2.8).
P3 adds the rest: accept, receive, peek and send on every backend, the deadline queue (I13), the
connection state, the detection table, the handlers and the counters. The code is copied into
this repository from one P1 commit, recorded at the copy, with an attribution note in each copied
file and in the commit message; the author is the same. Nothing builds against P1's repository.
No licence is chosen for now, and the paper repositories stay private until Alex decides. The
paper cites P1 only where P1's text bears on a claim (rule D8). (Q7, decided.)

I3. Connection state is a tagged union of handler states. Dispatch is a switch on the tag, with
no virtual call. A dedicated listener sets the tag at accept, a one-port listener at
classification. From then on both modes run the same code.

### 2.2 Listener and accept

I4. One-port mode has one listening TCP socket per process, so one per transport and accept
model. With more than one worker, the workers share that socket:
- epoll: each worker's epoll set holds it with `EPOLLEXCLUSIVE` (Linux 4.5 and later,
  epoll_ctl(2));
- io_uring: each worker's ring holds a multishot accept on it (kernel 5.19 and later,
  `io_uring_prep_accept(3)`). A completion without `IORING_CQE_F_MORE` ends the multishot, and
  the worker arms it again;
- IOCP: one completion port, shared by the worker threads, with AcceptEx requests posted on the
  socket.
A group of `SO_REUSEPORT` sockets, one per worker, is a different listener layout. It is
measured only in the secondary 2-core cells (Q11; 5.7).

I5. Accept on each backend:
- epoll: non-blocking `accept4` on readiness of the listening socket, drained per readiness.
- io_uring: the multishot accept of I4.
- IOCP: AcceptEx with `dwReceiveDataLength` = 0 on every listener that names a fallback. It then
  completes as soon as a connection arrives (AcceptEx docs). With a receive buffer, AcceptEx
  completes only after data arrives, `SO_CONNECT_TIME` counts whole seconds, and the documented
  remedy for a client that sends nothing is to close its socket (AcceptEx docs). The server
  therefore does not use the receive buffer on fallback listeners (audit F18). The form with a
  receive buffer gives the first bytes at accept time (gap 8). It is used only on listeners
  without a fallback, in secondary cells.
- IOCP accept depth: every listener keeps `N_ACCEPTEX` AcceptEx requests outstanding, a constant
  set in engineering, the same in both modes. In dedicated mode each of the six listeners keeps
  that many, and in a cost cell only one of them receives connections (audit F29).
- IOCP completions: the server sets `FILE_SKIP_COMPLETION_PORT_ON_SUCCESS` on accepted sockets in
  both modes, as libuv v1.53.0 does (`src/win/tcp.c` line 189). I29 counts operations either way
  (audit F17).
- Listen backlog: on L the server passes the value of `net.core.somaxconn`, read at startup, the
  largest backlog the kernel accepts (ip-sysctl docs). On W it passes `SOMAXCONN`; the Winsock
  `listen` text on it is quoted at the freeze (audit F9.3).

### 2.3 Detection table

I6. Matchers are C++23 `constexpr` descriptors in one table. Each has:
- `first`, the set of first bytes it can accept (256 bits);
- `need`, the fewest and the most bytes it needs to decide;
- `match(std::span<const std::byte>)`, a `constexpr` function that returns yes, no, or
  need-more with the number of bytes still needed;
- `samples`, byte strings taken from the specs (RFC 9112, RFC 9113, RFC 8446, RFC 4253,
  MQTT 3.1.1 and 5.0).

I7. Computed at compile time from the table:
- a 256-entry array from the first byte to the set of candidate matchers;
- `static_assert` checks over the sample corpus: each protocol's samples are accepted by its
  matcher; every prefix of them is rejected, or left need-more, by every other matcher; no
  matcher accepts any prefix of another protocol's sample; every `need` maximum is at most the
  budget B_dec (I14).
So the classes are prefix-disjoint over the corpus, and the order of the table cannot change a
decision on it. Inside a first-byte bucket, the matcher with the smaller `need` runs first, for
speed only.

I8. The matchers:

| Matcher | Accepts | Decides at |
|---|---|---|
| TLS | byte 0 = 0x16; byte 1 = 0x03; byte 2 any, since RFC 8446 s5.1 says to ignore the record version (ambiguity 3); a record length of at most 2^14; byte 5 = 0x01, client_hello | 6 bytes |
| h2c | the 24-byte preface of RFC 9113 s3.4, exactly | 24 bytes, or the first byte that differs |
| HTTP/1.1 | at most one leading CRLF (RFC 9112 s2.2), then GET, HEAD, POST, PUT, DELETE, CONNECT, OPTIONS or TRACE (RFC 9110 s9.1) or PATCH (RFC 5789), then exactly one SP, the strict reading of ambiguity 9 | at most 10 bytes |
| SSH | `SSH-` (RFC 4253 s4.2) | 4 bytes |
| MQTT | byte 0 = 0x10 (CONNECT); a Remaining Length of 1 to 4 bytes; then `00 04 4D 51 54 54` ("MQTT") and level 4 or 5 (MQTT 3.1.1 s3.1.2.1 and s3.1.2.2; MQTT 5.0 s3.1.2.2) | 9 to 12 bytes |
| PROXY v1 and v2 | not in the table; parsed before it, on a configured listener only (I9) | v1: 8 bytes, then the line to its CRLF, at most 107; v2: 16 bytes, then the address block |

A method outside the list is rejected (Q14: the nine methods of RFC 9110 and PATCH). The list is
a compile-time constant.

I9. Order of the tests on one connection:
1. On a PROXY listener, the PROXY header, by the spec's decision rule: v2 needs 16 bytes with
   the first 13 matching, v1 needs 8 with the first 5 equal to "PROXY" (survey 2.4). A prefix
   that cannot match closes the connection. A partial header waits until T_hdr, then the
   connection closes. This is the strict rule; the spec's tolerant wording is not used (survey
   1.3). The header is consumed exactly, so the next read starts at the first application
   byte. A v2 header may be at most 536 bytes, the size both formats were designed to fit
   (survey 2.4). A longer one is rejected, and the paper says so.
2. The first-byte array. An empty candidate set rejects at once (S6 e).
3. The candidates' matchers, in bucket order, until one says yes, all say no, or more bytes are
   needed.

I10. How each item of the survey's ambiguity list is handled:

| Item | Handling |
|---|---|
| 1. PROXY v2 begins with CRLF CRLF | The PROXY parser runs before the table, so the HTTP matcher's CRLF skip never sees a PROXY header. |
| 2. The h2 preface parses as HTTP/1 with method PRI | PRI is not in the method list; h2c needs all 24 bytes. |
| 3. The TLS record version | Ignored, except the major byte 0x03. |
| 4. SNI and ALPN may span records | In-process, 6 bytes decide. In pass-through the server's parser reassembles the ClientHello across records, up to B_CH (I14). |
| 5. SSH has no fixed order | Client-first SSH is found by `SSH-`. A silent SSH client is served only when SSH is the fallback. |
| 6. `SSH-` is a legal HTTP token prefix | No listed method starts with S; I7 checks it at compile time. |
| 7. MQTT's name sits at offset 2 to 5 | The matcher decodes the Remaining Length first. |
| 8. Redis inline commands share HTTP's first bytes | Redis is not served. `GET key` is classified HTTP/1.1, and the HTTP handler answers 400 (HC25). |
| 9. Lenient whitespace enables smuggling | Strict: one listed method, then one SP. |
| 10. TLS protocols told apart by ALPN | Pass-through routes on SNI and ALPN. In-process termination negotiates ALPN `http/1.1` or `h2`. |
| 11. Server-first protocols | The fallback (S6). |
| 12. QUIC bits are version-specific | Out of scope (S1). |
| 13. PostgreSQL and DNS both start with 0x00 | Neither is served; 0x00 rejects at once. |
| 14. Client-first protocols with server-first exceptions | Not served (AMQP, Redis); an SMTP server's 554 opening does not arise. |

### 2.4 Detection modes, and the peek story on each backend

I11. Two modes, chosen by `--detect`:
- **Replay, read in place** (`replay`). The first read goes into the buffer the handler would
  read into in dedicated mode. The matcher runs on it, and the handler then parses the same
  buffer from its start. No byte is copied for the replay, and the system calls are those of
  dedicated mode.
- **Peek** (`peek`). The bytes are copied with `MSG_PEEK` into a per-worker scratch buffer and
  stay in the kernel. The handler later reads them as in dedicated mode. This costs at least one
  receive operation per connection more than replay. Every peek is a synchronous call on the
  worker thread, so two pending peeks never share the scratch buffer (audit F8.1).

The story on each backend (revised after audit F8 and F19):

| Backend | Peek | Replay |
|---|---|---|
| epoll | Sockets are registered with `EPOLLRDHUP` in both modes; the trigger mode is the one dedicated mode uses, fixed in engineering. On readiness the server calls `recv(MSG_PEEK)`. `EPOLLRDHUP` (Linux 2.6.17 and later, epoll_ctl(2)) reports a peer that shut down writing (S6 h), which a peek alone cannot show: it never returns 0 while bytes are queued. When a peek is undecided, the server sets `SO_RCVLOWAT` to the total number of bytes the matcher needs, the queued bytes plus the missing ones, because readiness counts every unread byte (`tcp_epollin_ready`, include/net/tcp.h lines 1823 to 1833 at v7.2; audit F8.2). The next readiness then comes only when that many bytes are queued (socket(7): since Linux 2.6.28, select, poll and epoll respect `SO_RCVLOWAT`). Before the handler reads, one more `setsockopt` resets it to 1. I29 counts both calls. With `SO_RCVLOWAT` set, a level-triggered registration would not spin either; edge-triggered mode is nginx's condition for its peek path (survey 2.1), not a necessity of this design (audit F19). | `recv` into the handler's buffer, triggered as in dedicated mode. |
| io_uring | The peek waits with `IORING_OP_POLL_ADD` for `POLLIN \| POLLRDHUP` and reads the returned mask from the completion. `POLLRDHUP` reports a half-close (S6 h). Otherwise the worker calls `recv(MSG_PEEK \| MSG_DONTWAIT)` synchronously. `SO_RCVLOWAT` is set and reset as on epoll; `tcp_poll` applies it (net/ipv4/tcp.c line 589 at v7.2). This replaces the first version's remedy, a peeking `IORING_OP_RECV` with `IORING_RECVSEND_POLL_FIRST`, for two reasons the audit found in the v7.2 source: such receives copy inside the kernel when issued or retried, so several could fill one scratch buffer before any completion is reaped (F8.1); and a receive result does not report a FIN, so after a half-close the peek would return the same bytes until T_dec (F8.4). That the poll completes only at the low-water mark is derived from the source (audit, "Technical claims"). It is pinned by a test before use (RK4). Multishot receive is not used for peeking. | `IORING_OP_RECV` into a buffer taken from a provided-buffer ring, so a pending receive holds no buffer of its own. |
| IOCP | `WSARecv` with `MSG_PEEK` is valid only for nonoverlapped sockets, and a `WSARecv` with both `lpOverlapped` and `lpCompletionRoutine` NULL treats the socket as nonoverlapped (WSARecv docs; audit F17). So the peek is a zero-byte overlapped `WSARecv`, used as the readiness signal (the pattern of libuv v1.53.0, `src/win/tcp.c`, flag `UV_HANDLE_ZERO_READ`), then a synchronous `recv(MSG_PEEK)` on the non-blocking socket. Windows does not support `SO_RCVLOWAT`; `setsockopt` fails with `WSAEINVAL` (SOL_SOCKET options docs; audit F8.3). So nothing can wait for more bytes while they stay queued. After the first undecided peek, the connection switches to replay for the rest of its detection: the next receive reads into the handler's buffer, and matching continues there. I29 counts each switch. A half-close is then seen as a read that returns 0 bytes, as in replay mode; a peek that returns 0 bytes after the zero-byte completion is a half-close with no byte (S6 h). Both are pinned by tests before use. | Either a zero-byte `WSARecv` and then `recv` into the handler's buffer, or a `WSARecv` with the buffer posted at once. Rule E (I31) chooses. |

I12. Each backend has one default mode, used by every cost and robustness cell. The proposed
default is replay on all three, by the operation count of I11. Both modes are in the frozen
binary, so the default is a flag value. Rule E (I31 E2) may change it per backend after the pilot
entry and before any confirmatory window. M1 tests the default against the other mode. On IOCP the peek mode
includes the switch to replay above (RK5).

### 2.5 Timers, buffers and memory per pending connection

I13. The deadline queue. All pending connections of a listener wait under the same durations,
so their deadlines arrive in accept order. One intrusive FIFO list per listener and timer gives
constant-time arming, cancelling and expiry checks. The loop's wait bound is the earliest head
deadline: `epoll_pwait2` with a timespec, the io_uring wait with its timeout argument, and
`GetQueuedCompletionStatus` in milliseconds, as in P1. After every wait the loop reads the clock.
If no deadline has passed, it waits again, so no timed event is handled early. Within one pass,
the loop handles every completion and readiness event it has before it handles any expired
deadline, and a fallback dispatch makes the check of S6(b) first (audit 2 N14). A wait can end
early: on Windows, a timeout between one and two clock ticks can end after one tick (Wait
Functions docs; audit F12). For each timed event the loop records when its wait returned and in
which pass the event was handled (B2).

I14. Budgets, all compile-time constants:
- B_dec = 24 bytes after any PROXY header: the largest `need` in the table (h2c);
- B_CH = 16384 bytes for a ClientHello reassembled in pass-through: the TLS record limit 2^14
  (RFC 8446 s5.1), and Envoy's default `max_client_hello_size` (survey 2.5);
- the PROXY limit of I9.
A connection that exceeds a budget while undecided is rejected.

I15. Memory held by a pending connection, by design:
- the connection state (descriptor or handle, tag, matcher progress, deadline links), whose size
  is fixed at compile time and reported;
- no data buffer while no byte has arrived, on every backend: epoll takes a buffer on
  readiness, io_uring uses provided buffers for replay and a synchronous peek into the worker's
  scratch buffer, IOCP waits with a zero-byte receive (if rule E chooses the posted-buffer form on
  IOCP, the paper reports the buffer it holds);
- with replay, the handler's buffer from the first byte on; with peek, nothing in user space,
  since the bytes stay in the socket's receive queue, which WL7 counts;
- in pass-through, the partial ClientHello, at most B_CH.
B2(d) checks these bounds with counters.

### 2.6 Dispatch modes

I16. **In-process** (`--dispatch inproc`). The classified connection stays on its worker, and
its handler takes over (I3). TLS is terminated in the server (I22).

I17. **Hand-off by relay** (`--dispatch relay`), Linux only. The front opens a TCP connection
over loopback to the backend chosen by class. For TLS the class comes from the server's own
ClientHello parser (SNI and ALPN), and the front never terminates TLS (pass-through). The front
first writes any replayed bytes, then relays both directions until one side closes. This is the
topology of the five proxies (survey 2); what each system examines to choose a route differs
(M3). The backend is described in I18. The relay copy (user-space buffers; or `splice(2)` on
epoll and `IORING_OP_SPLICE` on io_uring) is chosen by rule E. If rule E chooses splice, HAProxy
gets its documented counterpart, `option splice-auto` (CP2; audit F9.4). The user-space relay
buffer is `RELAY_BUF` bytes per direction, a constant set in engineering and reported beside each
proxy's default buffer size (audit F9.7).

I18. The backend of the hand-off cells is the same for every arm of a cell. For M2 it is the
server in dedicated mode, which terminates TLS. For M3 and for B against the proxies it is the
server in stub mode (`--mode stub`): one listening port per class, and each connection gets the
least work that completes an exchange. HTTP/1.1 gets the I26 response. TLS: the stub reads one
whole TLS record, the ClientHello, writes the fixed 13-byte body of I26, and closes; it never
handshakes. `opgen` sends one recorded ClientHello, the same bytes on every connection, captured
once from OpenSSL with the settings of I24 and kept in the repository's test fixtures, so that no
key share is generated per connection for a backend that never uses it. The stub closes first in
both exchanges (audit F9.6). So M3 measures the front, not a TLS handshake behind it. The backend
runs in its own process on its own cores (LB2).

I19. Hand-off by descriptor (`SCM_RIGHTS`) is dropped and not built (Q8, default applied; audit
F14).

### 2.7 Dedicated-port mode

I20. `--mode dedicated` opens one listening socket per protocol (HTTP/1.1, h2c, TLS, MQTT,
SSH, SMTP) on consecutive ports. Backend, workers, handlers, buffers and the PROXY setting are
those of one-port mode. It has no detection, no detection timers and no detection budget. That
is the whole difference between the modes, and it is what the cost family measures. The modes
also agree on invalid input, because the HTTP/1.1 handler applies the detector's request-line
grammar (I26). Z2 tests both modes on the inputs of HC17, HC23 and HC25 (audit F22).

I21. One binary serves both modes. The flag is read once, at startup, in the listener setup.
A structural test fails if any other source file reads it (in the manner of P1's test X1), so
the handlers cannot differ between the modes.

### 2.8 TLS

I22. TLS decision:
- **In-process: termination.** In the cost family, in the in-process robustness cells, in M1
  and in M2's in-process arm, the server terminates TLS. One-port and dedicated arms use the
  same library build and the same settings. The detector checks only the 6 bytes of I8. ALPN is
  negotiated inside the handshake. On every backend and in both modes, the loop owns the socket
  and feeds the library through memory BIOs, because io_uring and IOCP complete I/O that the
  library cannot issue itself.
- **Hand-off: pass-through.** In M2's relay arm, in M3 and in B against the proxies, the front
  parses the ClientHello itself for SNI and ALPN and never terminates. All five proxies pass
  through in the configurations of section 6 (survey 2.1, 2.3, 2.5, 2.7, 2.8).

I23. The library is OpenSSL, from its 3.5 LTS series (Q4). On 2026-10-02 its latest release is
3.5.9, released 2026-09-29, with support until 2030-04-08 (openssl-library.org/source). It is
pinned at the freeze to the latest 3.5 release, by archive URL and sha256, and the same tarball is
built from source on L and on W. W builds it with MSVC, using Strawberry Perl and NASM installed
at user level (section 11.1). The configure options that select TLS features are the same on both
hosts; the target and toolchain options necessarily differ, and both lists are recorded (audit
F15.2).

I24. TLS settings, the same in the server, the backend and the generator:
- TLS 1.3 only; cipher suite TLS_AES_128_GCM_SHA256 and signature scheme ecdsa_secp256r1_sha256,
  both MUST in RFC 8446 s9.1;
- key exchange group X25519 only. RFC 8446 s9.1 makes X25519 SHOULD and secp256r1 MUST. X25519
  alone departs from OpenSSL 3.5's DEFAULT group list, whose predicted key share is
  X25519MLKEM768 (`SSL_CTX_set1_curves(3)` at openssl-3.5.9; audit F16). The reason: one
  classical group gives a small ClientHello of one fixed length, ℓ (WL7), for every connection
  and every system;
- one ECDSA P-256 certificate, made from a fixed test key in the repository's test fixtures;
- no session tickets: `SSL_CTX_set_num_tickets(ctx, 0)`, because under TLS 1.3
  `SSL_OP_NO_TICKET` only switches to stateful tickets, which are still sent (OpenSSL 3.5.9 man
  pages; audit F16); no session cache: `SSL_CTX_set_session_cache_mode(ctx,
  SSL_SESS_CACHE_OFF)`; no early data. So every churn connection makes a full handshake;
- ALPN `http/1.1` in the cost cells; `h2` only in secondary cells.
Session resumption is a secondary cell.

I25. Stated before the run: the handshake dominates the cost of a TLS churn connection, so the
TLS cells of the cost family have little power to show the cost of a 6-byte check. The paper
says so beside their result (RK6).

### 2.9 Handlers

I26. Every handler is the same code in both modes (I21). Each is minimal:

| Handler | What it serves |
|---|---|
| HTTP/1.1 | The server's own parser: request line and headers up to the empty line, no request body, keep-alive and `Connection: close`. Response: 200, `Content-Type: text/plain`, `Content-Length: 13`, body `Hello, World!`, the 13-byte body of P2's server (`papers/typed-routing/hypotheses-round2.md`, H6). The request line follows the detector's grammar (I8): at most one leading CRLF, one listed method, one SP. A request line that breaks it is closed without a response, in both modes, as the detector closes it in one-port mode. Any other malformed request gets 400. |
| h2 (h2c, and over TLS with ALPN `h2`) | nghttp2's server session through its memory callbacks, the same build and settings in both modes. nghttp2 v1.70.0 is the latest release on 2026-10-02 (github.com/nghttp2/nghttp2/releases); pinned at the freeze by sha256. Response: 200 with the same body. |
| TLS | OpenSSL (I22 to I24), then the HTTP/1.1 or h2 handler on the decrypted bytes. |
| MQTT | Reads CONNECT and answers CONNACK, accepted (MQTT 3.1.1 s3.2, fixed header `20 02`; the MQTT 5.0 form with an empty property list). Answers PINGREQ (`C0 00`, s3.12) with PINGRESP (`D0 00`, s3.13). Closes on DISCONNECT (s3.14). No sessions, no publish. |
| SSH | Sends its identification line, `SSH-2.0-oneport` and CRLF, on entry. Reads the client's line, at most 255 bytes (RFC 4253 s4.2). Then closes. |
| SMTP | Fallback and its dedicated port only. Sends the 220 greeting, answers EHLO with 250 and QUIT with 221, and anything else with 500 (RFC 5321). |

I27. Each handler's receive buffer has the same size in both modes and is taken on the first
readiness or completion, not at accept (I15). In replay mode the detector reads into that buffer,
so one-port mode adds no buffer of its own.

I28. SSH is the one protocol whose message order changes with the mode. In dedicated mode
"entry" is accept, so the server speaks at once. In one-port mode entry is classification,
after the client's `SSH-`. The handler is identical, but in one-port mode the server's line
waits for the client's first bytes. This is structural. SSH is therefore a secondary cell of the
cost family, with this stated (Q12).

### 2.10 Counters

I29. Every build counts, per worker, in plain integers without atomics:
- operations by kind: accept, receive, peek, zero-byte receive, send, `setsockopt` (each
  `SO_RCVLOWAT` set and reset), the non-blocking check of S6(b), `io_uring_enter` calls,
  submissions by opcode (`IORING_OP_POLL_ADD` included), `GetQueuedCompletionStatus` calls;
- switches from peek to replay (IOCP, I11);
- payload bytes crossing the user and kernel boundary, by direction (peeked bytes included);
- payload bytes copied in user space;
- wakeups per connection during detection;
- outcomes per class (classified, rejected, undecided, silent, fallback);
- for each timed event, its deadline, the time its wait returned, and the pass that handled it.
The counters are in every arm, so they cost the same on both sides of each contrast. They are
reported per window. On L, a separate untimed window per cost cell checks the system-call
counters against `perf trace -s` (perf-trace(1)). On W the counters stand alone.

### 2.11 Generators and the holder

I30. Three first-party programs, each with its own sanitizer records (Z1):
- `opgen`, the load generator. C++23, with an epoll backend on Linux and a backend for
  Windows chosen in engineering. Scripted exchanges per protocol (WL1); churn and keep-alive;
  closed and open loop; time to first response byte per exchange. It uses the same OpenSSL build
  and settings as the server, and the recorded ClientHello against the stub (I18). Its h2 frames
  carry only static-table header fields, and it reads each response up to END_STREAM. The lab's
  t1gen cannot serve: it speaks HTTP/1.1 keep-alive only (`lab/t1/gen/t1gen.c`).
  - Source addresses: every socket that binds a source address sets `IP_BIND_ADDRESS_NO_PORT`
    (Linux 4.2 and later), so `bind()` reserves no port and `connect()` picks one that may be
    shared while the 4-tuple is unique (IP_BIND_ADDRESS_NO_PORT(2const); audit F6). Each window
    takes the next unused block of `K_SRC` addresses of 127.0.0.0/8, so no 4-tuple recurs while an
    earlier window's TIME-WAIT sockets last (60 s, `TCP_TIMEWAIT_LEN`, include/net/tcp.h line 140
    at v7.2). The run script checks that no block is reused within 60 s. `K_SRC` is set in
    engineering, before the code freeze, so that no connect fails in the development runs, and is
    recorded in the revision log; the pilot needs it, so the pilot cannot set it (audit 2 N13).
    A connect failure in any later window invalidates that window (ST10; RK2).
- `opcase`, the case generator. It runs each hard case (section 4.2) and B3's openings (WL7) as
  a script of writes and gaps, with `TCP_NODELAY` and one write per chunk. It records each write's
  time on the same clock the server uses (`CLOCK_MONOTONIC` on L, QueryPerformanceCounter on W),
  checks the outcome and the transcript against the frozen table, and runs against any system by
  address and port. It cannot force how bytes arrive. The gap between chunks, `GAP_SPLIT`, is set
  by the split part of the A/A pilot, in dedicated mode (ST13 step 8): the smallest tested value
  at which the server's counters show the split read in every replicate on every backend of L
  and W.
- `ophold`, the holder. It accepts connections and holds them without reading or polling them.
  It exists only to measure the kernel's per-socket baseline for B3 (WL7).

### 2.12 Engineering and the order of freezes (rule D2)

I31. Rule E:
- E1. Development runs are development data. They are never results, they are cited only in the
  revision log and the lab journal, and the methods disclose them, as P2 did with its first
  round. Before the code freeze they may time dedicated mode against anything, and one-port mode
  against the competitors or against another one-port option (for example M3's relay against a
  proxy, or peek against replay). No window, on any code, times one-port mode against dedicated
  mode before the pilot entry is committed (ST13 step 9). On the frozen code, no one-port window
  of any kind runs before the pilot entry (E4). A dedicated window and a one-port window against
  the same competitor, at the same protocol, backend and host, still give an indirect one-port
  against dedicated ratio on pre-freeze code. The competitors are the only reference both modes
  may share before the code freeze, since dedicated mode is never timed against one-port mode.
  So every such pair of development cells is listed in the revision log of `hypotheses.md` when
  it runs, and in the paper's methods; no rule uses it (freeze check FC5). The margin was fixed
  by Alex on 2026-10-02, before any code of this paper existed (section 11.1). R_C, the resolved
  list and m_C come from the A/A pilot by a fixed rule with a fixed seed, and the pilot holds no
  one-port data (ST13). So none of them can be tuned to a one-port comparison (audit F4; audit 2
  N1).
  Why one-port windows are allowed before the code freeze at all: rule D2 asks for the server to
  be engineered until it wins, which needs timings of the relay against the proxies and of one
  option against another, and the pilot must run on the frozen code, so it comes after them.
  Those windows hold no cost contrast, and nothing they measure enters the pilot's rule.
- E2. Three choices per backend are fixed by rule E: the default detection mode (I12), the IOCP
  receive form (I11), and the relay copy (I17). Both options of each are built into the frozen
  binary as flag values, since in P2 a layout change of the binary alone moved timings. An option
  replaces the proposed default only if every session of at least 6 development sessions of
  HTTP/1.1 churn (ST1) favours it, and its operation counts per connection (I29) are not higher.
  Six is the smallest count at which an exact sign test can reach p = 2^-6 = 0.0156, below 0.025,
  the minimum P2 used for its T1 cells (P2 H6). When each is decided:
  - the IOCP receive form also sets how dedicated mode reads on W, so it is decided before the W
    pilot, on the frozen binary, with both arms in dedicated mode;
  - the default detection mode and the relay copy exist only in one-port mode, so they are
    decided after the pilot entry, on the frozen binary, before any confirmatory window.
  Each choice is written into the revision log of `hypotheses.md` when it is made.
- E3. Engineering ends at the code freeze: one commit, `CODE_FREEZE`, of the server, the
  generators, the holder, the harnesses, the pins and the tests. The freeze needs green sanitizer
  records (Z1) and a passing test suite. The values that engineering sets (`K_SRC`, `N_ACCEPTEX`,
  `RELAY_BUF`, `N_BG_TLS`, `N_BG_MQTT`, `N_BG_SILENT`, ℓ, and the pins of section 6) and the skb
  caches as L's kernel lists them (WL7) are recorded in the revision log of `hypotheses.md` at the
  code freeze. The A/A pilot (ST13) runs on the frozen code.
- E4. The order (audit 2 N1). Each step starts only after the one before it is committed:
  1. The hypotheses freeze: `hypotheses.md` is frozen before any code of the server exists.
  2. Engineering (E1). Before it ends, one revision-log entry fixes the seeds of ST9, and the
     analysis code that runs the simulation of ST13 is committed with its tests
     (`ANALYSIS_COMMIT`).
  3. The code freeze (E3).
  4. On the frozen binary, in dedicated mode only: the IOCP receive form (E2), then the A/A
     pilot with its timer and split parts (ST13 steps 1 and 8).
  5. The simulation of ST13, at `ANALYSIS_COMMIT`, with `SEED_SIM`.
  6. The pilot entry (ST13 step 9).
  7. After it: rule E2's other two choices, M2's rates (WL6), the B3 feasibility windows,
     `K_BASE`, and every confirmatory, secondary and hard-case run.
  A code change once the pilot has started (freeze check FC2, FC3). Before the simulation of
  step 5 starts, a change that a named failure forces (ST13 step 1) needs new records and a new
  pilot, under the cap of ST13 step 1. Every other change follows the rule for a later change: a
  change that no named failure forces, a change once the simulation has started, and a change
  once that cap is spent. Under that rule the pilot is not run again, and its outputs go into the
  pilot entry or, if the entry is committed, stand; the new build gets new records; every
  confirmatory window of the old build is archived and not used; the runs start again on the new
  build; and the revision log records the change as a deviation. No one-port window of either
  build runs before the pilot entry.

I32. Engineering targets, stated as goals, not as results: in replay mode, one-port mode should
issue the same operations per connection as dedicated mode on every backend; the relay should
not copy in user space where `splice` serves; a silent pending connection should hold no data
buffer.

I33. Layout: `bench/server/` (`oneport`), `bench/gen/` (`opgen`), `bench/cases/` (`opcase`,
`ophold` and the expected-outcome table), `bench/competitors/` (pinned build recipes and
configuration files, each line with its reason, as the Envoy FAQ advises for any benchmark
configuration), `bench/harness/` (the Netty, Jetty, cmux and hyper-util harnesses),
`bench/cmake/pins.cmake`, `tests/`, `analysis/` (including the R-sizing simulation of ST13),
`results/`.

## 3. Arms and contrast families

A1. The server's arms are one binary with four flags: mode (one-port, dedicated, stub),
detection (replay, peek), dispatch (inproc, relay), backend (epoll, io_uring, IOCP).

A2. Three families, never mixed:
- **Cost (C).** The server in one-port mode against the server in dedicated mode: in-process
  dispatch, default detection mode, same binary, same handlers. Only this family can support
  "no measurable cost", and only as "equivalent within [0.98, 1.02]" (ST12). The cost family
  leads the paper (section 11.1).
- **Robustness (B).** The server against the five proxies (the server in relay mode,
  pass-through) and against the four in-process libraries (the server in in-process mode), on
  the hard cases and on memory per pending connection.
- **Mechanism (M).** The server's modes against each other (peek against replay; in-process
  against relay), and the server's relay against each proxy. The proxies add a network hop, so
  they are compared only with the server's relay mode.

A3. No contrast crosses families. No proxy is compared with the server's in-process mode. No
mechanism result supports a cost claim, and no cost result is set beside a proxy.

A4. What each competitor can detect, from the survey. "cfg" means through its configuration
language; "built-in" means a matcher the library ships, wired by a minimal harness; "example"
means the project's own published example, used as it is; "code" means only through a matcher
the user writes. Competitors run only the cells and cases that their configuration language,
built-in matchers or own example cover. Libraries are wired by a minimal harness. Nothing that
would need a new matcher is run (audit F24).

| System | HTTP/1.1 | h2c | TLS, SNI and ALPN | PROXY | SSH | MQTT | Silent-client fallback |
|---|---|---|---|---|---|---|---|
| nginx stream (2.1) | as "not TLS" only | no | yes | yes, mandatory | as "not TLS" only | no | no: closed at `preread_timeout` |
| HAProxy (2.3) | yes | cfg (`req.payload`) | yes | yes | cfg (`req.payload`) | yes (`mqtt_is_valid`) | yes: `inspect-delay`, then the default backend |
| Envoy (2.5) | yes (http_inspector) | yes | yes | yes | no | no | yes, with `continue_on_listener_filters_timeout` |
| caddy-l4 (2.7) | yes | yes | yes | yes | yes | cfg (regexp matcher) | no: closed at `matching_timeout` |
| sslh-ev (2.8) | yes (http probe) | not verified | yes | not verified | yes | cfg (regex probe) | `on-timeout` exists; not verified for sslh-ev, whose probe timeout is checked only on read activity (survey 2.8, RK10) |
| Netty (2.15) | example (`PortUnificationServerHandler`) | yes | yes (`SniHandler`) | yes | code | code | no |
| Jetty (2.16) | yes | yes (upgrade from HTTP/1) | record only (2-byte sniff), no SNI | yes | no | no | no: idle timeout closes |
| cmux (2.10) | yes | yes | record header only, no SNI | no | built-in (`PrefixMatcher`, Go code in the harness) | code | yes, by inference: `Any()` with `SetReadTimeout` |
| hyper-util (2.12) | yes | yes | no | no | no | no | no |

## 4. Workloads, metrics and hard cases

### 4.1 Workloads and metrics

WL1. Churn, closed loop. C connection slots; each repeats connect, one exchange, close.
C = 64 per server core, the lab's T1 default (`lab/t1/t1.py`, `--connections`). The exchange
per protocol, and who closes first, are fixed and the same in both arms:

| Protocol | Exchange | Closes first |
|---|---|---|
| HTTP/1.1 | GET with `Connection: close`, read the response | server |
| h2c | preface, SETTINGS, one HEADERS frame with END_STREAM; read to END_STREAM; GOAWAY | client |
| TLS (HTTP/1.1) | full handshake, then the HTTP/1.1 exchange | server |
| MQTT | CONNECT, read CONNACK, DISCONNECT | client |
| SSH (secondary) | send the identification line, read the server's | server |
| TLS against the stub (M3) | the recorded ClientHello, read the stub's 13 bytes to EOF (I18) | server |

Metric: connections per second, the exchanges completed without error per second of the
measured window. Time to first response byte (TTFB) runs from just before `connect` to the
first byte of the response, on the generator's clock.

WL2. Churn, open loop. Exchanges fall due on a fixed schedule at rate λ = `RATE_FRAC` × the median,
over the A/A pilot's sessions, of the session's mean connections per second in the C1 pilot cell
with the same protocol and backend (ST13). The pilot therefore runs the C1 cells of a host before
its C3 cells. `RATE_FRAC` = 0.5 (Q9), below saturation, since the Envoy benchmarking FAQ advises
never to measure latency at maximum load. Latency is measured from the due time, as t1gen does, so
no stall is hidden. An open-loop window is invalid if fewer than 99% of the exchanges due in it
completed, a design choice (ST10; audit F11). Metric: median TTFB; the 99th percentile is secondary.
For the secondary open-loop M cells, λ is `RATE_FRAC` × the slower arm's median connections per
second in that cell's closed-loop sessions. For the secondary SSH C3 cells, which the pilot does not
run, λ is `RATE_FRAC` × the slower arm's median connections per second in the SSH C1 secondary
sessions of the same backend, which therefore run before them (audit 2 N12).

WL3. Keep-alive. C connections established before the window, one request in flight per
connection. Requests: HTTP/1.1 GET; one h2 stream at a time; MQTT PINGREQ after one CONNECT;
HTTP/1.1 GET over one TLS connection. Detection happens once per connection, before the window,
so this workload asks whether one-port mode leaves any cost per request once the connection is
classified. Metric: requests per second.

WL4. CPU and memory of the server. CPU time of the server's processes over the window (on L
`utime` plus `stime` from `/proc/<pid>/stat`; on W `GetProcessTimes`), divided by the exchanges
completed. Resident memory at the end of the window and its peak (on L `VmRSS` and `VmHWM`; on W
the working set and its peak).

WL5. Operations and copies per connection: the counters of I29, divided by the connections of
the window. For the proxies, `perf trace -s -p` over a separate untimed window gives system
calls per connection by name (secondary).

WL6. Server CPU per connection under hand-off: the CPU time of the front and the backend
together, at an open-loop rate, divided by the connections completed. The rate of each M2 cell
is `RATE_FRAC` × the smaller of its two arms' median closed-loop connections per second, each
measured in 6 development sessions of the cell on the frozen binary, after the pilot entry and
before any M2 session, and recorded in the revision log as `M2_RATE` (rule E1, E4). The relay is not
assumed to be the slower arm: in M2's TLS cells the in-process arm terminates TLS on one core,
while the relay arm's backend terminates it on two (audit F11). Both arms use the hand-off
placement (LB2); in the in-process arm, CPUs 10 to 13 stay idle.

WL7. Memory per pending connection (B3). Connections are opened in the state of the case and
sampled while still pending. "Pending" means the client's bytes are still incomplete, whatever
the system has decided from them so far. Jetty and cmux classify TLS from the record header (A4),
so for them a partial ClientHello waits in their TLS engine, and that memory is what is measured;
the same holds for the server in in-process mode, whose OpenSSL session waits for the rest.

The window. Every B3 window has a fixed length of 30 s from the first connect, a design choice
that ends every sample well inside the 60 s detection timeout (S7) of the first connection
accepted (audit F2.5, F14). The lengths of its phases are design choices too, each given with its
reason (audit 2 N15):
- Before t = 0: fresh processes, the probe of ST1, and a baseline sample (below). The probe's
  client closes by reset, as `opcase` does below.
- Opening, t = 0 to at most 10 s. `opcase` opens `N_PEND` connections in batches of 25, one
  batch every 25 ms. A batch is half of 50, the smallest listen backlog among the systems, sslh's
  hard-coded `listen(sockfd, 50)` (common.c line 152 at v2.3.1; audit F2.1). So a batch fits the
  accept queue even if the previous batch has not been accepted. The 25 ms pace is a design
  choice: it opens 1,000 connections per second, so `N_PEND` takes 400 batches and 10 s, a third
  of the window. Each connection then sends the case's bytes: nothing (silent case); or the TLS
  record header announcing the recorded ClientHello of length ℓ (I18, I24), then its first ⌊ℓ/2⌋
  bytes (partial-ClientHello case). ℓ is measured when the ClientHello is recorded and is fixed
  at the freeze. Half is a design choice: the record is incomplete for every system, whatever
  prefix the system needs.
- Settling, to t = 20 s: a design choice, 10 s after the last batch, for every system to accept,
  register and read what it was sent before the first sample.
- Sample 1 at t = 20 s and sample 2 at t = 25 s: a design choice, two readings 5 s apart for the
  settling check, both 5 s or more before closing. Sample 2 is the value used. The window is
  invalid if any of these holds:
  - the footprint W = U + Kq + Ks (below, with Ks net of the skb caches) differs between the
    samples by more than the larger of 2% of sample 2's W and `SETTLE_ABS` = 8 bytes per pending
    connection. The 2% is a design choice, a fifth of B3's margin of 10% (B3). W is checked, not
    U alone, because U can be near 0 for a server built to hold little (I32), where a relative
    tolerance on U falls below the resolution of `VmRSS`, and because Ks is now part of the
    footprint (audit 2 N8).
    `SETTLE_ABS` is a design choice that keeps the rule defined when W is near 0 or negative: it
    is 80,000 bytes over `N_PEND`, above the 1 kB unit in which `/proc` reports `VmRSS` and
    `Slab` (proc_pid_status(5), proc_meminfo(5));
  - the host's TIME-WAIT count (`ss`) at either sample differs from the baseline's (audit 2 N8);
  - fewer than `N_PEND` of the system's accepted sockets are established at either sample.
- Closing, to t = 30 s: `opcase` closes every connection by reset (`SO_LINGER` on, with a zero
  timeout), so neither end enters TIME-WAIT.

TIME-WAIT sockets are slab objects (net/ipv4/inet_timewait_sock.c line 178 at v7.2, via audit 2
N8) and last 60 s (`TCP_TIMEWAIT_LEN`, I30), longer than a B3 window. A closing phase that left
them would free them inside a later window, and `Slab` would move for reasons outside the system
under test. So B3 windows and `ophold`'s windows close by reset and create none, and the first B3
or `ophold` window of a lab job starts at least 60 s after the last other window on L ended. The
TIME-WAIT check above catches what remains.

Each sample measures:
- U, user memory: the growth over the baseline of the summed `VmRSS` of the processes of the
  system under test (proc_pid_status(5)), divided by `N_PEND`. The stub backend of the relay
  systems receives no pending connection, is the same process for every relay system, and is left
  out.
- Kq, the receive queue: the mean, over the system's accepted sockets on its listening port, of
  the `r` field (rmem_alloc) of `ss -tm` (ss(8)). It is the sum of the truesize of the skbs
  queued for reading, and truesize holds the payload and also the skb's struct and linear head
  (include/net/sock.h lines 2474 to 2481, include/linux/skbuff.h lines 273 to 275,
  net/ipv4/tcp.c lines 926 to 935, all at v7.2; via freeze check FC1). The `f` field (fwd_alloc)
  is reported beside it and not added: ss(8) defines it as memory the socket holds as cache, not
  yet used for packets, so adding it would count reserved, unused memory (audit F2.2).
- Ks, kernel slab: the growth over the baseline of `Slab` in `/proc/meminfo` (proc_meminfo(5)),
  less the growth of the skb caches (below), divided by `N_PEND`. It is host-wide and includes
  both ends of each loopback connection. The client ends are `opcase`'s, the same for every
  system.

The skb caches (freeze check FC1; option (a), the coordinator's decision). A queued skb's struct
and linear head are slab objects, so `Slab` holds them while Kq charges them too, and without a
correction W would count them twice in every cell where a system leaves bytes queued. On Linux
v7.2 the struct comes from the cache "skbuff_head_cache", or, for the fast clones that TCP's send
path allocates, from "skbuff_fclone_cache"; a linear head that fits comes from
"skbuff_small_head" (net/core/skbuff.c lines 606 to 625, 684 to 685 and 5196 to 5225). A search
of every cache created under `net/` at v7.2 finds no other that holds skb structs or heads:
"skbuff_ext_cache" (line 5176) holds skb extensions, neither a head nor data, and the payload
lies in page fragments, outside `Slab`. At the baseline and at each sample the run script reads
`/proc/slabinfo` as root, through L's passwordless sudo: the file has mode 0400
(mm/slab_common.c lines 1098 and 1226; slabinfo(5): "Only root can read"). A cache's size is its
num_slabs × pagesperslab × the page size (slabinfo(5)), a design choice: the unit in which
`Slab` counts the same pages (slabinfo(5) notes that `Slab` holds the memory of these caches).
The growth of the three caches over the baseline is subtracted from the growth of `Slab`, so a
queued skb is counted once, in Kq. Two residuals remain, and the paper names both:
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
detection mode is peek (rule E, I31 E2, and the peek side of 5.7's B3 cells). The first residual
raises that system's W, the second lowers it. Where the competitor leaves bytes queued and the
server reads them, the first biases Q upward, in the server's favour, and the second downward;
where the server leaves them queued and the competitor reads them, both directions reverse. In the
silent case nothing is queued and neither applies.

Merged caches. The kernel may merge a cache with others of the same size (mm/slab_common.c lines
50 to 52 and 155 to 230 at v7.2), and "skbuff_fclone_cache" carries none of the flags that
prevent it (skbuff.c lines 5208 to 5212). `/proc/slabinfo` exists only in a kernel built with
`CONFIG_SLUB_DEBUG` (mm/slab_common.c lines 1097 to 1231). Before the code freeze, L's
`/proc/slabinfo` and `/sys/kernel/slab/` are read for the three names (mm/slub.c lines 9156 to
9160 and 9641 to 9722 at v7.2). A cache merged with others is read under the name that
`/proc/slabinfo` lists for the shared cache, the whole growth of that cache is subtracted, and the
caches merged with it are named in the revision log of `hypotheses.md` at the code freeze (E3)
and in the paper. Whether L's kernel has `/proc/slabinfo` at all is not yet read ("Sources
added", the list of items not verified); B3 as frozen depends on it.

A system's footprint per pending connection is T = U + Kq + (Ks - `K_BASE`) (audit 2 N3): user
memory, the receive queue, and the kernel slab the system adds beyond a bare held socket. The last
term holds the kernel objects that differ by design between the systems. In replay mode on
io_uring each pending connection has an armed `IORING_OP_RECV` (I11, I15), a `struct io_kiocb`
from the slab cache "io_kiocb" (io_uring/io_uring.c line 3257 at v7.2); an epoll registration, as
every competitor and the server's epoll arm make, is an `epitem` from "eventpoll_epi"
(fs/eventpoll.c line 3015 at v7.2) (both via audit 2 N3). The sign of that difference is not
known before it is measured, so it is measured, not left out.

W = T + `K_BASE` = U + Kq + Ks is the counted footprint per pending connection: what these three
readings see, with each queued skb counted once, except as named above. It is the footprint of
each system as configured, not of its detection design alone (audit F10). It is no longer called
whole-system (freeze check FC1): outside it, and said in the paper, are the `f` field, reserved
and unused (above); kernel memory outside `Slab` that no receive queue is charged for; and the
skb-cache memory of the second residual; and the first residual can count bytes twice. The
client ends of the loopback connections are in Ks for every system alike. B3 tests the ratio of
two systems' W (B3).

The kernel's per-socket baseline (audit F2.2). The structures of an accepted TCP socket are paid
alike by every system. They are measured once per host and case-independent, by one procedure
applied to no system in particular: `ophold` accepts `N_PEND` silent connections in the same window
layout and holds them without reading or polling them. Its Ks, net of the skb caches as above, over
16 windows (median) is `K_BASE`, the kernel slab per held connection, both loopback ends included.
Sixteen is a design choice, R_B, the number of sessions per B3 cell (audit 2 N15). Which slab caches
make it up is not claimed; it is measured. Since T + `K_BASE` = W, `K_BASE` cancels from B3's ratio,
(T_comp + `K_BASE`) / (T_srv + `K_BASE`) = W_comp / W_srv, as it cancels from the difference D: no
decision depends on its value. It is reported beside every B3 result as the share of each footprint
that every system pays alike. Because that share holds the client end, which every system pays, it
pulls the ratio toward 1, against the server. Each system's Ks - `K_BASE` is reported as the kernel
objects it adds beyond a bare held socket, such as its poll registrations.

Limits, so that every system can hold `N_PEND` (audit F2.1). Each line is in the system's B3
configuration with its source (section 6):
- Open files. Every process of every system, the generators and `ophold` start with the soft
  `RLIMIT_NOFILE` raised to the hard limit by the run script (`ulimit -n`). Go programs do the
  same themselves since Go 1.19 (Go 1.19 release notes). The hard limit, `fs.nr_open` and
  `fs.file-max` are read on L at the freeze and not changed. Each process's limit must exceed
  `N_PEND` plus its other descriptors. The host's must exceed 2 × `N_PEND` plus the processes'
  other descriptors, since both ends of every loopback connection are on L (audit F27).
- Connection limits: nginx `worker_connections` and `worker_rlimit_nofile` at 2 × `N_PEND`
  (CP1); HAProxy global `maxconn` at 2 × `N_PEND` (CP2); sslh `max_connections` left unset, which
  sets no limit (CP5); Envoy sets no downstream connection limit unless one is configured (CP3);
  the harnesses set none.
- Listen backlogs: `N_PEND` wherever the system has a setting (nginx `backlog=`, HAProxy through
  `maxconn`, Envoy `tcp_backlog_size`, and the Netty, Jetty and hyper-util harnesses). The Go
  systems use `net.core.somaxconn` (net/sock_linux.go at go1.27.1). sslh's is 50, hard-coded, and
  cannot be raised without changing its code (A4); the pace above respects it. The kernel caps
  every backlog at `net.core.somaxconn` (default 4096 since Linux 5.4, ip-sysctl docs), which is
  read at the freeze and not changed. The pace keeps the accept queue far below every cap.
- Overflows: a B3 window is invalid if `TcpExtListenOverflows` or `TcpExtListenDrops` (nstat)
  changed during it (ST10).

Buffers (audit 2 N2). In each competitor, documented settings size what a pending connection
holds in user space; section 6 names them per system. The rule, a design choice: a default is
changed for B3 only where the project documents a value for a deployment that faces many
untrusted connections, or documents that the buffer grows on demand, so that a smaller start
refuses no input the default accepts. Otherwise the default is kept, and section 6 says why.
Under this rule Envoy's B3 configuration changes two buffer settings, and HAProxy's adds one
option that should not touch a pending connection (section 6). The server's own bounds are those
of I15, and are reported beside every B3 cell.

Runtimes with a collector (audit F2.3, F2.4). Before each sample:
- the JVM systems get `jcmd <pid> GC.run`, which calls `System.gc()` (jcmd(1)); their heap is
  read with `jcmd <pid> GC.heap_info` and reported beside U;
- the cmux harness calls `debug.FreeOSMemory`, which forces a collection and then returns as much
  memory to the operating system as possible (runtime/debug docs), and reports
  `runtime.MemStats.HeapInuse`;
- caddy-l4 gets a heap-profile request with `gc=1` at its admin endpoint, which runs a collection
  before the sample (Caddy profiling docs).
The collectors and heap settings are those of CP6 to CP8.

`N_PEND` = 10,000 (Q10, a design choice). Every system's detection timer is 60 s in B3 runs (S7).

WL8. Hard-case runs (section 4.2). Per case: the outcome, the transcript, and the decision time,
from the server's counters against `opcase`'s write times on the same clock.

### 4.2 Hard cases

Each case runs on every backend, in both detection modes, with in-process and relay dispatch
where it applies, and 16 replicates. Sixteen is a design choice: the cases are deterministic, so
one deviation fails B1, and the replicates only exercise the timing variation of arrival (audit
F27). The table of expected outcomes is frozen with the hypotheses.

| Id | Case | Expected outcome for the server |
|---|---|---|
| HC1 | The whole signature in one write, for HTTP/1.1, h2c, TLS, MQTT 3.1.1, MQTT 5.0 and SSH | classified; the transcript equals the dedicated port's |
| HC2 | Split signature: two writes, split after byte k, for every k from 1 to the matcher's `need` minus 1, `GAP_SPLIT` apart | as HC1 |
| HC3 | Drip: one byte per write, the whole signature arriving before T_dec | as HC1 |
| HC4 | Slow drip: a partial signature that is still incomplete at T_dec | closed at T_dec, "undecided" (S6 d) |
| HC5 | Silent client, SMTP fallback configured; then an SMTP client script | greeting after T_fb; the transcript equals the dedicated SMTP port's (S6 a, c) |
| HC6 | Silent client, no fallback | closed at T_dec, "silent" (S6 f) |
| HC7 | HTTP/1.1 client whose first byte is written at T_fb + G, SMTP fallback; and its twin whose first byte is written at T_fb - G. `G` is set per host by the timer part of the A/A pilot, in dedicated mode, above the largest timer lateness it observed on any backend of that host, so above its 99th percentile, and below T_fb (ST13 step 8; audit F12; audit 2 N13) | the first goes to the fallback, and its request gets 500 from the SMTP handler (S6 g); the twin is HTTP/1.1 |
| HC8 | SMTP client that sends EHLO before any greeting | rejected at once: no matcher starts with E (S6 e) |
| HC9 | PROXY v2 header, then an HTTP/1.1 request, in one write | header consumed; the source address the server records equals the header's; HTTP/1.1 response |
| HC10 | PROXY v2 header split after every byte k inside it, then HTTP/1.1 | as HC9 |
| HC11 | PROXY listener, no header, plain HTTP/1.1 | closed at once: the header is required, never guessed |
| HC12 | PROXY v2 header incomplete, then silence | closed at T_hdr |
| HC13 | PROXY v1 line, then a TLS ClientHello | TLS |
| HC14 | PROXY v2 with TLVs, at most 536 bytes, then MQTT; and one longer than 536 bytes | MQTT; rejected (I9) |
| HC15 | PROXY header complete, then silence, SMTP fallback | greeting T_fb after the header completed |
| HC16 | The h2 preface with the byte at position k replaced by its bitwise complement (b XOR 0xFF), for every k from 0 to 23 | rejected when byte k arrives. Every complement of a preface byte is at least 0x80, and no matcher's first-byte set holds such a byte; after the first byte, the HTTP/1.1 matcher has already rejected "PR". Derived from I8 and checked at compile time by I7's corpus (audit F25). |
| HC17 | One leading CRLF, then HTTP/1.1; and two leading CRLFs | HTTP/1.1; rejected (I8 accepts at most one) |
| HC18 | SSH identification line with a comment after a space | SSH |
| HC19 | ClientHello with record version `03 01`, and with `03 03` | TLS |
| HC20 | ClientHello fragmented across two TLS records, in two writes | in-process: the handshake completes; pass-through: routed by its SNI |
| HC21 | Peer shuts down writing after a partial signature; and after no byte | closed at once, "undecided"; closed at once, "silent" (S6 h; no wait for T_dec) |
| HC22 | Peer resets during detection | state freed; counters consistent; no leak under the sanitizer records |
| HC23 | 4,096 bytes starting `GETX`; 4,096 bytes of `A` | rejected at the first impossible byte; no budget exceeded. The length is a design choice, far beyond B_dec, so a detector that waited for a budget instead of rejecting would show it (audit F27) |
| HC24 | MQTT CONNECT with a Remaining Length of 1, 2, 3 and 4 bytes; MQTT 3.1 `MQIsdp` | MQTT for the four; rejected (S8) |
| HC25 | `GET key` and CRLF, as a Redis inline command | HTTP/1.1, answered 400 |

The competitors run the cases their features cover (A4), with matched timeouts, and once at
their defaults, with `R_COMP_CASES` = 3 replicates per case and setting, a design choice: their
table is descriptive. A run on a system that never decides a case (cmux without
`SetReadTimeout`, hyper-util, the Netty example: no detection timer) is observed for at most
`T_OBS` = 60 s and recorded as "no decision within `T_OBS`". `T_OBS` is a design choice: twice the
longest default timer among the others (nginx `preread_timeout` and Jetty's idle timeout, 30 s;
survey 2.1, Jetty modules docs) (audit F26). Their outcomes are tabulated against the same table
and against their own documentation. That table is descriptive and tests nothing.

## 5. Hypotheses and statistics

### 5.1 Session design

ST1. A session is four windows of the two arms of a cell in mirrored order, X Y Y X. Which arm
is X is drawn per session from the order generator (ST9). Each window starts fresh processes
(server, backend if any, generator), checks one exchange of each protocol the cell uses (the
probe), then runs a 1 s warm-up and a 5 s measured window. These are the T1 defaults of
`lab/t1/t1.py` and the design of P2's H6 (`papers/typed-routing/hypotheses-round2.md`). B3
windows have the fixed layout of WL7 instead.

ST2. An arm's value in a session is the mean of its two windows. The session's ratio is
arm / reference, with the direction each hypothesis states. In B3 the session's statistic is
Q, the ratio of the two arms' counted footprints W, competitor / server (B3).

ST3. Placement: disjoint cores on loopback, the SMT sibling of every server core idle (LB2,
LB3).

ST4. Fixed R per family (5.6): R_C for the cost family, sized from the A/A pilot (ST13);
R_B = R_M = 16. There is no sequential stopping. A session with an invalid window (ST10) is
discarded and run again at the end of the order, at most ⌈R/4⌉ times per cell, a design choice
that bounds the time (4 at R = 16; audit F27). A cell with fewer than R valid sessions cannot pass
and enters Holm with p = 1. Beside every decision, the paper reports the cell's invalid windows
per arm, with their reasons, so that a defect of one arm is not hidden by a rerun (audit 2 N7).

### 5.2 Statistics shared by all families

ST5. Cell statistic: the median of the R session ratios (in B3, of the R session values of Q).

ST6. Clustered BCa interval, as in P2 (`hypotheses-round2.md`, section 5): 10,000 resamples of
the sessions, drawn with replacement. The cluster is the session: both arms' windows stay
together. The bias correction z0 counts ties as half; the acceleration comes from the jackknife
over sessions; the share of resamples beyond a bound is clipped to [1/(2B), 1 - 1/(2B)],
B = 10,000. The one-sided p-value against a bound is the level α at which the bound of the
1 - 2α interval equals it. With z0 and the acceleration at 0, the smallest BCa p is about 5.0e-5
(P2, section 5). That holds only at z0 = 0: under the two one-sided tests of ST12 the floor is
Φ(Φ⁻¹(1/(2B)) + 2|z0|), so at B = 10,000 a cost cell can pass α/36 only if |z0| < 0.347 (audit
F1, F20). These two figures hold for even R, where the jackknife acceleration of a median is 0
(P2, section 5). For odd R = 2k + 1 the leave-one-out medians take three values and the
acceleration can reach 1/(6 sqrt(k(k + 1)(2k + 1))) in magnitude. On the unfavourable side the
floor at z0 = 0 then rises to 8.6e-5 at R = 11, and the |z0| limit falls to 0.289 at R = 11,
0.311 at 15, 0.330 at 25 and 0.335 at 31 (audit 2 N4). The sizing simulation of ST13 runs this
computation as it is, so its power figures already include these effects.

ST7. Exact sign test: X counts the sessions whose ratio lies strictly on the
hypothesis side of the bound; a tie counts against. Under the null at its boundary, X is binomial
with R and 1/2; p = P(X ≥ x), computed exactly. In the cost family the sign test is the binding
computation: at Holm's first threshold it allows fewer sessions beyond a bound than the BCa
needs. The methods say so (audit F3).

ST8. Holm's step-down per family, at family-wise α = 0.025, one-sided, as in P2 (its section 5),
run separately for each of the two computations. A cell passes only if it passes under both. If
they disagree, both are reported and the cell does not pass. A cell that cannot be tested enters
with p = 1.

ST9. Order. All sessions of one family's cells on one host run in one shuffled order, so that
drift in time spreads over the cells (audit F21). The B3 order also holds B3's descriptive and
secondary cells, which share its window layout. The other secondary cells run in one order per
host. Seeds:
- orders: `SEED_ORDER_C_L`, `SEED_ORDER_C_W`, `SEED_ORDER_B_L`, `SEED_ORDER_M_L`,
  `SEED_ORDER_M_W`, `SEED_ORDER_S_L`, `SEED_ORDER_S_W` (S for the secondary cells; audit 2 N5);
- resampling: `SEED_BOOT_C`, `SEED_BOOT_B`, `SEED_BOOT_M`, `SEED_BOOT_S`, one generator per
  family. Each cell of the family's list (B3's descriptive cells after its Holm cells) draws its
  resamples once, in the family's order, whether or not it is in Holm. Every other interval, those
  of 5.7, draws from `SEED_BOOT_S`, bullet by bullet in the order of 5.7; the cost cells not
  resolved and B3's descriptive cells keep their family's draws and draw nothing more. Within a
  bullet the cells follow the cost family's order of ST13 step 3 (hypothesis, host, backend,
  protocol), then the system in the order of section 6; a case, variant or form that the bullet
  names comes after the protocol, in the order the bullet names it; within a cell, the metrics
  follow the order the bullet names them. A bullet that covers cells of a family's list (the cost
  cells' CPU and memory, the analyses clustered by lab job of ST11) takes them in that list's
  order, family by family (freeze check FC8). A cell with fewer than R valid sessions draws
  nothing;
- the pilot: `SEED_PILOT_L`, `SEED_PILOT_W` (the order of the pilot's sessions) and `SEED_SIM`
  (the simulation of ST13).
Every seed is fixed in one revision-log entry before the code freeze (I31 E4), so before any
window of the frozen code, and each is checked against the lab journal as used by no earlier
run. No seed is changed after that entry.

ST10. A window is invalid, and is listed with its reason, if:
- the server, the backend or the probe failed, or no exchange completed;
- on L, the error share exceeded 0.1%, the generator's CPUs were more than 90% busy in a
  saturation cell, or the mean CPU MHz drifted more than 2% from the session's value (the rules of
  `lab/t1/t1.py`, as P2's H6 used them);
- on W, the rules of LB3 that can be computed there (audit F13);
- any connect failed (address or port exhaustion, RK2);
- any connection was classified other than as its script's protocol (I29). This is also a
  server defect, whatever the window: it is reported as a failure of B1, in the way 5.8 reports
  B1 failures, and not only as a reason to run the session again (audit 2 N7);
- in a B3 or `ophold` window, any rule of WL7's sample phase (the settling check, the TIME-WAIT
  count, the established count);
- in hand-off cells, a backend core was more than 90% busy, a design choice by analogy with the
  generator rule, not a rule of `t1.py` (audit F27);
- in an open-loop window, fewer than 99% of the exchanges due in it completed (WL2; audit F11);
- in the cost family, M1, M2 and B3, `TcpExtListenOverflows` or `TcpExtListenDrops` changed during
  the window (audit F6). In M3 the proxies keep their own backlogs (Q20), so overflows there are
  recorded and reported beside each cell instead (M3).
Recorded per window, deciding nothing: the TIME-WAIT count at start and end, the change of
`TcpExtTCPTimeWaitOverflow`, the source-address block, and on W the power plan and the timer
resolution (LB5).

ST11. Independence. Sessions are separate process lifetimes at different times, and nothing
passes between them; the analysis treats them as independent. Each family runs as one or more
lab-locked jobs; the job of each session is recorded, and an analysis clustered by job is
reported. It decides nothing.

ST12. Equivalence (cost family only). The margin is fixed from relevance, not from data. Alex
set it on 2026-10-02: the widest difference he still calls "no measurable cost" is a ratio
between 0.98 and 1.02, for C1, C2 and C3, on L and on W (section 11.1). It replaces the
pilot-derived margins of the first version (audit F1, F3, F4).
- Each cell has two one-sided nulls: "the median ratio is at most 0.98" and "it is at least
  1.02". Each is tested at α = 0.025 by both computations.
- Sign test: X_low counts the sessions whose ratio is above 0.98, X_high those whose ratio is
  below 1.02; a session exactly at a bound counts against.
- BCa: the lower test uses the share of resamples below 0.98, the upper test the share above 1.02
  (ST6).
- A computation's p-value for the cell is the larger of its two one-sided p-values. This is the
  two one-sided tests procedure. Before Holm's adjustment, the BCa form passes at 0.025 exactly
  when the two-sided 95% BCa interval lies inside [0.98, 1.02].
- Cells are decided at Holm's thresholds, not at 0.025. So beside the 95% BCa interval, each cost
  cell shows the two-sided BCa interval at level 1 - 2α_j, where α_j = 0.025 / (m_C - j + 1) and
  j is the cell's rank among the family's BCa p-values (ties in the family's order). A 95%
  interval inside the margin on a cell that fails Holm is then not read as a contradiction
  (audit 2 N6).
- The bounds are used as Alex stated them. On the log scale they are not symmetric (log 0.98 =
  -0.0202, log 1.02 = 0.0198).
Why this is not a superiority test in disguise: the null of each cell is that the ratio lies
outside the margin; a cell passes only when both one-sided nulls are rejected. A noisy cell, or
one with too few valid sessions, fails. A difference that is merely not significant never counts
as equivalence.

ST13. Sizing R_C from an A/A pilot. The pilot only sizes R; it sets no margin.
1. The pilot. Every cell of C1 to C3 on its host runs P = 16 sessions of ST1, a design choice
   (the count of the first version and of P2), with both arms in dedicated mode: two separate
   starts of the same binary and flags. The second start's listeners are shifted by a fixed port
   offset, so that every window transition changes port as in the A/B design (audit F6). No
   one-port data enters it. It runs on the frozen binary at step 4 of I31 E4, in an order shuffled
   with `SEED_PILOT_L` or `SEED_PILOT_W`, the C1 and C2 cells of a host before its C3 cells
   (WL2). It is development data and never a result. Reruns (audit F4; audit 2 N1, N5; freeze
   check FC2, FC3):
   - Within the pilot, a session with a window that is invalid by a rule of ST10 is discarded and
     run again at the end of the pilot's order, at most ⌈P/4⌉ = 4 times per cell, the rule of ST4.
     A cell that still has fewer than P valid sessions is not resolved (step 5).
   - The whole pilot may be run again at most once, and only before the simulation of I31 E4
     step 5 starts: if an infrastructure fault stopped it (the host failed, the lab lock was
     lost, the run script crashed), or if a named failure forced a change of the frozen code (a
     failing test, a sanitizer record that is not green, the gate refusing a build, or a crash of
     a first-party program), recorded with its evidence in the revision log, and the new build has
     new records (I31 E4). The abandoned pilot is archived, named in the revision log with its
     reason, and not used. The repeat uses the same seeds, as P2 restarted a stopped run. The
     cutoff is the simulation's start, not the pilot entry, so that no repeat can be decided with
     R_C and the resolved list in view.
   - Once the simulation has started, no pilot session runs again, for any reason.
   - If the cap is spent, or the repeat is itself stopped, the pilot entry is made from the last
     pilot: a cell without P valid sessions is not resolved, and a timer run or split replicate
     that did not take place counts as excluded (step 8). A further code change then follows the
     rule for a later change (I31 E4).
2. The per-cell rule. For cell c, y_i is the log of session i's ratio, i = 1 to P.
   - Centre: e_i = y_i - median(y). Power is then computed at a true ratio of 1, not at the
     pilot's chance offset.
   - Spread: s is the standard deviation of the e_i (divisor P - 1). The bandwidth factor is
     b = 0.9 × min(1, IQR(e)/(1.34 s)) × P^(-1/5), Silverman's rule of thumb (Silverman 1986,
     p. 45; see "Sources added") divided by s. The upper bound s_U = s × sqrt((P - 1) / q), where
     q is the 0.20 quantile of the chi-square distribution with P - 1 degrees of freedom: the
     one-sided 80% upper confidence bound for the standard deviation under normality. For P = 16,
     q = 10.307 and s_U = 1.2064 s.
   - One simulated run of R sessions: draw z_1 to z_R with replacement from the e_i / s, add to
     each an independent normal draw with standard deviation b, and multiply by
     s_U / sqrt(1 + b²). This is a smoothed bootstrap scaled toward the variance s_U². A draw
     from the P values e_i / s has variance (P - 1)/P, since s uses the divisor P - 1. So the
     simulated sessions have a variance of 0.9375 to 0.9507 of s_U², by the size of b, and a
     standard deviation about 3% below s_U (audit 2 N5). The rule is kept as it is, so that
     Appendix A still describes it. Simulated values can lie beyond the pilot's extremes, so the
     result is not set by the pilot's largest deviation (audit F1 item 3). The session ratios are
     the exponentials of the draws.
   - Each run is analysed by the confirmatory analysis code itself: both computations of ST12 at
     [0.98, 1.02], the BCa with B = 10,000 resamples, the same count as the real test, and the
     sign test. The run passes if both p-values are at most α/36 = 6.94e-4, Holm's first
     threshold for the full family.
   - Power_c(R) is the share of `N_SIM` = 1,000 runs that pass. `N_SIM` is a design choice; its
     Monte Carlo standard error at 0.80 is sqrt(0.80 × 0.20 / 1,000) = 0.0126 (audit 2 N15).
3. Random streams (audit 2 N5). Every draw of the simulation follows from `SEED_SIM`:
   - The cost cells are numbered c = 1 to 36 in the family's order: C1, C2, C3; within each, the L
     cells before the W cells; backends in the order epoll, io_uring, IOCP; within a backend,
     HTTP/1.1, h2c, TLS, MQTT.
   - Run j of cell c (j = 1 to `N_SIM`) draws its sessions from one stream seeded by the tuple
     (`SEED_SIM`, c, j): first 31 indices with replacement, then 31 normal draws. The run at a
     candidate R uses the first R sessions of that draw. So every candidate sees the same draws
     (common random numbers), and the estimates differ between candidates only through R.
   - The BCa resamples of run j at candidate R come from one stream seeded by (`SEED_SIM`, c, j,
     R).
   - So no result depends on the order in which cells, runs or candidates are computed. The code
     is the analysis code at `ANALYSIS_COMMIT` (I31 E4), which pins its library versions.
4. Candidate values of R. Between the D9 minimum, 11, and 32, the sign test's allowed number of
   sessions beyond each bound rises only at R = 11, 15, 18, 22, 25, 28 and 31 (5.6). Between two
   of these values an added session can only lower the sign test's pass rate. The candidates are
   these seven values. R = 32 allows no more sessions beyond a bound than R = 31, so it is never
   chosen.
5. Resolved, defined once (audit 2 N5). The power target is 0.80, a design choice, the value the
   audit's analysis used. A cell is resolved if it has P valid pilot sessions and
   Power_c(31) ≥ 0.80. Otherwise it is "not resolved": it would need R above 32. Each resolved
   cell's own R_c, the smallest candidate with Power_c(R) ≥ 0.80, is reported.
6. The family's R_C is the smallest candidate at which every resolved cell has
   Power_c(R) ≥ 0.80. By the definition of "resolved", R = 31 always qualifies, so R_C exists.
   If no cell is resolved, R_C = 31 and m_C = 0.
7. The family after the pilot. A cell that is not resolved leaves the confirmatory family at the
   pilot entry. It still runs at R_C and is reported with its interval as "not resolved at
   R ≤ 32", and the claim narrows: no equivalence is claimed for that metric, protocol, backend
   and host. m_C is the number of resolved cells. R was sized at α/36; a smaller family only
   raises Holm's thresholds, so the power of the resolved cells does not fall, and the D9 minimum
   for the smaller family is at most 11. Beside R_C, the entry reports for each protocol, backend
   and host whose C1, C2 and C3 cells are all resolved the product of their three Power_c(R_C):
   the simulated power of the claim "no measurable cost" there. The cells are simulated
   independently, so the product is their joint pass rate under the simulation's model. It is
   reported, not targeted (audit 2 N6).
8. Rates, timers and splits, all from dedicated mode (audit 2 N13).
   - Rates. The C1 pilot sessions give the open-loop rate λ of WL2 for each C3 cell.
   - Timer part. On each backend of the host, 128 runs, one connection at a time, of HC12's
     script (a PROXY v2 header that stays incomplete, then silence) against the dedicated HTTP/1.1
     port with the PROXY setting on, which dedicated mode keeps (I20). Each run waits for
     T_hdr = 3 s in the deadline queue of I13, the queue T_fb uses in one-port mode. The statistic
     is each run's lateness: the time from the deadline to the start of the loop pass that handled
     it, from the counters of I29. G for the host (`G_L`, `G_W`) is the smallest whole number of
     milliseconds above the largest lateness of all the host's valid runs, so it is above their
     99th percentile. If the host has no valid run, or G is not below T_fb, HC7 is not run on that
     host, and the paper says why.
     128 runs per backend is a design choice, the number of the server's runs per timer case on
     L in 9.2.
   - Split part. On each backend of the host, HC2's HTTP/1.1 script split after its first byte,
     against the dedicated HTTP/1.1 port, 16 replicates at each tested gap of 5, 10, 20, 50 and
     100 ms. The gaps are a design choice, a 1-2-5 series; 16 is the replicate count of the hard
     cases (4.2). A replicate shows the split read when the counters of its one connection show
     two receives that returned payload. `GAP_SPLIT` is the smallest tested gap at which every
     valid replicate on every backend of L and of W shows it, each backend having at least one
     valid replicate at that gap. If none does, `GAP_SPLIT` = 100 ms, and HC2, HC3 and HC10 report
     the share of their replicates whose counters show the split.
   - Both parts run after the pilot's sessions on that host. They are development data and set
     G and `GAP_SPLIT` only.
   - Failed runs of the parts (freeze check FC4). A timer run or split replicate whose server or
     `opcase` failed is excluded and listed in the pilot entry. The parts run again only with the
     whole pilot, under the cap of step 1. The two cases this leaves empty are closed: a host with
     no valid timer run has no G, and HC7 is not run on it; a tested gap at which some backend has
     no valid replicate does not qualify for `GAP_SPLIT`.
9. The pilot entry (audit 2 N1). One revision-log entry of `hypotheses.md`, made from the
   pilot's and the simulation's outputs alone, is committed before any one-port window of the
   frozen code. It needs both hosts' pilots, since R_C and m_C span L and W. It records:
   `CODE_FREEZE`; `ANALYSIS_COMMIT`; the sha256 of the pilot's archive; the pilot's invalid
   windows and reruns, and its excluded timer runs and split replicates; each cell's Power_c at
   every candidate and its R_c; the resolved list; R_C; m_C; the joint powers of step 7; λ for
   each C3 cell; `G_L` and `G_W`; `GAP_SPLIT`; and,
   named again, the IOCP receive form of rule E.
   Nothing in it is chosen: every value follows from the rules above.
Appendix A checks the rule of steps 2 to 6 on synthetic data.

### 5.3 Cost family

Cells: protocol p in {HTTP/1.1, h2c, TLS with HTTP/1.1, MQTT} and backend b in {epoll and
io_uring on L, IOCP on W}, 12 per hypothesis (8 on L, 4 on W). Arms: one-port mode against
dedicated mode (A2). Session ratio: one-port / dedicated. Load: one protocol per cell (S2).
Margin: [0.98, 1.02] in every cell (ST12). Replicates: R_C sessions per cell (ST13).

C1. Churn throughput is equivalent. In every cell, the median ratio of connections per second
under WL1 lies inside [0.98, 1.02], by ST12.

C2. Keep-alive throughput is equivalent. In every cell, the median ratio of requests per second
under WL3 lies inside [0.98, 1.02], by ST12. Both modes run the same code once a connection is
classified (I3), so C2 is likely to pass. It is kept: Alex set its margin together with C1's and
C3's, and it is the test that one-port mode leaves no cost per request (audit F23).

C3. Latency at a fixed load is equivalent. In every cell, the median ratio of median TTFB under
WL2 lies inside [0.98, 1.02], by ST12.

m_C = 3 × 12 = 36 cells at most; fewer if ST13 finds cells not resolved.

### 5.4 Robustness family

B1. Conformance, deterministic, not in the Holm family. For every hard case, backend, detection
mode, applicable dispatch mode and replicate, the server's outcome and transcript equal the
frozen expected table of section 4.2. One deviation fails B1. B1 is not narrowed: a deviation
means the server is not done.

B2. Bounded behaviour, deterministic, not in the Holm family:
- (a) Never early: no fallback, close or deadline event happens before its deadline on the
  server's clock (with the clock check of I13).
- (b) Each deadline is handled in the first loop pass whose wait returned at or after it
  (I13 records both).
- (c) Each connection is classified in the loop pass that received its deciding byte.
- (d) No pending connection holds more user-space payload bytes than its mode's bound in I15,
  and a pending connection that has received no byte holds no data buffer.
- (e) A half-close before a decision closes the connection in the pass that observes it (S6 h).
The lateness of timed events and the decision latency are reported per backend as
distributions. They are not tested: they include the operating system's timer behaviour, which
P3 does not claim to control.

B3. Footprint per pending connection, in the Holm family. B3 compares counted footprints per
pending connection, W of WL7, each system as configured for B3 in section 6, not detection
designs alone (audit F10). "Counted" means W = U + Kq + Ks, with Ks in W and in `K_BASE` net of
the skb caches' growth, so a queued skb is counted once, in Kq; the exclusions and the two
residuals that WL7 names are stated beside the results (audit 2 N3; freeze check FC1). The test
and Alex's margin of 1.10 are unchanged by that correction.
- The margin. Alex decided on 2026-10-02 that a cell counts as a win only if
  (T_comp + `K_BASE`) / (T_srv + `K_BASE`) is at least 1.10, where `K_BASE` is the kernel
  per-socket memory common to all systems (Q22, section 11.1; audit 2 N2). By WL7 this ratio is
  W_comp / W_srv. The decision was taken before any B3 window ran, feasibility windows included.
- Session statistic: Q = W_comp / W_srv, each arm's W the mean of its two windows (ST2). A session
  whose W_srv is 0 or less has no ratio: it takes Q = 0 in both computations, below every bound,
  so it counts against (freeze check FC6).
- Cell statistic: the median of the R_B = 16 session values of Q (ST5).
- The test: superiority against the ratio margin 1.10. The null of each cell is "the median Q is
  at most 1.10". Both computations:
  - the exact sign test (ST7): X counts the sessions whose Q is strictly above 1.10; a session at
    1.10, or without a ratio, counts against; p = P(X ≥ x), with X binomial with 16 and 1/2;
  - the clustered BCa (ST6): 10,000 resamples of the sessions; p is the level α at which the lower
    bound of the two-sided 1 - 2α interval equals 1.10, with the share of resamples below 1.10
    clipped to [1/(2B), 1 - 1/(2B)].
  Holm's step-down runs over the 18 cells at family-wise α = 0.025, one-sided, once for each
  computation (ST8). A cell passes only if it passes under both. A cell with fewer than 16 valid
  sessions enters with p = 1. At R = 16 the D9 condition holds: 2^-16 = 1.53e-5 < 0.025/18.
- Reported beside each cell, deciding nothing: both footprints W and their parts U, Kq and
  Ks - `K_BASE`; the skb caches' growth subtracted from each Ks; `f`; `K_BASE`; the difference
  D = W_comp - W_srv, which equals T_comp - T_srv, in bytes per pending connection, with its 95%
  BCa interval; the median Q with its 95% BCa interval and with the interval at the level Holm
  used for the cell (ST12's rule, on B3's BCa ranks); the sign-test count; and the server's
  bounds of I15.
- The server runs in relay mode against the proxies and in in-process mode against the libraries,
  in its default detection mode.
- Wording (audit 2 N2, N10). A pass is written "the competitor held at least 1.10 times the
  server's counted footprint per pending connection, by B3's test", always with D and its
  interval, and with WL7's exclusions and residuals named. A cell that fails is "not shown".
  "Loss" is used only where the 95% BCa interval of Q lies wholly below 1.00, and it is a
  description, not a test.
Holm cells:
- the silent case, against nginx, HAProxy, Envoy, sslh-ev and hyper-util (5);
- the partial-ClientHello case, against nginx, HAProxy, Envoy and sslh-ev (4); hyper-util serves
  no TLS (A4);
- each on the server's two Linux backends, epoll and io_uring.
m_B = (5 + 4) × 2 = 18 cells.
Descriptive cells, outside Holm (Q19): the systems whose runtime has a collector, Netty and Jetty
(JVM) and caddy-l4 and cmux (Go), in both cases on both backends: 4 × 2 × 2 = 16 cells. They run
with the same sessions, R and statistic Q, are reported with their BCa intervals and sign-test
counts against 1.10, and decide nothing. They measure the runtime as much as the detector, and
the paper says so (audit F10). The competitors are Linux programs, so B3 runs on L only.

### 5.5 Mechanism family

M1. The default detection mode is cheaper. In-process, churn (WL1), the session ratio
connections per second (default mode) / (other mode) is above 1.00 in every cell of {HTTP/1.1,
h2c} × {epoll, io_uring, IOCP}: 6 cells. The proposed default is replay (I12); rule E fixes it
per backend after the pilot entry, on the frozen binary, before any confirmatory window (I31 E2),
and M1's direction follows it. M1's sessions are new data, not the development sessions of rule
E. On IOCP the peek mode includes the
switch to replay after an undecided peek (I11). The counters report how often it happened, and
the paper says that M1 on IOCP measures the API's limits as much as the idea (RK5).

M2. In-process dispatch costs less than relay. The session ratio of server CPU per connection
(WL6), in-process / relay, is below 1.00 in every cell of {HTTP/1.1, TLS} × {epoll, io_uring}:
4 cells. The relay arm passes TLS through to a backend that terminates it (I18), so both arms
make one handshake per connection. The rate of each cell comes from its slower arm, and both
arms use one placement (WL6).

M3. The server's relay is faster than each proxy. With one front core and the stub backend
(I18), churn (WL1), the session ratio of connections per second, server / proxy, is above 1.00
in every cell of {TLS routed by SNI, plaintext HTTP/1.1} × {nginx, HAProxy, Envoy, caddy-l4,
sslh-ev}: 10 cells. The server runs on epoll, the accept model all five proxies use. Fairness
(audit F9):
- Routes. Every system runs its M3 configuration (section 6), which holds exactly two routes and
  no other: TLS by SNI to one stub port, everything else to the HTTP/1.1 stub port. The SSH, MQTT
  and PROXY routes of the case configurations are not in it (audit 2 N9). What each system
  examines to choose differs: nginx tells TLS from not-TLS (survey 2.1); the server runs its
  whole table. The paper states this beside each cell.
- Logging of connections is off in every system, and the bookkeeping that stays on is matched:
  Envoy's statistics against the server's counters (CP1 to CP5).
- Accept. nginx gets `multi_accept on`, so it drains the accept queue per event as the server
  does (I5). Listen backlogs stay as each system sets them (Q20); sslh's is 50. Listen overflows
  are recorded per window and reported beside each cell, above all beside each cell that fails.
- Splice. HAProxy gets `option splice-auto` only if the server's relay splices (I17).
- The headline is closed-loop throughput. The Envoy benchmarking FAQ prefers open-loop
  generators; M3's open-loop TTFB is a secondary result (5.7).
- Wording (audit 2 N10). A cell that fails is "not shown". "Loss" is used only where the 95% BCa
  interval of the ratio lies wholly below 1.00, and it is a description, not a test.

m_M = 6 + 4 + 10 = 20 cells.

### 5.6 Replicates and family sizes (rule D9)

D9 asks for an R at which an exact paired test can pass the family's Holm threshold
(2^-R < α/m). The A/A pilot sizes R only for the cost family. It cannot size a superiority
family: power there depends on an effect size that nothing in this design sets. So R_B and R_M
are 16, P2's reference, between their D9 minimum and 32.

| Family | m | Holm's first threshold α/m | D9 minimum R | R |
|---|---|---|---|---|
| Cost | 36 at most (ST13) | 6.94e-4 | 11 (2^-11 = 4.88e-4) | R_C in {11, 15, 18, 22, 25, 28, 31}, from the pilot (ST13) |
| Robustness (B3) | 18 | 1.39e-3 | 10 (2^-10 = 9.77e-4) | 16 |
| Mechanism | 20 | 1.25e-3 | 10 (2^-10 = 9.77e-4) | 16 |

Cost family. Sessions allowed beyond each bound at α/36, with the exact one-sided p of that count
and of one more:

| R_C | Allowed beyond each bound | p at that count | p at one more |
|---|---|---|---|
| 11 | 0 | 1/2048 = 4.88e-4 | 5.86e-3 |
| 15 | 1 | 16/32768 = 4.88e-4 | 3.69e-3 |
| 18 | 2 | 172/262144 = 6.56e-4 | 3.77e-3 |
| 22 | 3 | 1794/4194304 = 4.28e-4 | 2.17e-3 |
| 25 | 4 | 15276/33554432 = 4.55e-4 | 2.04e-3 |
| 28 | 5 | 122438/268435456 = 4.56e-4 | 1.86e-3 |
| 31 | 6 | 942649/2147483648 = 4.39e-4 | 1.66e-3 |

The count applies to each one-sided test: one session beyond the lower bound and another beyond
the upper bound leave each test with one session out, and the larger of the two p-values decides.
At R = 32 the allowed count is still 6 (p = 1,149,017/2^32 = 2.68e-4; 7 out gives 1.05e-3), as
the audit found (F3).

Robustness and mechanism families, at R = 16. The smallest exact one-sided p is
2^-16 = 1.53e-5. One session on the wrong side of the bound gives p = 17/65536 = 2.59e-4, which
clears α/m in every cell of both families. Two give 137/65536 = 2.09e-3, which clears Holm's
threshold α/k only for k ≤ 11. Three give 697/65536 = 1.06e-2, which clears it only for k ≤ 2.
"Clears for k ≤ n" counts how many cells may have that count and still pass when every other
cell has a smaller p. The smallest BCa p, about 5.0e-5, holds only at z0 = 0 (ST6).

### 5.7 Secondary results, not in any Holm family

Secondary cells that need sessions run at R = 16, a design choice (P2's reference). Each is
reported with its 95% BCa interval where it has one, and decides nothing:
- CPU per connection or request and resident memory for every C cell (WL4); p99 TTFB (WL2);
- cost cells that ST13 finds not resolved, at R_C (ST13);
- the SSH cells of the cost family, C1 to C3 on three backends (9 cells), with the order change
  of I28; their C1 sessions run before their C3 sessions, which take their rate from them (WL2;
  audit 2 N12);
- the mixed-protocol cell (audit F7): C1's HTTP/1.1 churn with a fixed background of TLS
  keep-alive, MQTT keep-alive and silent connections, the same background in both modes
  (dedicated mode spreads it over its ports), on each backend (3 cells). The background's sizes,
  `N_BG_TLS`, `N_BG_MQTT` and `N_BG_SILENT`, are set in engineering before the freeze;
- TLS with session resumption and TLS with ALPN `h2`, C1 on each backend (6 cells);
- 2 server cores (Q11): C1 HTTP/1.1 on each backend (3 cells); and on epoll and io_uring the
  `SO_REUSEPORT` group against the shared listener, both in one-port mode (2 cells). The 4-core
  cells are dropped: they would leave `opgen` 1.5 logical CPUs per server core (audit F14);
- the server's relay on io_uring against the proxies (10 cells);
- on IOCP, on a listener without a fallback (gap 8), against the default form, which is AcceptEx
  with no receive buffer (`dwReceiveDataLength` = 0, I5) followed by the receive form rule E
  chose (I11, I31 E2) (2 cells): AcceptEx with a receive buffer; and the receive form rule E did
  not choose (the zero-byte `WSARecv` or the posted buffer), after the same AcceptEx. If rule E
  chooses the posted buffer, the second cell is the zero-byte `WSARecv` against it, so no cell
  compares a form with itself (freeze check FC7);
- operations and copies per connection for every mode and backend (I29), and system calls per
  connection for the proxies (WL5);
- for M1 and M3, TTFB at a fixed load (WL2), 16 cells; for every M cell, CPU per connection (WL4)
  from its windows. So each mechanism contrast also reports setup latency and CPU;
- B3 with the server in its other detection mode against its default mode, in both cases on
  both Linux backends (4 cells), with B3's statistic Q (other mode / default mode); a session
  whose default-mode W is 0 or less takes Q = 0, as in B3;
- B3's descriptive JVM and Go cells (B3);
- the competitors' outcomes on the hard cases, at matched timeouts and at their defaults;
- the lateness and decision-latency distributions of B2.

### 5.8 What counts against the claims

- C: a cell that fails is reported with its interval as "equivalence not shown" on that
  protocol, backend and host. It is called a measured cost only where its 95% BCa interval lies
  wholly outside [0.98, 1.02]. "No measurable cost" is claimed only in the form "equivalent
  within [0.98, 1.02]", for single-protocol load, and only for the protocol, backend and host
  where C1, C2 and C3 all pass (audit F5). Each such claim quotes the simulated joint power of
  ST13 step 7 and the intervals at Holm's level (ST12; audit 2 N6). Cells that ST13 finds not
  resolved are named as such.
- B1 and B2: not narrowed; a failure in any run of the frozen code, including a misclassified
  connection in any measured window (ST10), is reported as a failure, and the robustness claim is
  not made.
- B3: narrowed to the competitors and cases where it passes. Each pass is written as B3 says,
  with D and its interval; a cell that fails is "not shown"; "loss" only as B3 defines it (audit
  2 N10).
- M1 and M2: reported per backend as measured. A cell that fails shows only that a difference was
  not shown. The paper does not read it as "costs nothing extra" (audit F5).
- M3: narrowed to the proxies and protocols where it passes; a cell that fails is "not shown";
  "loss" only as M3 defines it (audit 2 N10).
- Order (Alex, 2026-10-02). The cost family leads the paper. If a family cannot be won cleanly
  (D2), the claims narrow in this order: M3 first, to the proxies and protocols the server beats;
  then B3, to the competitors and cases it beats; then the cost family, per backend.

## 6. Competitors and pins

The survey's versions are used unless a newer release exists at the code freeze. Each pin change
is listed then, in the revision log of `hypotheses.md`. Every configuration file is in
`bench/competitors/`, every line with its reason. In M3 every front gets one core (LB2). In B
every competitor gets the server's core count. Logging of individual connections is off in every
system (Q20; audit F9.1). Each proxy has three configurations (audit 2 N9):
- cases: every route its features cover (A4), the matched timers, and the fallback where it has
  one;
- M3: exactly M3's two routes and no other (M3);
- B3: the M3 configuration, plus the limits of WL7, the 60 s detection timer and the buffer
  settings below.
Each library harness has two, cases and B3. Its B3 configuration starts from its case
configuration, since the libraries have no M3 configuration.

Buffers in B3 (audit 2 N2; the rule of WL7, a design choice). For each system, the documented
settings that size what a pending connection holds, and what B3 does with them:

| System | Settings that size what a pending connection holds | In B3 |
|---|---|---|
| nginx | `preread_buffer_size`, default 16k, "a size of the preread buffer" (stream core module docs); `proxy_buffer_size`, default 16k, which also "sets the size of the buffer used for reading data from the client" (stream proxy module docs) | Defaults kept. The docs give no value for many pending connections and describe no growth, and a full preread buffer ends the session (survey 2.1). A smaller buffer would refuse ClientHellos that the default accepts. |
| HAProxy | `tune.bufsize`, default 16384: "Lower values allow more streams to coexist in the same amount of RAM" (configuration.txt v3.4.6 line 4208); `tune.maxrewrite` (line 5002); `option use-small-buffers` (line 12180) | `tune.bufsize` and `tune.maxrewrite` kept: the same paragraph says "It is strongly recommended not to change this from the default value". `option use-small-buffers` is set, with no parameter, in the backends; it cannot be set in a frontend (line 6286). It saves memory on queued requests, L7 retries and health checks and falls back to a regular buffer when data are too large (line 12180). A pending connection has none of these, so it should change nothing B3 measures; it is set so that no documented memory saving is left out. |
| Envoy | the listener's `per_connection_buffer_limit_bytes`, a soft limit, default 1 MiB (listener.proto v1.39.2); tls_inspector's `initial_read_buffer_size`, which defaults to the maximum of 16 KiB, and from which "the filter will double the buffer" up to that maximum (tls_inspector.proto v1.39.2); http_inspector has no setting (its proto message has no fields) | Configured. `per_connection_buffer_limit_bytes` 32768 on the listener and on the cluster: the docs' edge page says "TCP proxies should configure" listener and cluster buffer limits of 32 KiB (best practices, v1.39.2). `initial_read_buffer_size` 256, the smallest value the proto accepts (`gt: 255`), a design choice: the buffer doubles on demand, so no ClientHello that the default accepts is refused. The edge page's other TCP items, restricting the admin endpoint and the overload manager, protect or limit and size nothing a connection holds. They are not configured, so no overload action can close pending connections. |
| caddy-l4 | none: `prefetchChunkSize` 2048 and `MaxMatchingBytes` 16 KiB are constants in the code (survey 2.7), and docs/servers.md documents only `matching_timeout` | Nothing to configure. Descriptive cells (Q19). |
| sslh-ev | none: probing reads into `BUFSIZ` bytes of the C library and keeps the bytes in a queue that grows with `realloc` (survey 2.8) | Nothing to configure. |
| Netty | `ChannelOption.RECVBUF_ALLOCATOR` and `ChannelOption.ALLOCATOR` (ChannelOption.java at netty-4.2.18.Final). The base configuration's receive allocator is `AdaptiveRecvByteBufAllocator`, minimum 64, initial 2048 and maximum 65536 bytes (DefaultChannelConfig.java line 75; AdaptiveRecvByteBufAllocator.java lines 34 to 37). Which allocator the native epoll transport uses is read at the code freeze. | Defaults kept: no Netty document read gives a value for many pending connections. Descriptive cells (Q19). |
| Jetty | `jetty.httpConfig.inputBufferSize`, default 8192, and the `bytebufferpool` module's properties (Jetty 12.1 standard modules docs); `DetectorConnectionFactory` reads into a buffer of `IO.DEFAULT_BUFFER_SIZE` = 8192 (survey 2.16) | Defaults kept: the modules page gives no value for many pending connections. Descriptive cells (Q19). |
| cmux | none: each connection's `bufferedReader` keeps what the matchers read (survey 2.10) | Nothing to configure. Descriptive cells (Q19). |
| hyper-util | none for detection: `ReadVersion` fills a fixed 24-byte buffer (survey 2.12) | Nothing to configure. |

| Id | System and pin | Families | Configuration, with its source |
|---|---|---|---|
| CP1 | nginx 1.30.5, stream module with `ssl_preread`, built from the release tag | B, M3 | `worker_processes 1` and `worker_cpu_affinity` on the front core: the docs call the number of available CPU cores "a good start". The event method is left to nginx, which picks the most efficient one; on Linux that gives epoll with RDHUP and so the peek path (survey 2.1). `ssl_preread on`; `map $ssl_preread_server_name` to the upstreams; non-TLS traffic to the HTTP upstream, as in the docs' example (survey 2.1). `preread_timeout` matched (default 30s) and `proxy_protocol_timeout` matched (default 30s). `multi_accept on`: off by default, and when on a worker accepts all new connections at a time (core module docs; audit F9.3). Logging: the stream module writes no access log unless one is configured, and none is (audit F9.1). B3: `worker_connections` and `worker_rlimit_nofile` at 2 × `N_PEND`, since `worker_connections` counts connections to proxied servers too and cannot exceed the open-file limit, which `worker_rlimit_nofile` raises (core module docs); `listen ... backlog=N_PEND`, whose default on Linux is 511 (stream core module docs). Sources: nginx.org core module and stream core module docs. |
| CP2 | HAProxy 3.4.6 | B, M3 | `mode tcp`; `tcp-request inspect-delay` matched; `tcp-request content accept` on `req.ssl_hello_type 1`; `use_backend` on `req.ssl_sni`, `req.proto_http`, `req.payload(0,4)` for `SSH-`, and `mqtt_is_valid`; `default_backend` for the fallback (survey 2.3). One thread on the front core: on platforms with CPU affinity, `nbthread` defaults to the number of CPUs the process is bound to at startup, so `taskset` sets it (configuration.txt v3.4.6 line 3115; audit F30). The `cpu-map` text is quoted at the freeze. Logging: HAProxy logs only through `log` lines, and none is configured (audit F9.1). `option splice-auto`, "not enabled by default" (line 11720), only if the server's relay splices (I17). Backlog as HAProxy sets it: it passes the frontend's `maxconn` to `listen()` (line 6383). B3: global `maxconn` at 2 × `N_PEND`: unset, it is computed from the descriptor limits, and a frontend's `maxconn` defaults to the global value (lines 3951 and 9717; audit F2.1). |
| CP3 | Envoy 1.39.2, the release binary (Q15) | B, M3 | From the docs' benchmarking FAQ: a release binary; `--concurrency` set to the cores the other proxies get (here 1); circuit breaking disabled (cluster limits raised); filter chains only for the compared features. Listener filters tls_inspector and http_inspector, and proxy_protocol in the PROXY cases; filter chains by `server_names`, `transport_protocol` and `application_protocols`; tcp_proxy. `listener_filters_timeout` matched; `continue_on_listener_filters_timeout` true only in the fallback cases (survey 2.5). No access log is configured. Envoy's default statistics stay on, as the server's counters stay on (I29): the bookkeeping is matched. The FAQ's other items, disabling `generate_request_id` and `dynamic_stats`, are fields of the HTTP connection manager and the router filter (their v1.39.2 protos), which a tcp_proxy chain does not contain (audit F9.2). B3: `tcp_backlog_size` `N_PEND` (default `net.core.somaxconn` on Linux, listener.proto v1.39.2); no downstream connection limit is configured, and none applies by default: Envoy then warns at startup that there is no global limit (overload manager docs, v1.39.2); `listener_filters_timeout` 60 s. |
| CP4 | caddy-l4 v0.1.2 = commit 42db5690dea199f930a6f08005fe2e4aab10dcc9, on Caddy v2.11.4 (its `go.mod`), built with xcaddy and go1.27.1 | B, M3 | The layer4 app: routes with the tls (SNI), http, ssh and regexp matchers and the proxy handler; `matching_timeout` matched (survey 2.7). The Go runtime takes GOMAXPROCS from the CPU affinity mask (Go runtime docs, go1.27.1), so `taskset` on the front core sets it to 1. Logging: caddy-l4 logs connections at Debug (layer4/server.go lines 192 and 210; audit F9.1), and Caddy runs at a level above Debug. Go raises its own open-file limit (Go 1.19 release notes). B3: backlog from `net.core.somaxconn` (net/sock_linux.go at go1.27.1); before each sample, a heap profile with `gc=1` at the admin endpoint runs a collection (Caddy profiling docs); `matching_timeout` 60 s. Descriptive in B3 (Q19). **Pin risk:** the README warns that the app is in development and may break (survey 2.7). The commit is pinned and read again at the freeze; any change of behaviour is a new pin, logged. |
| CP5 | sslh 2.3.1, the `sslh-ev` binary | B, M3 | doc/INSTALL.md: sslh-ev uses libev to manage thousands of connections, and sslh-select, which it resembles, uses one thread. Probes: tls with `sni_hostnames`, http, ssh, and a regex probe for MQTT (built with `ENABLE_REGEX`, survey 2.8). `timeout` matched (whole seconds); `on-timeout` names the fallback in the fallback cases. `verbose-connections: 0`: the code default is 3 (sslhconf.cfg), which writes a line per connection to stderr and to syslog (log.c; audit F9.1). The listen backlog is 50, hard-coded (common.c line 152 at v2.3.1). B3: `max_connections` left unset on the listen entry and on every protocol: it is optional and has no default (sslhconf.cfg), and doc/max_connections.md describes it as the way to limit connections, so unset means no limit; the open-file limit is raised as for every system (WL7); `timeout` 60. |
| CP6 | Netty 4.2.18.Final | B | A harness after the `PortUnificationServerHandler` example, with Netty's built-ins: `SniHandler`, `CleartextHttp2ServerUpgradeHandler`, `HAProxyMessageDecoder`, the HTTP codec (survey 2.15). The native epoll transport: the Netty wiki says native transports "generally improve performance when compared to the NIO based transport". `ReadTimeoutHandler` matched (it has no default). The JDK is the latest LTS release at the freeze, pinned then (Q18). Collector and heap: Netty documents no collector or heap setting (Netty wiki searched on 2026-10-02). So the JDK vendor's documented default for a server-class machine is used: G1 (Oracle JDK 25 GC tuning guide, "Ergonomics", re-read for the pinned JDK at the freeze). It is selected explicitly with `-XX:+UseG1GC`, because the JVM picks the Serial collector unless it detects two or more processors and at least 1792 MB, and B pins the JVM to one core (same guide; audit F2.4). The heap bounds are the same guide's defaults, initial 1/64 and maximum 1/4 of physical memory, written out as `-Xms` and `-Xmx` from L's MemTotal at the freeze. B3: the harness sets `ChannelOption.SO_BACKLOG` to `N_PEND` (Netty's default, `NetUtil.SOMAXCONN`, reads `/proc/sys/net/core/somaxconn`; NetUtil.java at netty-4.2.18.Final). Descriptive in B3 (Q19). |
| CP7 | Jetty 12.1.13 | B | `DetectorConnectionFactory` with `SslConnectionFactory` and `ProxyConnectionFactory`, then HTTP/1.1 with the h2c upgrade (`HTTP2CServerConnectionFactory`), as the programming guide's I/O architecture section describes (survey 2.16). Idle timeout matched (default 30000 ms, Jetty 12.1 standard modules docs). Collector and heap as CP6: Jetty's operations guide documents no collector or heap size (standard modules page, 12.1). B3: `acceptQueueSize` `N_PEND` (0 picks the platform default, ibid.). Descriptive in B3 (Q19). |
| CP8 | cmux v0.1.5 on go1.27.1 | B | Matchers `HTTP2()`, `HTTP1Fast()`, `TLS()`, `PrefixMatcher("SSH-")`, and `Any()` last for the fallback; `SetReadTimeout` matched (survey 2.10). GOMAXPROCS from the affinity mask. The collector at Go's documented defaults: GOGC 100 when the variable is unset, and no memory limit (runtime/debug docs). B3: backlog from `net.core.somaxconn` (net/sock_linux.go at go1.27.1); the harness calls `debug.FreeOSMemory` before each sample. Descriptive in B3 (Q19). |
| CP9 | hyper-util 0.1.21 | B | `server::conn::auto` on a tokio runtime with one worker thread (survey 2.12). It has no detection timer; nothing is added. Cases: HTTP/1.1 and h2c only. B3: the harness listens through tokio's `TcpSocket::listen` with backlog `N_PEND` (tokio docs). |

Also pinned: OpenSSL (I23), nghttp2 (I26), clang 22.1.8 on L, MSVC 19.51.36246 on W (the
compilers of P2's records, `hypotheses-round2.md` section 1), go1.27.1 on L, and the Rust
toolchain, JDK and xcaddy versions read at the freeze. Downloads go into `~/opt` on L from the
official release URLs, each with its sha256 (LB1). Go net/http alone is not an arm: it tells only
HTTP/1 from h2c (survey 2.11), while cmux runs on it and splits several protocols (survey 2.10).

## 7. Sanitizer coverage (rule D5)

Z1. Records, made with `lab/bin/sanitize.sh` and `sanitize.ps1`:
- `oneport-<commit>-L-asan` (ASan with UBSan), `-L-tsan` and `-L-msan`, clang 22.1.8 on L. The
  MSan build uses an MSan-instrumented libc++, as P1's does;
- `oneport-<commit>-W-asan`, MSVC 19.51.36246 on W. One compiler, because the gate matches the
  compiler (audit F15.6). clang-cl is not used: P1's design notes a clang-cl stack-use-after-return
  false positive (P1 4.6; lab evidence `2026-09-26-clangcl-asan-uar-false-positive`).
Each record covers the targets `oneport`, `opgen`, `opcase`, `ophold` and the test suite, by
inputs hash (`lab/bin/inputs_hash.py`).

Z2. The test suite in every record runs: the detection table on its corpus at every split; the
whole hard-case catalogue against the server at short test timeouts; every mode of the binary,
one-port, dedicated and stub, since all three are measured arms (audit F15.1); both detection
modes, with the peek paths of I11 (the `SO_RCVLOWAT` set and reset, the io_uring poll with
`POLLRDHUP`, the IOCP switch to replay, the half-close of S6 h); the check of S6(b) in both its
forms, the peek and the non-waiting reap, with a byte that arrives in the pass of the expiry; both dispatch modes with a
backend process; the HTTP/1.1 grammar on invalid input in both modes (I20); TLS handshakes; h2
sessions; MQTT, SSH and SMTP exchanges; the counters; `ophold`; and, under TSan, two workers on
the shared listener. On L both Linux backends run; on W, IOCP.

Z3. Third-party C code is built from its pinned source with the record's sanitizer flags:
OpenSSL (its `enable-asan` and `enable-ubsan` options; MSan through `enable-msan`, which in
`Configure` at openssl-3.5.9 also turns assembly off) and nghttp2.
- OpenSSL under TSan is declared as a gap now (Z6). If engineering builds it with TSan and the
  suite passes, the revision log records that and the gap is withdrawn (audit F15.3).
- On W, OpenSSL and nghttp2 are built with MSVC's AddressSanitizer flag. How is settled in
  engineering. A library that cannot be built that way is declared in Z6 before the freeze
  (audit F15.2).

Z4. The gate. The rules of P2's `bench/gate_lib.py` are copied into this repository with
attribution (Q13): a measured build is refused unless green records on the same host cover every
first-party target by inputs hash, with the same compiler, configuration, pins file hash and
fetched archives. Every measured build is gated: the server and backend, the generators, the
holder, and the harnesses.

Z5. Logs stay under `~/lab/records-logs/<record>/`, never `/tmp`, and are archived with a sha256.
The report pattern is the shared one, self-tested by `lab/bin/test_report_pattern.sh`.

Z6. Declared gaps for `bench/coverage.json`:
- **OpenSSL's assembly.** No sanitizer instruments it. `enable-msan` turns assembly off, so MSan
  covers the C fallbacks, not the measured build's assembly paths. The ASan and TSan builds keep
  the assembly, which those sanitizers do not instrument either (audit F15.4).
- **OpenSSL under TSan**, unless withdrawn as Z3 says.
- **io_uring kernel writes are invisible to MSan.** Mitigation from P1: value-initialise every
  structure a raw call fills, and unpoison exactly the `res` bytes a completion reports. For a
  receive into a provided buffer, those bytes are in the selected buffer, which the completion's
  flags name, not in the completion itself; the code unpoisons that buffer's first `res` bytes
  (audit F15.5). A read past `res` in our code would then be hidden, so the tests check `res`
  against the bytes used. The io_uring peek of I11 is a synchronous `recv`, which MSan's
  interceptors see. Unlike P2's binaries, P3's L records must run io_uring.
- **Competitor binaries and runtimes** (nginx, HAProxy, Envoy, caddy-l4, sslh-ev, the JVM, the Go
  runtime, Rust's standard library and tokio): not first-party; pinned, not instrumented.
- **The harnesses** (Java, Go, Rust) are first-party but not C++. The Go and Rust harnesses get
  ASan+UBSan and TSan records, built the way P2's records built its Go and Rust arms
  (`papers/typed-routing/hypotheses-round2.md`, section 1: ASan and TSan covered every arm, and
  only MSan left out the FFI arms). Only their MSan gap is declared, the gap rule D5 names as its
  example. None of the three sanitizers applies to the Java harnesses; that gap is declared
  whole.
- **Windows:** only ASan is required (D5).

## 8. Lab

LB1. L does the Linux runs at T1: loopback, disjoint cores, `lab/bin/pin.sh` (boost off, the
performance governor, mains power), each run under `lab/bin/lablock`. L is frozen: kernel 7.2.3,
clang 22.1.8, go1.27.1 (`papers/typed-routing/hypotheses-round2.md`, section 1). No update and no
reboot. Alex allows (2026-10-02): pinned user-space downloads into `~/opt` from official release
URLs, each with its sha256 recorded; and `pacman -S` for missing tools, never `-Syu`. Every tool
the design needs is read on L at the freeze and never assumed. Machine time on L is as long as the
design needs (section 9).

LB2. Core layout on L, the SMT sibling of each used core idle, as in P2's H6. CPUs 0 and 1 run
the system and the driver.
- In-process cells: the server on CPU 14 (CPU 15 idle); `opgen` on CPUs 2 to 13.
- Hand-off cells: the front on CPU 14 (15 idle); the backend on CPUs 10 and 12 (11 and 13
  idle); `opgen` on CPUs 2 to 9. M2's in-process arm uses this layout too, with CPUs 10 to 13
  idle (WL6).
- 2-core secondary cells: the server on CPUs 12 and 14 (13 and 15 idle); `opgen` on CPUs 2 to 11.
- B3 and hard cases: the system under test, or `ophold`, on CPU 14, with its backend, where it
  has one, on CPUs 10 and 12; `opcase` on CPUs 2 to 9.

LB3. W does the IOCP runs, on loopback, only in windows that Alex frees (section 11.1). The
server runs on one logical CPU of the last physical core, its sibling idle; `opgen` uses the
cores between core 0 and the server's. The sibling sets are read from the system at each run.
Strawberry Perl and NASM may be installed at user level to build OpenSSL (I23). W's procedure is
defined in engineering before the freeze and approved by Alex (Q6): the power plan, the boost
policy, the timer resolution, and a CPU frequency check from a Windows performance counter, named
and tested in engineering against a known load. If no counter passes that test, W windows are
validated without the frequency rule, on the other rules of ST10, and the paper says so (audit
F13). The power plan and the timer resolution are recorded per window.

LB4. No LAN subnet is used. Rule D7 is not exercised.

LB5. Port exhaustion and TIME-WAIT. On L the kernel reuses TIME-WAIT sockets for loopback by
default (`tcp_tw_reuse` = 2, "enable for loopback traffic only", with `tcp_tw_reuse_delay` 1000 ms;
ephemeral range 32768 to 60999 by default; docs.kernel.org ip-sysctl). These values,
`tcp_max_tw_buckets` (half the established hash size, so host-dependent; audit F6) and
`net.core.somaxconn` are read on L at the freeze and not changed. `opgen` sets
`IP_BIND_ADDRESS_NO_PORT` and takes a fresh block of source addresses per window (I30), and a
connect failure invalidates the window (ST10). Per window the run records the TIME-WAIT count at
start and end (`ss`), and `TcpExtListenOverflows`, `TcpExtListenDrops` and
`TcpExtTCPTimeWaitOverflow` (nstat) (audit F6). Windows' limits are read on W in the pilot (RK2).

LB6. Raw outputs go under `lab/runs/` and are archived with a sha256 (`lab/README.md`). Numbers
reach the paper only through `results/macros.tex`, generated by `analysis/`.

## 9. Time

Basis. The only measured basis is P2's H6 run on L: 6.63 s per window of 1 s warm-up and 5 s
measurement (`hypotheses-round2.md`, section 10). As in the audit, every row is windows × 6.63 s.
A window here also starts a backend and, in M3, a proxy, so the rate is a floor.
- B3 windows are 30 s by design (WL7). With P2's 0.63 s of start and stop per window they are
  taken as 30.63 s. That is also a floor: a JVM starts more slowly, and closing `N_PEND`
  connections takes time. The B3 feasibility windows measure it first.
- W's window time is assumed equal to L's. W's pilot measures it first.
- R_C is known only after the pilot. The cost rows are given for every candidate, and the totals
  at the smallest and largest, R_C = 11 and R_C = 31.
- Builds, sanitizer records and the ST13 simulation are not machine time on the lab windows and
  are not counted. Nor is the wait of up to 60 s that starts each lab job of B3 or `ophold`
  windows (WL7).

9.1 The cost family's confirmatory windows by R_C (24 cells on L, 12 on W, 4 windows per session):

| R_C | L windows | L time | W windows | W time |
|---|---|---|---|---|
| 11 | 1,056 | 7,001.28 s = 1 h 56 min 41 s | 528 | 3,500.64 s = 58 min 21 s |
| 15 | 1,440 | 9,547.20 s = 2 h 39 min 7 s | 720 | 4,773.60 s = 1 h 19 min 34 s |
| 18 | 1,728 | 11,456.64 s = 3 h 10 min 57 s | 864 | 5,728.32 s = 1 h 35 min 28 s |
| 22 | 2,112 | 14,002.56 s = 3 h 53 min 23 s | 1,056 | 7,001.28 s = 1 h 56 min 41 s |
| 25 | 2,400 | 15,912.00 s = 4 h 25 min 12 s | 1,200 | 7,956.00 s = 2 h 12 min 36 s |
| 28 | 2,688 | 17,821.44 s = 4 h 57 min 1 s | 1,344 | 8,910.72 s = 2 h 28 min 31 s |
| 31 | 2,976 | 19,730.88 s = 5 h 28 min 51 s | 1,488 | 9,865.44 s = 2 h 44 min 25 s |

9.2 Every row (audit F14):

| Part | Run | Host | Windows or waits | Time |
|---|---|---|---|---|
| Primary | Cost family, 24 or 12 cells × R_C × 4 | L, W | 9.1 | 9.1 |
| Primary | Mechanism, 18 cells × 16 × 4 | L | 1,152 | 7,637.76 s = 2 h 7 min 18 s |
| Primary | Mechanism, M1's 2 IOCP cells × 16 × 4 | W | 128 | 848.64 s = 14 min 9 s |
| Primary | B3, 34 cells × 16 × 4 (18 Holm cells: 1,152 windows; 16 descriptive cells: 1,024) | L | 2,176 at 30.63 s | 66,650.88 s = 18 h 30 min 51 s |
| Primary | `K_BASE` with `ophold`, 16 windows | L | 16 at 30.63 s | 490.08 s = 8 min 10 s |
| Pilot | A/A pilot, 24 cells × 16 × 4 | L | 1,536 | 10,183.68 s = 2 h 49 min 44 s |
| Pilot | A/A pilot, 12 cells × 16 × 4 | W | 768 | 5,091.84 s = 1 h 24 min 52 s |
| Pilot | Timer and split parts (ST13 step 8), dedicated mode, waits only: timer, 2 backends × 128 runs × 3 s = 768 s; split, 2 backends × 16 replicates × (5 + 10 + 20 + 50 + 100) ms = 5.92 s | L | 773.92 s | 773.92 s = 12 min 54 s |
| Pilot | The same on IOCP: timer, 128 × 3 s = 384 s; split, 16 × 185 ms = 2.96 s | W | 386.96 s | 386.96 s = 6 min 27 s |
| Pilot | B3 feasibility, after the pilot entry: one window per system and case (11 systems silent, 10 partial), development data | L | 21 at 30.63 s | 643.23 s = 10 min 43 s |
| Secondary | 40 cells × 16 × 4: SSH 6, mixed 2, TLS resumption and `h2` 4, 2 cores 2, `SO_REUSEPORT` 2, relay on io_uring 10, open-loop TTFB for M1 4 and M3 10 | L | 2,560 | 16,972.80 s = 4 h 42 min 53 s |
| Secondary | Untimed counter checks: one per cost cell (24) and `perf trace` of the proxies (10) | L | 34 | 225.42 s = 3 min 45 s |
| Secondary | B3, the server's other detection mode, 4 cells × 16 × 4 | L | 256 at 30.63 s | 7,841.28 s = 2 h 10 min 41 s |
| Secondary | 11 cells × 16 × 4: SSH 3, mixed 1, TLS resumption and `h2` 2, 2 cores 1, open-loop TTFB for M1 2, IOCP accept forms 2 | W | 704 | 4,667.52 s = 1 h 17 min 48 s |
| Rerun, at most | Cost family, 24 or 12 cells × ⌈R_C/4⌉ × 4 | L | 288 (R_C = 11) to 768 (R_C = 31) | 1,909.44 s = 31 min 49 s to 5,091.84 s = 1 h 24 min 52 s |
| Rerun, at most | Cost family | W | 144 to 384 | 954.72 s = 15 min 55 s to 2,545.92 s = 42 min 26 s |
| Rerun, at most | Mechanism, 18 × 4 × 4 | L | 288 | 1,909.44 s = 31 min 49 s |
| Rerun, at most | Mechanism, 2 × 4 × 4 | W | 32 | 212.16 s = 3 min 32 s |
| Rerun, at most | B3, 34 × 4 × 4 | L | 544 at 30.63 s | 16,662.72 s = 4 h 37 min 43 s |
| Rerun, at most | Secondary, 40 × 4 × 4 and B3 secondary 4 × 4 × 4 | L | 640, and 64 at 30.63 s | 4,243.20 s + 1,960.32 s = 6,203.52 s = 1 h 43 min 24 s |
| Rerun, at most | Secondary, 11 × 4 × 4 | W | 176 | 1,166.88 s = 19 min 27 s |
| Rerun, at most | A/A pilot, 24 × 4 × 4 (ST13 step 1; audit 2 N5) | L | 384 | 2,545.92 s = 42 min 26 s |
| Rerun, at most | A/A pilot, 12 × 4 × 4 | W | 192 | 1,272.96 s = 21 min 13 s |
| Hard cases | The server, timer waits only: 5 cases (HC4, HC5, HC6, HC12, HC15) × 128 runs (4 backend and dispatch pairs × 2 modes × 16) × 3 s = 1,920 s; HC7's late run waits 3 s + G, at most 128 × 6 s = 768 s, since G < T_fb (audit 2 N13); HC7's twin waits under 3 s, at most 128 × 3 s = 384 s | L | 1,920 s + at most 768 s + at most 384 s | at most 3,072 s = 51 min 12 s |
| Hard cases | The same on IOCP: 5 × 32 runs × 3 s = 480 s; HC7 late at most 32 × 6 s = 192 s; twin at most 32 × 3 s = 96 s | W | 480 s + at most 192 s + at most 96 s | at most 768 s = 12 min 48 s |
| Hard cases | Competitors, upper bound, 6 timer cases × 3 replicates each: matched timers, 8 systems × 3 s = 432 s and hyper-util at `T_OBS` = 1,080 s; defaults (nginx 30 + Envoy 15 + Jetty 30 + sslh 5 + caddy-l4 3 + HAProxy 0, since with no `inspect-delay` set HAProxy does not wait (survey 2.3; audit 2 N15), + cmux, hyper-util and the Netty example 60 each = 263 s) × 18 = 4,734 s | L | 6,246 s | at most 1 h 44 min 6 s |
| Development | After the pilot entry, on the frozen binary: rule E's default detection mode and relay copy on epoll and io_uring, 4 choices × 6 sessions × 4 = 96; M2's rates (WL6), 4 cells × 6 sessions × 4 = 96 | L | 192 | 1,272.96 s = 21 min 13 s |
| Development | Rule E on the frozen binary: the IOCP receive form before the W pilot, in dedicated mode, and the default detection mode after the pilot entry, 2 choices × 6 × 4 | W | 48 | 318.24 s = 5 min 18 s |

The hard cases that wait on `GAP_SPLIT` (HC2, HC3, HC10) and the cases that decide at once add
time that depends on `GAP_SPLIT`, at most 100 ms per gap (ST13 step 8). The competitors' bound counts every
timer case for every system, although some cases do not apply to some systems (A4).

9.3 Totals by part:

| Part | L, R_C = 11 | L, R_C = 31 | W, R_C = 11 | W, R_C = 31 |
|---|---|---|---|---|
| Primary | 81,780.00 s = 22 h 43 min 0 s | 94,509.60 s = 26 h 15 min 10 s | 4,349.28 s = 1 h 12 min 29 s | 10,714.08 s = 2 h 58 min 34 s |
| Pilot | 11,600.83 s = 3 h 13 min 21 s | the same | 5,478.80 s = 1 h 31 min 19 s | the same |
| Secondary | 25,039.50 s = 6 h 57 min 19 s | the same | 4,667.52 s = 1 h 17 min 48 s | the same |
| Rerun, at most | 29,231.04 s = 8 h 7 min 11 s | 32,413.44 s = 9 h 0 min 13 s | 3,606.72 s = 1 h 0 min 7 s | 5,197.92 s = 1 h 26 min 38 s |
| Hard cases, at most | 9,318.00 s = 2 h 35 min 18 s | the same | 768.00 s = 12 min 48 s | the same |
| Development | 1,272.96 s = 21 min 13 s | the same | 318.24 s = 5 min 18 s | the same |
| **Total** | **158,242.33 s = 43 h 57 min 22 s** | **174,154.33 s = 48 h 22 min 34 s** | **19,188.56 s = 5 h 19 min 49 s** | **27,144.56 s = 7 h 32 min 25 s** |

B3 takes most of L's time: 18 h 31 min of primary windows and up to 4 h 38 min of reruns. Each
second added to a B3 window by start or teardown adds 2,176 s = 36 min 16 s to the primary B3 run.
Totals at the other candidates of R_C: L 44 h 50 min 25 s (15), 45 h 32 min 51 s (18), 46 h 25 min
53 s (22), 47 h 8 min 19 s (25), 47 h 40 min 8 s (28); W 5 h 46 min 20 s (15), 6 h 7 min 33 s
(18), 6 h 34 min 4 s (22), 6 h 55 min 17 s (25), 7 h 11 min 12 s (28).

Measured before the rest can be fixed: W's window time, R_C, `GAP_SPLIT` and `G` (the pilot, in
dedicated mode, before the pilot entry); the B3 window's start and teardown (the feasibility
windows, after it).

## 10. Risks

RK1. Cells not resolved. The A/A pilot may show that a cell cannot reach 80% power at the 2%
margin with R ≤ 32 (ST13). That cell leaves the confirmatory family at the pilot entry, and the
claim narrows.

RK2. Port exhaustion under churn, worst on W, where the TIME-WAIT and ephemeral-port limits are
not yet read. Mitigation: source addresses spread over 127.0.0.0/8 with
`IP_BIND_ADDRESS_NO_PORT`, a fresh block per window, who-closes-first fixed per protocol, and
invalid windows on any connect failure. If W cannot sustain churn without errors, its C1 and C3
cells cannot pass, and the paper says why.

RK3. A proxy may beat the server's relay, HAProxy above all. Rule D2: engineer first, before the
code freeze (I31 E1); then report each cell that fails as "not shown", a loss only where M3's
wording allows it, and narrow M3.

RK4. The io_uring peek (I11) rests on poll respecting `SO_RCVLOWAT`, derived from the source. If
the test fails, io_uring takes IOCP's rule: after the first undecided peek, the connection
switches to replay. The revision log says so.

RK5. Windows has no low-water mark, so an undecided IOCP peek switches to replay (I11). M1 on
IOCP then measures the API as much as the idea, and the paper says so.

RK6. The TLS handshake dominates TLS churn, so the TLS cost cells are close to certain to pass
and tell little (I25). They are not to be read as evidence about the 6-byte check.

RK7. caddy-l4 may change behaviour between commits (CP4). It is pinned by commit and read again
at the freeze.

RK8. Downloads and builds on a frozen L (Envoy's binary, the JDK, Maven artifacts, Go modules,
Rust crates, nginx, HAProxy and sslh sources with their headers). They go into `~/opt` with a
sha256, or through `pacman -S` without `-Syu` (LB1). A competitor that cannot be installed under
these rules is dropped, named, with the reason; its cells enter Holm with p = 1.

RK9. JVM and Go memory depend on the collector and the heap policy. B3 states both (CP6 to CP8),
forces a collection before each sample, and reports the live heap beside RSS (WL7). Their B3
cells are descriptive.

RK10. sslh-ev's probe timeout may not fire on an idle connection: the survey found no ev_timer
covering probing connections (survey 2.8). Its timer cases are reported as observed.

RK11. Copying P1's loop: P1 may change during its own review. P3 copies a fixed commit and
records it; later P1 changes are not followed.

RK12. Family sizes are fixed: m_B = 18 and m_M = 20 at the hypotheses freeze, m_C by the pilot
entry (ST13 step 9). A cell that cannot run enters Holm with p = 1.

RK13. The pilot's noise must match the confirmatory run's. The port offset of ST13 gives the
pilot the A/B design's port transitions, and the upper confidence bound of ST13 allows for a
pilot that understates the noise. If the confirmatory sessions are noisier still, cells fail
without any cost being present; the paper reports their intervals and claims no equivalence
there.

RK14. B3's opening. A system may overflow its accept queue at B3's pace (WL7), a JVM during a
collection above all. Such windows are invalid and are run again (ST4). A system that cannot hold
`N_PEND` without overflow within ⌈R/4⌉ reruns cannot pass, and the paper says why.

RK15. The 2-core secondary cells leave `opgen` 10 logical CPUs for two server cores, against 12
for one in the primary cells. The generator rule of ST10 may invalidate them. They are
secondary.

## 11. Decisions and open questions

### 11.1 Decisions taken on 2026-10-02

"Alex" marks the author's binding decisions. "Default" marks the audit's default, applied as
the author instructed.

| Q | Decision | By | Applied in |
|---|---|---|---|
| Q1 | The cost family leads. If a family cannot be won cleanly (D2), the claims narrow in this order: M3, then B3, then the cost family per backend | Alex | A2, 5.8 |
| Q2 | Margin: a ratio between 0.98 and 1.02 is "no measurable cost", for C1, C2 and C3, on L and on W. It replaces the pilot-derived margins; the pilot only sizes R | Alex | ST12, ST13 |
| Q3 | MQTT is the sixth protocol | Default | S3, S4 |
| Q4 | OpenSSL 3.5 LTS, the latest 3.5 release at the freeze | Default | I23 |
| Q5 | L: pinned user-space downloads into `~/opt` from official release URLs with a sha256; `pacman -S` for missing tools, never `-Syu`; no reboot | Alex | LB1, RK8 |
| Q6, in part | W is used only when Alex frees it. Strawberry Perl and NASM may be installed at user level to build OpenSSL 3.5 with MSVC from the pinned tarball, the version used on L | Alex | LB3, I23 |
| Q7 | No licence for now; the paper repositories stay private until Alex decides. P1's loop is copied with an attribution note in the code. The paper cites P1 only where its text bears on a claim (D8) | Alex | I2 |
| Q8 | Descriptor hand-off is dropped | Default | I19 |
| Q9 | `RATE_FRAC` = 0.5; M2's rate from the slower arm | Default | WL2, WL6 |
| Q10 | 3 s timers; 60 s for B3; `N_PEND` = 10,000; the competitors' limits raised, each with a source | Default | S7, WL7, section 6 |
| Q11 | The 4-core cells are dropped; the 2-core cells and `SO_REUSEPORT` stay as secondary | Default | I4, 5.7 |
| Q12 | SSH is secondary | Default | I28, 5.7 |
| Q13 | P2's gate is copied into this repository | Default | Z4 |
| Q14 | The nine methods (RFC 9110 and PATCH) | Default | I8 |
| Q15 | Envoy is the release binary | Default | CP3 |
| Q16 | R from the pilot, at most 32 | Default, with Q2 | ST13 |
| Q17 | The claim is scoped to single-protocol load; the mixed-protocol cell is secondary | Default | S2, 5.7 |
| Q18 | The JDK is the latest LTS at the freeze; the collector is stated explicitly | Default | CP6, CP7 |
| Q19 | B3's primary statistic was the difference in bytes; since Q22 it is the ratio Q against 1.10, with the difference reported beside it. The JVM and Go cells are descriptive, outside Holm | Default, then Q22 | B3 |
| Q20 | Logging off in every system; backlogs as each system sets them; overflows recorded | Default | section 6, ST10, M3 |
| Q21, in part | Machine time on L is as long as the design needs | Alex | LB1, section 9 |
| Q22 | B3 counts as a win only if (T_comp + `K_BASE`) / (T_srv + `K_BASE`) is at least 1.10 in a cell, `K_BASE` being the kernel per-socket memory common to all systems. Decided before any B3 window ran | Alex, 2026-10-02 | B3, WL7 |

### 11.2 Open questions

Q6. W's procedure and time. Approve the W procedure that engineering drafts (LB3: power plan,
boost policy, timer resolution, frequency counter), and free W for the windows of section 9.3:
5 h 19 min 49 s to 7 h 32 min 25 s at the floor rate, depending on R_C, plus builds and the W
sanitizer record. The pilot entry waits for W's pilot, since R_C and m_C span both hosts
(ST13 step 9).

Q22 is closed (section 11.1).

## Sources added beyond the survey

All read on 2026-10-02.
- WSARecv: `MSG_PEEK` "is valid only for nonoverlapped sockets"; a call with NULL
  `lpOverlapped` and NULL `lpCompletionRoutine` treats the socket as nonoverlapped.
  https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-wsarecv
- recv (Winsock): `MSG_PEEK` in the flags table; `WSAEWOULDBLOCK` on a non-blocking socket.
  https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-recv
- AcceptEx: with `dwReceiveDataLength` = 0 it completes as soon as a connection arrives; with a
  buffer it waits for data; `SO_CONNECT_TIME` returns seconds connected, 0xFFFFFFFF if not
  connected; closing such sockets is recommended.
  https://learn.microsoft.com/en-us/windows/win32/api/mswsock/nf-mswsock-acceptex
- SOL_SOCKET options: `SO_RCVLOWAT` is not supported by the Windows TCP/IP provider; setsockopt
  fails with WSAEINVAL (via audit F8.3).
  https://learn.microsoft.com/en-us/windows/win32/winsock/sol-socket-socket-options
- Wait Functions: a timeout between one and two clock ticks can end after one tick (via audit
  F12). https://learn.microsoft.com/en-us/windows/win32/sync/wait-functions
- epoll_ctl(2), man-pages 6.19: `EPOLLRDHUP` (since 2.6.17), `EPOLLET`, `EPOLLEXCLUSIVE` (since 4.5).
  https://man7.org/linux/man-pages/man2/epoll_ctl.2.html
- socket(7), man-pages 6.19: `SO_RCVLOWAT`, respected by select, poll and epoll since 2.6.28.
  https://man7.org/linux/man-pages/man7/socket.7.html
- IP_BIND_ADDRESS_NO_PORT(2const), Linux 4.2 (via audit F6).
  https://man7.org/linux/man-pages/man2/IP_BIND_ADDRESS_NO_PORT.2const.html
- proc_meminfo(5): `Slab`, "In-kernel data structures cache".
  https://man7.org/linux/man-pages/man5/proc_meminfo.5.html
- liburing man pages, repository master (latest tag liburing-2.15): `io_uring_prep_recv(3)`
  (`IORING_RECVSEND_POLL_FIRST` since 5.19; multishot receive since 6.0, without `MSG_WAITALL`) and
  `io_uring_prep_accept(3)` (multishot accept since 5.19; no `IORING_CQE_F_MORE` means no further
  completions). https://github.com/axboe/liburing/tree/master/man
- Linux v7.2 sources, as the audit read them: `io_uring/net.c` (`msg_flags` read from the
  submission; no special handling of `MSG_PEEK`; the copy inside `sock_recvmsg`, line 1263);
  `include/net/tcp.h` (`TCP_TIMEWAIT_LEN`, line 140; `tcp_epollin_ready`, lines 1823 to 1833);
  `net/ipv4/tcp.c` (`tcp_poll`: `RCV_SHUTDOWN` at lines 583 to 584, `sock_rcvlowat` at line 589).
  https://raw.githubusercontent.com/torvalds/linux/v7.2/
- libuv v1.53.0 `src/win/tcp.c`: the zero-byte `WSARecv` (`UV_HANDLE_ZERO_READ`);
  `FILE_SKIP_COMPLETION_PORT_ON_SUCCESS` at line 189 (via audit F17).
  https://raw.githubusercontent.com/libuv/libuv/v1.53.0/src/win/tcp.c
- Linux networking sysctls (docs.kernel.org, rendered for 7.3.0-rc5): `tcp_tw_reuse` default 2,
  loopback only; `tcp_tw_reuse_delay` default 1000 ms; `ip_local_port_range` default 32768 to
  60999; `somaxconn` "Defaults to 4096. (Was 128 before linux-5.4)"; `tcp_max_tw_buckets`.
  https://docs.kernel.org/networking/ip-sysctl.html
- OpenSSL downloads: 3.5 is the LTS series, latest 3.5.9 (2026-09-29, end of life 2030-04-08);
  4.0.3 is the latest 4.0. https://openssl-library.org/source/ . `Configure` at openssl-3.5.9:
  the `msan` option, and enabling it disables `asm`.
  https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.9/Configure . INSTALL.md: Perl 5
  and make are prerequisites. https://raw.githubusercontent.com/openssl/openssl/master/INSTALL.md
- OpenSSL 3.5.9 man pages `SSL_CTX_set_options`, `SSL_CTX_set_num_tickets`,
  `SSL_CTX_set1_curves` (via audit F16).
  https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.9/doc/man3/
- RFC 8446 s9.1, mandatory-to-implement suites, signatures and groups (via audit F16).
  https://www.rfc-editor.org/rfc/rfc8446.txt
- nghttp2 releases: v1.70.0 is the latest. https://github.com/nghttp2/nghttp2/releases
- Envoy v1.39.2 FAQ, benchmarking: release binary, `--concurrency`, circuit breaking,
  `generate_request_id`, `dynamic_stats` and stats, comparable filter chains, never measuring
  latency at maximum load.
  https://www.envoyproxy.io/docs/envoy/v1.39.2/faq/performance/how_to_benchmark_envoy
- Envoy v1.39.2 `listener.proto`: `tcp_backlog_size` ("If no value is provided
  net.core.somaxconn will be used on Linux"); `listener_filters_timeout` (default 15s).
  https://www.envoyproxy.io/docs/envoy/v1.39.2/api-v3/config/listener/v3/listener.proto
- Envoy v1.39.2 `http_connection_manager.proto`: `generate_request_id` is a field of
  `HttpConnectionManager`, default true.
  https://www.envoyproxy.io/docs/envoy/v1.39.2/api-v3/extensions/filters/network/http_connection_manager/v3/http_connection_manager.proto .
  `router.proto`: `dynamic_stats` is a field of `Router`, default true.
  https://www.envoyproxy.io/docs/envoy/v1.39.2/api-v3/extensions/filters/http/router/v3/router.proto
- Envoy v1.39.2 overload manager: with no downstream connection limit configured there is no
  global limit, and Envoy warns at startup.
  https://www.envoyproxy.io/docs/envoy/v1.39.2/configuration/operations/overload_manager/overload_manager
- nginx core module (`worker_processes`, `worker_cpu_affinity`, `use`, `worker_connections`
  default 512 and counting connections to proxied servers, `worker_rlimit_nofile`, `multi_accept`
  default off) and stream core module (`listen ... reuseport`, `listen ... backlog=` default 511 on
  Linux, `preread_buffer_size` 16k, `preread_timeout` 30s, `proxy_protocol_timeout` 30s).
  https://nginx.org/en/docs/ngx_core_module.html ,
  https://nginx.org/en/docs/stream/ngx_stream_core_module.html
- HAProxy v3.4.6 configuration.txt, as the audit read it: `nbthread` (line 3115), global
  `maxconn` (line 3951), `backlog` (line 6383), frontend `maxconn` (line 9717), `option
  splice-auto` (line 11720).
  https://git.haproxy.org/?p=haproxy-3.4.git;a=blob_plain;f=doc/configuration.txt;hb=refs/tags/v3.4.6
- sslh v2.3.1: `sslhconf.cfg` (`verbose-connections` default 3; `timeout` default 5; `on-timeout`
  default "ssh"; `max_connections`, optional, per listen entry and per protocol, no default);
  `doc/max_connections.md`; `common.c` line 152, `listen (sockfd, 50)` (via audit F2); `log.c` and
  `tcp-listener.c` (via audit F9).
  https://raw.githubusercontent.com/yrutschle/sslh/v2.3.1/
- caddy-l4 v0.1.2 `layer4/server.go` lines 192 and 210, connection logs at Debug (via audit F9).
  https://raw.githubusercontent.com/mholt/caddy-l4/v0.1.2/layer4/server.go
- Caddy profiling: profiles at `/debug/pprof/` on the admin interface; the heap profile takes a
  `gc` parameter that runs a collection first. https://caddyserver.com/docs/profiling
- Netty native transports. https://netty.io/wiki/native-transports.html . Netty
  `NetUtil.SOMAXCONN` reads `/proc/sys/net/core/somaxconn`.
  https://raw.githubusercontent.com/netty/netty/netty-4.2.18.Final/common/src/main/java/io/netty/util/NetUtil.java
- Jetty 12.1 standard modules: `acceptQueueSize` (0 picks the platform default), `idleTimeout`
  default 30000 ms; no collector or heap guidance on the page.
  https://jetty.org/docs/jetty/12.1/operations-guide/modules/standard.html
- Oracle JDK 25 GC tuning guide, Ergonomics: G1 on server-class machines, Serial otherwise;
  server-class means two or more processors and at least 1792 MB; initial heap 1/64 and maximum
  heap 1/4 of physical memory. https://docs.oracle.com/en/java/javase/25/gctuning/ergonomics.html
- jcmd(1), JDK 25: `GC.run` calls `java.lang.System.gc()`; `GC.heap_info`.
  https://docs.oracle.com/en/java/javase/25/docs/specs/man/jcmd.html
- Go runtime, go1.27.1: the GOMAXPROCS default uses the CPU count, the affinity mask and the cgroup
  limit. https://pkg.go.dev/runtime . runtime/debug: GOGC 100 when unset, no memory limit by
  default, `FreeOSMemory`. https://pkg.go.dev/runtime/debug . Go 1.19 release notes: programs that
  import `os` raise the soft `RLIMIT_NOFILE` to the hard limit. https://go.dev/doc/go1.19 .
  `net/sock_linux.go` at go1.27.1: the listen backlog is read from
  `/proc/sys/net/core/somaxconn`. https://raw.githubusercontent.com/golang/go/go1.27.1/src/net/sock_linux.go
- tokio `TcpSocket::listen(backlog)`. https://docs.rs/tokio/latest/tokio/net/struct.TcpSocket.html
- caddy-l4 v0.1.2 `go.mod`: `go 1.25.1`, Caddy v2.11.4.
  https://raw.githubusercontent.com/mholt/caddy-l4/v0.1.2/go.mod
- sslh v2.3.1 doc/INSTALL.md: sslh-select uses one thread with a 16-byte overhead per connection;
  sslh-ev uses libev for thousands of connections.
  https://raw.githubusercontent.com/yrutschle/sslh/v2.3.1/doc/INSTALL.md
- ss(8), iproute2 (page of 2026-08-04): the `skmem` fields of `-m`.
  https://man7.org/linux/man-pages/man8/ss.8.html
- perf-trace(1): `-s`, `--summary`. https://man7.org/linux/man-pages/man1/perf-trace.1.html
- MQTT 3.1.1: CONNACK s3.2 (`20 02`), PINGREQ s3.12 (`C0 00`), PINGRESP s3.13 (`D0 00`),
  DISCONNECT s3.14; the first packet MUST be CONNECT (s3.1); protocol name and level (s3.1.2.1,
  s3.1.2.2). https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html
- Added for audit 2 (N2, N15), read on 2026-10-02:
  - HAProxy v3.4.6 configuration.txt (URL above): `tune.bufsize` (line 4208: default 16384,
    "Lower values allow more streams to coexist in the same amount of RAM", "It is strongly
    recommended not to change this from the default value"); `tune.maxrewrite` (line 5002); the
    keyword table row of `option use-small-buffers`, not allowed in a frontend (line 6286); the
    option itself (line 12180: queue, l7-retries and check; a regular buffer when data are too
    large).
  - nginx stream proxy module: `proxy_buffer_size`, default 16k, also the buffer for reading data
    from the client. https://nginx.org/en/docs/stream/ngx_stream_proxy_module.html . Stream core
    module: `preread_buffer_size`, default 16k, "Specifies a size of the preread buffer" (URL
    above).
  - Envoy v1.39.2, "Configuring Envoy as an edge proxy": TCP proxies should configure admin
    access, the overload manager, and listener and cluster buffer limits of 32 KiB.
    https://www.envoyproxy.io/docs/envoy/v1.39.2/configuration/best_practices/edge
  - Envoy v1.39.2 `listener.proto`: `per_connection_buffer_limit_bytes`, a soft limit, default
    1MiB (URL above). `tls_inspector.proto`: `initial_read_buffer_size` (`gt: 255`, `lt: 65537`;
    the buffer doubles up to 16KiB; unset means the maximum) and `max_client_hello_size`.
    https://raw.githubusercontent.com/envoyproxy/envoy/v1.39.2/api/envoy/extensions/filters/listener/tls_inspector/v3/tls_inspector.proto .
    `http_inspector.proto`: the message has no fields.
    https://raw.githubusercontent.com/envoyproxy/envoy/v1.39.2/api/envoy/extensions/filters/listener/http_inspector/v3/http_inspector.proto
  - caddy-l4 v0.1.2 docs/servers.md: `matching_timeout` is the documented server setting.
    https://raw.githubusercontent.com/mholt/caddy-l4/v0.1.2/docs/servers.md
  - Netty netty-4.2.18.Final: `ChannelOption.java` (`RECVBUF_ALLOCATOR`, `ALLOCATOR`);
    `DefaultChannelConfig.java` line 75 (`AdaptiveRecvByteBufAllocator` by default);
    `AdaptiveRecvByteBufAllocator.java` lines 34 to 37 (64, 2048, 65536).
    https://raw.githubusercontent.com/netty/netty/netty-4.2.18.Final/transport/src/main/java/io/netty/channel/
  - Jetty 12.1 standard modules (URL above): `jetty.httpConfig.inputBufferSize=8192` and the
    `bytebufferpool` module's properties.
  - Silverman's rule of thumb, h = 0.9 min(σ, IQR/1.34) n^(-1/5): B. W. Silverman, Density
    Estimation for Statistics and Data Analysis, Chapman & Hall, London, 1986, p. 45,
    ISBN 978-0-412-24620-3, as cited (reference 22) by
    https://en.wikipedia.org/wiki/Kernel_density_estimation . The book itself was not read.
- Added for the freeze check (FC1), read on 2026-10-02:
  - Linux v7.2 sources, https://raw.githubusercontent.com/torvalds/linux/v7.2/ (tag v7.2, commit
    8d3ae59288f1e7d58d76558a6ee96d533bc5019f): `net/core/skbuff.c` (`SKB_SMALL_HEAD_SIZE` and
    `SKB_SMALL_HEAD_CACHE_SIZE`, lines 106 to 116; `kmalloc_reserve`, lines 606 to 649, with the
    small-head cache at lines 613 to 625 and the kmalloc fallback at lines 627 to 646;
    `__alloc_skb` taking the struct from "skbuff_fclone_cache" for `SKB_ALLOC_FCLONE`, lines 684
    to 685; `kfree_skbmem`, which frees a fast-clone pair only when both halves are freed, lines
    1139 to 1167; "skbuff_ext_cache", line 5176; `skb_init` creating "skbuff_head_cache" with
    `SLAB_NO_MERGE`, "skbuff_fclone_cache" without it, and "skbuff_small_head" with a usercopy
    region, lines 5186 to 5225); `include/linux/skbuff.h` (`SKB_TRUESIZE`, lines 273 to 275;
    `struct sk_buff_fclones`, lines 1395 to 1401); `include/net/sock.h` (`skb_set_owner_r`, lines
    2474 to 2481); `net/ipv4/tcp.c` (`tcp_stream_alloc_skb`, lines 926 to 935; its call with
    `sk->sk_allocation`, line 1256); `net/core/sock.c` (`sk_allocation` = `GFP_KERNEL`, line
    3750); `include/linux/slab.h` (`KMALLOC_NOT_NORMAL_BITS`, lines 745 to 748); `mm/slab_common.c`
    (`SLAB_NEVER_MERGE`, lines 50 to 52; the merge rules, lines 155 to 230; `/proc/slabinfo`
    under `CONFIG_SLUB_DEBUG`, lines 1097 to 1231, with mode 0400 at line 1098 and its creation
    at line 1226); `mm/slub.c` (the `aliases` attribute, lines 9156 to 9160; the sysfs names and
    links of merged caches, lines 9641 to 9722); `include/net/tcp.h` (`MAX_TCP_HEADER`, line 70).
    A search of every `kmem_cache_create` and `KMEM_CACHE` under `net/` and `include/net/` at the
    tag found no other cache that holds skb structs or heads.
  - slabinfo(5), man-pages 6.19: the columns `pagesperslab` and `num_slabs`; "Only root can read"
    the file; `Slab` in `/proc/meminfo` shows the memory of these caches.
    https://man7.org/linux/man-pages/man5/slabinfo.5.html
- Not verified, to be read at the freeze: HAProxy 3.4.6 `cpu-map` text; OpenSSL's Windows build
  notes on NASM; sslh's PROXY support for incoming connections; the Winsock `listen` text on
  `SOMAXCONN`; which JDK release is the latest LTS (Oracle's support roadmap page refused the
  fetch); which receive allocator Netty's native epoll transport uses by default. To be read on L
  before the hypotheses freeze, since B3 depends on it: whether L's kernel has `/proc/slabinfo`
  (`CONFIG_SLUB_DEBUG`), and under which names it lists the three skb caches (WL7).

## Appendix A. Synthetic check of the R rule (ST13)

These are computations under a stated model, not lab results.

Model: the log session ratios of a pilot cell are iid normal with mean 0 (A/A truth) and standard
deviation σ; P = 16. The rule is ST13 exactly: centring at the median, the smoothed bootstrap
scaled to the one-sided 80% upper bound s_U, both computations of ST12 at [0.98, 1.02] with
B = 10,000 BCa resamples and the sign test, α/36, `N_SIM` = 1,000 runs per candidate, target 0.80.
"True power" is the pass rate of 1,000 fresh normal samples of size R at the true σ, analysed the
same way. Eight pilots per σ. numpy 2.5.0, Python 3.14.5, `statistics.NormalDist` for Φ, master
seed 43. The script ran in the coordinator's scratch directory and is not committed; its logic is
fully given here and in ST13.

True power by R:

| σ | R = 11 | 15 | 18 | 22 | 25 | 28 | 31 |
|---|---|---|---|---|---|---|---|
| 0.0100 | 0.614 | 0.909 | 0.991 | 0.996 | 1.000 | 1.000 | 1.000 |
| 0.0125 | 0.296 | 0.645 | 0.849 | 0.936 | 0.978 | 0.996 | 0.999 |
| 0.0150 | 0.109 | 0.353 | 0.583 | 0.732 | 0.857 | 0.927 | 0.966 |

The rule's choice over the 24 pilots: in 17 the chosen R had true power of at least 0.80; in 3 it
was below (0.614 once at σ = 0.010; 0.732 twice at σ = 0.015, where the pilots' standard
deviations were 0.0077, 0.0115 and 0.0114); in 4 the cell was declared not resolved although its
true power at R = 31 was 0.999 (σ = 0.0125, twice) or 0.966 (σ = 0.015, twice). With a 90% bound
instead, no chosen R fell below 0.80, but 7 of the 24 cells were declared not resolved. The 80%
bound is kept, the level of the power target. The family's R_C is the largest R_c over the cells,
so most cells run with more power than their own R_c gives.

## Revision log

- 2026-10-02: first version, for review.
- 2026-10-02, review fixes: Z6 now gives the Go and Rust harnesses ASan and TSan records, as P2
  did for its Go and Rust arms, and declares only their MSan gap; WL7 and B3 define "pending" for
  the partial-ClientHello case, so all eight TLS-serving competitors apply and m_B stays 34; A4
  shows Jetty's TLS detection as record only, without SNI.
- 2026-10-02, revision after the audit at 83c4710 and Alex's decisions of the same day: see the
  next section. m_B is now 18, with 16 descriptive cells.
- 2026-10-02, revision after audit 2 (commit 49993f5) and the decisions of the same day on N1, N2
  and N3: see the section "Revision log (audit 2, commit 49993f5)". `hypotheses.md` is drafted
  from this file.
- 2026-10-02, revision after the freeze check of `hypotheses.md` (`design/freeze-check.md`,
  commit 56f90bd) and the coordinator's decisions of the same day: see the last section. The same
  changes are made in `hypotheses.md`, which stays a draft.

## Revision log (audit 83c4710)

Each finding of `design/proposal-audit.md`, with the change it caused. None is deferred; where a
fix needs engineering, the rule for the engineering result is fixed here.

| Finding | Severity | Change |
|---|---|---|
| F1 | BLOCKER | ST13 replaced. The margin is fixed from relevance by Alex, [0.98, 1.02] (ST12). The A/A pilot only sizes R_C: a per-cell rule, a smoothed bootstrap scaled to an upper confidence bound so the pilot's maximum does not set the result, B = 10,000 inside the simulation, α/36 at the full family, a 0.80 target, candidates where the sign test's allowed count steps, and "not resolved" above 32 (ST13). The joint-reading ambiguity is gone: power is per cell, and R_C serves every resolved cell. Appendix A checks the rule. |
| F2 | BLOCKER | WL7 and B3 rewritten. Primary statistic: the difference in bytes. Kernel per-socket baseline `K_BASE` measured once per host with `ophold`, the same for all, reported, cancelled in the difference and added to both sides of the reported ratio. `f` reported, not added. Limits raised with sources (nginx `worker_connections`, `worker_rlimit_nofile`, `backlog=`; HAProxy `maxconn`; Envoy `tcp_backlog_size`; harness backlogs; sslh `max_connections` unset, its hard-coded backlog of 50 met by pacing). Paced opening, overflow counters invalidate a window. Fixed 30 s window, settling rule, ℓ defined. JVM collector G1 explicit with the vendor's documented heap defaults, since neither Netty nor Jetty documents one; forced collections and live heap for the JVM and Go (CP6 to CP8). |
| F3 | MAJOR | R_C sized from the pilot at the fixed margin, up to 31 (32 adds nothing); the sign test named as the binding computation (ST7, ST13, 5.6). |
| F4 | MAJOR | The margin was set by Alex on 2026-10-02 before any code existed; the pilot runs once on frozen code with logged seeds; one-port against dedicated timing waits for the margin and R_C (I31 E1, ST13). |
| F5 | MAJOR | M1 and M2 losses are "not shown" (5.8). Every cost claim reads "equivalent within [0.98, 1.02]" (S2, A2, 5.8). |
| F6 | MAJOR | Fresh 127/8 block per window, `IP_BIND_ADDRESS_NO_PORT` (I30); TIME-WAIT counts, overflow counters and `tcp_max_tw_buckets` recorded (LB5, ST10); the pilot's second start on a port offset (ST13). |
| F7 | MAJOR | The claim is scoped to single-protocol load (S2, title); a mixed-protocol cell is secondary (5.7). |
| F8 | MAJOR | All peeks are synchronous on the worker, so no shared-buffer race (I11). `SO_RCVLOWAT` is the total needed, reset before the handler reads, both counted. IOCP switches to replay after an undecided peek. io_uring waits with `IORING_OP_POLL_ADD` for `POLLRDHUP`, so half-close is seen; IOCP sees it as a zero-byte read. Tests pin each before use (RK4, RK5, Z2). |
| F9 | MAJOR | Logging off in every system (sslh `verbose-connections: 0`), Envoy's stats matched to the server's counters, nginx `multi_accept on`, HAProxy `splice-auto` if the server splices, one route table for all, M3's TLS exchange specified (recorded ClientHello, stub reply, stub closes), the relay buffer stated, overflows recorded beside each M3 cell, and the departure from the FAQ's open-loop advice stated (I17, I18, M3, section 6). |
| F10 | MAJOR | B3 worded as whole-system footprint, as configured; the JVM and Go cells descriptive, outside Holm (B3). |
| F11 | MAJOR | M2's rate from the slower arm's measured capacity; open-loop windows invalid below 99% of the due load; one placement for both M2 arms (WL6, ST10, LB2). |
| F12 | MAJOR | S6 defines "delivered" on the loop's observation, a tie rule with a non-blocking check that wins, and S6(h) for half-close; HC7 gets a guard band G; I13 re-reads the clock after every wait. |
| F13 | MAJOR | W's procedure (power plan, boost, timer resolution, a frequency counter tested in engineering) or, failing the test, validation without the frequency rule, said in the paper (LB3, ST10). |
| F14 | MAJOR | Section 9 rewritten: every part, per host, with totals; 4-core cells dropped; descriptor hand-off dropped; W's time is open question Q6. |
| F15 | MAJOR | Z2 names one-port, dedicated and stub modes; W's third-party ASan builds settled in engineering or declared; OpenSSL under TSan declared now unless withdrawn; the assembly gap extended to ASan and TSan; provided-buffer unpoisoning stated; MSVC chosen as W's one compiler (Z1 to Z6). |
| F16 | MINOR | `SSL_CTX_set_num_tickets(ctx, 0)` and `SSL_SESS_CACHE_OFF` named; RFC 8446 s9.1 cited; the departure from OpenSSL's default groups stated with its reason (I24). |
| F17 | MINOR | The WSARecv statement on NULL overlapped and completion routine cited as the basis of the synchronous peek; `FILE_SKIP_COMPLETION_PORT_ON_SUCCESS` set in both modes (I5, I11). |
| F18 | MINOR | I5 reworded: the documented remedy is to close the socket, so the server does not use the receive buffer on fallback listeners. |
| F19 | MINOR | I11 reworded: edge-triggered mode is nginx's condition, not a necessity once `SO_RCVLOWAT` is set. |
| F20 | MINOR | ST6 and 5.6 state that the smallest BCa p holds only at z0 = 0, and give the TOST floor. |
| F21 | MINOR | One order per family and host, with seeds per host (ST9); section 9 split by host, M1's IOCP cells on W. |
| F22 | MINOR | The HTTP/1.1 handler applies the detector's request-line grammar in both modes; Z2 tests both modes on invalid input (I20, I26). |
| F23 | MINOR | C2 kept, with the reason: Alex set its margin with C1's and C3's, and it tests the cost per request after classification (C2). |
| F24 | MINOR | S3 says "every system of A4"; sslh-ev's fallback "not verified"; sslh's h2c "not verified"; cmux's SSH "built-in, Go code in the harness"; A4's rule reworded for harnesses; banner-first hand-off left out with its reason (S5). |
| F25 | MINOR | HC16 uses the bitwise complement at every position, with the derivation of "rejected at byte k". |
| F26 | MINOR | `R_COMP_CASES` = 3 and `T_OBS` = 60 s, design choices with reasons (4.2). |
| F27 | MINOR | Each listed number is now sourced, a placeholder with a rule, or a design choice with its reason: the rerun cap ⌈R/4⌉ (ST4); the ST13 constants replaced (0.80 target, 1,000 runs with their standard error, B = 10,000); the backend-core rule (ST10); 60 s and `N_PEND` (Q10); ℓ and ⌊ℓ/2⌋ (WL7); the open-file limits per process and per host (WL7); 16 hard-case replicates (4.2); 4,096 bytes (HC23); the TLS choices (I24, RFC 8446 s9.1). |
| F28 | MINOR | Working title scoped to client-first TCP protocols and to cost; I4 no longer defines "the one-listener design". |
| F29 | MINOR | `N_ACCEPTEX` outstanding AcceptEx requests per listener, the same in both modes (I5). |
| F30 | MINOR | HAProxy's `nbthread` default quoted from configuration.txt line 3115; the open item closed (CP2). |
| F31 | MINOR | B3's bound is 0 bytes with the size of every pass reported; a relevance margin in bytes is open question Q22 (B3). |

## Revision log (audit 2, commit 49993f5)

Each finding of `design/proposal-audit-2.md`, with the change it caused. The decisions on N1, N2
and N3 are the coordinator's and Alex's of 2026-10-02; the text applies them. One item is
deferred, with its reason.

| Finding | Severity | Change |
|---|---|---|
| N1 | MAJOR | The order is fixed (I31 E4): hypotheses freeze, engineering, code freeze, the A/A pilot in dedicated mode on the frozen binary, the simulation, one pilot entry, then any one-port window of the frozen code. The pilot entry commits `CODE_FREEZE`, `ANALYSIS_COMMIT`, the pilot archive's sha256, R_C, the resolved list, m_C, the joint powers, the WL2 rates, G and `GAP_SPLIT`, all computed by fixed rules with fixed seeds (ST13 step 9). Reruns: invalid pilot sessions at most ⌈P/4⌉ = 4 per cell; the whole pilot at most once, after an infrastructure fault or a code change, only before the pilot entry and before any one-port window of the frozen code; never after (ST13 step 1). A code change after that keeps the committed outputs and restarts the runs on the new build (I31 E4). Interpretation, stated in E1: before the code freeze, development may time one-port arms against the competitors or against other one-port options, because D2's engineering needs it and the pilot must run on the frozen code; no window on any code times one-port against dedicated mode before the pilot entry. Rule E's two one-port choices and M2's rates move after the pilot entry (they are flag values of the frozen binary); the IOCP receive form is chosen in dedicated mode before the W pilot. `K_SRC` is set in engineering, since the pilot needs it. The seeds are placeholders fixed in one revision-log entry before the code freeze. |
| N2 | MAJOR | Q22 closed by Alex on 2026-10-02, before any B3 window: B3 is a superiority test of Q = (T_comp + `K_BASE`) / (T_srv + `K_BASE`) against the margin 1.10, by the exact sign test and the clustered BCa, Holm over the 18 cells (B3). Wording of passes and failures fixed (B3, 5.8). Each competitor's documented buffer settings are named with a rule for changing them: Envoy gets the edge page's 32 KiB buffer limits and tls_inspector's smallest initial buffer, HAProxy gets `option use-small-buffers` in its backends, the others keep their defaults with the reason (WL7, section 6). |
| N3 | MAJOR | T = U + Kq + (Ks - `K_BASE`); W = T + `K_BASE` = U + Kq + Ks is the whole-system footprint, with its two exclusions named (`f`; kernel memory outside `Slab` that no receive queue is charged for). `K_BASE` cancels from both D and Q and is reported as the shared share (WL7, B3). |
| N4 | MINOR | ST6: the floor and the limit on the size of z0 hold for even R; the odd-R values are given. |
| N5 | MINOR | "Resolved" defined once (Power_c(31) ≥ 0.80 with P valid sessions); the stream layout of `SEED_SIM` (tuple-seeded streams per cell, run and candidate; common random numbers); `ANALYSIS_COMMIT`; the variance stated as 0.9375 to 0.9507 of s_U², the rule kept; ST4's rerun rule applied to the pilot and counted in section 9; order seeds for the secondary cells (ST9, ST13). Deferred: committing the Appendix A script under `analysis/`. The script ran in the coordinator's scratch directory and is not in this repository, and this revision writes no code. The coordinator commits it, or Appendix A states that it is not committed, as it does now. |
| N6 | MINOR | The pilot entry reports the joint power per protocol, backend and host; each cost cell shows its interval at Holm's level beside the 95% interval (ST12, ST13 step 7, 5.8). |
| N7 | MINOR | Invalid windows reported per arm and cell beside each decision (ST4); a misclassified connection in any measured window is a B1 failure, not only a rerun (ST10, 5.8). |
| N8 | MINOR | B3 and `ophold` windows close by reset, the probe too; the TIME-WAIT count is checked at both samples; each B3 or `ophold` job starts 60 s after the last other window. The settling check is on W, with the tolerance max(2% of W, `SETTLE_ABS` = 8 bytes per pending connection), a design choice (WL7, ST10). |
| N9 | MINOR | Each proxy has three configurations, cases, M3 and B3; M3's holds exactly the two routes; B3's starts from M3's, and the libraries' from their case configuration (M3, section 6). |
| N10 | MINOR | A failed M3 or B3 cell is "not shown"; "loss" only where the 95% BCa interval lies wholly on the competitor's side (B3, M3, 5.8, RK3). |
| N11 | MINOR | The working title carries the single-protocol load scope. |
| N12 | MINOR | The SSH C3 secondary cells take their rate from their own C1 secondary sessions (WL2, 5.7). |
| N13 | MINOR | The pilot's timer and split parts, in dedicated mode, set G (per host) and `GAP_SPLIT`, with their cases, backends, runs and statistics; their time is in section 9; HC7's late run is counted at 3 s + G, at most 6 s (I30, HC7, ST13 step 8, section 9). |
| N14 | MINOR | Each loop pass handles completions before expiries; a connection whose receive was posted with a buffer is checked by a non-waiting reap of the ring or port, not a peek; S6(b) claims only what these give (S6, I13). |
| N15 | MINOR | WL7's phase lengths, `K_BASE`'s 16 windows and `N_SIM` are labelled design choices with reasons; Silverman's rule is sourced; HAProxy's 0 s default wait is sourced to survey 2.3 (WL7, ST13, section 9, sources). |

## Revision log (freeze check, commit 56f90bd)

Each finding of `design/freeze-check.md`, with the change it caused. FC1 is option (a), decided
by the coordinator on 2026-10-02. FC2 to FC8 apply the fixes the check suggests; where it left a
choice, the choice is stated in the row. W1 to W10 are applied. Nothing is deferred. B3's test
and Alex's ratio margin of 1.10 are unchanged. `hypotheses.md` carries the same text and keeps
its DRAFT status.

| Finding | Severity | Change |
|---|---|---|
| FC1 | MAJOR | Option (a). Ks is now the growth of `Slab` less the growth of the skb caches "skbuff_head_cache", "skbuff_fclone_cache" and "skbuff_small_head", read from `/proc/slabinfo` as root at the baseline and at each sample, in slab pages, the unit of `Slab` (a design choice); `K_BASE` uses the same corrected Ks. So a queued skb is counted once, in Kq. The cache names and their roles are read in the v7.2 sources; a search of every cache created under `net/` finds no other that holds skb structs or heads, and "skbuff_ext_cache" holds extensions, so it is not subtracted. Two residuals are named with their directions: a head that falls back to kmalloc stays in Ks and is still counted twice (not expected on TCP's send path, which takes `MAX_TCP_HEADER` from "skbuff_small_head" under `GFP_KERNEL`); and skb-cache memory that no receive queue is charged for, such as the second struct of a fast-clone pair, leaves W. Both sit with a system that leaves bytes queued (nginx and Envoy in the partial-ClientHello case, the server only in peek mode): the first raises its W, the second lowers it, and the bias of Q follows from which side that is. Merged caches: a rule for a cache the kernel merged, and a reading on L before the code freeze, since `/proc/slabinfo` needs `CONFIG_SLUB_DEBUG` and "skbuff_fclone_cache" can be merged. "Whole-system" is dropped, since a residual can still count bytes twice: W is the "counted footprint", each system as configured, not its detection design alone (audit F10's point kept). The subtracted growth is reported beside each B3 cell (WL7, ST2, B3, I31 E3, "Sources added"). |
| FC2 | MINOR | The cutoff for repeating the pilot moves from the pilot entry to the start of the simulation, so that no repeat can be decided with R_C and the resolved list in view. A code-change repeat needs a change forced by a named failure (a failing test, a sanitizer record that is not green, the gate refusing a build, a crash of a first-party program), recorded with its evidence. Choice made here: a change that no named failure forces follows the rule for a later change whenever it comes, so its pilot's outputs go into the entry and stand (ST13 step 1, I31 E4). |
| FC3 | MINOR | If the cap is spent, or the repeat is itself stopped: the entry is made from the last pilot, a cell without P valid sessions is not resolved, a timer run or split replicate that did not take place counts as excluded, and a further code change follows the rule for a later change (ST13 step 1, I31 E4). |
| FC4 | MINOR | A timer run or split replicate whose server or `opcase` failed is excluded and listed in the pilot entry; the parts run again only with the whole pilot, under its cap. Added beyond the check, to close the two cases this leaves empty: a host with no valid timer run has no G and does not run HC7; a tested gap at which some backend has no valid replicate does not qualify for `GAP_SPLIT` (ST13 steps 8 and 9). |
| FC5 | MINOR | Disclosure, the coordinator's decision. Every pair of development cells in which dedicated mode and one-port mode were each timed against the same competitor, at the same protocol, backend and host, is listed in the revision log of `hypotheses.md` when it runs, and in the paper's methods. The competitors are the only reference both modes may share before the code freeze, so this covers the check's "same system or option" (I31 E1). FC2's cutoff closes the one path by which such data could reach a pilot output. |
| FC6 | MINOR | A B3 session without a ratio takes Q = 0 in both computations, below every bound; the same holds in the secondary B3 cells of the server's other detection mode (B3, 5.7). |
| FC7 | MINOR | The default form is named: AcceptEx with `dwReceiveDataLength` = 0, followed by the receive form rule E chose. The second cell compares the receive form rule E did not choose with the one it chose, so no cell compares a form with itself (5.7). |
| FC8 | MINOR | The secondary intervals draw from `SEED_BOOT_S` bullet by bullet in the order of 5.7; within a bullet, the order of ST13 step 3 (hypothesis, host, backend, protocol), then the system in the order of section 6. Choices made here: a case, variant or form that a bullet names, and the metrics within a cell, follow the order the bullet names them; the cost cells not resolved and B3's descriptive cells keep their family's draws; a bullet that covers a family's list, including the analyses clustered by lab job (beyond the check), takes it in that list's order (ST9). |
| W1 to W10 | wording | Applied to `hypotheses.md` at the lines the check names: the sources of the L and W versions (W1); α as in P2 (W2); the reason for the 536-byte PROXY v2 limit (W3); the 99% rule labelled a design choice from audit F11 (W4); "the probe" (W5); the placement as in P2's H6 (W6); the reason for R_B = R_M = 16 (W7); `TCP_TIMEWAIT_LEN` with its source line (W8); the split part's 16 replicates as the hard cases' count (W9); the Envoy buffer row (W10). This file already carried W1, W3 and W6 to W10; W2, W4 and W5 are added here too (ST8, WL2, ST1). |
