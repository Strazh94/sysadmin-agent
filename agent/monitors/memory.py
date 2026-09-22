"""Memory / swap monitor.

Triggers a cleanup action when used RAM or swap crosses configured
thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import psutil

from ..config import Config

log = logging.getLogger("sysadmin-agent.memory")


@dataclass
class MemoryStatus:
    used_percent: float
    swap_percent: float
    total_gb: float
    available_gb: float

    @property
    def anomaly(self) -> bool:
        return self.over_memory or self.over_swap

    over_memory: bool = False
    over_swap: bool = False

    def describe(self) -> str:
        reasons = []
        if self.over_memory:
            reasons.append(f"RAM {self.used_percent:.1f}% used")
        if self.over_swap:
            reasons.append(f"swap {self.swap_percent:.1f}% used")
        return (
            "; ".join(reasons)
            or f"RAM ok ({self.used_percent:.1f}%, {self.available_gb:.1f} GiB free)"
        )


def check(cfg: Config) -> MemoryStatus | None:
    if not cfg.enabled("memory.enabled"):
        return None

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    mem_threshold = float(cfg.get("memory.used_percent_threshold", 90))
    swap_threshold = float(cfg.get("memory.swap_percent_threshold", 80))

    status = MemoryStatus(
        used_percent=float(vm.percent),
        swap_percent=float(swap.percent),
        total_gb=vm.total / 1024**3,
        available_gb=vm.available / 1024**3,
        over_memory=vm.percent >= mem_threshold,
        over_swap=swap.percent >= swap_threshold,
    )

    if status.anomaly:
        log.warning("anomaly detected: %s", status.describe())
    else:
        log.debug("%s", status.describe())

    return status
