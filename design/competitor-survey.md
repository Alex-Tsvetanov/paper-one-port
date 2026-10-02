# Competitor survey: several protocols behind one listening socket

Working title of the planned paper: "One listener for every protocol: first-bytes demultiplexing".
This file describes what exists. It does not choose a framing.

## 1. Sources and method

- Date of all fetches: 2026-10-02.
- Scope: servers, proxies, libraries and kernel mechanisms that put several protocols behind one
  listening socket (port unification, protocol detection, protocol sniffing, first-bytes
  demultiplexing). Also the first-bytes signatures of common protocols, published research, and the
  ICEST call for papers.
- Method. The work was split into eight research passes (nginx and HAProxy; Envoy, Traefik and
  caddy-l4; sslh, sshttp and kernel mechanisms; Go, Rust and Node.js; Netty, Jetty and Grizzly;
  Kestrel, h2o, httpd, Vert.x, Cowboy, Tomcat and PostgreSQL; signatures; research and ICEST). Each
  pass used primary sources only: official docs, source files at a release tag or commit, RFCs and
  specs, and publisher pages. Blog posts and search snippets were used only to find a primary source.
- Access. Plain unauthenticated HTTPS fetches and web search. Source files were read from
  raw.githubusercontent.com at a tag, from git.haproxy.org at a tag, and from sourceware.org. No
  credentials, cookies, accounts or contact data were used in any request. DOIs were checked by
  their doi.org redirect.
- Limits met. IEEE Xplore answered with a bot challenge (HTTP 202). ACM DL answered 403. The DBLP
  and Semantic Scholar APIs answered 429. The arXiv API was rate limited, so the arXiv web search
  was used. Google Scholar answered plain fetches (five queries).
- Wording. Doc text is paraphrased. Exact code tokens, constants and config defaults are given in
  backticks with file and line, so each number can be found at its source. "Inference" or "derived"
  marks the researcher's reading of code or spec, not text from the project. "Not verified" means
  the claim could not be checked and is not relied on.
- Coverage: 23 user-space systems (nginx, HAProxy, Envoy, Traefik, caddy-l4, sslh, sshttp, cmux,
  Go net/http with x/net h2c, hyper-util, tonic with axum, Node.js, Netty, Jetty, Grizzly,
  GlassFish, Kestrel, h2o, Apache httpd, Vert.x, Cowboy with Ranch, Tomcat, PostgreSQL), 6 kernel
  or OS mechanisms (Linux `sk_reuseport`, `sk_lookup`, `TCP_DEFER_ACCEPT`, sockmap `SK_SKB`;
  FreeBSD accept filters; Windows HTTP.sys and Net.TCP port sharing), and the PROXY protocol spec.

### 1.1 Versions read

| System | Version read | Where |
|---|---|---|
| nginx | release-1.30.5 (stable, tagged 2026-09-15); 1.31.6 spot-checked; 1.24.0, 1.25.0, 1.25.1 for history | github.com/nginx/nginx, nginx.org/en/docs |
| HAProxy | v3.4.6 (latest LTS per haproxy.org; GitHub carries only v3.4.0, used for one cross-check) | git.haproxy.org, haproxy-3.4.git |
| PROXY protocol spec | doc/proxy-protocol.txt in HAProxy v3.4.6 (date line 2026/04/27) and v3.2.0 (date line 2020/03/05) | same |
| Envoy | v1.39.2 (released 2026-10-01) | github.com/envoyproxy/envoy, envoyproxy.io/docs/envoy/v1.39.2 |
| Traefik | v3.7.13 (released 2026-09-04) | github.com/traefik/traefik, doc.traefik.io/traefik/v3.7 |
| caddy-l4 | v0.1.2 = commit 42db5690dea199f930a6f08005fe2e4aab10dcc9 (2026-07-16) | github.com/mholt/caddy-l4 |
| sslh | v2.3.1 (tagged 2026-03-05) | github.com/yrutschle/sslh |
| sshttp | master commit 91be220338249e9c7a937c8d9790f559a9fe1a60 (2023-06-22); last tags 2017-05-18 | github.com/stealth/sshttp |
| cmux | v0.1.5 (2021-02-05), diffed against newest commit 7b740c1 (2026-06-08): no behaviour change | github.com/soheilhy/cmux |
| etcd (cmux user) | v3.7.2 | github.com/etcd-io/etcd |
| Go net/http | go1.27.1 | github.com/golang/go |
| Go x/net h2c | v0.59.0 | github.com/golang/net |
| hyper-util | v0.1.21 (2026-09-24) | github.com/hyperium/hyper-util |
| tonic, axum | tonic-v0.14.6; axum-v0.8.9, plus axum-v0.7.9 and axum-v0.6.20 for the removed example | github.com/hyperium/tonic, github.com/tokio-rs/axum |
| Node.js | v24.21.0 (LTS) | github.com/nodejs/node doc/api at the tag |
| Netty | netty-4.2.18.Final (example identical at netty-4.1.138.Final) | github.com/netty/netty |
| Jetty | jetty-12.1.13 | github.com/jetty/jetty.project, jetty.org/docs/jetty/12.1 |
| Grizzly | 5.0.3 (tag dated 2026-10-01) | github.com/eclipse-ee4j/glassfish-grizzly |
| GlassFish | 8.0.4 | github.com/eclipse-ee4j/glassfish, glassfish.org/docs/latest |
| Kestrel | dotnet/aspnetcore v10.0.12 (also v9.0.20, v11.0.0-rc.1.26425.128) | github.com/dotnet/aspnetcore, learn.microsoft.com |
| h2o | master commit cac7e6568ad98a848f099ecd0a18b881f632479a (2026-09-10); the project stopped tagging after v2.2.6 (2019) | github.com/h2o/h2o, h2o.examp1e.net |
| Apache httpd | 2.4.69 | github.com/apache/httpd, httpd.apache.org/docs/2.4 |
| Vert.x | 5.2.0 (constant also checked at 4.5.34) | github.com/eclipse-vertx/vert.x, vertx.io/docs |
| Cowboy, Ranch | Cowboy 2.19.0, Ranch 2.3.0 | github.com/ninenines, ninenines.eu/docs |
| Tomcat | 11.0.26 | github.com/apache/tomcat, tomcat.apache.org/tomcat-11.0-doc |
| PostgreSQL | REL_18_6 and REL_17_11; docs 18 and 17 | github.com/postgres/postgres, postgresql.org/docs |
| Linux | source tag v7.2; man-pages 6.19; docs.kernel.org | torvalds/linux, man7.org |
| FreeBSD | man pages with footer "FreeBSD 15.1" | man.freebsd.org |
| Windows | learn.microsoft.com pages | learn.microsoft.com |
| OpenSSH (signatures) | openssh-portable V_10_0_P2 | github.com/openssh/openssh-portable |

### 1.2 Claims re-checked directly against the source

Eight claims carry the most weight. Each was re-fetched and confirmed on 2026-10-02.

| Claim | Confirmed at |
|---|---|
| Envoy listener filters peek with `MSG_PEEK`; only `drain()` consumes | envoy v1.39.2 source/common/network/listener_filter_buffer_impl.cc line 59 (`recv(..., MSG_PEEK)`) and line 40 (`recv(..., 0)`) |
| nginx stream preread peeks only on non-TLS, edge-triggered kqueue or epoll-RDHUP connections | nginx release-1.30.5 src/stream/ngx_stream_core_module.c, `ngx_stream_preread_can_peek` (lines 315 to 340) and the `recv(..., MSG_PEEK)` at line 357 |
| nginx stream closes a silent client at `preread_timeout` (default 30s) | same file: on timeout `rc = NGX_STREAM_OK` (line 245), which is 200 (src/stream/ngx_stream.h line 29) and reaches `ngx_stream_finalize_session` (line 311); default merge `30000` ms at lines 861 to 862 |
| HAProxy `tcp-request inspect-delay` has no documented default, and on expiry with no matching rule the connection passes unaffected | HAProxy v3.4.6 doc/configuration.txt, inspect-delay section (around lines 14500 to 14545) |
| sslh compiled defaults are `timeout` 5 and `on-timeout` "ssh", while the man page says 2s | sslh v2.3.1 sslhconf.cfg lines 70 and 89; sslh.pod line 90 |
| cmux has no default read timeout | cmux v0.1.5 cmux.go lines 69 (`var noTimeout time.Duration`) and 78 (`readTimeout: noTimeout`) |
| Kestrel does not sniff on a cleartext `Http1AndHttp2` endpoint and uses HTTP/1.1 | aspnetcore v10.0.12 src/Servers/Kestrel/Core/src/Internal/HttpConnection.cs lines 251 to 254 |
| An `sk_reuseport` program selects the listener at the received SYN for TCP | linux v7.2 include/uapi/linux/bpf.h, comment at line 6673 in `struct sk_reuseport_md` |

Also confirmed: the nginx HTTP preface check (`ngx_http_request.c` line 498 at release-1.30.5), the
nginx docs note that the `http2` directive appeared in 1.25.1, and the HAProxy h2 preface check
(`src/mux_h1.c` line 4186 at v3.4.6).

### 1.3 Doc-versus-code disagreements found

These are reported as found. None was resolved.

- sslh v2.3.1: code default `timeout` is 5 s and `on-timeout` is "ssh" (sslhconf.cfg). The man page
  (sslh.pod) says the timeout default is 2s and that on-timeout defaults to the first specified
  protocol. example.cfg sets 2. doc/config.md advises raising the timeout to 5 seconds for some
  clients.
- Envoy v1.39.2: tls_inspector.rst line 78 says the maximum ClientHello size is 64KiB. The proto
  (`max_client_hello_size`, default 16KiB, bounded by 16384) and the code
  (`TLS_MAX_CLIENT_HELLO = SSL3_RT_MAX_PLAIN_LENGTH`, 16384 in BoringSSL) say 16 KiB.
- Envoy v1.39.2: the `application_protocols` doc says only the TLS Inspector detects application
  protocols, but http_inspector sets the requested application protocols. The FilterChainMatch
  comment speaks of "8 steps" while listing 9.
- Vert.x 5.2.0: the docs write the prior-knowledge preface as `PRI * HTTP/2.0\r\nSM\r\n`. The code
  constant is the full RFC preface `PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n`.
- Traefik v3.7.13: the router.go comment says peeking is skipped when there are neither HTTP(S) nor
  TLS routers. The condition tests only the TCP, TCP-TLS and HTTPS muxers, not plain HTTP routers.
- PROXY spec: section 2 recommends being tolerant. Section 2.2 says partial headers must be
  rejected. HAProxy's code follows the strict rule.
- caddy-l4 v0.1.2: a docs footnote says matching uses bytes of the first incoming packet only. The
  code prefetches repeatedly up to `MaxMatchingBytes`.
- HAProxy v3.4.6: the tune.maxrewrite docs describe the default as historically half of bufsize.
  The code sets `MAXREWRITE 1024`.

## 2. Systems

Each system has the same six items: (1) mechanism; (2) short first read, slow client and
server-speaks-first protocols; (3) protocols told apart and how to add one; (4) TLS position;
(5) documented cost; (6) sources.

### 2.1 nginx, stream module with `ssl_preread`

Version: release-1.30.5.

1. Mechanism. Two code paths, chosen per connection by `ngx_stream_preread_can_peek()`.
   - Peek path: used only when nginx does not terminate TLS on the connection, events are
     edge-triggered (`NGX_USE_CLEAR_EVENT`), and the event method is kqueue or epoll with RDHUP. It
     calls `recv(c->fd, ..., MSG_PEEK)` and resets the buffer after each handler call, so nothing
     is consumed.
   - Otherwise: read and replay. `c->recv` reads into `c->buffer`, and the proxy module later queues
     that buffer to the upstream (`ngx_stream_proxy_module.c`, around lines 899 to 918).
   - The peek path first appears in release-1.25.5. It is absent at tags 1.25.0 to 1.25.4. The
     CHANGES file does not mention it.
   - Maximum: `preread_buffer_size`, default 16k (docs). A full buffer logs "preread buffer full"
     and ends the session with `NGX_STREAM_BAD_REQUEST`.
   - The ClientHello parser needs at least 5 bytes and the whole first TLS record. A first byte
     other than `0x16` makes the module decline, and the variables stay empty.
2. Timeouts.
   - `preread_timeout`, default 30s (docs; code default 30000 ms). It is armed once, so it is a
     total deadline for the phase, not an idle timer.
   - On expiry the session is finalized with code 200 and the connection is closed. A client that
     sends nothing, or fewer than 5 bytes, is never proxied.
   - nginx waits only while a preread handler returns `NGX_AGAIN`. With `ssl_preread off` nothing
     waits.
   - Server-speaks-first protocols with `ssl_preread on`: not supported (closed at the timeout).
3. Protocols. TLS ClientHello (including the SSLv2 form) versus anything else. Variables:
   `$ssl_preread_server_name`, `$ssl_preread_alpn_protocols` (since 1.13.10),
   `$ssl_preread_protocol` (since 1.15.2). The docs example maps an empty `$ssl_preread_protocol`
   to an SSH upstream, to put SSH and HTTPS on one port. Extension: njs code via `js_preread`. There
   is no built-in plug-in or regex classifier.
4. TLS position. Before the handshake, without terminating TLS. If the listener terminates TLS,
   the peek path is off and preread sees decrypted bytes.
5. Documented cost: none in the sources read.
6. Sources:
   - https://nginx.org/en/docs/stream/ngx_stream_ssl_preread_module.html (read in full)
   - https://nginx.org/en/docs/stream/ngx_stream_core_module.html (searched)
   - https://nginx.org/en/docs/stream/stream_processing.html (read in full)
   - https://nginx.org/en/docs/stream/ngx_stream_js_module.html (searched)
   - https://raw.githubusercontent.com/nginx/nginx/release-1.30.5/src/stream/ngx_stream_core_module.c
     (lines 225 to 460 read)
   - same tag: src/stream/ngx_stream_ssl_preread_module.c, ngx_stream_proxy_module.c,
     ngx_stream.h, ngx_stream_handler.c (searched)
   - https://nginx.org/en/CHANGES (searched)

### 2.2 nginx, HTTP listener serving HTTP/1.1 and HTTP/2

Version: release-1.30.5; history read at 1.24.0, 1.25.0 and 1.25.1.

1. Mechanism.
   - Plain listener: the first bytes are read, not peeked, into `c->buffer`
     (`client_header_buffer_size`, default 1k). They are compared with `NGX_HTTP_V2_PREFACE`, the
     24-byte preface (`src/http/v2/ngx_http_v2.h` lines 410 to 413).
   - The test runs only when `!hc->ssl && (h2scf->enable || hc->addr_conf->http2)`
     (`src/http/ngx_http_request.c` line 498). A full match starts HTTP/2. A partial match re-posts
     the read event and waits. A mismatch falls through to HTTP/1.x parsing.
   - So one plain listener with `http2 on;` serves HTTP/1.1 and HTTP/2 with prior knowledge. The
     `http2` directive appeared in 1.25.1 (docs). The sniff is absent in the 1.25.0 source.
   - Before 1.25.1, `listen ... http2` without `ssl` made the port HTTP/2 only (1.24.0 code). That
     parameter is now deprecated.
   - On an `ssl` listener nginx peeks 1 byte with `MSG_PEEK` before the handshake. `0x16` or the
     SSLv2 high bit means TLS. Plain HTTP sent to an HTTPS port gets the special code 497.
2. Timeouts. `client_header_timeout`, default 60s. On expiry nginx logs "client timed out" and
   closes without a response. Server-speaks-first: not applicable (HTTP only).
3. Protocols. HTTP/2 preface versus HTTP/1.x (plaintext only); TLS versus plaintext by the first
   byte on `ssl` listeners (to reject plain HTTP); the PROXY header if configured. No user
   extension point.
4. TLS position. The preface sniff is plaintext only. Over TLS, ALPN "h2" selects HTTP/2. TLS
   without ALPN "h2" is treated as HTTP/1.x.
5. PROXY protocol on `listen`: mandatory for every connection on that port (docs). Input that is
   not PROXY logs "broken header" and the connection closes. On the `ssl` and stream paths nginx
   peeks into a 4097-byte buffer (`NGX_PROXY_PROTOCOL_MAX_HEADER` 4096 plus 1) and then consumes
   exactly the header. The stream path has `proxy_protocol_timeout`, default 30s.
   Documented cost: none in the sources read.
6. Sources:
   - https://nginx.org/en/docs/http/ngx_http_v2_module.html (read in full)
   - https://nginx.org/en/docs/http/ngx_http_core_module.html,
     https://nginx.org/en/docs/http/ngx_http_ssl_module.html (searched)
   - https://raw.githubusercontent.com/nginx/nginx/release-1.30.5/src/http/ngx_http_request.c
     (wait_request_handler and ssl_handshake read in full)
   - same tag: src/http/v2/ngx_http_v2.h, src/core/ngx_proxy_protocol.c and .h,
     src/stream/ngx_stream_handler.c (searched)
   - https://raw.githubusercontent.com/nginx/nginx/release-1.24.0/src/http/ngx_http_request.c
     (lines 318 to 350 read)

### 2.3 HAProxy

Version: v3.4.6. Base URL for files:
`https://git.haproxy.org/?p=haproxy-3.4.git;a=blob_plain;hb=refs/tags/v3.4.6;f=` plus the path.

1. Mechanism.
   - Content inspection is read and replay. Socket reads use `recvmsg(..., 0)` into the request
     channel buffer (`src/raw_sock.c`). While rules wait for more data, the server connect is held
     back (`channel_dont_connect`, `src/tcp_rules.c`). Rules are evaluated again on every new chunk.
   - Upper bound: the buffer counts as full when data plus `maxrewrite` reaches the buffer size.
     `tune.bufsize` default is 16384 (docs; `#define BUFSIZE 16384`) and `MAXREWRITE` is 1024
     (`include/haproxy/defaults.h`). Derived, not stated: 15360 bytes for raw TCP inspection.
   - PROXY header: `conn_recv_proxy` (`src/connection.c`) peeks with `MSG_PEEK`, then consumes
     exactly the header length. A code comment relies on the header arriving in one segment. v1
     needs 6 bytes; v2 needs 16 (`PP2_HEADER_LEN`).
   - HTTP/2 cleartext: an HTTP-mode frontend compares the input with `H2_CONN_PREFACE`
     (`src/mux_h1.c` line 4186) and upgrades the mux to h2. The docs (option disable-h2-upgrade)
     say this supports HTTP/1.x and HTTP/2 clients on non-SSL connections. `bind ... proto h2`
     forces h2. `proto h1` disables the upgrade. In a TCP frontend only the preface can be parsed.
2. Timeouts and server-speaks-first.
   - `tcp-request inspect-delay`: no default value is documented. With no delay set, HAProxy does
     not wait and decides on the data at hand.
   - On expiry a last rule pass treats the data as final. If no rule matches, the default policy
     lets the connection pass unaffected, to the default backend.
   - The docs name server-speaks-first directly: a large delay can ensure that the client never
     talks before the server (SMTP). They also give an example that rejects an SMTP client that
     speaks first. The client timeout must cover the inspection delay.
   - The delay ends early if the buffer fills or the client closes. The `WAIT_END` ACL waits for
     the end of the period.
   - So a server-speaks-first protocol can share a sniffing frontend. Its clients wait for the full
     inspect-delay.
   - PROXY: a truncated header fails at once. The wait is bounded by `timeout client-hs`, else
     `timeout client`.
3. Protocols and extension.
   - Built in: HTTP (`req.proto_http`, the `HTTP` ACL); TLS ClientHello fields (`req.ssl_hello_type`,
     `req.ssl_ver`, `req.ssl_sni`, `req.ssl_alpn`, ciphers, groups); RDP cookie; distcc; FIX
     (`fix_is_valid`); MQTT (`mqtt_is_valid`); the h2 preface in HTTP mode.
   - Generic: `req.payload(offset,length)` and `req.payload_lv`, matched with `-m bin` or `-m reg`.
   - Users add a protocol with ACLs in config, `tcp-request content switch-mode http`, or Lua
     services.
   - Absence: no example routing SSH and HTTPS to different backends from one frontend, in
     configuration.txt or in the 7 example .cfg files at v3.4.6. It can be built from the
     documented pieces.
4. TLS position. Both. The `req.ssl_*` fetches parse the raw ClientHello before any handshake. They
   do not work on `bind` lines with `ssl`, only the first ClientHello is parsed, and with ECH they
   see the outer SNI. After termination, ALPN selects h2. Preface upgrade over TLS without ALPN h2:
   not verified.
5. PROXY is mandatory when enabled: `accept-proxy` enforces it on every socket of the bind line.
   `tcp-request connection expect-proxy layer4` can be limited by a source-address ACL, which is
   selection by address, not by content. Documented cost: none. The docs only note that rules are
   re-run per chunk, and that some regex libraries are much slower with `-i`.
6. Sources (base URL above):
   - doc/configuration.txt (33196 lines; searched; read in full: tcp-request inspect-delay,
     tcp-request content, switch-mode, tune.bufsize, tune.maxrewrite, option disable-h2-upgrade,
     bind proto, accept-proxy, expect-proxy, timeout client-hs, timeout http-request, the req.*
     fetches, wait_end, the predefined ACLs, the TCP-to-HTTP upgrade text)
   - src/connection.c, src/mux_h1.c, src/tcp_rules.c (relevant functions read)
   - src/raw_sock.c, include/haproxy/channel.h, include/haproxy/defaults.h, src/haproxy.c,
     src/chunk.c, include/haproxy/h2.h (searched)
   - https://raw.githubusercontent.com/haproxy/haproxy/v3.4.0/src/mux_h1.c (cross-check)
   - https://www.haproxy.org/ (version table)

### 2.4 The PROXY protocol specification

Not a server. It constrains every server that accepts a PROXY header.
Versions: doc/proxy-protocol.txt in HAProxy v3.4.6 (date line 2026/04/27) and v3.2.0 (date line
2020/03/05).

1. Format.
   - v1 starts with "PROXY" (`50 52 4F 58 59`) and a space. The worst-case line is 107 characters,
     so a 108-byte buffer is enough.
   - v2 starts with a 12-byte signature (`0D 0A 0D 0A 00 0D 0A 51 55 49 54 0A`). Byte 13 holds the
     version and command. Bytes 15 and 16 hold the address length. The header is 16 bytes plus
     that length.
   - Decision rule (section 2.2): v2 needs at least 16 bytes with the first 13 matching. v1 needs
     at least 8 bytes with the first 5 matching "PROXY". Otherwise the connection must be dropped.
   - Reading: `MSG_PEEK` appears only in the section 9 sample code (peek, then consume exactly the
     header). Section 1 also allows a single read.
2. Missing or incomplete header.
   - The receiver must not process the connection before it has a complete, valid header. The
     spec calls this important for protocols where the receiver speaks first (SMTP, FTP, SSH).
   - Timeout guidance: at least 3 seconds, to cover a TCP retransmit.
   - Tolerant versus strict on partial headers: see section 1.3.
   - Size: both formats fit in 536 bytes (576 minus 40).
3. Detection policy.
   - The receiver must be configured to expect the header and must not guess whether it is present.
     The spec says this explicitly prevents sharing one port between public and private access.
   - The v2 signature was designed to fail at once on HTTP, TLS, SMTP, FTP and POP.
   - Implementations differ. Mandatory once enabled: nginx, HAProxy, Cowboy. Accepted with or without
     the header: h2o (option, default off), Traefik (trusted IPs), Envoy
     (`allow_requests_without_proxy_protocol`, default false), caddy-l4 (`fallback_policy` default
     `IGNORE`), and Jetty (inference from code).
4. TLS position: the header precedes any application byte, so it comes before any ClientHello.
5. Cost: only design goals (limit processing cost; text IPv6 parsing is inefficient). No numbers.
6. Sources:
   - https://git.haproxy.org/?p=haproxy-3.4.git;a=blob_plain;f=doc/proxy-protocol.txt;hb=refs/tags/v3.4.6
     (sections 1, 2, 2.1, start of 2.2, 5 and 9 read)
   - https://raw.githubusercontent.com/haproxy/haproxy/v3.2.0/doc/proxy-protocol.txt (searched)

### 2.5 Envoy

Version: v1.39.2. Base URL for files: `https://raw.githubusercontent.com/envoyproxy/envoy/v1.39.2/`.

1. Mechanism.
   - Listener filters run on the accepted socket before a Connection object exists. They share
     `ListenerFilterBufferImpl`, which peeks with `MSG_PEEK` (line 59). Only `drain()` consumes, with
     a real `recv` (line 40). The proxy_protocol filter drains its header. tls_inspector and
     http_inspector never call drain, so their bytes stay in the socket. The buffer is resized to
     each filter's `maxReadBytes()`.
   - tls_inspector parses the ClientHello with BoringSSL on a memory BIO and aborts the handshake
     early. It extracts SNI, ALPN, and JA3 and JA4 hashes (both off by default). It marks the
     transport protocol as "tls".
   - tls_inspector limits: `TLS_MAX_CLIENT_HELLO = SSL3_RT_MAX_PLAIN_LENGTH` (tls_inspector.h line 73),
     which BoringSSL defines as 16384. Proto field `max_client_hello_size`: default 16KiB, bounds
     256 to 16384. The read buffer starts at `initial_read_buffer_size` and doubles. The docs state
     64KiB instead (section 1.3).
   - http_inspector: `DEFAULT_INITIAL_BUFFER_SIZE = 8 * 1024` and `MAX_INSPECT_SIZE = 64 * 1024`. It
     detects the h2c preface. Otherwise it runs an HTTP/1 parser up to the first newline and
     reports HTTP/1.1 or HTTP/1.0. At 64 KiB without a verdict it closes the connection.
2. Timeouts and server-speaks-first.
   - `listener_filters_timeout`, default 15s (api/envoy/config/listener/v3/listener.proto line 290).
     On expiry the socket is closed without a connection, unless
     `continue_on_listener_filters_timeout` (default false) is true. Then the default filter chain
     takes the connection. 0 disables the timeout. The docs warn not to combine that option with
     the PROXY filter.
   - On a short read, tls_inspector waits for the next event.
   - proxy_protocol docs: inputs of at most 12 bytes matching the v2 signature, or at most 6 bytes
     matching v1, time out.
   - The contrib postgres_inspector has its own startup timeout, `DEFAULT_STARTUP_TIMEOUT_MS = 10000`,
     and closes on expiry. Its source notes that clients of PostgreSQL before 17 wait for the
     server's reply before sending a ClientHello.
   - Absence: no wording on server-first protocols in listener.proto, listener_components.proto,
     listener_filters.rst, listeners.rst, sni.rst or the timeouts FAQ.
   - Inference: a silent client waits the full 15 s. It is then closed, or with continue=true
     served by the default chain after that delay.
3. Protocols and extension.
   - Listener filters on the v1.39.2 docs index: HTTP Inspector, Local rate limit, Original
     Destination, Original Source, Postgres Inspector (contrib), Proxy Protocol, Set-Filter-State,
     TLS Inspector. `envoy.filters.listener.dynamic_modules` is also registered in the build config.
   - Byte detection covers TLS versus plaintext, HTTP/1.0, HTTP/1.1, h2c, and PROXY v1 and v2. PROXY
     is mandatory unless `allow_requests_without_proxy_protocol` is set (default false). The contrib
     filter adds PostgreSQL SSLRequest, CancelRequest and startup (`DEFAULT_MAX_STARTUP_MESSAGE_SIZE
     = 10000`).
   - Extension: a C++ listener filter, or a dynamic module whose proto says it can inspect initial
     bytes to detect protocols. No regex-on-bytes config was found.
   - Filter chain choice (FilterChainMatch), in order: destination port, destination IP, server
     name (SNI), transport protocol, application protocols (ALPN), directly connected source IP,
     source type, source IP, source port. With no match, the default filter chain is used if
     configured, else the connection closes. `filter_chain_matcher` (unified matcher API) can
     replace this, and matching is done once per connection. `transport_protocol` is `raw_buffer`
     when nothing was detected.
4. TLS position. tls_inspector works before the handshake on the peeked ClientHello. TLS is
   terminated later, in the chosen chain's `transport_socket`. http_inspector works on plaintext
   only.
5. Documented cost: none for listener filters or the TLS inspector. The only performance remark is
   a design note that the matcher tree permits sublinear matching (matching_api.rst). It is not a
   measurement.
6. Sources (base URL above):
   - source/common/network/listener_filter_buffer_impl.cc (read in full)
   - source/extensions/filters/listener/tls_inspector/tls_inspector.cc and .h,
     source/extensions/filters/listener/http_inspector/http_inspector.cc and .h,
     source/extensions/filters/listener/proxy_protocol/proxy_protocol.cc,
     source/common/listener_manager/active_tcp_socket.cc,
     contrib/postgres_inspector/filters/listener/source/postgres_inspector.cc and .h (searched)
   - api/envoy/extensions/filters/listener/tls_inspector/v3/tls_inspector.proto (message read in full);
     api/envoy/config/listener/v3/listener.proto, listener_components.proto,
     api/envoy/extensions/filters/listener/dynamic_modules/v3/dynamic_modules.proto (searched)
   - docs/root/intro/arch_overview/listeners/listener_filters.rst (read in full); listeners.rst,
     matching_listener.rst, matching_api.rst, tls_inspector.rst, faq/configuration/sni.rst (searched)
   - https://www.envoyproxy.io/docs/envoy/v1.39.2/configuration/listeners/listener_filters/listener_filters
   - https://www.envoyproxy.io/docs/envoy/v1.39.2/configuration/listeners/listener_filters/tls_inspector
   - https://www.envoyproxy.io/docs/envoy/v1.39.2/configuration/listeners/listener_filters/http_inspector
   - https://raw.githubusercontent.com/google/boringssl/0.20250818.0/include/openssl/ssl3.h (searched)

### 2.6 Traefik (TCP routers next to HTTP routers on one entry point)

Version: v3.7.13. Base URL for files: `https://raw.githubusercontent.com/traefik/traefik/v3.7.13/`.

1. Mechanism.
   - Read and replay in user space. `peekConn` wraps the connection in a `bufio.Reader` plus a buffer
     of bytes consumed during detection. Later reads return those bytes first (comments in
     pkg/server/router/tcp/router.go). No `MSG_PEEK` in any of the 478 non-test Go files under
     pkg/.
   - Step 1 is `conn.Peek(1)`. `0x16` means TLS, and `0x80` is treated as SSLv2, so also TLS.
   - Step 2 parses the ClientHello with Go `tls.Server`. A sentinel error from
     `GetConfigForClient` stops it after the ClientHello.
   - PostgreSQL STARTTLS: the router peeks 1 to 8 bytes, one at a time, against
     `00 00 00 08 04 D2 16 2F`. On a match it replies `S` and then reads the ClientHello.
   - No Traefik-specific byte cap was found. The Go limits apply: `defaultBufSize = 4096` (bufio)
     and `maxHandshake = 65536` (crypto/tls) in go1.26.0, the version go.mod names. The toolchain
     used for release binaries: not verified.
2. Timeouts and server-speaks-first.
   - Entry point `transport.respondingTimeouts.readTimeout`, default 60s (docs; `DefaultReadTimeout`).
     A code comment says it is set on the connection because server-level deadlines do not cover
     the peek. On expiry the peek fails and the connection is closed, with nothing logged.
   - router.go lines 102 to 106: a comment notes that a non-TLS client that does not send first
     would block forever on ClientHello parsing. So peeking is skipped when
     `r.muxerTCP.HasRoutes() && !r.muxerTCPTLS.HasRoutes() && !r.muxerHTTPS.HasRoutes()`.
     For the comment versus this condition, see section 1.3.
   - Inference: if the entry point has any TCP-TLS or HTTPS router, a silent client waits
     readTimeout and is then closed.
3. Protocols and extension.
   - Byte detection: TLS versus non-TLS, PostgreSQL STARTTLS, and ACME-TLS/1 through ALPN.
   - TCP rule matchers: `ALPN`, `ClientIP`, `HostSNI`, `HostSNIRegexp`
     (pkg/muxer/tcp/matcher.go). Non-TLS catch-all: ``HostSNI(`*`)``.
   - Docs: on a shared entry point TCP routers apply first. If none matches, HTTP routers take over.
   - Code nuance: an HTTPS router can take precedence over a TCP-TLS router only if the latter is
     not ``HostSNI(`*`)``.
   - Inference: no byte-level HTTP or other plaintext detection in router.go.
   - Users cannot add a byte-level protocol through config. A plugin route: not verified.
   - proxyProtocol: when enabled, the entry point accepts connections with or without the header
     (docs). It is configured by `trustedIPs` or `insecure`. Untrusted IPs get `IGNORE`.
4. TLS position. Before the handshake for SNI and ALPN. TLS is then terminated or passed through.
   HTTPS routing happens after termination. The project's security doc lists CVE-2026-32305: a
   fragmented ClientHello fell back to the default before SNI was seen.
5. Documented cost: only that HostSNI is more efficient than HostSNIRegexp. No measurement.
6. Sources (base URL above):
   - pkg/server/router/tcp/router.go (lines 96 to 270 and from 355 read), pkg/server/router/tcp/postgres.go
     (lines 1 to 140 read)
   - pkg/server/server_entrypoint_tcp.go, pkg/config/static/entrypoints.go, static_config.go,
     pkg/muxer/tcp/matcher.go, go.mod (searched)
   - docs/content/reference/routing-configuration/tcp/routing/rules-and-priority.md (read in full);
     router.md, tcp/tls.md, reference/install-configuration/entrypoints.md,
     contributing/security-decisions.md (searched)
   - https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/tcp/routing/rules-and-priority/
   - https://raw.githubusercontent.com/golang/go/go1.26.0/src/bufio/bufio.go and
     src/crypto/tls/common.go (searched)

### 2.7 Caddy layer4 app (caddy-l4)

Version: v0.1.2 (commit 42db5690dea199f930a6f08005fe2e4aab10dcc9). The README warns that the app is
still in development and may break. Base URL for files:
`https://raw.githubusercontent.com/mholt/caddy-l4/v0.1.2/`.

1. Mechanism.
   - Read into a buffer and replay. `WrapConnection` supports recording and rewinding.
   - `prefetch` reads what the client sent in chunks of `prefetchChunkSize = 2048`. The cap is
     `MaxMatchingBytes = 16 * 1024`. A code comment says the buffer can reach
     `MaxMatchingBytes - 1 + prefetchChunkSize`.
   - Matchers run in a frozen state and the offset is rewound after each one. After matching,
     reads drain the recorded buffer before the socket.
   - No `MSG_PEEK` in any .go or .md file at the tag.
2. Timeouts and server-speaks-first.
   - `matching_timeout`, default 3s (`MatchingTimeoutDefault`; docs/servers.md). It is applied as a
     read deadline.
   - On expiry `ErrMatchingTimeout` is logged at Warn level and the connection is closed. There is
     no fallback.
   - A matcher asks for more data by returning `ErrConsumedAllPrefetchedBytes`. At the cap,
     `ErrMatchingBufferFull` is logged as an error and the connection closes.
   - A match-all fallback route is skipped while an earlier matcher still needs data.
   - Inference: the first matching pass runs before any read. So a route whose matcher needs no
     data (for example `remote_ip`) placed before all data matchers can take a silent client.
     Otherwise a silent client waits 3 s and is closed.
   - No docs text on server-first protocols.
3. Protocols and extension.
   - Data matchers per docs/matchers.md: dns, http (including h2c prior knowledge), openvpn,
     postgres, proxy_protocol, quic, rdp, regexp, socks4, socks5, ssh, tls, winbox, wireguard, xmpp.
   - IP matchers: local_ip, remote_ip, remote_ip_list. Special matchers: clock, not, vars,
     vars_regexp.
   - Extension: a Caddy module with ID `layer4.matchers.<name>` that implements
     `Match(*Connection) (bool, error)`, built with xcaddy. The regexp matcher covers config-only
     cases.
   - Routes are evaluated in order. A route with no matchers takes all traffic.
   - The proxy_protocol handler has `fallback_policy` (default `IGNORE`) and `timeout` (default
     zero).
4. TLS position. Both.
   - The tls matcher parses the raw ClientHello itself: a 5-byte header, then the record. A
     multi-record ClientHello is capped at `MaxMatchingBytes`. SNI and ALPN matching use Caddy
     `tls.handshake_match` modules.
   - After a tls handler terminates TLS, matching continues on the decrypted stream.
5. Documented cost: guidance only (keep matchers small, since they run on every new connection).
   No numbers.
6. Sources (base URL above):
   - README.md, docs/matchers.md, docs/servers.md, layer4/connection.go (read in full)
   - layer4/routes.go (lines 28 to 239 read)
   - docs/routes.md, docs/matchers/tls.md, docs/handlers/proxy_protocol.md, layer4/server.go,
     layer4/matchers.go, modules/l4tls/matcher.go, modules/l4http/httpmatcher.go (searched)

### 2.8 sslh

Version: v2.3.1. Base URL for files: `https://raw.githubusercontent.com/yrutschle/sslh/v2.3.1/`.

1. Mechanism.
   - Read and replay. sslh does not use `MSG_PEEK` on TCP; 13 .c files were grepped, and the only
     hit is a comment in udp-listener.c.
   - tcp-probe.c reads with `read()` into `char buffer[BUFSIZ]`, then `defer_write`s the bytes to
     the backend queue. Probes run on the accumulated deferred data. After the backend connects,
     the data is flushed with `write()`.
   - `BUFSIZ` comes from the C library. glibc 2.40 defines it as 8192.
   - No total cap was found. `defer_write` grows the buffer with `realloc` on each read, and each
     read re-probes the whole buffer. Only the timeout bounds it.
   - Probe results are `PROBE_NEXT`, `PROBE_MATCH` and `PROBE_AGAIN`. If every probe fails, sslh
     connects to the last configured protocol.
   - Per probe: ssh needs 4 bytes (`SSH-`). xmpp waits for 50 bytes. tls waits for the whole first
     record. An optional per-protocol `minlength` exists.
   - UDP: one datagram in a 65536-byte buffer. It is dropped if undecided. Associations last 60 s
     by default (`udp_timeout`).
2. Timeouts and server-speaks-first.
   - Option `timeout` (`-t`, whole seconds). Code default 5 (sslhconf.cfg line 70; generated
     sslh-conf.c). `on-timeout` code default "ssh" (sslhconf.cfg line 89). The man page states
     2s (section 1.3).
   - Documented reason (sslh.pod): the SSH spec does not say who speaks first, and many SSH
     clients wait for the server's banner.
   - On expiry sslh connects to the timeout target and flushes whatever it has buffered (sslh-fork
     select timeout; sslh-select sweep; `probing_read_process` in tcp-listener.c).
   - sslh-ev: no ev_timer covering probing connections was found. The probe timeout is checked
     only on read activity. Runtime behaviour: not verified.
3. Protocols and extension.
   - Built-in probes (`builtins[]` in probe.c): ssh, openvpn, wireguard, tinc, xmpp, http, tls, adb,
     socks5, syslog, teamspeak, msrdp, anyprot. Also `regex` (PCRE2, built with `ENABLE_REGEX`) and
     the pseudo-probe `timeout`.
   - tls options: `sni_hostnames` (glob) and `alpn_protocols`. If both are set, both must match.
   - To add a protocol: a regex probe in config, or a C function added to `builtins[]`. No document
     describes writing a C probe.
4. TLS position. Before the handshake. sslh parses the ClientHello for SNI and ALPN and never
   terminates TLS.
5. Documented cost (doc/INSTALL.md): sslh-fork carries the overhead of many processes and suits a
   small setup. sslh-select has a 16-byte overhead per connection and suits a few hundred
   connections. sslh-ev uses libev for thousands of concurrent connections. UDP does not work with
   sslh-fork. No throughput or latency numbers.
6. Sources (base URL above):
   - README.md, doc/config.md, example.cfg, sslh.pod, probe.h, tcp-probe.c (read in full)
   - probe.c, common.c, sslh-fork.c, sslh-select.c, sslh-ev.c, tcp-listener.c, processes.c,
     collection.c, udp-listener.c, tls.c, sslhconf.cfg, sslh-conf.c, doc/INSTALL.md, doc/FAQ.md,
     doc/max_connections.md, doc/tproxy.md, doc/proxyprotocol.md, ChangeLog (searched)
   - https://sourceware.org/git/?p=glibc.git;a=blob_plain;f=libio/stdio.h;hb=refs/tags/glibc-2.40 (searched)

### 2.9 sshttp

Version: master commit 91be220338249e9c7a937c8d9790f559a9fe1a60 (2023-06-22). The latest tags,
sshttp-0-35s2 and sshttp-splice-0-35s2, date from 2017-05-18. The repository is not archived.

1. Mechanism.
   - One `MSG_PEEK` of at most 2048 bytes (`find_port` in src/sshttp.cc, lines 633 to 661). A
     `SSH-` prefix selects the SSH port. Otherwise the SNI table is tried if configured, else the
     HTTP(S) port. There is no retry for more bytes.
   - The relay uses `read()` and `write()` through a 1024-byte buffer. Splice lives in a separate
     branch, which was not read.
   - SMTP mode is read and replay. It sends its own SMTP banner plus the SSH banner, reads to see
     `SSH` or `HELO`, and drops the backend's real banner.
2. Timeouts. A compile-time enum: `TIMEOUT_PROTOCOL = 2` seconds. There is no command-line option.
   When the peek finds no data after that, the connection goes to SSH. In SMTP mode,
   `TIMEOUT_MAILBANNER = 3` closes a connection that sends nothing.
3. Protocols (README): SSH with HTTP, SSH with HTTPS, SSH with SMTP (no multiline banners), HTTPS
   SNI multiplexing. HTTP/SSH and HTTPS/SSH cannot be mixed in one instance. SNI targets are added
   with `-N`. Anything else needs code.
4. TLS position. Before the handshake. SNI comes from the peeked ClientHello, with no termination.
5. Documented cost (README): small footprint and tuned for speed; one thread per CPU core; splice
   avoids copies at the price of two extra pipe descriptors per connection. No numbers.
6. Sources:
   - https://raw.githubusercontent.com/stealth/sshttp/91be220338249e9c7a937c8d9790f559a9fe1a60/README.md
     and src/sshttp.h (read in full); src/sshttp.cc and src/main.cc (searched)
   - https://github.com/stealth/sshttp/tags

### 2.10 Go: cmux

Version: v0.1.5. Base URL for files: `https://raw.githubusercontent.com/soheilhy/cmux/v0.1.5/`.

1. Mechanism.
   - Read and replay. Each connection is wrapped in `MuxConn` with a `bufferedReader`. It behaves
     like a MultiReader over the recorded bytes and a TeeReader of the socket.
   - Every matcher starts again from byte 0. The order of `Match` calls sets the priority.
   - No peek, syscall or `MSG_` use in cmux.go, buffer.go, matchers.go or patricia.go.
   - Bytes read per matcher:
     - PrefixMatcher, HTTP1Fast and TLS read the longest prefix plus 1 with `io.ReadFull`.
     - HTTP2 reads the 24-byte preface and stops at the first mismatch.
     - HTTP1 is bounded by `maxHTTPRead = 4096`.
     - The header-field matchers have no cmux cap. The x/net Framer at the pinned commit allows
       frames up to `1<<24 - 1`.
     - `bufLen: 1024` is the capacity of each matched listener's channel, not a byte limit.
2. Timeouts and server-speaks-first.
   - `SetReadTimeout`; default none (`var noTimeout time.Duration`, line 69; `readTimeout:
     noTimeout`, line 78). When set, a read deadline is applied before matching and cleared on a
     match.
   - With no match, the connection is closed and `ErrNotMatched` goes to the ErrorHandler. The
     default handler keeps serving.
   - Inference from code: with no timeout, a silent client blocks the first reading matcher
     forever. With a timeout, the reading matchers fail, and `Any()` (which never reads) can match.
     That is the only route for a server-speaks-first protocol. The README does not describe this.
3. Protocols and extension.
   - Matchers: `Any`, `PrefixMatcher`, `HTTP1Fast`, `TLS`, `HTTP1`, `HTTP2`, `HTTP1HeaderField`,
     `HTTP1HeaderFieldPrefix`, `HTTP2HeaderField`, `HTTP2HeaderFieldPrefix`.
   - MatchWriters: `HTTP2MatchHeaderFieldSendSettings`, `HTTP2MatchHeaderFieldPrefixSendSettings`.
   - HTTP1Fast's default methods are OPTIONS, GET, HEAD, POST, PUT, DELETE, TRACE and CONNECT
     (PATCH is not among them). More can be passed as `extMethods`.
   - Extension in code: `type Matcher func(io.Reader) bool` or `type MatchWriter`. The README says
     SSH can also be served, but no SSH matcher is exported; a user would write a PrefixMatcher.
   - README limitations, exactly three:
     - `http.Request.TLS` is not set, because the wrapper defeats net/http's type assertion.
     - A connection is matched once, so it is gRPC or REST, not both.
     - Java gRPC clients wait for a SETTINGS frame, so they need `MatchWithWriters`.
   - Use: etcd v3.7.2 imports cmux v0.1.5 (server/go.mod line 20). On its insecure path it splits
     with `cmux.HTTP1()` and `cmux.HTTP2()` (server/embed/serve.go lines 208 and 214). On its secure
     path it matches `cmux.Any()` and then wraps TLS (line 284), so no split happens there.
4. TLS position. `TLS()` matches only the record header (`22` plus version bytes). The default list
   is SSL 3.0 and TLS 1.0 to 1.2. It does not parse the ClientHello, SNI or ALPN. How TLS 1.3
   clients fare: not verified. TLS is terminated after the split.
5. Documented cost (README, "Performance"): the overhead on long-lived connections is called
   negligible because only the first bytes are matched, with a TODO to add benchmarks.
   bench_test.go has four benchmarks. No results are published.
6. Sources (base URL above):
   - README.md, cmux.go, buffer.go, matchers.go, patricia.go, doc.go (read in full); bench_test.go,
     go.mod (searched)
   - diff of the same files at commit 7b740c1fa6e0c65ffbaab53cc1ef5dfeda821a4f
   - https://raw.githubusercontent.com/golang/net/c7110b5ffcbb/http2/frame.go (searched)
   - https://raw.githubusercontent.com/etcd-io/etcd/v3.7.2/server/embed/serve.go and server/go.mod

### 2.11 Go: net/http (`Server.Protocols`) and x/net h2c

Version: go1.27.1; x/net v0.59.0.

1. Mechanism (net/http, server.go at go1.27.1).
   - On a non-TLS connection with `UnencryptedHTTP2` enabled (line 2043), the server checks the
     preface in two stages: 14 bytes (`PRI * HTTP/2.0`), then all 24 (lines 2241 and 2244).
   - The check uses `bufio.Reader.Peek` in user space, not `MSG_PEEK`. A read limit makes at most
     24 bytes come off the socket during detection (lines 2235 to 2240, 845 to 847).
   - On a match the connection goes to HTTP/2. On a mismatch the bytes stay in the buffer and the
     HTTP/1 parser reads them.
2. Timeouts. The `ReadHeaderTimeout` deadline (falling back to `ReadTimeout`) is set before
   detection (lines 2038 to 2040). The default is no timeout. Inference: if the Peek fails, the
   server falls back to HTTP/1. Server-speaks-first: not applicable.
3. Protocols.
   - `Protocols` has three flags: HTTP1, HTTP2 (over TLS) and UnencryptedHTTP2. UnencryptedHTTP2 is
     opt-in; when `Protocols` is nil the server enables HTTP/1 and HTTP/2.
   - The `Server.Protocols` docs say the server can serve HTTP/1 and unencrypted HTTP/2 on one
     address and port.
   - Go 1.24 release notes: this uses prior knowledge (RFC 9113 section 3.3), and the deprecated
     `Upgrade: h2c` header is not supported.
   - There is no plug-in point for non-HTTP protocols.
4. TLS position. Over TLS the choice is by ALPN (`NegotiatedProtocol == "h2"`). The sniff is
   plaintext only.
5. x/net/http2/h2c (v0.59.0).
   - The package doc marks it deprecated in favour of `Server.Protocols`.
   - It does no byte sniffing. It is an `http.Handler` behind the HTTP/1 parser. It recognises the
     `PRI * HTTP/2.0` pseudo-request, which net/http deliberately lets through, or an
     `Upgrade: h2c` header, and then hijacks the connection.
   - The `NewHandler` doc warns that it reads the first request fully into memory and suggests
     `http.MaxBytesHandler`. It has no timeout of its own.
   - Documented cost: none for net/http.
6. Sources:
   - https://raw.githubusercontent.com/golang/go/go1.27.1/src/net/http/server.go (searched; listed
     ranges read) and src/net/http/http.go (lines 18 to 93 read)
   - https://go.dev/doc/go1.24 (searched)
   - https://raw.githubusercontent.com/golang/net/v0.59.0/http2/h2c/h2c.go (lines 1 to 140 read)

### 2.12 Rust: hyper-util `server::conn::auto`

Version: v0.1.21. File: `https://raw.githubusercontent.com/hyperium/hyper-util/v0.1.21/src/server/conn/auto/mod.rs`.

1. Mechanism.
   - Read and replay, at most 24 bytes. `H2_PREFACE` is the 24-byte preface (line 38). The
     `ReadVersion` future fills a 24-byte buffer. It switches to HTTP/1 at the first mismatching
     byte or a zero-length read (lines 358 to 369).
   - The bytes are then replayed with `Rewind::new_buffered` (line 377; src/common/rewind.rs).
   - No `MSG_PEEK`. `http1_only()` and `http2_only()` skip detection.
2. Timeouts. There is no timer in `ReadVersion`. A partial preface keeps polling. Graceful shutdown
   cancels detection. The HTTP/1 header timeout (default currently 30 seconds, per the doc) applies
   only after detection. Server-speaks-first: not supported.
3. Protocols. HTTP/1 versus HTTP/2 only. No plug-in.
4. TLS position. It runs on whatever I/O it is given and never consults ALPN. Over TLS it therefore
   runs after termination.
5. Documented cost: none for detection. (A "performance drop of about 5%" note in the file concerns
   `max_headers`, not detection.)
6. Sources: mod.rs above (lines 1 to 60, 200 to 400, 458 to 470, 810 to 840 read);
   https://raw.githubusercontent.com/hyperium/hyper-util/v0.1.21/src/common/rewind.rs (lines 1 to 90
   read); https://docs.rs/hyper-util/0.1.21/hyper_util/server/conn/auto/index.html.

### 2.13 Rust: tonic gRPC and axum HTTP on one port

Versions: tonic-v0.14.6; axum-v0.8.9, axum-v0.7.9, axum-v0.6.20.

1. Mechanism. There are two layers, and neither routes gRPC versus REST on first bytes.
   - Layer 1, per connection: HTTP/1 versus HTTP/2 by the 24-byte preface, through hyper-util auto.
     - axum always uses it (axum/src/serve/mod.rs lines 17, 391 and 396).
     - tonic uses it but forces `http2_only` unless `accept_http1(true)` is set. The default is
       false, and the doc says HTTP/1 is only useful for grpc-web (server/mod.rs lines 478 to 485,
       774, 801 to 805).
   - Layer 2, per request, gRPC versus REST:
     - by `content-type` starting with `application/grpc`, in axum's old rest-grpc-multiplex example;
     - or by URL path, with tonic `Routes` mounted in an axum Router at `/<ServiceName>/{*rest}`
       (tonic/src/service/router.rs lines 89 to 90, `into_axum_router` at 106, `From<axum::Router>`
       at 132).
   - The axum example is a stub at axum-v0.7.9 and is gone by axum-v0.8.0. Its last working
     version is axum-v0.6.20.
2. Timeouts. No detection timeout. tonic can time out the TLS handshake. Server-speaks-first: not
   supported.
3. Protocols: HTTP/1 (grpc-web via tonic-web), HTTP/2, gRPC. Routes are added in code.
4. TLS position. tonic's server TLS advertises only `h2` in ALPN. The TLS accept happens before
   serving, so detection runs after termination.
5. Documented cost: none.
6. Sources:
   - https://raw.githubusercontent.com/hyperium/tonic/tonic-v0.14.6/tonic/src/transport/server/mod.rs,
     tonic/src/service/router.rs, tonic/src/transport/server/service/tls.rs, tonic-web/src/lib.rs
   - https://raw.githubusercontent.com/tokio-rs/axum/axum-v0.8.9/axum/src/serve/mod.rs
   - https://raw.githubusercontent.com/tokio-rs/axum/axum-v0.7.9/examples/rest-grpc-multiplex/src/main.rs
     and multiplex_service.rs; the same files at axum-v0.6.20

### 2.14 Node.js

Version: v24.21.0 (LTS). Base URL for files: `https://raw.githubusercontent.com/nodejs/node/v24.21.0/`.

1. Mechanism.
   - `http2.createSecureServer({ allowHTTP1 })` decides by the ALPN result, not by bytes
     (lib/internal/http2/core.js lines 3346 to 3349). The server offers `h2`, plus `http/1.1` when
     `allowHTTP1` is true (lines 3461 to 3463). `allowHTTP1` defaults to false.
   - Cleartext `http2.createServer` has no `allowHTTP1` option. The docs say upgrading from non-TLS
     HTTP/1 is not supported. Inference from code: a plain socket always becomes an HTTP/2 session.
   - No documented option serves HTTP/1 and h2c prior knowledge on one plain server.
   - Plain TCP sniffing has no documented peek API. The core building blocks are:
     - `net.Server` `pauseOnConnect` (default false);
     - `readable.unshift()`, which pushes consumed bytes back;
     - emitting `'connection'` on `http.Server` (or the http2 servers) with any Duplex stream, to
       inject a connection.
     So sniffing is read and replay in user code.
2. Timeouts.
   - `unknownProtocolTimeout`, default 10000 ms, destroys a socket left after an `'unknownProtocol'`
     event. Since v19 that event fires only when `allowHTTP1` is false and the client sends no ALPN.
   - `net.Socket` has no default timeout, and its `'timeout'` event does not close the socket.
   - After hand-off, `http.Server` `headersTimeout` applies (the smaller of `requestTimeout` and
     60000). On expiry the server answers 408 and closes.
   - Server-speaks-first: only in user code.
3. Protocols. HTTP/2 and HTTP/1.1 by ALPN. Anything else is user code (the `'unknownProtocol'`
   event, or a hand-written sniffer).
4. TLS position. During the handshake (ALPN) for http2. For hand-written sniffing, the user chooses.
5. Documented cost: none.
6. Sources (base URL above): doc/api/http2.md (listed ranges read), doc/api/tls.md, doc/api/net.md,
   doc/api/stream.md (lines 1850 to 1935 read), doc/api/http.md, lib/internal/http2/core.js,
   lib/net.js (searched); https://nodejs.org/dist/index.json.

### 2.15 Netty

Version: netty-4.2.18.Final; the example is identical at netty-4.1.138.Final. Base URL for files:
`https://raw.githubusercontent.com/netty/netty/netty-4.2.18.Final/`.

1. Mechanism.
   - The example `PortUnificationServerHandler` is a `ByteToMessageDecoder`. It waits for 5 bytes and
     reads them without consuming (`getUnsignedByte` at the reader index). It recognises:
     - TLS, through `SslHandler.isEncrypted` on the record header;
     - gzip, by magic `31, 139`;
     - HTTP, by the first two letters of 9 methods;
     - the example's own protocol, by `'F'`.
     Anything else is cleared and closed.
   - Replay: the handler rewires the pipeline and removes itself. `ByteToMessageDecoder.handlerRemoved`
     then fires the accumulated buffer to the next handler. The default `MERGE_CUMULATOR` copies.
   - After TLS, detection runs again on the decrypted bytes. The example's javadoc counts five
     combinations of SSL and gzip.
   - Built-in detectors:
     - `OptionalSslHandler`: a 5-byte check, then it replaces itself with an `SslHandler`.
     - `SslClientHelloHandler`, `AbstractSniHandler` and `SniHandler`: reassemble the full ClientHello
       (`DEFAULT_MAX_CLIENT_HELLO_LENGTH = 64 * 1024`, maximum `0xFFFFFF`) and read SNI only.
     - `CleartextHttp2ServerUpgradeHandler`: prior knowledge by the 24-byte preface, or Upgrade. The
       first mismatching byte falls back to the HTTP/1 codec.
     - `HAProxyMessageDecoder.detectProtocol`: 12 bytes for v2, "PROXY" for v1, else invalid. The
       decoder itself parses any non-v2 input as v1 text.
     - `SocksPortUnificationServerHandler`: one version byte.
2. Timeouts. The example and `OptionalSslHandler` have no timer. `SniHandler` has
   `DEFAULT_HANDSHAKE_TIMEOUT_MILLIS` of 10 seconds, armed when the channel becomes active, and
   closes on expiry. `SslHandler` has a 10000 ms handshake timeout, but in the example it is added
   only after TLS bytes arrive. `ReadTimeoutHandler` has no default. Server-speaks-first: not
   supported, since detection runs only on inbound bytes.
3. Protocols. Example: TLS, gzip, HTTP/1.x, a demo protocol. Built-ins: TLS or plaintext, SNI,
   h2c prior knowledge or Upgrade, PROXY v1 and v2, SOCKS4a and SOCKS5, ALPN after TLS.
   Extension in code (a decoder, or `OptionalSslHandler.newNonSslHandler`). No registry, regex or
   config.
4. TLS position. Record-header sniff before the handshake. `SniHandler` parses the ClientHello
   before it creates the `SslHandler`. ALPN after the handshake (`ApplicationProtocolNegotiationHandler`).
5. Documented cost: none for detection. Two general decoder notes are not about detection (the
   composite cumulator may be slower; `setSingleDecode` has a performance impact).
6. Sources (base URL above): example/src/main/java/io/netty/example/portunification/PortUnificationServerHandler.java
   and PortUnificationServer.java, handler/src/main/java/io/netty/handler/ssl/OptionalSslHandler.java,
   SslClientHelloHandler.java, AbstractSniHandler.java,
   codec-http2/src/main/java/io/netty/handler/codec/http2/CleartextHttp2ServerUpgradeHandler.java,
   codec-socks/.../SocksPortUnificationServerHandler.java, handler/.../timeout/ReadTimeoutHandler.java
   (read in full); codec-base/.../ByteToMessageDecoder.java, SslHandler.java, SslUtils.java,
   SniHandler.java, ApplicationProtocolNegotiationHandler.java, Http2CodecUtil.java,
   codec-haproxy/.../HAProxyMessageDecoder.java (searched); https://netty.io/wiki/.

### 2.16 Jetty

Version: jetty-12.1.13. Base URL for files:
`https://raw.githubusercontent.com/jetty/jetty.project/jetty-12.1.13/jetty-core/`.

1. Mechanism.
   - `DetectorConnectionFactory` reads into its own buffer. The input buffer default is
     `IO.DEFAULT_BUFFER_SIZE = 8192`. It asks each `ConnectionFactory.Detecting` in turn.
   - The contract says detectors must not consume or modify the buffer. Results are `RECOGNIZED`,
     `NOT_RECOGNIZED` and `NEED_MORE_BYTES`.
   - The first RECOGNIZED wins. If all say NOT_RECOGNIZED, the next protocol in the connector list
     takes over. If the buffer fills while all want more bytes, the connection closes with an
     overflow error.
   - Replay: the unread bytes are copied into a new direct buffer and handed to the next
     connection's `onUpgradeTo`.
   - Bytes per detector: `SslConnectionFactory` needs 2 (`0x16` or `0x15`, then major version 3).
     PROXY v1 needs 5 and v2 needs 12. Detectors can nest.
2. Timeouts. No timer of its own. The endpoint idle timeout applies: default 30000 ms
   (`AbstractConnector`), reset by any byte, and it closes the connection. The PROXY v2 detector
   returns NEED_MORE_BYTES below 12 bytes even when byte 0 already mismatches. So with
   `ProxyConnectionFactory`, a first read of 1 to 11 bytes waits. Server-speaks-first: not
   supported (closed at idle timeout).
3. Protocols and extension.
   - Detectors found: SSL, PROXY v1 and v2, and the detector factory itself.
   - `OptionalSslConnectionFactory` still exists and is deprecated in favour of
     `DetectorConnectionFactory` with `SslConnectionFactory`. The same deprecation note is present
     at jetty-9.4.58.v20250814, jetty-10.0.0 and jetty-11.0.0.
   - Inference from code: PROXY is optional in practice, because detection falls through to the
     next protocol.
   - HTTP/1.1 and h2c on one connector is not a detector. `HttpConnection` parses the
     `PRI * HTTP/2.0` request and upgrades to HTTP/2 (`HTTP2CServerConnectionFactory` implements
     `ConnectionFactory.Upgrading`). The docs describe it the same way.
   - Extension in code: implement `ConnectionFactory.Detecting`.
4. TLS position. `SslConnectionFactory` sniffs 2 plaintext bytes before the handshake and does not
   parse the ClientHello. ALPN after TLS (documented connector order: tls, alpn, h2, http11).
5. Documented cost: none. A code fact, not a project statement: every upgrade copies the unread
   bytes into a newly allocated direct buffer.
6. Sources (base URL above): jetty-server/src/main/java/org/eclipse/jetty/server/DetectorConnectionFactory.java
   and OptionalSslConnectionFactory.java (read in full); ConnectionFactory.java, SslConnectionFactory.java,
   ProxyConnectionFactory.java, internal/HttpConnection.java, AbstractConnector.java,
   ServerConnector.java, jetty-io AbstractEndPoint.java, Connection.java, ssl/SslConnection.java,
   jetty-http2-server HTTP2CServerConnectionFactory.java (searched);
   https://jetty.org/docs/jetty/12.1/programming-guide/server/io-arch.html (section on bytes
   detection read in full); https://jetty.org/docs/jetty/12.1/programming-guide/server/http.html.

### 2.17 Grizzly

Version: 5.0.3 (repository eclipse-ee4j/glassfish-grizzly). The docs page was last published
2021-03-17 and describes the Grizzly 2.3 API, whose class names match 5.0.3. Base URL for files:
`https://raw.githubusercontent.com/eclipse-ee4j/glassfish-grizzly/5.0.3/modules/`.

1. Mechanism.
   - `PUFilter` tries the registered `ProtocolFinder`s in order. Results are `FOUND`, `NOT_FOUND` and
     `NEED_MORE_DATA`.
   - On FOUND, the same buffer goes to that protocol's filter chain. On NEED_MORE_DATA, the
     remainder is stored and the next data is appended to it. This is read and replay with
     accumulation.
   - `PUFilter` has no byte cap of its own.
   - `SSLProtocolFinder` needs the 5-byte header, then the whole first record.
   - `HttpProtocolFinder` checks the first byte against `G P O H D T C`, then scans for the `P/` of
     `HTTP/`. Its default request-line limit is 2048, after which it returns NOT_FOUND.
   - Unrecognised connections are closed silently by default. Detection is sticky by default.
2. Timeouts. None in `PUFilter`, `PUContext`, `ProtocolFinder` or the built-in finders.
   `IdleTimeoutFilter` exists separately. Server-speaks-first: not supported.
3. Protocols. Built in: SSL and HTTP finders. Extension in code: implement `ProtocolFinder` and build
   a chain whose first filter is `BackChannelFilter`.
4. TLS position. Record sniff before the handshake. No SNI or ALPN in the finder. Detection after TLS
   needs a second `PUFilter` after the SSL filter, which GlassFish does.
5. Documented cost: none.
6. Sources (base URL above): portunif/src/main/java/org/glassfish/grizzly/portunif/ProtocolFinder.java,
   PUFilter.java, PUContext.java, PUProtocol.java, finders/SSLProtocolFinder.java,
   finders/HttpProtocolFinder.java (read in full); https://eclipse-ee4j.github.io/glassfish-grizzly/portunification.html
   (read in full).

### 2.18 GlassFish (Grizzly port unification in an application server)

Version: 8.0.4.

1. Mechanism.
   - The default domain.xml puts `admin-listener` on a protocol with `<port-unification>`. Two
     `HttpProtocolFinder` entries send traffic to a secure admin listener or to an HTTP-to-HTTPS
     redirect.
   - `GenericGrizzlyListener` wraps secure targets in an `SSLProtocolFinder` and places the user's
     finder in an inner `PUFilter` after the SSL filter.
2. Timeouts. Whether `IdleTimeoutFilter`, the transport `READ_TIMEOUT` (30000), or the SSL
   `HANDSHAKE_TIMEOUT_MILLIS` (-1) cover the detection phase: not verified.
3. Protocols: HTTP and HTTPS on one port, plus a redirect. Users add finders with
   `asadmin create-protocol-finder --classname`. A warning string in the source says HTTP/2 is not
   supported with port unification and is disabled on that listener.
4. TLS position. TLS is sniffed before the handshake. HTTP detection runs on decrypted bytes.
5. Documented cost: none.
6. Sources: https://raw.githubusercontent.com/eclipse-ee4j/glassfish/8.0.4/appserver/admin/template/src/main/resources/config/domain.xml,
   nucleus/grizzly/config/src/main/java/org/glassfish/grizzly/config/GenericGrizzlyListener.java and
   portunif/HttpProtocolFinder.java at the same tag; https://glassfish.org/docs/latest/reference-manual.html,
   https://glassfish.org/docs/latest/security-guide.html.

### 2.19 Kestrel (ASP.NET Core)

Version: dotnet/aspnetcore v10.0.12 (also v9.0.20, v11.0.0-rc.1.26425.128); docs moniker
aspnetcore-10.0. Base URL for files:
`https://raw.githubusercontent.com/dotnet/aspnetcore/v10.0.12/src/Servers/Kestrel/Core/src/`.

1. Mechanism.
   - Cleartext `Http1AndHttp2`: no sniffing. `SelectProtocol()` returns HTTP/1 when there is no TLS
     and HTTP/1 is enabled. The code comment says HTTP/2 is ambiguous without ALPN
     (Internal/HttpConnection.cs lines 251 to 254). A startup warning says HTTP/2 is not enabled on
     an endpoint without TLS. It is logged when protocols are set explicitly.
   - Docs (endpoints): TLS with ALPN is required to support more than one HTTP version on an
     endpoint. `Http1AndHttp2` picks HTTP/2 only through ALPN, else HTTP/1.1. `Http2` alone may run
     without TLS with prior knowledge. The default endpoint protocol is `Http1AndHttp2`.
   - `Http2`-only cleartext: `TryReadPrefaceAsync` reads through the PipeReader and compares the
     24-byte preface. This is read and replay in a user-space pipe. An HTTP/1.x request line gets a
     400. That scan is capped by `MaxRequestLineSize`, default 8,192 bytes. A code comment lists
     detecting a TLS frame as a future improvement.
   - In 10.0 only, `TlsClientHelloBytesCallback` runs an internal `TlsListener`. It checks the record
     (`0x16`, version, length, handshake type 1), buffers 5 plus the record length, then rewinds.
     It sees only the first fragment.
2. Timeouts.
   - `HandshakeTimeout`, default 10 seconds. The ClientHello sniff runs under the same token.
   - HTTP/2 preface wait: `KeepAliveTimeout`, default 130 seconds.
   - HTTP/1 (inference from code): `KeepAliveTimeout` until the first non-CRLF byte, then
     `RequestHeadersTimeout`, default 30 seconds.
   - The 11.0 RC adds a ClientHello listener timeout, default 8 seconds, added on top of the
     handshake timeout. It is not in v10.0.12.
   - Server-speaks-first: not supported.
3. Protocols. HTTP/1.x, HTTP/2 (ALPN, or prior knowledge on an `Http2`-only endpoint), HTTP/3 over
   QUIC on a separate multiplexed transport. Extension: connection middleware (`ListenOptions.Use`).
   The only official sample runs after `UseHttps`. No official sample peeks bytes with the
   PipeReader. No PROXY protocol support was found in the docs read.
4. TLS position. ALPN after the handshake. An optional raw ClientHello callback runs before it
   (10.0). SNI certificate selection callbacks.
5. Documented cost: none.
6. Sources (base URL above): Internal/HttpConnection.cs (SelectProtocol read in full),
   Internal/Http2/Http2Connection.cs (TryReadPrefaceAsync read in full), Middleware/TlsListener.cs,
   Middleware/HttpsConnectionMiddleware.cs, Internal/KestrelServerImpl.cs,
   Internal/Infrastructure/KestrelTrace.General.cs, KestrelServerLimits.cs,
   Internal/Http/Http1Connection.cs, HttpsConnectionAdapterOptions.cs;
   https://raw.githubusercontent.com/dotnet/AspNetCore.Docs/0998e7d9c395b093a0670ef0204d0cc49b49cab3/aspnetcore/fundamentals/servers/kestrel/endpoints.md
   (lines 506 to 516 read);
   https://learn.microsoft.com/en-us/aspnet/core/fundamentals/servers/kestrel/endpoints?view=aspnetcore-10.0,
   .../kestrel/connection-middleware?view=aspnetcore-10.0, .../kestrel/options?view=aspnetcore-10.0,
   .../kestrel/http3?view=aspnetcore-10.0;
   https://learn.microsoft.com/en-us/dotnet/api/microsoft.aspnetcore.server.kestrel.core.httpprotocols?view=aspnetcore-9.0.

### 2.20 h2o

Version: master commit cac7e6568ad98a848f099ecd0a18b881f632479a (2026-09-10). The last version tags
are v2.2.6 and v2.3.0-beta2 (2019-08-13). A release note says the project stopped tagging in 2019
and advises users to track master. Base URL for files:
`https://raw.githubusercontent.com/h2o/h2o/cac7e6568ad98a848f099ecd0a18b881f632479a/`.

1. Mechanism.
   - No pre-dispatch sniffer. A plain listener goes straight to the HTTP/1 handler.
   - The prior-knowledge check sits in the HTTP/1 parser's error path (lib/http1.c). If parsing fails
     and the input starts with `PRI * HTTP/2` (12 bytes), and HTTP/2 upgrade is enabled, the
     connection goes to HTTP/2. HTTP/2 re-feeds the buffered input and checks the full 24-byte
     preface. This is read and replay.
   - The bound is `H2O_MAX_REQLEN (8192 + 4096 * (H2O_MAX_HEADERS))`. The value of
     `H2O_MAX_HEADERS`: not verified.
2. Timeouts. `http1-request-timeout` default 10 s; `http1-request-io-timeout` default 5 s;
   `handshake-timeout` default 10 s (PROXY and TLS included). All close on expiry. Whether a
   partial `PRI * H` first read waits: not verified. Server-speaks-first: not supported.
3. Protocols. HTTP/1.x; h2c by prior knowledge or Upgrade, both gated by `http1-upgrade-to-http2`
   (default ON); ALPN `h2`, `h2-16`, `h2-14` or `http/1.1`; HTTP/3 on the listen directive.
   PROXY is optional (`proxy-protocol`, default OFF). When on, h2o tries to parse v1. If the bytes do
   not match, they are treated as the start of TLS or HTTP. No user mechanism for new protocols was
   found (not verified).
4. TLS position. The PROXY line is read before TLS. ALPN picks the protocol after the handshake.
   Inference: the `PRI * HTTP/2` check does not test for TLS. Behaviour over TLS without ALPN h2:
   not verified.
5. Documented cost: none.
6. Sources (base URL above): lib/http1.c, lib/http2/connection.c, lib/core/util.c, include/h2o.h
   (searched; quoted blocks read); https://h2o.examp1e.net/configure/http1_directives.html (read in
   full); https://h2o.examp1e.net/configure/base_directives.html,
   https://h2o.examp1e.net/configure/http2_directives.html (searched); https://github.com/h2o/h2o/tags.

### 2.21 Apache httpd, mod_http2 (`H2Direct`)

Version: 2.4.69; docs at httpd.apache.org/docs/2.4.

1. Mechanism.
   - Docs: `H2Direct` is on by default for h2c and off for h2. When the first bytes match the HTTP/2
     preamble, the connection switches to HTTP/2 at once.
   - Code (modules/http2/h2_c1.c): a blocking `AP_MODE_SPECULATIVE` read of 24 bytes, compared with
     `H2_MAGIC_TOKEN`. A speculative read keeps the data for later, so this is read and replay in
     the filter chain, at most 24 bytes.
   - Inference from code: a first segment under 24 bytes is not detected, and the connection stays
     HTTP/1.1.
2. Timeouts and server-speaks-first.
   - The docs address the hanging-read risk directly. If a server or vhost does not enable h2 or h2c
     in `Protocols`, the connection is never inspected. The docs name NNTP as a protocol whose
     initial read might hang.
   - The default `Protocols` is `http/1.1`, so nothing is inspected out of the box.
   - The blocking peek is bounded by core `TimeOut`, default 60.
   - Inference: mod_reqtimeout's handshake stage is disabled by default, so only `TimeOut` applies
     during the peek.
3. Protocols. http/1.1, h2c direct, h2c Upgrade (`H2Upgrade`), and h2 via ALPN. Modules can add
   protocols through the protocol propose, switch and get hooks plus the `Protocols` directive.
   The 24-byte detection is specific to mod_http2.
4. TLS position. Direct mode is off on TLS by default. Inference: on TLS, detection reads after
   mod_ssl decryption.
5. Documented cost: the docs state only a benefit (no upgrade round, better performance). No
   overhead is documented.
6. Sources: https://httpd.apache.org/docs/2.4/mod/mod_http2.html, https://httpd.apache.org/docs/2.4/mod/core.html,
   https://httpd.apache.org/docs/2.4/mod/mod_reqtimeout.html (searched);
   https://raw.githubusercontent.com/apache/httpd/2.4.69/modules/http2/h2_c1.c (lines 215 to 300
   read), modules/http2/h2_switch.c, server/core_filters.c, include/util_filter.h,
   modules/filters/mod_reqtimeout.c (searched).

### 2.22 Vert.x

Version: 5.2.0 (constant also checked at 4.5.34). Base URL for files:
`https://raw.githubusercontent.com/eclipse-vertx/vert.x/5.2.0/vertx-core/src/main/java/io/vertx/core/`.

1. Mechanism.
   - `Http1xOrH2CHandler` compares the preface byte by byte across reads. It stops at the first
     mismatching byte. When it decides, it rebuilds the consumed prefix and replays it. This is read
     and replay, at most 24 bytes.
   - It is installed in the non-SSL branch when HTTP/2 is configured, to support h2c with prior
     knowledge. `http2ClearTextEnabled` defaults to true.
   - The docs and the code give different preface strings (section 1.3).
   - How the option becomes the HTTP/2 config in the initializer was not traced line by line.
2. Timeouts. No timer on the detection handler. `idleTimeout` defaults to 0, meaning none.
   Inference: a silent cleartext client is not timed out by default. The SSL handshake timeout is
   10 s. The PROXY timeout is 10 s, and `useProxyProtocol` defaults to false. Server-speaks-first:
   not supported.
3. Protocols. HTTP/1.x, h2c by Upgrade and prior knowledge, h2 via ALPN, HTTP/3. PROXY is opt-in.
   No documented way to add a first-bytes protocol.
4. TLS position. ALPN after the handshake. The sniff is cleartext only.
5. Documented cost: none. The docs note that browsers do not support h2c.
6. Sources (base URL above): http/impl/tcp/Http1xOrH2CHandler.java (read in full),
   http/impl/tcp/HttpServerConnectionInitializer.java, http/HttpServerOptions.java,
   http/HttpServerConfig.java, net/NetServerOptions.java (searched); https://vertx.io/docs/vertx-core/java/.

### 2.23 Cowboy and Ranch (Erlang)

Versions: Cowboy 2.19.0, Ranch 2.3.0.

1. Mechanism.
   - Cowboy has no separate sniffer. The clear listener starts the HTTP/1.1 handler unless only
     http2 is configured.
   - The request-line parser recognises `PRI * HTTP/2.0\r\n` at the start of the connection (first
     stream only). It hands the buffer to the HTTP/2 handler if `http2` is in `protocols` (default
     `[http2, http]`), else it answers 501. This is read and replay, needing the first 16 bytes.
   - The guide says the clear port expects HTTP/1.1 or HTTP/2, by Upgrade or by direct preface.
   - Ranch does no protocol detection. A protocol handler is user code (`ranch_protocol`).
   - Ranch's PROXY parsing reads once, parses, and returns the rest with `gen_tcp:unrecv`. Behaviour
     with a header split across segments: not verified.
2. Timeouts. `request_timeout` 5000 ms and `idle_timeout` 60000 ms (manual). With no request line
   before the timeout, the connection ends with a timeout error. PROXY is mandatory once enabled
   (`proxy_header`, default false; read with a 1000 ms timeout; failure exits).
   Server-speaks-first: not supported.
3. Protocols. HTTP/1.1 and HTTP/2 on the clear port; others by writing a Ranch protocol.
4. TLS position. Clear port: plaintext sniff. TLS port: ALPN, with `alpn_default_protocol`
   defaulting to http. A preface sent over TLS without ALPN is refused.
5. Documented cost: none.
6. Sources: https://ninenines.eu/docs/en/cowboy/2.19/guide/listeners/ (read in full);
   https://ninenines.eu/docs/en/cowboy/2.19/manual/cowboy_http/;
   https://raw.githubusercontent.com/ninenines/cowboy/2.19.0/src/cowboy_clear.erl (read in full) and
   src/cowboy_http.erl (searched); https://raw.githubusercontent.com/ninenines/ranch/2.3.0/src/ranch_tcp.erl;
   https://ninenines.eu/docs/en/ranch/2.3/manual/ranch.recv_proxy_header/,
   https://ninenines.eu/docs/en/ranch/2.3/guide/protocols/.

### 2.24 Apache Tomcat

Version: 11.0.26. Base URL for files: `https://raw.githubusercontent.com/apache/tomcat/11.0.26/java/org/apache/`.

1. Mechanism.
   - Docs: HTTP/2 is available as h2 over TLS, h2c by Upgrade, and direct h2c. It is enabled by
     nesting the `Http2Protocol` UpgradeProtocol in an HTTP/1.1 connector.
   - Code (`Http11InputBuffer.parseRequestLine`): the preface is compared only on a fresh
     connection, at buffer position 0, with at least 24 bytes buffered. A match returns UPGRADING.
     `AbstractProtocol` then calls `unRead` on the leftover input and assumes direct h2c. This is
     read and replay, at most 24 bytes.
   - Inference from code: a first fill under 24 bytes skips detection, and the bytes are parsed as an
     HTTP/1.1 request line.
   - Inference: with no UpgradeProtocol configured, a matched preface closes the connection.
2. Timeouts. `connectionTimeout`, default 60000 ms; the shipped server.xml sets 20000. HTTP/2
   `keepAliveTimeout`, default 20000. Server-speaks-first: not supported.
3. Protocols. HTTP/1.1, h2c (Upgrade and direct), h2 over TLS. Users can nest UpgradeProtocol
   implementations. Direct detection is hard-wired to h2c.
4. TLS position.
   - TLS connectors parse the ClientHello before the handshake (`TLSClientHelloExtractor`: SNI,
     ALPN list, ciphers; first byte 22).
   - Cleartext HTTP on a TLS connector is classed `NON_SECURE` and answered with a 400 saying TLS is
     required. Tomcat rejects it; it does not serve both.
   - h2 is chosen by ALPN.
5. Documented cost: none for detection.
6. Sources: https://tomcat.apache.org/tomcat-11.0-doc/config/http.html,
   https://tomcat.apache.org/tomcat-11.0-doc/config/http2.html (searched); base URL above:
   coyote/http11/Http11InputBuffer.java (lines 300 to 380 read), coyote/http11/Http11Processor.java,
   coyote/AbstractProtocol.java, tomcat/util/net/TLSClientHelloExtractor.java,
   tomcat/util/net/SecureNioChannel.java (searched).

### 2.25 PostgreSQL 17 and later (direct TLS and SSLRequest on one port)

Versions: REL_18_6 and REL_17_11; docs 18 and 17. Base URL for files:
`https://raw.githubusercontent.com/postgres/postgres/REL_18_6/src/`.

1. Mechanism.
   - One byte decides. `ProcessSSLStartup` (backend/tcop/backend_startup.c) peeks one byte with
     `pq_peekbyte()`. If it is not `0x16`, startup proceeds as before (SSLRequest, StartupMessage,
     GSSENCRequest, CancelRequest).
   - A code comment explains why `0x16` is safe: as a startup length it would mean a packet hundreds
     of megabytes long.
   - The peek is into the user-space receive buffer, not `MSG_PEEK`. The buffered bytes are later
     pushed into the TLS setup. This is read and replay. The same check exists at REL_17_11.
2. Timeouts. `authentication_timeout` (default 1 min) is armed before the peek. A code comment says
   a hostile client could hold a process for nearly twice that. The protocol is client-first.
3. Protocols. Direct TLS versus PostgreSQL startup packets. Not extensible.
4. TLS position. The sniff is before TLS, on the record's first byte. After the handshake, ALPN
   `postgresql` is required; other values are refused with a `no_application_protocol` alert. libpq
   `sslnegotiation=direct` was introduced in 17 and needs `sslmode=require` or higher.
5. Documented cost. The docs give only the benefit: one fewer round trip. The downside they give is
   that direct mode cannot negotiate the best encryption or an unencrypted connection. No overhead
   is documented.
6. Sources: https://www.postgresql.org/docs/current/protocol-flow.html,
   https://www.postgresql.org/docs/18/protocol-message-formats.html,
   https://www.postgresql.org/docs/17/protocol-message-formats.html,
   https://www.postgresql.org/docs/18/libpq-connect.html,
   https://www.postgresql.org/docs/18/runtime-config-connection.html; base URL above:
   backend/tcop/backend_startup.c (ProcessSSLStartup read in full), backend/libpq/pqcomm.c,
   backend/libpq/be-secure.c, backend/libpq/be-secure-openssl.c.

### 2.26 Kernel and OS mechanisms

**Linux `SO_REUSEPORT` with a `BPF_PROG_TYPE_SK_REUSEPORT` program.**
- Use: the program picks which socket in a reuseport group takes a new connection or datagram.
  socket(7) dates the program type to Linux 4.19. Reuseport BPF itself dates to 4.5 for UDP and
  4.6 for TCP.
- What it sees: `struct sk_reuseport_md` (include/uapi/linux/bpf.h at v7.2) exposes data from the
  TCP or UDP header on, a length, protocol fields, a 4-tuple hash, and the socket.
- When it runs: a comment in that struct says that for TCP it selects a listener for the received
  SYN. Inference: an ordinary SYN carries no application bytes, so the program cannot see them on
  TCP.
- TCP Fast Open data in the SYN: not verified. For UDP, the classic filter path advances the data
  pointer to the payload, so each datagram's payload is visible (net/core/sock_reuseport.c).
- Timeout: none, since it does not wait for data. Protocols: none built in. Documented cost: only
  qualitative (load distribution).
- Sources: https://man7.org/linux/man-pages/man7/socket.7.html;
  https://raw.githubusercontent.com/torvalds/linux/v7.2/include/uapi/linux/bpf.h,
  net/core/sock_reuseport.c, net/ipv4/inet_hashtables.c, include/net/inet_hashtables.h.

**Linux `BPF_PROG_TYPE_SK_LOOKUP`.**
- When it runs: whenever the transport layer looks for a listening TCP socket or an unconnected
  UDP socket for an incoming packet. Established traffic does not trigger it.
- What it sees: `struct bpf_sk_lookup` has family, protocol, local and remote addresses and ports,
  and the ingress interface. It has no data pointers, so no payload. It selects a socket with
  `bpf_sk_assign()`, usually from a SOCKMAP.
- Version: the docs do not state it. The type is present in bpf.h at v5.9 and absent at v5.8.
- Order: in v7.2 it runs before reuseport selection.
- Documented cost: none for the hook. It routes by address, port and interface only.
- Sources: https://docs.kernel.org/bpf/prog_sk_lookup.html (read in full); bpf.h at v5.8, v5.9, v7.2.

**Linux `TCP_DEFER_ACCEPT`.**
- Use: tcp(7) says the listener is woken only when data arrives. The value is in seconds and is
  rounded up to a retransmit duration. It does not route or peek, and the data stays in the socket.
- Expiry: tcp(7) does not say what happens. Inference from source (net/ipv4/inet_connection_sock.c
  around lines 841 to 843): at the end of the deferral the kernel retransmits to give a last
  chance, so a client that speaks second is accepted late, not refused.
- tcp(7) warns the option is not portable.
- Sources: https://man7.org/linux/man-pages/man7/tcp.7.html; v7.2 net/ipv4/inet_connection_sock.c,
  net/ipv4/tcp_minisocks.c.

**FreeBSD accept filters.**
- Use: the kernel withholds a connection from `accept()` until a condition holds. The bytes stay
  in the socket, and no filter routes to a different socket.
  - accf_data waits for any data.
  - accf_http waits for a full HTTP/1.0 or 1.1 GET or HEAD request, and passes other input through.
  - accf_dns reads a 2-byte length and waits for that many bytes.
  - accf_tls (since FreeBSD 15.0) checks byte 0 for `0x16`, reads the 2-byte length at offset 3,
    and waits for the whole handshake record. Other first bytes pass through.
- Timeout: none in the pages read. listen(2): when the queue of not-yet-ready sockets is full, the
  oldest one is dropped. New filters are kernel modules.
- Documented cost: accf_http and accf_tls claim reduced CPU use. No numbers.
- Sources: https://man.freebsd.org/cgi/man.cgi?query=accept_filter&sektion=9&format=ascii, and the
  same URL with query=accf_data, accf_http, accf_dns, accf_tls; listen(2) and setsockopt(2).

**Linux sockmap with `BPF_PROG_TYPE_SK_SKB` stream parser and verdict.**
- Use: once a socket is inserted into a SOCKMAP or SOCKHASH, a parser program frames the stream.
  A verdict program can drop, pass, or redirect the data to another socket in the map.
- The verdict program can read payload: `data` is a packet pointer for this program type
  (net/core/filter.c at v7.2).
- It moves data, not the connection, and needs the socket placed in the map first. SOCKMAP dates
  from 4.14 and SOCKHASH from 4.18.
- No timeout for a parser waiting on bytes is documented.
- Sources: https://docs.kernel.org/bpf/map_sockmap.html (read in full);
  https://docs.kernel.org/networking/strparser.html; v7.2 net/core/filter.c.

**Windows.**
- HTTP.sys is a kernel-mode HTTP stack that lets several applications share one TCP port by URL
  namespace. It handles HTTP only.
- Net.TCP Port Sharing is a user-mode service that reads the incoming net.tcp message stream to
  find the destination. It handles net.tcp only.
- `AcceptEx` can return the first block of client data with the accept. With a receive buffer it
  does not complete until data arrives, and there is no built-in timeout; the docs suggest checking
  `SO_CONNECT_TIME`. It is an API, not routing.
- No documented Windows mechanism was found that splits one TCP port across different protocols
  by first bytes.
- Sources: https://learn.microsoft.com/en-us/iis/get-started/introduction-to-iis/introduction-to-iis-architecture,
  https://learn.microsoft.com/en-us/windows/win32/http/about-http-server-api,
  https://learn.microsoft.com/en-us/dotnet/framework/wcf/feature-details/net-tcp-port-sharing,
  https://learn.microsoft.com/en-us/windows/win32/api/mswsock/nf-mswsock-acceptex.

Not checked: netfilter or nftables payload matching, XDP, Linux KCM, Windows Filtering Platform.

## 3. First-bytes signatures

Classes used in the "Who speaks first" column:
- **Client**: the spec requires the client to send first.
- **Server**: the spec has the server send a greeting first, and the client should wait. No spec
  text forbids an early client send, but a server cannot rely on one. A listener that waits for
  client bytes stalls compliant clients. This is a basic limit for first-bytes demultiplexing.
- **Both**: both sides send on connect, and no order is required.

| Protocol | Transport | Who speaks first | First bytes (hex, ASCII) | Bytes needed to decide | Primary source |
|---|---|---|---|---|---|
| TLS ClientHello | TCP | Client (REQUIRED, RFC 8446 s4.1.2) | `16 03 01 LL LL 01` or `16 03 03 LL LL 01`: handshake(22), legacy_record_version, length (at most 2^14), client_hello(1). Older clients may send `16 03 XX` | 6. SNI and ALPN sit in extensions and may span several records | RFC 8446 s4, s4.1.2, s5.1, App. D.5; RFC 5246 App. E.1; RFC 6066 s3; RFC 7301 s3.1 (https://www.rfc-editor.org/rfc/rfc8446.txt) |
| HTTP/2 connection preface (prior knowledge) | TCP cleartext | Client. The server also sends a preface, but the client does not wait for it | `50 52 49 20 2A 20 48 54 54 50 2F 32 2E 30 0D 0A 0D 0A 53 4D 0D 0A 0D 0A` = `PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n`, then SETTINGS | 24 | RFC 9113 s3.3, s3.4, App. B (https://www.rfc-editor.org/rfc/rfc9113.txt) |
| HTTP/1.x request line | TCP, or TLS with ALPN `http/1.1` | Client | method token, SP, target, SP, `HTTP/x.y`, CRLF; e.g. `47 45 54 20` "GET ". A server should ignore at least one leading CRLF | Token plus SP: at most 8 bytes for the 8 RFC 9110 methods, plus any skipped CRLF (derived). The HTTP-version at line end confirms it | RFC 9112 s2.2, s2.3, s3; RFC 9110 s5.6.2, s9.1 (https://www.rfc-editor.org/rfc/rfc9112.txt) |
| PROXY v1 | TCP, prepended by the connection initiator | Client side (the proxy) | `50 52 4F 58 59 20` "PROXY ", then `TCP4`, `TCP6` or `UNKNOWN`; line at most 107 bytes with CRLF | At least 8 with the first 5 = "PROXY", then read to CRLF | HAProxy doc/proxy-protocol.txt s2.1, s2.2 (v3.4.6 and v3.2.0 copies) |
| PROXY v2 | TCP, prepended | Client side (the proxy) | `0D 0A 0D 0A 00 0D 0A 51 55 49 54 0A`, then version/command `0x20` or `0x21`, family, 2-byte length | At least 16 with the first 13 = signature plus version 2. Configured, never guessed | same, s2.2, s5 |
| SSH identification string | TCP | **Both** (spec). Spec and implementation below | `53 53 48 2D` "SSH-", then `2.0-` | 4 for "SSH-", 8 for "SSH-2.0-". At most 255 bytes per RFC; OpenSSH accepts up to 8192 | RFC 4253 s4.2, s5.2 (https://www.rfc-editor.org/rfc/rfc4253.txt); OpenSSH V_10_0_P2 kex.c, ssh.h |
| PostgreSQL SSLRequest | TCP | Client | `00 00 00 08 04 D2 16 2F` (length 8, code 80877103) | 8 | PG 18 docs, protocol-message-formats s54.7 (https://www.postgresql.org/docs/18/protocol-message-formats.html) |
| PostgreSQL GSSENCRequest, CancelRequest | TCP | Client | `00 00 00 08 04 D2 16 30` (80877104); CancelRequest: length, then `04 D2 16 2E` (80877102; 16 bytes in 3.0, variable in 3.2) | 8 | same |
| PostgreSQL StartupMessage | TCP | Client | Int32 length, then `00 03 00 00` (3.0, 196608) or `00 03 00 02` (3.2, 196610, PG 18 docs) | 8 | PG 18 and PG 17 docs; PG 18 notes libpq still uses 3.0 by default |
| PostgreSQL direct TLS (17+) | TCP | Client | TLS ClientHello with ALPN `postgresql` | 1 byte (`0x16`) in the server | PG 18 protocol-flow s54.2.10; source REL_18_6 |
| MQTT CONNECT (3.1.1, 5.0) | TCP (also TLS, WebSocket) | Client (first packet MUST be CONNECT) | `10`, Remaining Length (1 to 4 bytes), `00 04 4D 51 54 54` "MQTT", level `04` (3.1.1) or `05` (5.0) | Name ends at byte 8 to 11; level at byte 9 to 12 | OASIS MQTT 3.1.1 s2.2.3, s3.1, s3.1.1, s3.1.2.1, s3.1.2.2 (https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html); MQTT 5.0 s1.5.5, s3.1.2.2 (https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html) |
| Redis RESP | TCP | Client (request-response). Exception: protected mode sends `-DENIED` unconditionally | `2A` "*" (array of bulk strings). Inline commands are plain text with no marker. RESP3 sessions should start with HELLO | 1 for the array form. The inline form has no signature | https://redis.io/docs/latest/develop/reference/protocol-spec/ ; Redis 8.0.0 src/networking.c |
| QUIC long header (for contrast) | UDP | Client in v1 (Initial). Not invariant across versions (RFC 8999 App. A) | byte 0 has `0x80` (long header) and `0x40` (fixed bit, v1); type bits `00` for a v1 Initial; version `00 00 00 01` (v1) or `6B 33 43 CF` (v2) | 5 (byte 0 plus version). Per datagram; client Initial datagrams are at least 1200 bytes. No connection-level first read | RFC 9000 s14.1, s15, s17.2, s17.2.2; RFC 8999 s5; RFC 9369 s3 |
| SMTP | TCP | **Server** (220 greeting, or 554); the client SHOULD wait | server sends `32 32 30` "220" | not applicable | RFC 5321 s3.1, s4.3.1 (https://www.rfc-editor.org/rfc/rfc5321.txt) |
| FTP | TCP | **Server** (220 reply); the user should wait | server sends "220" (or "120" then "220") | not applicable | RFC 959 s5.4 |
| POP3 | TCP | **Server** (greeting) | server sends "+OK ..." | not applicable | RFC 1939 s3, s4 |
| IMAP4rev2 | TCP | **Server** (greeting) | server sends `*` SP then OK, PREAUTH or BYE | not applicable | RFC 9051 s2.2, s3, s9 |
| MySQL | TCP | **Server** (Initial Handshake packet) | 4-byte packet header, then protocol version 10 (`0x0A`), or an ERR packet | not applicable | https://dev.mysql.com/doc/dev/mysql-server/latest/page_protocol_connection_phase.html (no section numbers; no version attached) |
| VNC (RFB) | TCP | **Server** (ProtocolVersion first) | server sends `52 46 42 20 30 30 33 2E 30 30 38 0A` "RFB 003.008\n" | not applicable | RFC 6143 s7.1.1 |
| Implicit TLS mail (pop3s, imaps, submissions) | TCP | Client (TLS starts at once) | a TLS ClientHello; ALPN ids `imap`, `pop3`, `ftp` are registered; no SMTP id was found | 6, plus ALPN | RFC 8314 s3.1 to s3.3; IANA ALPN registry |
| AMQP 1.0 | TCP | Client MUST send at once; the server MAY wait, or may send first | `41 4D 51 50 00 01 00 00` "AMQP" 0 1.0.0; TLS layer `... 02 01 00 00`; SASL layer `... 03 01 00 00` | 8 | OASIS AMQP 1.0 transport s2.2; security s5.2, s5.3 |
| AMQP 0-9-1 | TCP | Client (implementation only) | `41 4D 51 50 00 00 09 01`. Spec text not verified | 8 (RabbitMQ reads 8) | RabbitMQ v4.1.0 deps/rabbit/src/rabbit_reader.erl |
| XMPP | TCP | Client (initiating entity) | `3C 3F 78 6D 6C` "<?xml" (SHOULD), then the stream header | 1 byte "<" excludes an HTTP token (derived); 5 for "<?xml" | RFC 6120 s4.2, s11.5, s11.6 |
| DNS over TCP | TCP | Client | 2-byte length, then the message. No constant bytes (derived) | hard to fingerprint | RFC 1035 s4.2.2; RFC 7766 s8 |
| WebSocket | TCP | Client | an HTTP/1.1 `GET ` request line | not decidable from first bytes; needs the Upgrade header | RFC 6455 s4.1 |
| TCPMUX (Historic) | TCP port 1 | Client | a service name, then CRLF; the server answers `+` or `-` | up to the CRLF | RFC 1078; RFC 7805 s2.1 |
| UDP first-byte demux (STUN, ZRTP, DTLS, TURN, RTP, QUIC) | UDP | per packet | ranges of byte 0: 0 to 3 STUN, 16 to 19 ZRTP, 20 to 63 DTLS, 64 to 79 TURN channel or QUIC, 80 to 127 QUIC, 128 to 191 RTP/RTCP, 192 to 255 QUIC | 1, plus source address for 64 to 79 | RFC 9443 s3 (updates RFC 7983) |

### 3.1 SSH: spec versus implementation

- Spec (RFC 4253 s4.2): both sides must send an identification string once the connection is up.
  The server may send other lines before its version string. Section 5.2 lets a client send data
  right after its own identification string, before it receives the server's. No text requires a
  client to send without waiting.
- Implementation (OpenSSH portable V_10_0_P2, kex.c `kex_exchange_identification`): each side sends
  its own banner first, then reads the peer's. The client calls it from sshconnect.c. The server
  rejects lines before the client's SSH identification. `SSH_MAX_BANNER_LEN` is 8192.
- sslh's docs report that many SSH clients wait for the server banner (section 2.8). Other SSH
  clients were not checked.
- So SSH works on a first-bytes listener only with clients that send first, or behind a timeout
  fallback.

### 3.2 Ambiguities a demultiplexer must handle

Each item rests on the cited spec text. "Derived" marks reasoning from that text.
1. The PROXY v2 signature starts with `0D 0A 0D 0A`, and RFC 9112 s2.2 tells HTTP servers to skip a
   leading CRLF. A configured PROXY check must therefore run before any HTTP/1 CRLF skipping
   (derived).
2. The HTTP/2 preface parses as an HTTP/1 request line with method PRI (RFC 7540 s11.6). Test all 24
   bytes before falling back to HTTP/1. h2c Upgrade is deprecated (RFC 9113 App. B), so cleartext
   HTTP/2 now arrives only through the preface.
3. The TLS record version is not a reliable key. RFC 8446 s5.1 allows `0x0301` or `0x0303` and says
   the field must be ignored. RFC 5246 App. E.1 lets older clients send any `03 XX`.
4. SNI and ALPN may need more than one record. RFC 8446 s5.1 allows a handshake message to be
   fragmented across records.
5. The SSH order is not guaranteed (section 3.1).
6. `SSH-` is a legal HTTP token prefix (S, H and `-` are all tchar, RFC 9110 s5.6.2). Test it before
   HTTP/1 (derived).
7. MQTT's Remaining Length is 1 to 4 bytes, so the protocol name starts at offset 2 to 5. MQTT 5.0
   says a multi-protocol server uses the protocol name to recognise MQTT.
8. Redis inline commands have no signature. An inline `GET key` and the HTTP `GET / HTTP/1.1` share
   their first 4 bytes, and only the HTTP-version token separates them. Redis itself rejects
   first arguments `post` and `host:` (src/server.c, 8.0.0).
9. RFC 9112 s3 allows lenient whitespace parsing and warns that it can enable request smuggling. A
   strict "token plus SP" test is the safe reading.
10. TLS versus PostgreSQL on one port: PostgreSQL 17+ requires ALPN `postgresql` against protocol
    confusion. A shared TLS listener must route by ALPN among `http/1.1`, `h2`, `postgresql`,
    `mqtt`, `imap`, `pop3` and others.
11. Server-first protocols cannot be recognised from client bytes. Implicit TLS (RFC 8314) makes
    pop3s, imaps and submissions client-first at the TCP layer. One surveyed workaround: sshttp's
    SMTP mode sends a greeting first that serves both SMTP and SSH. This relies on RFC 4253 s4.2
    letting an SSH server send lines before its version string. sshttp then reads the client's
    reply and drops the backend's real banner, and it does not support multiline SMTP banners
    (section 2.9).
12. QUIC first-byte bits are version-specific (RFC 8999 App. A; RFC 9369 s3.2). RFC 9443 forbids
    the grease_quic_bit transport parameter for endpoints that multiplex.
13. PostgreSQL and DNS over TCP both start with a big-endian length, so both often begin with
    `0x00`. Telling them apart needs bytes 4 to 7 (derived; DNS header constants not verified).
14. Some client-first protocols allow server-first behaviour: an AMQP 1.0 server may send first,
    Redis protected mode sends `-DENIED`, and an SMTP server may open with 554.

Not verified in this section: the AMQP 0-9-1 spec text, SSH clients other than OpenSSH, the full
IANA HTTP Method Registry, MQTT 3.1 (`MQIsdp`), where PostgreSQL enforces
`MAX_STARTUP_PACKET_LENGTH` (10000), and MySQL integer byte order.

## 4. Comparison table

"Read and replay" means the bytes are read from the socket into a user-space buffer and later
handed to the chosen protocol. "Peek" means `MSG_PEEK` (bytes stay in the kernel). "n/a" means the
system handles only client-first protocols on that listener.

| System | Mechanism | Peek or read | Max bytes before decision | Server-speaks-first handling | Extensible | TLS position | Documented cost |
|---|---|---|---|---|---|---|---|
| nginx stream `ssl_preread` | ClientHello parse in preread phase | Peek on non-TLS, edge-triggered kqueue or epoll-RDHUP; else read and replay | `preread_buffer_size` 16k | Not supported: closed at `preread_timeout` 30s | njs `js_preread` (code) | Before handshake (SNI, ALPN, version) | None |
| nginx HTTP listener | 24-byte preface compare on plain listener | Read and reuse; 1-byte peek for TLS check on `ssl` listeners | 24, within `client_header_buffer_size` 1k | n/a; `client_header_timeout` 60s closes | No | Preface plaintext only; ALPN over TLS | None |
| HAProxy | `tcp-request content` rules; h2 preface in HTTP mode | Read and replay; peek only for PROXY header | 16384 minus 1024 = 15360 (derived) | `inspect-delay` (no default), then default backend; docs name SMTP | ACLs with `req.payload` bin or regex; Lua | Both: raw ClientHello fetches before; ALPN after termination | None (rules re-run per chunk) |
| Envoy | Listener filters, then FilterChainMatch | Peek; drain only for PROXY | TLS 16 KiB (proto, code; docs say 64KiB); HTTP 64 KiB | `listener_filters_timeout` 15s then close, or default chain if `continue_on_listener_filters_timeout` | C++ filter or dynamic module | Before handshake; termination in chosen chain | None |
| Traefik | First byte, ClientHello, PG STARTTLS 8 bytes | Read and replay (bufio wrapper) | No Traefik cap; Go bufio 4096, `maxHandshake` 65536 | Peek skipped only if no TCP-TLS or HTTPS routers; else `readTimeout` 60s then close (inference) | No (four matchers) | Before handshake (SNI, ALPN) | Only "HostSNI more efficient" |
| caddy-l4 | Ordered routes of matchers | Read and replay (record, rewind) | `MaxMatchingBytes` 16 KiB (can overshoot by up to 2047) | `matching_timeout` 3s then close; a non-reading matcher first can take silent clients (inference) | Caddy modules; regexp matcher | Both; matching continues after tls handler | Guidance only |
| sslh | Probes on accumulated data | Read and replay | No cap (realloc); `BUFSIZ` per read (8192 in glibc) | `timeout` (code 5 s, man page 2s) then `on-timeout` (code "ssh") | Regex probe (PCRE2); C probes | Before handshake (SNI, ALPN) | fork: many processes; select: 16 bytes per connection; ev: thousands |
| sshttp | `SSH-` prefix, SNI table | Peek, once (SMTP mode: read and replay) | 2048 | 2 s (compile time), then SSH. SMTP mode: sends its own composite SMTP plus SSH banner first, then reads `SSH` or `HELO`, and drops the backend's banner | SNI via `-N`; else code | Before handshake (SNI) | Qualitative only |
| Go cmux | Ordered matchers | Read and replay | Prefix plus 1; 24 (HTTP2); 4096 (HTTP1); unbounded for header-field matchers | No default timeout; with `SetReadTimeout`, `Any()` can take silent clients (inference) | `Matcher` / `MatchWriter` funcs | Record header only, before TLS | "Negligible", no numbers |
| Go net/http | Preface check on non-TLS | User-space `bufio` Peek, then reuse | 24 | n/a; `ReadHeaderTimeout` default none | No | Plaintext; ALPN over TLS | None |
| hyper-util auto | Preface read | Read and replay (`Rewind`) | 24 | n/a; no detection timer | No | After termination | None |
| tonic with axum | HTTP version per connection, gRPC per request | Read and replay (via hyper-util) | 24, then HTTP headers | n/a | Routes in code | After termination; tonic offers ALPN h2 only | None |
| Node.js http2 `allowHTTP1` | ALPN result | n/a (inside TLS) | n/a | n/a; `unknownProtocolTimeout` 10000 ms | `'unknownProtocol'` event | During handshake | None |
| Node.js core sniffing | User code with `unshift` and `emit('connection')` | Read and replay (user code) | User code | User code | User code | User choice | None |
| Netty | `ByteToMessageDecoder` handlers | Read and replay (cumulation) | Example 5; SNI ClientHello 64 KiB default | Not supported; `SniHandler` 10 s | Code | Record sniff before; SNI before; ALPN after; re-detect after TLS | None |
| Jetty | `DetectorConnectionFactory` | Read and replay (copy to new buffer) | Input buffer 8192 | Not supported; idle timeout 30000 ms closes | Code (`Detecting`) | 2-byte record sniff before; ALPN after | None |
| Grizzly | `PUFilter` with `ProtocolFinder`s | Read and replay (accumulate) | SSL: one full record; HTTP: 2048 | Not supported; no timer in `PUFilter` | Code (`ProtocolFinder`) | Record sniff before; nested `PUFilter` after SSL | None |
| GlassFish | Grizzly port unification in domain config | Read and replay | As Grizzly | Not verified | `create-protocol-finder` (Java class) | TLS sniff, then HTTP on decrypted bytes | None; HTTP/2 off with port unification |
| Kestrel | None on cleartext `Http1AndHttp2`; preface read on `Http2`-only | Read (PipeReader) | 24 (`Http2`-only) | n/a | Connection middleware (no official peek sample) | ALPN after TLS; raw ClientHello callback before (10.0) | None |
| h2o | `PRI * HTTP/2` check in HTTP/1 error path | Read and replay | `H2O_MAX_REQLEN` (exact value not verified) | n/a; `http1-request-timeout` 10 s | No | ALPN after TLS | None |
| Apache httpd mod_http2 | Speculative 24-byte read when h2c enabled | Read and replay (speculative filter read) | 24 | Never inspects unless h2 or h2c is in `Protocols` (docs name NNTP) | Protocol hooks (modules) | Direct mode off on TLS by default | Benefit only |
| Vert.x | `Http1xOrH2CHandler` | Read and replay | 24 | n/a; idle timeout default none | No | ALPN after TLS | None |
| Cowboy (Ranch) | Request-line parser sees `PRI` | Read and replay | 16 | n/a; `request_timeout` 5000 ms | Ranch protocol (code) | ALPN on TLS port | None |
| Tomcat | Request-line preface compare | Read and replay (`unRead`) | 24 (only if 24 arrive in the first fill, inference) | n/a; `connectionTimeout` 60000 ms (20000 in shipped server.xml) | UpgradeProtocol | ClientHello parse before TLS (rejects plain); ALPN | None |
| PostgreSQL 17+ | First byte `0x16` versus startup packet | User-space 1-byte peek, then replay into TLS | 1 | n/a (client-first); `authentication_timeout` 1 min | No | Before TLS; ALPN `postgresql` required | Benefit only (one fewer round trip) |
| Linux `SO_REUSEPORT` + `sk_reuseport` BPF | BPF picks the listener | Runs at the SYN for TCP; sees UDP payload | 0 application bytes on TCP (inference) | n/a | BPF | None | Qualitative |
| Linux `sk_lookup` BPF | BPF picks the socket at lookup | No payload fields | 0 | n/a | BPF | None | None |
| Linux `TCP_DEFER_ACCEPT` | Delays accept until data | No routing | n/a | Late accept after the deferral (inference from source) | No | n/a | None |
| FreeBSD accept filters | Delays accept until a condition | No routing; kernel buffers | Full HTTP request, DNS message, or first TLS record | No timeout; oldest unready dropped when queue full | Kernel modules | `accf_tls` checks record header | "Reduces CPU", no numbers |
| Linux sockmap `SK_SKB` | Verdict program on an established stream | Reads payload; redirects data | Parser decides | None documented | BPF | Raw stream | None |
| Windows HTTP.sys, Net.TCP port sharing | URL or net.tcp address routing | Kernel HTTP parsing; user-mode service | n/a | HTTP or net.tcp only | No | Not read | Qualitative |

## 5. Published research

Search: Google Scholar (5 queries), arXiv web search (9 queries), Crossref (4 queries), and 25 web
searches restricted to publisher sites at times. Queries included "port unification", "protocol
multiplexing" "same port", "multiple protocols" "single port", "protocol demultiplexing",
"port sharing", and "ALPN cross-protocol". IEEE Xplore and ACM DL pages could not be read (see
section 1). DOIs below were checked on 2026-10-02 by their doi.org redirect.

No peer-reviewed paper was found whose subject is a server serving several protocols on one
listener.

### 5.1 Partly relevant papers

1. M. Brinkmann, C. Dresen, R. Merget, D. Poddebniak, J. Müller, J. Somorovsky, J. Schwenk,
   S. Schinzel. "ALPACA: Application Layer Protocol Confusion: Analyzing and Mitigating Cracks in
   TLS Authentication". 30th USENIX Security Symposium, 2021, pp. 4293-4310. No DOI.
   https://www.usenix.org/conference/usenixsecurity21/presentation/brinkmann
   - Bearing: TLS does not bind a connection to its intended application protocol, so traffic for
     one TLS service can be redirected to another. The paper discusses ALPN and SNI checks as
     mitigations.
   - Relevance: partial. Its endpoints are separate servers, not one listener.
2. S. Frolov, J. Wampler, E. Wustrow. "Detecting Probe-resistant Proxies". NDSS 2020.
   DOI 10.14722/ndss.2020.23087 (redirects to the paper PDF on ndss-symposium.org).
   https://www.ndss-symposium.org/ndss-paper/detecting-probe-resistant-proxies/
   - Bearing: how a server reacts to first bytes it does not recognise (timeouts, and closing after
     a certain number of bytes) is a fingerprint. The authors advise unlimited timeouts for failed
     client handshakes.
   - Relevance: partial. It bears on how a demultiplexer should treat unknown or incomplete prefixes.
3. S. Frolov, E. Wustrow. "HTTPT: A Probe-Resistant Proxy". USENIX FOCI 2020. No DOI.
   https://www.usenix.org/conference/foci20/presentation/frolov
   - Bearing: a proxy hidden behind an existing HTTPS server. The web server forwards requests with
     a secret path and a WebSocket upgrade, and answers others normally.
   - Relevance: partial. Dispatch is inside HTTP after TLS, not on first bytes.
4. D. Poddebniak, F. Ising, H. Böck, S. Schinzel. "Why TLS is better without STARTTLS: A Security
   Analysis of STARTTLS in the Email Context". 30th USENIX Security Symposium, 2021, pp. 4365-4382.
   No DOI. https://www.usenix.org/conference/usenixsecurity21/presentation/poddebniak
   - Bearing: bugs where bytes read before a protocol switch are interpreted after it. The fix is
     not to treat plaintext bytes as part of the encrypted session.
   - Relevance: partial. A first-bytes demultiplexer hands already-read bytes to the next protocol,
     and must get that hand-off right.

### 5.2 Adjacent work (classifies traffic on the wire, does not serve it)

1. H. Dreger, A. Feldmann, M. Mai, V. Paxson, R. Sommer. "Dynamic Application-Layer Protocol Analysis
   for Network Intrusion Detection". 15th USENIX Security Symposium, 2006. No DOI.
   https://www.usenix.org/legacy/event/sec06/tech/dreger.html
   - Why adjacent: an intrusion detection system infers each connection's protocol from content and
     runs the matching analyzer. The dispatch is close to ours, but on a passive monitor.
2. L. Deri, M. Martinelli, T. Bujlow, A. Cardigliano. "nDPI: Open-source high-speed deep packet
   inspection". IWCMC 2014, pp. 617-622. DOI 10.1109/IWCMC.2014.6906427 (redirects to
   https://ieeexplore.ieee.org/document/6906427; the IEEE page itself was not readable, so the
   metadata is from the DOI registration).
   - Why adjacent: a library that identifies application protocols in captured traffic.
3. L. Bernaille, R. Teixeira, I. Akodjenou, A. Soule, K. Salamatian. "Traffic classification on the
   fly". ACM SIGCOMM Computer Communication Review 36(2), pp. 23-26. DOI 10.1145/1129582.1129589
   (redirects to dl.acm.org; the ACM page was not readable).
   - Why adjacent: it identifies the application from the first few packets of a TCP connection,
     for monitoring.
   - To check against the PDF: the DOI record dates the paper April 2006 and spells the third author
     "Akodkenou", while a search snippet gave October 2006 and "Akodjenou".

Also checked and not listed: Nguyen and Armitage, IEEE Communications Surveys and Tutorials 10(4),
2008, DOI 10.1109/SURV.2008.080406 (resolves; IEEE page blocked). Examined and dropped as off
topic: LZR (USENIX Security 2021), "The ties that un-bind" (SIGCOMM 2021), a CCS 2012 cross-protocol
attack paper (not opened), DROWN (not opened), an NDSS 2025 email auto-detect study (client side),
arXiv 1912.03962 (protocol disambiguation for monitors; could replace one adjacent item).

### 5.3 Standards and drafts (closest prior art)

- RFC 1078, TCPMUX (https://www.rfc-editor.org/rfc/rfc1078.txt): many services on one well-known TCP
  port. The client names the service; nothing is sniffed. RFC 7805 moved it to Historic, citing the
  single-port connection limit and firewall complexity.
- RFC 7301, ALPN (https://www.rfc-editor.org/rfc/rfc7301.txt): negotiates the application protocol
  inside the TLS handshake for several protocols on the same port.
- RFC 9113 s3 (https://www.rfc-editor.org/rfc/rfc9113.txt): servers can identify prior-knowledge
  HTTP/2 by the preface. The h2c Upgrade path is deprecated.
- RFC 7983 and RFC 9443 (https://www.rfc-editor.org/rfc/rfc9443.txt): first-byte demultiplexing of
  DTLS, RTP, RTCP, STUN, TURN, ZRTP and QUIC on one UDP socket.
- D. K. Gillmor, draft-dkg-dprive-demux-dns-http-03, "Demultiplexing Streamed DNS from HTTP/1.x",
  dated 2017-05-17, expired 2017-11-18. Not an RFC and not peer reviewed.
  https://www.ietf.org/archive/id/draft-dkg-dprive-demux-dns-http-03.txt
  - It argues that a server can tell a stream of DNS queries from HTTP/1.x requests by the first few
    client octets.
  - It warns that wide use could ossify the distinguishing bit patterns.

## 6. Gaps

Each gap is stated only as far as the sources read support it.

1. **No surveyed project publishes a measured cost of first-bytes detection** (latency added,
   throughput, CPU, memory). The statements found are qualitative: cmux ("negligible", benchmarks
   in code with no published results), sslh (per-variant guidance, 16 bytes per connection for
   sslh-select), sshttp (footprint), FreeBSD accept filters (CPU reduction), caddy-l4 (keep matchers
   small), Envoy (matcher tree design). Label: **verified absent in the docs and source read**.
2. **No surveyed system serves a server-speaks-first protocol on a sniffing listener except by
   waiting out a timer or by speaking first itself.**
   - Timer: sslh (`timeout`, `on-timeout`), HAProxy (`inspect-delay`, then the default backend),
     sshttp (2 s, then SSH), Envoy with `continue_on_listener_filters_timeout` (15 s by default),
     and cmux with `SetReadTimeout` plus `Any()` (inference).
   - Speaking first: sshttp's SMTP mode sends a composite SMTP and SSH greeting, then reads the
     client's reply. It discards the backend's real banner and does not support multiline SMTP
     banners. It covers only that pair of protocols.
   - Routing a silent client by source address (caddy-l4 `remote_ip`, HAProxy ACLs) is not
     first-bytes detection.
   - The other systems close the connection or are HTTP only.
   - Label: **verified absent in the docs and source read** (the cmux, caddy-l4 and Traefik parts
     rest on code reading).
3. **No surveyed project documents a comparison between peeking (`MSG_PEEK`) and read and replay.**
   - Peek is used by Envoy (all listener filters), nginx (stream preread on some event methods, a
     1-byte TLS check, PROXY), HAProxy (PROXY header only), sshttp, and the PROXY spec's sample code.
   - Every other system reads and replays in user space.
   - nginx added its peek path in 1.25.5 with no CHANGES entry.
   - Label: **not found, not proven absent** (issue trackers and mailing lists were not searched).
4. **No kernel mechanism found routes a TCP connection to a listener by its first application
   bytes.**
   - `sk_reuseport` runs at the SYN. `sk_lookup` has no payload fields.
   - `TCP_DEFER_ACCEPT` and FreeBSD accept filters only delay `accept()` on the same socket.
   - sockmap `SK_SKB` redirects the data of a socket already in a map, not the connection.
   - Label: **verified absent in the docs and source read** for these five. **Not found, not proven
     absent** in general: netfilter, nftables, XDP, KCM and the Windows Filtering Platform were not
     checked.
5. **No surveyed in-process server library ships a built-in detector for SSH, MQTT, PostgreSQL or
   Redis.**
   - The libraries are Netty, Jetty, Grizzly, cmux, Go net/http, hyper-util, Kestrel, Vert.x,
     Cowboy and Tomcat. Their built-ins cover TLS, HTTP versions, PROXY, gzip and SOCKS (Netty).
   - Detectors for SSH, MQTT or PostgreSQL appear only in proxies and multiplexers: sslh (ssh),
     caddy-l4 (ssh, postgres), HAProxy (`mqtt_is_valid`), Envoy contrib (postgres_inspector),
     Traefik (PostgreSQL STARTTLS).
   - Label: **verified absent in the docs and source read**. A built-in Redis RESP detector was not
     found in any surveyed system: **not found, not proven absent**.
6. **Most general-purpose HTTP servers sniff only to tell HTTP/1.x from HTTP/2 prior knowledge.**
   - These are nginx HTTP, h2o, httpd, Vert.x, Cowboy, Tomcat, Go net/http and hyper-util. Some also
     check TLS or PROXY.
   - Kestrel and Node.js do not sniff to choose between protocols on cleartext. Kestrel's
     `Http2`-only endpoint reads the preface only to reject HTTP/1.
   - Label: **verified absent in the docs and source read**.
7. **Behaviour on a first read shorter than the signature is not documented.**
   - Inference from code: httpd mod_http2 and Tomcat skip h2 detection when fewer than 24 bytes
     arrive first, and treat the connection as HTTP/1.1. sshttp decides on a single peek.
   - nginx, hyper-util, Go net/http, Vert.x, Jetty, Netty and cmux wait for more bytes.
   - Label: **verified absent in the docs read** for httpd and Tomcat; **not found, not proven
     absent** for the others.
8. **No surveyed system's docs or source read describe using the accept call itself to obtain the
   first bytes for protocol detection, or compare detection across accept models.** Examples of
   such accept-time mechanisms are the Windows `AcceptEx` receive buffer, FreeBSD accept filters and
   `TCP_DEFER_ACCEPT`. Label: **not found, not proven absent** (this was not searched for directly).
9. **No peer-reviewed paper on serving several protocols on one listener was found.** The closest
   prior art is standards work (RFC 1078, 7301, 7983, 9443, 9113) and one expired draft. Label:
   **not found, not proven absent** (IEEE Xplore and ACM DL could not be read; DBLP and Semantic
   Scholar were rate limited).

## 7. ICEST 2027 dates

- **ICEST 2027: not published** as of 2026-10-02.
  - The site search for "2027" on https://icestconf.org/ found nothing, and so did its pages API.
  - Neither https://icestconf.org/history-of-icest-conference/ nor
    http://rcvt.tu-sofia.bg/icest_en.html has 2027 content.
  - The history page says the conference rotates among TU Sofia (Faculty of Telecommunications),
    the University of Niš (Faculty of Electronic Engineering) and the University of Bitola (Faculty
    of Technical Sciences). No official page says who hosts 2027.
  - A different conference also called "ICEST 2027" (Engineering, Science and Technology, Jersey
    City) appears in search results and is unrelated.
- **Reference: ICEST 2026**, the 61st conference, Niš, Serbia, July 01-03, 2026
  (https://icestconf.org/). Two official pages differ, so both are given.
  - https://icestconf.org/important-dates-2/ (last modified 2026-01-30): papers April 17, 2026;
    notification May 29, 2026; program June 15, 2026.
  - https://icestconf.org/important-dates-2025/ (titled for ICEST 2026, last modified 2026-04-20):
    - full papers April 17, 2026; hard deadline April 30, 2026;
    - notification May 29, 2026; final paper June 08, 2026; program June 15, 2026;
    - eCopyright June 25, 2026; conference July 01-03, 2026.
  - CFP PDF (https://icestconf.org/wp-content/uploads/2026/04/CALL_for_PAPERS_ICEST2026.pdf): lists
    April 30, May 29 and June 15, 2026. April 17 is not in the PDF.
  - Camera-ready: June 08, 2026 (https://icestconf.org/paper-submission/).
  - Registration: no deadline stated; early-bird rates before June 15, 2026
    (https://icestconf.org/conference-fee/).
  - Length: up to 6 pages (https://icestconf.org/final-paper-submission/).
  - Proceedings: accepted papers are submitted for inclusion in IEEE Xplore
    (https://icestconf.org/post-conference-publications/). The site footer gives IEEE conference
    record #71230. The IEEE record page could not be read.
- Site integrity: the researcher saw gambling-promotion posts dated 2026-09-21 to 2026-10-01 in
  icestconf.org's posts feed (https://icestconf.org/wp-json/wp/v2/posts), so the site may be
  compromised. The quoted pages were last modified before that.

## 8. Candidate framings (questions for Alex)

No recommendation is made.

1. **Cost.** Should the paper show that one first-bytes listener adds no measurable cost over
   dedicated ports per protocol, against nginx, HAProxy, Envoy, caddy-l4 and sslh-ev, measured by
   req/s, added time to first response byte, CPU and RAM per connection?
   - Needs: a dedicated-port baseline with the same backends.
   - Protocols: HTTP/1.1, h2c, TLS, plus one non-HTTP client-first protocol (SSH or PostgreSQL).
   - Addresses gap 1.
2. **Robustness.** Should the paper show correct and bounded behaviour on the hard first-bytes cases
   against the same proxies plus Netty, Jetty and Go net/http, measured by classification
   correctness, time to decision and memory held per pending connection?
   - Hard cases: split signatures, slow drip, silent clients, server-speaks-first protocols
     (timeout fallback and banner-first hand-off), and a PROXY v2 header in front of HTTP/1.
   - Needs: a traffic generator for each case.
   - Protocols: TLS, h2c, HTTP/1, PROXY v1 and v2, SSH, SMTP.
   - Addresses gaps 2 and 7.
3. **Mechanism.** Should the paper compare peek (`MSG_PEEK`) with read and replay, and in-process
   dispatch with proxy hand-off, across accept models? Competitors would be Envoy (peek) and
   caddy-l4 or sslh (read and replay). Measures would be syscalls and copies per connection,
   connection setup latency, and CPU per accepted connection.
   - Needs: both modes in the paper's own implementation.
   - Accept models: epoll and io_uring on Linux, IOCP `AcceptEx` on Windows.
   - Addresses gaps 3 and 8.
