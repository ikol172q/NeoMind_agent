"""Delta-since-review — "what changed since you last looked at this ticker".

Powers the drawer's top summary banner: when user opens a ticker
they've reviewed before, surface a compressed list of what's new
since `last_reviewed_at`. Without this the user re-reads the whole
drawer (5 tabs × N rows) every visit.

Five delta streams, each filtered to events with `event_at >= last_reviewed_at`:

  1. Signal events touching this ticker (scanner_name + signal_type)
  2. Thesis status changes (active ↔ requires_review ↔ invalidated)
  3. Price move % (from latest market_data_daily at review vs now)
  4. Smart-money cluster: 13F / insider / congress moves on this ticker
  5. New anchored facts (extracted_at >= last_reviewed_at)

If `last_reviewed_at` is null (ticker never reviewed), fall back to
"last 14 days" so the panel is still useful for first-time opens.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


_FALLBACK_LOOKBACK_DAYS = 14


def build_delta_since_review_router() -> APIRouter:
    router = APIRouter(prefix="/api/stock", tags=["delta-since-review"])

    @router.get("/{ticker}/delta_since_review")
    def delta_since_review(ticker: str) -> Dict[str, Any]:
        t = (ticker or "").strip().upper()
        if not t:
            raise HTTPException(400, "ticker required")
        return _compute_delta(t)

    return router


def _compute_delta(ticker: str) -> Dict[str, Any]:
    ensure_schema()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        # Anchor timestamp: either last_reviewed_at if set, else 14d ago.
        row = conn.execute(
            "SELECT last_reviewed_at FROM user_watchlist WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        last_iso: Optional[str] = row["last_reviewed_at"] if row else None
        if last_iso:
            try:
                last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                anchor = last_dt
                anchor_source = "last_reviewed_at"
            except Exception:
                anchor = now - timedelta(days=_FALLBACK_LOOKBACK_DAYS)
                anchor_source = "fallback_parse_error"
        else:
            anchor = now - timedelta(days=_FALLBACK_LOOKBACK_DAYS)
            anchor_source = "fallback_never_reviewed"
        anchor_iso = anchor.isoformat()
        days_since = max(0, (now - anchor).total_seconds() / 86400)

        # ── Stream 1: signal events ─────────────────────────────
        sig_rows = conn.execute(
            "SELECT scanner_name, signal_type, severity, title, detected_at "
            "FROM signal_events "
            "WHERE ticker = ? AND detected_at >= ? "
            "ORDER BY detected_at DESC LIMIT 12",
            (ticker, anchor_iso),
        ).fetchall()
        signals = [
            {
                "scanner": r["scanner_name"],
                "type":    r["signal_type"],
                "severity": r["severity"],
                "title":   (r["title"] or "")[:140],
                "ts":      r["detected_at"],
            }
            for r in sig_rows
        ]

        # Aggregate by scanner so the UI can show a compact tally
        # (e.g., "watchlist 3 · news 1 · 13f 2").
        scanner_tally: Dict[str, int] = {}
        for s in signals:
            scanner_tally[s["scanner"]] = scanner_tally.get(s["scanner"], 0) + 1

        # ── Stream 2: thesis state transitions ──────────────────
        # We don't have a dedicated thesis_audit log yet, but we can
        # detect "was updated since anchor" by reading updated_at.
        thesis_rows = conn.execute(
            "SELECT thesis_id, status, created_at, "
            "       last_health_check_at, invalidated_at "
            "FROM investment_theses "
            "WHERE ticker = ? "
            "  AND (created_at >= ? "
            "       OR last_health_check_at >= ? "
            "       OR invalidated_at >= ?)",
            (ticker, anchor_iso, anchor_iso, anchor_iso),
        ).fetchall()
        thesis_changes = []
        for r in thesis_rows:
            change_type = None
            ts = None
            if r["invalidated_at"] and r["invalidated_at"] >= anchor_iso:
                change_type = "invalidated"
                ts = r["invalidated_at"]
            elif r["created_at"] >= anchor_iso:
                change_type = "created"
                ts = r["created_at"]
            elif r["last_health_check_at"] and r["last_health_check_at"] >= anchor_iso:
                # Health check ran but only relevant if it set requires_review
                if r["status"] == "requires_review":
                    change_type = "flagged_review"
                    ts = r["last_health_check_at"]
            if change_type:
                thesis_changes.append({
                    "thesis_id": r["thesis_id"],
                    "status":    r["status"],
                    "change":    change_type,
                    "ts":        ts,
                })

        # ── Stream 3: price move % ──────────────────────────────
        # Pull the first and last close from market_data_daily across
        # the anchor → now window. Approximate (only weekday data
        # available), but good enough for "how much did it move".
        price_delta = None
        try:
            anchor_date = anchor.date().isoformat()
            rows = conn.execute(
                "SELECT date, close FROM market_data_daily "
                "WHERE ticker = ? AND date >= ? "
                "ORDER BY date ASC",
                (ticker, anchor_date),
            ).fetchall()
            if rows and len(rows) >= 2:
                start = float(rows[0]["close"] or 0)
                end   = float(rows[-1]["close"] or 0)
                if start > 0:
                    pct = (end - start) / start * 100
                    price_delta = {
                        "start_date":  rows[0]["date"],
                        "start_close": start,
                        "end_date":    rows[-1]["date"],
                        "end_close":   end,
                        "pct":         round(pct, 2),
                    }
        except Exception as exc:
            logger.debug("price_delta query failed for %s: %s", ticker, exc)

        # ── Stream 4: new anchored facts ────────────────────────
        new_facts_rows = conn.execute(
            "SELECT fact_type, COUNT(*) AS n "
            "FROM stock_anchored_facts "
            "WHERE ticker = ? AND extracted_at >= ? "
            "GROUP BY fact_type",
            (ticker, anchor_iso),
        ).fetchall()
        new_facts_by_type = {r["fact_type"]: r["n"] for r in new_facts_rows}

        # ── Stream 5: closed lots in window ─────────────────────
        closed_lot_rows = conn.execute(
            "SELECT close_date, close_price, open_price, close_quantity "
            "FROM tax_lots "
            "WHERE symbol = ? AND close_date >= ? "
            "ORDER BY close_date DESC",
            (ticker, anchor.date().isoformat()),
        ).fetchall()
        closed_lots = [
            {
                "close_date":     r["close_date"],
                "realized_pnl":   round(
                    float((r["close_price"] or 0) - (r["open_price"] or 0))
                    * float(r["close_quantity"] or 0), 2),
                "close_quantity": r["close_quantity"],
            }
            for r in closed_lot_rows
        ]

    total_changes = (
        len(signals) + len(thesis_changes) + len(new_facts_by_type)
        + len(closed_lots) + (1 if price_delta else 0)
    )

    return {
        "ticker":         ticker,
        "anchor_at":      anchor_iso,
        "anchor_source":  anchor_source,
        "days_since":     round(days_since, 1),
        "signals":        signals,
        "scanner_tally":  scanner_tally,
        "thesis_changes": thesis_changes,
        "price_delta":    price_delta,
        "new_facts_by_type": new_facts_by_type,
        "closed_lots":    closed_lots,
        "total_changes":  total_changes,
    }
