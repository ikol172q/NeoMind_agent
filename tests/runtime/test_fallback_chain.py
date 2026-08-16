"""Phase 5 — the provider chain, lifted out of the Telegram turn loop.

The behaviour these pin down was previously reachable only by taking a real
provider down mid-conversation, so none of it was tested.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.runtime.llm_stream import (
    FinishChunk,
    LLMAuthError,
    LLMRateLimited,
    LLMTransportError,
    TextChunk,
    parse_retry_after,
)
from agent.runtime.providers.fallback import (
    BACKOFF_CEILING,
    AllProvidersFailed,
    ChainLink,
    FallbackChain,
)


class FakeLLM:
    """A provider that does whatever the script says, and records its calls."""

    def __init__(self, *, chunks=None, raises=None, raise_after=0):
        self.chunks = chunks or []
        self.raises = raises
        self.raise_after = raise_after
        self.calls = 0
        self.models = []

    def stream(self, messages, model, **kwargs):
        self.calls += 1
        self.models.append(model)

        async def gen():
            for i, chunk in enumerate(self.chunks):
                if self.raises and i == self.raise_after:
                    raise self.raises
                yield chunk
            if self.raises and self.raise_after >= len(self.chunks):
                raise self.raises

        return gen()


class Clock:
    def __init__(self):
        self.slept = []

    async def sleep(self, seconds):
        self.slept.append(seconds)


def drain(chain, **kw):
    async def go():
        return [c async for c in chain.stream([{"role": "user", "content": "hi"}], "m", **kw)]

    return asyncio.run(go())


def ok(text="hello"):
    return FakeLLM(chunks=[TextChunk(text=text), FinishChunk(reason="stop")])


class TestOrder:

    def test_the_first_working_provider_answers(self):
        first, second = ok("from first"), ok("from second")
        chunks = drain(FallbackChain([ChainLink(first, "a"), ChainLink(second, "b")]))
        assert chunks[0].text == "from first"
        assert second.calls == 0, "a working first provider must end the search"

    def test_a_dead_provider_is_skipped(self):
        dead = FakeLLM(raises=LLMTransportError("connection refused"))
        alive = ok("from second")
        chunks = drain(FallbackChain([ChainLink(dead, "a"), ChainLink(alive, "b")]))
        assert chunks[0].text == "from second"

    def test_each_link_is_asked_for_its_own_model(self):
        """The chain is a list of provider+model pairs, not one model tried
        against several hosts."""
        dead = FakeLLM(raises=LLMTransportError("down"))
        alive = ok()
        drain(FallbackChain([ChainLink(dead, "model-a"), ChainLink(alive, "model-b")]))
        assert dead.models == ["model-a"]
        assert alive.models == ["model-b"]

    def test_an_empty_chain_is_rejected_at_construction(self):
        with pytest.raises(ValueError):
            FallbackChain([])


class TestNoFailoverMidStream:
    """The rule that makes the chain safe to put in front of a live UI."""

    def test_a_failure_after_the_first_chunk_is_not_retried_elsewhere(self):
        broken = FakeLLM(
            chunks=[TextChunk(text="I was saying so")],
            raises=LLMTransportError("connection reset"),
            raise_after=1,
        )
        backup = ok("completely different answer")
        chain = FallbackChain([ChainLink(broken, "a"), ChainLink(backup, "b")])

        async def go():
            seen = []
            with pytest.raises(LLMTransportError):
                async for chunk in chain.stream([], "m"):
                    seen.append(chunk)
            return seen

        seen = asyncio.run(go())
        assert seen[0].text == "I was saying so"
        assert backup.calls == 0, (
            "restarting on another provider would replay the answer the user "
            "has already read"
        )

    def test_a_failure_before_any_chunk_does_fail_over(self):
        broken = FakeLLM(chunks=[], raises=LLMTransportError("refused"))
        backup = ok("backup answer")
        chunks = drain(FallbackChain([ChainLink(broken, "a"), ChainLink(backup, "b")]))
        assert chunks[0].text == "backup answer"


class TestRateLimits:

    def test_429_retries_the_same_provider_before_advancing(self):
        """A one-entry chain has nowhere to advance to, which is the usual
        shape here: the local router is the only provider."""
        limited = FakeLLM(raises=LLMRateLimited("slow down"))
        clock = Clock()
        chain = FallbackChain([ChainLink(limited, "a")], sleep=clock.sleep)
        with pytest.raises(AllProvidersFailed):
            drain(chain)
        assert limited.calls == 3, "initial attempt plus two retries"
        assert len(clock.slept) == 2

    def test_retry_after_is_honoured(self):
        limited = FakeLLM(raises=LLMRateLimited("slow", retry_after=7.0))
        clock = Clock()
        chain = FallbackChain([ChainLink(limited, "a")], sleep=clock.sleep)
        with pytest.raises(AllProvidersFailed):
            drain(chain)
        assert clock.slept == [7.0, 7.0]

    def test_backoff_grows_when_the_server_says_nothing(self):
        limited = FakeLLM(raises=LLMRateLimited("slow"))
        clock = Clock()
        chain = FallbackChain([ChainLink(limited, "a")], sleep=clock.sleep)
        with pytest.raises(AllProvidersFailed):
            drain(chain)
        assert clock.slept[1] > clock.slept[0]

    def test_an_absurd_retry_after_is_capped(self):
        """A provider asking for five minutes is asking for longer than
        anyone will sit in front of a chat window."""
        limited = FakeLLM(raises=LLMRateLimited("slow", retry_after=600.0))
        clock = Clock()
        chain = FallbackChain([ChainLink(limited, "a")], sleep=clock.sleep)
        with pytest.raises(AllProvidersFailed):
            drain(chain)
        assert max(clock.slept) == BACKOFF_CEILING

    def test_a_recovered_provider_is_used(self):
        class Flaky:
            def __init__(self):
                self.calls = 0

            def stream(self, messages, model, **kwargs):
                self.calls += 1
                first = self.calls == 1

                async def gen():
                    if first:
                        raise LLMRateLimited("slow down")
                    yield TextChunk(text="recovered")
                    yield FinishChunk(reason="stop")

                return gen()

        flaky = Flaky()
        chunks = drain(FallbackChain([ChainLink(flaky, "a")], sleep=Clock().sleep))
        assert chunks[0].text == "recovered"


class TestNonRetryable:

    def test_a_bad_key_advances_immediately(self):
        """Retrying a 401 just burns the rate limit against a key that will
        never work."""
        bad = FakeLLM(raises=LLMAuthError("invalid api key"))
        alive = ok()
        clock = Clock()
        drain(FallbackChain([ChainLink(bad, "a"), ChainLink(alive, "b")], sleep=clock.sleep))
        assert bad.calls == 1
        assert clock.slept == [], "no backoff for an error that will not heal"


class TestExhaustion:

    def test_the_last_real_error_is_what_surfaces(self):
        """'All providers failed' sends nobody anywhere. 'HTTP 401' does."""
        a = FakeLLM(raises=LLMTransportError("refused"))
        b = FakeLLM(raises=LLMAuthError("invalid api key"))
        chain = FallbackChain([ChainLink(a, "a", "local"), ChainLink(b, "b", "remote")])
        with pytest.raises(AllProvidersFailed) as caught:
            drain(chain)
        err = caught.value
        assert err.code == "llm_auth"
        assert err.retryable is False
        assert len(err.failures) == 2

    def test_the_message_names_every_provider_that_failed(self):
        a = FakeLLM(raises=LLMTransportError("refused"))
        b = FakeLLM(raises=LLMAuthError("bad key"))
        chain = FallbackChain([ChainLink(a, "m1", "local"), ChainLink(b, "m2", "remote")])
        with pytest.raises(AllProvidersFailed) as caught:
            drain(chain)
        text = str(caught.value)
        assert "local:m1" in text and "remote:m2" in text

    def test_attributions_are_not_misaligned_by_retries(self):
        """One link can fail three times; pairing errors with links by
        position would blame the wrong provider."""
        a = FakeLLM(raises=LLMRateLimited("slow"))
        b = FakeLLM(raises=LLMAuthError("bad key"))
        chain = FallbackChain(
            [ChainLink(a, "m1", "local"), ChainLink(b, "m2", "remote")],
            sleep=Clock().sleep,
        )
        with pytest.raises(AllProvidersFailed) as caught:
            drain(chain)
        text = str(caught.value)
        assert text.count("local:m1") == 3
        assert text.count("remote:m2") == 1
        assert "remote:m2 → llm_auth" in text


class TestObservation:
    """Usage accounting has to know which provider actually answered."""

    def test_the_selected_provider_is_reported_once(self):
        selected = []
        dead = FakeLLM(raises=LLMTransportError("down"))
        alive = ok()
        chain = FallbackChain(
            [ChainLink(dead, "a", "first"), ChainLink(alive, "b", "second")],
            on_selected=selected.append,
        )
        drain(chain)
        assert [link.name for link in selected] == ["second"]

    def test_nothing_is_reported_as_selected_when_all_fail(self):
        selected = []
        chain = FallbackChain(
            [ChainLink(FakeLLM(raises=LLMAuthError("no")), "a")],
            on_selected=selected.append,
        )
        with pytest.raises(AllProvidersFailed):
            drain(chain)
        assert selected == []

    def test_failures_are_reported_as_they_happen(self):
        seen = []
        chain = FallbackChain(
            [ChainLink(FakeLLM(raises=LLMTransportError("down")), "a", "first"),
             ChainLink(ok(), "b", "second")],
            on_failure=lambda link, exc: seen.append((link.name, exc.code)),
        )
        drain(chain)
        assert seen == [("first", "llm_transport")]


class TestRetryAfterParsing:

    @pytest.mark.parametrize("raw,expected", [
        ("5", 5.0),
        ("2.5", 2.5),
        (7, 7.0),
        (None, None),
        ("", None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),  # HTTP-date form: not honoured
        ("-3", None),
    ])
    def test_header_forms(self, raw, expected):
        assert parse_retry_after(raw) == expected
