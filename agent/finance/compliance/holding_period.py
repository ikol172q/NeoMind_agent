"""Holding period classifier — short-term vs long-term capital gains.

IRS rule (Pub 544 / 550):
  - Holding period starts the day AFTER acquisition.
  - To qualify as long-term, you must hold for MORE than 1 year (i.e.,
    > 365 days, with leap-year handling baked into the date math).
  - Sell on day 366 → long-term. Sell on day 365 → short-term.

Edge cases NOT handled in V1 (flagged with TODO comments — Phase 4):
  - Wash sale rule extends holding period across replacement shares.
  - Constructive sales of appreciated financial positions.
  - Section 1233 short-against-the-box.
  - Gift / inheritance basis-step-up cases.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

LONG_TERM_DAYS = 365  # IRS threshold: > 365 = long-term


def _parse_date(s: str) -> date:
    return datetime.fromisoformat(s).date() if "T" in s else date.fromisoformat(s)


def classify_holding_period(
    open_date: str,
    close_date: str,
) -> Literal["short_term", "long_term"]:
    """Return 'long_term' iff the gap is strictly > 365 days."""
    o = _parse_date(open_date)
    c = _parse_date(close_date)
    days_held = (c - o).days
    return "long_term" if days_held > LONG_TERM_DAYS else "short_term"


def days_until_long_term(open_date: str, asof: Optional[date] = None) -> int:
    """For an OPEN lot: how many more days of holding before this lot
    qualifies as long-term if sold then. Returns 0 if already qualified.
    """
    o = _parse_date(open_date)
    today = asof or date.today()
    days_held = (today - o).days
    return max(0, LONG_TERM_DAYS - days_held + 1)


def snapshot_holding_periods(
    conn: sqlite3.Connection,
    asof: Optional[date] = None,
    detection_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk all OPEN lots, write a holding_period_snapshots row per lot
    for today. Idempotent via the (lot_id, snapshot_date) UNIQUE
    constraint. Returns summary dict for the run log.
    """
    today = asof or date.today()
    today_iso = today.isoformat()

    open_lots = list(conn.execute(
        """
        SELECT lot_id, symbol, open_date FROM tax_lots
        WHERE close_date IS NULL
        """
    ))

    written = 0
    skipped_dup = 0
    for lot in open_lots:
        try:
            o = _parse_date(lot["open_date"])
        except (TypeError, ValueError):
            logger.warning("lot %s has unparseable open_date %r — skipping",
                           lot["lot_id"], lot["open_date"])
            continue
        days_held = (today - o).days
        days_to_lt = max(0, LONG_TERM_DAYS - days_held + 1)
        qualified = "long_term" if days_held > LONG_TERM_DAYS else "short_term"

        try:
            conn.execute(
                """
                INSERT INTO holding_period_snapshots
                    (lot_id, snapshot_date, days_held, days_to_long_term, qualified_today)
                VALUES (?, ?, ?, ?, ?)
                """,
                (lot["lot_id"], today_iso, days_held, days_to_lt, qualified),
            )
            written += 1
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint" in str(exc):
                skipped_dup += 1
            else:
                raise

    # Backfill the holding_period_qualified column on closed lots that
    # don't have it set yet (cheap correctness improvement):
    conn.execute(
        """
        UPDATE tax_lots
           SET holding_period_qualified =
               CASE
                 WHEN julianday(close_date) - julianday(open_date) > ?
                 THEN 'long_term'
                 ELSE 'short_term'
               END
         WHERE close_date IS NOT NULL
           AND holding_period_qualified IS NULL
        """,
        (LONG_TERM_DAYS,),
    )

    return {
        "open_lots": len(open_lots),
        "snapshots_written": written,
        "snapshots_skipped_duplicate": skipped_dup,
        "snapshot_date": today_iso,
    }
