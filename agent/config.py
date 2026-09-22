"""Configuration loader for sysadmin-agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATHS = (
    Path("/etc/sysadmin-agent/config.yaml"),
    Path(__file__).resolve().parent.parent / "config" / "config.yaml",
)


class Config:
    """Thin wrapper around a YAML dict with dotted-path access."""

    def __init__(self, data: dict[str, Any], source: Path):
        self.data = data
        self.source = source

    # ------------------------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        """Fetch a value by dotted path, e.g. ``memory.used_percent_threshold``."""
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def enabled(self, path: str) -> bool:
        return bool(self.get(path, default=False))

    # ------------------------------------------------------------------
    @property
    def dry_run(self) -> bool:
        return bool(self.get("dry_run", default=True))

    @property
    def interval_sec(self) -> int:
        try:
            return max(5, int(self.get("interval_sec", default=30)))
        except (TypeError, ValueError):
            return 30

    @property
    def whitelist(self) -> list[str]:
        raw = self.get("whitelist", default=[]) or []
        return [str(x).strip() for x in raw if str(x).strip()]


def load_config(explicit: str | os.PathLike[str] | None = None) -> Config:
    """Load YAML config.

    Search order: explicit argument -> $SYSADMIN_AGENT_CONFIG -> known paths.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("SYSADMIN_AGENT_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(DEFAULT_CONFIG_PATHS)

    for path in candidates:
        try:
            if path.is_file():
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                if not isinstance(data, dict):
                    raise ValueError(f"config root must be a mapping: {path}")
                return Config(data, path)
        except yaml.YAMLError as exc:
            raise SystemExit(f"invalid YAML in {path}: {exc}") from exc

    raise SystemExit(
        "config file not found, searched:\n  " + "\n  ".join(str(p) for p in candidates)
    )
