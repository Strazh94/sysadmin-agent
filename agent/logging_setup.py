"""Logging setup: journald (via python syslog handler) + plain log file.

systemd unit sets ``SyslogIdentifier=sysadmin-agent``, so everything sent to
syslog lands in ``journalctl -u sysadmin-agent``. A copy is also appended to
``/var/log/sysadmin-agent.log`` (path overridable by env var).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOG_FILE = os.environ.get(
    "SYSADMIN_AGENT_LOG", "/var/log/sysadmin-agent.log"
)
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(FORMAT)

    # --- stdout: captured by journald when run under systemd ---
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    # --- syslog: explicit journald routing for non-journal setups ---
    try:
        syslog = logging.handlers.SysLogHandler(address="/dev/log")
        syslog.setFormatter(
            logging.Formatter("sysadmin-agent[%(process)d]: %(levelname)s %(message)s")
        )
        root.addHandler(syslog)
    except (OSError, AttributeError):
        # /dev/log missing or no AF_UNIX (non-Linux) -> stdout only
        pass

    # --- file ---
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        # /var/log not writable (dev machine) -> fall back to temp dir
        import tempfile

        fallback = Path(tempfile.gettempdir()) / "sysadmin-agent.log"
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                fallback, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            root.warning("cannot open log file %s: %s", fallback, exc)

    return logging.getLogger("sysadmin-agent")
