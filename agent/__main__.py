"""sysadmin-agent entry point.

Usage:
    python -m agent [--config PATH] [--once] [--verbose]

Run as a foreground process; systemd unit wraps it as a service.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from . import __version__
from .actions import cleanup, firewall
from .config import load_config
from .logging_setup import setup_logging
from .monitors import disk, gpu, memory, ssh_log, users

log = logging.getLogger("sysadmin-agent")

_shutdown = False


def _handle_signal(signum: int, _frame) -> None:  # type: ignore[no-untyped-def]
    global _shutdown
    log.info("received signal %s, shutting down after current cycle", signum)
    _shutdown = True


def run_cycle(cfg) -> None:  # type: ignore[no-untyped-def]
    """One monitoring pass: check -> react."""
    # ---- checks -----------------------------------------------------
    mem_status = memory.check(cfg)
    disk_status = disk.check(cfg)
    gpu_statuses = gpu.check(cfg)
    ssh_status = ssh_log.check(cfg)
    user_status = users.check(cfg)

    # ---- reactions --------------------------------------------------
    if mem_status is not None and mem_status.anomaly:
        log.warning("ACTION: RAM anomaly -> running memory cleanup")
        cleanup.memory_cleanup(cfg)

    if disk_status is not None and disk_status.anomaly:
        log.warning("ACTION: low disk space -> running disk cleanup")
        cleanup.disk_cleanup(cfg)

    if gpu_statuses:
        hot = [g for g in gpu_statuses if g.anomaly]
        if hot:
            # GPU pressure: only logging for now - killing GPU jobs is too
            # destructive for an automated agent.
            log.warning("ACTION: GPU anomaly (%s) - alert raised, no auto-kill",
                        ", ".join(g.describe() for g in hot))

    if ssh_status is not None:
        candidates = ssh_log.ban_candidates(ssh_status, cfg.whitelist)
        if candidates:
            ttl = int(cfg.get("ssh_log.ban_ttl_sec", 3600))
            log.warning("ACTION: brute-force detected -> banning %s", candidates)
            firewall.ban_ips(cfg, candidates, ttl_sec=ttl)

    if user_status is not None and user_status.anomaly:
        log.warning("ALERT: %s", user_status.describe())

    # heartbeat with a compact summary
    parts = []
    if mem_status:
        parts.append(f"ram={mem_status.used_percent:.0f}%")
    if disk_status:
        low = disk_status.low_mounts
        parts.append(f"disk_low={len(low)}" if low else "disk=ok")
    if gpu_statuses:
        parts.append(f"gpu={len(gpu_statuses)}")
    if ssh_status:
        parts.append(f"ssh_events={len(ssh_status.events)}")
    parts.append("mode=" + ("dry-run" if cfg.dry_run else "LIVE"))
    log.info("cycle done: %s", " ".join(parts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sysadmin-agent",
        description="Monitor server vitals and react to anomalies "
                    "(cleanup, iptables bans) instead of just alerting.",
    )
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit (for cron/debug)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="debug logging")
    parser.add_argument("--version", action="version",
                        version=f"sysadmin-agent {__version__}")
    args = parser.parse_args(argv)

    setup_logging(verbose=args.verbose)
    log.info("sysadmin-agent %s starting", __version__)

    try:
        cfg = load_config(args.config)
    except SystemExit as exc:
        log.error("%s", exc)
        return 2

    log.info("config: %s (dry_run=%s, interval=%ss)",
             cfg.source, cfg.dry_run, cfg.interval_sec)
    if not cfg.dry_run:
        log.warning("LIVE MODE: destructive actions (drop_caches, iptables) enabled")

    if args.once:
        run_cycle(cfg)
        return 0

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not _shutdown:
        started = time.monotonic()
        try:
            run_cycle(cfg)
        except Exception:  # noqa: BLE001 - daemon must never die on one bad cycle
            log.exception("cycle crashed, will retry")
        elapsed = time.monotonic() - started
        sleep_for = max(1.0, cfg.interval_sec - elapsed)
        # sleep in small slices so SIGTERM is handled promptly
        deadline = time.monotonic() + sleep_for
        while not _shutdown and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    log.info("sysadmin-agent stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
