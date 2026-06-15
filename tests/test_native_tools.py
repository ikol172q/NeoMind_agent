"""Unit tests for agent.llm.native_tools — verified against the REAL
agent.coding.tool_parser.ToolCallParser (the live regex parser the agentic
loop uses). This proves the reliability win: structured native args → a
<tool_call> block the existing parser always parses, even for large payloads.

Run:  python3 tests/test_native_tools.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.coding.tool_parser import ToolCallParser  # noqa: E402
from agent.llm.native_tools import (  # noqa: E402
    accumulate_tool_call_deltas,
    synthesize_from_accumulated,
    synthesize_tool_call_text,
)

PARSER = ToolCallParser()


def test_simple_call_roundtrips():
    text = synthesize_tool_call_text("Read", {"file_path": "/tmp/a.txt"})
    tc = PARSER.parse(text)
    assert tc is not None
    assert tc.tool_name == "Read"
    assert tc.params["file_path"] == "/tmp/a.txt"


def test_large_multiline_content_survives_roundtrip():
    # Realistic code payload: newlines, double quotes, braces, backslashes —
    # exactly what breaks a naive free-text <tool_call>.
    content = (
        'def f(x):\n'
        '    return {"a": x, "b": [1, 2, 3]}  # quote " and \\ backslash\n'
        '\n'
        'class C:\n'
        '    """doc with } brace and <tool_call> lookalike"""\n'
        '    pass\n'
    )
    text = synthesize_tool_call_text(
        "Write", {"file_path": "/tmp/x.py", "content": content}
    )
    tc = PARSER.parse(text)
    assert tc is not None, "synthesized block must parse"
    assert tc.tool_name == "Write"
    assert tc.params["content"] == content, "content must round-trip byte-exact"
    assert tc.params["file_path"] == "/tmp/x.py"


def test_adversarial_content_roundtrips():
    # The real guarantee: synthesized output is always valid JSON the parser
    # parses byte-exact — even when the content contains the exact tokens that
    # confuse a text protocol (a literal </tool_call>, braces, quotes, backslash).
    content = (
        'x = {"k": "v"}\n'
        'print("</tool_call> looks like a close tag")\n'
        'if a > b: pass  # trailing brace } and { open\n'
        'path = "C:\\\\tmp\\\\x"\n'
    )
    tc = PARSER.parse(synthesize_tool_call_text("Write", {"content": content}))
    assert tc is not None, "adversarial content must still parse"
    assert tc.tool_name == "Write"
    assert tc.params["content"] == content, "adversarial content must round-trip byte-exact"


def test_streaming_accumulation_then_synthesize():
    acc: dict = {}
    # name + args arrive split across stream chunks (as DeepSeek streams them)
    accumulate_tool_call_deltas(acc, [{"index": 0, "id": "call_1",
                                       "function": {"name": "Re"}}])
    accumulate_tool_call_deltas(acc, [{"index": 0, "function": {"name": "ad"}}])
    accumulate_tool_call_deltas(acc, [{"index": 0,
                                       "function": {"arguments": '{"file_path":'}}])
    accumulate_tool_call_deltas(acc, [{"index": 0,
                                       "function": {"arguments": ' "/tmp/a.txt"}'}}])
    tc = PARSER.parse(synthesize_from_accumulated(acc))
    assert tc is not None
    assert tc.tool_name == "Read"
    assert tc.params["file_path"] == "/tmp/a.txt"


def test_args_as_dict():
    tc = PARSER.parse(synthesize_tool_call_text("Grep", {"pattern": "def foo"}))
    assert tc.tool_name == "Grep" and tc.params["pattern"] == "def foo"


def test_invalid_json_args_falls_back_not_crash():
    tc = PARSER.parse(synthesize_tool_call_text("X", "not json{{"))
    assert tc is not None and "_raw" in tc.params


def test_empty_accumulated_is_empty():
    assert synthesize_from_accumulated({}) == ""
    assert synthesize_from_accumulated({0: {"id": "", "name": "", "args": ""}}) == ""


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
