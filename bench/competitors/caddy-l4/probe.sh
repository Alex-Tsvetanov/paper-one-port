#!/usr/bin/env bash
# The probe of caddy-l4 before a window (bench/competitors/probe.py): its M3 or B3 configuration
# behind a fresh stub, both routes of M3, the silent and the partial-ClientHello client.
#   bench/competitors/caddy-l4/probe.sh --kind m3|b3 --build DIR --out DIR
exec python3 "$(dirname "$0")/../probe.py" --system caddy-l4 "$@"
