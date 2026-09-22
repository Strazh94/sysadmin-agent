"""NVIDIA GPU monitor via `nvidia-smi`.

If the binary is missing (no NVIDIA driver / not Linux) the monitor is
disabled with a single warning.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

from ..config import Config

log = logging.getLogger("sysadmin-agent.gpu")

QUERY = (
    "utilization.gpu,memory.used,memory.total,"
    "utilization.memory,temperature.gpu"
)


@dataclass
class GpuStatus:
    index: int
    util_percent: int
    mem_used_mb: int
    mem_total_mb: int
    mem_percent: float
    temperature: int
    over_util: bool
    over_mem: bool

    @property
    def anomaly(self) -> bool:
        return self.over_util or self.over_mem

    def describe(self) -> str:
        base = (
            f"GPU{self.index}: util {self.util_percent}%, "
            f"mem {self.mem_used_mb}/{self.mem_total_mb} MB, {self.temperature}C"
        )
        if self.anomaly:
            return base + " [HIGH]"
        return base


def nvidia_smi_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def check(cfg: Config) -> list[GpuStatus] | None:
    if not cfg.enabled("gpu.enabled"):
        return None
    if not nvidia_smi_available():
        log.warning("nvidia-smi not found - GPU monitor disabled")
        # disable for the rest of the run
        cfg.data.setdefault("gpu", {})["enabled"] = False
        return None

    util_threshold = float(cfg.get("gpu.used_percent_threshold", 90))
    mem_threshold = float(cfg.get("gpu.mem_used_percent_threshold", 90))

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={QUERY}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("nvidia-smi failed: %s", exc)
        return None

    if proc.returncode != 0:
        log.error("nvidia-smi rc=%s: %s", proc.returncode, proc.stderr.strip())
        return None

    statuses: list[GpuStatus] = []
    for idx, line in enumerate(proc.stdout.splitlines()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            util = int(float(parts[0]))
            mem_used = int(float(parts[1]))
            mem_total = int(float(parts[2]))
            temperature = int(float(parts[4]))
        except ValueError:
            log.debug("unparsable nvidia-smi line: %r", line)
            continue
        mem_percent = (mem_used / mem_total * 100.0) if mem_total else 0.0
        status = GpuStatus(
            index=idx,
            util_percent=util,
            mem_used_mb=mem_used,
            mem_total_mb=mem_total,
            mem_percent=mem_percent,
            temperature=temperature,
            over_util=util >= util_threshold,
            over_mem=mem_percent >= mem_threshold,
        )
        if status.anomaly:
            log.warning("anomaly detected: %s", status.describe())
        else:
            log.debug("%s", status.describe())
        statuses.append(status)

    return statuses
