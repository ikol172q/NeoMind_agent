"""Real-time streaming chat endpoint — direct DeepSeek call, not
through fleet. Emits SSE with token-by-token `delta` events so the
UI gets Telegram-style typing effect, not a 20s-silent-then-dump.

Persona / model / behavior come from the single source of truth:
- system prompt: ``agent_config.get_mode_config("fin")["system_prompt"]``
  (i.e. fin.yaml — same prompt CLI ``neomind`` mode uses)
- model: ``get_active_model("neomind")`` (i.e. ``provider-state.json``
  — runtime ``/model`` selection takes effect immediately)
- tools: web channel has no tool dispatch yet, so we append a fence
  telling the LLM "AVAILABLE TOOLS: (none)" so the fin persona prompt
  (which expects runtime tool injection) doesn't emit raw <tool_call>
  XML

Web-only concerns kept here (not config dilution, just channel-level):
- SSE token-by-token streaming
- Investment-root data firewall (project_id validation)
- Zero-data-loss audit log (full messages + full content)
- DASHBOARD STATE injection via build_context_block

Each SSE stream ends with an ``event: done`` carrying the req_id,
so the UI can link the chat bubble to its audit entry for debug.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from agent.constants.models import get_active_max_context, get_active_model
from agent.finance import agent_audit, investment_projects
from agent.finance.dashboard_context import WEB_CHANNEL_FENCE, build_context_block
from agent_config import agent_config

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
_MAX_TOKENS = 4096
_TEMPERATURE = 0.3
_SEARCH_TIMEOUT_S = 15.0

# ── Auto-compact tunables ────────────────────────────────────────────
# When estimated prompt tokens for the next LLM call exceed this
# fraction of the model's max_context, summarize the older portion of
# history (Claude Code / LangChain SummaryBufferMemory pattern).
_COMPACT_TRIGGER_PCT = 0.9
# Number of trailing messages kept verbatim after compaction. 12 = 6
# turns (6 user + 6 assistant) — LangChain default ballpark.
_COMPACT_KEEP_RECENT_MSGS = 12
# Max tokens reserved for the summary itself (cap the summarizer's
# output so it doesn't undo the compression).
_COMPACT_SUMMARY_MAX_TOKENS = 2000
_COMPACT_SUMMARIZER_TIMEOUT_S = 30.0
# Marker prefix written into the role=system entry persisted in
# chat_sessions. Backend looks for this on subsequent loads so a
# session never re-summarizes already-compacted prefix.
_COMPACT_MARKER_PREFIX = "[COMPACT_SUMMARY]\n"


def _estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """Rough estimate: ~0.4 tokens/char (zh-heavy fin chat). Off by
    ±20% but the compact threshold has slack — exactness not needed.
    Avoids adding tiktoken / sentencepiece runtime dep."""
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return int(total_chars * 0.4)


async def _summarize_history(
    history: List[Dict[str, Any]],
    api_key: str,
    model: str,
) -> Optional[str]:
    """Compress old turns into a brief factual summary. Returns None
    on any failure so the caller can fall back to drop-oldest."""
    convo = "\n\n".join(
        f"{m['role'].upper()}: {m.get('content', '')}" for m in history
    )
    prompt = (
        "Compress this conversation into a brief summary that preserves "
        "ALL key facts, numbers, dates, decisions, named entities, and "
        "open questions mentioned. Output as plain text, max 800 words, "
        "no markdown headings, no preamble. The summary will be fed back "
        "into the same agent so the assistant retains continuity.\n\n"
        + convo
    )
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_COMPACT_SUMMARIZER_TIMEOUT_S)
        ) as client:
            resp = await client.post(
                _DEEPSEEK_URL,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a concise, faithful summarizer."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "temperature": 0.1,
                    "max_tokens": _COMPACT_SUMMARY_MAX_TOKENS,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            logger.warning(
                "compact summarize: deepseek %d: %s",
                resp.status_code, resp.text[:200],
            )
            return None
        data = resp.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip() or None
    except Exception as exc:
        logger.warning("compact summarize failed: %s", exc)
        return None


# ── OpenAI function-calling tool dispatch ────────────────────────────
# Lazy data_hub singleton (FinanceDataHub no-arg ctor — same pattern
# dashboard_server.py:1325 uses).
_data_hub: Any = None


def _get_data_hub():
    global _data_hub
    if _data_hub is None:
        try:
            from agent.finance.data_hub import FinanceDataHub
            _data_hub = FinanceDataHub()
        except Exception as exc:
            logger.warning("data_hub init failed: %s", exc)
            _data_hub = False
    return _data_hub if _data_hub else None


# OpenAI Chat Completions function-calling tool schemas. Subset of
# agent/tools/finance_tools.py (the ones that work without quant /
# digest / RAG dependencies — those would need full component wiring
# we don't have here). DeepSeek is OpenAI-compatible, so this same
# schema works on OpenAI / Anthropic too if the model is swapped.
_FIN_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "finance_get_stock",
            "description": (
                "Look up a real-time stock quote by ticker (e.g. AAPL, "
                "NVDA, TSLA). Returns price, change, volume, market cap, "
                "source, timestamp. Use this when the user asks about a "
                "specific stock's current price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol like AAPL, MSFT, TSLA",
                    },
                    "market": {
                        "type": "string",
                        "description": "Market code: us (default), cn, hk",
                        "default": "us",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_get_crypto",
            "description": (
                "Look up a real-time crypto price. Accepts ticker (BTC, "
                "ETH, SOL) or CoinGecko coin_id (bitcoin, ethereum). "
                "Returns price, 24h change, volume, market cap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_or_id": {
                        "type": "string",
                        "description": "Crypto ticker or coin_id: BTC / ETH / bitcoin",
                    },
                },
                "required": ["symbol_or_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_market_overview",
            "description": (
                "Get a quick overview of major US market indices and "
                "ETFs: SPY, QQQ, DIA, IWM, VIXY. Returns current prices "
                "and daily change. Use when user asks 'how's the market today'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_news_search",
            "description": (
                "Search financial news. Returns top headlines with "
                "source, time, snippet. Use for 'latest news on X' or "
                "specific tickers / topics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (ticker, topic, event keyword)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of headlines (default 5, max 10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
]


async def _execute_tool(name: str, args: dict) -> dict:
    """Dispatch a tool call. Returns the raw dict the underlying
    finance_tools function returns; chat_streaming serializes it as
    the `tool` role message content. All tools fail-soft: an exception
    becomes {ok: False, error: ...} instead of bubbling up."""
    try:
        if name == "finance_get_stock":
            from agent.tools.finance_tools import finance_get_stock
            return await finance_get_stock(_get_data_hub(), **args)
        if name == "finance_get_crypto":
            from agent.tools.finance_tools import finance_get_crypto
            return await finance_get_crypto(_get_data_hub(), **args)
        if name == "finance_market_overview":
            from agent.tools.finance_tools import finance_market_overview
            return await finance_market_overview(_get_data_hub(), **args)
        if name == "finance_news_search":
            from agent.tools.finance_tools import finance_news_search
            return await finance_news_search(_get_data_hub(), **args)
        return {"ok": False, "error": f"unknown tool: {name}"}
    except Exception as exc:
        logger.exception("tool %s execution failed", name)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# Hard cap on chained tool calls per chat turn — prevents an LLM
# from looping forever (e.g. retrying a failing tool).
_MAX_TOOL_ITERATIONS = 5


def _persist_compact_summary(
    pid: str,
    sid: str,
    summary: str,
    compacted_n: int,
) -> None:
    """Append a compact_summary entry to chat_sessions jsonl. Original
    raw turns stay in the file (UI history sidebar still shows them);
    chat_streaming's load loop just skips everything before this marker
    on subsequent calls."""
    from agent.finance.chat_sessions import _session_path
    spath = _session_path(pid, sid)
    entry = {
        "role": "system",
        "content": _COMPACT_MARKER_PREFIX + summary,
        "ts": datetime.now(timezone.utc).isoformat(),
        "compacted_message_count": compacted_n,
    }
    with spath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# Lazy singleton — UniversalSearchEngine init pulls in tier1/2/3
# sources + cache + reranker, so we only pay for it once and only
# when auto-search is actually wanted.
_search_engine: Any = None  # None = uninitialized, False = init failed


def _get_search_engine():
    """Return UniversalSearchEngine instance or None if unavailable.

    Triggers come from fin.yaml's auto_search.triggers list (single
    source — same triggers CLI uses). Domain hardcoded to "finance"
    because this endpoint is fin-only.
    """
    global _search_engine
    if _search_engine is None:
        try:
            from agent.search.engine import UniversalSearchEngine
            triggers_list = (
                agent_config.get_mode_config("fin")
                .get("auto_search", {})
                .get("triggers", [])
            )
            _search_engine = UniversalSearchEngine(
                domain="finance",
                triggers=set(triggers_list) if triggers_list else None,
            )
            logger.info(
                "auto-search engine ready: %d triggers, %d tier1 + %d tier2 + %d tier3 sources",
                len(_search_engine.triggers),
                len(_search_engine.tier1_sources),
                len(_search_engine.tier2_sources),
                len(_search_engine.tier3_sources),
            )
        except Exception as exc:
            logger.warning(
                "UniversalSearchEngine init failed: %s; auto-search disabled",
                exc,
            )
            _search_engine = False  # Sentinel — don't retry every call
    return _search_engine if _search_engine else None


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
        session_id: Optional[str] = Query(
            None,
            description="If set, load prior user/assistant turns from "
                        "chat_sessions and prepend so the LLM sees the "
                        "full conversation. chat_sessions is the single "
                        "source of truth — frontend does not resend "
                        "history. Standard OpenAI Chat Completions shape "
                        "(role/content), works on DeepSeek + OpenAI + "
                        "Anthropic with no vendor-specific fields.",
        ),
        model: Optional[str] = Query(
            None,
            description="Override the model. When omitted, uses "
                        "get_active_model('neomind') so runtime "
                        "/model selection takes effect.",
        ),
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

        if not model:
            model = get_active_model("neomind")

        api_key = _get_api_key()
        req_id = agent_audit.new_req_id()

        # System prompt layers (in order):
        #   1. fin.yaml persona (CLI's source of truth)
        #   2. WEB_CHANNEL_FENCE — "no LLM-driven tool dispatch"
        #   3. AUTO-SEARCH RESULTS (if message hits fin.yaml triggers
        #      and UniversalSearchEngine returns something)
        #   4. DASHBOARD STATE (if widget context requested)
        # get_mode_config("fin") is mode-agnostic so the dashboard's
        # prompt doesn't drift if user runs `/mode coding` in the CLI.
        fin_prompt = agent_config.get_mode_config("fin").get("system_prompt", "")
        # Chat channel HAS tool dispatch (Step 13) — replace the
        # generic "no tools" fence with an explicit AVAILABLE TOOLS
        # marker so fin.yaml's PINNACLE rules ("不在那里的工具你没有")
        # have something to reference. Actual JSON schemas go in the
        # OpenAI `tools` field of the LLM call below; this is just
        # the human-readable marker.
        system_prompt = fin_prompt + "\n\n" + (
            "══════ AVAILABLE TOOLS ══════\n\n"
            "Real tools are available via OpenAI function calling. "
            "Call any of these directly when the user needs real-time "
            "data (server auto-executes):\n"
            "  - finance_get_stock(symbol, market='us')\n"
            "  - finance_get_crypto(symbol)\n"
            "  - finance_market_overview()\n"
            "  - finance_news_search(query, max_results=5)\n"
            "The full JSON schemas are in the `tools` field of this "
            "LLM call. Use them instead of saying \"I don't have tool "
            "access\". For data not covered by these tools (live "
            "options chains, intraday charts), still suggest the "
            "Research-tab widgets.\n"
        )

        # Auto-search: trigger detection comes from fin.yaml's
        # auto_search.triggers (single source — same trigger set CLI
        # uses). Failure / timeout degrades to "no results" rather
        # than blocking the chat — answering from training knowledge
        # is still useful.
        engine = _get_search_engine()
        if engine and engine.should_search(message):
            try:
                ok, search_text = await asyncio.wait_for(
                    engine.search(message),
                    timeout=_SEARCH_TIMEOUT_S,
                )
                if ok and search_text:
                    system_prompt += (
                        "\n\n══════ AUTO-SEARCH RESULTS ══════\n"
                        f"(query: {message!r})\n\n"
                        f"{search_text}\n"
                        "══════ END AUTO-SEARCH ══════"
                    )
            except asyncio.TimeoutError:
                logger.warning("auto-search timed out after %ss", _SEARCH_TIMEOUT_S)
            except Exception as exc:
                logger.warning("auto-search failed: %s", exc)

        injected_ctx = build_context_block(
            project_id=pid,
            context_symbol=context_symbol,
            context_project=context_project,
        )
        if injected_ctx:
            system_prompt = system_prompt + "\n\n" + injected_ctx

        # Multi-turn: load prior turns from chat_sessions (single
        # source of truth on the server). Two pass:
        #   1. Read all entries, identify the LATEST compact_summary
        #      marker (everything before it has been folded into a
        #      summary on a previous turn).
        #   2. Build effective history = [summary as system] + raw
        #      user/assistant turns AFTER the marker. If no marker,
        #      use all raw user/assistant turns.
        # Dedup trailing turn against current message in case the
        # frontend's fire-and-forget persist beat us to the file.
        raw_entries: list[dict] = []
        if session_id:
            try:
                from agent.finance.chat_sessions import (
                    _session_path,
                    _validate_session_id,
                )
                sid_validated = _validate_session_id(session_id)
                spath = _session_path(pid, sid_validated)
                if spath.exists():
                    with spath.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            if not isinstance(obj, dict):
                                continue
                            role = obj.get("role")
                            content = obj.get("content")
                            if role in ("user", "assistant") and isinstance(content, str):
                                raw_entries.append({"role": role, "content": content})
                            elif (
                                role == "system"
                                and isinstance(content, str)
                                and content.startswith(_COMPACT_MARKER_PREFIX)
                            ):
                                raw_entries.append({
                                    "role": "system",
                                    "content": content,
                                    "_compact": True,
                                })
            except Exception as exc:
                logger.warning(
                    "session history load failed for %s: %s; continuing without history",
                    session_id, exc,
                )

        last_compact_idx = -1
        for i, e in enumerate(raw_entries):
            if e.get("_compact"):
                last_compact_idx = i

        if last_compact_idx >= 0:
            history = [{
                "role": "system",
                "content": raw_entries[last_compact_idx]["content"],
            }]
            for e in raw_entries[last_compact_idx + 1:]:
                if e["role"] in ("user", "assistant"):
                    history.append({"role": e["role"], "content": e["content"]})
        else:
            history = [
                {"role": e["role"], "content": e["content"]}
                for e in raw_entries
                if e["role"] in ("user", "assistant")
            ]

        if (
            history
            and history[-1]["role"] == "user"
            and history[-1]["content"] == message
        ):
            history.pop()

        # Auto-compact when the next call would push prompt tokens
        # over _COMPACT_TRIGGER_PCT of the model's context window.
        # Only attempt once per turn — if it fails we fall back to
        # drop-oldest (lossy buffer-window). Need at least
        # _COMPACT_KEEP_RECENT_MSGS + 1 messages of history before it
        # makes sense to summarize.
        compacted_this_turn = False
        candidate = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": message},
        ]
        max_ctx = get_active_max_context("neomind")
        if (
            session_id
            and len(history) > _COMPACT_KEEP_RECENT_MSGS
            and _estimate_tokens(candidate) > _COMPACT_TRIGGER_PCT * max_ctx
        ):
            old = history[:-_COMPACT_KEEP_RECENT_MSGS]
            recent = history[-_COMPACT_KEEP_RECENT_MSGS:]
            summary = await _summarize_history(old, api_key, model)
            if summary:
                try:
                    _persist_compact_summary(pid, session_id, summary, len(old))
                    history = [{
                        "role": "system",
                        "content": _COMPACT_MARKER_PREFIX + summary,
                    }] + recent
                    compacted_this_turn = True
                    logger.info(
                        "auto-compacted session %s: %d old msgs summarized into %d chars",
                        session_id, len(old), len(summary),
                    )
                except Exception as exc:
                    logger.warning("compact persist failed for %s: %s", session_id, exc)
            else:
                # Fallback: drop oldest 12 messages (lossy buffer-window)
                history = history[_COMPACT_KEEP_RECENT_MSGS:]
                logger.warning(
                    "auto-compact summarize failed for %s; fell back to drop-oldest %d msgs",
                    session_id, _COMPACT_KEEP_RECENT_MSGS,
                )

        messages = [
            {"role": "system", "content": system_prompt},
            *history,
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
            # Tool-dispatch loop: each iteration is one LLM call. If
            # the LLM emits tool_calls (finish_reason="tool_calls") we
            # execute them, append results, and loop. If it emits a
            # plain message (finish_reason="stop") we break. Cap at
            # _MAX_TOOL_ITERATIONS to avoid runaway loops where a
            # broken tool keeps getting retried.
            full_content: list[str] = []
            usage: Dict[str, Any] = {}
            finish_reason: str | None = None
            iter_messages = list(messages)  # mutated across iterations
            t0 = time.monotonic()
            iteration = 0

            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None)) as client:
                    while iteration < _MAX_TOOL_ITERATIONS:
                        iteration += 1
                        # Per-iteration buffers
                        iter_content: list[str] = []
                        # DeepSeek v4 thinking-mode REQUIRES the
                        # reasoning_content of the previous assistant
                        # turn to be passed back on subsequent calls
                        # (see api-docs.deepseek.com/guides/thinking_mode
                        # + litellm issue #26395). Without this the
                        # next iteration fails with HTTP 400 "The
                        # reasoning_content in the thinking mode must
                        # be passed back to the API." Other vendors
                        # (OpenAI/Anthropic) ignore the extra field.
                        iter_reasoning: list[str] = []
                        # tool_calls in DeepSeek/OpenAI streaming arrive
                        # in pieces — each chunk has delta.tool_calls
                        # which is a list of partial entries indexed by
                        # `index`. We accumulate by index until done.
                        accumulated_tcs: dict[int, dict] = {}
                        iter_finish_reason: str | None = None

                        logger.info(
                            "chat_stream iter %d: sending to deepseek with %d msgs, %d tools",
                            iteration, len(iter_messages), len(_FIN_TOOLS),
                        )
                        async with client.stream(
                            "POST",
                            _DEEPSEEK_URL,
                            json={
                                "model": model,
                                "messages": iter_messages,
                                "tools": _FIN_TOOLS,
                                "tool_choice": "auto",
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
                                        iter_content.append(token)
                                        full_content.append(token)
                                        yield {
                                            "event": "delta",
                                            "data": json.dumps({"content": token}),
                                        }
                                    rc = delta.get("reasoning_content") or ""
                                    if rc:
                                        iter_reasoning.append(rc)
                                    tcs = delta.get("tool_calls")
                                    if tcs:
                                        for tc in tcs:
                                            idx = tc.get("index", 0)
                                            slot = accumulated_tcs.setdefault(
                                                idx,
                                                {"id": "", "name": "", "args": ""},
                                            )
                                            if tc.get("id"):
                                                slot["id"] = tc["id"]
                                            fn = tc.get("function") or {}
                                            if fn.get("name"):
                                                slot["name"] += fn["name"]
                                            if fn.get("arguments"):
                                                slot["args"] += fn["arguments"]
                                    fr = choices[0].get("finish_reason")
                                    if fr:
                                        iter_finish_reason = fr
                                u = chunk.get("usage")
                                if u:
                                    usage = u

                        finish_reason = iter_finish_reason

                        if iter_finish_reason != "tool_calls" or not accumulated_tcs:
                            # Normal final assistant message — done
                            break

                        # The LLM wants tools. Append the assistant
                        # message (with tool_calls) and execute each
                        # tool, appending its result, then loop for
                        # the next LLM call.
                        tool_calls_for_msg = []
                        for idx in sorted(accumulated_tcs.keys()):
                            slot = accumulated_tcs[idx]
                            tool_calls_for_msg.append({
                                "id": slot["id"] or f"call_{iteration}_{idx}",
                                "type": "function",
                                "function": {
                                    "name": slot["name"],
                                    "arguments": slot["args"] or "{}",
                                },
                            })
                        assistant_turn = {
                            "role": "assistant",
                            "content": "".join(iter_content) or None,
                            "tool_calls": tool_calls_for_msg,
                        }
                        if iter_reasoning:
                            # DeepSeek thinking-mode requires this on
                            # subsequent turns; OpenAI/Anthropic ignore
                            assistant_turn["reasoning_content"] = "".join(iter_reasoning)
                        iter_messages.append(assistant_turn)

                        for tc_msg in tool_calls_for_msg:
                            name = tc_msg["function"]["name"]
                            raw_args = tc_msg["function"]["arguments"]
                            try:
                                args = json.loads(raw_args) if raw_args else {}
                            except Exception:
                                args = {}
                            yield {
                                "event": "tool_call_start",
                                "data": json.dumps({
                                    "name": name,
                                    "args": args,
                                }, ensure_ascii=False),
                            }
                            t_tool = time.monotonic()
                            tool_result = await _execute_tool(name, args)
                            tool_dur_ms = int((time.monotonic() - t_tool) * 1000)
                            iter_messages.append({
                                "role": "tool",
                                "tool_call_id": tc_msg["id"],
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            })
                            yield {
                                "event": "tool_call_result",
                                "data": json.dumps({
                                    "name": name,
                                    "ok": bool(tool_result.get("ok")),
                                    "duration_ms": tool_dur_ms,
                                    "error": tool_result.get("error"),
                                }, ensure_ascii=False),
                            }
                        # loop continues — next LLM call sees tool results

                    if iteration >= _MAX_TOOL_ITERATIONS and finish_reason == "tool_calls":
                        logger.warning(
                            "chat_stream: hit MAX_TOOL_ITERATIONS=%d for session %s; "
                            "stopping tool loop and returning what we have",
                            _MAX_TOOL_ITERATIONS, session_id,
                        )
                        yield {
                            "event": "delta",
                            "data": json.dumps({"content": (
                                "\n\n[hit max tool-call depth — stopping. "
                                "Try rephrasing or asking step-by-step.]"
                            )}),
                        }
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

            # Final marker carries req_id so UI can link to audit entry,
            # plus token usage so the chat header can show the context-
            # window status bar (cumulative prompt tokens vs model's
            # advertised max_context — single source via constants.models
            # so both CLI and web see the same budget).
            yield {
                "event": "done",
                "data": json.dumps({
                    "req_id": req_id,
                    "duration_ms": duration_ms,
                    "total_tokens": (usage or {}).get("total_tokens"),
                    "prompt_tokens": (usage or {}).get("prompt_tokens"),
                    "max_context": get_active_max_context("neomind"),
                    "compacted": compacted_this_turn,
                    "content_length": len(final_content),
                }),
            }

        return EventSourceResponse(event_generator())

    return router
