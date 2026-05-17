"""Quarterly auto-refresh of stock_anchored_facts.

Without this, 10-K-derived relations (competitor / customer / supplier /
risk / segment / business_summary) silently rot from the day a ticker
files its next 10-K until the user manually clicks "↻ re-extract from
SEC" on each ticker's drawer.

US companies file 10-K annually (some 10-Q semi-annually). Per plan §5
Pillar 2 the staleness threshold is 18 months, but that's the
absolute-rot ceiling — we want the data to be fresher than that.

This job:
  1. Lists every ticker in user_watchlist.
  2. For each ticker, checks the newest `source_filing_date` across
     its stock_anchored_facts rows.
  3. If newest filing > 90 days old (rough quarterly threshold), kicks
     off `_run_pipeline` for each fact_type defined in
     anchored_research._PIPELINES.
  4. Gracefully skips tickers without an EDGAR 10-K (e.g. ADRs,
     non-US listings).

Cost per ticker per fact_type: ~$0.005 + 1 SEC HTTP. Six fact_types ×
~50 tickers = ~$1.50 per run. Runs weekly (not daily) since SEC filing
cadence is at most monthly per ticker.

Cron: 0 4 * * 0 (04:00 UTC Sunday — quiet hours, no overlap with
hourly signal_hourly or daily whale_daily).

Manual rerun:
    python -m agent.finance.scheduler.runner --run-once anchored_quarterly
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)


JOB_NAME = "anchored_quarterly"
DEFAULT_CRON = "0 4 * * 0"   # 04:00 UTC Sunday
DESCRIPTION = (
    "Weekly: for every watchlist ticker whose newest 10-K-anchored fact "
    "is > 90 days old, re-run _run_pipeline for every fact_type so the "
    "graph reflects the latest SEC filing. Closes the auto-refresh gap "
    "that previously left relations stale until manual re-extract."
)


# Tickers whose 10-K source_filing_date is older than this trigger a
# refresh. 90 days roughly matches quarterly cadence — anything fresher
# is presumed up-to-date already.
_REFRESH_THRESHOLD_DAYS = 90


async def run() -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )
    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        summary.update(_do_refresh())
        summary["status"] = "completed"
    except Exception as exc:
        logger.exception("anchored_quarterly failed")
        summary.update({"status": "failed", "error": str(exc)})
    finally:
        with connect() as conn:
            dao.finish_analysis_run(
                conn, run_id=run_id,
                status=summary["status"], summary_json=summary,
            )
    return summary


def _do_refresh() -> Dict[str, Any]:
    """List candidates and re-extract each via the existing pipeline."""
    from agent.finance.anchored_research import _PIPELINES, _run_pipeline

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=_REFRESH_THRESHOLD_DAYS)
    cutoff_iso = cutoff_dt.isoformat()

    with connect() as conn:
        tickers = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM user_watchlist ORDER BY ticker"
        ).fetchall()]
        # Newest filing date per ticker (or NULL = never extracted)
        rows = conn.execute(
            "SELECT ticker, MAX(source_filing_date) AS newest_filing "
            "FROM stock_anchored_facts "
            "WHERE ticker IN ({}) "
            "GROUP BY ticker".format(",".join("?" * len(tickers)) or "''"),
            tuple(tickers),
        ).fetchall() if tickers else []
        # Tickers with ANY fact flagged requires_reextract=1 by the
        # thesis_health_check job. These need refresh independent of
        # the 90-day filing-date threshold (e.g. flagged because a
        # downstream thesis broke and the user needs current data).
        flagged_rows = conn.execute(
            "SELECT DISTINCT ticker FROM stock_anchored_facts "
            "WHERE requires_reextract = 1 "
            "  AND ticker IN ({})".format(
                ",".join("?" * len(tickers)) or "''"),
            tuple(tickers),
        ).fetchall() if tickers else []
        flagged_set = {r["ticker"] for r in flagged_rows}
    by_ticker = {r["ticker"]: r["newest_filing"] for r in rows}

    stale_tickers: List[str] = []
    for tk in tickers:
        newest = by_ticker.get(tk)
        if (newest is None
                or newest < cutoff_iso[:10]
                or tk in flagged_set):
            # never extracted / filing > 90d / explicitly flagged
            stale_tickers.append(tk)

    logger.info(
        "[anchored_quarterly] %d watchlist tickers, %d stale (>%dd old)",
        len(tickers), len(stale_tickers), _REFRESH_THRESHOLD_DAYS,
    )

    per_ticker_results: List[Dict[str, Any]] = []
    n_refreshed = 0
    n_skipped = 0
    n_errored = 0

    for tk in stale_tickers:
        per_type: Dict[str, Any] = {}
        ticker_ok = False
        for fact_type in _PIPELINES.keys():
            try:
                res = _run_pipeline(tk, fact_type)
                per_type[fact_type] = {
                    "n_persisted": res.get("n_persisted", 0),
                    "filing_date": res.get("source_filing_date"),
                }
                ticker_ok = True
            except Exception as exc:
                msg = str(exc)
                per_type[fact_type] = {"error": msg[:120]}
                # 10-K not found is a "skip" not "error" — many ADRs /
                # non-US listings legitimately don't have EDGAR filings.
                if "no 10-K filing found" in msg or "404" in msg:
                    pass
                else:
                    logger.warning(
                        "anchored_quarterly: %s/%s failed: %s",
                        tk, fact_type, msg[:160],
                    )
        per_ticker_results.append({"ticker": tk, "by_type": per_type})
        if ticker_ok:
            n_refreshed += 1
        else:
            # All fact_types failed → either no EDGAR filing (skip) or
            # systemic error (count). Distinguish by inspecting messages.
            all_404 = all(
                isinstance(v, dict) and "error" in v
                and ("no 10-K filing found" in v["error"] or "404" in v["error"])
                for v in per_type.values()
            )
            if all_404:
                n_skipped += 1
            else:
                n_errored += 1

    return {
        "n_watchlist":     len(tickers),
        "n_stale":         len(stale_tickers),
        "n_refreshed":     n_refreshed,
        "n_skipped_no_edgar": n_skipped,
        "n_errored":       n_errored,
        "n_flagged_reextract": len(flagged_set),
        "per_ticker":      per_ticker_results,
        "threshold_days":  _REFRESH_THRESHOLD_DAYS,
    }
