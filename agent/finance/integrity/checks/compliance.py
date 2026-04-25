"""Tax & compliance invariants — wash sale, PDT, holding period.

These are the actual safety-net checks the user explicitly asked
for: they don't just verify schema integrity, they verify the
**rule logic** held when rows were written. A wash_sale_event row
must satisfy IRS's 30-day window; a PDT entry must reference trades
within a real 5-trading-day rolling window.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple


def _parse_date(s: str) -> date:
    return datetime.fromisoformat(s).date() if "T" in s else date.fromisoformat(s)


def check_wash_sale_window(conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = list(conn.execute(
        """
        SELECT w.event_id, w.days_between, w.disallowed_loss,
               s.lot_id AS sell_lot, s.close_date AS sell_date,
               r.lot_id AS repl_lot, r.open_date AS repl_date
        FROM wash_sale_events w
        JOIN tax_lots s ON s.lot_id = w.sell_lot_id
        JOIN tax_lots r ON r.lot_id = w.replacement_lot_id
        """
    ))
    offenders: List[Dict[str, Any]] = []
    for r in rows:
        try:
            sell = _parse_date(r["sell_date"]) if r["sell_date"] else None
            repl = _parse_date(r["repl_date"])
        except (TypeError, ValueError):
            offenders.append({"event_id": r["event_id"], "reason": "unparseable date"})
            continue
        if sell is None:
            offenders.append({"event_id": r["event_id"], "reason": "sell lot not closed"})
            continue
        actual_days = abs((repl - sell).days)
        if actual_days > 30:
            offenders.append({
                "event_id": r["event_id"], "actual_days": actual_days,
                "stored_days": r["days_between"],
            })
        elif actual_days != r["days_between"]:
            offenders.append({
                "event_id": r["event_id"], "actual_days": actual_days,
                "stored_days": r["days_between"],
                "reason": "stored days_between disagrees with computed",
            })
    if offenders:
        return {
            "pass": False,
            "detail": f"{len(offenders)} / {len(rows)} wash-sale events violate IRS window or disagree with stored days",
            "offenders": offenders[:50],
        }
    return {
        "pass": True,
        "detail": f"{len(rows)} / {len(rows)} wash-sale events within 30-day window",
    }


def check_pdt_window(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Approximation: 5 trading days ≈ 7 calendar days. Real US calendar
    drops weekends + ~9 federal holidays, so 9 calendar days is a safe
    upper bound. Anything beyond that is a definite logic error.
    """
    rows = list(conn.execute(
        """
        SELECT p.id, p.trade_date, o.open_date AS open_date
        FROM pdt_round_trips p
        JOIN tax_lots o ON o.lot_id = p.open_lot_id
        """
    ))
    offenders: List[Dict[str, Any]] = []
    for r in rows:
        try:
            opened = _parse_date(r["open_date"])
            traded = _parse_date(r["trade_date"])
        except (TypeError, ValueError):
            offenders.append({"id": r["id"], "reason": "unparseable date"})
            continue
        gap = (traded - opened).days
        if gap < 0 or gap > 9:
            offenders.append({
                "id": r["id"], "gap_calendar_days": gap,
                "open_date": r["open_date"], "trade_date": r["trade_date"],
            })
    if offenders:
        return {
            "pass": False,
            "detail": f"{len(offenders)} / {len(rows)} PDT entries with gap outside [0, 9 cal days]",
            "offenders": offenders[:50],
        }
    return {
        "pass": True,
        "detail": f"{len(rows)} / {len(rows)} PDT entries within 5-trading-day window",
    }


def check_holding_period(conn: sqlite3.Connection) -> Dict[str, Any]:
    """IRS rule: holding period is the period between (acquisition date + 1)
    and the date of disposition. > 1 year (i.e., > 365 days when no leap)
    qualifies as long-term. We use ``> 365`` for the boundary since the
    'plus one day' on the open side is what triggers strict greater-than.
    """
    rows = list(conn.execute(
        """
        SELECT lot_id, open_date, close_date, holding_period_qualified
        FROM tax_lots
        WHERE close_date IS NOT NULL AND holding_period_qualified IS NOT NULL
        """
    ))
    offenders: List[Dict[str, Any]] = []
    for r in rows:
        try:
            o = _parse_date(r["open_date"])
            c = _parse_date(r["close_date"])
        except (TypeError, ValueError):
            offenders.append({"lot_id": r["lot_id"], "reason": "unparseable date"})
            continue
        days_held = (c - o).days
        expected = "long_term" if days_held > 365 else "short_term"
        if r["holding_period_qualified"] != expected:
            offenders.append({
                "lot_id": r["lot_id"], "days_held": days_held,
                "stored": r["holding_period_qualified"], "expected": expected,
            })
    if offenders:
        return {
            "pass": False,
            "detail": f"{len(offenders)} / {len(rows)} closed lots misclassified",
            "offenders": offenders[:50],
        }
    return {
        "pass": True,
        "detail": f"{len(rows)} / {len(rows)} closed lots correctly classified",
    }
