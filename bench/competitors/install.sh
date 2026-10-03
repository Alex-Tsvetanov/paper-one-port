#!/usr/bin/env bash
# Installs the pinned proxies of hypotheses.md, section 2.3 (M3 and B3) into ~/opt on L: nginx,
# HAProxy and sslh-ev built from their release archives, Envoy's release binary, and caddy-l4 built
# by xcaddy. Linux only. Run under the lab lock (design/status.md: builds are lab jobs).
#
#   bench/competitors/install.sh [nginx haproxy envoy caddy-l4 sslh ...]   (default: all five)
#
# Versions, URLs and sha256 come from bench/cmake/pins.cmake, the one source of them. An archive
# is downloaded into $ONEPORT_OPT/src (default ~/opt/src) if absent, and nothing is built unless its
# sha256 equals the pin. Each system is built in a fresh directory under $ONEPORT_OPT/build and
# installed into $ONEPORT_OPT/<system>-<version>; an existing build directory or prefix is never
# removed or overwritten (the script stops). Logs: $ONEPORT_OPT/build/logs/<system>.log. Nothing
# is installed system-wide, and no package is installed: the build dependencies (libev, libconfig,
# pcre2, gcc, go) are L's, as read on 2026-10-03 (design/status.md, M4a).
#
# Build choices (design/status.md, M4a; each one recorded there with its source):
#   nginx    ./configure --with-stream --with-stream_ssl_preread_module --without-http
#            --with-cc-opt=-O2: the stream module and ssl_preread, the only modules the M3 and B3
#            configurations use (Appendix B); -O2, the level of nginx.org's own Linux packages of
#            1.30.5 (nginx -V of nginx_1.30.5-1~trixie_amd64.deb), above auto/cc/gcc's default -O.
#   HAProxy  make TARGET=linux-glibc, INSTALL's command for Linux, the Makefile's default flags
#            (-O2); no OpenSSL, PCRE or Lua: the configurations terminate no TLS and use no regex.
#   sslh     ./configure; make sslh-ev, Makefile.in's defaults (ENABLE_REGEX=1 for the regex probe
#            of Appendix B, USELIBCONFIG=1, USELIBEV=1, -O2).
#   Envoy    the release binary, unpacked as it is (hypotheses.md 2.3).
#   caddy-l4 xcaddy build v2.11.4 --with github.com/mholt/caddy-l4@<commit>, with L's go1.27.1
#            (GOTOOLCHAIN=local, so Go cannot fetch another toolchain) and the default module proxy
#            and checksum database; the build's go.mod and go.sum are copied beside the binary and
#            kept in the repository (bench/competitors/caddy-l4/).
# The C builds use L's default compiler, gcc (cc), which each project's build picks by default.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
pins="$here/../cmake/pins.cmake"
opt=${ONEPORT_OPT:-$HOME/opt}
jobs=${ONEPORT_JOBS:-8}
logs="$opt/build/logs"
mkdir -p "$opt/src" "$opt/build" "$logs"

pin() {  # pin NAME -> the value of set(NAME "value") in pins.cmake
    local v
    v=$(sed -n "s/^set($1 \"\\([^\"]*\\)\")\$/\\1/p" "$pins")
    [ -n "$v" ] || { echo "install: no $1 in $pins" >&2; exit 2; }
    printf '%s' "$v"
}

fetch() {  # fetch URL SHA256 -> the verified archive's path
    local url=$1 want=$2 file got
    file="$opt/src/$(basename "$url")"
    [ -f "$file" ] || curl -fsSL -o "$file" "$url"
    got=$(sha256sum "$file" | cut -d' ' -f1)
    if [ "$got" != "$want" ]; then
        echo "install: $file has sha256 $got, the pin is $want" >&2
        exit 3
    fi
    printf '%s' "$file"
}

fresh() {  # fresh DIR: stop if DIR exists
    if [ -e "$1" ]; then
        echo "install: $1 exists; remove it by hand to rebuild" >&2
        exit 4
    fi
}

unpack() {  # unpack ARCHIVE NAME -> a fresh build directory holding the archive's one top directory
    local dir="$opt/build/$2"
    fresh "$dir"
    mkdir -p "$dir"
    tar -xzf "$1" -C "$dir"
    printf '%s' "$dir/$(ls "$dir")"
}

nginx() {
    local v src prefix
    v=$(pin ONEPORT_NGINX_VERSION)
    prefix="$opt/nginx-$v"
    fresh "$prefix"
    src=$(unpack "$(fetch "$(pin ONEPORT_NGINX_URL)" "$(pin ONEPORT_NGINX_SHA256)")" "nginx-$v")
    (cd "$src" && ./configure --prefix="$prefix" --with-stream --with-stream_ssl_preread_module --without-http \
        --with-cc-opt=-O2 && make -j"$jobs" && make install)
    "$prefix/sbin/nginx" -V
}

haproxy() {
    local v src prefix
    v=$(pin ONEPORT_HAPROXY_VERSION)
    prefix="$opt/haproxy-$v"
    fresh "$prefix"
    src=$(unpack "$(fetch "$(pin ONEPORT_HAPROXY_URL)" "$(pin ONEPORT_HAPROXY_SHA256)")" "haproxy-$v")
    (cd "$src" && make -j"$jobs" TARGET=linux-glibc && make install-bin PREFIX="$prefix")
    "$prefix/sbin/haproxy" -vv
}

envoy() {
    local v prefix file
    v=$(pin ONEPORT_ENVOY_VERSION)
    prefix="$opt/envoy-$v"
    fresh "$prefix"
    file=$(fetch "$(pin ONEPORT_ENVOY_URL)" "$(pin ONEPORT_ENVOY_SHA256)")
    mkdir -p "$prefix/bin"
    install -m 0755 "$file" "$prefix/bin/envoy"
    "$prefix/bin/envoy" --version
}

sslh() {
    local v src prefix
    v=$(pin ONEPORT_SSLH_VERSION)
    prefix="$opt/sslh-$v"
    fresh "$prefix"
    src=$(unpack "$(fetch "$(pin ONEPORT_SSLH_URL)" "$(pin ONEPORT_SSLH_SHA256)")" "sslh-$v")
    (cd "$src" && ./configure && make -j"$jobs" sslh-ev)
    mkdir -p "$prefix/bin"
    install -m 0755 "$src/sslh-ev" "$prefix/bin/sslh-ev"
    "$prefix/bin/sslh-ev" -V
}

caddy_l4() {
    local xv xdir caddy l4 commit prefix work
    xv=$(pin ONEPORT_XCADDY_VERSION)
    caddy=$(pin ONEPORT_CADDY_VERSION)
    l4=$(pin ONEPORT_CADDY_L4_VERSION)
    commit=$(pin ONEPORT_CADDY_L4_COMMIT)
    xdir="$opt/xcaddy-$xv"
    if [ ! -x "$xdir/xcaddy" ]; then
        mkdir -p "$xdir"
        tar -xzf "$(fetch "$(pin ONEPORT_XCADDY_URL)" "$(pin ONEPORT_XCADDY_SHA256)")" -C "$xdir"
    fi
    prefix="$opt/caddy-l4-$l4"
    fresh "$prefix"
    work="$opt/build/caddy-l4-$l4"
    fresh "$work"
    mkdir -p "$prefix" "$work"
    go version
    go env GOPROXY GOSUMDB GOFLAGS GOTOOLCHAIN
    # xcaddy builds in a temporary module; XCADDY_SKIP_CLEANUP keeps it, and its go.mod and go.sum
    # are the record of every module the build used. TMPDIR puts it under the build directory.
    (cd "$work" && TMPDIR="$work" GOTOOLCHAIN=local XCADDY_SKIP_CLEANUP=1 \
        "$xdir/xcaddy" build "$caddy" --with "github.com/mholt/caddy-l4@$commit" --output "$prefix/caddy")
    local mod
    mod=$(dirname "$(ls -d "$work"/buildenv_*/go.mod | head -1)")
    cp "$mod/go.mod" "$mod/go.sum" "$prefix/"
    "$prefix/caddy" version
    "$prefix/caddy" list-modules --versions | grep -E "^layer4( |\.)" | head -40
}

run() {  # run SYSTEM: its install, logged
    local name=$1
    echo "install: $name ($(date -Is))"
    if ( set -euo pipefail; "${name//-/_}" ) > "$logs/$name.log" 2>&1; then
        echo "install: $name done"
    else
        echo "install: $name FAILED, see $logs/$name.log"
        return 1
    fi
}

systems=("$@")
[ ${#systems[@]} -gt 0 ] || systems=(nginx haproxy envoy caddy-l4 sslh)
rc=0
for s in "${systems[@]}"; do
    case $s in
        nginx | haproxy | envoy | caddy-l4 | sslh) run "$s" || rc=1 ;;
        *) echo "install: unknown system $s" >&2; exit 2 ;;
    esac
done
exit "$rc"
