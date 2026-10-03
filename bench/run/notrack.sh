#!/usr/bin/env bash
# notrack.sh RECORD COMMAND [ARGS...]: runs COMMAND with connection tracking off for loopback on L
# (Alex's approval of 2026-10-03; design/status.md, "L's connection tracking: NOTRACK for
# loopback"). lab_job.sh runs it inside the lab lock, so one job's rules never meet another's.
#
# With the iptables that Docker uses on L (iptables-nft: `iptables -V` reads "nf_tables"), it adds
# exactly two rules to the raw table:
#   iptables -t raw -A PREROUTING -i lo -j NOTRACK
#   iptables -t raw -A OUTPUT -o lo -j NOTRACK
# and removes exactly those two when COMMAND ends, however it ends (an EXIT trap; INT, TERM and HUP
# end the script so that the trap runs), then checks that they are gone. A base chain of the raw
# table that the first rule had to create is deleted again once it is empty, so the ruleset is left
# as it was found, which the record checks (`nft -s list ruleset` before and after). Docker's rules
# and chains are never touched, no table is flushed, and nothing persistent changes (no saved rule
# set, no unit).
#
# It refuses to run COMMAND (exit 91) if a rule is already present before the job (left by a job
# killed with SIGKILL: a rule it did not add is not its to remove), and (exit 93) if a rule cannot
# be added; each refusal writes RECORD with its reason. The NOTRACK target needs the kernel module xt_CT; a kernel whose module tree is no
# longer installed (a kernel package upgraded without a reboot) cannot load it.
#
# ONEPORT_NOTRACK=off runs COMMAND without the rules, loopback tracked, and says so in RECORD; it
# exists so that lab jobs can run while the rules cannot be added. Nothing falls back to it alone.
#
# RECORD (JSON): whether NOTRACK was in effect (and why not), the iptables version, the ruleset
# before, the rules added and when, the connection-tracking count at the job's start and end, the
# removal check and the job's exit status.
set -u
record=$1
shift
IPT=(sudo -n iptables-nft)
NFT=(sudo -n nft)
RULES=("PREROUTING -i lo -j NOTRACK" "OUTPUT -o lo -j NOTRACK")

ct_count() { cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo null; }
has_chain() { "${NFT[@]}" list chain ip raw "$1" > /dev/null 2>&1; }
has_table() { "${NFT[@]}" list table ip raw > /dev/null 2>&1; }

# write_record CT_END GONE RESTORED JOB_EXIT RULESET_AFTER CHAINS_DELETED REASON
write_record() {
  NT_RECORD=$record NT_VERSION=${version:-} NT_ADDED_AT=${added_at:-} NT_REMOVED_AT=${removed_at:-} \
  NT_CT_START=$ct_start NT_CT_END=$1 NT_GONE=$2 NT_RESTORED=$3 NT_RC=$4 NT_AFTER=$5 NT_DELETED=$6 NT_REASON=$7 \
  NT_RULES_ADDED=${#added[@]} NT_HAD="${had_table:-} ${had_pre:-} ${had_out:-}" NT_BEFORE=${ruleset_before:-} \
  NT_KERNEL="$(uname -r)" python3 - <<'PY'
import json, os
e = os.environ
num = lambda v: None if v in ("", "null") else int(v)
flag = lambda v: None if v == "" else v == "1"
had = (e["NT_HAD"].split() + ["", "", ""])[:3]
rec = {
    "notrack": num(e["NT_RULES_ADDED"]) == 2,
    "reason": e["NT_REASON"] or None,
    "iptables": e["NT_VERSION"] or None,
    "kernel": e["NT_KERNEL"],
    "rules": ["-t raw -A PREROUTING -i lo -j NOTRACK", "-t raw -A OUTPUT -o lo -j NOTRACK"],
    "rules_added": num(e["NT_RULES_ADDED"]),
    "added_at": e["NT_ADDED_AT"] or None,
    "removed_at": e["NT_REMOVED_AT"] or None,
    "conntrack_count_start": num(e["NT_CT_START"]),
    "conntrack_count_end": num(e["NT_CT_END"]),
    "before": {"raw_table": flag(had[0]), "raw_prerouting": flag(had[1]), "raw_output": flag(had[2])},
    "chains_deleted": e["NT_DELETED"].split(),
    "rules_gone": flag(e["NT_GONE"]),
    "ruleset_restored": flag(e["NT_RESTORED"]),
    "job_exit": num(e["NT_RC"]),
}
if e["NT_BEFORE"]:
    rec["ruleset_before"] = e["NT_BEFORE"]
if e["NT_AFTER"]:
    rec["ruleset_after"] = e["NT_AFTER"]
with open(e["NT_RECORD"], "w") as f:
    json.dump(rec, f, indent=1)
PY
}

added=()
ct_start=$(ct_count)

if [ "${ONEPORT_NOTRACK:-on}" = off ]; then
  echo "notrack: off (ONEPORT_NOTRACK=off): loopback is tracked for this job" >&2
  write_record "" "" "" "" "" "" "ONEPORT_NOTRACK=off"
  "$@"
  rc=$?
  write_record "$(ct_count)" "" "" "$rc" "" "" "ONEPORT_NOTRACK=off"
  exit "$rc"
fi

version=$(sudo -n iptables -V 2>&1)
case $version in
  *nf_tables*) ;;
  *)
    echo "notrack: iptables is not the nf_tables variant Docker uses on L: $version" >&2
    write_record "$(ct_count)" "" "" "" "" "" "iptables is not iptables-nft: $version"
    exit 90 ;;
esac
for r in "${RULES[@]}"; do
  # shellcheck disable=SC2086  # the rule's words are its arguments
  if "${IPT[@]}" -t raw -C $r > /dev/null 2>&1; then
    echo "notrack: '-t raw $r' is already present; not adding or removing it, not running the job" >&2
    write_record "$(ct_count)" "" "" "" "" "" "'-t raw $r' was already present (exit 91): the job did not run"
    exit 91
  fi
done
ruleset_before=$("${NFT[@]}" -s list ruleset)
had_table=0; has_table && had_table=1
had_pre=0; has_chain PREROUTING && had_pre=1
had_out=0; has_chain OUTPUT && had_out=1
added_at=""
removed_at=""
reason=""

teardown() {
  rc=$?
  trap - EXIT INT TERM HUP
  local r i deleted=""
  for (( i=${#added[@]}-1; i>=0; i-- )); do
    r=${added[$i]}
    # shellcheck disable=SC2086
    "${IPT[@]}" -t raw -D $r || echo "notrack: could not delete '-t raw $r'" >&2
  done
  local gone=1
  for r in "${RULES[@]}"; do
    # shellcheck disable=SC2086
    if "${IPT[@]}" -t raw -C $r > /dev/null 2>&1; then gone=0; echo "notrack: '-t raw $r' is still present" >&2; fi
  done
  # A base chain (or the table) that the first rule created, deleted once empty; nft refuses to
  # delete a chain that holds a rule, so a rule another program added meanwhile stays.
  if [ "$gone" = 1 ]; then
    if [ "$had_out" = 0 ] && has_chain OUTPUT && "${NFT[@]}" delete chain ip raw OUTPUT 2>/dev/null; then deleted+=" OUTPUT"; fi
    if [ "$had_pre" = 0 ] && has_chain PREROUTING && "${NFT[@]}" delete chain ip raw PREROUTING 2>/dev/null; then deleted+=" PREROUTING"; fi
    if [ "$had_table" = 0 ] && has_table && [ -z "$("${NFT[@]}" list table ip raw | grep -w chain)" ] \
       && "${NFT[@]}" delete table ip raw 2>/dev/null; then deleted+=" table"; fi
  fi
  removed_at=$(date -Is)
  local after restored=0
  after=$("${NFT[@]}" -s list ruleset)
  [ "$after" = "$ruleset_before" ] && restored=1
  local n_added=${#added[@]}
  write_record "$(ct_count)" "$gone" "$restored" "$rc" "$([ $restored = 1 ] || echo "$after")" "$deleted" "$reason"
  if [ "$gone" != 1 ]; then rc=92; fi
  echo "notrack: $n_added rules added, removed: gone=$gone ruleset restored=$restored" >&2
  exit "$rc"
}
trap teardown EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

for r in "${RULES[@]}"; do
  # shellcheck disable=SC2086
  if ! "${IPT[@]}" -t raw -A $r; then
    reason="could not add '-t raw $r' (kernel $(uname -r), its module tree $( [ -d "/lib/modules/$(uname -r)" ] && echo present || echo missing))"
    echo "notrack: $reason; the job does not run" >&2
    exit 93
  fi
  added+=("$r")
done
added_at=$(date -Is)
write_record "" "" "" "" "" "" ""
echo "notrack: active ($version), conntrack count $ct_start" >&2

"$@"
exit $?
