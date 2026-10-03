#!/usr/bin/env bash
# records_job.sh OUT RECORDS_DIR: every sanitizer record of the code freeze on L, in order, then
# the gate of the same commit's Release build (hypotheses.md, sections 8 step 3 and 11; the Papers
# repo's rule D5). Run as one lab job, from a clone of the lab remote at the commit to record:
#     setsid nohup bash <clone>/bench/run/lab_job.sh <dir> <name> \
#         bash <clone>/bench/records_job.sh <OUT> <RECORDS_DIR> &
# lab_job.sh holds the lab lock (lab/bin/lablock) for the whole job, with the clock floor, THP at
# madvise and NOTRACK, and writes the pid and done files; poll the done file, never pgrep -f.
#
# Steps, each stopping the job unless it exits 0 (a record that is not green stops it: nothing
# after it runs, and the record is reported as it is, never made again in silence, since each
# driver refuses to start over existing logs):
#   release        a Release build of the clone (OUT/build-release): the measured build the gate
#                  checks, and the opgen and server the harness checks use; the harnesses in their
#                  release flavour beside it (OUT/build-release/harness, build_harnesses.sh);
#   asan, tsan     oneport's records (bench/sanitize_oneport.sh), the two suites at once (the
#                  brief's limit: at most two sanitizer suites at once; each build ninja -j 5);
#   msan           oneport's MSan record, alone;
#   cmux-asan, cmux-tsan, hyper-util-asan, hyper-util-tsan
#                  the Go and Rust harnesses' records (bench/sanitize_harness.sh), one at a time:
#                  their checks bind fixed ports;
#   gate           bench/build_inputs.py over the Release build, then bench/check_records.py with
#                  --inputs and --harnesses against RECORDS_DIR, into OUT/gate-L.json, and the
#                  inputs hash and sha256 of every measured binary into OUT/measured-L.json.
# ONLY (default "release asan tsan msan cmux-asan cmux-tsan hyper-util-asan hyper-util-tsan gate")
# names the steps to run; "release" is needed by every later step of a fresh OUT.
#
# DRY_RUN=1: a test of the drivers on the current tree, never citable: every record is named
# ...-dryrun and marked, RECORDS_DIR may not be lab/sanitizer-records, the logs stay under OUT,
# and the gate runs with --accept-dry-run, so its output is marked and bench/check_rows.py refuses
# it. The citable records are made only at the code freeze's commit.
#
# W's record (MSVC ASan, bench/sanitize_oneport.ps1) is made on W, by Alex or with his yes.
set -uo pipefail
export GOPROXY=direct GOTOOLCHAIN=local

main() {
    local out=${1:?usage: records_job.sh OUT RECORDS_DIR}
    local records=${2:?usage: records_job.sh OUT RECORDS_DIR}
    mkdir -p "$out" "$records"
    out=$(cd "$out" && pwd)
    records=$(cd "$records" && pwd)
    local here repo dry=${DRY_RUN:-}
    here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    repo=$(cd "$here/.." && pwd)
    status=incomplete
    trap 'echo "$(date -Is) $status" > "'"$out"'/records.done"' EXIT
    exec > >(tee -a "$out/records.log") 2>&1
    if [ -n "$dry" ]; then
        case "$records" in */lab/sanitizer-records) status="STOPPED: a dry run never writes into lab/sanitizer-records"; echo "$status"; exit 2 ;; esac
        export RECORDS_LOGS="$out/records-logs"
    fi
    [ -z "$(git -C "$repo" status --porcelain --untracked-files=no)" ] || { status="STOPPED: $repo has tracked changes"; echo "$status"; exit 2; }
    local commit
    commit=$(git -C "$repo" rev-parse HEAD)
    echo "records start $(date -Is), one-port $commit${dry:+ (DRY RUN: never citable)}, host $(uname -n) $(uname -r)"
    echo "  $(clang++ --version | head -1); $(go version); $(rustc --version); $(python3 --version)"
    export WORK="$out/work"
    local build="$out/build-release"

    run() {  # run STEP COMMAND...: one step; stops the job unless it exits 0
        local step=$1 t0 rc
        shift
        t0=$(date +%s)
        echo "== $step start $(date -Is)"
        "$@" > "$out/$step.log" 2>&1
        rc=$?
        tail -n 8 "$out/$step.log"
        echo "== $step exit $rc, $(( $(date +%s) - t0 )) s"
        echo "$step $rc $(( $(date +%s) - t0 ))" >> "$out/steps.txt"
        if [ "$rc" -ne 0 ]; then
            status="STOPPED: $step exited $rc (not green or failed; $out/$step.log)"
            echo "$status"
            exit 1
        fi
    }
    pair() {  # pair STEP_A STEP_B: two oneport records at once, both waited for
        local a=$1 b=$2 pa pb ra rb t0
        t0=$(date +%s)
        echo "== $a and $b start $(date -Is)"
        bash "$here/sanitize_oneport.sh" "$a" "$records" > "$out/$a.log" 2>&1 &
        pa=$!
        bash "$here/sanitize_oneport.sh" "$b" "$records" > "$out/$b.log" 2>&1 &
        pb=$!
        wait "$pa"; ra=$?
        wait "$pb"; rb=$?
        tail -n 3 "$out/$a.log" "$out/$b.log"
        echo "$a $ra $(( $(date +%s) - t0 ))" >> "$out/steps.txt"
        echo "$b $rb $(( $(date +%s) - t0 ))" >> "$out/steps.txt"
        echo "== $a exit $ra, $b exit $rb, $(( $(date +%s) - t0 )) s"
        if [ "$ra" -ne 0 ] || [ "$rb" -ne 0 ]; then
            status="STOPPED: $a exited $ra, $b exited $rb ($out/$a.log, $out/$b.log)"
            echo "$status"
            exit 1
        fi
    }
    release() {
        cmake -S "$repo" -B "$build" -G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=Release &&
            ninja -C "$build" -j 10 &&
            bash "$repo/bench/competitors/build_harnesses.sh" "$build/harness" release
    }
    gate() {
        python3 "$here/build_inputs.py" --build "$build" --host L --out "$out/release.inputs.json" || return 1
        python3 "$here/check_records.py" --records "$records" --host L --inputs "$out/release.inputs.json" \
            --harnesses "$build/harness/build.json" --out "$out/gate-L.json" ${dry:+--accept-dry-run} || return 1
        python3 - "$out/release.inputs.json" "$out/gate-L.json" "$out/measured-L.json" "$commit" <<'PY'
import json, sys
inputs, gate = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
b = inputs["builds"]["oneport"]
m = {"commit": sys.argv[4], "host": "L", "dry_run": gate["dry_run"], "citable": gate["citable"],
     "inputs_hash": {**{t: v["inputs_hash"] for t, v in b["targets"].items()}, **gate.get("harnesses", {}).get("inputs_hash", {})},
     "config": b.get("config"), "binaries": gate["binaries"], "records": sorted(gate["oneport"]["records"] + gate["harnesses"]["records"])}
json.dump(m, open(sys.argv[3], "w"), indent=1)
print(json.dumps({k: m[k] for k in ("commit", "dry_run", "citable", "binaries")}, indent=1))
PY
    }

    local only=" ${ONLY:-release asan tsan msan cmux-asan cmux-tsan hyper-util-asan hyper-util-tsan gate} "
    echo "steps: $only"
    [[ $only == *" release "* ]] && run release release
    if [[ $only == *" asan "* && $only == *" tsan "* ]]; then
        pair asan tsan
    else
        [[ $only == *" asan "* ]] && run asan bash "$here/sanitize_oneport.sh" asan "$records"
        [[ $only == *" tsan "* ]] && run tsan bash "$here/sanitize_oneport.sh" tsan "$records"
    fi
    [[ $only == *" msan "* ]] && run msan bash "$here/sanitize_oneport.sh" msan "$records"
    local h s
    for h in cmux hyper-util; do
        for s in asan tsan; do
            [[ $only == *" $h-$s "* ]] && run "$h-$s" env ONEPORT_BUILD="$build" bash "$here/sanitize_harness.sh" "$s" "$h" "$records"
        done
    done
    [[ $only == *" gate "* ]] && run gate gate
    status=done${dry:+ (dry run)}
    echo "records done $(date -Is)"
}

main "$@"
