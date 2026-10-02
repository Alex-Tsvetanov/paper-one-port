# P3 design proposal: one listener for every protocol

Status: proposal, not frozen. Written 2026-10-02 for review. Nothing in this file is a result.
After Alex's decisions (section 11) and an audit, section 5 and every decision it depends on
become `hypotheses.md`, frozen before any gated run. Later changes go into the revision log at
the end of this file.

Paper: "One listener for every protocol: first-bytes demultiplexing" (working title). Venue: MDPI
Future Internet. Author: Alex I. Tsvetanov, Technical University of Sofia, sole author.
Repository: `papers/one-port` (private `Alex-Tsvetanov/paper-one-port`).

Words used here:
- "The server" is the paper's own minimal server, `oneport`, built in this repository.
- "One-port mode" and "dedicated mode" are the server's two listener layouts, chosen by a flag
  (I20, I21).
- "Detection" decides a connection's protocol from its first bytes. "Dispatch" hands the
  classified connection to its handler.
- "L" and "W" are the lab hosts of `lab/README.md`. "The survey" is
  `design/competitor-survey.md`; "survey 2.5" is its section 2.5, "ambiguity 7" is item 7 of its
  section 3.2.
- A "window" is one timed run of one arm. A "session" is four windows in mirrored order (ST1).
  A "cell" is one contrast at one setting.

Numbering: S scope, I implementation, A arms, WL workloads, HC hard cases, ST statistics, C, B
and M the hypotheses of the cost, robustness and mechanism families, CP competitors, Z
sanitizers, LB lab, RK risks, Q questions for Alex. Facts beyond the survey carry their source,
listed again in "Sources added beyond the survey". Named placeholders, written in capitals
(for example `DELTA_C1_L`), stand for values that a pilot must measure or Alex must set. None
of them has a value yet.

## 1. Scope

S1. Transport: TCP only. QUIC and other UDP protocols are a later paper.

S2. The paper's claims are about the server, as measured on L and W under the conditions of
section 8. This proposal words no claim beyond the paper.

S3. Protocols served directly. All are client-speaks-first at the TCP layer (survey 3, column
"Who speaks first"):

| Member | Why it is in the set | Bytes to decide (I8) |
|---|---|---|
| HTTP/1.1 | Every system in the survey serves it. It is the default class of most sniffers (gap 6). | at most 10 |
| h2c, prior knowledge only | The one HTTP split most HTTP servers make on cleartext (gap 6). Its preface parses as an HTTP/1 request (ambiguity 2). The Upgrade path is deprecated (RFC 9113 App. B) and is not served. | 24 |
| TLS, by its ClientHello | Every proxy in the survey routes it before the handshake (survey 4). In-process it is terminated, in hand-off it is passed through by SNI and ALPN (I22). | 6 in-process; the whole ClientHello in pass-through |
| PROXY v1 and v2 prefix | Configured per listener, never guessed (survey 2.4, detection policy). It is a prefix, not a protocol. It carries ambiguity 1 and the hard case "PROXY v2 before HTTP/1". | 8 (v1) or 16 (v2), then the whole header |
| SSH | The "Both" class (survey 3.1). It is detectable when the client sends first, as OpenSSH does. `SSH-` is a legal HTTP token prefix (ambiguity 6). sslh and caddy-l4 detect it built in, HAProxy through `req.payload`; nginx and Envoy cannot (survey 2). | 4 |
| MQTT 3.1.1 and 5.0 | Binary and strictly client-first: the first packet MUST be CONNECT (MQTT 3.1.1 s3.1). Its signature sits at a variable offset (ambiguity 7). MQTT 5.0 says a multi-protocol server uses the protocol name to recognise it (survey 3). HAProxy has a built-in check, `mqtt_is_valid`; no surveyed in-process library has one (gap 5). | 9 to 12 |

S4. PostgreSQL is left out. Its first byte, 0x00, is unique in the set above, so it adds no
ambiguity the set lacks. Its direct-TLS mode (PostgreSQL 17 and later) adds only routing by
ALPN, which the TLS member already exercises (ambiguity 10). Alex may prefer it to MQTT (Q3).

S5. Server-speaks-first protocols (SMTP, FTP, POP3, IMAP, MySQL, VNC; survey 3) are a declared
scope boundary. They are served only through a timeout fallback (S6). SMTP represents them in
the experiments, with a minimal handler (I26).

S6. The fallback, and what "correct" means for it. A listener may name one fallback protocol.
Two timers start together (I13): the silence timer T_fb and the decision deadline T_dec. They
start at accept, or, on a listener configured for PROXY, at the moment the PROXY header is
complete. The behaviour is correct when all of these hold:
- (a) A connection that has delivered no application byte when T_fb expires is dispatched to
  the fallback handler. This happens in the first loop pass that handles that expiry (B2), never
  earlier. The connection is never closed or routed elsewhere instead.
- (b) A connection that delivers any byte before T_fb expires is never dispatched by the silence
  timer. Its bytes alone decide it.
- (c) After a fallback dispatch, the byte transcript in both directions equals the transcript of
  the same client script against the fallback protocol's dedicated port. Only the timing
  differs, by the wait for T_fb.
- (d) A connection with at least one byte that no matcher has decided when T_dec expires is
  closed and counted "undecided". It is never dispatched to the fallback.
- (e) A connection whose bytes rule out every matcher is closed at once and counted "rejected",
  unless the listener names a default route. The experiments name none.
- (f) A connection that is silent when T_dec expires, on a listener without a fallback, is
  closed and counted "silent".
- (g) A client-first client whose first byte arrives after T_fb is dispatched to the fallback.
  This is the defined price of the boundary, not an error. HC7 measures it.
SSH may be the fallback instead of SMTP (sslh's code default `on-timeout` is "ssh", survey
2.8). That configuration is secondary.

S7. Timeout values in the experiments, as design choices: T_fb = T_dec = 3 s and T_hdr (the
PROXY header deadline) = 3 s. The value follows the PROXY spec, which asks for at least 3 s to
cover a TCP retransmit (survey 2.4), and caddy-l4's default `matching_timeout`, 3 s (survey
2.7). In the robustness family every competitor with a matching setting gets the same value
(section 6); each also runs once at its defaults, for a descriptive table. The memory runs of
B3 use a longer matched value (WL7), so that connections stay pending while they are sampled.
Alex may change these values (Q10).

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
this repository with attribution in each file and in the commit message. Nothing builds against
P1's repository. Whether P1's repository is public, its licence, and whether the paper cites P1
(rule D8) are Alex's decisions (Q7).

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
A group of `SO_REUSEPORT` sockets, one per worker, is not the one-listener design. It is
measured only if Alex keeps the multi-core cells (Q11).

I5. Accept on each backend:
- epoll: non-blocking `accept4` on readiness of the listening socket, drained per readiness.
- io_uring: the multishot accept of I4.
- IOCP: AcceptEx with `dwReceiveDataLength` = 0 on every listener that names a fallback. With
  a receive buffer, AcceptEx does not complete until data arrives, and the documented way to
  find a silent client is `SO_CONNECT_TIME`, which counts whole seconds; the docs recommend
  closing such sockets (AcceptEx docs). So with a buffer the server could not greet a silent
  client. The form with a receive buffer gives the first bytes at accept time (gap 8). It is
  used only on listeners without a fallback, in secondary cells.

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

A method outside the list is rejected (Q14). The list is a compile-time constant.

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
- **Peek** (`peek`). The bytes are read with `MSG_PEEK` into a per-worker scratch buffer and
  stay in the kernel. The handler later reads them as in dedicated mode. This costs at least one
  receive operation per connection more than replay.

The story on each backend:

| Backend | Peek | Replay |
|---|---|---|
| epoll | The socket is registered `EPOLLET \| EPOLLRDHUP`, and on readiness the server calls `recv(MSG_PEEK)`. A level-triggered peek would busy-loop, because unread bytes keep the socket readable; this is nginx's condition for its peek path (survey 2.1). `EPOLLRDHUP` reports a peer that shut down writing (Linux 2.6.17 and later, epoll_ctl(2)), which ends the wait (HC21). When a peek is undecided, the server sets `SO_RCVLOWAT` to the byte count the matcher still needs. The next readiness then comes only when that many bytes are queued: since Linux 2.6.28, poll and epoll report a socket readable only when at least `SO_RCVLOWAT` bytes are available (socket(7)). | `recv` into the handler's buffer, triggered as in dedicated mode. |
| io_uring | `IORING_OP_RECV` with `MSG_PEEK` in `msg_flags`. The kernel reads `msg_flags` from the submission and treats `MSG_PEEK` like any other flag (Linux v7.2, `io_uring/net.c`). A peek that finds bytes queued completes at once, so an undecided peek, sent again, would complete again at once (derived from the same file and the receive path). Remedy, derived and to be pinned by a test before use: the retry carries `IORING_RECVSEND_POLL_FIRST` (kernel 5.19 and later, `io_uring_prep_recv(3)`), which arms poll before any receive, and `SO_RCVLOWAT` is set as on epoll, so the poll fires only when enough bytes are queued. Multishot receive is not used for peeking. | `IORING_OP_RECV` into a buffer taken from a provided-buffer ring, so a pending receive holds no buffer of its own. |
| IOCP | `WSARecv` with `MSG_PEEK` is valid only for non-overlapped sockets (WSARecv docs), and IOCP needs overlapped sockets. So the peek is a zero-byte overlapped `WSARecv`, used as the readiness signal (the pattern of libuv v1.53.0, `src/win/tcp.c`, flag `UV_HANDLE_ZERO_READ`), followed by a synchronous `recv(MSG_PEEK)` on the non-blocking socket (`recv` lists `MSG_PEEK`; recv docs). That is two operations per peek, imposed by the API. | Either a zero-byte `WSARecv` and then `recv` into the handler's buffer, or a `WSARecv` with the buffer posted at once. Rule E (I31) chooses. |

I12. Each backend has one default mode, used by every cost and robustness cell. The proposed
default is replay on all three, by the operation count of I11. Rule E (I31) may change it per
backend before the freeze. M1 tests the default against the other mode.

### 2.5 Timers, buffers and memory per pending connection

I13. The deadline queue. All pending connections of a listener wait under the same durations,
so their deadlines arrive in accept order. One intrusive FIFO list per listener and timer gives
constant-time arming, cancelling and expiry checks. The loop's wait bound is the earliest head
deadline: `epoll_pwait2` with a timespec, the io_uring wait with its timeout argument, and
`GetQueuedCompletionStatus` in milliseconds, as in P1. For each timed event the loop records
when its wait returned and in which pass the event was handled (B2).

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
  readiness, io_uring uses provided buffers, IOCP waits with a zero-byte receive (if rule E
  chooses the posted-buffer form on IOCP, the paper reports the buffer it holds);
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
first writes any replayed bytes, then relays both directions until one side closes. This is
what the five proxies do (survey 2), so the comparison with them is like for like. The backend
is described in I18. The relay copy (user-space buffers; or `splice(2)` on epoll and
`IORING_OP_SPLICE` on io_uring) is chosen by rule E.

I18. The backend of the hand-off cells is the same for every arm of a cell. For M2 it is the
server in dedicated mode, which terminates TLS. For M3 and for B against the proxies it is the
server in stub mode (`--mode stub`): one listening port per class, and each connection gets the
least work that completes an exchange. HTTP/1.1 gets the I26 response. TLS gets a fixed reply
after the ClientHello has been read, with no handshake. So M3 measures the front, not a TLS
handshake behind it. The backend runs in its own process on its own cores (LB2).

I19. **Hand-off by descriptor** (`--dispatch fdpass`), Linux only, secondary. The front passes
the accepted socket to the backend process over a Unix socket with `SCM_RIGHTS`. With peek, the
bytes are still in the socket, so nothing else moves. With replay, they travel in the same
message. It stays only if Alex agrees (Q8).

### 2.7 Dedicated-port mode

I20. `--mode dedicated` opens one listening socket per protocol (HTTP/1.1, h2c, TLS, MQTT,
SSH, SMTP) on consecutive ports. Backend, workers, handlers, buffers and the PROXY setting are
those of one-port mode. It has no detection, no detection timers and no detection budget. That
is the whole difference between the modes, and it is what the cost family measures.

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

I23. The library is OpenSSL, from its 3.5 LTS series. On 2026-10-02 its latest release is 3.5.9,
released 2026-09-29, with support until 2030-04-08 (openssl-library.org/source). It is pinned at
the freeze to the latest 3.5 release, by archive URL and sha256, and built from source on L and
W with the same configure options. Alex may prefer the 4.0 series (Q4).

I24. TLS settings, the same in the server, the backend and the generator:
- TLS 1.3 only; cipher suite TLS_AES_128_GCM_SHA256; key exchange group X25519 only;
- one ECDSA P-256 certificate, made from a fixed test key in the repository's test fixtures;
- no session tickets, no session cache, no early data, so every churn connection makes a full
  handshake;
- ALPN `http/1.1` in the cost cells; `h2` only in secondary cells.
Session resumption is a secondary cell.

I25. Stated before the run: the handshake dominates the cost of a TLS churn connection, so the
TLS cells of the cost family have little power to show the cost of a 6-byte check. The paper
says so beside their result (RK6).

### 2.9 Handlers

I26. Every handler is the same code in both modes (I21). Each is minimal:

| Handler | What it serves |
|---|---|
| HTTP/1.1 | The server's own parser: request line and headers up to the empty line, no request body, keep-alive and `Connection: close`. Response: 200, `Content-Type: text/plain`, `Content-Length: 13`, body `Hello, World!`, the 13-byte body of P2's server (`papers/typed-routing/hypotheses-round2.md`, H6). A malformed request gets 400. |
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
- operations by kind: accept, receive, peek, zero-byte receive, send, `setsockopt`, `io_uring_enter`
  calls, submissions by opcode, `GetQueuedCompletionStatus` calls;
- payload bytes crossing the user and kernel boundary, by direction (peeked bytes included);
- payload bytes copied in user space;
- wakeups per connection during detection;
- outcomes per class (classified, rejected, undecided, silent, fallback);
- for each timed event, its deadline, the time its wait returned, and the pass that handled it.
The counters are in every arm, so they cost the same on both sides of each contrast. They are
reported per window. On L, a separate untimed window per backend checks the system-call
counters against `perf trace -s` (perf-trace(1)). On W the counters stand alone.

### 2.11 Generators

I30. Two first-party generators, each with its own sanitizer records (Z1):
- `opgen`, the load generator. C++23, with an epoll backend on Linux and a backend for
  Windows chosen in engineering. Scripted exchanges per protocol (WL1); churn and keep-alive;
  closed and open loop; time to first response byte per exchange. It spreads source addresses
  over 127.0.0.0/8, using `K_SRC` addresses, a number set in the pilot so that no connect
  fails (RK2). It uses the same OpenSSL build and settings as the server. Its h2 frames carry
  only static-table header fields, and it reads each response up to END_STREAM. The lab's
  t1gen cannot serve: it speaks HTTP/1.1 keep-alive only (`lab/t1/gen/t1gen.c`).
- `opcase`, the case generator. It runs each hard case (section 4.2) as a script of writes and
  gaps, with `TCP_NODELAY` and one write per chunk. It records each write's time on the same
  clock the server uses (`CLOCK_MONOTONIC` on L, QueryPerformanceCounter on W), checks the
  outcome and the transcript against the frozen table, and runs against any system by address
  and port. It cannot force how bytes arrive. The gap between chunks, `GAP_SPLIT`, is set in
  the pilot to the smallest tested value at which the server's counters show the split read in
  every replicate on L and W.

### 2.12 Engineering before the freeze (rule D2)

I31. Rule E:
- E1. Development runs may time any arm against any other, one-port against dedicated included.
  They are development data. They are never results, they are cited only in the revision log
  and the lab journal, and the methods disclose them, as P2 did with its first round. The
  equivalence margins cannot be tuned to them, because ST13 derives the margins from an A/A
  pilot of the dedicated arm alone.
- E2. Three choices per backend are fixed by rule E and written into the revision log before
  the freeze: the default detection mode (I12), the IOCP receive form (I11), and the relay copy
  (I17). An option replaces the proposed default only if every session of at least 6
  development sessions of HTTP/1.1 churn (ST1) favours it, and its operation counts per
  connection (I29) are not higher. Six is the smallest count at which an exact sign test can
  reach p = 2^-6 = 0.0156, below 0.025, the minimum P2 used for its T1 cells (P2 H6). Both
  options are built into the same binary, since in P2 a layout change of the binary alone moved
  timings.
- E3. Engineering ends at the code freeze. The freeze needs green sanitizer records (Z1) and a
  passing test suite.

I32. Engineering targets, stated as goals, not as results: in replay mode, one-port mode should
issue the same operations per connection as dedicated mode on every backend; the relay should
not copy in user space where `splice` serves; a silent pending connection should hold no data
buffer.

I33. Layout: `bench/server/` (`oneport`), `bench/gen/` (`opgen`), `bench/cases/` (`opcase` and the
expected-outcome table), `bench/competitors/` (pinned build recipes and configuration files, each
line with its reason, as the Envoy FAQ advises for any benchmark configuration),
`bench/harness/` (the Netty, Jetty, cmux and hyper-util harnesses), `bench/cmake/pins.cmake`,
`tests/`, `analysis/`, `results/`.

## 3. Arms and contrast families

A1. The server's arms are one binary with four flags: mode (one-port, dedicated, stub),
detection (replay, peek), dispatch (inproc, relay, fdpass), backend (epoll, io_uring, IOCP).

A2. Three families, never mixed:
- **Cost (C).** The server in one-port mode against the server in dedicated mode: in-process
  dispatch, default detection mode, same binary, same handlers. Only this family can support
  "no measurable cost".
- **Robustness (B).** The server against the five proxies (the server in relay mode,
  pass-through) and against the four in-process libraries (the server in in-process mode), on
  the hard cases.
- **Mechanism (M).** The server's modes against each other (peek against replay; in-process
  against relay), and the server's relay against each proxy. The proxies add a network hop, so
  they are compared only with the server's relay mode.

A3. No contrast crosses families. No proxy is compared with the server's in-process mode. No
mechanism result supports a cost claim, and no cost result is set beside a proxy.

A4. What each competitor can detect, from the survey. "cfg" means through its configuration
language; "example" means through the project's own published example, used as it is; "code"
means only through code the user writes. Competitors run only the cells and cases their
built-in features, configuration or own examples cover; nothing they would need new code for is
run.

| System | HTTP/1.1 | h2c | TLS, SNI and ALPN | PROXY | SSH | MQTT | Silent-client fallback |
|---|---|---|---|---|---|---|---|
| nginx stream (2.1) | as "not TLS" only | no | yes | yes, mandatory | as "not TLS" only | no | no: closed at `preread_timeout` |
| HAProxy (2.3) | yes | cfg (`req.payload`) | yes | yes | cfg (`req.payload`) | yes (`mqtt_is_valid`) | yes: `inspect-delay`, then the default backend |
| Envoy (2.5) | yes (http_inspector) | yes | yes | yes | no | no | yes, with `continue_on_listener_filters_timeout` |
| caddy-l4 (2.7) | yes | yes | yes | yes | yes | cfg (regexp matcher) | no: closed at `matching_timeout` |
| sslh-ev (2.8) | yes (http probe) | as HTTP | yes | not verified | yes | cfg (regex probe) | yes: `on-timeout` |
| Netty (2.15) | example (`PortUnificationServerHandler`) | yes | yes (`SniHandler`) | yes | code | code | no |
| Jetty (2.16) | yes | yes (upgrade from HTTP/1) | record only (2-byte sniff), no SNI | yes | no | no | no: idle timeout closes |
| cmux (2.10) | yes | yes | record header only, no SNI | no | cfg (`PrefixMatcher`) | code | yes, by inference: `Any()` with `SetReadTimeout` |
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

Metric: connections per second, the exchanges completed without error per second of the
measured window. Time to first response byte (TTFB) runs from just before `connect` to the
first byte of the response, on the generator's clock.

WL2. Churn, open loop. Exchanges fall due on a fixed schedule at rate
λ = `RATE_FRAC` × the dedicated arm's median connections per second in the A/A pilot of that
cell (ST13). Latency is measured from the due time, as t1gen does, so no stall is hidden.
Metric: median TTFB; the 99th percentile is secondary. `RATE_FRAC` is proposed as 0.5, below
saturation, since the Envoy benchmarking FAQ advises never to measure latency at maximum load
(Q9).

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
together, at the open-loop rate of WL2, divided by the connections completed. Its rate comes
from the development sessions of the relay arm, the slower arm by design, and is fixed before
the freeze.

WL7. Memory per pending connection. `N_PEND` connections are opened in the state of the case
(silent; or a partial ClientHello: a record header announcing a ClientHello of length ℓ, then the
first ℓ/2 bytes of it). Once the server has accepted all of them (counted with `ss -t`), and
after a settling time, two parts are sampled:
- user memory: the growth of `VmRSS` of all server-side processes, divided by `N_PEND`;
- kernel memory: the mean over the server-side sockets of the `r` (rmem_alloc) and `f`
  (fwd_alloc) fields of `ss -tm` (ss(8)).
The total is their sum. "Pending" means the client's bytes are still incomplete, whatever the
system has decided from them so far. Jetty and cmux classify TLS from the record header (A4), so
for them a partial ClientHello waits in their TLS engine, and that memory is what is measured;
the same holds for the server in in-process mode, whose OpenSSL session waits for the rest.
Every system's detection timeout is set to 60 s for these runs, a
design choice, so that nothing expires during sampling. `N_PEND` is proposed as 10,000 (Q10).
The open-file limit on L is read at the freeze and must exceed twice `N_PEND`.

WL8. Hard-case runs (section 4.2). Per case: the outcome, the transcript, and the decision time,
from the server's counters against `opcase`'s write times on the same clock.

### 4.2 Hard cases

Each case runs on every backend, in both detection modes, with in-process and relay dispatch
where it applies, and 16 replicates. The table of expected outcomes is frozen with the
hypotheses.

| Id | Case | Expected outcome for the server |
|---|---|---|
| HC1 | The whole signature in one write, for HTTP/1.1, h2c, TLS, MQTT 3.1.1, MQTT 5.0 and SSH | classified; the transcript equals the dedicated port's |
| HC2 | Split signature: two writes, split after byte k, for every k from 1 to the matcher's `need` minus 1, `GAP_SPLIT` apart | as HC1 |
| HC3 | Drip: one byte per write, the whole signature arriving before T_dec | as HC1 |
| HC4 | Slow drip: a partial signature that is still incomplete at T_dec | closed at T_dec, "undecided" (S6 d) |
| HC5 | Silent client, SMTP fallback configured; then an SMTP client script | greeting after T_fb; the transcript equals the dedicated SMTP port's (S6 a, c) |
| HC6 | Silent client, no fallback | closed at T_dec, "silent" (S6 f) |
| HC7 | HTTP/1.1 client whose first byte comes after T_fb, SMTP fallback; and its twin whose first byte comes before T_fb | the first goes to the fallback, and its request gets 500 from the SMTP handler (S6 g); the twin is HTTP/1.1 |
| HC8 | SMTP client that sends EHLO before any greeting | rejected at once: no matcher starts with E (S6 e) |
| HC9 | PROXY v2 header, then an HTTP/1.1 request, in one write | header consumed; the source address the server records equals the header's; HTTP/1.1 response |
| HC10 | PROXY v2 header split after every byte k inside it, then HTTP/1.1 | as HC9 |
| HC11 | PROXY listener, no header, plain HTTP/1.1 | closed at once: the header is required, never guessed |
| HC12 | PROXY v2 header incomplete, then silence | closed at T_hdr |
| HC13 | PROXY v1 line, then a TLS ClientHello | TLS |
| HC14 | PROXY v2 with TLVs, at most 536 bytes, then MQTT; and one longer than 536 bytes | MQTT; rejected (I9) |
| HC15 | PROXY header complete, then silence, SMTP fallback | greeting T_fb after the header completed |
| HC16 | The h2 preface with one byte changed at position k, for every k | rejected at byte k |
| HC17 | One leading CRLF, then HTTP/1.1; and two leading CRLFs | HTTP/1.1; rejected (I8 accepts at most one) |
| HC18 | SSH identification line with a comment after a space | SSH |
| HC19 | ClientHello with record version `03 01`, and with `03 03` | TLS |
| HC20 | ClientHello fragmented across two TLS records, in two writes | in-process: the handshake completes; pass-through: routed by its SNI |
| HC21 | Peer shuts down writing after a partial signature | closed at once, "undecided" (no wait for T_dec) |
| HC22 | Peer resets during detection | state freed; counters consistent; no leak under the sanitizer records |
| HC23 | 4 KiB starting `GETX`; 4 KiB of `A` | rejected at the first impossible byte; no budget exceeded |
| HC24 | MQTT CONNECT with a Remaining Length of 1, 2, 3 and 4 bytes; MQTT 3.1 `MQIsdp` | MQTT for the four; rejected (S8) |
| HC25 | `GET key` and CRLF, as a Redis inline command | HTTP/1.1, answered 400 |

The competitors run the cases their features cover (A4), with matched timeouts, and once at
their defaults. Their outcomes are tabulated against the same table and against their own
documentation. That table is descriptive and tests nothing.

## 5. Hypotheses and statistics

### 5.1 Session design

ST1. A session is four windows of the two arms of a cell in mirrored order, X Y Y X. Which arm
is X is drawn per session from the order generator (ST9). Each window starts fresh processes
(server, backend if any, generator), checks one exchange of each protocol the cell uses, then
runs a 1 s warm-up and a 5 s measured window. These are the T1 defaults of `lab/t1/t1.py` and
the design of P2's H6 (`papers/typed-routing/hypotheses-round2.md`).

ST2. An arm's value in a session is the mean of its two windows. The session's ratio is
arm / reference, with the direction each hypothesis states.

ST3. Placement: disjoint cores on loopback, the SMT sibling of every server core idle (LB2,
LB3).

ST4. Fixed R. Each confirmatory cell needs 16 valid sessions. There is no sequential stopping.
A session with an invalid window (ST10) is discarded and run again at the end of the order, at
most 4 times per cell. A cell with fewer than 16 valid sessions cannot pass and enters Holm with
p = 1.

### 5.2 Statistics shared by all families

ST5. Cell statistic: the median of the 16 session ratios.

ST6. Clustered BCa interval, as in P2 (`hypotheses-round2.md`, section 5): 10,000 resamples of
the sessions, drawn with replacement. The cluster is the session: both arms' windows stay
together. The bias correction counts ties as half; the acceleration comes from the jackknife
over sessions; the share of resamples beyond a bound is clipped to [1/(2B), 1 - 1/(2B)],
B = 10,000. The one-sided p-value against a bound is the level α at which the bound of the
1 - 2α interval equals it.

ST7. Exact sign test: X counts the sessions whose ratio lies strictly on the hypothesis side of
the bound; a tie counts against. Under the null at its boundary, X is binomial with 16 and 1/2;
p = P(X ≥ x), computed exactly.

ST8. Holm's step-down per family, at family-wise α = 0.025, one-sided, run separately for each
of the two computations. A cell passes only if it passes under both. If they disagree, both are
reported and the cell does not pass. A cell that cannot be tested enters with p = 1.

ST9. Order. All sessions of a family's cells run in one shuffled order, so that drift in time
spreads over the cells. The order seed of each family (`SEED_ORDER_C`, `SEED_ORDER_B`,
`SEED_ORDER_M`) and the resampling seed (`SEED_BOOT`, one generator per family, cells in the
family's order) are fixed at the freeze and used by no earlier run.

ST10. A window is invalid, and is listed with its reason, if:
- the server, the backend or the probe failed, or no exchange completed;
- the error share exceeded 0.1%, the generator's CPUs were more than 90% busy in a saturation
  cell, or the mean CPU MHz drifted more than 2% from the session's value (the rules of
  `lab/t1/t1.py`, as P2's H6 used them);
- any connect failed (address or port exhaustion, RK2);
- any connection was classified other than as its script's protocol (I29);
- in hand-off cells, a backend core was more than 90% busy.

ST11. Independence. Sessions are separate process lifetimes at different times, and nothing
passes between them; the analysis treats them as independent. Each family runs as one or more
lab-locked jobs; the job of each session is recorded, and an analysis clustered by job is
reported. It decides nothing.

ST12. Equivalence (cost family only). The margin of metric x on host h is the ratio interval
[1/(1 + δ), 1 + δ] with δ = `DELTA_x_h`. Each cell has two one-sided nulls: "the median ratio is
at most 1/(1 + δ)" and "it is at least 1 + δ". Each is tested at α = 0.025 by both computations
(ST6, ST7). A computation's p-value for the cell is the larger of its two one-sided p-values.
This is the two one-sided tests procedure. Before Holm's adjustment, the BCa form passes at
0.025 exactly when the two-sided 95% BCa interval lies inside the margin. Why this is not a superiority test in
disguise: the null of each cell is that the ratio lies outside the margin; a cell passes only
when both one-sided nulls are rejected. A noisy cell, or one with too few valid sessions,
fails. A difference that is merely not significant never counts as equivalence.

ST13. Where the margins come from. No measured source exists for what L or W can resolve on
these workloads, so a pilot measures it before the freeze:
1. The A/A pilot runs the dedicated arm against itself: ST1's sessions with both arms in
   dedicated mode, two separate starts of the same binary and flags. It covers every cell of
   C1 to C3 on its host, 16 sessions each. No one-port data enters it.
2. For each metric x and host h, `DELTA_x_h` is the smallest multiple of 0.005 at which every
   cell of x on h passes both computations at Holm's first threshold, α / m_C, in at least 80%
   of 1,000 simulated runs. A simulated run draws 16 sessions with replacement from the cell's
   pilot sessions. Inside the simulation the BCa uses 2,000 resamples, for speed. This is the
   smallest margin the lab can resolve with the design's power.
3. Alex sets a relevance cap per metric, `CAP_C1`, `CAP_C2`, `CAP_C3` (Q2). If a `DELTA_x_h`
   exceeds its cap, the lab cannot show "no measurable cost" for x on h at a size that matters.
   Before the freeze, either the windows or the sessions grow (a design change, logged), or that
   metric on that host moves to the secondary results, and the paper says why.
4. The same pilot gives the open-loop rate of WL2 per cell. The pilot is development data.

Placeholders: `DELTA_C1_L`, `DELTA_C2_L`, `DELTA_C3_L`, `DELTA_C1_W`, `DELTA_C2_W`, `DELTA_C3_W`;
`CAP_C1`, `CAP_C2`, `CAP_C3`.

### 5.3 Cost family

Cells: protocol p in {HTTP/1.1, h2c, TLS with HTTP/1.1, MQTT} and backend b in {epoll and
io_uring on L, IOCP on W}, 12 per hypothesis. Arms: one-port mode against dedicated mode
(A2). Session ratio: one-port / dedicated.

C1. Churn throughput is equivalent. In every cell, the median ratio of connections per second
under WL1 lies inside [1/(1 + δ), 1 + δ], δ = `DELTA_C1_L` on L and `DELTA_C1_W` on W, by ST12.

C2. Keep-alive throughput is equivalent. In every cell, the median ratio of requests per second
under WL3 lies inside the margin with δ = `DELTA_C2_h`, by ST12.

C3. Latency at a fixed load is equivalent. In every cell, the median ratio of median TTFB under
WL2 lies inside the margin with δ = `DELTA_C3_h`, by ST12.

m_C = 3 × 12 = 36 cells.

### 5.4 Robustness family

B1. Conformance, deterministic, not in the Holm family. For every hard case, backend, detection
mode, applicable dispatch mode and replicate, the server's outcome and transcript equal the
frozen expected table of section 4.2. One deviation fails B1. B1 is not narrowed: a deviation
means the server is not done.

B2. Bounded behaviour, deterministic, not in the Holm family:
- (a) Never early: no fallback, close or deadline event happens before its deadline on the
  server's clock.
- (b) Each deadline is handled in the first loop pass whose wait returned at or after it
  (I13 records both).
- (c) Each connection is classified in the loop pass that received its deciding byte.
- (d) No pending connection holds more user-space payload bytes than its mode's bound in I15,
  and a pending connection that has received no byte holds no data buffer.
The lateness of timed events and the decision latency are reported per backend as
distributions. They are not tested: they include the operating system's timer behaviour, which
P3 does not claim to control.

B3. Memory per pending connection, in the Holm family. Session ratio: the server's memory per
pending connection (WL7) / the competitor's. In every cell the median ratio is below 1.00:
superiority, null "the ratio is at least 1.00", both computations. The server runs in relay
mode against the proxies and in in-process mode against the libraries, in its default
detection mode. Cells:
- the silent case, against all nine competitors;
- the partial-ClientHello case, against the eight that serve TLS (all but hyper-util), with
  "pending" as WL7 defines it;
- each on the server's two Linux backends, epoll and io_uring.
m_B = (9 + 8) × 2 = 34 cells. The competitors are Linux programs, so B3 runs on L only.

### 5.5 Mechanism family

M1. The default detection mode is cheaper. In-process, churn (WL1), the session ratio
connections per second (default mode) / (other mode) is above 1.00 in every cell of {HTTP/1.1,
h2c} × {epoll, io_uring, IOCP}: 6 cells. The proposed default is replay (I12); rule E fixes it
per backend before the freeze, and M1's direction follows it.

M2. In-process dispatch costs less than relay. The session ratio of server CPU per connection
(WL6), in-process / relay, is below 1.00 in every cell of {HTTP/1.1, TLS} × {epoll, io_uring}:
4 cells. The relay arm passes TLS through to a backend that terminates it (I18), so both arms
make one handshake per connection.

M3. The server's relay is faster than each proxy. With one front core and the stub backend
(I18), churn (WL1), the session ratio of connections per second, server / proxy, is above 1.00
in every cell of {TLS routed by SNI, plaintext HTTP/1.1} × {nginx, HAProxy, Envoy, caddy-l4,
sslh-ev}: 10 cells. The server runs on epoll, the accept model all five proxies use. Every
system holds the same routes: TLS by SNI to one backend port, HTTP/1.1 to another, SSH to a
third where the system can detect SSH.

m_M = 6 + 4 + 10 = 20 cells.

### 5.6 Replicates and family sizes (rule D9)

All three families use R = 16, P2's reference. The smallest exact one-sided p is
2^-16 = 1.53e-5. One session on the wrong side of the bound gives p = 17/65536 = 2.59e-4; two
give 137/65536 = 2.09e-3; three give 697/65536 = 1.06e-2. The smallest BCa p, with the clipping
of ST6, is about 5.0e-5 (P2, section 5).

| Family | m | Holm's first threshold α/m | Smallest R with 2^-R < α/m | At R = 16: one session out | two out | three out |
|---|---|---|---|---|---|---|
| Cost | 36 | 6.94e-4 | 11 | every cell can pass | up to 11 cells | up to 2 cells |
| Robustness (B3) | 34 | 7.35e-4 | 11 | every cell can pass | up to 11 cells | up to 2 cells |
| Mechanism | 20 | 1.25e-3 | 10 | every cell can pass | up to 11 cells | up to 2 cells |

"Up to n cells" counts how many cells may have that count and still pass when every other cell
has a smaller p: a p of 2.09e-3 clears Holm's threshold α/k only for k ≤ 11, and 1.06e-2 only
for k ≤ 2. In the cost family the count applies to each one-sided test: one session beyond the
lower bound and another beyond the upper bound leave each test with one session out, and the
larger of the two p-values decides.

### 5.7 Secondary results, not in any Holm family

Each is reported with its 95% BCa interval where it has one, and decides nothing:
- CPU per connection or request and resident memory for every C cell (WL4); p99 TTFB (WL2);
- the SSH cells of the cost family, with the order change of I28;
- TLS with session resumption; TLS with ALPN `h2`;
- 2 and 4 server cores, if Alex keeps them (Q11), and the `SO_REUSEPORT` variant;
- the server's relay on io_uring against the proxies;
- on IOCP: AcceptEx with a receive buffer, a zero-byte receive, and a posted buffer, compared
  on a listener without a fallback (gap 8);
- descriptor hand-off (I19), if kept;
- operations and copies per connection for every mode and backend (I29), and system calls per
  connection for the proxies (WL5);
- for every M cell, TTFB at a fixed load (WL2) and CPU per connection (WL4), so that each
  mechanism contrast also reports setup latency and CPU;
- B3 in the server's other detection mode;
- the competitors' outcomes on the hard cases, at matched timeouts and at their defaults;
- the lateness and decision-latency distributions of B2.

### 5.8 What counts against the claims

- C: a cell that fails is reported as a measured, or unresolved, cost on that protocol and
  backend, with its interval. "No measurable cost" is claimed only for the protocol and backend
  pairs where C1, C2 and C3 all pass.
- B1 and B2: not narrowed; a failure after the freeze is reported as a failure, and the
  robustness claim is not made.
- B3: narrowed to the competitors and cases where it passes; each loss is reported.
- M1 and M2: reported per backend as measured. A loss is a finding about the mechanism, for
  example that peek costs nothing extra on one backend, and is not narrowed away.
- M3: narrowed to the proxies and protocols where it passes; each loss is reported.
- The order in which framings give way when a family cannot be won cleanly is Alex's (Q1).
  Proposed: M3 first, then B3, then the cost family per backend.

## 6. Competitors and pins

The survey's versions are used unless a newer release exists at the freeze. Each pin change is
listed then. Every configuration file is in `bench/competitors/`, every line with its reason.
In M3 every front gets one core (LB2). In B every competitor gets the server's core count.

| Id | System and pin | Families | Configuration, with its source |
|---|---|---|---|
| CP1 | nginx 1.30.5, stream module with `ssl_preread`, built from the release tag | B, M3 | `worker_processes 1` and `worker_cpu_affinity` on the front core: the docs call the number of available CPU cores "a good start". The event method is left to nginx, which picks the most efficient one; on Linux that gives epoll with RDHUP and so the peek path (survey 2.1). `ssl_preread on`; `map $ssl_preread_server_name` to the upstreams; non-TLS traffic to the HTTP upstream, as in the docs' example (survey 2.1). `preread_timeout` matched (default 30s) and `proxy_protocol_timeout` matched (default 30s). Sources: nginx.org core module and stream core module docs. |
| CP2 | HAProxy 3.4.6 | B, M3 | `mode tcp`; `tcp-request inspect-delay` matched; `tcp-request content accept` on `req.ssl_hello_type 1`; `use_backend` on `req.ssl_sni`, `req.proto_http`, `req.payload(0,4)` for `SSH-`, and `mqtt_is_valid`; `default_backend` for the fallback (survey 2.3). One thread on the front core (`nbthread`, `cpu-map`). The text of those two keywords in configuration.txt v3.4.6 is to be quoted at the freeze: the manual page was truncated when read for this proposal. |
| CP3 | Envoy 1.39.2, the release binary | B, M3 | From the docs' benchmarking FAQ: a release binary; `--concurrency` set to the cores the other proxies get (here 1); circuit breaking disabled (cluster limits raised); filter chains only for the compared features. Listener filters tls_inspector and http_inspector, and proxy_protocol in the PROXY cases; filter chains by `server_names`, `transport_protocol` and `application_protocols`; tcp_proxy. `listener_filters_timeout` matched; `continue_on_listener_filters_timeout` true only in the fallback cases (survey 2.5). |
| CP4 | caddy-l4 v0.1.2 = commit 42db5690dea199f930a6f08005fe2e4aab10dcc9, on Caddy v2.11.4 (its `go.mod`), built with xcaddy and go1.27.1 | B, M3 | The layer4 app: routes with the tls (SNI), http, ssh and regexp matchers and the proxy handler; `matching_timeout` matched (survey 2.7). The Go runtime takes GOMAXPROCS from the CPU affinity mask (Go runtime docs, go1.27.1), so `taskset` on the front core sets it to 1. **Pin risk:** the README warns that the app is in development and may break (survey 2.7). The commit is pinned and read again at the freeze; any change of behaviour is a new pin, logged. |
| CP5 | sslh 2.3.1, the `sslh-ev` binary | B, M3 | doc/INSTALL.md: sslh-ev uses libev to manage thousands of connections, and sslh-select, which it resembles, uses one thread. Probes: tls with `sni_hostnames`, http, ssh, and a regex probe for MQTT (built with `ENABLE_REGEX`, survey 2.8). `timeout` matched (whole seconds); `on-timeout` names the fallback in the fallback cases. |
| CP6 | Netty 4.2.18.Final | B | A harness after the `PortUnificationServerHandler` example, with Netty's built-ins: `SniHandler`, `CleartextHttp2ServerUpgradeHandler`, `HAProxyMessageDecoder`, the HTTP codec (survey 2.15). The native epoll transport: the Netty wiki says native transports "generally improve performance when compared to the NIO based transport". `ReadTimeoutHandler` matched (it has no default). The JDK is pinned at the freeze (Q5). |
| CP7 | Jetty 12.1.13 | B | `DetectorConnectionFactory` with `SslConnectionFactory` and `ProxyConnectionFactory`, then HTTP/1.1 with the h2c upgrade (`HTTP2CServerConnectionFactory`), as the programming guide's I/O architecture section describes (survey 2.16). Idle timeout matched. |
| CP8 | cmux v0.1.5 on go1.27.1 | B | Matchers `HTTP2()`, `HTTP1Fast()`, `TLS()`, `PrefixMatcher("SSH-")`, and `Any()` last for the fallback; `SetReadTimeout` matched (survey 2.10). GOMAXPROCS from the affinity mask. |
| CP9 | hyper-util 0.1.21 | B | `server::conn::auto` on a tokio runtime with one worker thread (survey 2.12). It has no detection timer; nothing is added. Cases: HTTP/1.1 and h2c only. |

Also pinned: OpenSSL (I23), nghttp2 (I26), clang 22.1.8 on L, MSVC 19.51.36246 on W (the
compilers of P2's records, `hypotheses-round2.md` section 1), go1.27.1 on L, and the Rust
toolchain, JDK and xcaddy versions read at the freeze. Go net/http alone is not an arm: it tells
only HTTP/1 from h2c (survey 2.11), while cmux runs on it and splits several protocols (survey
2.10).

## 7. Sanitizer coverage (rule D5)

Z1. Records, made with `lab/bin/sanitize.sh` and `sanitize.ps1`:
- `oneport-<commit>-L-asan` (ASan with UBSan), `-L-tsan` and `-L-msan`, clang 22.1.8 on L. The
  MSan build uses an MSan-instrumented libc++, as P1's does;
- `oneport-<commit>-W-asan`, MSVC 19.51.36246 or clang-cl on W. P1's design notes a clang-cl
  stack-use-after-return false positive (P1 4.6; lab evidence
  `2026-09-26-clangcl-asan-uar-false-positive`).
Each record covers the targets `oneport`, `opgen`, `opcase` and the test suite, by inputs hash
(`lab/bin/inputs_hash.py`).

Z2. The test suite in every record runs: the detection table on its corpus at every split; the
whole hard-case catalogue against the server at short test timeouts; both detection modes; every
dispatch mode with a backend process; TLS handshakes; h2 sessions; MQTT, SSH and SMTP exchanges;
the counters; and, under TSan, two workers on the shared listener. On L both Linux backends run;
on W, IOCP.

Z3. Third-party C code is built from its pinned source with the record's sanitizer flags:
OpenSSL (its `enable-asan` and `enable-ubsan` options; MSan through `enable-msan`, which in
`Configure` at openssl-3.5.9 also turns assembly off; TSan through the configure flags, to be
checked in engineering) and nghttp2. A build that cannot be instrumented is declared in Z6
before the freeze.

Z4. The gate. The rules of P2's `bench/gate_lib.py` are copied into this repository with
attribution (Q13): a measured build is refused unless green records on the same host cover every
first-party target by inputs hash, with the same compiler, configuration, pins file hash and
fetched archives. Every measured build is gated: the server and backend, the generators, and the
harnesses.

Z5. Logs stay under `~/lab/records-logs/<record>/`, never `/tmp`, and are archived with a sha256.
The report pattern is the shared one, self-tested by `lab/bin/test_report_pattern.sh`.

Z6. Declared gaps for `bench/coverage.json`:
- **OpenSSL under MSan:** `enable-msan` disables assembly, so the assembly paths of the measured
  build are not covered by MSan.
- **io_uring kernel writes are invisible to MSan.** Mitigation from P1: value-initialise every
  structure a raw call fills, and unpoison exactly the `res` bytes of each completion. A read
  past `res` in our code would then be hidden, so the tests check `res` against the bytes used.
  Unlike P2's binaries, P3's L records must run io_uring.
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
reboot. Every tool the design needs is read on L at the freeze and never assumed; whatever is
missing is a question (Q5).

LB2. Core layout on L, the SMT sibling of each used core idle, as in P2's H6. CPUs 0 and 1 run
the system and the driver.
- In-process cells: the server on CPU 14 (CPU 15 idle); `opgen` on CPUs 2 to 13.
- Hand-off cells: the front on CPU 14 (15 idle); the backend on CPUs 10 and 12 (11 and 13
  idle); `opgen` on CPUs 2 to 9.
- B3 and hard cases: the system under test on CPU 14, with its backend, where it has one, on
  CPUs 10 and 12; `opcase` on CPUs 2 to 9.

LB3. W does the IOCP runs, on loopback, in quiet windows only (`lab/README.md`). The server runs
on one logical CPU of the last physical core, its sibling idle; `opgen` uses the cores between
core 0 and the server's. The sibling sets are read from the system at each run. The lab has no
W counterpart of `pin.sh`; the power plan and the timer resolution are recorded per window, and
the procedure is Alex's (Q6).

LB4. No LAN subnet is used. Rule D7 is not exercised.

LB5. Port exhaustion under churn. On L the kernel reuses TIME-WAIT sockets for loopback by
default (`tcp_tw_reuse` = 2, "enable for loopback traffic only"; ephemeral range 32768 to 60999 by
default; docs.kernel.org ip-sysctl). Both values are read on L at the freeze, not changed. `opgen`
spreads its source addresses (I30), and a connect failure invalidates the window (ST10). Windows'
limits are read on W in the pilot (RK2).

LB6. Raw outputs go under `lab/runs/` and are archived with a sha256 (`lab/README.md`). Numbers
reach the paper only through `results/macros.tex`, generated by `analysis/`.

## 9. Time

The only measured basis: P2's H6 run on L took 6.63 s per window, for 1 s warm-up and 5 s
windows (`hypotheses-round2.md`, section 10). A session is 4 windows, about 26.5 s. Estimates at
that rate:

| Run | Windows | Estimate |
|---|---|---|
| Cost family on L: 24 cells × 16 sessions | 1,536 | 2 h 50 min |
| Cost family on W: 12 cells × 16 sessions | 768 | 1 h 25 min, if W's window costs the same |
| A/A pilot (ST13): the same cells again | 2,304 | 4 h 15 min |
| Mechanism family: 20 cells × 16 sessions | 1,280 | 2 h 21 min, more if the proxies start slowly |
| B3: 34 cells × 16 sessions | 2,176 | to be measured in the pilot: opening `N_PEND` connections sets the window |
| Hard cases | | to be measured; the timer cases wait 3 s each |

Re-run sessions (ST4), the untimed counter checks (I29) and rule E's development sessions come on
top.

## 10. Risks

RK1. Margins too wide. The A/A pilot may show that L or W cannot resolve a relevant difference
on some metric (ST13, step 3). Then the claim shrinks or the design grows before the freeze.

RK2. Port exhaustion under churn, worst on W, where the TIME-WAIT and ephemeral-port limits are
not yet read. Mitigation: source addresses spread over 127.0.0.0/8, who-closes-first fixed per
protocol, and invalid windows on any connect failure. If W cannot sustain churn without errors,
its C1 and C3 cells cannot pass, and the paper says why.

RK3. A proxy may beat the server's relay, HAProxy above all. Rule D2: engineer first; report a
loss and narrow M3.

RK4. The io_uring peek remedy (I11) rests on a derivation. If `IORING_RECVSEND_POLL_FIRST` with
`SO_RCVLOWAT` does not hold in the test, io_uring peek becomes a poll followed by a synchronous
`recv(MSG_PEEK)`, and the revision log says so.

RK5. Peek on IOCP needs two operations because of the API (I11). M1 on IOCP then measures the
API as much as the idea, and the paper says so.

RK6. The TLS handshake dominates TLS churn, so the TLS cost cells are close to certain to pass
and tell little (I25). They are not to be read as evidence about the 6-byte check.

RK7. caddy-l4 may change behaviour between commits (CP4). It is pinned by commit and read again
at the freeze.

RK8. Downloads and builds on a frozen L (Envoy's binary, the JDK, Maven artifacts, Go modules,
Rust crates, nginx, HAProxy and sslh sources with their headers). Each needs Alex's yes (Q5,
Q15). A competitor that cannot be installed under the freeze is dropped, named, with the reason;
its cells enter Holm with p = 1.

RK9. The JVM's resident memory depends on heap sizing and collection. B3 uses each library's
defaults and samples after the settling time; the paper reports the setting and the variation.

RK10. sslh-ev's probe timeout may not fire on an idle connection: the survey found no ev_timer
covering probing connections (survey 2.8). Its timer cases are reported as observed.

RK11. Copying P1's loop: P1 may change during its own review. P3 copies a fixed commit and
records it; later P1 changes are not followed.

RK12. Family sizes may change before the freeze if a cell proves inapplicable. m is fixed at
the freeze; a cell that cannot run enters Holm with p = 1.

RK13. The cost family's equivalence rests on the A/A pilot's noise matching the confirmatory
run's. If the confirmatory sessions are noisier, cells fail without any cost being present. The
paper then reports the intervals and does not claim equivalence where they are wide.

## 11. Open questions for Alex

Q1. If a family cannot be won cleanly (D2), in which order do the framings give way, and which
framing leads the paper? Proposed: M3 narrows first, to the proxies the server beats; then B3,
to the competitors it beats; the cost family last, per backend. If the cost family fails on a
whole backend, which framing should lead?

Q2. The relevance caps `CAP_C1`, `CAP_C2`, `CAP_C3`: the widest margin for each metric that you
would still call "no measurable cost" (ST13).

Q3. MQTT (proposed, S3) or PostgreSQL as the sixth protocol?

Q4. OpenSSL 3.5 LTS (proposed) or 4.0?

Q5. Tools on L, which is frozen. Which of these exist, and which may be added without updating
installed packages: Perl and make for the OpenSSL build; headers for pcre2, zlib, libev and
libconfig (nginx, HAProxy and sslh built from source into a home prefix, no system install);
a JDK and the Maven artifacts of Netty and Jetty; xcaddy and the Go modules of caddy-l4; the
Rust crates of hyper-util; perf and ss. Each download needs your yes.

Q6. W: may Perl, and NASM if OpenSSL's Windows notes require it, be installed for the OpenSSL
build? Which pinning procedure should W follow, given that the lab has no `pin.sh` for it? Which
quiet windows are available?

Q7. P1's loop: is copying it into P3 with attribution acceptable? Will P1's repository be
public, under which licence, and should P3 cite P1 (D8: only if its text bears on the claim)?

Q8. Descriptor hand-off (I19): keep it as a secondary result, or drop it?

Q9. `RATE_FRAC` = 0.5 for the open-loop cells (WL2)?

Q10. T_fb = T_dec = T_hdr = 3 s (S7); 60 s for B3's runs; `N_PEND` = 10,000 (WL7)?

Q11. Keep secondary cells at 2 and 4 server cores, with the `SO_REUSEPORT` variant, or drop them?

Q12. SSH: a secondary cost cell because its message order changes (I28), or primary with that
stated?

Q13. The gate: copy P2's `gate_lib.py` into this repository (proposed), or move it to `lab/bin/`,
which changes the Papers repository outside this paper?

Q14. HTTP methods: the eight of RFC 9110 and PATCH, others rejected (I8)?

Q15. Envoy: download the 1.39.2 release binary (what the FAQ asks for), or build it from source?

## Sources added beyond the survey

All read on 2026-10-02.
- WSARecv: `MSG_PEEK` "is valid only for nonoverlapped sockets".
  https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-wsarecv
- recv (Winsock): `MSG_PEEK` in the flags table; `WSAEWOULDBLOCK` on a non-blocking socket.
  https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-recv
- AcceptEx: with `dwReceiveDataLength` = 0 it completes at once; with a buffer it waits for data;
  `SO_CONNECT_TIME` returns seconds connected, 0xFFFFFFFF if not connected; closing such sockets
  is recommended. https://learn.microsoft.com/en-us/windows/win32/api/mswsock/nf-mswsock-acceptex
- epoll_ctl(2), man-pages 6.19: `EPOLLRDHUP` (since 2.6.17), `EPOLLET`, `EPOLLEXCLUSIVE` (since 4.5).
  https://man7.org/linux/man-pages/man2/epoll_ctl.2.html
- socket(7), man-pages 6.19: `SO_RCVLOWAT`, respected by select, poll and epoll since 2.6.28.
  https://man7.org/linux/man-pages/man7/socket.7.html
- liburing man pages, repository master (latest tag liburing-2.15): `io_uring_prep_recv(3)`
  (`IORING_RECVSEND_POLL_FIRST` since 5.19; multishot receive since 6.0, without `MSG_WAITALL`) and
  `io_uring_prep_accept(3)` (multishot accept since 5.19; no `IORING_CQE_F_MORE` means no further
  completions). https://github.com/axboe/liburing/tree/master/man
- Linux v7.2 `io_uring/net.c`: `msg_flags` read from the submission; no special handling of
  `MSG_PEEK`; `MSG_WAITALL` refused with multishot receive; the poll-first check.
  https://raw.githubusercontent.com/torvalds/linux/v7.2/io_uring/net.c
- libuv v1.53.0 `src/win/tcp.c`: the zero-byte `WSARecv` (`UV_HANDLE_ZERO_READ`).
  https://raw.githubusercontent.com/libuv/libuv/v1.53.0/src/win/tcp.c
- Linux networking sysctls (docs.kernel.org, rendered for 7.3.0-rc5): `tcp_tw_reuse` default 2,
  loopback only; `ip_local_port_range` default 32768 to 60999.
  https://docs.kernel.org/networking/ip-sysctl.html
- OpenSSL downloads: 3.5 is the LTS series, latest 3.5.9 (2026-09-29, end of life 2030-04-08);
  4.0.3 is the latest 4.0. https://openssl-library.org/source/ . `Configure` at openssl-3.5.9:
  the `msan` option, and enabling it disables `asm`.
  https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.9/Configure . INSTALL.md: Perl 5
  and make are prerequisites. https://raw.githubusercontent.com/openssl/openssl/master/INSTALL.md
- nghttp2 releases: v1.70.0 is the latest. https://github.com/nghttp2/nghttp2/releases
- Envoy v1.39.2 FAQ, benchmarking.
  https://www.envoyproxy.io/docs/envoy/v1.39.2/faq/performance/how_to_benchmark_envoy
- nginx core module (`worker_processes`, `worker_cpu_affinity`, `use`) and stream core module
  (`listen ... reuseport`, `preread_buffer_size` 16k, `preread_timeout` 30s,
  `proxy_protocol_timeout` 30s). https://nginx.org/en/docs/ngx_core_module.html ,
  https://nginx.org/en/docs/stream/ngx_stream_core_module.html
- Netty native transports. https://netty.io/wiki/native-transports.html
- Go runtime, go1.27.1: the GOMAXPROCS default uses the CPU count, the affinity mask and the cgroup
  limit. https://pkg.go.dev/runtime
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
- Not verified, to be read at the freeze: HAProxy 3.4.6 `nbthread` and `cpu-map` text (the
  manual page was truncated when fetched); OpenSSL's Windows build notes on NASM; sslh's PROXY
  support for incoming connections.

## Revision log

- 2026-10-02: first version, for review.
- 2026-10-02, review fixes: Z6 now gives the Go and Rust harnesses ASan and TSan records, as P2
  did for its Go and Rust arms, and declares only their MSan gap; WL7 and B3 define "pending" for
  the partial-ClientHello case, so all eight TLS-serving competitors apply and m_B stays 34; A4
  shows Jetty's TLS detection as record only, without SNI.
