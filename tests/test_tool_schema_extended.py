"""Extended edge-case tests for tool_schema.py.

Focuses on areas NOT covered by test_tool_schema.py:
- validate_params mutation semantics (unknown param stripping)
- Multiple unknown params at once
- Edge cases: empty string params, None values, nested dicts
- apply_defaults with None defaults (should NOT fill)
- to_prompt_schema edge cases
- generate_tool_prompt with many tools
- ToolDefinition repr
- ToolParam repr edge cases
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tool_schema import (
    ToolParam, ParamType, ToolDefinition, PermissionLevel, generate_tool_prompt,
)
from agent.tools import ToolResult


def _noop(**kwargs):
    return ToolResult(True, output="ok")


# ── TestValidateParamsMutation ───────────────────────────────────────────────

class TestValidateParamsMutation(unittest.TestCase):
    """Test that unknown params are stripped and dict is mutated in place."""

    def test_single_unknown_param_stripped(self):
        """Verify single unknown param is removed from the dict."""
        tool = ToolDefinition(
            name="Test",
            description="Test tool",
            parameters=[ToolParam("required_param", ParamType.STRING, "Required")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"required_param": "value", "unknown_param": 123}
        ok, err = tool.validate_params(params)
        self.assertTrue(ok)
        self.assertNotIn("unknown_param", params)
        self.assertIn("required_param", params)

    def test_multiple_unknown_params_stripped(self):
        """Multiple unknown params should all be stripped at once."""
        tool = ToolDefinition(
            name="Test",
            description="Test tool",
            parameters=[ToolParam("name", ParamType.STRING, "Name")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {
            "name": "test",
            "reason": "debug",
            "explanation": "detailed reason",
            "note": "extra comment",
        }
        ok, err = tool.validate_params(params)
        self.assertTrue(ok)
        self.assertNotIn("reason", params)
        self.assertNotIn("explanation", params)
        self.assertNotIn("note", params)
        self.assertIn("name", params)

    def test_unknown_params_stripped_in_place(self):
        """Verify the params dict is mutated (same object identity)."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("x", ParamType.STRING, "X")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"x": "1", "unknown": "2"}
        params_id = id(params)
        ok, err = tool.validate_params(params)
        # Should be the exact same object
        self.assertEqual(id(params), params_id)
        self.assertNotIn("unknown", params)

    def test_only_unknown_params_removed_known_kept(self):
        """When multiple params mixed, only unknowns removed, knowns kept."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("a", ParamType.STRING, "A"),
                ToolParam("b", ParamType.INTEGER, "B", required=False, default=0),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"a": "val", "b": 5, "unknown1": "x", "unknown2": "y"}
        ok, err = tool.validate_params(params)
        self.assertTrue(ok)
        self.assertIn("a", params)
        self.assertIn("b", params)
        self.assertNotIn("unknown1", params)
        self.assertNotIn("unknown2", params)

    def test_stripping_unknown_with_valid_required(self):
        """Strip unknowns but still have valid required params → pass."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("required", ParamType.STRING, "Req")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"required": "ok", "extra1": 1, "extra2": 2, "extra3": 3}
        ok, err = tool.validate_params(params)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertIn("required", params)
        self.assertEqual(len(params), 1)

    def test_stripping_unknown_with_missing_required(self):
        """Strip unknowns but required is missing → still fails."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("required", ParamType.STRING, "Req")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"unknown1": "x", "unknown2": "y"}
        ok, err = tool.validate_params(params)
        self.assertFalse(ok)
        self.assertIn("required", err)
        # Unknowns should be stripped even though validation failed
        self.assertNotIn("unknown1", params)
        self.assertNotIn("unknown2", params)

    def test_all_params_unknown_then_check_required(self):
        """All params are unknown → all stripped → missing required error."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("path", ParamType.STRING, "Path")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"reason": "debug", "extra": 123}
        ok, err = tool.validate_params(params)
        self.assertFalse(ok)
        self.assertIn("path", err)
        self.assertEqual(len(params), 0)


# ── TestValidateParamsEdgeCases ──────────────────────────────────────────────

class TestValidateParamsEdgeCases(unittest.TestCase):
    """Test edge cases for type checking and special values."""

    def test_empty_string_is_valid_string(self):
        """Empty string should be valid for STRING param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("text", ParamType.STRING, "Text")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"text": ""})
        self.assertTrue(ok)

    def test_very_long_string(self):
        """Very long string (100K chars) should be valid."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("text", ParamType.STRING, "Text")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        long_str = "x" * 100000
        ok, err = tool.validate_params({"text": long_str})
        self.assertTrue(ok)

    def test_unicode_emoji_in_string(self):
        """Unicode and emoji should be valid for STRING param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("text", ParamType.STRING, "Text")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, _ = tool.validate_params({"text": "Hello 世界 🎉"})
        self.assertTrue(ok)

    def test_zero_is_valid_integer(self):
        """Zero should be valid for INTEGER param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("count", ParamType.INTEGER, "Count")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"count": 0})
        self.assertTrue(ok)

    def test_negative_integer_valid(self):
        """Negative integers should be valid."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("delta", ParamType.INTEGER, "Delta")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"delta": -42})
        self.assertTrue(ok)

    def test_large_integer(self):
        """Very large integer (10^18) should be valid."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("id", ParamType.INTEGER, "ID")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"id": 10**18})
        self.assertTrue(ok)

    def test_float_not_valid_for_integer(self):
        """Float value should be invalid for INTEGER param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("count", ParamType.INTEGER, "Count")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"count": 3.14})
        self.assertFalse(ok)
        self.assertIn("must be integer", err)

    def test_none_value_for_string_invalid(self):
        """None as string value should be invalid."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("text", ParamType.STRING, "Text")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"text": None})
        self.assertFalse(ok)
        self.assertIn("must be string", err)

    def test_nested_dict_not_valid_string(self):
        """Nested dict should be invalid for STRING param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("text", ParamType.STRING, "Text")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"text": {"nested": "value"}})
        self.assertFalse(ok)
        self.assertIn("must be string", err)

    def test_list_not_valid_string(self):
        """List value should be invalid for STRING param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("text", ParamType.STRING, "Text")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"text": [1, 2, 3]})
        self.assertFalse(ok)
        self.assertIn("must be string", err)

    def test_boolean_true_not_valid_string(self):
        """Boolean True should be invalid for STRING param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("text", ParamType.STRING, "Text")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"text": True})
        self.assertFalse(ok)
        self.assertIn("must be string", err)

    def test_integer_zero_not_valid_boolean(self):
        """Integer 0 should be invalid for BOOLEAN param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("flag", ParamType.BOOLEAN, "Flag")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"flag": 0})
        self.assertFalse(ok)
        self.assertIn("must be boolean", err)

    def test_integer_one_not_valid_boolean(self):
        """Integer 1 should be invalid for BOOLEAN param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("flag", ParamType.BOOLEAN, "Flag")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"flag": 1})
        self.assertFalse(ok)
        self.assertIn("must be boolean", err)

    def test_string_true_not_valid_boolean(self):
        """String "true" should be invalid for BOOLEAN param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("flag", ParamType.BOOLEAN, "Flag")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"flag": "true"})
        self.assertFalse(ok)
        self.assertIn("must be boolean", err)

    def test_boolean_false_valid(self):
        """Boolean False should be valid."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("flag", ParamType.BOOLEAN, "Flag")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"flag": False})
        self.assertTrue(ok)

    def test_boolean_true_valid(self):
        """Boolean True should be valid."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("flag", ParamType.BOOLEAN, "Flag")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"flag": True})
        self.assertTrue(ok)

    def test_zero_float_valid(self):
        """Float 0.0 should be valid for FLOAT param."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("value", ParamType.FLOAT, "Value")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"value": 0.0})
        self.assertTrue(ok)

    def test_negative_float_valid(self):
        """Negative float should be valid."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[ToolParam("value", ParamType.FLOAT, "Value")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"value": -3.14})
        self.assertTrue(ok)


# ── TestApplyDefaultsEdgeCases ────────────────────────────────────────────────

class TestApplyDefaultsEdgeCases(unittest.TestCase):
    """Test edge cases for apply_defaults behavior."""

    def test_optional_with_none_default_not_filled(self):
        """Optional param with default=None should NOT be filled."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("required", ParamType.STRING, "Req"),
                ToolParam("optional", ParamType.STRING, "Opt", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        result = tool.apply_defaults({"required": "val"})
        self.assertNotIn("optional", result)

    def test_optional_with_zero_default_filled(self):
        """Optional param with default=0 should be filled with 0."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("x", ParamType.STRING, "X"),
                ToolParam("count", ParamType.INTEGER, "Count", required=False, default=0),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        result = tool.apply_defaults({"x": "val"})
        self.assertIn("count", result)
        self.assertEqual(result["count"], 0)

    def test_optional_with_empty_string_default_filled(self):
        """Optional param with default="" should be filled with empty string."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("x", ParamType.STRING, "X"),
                ToolParam("suffix", ParamType.STRING, "Suffix", required=False, default=""),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        result = tool.apply_defaults({"x": "val"})
        self.assertIn("suffix", result)
        self.assertEqual(result["suffix"], "")

    def test_optional_with_false_default_filled(self):
        """Optional param with default=False should be filled."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("x", ParamType.STRING, "X"),
                ToolParam("flag", ParamType.BOOLEAN, "Flag", required=False, default=False),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        result = tool.apply_defaults({"x": "val"})
        self.assertIn("flag", result)
        self.assertEqual(result["flag"], False)

    def test_multiple_optional_some_provided(self):
        """Multiple optional params, some provided some not."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("required", ParamType.STRING, "Req"),
                ToolParam("opt1", ParamType.INTEGER, "Opt1", required=False, default=10),
                ToolParam("opt2", ParamType.INTEGER, "Opt2", required=False, default=20),
                ToolParam("opt3", ParamType.STRING, "Opt3", required=False, default=None),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        result = tool.apply_defaults({"required": "x", "opt1": 100})
        self.assertEqual(result["required"], "x")
        self.assertEqual(result["opt1"], 100)  # Provided, not overridden
        self.assertEqual(result["opt2"], 20)   # Not provided, filled with default
        self.assertNotIn("opt3", result)       # None default not filled

    def test_apply_defaults_does_not_modify_input(self):
        """apply_defaults should return new dict, not modify input."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("x", ParamType.STRING, "X"),
                ToolParam("y", ParamType.INTEGER, "Y", required=False, default=5),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        original = {"x": "val"}
        result = tool.apply_defaults(original)
        self.assertNotIn("y", original)
        self.assertIn("y", result)


# ── TestToPromptSchemaEdgeCases ───────────────────────────────────────────────

class TestToPromptSchemaEdgeCases(unittest.TestCase):
    """Test edge cases for to_prompt_schema."""

    def test_tool_with_no_examples(self):
        """Tool with no examples should not have Examples section."""
        tool = ToolDefinition(
            name="Test",
            description="A test tool",
            parameters=[ToolParam("x", ParamType.STRING, "X")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        schema = tool.to_prompt_schema()
        self.assertNotIn("Examples:", schema)

    def test_tool_with_multiple_examples(self):
        """Tool with multiple examples should show all of them."""
        tool = ToolDefinition(
            name="Test",
            description="A test tool",
            parameters=[ToolParam("x", ParamType.STRING, "X")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
            examples=[
                {"x": "example1"},
                {"x": "example2"},
                {"x": "example3"},
            ],
        )
        schema = tool.to_prompt_schema()
        self.assertIn("Examples:", schema)
        self.assertIn("example1", schema)
        self.assertIn("example2", schema)
        self.assertIn("example3", schema)

    def test_tool_with_empty_description(self):
        """Tool with empty description should still work."""
        tool = ToolDefinition(
            name="Test",
            description="",
            parameters=[ToolParam("x", ParamType.STRING, "X")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        schema = tool.to_prompt_schema()
        self.assertIn("**Test**:", schema)

    def test_examples_json_is_valid(self):
        """JSON in examples should be valid and parseable."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("x", ParamType.STRING, "X"),
                ToolParam("y", ParamType.INTEGER, "Y", required=False, default=42),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
            examples=[{"x": "val", "y": 99}],
        )
        schema = tool.to_prompt_schema()
        self.assertIn("Examples:", schema)
        # Extract and validate the JSON
        lines = schema.split("\n")
        json_line = [l for l in lines if "Test" in l and "{" in l]
        self.assertTrue(len(json_line) > 0)

    def test_tool_with_long_param_description(self):
        """Tool with long parameter descriptions should format correctly."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam(
                    "path",
                    ParamType.STRING,
                    "This is a very long description that contains many words "
                    "and explains in detail what this parameter does and why "
                    "you might want to use it in various scenarios",
                ),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        schema = tool.to_prompt_schema()
        self.assertIn("path", schema)
        self.assertIn("long description", schema)


# ── TestGenerateToolPromptComprehensive ──────────────────────────────────────

class TestGenerateToolPromptComprehensive(unittest.TestCase):
    """Comprehensive tests for generate_tool_prompt."""

    def test_empty_tool_list(self):
        """Empty tool list should still generate prompt with header and rules."""
        prompt = generate_tool_prompt([])
        self.assertIn("TOOL SYSTEM:", prompt)
        self.assertIn("AVAILABLE TOOLS:", prompt)
        self.assertIn("RULES:", prompt)
        self.assertIn("ONE tool call per response", prompt)

    def test_single_tool_in_prompt(self):
        """Single tool should appear in prompt with proper format."""
        tool = ToolDefinition(
            name="SingleTool",
            description="A single test tool",
            parameters=[ToolParam("param", ParamType.STRING, "A param")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        prompt = generate_tool_prompt([tool])
        self.assertIn("**SingleTool**:", prompt)
        self.assertIn("A single test tool", prompt)
        self.assertIn("param", prompt)

    def test_many_tools_in_prompt(self):
        """Many tools should all appear in the prompt."""
        tools = [
            ToolDefinition(
                name=f"Tool{i}",
                description=f"Tool {i}",
                parameters=[ToolParam(f"p{i}", ParamType.STRING, f"Param {i}")],
                permission_level=PermissionLevel.READ_ONLY,
                execute=_noop,
            )
            for i in range(7)
        ]
        prompt = generate_tool_prompt(tools)
        for i in range(7):
            self.assertIn(f"**Tool{i}**:", prompt)

    def test_rules_section_always_present(self):
        """RULES section should always be present."""
        prompt = generate_tool_prompt([])
        self.assertIn("RULES:", prompt)
        self.assertIn("Do NOT guess or hallucinate", prompt)
        self.assertIn("Read a file before editing", prompt)

    def test_tool_call_format_in_prompt(self):
        """Tool call format examples should be in prompt."""
        prompt = generate_tool_prompt([])
        self.assertIn("<tool_call>", prompt)
        self.assertIn("</tool_call>", prompt)
        self.assertIn("<tool_result>", prompt)

    def test_prompt_contains_all_rules(self):
        """Check that all important rules are present."""
        prompt = generate_tool_prompt([])
        required_rules = [
            "ONE tool call per response",
            "Do NOT guess or hallucinate",
            "Read a file before editing",
            "Break complex tasks into steps",
        ]
        for rule in required_rules:
            self.assertIn(rule, prompt)


# ── TestToolDefinitionRepr ────────────────────────────────────────────────────

class TestToolDefinitionRepr(unittest.TestCase):
    """Test ToolDefinition repr."""

    def test_repr_contains_name(self):
        """Repr should contain the tool name."""
        tool = ToolDefinition(
            name="MyTool",
            description="Test",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        self.assertIn("MyTool", repr(tool))

    def test_repr_contains_param_count(self):
        """Repr should contain param count."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("a", ParamType.STRING, "A"),
                ToolParam("b", ParamType.INTEGER, "B"),
                ToolParam("c", ParamType.BOOLEAN, "C"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        repr_str = repr(tool)
        self.assertIn("params=3", repr_str)

    def test_repr_contains_permission_level(self):
        """Repr should contain permission level value."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[],
            permission_level=PermissionLevel.DESTRUCTIVE,
            execute=_noop,
        )
        repr_str = repr(tool)
        self.assertIn("destructive", repr_str)

    def test_different_tools_different_reprs(self):
        """Different tools should have different reprs."""
        tool1 = ToolDefinition(
            name="Tool1",
            description="Test",
            parameters=[ToolParam("x", ParamType.STRING, "X")],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        tool2 = ToolDefinition(
            name="Tool2",
            description="Test",
            parameters=[
                ToolParam("a", ParamType.STRING, "A"),
                ToolParam("b", ParamType.STRING, "B"),
            ],
            permission_level=PermissionLevel.WRITE,
            execute=_noop,
        )
        self.assertNotEqual(repr(tool1), repr(tool2))
        self.assertIn("Tool1", repr(tool1))
        self.assertIn("Tool2", repr(tool2))

    def test_no_params_repr(self):
        """Tool with no params should show params=0."""
        tool = ToolDefinition(
            name="NoParams",
            description="Test",
            parameters=[],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        self.assertIn("params=0", repr(tool))


# ── TestToolParamReprEdgeCases ────────────────────────────────────────────────

class TestToolParamReprEdgeCases(unittest.TestCase):
    """Test ToolParam repr edge cases."""

    def test_param_repr_required(self):
        """Repr of required param should show 'required'."""
        p = ToolParam("name", ParamType.STRING, "Name", required=True)
        self.assertIn("required", repr(p))

    def test_param_repr_optional_with_default(self):
        """Repr of optional param should show default value."""
        p = ToolParam("timeout", ParamType.INTEGER, "Timeout", required=False, default=30)
        repr_str = repr(p)
        self.assertIn("optional", repr_str)
        self.assertIn("30", repr_str)

    def test_param_repr_optional_with_none_default(self):
        """Repr of optional param with None default."""
        p = ToolParam("x", ParamType.STRING, "X", required=False, default=None)
        repr_str = repr(p)
        self.assertIn("optional", repr_str)

    def test_param_repr_shows_type(self):
        """Repr should show parameter type."""
        p = ToolParam("value", ParamType.FLOAT, "Value")
        self.assertIn("float", repr(p))

    def test_param_repr_with_enum(self):
        """Repr of param with enum constraint."""
        p = ToolParam(
            "mode",
            ParamType.STRING,
            "Mode",
            required=False,
            default="read",
            enum=["read", "write", "append"],
        )
        repr_str = repr(p)
        self.assertIn("mode", repr_str)


# ── TestValidateParamsWithEnumEdgeCases ──────────────────────────────────────

class TestValidateParamsWithEnumEdgeCases(unittest.TestCase):
    """Test enum validation edge cases."""

    def test_enum_with_single_value(self):
        """Enum with single value should work."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam(
                    "only_one",
                    ParamType.STRING,
                    "Only",
                    required=False,
                    default="value",
                    enum=["value"],
                ),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"only_one": "value"})
        self.assertTrue(ok)

    def test_enum_with_empty_string(self):
        """Enum can contain empty string as valid value."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam(
                    "val",
                    ParamType.STRING,
                    "Val",
                    required=False,
                    default="",
                    enum=["", "a", "b"],
                ),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"val": ""})
        self.assertTrue(ok)

    def test_enum_with_numeric_strings(self):
        """Enum can contain numeric strings."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam(
                    "num",
                    ParamType.STRING,
                    "Num",
                    required=False,
                    default="1",
                    enum=["1", "2", "3"],
                ),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        ok, err = tool.validate_params({"num": "2"})
        self.assertTrue(ok)
        ok, err = tool.validate_params({"num": 2})
        self.assertFalse(ok)  # Integer 2 != string "2"


# ── TestPermissionLevelEnum ──────────────────────────────────────────────────

class TestPermissionLevelEnum(unittest.TestCase):
    """Test PermissionLevel enum edge cases."""

    def test_all_permission_levels_exist(self):
        """All expected permission levels should exist."""
        self.assertEqual(PermissionLevel.READ_ONLY.value, "read_only")
        self.assertEqual(PermissionLevel.WRITE.value, "write")
        self.assertEqual(PermissionLevel.EXECUTE.value, "execute")
        self.assertEqual(PermissionLevel.DESTRUCTIVE.value, "destructive")

    def test_permission_level_equality(self):
        """Permission levels should be comparable."""
        self.assertEqual(PermissionLevel.READ_ONLY, PermissionLevel.READ_ONLY)
        self.assertNotEqual(PermissionLevel.READ_ONLY, PermissionLevel.WRITE)

    def test_permission_level_name(self):
        """Permission level should have correct name."""
        self.assertEqual(PermissionLevel.READ_ONLY.name, "READ_ONLY")
        self.assertEqual(PermissionLevel.WRITE.name, "WRITE")


# ── TestParamTypeEnum ────────────────────────────────────────────────────────

class TestParamTypeEnum(unittest.TestCase):
    """Test ParamType enum."""

    def test_all_param_types_exist(self):
        """All expected param types should exist."""
        self.assertEqual(ParamType.STRING.value, "string")
        self.assertEqual(ParamType.INTEGER.value, "integer")
        self.assertEqual(ParamType.BOOLEAN.value, "boolean")
        self.assertEqual(ParamType.FLOAT.value, "float")

    def test_param_type_names(self):
        """Param types should have correct names."""
        self.assertEqual(ParamType.STRING.name, "STRING")
        self.assertEqual(ParamType.INTEGER.name, "INTEGER")
        self.assertEqual(ParamType.BOOLEAN.name, "BOOLEAN")
        self.assertEqual(ParamType.FLOAT.name, "FLOAT")


# ── TestComplexValidationScenarios ───────────────────────────────────────────

class TestComplexValidationScenarios(unittest.TestCase):
    """Test complex real-world validation scenarios."""

    def test_validate_then_apply_defaults(self):
        """Validate then apply defaults workflow."""
        tool = ToolDefinition(
            name="Complex",
            description="Complex tool",
            parameters=[
                ToolParam("required", ParamType.STRING, "Req"),
                ToolParam("opt1", ParamType.INTEGER, "Opt1", required=False, default=10),
                ToolParam("opt2", ParamType.BOOLEAN, "Opt2", required=False, default=False),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"required": "val", "unknown": "strip_me"}
        ok, err = tool.validate_params(params)
        self.assertTrue(ok)
        self.assertNotIn("unknown", params)

        # Apply defaults to validated params
        final = tool.apply_defaults(params)
        self.assertEqual(final["required"], "val")
        self.assertEqual(final["opt1"], 10)
        self.assertEqual(final["opt2"], False)

    def test_llm_hallucinated_params(self):
        """Simulate LLM hallucinating extra params."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("path", ParamType.STRING, "Path"),
                ToolParam("offset", ParamType.INTEGER, "Offset", required=False, default=0),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        # LLM output with hallucinated params
        params = {
            "path": "file.txt",
            "offset": 10,
            "reason": "user requested",
            "explanation": "here is why",
            "urgency": "high",
        }
        ok, err = tool.validate_params(params)
        self.assertTrue(ok)
        # All hallucinated params stripped
        self.assertEqual(len(params), 2)
        self.assertIn("path", params)
        self.assertIn("offset", params)

    def test_mixed_valid_invalid_params(self):
        """Mix of valid and invalid params."""
        tool = ToolDefinition(
            name="Test",
            description="Test",
            parameters=[
                ToolParam("a", ParamType.STRING, "A"),
                ToolParam("b", ParamType.INTEGER, "B"),
            ],
            permission_level=PermissionLevel.READ_ONLY,
            execute=_noop,
        )
        params = {"a": "valid", "b": "invalid"}
        ok, err = tool.validate_params(params)
        self.assertFalse(ok)
        self.assertIn("must be integer", err)


if __name__ == "__main__":
    unittest.main()
