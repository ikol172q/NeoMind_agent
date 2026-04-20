"""Real-time streaming chat endpoint — direct DeepSeek call, not
through fleet. Emits SSE with token-by-token `delta` events so the
UI gets Telegram-style typing effect, not a 20s-silent-then-dump.

Trade-off vs fleet:
- No fleet multi-agent deliberation (not needed for chat UX)
- No persona config YAML loading (hardcoded system prompt below)
- No transcript writing (but audit log still captures full request+response)

Preserves:
- Investment-root data firewall (project_id validation)
- Zero-data-loss audit log (full messages + full content)
- Tool-free mode (no tool_call XML leak)

Each SSE stream ends with an ``event: done`` carrying the req_id,
so the UI can link the chat bubble to its audit entry for debug.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Dict

import httpx
from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from agent.finance import agent_audit, investment_projects

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_DEFAULT_MODEL = "deepseek-chat"  # chat model for streaming UX; reasoner has CoT overhead
_MAX_TOKENS = 4096
_TEMPERATURE = 0.3

# Hard-coded fin persona prompt. Concise — fleet has the full
# multi-thousand-char version; this is optimized for chat UX.
_SYSTEM_PROMPT = """You are NeoMind (新思), 金融认知延伸, the user's finance copilot inside a local-first dashboard.

- Respond in the user's language (中文/English, match their input).
- You do NOT have tool access in this chat channel. Do not emit <tool_call> blocks. Do not say "let me search" — answer from your own knowledge.
- If the user clearly needs real-time data (live prices, today's news), briefly say so and suggest they use the Quote / Chart / News widgets on the Research tab.
- Be concrete, concise, numeric when possible. Avoid filler.
- If the question is about trading/investing, add a brief risk caveat when relevant — not every turn.
- Markdown allowed (bold, bullets, code). No tables unless the user asks.
"""


def _get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            503,
            "DEEPSEEK_API_KEY missing from process env — run "
            "`./scripts/sync_launchd_env.sh` then restart the dashboard",
        )
    return key


def _validate_project(pid: str) -> str:
    if not investment_projects._PROJECT_ID_RE.match(pid):
        raise HTTPException(400, f"invalid project_id {pid!r}")
    if pid not in investment_projects.list_projects():
        raise HTTPException(404, f"project {pid!r} is not registered")
    return pid


def build_chat_stream_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/chat_stream")
    async def chat_stream(
        project_id: str = Query(...),
        message: str = Query(...),
        model: str = Query(_DEFAULT_MODEL),
    ):
        pid = _validate_project(project_id)
        if not message.strip():
            raise HTTPException(400, "message is empty")
        if len(message) > 4000:
            raise HTTPException(400, "message too long")

        api_key = _get_api_key()
        req_id = agent_audit.new_req_id()

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ]

        # Audit request BEFORE dispatch (never lose request record)
        agent_audit.audit_request(
            req_id=req_id,
            endpoint="/api/chat_stream",
            agent_id="chat-stream",
            messages=messages,
            model=model,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            project_id=pid,
        )

        async def event_generator() -> AsyncGenerator[Dict[str, Any], None]:
            full_content: list[str] = []
            usage: Dict[str, Any] = {}
            finish_reason: str | None = None
            t0 = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None)) as client:
                    async with client.stream(
                        "POST",
                        _DEEPSEEK_URL,
                        json={
                            "model": model,
                            "messages": messages,
                            "stream": True,
                            "stream_options": {"include_usage": True},
                            "temperature": _TEMPERATURE,
                            "max_tokens": _MAX_TOKENS,
                        },
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                    ) as response:
                        if response.status_code != 200:
                            body = (await response.aread()).decode(errors="replace")
                            raise HTTPException(
                                response.status_code,
                                f"DeepSeek upstream {response.status_code}: {body[:200]}",
                            )
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                            except Exception:
                                continue
                            choices = chunk.get("choices") or []
                            if choices:
                                delta = choices[0].get("delta") or {}
                                token = delta.get("content") or ""
                                if token:
                                    full_content.append(token)
                                    yield {
                                        "event": "delta",
                                        "data": json.dumps({"content": token}),
                                    }
                                fr = choices[0].get("finish_reason")
                                if fr:
                                    finish_reason = fr
                            u = chunk.get("usage")
                            if u:
                                usage = u
            except HTTPException as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                agent_audit.audit_error(
                    req_id=req_id,
                    endpoint="/api/chat_stream",
                    agent_id="chat-stream",
                    error_type="HTTPException",
                    error_msg=str(exc.detail),
                    duration_ms=duration_ms,
                    project_id=pid,
                )
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": str(exc.detail), "status": exc.status_code}),
                }
                return
            except Exception as exc:
                import traceback
                duration_ms = int((time.monotonic() - t0) * 1000)
                agent_audit.audit_error(
                    req_id=req_id,
                    endpoint="/api/chat_stream",
                    agent_id="chat-stream",
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                    traceback_text=traceback.format_exc(),
                    duration_ms=duration_ms,
                    project_id=pid,
                )
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": str(exc)}),
                }
                return

            duration_ms = int((time.monotonic() - t0) * 1000)
            final_content = "".join(full_content)
            agent_audit.audit_response(
                req_id=req_id,
                endpoint="/api/chat_stream",
                agent_id="chat-stream",
                content=final_content,
                finish_reason=finish_reason,
                usage=usage or None,
                duration_ms=duration_ms,
                project_id=pid,
            )

            # Final marker carries req_id so UI can link to audit entry
            yield {
                "event": "done",
                "data": json.dumps({
                    "req_id": req_id,
                    "duration_ms": duration_ms,
                    "total_tokens": (usage or {}).get("total_tokens"),
                    "content_length": len(final_content),
                }),
            }

        return EventSourceResponse(event_generator())

    return router
