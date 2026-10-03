#!/usr/bin/env bash
# Builds the first-party harnesses of the in-process libraries (hypotheses.md, section 2.3 and
# Appendix B; M4b-2) from this checkout into OUT, on L:
#   netty       OUT/netty/harness.jar        javac --release 25 against ~/opt/netty-<v>/lib
#   jetty       OUT/jetty/harness.jar        javac --release 25 against ~/opt/jetty-<v>/lib
#   cmux        OUT/cmux/oneport-cmux        go build, L's go1.27.1, go.sum
#   hyper-util  OUT/hyper-util/oneport-hyper-util  cargo build --release --locked, Cargo.lock
# The JDK and the jars come from bench/competitors/install.sh (jdk, netty, jetty).
#
#   bench/competitors/build_harnesses.sh OUT [release|asan|tsan] [netty jetty cmux hyper-util ...]
#
# Flavours (hypotheses.md section 11 and design/proposal.md Z6: the Go and Rust harnesses get ASan
# and TSan records, built the way P2's records built its Go and Rust arms; no sanitizer applies to
# the Java harnesses, so asan and tsan build only cmux and hyper-util):
#   release  the measured build: Go with -trimpath; Rust with cargo's default release profile;
#   asan     Go with -asan; Rust with -Zsanitizer=address (rustc accepts it on the stable toolchain
#            with RUSTC_BOOTSTRAP=1, as P2's records did) and the standard library rebuilt with it
#            (-Zbuild-std, from rust-src at the same version);
#   tsan     Go with -race (Go's race detector is ThreadSanitizer); Rust with -Zsanitizer=thread and
#            -Zbuild-std, without which ThreadSanitizer reports false races in the uninstrumented
#            standard library.
# Every Go build: GOTOOLCHAIN=local (no other toolchain is fetched), GOFLAGS=-mod=readonly (go.sum
# decides), CGO_ENABLED=1 and CC=clang (L's clang 22.1.8, the compiler of the records; -asan and
# -race need cgo). Every Rust build: --locked and --target x86_64-unknown-linux-gnu (the sanitizer
# flags then reach the target's crates and not the build scripts). UBSan has no Go or Rust form.
# OUT/build.json records, per harness, the flavour, the tools, the commands, and the sha256 of its
# sources and of what was built. An existing OUT/<harness> is replaced.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
pins="$here/../cmake/pins.cmake"
opt=${ONEPORT_OPT:-$HOME/opt}
out=$1
flavour=${2:-release}
shift $(($# >= 2 ? 2 : 1))
case $flavour in release | asan | tsan) ;; *) echo "build_harnesses: flavour $flavour, not release, asan or tsan" >&2; exit 2 ;; esac
harnesses=("$@")
if [ ${#harnesses[@]} -eq 0 ]; then
    if [ "$flavour" = release ]; then harnesses=(netty jetty cmux hyper-util); else harnesses=(cmux hyper-util); fi
fi

pin() {
    local v
    v=$(sed -n "s/^set($1 \"\\([^\"]*\\)\")\$/\\1/p" "$pins")
    [ -n "$v" ] || { echo "build_harnesses: no $1 in $pins" >&2; exit 2; }
    printf '%s' "$v"
}

jdk="$opt/jdk-$(pin ONEPORT_JDK_VERSION)"
mkdir -p "$out"
record="$out/build.json"
[ -f "$record" ] || echo '{}' > "$record"

note() {  # note NAME FILE COMMAND...: one entry of build.json
    local name=$1 file=$2
    shift 2
    BH_NAME=$name BH_FILE=$file BH_FLAVOUR=$flavour BH_RECORD=$record BH_SRC="$here/$name" BH_CMD="$*" \
    BH_TOOLS="$(tools "$name")" python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
e = os.environ
src = Path(e["BH_SRC"])
h = hashlib.sha256()
for p in sorted(x for x in src.rglob("*") if x.is_file() and "target" not in x.relative_to(src).parts):
    h.update(str(p.relative_to(src)).encode() + b"\0" + p.read_bytes())
rec = json.loads(Path(e["BH_RECORD"]).read_text())
rec[e["BH_NAME"]] = {"flavour": e["BH_FLAVOUR"], "output": e["BH_FILE"],
                     "output_sha256": hashlib.sha256(Path(e["BH_FILE"]).read_bytes()).hexdigest(),
                     "sources_sha256": h.hexdigest(), "command": e["BH_CMD"], "tools": e["BH_TOOLS"]}
Path(e["BH_RECORD"]).write_text(json.dumps(rec, indent=1))
PY
}

tools() {
    case $1 in
        netty | jetty) "$jdk/bin/javac" -version 2>&1 ;;
        cmux) GOTOOLCHAIN=local go version; clang --version | head -1 ;;
        hyper-util) rustc -vV | tr '\n' ' '; cargo -V ;;
    esac
}

java_harness() {  # java_harness NAME CLASS VERSION_PIN
    local name=$1 class=$2 lib dir
    lib="$opt/$name-$(pin "$3")/lib"
    [ -d "$lib" ] || { echo "build_harnesses: no $lib (bench/competitors/install.sh $name)" >&2; exit 3; }
    dir="$out/$name"
    rm -rf "$dir"
    mkdir -p "$dir/classes"
    "$jdk/bin/javac" --release 25 -Xlint:all -Werror -d "$dir/classes" -cp "$lib/*" "$here/$name/src/oneport/$class.java"
    "$jdk/bin/jar" --create --file "$dir/harness.jar" -C "$dir/classes" .
    note "$name" "$dir/harness.jar" "javac --release 25 -Xlint:all -Werror -cp $lib/* $class.java; jar"
}

cmux_harness() {
    local dir flags=(-trimpath)
    dir="$out/cmux"
    rm -rf "$dir"
    mkdir -p "$dir"
    case $flavour in asan) flags+=(-asan) ;; tsan) flags+=(-race) ;; esac
    (cd "$here/cmux" && GOTOOLCHAIN=local GOFLAGS=-mod=readonly CGO_ENABLED=1 CC=clang go build "${flags[@]}" -o "$dir/oneport-cmux" .)
    note cmux "$dir/oneport-cmux" "GOTOOLCHAIN=local GOFLAGS=-mod=readonly CGO_ENABLED=1 CC=clang go build ${flags[*]}"
}

hyper_util_harness() {
    local dir target=x86_64-unknown-linux-gnu env=() flags=(build --release --locked --target "$target")
    dir="$out/hyper-util"
    rm -rf "$dir"
    mkdir -p "$dir"
    case $flavour in
        asan) env=(RUSTC_BOOTSTRAP=1 RUSTFLAGS=-Zsanitizer=address); flags+=(-Zbuild-std) ;;
        tsan) env=(RUSTC_BOOTSTRAP=1 RUSTFLAGS=-Zsanitizer=thread); flags+=(-Zbuild-std) ;;
    esac
    (cd "$here/hyper-util" && env "${env[@]}" cargo "${flags[@]}" --target-dir "$dir/target")
    cp "$dir/target/$target/release/oneport-hyper-util" "$dir/oneport-hyper-util"
    note hyper-util "$dir/oneport-hyper-util" "${env[*]} cargo ${flags[*]}"
}

for h in "${harnesses[@]}"; do
    case $h in
        netty) [ "$flavour" = release ] && java_harness netty NettyHarness ONEPORT_NETTY_VERSION ;;
        jetty) [ "$flavour" = release ] && java_harness jetty JettyHarness ONEPORT_JETTY_VERSION ;;
        cmux) cmux_harness ;;
        hyper-util) hyper_util_harness ;;
        *) echo "build_harnesses: unknown harness $h" >&2; exit 2 ;;
    esac
    echo "build_harnesses: $h ($flavour) built"
done
