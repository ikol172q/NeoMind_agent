"""Telegram regressions for text-based tool-call protocol variants."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agent.integration.telegram_bot import (
    NeoMindTelegramBot,
    _contains_tool_call,
    _strip_tool_calls,
)


_PROVIDER = {
    "name": "mlx-local",
    "model": "mlx-community/test",
    "base_url": "http://localhost.invalid/v1/chat/completions",
    "api_key": "test-key",
}


class _SyncStreamResponse:
    status_code = 200
    headers = {}

    def __init__(self, content_chunks, reasoning_chunks=None):
        self._content_chunks = content_chunks
        self._reasoning_chunks = reasoning_chunks or [""] * len(content_chunks)

    def __bool__(self):
        return True

    def iter_lines(self):
        for content, reasoning in zip(self._content_chunks, self._reasoning_chunks):
            delta = {"content": content}
            if reasoning:
                delta["reasoning_content"] = reasoning
            payload = {"choices": [{"delta": delta}]}
            yield f"data: {json.dumps(payload)}".encode()
        yield b"data: [DONE]"


class _AsyncContent:
    def __init__(self, text):
        self._lines = [
            (
                "data: "
                + json.dumps({"choices": [{"delta": {"content": text}}]})
                + "\n"
            ).encode(),
            b"data: [DONE]\n",
        ]

    def __aiter__(self):
        self._iterator = iter(self._lines)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _AsyncStreamResponse:
    status = 200

    def __init__(self, text="直接回答"):
        self.content = _AsyncContent(text)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return ""

    async def json(self):
        return {"choices": [{"message": {"content": "直接回答"}}]}


class _AsyncSession:
    def __init__(self, *args, response_text="直接回答", **kwargs):
        self._response_text = response_text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        return _AsyncStreamResponse(self._response_text)


class _NudgeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return {
            "choices": [{"message": {"content": (
                "<|tool_call|>"
                '{"tool":"WebSearch","params":{"query":"test"}}'
                "<|/tool_call|>"
            )}}]
        }

    async def text(self):
        return ""


class _NudgeSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        return _NudgeResponse()


def _make_bot():
    bot = NeoMindTelegramBot.__new__(NeoMindTelegramBot)
    bot.config = SimpleNamespace(max_message_length=4096)
    bot._store = MagicMock()
    bot._store.get_recent_history.return_value = []
    bot._get_provider_chain = MagicMock(return_value=[_PROVIDER])
    bot._auto_compact_if_needed_db = MagicMock(return_value=None)
    bot._get_system_prompt = MagicMock(return_value="system")
    bot._should_search = MagicMock(return_value=False)
    bot._usage = MagicMock()
    bot._md_to_html = MagicMock(side_effect=lambda text: text)
    bot._safe_edit = AsyncMock()
    bot._send_long_message = AsyncMock()
    bot._run_agentic_tool_loop = AsyncMock()
    bot._evidence_trail = None
    return bot


def _make_message():
    live = MagicMock()
    live.edit_text = AsyncMock()
    live.delete = AsyncMock()
    msg = MagicMock()
    msg.reply_text = AsyncMock(return_value=live)
    return msg, live


def _use_real_agentic_loop(bot):
    bot._run_agentic_tool_loop = NeoMindTelegramBot._run_agentic_tool_loop.__get__(
        bot, NeoMindTelegramBot,
    )


def _visible_texts(bot, live):
    texts = [call.args[1] for call in bot._safe_edit.await_args_list]
    texts.extend(call.args[0] for call in live.edit_text.await_args_list)
    texts.extend(call.args[1] for call in bot._send_long_message.await_args_list)
    return texts


def test_helpers_cover_plain_and_deepseek_pipe_variants():
    variants = (
        ("<tool_call>", "</tool_call>"),
        ("<|tool_call|>", "<|/tool_call|>"),
        ("<|tool_call_begin|>", "<|tool_call_end|>"),
        ("<|tool_call_begin|>", "<|/tool_call_end|>"),
    )
    for opener, closer in variants:
        text = f"before {opener}secret payload{closer} after"
        assert _contains_tool_call(text)
        cleaned = _strip_tool_calls(text)
        assert "secret payload" not in cleaned
        assert "tool_call" not in cleaned
        assert "before" in cleaned and "after" in cleaned

    normal = "Normal prose about tool calls and <|tool_calls|> stays visible."
    assert not _contains_tool_call(normal)
    assert _strip_tool_calls(normal) == normal
    assert _strip_tool_calls("answer</tool_report>") == "answer"


def test_streaming_helper_hides_every_partial_delimiter_prefix_only_in_stream():
    assert _strip_tool_calls("answer <", streaming=True) == "answer "
    assert _strip_tool_calls("answer <|t", streaming=True) == "answer "

    completed = (
        "answer <|tool_call|>"
        '{"tool":"Read","params":{"path":"file.txt"}}'
        "<|/tool_call|> after"
    )
    assert _strip_tool_calls(completed, streaming=True) == "answer  after"

    # Completion-time cleanup must not eat legitimate ordinary punctuation.
    assert _strip_tool_calls("x <") == "x <"


def test_normal_stream_hides_pipe_payload_and_starts_agentic_loop():
    bot = _make_bot()
    msg, live = _make_message()
    raw = (
        "准备执行。\n<|tool_call|>"
        '{"tool":"Read","params":{"path":"secret.txt"}}'
        "<|/tool_call|>"
    )

    with patch("requests.post", return_value=_SyncStreamResponse([raw])):
        asyncio.run(bot._ask_llm_stream_normal(msg, "read it", 7, "private"))

    bot._run_agentic_tool_loop.assert_awaited_once()
    assert bot._run_agentic_tool_loop.await_args.args[1] == raw
    for visible in _visible_texts(bot, live):
        assert "tool_call" not in visible
        assert "secret.txt" not in visible


def test_normal_pipe_only_stream_deletes_live_placeholder():
    bot = _make_bot()
    msg, live = _make_message()
    raw = (
        "<|tool_call|>"
        '{"tool":"Read","params":{"path":"file.txt"}}'
        "<|/tool_call|>"
    )

    with patch("requests.post", return_value=_SyncStreamResponse([raw])):
        asyncio.run(bot._ask_llm_stream_normal(msg, "read it", 7, "private"))

    live.delete.assert_awaited_once_with()
    bot._run_agentic_tool_loop.assert_awaited_once()


def test_thinking_stream_hides_pipe_payload_and_starts_agentic_loop():
    bot = _make_bot()
    msg, _ = _make_message()
    raw = (
        "准备执行。\n<|tool_call_begin|>"
        '{"tool":"Read","params":{"path":"secret.txt"}}'
        "<|tool_call_end|>"
    )
    response = _SyncStreamResponse([raw], reasoning_chunks=["先检查文件"])

    with patch("requests.post", return_value=response):
        asyncio.run(bot._ask_llm_streaming(msg, "read it", 7, "private"))

    bot._run_agentic_tool_loop.assert_awaited_once()
    bot._send_long_message.assert_awaited_once()
    visible = bot._send_long_message.await_args.args[1]
    assert visible == "准备执行。"
    assert "tool_call" not in visible
    assert "secret.txt" not in visible


def test_nudge_detects_pipe_tool_call_and_executes_it():
    bot = _make_bot()
    msg, _ = _make_message()

    with (
        patch("requests.post", return_value=_SyncStreamResponse(["我来搜索："])),
        patch("aiohttp.ClientSession", _NudgeSession),
    ):
        asyncio.run(bot._ask_llm_stream_normal(msg, "search", 7, "private"))

    bot._run_agentic_tool_loop.assert_awaited_once()
    nudge_raw = bot._run_agentic_tool_loop.await_args.args[1]
    assert nudge_raw.startswith("<|tool_call|>")
    assert nudge_raw.endswith("<|/tool_call|>")


class _EventsAgentic:
    def __init__(self, events):
        self._events = events

    async def run(self, initial_response, messages, llm_caller):
        for event in self._events:
            yield event


def test_agentic_llm_response_hides_pipe_payload():
    bot = _make_bot()
    _use_real_agentic_loop(bot)
    raw = (
        "最终答案。<|tool_call|>"
        '{"tool":"Read","params":{"path":"secret.txt"}}'
        "<|/tool_call|>"
    )
    events = [
        SimpleNamespace(type="llm_response", llm_text=raw),
        SimpleNamespace(type="done", iteration=1),
    ]
    bot._get_agentic_loop = MagicMock(return_value=_EventsAgentic(events))
    msg, _ = _make_message()

    with patch.dict(os.environ, {"NEOMIND_NATIVE_TOOLS": ""}):
        asyncio.run(bot._run_agentic_tool_loop(msg, raw, 7, "private", _PROVIDER))

    bot._send_long_message.assert_awaited_once_with(msg, "最终答案。")


def test_unanswered_tool_status_resolves_as_not_executed():
    bot = _make_bot()
    _use_real_agentic_loop(bot)
    events = [
        SimpleNamespace(
            type="tool_start", tool_preview="Write(secret.txt)", tool_name="Write",
        ),
        SimpleNamespace(type="done", iteration=1),
    ]
    bot._get_agentic_loop = MagicMock(return_value=_EventsAgentic(events))
    msg, status = _make_message()

    with (
        patch.dict(os.environ, {"NEOMIND_NATIVE_TOOLS": ""}),
        patch("aiohttp.ClientSession", _AsyncSession),
    ):
        asyncio.run(bot._run_agentic_tool_loop(msg, "tool call", 7, "private", _PROVIDER))

    denied_text = status.edit_text.await_args_list[0].args[0]
    assert "未获批准，未执行" in denied_text
    assert "失败" not in denied_text


def test_tool_result_resets_status_before_done():
    bot = _make_bot()
    _use_real_agentic_loop(bot)
    events = [
        SimpleNamespace(type="tool_start", tool_preview="Read(file.txt)", tool_name="Read"),
        SimpleNamespace(
            type="tool_result", result_output="contents", result_success=True,
            result_error=None, tool_name="Read", feedback_message=None,
        ),
        SimpleNamespace(type="llm_response", llm_text="读取完成。"),
        SimpleNamespace(type="done", iteration=1),
    ]
    bot._get_agentic_loop = MagicMock(return_value=_EventsAgentic(events))
    msg, status = _make_message()

    with patch.dict(os.environ, {"NEOMIND_NATIVE_TOOLS": ""}):
        asyncio.run(bot._run_agentic_tool_loop(msg, "tool call", 7, "private", _PROVIDER))

    edits = [call.args[0] for call in status.edit_text.await_args_list]
    assert len(edits) == 1
    assert "✅" in edits[0]
    assert all("未执行" not in text for text in edits)
