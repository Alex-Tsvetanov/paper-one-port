#!/usr/bin/env bash
# lab_job.sh DIR NAME COMMAND [ARGS...]: one lab job on L, detached from the ssh session.
#
# Runs COMMAND under the lab lock (lab/bin/lablock: one job on L at a time), writes DIR/NAME.pid
# (the job's process id, so it is stopped by its pid, never by pgrep -f or pkill -f),
# DIR/NAME.log (its output) and, when it ends, DIR/NAME.done (exit status and end time). Poll the
# done file, not the process table. The lock's path: ONEPORT_LABLOCK, else L's Papers checkout,
# ~/lab/Papers/lab/bin/lablock (read-only use; its content equals the Papers repo's lab/bin/lablock).
#
# Inside the lock, clockfloor.sh (beside this script) raises every CPU's scaling_min_freq to its
# scaling_max_freq for the job's length and sets each back at its end, recorded in
# DIR/NAME.clock.json (the coordinator's decision of 2026-10-03; design/status.md, M4b-1); inside
# it, thp.sh sets transparent huge pages to madvise for the job's length and sets them back at its
# end, recorded in DIR/NAME.thp.json (Alex's decision of 2026-10-03; design/status.md, M4b-2);
# inside that, notrack.sh turns connection tracking off for loopback for the job's length and
# records it in DIR/NAME.notrack.json (Alex's approval of 2026-10-03; design/status.md); it refuses
# to run the job if a NOTRACK rule is already present.
#   setsid nohup bash bench/run/lab_job.sh ~/lab/p3/m3-aa aa-1 python3 bench/run/aa.py ... &
# Launched from L's login shell, zsh, that line runs at nice 5: zsh lowers the priority of every
# background job (its BG_NICE option, on by default). Found in M7c: at nice above 0 the kernel
# gives a timed wait of epoll a slack of 0.5% of the time left instead of 0.1% (fs/select.c,
# select_estimate_accuracy, used by epoll_pwait2), so the pilot's timer part saw T_hdr handled
# about 15 ms late on epoll; and every process of the job competes at a lower priority than the
# host's own. A lab job runs at nice 0: this script refuses a job at any other (exit 92), unless
# ONEPORT_ALLOW_NICE=1. Launch it from bash, for example
#   bash -c '(setsid nohup bash bench/run/lab_job.sh DIR NAME COMMAND ... > /dev/null 2>&1 &)'
# or from zsh after `setopt NO_BG_NICE`.
set -u
dir=$1
name=$2
shift 2
mkdir -p "$dir"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lablock=${ONEPORT_LABLOCK:-$HOME/lab/Papers/lab/bin/lablock}
echo $$ > "$dir/$name.pid"
date -Is > "$dir/$name.start"
nice_now=$(ps -o ni= -p $$ | tr -d ' ')
if [ "$nice_now" != 0 ] && [ "${ONEPORT_ALLOW_NICE:-0}" != 1 ]; then
  echo "lab_job: this job runs at nice $nice_now; a lab job runs at nice 0, so it does not run (zsh runs" \
    "background jobs at nice 5: launch from bash, or setopt NO_BG_NICE; ONEPORT_ALLOW_NICE=1 runs it anyway)" > "$dir/$name.log"
  printf '{"exit": %d, "end": "%s", "nice": %s}\n' 92 "$(date -Is)" "$nice_now" > "$dir/$name.done"
  exit 92
fi
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
# gets its done file. Bash runs the trap once the lock's process has ended; notrack.sh, thp.sh and
# clockfloor.sh, which hold the lock's descriptor until their teardowns end, may still be removing
# their rules or setting the floors and THP back then, so the done file waits (at most 60 s in all)
# for each record to name its teardown. Tested on L, 2026-10-03 (M4a; the floor's in M4b-1; THP's in
# M4b-2).
sig=""
trap 'sig=TERM' TERM
trap 'sig=INT' INT
trap 'sig=HUP' HUP
"$lablock" bash "$here/clockfloor.sh" "$dir/$name.clock.json" \
  bash "$here/thp.sh" "$dir/$name.thp.json" \
  bash "$here/notrack.sh" "$dir/$name.notrack.json" "$@" > "$dir/$name.log" 2>&1
rc=$?
if [ -n "$sig" ]; then
  for _ in $(seq 600); do
    if grep -q '"added_at": "' "$dir/$name.notrack.json" 2> /dev/null \
       && ! grep -q '"removed_at": "' "$dir/$name.notrack.json"; then sleep 0.1; continue; fi
    if grep -q '"set_at": "' "$dir/$name.clock.json" 2> /dev/null \
       && ! grep -q '"restored_at": "' "$dir/$name.clock.json"; then sleep 0.1; continue; fi
    if grep -q '"set_at": "' "$dir/$name.thp.json" 2> /dev/null \
       && ! grep -q '"restored_at": "' "$dir/$name.thp.json"; then sleep 0.1; continue; fi
    break
  done
fi
printf '{"exit": %d, "end": "%s", "signal": %s}\n' "$rc" "$(date -Is)" "$([ -n "$sig" ] && echo "\"$sig\"" || echo null)" > "$dir/$name.done"
exit "$rc"
