"""Dashboard-state context block construction — shared across all
fin endpoints that want to inject the user's live dashboard data
(quote / position / earnings / sector / news / regime) as an extra
system-level block alongside the persona prompt.

Used by chat_streaming, research_brief, and insight — all of which
need the same DASHBOARD STATE shape so the agent has consistent
grounding regardless of which surface the user reached it through.

Lives outside chat_streaming.py so consumers don't pull in the
chat-channel module just to reuse the context formatter.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Web-channel runtime fence appended to fin.yaml's system prompt.
# fin.yaml is shared with CLI (which has live tool injection); web
# endpoints don't, so we tell the model up-front. Mirrors the
# AVAILABLE TOOLS block CLI's prompt_composer would produce, but
# empty. Used by chat_streaming, research_brief, and insight — all
# the web-side fin endpoints that call the LLM without tool dispatch.
WEB_CHANNEL_FENCE = """══════ AVAILABLE TOOLS ══════

(no LLM-driven tool dispatch in this channel. Do not emit
<tool_call> blocks. Do not say "let me search". Answer from:
  1. your own knowledge, OR
  2. the AUTO-SEARCH RESULTS section below if present (server
     auto-runs hybrid search when the message hits fin.yaml
     auto_search triggers — cite these for any current-fact
     answer), OR
  3. the DASHBOARD STATE section below if present (live widget data).
If you still cannot answer with fresh data, briefly say so and
suggest the user open the Quote / Chart / News widgets on the
Research tab.)
"""


def build_context_block(
    project_id: str,
    context_symbol: Optional[str],
    context_project: bool,
) -> str:
    """Render a compact DASHBOARD STATE block for the system prompt.

    The block is agent-oriented: bullet points, no raw JSON, each
    section labelled so the model can reference it back to the user.
    We intentionally keep it under ~1.5k tokens — big enough to be
    useful, small enough not to dominate the context window.
    """
    if not context_symbol and not context_project:
        return ""
    try:
        from agent.finance import synthesis  # lazy: avoid circular
    except Exception as exc:
        logger.debug("synth import failed: %s", exc)
        return ""

    parts: list[str] = ["### DASHBOARD STATE (fresh, from the user's running dashboard) ###"]

    if context_symbol:
        sym = context_symbol.upper()
        try:
            s = synthesis.synth_symbol_data(project_id, sym)
        except Exception as exc:
            logger.debug("synth_symbol failed for %s: %s", sym, exc)
            s = None
        if s:
            parts.append(format_symbol_block(s))

    if context_project:
        try:
            p = synthesis.synth_project_data(project_id)
        except Exception as exc:
            logger.debug("synth_project failed: %s", exc)
            p = None
        if p:
            parts.append(format_project_block(p))

    parts.append(
        "### END DASHBOARD STATE ###\n"
        "Use the data above to ground your answer. If the user asks "
        "something the data supports, cite the specific number. If the "
        "data conflicts with something they said, surface the conflict. "
        "If a field is null, say so — don't invent."
    )
    return "\n\n".join(parts)


def format_symbol_block(s: Dict[str, Any]) -> str:
    sym = s.get("symbol", "?")
    mkt = s.get("market", "?")
    out: list[str] = [f"## Symbol: {sym} ({mkt})"]

    q = s.get("quote") or {}
    if q.get("price") is not None:
        chg = q.get("change_pct")
        chg_s = f"{chg:+.2f}%" if chg is not None else "n/a"
        out.append(f"- quote: {q['price']} ({chg_s} day)")

    pos = s.get("position")
    if pos:
        pct = pos.get("unrealized_pnl_pct")
        pct_s = f"{pct:+.2f}%" if pct is not None else "n/a"
        out.append(
            f"- position held: {pos.get('quantity')} @ {pos.get('entry_price')} "
            f"(unrealized {pct_s}, ${pos.get('unrealized_pnl'):+.2f})"
        )

    wl = s.get("watchlist")
    if wl:
        note = (wl.get("note") or "").strip()
        out.append(f"- on watchlist{' · note: ' + note if note else ''}")

    t = s.get("technical") or {}
    if t:
        bits = []
        if t.get("trend"): bits.append(f"trend {t['trend']}")
        if t.get("momentum"): bits.append(f"momentum {t['momentum']}")
        if t.get("rsi14") is not None: bits.append(f"RSI14 {t['rsi14']}")
        if t.get("range_pos_20d_pct") is not None: bits.append(f"20d-range {t['range_pos_20d_pct']}%")
        if t.get("return_5d_pct") is not None: bits.append(f"5d {t['return_5d_pct']:+.2f}%")
        if bits:
            out.append("- technical: " + " · ".join(bits))

    e = s.get("earnings") or {}
    if e:
        bits = []
        if e.get("days_until") is not None: bits.append(f"{e['days_until']}d out ({e.get('next_earnings_date')})")
        if e.get("atm_iv_pct") is not None: bits.append(f"ATM IV {e['atm_iv_pct']}%")
        if e.get("avg_abs_move_pct") is not None: bits.append(f"avg |move| {e['avg_abs_move_pct']}%")
        if e.get("rv_30d_pct") is not None: bits.append(f"30d RV {e['rv_30d_pct']}%")
        if bits:
            out.append("- earnings: " + " · ".join(bits))

    r = s.get("rs") or {}
    if r:
        rank = r.get("rank_in_sp100_3m")
        uni = r.get("universe_size")
        r3m, r6m, rytd = r.get("return_3m"), r.get("return_6m"), r.get("return_ytd")
        out.append(
            f"- relative strength: rank {rank}/{uni} on 3M · "
            f"3M {r3m:+.2f}% · 6M {r6m:+.2f}% · YTD {rytd:+.2f}%"
        )

    sec = s.get("sector") or {}
    if sec.get("sector"):
        bits = [sec["sector"]]
        if sec.get("industry") and sec.get("industry") != sec.get("sector"):
            bits.append(sec["industry"])
        out.append(f"- sector: {' / '.join(bits)}")

    news = s.get("news") or {}
    headlines = (news.get("headlines") or [])[:3]
    if headlines:
        out.append(f"- recent news ({news.get('count_7d_approx', 0)} recent hits):")
        for h in headlines:
            out.append(f"  · {h.get('title', '')[:110]}")
    elif news.get("count_7d_approx") == 0:
        out.append("- no recent news hits for this symbol")

    sent = s.get("market_sentiment") or {}
    if sent.get("label"):
        out.append(
            f"- market regime (for context, not symbol-specific): "
            f"{sent['label']} ({sent.get('composite_score')}/100)"
        )

    return "\n".join(out)


def format_project_block(p: Dict[str, Any]) -> str:
    out: list[str] = [f"## Project: {p.get('project_id')}"]

    wl = p.get("watchlist") or []
    if wl:
        summary = ", ".join(f"{e['market']}:{e['symbol']}" for e in wl[:20])
        out.append(f"- watchlist ({len(wl)}): {summary}")

    positions = p.get("positions") or []
    if positions:
        parts = []
        for pos in positions:
            pct = pos.get("unrealized_pnl_pct")
            pct_s = f"{pct:+.2f}%" if pct is not None else "n/a"
            parts.append(f"{pos['symbol']} {pos.get('quantity')} @ {pos.get('entry_price')} ({pct_s})")
        out.append("- paper positions: " + "; ".join(parts))

    acct = p.get("account") or {}
    if acct.get("equity") is not None:
        out.append(
            f"- account: equity ${acct.get('equity')} · "
            f"total P&L ${acct.get('total_pnl')} ({acct.get('total_pnl_pct'):+.3f}%)"
        )

    upcoming = p.get("upcoming_earnings") or []
    if upcoming:
        bits = [
            f"{e['symbol']} in {e['days_until']}d "
            f"(IV {e.get('atm_iv_pct','?')}% vs avg |move| {e.get('avg_abs_move_pct','?')}%)"
            for e in upcoming[:10]
        ]
        out.append("- upcoming earnings: " + "; ".join(bits))

    sm = p.get("sector_movers") or {}
    tops = sm.get("top") or []
    bots = sm.get("bottom") or []
    if tops:
        out.append(
            "- sectors today — top: "
            + ", ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in tops)
        )
    if bots:
        out.append(
            "  bottom: "
            + ", ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in bots)
        )

    sent = p.get("market_sentiment") or {}
    if sent.get("label"):
        out.append(
            f"- market regime: {sent['label']} ({sent.get('composite_score')}/100)"
        )

    news = p.get("relevant_news") or []
    if news:
        out.append(f"- recent news mentioning your holdings/watchlist ({len(news)}):")
        for h in news[:8]:
            out.append(f"  · {h.get('title', '')[:110]}")

    return "\n".join(out)
