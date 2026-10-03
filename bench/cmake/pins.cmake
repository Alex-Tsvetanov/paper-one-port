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

# The in-process libraries of hypotheses.md, section 2.3 (B3, descriptive cells and hyper-util's
# Holm cells), their runtimes and toolchains, pinned in M4b-2 on 2026-10-03; read again at the code
# freeze (section 9.1). bench/competitors/install.sh reads these values.

# The JDK: the latest LTS release at the code freeze (section 2.3). On 2026-10-03 the latest LTS is
# 25 (Adoptium's API, available_releases: most_recent_lts 25) and its latest GA build Eclipse
# Temurin 25.0.4.1+1, published 2026-08-21 (the 25.0.5 update is due later in October 2026, so the
# freeze reads this again). Published hash: the release asset's .sha256.txt and the API's
# checksum, both equal; the archive's PGP signature (.sig) verified good with the Adoptium key
# 3B04 D753 C905 0D9A 5D34 3F39 843C 48A5 65F8 F04B (keyserver.ubuntu.com, no trust path).
set(ONEPORT_JDK_VERSION "25.0.4.1+1")
set(ONEPORT_JDK_URL "https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/OpenJDK25U-jdk_x64_linux_hotspot_25.0.4.1_1.tar.gz")
set(ONEPORT_JDK_SHA256 "dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e")

# Netty 4.2.18.Final and Jetty 12.1.13 (section 2.3) from Maven Central: every jar of each harness,
# with its URL and sha256, is in bench/competitors/netty/maven.lock and jetty/maven.lock, each
# compared with the checksums Central publishes beside it.
set(ONEPORT_NETTY_VERSION "4.2.18.Final")
set(ONEPORT_JETTY_VERSION "12.1.13")

# cmux v0.1.5 on go1.27.1 (section 2.3): Go modules, verified by bench/competitors/cmux/go.sum
# against the Go checksum database; L's go1.27.1 (Arch's go 2:1.27.1-1), GOTOOLCHAIN=local.
set(ONEPORT_CMUX_VERSION "v0.1.5")

# hyper-util 0.1.21 (section 2.3): crates verified by bench/competitors/hyper-util/Cargo.lock;
# its rust-version is 1.85. The Rust toolchain is L's Arch package rust 1:1.98.1-1 (rustc 1.98.1,
# 48a229cea 2026-09-01, LLVM 22.1.8; package sha256
# a0e72c52cf8b8cbc9a16a82fca439e6fe502c6dc4a27b7c1d805f0399ad709ba), with rust-src 1:1.98.1-1 for
# the sanitizer builds' standard library (installed with pacman -S on 2026-10-03; package sha256
# 68f5e4b1592418cf68e816a71f4490bd26963394055485e369e90072f691641c).
set(ONEPORT_HYPER_UTIL_VERSION "0.1.21")
set(ONEPORT_RUSTC_VERSION "1.98.1")
