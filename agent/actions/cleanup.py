"""Cleanup actions: pagecache drop, /tmp wipe, log rotation, journal vacuum."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from ..config import Config

log = logging.getLogger("sysadmin-agent.cleanup")

_HAVE_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False


def _sh(cmd: list[str], dry_run: bool, label: str) -> bool:
    if dry_run:
        log.info("[dry-run] would execute (%s): %s", label, " ".join(cmd))
        return True
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("%s failed to start: %s", label, exc)
        return False
    if proc.returncode != 0:
        log.error("%s rc=%s: %s", label, proc.returncode, proc.stderr.strip())
        return False
    log.info("%s: ok", label)
    return True


# ----------------------------------------------------------------------
def memory_cleanup(cfg: Config) -> None:
    """Free RAM: drop pagecache and remove stale files from /tmp."""
    if not cfg.enabled("actions.memory_cleanup.enabled"):
        log.debug("memory cleanup disabled in config")
        return
    dry = cfg.dry_run

    if not _HAVE_ROOT and not dry:
        log.error("memory cleanup requires root (run as root or enable dry_run)")
        return

    if cfg.get("actions.memory_cleanup.drop_caches", True):
        if dry:
            log.info("[dry-run] would: sync && echo 3 > /proc/sys/vm/drop_caches")
        else:
            try:
                subprocess.run(["sync"], check=False, timeout=60)
                Path("/proc/sys/vm/drop_caches").write_text("3\n", encoding="ascii")
                log.info("drop_caches executed")
            except (OSError, subprocess.SubprocessError) as exc:
                log.error("drop_caches failed: %s", exc)

    if cfg.get("actions.memory_cleanup.clean_tmp", True):
        max_age_days = int(cfg.get("actions.memory_cleanup.tmp_max_age_days", 7))
        _clean_old_files(Path("/tmp"), max_age_days, dry)


def disk_cleanup(cfg: Config) -> None:
    """Free disk space: vacuum systemd journal and remove old rotated logs."""
    if not cfg.enabled("actions.disk_cleanup.enabled"):
        log.debug("disk cleanup disabled in config")
        return
    dry = cfg.dry_run

    if not _HAVE_ROOT and not dry:
        log.error("disk cleanup requires root (run as root or enable dry_run)")
        return

    vacuum_mb = int(cfg.get("actions.disk_cleanup.vacuum_journal_mb", 200))
    _sh(["journalctl", "--vacuum-size", f"{vacuum_mb}M"], dry, "journal vacuum")

    max_age_days = int(cfg.get("actions.disk_cleanup.log_max_age_days", 14))
    _clean_old_files(Path("/var/log"), max_age_days, dry, patterns=("*.gz", "*.1", "*.2"))


def _clean_old_files(
    root: Path, max_age_days: int, dry_run: bool, patterns: tuple[str, ...] = ("*",)
) -> None:
    """Delete regular files in `root` older than max_age_days.

    Never recurses (so /tmp/<dir> of running services stays intact).
    """
    if not root.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    freed = 0
    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                stat = path.stat()
                if stat.st_mtime >= cutoff:
                    continue
                if dry_run:
                    log.info("[dry-run] would remove %s (%.1f MB, old)",
                             path, stat.st_size / 1024**2)
                    continue
                path.unlink()
                removed += 1
                freed += stat.st_size
            except OSError as exc:
                log.debug("cannot remove %s: %s", path, exc)
    if removed:
        log.info("cleanup: removed %d files, freed %.1f MB in %s",
                 removed, freed / 1024**2, root)
