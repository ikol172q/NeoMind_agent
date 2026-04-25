"""Research-tab narrative hero endpoint.

One call in, one short brief out. The brief is the same shape the
``/brief`` slash command produces, but:

- Non-streaming — the widget renders text once, not token-by-token.
- Server-cached (5 min) so repeated page loads / auto-refresh don't
  each hit DeepSeek.
- Tightly bounded length (target ≤ 220 words, hard cap via max_tokens).

Widgets then just ``GET /api/research_brief?project_id=X`` and render.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from agent.constants.models import DEFAULT_MODEL
from agent.finance import agent_audit, investment_projects, synthesis
from agent.finance.chat_streaming import _SYSTEM_PROMPT, _build_context_block

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_MODEL = DEFAULT_MODEL
_TEMPERATURE = 0.25
_MAX_TOKENS = 700

_TTL_S = 300.0          # 5 min per project
_REQUEST_TIMEOUT_S = 35.0

_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Fixed template so the widget's read is always the same shape and
# caching-friendly. Keeps the hero deterministic in structure, so the
# user's eye finds each section in the same place every time.
_BRIEF_PROMPT = (
    "Produce a dashboard-hero brief using the DASHBOARD STATE block. "
    "Output EXACTLY three labelled lines, no more, no less:\n"
    "\n"
    "Market: <one sentence citing the sentiment label + composite score + one driver>\n"
    "Book: <one sentence on my positions — winner / loser / flat, cite the symbol and %>\n"
    "Next: <one sentence on the nearest catalyst — earnings in N days with IV/move context, OR a sector mover>\n"
    "\n"
    "Rules:\n"
    "- Cite specific numbers from DASHBOARD STATE. If a value is null, say so plainly ('no positions yet').\n"
    "- Each line stands alone: no filler words ('here is...', 'today...').\n"
    "- Under 55 words total across the three lines.\n"
    "- Plain text. No markdown, no emoji, no quotes around numbers.\n"
    "\n"
    "Citation tags (IMPORTANT — the UI renders these as clickable chips):\n"
    "- Wrap every ticker symbol you mention as [[TICKER]]  e.g. [[AAPL]], [[NVDA]].\n"
    "- Wrap a sector reference as [[sector:Name]]  e.g. [[sector:Technology]].\n"
    "- Wrap a position reference as [[pos:TICKER]]  e.g. [[pos:AAPL]] (use this only for symbols I actually hold).\n"
    "- Do NOT wrap numbers, percentages, or sentiment labels — only the three reference types above."
)


def _get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            503,
            "DEEPSEEK_API_KEY missing — run scripts/sync_launchd_env.sh and restart",
        )
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


async def _call_deepseek(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    api_key = _get_api_key()
    async with httpx.AsyncClient(timeout=httpx.Timeout(_REQUEST_TIMEOUT_S)) as client:
        resp = await client.post(
            _DEEPSEEK_URL,
            json={
                "model": _MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
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
        raise HTTPException(
            resp.status_code,
            f"DeepSeek upstream {resp.status_code}: {resp.text[:200]}",
        )
    return resp.json()


def build_research_brief_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/research_brief")
    async def research_brief(
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        cache_key = f"brief::{project_id}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        req_id = agent_audit.new_req_id()
        system_prompt = _SYSTEM_PROMPT + "\n\n" + _build_context_block(
            project_id=project_id,
            context_symbol=None,
            context_project=True,
        )
        agent_audit.audit_request(
            req_id=req_id,
            endpoint="/api/research_brief",
            agent_id="research-brief",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _BRIEF_PROMPT},
            ],
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            project_id=project_id,
        )

        t0 = time.monotonic()
        try:
            response = await _call_deepseek(system_prompt, _BRIEF_PROMPT)
        except HTTPException as exc:
            agent_audit.audit_error(
                req_id=req_id,
                endpoint="/api/research_brief",
                agent_id="research-brief",
                error_type="HTTPException",
                error_msg=str(exc.detail),
                duration_ms=int((time.monotonic() - t0) * 1000),
                project_id=project_id,
            )
            raise
        except Exception as exc:
            logger.exception("research_brief failed")
            import traceback
            agent_audit.audit_error(
                req_id=req_id,
                endpoint="/api/research_brief",
                agent_id="research-brief",
                error_type=type(exc).__name__,
                error_msg=str(exc),
                traceback_text=traceback.format_exc(),
                duration_ms=int((time.monotonic() - t0) * 1000),
                project_id=project_id,
            )
            raise HTTPException(502, f"research_brief failed: {exc}") from None

        duration_ms = int((time.monotonic() - t0) * 1000)
        try:
            content = response["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            raise HTTPException(502, f"malformed deepseek response: {exc}")
        usage = response.get("usage") or {}
        finish = (response.get("choices") or [{}])[0].get("finish_reason")

        agent_audit.audit_response(
            req_id=req_id,
            endpoint="/api/research_brief",
            agent_id="research-brief",
            content=content,
            finish_reason=finish,
            usage=usage,
            duration_ms=duration_ms,
            project_id=project_id,
        )

        payload = {
            "project_id": project_id,
            "text": content,
            "req_id": req_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
        }
        _put(cache_key, payload)
        return payload

    return router
