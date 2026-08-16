"""Try several providers in order, with backoff on rate limits.

The Telegram bot has always had this: a chain of providers, each tried until
one answers, with 429 retried against the *same* provider before moving on —
which matters when the chain has one entry (the local router) and advancing
means having nothing left to advance to.

It lived inline in a 436-line method, so nothing else could use it and nothing
could test it. Here it is an `LLMPort` that wraps other `LLMPort`s, which means
the session cannot tell the difference between this and a single provider.

The one rule that makes it safe:

    Failover is only legal before the first chunk.

Once a token has been yielded, the user has seen it. Restarting on another
provider would replay the answer from the beginning, so a mid-stream failure
propagates instead — the caller keeps the partial text, which is what the
renderer already does with a `TurnFailed` after `TextDelta`s.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Sequence

from agent.runtime.llm_stream import (
    LLMRateLimited,
    LLMStreamError,
    StreamChunk,
)

#: How many times one provider is retried on 429 before the chain advances.
DEFAULT_MAX_RATE_LIMIT_RETRIES = 2

#: Never wait longer than this between attempts, whatever `Retry-After` says.
#: A provider asking for five minutes is asking for longer than any user will
#: sit in front of a chat window.
BACKOFF_CEILING = 30.0


@dataclass
class ChainLink:
    """One provider in the chain, with the model to ask it for."""

    llm: Any
    model: str = ""
    name: str = ""

    def label(self) -> str:
        return f"{self.name or 'provider'}:{self.model or 'default'}"


class AllProvidersFailed(LLMStreamError):
    """Every link failed. Carries the last real error so the code is useful.

    Reported as whatever the final provider said rather than a generic
    "all failed", because "HTTP 401" and "connection refused" send the
    operator to completely different places.
    """

    code = "llm_all_providers_failed"
    retryable = True

    def __init__(self, message: str, *, failures: Sequence[LLMStreamError] = ()) -> None:
        super().__init__(message)
        self.failures = list(failures)
        last = self.failures[-1] if self.failures else None
        if last is not None:
            self.code = last.code
            self.retryable = last.retryable
            self.status = last.status


class FallbackChain:
    """An `LLMPort` that tries each provider in turn.

    `sleep` is injected so the backoff can be asserted without a test that
    actually waits thirty seconds.
    """

    def __init__(
        self,
        links: Sequence[ChainLink],
        *,
        max_rate_limit_retries: int = DEFAULT_MAX_RATE_LIMIT_RETRIES,
        sleep: Optional[Callable[[float], Any]] = None,
        on_selected: Optional[Callable[[ChainLink], None]] = None,
        on_failure: Optional[Callable[[ChainLink, LLMStreamError], None]] = None,
    ) -> None:
        if not links:
            raise ValueError("a fallback chain needs at least one provider")
        self.links = list(links)
        self.max_rate_limit_retries = max_rate_limit_retries
        self._sleep = sleep or asyncio.sleep
        self._on_selected = on_selected
        self._on_failure = on_failure

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        failures: List[LLMStreamError] = []
        # Kept alongside the errors: one link can fail several times (a 429
        # retried twice), so the two lists do not line up positionally and
        # zipping them would mislabel which provider said what.
        attributions: List[str] = []

        for link in self.links:
            attempt = 0
            while True:
                started = False
                try:
                    stream = link.llm.stream(
                        messages, link.model or model, **kwargs
                    )
                    async for chunk in stream:
                        if not started:
                            started = True
                            # Committed. From here the answer belongs to this
                            # provider, whatever happens next.
                            if self._on_selected:
                                self._on_selected(link)
                        yield chunk
                    return

                except LLMStreamError as exc:
                    if started:
                        # Mid-stream. The user has already seen part of this
                        # answer; another provider would start it over.
                        raise
                    failures.append(exc)
                    attributions.append(f"{link.label()} → {exc.code}")
                    if self._on_failure:
                        self._on_failure(link, exc)

                    if (
                        isinstance(exc, LLMRateLimited)
                        and attempt < self.max_rate_limit_retries
                    ):
                        await self._sleep(self._backoff(exc, attempt))
                        attempt += 1
                        continue  # same provider — advancing may have nowhere to go

                    break  # next provider

        raise AllProvidersFailed(
            "all providers failed: " + "; ".join(attributions),
            failures=failures,
        )

    def _backoff(self, exc: LLMRateLimited, attempt: int) -> float:
        """Honour `Retry-After`, else double each time, never past the ceiling."""
        requested = getattr(exc, "retry_after", None)
        if requested is None:
            requested = 5.0 * (2**attempt)
        return min(float(requested), BACKOFF_CEILING)
