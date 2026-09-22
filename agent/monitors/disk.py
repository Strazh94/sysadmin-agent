"""Free disk space monitor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import psutil

from ..config import Config

log = logging.getLogger("sysadmin-agent.disk")


@dataclass
class MountStatus:
    mount: str
    total_gb: float
    free_gb: float
    free_percent: float
    critical: bool
    low: bool


@dataclass
class DiskStatus:
    threshold: float
    mounts: list[MountStatus] = field(default_factory=list)

    @property
    def low_mounts(self) -> list[MountStatus]:
        return [m for m in self.mounts if m.low]

    @property
    def anomaly(self) -> bool:
        return bool(self.low_mounts)

    def describe(self) -> str:
        if not self.anomaly:
            return f"disk ok (threshold {self.threshold:.0f}% free)"
        parts = [
            f"{m.mount}: {m.free_percent:.1f}% free ({m.free_gb:.1f} GiB)"
            + (" [critical]" if m.critical else "")
            for m in self.low_mounts
        ]
        return "low free space -> " + "; ".join(parts)


def _is_mount(path: str, mounts: set[str]) -> bool:
    """True when `path` itself is a mount point (or root)."""
    p = path.rstrip("/") or "/"
    return p in mounts or p == "/"


def check(cfg: Config) -> DiskStatus | None:
    if not cfg.enabled("disk.enabled"):
        return None

    threshold = float(cfg.get("disk.free_percent_threshold", 10))
    critical_paths = [str(p) for p in (cfg.get("disk.critical_paths", ["/"]) or [])]

    seen: set[str] = set()
    mounts: list[MountStatus] = []

    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError):
            continue
        # skip tiny pseudo filesystems (snap, docker overlays, ...)
        if usage.total < 100 * 1024**2:
            continue
        seen.add(part.mountpoint)
        free_percent = 100.0 - usage.percent
        critical = _is_mount(part.mountpoint, set(critical_paths))
        # critical mounts always use the threshold, others only if explicitly listed
        relevant = critical or part.mountpoint in critical_paths
        mounts.append(
            MountStatus(
                mount=part.mountpoint,
                total_gb=usage.total / 1024**3,
                free_gb=usage.free / 1024**3,
                free_percent=free_percent,
                critical=critical,
                low=relevant and free_percent < threshold,
            )
        )

    status = DiskStatus(threshold=threshold, mounts=mounts)

    if status.anomaly:
        log.warning("anomaly detected: %s", status.describe())
    else:
        log.debug("%s", status.describe())

    return status
