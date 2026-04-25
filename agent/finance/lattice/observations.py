"""L1 observation generators.

Each generator scans an existing synthesis / anomaly / factor /
sector / sentiment / attribution / news source and emits zero or
more structured ``Observation`` rows. No LLM involvement at this
layer — everything here is deterministic Python.

An observation is the atomic unit of the Insight Lattice: a single
specific, verifiable claim with a number, a source pointer back to
a widget cell, and a multi-label tag set the L2 clusterer uses to
group overlapping evidence.

Generator contract:

    def gen_X(project_id, synthesis_project, extras...) -> list[Observation]

Each generator is narrow (one kind of signal). The engine composes
them; missing inputs degrade to zero observations, never to errors.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence

from agent.finance.lattice.taxonomy import (
    load_taxonomy,
    tag_kv,
    tag_market,
    tag_position,
    tag_sector,
    tag_symbol,
)

logger = logging.getLogger(__name__)


# ── Data class ──────────────────────────────────────────

@dataclass
class Observation:
    id: str
    kind: str
    text: str
    numbers: Dict[str, float] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    source: Dict[str, Any] = field(default_factory=dict)
    severity: str = "info"             # info | warn | alert
    confidence: float = 0.8            # 0-1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── V10·A3 raw widget payload store ────────────────────
#
# After build_observations runs, this dict holds the last-seen raw
# payload per widget, keyed by project_id. The graph builder reads
# it to attach attrs.raw_payload onto L0 widget nodes so the trace
# panel can show "this is exactly what fed L1 this cycle".
#
# Keys are widget ids (same strings used in obs.source["widget"]).
# Values are JSON-serializable slices of the synthesis output.

_last_widget_payloads: Dict[str, Dict[str, Any]] = {}


def get_last_widget_payloads(project_id: str) -> Dict[str, Any]:
    """Return the most recent widget-payload snapshot for a project,
    or {} if build_observations hasn't run for it yet."""
    return _last_widget_payloads.get(project_id, {})


def _stash_widget_payloads(project_id: str, payloads: Dict[str, Any]) -> None:
    _last_widget_payloads[project_id] = payloads


# ── ID generation ──────────────────────────────────────

_COUNTER: Dict[str, int] = {}


def _next_id(kind: str) -> str:
    """Generate a stable-shape id per observation kind. IDs reset
    each engine invocation so two runs don't share id space."""
    _COUNTER[kind] = _COUNTER.get(kind, 0) + 1
    return f"obs_{kind}_{_COUNTER[kind]:03d}"


def _reset_ids() -> None:
    _COUNTER.clear()


# ── Generators ─────────────────────────────────────────

def gen_technical_signals(proj: Dict[str, Any], sym_snaps: Dict[str, Dict[str, Any]]) -> List[Observation]:
    """Pulls technical-pill observations from per-symbol synthesis."""
    out: List[Observation] = []
    for sym, s in sym_snaps.items():
        tech = s.get("technical") or {}
        if not tech:
            continue
        market = str(s.get("market", "US")).upper()
        sector_name = (s.get("sector") or {}).get("sector")
        base_tags = [tag_symbol(sym), tag_market(market)]
        if sector_name:
            base_tags.append(tag_sector(sector_name))

        rng = tech.get("range_pos_20d_pct")
        rsi = tech.get("rsi14")
        r5d = tech.get("return_5d_pct")

        if rng is not None and rng >= 85:
            obs = Observation(
                id=_next_id("near_52w_high"),
                kind="near_52w_high",
                text=f"{sym} at {rng:.0f}th percentile of its 20-day range (near-top).",
                numbers={"range_pos_20d_pct": rng},
                tags=base_tags + [
                    "technical:near_52w_high",
                    "technical:breakout",
                    "timescale:short",
                    "direction:up",
                    "signal:bullish",
                ],
                source={"widget": "chart", "symbol": sym, "field": "range_pos_20d_pct"},
                severity="info",
                confidence=0.9,
            )
            out.append(obs)
        elif rng is not None and rng <= 15:
            out.append(Observation(
                id=_next_id("near_52w_low"),
                kind="near_52w_low",
                text=f"{sym} at {rng:.0f}th percentile of its 20-day range (near-bottom).",
                numbers={"range_pos_20d_pct": rng},
                tags=base_tags + [
                    "technical:near_52w_low",
                    "technical:breakdown",
                    "timescale:short",
                    "direction:down",
                    "signal:bearish",
                ],
                source={"widget": "chart", "symbol": sym, "field": "range_pos_20d_pct"},
                severity="warn",
                confidence=0.85,
            ))

        if rsi is not None:
            if rsi >= 70:
                out.append(Observation(
                    id=_next_id("overbought"),
                    kind="overbought",
                    text=f"{sym} RSI14 at {rsi:.1f} — overbought territory.",
                    numbers={"rsi14": rsi},
                    tags=base_tags + ["technical:overbought", "timescale:short", "signal:bearish"],
                    source={"widget": "chart", "symbol": sym, "field": "rsi14"},
                    severity="info",
                    confidence=0.75,
                ))
            elif rsi <= 30:
                out.append(Observation(
                    id=_next_id("oversold"),
                    kind="oversold",
                    text=f"{sym} RSI14 at {rsi:.1f} — oversold territory.",
                    numbers={"rsi14": rsi},
                    tags=base_tags + ["technical:oversold", "timescale:short", "signal:bullish"],
                    source={"widget": "chart", "symbol": sym, "field": "rsi14"},
                    severity="warn",
                    confidence=0.75,
                ))

        if r5d is not None and abs(r5d) >= 5:
            out.append(Observation(
                id=_next_id("strong_5d_move"),
                kind="strong_5d_move",
                text=f"{sym} has moved {r5d:+.1f}% over the last 5 sessions.",
                numbers={"return_5d_pct": r5d},
                tags=base_tags + [
                    "timescale:short",
                    f"direction:{'up' if r5d > 0 else 'down'}",
                    f"signal:{'bullish' if r5d > 0 else 'bearish'}",
                ],
                source={"widget": "chart", "symbol": sym, "field": "return_5d_pct"},
                severity="info",
                confidence=0.8,
            ))

    return out


def gen_earnings_signals(proj: Dict[str, Any]) -> List[Observation]:
    """Upcoming earnings + IV richness vs historical moves."""
    out: List[Observation] = []
    for e in proj.get("upcoming_earnings") or []:
        sym = e.get("symbol")
        du = e.get("days_until")
        iv = e.get("atm_iv_pct")
        avg_move = e.get("avg_abs_move_pct")
        if not sym or du is None:
            continue

        base_tags = [tag_symbol(sym), tag_market("US"), "catalyst:earnings", "risk:earnings"]

        if 0 <= du <= 14:
            out.append(Observation(
                id=_next_id("earnings_soon"),
                kind="earnings_soon",
                text=f"{sym} reports in {du}d ({e.get('next_earnings_date')}).",
                numbers={"days_until": du},
                tags=base_tags + ["timescale:short"],
                source={"widget": "earnings", "symbol": sym, "field": "days_until"},
                severity="warn" if du <= 7 else "info",
                confidence=0.95,
            ))

        if iv is not None and avg_move is not None and avg_move > 0:
            implied_daily = iv / 16.0
            ratio = implied_daily / avg_move
            if ratio >= 1.3:
                out.append(Observation(
                    id=_next_id("iv_rich"),
                    kind="iv_rich",
                    text=(
                        f"{sym} ATM IV {iv:.1f}% implies ≈{implied_daily:.1f}% daily, "
                        f"{ratio:.1f}× the historical avg |move| ({avg_move:.1f}%)."
                    ),
                    numbers={"atm_iv_pct": iv, "implied_daily_pct": implied_daily, "ratio": ratio},
                    tags=base_tags + ["timescale:short", "signal:neutral"],
                    source={"widget": "earnings", "symbol": sym, "field": "atm_iv_pct"},
                    severity="warn",
                    confidence=0.8,
                ))
            elif ratio <= 0.7:
                out.append(Observation(
                    id=_next_id("iv_cheap"),
                    kind="iv_cheap",
                    text=(
                        f"{sym} ATM IV {iv:.1f}% implies ≈{implied_daily:.1f}% daily, "
                        f"only {ratio:.1f}× the historical avg |move| ({avg_move:.1f}%)."
                    ),
                    numbers={"atm_iv_pct": iv, "implied_daily_pct": implied_daily, "ratio": ratio},
                    tags=base_tags + ["timescale:short", "signal:neutral"],
                    source={"widget": "earnings", "symbol": sym, "field": "atm_iv_pct"},
                    severity="info",
                    confidence=0.75,
                ))

    return out


def gen_portfolio_signals(proj: Dict[str, Any]) -> List[Observation]:
    """Position-level P&L, drawdown, and concentration observations."""
    out: List[Observation] = []
    positions = proj.get("positions") or []
    account = proj.get("account") or {}

    for p in positions:
        sym = p.get("symbol")
        pct = p.get("unrealized_pnl_pct")
        pnl = p.get("unrealized_pnl")
        if not sym or pct is None:
            continue
        base_tags = [tag_symbol(sym), tag_market("US"), tag_position(sym)]

        if pct <= -10:
            out.append(Observation(
                id=_next_id("position_deep_loss"),
                kind="position_deep_loss",
                text=f"{sym} position down {pct:.2f}% (${pnl:+.2f}) — stop-zone.",
                numbers={"pnl_pct": pct, "pnl_usd": pnl or 0.0},
                tags=base_tags + ["pnl:large_loss", "pnl:negative", "risk:drawdown", "signal:bearish"],
                source={"widget": "portfolio", "symbol": sym, "field": "unrealized_pnl_pct"},
                severity="alert",
                confidence=0.95,
            ))
        elif pct <= -5:
            out.append(Observation(
                id=_next_id("position_drawdown"),
                kind="position_drawdown",
                text=f"{sym} position down {pct:.2f}% — check thesis.",
                numbers={"pnl_pct": pct, "pnl_usd": pnl or 0.0},
                tags=base_tags + ["pnl:negative", "risk:drawdown", "signal:bearish"],
                source={"widget": "portfolio", "symbol": sym, "field": "unrealized_pnl_pct"},
                severity="warn",
                confidence=0.9,
            ))
        elif pct >= 15:
            out.append(Observation(
                id=_next_id("position_big_winner"),
                kind="position_big_winner",
                text=f"{sym} position up {pct:.2f}% (${pnl:+.2f}).",
                numbers={"pnl_pct": pct, "pnl_usd": pnl or 0.0},
                tags=base_tags + ["pnl:large_gain", "pnl:positive", "signal:bullish"],
                source={"widget": "portfolio", "symbol": sym, "field": "unrealized_pnl_pct"},
                severity="info",
                confidence=0.9,
            ))

    # Concentration
    if positions:
        count = len(positions)
        by_val = sorted(
            ((p.get("symbol"), float(p.get("current_price") or 0) * float(p.get("quantity") or 0))
             for p in positions),
            key=lambda t: -t[1],
        )
        total_mv = sum(v for _, v in by_val)
        if total_mv > 0:
            top_sym, top_val = by_val[0]
            top_pct = top_val / total_mv * 100.0
            if top_pct >= 50 and count >= 2:
                out.append(Observation(
                    id=_next_id("concentration_risk"),
                    kind="concentration_risk",
                    text=f"{top_sym} is {top_pct:.0f}% of the book — concentration risk.",
                    numbers={"top_weight_pct": top_pct, "position_count": count},
                    tags=[tag_symbol(top_sym), tag_position(top_sym),
                          "risk:concentration", "market:US"],
                    source={"widget": "portfolio", "symbol": top_sym, "field": "quantity"},
                    severity="warn",
                    confidence=0.85,
                ))

    # Account-level day move — Q4: only emit on a meaningful move.
    # A $-35 swing on a $100k book is rounding error; emitting it
    # burns an L1 slot on nothing. Threshold: |pct| >= 1.0% OR
    # |usd| >= 500. Below that, the fact isn't worth a user's attention.
    total_pnl_today = account.get("total_pnl")
    total_pnl_pct_today = account.get("total_pnl_pct")
    if total_pnl_today is not None and positions:
        abs_usd = abs(total_pnl_today)
        abs_pct = abs(total_pnl_pct_today or 0.0)
        if abs_usd >= 500 or abs_pct >= 1.0:
            direction = "up" if total_pnl_today > 0 else "down"
            out.append(Observation(
                id=_next_id("book_day_move"),
                kind="book_day_move",
                text=(
                    f"Book P&L ${total_pnl_today:+.2f} today"
                    + (f" ({total_pnl_pct_today:+.2f}%)" if total_pnl_pct_today is not None else "")
                    + "."
                ),
                numbers={"pnl_usd": total_pnl_today, "pnl_pct": total_pnl_pct_today or 0.0},
                tags=[
                    tag_market("US"),
                    f"pnl:{'positive' if total_pnl_today > 0 else 'negative'}",
                    f"direction:{direction}",
                    "timescale:intraday",
                ],
                source={"widget": "portfolio", "field": "total_pnl"},
                severity="info",
                confidence=0.95,
            ))

    return out


_SECTOR_MIN_PCT = 0.5   # Q1: don't emit obs for noise-level moves

def gen_sector_signals(proj: Dict[str, Any]) -> List[Observation]:
    """Today's sector movers — only those that actually moved.

    Q1 fix: apply a |pct| >= 0.5% threshold. Before this, a "leader"
    at +0.08% or a "leader" at -0.63% (sign-wrong: it was merely the
    top of a down day) polluted the L1 layer with false signal.
    Also rewrites the human text to use "top-ranked" / "bottom-ranked"
    which is accurate regardless of absolute sign.
    """
    out: List[Observation] = []
    sm = proj.get("sector_movers") or {}
    for s in (sm.get("top") or []):
        name = s.get("name")
        pct = s.get("change_pct")
        if not name or pct is None:
            continue
        if abs(pct) < _SECTOR_MIN_PCT:
            continue
        direction = "up" if pct >= 0 else "down"
        label = "leading" if pct >= _SECTOR_MIN_PCT else "top-ranked"
        out.append(Observation(
            id=_next_id("sector_leader"),
            kind="sector_leader",
            text=f"{name} sector {label} today ({pct:+.2f}%).",
            numbers={"day_pct": pct},
            tags=[tag_sector(name), "regime:rotation", f"direction:{direction}", "timescale:intraday"],
            source={"widget": "sectors", "field": "change_pct"},
            severity="info",
            confidence=0.95,
        ))
    for s in (sm.get("bottom") or []):
        name = s.get("name")
        pct = s.get("change_pct")
        if not name or pct is None:
            continue
        if abs(pct) < _SECTOR_MIN_PCT:
            continue
        direction = "down" if pct <= 0 else "up"
        label = "lagging" if pct <= -_SECTOR_MIN_PCT else "bottom-ranked"
        out.append(Observation(
            id=_next_id("sector_laggard"),
            kind="sector_laggard",
            text=f"{name} sector {label} today ({pct:+.2f}%).",
            numbers={"day_pct": pct},
            tags=[tag_sector(name), "regime:rotation", f"direction:{direction}", "timescale:intraday"],
            source={"widget": "sectors", "field": "change_pct"},
            severity="info",
            confidence=0.95,
        ))
    return out


def gen_sentiment_signals(proj: Dict[str, Any]) -> List[Observation]:
    """Market regime derived from sentiment gauge."""
    out: List[Observation] = []
    sent = proj.get("market_sentiment") or {}
    score = sent.get("composite_score")
    label = sent.get("label")
    if score is None or not label:
        return out

    # Q2: suppress the "neutral" regime obs (45 <= score <= 55).
    # A neutral reading is literally "no actionable read" — emitting
    # it clutters L1 with a zero-information fact. Only emit when the
    # regime actually leans (greed or fear).
    if score >= 55 or score <= 45:
        out.append(Observation(
            id=_next_id("market_regime"),
            kind="market_regime",
            text=f"Market regime: {label} ({score:.1f}/100 composite).",
            numbers={"composite_score": score},
            tags=[
                "regime:sentiment",
                f"signal:{'bullish' if score >= 55 else 'bearish'}",
                "timescale:short",
            ],
            source={"widget": "sentiment", "field": "composite_score"},
            severity="info",
            confidence=0.85,
        ))

    components = sent.get("components") or {}
    vix = components.get("vix") or {}
    vix_pct = vix.get("percentile_pct")
    if vix_pct is not None and vix_pct >= 75:
        out.append(Observation(
            id=_next_id("vix_elevated"),
            kind="vix_elevated",
            text=f"VIX at {vix_pct:.0f}th percentile (1y) — elevated fear.",
            numbers={"vix_percentile": vix_pct, "vix_raw": vix.get("raw") or 0.0},
            tags=["regime:vix", "risk:macro", "signal:bearish", "timescale:short"],
            source={"widget": "sentiment", "field": "components.vix"},
            severity="warn",
            confidence=0.9,
        ))

    breadth = components.get("breadth") or {}
    b_score = breadth.get("score")
    if b_score is not None and b_score <= 30:
        out.append(Observation(
            id=_next_id("breadth_weak"),
            kind="breadth_weak",
            text=f"Market breadth weak — only {breadth.get('up')}/{breadth.get('total')} S&P100 up today.",
            numbers={"breadth_score": b_score},
            tags=["regime:breadth", "signal:bearish", "timescale:intraday"],
            source={"widget": "sentiment", "field": "components.breadth"},
            severity="warn",
            confidence=0.9,
        ))

    return out


def gen_anomaly_signals(anomaly_payload: Dict[str, Any]) -> List[Observation]:
    """Map existing anomaly flags into the observation format. Anomalies
    were already the prototype of 'facts worth the user's attention' —
    reusing them as L1 is the cleanest migration path."""
    out: List[Observation] = []
    flags = anomaly_payload.get("flags") or []
    for f in flags:
        kind = f.get("kind", "anomaly")
        sym = f.get("symbol", "")
        msg = f.get("message", "")
        sev = f.get("severity", "info")
        tags = [f"symbol:{sym}", "market:US"] if sym else []
        # Heuristic tag mapping
        if kind == "near_52w_with_earnings":
            tags += ["technical:near_52w_high", "risk:earnings", "catalyst:earnings", "timescale:short"]
        elif kind == "iv_richness":
            tags += ["risk:earnings", "catalyst:earnings", "timescale:short"]
        elif kind == "position_drawdown":
            tags += [tag_position(sym), "pnl:negative", "risk:drawdown"]
        elif kind == "sector_divergence":
            tags += [tag_position(sym), "regime:rotation"]
        elif kind == "oversold_watch":
            tags += ["technical:oversold", "signal:bullish", "timescale:short"]

        out.append(Observation(
            id=_next_id(f"anomaly_{kind}"),
            kind=f"anomaly_{kind}",
            text=msg,
            numbers={},
            tags=tags,
            source={"widget": "anomalies", "symbol": sym, "field": "kind"},
            severity=sev,
            confidence=0.8,
        ))
    return out


# ── News salience (research: symbol+keyword+recency → MMR) ─

# Keyword multipliers — curated event vocabulary, research-backed
# (Ravenpack / Dow Jones Elementized taxonomies are this pattern).
_KEYWORD_MULTIPLIERS: Dict[str, float] = {
    "earnings": 1.5, "eps": 1.3, "guidance": 1.4, "revenue": 1.2,
    "beats": 1.3, "misses": 1.3, "downgrade": 1.5, "upgrade": 1.4,
    "lawsuit": 1.6, "sued": 1.5, "sec": 1.4, "doj": 1.6, "fda": 1.6,
    "merger": 1.5, "acquisition": 1.5, "spinoff": 1.4,
    "layoff": 1.4, "bankruptcy": 1.7, "restructur": 1.4,
    "dividend": 1.2, "buyback": 1.3,
    "ceo": 1.3, "resign": 1.4, "fired": 1.4,
    "fed": 1.3, "rate": 1.2, "inflation": 1.2, "cpi": 1.3,
    "tariff": 1.4, "china": 1.1, "iran": 1.2,
    "recall": 1.5, "strike": 1.4,
}

_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")


def _news_score(
    title: str,
    published_at: str,
    watchlist_syms: set[str],
    position_syms: set[str],
    now_epoch: Optional[float] = None,
) -> tuple[float, List[str]]:
    """Return (score, matched_tickers). Score = base_ticker_weight ×
    keyword_multiplier × recency_decay. All multiplicative."""
    import time as _time
    from datetime import datetime

    tickers = set(_TICKER_RE.findall(title))
    matched_positions = tickers & position_syms
    matched_watch = tickers & watchlist_syms - matched_positions

    ticker_weight = (
        2.0 if matched_positions
        else 1.0 if matched_watch
        else 0.0
    )
    if ticker_weight == 0:
        return (0.0, [])

    lt = title.lower()
    kw_mult = 1.0
    for keyword, mult in _KEYWORD_MULTIPLIERS.items():
        if keyword in lt:
            kw_mult = max(kw_mult, mult)

    # Recency decay: 1 / (1 + log10(1 + age_minutes))
    try:
        ts = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_min = max(0.0, ((now_epoch or _time.time()) - ts.timestamp()) / 60.0)
    except Exception:
        age_min = 120.0
    recency = 1.0 / (1.0 + math.log10(1.0 + age_min))

    return (ticker_weight * kw_mult * recency, sorted(matched_positions | matched_watch))


def gen_news_signals(
    news_entries: Sequence[Dict[str, Any]],
    watchlist_syms: set[str],
    position_syms: set[str],
    top_k: int = 4,
) -> List[Observation]:
    """Score news headlines by ticker-match × keyword × recency, take
    the top-K with an MMR-style dedup by ticker overlap. Research-
    backed: this is Bloomberg First Word's pattern."""
    if not news_entries:
        return []

    scored = []
    for e in news_entries:
        title = str(e.get("title") or "")
        pub = str(e.get("published_at") or "")
        score, matched = _news_score(title, pub, watchlist_syms, position_syms)
        if score > 0:
            scored.append((score, e, matched))

    scored.sort(key=lambda t: -t[0])

    # MMR-style dedup: pick greedily; skip a headline if a prior one
    # already covered the same ticker set.
    picked: List[tuple[float, Dict[str, Any], List[str]]] = []
    seen_tickers: set[str] = set()
    for score, e, matched in scored:
        new_tickers = set(matched) - seen_tickers
        if not new_tickers and picked:
            continue
        picked.append((score, e, matched))
        seen_tickers.update(matched)
        if len(picked) >= top_k:
            break

    out: List[Observation] = []
    for score, e, matched in picked:
        sym = matched[0] if matched else ""
        title = str(e.get("title") or "")
        feed = str(e.get("feed_title") or "")
        is_position = sym in position_syms

        tags = ["timescale:short"]
        if sym:
            tags.append(tag_symbol(sym))
            if is_position:
                tags.append(tag_position(sym))
        # Best-effort catalyst tag from keyword match
        lt = title.lower()
        if "earnings" in lt or "eps" in lt or "guidance" in lt:
            tags.append("catalyst:earnings")
            tags.append("risk:earnings")
        if any(k in lt for k in ("sec", "doj", "lawsuit", "sued", "fda", "regulator")):
            tags.append("catalyst:regulatory")
            tags.append("risk:regulatory")
        if any(k in lt for k in ("merger", "acquisition", "buyout", "spinoff")):
            tags.append("catalyst:merger")
        if any(k in lt for k in ("cpi", "fed", "fomc", "rate", "inflation", "jobs")):
            tags.append("catalyst:fed" if ("fed" in lt or "fomc" in lt) else "catalyst:data")
            tags.append("risk:macro")

        out.append(Observation(
            id=_next_id("news_hit"),
            kind="news_hit",
            text=f'"{title[:90]}"  ({feed})',
            numbers={"salience_score": round(score, 3)},
            tags=tags,
            source={
                "widget": "news", "symbol": sym, "field": "title",
                "url": e.get("url"),
            },
            severity="info",
            confidence=0.6,
        ))
    return out


# ── Engine ─────────────────────────────────────────────

def build_observations(
    project_id: str,
    *,
    news_limit_per_scan: int = 50,
    fresh: bool = False,
) -> List[Observation]:
    """Scan every available L0 source and produce L1 observations.

    When ``fresh=True``, bypass every downstream cache (synthesis,
    anomalies). This is needed by tests that seed + immediately
    assert, and by the ?fresh=1 API bypass.

    Imports live inside the function so a missing upstream (yfinance
    down, DeepSeek 503) degrades gracefully — the matching generator
    just returns [].
    """
    _reset_ids()

    try:
        from agent.finance import synthesis
    except Exception as exc:
        logger.error("lattice: synthesis import failed: %s", exc)
        return []

    try:
        proj = synthesis.synth_project_data(project_id, fresh=fresh)
    except Exception as exc:
        logger.warning("lattice: project synth failed: %s", exc)
        proj = {}

    symbols: set[str] = set()
    for w in (proj.get("watchlist") or []):
        if str(w.get("market", "")).upper() == "US":
            symbols.add(w["symbol"])
    for p in (proj.get("positions") or []):
        symbols.add(p["symbol"])

    sym_snaps: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        try:
            sym_snaps[sym] = synthesis.synth_symbol_data(project_id, sym, fresh=fresh)
        except Exception as exc:
            logger.debug("lattice: symbol synth failed %s: %s", sym, exc)

    # Anomalies — rebuild when fresh; otherwise trust cache
    anomaly_payload: Dict[str, Any] = {}
    try:
        from agent.finance import anomalies
        if fresh:
            anomaly_payload = anomalies._compute(project_id)
            anomalies._put(project_id, anomaly_payload)
        else:
            cached = anomalies._cached(project_id)
            anomaly_payload = cached if cached is not None else anomalies._compute(project_id)
            if cached is None:
                anomalies._put(project_id, anomaly_payload)
    except Exception as exc:
        logger.debug("lattice: anomalies fetch failed: %s", exc)

    # News entries (via news_hub fetch with watchlist+position symbols)
    news_entries: List[Dict[str, Any]] = []
    try:
        from agent.finance import news_hub
        from dataclasses import asdict as _asdict
        entries = news_hub.fetch_entries(limit=news_limit_per_scan)
        news_entries = [_asdict(e) for e in entries]
    except Exception as exc:
        logger.debug("lattice: news fetch failed: %s", exc)

    watchlist_syms = {w["symbol"] for w in (proj.get("watchlist") or [])
                      if str(w.get("market", "")).upper() == "US"}
    position_syms = {p["symbol"] for p in (proj.get("positions") or [])}

    # Compose all generators. Order matters only for ID generation
    # stability within one scan — the engine itself is order-independent.
    # V10·A3: stamp each emitted observation with the generator
    # function name that produced it, so the trace UI can show
    # "source.generator" alongside "source.widget". The selfcheck
    # invariant `observations_have_source` relies on this.
    rows: List[Observation] = []
    for name, call in [
        ("gen_technical_signals", lambda: gen_technical_signals(proj, sym_snaps)),
        ("gen_earnings_signals",  lambda: gen_earnings_signals(proj)),
        ("gen_portfolio_signals", lambda: gen_portfolio_signals(proj)),
        ("gen_sector_signals",    lambda: gen_sector_signals(proj)),
        ("gen_sentiment_signals", lambda: gen_sentiment_signals(proj)),
        ("gen_anomaly_signals",   lambda: gen_anomaly_signals(anomaly_payload)),
        ("gen_news_signals",
            lambda: gen_news_signals(news_entries, watchlist_syms, position_syms)),
    ]:
        try:
            batch = call()
        except Exception as exc:
            logger.warning("lattice: %s failed: %s", name, exc)
            batch = []
        for o in batch:
            o.source.setdefault("generator", name)
        rows.extend(batch)

    # Dedup exact-text duplicates (e.g. anomaly + direct signal overlap)
    seen: set[str] = set()
    out: List[Observation] = []
    for r in rows:
        key = (r.kind, r.source.get("symbol", ""), r.text[:80])
        if key in seen:
            continue
        seen.add(str(key))
        out.append(r)

    # Taxonomy-validate tags; drop invalid ones loudly (logs warn).
    tax = load_taxonomy()
    for obs in out:
        obs.tags = tax.reject_invalid(obs.tags)

    # Severity-first ordering so UI sees most important first.
    severity_rank = {"alert": 0, "warn": 1, "info": 2}
    out.sort(key=lambda o: (severity_rank.get(o.severity, 99), -o.confidence))

    # V10·A3: stash the raw payloads that fed the generators this
    # cycle, keyed by widget id. The graph builder attaches these
    # onto L0 widget nodes so the trace UI can show "this is the
    # exact blob that drove today's observations".
    _stash_widget_payloads(project_id, {
        "chart":     {"sym_snaps": sym_snaps},
        "earnings":  {"sym_snaps": {s: {k: v for k, v in (snap or {}).items()
                                         if k in ("days_until_earnings", "atm_iv_pct",
                                                  "earnings_date", "pre_earnings")}
                                    for s, snap in sym_snaps.items()}},
        "portfolio": {
            "positions": proj.get("positions") or [],
            "total_pnl": (proj.get("portfolio_summary") or {}).get("total_pnl"),
        },
        "sectors":   {"heatmap": proj.get("sector_heatmap") or proj.get("sectors") or []},
        "sentiment": {"composite": (proj.get("sentiment") or {}).get("composite_score"),
                      "breakdown": (proj.get("sentiment") or {})},
        "anomalies": anomaly_payload,
        "news":      {"entries_count": len(news_entries),
                      "sample": news_entries[:5]},
        "market_regime": {"regime": (proj.get("sentiment") or {}).get("regime")},
    })
    return out
