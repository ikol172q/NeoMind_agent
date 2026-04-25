"""Pattern Day Trader (PDT) round-trip counter — FINRA rule 4210.

Rule: in a margin account with equity < $25,000, you may execute at
most 3 day-trade round-trips in any rolling 5 BUSINESS-day window.
A round-trip = open and close the same security on the same day.

For tax_lots:
  - A "day trade" round-trip happens when the same lot's open_date ==
    close_date (intraday round-trip on a single lot), OR when an
    open lot at start-of-day is closed and a NEW lot for the same
    symbol is opened the same day, then THAT new lot is closed the
    same day. V1 only handles the first case.

Calendar: we approximate trading days as Mon–Fri, ignoring US federal
holidays. The error is bounded — Memorial Day, July 4, etc. each
shift the window by 1 day. For the integrity check we use the
9-calendar-day upper bound (5 trading days + 2 weekends + ~2
holidays).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

PDT_LIMIT = 3                   # FINRA: max 3 day trades per 5 business days
PDT_WINDOW_TRADING_DAYS = 5
PDT_EQUITY_THRESHOLD = 25_000   # USD — above this, PDT doesn't apply


def _parse_date(s: str) -> date:
    return datetime.fromisoformat(s).date() if "T" in s else date.fromisoformat(s)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _trading_days_back(today: date, n: int) -> date:
    """Return the date that is N trading days (Mon-Fri) before `today`,
    inclusive of `today` if it's a weekday. Doesn't account for US
    federal holidays — out by at most 2 days, see module docstring.
    """
    cur = today
    counted = 0
    if cur.weekday() < 5:
        counted = 1
    while counted < n:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            counted += 1
    return cur


def compute_round_trips(
    conn: sqlite3.Connection,
    detection_run_id: Optional[str] = None,
    asof: Optional[date] = None,
    account_id: str = "main",
) -> Dict[str, Any]:
    """Scan tax_lots for same-day open-and-close pairs (intraday
    round-trips) and write a row to ``pdt_round_trips`` for each.
    Idempotent: re-runs collapse via UNIQUE (open_lot, close_lot,
    trade_date).

    Returns summary dict.
    """
    rows = list(conn.execute(
        """
        SELECT lot_id, account_id, symbol, market,
               open_date, close_date
        FROM tax_lots
        WHERE close_date IS NOT NULL
          AND open_date = close_date
          AND account_id = ?
        ORDER BY close_date ASC, lot_id ASC
        """,
        (account_id,),
    ))

    written = 0
    dup = 0

    for r in rows:
        try:
            conn.execute(
                """
                INSERT INTO pdt_round_trips
                    (account_id, symbol, market,
                     open_lot_id, close_lot_id, trade_date, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["account_id"], r["symbol"], r["market"],
                    r["lot_id"], r["lot_id"],   # same lot, intraday
                    r["close_date"], _now_iso(),
                ),
            )
            written += 1
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint" in str(exc):
                dup += 1
            else:
                raise

    return {
        "scanned_intraday_lots": len(rows),
        "round_trips_written": written,
        "round_trips_skipped_duplicate": dup,
    }


def compute_pdt_status(
    conn: sqlite3.Connection,
    asof: Optional[date] = None,
    account_id: str = "main",
) -> Dict[str, Any]:
    """Compute the user's current PDT exposure: how many round-trips
    in the rolling 5-trading-day window, days until oldest one ages
    out, and whether the next round-trip would breach.

    Read-only — purely a derived view from pdt_round_trips. The UI
    consumes this; integrity does NOT.
    """
    today = asof or date.today()
    window_start = _trading_days_back(today, PDT_WINDOW_TRADING_DAYS)

    rows = list(conn.execute(
        """
        SELECT trade_date, symbol FROM pdt_round_trips
        WHERE account_id = ?
          AND trade_date >= ?
          AND trade_date <= ?
        ORDER BY trade_date ASC
        """,
        (account_id, window_start.isoformat(), today.isoformat()),
    ))

    used = len(rows)
    remaining = max(0, PDT_LIMIT - used)
    breach = used >= PDT_LIMIT

    days_until_oldest_ages_out = None
    if rows:
        oldest = _parse_date(rows[0]["trade_date"])
        # Oldest stays in the window until 5 trading days have passed.
        # Approximate: 5 trading days ≈ 7 calendar days from oldest.
        days_until_oldest_ages_out = max(0, 7 - (today - oldest).days)

    return {
        "account_id": account_id,
        "asof": today.isoformat(),
        "window_start": window_start.isoformat(),
        "limit": PDT_LIMIT,
        "used": used,
        "remaining": remaining,
        "would_breach_on_next_trade": breach,
        "days_until_oldest_ages_out": days_until_oldest_ages_out,
        "round_trips": [
            {"date": r["trade_date"], "symbol": r["symbol"]} for r in rows
        ],
    }
