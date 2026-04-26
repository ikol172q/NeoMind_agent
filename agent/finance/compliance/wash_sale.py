"""Wash sale detector — IRS § 1091.

Rule: if you sell a security at a loss and acquire (or contract to
acquire) a "substantially identical" security within 30 days BEFORE
or AFTER the sale, the loss is **disallowed**. The disallowed amount
is added to the basis of the replacement shares, and the holding
period of the replacement shares includes the holding period of the
sold shares.

Scope (V1):
  - "Substantially identical" = same (symbol, market). Cross-vehicle
    identity (e.g., AAPL stock vs AAPL ITM call vs AAPL ETF that's
    99% AAPL) is NOT yet handled — flagged with TODO. Phase 4.
  - Cross-account / IRA wash sales are NOT yet detected. Schema's
    ``account_id`` column is in place; just not exercised. Phase 4.
  - Partial-share matching is by quantity proportion, simplest model.

Determinism:
  - For each loss-closed lot, the FIRST replacement found in the
    61-day window (sorted by absolute days_between, ties broken by
    lot_id ASC) becomes the matched replacement. Stable across runs
    so the (sell_lot_id, replacement_lot_id, rule_version) UNIQUE
    constraint catches re-runs without producing dups.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

WASH_SALE_WINDOW_DAYS = 30  # before AND after = 61-day total window
RULE_VERSION = "irs_2024"


def _parse_date(s: str) -> date:
    return datetime.fromisoformat(s).date() if "T" in s else date.fromisoformat(s)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def detect_wash_sales(
    conn: sqlite3.Connection,
    detection_run_id: Optional[str] = None,
    asof: Optional[date] = None,
) -> Dict[str, Any]:
    """Scan closed-with-loss lots for wash sale matches and write
    wash_sale_events rows. Idempotent: re-running won't double-write
    thanks to UNIQUE (sell_lot_id, replacement_lot_id, rule_version).

    Returns:
        {
          "scanned_loss_lots": int,
          "events_written": int,
          "events_skipped_duplicate": int,
          "skipped_no_match": int,
        }
    """
    asof = asof or date.today()

    # All lots closed at a realized loss. close_price/quantity must be
    # populated; realized_gain_loss might be NULL if the writer
    # forgot — fall back to computing from prices.
    loss_lots = list(conn.execute(
        """
        SELECT
            lot_id, account_id, symbol, market, asset_class,
            open_date, open_price, open_quantity,
            close_date, close_price, close_quantity, close_fees,
            realized_gain_loss
        FROM tax_lots
        WHERE close_date IS NOT NULL
          AND (
              realized_gain_loss < 0
              OR (
                realized_gain_loss IS NULL
                AND close_price < open_price
              )
          )
        """
    ))

    events_written = 0
    events_skipped_dup = 0
    skipped_no_match = 0

    for sell in loss_lots:
        # Compute the actual disallowed loss amount.
        rgl = sell["realized_gain_loss"]
        if rgl is None:
            qty = sell["close_quantity"] or sell["open_quantity"]
            rgl = (sell["close_price"] - sell["open_price"]) * qty - (sell["close_fees"] or 0)
        if rgl is None or rgl >= 0:
            continue
        loss_amount = abs(float(rgl))

        try:
            sell_close = _parse_date(sell["close_date"])
        except (TypeError, ValueError):
            logger.warning("lot %s has unparseable close_date — skipping",
                           sell["lot_id"])
            continue

        window_start = sell_close - timedelta(days=WASH_SALE_WINDOW_DAYS)
        window_end = sell_close + timedelta(days=WASH_SALE_WINDOW_DAYS)

        # Replacement candidates: lots opened in the window for the
        # SAME (account, symbol, market). Exclude the lot itself.
        replacements = list(conn.execute(
            """
            SELECT lot_id, open_date, open_price, open_quantity
            FROM tax_lots
            WHERE account_id = ?
              AND symbol     = ?
              AND market     = ?
              AND lot_id    != ?
              AND open_date BETWEEN ? AND ?
            ORDER BY ABS(julianday(open_date) - julianday(?)) ASC, lot_id ASC
            """,
            (
                sell["account_id"], sell["symbol"], sell["market"],
                sell["lot_id"],
                window_start.isoformat(), window_end.isoformat(),
                sell["close_date"],
            ),
        ))

        if not replacements:
            skipped_no_match += 1
            continue

        match = replacements[0]
        try:
            match_open = _parse_date(match["open_date"])
        except (TypeError, ValueError):
            continue

        days_between = abs((match_open - sell_close).days)

        try:
            conn.execute(
                """
                INSERT INTO wash_sale_events
                    (sell_lot_id, replacement_lot_id, disallowed_loss,
                     basis_addition, days_between, rule_version,
                     detected_at, detection_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sell["lot_id"], match["lot_id"], loss_amount, loss_amount,
                    days_between, RULE_VERSION, _now_iso(), detection_run_id,
                ),
            )
            events_written += 1

            # Mirror the basis adjustment onto the replacement lot for
            # easy reading (we don't rely on this; events table is
            # source of truth, but keeping it on the lot helps the
            # signal layer surface "this lot has wash sale basis").
            conn.execute(
                """
                UPDATE tax_lots
                   SET wash_sale_basis_adjustment =
                       wash_sale_basis_adjustment + ?,
                       updated_at = ?
                 WHERE lot_id = ?
                """,
                (loss_amount, _now_iso(), match["lot_id"]),
            )

        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint" in str(exc):
                events_skipped_dup += 1
            else:
                raise

    return {
        "scanned_loss_lots": len(loss_lots),
        "events_written": events_written,
        "events_skipped_duplicate": events_skipped_dup,
        "skipped_no_match": skipped_no_match,
    }
