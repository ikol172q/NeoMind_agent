"""Daily thesis health check.

For every active investment_theses row, verify:
  1. supporting_fact_ids — all still present in stock_anchored_facts AND
     not flagged stale (filing_date > 18mo old) NOR requires_reextract.
  2. supporting_signal_types — at least one signal_event of any of these
     types fired in the last 30 days for the thesis's ticker.

If EITHER check fails → mark thesis status='requires_review' and update
last_health_check_at. Watchlist tab + chain panel surface this; user
gets nudged to re-examine the thesis.

Per plan §5 Pillar 4 + §2 philosophy: dashboard NEVER auto-invalidates
a thesis. It can only flag for review. User decides whether the thesis
is genuinely broken or the supporting signals just went temporarily
quiet.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from agent.finance.persistence import connect, dao

logger = logging.getLogger(__name__)

JOB_NAME = "thesis_health_check"
DEFAULT_CRON = "30 6 * * *"   # 06:30 daily, after learning_daily (06:00)

DESCRIPTION = (
    "Daily check of every active investment_thesis: do supporting_fact_ids "
    "still exist + not stale, did supporting_signal_types fire in last 30d? "
    "Flag stale theses for user review."
)

_SIGNAL_LOOKBACK_DAYS = 30
_FACT_STALE_DAYS = 18 * 30   # 18 months (to mirror is_stale semantic in plan §5)


async def run() -> Dict[str, Any]:
    """Scheduler entrypoint. Mirrors news_pull / learning_daily shape."""
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )
    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        result = _do_check()
        summary.update({"status": "completed", **result})
        logger.info(
            "[thesis_health_check] checked=%d ok=%d flagged=%d already_flagged=%d",
            result["n_checked"], result["n_ok"], result["n_flagged"],
            result["n_already_flagged"],
        )
    except Exception as exc:
        logger.exception("thesis_health_check failed")
        summary.update({"status": "failed", "error": str(exc)})

    with connect() as conn:
        dao.finish_analysis_run(
            conn, run_id=run_id,
            status=summary["status"],
            summary_json=summary,
        )
    return summary


def _do_check() -> Dict[str, Any]:
    """Inspect every active thesis. Mark requires_review if checks fail.
    Returns counts for the run summary."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    sig_cutoff = (now - timedelta(days=_SIGNAL_LOOKBACK_DAYS)).isoformat()

    n_checked = 0
    n_ok = 0
    n_flagged = 0      # newly flagged in this run
    n_already_flagged = 0

    with connect() as conn:
        rows = conn.execute(
            "SELECT thesis_id, ticker, supporting_fact_ids, "
            "       supporting_signal_types, status "
            "FROM investment_theses WHERE status IN ('active','requires_review')"
        ).fetchall()

        for row in rows:
            n_checked += 1
            thesis_id = row["thesis_id"]
            ticker = row["ticker"]
            try:
                fact_ids: List[int] = json.loads(row["supporting_fact_ids"] or "[]")
                signal_types: List[str] = json.loads(row["supporting_signal_types"] or "[]")
            except json.JSONDecodeError:
                fact_ids, signal_types = [], []

            failures = []

            # Check 1: facts still alive + fresh
            if fact_ids:
                placeholders = ",".join("?" * len(fact_ids))
                cur = conn.execute(
                    f"SELECT id, source_filing_date, requires_reextract "
                    f"FROM stock_anchored_facts WHERE id IN ({placeholders})",
                    fact_ids,
                )
                found_facts = {r["id"]: r for r in cur.fetchall()}
                missing_facts = [fid for fid in fact_ids if fid not in found_facts]
                if missing_facts:
                    failures.append(f"{len(missing_facts)} supporting fact(s) deleted")
                # is_stale check: filing_date > 18mo old
                stale_facts = []
                for fid, fact_row in found_facts.items():
                    fd = fact_row["source_filing_date"]
                    if fd:
                        try:
                            fd_dt = datetime.fromisoformat(fd.replace("Z","+00:00"))
                            if (now - fd_dt).days > _FACT_STALE_DAYS:
                                stale_facts.append(fid)
                        except Exception:
                            pass
                    if fact_row["requires_reextract"]:
                        stale_facts.append(fid)
                if stale_facts:
                    failures.append(f"{len(stale_facts)} fact(s) stale or marked for re-extract")

            # Check 2: any signal in supporting_signal_types in last 30d
            if signal_types:
                sig_placeholders = ",".join("?" * len(signal_types))
                cur = conn.execute(
                    f"SELECT COUNT(*) AS n FROM signal_events "
                    f"WHERE ticker = ? AND signal_type IN ({sig_placeholders}) "
                    f"  AND detected_at >= ?",
                    [ticker, *signal_types, sig_cutoff],
                )
                n_recent = cur.fetchone()["n"]
                if n_recent == 0:
                    failures.append(
                        f"no supporting_signal_types fired in last "
                        f"{_SIGNAL_LOOKBACK_DAYS}d ({signal_types})"
                    )

            # Apply verdict — flag for review if any failure, otherwise
            # restore to 'active' if previously flagged but now healthy
            new_status = "requires_review" if failures else "active"
            conn.execute(
                "UPDATE investment_theses "
                "SET status = ?, last_health_check_at = ? "
                "WHERE thesis_id = ?",
                (new_status, now_iso, thesis_id),
            )
            if failures:
                if row["status"] == "requires_review":
                    n_already_flagged += 1
                else:
                    n_flagged += 1
                    logger.info(
                        "[thesis_health_check] flagged %s (%s) — %s",
                        thesis_id[:8], ticker, "; ".join(failures),
                    )
            else:
                n_ok += 1

    return {
        "n_checked":         n_checked,
        "n_ok":              n_ok,
        "n_flagged":         n_flagged,
        "n_already_flagged": n_already_flagged,
        "checked_at":        now_iso,
    }
