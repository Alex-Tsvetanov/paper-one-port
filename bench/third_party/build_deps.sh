#!/usr/bin/env bash
# Builds the pinned third-party C libraries of oneport on L, one install prefix per build flavour
# (design/proposal.md, Z3: third-party C code is built from its pinned source with the record's
# sanitizer flags). Linux and clang only.
#
#   bench/third_party/build_deps.sh [release|asan|tsan|msan ...]     (default: all four)
#   ONEPORT_LIBS="openssl" bench/third_party/build_deps.sh asan        (one library; default both)
#
# Versions, URLs and sha256 come from bench/cmake/pins.cmake, the one source of them. The archive
# is downloaded into $ONEPORT_OPT/src (default ~/opt/src) if absent, and the build stops unless its
# sha256 equals the pin. Each library and flavour is built in its own fresh copy of the source
# under $ONEPORT_OPT/build and installed into $ONEPORT_OPT/<lib>-<version>-<flavour>, which
# CMakeLists.txt finds by the same names. An existing build directory or prefix is never removed
# or overwritten: the script stops instead. Logs: $ONEPORT_OPT/build/logs/<lib>-<flavour>.log, and
# a .done file with the exit code when the step ends.
#
# The flavours and their flags (the same compiler as the server: clang 22.1.8 on L):
#   release  no sanitizer; the Debug and Release builds of oneport link it
#   asan     ASan with UBSan (OpenSSL: enable-asan enable-ubsan, and openssl-ubsan.ignorelist,
#            which leaves -fsanitize=function out of all of OpenSSL; bench/coverage.json)
#   tsan     TSan (OpenSSL has no enable-tsan; -fsanitize=thread is passed as a compiler flag)
#   msan     MSan (OpenSSL: enable-msan, which also turns assembly off, Configure line 707)
# OpenSSL options common to every flavour: a static build (no-shared, as INSTALL.md asks for
# enable-asan), no loadable modules, no tests, no documentation. The TLS features are OpenSSL's
# defaults in every flavour; oneport selects TLS 1.3, its suite, group and signature scheme at run
# time (bench/tls). The sanitizer flavours also leave out the openssl program (no-apps), which
# selects no feature; the release flavour keeps it, to make the test certificate.
# nghttp2: the library only (ENABLE_LIB_ONLY), static, in a CMake Release build.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
pins="$here/../cmake/pins.cmake"
opt=${ONEPORT_OPT:-$HOME/opt}
jobs=${ONEPORT_JOBS:-8}
cc=${CC:-clang}

pin() {  # pin NAME -> the value of set(NAME "value") in pins.cmake
    local v
    v=$(sed -n "s/^set($1 \"\\([^\"]*\\)\")\$/\\1/p" "$pins")
    [ -n "$v" ] || { echo "build_deps: no $1 in $pins" >&2; exit 2; }
    printf '%s' "$v"
}

fetch() {  # fetch URL SHA256 -> the verified archive's path
    local url=$1 want=$2 file
    file="$opt/src/$(basename "$url")"
    mkdir -p "$opt/src"
    [ -f "$file" ] || curl -fsSL -o "$file" "$url"
    local got
    got=$(sha256sum "$file" | cut -d' ' -f1)
    if [ "$got" != "$want" ]; then
        echo "build_deps: $file has sha256 $got, the pin is $want" >&2
        exit 3
    fi
    printf '%s' "$file"
}

fresh() {  # fresh DIR: stop if DIR exists
    if [ -e "$1" ]; then
        echo "build_deps: $1 exists; remove it by hand to rebuild" >&2
        exit 4
    fi
}

openssl_flags() {
    case $1 in
        release) echo "" ;;
        asan) echo "enable-asan enable-ubsan -fsanitize-ignorelist=$here/openssl-ubsan.ignorelist" ;;
        tsan) echo "-fsanitize=thread -fno-omit-frame-pointer -g" ;;
        msan) echo "enable-msan -fsanitize-memory-track-origins=2" ;;
        *) echo "build_deps: unknown flavour $1" >&2; exit 2 ;;
    esac
}

nghttp2_cflags() {
    case $1 in
        release) echo "" ;;
        asan) echo "-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer -g" ;;
        tsan) echo "-fsanitize=thread -fno-omit-frame-pointer -g" ;;
        msan) echo "-fsanitize=memory -fsanitize-memory-track-origins=2 -fno-omit-frame-pointer -g" ;;
        *) echo "build_deps: unknown flavour $1" >&2; exit 2 ;;
    esac
}

build_openssl() {
    local flavour=$1 version url sha archive src prefix apps
    version=$(pin ONEPORT_OPENSSL_VERSION)
    url=$(pin ONEPORT_OPENSSL_URL)
    sha=$(pin ONEPORT_OPENSSL_SHA256)
    archive=$(fetch "$url" "$sha")
    src="$opt/build/openssl-$version-$flavour"
    prefix="$opt/openssl-$version-$flavour"
    fresh "$src"
    fresh "$prefix"
    mkdir -p "$src"
    tar xzf "$archive" -C "$src" --strip-components=1
    apps=no-apps
    [ "$flavour" = release ] && apps=""
    # shellcheck disable=SC2046
    local cmd=(./Configure linux-x86_64-clang no-shared no-module no-tests no-docs $apps
               "--prefix=$prefix" "--openssldir=$prefix/ssl" --libdir=lib $(openssl_flags "$flavour"))
    (
        cd "$src"
        echo "CC=$cc ${cmd[*]}"
        CC=$cc "${cmd[@]}"
        make -j"$jobs"
        make install_sw
    )
}

build_nghttp2() {
    local flavour=$1 version url sha archive src prefix
    version=$(pin ONEPORT_NGHTTP2_VERSION)
    url=$(pin ONEPORT_NGHTTP2_URL)
    sha=$(pin ONEPORT_NGHTTP2_SHA256)
    archive=$(fetch "$url" "$sha")
    src="$opt/build/nghttp2-$version-$flavour"
    prefix="$opt/nghttp2-$version-$flavour"
    fresh "$src"
    fresh "$prefix"
    mkdir -p "$src"
    tar xJf "$archive" -C "$src" --strip-components=1
    local cmd=(cmake -S "$src" -B "$src/build" -G Ninja "-DCMAKE_C_COMPILER=$cc" -DCMAKE_BUILD_TYPE=Release
               -DENABLE_LIB_ONLY=ON -DBUILD_SHARED_LIBS=OFF -DBUILD_STATIC_LIBS=ON -DENABLE_DOC=OFF
               -DBUILD_TESTING=OFF "-DCMAKE_INSTALL_PREFIX=$prefix" -DCMAKE_INSTALL_LIBDIR=lib
               "-DCMAKE_C_FLAGS=$(nghttp2_cflags "$flavour")")
    echo "${cmd[*]}"
    "${cmd[@]}"
    cmake --build "$src/build" -j "$jobs"
    cmake --install "$src/build"
}

step() {  # step LIB FLAVOUR: one build with its log and done file
    local lib=$1 flavour=$2 log rc
    mkdir -p "$opt/build/logs"
    log="$opt/build/logs/$lib-$flavour.log"
    rc=0
    { echo "build_deps: $lib $flavour, $(date -Is), $($cc --version | head -1)"; "build_$lib" "$flavour"; } >"$log" 2>&1 || rc=$?
    echo "$rc" >"$opt/build/logs/$lib-$flavour.done"
    echo "build_deps: $lib $flavour exit $rc ($log)"
    return "$rc"
}

flavours=("$@")
[ ${#flavours[@]} -gt 0 ] || flavours=(release asan tsan msan)
libs=${ONEPORT_LIBS:-"nghttp2 openssl"}
for f in "${flavours[@]}"; do
    openssl_flags "$f" >/dev/null
    for lib in $libs; do
        case $lib in
            nghttp2 | openssl) step "$lib" "$f" ;;
            *) echo "build_deps: unknown library $lib" >&2; exit 2 ;;
        esac
    done
done
