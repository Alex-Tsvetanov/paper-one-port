#!/usr/bin/env bash
# l_quick.sh HOME PLAN OUT SHA256 BUILD SEED: one quick-benchmark plan on L (quick-plan.md, decisions d006 and d007), from this
# checkout, run by lab_p3.py quick inside labrun's L wrappers (the lab lock, the clock floor, THP at madvise, NOTRACK, nice 0).
# The Release build BUILD was made in the build phase by lab_p3.py prepare. This script runs
#   bench/run/quick_run.py --plan PLAN --build BUILD --out OUT --quick SHA256 --seed SEED --blocks HOME/src-blocks.json
# and writes OUT/quick-summary.txt (the host, the commit, the build's flags and the exit status). It refuses a job at any
# nice other than 0 (exit 92), as lab_job.sh does. Written for P3.
set -u
home=${1:?usage: l_quick.sh HOME PLAN OUT SHA256 BUILD SEED}
plan=${2:?usage: l_quick.sh HOME PLAN OUT SHA256 BUILD SEED}
out=${3:?usage: l_quick.sh HOME PLAN OUT SHA256 BUILD SEED}
sha=${4:?usage: l_quick.sh HOME PLAN OUT SHA256 BUILD SEED}
build=${5:?usage: l_quick.sh HOME PLAN OUT SHA256 BUILD SEED}
seed=${6:?usage: l_quick.sh HOME PLAN OUT SHA256 BUILD SEED}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)
mkdir -p "$out" "$home"
summary=$out/quick-summary.txt
: > "$summary"
nice_now=$(ps -o ni= -p $$ | tr -d ' ')
{
  echo "commit $(git -C "$repo" rev-parse HEAD)"
  echo "host $(uname -n) kernel $(uname -r) nice $nice_now"
  echo "plan $plan sha256 $sha seed $seed"
  echo "build $build"
  echo "CMAKE_BUILD_TYPE $(sed -n 's/^CMAKE_BUILD_TYPE:STRING=//p' "$build/CMakeCache.txt")"
  echo "clang $(clang++ --version | head -1)"
} >> "$summary"
if [ "$nice_now" != 0 ] && [ "${ONEPORT_ALLOW_NICE:-0}" != 1 ]; then
  echo "l_quick: nice $nice_now, a lab job runs at nice 0" | tee -a "$summary"
  exit 92
fi
python3 "$here/quick_run.py" --plan "$plan" --build "$build" --out "$out" --quick "$sha" --seed "$seed" \
  --blocks "$home/src-blocks.json" > "$out/quick.log" 2>&1
rc=$?
echo "quick_run $rc" >> "$summary"
tail -n 5 "$out/quick.log"
cat "$summary"
exit "$rc"
