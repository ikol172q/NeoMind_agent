"""Phase 2 gate — provider streaming behind `LLMPort`.

Each test here maps to a line of the Phase 2 done gate in
plans/2026-08-06_frontend-contract-cli-tui-decoupling-plan.md:

  * recorded SSE fixtures replay to the same ordered trace, deterministically
  * DeepSeek text *and* reasoning arrive through the port
  * a second provider fixture uses the same code with nothing swapped
  * cancelling closes the provider stream
  * the runtime writes nothing to a terminal
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import pytest

from agent.runtime.llm_stream import (
    FinishChunk,
    LLMAuthError,
    LLMHTTPError,
    LLMProtocolError,
    LLMRateLimited,
    LLMTimeout,
    LLMTransportError,
    TextChunk,
    ThinkingChunk,
    UsageChunk,
    error_for_status,
)
from agent.runtime.providers.openai_sse import (
    OpenAICompatibleStream,
    parse_sse_frame,
    parse_sse_lines,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def trace(chunks):
    """Compact, comparable shape of a stream: [(kind, payload), ...]."""
    out = []
    for c in chunks:
        if isinstance(c, (TextChunk, ThinkingChunk)):
            out.append((c.kind, c.text))
        elif isinstance(c, FinishChunk):
            out.append((c.kind, c.reason))
        elif isinstance(c, UsageChunk):
            out.append((c.kind, (c.prompt_tokens, c.completion_tokens, c.total_tokens)))
    return out


# ── Frame parsing ─────────────────────────────────────────────────────────


class TestFrameParsing:

    def test_blank_and_comment_lines_yield_nothing(self):
        assert parse_sse_frame("") == []
        assert parse_sse_frame(": keep-alive") == []

    def test_done_sentinel_yields_nothing(self):
        assert parse_sse_frame("data: [DONE]") == []

    def test_non_data_fields_are_ignored(self):
        assert parse_sse_frame("event: message") == []
        assert parse_sse_frame("id: 42") == []

    def test_text_delta(self):
        got = parse_sse_frame('data: {"choices":[{"delta":{"content":"hi"}}]}')
        assert got == [TextChunk(text="hi")]

    def test_reasoning_delta_becomes_thinking(self):
        got = parse_sse_frame('data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}')
        assert got == [ThinkingChunk(text="hmm")]

    def test_thinking_end_marker_is_stripped_and_produces_no_chunk(self):
        for token in ("<｜end▁of▁thinking｜>", "<|end▁of▁thinking|>"):
            frame = "data: " + json.dumps({"choices": [{"delta": {"content": token}}]})
            assert parse_sse_frame(frame) == [], f"{token!r} should vanish entirely"

    def test_marker_mixed_with_text_keeps_the_text(self):
        frame = "data: " + json.dumps(
            {"choices": [{"delta": {"content": "<｜end▁of▁thinking｜>Four."}}]}
        )
        assert parse_sse_frame(frame) == [TextChunk(text="Four.")]

    def test_whitespace_only_delta_survives(self):
        """The paragraph break the baseline dropped.

        stream_response() ran `if not content.strip(): continue` after
        stripping the marker, so a genuine "\\n\\n" delta was discarded and
        paragraphs ran together in the rendered answer.
        """
        frame = "data: " + json.dumps({"choices": [{"delta": {"content": "\n\n"}}]})
        assert parse_sse_frame(frame) == [TextChunk(text="\n\n")]

    def test_finish_reason(self):
        got = parse_sse_frame('data: {"choices":[{"delta":{},"finish_reason":"length"}]}')
        assert got == [FinishChunk(reason="length")]

    def test_usage_frame(self):
        got = parse_sse_frame(
            'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":5,"total_tokens":8}}'
        )
        assert len(got) == 1
        usage = got[0]
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (3, 5, 8)

    def test_usage_keeps_vendor_extras_in_raw(self):
        got = parse_sse_frame(
            'data: {"choices":[],"usage":{"prompt_tokens":1,"prompt_cache_hit_tokens":9}}'
        )
        assert got[0].raw["prompt_cache_hit_tokens"] == 9

    def test_one_frame_can_carry_finish_and_usage(self):
        got = parse_sse_frame(
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":4}}'
        )
        assert [c.kind for c in got] == ["finish", "usage"]

    def test_malformed_json_raises_rather_than_truncating(self):
        with pytest.raises(LLMProtocolError):
            parse_sse_frame("data: {not json")

    def test_non_object_frame_raises(self):
        with pytest.raises(LLMProtocolError):
            parse_sse_frame("data: [1, 2, 3]")


# ── Recorded fixtures ─────────────────────────────────────────────────────


class TestRecordedStreams:

    def test_deepseek_reasoning_trace(self):
        chunks = parse_sse_lines(load_fixture("sse_deepseek_reasoning.txt"))
        assert trace(chunks) == [
            ("thinking", "The user asks for "),
            ("thinking", "two plus two."),
            ("text", "Four."),
            ("text", "\n\n"),
            ("text", "Ask me another."),
            ("finish", "stop"),
            ("usage", (11, 7, 18)),
        ]

    def test_deepseek_replay_is_deterministic(self):
        lines = load_fixture("sse_deepseek_reasoning.txt")
        assert trace(parse_sse_lines(lines)) == trace(parse_sse_lines(lines))

    def test_second_provider_runs_through_the_same_parser(self):
        """No reasoning channel, no vendor markers, nothing swapped."""
        chunks = parse_sse_lines(load_fixture("sse_plain_openai.txt"))
        assert trace(chunks) == [
            ("text", "Hello"),
            ("text", ", world."),
            ("finish", "stop"),
            ("usage", (4, 3, 7)),
        ]
        assert not [c for c in chunks if isinstance(c, ThinkingChunk)]

    def test_answer_reassembles_from_text_chunks(self):
        chunks = parse_sse_lines(load_fixture("sse_deepseek_reasoning.txt"))
        answer = "".join(c.text for c in chunks if isinstance(c, TextChunk))
        assert answer == "Four.\n\nAsk me another."
        assert "end▁of▁thinking" not in answer


# ── Error mapping ─────────────────────────────────────────────────────────


class TestErrorMapping:

    @pytest.mark.parametrize(
        "status,cls,retryable",
        [
            (401, LLMAuthError, False),
            (403, LLMAuthError, False),
            (429, LLMRateLimited, True),
            (400, LLMHTTPError, False),
            (500, LLMHTTPError, True),
            (503, LLMHTTPError, True),
        ],
    )
    def test_status_maps_to_typed_error(self, status, cls, retryable):
        err = error_for_status(status, "body text")
        assert isinstance(err, cls)
        assert err.retryable is retryable
        assert err.status == status

    def test_error_bodies_are_truncated(self):
        err = error_for_status(500, "x" * 5000)
        assert len(str(err)) < 400


# ── Transport ─────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, lines, status_code=200, body=b"", on_close=None, headers=None):
        self._lines = lines
        self.status_code = status_code
        self._body = body
        self._on_close = on_close
        self.closed = False
        # A real httpx response always carries these; a double without them
        # lets the adapter read a header in production that no test can see.
        self.headers = dict(headers or {})

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            await asyncio.sleep(0)
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        if self._on_close:
            self._on_close()
        return False


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.aclosed = False

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response

    async def aclose(self):
        self.aclosed = True


async def collect(port, **kwargs):
    return [c async for c in port.stream([{"role": "user", "content": "hi"}], "m", **kwargs)]


class TestTransport:

    def test_stream_yields_fixture_chunks(self):
        resp = FakeResponse(load_fixture("sse_plain_openai.txt"))
        port = OpenAICompatibleStream("http://x/v1/chat/completions", "k", client=FakeClient(resp))
        assert trace(asyncio.run(collect(port))) == [
            ("text", "Hello"),
            ("text", ", world."),
            ("finish", "stop"),
            ("usage", (4, 3, 7)),
        ]

    def test_non_200_raises_typed_error_and_closes(self):
        resp = FakeResponse([], status_code=401, body=b"bad key")
        port = OpenAICompatibleStream("http://x", "k", client=FakeClient(resp))
        with pytest.raises(LLMAuthError):
            asyncio.run(collect(port))
        assert resp.closed, "response must be closed even on an error path"

    def test_a_429_carries_retry_after_through_to_the_caller(self):
        """The chain backs off by this. Dropping the header on the floor here
        turns a server-specified wait into a guess."""
        from agent.runtime.llm_stream import LLMRateLimited

        resp = FakeResponse(
            [], status_code=429, body=b"slow down", headers={"Retry-After": "12"}
        )
        port = OpenAICompatibleStream("http://x", "k", client=FakeClient(resp))
        with pytest.raises(LLMRateLimited) as caught:
            asyncio.run(collect(port))
        assert caught.value.retry_after == 12.0

    def test_a_429_without_the_header_is_still_a_rate_limit(self):
        from agent.runtime.llm_stream import LLMRateLimited

        resp = FakeResponse([], status_code=429, body=b"slow down")
        port = OpenAICompatibleStream("http://x", "k", client=FakeClient(resp))
        with pytest.raises(LLMRateLimited) as caught:
            asyncio.run(collect(port))
        assert caught.value.retry_after is None

    def test_cancelling_closes_the_provider_stream(self):
        """The Phase 2 gate: a cancelled turn must not leave the socket open."""
        never_ends = [
            'data: {"choices":[{"delta":{"content":"tick"}}]}'
        ] * 10_000
        resp = FakeResponse(never_ends)
        port = OpenAICompatibleStream("http://x", "k", client=FakeClient(resp))

        async def run():
            agen = port.stream([{"role": "user", "content": "hi"}], "m")
            got = []
            async for chunk in agen:
                got.append(chunk)
                if len(got) == 3:
                    break          # early exit == consumer cancelled
            await agen.aclose()
            return got

        got = asyncio.run(run())
        assert len(got) == 3
        assert resp.closed, "aclose() must unwind the async with and close the response"

    def test_owned_client_is_closed_after_a_normal_stream(self):
        resp = FakeResponse(load_fixture("sse_plain_openai.txt"))
        client = FakeClient(resp)
        port = OpenAICompatibleStream("http://x", "k", client=client)
        asyncio.run(collect(port))
        # client was injected, so the port must NOT close someone else's client
        assert client.aclosed is False
        assert resp.closed is True

    def test_payload_matches_what_the_endpoint_expects(self):
        resp = FakeResponse([])
        client = FakeClient(resp)
        port = OpenAICompatibleStream("http://x", "k", client=client)
        asyncio.run(collect(port, temperature=0.3, max_tokens=100))
        _, _, kwargs = client.calls[0]
        payload = kwargs["json"]
        assert payload["stream"] is True
        assert payload["model"] == "m"
        assert payload["temperature"] == 0.3
        assert payload["max_tokens"] == 100

    def test_unset_optional_params_are_omitted_not_nulled(self):
        resp = FakeResponse([])
        client = FakeClient(resp)
        port = OpenAICompatibleStream("http://x", "k", client=client)
        asyncio.run(collect(port))
        payload = client.calls[0][2]["json"]
        for key in ("temperature", "max_tokens", "thinking"):
            assert key not in payload, f"{key} should be absent, not None"

    def test_thinking_is_opt_in_by_caller_not_by_provider_name(self):
        resp = FakeResponse([])
        client = FakeClient(resp)
        port = OpenAICompatibleStream("http://x", "k", client=client)
        asyncio.run(collect(port, thinking={"type": "enabled"}))
        assert client.calls[0][2]["json"]["thinking"] == {"type": "enabled"}

    def test_authorization_header_is_sent(self):
        resp = FakeResponse([])
        client = FakeClient(resp)
        port = OpenAICompatibleStream("http://x", "secret", client=client)
        asyncio.run(collect(port))
        assert client.calls[0][2]["headers"]["Authorization"] == "Bearer secret"


# ── The runtime stays silent ──────────────────────────────────────────────


class TestNoTerminalOutput:

    def test_a_full_stream_writes_nothing_to_stdout_or_stderr(self):
        """`stream_response()` printed ANSI, wrote "\\r\\033[K" to stderr and
        drove a spinner from inside the parse loop. None of that may survive
        into the runtime."""
        resp = FakeResponse(load_fixture("sse_deepseek_reasoning.txt"))
        port = OpenAICompatibleStream("http://x", "k", client=FakeClient(resp))

        out, err = io.StringIO(), io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            chunks = asyncio.run(collect(port))
        finally:
            sys.stdout, sys.stderr = real_out, real_err

        assert chunks, "sanity: the stream did produce chunks"
        assert out.getvalue() == ""
        assert err.getvalue() == ""

    def test_parsing_alone_writes_nothing(self):
        out, err = io.StringIO(), io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            parse_sse_lines(load_fixture("sse_deepseek_reasoning.txt"))
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        assert out.getvalue() == ""
        assert err.getvalue() == ""


# ── Real provider ─────────────────────────────────────────────────────────


class TestRealProvider:
    """Fixtures prove the parser; only a real call proves the wire format.

    Skipped without a key rather than mocked: a mock of DeepSeek's SSE shape
    would be testing this file's assumptions about DeepSeek, which is the
    thing that needs checking.
    """

    @pytest.mark.skipif(
        not __import__("os").environ.get("DEEPSEEK_API_KEY", "").strip(),
        reason="no DEEPSEEK_API_KEY",
    )
    def test_deepseek_streams_text_and_reasoning_incrementally(self):
        import os

        port = OpenAICompatibleStream(
            "https://api.deepseek.com/chat/completions",
            os.environ["DEEPSEEK_API_KEY"].strip(),
            timeout=90,
        )

        async def run():
            return [
                c
                async for c in port.stream(
                    [{"role": "user", "content": "What is 2+2? Answer in one short sentence."}],
                    "deepseek-v4-flash",
                    max_tokens=800,
                    thinking={"type": "enabled"},
                )
            ]

        chunks = asyncio.run(run())
        texts = [c for c in chunks if isinstance(c, TextChunk)]
        thinks = [c for c in chunks if isinstance(c, ThinkingChunk)]
        usages = [c for c in chunks if isinstance(c, UsageChunk)]
        finishes = [c for c in chunks if isinstance(c, FinishChunk)]

        assert len(texts) > 1, "one text chunk means it buffered instead of streaming"
        assert thinks, "reasoning channel produced nothing with thinking enabled"
        assert len(finishes) == 1
        assert len(usages) == 1
        assert usages[0].total_tokens > 0, "provider usage must survive the extraction"
        assert "4" in "".join(c.text for c in texts)
