#!/usr/bin/env bash
# The probe of the netty harness (bench/competitors/probe.py, M4b-2): its cases or B3 configuration on
# the front core, every protocol it serves by opgen --probe, the silent and the partial-ClientHello
# client against what its documents say it does. The harness comes from <build>/harness
# (build_harnesses.sh).
#   bench/competitors/netty/probe.sh --kind cases|b3 --build DIR --out DIR
exec python3 "$(dirname "$0")/../probe.py" --system netty "$@"
