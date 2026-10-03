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
"$lablock" bash "$here/notrack.sh" "$dir/$name.notrack.json" "$@" > "$dir/$name.log" 2>&1
rc=$?
printf '{"exit": %d, "end": "%s"}\n' "$rc" "$(date -Is)" > "$dir/$name.done"
exit "$rc"
