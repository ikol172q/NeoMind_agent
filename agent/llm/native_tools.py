"""Native tool-calling bridge (model-agnostic, opt-in).

Bridges a provider's NATIVE tool-calling (OpenAI-style structured `tool_calls`)
back into NeoMind's existing text-based agentic loop **without changing the
loop**. The loop keeps regex-parsing ``<tool_call>{...}</tool_call>`` — we just
hand it a guaranteed-well-formed block synthesized from the structured call.

Why this matters (the reliability win): for large payloads — e.g. a Write/Edit
``new_content`` with newlines, quotes and braces — the model's *free-text*
``<tool_call>`` is often malformed JSON and the regex parse silently fails.
Native tool-calling returns the arguments as an **API-validated JSON object**;
``json.dumps`` re-serializes it (escaping ``\\n`` etc.) into a single-line block
the parser always parses.

Gated by :mod:`agent.llm.model_capabilities` + the ``NEOMIND_NATIVE_TOOLS`` env
flag, so the default — and any non-native / swapped model — keeps the old regex
path untouched. This module is a pure bridge: no I/O, no model calls.
"""
from __future__ import annotations

import json
from typing import Any


def synthesize_tool_call_text(name: str, arguments: Any) -> str:
    """Turn a native tool call (``name`` + ``arguments``) into a ``<tool_call>``
    block that NeoMind's ToolCallParser parses reliably.

    ``arguments`` may be the JSON string from ``function.arguments`` or an
    already-parsed dict. It is re-serialized with ``json.dumps`` → fully
    escaped, single line → always regex-extractable + json-loadable.
    """
    if isinstance(arguments, str):
        try:
            params = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            # Defensive: provider returned non-JSON args — pass through as a
            # single param rather than crashing the loop.
            params = {"_raw": arguments}
    elif isinstance(arguments, dict):
        params = arguments
    else:
        params = {}
    payload = {"tool": name, "params": params}
    return "<tool_call>" + json.dumps(payload, ensure_ascii=False) + "</tool_call>"


def accumulate_tool_call_deltas(accumulated: dict, tool_call_deltas: list | None) -> None:
    """Accumulate streaming ``delta.tool_calls`` by index, in place.

    Mirrors agent/finance/chat_streaming.py's proven accumulation:
    ``accumulated`` maps ``index -> {"id","name","args"}``.
    """
    for tc in tool_call_deltas or []:
        idx = tc.get("index", 0)
        slot = accumulated.setdefault(idx, {"id": "", "name": "", "args": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] += fn["name"]
        if fn.get("arguments"):
            slot["args"] += fn["arguments"]


def synthesize_from_accumulated(accumulated: dict) -> str:
    """Build the ``<tool_call>`` text from accumulated streaming deltas.

    Only the FIRST tool call is used — the agentic loop executes one tool per
    turn (ToolCallParser also only extracts the first). Returns "" if none.
    """
    if not accumulated:
        return ""
    first = accumulated[min(accumulated)]
    if not first.get("name"):
        return ""
    return synthesize_tool_call_text(first["name"], first.get("args", ""))
