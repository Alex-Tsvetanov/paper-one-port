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

# Pinned later, at or before the code freeze, with the archive URL and the sha256 read from the
# official release: the competitors of hypotheses.md, section 2.3, the JDK (the latest LTS), the
# Rust toolchain and xcaddy (hypotheses.md, section 9.1).
