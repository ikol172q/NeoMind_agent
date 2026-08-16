"""Two defects found by using the coding REPL, not by reading it.

Both corrupted a real session on 2026-08-15 and both are silent: nothing
errored, the agent simply did the wrong thing while looking fine.
"""

from __future__ import annotations

import json

import pytest

from agent.coding.tool_parser import ToolCallParser


def assemble_legacy(deltas):
    """The exact accumulation `code_commands.stream_response()` performs."""
    out = ""
    for content in deltas:
        if content:
            before = content
            content = content.replace("<｜end▁of▁thinking｜>", "")
            content = content.replace("<|end▁of▁thinking|>", "")
            if not content and before:
                continue
            out += content
    return out


class TestWhitespaceDeltasSurvive:
    """A token boundary lands on a space constantly.

    The old condition was `if not content.strip(): continue`, which discarded
    any delta that was only whitespace. Observed live: the model emitted
    `ls -F agent neomind cli`, then `" "`, then `2>/dev/null`, and the space
    was dropped — so its own history read `cli2>/dev/null`. It then saw a typo
    it had not made and spent several turns "fixing" it.
    """

    def test_a_lone_space_between_deltas_is_kept(self):
        assert assemble_legacy(["ls -F agent cli", " ", "2>/dev/null"]) == (
            "ls -F agent cli 2>/dev/null"
        )

    def test_a_paragraph_break_is_kept(self):
        assert assemble_legacy(["One.", "\n\n", "Two."]) == "One.\n\nTwo."

    def test_a_numbered_list_does_not_run_together(self):
        """Observed: "最有趣2. **怎么设计**" with the newline eaten."""
        assert assemble_legacy(["1. first", "\n", "2. second"]) == "1. first\n2. second"

    def test_a_delta_that_is_only_the_thinking_marker_is_still_dropped(self):
        assert assemble_legacy(["Four.", "<｜end▁of▁thinking｜>", " more"]) == "Four. more"

    def test_the_ascii_marker_variant_is_dropped_too(self):
        assert assemble_legacy(["a", "<|end▁of▁thinking|>", "b"]) == "ab"

    def test_the_live_path_agrees_with_the_runtime_port(self):
        """The legacy loop and agent/runtime must not disagree about text."""
        from agent.runtime.providers.openai_sse import parse_sse_frame

        deltas = ["ls -F agent cli", " ", "2>/dev/null", "\n\n", "done"]
        via_port = "".join(
            c.text
            for d in deltas
            for c in parse_sse_frame(
                "data: " + json.dumps({"choices": [{"delta": {"content": d}}]})
            )
        )
        assert via_port == assemble_legacy(deltas)


class TestToolCallDelimiterVariants:
    """An unrecognised delimiter is not a parse failure — it is prose.

    When the parser did not match, the raw JSON payload was printed to the
    user as if the model had written it, and the agent loop stopped. Observed
    live with DeepSeek's fullwidth spelling.
    """

    PAYLOAD = '{"tool": "Read", "params": {"path": "README.md"}}'

    @pytest.mark.parametrize(
        "opening,closing",
        [
            ("<tool_call>", "</tool_call>"),
            ("<|tool_call|>", "<|/tool_call|>"),
            ("<|tool_call_begin|>", "<|tool_call_end|>"),
            ("<｜｜DSML｜｜tool_call>", "</｜｜DSML｜｜tool_call>"),
            ("<｜tool_call｜>", "<｜/tool_call｜>"),
        ],
    )
    def test_every_known_delimiter_spelling_parses(self, opening, closing):
        parser = ToolCallParser()
        call = parser.parse(f"sure, reading it:\n\n{opening}\n{self.PAYLOAD}\n{closing}")
        assert call is not None, f"{opening} was treated as prose"
        assert call.tool_name == "Read"
        assert call.params.get("path") == "README.md"

    def test_the_payload_does_not_survive_into_display_text(self):
        parser = ToolCallParser()
        text = (
            "参数名用错了,重试:\n\n"
            "<｜｜DSML｜｜tool_call>\n" + self.PAYLOAD + "\n</｜｜DSML｜｜tool_call>"
        )
        call = parser.parse(text)
        assert call is not None
        stripped = parser.strip_tool_call(text, call)
        assert "DSML" not in stripped
        assert '"tool"' not in stripped
        assert "参数名用错了" in stripped, "the model's prose should remain"
