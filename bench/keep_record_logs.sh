#!/usr/bin/env bash
# keep_record_logs.sh check NAME
# keep_record_logs.sh pack NAME [SRC...]
#
# The logs of the sanitizer record NAME, kept as the Papers repo's rule D5 asks: in
# $RECORDS_LOGS/NAME/ (default ~/lab/records-logs, never /tmp), packed into
# $RECORDS_LOGS/NAME.tar.gz, whose sha256 goes to NAME.tar.gz.sha256 and into the record.
#
#   check  refuses (exit 2) if NAME's directory or archive exists: record logs are never
#          overwritten, so a record is never made again in silence over an earlier one.
#   pack   copies each SRC file or directory into NAME/ (none: the directory already holds the
#          logs), writes NAME/SHA256SUMS (every file in it), packs NAME/ into NAME.tar.gz, writes
#          NAME.tar.gz.sha256, and prints the archive's path and sha256 on one line.
#
# Copied from paper-typed-routing bench/keep_record_logs.sh at commit 7c1e248, same author,
# unchanged but for this comment. Used by bench/sanitize_oneport.sh and bench/sanitize_harness.sh.
set -euo pipefail

mode=${1:?usage: keep_record_logs.sh check|pack NAME [SRC...]}
name=${2:?usage: keep_record_logs.sh check|pack NAME [SRC...]}
shift 2
root=${RECORDS_LOGS:-$HOME/lab/records-logs}
case "$root" in /tmp/*) echo "keep_record_logs: record logs never go to /tmp" >&2; exit 2 ;; esac
dir=$root/$name
tar=$root/$name.tar.gz

case "$mode" in
    check)
        if [ -e "$dir" ] || [ -e "$tar" ]; then
            echo "keep_record_logs: $dir or $tar exists; record logs are never overwritten" >&2
            exit 2
        fi ;;
    pack)
        [ ! -e "$tar" ] || { echo "keep_record_logs: $tar exists" >&2; exit 2; }
        mkdir -p "$dir"
        for src in "$@"; do
            [ -e "$src" ] && cp -a "$src" "$dir/"
        done
        (cd "$dir" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 -r sha256sum > SHA256SUMS)
        tar -czf "$tar" -C "$root" "$name"
        sha=$(sha256sum "$tar" | cut -d' ' -f1)
        printf '%s  %s\n' "$sha" "$name.tar.gz" > "$tar.sha256"
        echo "$tar $sha" ;;
    *) echo "keep_record_logs: unknown mode '$mode'" >&2; exit 2 ;;
esac
