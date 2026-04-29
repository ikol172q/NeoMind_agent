"""FastAPI routes for the regime pipeline.

Mounted in dashboard_server.py:

    from agent.finance.regime.api import router as regime_router
    app.include_router(regime_router)

Endpoints:

    GET  /api/regime/today            — today's fingerprint (compute if missing)
    GET  /api/regime/at?date=YYYY-MM-DD — historical fingerprint (compute if missing)
    GET  /api/regime/history           — list recent fingerprints
    POST /api/regime/ingest            — trigger one-shot yfinance pull
    POST /api/regime/backfill          — one-shot historical backfill
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regime", tags=["fin-regime"])


@router.get("/today")
def get_today() -> Dict[str, Any]:
    """Today's fingerprint, computed on demand from raw_market_data."""
    from agent.finance.regime import fingerprint_for_date
    today = _date.today().isoformat()
    fp = fingerprint_for_date(today)
    return fp


@router.get("/at")
def get_at(
    date: str = Query(..., description="YYYY-MM-DD UTC"),
    recompute: bool = Query(False, description="Force recompute (ignore cache)"),
) -> Dict[str, Any]:
    """Fingerprint for a specific date.  Computes on demand if missing."""
    from agent.finance.regime import fingerprint_for_date
    try:
        fp = fingerprint_for_date(date, recompute=recompute)
    except Exception as exc:
        logger.exception("fingerprint compute failed")
        raise HTTPException(500, f"fingerprint compute failed: {exc}")
    return fp


@router.get("/history")
def get_history(
    limit: int = Query(120, ge=1, le=500),
    since: Optional[str] = Query(None, description="YYYY-MM-DD UTC inclusive"),
) -> Dict[str, Any]:
    """Recent fingerprints, newest first.  Used by the k-NN UI / sparkline."""
    from agent.finance.regime.store import list_fingerprints
    rows = list_fingerprints(limit=limit, since=since)
    return {"count": len(rows), "fingerprints": rows}


@router.post("/ingest")
def post_ingest(
    lookback_days: int = Query(5, ge=1, le=30),
) -> Dict[str, Any]:
    """Pull last N days of yfinance data for the 3-tier watchlist.
    Idempotent — re-runs replace existing rows."""
    from agent.finance.regime.ingest import ingest_yfinance_daily
    try:
        result = ingest_yfinance_daily(lookback_days=lookback_days)
    except Exception as exc:
        logger.exception("yfinance ingest failed")
        raise HTTPException(502, f"yfinance ingest failed: {exc}")
    return result


@router.post("/backfill")
def post_backfill(
    period: str = Query("1y", description="yfinance period: '1mo'/'3mo'/'6mo'/'1y'/'2y'/'5y'/'max'"),
    compute_fingerprints: bool = Query(True, description="Also compute fingerprints for every trading day"),
) -> Dict[str, Any]:
    """One-shot historical backfill.  Pulls bulk yfinance data for the
    full 3-tier watchlist, then optionally computes fingerprints for
    each trading day in the window."""
    from agent.finance.regime.ingest import backfill_history
    from agent.finance.regime.fingerprint import backfill_fingerprints
    from datetime import timedelta

    try:
        ingest_result = backfill_history(period=period)
    except Exception as exc:
        logger.exception("backfill ingest failed")
        raise HTTPException(502, f"backfill ingest failed: {exc}")

    fp_result: Dict[str, Any] = {"skipped": True}
    if compute_fingerprints:
        period_to_days = {
            "1mo": 31, "3mo": 92, "6mo": 183,
            "1y": 365, "2y": 730, "5y": 1826, "max": 3650,
        }
        d = period_to_days.get(period, 365)
        since = (_date.today() - timedelta(days=d)).isoformat()
        try:
            fp_result = backfill_fingerprints(since=since, skip_existing=True)
        except Exception as exc:
            logger.exception("fingerprint backfill failed")
            fp_result = {"error": str(exc)}

    return {"ingest": ingest_result, "fingerprints": fp_result}
