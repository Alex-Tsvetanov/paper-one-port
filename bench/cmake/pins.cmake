# Every fetched or built third-party input of the measured builds, pinned by archive URL and
# sha256 (hypotheses.md, sections 2.1, 2.3 and 9.1; design/proposal.md, I23 and section 6).
# The records gate hashes this file (bench/gate_lib.py, pins_sha256): a measured build is refused
# unless its sanitizer records were made with this file as it is.
#
# bench/third_party/build_deps.sh reads the three values of each library from this file, so the
# file is the one source of the versions, URLs and hashes. Each sha256 below was computed on L
# from the downloaded archive on 2026-10-02 and is equal to the value the release publishes beside
# it (the URL in the comment). Read again at the code freeze: OpenSSL is pinned then to the latest
# release of its 3.5 LTS series.

# OpenSSL, the latest release of the 3.5 LTS series on 2026-10-02: 3.5.9, published 2026-09-29
# (github.com/openssl/openssl/releases/tag/openssl-3.5.9; also listed at
# openssl-library.org/source). Published hash: the release asset openssl-3.5.9.tar.gz.sha256.
set(ONEPORT_OPENSSL_VERSION "3.5.9")
set(ONEPORT_OPENSSL_URL "https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz")
set(ONEPORT_OPENSSL_SHA256 "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a")

# nghttp2 v1.70.0, the version hypotheses.md section 2.1 names, published 2026-07-29 and still the
# latest release on 2026-10-02 (github.com/nghttp2/nghttp2/releases/tag/v1.70.0). Published hash:
# the release asset checksums.txt.
set(ONEPORT_NGHTTP2_VERSION "1.70.0")
set(ONEPORT_NGHTTP2_URL "https://github.com/nghttp2/nghttp2/releases/download/v1.70.0/nghttp2-1.70.0.tar.xz")
set(ONEPORT_NGHTTP2_SHA256 "e05cb1388eaca3830aded4ccf20044b6e1ac1a61411dcca11b0437c4285c8bc2")

# The proxies of hypotheses.md, section 2.3 (M3 and B3), at the frozen versions, downloaded on L on
# 2026-10-03 (M4a) into ~/opt/src from these official release URLs; bench/competitors/install.sh
# reads the three values of each from this file, checks the archive, and builds or unpacks it into
# ~/opt. Each line says which published check the sha256 was compared with. Read again at the code
# freeze (section 2.3: a newer release then is a new pin, logged).

# nginx 1.30.5, the stable release of the frozen pin (release-1.30.5), built from the release
# tarball (hypotheses.md 2.3: "built from the release tag"). nginx publishes a PGP signature, not
# a hash: nginx-1.30.5.tar.gz.asc verified good against Sergey Kandaurov's key from
# nginx.org/keys/pluknet.key (fingerprint D678 6CE3 03D9 A902 2998 DC6C C846 4D54 9AF7 5C0A); the
# sha256 is computed only.
set(ONEPORT_NGINX_VERSION "1.30.5")
set(ONEPORT_NGINX_URL "https://nginx.org/download/nginx-1.30.5.tar.gz")
set(ONEPORT_NGINX_SHA256 "6c20565aa2325cb82216ae804f4a4ff1875179014759a381c42ddc8e11c4906d")

# HAProxy 3.4.6 (www.haproxy.org, the 3.4 branch). Published hash: haproxy-3.4.6.tar.gz.sha256
# beside the archive, equal.
set(ONEPORT_HAPROXY_VERSION "3.4.6")
set(ONEPORT_HAPROXY_URL "https://www.haproxy.org/download/3.4/src/haproxy-3.4.6.tar.gz")
set(ONEPORT_HAPROXY_SHA256 "791e1815f8af6e8b850a227a9a0a190f3d3478c9e8d38a0f51c98b7f4bfe368b")

# Envoy 1.39.2, the release binary (hypotheses.md 2.3), published 2026-10-01. Published hash: the
# release's checksums.txt.asc, equal, and the GitHub release asset's digest, equal; the file's PGP
# signature verified good ("Envoy maintainers", key 0AFC E836 BA4D 1D35 763C 8523 D8CD C375 0181
# F31F, fetched from keyserver.ubuntu.com, no trust path).
set(ONEPORT_ENVOY_VERSION "1.39.2")
set(ONEPORT_ENVOY_URL "https://github.com/envoyproxy/envoy/releases/download/v1.39.2/envoy-1.39.2-linux-x86_64")
set(ONEPORT_ENVOY_SHA256 "d2f1a9f4f19b7fc064e75b4e52d191754c49a4de1ae2145462c0c7e19a860e1b")

# xcaddy 0.4.7, the latest release on 2026-10-03 (published 2026-08-17), the builder of caddy-l4.
# Published hash: xcaddy_0.4.7_checksums.txt gives SHA-512, equal; the GitHub release asset's
# sha256 digest, equal.
set(ONEPORT_XCADDY_VERSION "0.4.7")
set(ONEPORT_XCADDY_URL "https://github.com/caddyserver/xcaddy/releases/download/v0.4.7/xcaddy_0.4.7_linux_amd64.tar.gz")
set(ONEPORT_XCADDY_SHA256 "e6d2882fb751b9697cdb73b0da8b8a7393f0d7f2cb47afa79a23982c4c61d2d4")

# caddy-l4 v0.1.2 = commit 42db5690dea199f930a6f08005fe2e4aab10dcc9 on Caddy v2.11.4 (its go.mod),
# built by xcaddy with L's go1.27.1 (GOTOOLCHAIN=local). Go modules, not an archive: every module
# is verified by go.sum against the Go checksum database; the build's go.mod and go.sum are kept in
# bench/competitors/caddy-l4/.
set(ONEPORT_CADDY_VERSION "v2.11.4")
set(ONEPORT_CADDY_L4_VERSION "v0.1.2")
set(ONEPORT_CADDY_L4_COMMIT "42db5690dea199f930a6f08005fe2e4aab10dcc9")

# sslh 2.3.1 (tag v2.3.1 = commit d39388d1edcc9fe7a35449fc5c23d222d20d6f81), the author's release
# tarball. No hash is published: the sha256 is computed only; the tarball's tree equals the tree of
# the tag's archive on GitHub (diff -r, no difference).
set(ONEPORT_SSLH_VERSION "2.3.1")
set(ONEPORT_SSLH_URL "https://www.rutschle.net/tech/sslh/sslh-v2.3.1.tar.gz")
set(ONEPORT_SSLH_SHA256 "51a5516ec5cb01823633b4d8cacdeee4efa0c56ef620d1c996d4f52ca51a601b")

# Pinned later, at or before the code freeze, with the archive URL and the sha256 read from the
# official release: the libraries of hypotheses.md, section 2.3 (Netty, Jetty, cmux, hyper-util),
# the JDK (the latest LTS) and the Rust toolchain (hypotheses.md, section 9.1).
