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
from typing import Any, AsyncGenerator, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from agent.constants.models import DEFAULT_MODEL
from agent.finance import agent_audit, investment_projects

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_DEFAULT_MODEL = DEFAULT_MODEL
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


def _build_context_block(
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
            parts.append(_format_symbol_block(s))

    if context_project:
        try:
            p = synthesis.synth_project_data(project_id)
        except Exception as exc:
            logger.debug("synth_project failed: %s", exc)
            p = None
        if p:
            parts.append(_format_project_block(p))

    parts.append(
        "### END DASHBOARD STATE ###\n"
        "Use the data above to ground your answer. If the user asks "
        "something the data supports, cite the specific number. If the "
        "data conflicts with something they said, surface the conflict. "
        "If a field is null, say so — don't invent."
    )
    return "\n\n".join(parts)


def _format_symbol_block(s: Dict[str, Any]) -> str:
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


def _format_project_block(p: Dict[str, Any]) -> str:
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
        context_symbol: Optional[str] = Query(
            None,
            description="If set, fetch /api/synthesis/symbol/{sym} and "
                        "inject as a DASHBOARD STATE block into the system "
                        "prompt so the agent reads the widget data alongside "
                        "the user's question.",
        ),
        context_project: bool = Query(
            False,
            description="If true, fetch /api/synthesis/project and inject "
                        "a project-wide snapshot into the system prompt. "
                        "Used by /brief + /check slash commands.",
        ),
    ):
        pid = _validate_project(project_id)
        if not message.strip():
            raise HTTPException(400, "message is empty")
        if len(message) > 4000:
            raise HTTPException(400, "message too long")

        api_key = _get_api_key()
        req_id = agent_audit.new_req_id()

        # Context injection — pull synthesis snapshots and prepend as
        # an extra system-level block. Keep best-effort: if synthesis
        # fails we still send the user's message, just without the
        # extra context (chat is useful even without dashboard state).
        system_prompt = _SYSTEM_PROMPT
        injected_ctx = _build_context_block(
            project_id=pid,
            context_symbol=context_symbol,
            context_project=context_project,
        )
        if injected_ctx:
            system_prompt = _SYSTEM_PROMPT + "\n\n" + injected_ctx

        messages = [
            {"role": "system", "content": system_prompt},
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
