"""OpenAI-compatible SSE streaming, as an `LLMPort`.

DeepSeek, z.ai and the local LiteLLM router all speak the OpenAI chat
completions wire format, so one adapter covers them; the vendor-specific parts
are named and isolated below rather than spread through a loop.

What this replaces
------------------
`code_commands.stream_response()` interleaved, in a single `for line in
response.iter_lines()` body: SSE framing, JSON decoding, DeepSeek's
`reasoning_content` field, DeepSeek's thinking end-token, spinner callbacks,
`sys.stderr.write("\\r\\033[K")` and `print()` with ANSI colour. Nothing could
consume that stream without also owning a terminal, and the parsing could not
be tested without one either.

Parsing is split in two on purpose. `parse_sse_frame()` is a pure function over
one decoded line, so recorded fixtures can be replayed with no client, no event
loop and no network; `OpenAICompatibleStream.stream()` only adds transport.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, Iterable, List, Mapping, Optional

from agent.runtime.llm_stream import (
    FinishChunk,
    LLMProtocolError,
    LLMStreamError,
    LLMTimeout,
    LLMTransportError,
    StreamChunk,
    TextChunk,
    ThinkingChunk,
    UsageChunk,
    error_for_status,
)

__all__ = [
    "DONE_SENTINEL",
    "THINKING_END_TOKENS",
    "OpenAICompatibleStream",
    "parse_sse_frame",
]

DONE_SENTINEL = "[DONE]"

#: DeepSeek emits its end-of-thinking marker inside normal content. Both
#: variants occur in the wild — the first uses fullwidth vertical bars, the
#: second ASCII ones — and the baseline stripped both, so both stay stripped.
THINKING_END_TOKENS = (
    "<｜end▁of▁thinking｜>",
    "<|end▁of▁thinking|>",
)


def _strip_thinking_markers(text: str) -> str:
    for token in THINKING_END_TOKENS:
        text = text.replace(token, "")
    return text


def parse_sse_frame(line: str) -> List[StreamChunk]:
    """Turn one decoded SSE line into zero or more chunks.

    Pure: no I/O, no state, no clock. A frame can legitimately produce more
    than one chunk — a final frame often carries both a finish_reason and
    usage — so the return is a list rather than an Optional.

    Raises `LLMProtocolError` on a `data:` payload that is not JSON. The
    baseline swallowed those in a bare `except`, which turned a malformed
    stream into a silently truncated answer.
    """
    line = line.strip()
    if not line or line.startswith(":"):
        return []  # keep-alive comment or blank separator
    if not line.startswith("data:"):
        return []  # `event:` / `id:` fields carry nothing we consume
    payload = line[len("data:"):].strip()
    if payload == DONE_SENTINEL:
        return []

    try:
        frame = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise LLMProtocolError(f"malformed SSE data frame: {exc}") from exc
    if not isinstance(frame, dict):
        raise LLMProtocolError(f"SSE data frame was {type(frame).__name__}, not an object")

    chunks: List[StreamChunk] = []

    choices = frame.get("choices") or []
    if choices:
        choice = choices[0] or {}
        delta = choice.get("delta") or {}

        # Vendor field: DeepSeek separates reasoning from the answer. Providers
        # without it simply never set it, and no ThinkingChunk is produced.
        reasoning = delta.get("reasoning_content")
        if reasoning:
            chunks.append(ThinkingChunk(text=reasoning))

        content = delta.get("content")
        if content:
            cleaned = _strip_thinking_markers(content)
            # Emit whenever anything survives, and stay silent only when the
            # marker was the entire delta. The baseline used
            # `if not content.strip(): continue`, which also dropped genuine
            # whitespace-only deltas — a "\n\n" between paragraphs vanished and
            # the rendered text ran together.
            if cleaned:
                chunks.append(TextChunk(text=cleaned))

        finish_reason = choice.get("finish_reason")
        if finish_reason:
            chunks.append(FinishChunk(reason=finish_reason))

    usage = frame.get("usage")
    if isinstance(usage, Mapping) and usage:
        chunks.append(
            UsageChunk(
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
                raw=dict(usage),
            )
        )

    return chunks


def parse_sse_lines(lines: Iterable[str]) -> List[StreamChunk]:
    """Replay a recorded stream. Used by fixtures and by callers with a body
    already in hand; `stream()` is the same logic plus a socket."""
    out: List[StreamChunk] = []
    for line in lines:
        out.extend(parse_sse_frame(line))
    return out


class OpenAICompatibleStream:
    """An `LLMPort` over an OpenAI-compatible `/chat/completions` endpoint.

    Async by way of httpx rather than `requests` + a worker thread: cancelling
    an `asyncio.to_thread()` does not stop a blocking `iter_lines()`, so the
    socket would stay open after a cancelled turn. Here the `async with`
    unwinds on `CancelledError` and closes the response, which is what the
    Phase 2 gate asks to be demonstrated rather than assumed.

    Emits no output. The only way anything reaches a terminal is if a caller
    renders the chunks.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 60.0,
        extra_headers: Optional[Mapping[str, str]] = None,
        client: Any = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})
        self._client = client  # injectable for tests; None means "make one"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        headers.update(self.extra_headers)
        return headers

    def build_payload(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Mirrors what `stream_response()` sends today.

        `thinking` is gated on the caller passing it, not on a provider-name
        string compared inside the adapter — the baseline's
        `provider.get("name") == "deepseek"` check meant an OpenAI-compatible
        endpoint serving a DeepSeek model could not enable it.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        for key in ("temperature", "max_tokens", "thinking", "stream_options"):
            if kwargs.get(key) is not None:
                payload[key] = kwargs[key]
        return payload

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        import httpx

        payload = self.build_payload(messages, model, **kwargs)
        client = self._client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=self.timeout)

        try:
            async with client.stream(
                "POST", self.base_url, headers=self._headers(), json=payload
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise error_for_status(
                        response.status_code,
                        body.decode("utf-8", errors="replace"),
                    )
                async for line in response.aiter_lines():
                    for chunk in parse_sse_frame(line):
                        yield chunk
        except LLMStreamError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"stream timed out after {self.timeout}s: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMTransportError(f"transport failure: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()
