#!/usr/bin/env bash
# The sanitizer record of one in-process library's harness on L (hypotheses.md, section 11: the Go
# and Rust harnesses get ASan and TSan records; their MSan gap and the Java harnesses' whole gap
# are declared in bench/coverage.json).
#
#   ONEPORT_BUILD=DIR bench/sanitize_harness.sh asan|tsan cmux|hyper-util RECORDS_DIR
#
# From this checkout, which must have no tracked changes: builds the harness in the sanitizer's
# flavour (bench/competitors/build_harnesses.sh: cmux with go build -asan or -race, hyper-util with
# -Zsanitizer=address or thread and -Zbuild-std), runs it as M4b-2's development checks did (its
# probe in its cases kinds, bench/competitors/probe.py, and its route checks at both timer
# settings, bench/competitors/cases_check.py) in the environment its flavour runs with (build.json's
# run_env: hyper-util's TSan reads its tsan.supp), keeps the logs (bench/keep_record_logs.sh) and
# writes RECORDS_DIR/harness_<name>-<commit>-L-<san>.json (bench/harness_record.py). The checks
# need opgen and the server: ONEPORT_BUILD is a Release build of the same checkout, whose bench/
# directory the check's build directory links to. The checks bind fixed ports (cases_check.PORT,
# probe.py's), so no other harness record or suite may run at the same time.
#
# DRY_RUN=1: a test of this driver, never a citable record, as in bench/sanitize_oneport.sh (the
# name ends in -dryrun, the record is marked, RECORDS_DIR may not be lab/sanitizer-records, the
# logs go to WORK's records-logs). Environment: WORK (default ~/lab/p3/records-work), RECORDS_LOGS,
# REPO_URL, as sanitize_oneport.sh. Exits 0 when the record is green.
set -euo pipefail

san=${1:?usage: sanitize_harness.sh asan|tsan cmux|hyper-util RECORDS_DIR}
harness=${2:?usage: sanitize_harness.sh asan|tsan cmux|hyper-util RECORDS_DIR}
records=${3:?usage: sanitize_harness.sh asan|tsan cmux|hyper-util RECORDS_DIR}
build=${ONEPORT_BUILD:?ONEPORT_BUILD is required (a Release build of this checkout: opgen and the server)}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
dry=${DRY_RUN:-}
case "$san" in asan | tsan) ;; *) echo "sanitize_harness: $san: the harnesses' records are asan and tsan (section 11)" >&2; exit 2 ;; esac
case "$harness" in cmux | hyper-util) ;; *) echo "sanitize_harness: $harness: only the Go and Rust harnesses have records (section 11)" >&2; exit 2 ;; esac
[ -x "$build/bench/gen/opgen" ] && [ -x "$build/bench/server/oneport" ] || { echo "sanitize_harness: no opgen or oneport in $build" >&2; exit 2; }
mkdir -p "$records"
records=$(cd "$records" && pwd)
if [ -n "$dry" ]; then
    case "$records" in */lab/sanitizer-records) echo "sanitize_harness: a dry run never writes into lab/sanitizer-records" >&2; exit 2 ;; esac
fi
if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then
    echo "sanitize_harness: $repo has tracked changes; a record must name committed code" >&2
    exit 2
fi
commit=$(git -C "$repo" rev-parse HEAD)
target=harness_${harness//-/_}
name=$target-${commit:0:9}-L-$san${dry:+-dryrun}
work=${WORK:-$HOME/lab/p3/records-work}/$target-$san${dry:+-dryrun}
if [ -n "$dry" ]; then export RECORDS_LOGS=${RECORDS_LOGS:-${WORK:-$HOME/lab/p3/records-work}/records-logs}; fi
bash "$here/keep_record_logs.sh" check "$name"

echo "sanitize_harness: $name from $repo at $commit, work $work, opgen and the server from $build"
rm -rf "$work"
mkdir -p "$work/check-build" "$work/check"
ln -s "$(cd "$build" && pwd)/bench" "$work/check-build/bench"
start=$(date +%s)
set +e
bash "$repo/bench/competitors/build_harnesses.sh" "$work/check-build/harness" "$san" "$harness" > "$work/build.log" 2>&1
build_rc=$?
check_rc=1
if [ "$build_rc" -eq 0 ]; then
    cp "$work/check-build/harness/build.json" "$work/build.json"
    # The environment the flavour runs with (harness_inputs.RUN_ENV, through build.json).
    mapfile -t runenv < <(python3 -c 'import json,sys; [print(f"{k}={v}") for k, v in json.load(open(sys.argv[1]))[sys.argv[2]].get("run_env", {}).items()]' \
        "$work/build.json" "$harness")
    echo "run environment: ${runenv[*]:-none}" | tee -a "$work/build.log"
    kinds=(cases)
    [ "$harness" = cmux ] && kinds+=(cases-fallback)  # bench/competitors/competitors.py, FALLBACK_SYSTEMS
    check_rc=0
    for kind in "${kinds[@]}"; do
        env "${runenv[@]}" python3 "$repo/bench/competitors/probe.py" --system "$harness" --kind "$kind" \
            --build "$work/check-build" --out "$work/check/probe-$kind" > "$work/check/probe-$kind.log" 2>&1 || check_rc=1
    done
    env "${runenv[@]}" python3 "$repo/bench/competitors/cases_check.py" --build "$work/check-build" --out "$work/check/cases" \
        --systems "$harness" --timers matched,default > "$work/check/cases_check.log" 2>&1 || check_rc=1
    tail -n 5 "$work"/check/*.log
fi
set -e
seconds=$(( $(date +%s) - start ))
read -r archive archive_sha < <(bash "$here/keep_record_logs.sh" pack "$name" "$work/build.log" "$work/build.json" "$work/check")

python3 "$here/harness_record.py" --work "$work" --harness "$harness" --sanitizer "$san" --record "$records/$name.json" \
    --repo "${REPO_URL:-$(git -C "$repo" remote get-url origin)}" --commit "$commit" --host "$(uname -n)" --host-tag L \
    --build-exit "$build_rc" --check-exit "$check_rc" --seconds "$seconds" --pins "$repo/bench/cmake/pins.cmake" \
    --logs-archive "$archive" --logs-sha256 "$archive_sha" ${dry:+--dry-run}
