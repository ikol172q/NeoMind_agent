"""Daily earnings calendar scanner — Phase 3.

For every Core + Adjacent ticker in user_watchlist:
  1. Fetch yfinance calendar (next earnings date + EPS estimates)
  2. If next earnings within 14 days → emit signal_event of type
     'earnings_upcoming' with severity by proximity:
       ≤ 3 days  → high
       ≤ 7 days  → med
       ≤ 14 days → low
  3. Backfill earnings_history table from yfinance.earnings_history
     so the drawer chain panel can show beat/miss bars without hitting
     yfinance per render.

Per plan §5 Pillar 3 (information freshness) + §7 Phase 3.
Earnings is the single highest-signal event type for retail —
missing one means missing a 5-15% same-day move.

Idempotency: re-running on the same day for the same ticker won't
double-emit. We check signal_events for an existing 'earnings_upcoming'
emission within the last 20 hours for this ticker before inserting.
Earnings dates can shift, so a 20h window catches "company moved
earnings from Tue to Wed" and re-emits if the new date triggers.

Cost: yfinance is free + cached aggressively in their lib. ~9 Core
tickers + N Adjacent = ~30-50 yfinance calls = <60s total. Skipped
on weekends (US market closed, no fresh data).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent.finance.persistence import connect, dao, ensure_schema

logger = logging.getLogger(__name__)

JOB_NAME = "earnings_calendar"
DEFAULT_CRON = "10 7 * * 1-5"   # 07:10 weekdays (after market_data_pull)

DESCRIPTION = (
    "Daily yfinance fetch of next-earnings + earnings history for "
    "every Core + Adjacent ticker. Emits earnings_upcoming signal_event "
    "when within 14d. Backfills earnings_history table."
)

# Severity thresholds in days-until-earnings
_SEVERITY = [
    (3,  "high"),
    (7,  "med"),
    (14, "low"),
]
_DEDUP_WINDOW_HOURS = 20


async def run() -> Dict[str, Any]:
    """Scheduler entrypoint."""
    with connect() as conn:
        run_id = dao.start_analysis_run(
            conn, job_name=JOB_NAME, run_type="scheduled",
        )
    summary: Dict[str, Any] = {"run_id": run_id, "status": "running"}
    try:
        result = _do_scan()
        summary.update({"status": "completed", **result})
        logger.info(
            "[earnings_calendar] checked=%d emitted=%d skipped_dup=%d "
            "history_rows=%d errors=%d",
            result["n_tickers"], result["n_emitted"], result["n_skipped"],
            result["n_history_rows"], result["n_errors"],
        )
    except Exception as exc:
        logger.exception("earnings_calendar failed")
        summary.update({"status": "failed", "error": str(exc)})

    with connect() as conn:
        dao.finish_analysis_run(
            conn, run_id=run_id,
            status=summary["status"],
            summary_json=summary,
        )
    return summary


def _do_scan() -> Dict[str, Any]:
    """Iterate Core+Adjacent watchlist, fetch earnings, emit signals."""
    ensure_schema()
    now = datetime.now(timezone.utc)
    today = now.date()
    dedup_cutoff = (now - timedelta(hours=_DEDUP_WINDOW_HOURS)).isoformat()

    # Get tickers to scan: Core + Adjacent (skip Watching — too noisy)
    with connect() as conn:
        rows = conn.execute(
            "SELECT ticker FROM user_watchlist "
            "WHERE tier IN ('core','adjacent') ORDER BY tier, ticker"
        ).fetchall()
        tickers = [r["ticker"] for r in rows]

    n_emitted = 0
    n_skipped = 0
    n_errors = 0
    n_history_rows = 0
    emitted_examples: List[str] = []

    for ticker in tickers:
        try:
            cal = _fetch_calendar(ticker)
            if cal:
                next_date, eps_est, days_until, severity = cal
                # Idempotency: skip if we already emitted for THIS earnings_date
                # within the dedup window.
                if _already_emitted(ticker, next_date, dedup_cutoff):
                    n_skipped += 1
                else:
                    _emit_earnings_event(
                        ticker=ticker,
                        next_date=next_date,
                        eps_est=eps_est,
                        days_until=days_until,
                        severity=severity,
                        now=now,
                    )
                    n_emitted += 1
                    emitted_examples.append(f"{ticker}@{next_date}({days_until}d,{severity})")

            # Always try to backfill earnings_history (cheap if already cached)
            n_history_rows += _backfill_earnings_history(ticker, now)
        except Exception as exc:
            n_errors += 1
            logger.warning("earnings_calendar %s: %s", ticker, exc)

    return {
        "n_tickers":       len(tickers),
        "n_emitted":       n_emitted,
        "n_skipped":       n_skipped,
        "n_errors":        n_errors,
        "n_history_rows":  n_history_rows,
        "emitted_examples": emitted_examples[:10],
        "scanned_at":      now.isoformat(),
    }


def _fetch_calendar(ticker: str):
    """Returns (next_date, eps_est, days_until, severity) or None.

    Only returns for earnings within 14 days. yfinance returns calendar
    dict; we extract Earnings Date + Earnings Average."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    cal = t.calendar
    if not cal:
        return None
    earnings_dates = cal.get("Earnings Date") or []
    if not earnings_dates:
        return None
    next_d = earnings_dates[0] if isinstance(earnings_dates, list) else earnings_dates
    if hasattr(next_d, "date"):
        next_d = next_d.date()
    if not isinstance(next_d, date):
        return None
    today = date.today()
    days_until = (next_d - today).days
    if days_until < 0 or days_until > 14:
        return None
    eps_est = cal.get("Earnings Average")
    severity = "low"
    for thresh, sev in _SEVERITY:
        if days_until <= thresh:
            severity = sev
            break
    return next_d.isoformat(), eps_est, days_until, severity


def _already_emitted(ticker: str, next_date_iso: str, dedup_cutoff: str) -> bool:
    """Check if we emitted earnings_upcoming for this ticker+date in last 20h."""
    with connect() as conn:
        cur = conn.execute(
            "SELECT event_id FROM signal_events "
            "WHERE ticker = ? AND signal_type = 'earnings_upcoming' "
            "  AND detected_at >= ? "
            "  AND body_json LIKE ? "
            "LIMIT 1",
            (ticker, dedup_cutoff, f'%"earnings_date": "{next_date_iso}"%'),
        )
        return cur.fetchone() is not None


def _emit_earnings_event(
    *, ticker: str, next_date: str, eps_est: Optional[float],
    days_until: int, severity: str, now: datetime,
) -> None:
    body = {
        "earnings_date":  next_date,
        "days_until":     days_until,
        "eps_estimate":   eps_est,
    }
    title = f"{ticker} 业绩公告 in {days_until}d ({next_date})"
    if eps_est is not None:
        title += f" · EPS est ${eps_est:.2f}"
    with connect() as conn:
        conn.execute(
            "INSERT INTO signal_events "
            "(event_id, scanner_name, ticker, signal_type, severity, "
            " title, body_json, source_url, detected_at) "
            "VALUES (?, 'earnings_calendar', ?, 'earnings_upcoming', ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), ticker, severity, title,
             json.dumps(body), "yfinance:calendar", now.isoformat()),
        )


def _backfill_earnings_history(ticker: str, now: datetime) -> int:
    """Pull yfinance.earnings_history → upsert into earnings_history table.
    Returns number of rows inserted/updated."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        df = t.earnings_history
    except Exception as exc:
        logger.debug("earnings_history fetch %s: %s", ticker, exc)
        return 0
    if df is None or df.empty:
        return 0
    n_upserted = 0
    now_iso = now.isoformat()
    with connect() as conn:
        for idx, row in df.iterrows():
            # idx is "YYYY-MM-DD" or pandas Timestamp
            try:
                ed = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            except Exception:
                continue
            eps_est = _safe_float(row.get("epsEstimate"))
            eps_act = _safe_float(row.get("epsActual"))
            surprise = _safe_float(row.get("surprisePercent"))
            # surprisePercent in yfinance is decimal (0.08 = +8%) — store as %
            if surprise is not None:
                surprise = surprise * 100.0
            try:
                conn.execute(
                    "INSERT INTO earnings_history "
                    "(ticker, earnings_date, eps_est, eps_actual, surprise_pct, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(ticker, earnings_date) DO UPDATE SET "
                    "  eps_est = excluded.eps_est, "
                    "  eps_actual = excluded.eps_actual, "
                    "  surprise_pct = excluded.surprise_pct, "
                    "  fetched_at = excluded.fetched_at",
                    (ticker, ed, eps_est, eps_act, surprise, now_iso),
                )
                n_upserted += 1
            except Exception as exc:
                logger.debug("earnings_history upsert %s/%s: %s", ticker, ed, exc)
    return n_upserted


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None
