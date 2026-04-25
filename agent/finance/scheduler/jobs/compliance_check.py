"""Compliance check job — runs all three detectors in one pass.

Cron default: every 4 hours during US market hours weekdays. Cheap
(scans only the closed/intraday subset of tax_lots), idempotent at the
DB level, and the output is what the UI's "tax warnings" badges read.

Manual rerun:
    python -m agent.finance.scheduler.runner --run-once compliance_check
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from agent.finance.persistence import connect, ensure_schema
from agent.finance.persistence import dao

logger = logging.getLogger(__name__)


JOB_NAME = "compliance_check"
DEFAULT_CRON = "0 13,17,21 * * 1-5"   # 13:00, 17:00, 21:00 UTC = ~9/13/17 ET
DESCRIPTION = (
    "Run wash sale detector + PDT round-trip scanner + holding-period "
    "snapshot. Output lands in wash_sale_events / pdt_round_trips / "
    "holding_period_snapshots. Idempotent — re-runs collapse on UNIQUE "
    "constraints. Drives the UI tax-warning badges."
)


async def run() -> Dict[str, Any]:
    ensure_schema()
    # Lazy import — keep startup cheap if the job isn't being used.
    from agent.finance.compliance import (
        detect_wash_sales,
        compute_round_trips,
        snapshot_holding_periods,
    )

    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )

    summary: Dict[str, Any] = {"job": JOB_NAME}

    try:
        with connect() as conn:
            ws = detect_wash_sales(conn, detection_run_id=run_id)
            summary["wash_sale"] = ws
        with connect() as conn:
            pdt = compute_round_trips(conn, detection_run_id=run_id)
            summary["pdt"] = pdt
        with connect() as conn:
            hp = snapshot_holding_periods(conn, detection_run_id=run_id)
            summary["holding_period"] = hp

        rows_written = (
            ws["events_written"]
            + pdt["round_trips_written"]
            + hp["snapshots_written"]
        )
        with connect() as conn:
            dao.complete_analysis_run(
                conn, run_id, status="completed",
                rows_written=rows_written,
            )
        summary["run_id"] = run_id
        return summary

    except Exception as exc:  # noqa: BLE001
        logger.exception("compliance_check failed")
        with connect() as conn:
            dao.complete_analysis_run(
                conn, run_id, status="failed", error_message=str(exc),
            )
        summary["run_id"] = run_id
        summary["error"] = str(exc)
        return summary
