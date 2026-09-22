"""SSH auth monitor: parses journal/auth log for failed password attempts.

Collects (ip -> attempts) inside a sliding window so repeated brute-force
tries from a single host trigger an iptables ban.
"""

from __future__ import annotations

import collections
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from ..config import Config

log = logging.getLogger("sysadmin-agent.ssh")

# "Failed password for invalid user admin from 203.0.113.7 port 54321 ssh2"
# "Failed password for root from 203.0.113.7 port 54321 ssh2"
_FAILED_RE = re.compile(
    r"Failed (?:password|publickey|keyboard-interactive/(?:pam|device)) "
    r"for (?:invalid user )?(\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})",
    re.IGNORECASE,
)
# "Invalid user admin from 203.0.113.7 port 54321"
_INVALID_RE = re.compile(
    r"Invalid user (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})",
    re.IGNORECASE,
)
# "Accepted password for bob from 10.0.0.5 port 4242 ssh2"
_ACCEPTED_RE = re.compile(
    r"Accepted \S+ for (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})",
    re.IGNORECASE,
)


@dataclass
class SshEvent:
    ip: str
    username: str
    kind: str  # "failed" | "invalid" | "accepted"
    ts: float


@dataclass
class SshStatus:
    window_sec: int
    max_attempts: int
    events: list[SshEvent] = field(default_factory=list)

    @property
    def failures_by_ip(self) -> dict[str, int]:
        cutoff = time.time() - self.window_sec
        counts: collections.Counter[str] = collections.Counter()
        for ev in self.events:
            if ev.kind in ("failed", "invalid") and ev.ts >= cutoff:
                counts[ev.ip] += 1
        return dict(counts)

    def accepted_events(self) -> list[SshEvent]:
        return [ev for ev in self.events if ev.kind == "accepted"]


def _collect_recent(seconds: int) -> list[str]:
    """Return recent sshd log lines covering `seconds` back."""
    lines: list[str] = []

    # 1) journalctl - primary source on systemd distros
    if shutil.which("journalctl"):
        since = f"-{(max(seconds, 60))} seconds"
        try:
            proc = subprocess.run(
                ["journalctl", "-u", "sshd", "--since", since, "--no-pager",
                 "--output", "short-iso", "-n", "5000"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                lines.extend(proc.stdout.splitlines())
        except (subprocess.SubprocessError, OSError) as exc:
            log.debug("journalctl -u sshd failed: %s", exc)

    # 2) fallback to classic log files
    for path in ("/var/log/auth.log", "/var/log/secure", "/var/log/messages"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines.extend(fh.readlines())
            break
        except OSError:
            continue

    return lines


def check(cfg: Config) -> SshStatus | None:
    if not cfg.enabled("ssh_log.enabled"):
        return None

    window = int(cfg.get("ssh_log.window_sec", 300))
    max_attempts = int(cfg.get("ssh_log.max_failed_attempts", 5))

    status = SshStatus(window_sec=window, max_attempts=max_attempts)

    for line in _collect_recent(window + 60):
        m = _FAILED_RE.search(line)
        if m:
            status.events.append(
                SshEvent(ip=m.group("ip"), username=m.group(1),
                         kind="failed", ts=time.time())
            )
            continue
        m = _INVALID_RE.search(line)
        if m:
            status.events.append(
                SshEvent(ip=m.group("ip"), username=m.group("user"),
                         kind="invalid", ts=time.time())
            )
            continue
        m = _ACCEPTED_RE.search(line)
        if m:
            status.events.append(
                SshEvent(ip=m.group("ip"), username=m.group("user"),
                         kind="accepted", ts=time.time())
            )

    failures = status.failures_by_ip
    if failures:
        for ip, count in sorted(failures.items(), key=lambda kv: -kv[1]):
            level = logging.WARNING if count >= max_attempts else logging.INFO
            log.log(level, "SSH failures from %s: %d in last %ds", ip, count, window)

    for ev in status.accepted_events():
        log.info("SSH login accepted: user=%s ip=%s", ev.username, ev.ip)

    return status


def ban_candidates(status: SshStatus, whitelist: list[str]) -> list[str]:
    """Which violating IPs are actually safe (and useful) to ban."""
    import ipaddress

    wl: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in whitelist:
        try:
            wl.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            log.warning("invalid whitelist entry: %s", entry)

    result = []
    for ip, count in status.failures_by_ip.items():
        if count < status.max_attempts:
            continue
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if any(addr in net for net in wl):
            log.info("skipping whitelisted IP %s (%d failures)", ip, count)
            continue
        result.append(ip)
    return result
