"""User/account monitor: reports locked, expired and passwordless accounts.

Report-only — the agent never changes accounts by itself, it just surfaces
drift so an admin can react (alert goes to journald + log file).
"""

from __future__ import annotations

import logging

try:  # POSIX only - on dev machines (Windows) the monitor is skipped
    import pwd
except ImportError:  # pragma: no cover
    pwd = None  # type: ignore[assignment]

from dataclasses import dataclass, field

from ..config import Config

log = logging.getLogger("sysadmin-agent.users")

# system accounts that are expected to be locked / without a shell
_SYSTEM_OK = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail",
    "news", "uucp", "proxy", "backup", "list", "irc", "nobody", "_apt",
    "systemd-network", "systemd-resolve", "systemd-timesync",
    "systemd-coredump", "messagebus", "sshd", "syslog", "uuidd",
    "tss", "landscape", "pollinate", "lxd", "usbmux",
}


@dataclass
class UserStatus:
    locked: list[str] = field(default_factory=list)
    passwordless: list[str] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)

    @property
    def anomaly(self) -> bool:
        # locked system-ish accounts or anyone without a password
        return bool(self.passwordless)

    def describe(self) -> str:
        bits = []
        if self.passwordless:
            bits.append("passwordless: " + ", ".join(self.passwordless))
        if self.expired:
            bits.append("expired: " + ", ".join(self.expired))
        if self.locked:
            bits.append("locked: " + ", ".join(self.locked))
        return "; ".join(bits) or "accounts ok"


def check(cfg: Config) -> UserStatus | None:
    if not cfg.enabled("users.enabled"):
        return None

    status = UserStatus()

    if pwd is None:
        log.debug("pwd module unavailable - user monitor skipped")
        return None

    accounts = pwd.getpwall()
    for acct in accounts:
        is_system = (
            acct.pw_uid < 1000 or acct.pw_name in _SYSTEM_OK
        ) and acct.pw_shell in ("/usr/sbin/nologin", "/bin/false", "/bin/sync", "*")
        if acct.pw_uid == 0:
            is_system = False  # root is always inspected

        shadow_passwd = acct.pw_passwd  # '*' or 'x' usually

        # passwordless: empty password field allows direct login
        if shadow_passwd == "" and not is_system:
            status.passwordless.append(acct.pw_name)

        if shadow_passwd.startswith("!") or shadow_passwd.startswith("*!"):
            if not is_system:
                status.locked.append(acct.pw_name)

    if status.anomaly:
        log.warning("account anomalies: %s", status.describe())
    else:
        log.debug("%s", status.describe())

    return status
