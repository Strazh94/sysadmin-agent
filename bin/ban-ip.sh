#!/usr/bin/env bash
# ban-ip.sh - ban an IP address via iptables in the agent's dedicated chain.
#
# Usage:
#   sudo ./ban-ip.sh 203.0.113.7          # ban
#   sudo ./ban-ip.sh --unban 203.0.113.7  # unban
#   sudo ./ban-ip.sh --status             # list agent rules
#
# Can be called manually or by the sysadmin-agent daemon.
set -euo pipefail

CHAIN="${SYSADMIN_AGENT_CHAIN:-SYSADMIN_AGENT}"

die() { echo "error: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "root required"

command -v iptables >/dev/null 2>&1 || die "iptables not found"

ensure_chain() {
    iptables -n --list "$CHAIN" >/dev/null 2>&1 || iptables -N "$CHAIN"
    iptables -C INPUT -j "$CHAIN" 2>/dev/null || iptables -I INPUT 1 -j "$CHAIN"
}

case "${1:-}" in
    --status)
        echo "chain $CHAIN:"
        iptables -n --list "$CHAIN" 2>/dev/null || echo "  (not created)"
        exit 0
        ;;
    --unban)
        ip="${2:-}"; [[ -n "$ip" ]] || die "usage: $0 --unban <ip>"
        iptables -D "$CHAIN" -s "$ip" -j DROP 2>/dev/null || true
        echo "unbanned $ip"
        ;;
    "")
        die "usage: $0 <ip> | --unban <ip> | --status"
        ;;
    *)
        ip="$1"
        # basic sanity: IPv4 or IPv4 CIDR
        [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]] || die "bad ip: $ip"
        ensure_chain
        iptables -C "$CHAIN" -s "$ip" -j DROP 2>/dev/null || \
            iptables -A "$CHAIN" -s "$ip" -j DROP
        echo "banned $ip"
        command -v netfilter-persistent >/dev/null 2>&1 && netfilter-persistent save || true
        ;;
esac
