"""Today's priority list — "first thing to look at" inbox.

Replaces the user's manual scan across 5 scattered surfaces (Today's
Signals / 待复盘 banner / Outside ring / Smart Money / earnings) with
a single ranked top-N, computed server-side from the same DB tables
those surfaces draw from.

Scoring is intentionally simple + auditable: each candidate carries
the rule(s) that surfaced it so the user can see WHY a ticker made
the cut, not just THAT it did.

Held-weight boost is the central design choice: real-money exposure
multiplies priority. Outside-ring discoveries (no held position) can
still surface but at lower weight than a held ticker with the same
underlying signal.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


# Tunable weights. Updated 2026-05-16 after a walkthrough showed
# held + near-catalyst tickers being out-scored by outside-ring
# discovery — wrong: catalyst on my own money is MORE important
# than what to research next.
_HELD_BOOST = 2.0           # held tickers get 2× the unheld score
_W_CONFLUENCE = 0.40        # × n_sources (typically 2-4)
_W_THESIS_REVIEW = 0.50     # per active 'requires_review' thesis
_W_OUTSIDE_HIGH = 0.30      # × n_high_severity_events
_W_OUTSIDE_SOURCES = 0.10   # × n_sources
_W_EARNINGS_NEAR = 0.50     # × (6 - days), so 0d=3.0/5d=0.5 — UNHELD only
_W_HELD_EARNINGS_NEAR = 3.0 # × (6 - days), so 0d=18.0/5d=3.0 (with held_mul)
                            # — held + earnings_5d is the top-1 priority
                            # axis: a catalyst is about to fire on real $.
_W_STALE_CORE = 0.30        # × min(days_overdue / 14, 3)
_W_CLOSED_LOT = 0.80        # flat per lot — post-mortem is high signal


def build_priority_list_router() -> APIRouter:
    router = APIRouter(prefix="/api/dashboard", tags=["priority-list"])

    @router.get("/priority_list")
    def priority_list(
        limit: int = Query(5, ge=1, le=20, description="number of top-N to return"),
    ) -> Dict[str, Any]:
        return _compute_priority(limit=limit)

    return router


def _compute_priority(limit: int = 5) -> Dict[str, Any]:
    """Aggregate candidates across the 5 streams, score, return top-N."""
    ensure_schema()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    last_7d_iso = (now - timedelta(days=7)).isoformat()
    last_14d_iso = (now - timedelta(days=14)).isoformat()

    # Per-ticker accumulator. reasons holds {stream, text, score} so
    # the frontend can show a per-stream contribution popover for the
    # total score (transparency requirement — never display a number
    # without showing the math).
    cand: Dict[str, Dict[str, Any]] = {}

    def add(ticker: Optional[str], reason: str, score: float, stream: str) -> None:
        if not ticker:
            return
        tk = ticker.upper()
        if tk not in cand:
            cand[tk] = {"reasons": [], "score": 0.0}
        cand[tk]["reasons"].append({
            "stream": stream, "text": reason, "score": round(score, 3),
        })
        cand[tk]["score"] += score

    with connect() as conn:
        # Resolve "held" set and "core" set once.
        held_rows = conn.execute(
            "SELECT symbol, SUM(open_quantity) AS qty, "
            "       SUM(open_price * open_quantity + open_fees) AS cost "
            "FROM tax_lots WHERE close_date IS NULL "
            "GROUP BY symbol"
        ).fetchall()
        held_set = {r["symbol"] for r in held_rows}
        held_cost: Dict[str, float] = {r["symbol"]: float(r["cost"] or 0) for r in held_rows}

        core_set = {r["ticker"] for r in conn.execute(
            "SELECT ticker FROM user_watchlist WHERE tier='core'"
        ).fetchall()}

        def held_mul(tk: str) -> float:
            return _HELD_BOOST if tk in held_set else 1.0

        # ── Stream 1: active multi-source confluences ─────────────
        # signal_confluences are the "Today's Signals" tab content.
        # n_sources captures how many independent scanners agree.
        try:
            for r in conn.execute(
                "SELECT ticker, headline, color, n_sources "
                "FROM signal_confluences "
                "WHERE expires_at > ? "
                "  AND dismissed = 0 "
                "ORDER BY n_sources DESC, detected_at DESC",
                (now_iso,),
            ):
                tk = r["ticker"]
                if not tk:
                    continue
                n = int(r["n_sources"] or 0)
                score = _W_CONFLUENCE * n * held_mul(tk)
                reason = f"⚡ {r['headline'][:60]} ({n} 源)"
                add(tk, reason, score, "confluence")
        except Exception as exc:
            logger.warning("priority_list confluence stream failed: %s", exc)

        # ── Stream 2: theses flagged requires_review ──────────────
        # Set by thesis_health_check (supporting facts/signals decay) OR by
        # thesis_materiality (a new SEC event is material to the thesis).
        # When a materiality verdict exists, surface its WHY (the triggering
        # event + which L0/L1 it touches) so the inbox says why, not just that.
        try:
            mat = {}
            try:
                for m in conn.execute(
                    "SELECT ticker, verdict, items_json FROM thesis_materiality "
                    "WHERE verdict IN ('破','动摇')"
                ):
                    items = json.loads(m["items_json"] or "[]")
                    top = next((it for it in items if it["classification"] in ("破", "动摇")), None)
                    mat[m["ticker"]] = (m["verdict"], top)
            except Exception:
                pass  # table may not exist yet
            for r in conn.execute(
                "SELECT ticker FROM investment_theses "
                "WHERE status = 'requires_review'"
            ):
                tk = r["ticker"]
                score = _W_THESIS_REVIEW * held_mul(tk)
                verdict, top = mat.get(tk, (None, None))
                if top:
                    reason = f"⚠ 复盘:{verdict} — {top['ref'][:28]} ({top['touches']})"
                else:
                    reason = "⚠ thesis 需要 review"
                add(tk, reason, score, "thesis_review")
        except Exception as exc:
            logger.warning("priority_list thesis stream failed: %s", exc)

        # ── Stream 3: outside-ring discovery ───────────────────────
        # Multi-source scanner hits on tickers NOT in any watchlist
        # tier. Anti-anchoring counter-current. No held boost (by
        # definition not held).
        try:
            for r in conn.execute(
                "SELECT e.ticker, "
                "       COUNT(DISTINCT e.scanner_name) AS n_sources, "
                "       SUM(CASE WHEN e.severity='high' THEN 1 ELSE 0 END) AS n_high "
                "FROM signal_events e "
                "WHERE e.ticker IS NOT NULL "
                "  AND e.detected_at >= ? "
                "  AND e.severity IN ('high','med') "
                "  AND e.ticker NOT IN (SELECT ticker FROM user_watchlist) "
                "GROUP BY e.ticker "
                "HAVING COUNT(DISTINCT e.scanner_name) >= 2 "
                "ORDER BY n_high DESC, n_sources DESC "
                "LIMIT 10",
                (last_14d_iso,),
            ):
                tk = r["ticker"]
                n_high = int(r["n_high"] or 0)
                n_src = int(r["n_sources"] or 0)
                score = _W_OUTSIDE_HIGH * n_high + _W_OUTSIDE_SOURCES * n_src
                reason = f"🧭 outside ring · {n_src} 源 / {n_high} high"
                add(tk, reason, score, "outside")
        except Exception as exc:
            logger.warning("priority_list outside stream failed: %s", exc)

        # ── Stream 4: earnings within 5d ──────────────────────────
        # Held tickers get the heavy held_earnings stream (top-priority
        # axis); unheld tickers get the lighter earnings stream (still
        # useful for "what's reporting that I might want to watch").
        try:
            for r in conn.execute(
                "SELECT ticker, body_json FROM signal_events "
                "WHERE signal_type = 'earnings_upcoming' "
                "  AND detected_at >= ? "
                "ORDER BY detected_at DESC",
                (last_7d_iso,),
            ):
                tk = r["ticker"]
                if not tk:
                    continue
                try:
                    body = json.loads(r["body_json"] or "{}")
                except Exception:
                    body = {}
                # earnings_calendar job writes the days field as
                # `days_until` (not `days_to_earnings`). Sample row:
                # {"earnings_date": "2026-05-20", "days_until": 10, ...}
                days = body.get("days_until")
                if not isinstance(days, (int, float)) or days < 0 or days > 5:
                    continue
                # Held tickers with near-term earnings get the heaviest
                # priority axis in the whole system: catalyst is about
                # to fire on real $$, the user must be ready. Unheld
                # earnings is just calendar noise so it stays low.
                if tk in held_set:
                    score = _W_HELD_EARNINGS_NEAR * (6 - days) * _HELD_BOOST
                    reason = f"🎯 业绩 in {int(days)}d (你持仓)"
                    add(tk, reason, score, "held_earnings")
                else:
                    score = _W_EARNINGS_NEAR * (6 - days)
                    reason = f"📅 earnings in {int(days)}d"
                    add(tk, reason, score, "earnings")
        except Exception as exc:
            logger.warning("priority_list earnings stream failed: %s", exc)

        # ── Stream 6: closed-lot post-mortem (7d window) ──────────
        # Every closed lot within the last 7 days deserves a review:
        # was the exit timing right? Did the thesis hold? Without this
        # the system has no feedback loop on actual P&L vs intent.
        # We surface the ticker even if it's no longer in any tier;
        # the close itself created the obligation to evaluate.
        try:
            last_7d_for_close = (now - timedelta(days=7)).isoformat()[:10]
            for r in conn.execute(
                "SELECT symbol, close_date, close_price, close_quantity, "
                "       open_price, open_quantity, "
                "       (close_price - open_price) * close_quantity AS realized_pnl "
                "FROM tax_lots "
                "WHERE close_date IS NOT NULL "
                "  AND close_date >= ? "
                "ORDER BY close_date DESC",
                (last_7d_for_close,),
            ):
                tk = r["symbol"]
                if not tk:
                    continue
                pnl = float(r["realized_pnl"] or 0)
                # PnL sign drives reason emoji — gains worth celebrating,
                # losses worth dissecting; either way it's a learning event.
                emoji = "📗" if pnl >= 0 else "📕"
                pnl_str = (f"+${pnl:,.0f}" if pnl >= 0 else f"-${-pnl:,.0f}")
                reason = f"{emoji} 卖出 {r['close_date'][:10]} · {pnl_str} 复盘?"
                # Don't held-mul (it's CLOSED, no current $ at stake).
                add(tk, reason, _W_CLOSED_LOT, "closed_lot")
        except Exception as exc:
            logger.warning("priority_list closed_lot stream failed: %s", exc)

        # ── Stream 5: stale-core (held + core + >14d unreviewed) ─
        # Core tickers carry weekly-review obligation. If the user
        # has $ on a core that's also gone >14d without a review,
        # that's a discipline gap that should surface above unheld
        # stale ones.
        try:
            for r in conn.execute(
                "SELECT ticker, last_reviewed_at FROM user_watchlist "
                "WHERE tier='core'"
            ):
                tk = r["ticker"]
                last = r["last_reviewed_at"]
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        days = (now - last_dt).total_seconds() / 86400
                    except Exception:
                        days = None
                else:
                    days = None
                if days is None:
                    overdue = 14   # never-reviewed counts as "due now"
                elif days > 14:
                    overdue = days - 14
                else:
                    continue
                # Held-only — unheld stale cores aren't priority decisions
                if tk not in held_set:
                    continue
                # Saturate at 3× so a 90d-stale doesn't dominate forever
                score = _W_STALE_CORE * min(overdue / 14, 3.0) * held_mul(tk)
                reason = (f"🕐 core {int(days)}d 没复盘"
                          if days is not None else "🕐 core 从未复盘")
                add(tk, reason, score, "stale_core")
        except Exception as exc:
            logger.warning("priority_list stale stream failed: %s", exc)

    # Rank + slice.
    ordered = sorted(
        cand.items(),
        key=lambda kv: (-kv[1]["score"], kv[0]),
    )[:limit]

    return {
        "items": [
            {
                "ticker":    tk,
                "score":     round(info["score"], 3),
                # Streams derived from reasons preserve pair order.
                # Kept as a separate field for callers that only need
                # the unique-streams set (e.g. dedupe a badge row).
                "streams":   sorted({r["stream"] for r in info["reasons"]}),
                "reasons":   info["reasons"],  # [{stream, text}, ...]
                "held":      tk in held_set,
                "is_core":   tk in core_set,
                "held_cost": round(held_cost.get(tk, 0), 2) if tk in held_set else None,
            }
            for tk, info in ordered
        ],
        "n_total_candidates": len(cand),
        "computed_at":        now_iso,
        "weights": {
            "held_boost":         _HELD_BOOST,
            "confluence":         _W_CONFLUENCE,
            "thesis_review":      _W_THESIS_REVIEW,
            "outside_high":       _W_OUTSIDE_HIGH,
            "outside_src":        _W_OUTSIDE_SOURCES,
            "earnings_near":      _W_EARNINGS_NEAR,
            "held_earnings_near": _W_HELD_EARNINGS_NEAR,
            "stale_core":         _W_STALE_CORE,
            "closed_lot":         _W_CLOSED_LOT,
        },
    }
