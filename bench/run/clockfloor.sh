#!/usr/bin/env bash
# clockfloor.sh RECORD COMMAND [ARGS...]: runs COMMAND with every CPU's frequency floor raised to
# its ceiling on L, the coordinator's decision of 2026-10-03 (option (a) of design/status.md, M4a,
# step 0, 1): each CPU's scaling_min_freq is set to its scaling_max_freq for the job's length,
# beside what lab/bin/pin.sh sets (boost off, the performance governor, AC power), and set back to
# the value it had when COMMAND ends, however it ends (an EXIT trap; INT, TERM and HUP end the
# script so that the trap runs). lab_job.sh runs it inside the lab lock and outside notrack.sh, so
# one job's floor never meets another's. pin.sh is not changed: P1 and P2 use it as it is.
#
# Why (hypotheses.md revision log, "Host clock floor before the code freeze"): on kernel 7.2.6 the
# amd-pstate-epp driver's policy minimum on L reads 1,102,866 kHz, and a CPU whose APERF/MPERF
# sample is older than 20 ms reports the policy's current value as its `cpu MHz`, which the driver
# keeps at the policy minimum. pin.sh reads its session MHz with the host idle, so it read low. With
# the floor at the ceiling an idle CPU reports 3,201,000 kHz. Under the performance policy the
# driver does not pass scaling_min_freq to the hardware (drivers/cpufreq/amd-pstate.c at v7.2.6,
# amd_pstate_update_min_max_limit): the CPPC request stays MinPerf = MaxPerf = nominal, EPP 0, which
# the record reads from MSR 0xC00102B3 (read-only) before, while and after the job.
#
# Nothing persistent changes. Writing a value back leaves a user frequency request at that value
# where the driver's default was, which reads the same.
#
# RECORD (JSON): whether the floor was set (and why not), the state of every CPU before, once set
# and after the restore (scaling_min_freq, scaling_max_freq, the governor, EPP, the CPPC request),
# the times, whether every floor reached its ceiling and whether every floor came back, and
# COMMAND's exit status. The job's processes find RECORD in ONEPORT_CLOCK_RECORD (window.py puts
# its before values in each session's fingerprint).
# Exit 95: the floor could not be set; COMMAND did not run, and every value written is set back.
# Exit 96: a floor did not come back; COMMAND's status is in RECORD.
# ONEPORT_CLOCK_FLOOR=off runs COMMAND without the floor and says so in RECORD.
# For the test (bench/run/test_runner.py): CLOCKFLOOR_CPU_ROOT (a copy of the cpufreq tree),
# CLOCKFLOOR_SUDO ("" writes directly), CLOCKFLOOR_MSR=off.
set -u
record=$1
shift
root=${CLOCKFLOOR_CPU_ROOT:-/sys/devices/system/cpu}
SUDO=${CLOCKFLOOR_SUDO-sudo -n}
msr=${CLOCKFLOOR_MSR:-on}

# state: every CPU's cpufreq state as JSON on stdout (the MSR needs root, hence SUDO).
state() {
  # shellcheck disable=SC2086  # SUDO is a command and its options
  $SUDO python3 - "$root" "$msr" <<'PY'
import json, os, re, struct, sys
root, msr = sys.argv[1], sys.argv[2]

def rd(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None

def num(v):
    return int(v) if v is not None and v.isdigit() else v

def cppc_request(cpu):
    """MSR_AMD_CPPC_REQ (0xC00102B3), read only: the fields amd-pstate writes."""
    if msr != "on":
        return None
    try:
        fd = os.open(f"/dev/cpu/{cpu}/msr", os.O_RDONLY)
    except OSError:
        return None
    try:
        v = struct.unpack("<Q", os.pread(fd, 8, 0xC00102B3))[0]
    except OSError:
        return None
    finally:
        os.close(fd)
    return {"max_perf": v & 0xFF, "min_perf": (v >> 8) & 0xFF, "des_perf": (v >> 16) & 0xFF, "epp": (v >> 24) & 0xFF}

cpus = sorted(int(m.group(1)) for d in os.listdir(root)
              if (m := re.fullmatch(r"cpu(\d+)", d)) and os.path.isdir(f"{root}/{d}/cpufreq"))
out = {"boost": num(rd(f"{root}/cpufreq/boost")), "cpus": {}}
for c in cpus:
    p = f"{root}/cpu{c}/cpufreq"
    out["cpus"][str(c)] = {
        "scaling_min_freq": num(rd(f"{p}/scaling_min_freq")), "scaling_max_freq": num(rd(f"{p}/scaling_max_freq")),
        "scaling_governor": rd(f"{p}/scaling_governor"),
        "energy_performance_preference": rd(f"{p}/energy_performance_preference"), "cppc_request": cppc_request(c)}
print(json.dumps(out))
PY
}

# write_record JOB_EXIT HELD RESTORED ON
write_record() {
  CF_RECORD=$record CF_BEFORE=${before:-} CF_SET=${set_state:-} CF_AFTER=${after:-} CF_SET_AT=${set_at:-} \
  CF_RESTORED_AT=${restored_at:-} CF_REASON=${reason:-} CF_RC=$1 CF_HELD=$2 CF_RESTORED=$3 CF_ON=$4 CF_KERNEL="$(uname -r)" \
  CF_DRIVER="$(cat "$root/cpu0/cpufreq/scaling_driver" 2>/dev/null)" CF_STATUS="$(cat "$root/amd_pstate/status" 2>/dev/null)" \
  python3 - <<'PY'
import json, os
e = os.environ

def js(k):
    return json.loads(e[k]) if e.get(k) else None

def flag(k):
    return None if e.get(k, "") == "" else e[k] == "1"

rec = {
    "clock_floor": e["CF_ON"] == "1",
    "reason": e["CF_REASON"] or None,
    "kernel": e["CF_KERNEL"],
    "driver": e["CF_DRIVER"] or None,
    "amd_pstate_status": e["CF_STATUS"] or None,
    "set_at": e["CF_SET_AT"] or None,
    "restored_at": e["CF_RESTORED_AT"] or None,
    "floor_held": flag("CF_HELD"),
    "restored": flag("CF_RESTORED"),
    "job_exit": int(e["CF_RC"]) if e.get("CF_RC") else None,
    "before": js("CF_BEFORE"),
    "set": js("CF_SET"),
    "after": js("CF_AFTER"),
}
with open(e["CF_RECORD"], "w") as f:
    json.dump(rec, f, indent=1)
PY
}

# writev FILE VALUE
writev() {
  # shellcheck disable=SC2086
  echo "$2" | $SUDO tee "$1" > /dev/null
}

before=$(state)
if [ "${ONEPORT_CLOCK_FLOOR:-on}" = off ]; then
  reason="ONEPORT_CLOCK_FLOOR=off"
  echo "clockfloor: off (ONEPORT_CLOCK_FLOOR=off): each CPU keeps its floor for this job" >&2
  write_record "" "" "" 0
  "$@"
  rc=$?
  after=$(state)
  write_record "$rc" "" "" 0
  exit "$rc"
fi

files=("$root"/cpu[0-9]*/cpufreq/scaling_min_freq)
if [ ! -e "${files[0]}" ]; then
  reason="no scaling_min_freq under $root: the job does not run"
  echo "clockfloor: $reason" >&2
  write_record "" "" "" 0
  exit 95
fi
declare -A orig
for f in "${files[@]}"; do orig[$f]=$(cat "$f"); done
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
    writev "$f" "${orig[$f]}" || echo "clockfloor: could not write ${orig[$f]} to $f" >&2
    if [ "$(cat "$f")" != "${orig[$f]}" ]; then
      ok=0
      echo "clockfloor: $f reads $(cat "$f"), not ${orig[$f]}" >&2
    fi
  done
  restored=$ok
  restored_at=$(date -Is)
  after=$(state)
  write_record "$rc" "$held" "$restored" 1
  if [ "$restored" != 1 ]; then rc=96; fi
  echo "clockfloor: floors set back, restored=$restored" >&2
  exit "$rc"
}
trap teardown EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

held=1
for f in "${files[@]}"; do
  max=$(cat "${f%/scaling_min_freq}/scaling_max_freq")
  if ! writev "$f" "$max" 2>/dev/null || [ "$(cat "$f")" != "$max" ]; then
    held=0
    echo "clockfloor: $f did not take $max" >&2
  fi
done
set_at=$(date -Is)
set_state=$(state)
if [ "$held" != 1 ]; then
  reason="a CPU's scaling_min_freq did not take its scaling_max_freq: the job does not run"
  echo "clockfloor: $reason" >&2
  exit 95
fi
write_record "" "$held" "" 1
echo "clockfloor: every CPU's scaling_min_freq at its scaling_max_freq ($(cat "${files[0]%/scaling_min_freq}/scaling_max_freq") kHz on cpu0)" >&2

export ONEPORT_CLOCK_RECORD=$record
"$@"
exit $?
