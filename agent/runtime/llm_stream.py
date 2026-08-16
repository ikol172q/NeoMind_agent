"""Provider-neutral streaming chunks and errors.

This is the vocabulary `LLMPort` speaks. It sits one level below
`agent/runtime/events.py`: a port yields *chunks*, and the session turns
chunks into events. Keeping them separate is what lets a provider adapter
exist without knowing about sessions, turns or sequence numbers.

Two things the baseline got wrong are fixed by the shape here.

`code_commands.stream_response()` interleaved SSE framing, JSON decoding,
DeepSeek's `reasoning_content` field, DeepSeek's thinking end-token, ANSI
writes to stderr and spinner callbacks inside one loop, so nothing could
consume the stream without also owning a terminal. Chunks carry no
presentation.

Failures were strings printed at the point of failure — a caller could not
tell a timeout from a 401 from a malformed body without matching on prose.
They are exceptions here, each with a stable `code` and an explicit
`retryable`, because "should I retry this" is a decision the runtime has to
make and prose cannot answer.

Usage is a chunk rather than a return value on purpose. Providers send it in
the final SSE frame, and the existing code ignored it and re-estimated both
counts locally with tiktoken (`count_conversation_tokens()` /
`count_tokens(full_response)`), which is what `/cost` has been reporting.
Surfacing what the provider actually said lets that be corrected later
without another extraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


# ── Chunks ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StreamChunk:
    """Base. Frozen for the same reason runtime events are frozen."""

    @property
    def kind(self) -> str:
        return _CHUNK_KINDS.get(type(self), type(self).__name__)


@dataclass(frozen=True)
class TextChunk(StreamChunk):
    """A piece of the assistant's answer, as it arrived.

    One SSE frame's worth — not an accumulated buffer. A port that yields the
    finished string as a single chunk is not streaming, which is precisely why
    nothing built on the old QueryEngine could render progressively.
    """

    text: str = ""


@dataclass(frozen=True)
class ThinkingChunk(StreamChunk):
    """Reasoning text, where the provider exposes it separately.

    Provider-specific in origin (DeepSeek's `reasoning_content`), neutral by
    the time it gets here. Adapters for providers without a reasoning channel
    simply never yield this.
    """

    text: str = ""


@dataclass(frozen=True)
class UsageChunk(StreamChunk):
    """Token accounting as reported by the provider.

    `raw` keeps the untouched payload: providers add fields (cached tokens,
    reasoning tokens) at different times, and dropping them at the boundary
    means re-plumbing later to get them back.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinishChunk(StreamChunk):
    """Terminal chunk. `reason` is the provider's finish_reason, verbatim.

    Emitted exactly once per successful stream, last. A stream that ends
    without it ended abnormally, and a consumer is entitled to treat the
    absence as truncation rather than guessing.
    """

    reason: str = ""


_CHUNK_KINDS = {
    TextChunk: "text",
    ThinkingChunk: "thinking",
    UsageChunk: "usage",
    FinishChunk: "finish",
}


# ── Errors ────────────────────────────────────────────────────────────────


class LLMStreamError(Exception):
    """Base for anything that stops a stream.

    `retryable` is the whole point: the runtime has to decide whether to try
    again, and a 401 and a read timeout are both "an error string" to the
    caller unless the distinction is carried in the type.
    """

    code = "llm_error"
    retryable = False

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class LLMTimeout(LLMStreamError):
    code = "llm_timeout"
    retryable = True


class LLMTransportError(LLMStreamError):
    """Connection refused, DNS failure, connection reset mid-stream."""

    code = "llm_transport"
    retryable = True


class LLMAuthError(LLMStreamError):
    """401/403. Never retried — retrying a bad key just burns the rate limit."""

    code = "llm_auth"
    retryable = False


class LLMRateLimited(LLMStreamError):
    """429. Carries `Retry-After` when the server sent one.

    Without it the only option is a guessed backoff, and a guess that is too
    short spends the next attempt getting rate-limited again.
    """

    code = "llm_rate_limited"
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message, status=status)
        self.retry_after = retry_after


class LLMHTTPError(LLMStreamError):
    """Any other non-200. 5xx is retryable, 4xx is not."""

    code = "llm_http"

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message, status=status)
        self.retryable = status >= 500


class LLMProtocolError(LLMStreamError):
    """The body did not look like the SSE stream it claimed to be.

    Not retryable: a malformed frame from a healthy connection is a bug
    somewhere, and retrying hides it.
    """

    code = "llm_protocol"
    retryable = False


def parse_retry_after(value: Any) -> Optional[float]:
    """Read a `Retry-After` header, as seconds.

    Only the delta-seconds form is honoured. The HTTP-date form is legal but
    needs a clock comparison, and a misparsed date that lands far in the future
    would stall a turn for longer than any caller would accept — falling back
    to the caller's own backoff is the safer failure.
    """
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


def error_for_status(
    status: int, body: str, retry_after: Any = None
) -> LLMStreamError:
    """Map an HTTP status onto the right typed error."""
    snippet = body.strip()[:200]
    if status in (401, 403):
        return LLMAuthError(
            f"API authentication failed (HTTP {status}): {snippet}", status=status
        )
    if status == 429:
        return LLMRateLimited(
            f"Rate limited (HTTP 429): {snippet}",
            status=status,
            retry_after=parse_retry_after(retry_after),
        )
    return LLMHTTPError(f"HTTP {status}: {snippet}", status=status)
