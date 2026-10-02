# Every fetched or built third-party input of the measured builds, pinned by archive URL and
# sha256 (hypotheses.md, sections 2.1, 2.3 and 9.1; design/proposal.md, I23 and section 6).
# The records gate hashes this file (bench/gate_lib.py, pins_sha256): a measured build is refused
# unless its sanitizer records were made with this file as it is.
#
# M0 pins nothing yet, and no line below is a pin. Each of these is pinned at or before the code
# freeze, with the archive URL and the sha256 read from the official release:
# - OpenSSL, the latest release of its 3.5 LTS series at the code freeze (3.5.9 on 2026-10-02,
#   proposal I23), built from source on L and W;
# - nghttp2 v1.70.0 (hypotheses.md, section 2.1);
# - the competitors of hypotheses.md, section 2.3, the JDK (the latest LTS), the Rust toolchain
#   and xcaddy (hypotheses.md, section 9.1).
