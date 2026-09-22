"""Account related reactions.

The agent itself does not create/delete users; it reacts to anomalies:
unlocks a wrongly locked admin account and reports dangerous states.
Everything is logged to journald + log file.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from ..config import Config

log = logging.getLogger("sysadmin-agent.users-action")


def _run(cmd: list[str], dry_run: bool, label: str) -> bool:
    if dry_run:
        log.info("[dry-run] would execute (%s): %s", label, " ".join(cmd))
        return True
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("%s failed: %s", label, exc)
        return False
    if proc.returncode != 0:
        log.error("%s rc=%s: %s", label, proc.returncode, proc.stderr.strip())
        return False
    log.info("%s: ok", label)
    return True


def unlock_user(cfg: Config, username: str) -> bool:
    """Unlock a locked account (`usermod -U`)."""
    if not shutil.which("usermod"):
        log.error("usermod not available")
        return False
    return _run(["usermod", "-U", username], cfg.dry_run, f"unlock {username}")


def lock_user(cfg: Config, username: str) -> bool:
    """Lock an account (`usermod -L`)."""
    if not shutil.which("usermod"):
        log.error("usermod not available")
        return False
    return _run(["usermod", "-L", username], cfg.dry_run, f"lock {username}")


def expire_password(cfg: Config, username: str) -> bool:
    if not shutil.which("chage"):
        log.error("chage not available")
        return False
    return _run(["chage", "-E", "-1", username], cfg.dry_run,
                f"expire password {username}")
