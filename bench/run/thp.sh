#!/usr/bin/env bash
# thp.sh RECORD COMMAND [ARGS...]: runs COMMAND with transparent huge pages on L set to `madvise`,
# Alex's decision of 2026-10-03 (design/status.md, M4b-1, "B3 on L and transparent huge pages"):
# /sys/kernel/mm/transparent_hugepage/enabled is set to madvise for the job's length, and, only
# when ONEPORT_THP_DEFRAG names a value, `defrag` to that value too; each file is set back to the
# value it had when COMMAND ends, however it ends (an EXIT trap; INT, TERM and HUP end the script so
# that the trap runs). lab_job.sh runs it inside the lab lock, inside clockfloor.sh and outside
# notrack.sh, so one job's setting never meets another's. A second wrapper beside clockfloor.sh,
# not a change of it: clockfloor.sh stays as it was tested.
#
# Why (hypotheses.md revision log, "Transparent huge pages before the code freeze"): with
# enabled=always khugepaged collapses a process's anonymous memory into huge pages while the
# process is idle, about every 10 s on L (khugepaged/scan_sleep_millisecs 10000), and each collapse
# raised a B3 front's VmRSS by megabytes the front never touched (M4b-1: b3diag2, b3diag3), which
# failed section 7's settling rule. Under madvise, huge pages are used, at fault and by khugepaged,
# only in regions a process marks with madvise(MADV_HUGEPAGE) (Documentation/admin-guide/mm/
# transhuge.rst at v7.2.6, "Global THP controls"). `defrag` governs the page-fault path's reclaim
# and compaction for huge pages, not khugepaged's scan (ibid., the defrag modes; khugepaged/defrag
# is khugepaged's own); on L it reads madvise already.
#
# Nothing persistent changes: sysfs values last until the next write or boot.
#
# RECORD (JSON): whether THP was set (and why not), the state before, once set and after the
# restore (the selected word of enabled, defrag and khugepaged/defrag; AnonHugePages of
# /proc/meminfo; thp_fault_alloc and thp_collapse_alloc of /proc/vmstat; khugepaged's
# pages_collapsed and full_scans), the times, whether every setting took and whether every one came
# back, and COMMAND's exit status. The job's processes find RECORD in ONEPORT_THP_RECORD (window.py
# puts its before values in each session's fingerprint).
# Exit 97: a setting could not be made; COMMAND did not run, and every value written is set back.
# Exit 98: a setting did not come back; COMMAND's status is in RECORD.
# ONEPORT_THP=off runs COMMAND without the change and says so in RECORD.
# For the test (bench/run/test_runner.py): THP_ROOT (a copy of the sysfs tree), THP_SUDO ("" writes
# directly).
set -u
record=$1
shift
root=${THP_ROOT:-/sys/kernel/mm/transparent_hugepage}
SUDO=${THP_SUDO-sudo -n}
want_enabled=madvise
want_defrag=${ONEPORT_THP_DEFRAG:-}

# selected FILE: the word in brackets ("always [madvise] never"), or the whole value when a file
# holds one bare word (the test's copy of the tree after a write).
selected() {
  local v
  v=$(cat "$1" 2>/dev/null) || return 1
  if [[ $v =~ \[([^]]+)\] ]]; then echo "${BASH_REMATCH[1]}"; else echo "$v" | tr -d '[:space:]'; fi
}

# state: the THP settings and counters as JSON on stdout.
state() {
  THP_S_ENABLED="$(selected "$root/enabled")" THP_S_DEFRAG="$(selected "$root/defrag")" \
  THP_S_KDEFRAG="$(cat "$root/khugepaged/defrag" 2>/dev/null)" \
  THP_S_COLLAPSED="$(cat "$root/khugepaged/pages_collapsed" 2>/dev/null)" \
  THP_S_SCANS="$(cat "$root/khugepaged/full_scans" 2>/dev/null)" \
  python3 - <<'PY'
import json, os
e = os.environ

def num(v):
    return int(v) if v and v.strip().isdigit() else (v or None)

def proc(path, keys):
    out = {}
    try:
        with open(path) as f:
            for line in f:
                p = line.replace(":", " ").split()
                if p and p[0] in keys:
                    out[p[0]] = int(p[1])
    except OSError:
        pass
    return out

mem = proc("/proc/meminfo", {"AnonHugePages"})
vm = proc("/proc/vmstat", {"thp_fault_alloc", "thp_collapse_alloc"})
print(json.dumps({
    "enabled": e["THP_S_ENABLED"] or None, "defrag": e["THP_S_DEFRAG"] or None,
    "khugepaged_defrag": num(e["THP_S_KDEFRAG"]), "anon_huge_pages_kb": mem.get("AnonHugePages"),
    "thp_fault_alloc": vm.get("thp_fault_alloc"), "thp_collapse_alloc": vm.get("thp_collapse_alloc"),
    "khugepaged_pages_collapsed": num(e["THP_S_COLLAPSED"]), "khugepaged_full_scans": num(e["THP_S_SCANS"])}))
PY
}

# write_record JOB_EXIT HELD RESTORED ON
write_record() {
  TR_RECORD=$record TR_BEFORE=${before:-} TR_SET=${set_state:-} TR_AFTER=${after:-} TR_SET_AT=${set_at:-} \
  TR_RESTORED_AT=${restored_at:-} TR_REASON=${reason:-} TR_RC=$1 TR_HELD=$2 TR_RESTORED=$3 TR_ON=$4 TR_KERNEL="$(uname -r)" \
  TR_WANT_ENABLED=$want_enabled TR_WANT_DEFRAG=$want_defrag python3 - <<'PY'
import json, os
e = os.environ

def js(k):
    return json.loads(e[k]) if e.get(k) else None

def flag(k):
    return None if e.get(k, "") == "" else e[k] == "1"

rec = {
    "thp": e["TR_ON"] == "1",
    "reason": e["TR_REASON"] or None,
    "kernel": e["TR_KERNEL"],
    "wanted": {"enabled": e["TR_WANT_ENABLED"], "defrag": e["TR_WANT_DEFRAG"] or None},
    "set_at": e["TR_SET_AT"] or None,
    "restored_at": e["TR_RESTORED_AT"] or None,
    "held": flag("TR_HELD"),
    "restored": flag("TR_RESTORED"),
    "job_exit": int(e["TR_RC"]) if e.get("TR_RC") else None,
    "before": js("TR_BEFORE"),
    "set": js("TR_SET"),
    "after": js("TR_AFTER"),
}
with open(e["TR_RECORD"], "w") as f:
    json.dump(rec, f, indent=1)
PY
}

# writev FILE VALUE
writev() {
  # shellcheck disable=SC2086  # SUDO is a command and its options
  echo "$2" | $SUDO tee "$1" > /dev/null
}

before=$(state)
if [ "${ONEPORT_THP:-on}" = off ]; then
  reason="ONEPORT_THP=off"
  echo "thp: off (ONEPORT_THP=off): transparent huge pages keep their setting for this job" >&2
  write_record "" "" "" 0
  "$@"
  rc=$?
  after=$(state)
  write_record "$rc" "" "" 0
  exit "$rc"
fi

declare -A orig want
want[$root/enabled]=$want_enabled
if [ -n "$want_defrag" ]; then want[$root/defrag]=$want_defrag; fi
for f in "${!want[@]}"; do
  if ! orig[$f]=$(selected "$f") || [ -z "${orig[$f]}" ]; then
    unset "orig[$f]"
    reason="$f cannot be read: the job does not run"
    echo "thp: $reason" >&2
    write_record "" "" "" 0
    exit 97
  fi
done
held=""
restored=""
set_at=""
restored_at=""
reason=""

teardown() {
  rc=$?
  trap - EXIT INT TERM HUP
  local f ok=1
  for f in "${!orig[@]}"; do
    writev "$f" "${orig[$f]}" || echo "thp: could not write ${orig[$f]} to $f" >&2
    if [ "$(selected "$f")" != "${orig[$f]}" ]; then
      ok=0
      echo "thp: $f reads $(selected "$f"), not ${orig[$f]}" >&2
    fi
  done
  restored=$ok
  restored_at=$(date -Is)
  after=$(state)
  write_record "$rc" "$held" "$restored" 1
  if [ "$restored" != 1 ]; then rc=98; fi
  echo "thp: settings set back, restored=$restored" >&2
  exit "$rc"
}
trap teardown EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

held=1
for f in "${!want[@]}"; do
  if ! writev "$f" "${want[$f]}" 2>/dev/null || [ "$(selected "$f")" != "${want[$f]}" ]; then
    held=0
    echo "thp: $f did not take ${want[$f]}" >&2
  fi
done
set_at=$(date -Is)
set_state=$(state)
if [ "$held" != 1 ]; then
  reason="a transparent huge page setting did not take: the job does not run"
  echo "thp: $reason" >&2
  exit 97
fi
write_record "" "$held" "" 1
echo "thp: enabled=$(selected "$root/enabled") defrag=$(selected "$root/defrag") for this job" >&2

export ONEPORT_THP_RECORD=$record
"$@"
exit $?
