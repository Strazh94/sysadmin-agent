#!/usr/bin/env bash
# cleanup-logs.sh - manually free disk space and RAM.
#
# Usage:
#   sudo ./cleanup-logs.sh            # journal vacuum + old rotated logs + drop caches
#   sudo ./cleanup-logs.sh --dry-run  # show what would be done
#   sudo ./cleanup-logs.sh --logs     # only logs
#   sudo ./cleanup-logs.sh --memory   # only drop_caches + /tmp
set -euo pipefail

DRY=0
DO_LOGS=0
DO_MEM=0

for arg in "$@"; do
    case "$arg" in
        --dry-run)  DRY=1 ;;
        --logs)     DO_LOGS=1 ;;
        --memory)   DO_MEM=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 1 ;;
    esac
done
[[ $DO_LOGS -eq 0 && $DO_MEM -eq 0 ]] && { DO_LOGS=1; DO_MEM=1; }

run() {
    if [[ $DRY -eq 1 ]]; then
        echo "[dry-run] $*"
    else
        echo "+ $*"
        "$@"
    fi
}

if [[ $DO_LOGS -eq 1 ]]; then
    command -v journalctl >/dev/null 2>&1 && \
        run journalctl --vacuum-size=200M || echo "journalctl not available"

    # rotated logs older than 14 days
    if [[ $DRY -eq 1 ]]; then
        echo "[dry-run] files older than 14d in /var/log:"
        find /var/log -maxdepth 1 -type f \( -name '*.gz' -o -name '*.1' \) \
            -mtime +14 -print 2>/dev/null || true
    else
        find /var/log -maxdepth 1 -type f \( -name '*.gz' -o -name '*.1' \) \
            -mtime +14 -delete -print 2>/dev/null || true
    fi
fi

if [[ $DO_MEM -eq 1 ]]; then
    run sync
    if [[ $DRY -eq 1 ]]; then
        echo "[dry-run] echo 3 > /proc/sys/vm/drop_caches"
    else
        echo 3 > /proc/sys/vm/drop_caches
        echo "drop_caches done"
    fi
    # stale files in /tmp (older than 7 days, non-recursive)
    find /tmp -maxdepth 1 -type f -mtime +7 -delete 2>/dev/null || true
fi

df -h / /var 2>/dev/null || true
free -h 2>/dev/null || true
