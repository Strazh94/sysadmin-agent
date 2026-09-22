"""Firewall actions: ban offending IPs via iptables.

Rules are inserted into a dedicated chain (SYSADMIN_AGENT by default) that
is jumped to from INPUT, so the agent can flush only its own rules without
touching the rest of the firewall.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from ..config import Config

log = logging.getLogger("sysadmin-agent.firewall")

# remember already-banned IPs so we do not spam iptables every cycle
_banned: set[str] = set()


def _run(cmd: list[str], dry_run: bool, label: str) -> bool:
    if dry_run:
        log.info("[dry-run] would execute (%s): %s", label, " ".join(cmd))
        return True
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("%s failed to start: %s", label, exc)
        return False
    if proc.returncode != 0:
        log.error("%s rc=%s: %s", label, proc.returncode, proc.stderr.strip())
        return False
    return True


def available() -> bool:
    return shutil.which("iptables") is not None


def _ensure_chain(chain: str, dry_run: bool) -> None:
    """Create chain and INPUT jump if missing (idempotent)."""
    check = subprocess.run(
        ["iptables", "-n", "--list", chain], capture_output=True, text=True, check=False
    )
    if check.returncode != 0:
        _run(["iptables", "-N", chain], dry_run, "create chain")
    jump = subprocess.run(
        ["iptables", "-C", "INPUT", "-j", chain], capture_output=True, check=False
    )
    if jump.returncode != 0:
        _run(["iptables", "-I", "INPUT", "1", "-j", chain], dry_run, "add INPUT jump")


def ban_ip(cfg: Config, ip: str, ttl_sec: int = 0) -> bool:
    """Ban a single IP. Returns True if the ban is in effect (or dry-run)."""
    if not cfg.enabled("actions.firewall.enabled"):
        log.info("firewall actions disabled in config - would ban %s", ip)
        return False
    if not available():
        log.error("iptables not found - cannot ban %s", ip)
        return False

    dry = cfg.dry_run
    chain = str(cfg.get("actions.firewall.chain", "SYSADMIN_AGENT"))

    if ip in _banned and not dry:
        log.debug("%s already banned", ip)
        return True

    _ensure_chain(chain, dry)

    ok = _run(
        ["iptables", "-A", chain, "-s", ip, "-j", "DROP"],
        dry,
        f"ban {ip}",
    )
    if not ok:
        return False

    _banned.add(ip)
    log.warning("BANNED %s via iptables chain %s (ttl=%ss)%s",
                ip, chain, ttl_sec, " [dry-run]" if dry else "")

    if ttl_sec > 0 and not dry:
        log.info(
            "ban of %s should be lifted after %ss "
            "(use: bin/ban-ip.sh --unban %s)",
            ip, ttl_sec, ip,
        )

    if cfg.get("actions.firewall.persist", True) and not dry and shutil.which(
        "netfilter-persistent"
    ):
        _run(["netfilter-persistent", "save"], False, "persist rules")

    return True


def ban_ips(cfg: Config, ips: list[str], ttl_sec: int = 0) -> None:
    for ip in ips:
        ban_ip(cfg, ip, ttl_sec=ttl_sec)


def status_summary() -> str:
    if not _banned:
        return "no IPs banned by agent"
    return "banned: " + ", ".join(sorted(_banned))
