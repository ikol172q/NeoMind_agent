"""Scheduler entry point.

Two modes:

    # 1) Daemon — start APScheduler with all registered jobs:
    python -m agent.finance.scheduler.runner

    # 2) One-shot — run a single job synchronously and exit:
    python -m agent.finance.scheduler.runner --run-once daily_market_pull

The daemon mode is meant to be supervised by launchd (macOS) or
systemd (Linux). It blocks the main thread; APScheduler manages its
own thread pool internally.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Any, Dict

from agent.finance.persistence import connect, ensure_schema
from agent.finance.scheduler.core import build_default_registry, run_job_once

logger = logging.getLogger(__name__)


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _run_daemon() -> None:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    ensure_schema()
    reg = build_default_registry()
    with connect() as conn:
        reg.upsert_to_db(conn)

    scheduler = BackgroundScheduler(timezone="UTC")

    def _wrap(name: str) -> Any:
        def _fn() -> None:
            run_job_once(name)
        _fn.__name__ = f"run_{name}"
        return _fn

    for name in reg.names():
        spec = reg.get(name)
        # Read user-tweaked cron from DB if present; else use default.
        with connect() as conn:
            row = conn.execute(
                "SELECT cron_expression, enabled FROM scheduler_jobs WHERE job_name = ?",
                (name,),
            ).fetchone()
        cron = (row["cron_expression"] if row else None) or spec["cron"]
        enabled = bool(row["enabled"]) if row else True

        if not enabled:
            logger.info("job %r disabled in DB — skipping", name)
            continue

        trigger = CronTrigger.from_crontab(cron, timezone="UTC")
        scheduler.add_job(
            _wrap(name),
            trigger=trigger,
            id=name,
            name=name,
            misfire_grace_time=3600,  # if we missed by < 1h, still run
            coalesce=True,            # collapse missed runs to one
            replace_existing=True,
        )
        logger.info("scheduled %r → cron(%s)", name, cron)

    scheduler.start()

    # Block until SIGINT / SIGTERM
    stopping = {"flag": False}

    def _stop(signum: int, _frame: Any) -> None:
        logger.info("received signal %d — shutting down", signum)
        stopping["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while not stopping["flag"]:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="neomind-scheduler",
        description="NeoMind fin data scheduler",
    )
    parser.add_argument(
        "--run-once",
        metavar="JOB_NAME",
        help="run a single registered job synchronously and exit",
    )
    parser.add_argument(
        "--list-jobs",
        action="store_true",
        help="list registered jobs and exit",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    _setup_logging(args.log_level)

    if args.list_jobs:
        reg = build_default_registry()
        for name in reg.names():
            spec = reg.get(name)
            print(f"{name:30s}  cron({spec['cron']})  {spec['description']}")
        return 0

    if args.run_once:
        result: Dict[str, Any] = run_job_once(args.run_once)
        if "error" in result:
            print(f"FAILED: {result['error']}", file=sys.stderr)
            return 1
        print(f"OK: {result}")
        return 0

    _run_daemon()
    return 0


if __name__ == "__main__":
    sys.exit(main())
