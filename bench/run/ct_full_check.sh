#!/usr/bin/env bash
# ct_full_check.sh BUILD TESTBUILD OUT [RUNS]: does handlers.output_backpressure fail while L's
# connection-tracking table is full? (design/status.md, M3 step 0, item 3.)
#
# Fills the table with one HTTP/1.1 churn burst of opgen against a dedicated oneport (about 270,000
# connections in 6 s; each keeps its entry 120 s), then runs the backpressure test on epoll and on
# io_uring, alternately, RUNS times (3 by default) from the burst on, recording the table's count and
# drop counters before each run. Then the same RUNS runs once the table has drained. Run it under
# the lab lock. Development check, not a window.
set -u
build=$1
testbuild=$2
out=$3
runs=${4:-3}
mkdir -p "$out"
ct() { printf 'count %s drop %s\n' "$(cat /proc/sys/net/netfilter/nf_conntrack_count)" \
  "$(awk 'NR>1{s+=strtonum("0x"$11)} END{print s}' /proc/net/stat/nf_conntrack)"; }
one_round() {
  local tag=$1
  for i in $(seq 1 "$runs"); do
    for b in epoll io_uring; do
      echo "== $tag run $i $b $(ct)" >> "$out/ct_full.log"
      "$testbuild/tests/oneport_tests" test "handlers.output_backpressure.$b" >> "$out/ct_full.log" 2>&1
      echo "exit $?" >> "$out/ct_full.log"
    done
  done
}
taskset -c 14 "$build/bench/server/oneport" --mode dedicated --detect replay --dispatch inproc --backend epoll --port 22000 > "$out/filler.server.log" 2>&1 &
srv=$!
sleep 1
echo "== before burst $(ct)" >> "$out/ct_full.log"
taskset -c 2-13 "$build/bench/gen/opgen" --port 22000 --proto http1 --cpus 2-13 --conns 64 --warmup-ms 0 --duration-ms 6500 \
  --src-base 127.200.0.1 --k-src 16 --out "$out/filler.opgen.json" > /dev/null 2>&1
kill -TERM "$srv"; wait "$srv"
echo "== after burst $(ct)" >> "$out/ct_full.log"
one_round full
# The table drains 120 s after the burst.
while [ "$(cat /proc/sys/net/netfilter/nf_conntrack_count)" -gt 2000 ]; do sleep 5; done
one_round drained
grep -c "FAIL" "$out/ct_full.log"
