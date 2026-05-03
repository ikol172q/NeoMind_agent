"""LLM extraction base — strict JSON, no fabrication channels.

Each extractor in this package follows the same shape:

    1. Receive isolated source text (no ticker name, no metadata)
    2. Send to LLM with a *strict* system prompt + structured-output
       instruction
    3. Get back JSON, parse
    4. Caller hands result to validation.validate_quotes()

The LLM never sees more than the document section it's extracting
from — preventing it from "borrowing" memory about the ticker.
Strict JSON Schema (DeepSeek's response_format) forbids extra fields,
so the LLM can't smuggle reasoning into a free-text "note".
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Same router NeoMind already uses (LLM_ROUTER_BASE_URL points at the
# local litellm proxy at :8000/v1, which fans out to DeepSeek).
_BASE = os.getenv("LLM_ROUTER_BASE_URL") or "http://127.0.0.1:8000/v1"
_KEY = os.getenv("LLM_ROUTER_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "dummy"
_MODEL = os.getenv("STOCK_RESEARCH_MODEL") or "deepseek-v4-flash"
_TIMEOUT_S = 180.0


def call_strict_json(
    *,
    system_prompt: str,
    user_content: str,
    json_schema: dict[str, Any],
    schema_name: str,
    max_tokens: int = 2000,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Call LLM with JSON-mode output, schema embedded in prompt.

    DeepSeek does not yet support OpenAI-style ``response_format.type =
    json_schema`` strict mode (returns 400). We fall back to
    ``json_object`` mode (free-form JSON) + injecting the schema text
    into the system prompt. The downstream verbatim-quote validator
    is the real correctness gate; even with extra fabricated fields
    in the JSON, items without a verifiable quote still get dropped.

    Raises HTTPException on transport / parse failure.
    """
    schema_str = json.dumps(json_schema, indent=2)
    sys_with_schema = (
        system_prompt
        + "\n\nOutput must be a JSON object matching this schema "
        f"(extra fields will be ignored):\n{schema_str}"
    )
    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": sys_with_schema},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(_TIMEOUT_S)) as c:
            r = c.post(
                f"{_BASE.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {_KEY}",
                         "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"extractor LLM call failed: {exc}")
    try:
        raw = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise HTTPException(502, f"extractor: malformed LLM response: {exc}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # If strict-mode is honored this should never happen; we still
        # log defensively because providers vary.
        logger.warning("extractor: non-JSON output (first 300 chars): %s",
                       (raw or "")[:300])
        raise HTTPException(502, f"extractor: non-JSON output ({exc})")
