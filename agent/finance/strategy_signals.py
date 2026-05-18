"""Strategy-facing signal compiler.

GET /api/signals/strategy/{ticker}

Bridge from "NeoMind slow loop" (you + Claude + scanners + 10-K
extraction + 13F + congress + insider) into the "fast loop" where a
deterministic execution framework (QuantConnect / Lumibot /
NautilusTrader / ib_async) polls a number every minute or so.

Compiles **already-collected** signals into a single weighted score
plus rule-style recommendations. No LLM in this path — the slow loop
has already done the thinking. The fast loop just acts.

5 sub-scores in [-1, +1] (bullish positive, bearish negative):
  fundamental · smart_money · technical · news_sentiment · anchor_relevance
combined = weighted average. Rules: open / add / exit / blackout /
force_review. data_complete=false → strategy MUST hold (don't trade
on a partial picture).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _minutes_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        # scheduler_jobs.last_run_at is stored space-separated, naive.
        # Treat as UTC (matches how it's written via datetime('now')).
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (_now() - dt).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ─── 5 sub-score computers ───────────────────────────────────────────


def _fundamental_score(conn, ticker: str) -> Tuple[float, Dict[str, Any]]:
    """Thesis status + supporting facts staleness."""
    row = conn.execute(
        "SELECT thesis_id, status, last_health_check_at, "
        "       supporting_fact_ids, invalidated_at, created_at "
        "FROM investment_theses "
        "WHERE ticker = ? AND invalidated_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row:
        return 0.0, {"thesis": "none"}
    status = row["status"]
    if status == "invalidated":
        return -1.0, {"thesis_status": status, "thesis_id": row["thesis_id"]}
    if status == "requires_review":
        days_old = (_minutes_since(row["last_health_check_at"] or row["created_at"]) or 0) / 1440.0
        return _clip(-0.4 - min(days_old / 30.0, 0.4)), {
            "thesis_status": status,
            "days_since_check": round(days_old, 1),
        }
    days_old = (_minutes_since(row["last_health_check_at"] or row["created_at"]) or 0) / 1440.0
    freshness_bonus = max(0.0, 1.0 - days_old / 30.0)
    n_facts = len(json.loads(row["supporting_fact_ids"] or "[]"))
    fact_score = min(n_facts / 5.0, 1.0)
    score = _clip(0.4 * freshness_bonus + 0.6 * fact_score)
    return score, {
        "thesis_status": "active",
        "thesis_id": row["thesis_id"],
        "days_since_check": round(days_old, 1),
        "n_facts": n_facts,
    }


def _smart_money_score(conn, ticker: str) -> Tuple[float, Dict[str, Any]]:
    """13F + congress + insider Form 4 in last 90 days."""
    rows = conn.execute(
        "SELECT scanner_name, signal_type, body_json, severity, detected_at "
        "FROM signal_events "
        "WHERE ticker = ? "
        "  AND datetime(detected_at) >= datetime('now', '-90 days') "
        "  AND scanner_name IN ('13f', 'house_clerk_pdf', 'congressional', 'insider_form4')",
        (ticker,),
    ).fetchall()

    buckets: Dict[str, List[float]] = {"13f": [], "congress": [], "insider": []}
    for r in rows:
        sc = r["scanner_name"]
        st = (r["signal_type"] or "").lower()
        if "increase" in st or "purchase" in st or "buy" in st or st == "13f_new":
            direction = +1.0
        elif "decrease" in st or "sale" in st or "sell" in st or st == "13f_exit":
            direction = -1.0
        else:
            continue
        sev_weight = {"high": 1.0, "med": 0.6, "low": 0.3}.get(r["severity"], 0.5)
        signal = direction * sev_weight
        if sc == "13f":
            buckets["13f"].append(signal)
        elif sc in ("house_clerk_pdf", "congressional"):
            buckets["congress"].append(signal)
        elif sc == "insider_form4":
            buckets["insider"].append(signal)

    def _avg(xs: List[float]) -> Optional[float]:
        return sum(xs) / len(xs) if xs else None

    parts: List[float] = []
    weights: List[float] = []
    counts: Dict[str, int] = {}
    for name, w in (("13f", 0.5), ("congress", 0.3), ("insider", 0.2)):
        avg = _avg(buckets[name])
        counts[name] = len(buckets[name])
        if avg is not None:
            parts.append(avg * w)
            weights.append(w)
    if not parts:
        return 0.0, {"n_events_90d": 0, "buckets": counts}
    score = _clip(sum(parts) / sum(weights))
    return score, {
        "n_events_90d": sum(counts.values()),
        "buckets": counts,
        "13f_avg":      _avg(buckets["13f"]),
        "congress_avg": _avg(buckets["congress"]),
        "insider_avg":  _avg(buckets["insider"]),
    }


def _technical_score(conn, ticker: str) -> Tuple[float, Dict[str, Any]]:
    """Watchlist scanner's last 3d: vol_spike + 52w_high/low + RSI."""
    rows = conn.execute(
        "SELECT signal_type, severity, body_json, detected_at "
        "FROM signal_events "
        "WHERE ticker = ? AND scanner_name = 'watchlist' "
        "  AND datetime(detected_at) >= datetime('now', '-3 days') "
        "ORDER BY detected_at DESC",
        (ticker,),
    ).fetchall()
    if not rows:
        return 0.0, {"n_signals_3d": 0}

    score = 0.0
    detail: Dict[str, Any] = {"n_signals_3d": len(rows), "types": []}
    weights = {
        "new_52w_high":    +0.4,
        "new_52w_low":     -0.6,
        "rsi_overbought":  -0.2,
        "rsi_oversold":    +0.2,
        "vol_spike":       +0.1,
        "ma_cross_up":     +0.3,
        "ma_cross_down":   -0.3,
    }
    seen_types = set()
    for r in rows:
        st = r["signal_type"]
        if st in seen_types:
            continue
        seen_types.add(st)
        delta = weights.get(st, 0.0)
        sev_factor = {"high": 1.0, "med": 0.7, "low": 0.4}.get(r["severity"], 0.5)
        score += delta * sev_factor
        detail["types"].append({"type": st, "sev": r["severity"]})
    return _clip(score), detail


def _news_sentiment_score(conn, ticker: str) -> Tuple[float, Dict[str, Any]]:
    """Light keyword sentiment over last 24h news."""
    rows = conn.execute(
        "SELECT title, severity, detected_at "
        "FROM signal_events "
        "WHERE ticker = ? AND scanner_name = 'news' "
        "  AND datetime(detected_at) >= datetime('now', '-24 hours')",
        (ticker,),
    ).fetchall()
    if not rows:
        return 0.0, {"n_news_24h": 0}

    POS_KW = ("beat", "raise", "upgrade", "buy", "strong", "record", "rally", "surge",
              "outperform", "bull", "expand", "approval", "win", "高", "涨", "升级", "推荐", "看好")
    NEG_KW = ("miss", "cut", "downgrade", "sell", "weak", "drop", "plunge", "decline",
              "underperform", "bear", "lawsuit", "delay", "loss", "低", "跌", "下调", "看空", "警告")

    pos = neg = 0
    for r in rows:
        t = (r["title"] or "").lower()
        if any(kw in t for kw in POS_KW): pos += 1
        if any(kw in t for kw in NEG_KW): neg += 1
    total = len(rows)
    raw = (pos - neg) / max(total, 1)
    return _clip(raw), {"n_news_24h": total, "pos": pos, "neg": neg}


def _anchor_relevance_score(conn, ticker: str) -> Tuple[float, Dict[str, Any]]:
    """Tier + held → score."""
    tier_row = conn.execute(
        "SELECT tier FROM user_watchlist WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    held_row = conn.execute(
        "SELECT COUNT(*) AS n FROM tax_lots "
        "WHERE symbol = ? AND close_date IS NULL",
        (ticker,),
    ).fetchone()
    tier = tier_row["tier"] if tier_row else None
    held = (held_row["n"] or 0) > 0
    if tier == "core" or held:
        return 1.0, {"tier": tier, "held": held}
    if tier == "adjacent":
        return 0.5, {"tier": tier, "held": False}
    if tier == "watching":
        return 0.2, {"tier": tier, "held": False}
    return 0.0, {"tier": tier, "held": False}


def _earnings_proximity_days(conn, ticker: str) -> Optional[int]:
    row = conn.execute(
        "SELECT body_json FROM signal_events "
        "WHERE ticker = ? AND signal_type = 'earnings_upcoming' "
        "ORDER BY detected_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row:
        return None
    try:
        body = json.loads(row["body_json"] or "{}")
        return int(body.get("days_until")) if body.get("days_until") is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _data_freshness(conn) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT job_name, last_run_at, last_run_status FROM scheduler_jobs"
    ).fetchall()
    out = {}
    for r in rows:
        out[r["job_name"]] = {
            "last_run_at": r["last_run_at"],
            "minutes_ago": _minutes_since(r["last_run_at"]),
            "status":      r["last_run_status"],
        }
    return out


# ─── Public ──────────────────────────────────────────────────────────


def compile_strategy_signal(
    ticker: str,
    w_fundamental: float = 0.25,
    w_smart_money: float = 0.30,
    w_technical:   float = 0.15,
    w_news:        float = 0.10,
    w_anchor:      float = 0.20,
    max_position_pct: float = 0.10,
    stop_loss_pct:    float = 0.15,
    earnings_blackout_days: int = 2,
) -> Dict[str, Any]:
    """Pure function — usable from any code path (HTTP route, batch,
    scheduled job, vectorbt research). Raises HTTPException on invalid
    input so the route handler can return a clean 400."""
    t = ticker.upper().strip()
    if not t.isalpha() or len(t) > 5:
        raise HTTPException(400, f"invalid ticker {ticker!r}")
    ensure_schema()
    with connect() as conn:
        f_score, f_detail = _fundamental_score(conn, t)
        s_score, s_detail = _smart_money_score(conn, t)
        tech_score, tech_detail = _technical_score(conn, t)
        n_score, n_detail = _news_sentiment_score(conn, t)
        a_score, a_detail = _anchor_relevance_score(conn, t)
        earnings_days = _earnings_proximity_days(conn, t)
        freshness = _data_freshness(conn)

    w_sum = w_fundamental + w_smart_money + w_technical + w_news + w_anchor
    if w_sum <= 0:
        raise HTTPException(400, "all weights are zero")
    combined = (
        f_score    * w_fundamental
        + s_score  * w_smart_money
        + tech_score * w_technical
        + n_score  * w_news
        + a_score  * w_anchor
    ) / w_sum

    critical = ["signal_hourly", "daily_market_pull"]
    data_complete = True
    stale_scanners: List[Dict[str, Any]] = []
    for sc in critical:
        info = freshness.get(sc, {})
        mins = info.get("minutes_ago")
        if mins is None or mins > 360 or info.get("status") == "failed":
            data_complete = False
            stale_scanners.append({"scanner": sc, "minutes_ago": mins,
                                   "status": info.get("status")})

    in_earnings_blackout = (
        earnings_days is not None and 0 <= earnings_days <= earnings_blackout_days
    )
    allow_open = (
        data_complete
        and combined > 0.15
        and not in_earnings_blackout
    )
    allow_add = data_complete and combined > 0.35
    allow_exit = data_complete and combined < -0.30
    force_review = (
        f_detail.get("thesis_status") == "requires_review"
        or (earnings_days is not None and earnings_days <= 5)
    )

    return {
        "ticker": t,
        "as_of":  _now().isoformat(),
        "scores": {
            "fundamental":      round(f_score, 4),
            "smart_money":      round(s_score, 4),
            "technical":        round(tech_score, 4),
            "news_sentiment":   round(n_score, 4),
            "anchor_relevance": round(a_score, 4),
            "combined":         round(combined, 4),
        },
        "weights": {
            "fundamental":      w_fundamental,
            "smart_money":      w_smart_money,
            "technical":        w_technical,
            "news_sentiment":   w_news,
            "anchor_relevance": w_anchor,
        },
        "detail": {
            "fundamental":      f_detail,
            "smart_money":      s_detail,
            "technical":        tech_detail,
            "news_sentiment":   n_detail,
            "anchor_relevance": a_detail,
            "earnings_proximity_days": earnings_days,
        },
        "rules": {
            "allow_open":           allow_open,
            "allow_add":            allow_add,
            "allow_exit":           allow_exit,
            "in_earnings_blackout": in_earnings_blackout,
            "force_review":         force_review,
            "max_position_pct":     max_position_pct,
            "stop_loss_pct":        stop_loss_pct,
        },
        "data_complete": data_complete,
        "stale_scanners": stale_scanners,
        "freshness_minutes": {
            sc: info.get("minutes_ago")
            for sc, info in freshness.items()
        },
    }


def build_strategy_signals_router() -> APIRouter:
    router = APIRouter(prefix="/api/signals", tags=["strategy-signals"])

    @router.get("/strategy/{ticker}")
    def strategy_signal(
        ticker: str,
        w_fundamental: float = Query(0.25, ge=0.0, le=1.0),
        w_smart_money: float = Query(0.30, ge=0.0, le=1.0),
        w_technical:   float = Query(0.15, ge=0.0, le=1.0),
        w_news:        float = Query(0.10, ge=0.0, le=1.0),
        w_anchor:      float = Query(0.20, ge=0.0, le=1.0),
        max_position_pct: float = Query(0.10),
        stop_loss_pct:    float = Query(0.15),
        earnings_blackout_days: int = Query(2),
    ) -> Dict[str, Any]:
        return compile_strategy_signal(
            ticker, w_fundamental, w_smart_money, w_technical, w_news,
            w_anchor, max_position_pct, stop_loss_pct, earnings_blackout_days,
        )

    @router.get("/strategy_batch")
    def strategy_signal_batch(
        tickers: str = Query(..., description="逗号分隔的 ticker"),
    ) -> Dict[str, Any]:
        ts = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        ts = ts[:50]
        results: Dict[str, Any] = {}
        for t in ts:
            try:
                results[t] = compile_strategy_signal(t)
            except HTTPException as e:
                results[t] = {"error": e.detail}
        return {"n": len(ts), "results": results, "as_of": _now().isoformat()}

    return router
