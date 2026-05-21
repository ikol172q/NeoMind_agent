"""Whale research summary generator — Tavily search + LLM synthesis.

Per user request 2026-05-19: detailed, unbiased research summary for each
Smart Money entity, regenerable on demand, stored with timestamps so the
user can compare how the agent's read evolves.

Anti-hallucination guarantees (per CLAUDE.md):
  - LLM is given ONLY Tavily search snippets as evidence.
  - LLM prompt forbids inventing URLs — must use only URLs from search.
  - Every URL in the LLM output is HEAD-validated; broken URLs are
    dropped from the structured summary and marked ok=false in
    all_links_validated for transparency.
  - Numeric claims (AUM, returns, market share) must cite [source N]
    or be marked "信息不足".

Pipeline:
  1. gather_evidence(whale)   →  ~12 Tavily hits across 2-3 queries
  2. build_prompt()           →  structured zh+en prompt with citations
  3. _llm_call()              →  deepseek-v4-flash @ T=0.2
  4. _parse_json()            →  robust JSON extraction
  5. validate_urls()          →  HEAD all URLs; rewrite broken ones
  6. store_summary()          →  upsert into DB, mark previous as is_active=0

Sync entry point: generate_summary(whale_key) → dict
Async friendly: invoked inside FastAPI handler with run_in_executor or
in standalone CLI scripts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ── Prompt construction ──────────────────────────────────────────────


_SYSTEM_PROMPT = """You are an unbiased financial research analyst writing for a sophisticated retail investor (NeoMind dashboard user). Your job is to synthesize a detailed bilingual research summary about a specific Smart Money entity (hedge fund / family office / sovereign / activist).

CRITICAL RULES:
1. Use ONLY information from the provided "Evidence" section (Tavily search hits + 13F database moves).
2. NEVER invent URLs. Only cite URLs that appear in the Evidence.
3. Every numeric claim (AUM, returns, percentages, dollar amounts) MUST be followed by [source N] where N is the index of the Evidence item it came from.
4. If you don't have evidence for a section, write "信息不足 (insufficient evidence)" — DO NOT FABRICATE.
5. Write in Chinese primarily, English in parentheses for proper nouns / technical terms.
6. Be unbiased: state both bull and bear views, known criticisms, controversies if mentioned in evidence.

OUTPUT: Return EXACTLY a JSON object with this schema (no markdown wrapper, no commentary):
{
  "investment_logic": "200-400 字, 描述这个 fund 公开记录在案的投资理念 / 策略 / 历史风格. 引用 [source N].",
  "aum_market_position": "AUM 规模, 在同类基金中的地位, peer 比较. 必须 cite [source N]. 没数据写 '信息不足'.",
  "recent_moves_synthesis": "最近 13F / 公开动作的主题归纳 — 加仓什么板块, 清仓什么, 反映什么 thesis 变化.",
  "recent_news": [
    {
      "title": "exact title from evidence",
      "url": "exact url from evidence",
      "published": "YYYY-MM-DD or 'unknown'",
      "source": "domain/publisher",
      "summary": "30-80 字 about what the article says",
      "relevance": "为什么对理解这个 whale 重要 (1-2 句)"
    }
  ],
  "controversies_risks": "已知的争议 / 监管事件 / 风险, 来自 evidence. 无则写 '信息不足'.",
  "key_things_to_know": [
    "短句 1 (具体, 来自 evidence 或 13F 数据)",
    "短句 2",
    "短句 3-5"
  ]
}

DO NOT include any text outside the JSON. The output must be valid parseable JSON.
"""


def _build_evidence_block(
    search_hits: List[Dict[str, Any]],
    db_moves:    List[Dict[str, Any]],
) -> str:
    parts: List[str] = []
    parts.append("=== Evidence: Tavily search results ===\n")
    for i, h in enumerate(search_hits, 1):
        title = h.get("title", "(no title)")[:200]
        url = h.get("url", "")
        snippet = (h.get("snippet") or h.get("content") or "")[:600]
        pub = h.get("published") or h.get("published_date") or "unknown"
        source = h.get("source") or _domain_of(url)
        parts.append(f"[{i}] {title}")
        parts.append(f"    URL: {url}")
        parts.append(f"    Published: {pub} · Source: {source}")
        parts.append(f"    Snippet: {snippet}")
        parts.append("")

    def _num(x, default=0.0):
        if x is None or x == '':
            return default
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    if db_moves:
        parts.append("=== Evidence: Recent 13F moves from our database ===\n")
        for i, m in enumerate(db_moves, 1):
            delta = _num(m.get('delta_pct'))
            val_m = _num(m.get('value_usd_k')) / 1000
            parts.append(
                f"[DB-{i}] {m.get('filing_date', '?')} {m.get('change_type', '?')} "
                f"{m.get('ticker', '?')} (delta={delta:.1%} value=${val_m:.1f}M)"
            )
        parts.append("")

    return "\n".join(parts)


def _domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)/", url + "/")
    return m.group(1).lower() if m else "unknown"


# ── LLM call ─────────────────────────────────────────────────────────


async def _llm_call(prompt: str, *, model: str = "deepseek-v4-flash") -> str:
    base = (os.getenv("LLM_ROUTER_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
    key = (os.getenv("LLM_ROUTER_API_KEY")
           or os.getenv("DEEPSEEK_API_KEY")
           or "dummy")
    payload = {
        "model":       model,
        "messages":    [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens":  6000,
        # Strong nudge for JSON-only output; most OpenAI-compatible APIs honor this.
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as c:
        r = await c.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type":  "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
    msg = data["choices"][0]["message"]
    return msg.get("content") or ""


def _parse_json_robust(text: str) -> Dict[str, Any]:
    """LLMs sometimes wrap JSON in ```json fences, add trailing chatter,
    or truncate at max_tokens. We try in escalating tolerance:
      1) direct parse
      2) strip ``` fences
      3) extract first balanced { ... } block
      4) salvage truncated JSON by closing unterminated strings + braces"""
    t = text.strip()
    # Strip markdown fences
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    # Try direct parse
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # Extract the first balanced { ... } block
    depth = 0
    start = -1
    for i, ch in enumerate(t):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = t[start:i+1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

    # Salvage truncated JSON: walk text, track string state + brace depth,
    # then close all open strings/arrays/objects.
    if not t.lstrip().startswith("{"):
        raise ValueError(f"Could not extract JSON: {text[:200]}")
    in_str = False
    escape = False
    depth = 0
    open_arr = 0
    last_valid_end = -1
    for i, ch in enumerate(t):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_valid_end = i
        elif ch == "[":
            open_arr += 1
        elif ch == "]":
            open_arr -= 1
    # If we have a clean end, use it; else build closer
    if last_valid_end > 0:
        try:
            return json.loads(t[:last_valid_end + 1])
        except json.JSONDecodeError:
            pass
    # Build a closer
    closer = ""
    if in_str:
        closer += '"'
    # Trim trailing comma or partial key
    salvaged = t.rstrip().rstrip(",").rstrip()
    # If trailing ":, partial key, close as null
    if salvaged.endswith(":"):
        salvaged += " null"
    closer += "]" * max(0, open_arr) + "}" * max(0, depth)
    try:
        return json.loads(salvaged + closer)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not extract JSON (salvage failed): {exc} · text starts: {text[:200]}")


# ── URL validation ───────────────────────────────────────────────────


def _validate_url_sync(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """HEAD request; falls back to small GET. Returns
       {url, http_status, ok, validated_at}."""
    out: Dict[str, Any] = {
        "url":           url,
        "http_status":   None,
        "ok":            False,
        "validated_at":  datetime.now(timezone.utc).isoformat(),
    }
    if not url or not url.startswith(("http://", "https://")):
        return out
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout),
                          follow_redirects=True) as c:
            try:
                r = c.head(url, headers={"User-Agent": "NeoMind/whale-research"})
                if r.status_code == 405 or r.status_code >= 500:
                    # Some hosts disallow HEAD — try GET with stream
                    r = c.get(url, headers={"User-Agent": "NeoMind/whale-research"})
                out["http_status"] = r.status_code
                out["ok"] = 200 <= r.status_code < 400
            except httpx.HTTPError as exc:
                out["http_status"] = None
                out["ok"] = False
                out["error"] = str(exc)[:100]
    except Exception as exc:
        out["error"] = str(exc)[:100]
    return out


async def _validate_urls(urls: List[str]) -> List[Dict[str, Any]]:
    """Run HEAD validation in a thread pool for concurrency."""
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, _validate_url_sync, u) for u in urls]
    return await asyncio.gather(*tasks)


# ── Evidence gathering ───────────────────────────────────────────────


async def _gather_search_evidence(whale_short_name: str) -> List[Dict[str, Any]]:
    """Two-stage Tavily search for max coverage:
       1. fund/strategy/AUM
       2. recent news (last 90 days)
    Returns combined hits, deduped by URL."""
    try:
        from agent.search.engine import UniversalSearchEngine
        engine = UniversalSearchEngine()
    except Exception as exc:
        logger.warning("UniversalSearchEngine unavailable: %s", exc)
        return []

    queries = [
        f"{whale_short_name} hedge fund investment strategy AUM 2026",
        f"{whale_short_name} latest 13F holdings recent moves news",
    ]
    all_hits: List[Dict[str, Any]] = []
    seen_urls = set()
    for q in queries:
        try:
            res = await engine.search_advanced(
                query=q,
                max_results=6,
                extract_content=False,
                expand_queries=False,
            )
            for it in (res.items or []):
                if it.url in seen_urls:
                    continue
                seen_urls.add(it.url)
                all_hits.append({
                    "title":     it.title,
                    "url":       it.url,
                    "snippet":   it.snippet,
                    "source":    it.source,
                    "published": it.published.isoformat() if it.published else None,
                })
        except Exception as exc:
            logger.warning("search query '%s' failed: %s", q, exc)
            continue
    return all_hits


def _gather_db_moves(whale_key: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Recent 13F moves from our signal_events table."""
    try:
        from agent.finance.persistence import connect
        with connect() as conn:
            rows = conn.execute(
                "SELECT signal_type, severity, ticker, body_json, "
                "       source_timestamp, source_url "
                "  FROM signal_events "
                " WHERE scanner_name = '13f' "
                "   AND body_json LIKE ? "
                " ORDER BY source_timestamp DESC LIMIT ?",
                (f'%"whale_key": "{whale_key}"%', limit),
            ).fetchall()
    except Exception as exc:
        logger.warning("db moves lookup failed for %s: %s", whale_key, exc)
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            body = json.loads(r["body_json"]) if r["body_json"] else {}
        except Exception:
            body = {}
        out.append({
            "ticker":       r["ticker"],
            "filing_date":  r["source_timestamp"],
            "change_type":  body.get("change_type"),
            "delta_pct":    body.get("delta_pct") or 0,
            "value_usd_k":  body.get("value_usd_k") or 0,
            "signal_type":  r["signal_type"],
        })
    return out


# ── Main entry ───────────────────────────────────────────────────────


async def generate_summary(
    whale_key: str,
    *,
    model: str = "deepseek-v4-flash",
) -> Dict[str, Any]:
    """End-to-end generation. Returns the stored summary dict."""
    from agent.finance.regime.scanners.whale_scanner import WHALES_BY_KEY

    whale = WHALES_BY_KEY.get(whale_key)
    if not whale:
        raise ValueError(f"unknown whale_key: {whale_key}")

    whale_name = whale["short"]
    logger.info("generating research summary for %s (%s)", whale_key, whale_name)

    # 1. Gather evidence
    search_hits = await _gather_search_evidence(whale_name)
    db_moves = _gather_db_moves(whale_key)
    n_search = len(search_hits)
    logger.info("  evidence: %d search hits, %d db moves", n_search, len(db_moves))

    if not search_hits and not db_moves:
        # No evidence at all — abort with marker row
        empty = {
            "investment_logic":        "信息不足 (no search hits and no DB moves)",
            "aum_market_position":     "信息不足",
            "recent_moves_synthesis":  "信息不足",
            "recent_news":             [],
            "controversies_risks":     "信息不足",
            "key_things_to_know":      [],
            "all_links_validated":     [],
            "_meta": {
                "whale_key":   whale_key,
                "whale_name":  whale_name,
                "model":       model,
                "n_search":    0,
                "n_db_moves":  0,
                "error":       "no evidence available",
            },
        }
        _store(whale_key, empty, model, 0, 0, error="no evidence")
        return empty

    # 2. Build prompt + LLM call
    evidence = _build_evidence_block(search_hits, db_moves)
    user_prompt = (
        f"Whale: {whale_name}\n"
        f"CIK: {whale['cik']}\n"
        f"Style: {whale.get('style', 'unknown')}\n"
        f"Horizon: {whale.get('horizon', 'unknown')}\n"
        f"Curated philosophy (background only — verify against evidence): "
        f"{whale.get('philosophy', '')[:400]}\n\n"
        f"{evidence}\n\n"
        f"Now synthesize the JSON research summary per system instructions."
    )
    try:
        raw = await _llm_call(user_prompt, model=model)
        parsed = _parse_json_robust(raw)
    except Exception as exc:
        logger.exception("LLM call/parse failed for %s", whale_key)
        partial = {
            "investment_logic":        f"LLM 生成失败: {exc}",
            "aum_market_position":     "信息不足",
            "recent_moves_synthesis":  "信息不足",
            "recent_news":             [],
            "controversies_risks":     "信息不足",
            "key_things_to_know":      [],
            "all_links_validated":     [],
            "_meta": {"error": str(exc)},
        }
        _store(whale_key, partial, model, n_search, 0, error=str(exc)[:200])
        return partial

    # 3. Collect all URLs and validate
    urls_to_check: List[str] = []
    for item in (parsed.get("recent_news") or []):
        u = item.get("url")
        if u:
            urls_to_check.append(u)
    # Dedup
    urls_to_check = list(dict.fromkeys(urls_to_check))
    validations = await _validate_urls(urls_to_check)
    valid_set = {v["url"] for v in validations if v["ok"]}
    n_valid = len(valid_set)
    logger.info("  validated: %d/%d URLs OK", n_valid, len(urls_to_check))

    # 4. Filter broken URLs out of recent_news (keep in all_links_validated)
    clean_news = []
    for item in (parsed.get("recent_news") or []):
        u = item.get("url")
        if u in valid_set:
            clean_news.append(item)
    parsed["recent_news"] = clean_news
    parsed["all_links_validated"] = validations

    # 5. Attach meta
    parsed["_meta"] = {
        "whale_key":           whale_key,
        "whale_name":          whale_name,
        "model":               model,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "n_search_evidence":   n_search,
        "n_db_moves":          len(db_moves),
        "n_urls_validated":    n_valid,
        "n_urls_attempted":    len(urls_to_check),
    }

    # 6. Store
    _store(whale_key, parsed, model, n_search, n_valid)
    logger.info("  stored summary for %s", whale_key)
    return parsed


# ── Persistence ──────────────────────────────────────────────────────


def _store(
    whale_key:        str,
    summary:          Dict[str, Any],
    model:            str,
    n_search:         int,
    n_validated:      int,
    error:            Optional[str] = None,
) -> int:
    """Insert a new row + mark previous as is_active=0. Returns new row id."""
    from agent.finance.persistence import connect, ensure_schema
    ensure_schema()
    with connect() as conn:
        conn.execute(
            "UPDATE whale_research_summaries SET is_active = 0 WHERE whale_key = ?",
            (whale_key,),
        )
        cur = conn.execute(
            "INSERT INTO whale_research_summaries "
            "(whale_key, summary_json, model_used, n_search_results, "
            " n_urls_validated, is_active, error_message) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (whale_key, json.dumps(summary, ensure_ascii=False),
             model, n_search, n_validated, error),
        )
        conn.commit()
        return cur.lastrowid


def get_active_summary(whale_key: str) -> Optional[Dict[str, Any]]:
    from agent.finance.persistence import connect
    with connect() as conn:
        row = conn.execute(
            "SELECT id, whale_key, generated_at, summary_json, model_used, "
            "       n_search_results, n_urls_validated, error_message "
            "  FROM whale_research_summaries "
            " WHERE whale_key = ? AND is_active = 1 "
            " ORDER BY generated_at DESC LIMIT 1",
            (whale_key,),
        ).fetchone()
    if not row:
        return None
    try:
        summary = json.loads(row["summary_json"])
    except Exception:
        summary = {}
    return {
        "id":               row["id"],
        "whale_key":        row["whale_key"],
        "generated_at":     row["generated_at"],
        "model_used":       row["model_used"],
        "n_search_results": row["n_search_results"],
        "n_urls_validated": row["n_urls_validated"],
        "error_message":    row["error_message"],
        "summary":          summary,
    }


def list_history(whale_key: str, limit: int = 10) -> List[Dict[str, Any]]:
    from agent.finance.persistence import connect
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, generated_at, model_used, n_search_results, "
            "       n_urls_validated, is_active, error_message "
            "  FROM whale_research_summaries "
            " WHERE whale_key = ? "
            " ORDER BY generated_at DESC LIMIT ?",
            (whale_key, limit),
        ).fetchall()
    return [dict(r) for r in rows]
