#!/usr/bin/env bash
# lab_job.sh DIR NAME COMMAND [ARGS...]: one lab job on L, detached from the ssh session.
#
# Runs COMMAND under the lab lock (lab/bin/lablock: one job on L at a time), writes DIR/NAME.pid
# (the job's process id, so it is stopped by its pid, never by pgrep -f or pkill -f),
# DIR/NAME.log (its output) and, when it ends, DIR/NAME.done (exit status and end time). Poll the
# done file, not the process table. The lock's path: ONEPORT_LABLOCK, else L's Papers checkout,
# ~/lab/Papers/lab/bin/lablock (read-only use; its content equals the Papers repo's lab/bin/lablock).
#
# Inside the lock, notrack.sh (beside this script) turns connection tracking off for loopback for
# the job's length and records it in DIR/NAME.notrack.json (Alex's approval of 2026-10-03;
# design/status.md); it refuses to run the job if a NOTRACK rule is already present.
#   setsid nohup bash bench/run/lab_job.sh ~/lab/p3/m3-aa aa-1 python3 bench/run/aa.py ... &
set -u
dir=$1
name=$2
shift 2
mkdir -p "$dir"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lablock=${ONEPORT_LABLOCK:-$HOME/lab/Papers/lab/bin/lablock}
echo $$ > "$dir/$name.pid"
date -Is > "$dir/$name.start"
# Before the lock, so that a queued job does not fail hours later: NOTRACK needs a kernel module,
# and a kernel whose module tree is gone (upgraded without a reboot) can load none. notrack.sh, in
# the lock, still decides; this only refuses early what it would refuse.
if [ "${ONEPORT_NOTRACK:-on}" != off ] && [ ! -d "/lib/modules/$(uname -r)" ]; then
  echo "lab_job: kernel $(uname -r) has no module tree, so NOTRACK cannot be added; the job does not run" \
    "(ONEPORT_NOTRACK=off runs it with loopback tracked)" > "$dir/$name.log"
  printf '{"exit": %d, "end": "%s"}\n' 93 "$(date -Is)" > "$dir/$name.done"
  exit 93
fi
# A job stopped by a signal to its process group (kill -TERM -- -PID, PID from the pid file) still
# gets its done file. Bash runs the trap once the lock's process has ended; notrack.sh, which holds
# the lock's descriptor until its teardown ends, may still be removing its rules then, so the done
# file waits (at most 60 s) for the record to name the removal. Tested on L, 2026-10-03 (M4a).
sig=""
trap 'sig=TERM' TERM
trap 'sig=INT' INT
trap 'sig=HUP' HUP
"$lablock" bash "$here/notrack.sh" "$dir/$name.notrack.json" "$@" > "$dir/$name.log" 2>&1
rc=$?
if [ -n "$sig" ] && grep -q '"added_at": "' "$dir/$name.notrack.json" 2> /dev/null; then
  for _ in $(seq 600); do
    grep -q '"removed_at": "' "$dir/$name.notrack.json" && break
    sleep 0.1
  done
fi
printf '{"exit": %d, "end": "%s", "signal": %s}\n' "$rc" "$(date -Is)" "$([ -n "$sig" ] && echo "\"$sig\"" || echo null)" > "$dir/$name.done"
exit "$rc"
