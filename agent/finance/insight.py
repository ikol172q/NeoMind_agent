"""Per-symbol single-sentence insight for hover tooltips.

One endpoint, one sentence out. The hover interaction needs to feel
instant once the cache is warm, so:

- 5-min cache per (symbol, project) keyed tightly; first call is
  slow (LLM round-trip), subsequent hovers are free.
- Tight prompt: "ONE sentence, numbers only, no hedging."
- Non-streaming — tooltip isn't a conversation, it's a verdict.

The insight is fed the same DASHBOARD STATE block the chat agent
uses. No special synthesis needed.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from agent.constants.models import DEFAULT_MODEL
from agent.finance import agent_audit, investment_projects
from agent.finance.chat_streaming import _SYSTEM_PROMPT, _build_context_block

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_MODEL = DEFAULT_MODEL
_TEMPERATURE = 0.2
_MAX_TOKENS = 220

_TTL_S = 300.0
_REQUEST_TIMEOUT_S = 25.0

_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Tooltip prompt — constrained so every hover produces exactly one
# decision-oriented line.
_INSIGHT_PROMPT = (
    "One sentence, in plain English, under 25 words, answering: "
    "'what is the dashboard telling me about this symbol right now?'\n"
    "Rules:\n"
    "- Cite 1-2 specific numbers from DASHBOARD STATE (price, %, IV, RSI, etc.).\n"
    "- Lead with the signal (bullish / bearish / mixed / quiet), not a preamble.\n"
    "- No 'as an AI' / 'note that' / 'please consider'.\n"
    "- No emoji, no quotes around numbers.\n"
    "- If DASHBOARD STATE is empty/null for this symbol, say 'thin data' plainly."
)


def _get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "DEEPSEEK_API_KEY missing")
    return key


def _cached(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry[0] > _TTL_S:
        return None
    return entry[1]


def _put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


async def _call(system: str, user: str) -> str:
    api_key = _get_api_key()
    async with httpx.AsyncClient(timeout=httpx.Timeout(_REQUEST_TIMEOUT_S)) as client:
        resp = await client.post(
            _DEEPSEEK_URL,
            json={
                "model": _MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "temperature": _TEMPERATURE,
                "max_tokens": _MAX_TOKENS,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"DeepSeek {resp.status_code}: {resp.text[:200]}")
    j = resp.json()
    return j["choices"][0]["message"]["content"].strip()


def build_insight_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/insight/symbol/{symbol}")
    async def insight_symbol(
        symbol: str,
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} not registered")

        cache_key = f"insight::{project_id}::{sym}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        system = _SYSTEM_PROMPT + "\n\n" + _build_context_block(
            project_id=project_id,
            context_symbol=sym,
            context_project=False,
        )

        req_id = agent_audit.new_req_id()
        agent_audit.audit_request(
            req_id=req_id,
            endpoint="/api/insight/symbol",
            agent_id="insight",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _INSIGHT_PROMPT},
            ],
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            project_id=project_id,
        )

        t0 = time.monotonic()
        try:
            text = await _call(system, _INSIGHT_PROMPT)
        except HTTPException as exc:
            agent_audit.audit_error(
                req_id=req_id,
                endpoint="/api/insight/symbol",
                agent_id="insight",
                error_type="HTTPException",
                error_msg=str(exc.detail),
                duration_ms=int((time.monotonic() - t0) * 1000),
                project_id=project_id,
            )
            raise
        except Exception as exc:
            logger.exception("insight failed for %s", sym)
            raise HTTPException(502, f"insight failed: {exc}") from None

        duration_ms = int((time.monotonic() - t0) * 1000)
        agent_audit.audit_response(
            req_id=req_id,
            endpoint="/api/insight/symbol",
            agent_id="insight",
            content=text,
            duration_ms=duration_ms,
            project_id=project_id,
        )

        payload = {
            "symbol": sym,
            "text": text,
            "req_id": req_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
        }
        _put(cache_key, payload)
        return payload

    return router
