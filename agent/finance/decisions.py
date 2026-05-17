"""User decisions — record + replay investment decisions.

Closes the audit loop: each time the user opens a drawer and decides
(hold / trim / add / sell / watch_only / pass), the decision + its
basis is recorded. Lets us answer "why did I hold AAPL on 5/10?" by
reading basis_event_ids back from the row.

Endpoints under /api/stock/{ticker}/decisions:
  POST  → record a decision
  GET   → list decisions for ticker (chronological desc)

Also exposes a global GET /api/decisions/recent that powers a
post-mortem stream in the priority list (future).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.finance.persistence import connect, ensure_schema


_VALID_KINDS = {"hold", "trim", "add", "sell", "watch_only", "pass"}


class DecisionIn(BaseModel):
    kind: str = Field(..., description="hold | trim | add | sell | watch_only | pass")
    basis_event_ids: Optional[List[str]] = None
    basis_fact_ids: Optional[List[int]] = None
    note: Optional[str] = None


def _t(t: str) -> str:
    s = (t or "").strip().upper()
    if not s:
        raise HTTPException(400, "ticker required")
    return s


def build_decisions_router() -> APIRouter:
    router = APIRouter(tags=["user-decisions"])

    @router.post("/api/stock/{ticker}/decisions")
    def record(ticker: str, body: DecisionIn) -> Dict[str, Any]:
        tk = _t(ticker)
        if body.kind not in _VALID_KINDS:
            raise HTTPException(400, f"kind must be one of {sorted(_VALID_KINDS)}")
        ensure_schema()
        decision_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with connect() as conn:
            conn.execute(
                "INSERT INTO user_decisions "
                "(decision_id, ticker, decision_kind, basis_event_ids, "
                " basis_fact_ids, note, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id, tk, body.kind,
                    json.dumps(body.basis_event_ids or []),
                    json.dumps(body.basis_fact_ids or []),
                    (body.note or "").strip() or None,
                    now,
                ),
            )
        return {
            "ok": True, "decision_id": decision_id,
            "ticker": tk, "kind": body.kind, "decided_at": now,
        }

    @router.get("/api/stock/{ticker}/decisions")
    def list_decisions(ticker: str, limit: int = 20) -> Dict[str, Any]:
        tk = _t(ticker)
        ensure_schema()
        with connect() as conn:
            rows = conn.execute(
                "SELECT decision_id, decision_kind, basis_event_ids, "
                "       basis_fact_ids, note, decided_at "
                "FROM user_decisions "
                "WHERE ticker = ? "
                "ORDER BY decided_at DESC LIMIT ?",
                (tk, max(1, min(int(limit), 100))),
            ).fetchall()
        items = []
        for r in rows:
            try:
                events = json.loads(r["basis_event_ids"] or "[]")
            except Exception:
                events = []
            try:
                facts = json.loads(r["basis_fact_ids"] or "[]")
            except Exception:
                facts = []
            items.append({
                "decision_id":     r["decision_id"],
                "kind":            r["decision_kind"],
                "basis_event_ids": events,
                "basis_fact_ids":  facts,
                "note":            r["note"] or "",
                "decided_at":      r["decided_at"],
            })
        return {"ticker": tk, "items": items, "n": len(items)}

    @router.get("/api/stock/{ticker}/decisions/{decision_id}/outcome")
    def decision_outcome(ticker: str, decision_id: str) -> Dict[str, Any]:
        """Pair a past decision with its subsequent outcome.

        Outcome dimensions:
          - price_move_pct: from decided_at close to latest close
          - thesis_state_changes: any active thesis on this ticker that
                                  was invalidated / flagged after decision
          - subsequent_signals: high-severity scanner events since decision
          - subsequent_closes: tax_lots closed after decision (with PnL)

        Closes the "did my last decision pan out?" learning loop.
        """
        tk = _t(ticker)
        ensure_schema()
        with connect() as conn:
            row = conn.execute(
                "SELECT decision_kind, basis_event_ids, note, decided_at "
                "FROM user_decisions "
                "WHERE decision_id = ? AND ticker = ?",
                (decision_id, tk),
            ).fetchone()
            if row is None:
                raise HTTPException(404, f"decision {decision_id} not found for {tk}")
            decided_at = row["decided_at"]
            decided_date = decided_at[:10]
            # Price move: market_data_daily close on decided date → latest
            price_move = None
            try:
                rows = conn.execute(
                    "SELECT date, close FROM market_data_daily "
                    "WHERE ticker = ? AND date >= ? "
                    "ORDER BY date ASC",
                    (tk, decided_date),
                ).fetchall()
                if len(rows) >= 2:
                    start = float(rows[0]["close"] or 0)
                    end   = float(rows[-1]["close"] or 0)
                    if start > 0:
                        price_move = {
                            "start_date":  rows[0]["date"],
                            "start_close": start,
                            "end_date":    rows[-1]["date"],
                            "end_close":   end,
                            "pct":         round((end - start) / start * 100, 2),
                            "days":        len(rows) - 1,
                        }
            except Exception as exc:
                logger.debug("price_move failed: %s", exc)
            # Thesis state changes since decided_at
            thesis_changes = []
            try:
                trows = conn.execute(
                    "SELECT thesis_id, status, invalidated_at, last_health_check_at "
                    "FROM investment_theses "
                    "WHERE ticker = ? "
                    "  AND (invalidated_at >= ? OR last_health_check_at >= ?)",
                    (tk, decided_at, decided_at),
                ).fetchall()
                for tr in trows:
                    if tr["invalidated_at"] and tr["invalidated_at"] >= decided_at:
                        thesis_changes.append({
                            "thesis_id": tr["thesis_id"], "change": "invalidated",
                            "ts": tr["invalidated_at"],
                        })
                    elif tr["status"] == "requires_review" and tr["last_health_check_at"] and tr["last_health_check_at"] >= decided_at:
                        thesis_changes.append({
                            "thesis_id": tr["thesis_id"], "change": "flagged_review",
                            "ts": tr["last_health_check_at"],
                        })
            except Exception as exc:
                logger.debug("thesis_changes failed: %s", exc)
            # Subsequent high-severity events
            subsequent = []
            try:
                erows = conn.execute(
                    "SELECT scanner_name, signal_type, severity, title, source_url, detected_at "
                    "FROM signal_events "
                    "WHERE ticker = ? AND detected_at >= ? "
                    "  AND severity IN ('high','med') "
                    "ORDER BY detected_at DESC LIMIT 8",
                    (tk, decided_at),
                ).fetchall()
                subsequent = [
                    {
                        "scanner": e["scanner_name"], "type": e["signal_type"],
                        "severity": e["severity"], "title": e["title"][:120],
                        "source_url": e["source_url"], "ts": e["detected_at"],
                    }
                    for e in erows
                ]
            except Exception as exc:
                logger.debug("subsequent failed: %s", exc)
            # Tax lots closed AFTER decided_at
            closes = []
            try:
                crows = conn.execute(
                    "SELECT close_date, close_price, open_price, close_quantity "
                    "FROM tax_lots "
                    "WHERE symbol = ? AND close_date IS NOT NULL "
                    "  AND close_date >= ?",
                    (tk, decided_date),
                ).fetchall()
                closes = [
                    {
                        "close_date": c["close_date"],
                        "realized_pnl": round(
                            float((c["close_price"] or 0) - (c["open_price"] or 0))
                            * float(c["close_quantity"] or 0), 2),
                    }
                    for c in crows
                ]
            except Exception as exc:
                logger.debug("closes failed: %s", exc)
        return {
            "decision_id": decision_id,
            "ticker": tk,
            "decided_at": decided_at,
            "decision_kind": row["decision_kind"],
            "decision_note": row["note"] or "",
            "outcome": {
                "price_move":     price_move,
                "thesis_changes": thesis_changes,
                "subsequent":     subsequent,
                "closes":         closes,
            },
        }

    @router.get("/api/decisions/recent")
    def recent(limit: int = 20) -> Dict[str, Any]:
        ensure_schema()
        with connect() as conn:
            rows = conn.execute(
                "SELECT decision_id, ticker, decision_kind, note, decided_at "
                "FROM user_decisions "
                "ORDER BY decided_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return {
            "items": [
                {
                    "decision_id": r["decision_id"],
                    "ticker":      r["ticker"],
                    "kind":        r["decision_kind"],
                    "note":        r["note"] or "",
                    "decided_at":  r["decided_at"],
                }
                for r in rows
            ],
            "n": len(rows),
        }

    return router
