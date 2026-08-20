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


class TestDsmlInvokeShape:
    """DeepSeek's other DSML spelling, found only by using the REPL.

    After the JSON-shaped `<｜｜DSML｜｜tool_call>` variant was fixed, a real
    session produced the Anthropic-shaped one instead — `tool_calls` holding
    `invoke name="X"` with `parameter` children — and the payload was printed
    to the user all over again. One spelling fixed is not the format fixed.
    """

    RAW = (
        "好的，我来执行:\n"
        "<｜｜DSML｜｜tool_calls>\n"
        '<｜｜DSML｜｜invoke name="Bash">\n'
        '<｜｜DSML｜｜parameter name="command" string="true">echo PERMISSION_PATH_OK</｜｜DSML｜｜parameter>\n'
        '<｜｜DSML｜｜parameter name="description" string="true">Echo test</｜｜DSML｜｜parameter>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>\n"
        "之后我会汇报结果。"
    )

    def test_it_parses_into_a_tool_call(self):
        call = ToolCallParser().parse(self.RAW)
        assert call is not None, "the invoke shape was treated as prose"
        assert call.tool_name == "Bash"
        assert call.params["command"] == "echo PERMISSION_PATH_OK"

    def test_every_parameter_is_captured(self):
        call = ToolCallParser().parse(self.RAW)
        assert call.params["description"] == "Echo test"

    def test_the_payload_is_removed_from_display_text(self):
        parser = ToolCallParser()
        call = parser.parse(self.RAW)
        shown = parser.strip_tool_call(self.RAW, call)
        assert "DSML" not in shown
        assert "invoke" not in shown
        assert "echo PERMISSION_PATH_OK" not in shown

    def test_the_prose_around_it_survives(self):
        """ToolCall.raw scoped to the whole response deleted the model's own
        words along with the payload, leaving an apparently empty turn."""
        parser = ToolCallParser()
        call = parser.parse(self.RAW)
        shown = parser.strip_tool_call(self.RAW, call)
        assert "好的，我来执行" in shown
        assert "之后我会汇报结果" in shown

    def test_the_json_shape_still_works(self):
        call = ToolCallParser().parse(
            '<｜｜DSML｜｜tool_call>{"tool":"Read","params":{"path":"a"}}</｜｜DSML｜｜tool_call>'
        )
        assert call.tool_name == "Read" and call.params["path"] == "a"

    def test_the_standard_shape_still_works(self):
        call = ToolCallParser().parse(
            '<tool_call>{"tool":"Read","params":{"path":"b"}}</tool_call>'
        )
        assert call.tool_name == "Read" and call.params["path"] == "b"


class TestStreamingSuppressionOfDsmlBlocks:
    """The display filter carried a fourth copy of the delimiter list.

    parse() and strip_tool_call() were taught DeepSeek's fullwidth spellings;
    `_CodeFenceFilter`, which decides what reaches the screen *while* tokens
    arrive, was not. So a tool call was executed correctly and its payload
    still streamed out in fragments — "</｜｜DSML｜｜tool_ca" … "lls>".
    """

    @staticmethod
    def _run(chunks):
        import sys

        sys.argv = ["x"]
        from cli.neomind_interface import NeoMindInterface

        f = NeoMindInterface._CodeFenceFilter()
        return "".join(f.write(c) or "" for c in chunks) + (f.flush() or "")

    def test_a_streamed_dsml_block_never_reaches_the_screen(self):
        shown = self._run([
            "好的:\n",
            '<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name="bash">\n',
            '<｜｜DSML｜｜parameter string="command">date +%Y</｜｜DSML｜｜parameter>\n',
            "</｜｜DSML｜｜invoke>\n</｜｜DSML｜｜tool_calls>\n",
            "之后汇报。",
        ])
        assert "DSML" not in shown and "invoke" not in shown
        assert shown == "好的:之后汇报。"

    def test_the_closing_tag_of_the_outer_block_is_not_left_behind(self):
        """invoke nests inside tool_calls. Accepting either as the closer let
        `</invoke>` end the block early and printed `</｜｜DSML｜｜tool_calls>`."""
        shown = self._run([
            '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="b">x</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>',
            "tail",
        ])
        assert shown == "tail"

    def test_a_bare_invoke_without_a_wrapper_is_still_suppressed(self):
        shown = self._run(['A\n', '<｜｜DSML｜｜invoke name="b">x</｜｜DSML｜｜invoke>\n', "B"])
        assert shown == "AB"

    def test_ordinary_text_with_angle_brackets_is_untouched(self):
        text = "Hello world. a < b and c > d"
        assert self._run([text]) == text

    def test_a_block_split_across_every_character_boundary_is_suppressed(self):
        """The retained tail must be at least as long as the longest closer.

        It was 18, computed before the DSML forms existed;
        `</｜｜DSML｜｜tool_calls>` is 21, so a tag straddling two chunks was cut
        and three characters reached the screen as "lls>".
        """
        raw = (
            "好的:<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name=\"b\">"
            '<｜｜DSML｜｜parameter string="command">date</｜｜DSML｜｜parameter>'
            "</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>之后汇报。"
        )
        shown = self._run(list(raw))          # one character per chunk
        assert shown == "好的:之后汇报。", shown

    def test_bash_fences_are_still_suppressed(self):
        assert self._run(["see:\n", "```bash\nls -la\n```\n", "done"]) == "see:done"


class TestDsmlParameterAttributeVariants:
    """`<｜｜DSML｜｜parameter string="command">` — the name in a different
    attribute, and no `name` at all. The strict pattern captured nothing, so
    the call ran as `bash()` and was rejected for a missing parameter."""

    @staticmethod
    def _call(param_tag):
        return ToolCallParser().parse(
            "<｜｜DSML｜｜tool_calls>"
            '<｜｜DSML｜｜invoke name="bash">'
            f"{param_tag}date +%Y</｜｜DSML｜｜parameter>"
            "</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>"
        )

    def test_name_attribute(self):
        call = self._call('<｜｜DSML｜｜parameter name="command" string="true">')
        assert call.params == {"command": "date +%Y"}

    def test_name_carried_in_another_attribute(self):
        call = self._call('<｜｜DSML｜｜parameter string="command">')
        assert call.params == {"command": "date +%Y"}

    def test_type_words_are_not_mistaken_for_the_name(self):
        call = self._call('<｜｜DSML｜｜parameter string="true" name="command">')
        assert call.params == {"command": "date +%Y"}
