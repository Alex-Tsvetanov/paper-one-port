#!/usr/bin/env bash
# The sanitizer record of oneport on L (hypotheses.md, section 11; the Papers repo's rule D5).
#
#   bench/sanitize_oneport.sh asan|tsan|msan RECORDS_DIR
#
# From this checkout, which must have no tracked changes: configures the whole CMake project with
# clang (Release, ONEPORT_SANITIZER address+undefined, thread or memory with the MSan libc++),
# builds it with Ninja, hashes what it compiled (bench/build_inputs.py: every first-party target,
# the server, opgen, opcase, ophold, the suite and the libraries they link), runs the whole CTest
# suite (ctest -V) with the runtime options below, keeps the logs (bench/keep_record_logs.sh) and
# writes RECORDS_DIR/oneport-<commit>-L-<san>.json (bench/oneport_record.py). The record is green
# only if the build and every test passed and no log holds a sanitizer report. The gate
# (bench/check_records.py) matches it to a measured build by inputs hash, compiler, configuration
# and pins, whatever the commit.
#
# Runtime options: those of the development checks that were green in M5 (~/lab/p3/sancheck.sh,
# m5chk4 and m5chk5): ASan with UBSan ASAN_OPTIONS=detect_leaks=1:detect_stack_use_after_return=1:
# strict_string_checks=1:symbolize=1 and UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1 (the
# build adds -fno-sanitize-recover=all); TSan and MSan with the runtimes' defaults.
#
# DRY_RUN=1: a test of this driver, never a citable record. The record is named
# oneport-<commit>-L-<san>-dryrun.json and marked "dry_run" (the gate refuses it), RECORDS_DIR may
# not be the Papers repo's lab/sanitizer-records, and the logs go to WORK's records-logs, not
# ~/lab/records-logs, so the citable record's log directory stays free.
#
# Environment: WORK (default ~/lab/p3/records-work; the build tree is WORK/<san>[-dryrun], made
# afresh), JOBS (ninja -j, default 5: two suites run at once at most), CTEST_JOBS (default 8),
# MSAN_LIBCXX (default ~/opt/libcxx-msan-gcc), RECORDS_LOGS (default ~/lab/records-logs, under
# DRY_RUN WORK/records-logs), REPO_URL (recorded; default the checkout's origin), LAB_BIN (a
# directory holding the Papers repo's inputs_hash.py; default as bench/build_inputs.py finds it,
# on L ~/lab/p3/tools). Exits 0 when the record is green.
set -euo pipefail

san=${1:?usage: sanitize_oneport.sh asan|tsan|msan RECORDS_DIR}
records=${2:?usage: sanitize_oneport.sh asan|tsan|msan RECORDS_DIR}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
dry=${DRY_RUN:-}
# Each sanitizer's suite gets its own port block for the integration tests of
# bench/competitors/test_competitors.py (ONEPORT_TEST_PORT_SHIFT), so the two suites that run at
# once (bench/records_job.sh) never bind each other's ports.
case "$san" in
    asan) sanitizer=address+undefined; shift_ports=600
          sanenv=(ASAN_OPTIONS=detect_leaks=1:detect_stack_use_after_return=1:strict_string_checks=1:symbolize=1
                  UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1) ;;
    tsan) sanitizer=thread; shift_ports=1800; sanenv=() ;;
    msan) sanitizer=memory; shift_ports=3000; sanenv=() ;;
    *) echo "sanitize_oneport: unknown sanitizer '$san'" >&2; exit 2 ;;
esac
options="${sanenv[*]:-the runtime defaults}"
mkdir -p "$records"
records=$(cd "$records" && pwd)
if [ -n "$dry" ]; then
    case "$records" in */lab/sanitizer-records) echo "sanitize_oneport: a dry run never writes into lab/sanitizer-records" >&2; exit 2 ;; esac
fi
if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then
    echo "sanitize_oneport: $repo has tracked changes; a record must name committed code" >&2
    exit 2
fi
commit=$(git -C "$repo" rev-parse HEAD)
name=oneport-${commit:0:9}-L-$san${dry:+-dryrun}
work=${WORK:-$HOME/lab/p3/records-work}/$san${dry:+-dryrun}
if [ -n "$dry" ]; then export RECORDS_LOGS=${RECORDS_LOGS:-${WORK:-$HOME/lab/p3/records-work}/records-logs}; fi
bash "$here/keep_record_logs.sh" check "$name"

cmake_args=(-G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=Release "-DONEPORT_SANITIZER=$sanitizer")
[ "$san" = msan ] && cmake_args+=("-DONEPORT_MSAN_LIBCXX=${MSAN_LIBCXX:-$HOME/opt/libcxx-msan-gcc}")
echo "sanitize_oneport: $name from $repo at $commit, work $work"
rm -rf "$work"
mkdir -p "$work"
start=$(date +%s)
set +e
{ cmake -S "$repo" -B "$work/build" "${cmake_args[@]}" && ninja -C "$work/build" -j "${JOBS:-5}"; } > "$work/build.log" 2>&1
build_rc=$?
ctest_rc=1
if [ "$build_rc" -eq 0 ]; then
    python3 "$here/build_inputs.py" --build "$work/build" --host L --out "$work/build.inputs.json" \
        ${LAB_BIN:+--inputs-hash "$LAB_BIN/inputs_hash.py"} >> "$work/build.log" 2>&1
    (cd "$work/build" && env "${sanenv[@]}" ONEPORT_TEST_PORT_SHIFT="$shift_ports" ctest -V -j "${CTEST_JOBS:-8}" --timeout 900) \
        > "$work/ctest.log" 2>&1
    ctest_rc=$?
fi
set -e
seconds=$(( $(date +%s) - start ))
read -r archive archive_sha < <(bash "$here/keep_record_logs.sh" pack "$name" "$work/build.log" "$work/ctest.log" \
    "$work/build.inputs.json")

python3 "$here/oneport_record.py" --work "$work" --record "$records/$name.json" \
    --repo "${REPO_URL:-$(git -C "$repo" remote get-url origin)}" --commit "$commit" --repo-head "$commit" \
    --sanitizer "$san" --cmake-args="${cmake_args[*]}" --options="$options" --host "$(uname -n)" --host-tag L \
    --build-exit "$build_rc" --ctest-exit "$ctest_rc" --seconds "$seconds" --pins "$repo/bench/cmake/pins.cmake" \
    --logs-archive "$archive" --logs-sha256 "$archive_sha" ${dry:+--dry-run}
