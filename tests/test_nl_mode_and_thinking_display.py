"""Two more defects from the same real session.

Both are about what the user is told, not about whether the agent works —
which is why neither showed up in any suite until someone used it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent.services.nl_interpreter import NaturalLanguageInterpreter

REAL_MODES = {"chat", "coding", "fin"}


@pytest.fixture
def interp():
    return NaturalLanguageInterpreter()


class TestModeSwitching:
    """"换成 coding" reached the model as prose, and it answered — correctly —
    that it cannot change its own mode. There were no mode rules at all."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("switch to coding", "coding"),
            ("use fin mode", "fin"),
            ("change mode to chat", "chat"),
            ("coding mode", "coding"),
            ("换成 coding", "coding"),
            ("切换到 coding", "coding"),
            ("切到 fin", "fin"),
            ("切换模式到 chat", "chat"),
            ("进入编程模式", "coding"),
            ("进入对话模式", "chat"),
            ("换成理财模式", "fin"),
            ("进入投资模式", "fin"),
        ],
    )
    def test_phrasings_produce_a_valid_mode_command(self, interp, text, expected):
        cmd, confidence = interp.interpret(text, "chat")
        assert cmd == f"/mode {expected}", f"{text!r} produced {cmd!r}"
        assert confidence > 0

    def test_a_chinese_mode_name_is_translated_not_passed_through(self, interp):
        """`/mode 编程` is not a mode. Recognising the phrase and then emitting
        an invalid command is worse than not recognising it."""
        cmd, _ = interp.interpret("进入编程模式", "chat")
        assert cmd.split()[1] in REAL_MODES

    @pytest.mark.parametrize(
        "text",
        [
            "switch to whatever",
            "换成 python",
            "今天天气怎么样",
            "我想进入这个话题聊聊",
            "进入房间",
        ],
    )
    def test_near_misses_are_left_alone(self, interp, text):
        cmd, _ = interp.interpret(text, "chat")
        assert cmd is None, f"{text!r} should not have been rewritten to {cmd!r}"

    def test_the_pattern_list_is_generated_from_the_alias_table(self):
        """They were written out separately once and drifted immediately —
        对话 was in the table and missing from the pattern."""
        for name in NaturalLanguageInterpreter.MODE_ALIASES:
            interp = NaturalLanguageInterpreter()
            cmd, _ = interp.interpret(f"进入{name}模式", "chat")
            assert cmd is not None, f"{name} is in MODE_ALIASES but matches nothing"
            assert cmd.split()[1] in REAL_MODES


class TestChineseReachesTheInterpreterAtAll:
    """`should_suggest()` gated on English keywords, so no Chinese input ever
    reached the pattern table — not just mode switching."""

    def test_a_chinese_command_passes_the_gate(self, interp):
        assert interp.should_suggest("切换到 coding") is True

    def test_ordinary_chinese_conversation_still_does_not(self, interp):
        assert interp.should_suggest("你觉得这个设计怎么样") is False

    def test_word_boundaries_are_not_used_for_cjk(self, interp):
        """\\b is meaningless between CJK characters; the gate must substring."""
        assert interp.should_suggest("请切换到编程模式") is True


class TestThinkingSummaryDoesNotLeakFrameworkVocabulary:
    """The spinner label is the last line of raw reasoning. Observed live:
    "No procedures needed really — no claims, no URLs, no current state
    dependencies" and "为了匹配该 persona 用 Bash"."""

    @staticmethod
    def _summarizer():
        src = Path("agent/services/code_commands.py").read_text(encoding="utf-8")
        block = re.search(
            r"        _FRAMEWORK_WORDS = \((.*?)\n        \)\n\n"
            r"(        def _summarize_thinking.*?\n            return \"\")",
            src,
            re.S,
        )
        assert block, "the summarizer moved; update this test"
        code = (
            "_FRAMEWORK_WORDS = ("
            + block.group(1)
            + "\n)\n"
            + re.sub(r"^        ", "", block.group(2), flags=re.M)
        )
        namespace: dict = {}
        exec(code, namespace)
        return namespace["_summarize_thinking"]

    @pytest.mark.parametrize(
        "leaked",
        [
            "No procedures needed really — no claims, no URLs, no current state dependencies.",
            "We need answer user: What topic should we brainstorm about?",
            "为了匹配该 persona 用 Bash 而不是 Glob",
            "I should comply exactly with this format.",
        ],
    )
    def test_reasoning_about_its_own_instructions_is_suppressed(self, leaked):
        assert self._summarizer()(leaked) == ""

    @pytest.mark.parametrize(
        "kept",
        [
            "Let me start with listing the directory structure.",
            "I'll read pyproject.toml and check the build backend.",
        ],
    )
    def test_a_line_describing_the_action_survives(self, kept):
        assert self._summarizer()(kept) == kept

    def test_the_scrollback_line_carries_only_a_duration(self):
        """The summary is useful while the spinner runs and is noise once the
        turn is over — and the scrollback is where it was read."""
        src = Path("agent/services/code_commands.py").read_text(encoding="utf-8")
        printed = re.findall(r'print\(f"[^"]*Thought for \{elapsed[^"]*"\)', src)
        assert printed, "the Thought-for line moved; update this test"
        for line in printed:
            assert "{summary}" not in line, line
