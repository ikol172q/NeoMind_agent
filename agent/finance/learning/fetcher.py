"""Daily fresh-case fetcher.

Pipeline:
  1. Pull candidate items from miniflux (last 24h, finance categories)
     and Tavily (today/week financial news queries).
  2. LLM gate — for each candidate, ask "is this a useful investing
     learning case?" Yes/No + reason. Drops noise (gossip, single-
     ticker price moves with no story, repeat news).
  3. LLM extract — title_zh / summary_zh / themes / tickers in one
     shot. Translates to Chinese if source is English.
  4. Optionally fetch full article body for the cache (best-effort —
     a Tavily snippet alone is fine if extraction fails).
  5. Upsert into learning_cases with is_fresh=1.

Designed to be safe to re-run — slug dedup means same article
won't be added twice.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent.finance.learning.persistence import (
    expire_fresh_flags, slugify, upsert_case,
)

logger = logging.getLogger(__name__)


# Conservative defaults — first run should produce 3-8 fresh cases
# and stay well under 1c of LLM cost. Tunable via fetch_fresh_cases.
DEFAULT_MAX_CANDIDATES = 30          # before LLM gate
DEFAULT_MAX_ACCEPT = 8                # after LLM gate
DEFAULT_MINIFLUX_LIMIT = 25
DEFAULT_TAVILY_QUERIES = [
    "今日 A股 重大事件",
    "本周 中国 财经 大新闻",
    "today major financial markets news",
    "this week earnings surprise",
]


# ─── Step 1: candidate collection ───────────────────────────────

def _collect_miniflux_candidates(limit: int) -> List[Dict[str, Any]]:
    """Recent miniflux entries (uses the same ones the drawer News tab
    sees). Returns dicts shaped like {title, url, source, published, snippet}."""
    try:
        from agent.finance.news_hub import fetch_entries
        entries = fetch_entries(limit=limit)
    except Exception as exc:
        logger.warning("miniflux fetch failed: %s", exc)
        return []
    out = []
    for e in entries:
        out.append({
            "title": e.title,
            "url": e.url,
            "source": e.feed_title or "miniflux",
            "snippet": e.snippet or "",
            "published": e.published_at or "",
            "origin": "miniflux",
        })
    return out


def _collect_tavily_candidates(queries: List[str], per_query: int = 5
                               ) -> List[Dict[str, Any]]:
    """Run a few "today / this week" queries through the agent-wide
    Tavily-primary search engine. Returns the same shape as miniflux."""
    out: List[Dict[str, Any]] = []
    try:
        from agent.finance.chat_streaming import _get_search_engine
        engine = _get_search_engine()
    except Exception as exc:
        logger.warning("search engine init failed: %s", exc)
        return out
    if engine is None:
        return out

    async def _run_one(q: str) -> List[Dict[str, Any]]:
        try:
            result = await engine.search_advanced(
                query=q, max_results=per_query,
                extract_content=False, expand_queries=False)
        except Exception as exc:
            logger.warning("tavily query %r failed: %s", q, exc)
            return []
        return [{
            "title": it.title or "",
            "url": it.url or "",
            "source": it.source or "tavily",
            "snippet": (it.snippet or "")[:600],
            "published": (it.published.isoformat() if it.published else ""),
            "origin": "tavily",
        } for it in (result.items or [])]

    async def _run_all():
        results = await asyncio.gather(*(_run_one(q) for q in queries),
                                        return_exceptions=True)
        merged: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, list):
                merged.extend(r)
        return merged

    try:
        out = asyncio.run(_run_all())
    except RuntimeError:
        # Already in an event loop — fall back to sync per-query (rare;
        # the scheduler runs in its own loop so this typically doesn't fire)
        loop = asyncio.new_event_loop()
        try:
            out = loop.run_until_complete(_run_all())
        finally:
            loop.close()
    return out


def _dedup(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop duplicates by URL (first wins) and entries with no title."""
    seen = set()
    out = []
    for c in candidates:
        url = (c.get("url") or "").strip()
        title = (c.get("title") or "").strip()
        if not title:
            continue
        key = url or title
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# ─── Step 2 + 3: LLM gate + extract in one call ────────────────

_GATE_PROMPT_SYS = """\
You are screening news headlines for an investing-education library.
For each candidate, decide if it's a useful learning case (teaches a
transferable mental model, regime shift, behavioral lesson, or
significant company/sector event) — NOT just price-tape noise or
gossip.

Output STRICT JSON ONLY, this shape exactly:
{
  "verdict": "accept" | "reject",
  "reason": "<≤30 chars>",
  "title_zh": "<Chinese title, ≤40 chars>",
  "summary_zh": "<Chinese summary, 200-400 chars; lead with the lesson, then the facts>",
  "themes": ["<tag>", ...],         // 2-5 short Chinese or short English tags
  "tickers": ["AAPL", ...],         // any related US/HK/CN tickers, uppercase
  "language": "zh" | "en" | "mix",
  "difficulty": "beginner" | "intermediate" | "advanced",
  "era": "recent_2026"
}

Rules:
- Reject anything that's pure price commentary without a lesson.
- Reject duplicates / repeats of yesterday's news (use your judgment).
- title_zh MUST be Chinese even if source is English. Translate well.
- summary_zh leads with WHAT THE INVESTOR SHOULD LEARN, then the news.
"""


def _llm_gate_and_extract(candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One LLM call per candidate: gate + Chinese-extract in one shot.
    Returns the extracted dict, or None if the gate rejects."""
    from agent.finance.extractors.base import call_strict_json

    user = (
        f"=== CANDIDATE ===\n"
        f"title: {candidate.get('title', '')}\n"
        f"source: {candidate.get('source', '')}\n"
        f"url: {candidate.get('url', '')}\n"
        f"published: {candidate.get('published', '')}\n"
        f"snippet: {candidate.get('snippet', '')[:1500]}"
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "reason", "title_zh", "summary_zh",
                     "themes", "tickers", "language", "difficulty", "era"],
        "properties": {
            "verdict":   {"type": "string"},
            "reason":    {"type": "string"},
            "title_zh":  {"type": "string"},
            "summary_zh":{"type": "string"},
            "themes":    {"type": "array", "items": {"type": "string"}},
            "tickers":   {"type": "array", "items": {"type": "string"}},
            "language":  {"type": "string"},
            "difficulty":{"type": "string"},
            "era":       {"type": "string"},
        },
    }
    try:
        raw = call_strict_json(
            system_prompt=_GATE_PROMPT_SYS,
            user_content=user,
            json_schema=schema,
            schema_name="learning_gate",
            max_tokens=4000,
        )
    except Exception as exc:
        logger.warning("LLM gate failed for %r: %s",
                       candidate.get("title", "?")[:60], exc)
        return None
    if (raw.get("verdict") or "").lower() != "accept":
        logger.debug("gate rejected %r: %s",
                     candidate.get("title", "?")[:60],
                     raw.get("reason", "?"))
        return None
    return raw


# ─── Step 5: persist ───────────────────────────────────────────

def _persist_one(candidate: Dict[str, Any], extracted: Dict[str, Any]) -> str:
    """Build the slug + body and upsert. Returns slug."""
    base = (extracted.get("title_zh") or candidate.get("title") or "case").strip()
    slug = slugify(base)
    # Body: source snippet + extracted summary. Keep it lean —
    # the user can always click the source URL for the full text.
    body_parts = [
        f"# {extracted.get('title_zh','?')}",
        f"**来源**: {candidate.get('source','?')}",
        (f"**原标题**: {candidate.get('title','')}"
         if extracted.get('language') != 'zh' else ""),
        f"**链接**: {candidate.get('url','')}",
        f"**发布**: {candidate.get('published','?')}",
        "",
        "## 中文摘要",
        extracted.get("summary_zh", ""),
        "",
        "## 原文 snippet",
        candidate.get("snippet", ""),
    ]
    body = "\n\n".join([p for p in body_parts if p])

    upsert_case(
        slug=slug,
        title=candidate.get("title") or extracted.get("title_zh") or slug,
        title_zh=extracted.get("title_zh", ""),
        summary_zh=extracted.get("summary_zh", "")[:1500],
        source_url=candidate.get("url"),
        source_name=candidate.get("source"),
        body=body,
        language=extracted.get("language", "zh"),
        themes=extracted.get("themes") or [],
        tickers=[t.upper() for t in (extracted.get("tickers") or []) if t],
        era=extracted.get("era") or "recent_2026",
        difficulty=extracted.get("difficulty") or "intermediate",
        is_classic=False,
        is_fresh=True,
    )
    return slug


# ─── Public entrypoint ────────────────────────────────────────

def fetch_fresh_cases(
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_accept:     int = DEFAULT_MAX_ACCEPT,
    miniflux_limit: int = DEFAULT_MINIFLUX_LIMIT,
    tavily_queries: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the full pipeline once. Safe to re-run.

    Returns a summary dict with counts + the new slugs added.
    """
    t_start = datetime.now(timezone.utc)
    queries = tavily_queries if tavily_queries is not None else DEFAULT_TAVILY_QUERIES

    # 1. Collect
    candidates = _collect_miniflux_candidates(miniflux_limit)
    candidates += _collect_tavily_candidates(queries, per_query=5)
    candidates = _dedup(candidates)
    candidates = candidates[:max_candidates]
    logger.info("learning fetcher: %d candidates after dedup", len(candidates))

    # 2-3. Gate + extract per candidate
    accepted: List[Dict[str, Any]] = []
    rejected = 0
    failed = 0
    for c in candidates:
        if len(accepted) >= max_accept:
            break
        ext = _llm_gate_and_extract(c)
        if ext is None:
            failed += 1
            continue
        if (ext.get("verdict") or "").lower() != "accept":
            rejected += 1
            continue
        accepted.append({**c, "_extracted": ext})

    # 5. Persist
    new_slugs: List[str] = []
    for item in accepted:
        try:
            slug = _persist_one(item, item["_extracted"])
            new_slugs.append(slug)
        except Exception as exc:
            logger.exception("persist failed for %r: %s",
                             item.get("title", "?")[:60], exc)

    # Housekeeping: cases older than 7 days drop out of "Today"
    expired = expire_fresh_flags(days=7)

    duration_ms = int((datetime.now(timezone.utc) - t_start).total_seconds() * 1000)
    summary = {
        "n_candidates":     len(candidates),
        "n_accepted":       len(accepted),
        "n_rejected_gate":  rejected,
        "n_failed_llm":     failed,
        "n_expired_flag":   expired,
        "new_slugs":        new_slugs,
        "duration_ms":      duration_ms,
    }
    logger.info("learning fetcher done: %s", summary)
    return summary
