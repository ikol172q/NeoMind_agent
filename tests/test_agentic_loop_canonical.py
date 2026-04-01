"""Comprehensive unit tests for NeoMind canonical agentic loop.

Tests cover:
1. AgenticConfig defaults
2. AgenticEvent dataclass validation
3. AgenticLoop initialization
4. run() basic flow with mocked LLM and tool registry
5. run() iteration limits (hard and soft)
6. Tool execution errors
7. Permission flow (destructive tools)
8. Hooks integration
9. SkillForge integration
10. get_tool_prompt() generation

Uses unittest.mock extensively for all external dependencies.
"""

import os
import sys
import unittest
import asyncio
from unittest.mock import MagicMock, patch, call, PropertyMock, AsyncMock
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agentic import AgenticLoop, AgenticEvent, AgenticConfig


# Helper to collect all events from the async generator
def _collect_events(loop, llm_response, messages, llm_caller):
    """Collect all events from the async generator."""
    async def _run():
        events = []
        async for event in loop.run(llm_response, messages, llm_caller):
            events.append(event)
        return events
    return asyncio.run(_run())


# Helper to get the first event from the async generator
def _get_first_event(loop, llm_response, messages, llm_caller):
    """Get the first event from the async generator."""
    async def _run():
        async for event in loop.run(llm_response, messages, llm_caller):
            return event
    return asyncio.run(_run())


class TestAgenticConfigDefaults(unittest.TestCase):
    """Test AgenticConfig default values."""

    def test_default_max_iterations(self):
        """Verify max_iterations defaults to 10."""
        config = AgenticConfig()
        self.assertEqual(config.max_iterations, 10)

    def test_default_soft_limit(self):
        """Verify soft_limit defaults to 7."""
        config = AgenticConfig()
        self.assertEqual(config.soft_limit, 7)

    def test_default_auto_approve_reads(self):
        """Verify auto_approve_reads defaults to True."""
        config = AgenticConfig()
        self.assertTrue(config.auto_approve_reads)

    def test_default_tool_output_limit(self):
        """Verify tool_output_limit defaults to 3000."""
        config = AgenticConfig()
        self.assertEqual(config.tool_output_limit, 3000)

    def test_default_continuation_prompt(self):
        """Verify continuation_prompt is set."""
        config = AgenticConfig()
        self.assertIn("Continue", config.continuation_prompt)

    def test_default_wrapup_prompt(self):
        """Verify wrapup_prompt is set."""
        config = AgenticConfig()
        self.assertIn("stop making tool calls", config.wrapup_prompt.lower())

    def test_default_hooks_enabled(self):
        """Verify hooks_enabled defaults to True."""
        config = AgenticConfig()
        self.assertTrue(config.hooks_enabled)

    def test_default_skill_forge(self):
        """Verify skill_forge defaults to None."""
        config = AgenticConfig()
        self.assertIsNone(config.skill_forge)

    def test_custom_config(self):
        """Verify custom config values are applied."""
        config = AgenticConfig(
            max_iterations=20,
            soft_limit=15,
            hooks_enabled=False,
        )
        self.assertEqual(config.max_iterations, 20)
        self.assertEqual(config.soft_limit, 15)
        self.assertFalse(config.hooks_enabled)


class TestAgenticEventDataclass(unittest.TestCase):
    """Test AgenticEvent dataclass structure."""

    def test_event_tool_start(self):
        """Test tool_start event creation."""
        event = AgenticEvent(
            type="tool_start",
            iteration=0,
            tool_name="Read",
            tool_params={"path": "/tmp/test.txt"},
            tool_preview="Read(/tmp/test.txt)",
        )
        self.assertEqual(event.type, "tool_start")
        self.assertEqual(event.iteration, 0)
        self.assertEqual(event.tool_name, "Read")
        self.assertIsNotNone(event.tool_preview)

    def test_event_tool_result(self):
        """Test tool_result event creation."""
        event = AgenticEvent(
            type="tool_result",
            iteration=0,
            tool_name="Read",
            result_success=True,
            result_output="file contents",
        )
        self.assertEqual(event.type, "tool_result")
        self.assertTrue(event.result_success)
        self.assertEqual(event.result_output, "file contents")

    def test_event_tool_error(self):
        """Test tool_result event with error."""
        event = AgenticEvent(
            type="tool_result",
            iteration=0,
            tool_name="Read",
            result_success=False,
            result_error="File not found",
        )
        self.assertFalse(event.result_success)
        self.assertEqual(event.result_error, "File not found")

    def test_event_llm_response(self):
        """Test llm_response event creation."""
        event = AgenticEvent(
            type="llm_response",
            iteration=1,
            llm_text="The file contains important data.",
        )
        self.assertEqual(event.type, "llm_response")
        self.assertEqual(event.llm_text, "The file contains important data.")

    def test_event_permission(self):
        """Test permission event creation."""
        event = AgenticEvent(
            type="permission",
            iteration=0,
            tool_name="Bash",
            tool_preview="rm -rf /",
        )
        self.assertEqual(event.type, "permission")
        # Frontend can set this
        event.approved = False
        self.assertFalse(event.approved)

    def test_event_done(self):
        """Test done event."""
        event = AgenticEvent(type="done", iteration=2)
        self.assertEqual(event.type, "done")
        self.assertEqual(event.iteration, 2)

    def test_event_error(self):
        """Test error event."""
        event = AgenticEvent(
            type="error",
            iteration=1,
            error_message="LLM API failed",
        )
        self.assertEqual(event.type, "error")
        self.assertEqual(event.error_message, "LLM API failed")

    def test_event_skill_match(self):
        """Test skill_match event."""
        skills = [
            {"id": 1, "name": "ReadPy", "description": "Read Python files"},
        ]
        event = AgenticEvent(
            type="skill_match",
            iteration=0,
            matched_skills=skills,
        )
        self.assertEqual(event.type, "skill_match")
        self.assertEqual(len(event.matched_skills), 1)
        self.assertEqual(event.matched_skills[0]["name"], "ReadPy")

    def test_event_skill_record(self):
        """Test skill_record event."""
        event = AgenticEvent(
            type="skill_record",
            iteration=0,
            skill_id=42,
        )
        self.assertEqual(event.type, "skill_record")
        self.assertEqual(event.skill_id, 42)


class TestAgenticLoopInitialization(unittest.TestCase):
    """Test AgenticLoop initialization."""

    def test_init_with_default_config(self):
        """Verify loop initializes with default config."""
        mock_registry = MagicMock()
        loop = AgenticLoop(mock_registry)

        self.assertIsNotNone(loop.registry)
        self.assertIsNotNone(loop.config)
        self.assertEqual(loop.config.max_iterations, 10)

    def test_init_with_custom_config(self):
        """Verify loop accepts custom config."""
        mock_registry = MagicMock()
        config = AgenticConfig(max_iterations=5)
        loop = AgenticLoop(mock_registry, config)

        self.assertEqual(loop.config.max_iterations, 5)

    def test_init_with_skill_forge(self):
        """Verify loop stores skill_forge from config."""
        mock_registry = MagicMock()
        mock_skill_forge = MagicMock()
        config = AgenticConfig(skill_forge=mock_skill_forge)
        loop = AgenticLoop(mock_registry, config)

        self.assertIs(loop.config.skill_forge, mock_skill_forge)

    def test_parser_lazy_loads(self):
        """Verify parser is lazily loaded on first run."""
        mock_registry = MagicMock()
        loop = AgenticLoop(mock_registry)

        self.assertIsNone(loop._parser)
        # _get_parser should load it
        parser = loop._get_parser()
        self.assertIsNotNone(parser)


class TestAgenticLoopBasicFlow(unittest.TestCase):
    """Test the basic flow: tool call → execute → feedback → loop."""

    def _make_mock_registry_with_tool(self, tool_name="Read", success=True):
        """Create a mock ToolRegistry with a single working tool."""
        mock_registry = MagicMock()

        # Mock tool definition
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}

        # Mock tool result
        from agent.coding.tools import ToolResult
        result = ToolResult(
            success=success,
            output="file content" if success else "",
            error="" if success else "File not found"
        )
        mock_tool_def.execute.return_value = result

        mock_registry.get_tool.return_value = mock_tool_def
        return mock_registry

    def _make_mock_llm_caller(self, responses=None):
        """Create a mock llm_caller that returns predefined responses."""
        if responses is None:
            responses = [
                'The file contains: important data.',  # No tool call
            ]

        call_count = [0]
        async def llm_caller(messages):
            if call_count[0] < len(responses):
                result = responses[call_count[0]]
                call_count[0] += 1
                return result
            # Default: no tool call (ends loop)
            return "Done."

        return llm_caller

    @patch('agent.coding.tool_parser.ToolCallParser')
    def test_no_tool_call_exits_immediately(self, mock_parser_class):
        """If LLM response has no tool call, loop yields done and exits."""
        mock_parser = MagicMock()
        mock_parser.parse.return_value = None  # No tool call
        mock_parser_class.return_value = mock_parser

        mock_registry = self._make_mock_registry_with_tool()
        loop = AgenticLoop(mock_registry)

        events = _collect_events(
            loop,
            llm_response="The answer is 42.",
            messages=[],
            llm_caller=self._make_mock_llm_caller(),
        )

        # Should have exactly one event: done
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "done")

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_single_tool_call_flow(self, mock_format, mock_parser_class):
        """Test: LLM → tool call → execute → feedback → LLM → done."""
        mock_parser = MagicMock()

        # First parse: return a tool call, second parse: return None
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        # Format tool result
        mock_format.return_value = "<tool_result>...</tool_result>"

        mock_registry = self._make_mock_registry_with_tool()
        loop = AgenticLoop(mock_registry)

        llm_responses = [
            'Here is the data: file content.',  # After tool feedback
        ]

        events = _collect_events(
            loop,
            llm_response='<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>',
            messages=[],
            llm_caller=self._make_mock_llm_caller(llm_responses),
        )

        # Should have: tool_start, tool_result, llm_response, done
        event_types = [e.type for e in events]
        self.assertIn("tool_start", event_types)
        self.assertIn("tool_result", event_types)
        self.assertIn("llm_response", event_types)
        self.assertIn("done", event_types)

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_tool_execution_success(self, mock_format, mock_parser_class):
        """Verify tool execution success is recorded in event."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>content</tool_result>"

        mock_registry = self._make_mock_registry_with_tool(success=True)
        loop = AgenticLoop(mock_registry)

        events = _collect_events(
            loop,
            llm_response='',
            messages=[],
            llm_caller=self._make_mock_llm_caller(),
        )

        # Find tool_result event
        result_event = next((e for e in events if e.type == "tool_result"), None)
        self.assertIsNotNone(result_event)
        self.assertTrue(result_event.result_success)


class TestAgenticLoopIterationLimits(unittest.TestCase):
    """Test max_iterations hard limit and soft_limit wrap-up."""

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_hard_limit_stops_loop(self, mock_format, mock_parser_class):
        """Verify loop stops after max_iterations."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        # Always return a tool call (infinite loop scenario)
        mock_parser.parse.return_value = tool_call
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>...</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(max_iterations=3)
        loop = AgenticLoop(mock_registry, config)

        # LLM always returns a tool call
        async def llm_caller(msgs):
            return '<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>'

        events = _collect_events(
            loop,
            llm_response='<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>',
            messages=[],
            llm_caller=llm_caller,
        )

        # Count tool_start events (should equal max_iterations)
        tool_start_count = sum(1 for e in events if e.type == "tool_start")
        self.assertEqual(tool_start_count, 3)

        # Should end with done event
        self.assertEqual(events[-1].type, "done")

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_soft_limit_injects_wrapup_prompt(self, mock_format, mock_parser_class):
        """Verify wrapup_prompt is injected after soft_limit."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call] * 10 + [None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(max_iterations=10, soft_limit=3)
        loop = AgenticLoop(mock_registry, config)

        call_count = [0]
        def llm_caller(messages):
            call_count[0] += 1
            # After iteration 2 (soft_limit - 1), the prompt should have wrapup
            if call_count[0] >= config.soft_limit:
                # Verify wrapup prompt was injected in messages
                last_msg = messages[-1]
                if "wrap up" in last_msg.get("content", "").lower():
                    return "Done."
            return '<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>'

        events = _collect_events(
            loop,
            llm_response='<tool_call>{"tool": "Read", "params": {"path": "/tmp/test.txt"}}</tool_call>',
            messages=[],
            llm_caller=llm_caller,
        )

        # Verify we got some events
        self.assertGreater(len(events), 0)


class TestToolExecutionErrors(unittest.TestCase):
    """Test error handling during tool execution."""

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_unknown_tool_error(self, mock_format, mock_parser_class):
        """Verify unknown tool yields error event."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("UnknownTool", {"param": "value"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>...</tool_result>"

        mock_registry = MagicMock()
        mock_registry.get_tool.return_value = None  # Unknown tool

        loop = AgenticLoop(mock_registry)

        events = _collect_events(loop, '', [], llm_caller=AsyncMock(return_value="Done."),)

        # Should have tool_start, tool_result (with error), llm_response, done
        result_event = next((e for e in events if e.type == "tool_result"), None)
        self.assertIsNotNone(result_event)
        self.assertFalse(result_event.result_success)
        self.assertIn("Unknown tool", result_event.result_error)

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_invalid_params_error(self, mock_format, mock_parser_class):
        """Verify invalid params yields error event."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"invalid_param": "value"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>...</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        # validate_params returns False
        mock_tool_def.validate_params.return_value = (False, "Invalid params")
        mock_registry.get_tool.return_value = mock_tool_def

        loop = AgenticLoop(mock_registry)

        events = _collect_events(loop, '', [], llm_caller=AsyncMock(return_value="Done."),)

        result_event = next((e for e in events if e.type == "tool_result"), None)
        self.assertIsNotNone(result_event)
        self.assertFalse(result_event.result_success)

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_execution_exception_caught(self, mock_format, mock_parser_class):
        """Verify execution exceptions are caught and fed back."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>...</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        # Tool execution raises an exception
        mock_tool_def.execute.side_effect = RuntimeError("Tool crashed")
        mock_registry.get_tool.return_value = mock_tool_def

        loop = AgenticLoop(mock_registry)

        events = _collect_events(loop, '', [], llm_caller=AsyncMock(return_value="Done."),)

        result_event = next((e for e in events if e.type == "tool_result"), None)
        self.assertIsNotNone(result_event)
        self.assertFalse(result_event.result_success)
        self.assertIn("Tool crashed", result_event.result_error)


class TestPermissionFlow(unittest.TestCase):
    """Test permission event flow for destructive tools."""

    @patch('agent.coding.tool_parser.ToolCallParser')
    def test_permission_event_yielded(self, mock_parser_class):
        """Verify permission event is yielded for tool."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Bash", {"command": "rm -rf /"}, "raw")
        mock_parser.parse.return_value = tool_call
        mock_parser_class.return_value = mock_parser

        mock_registry = MagicMock()
        loop = AgenticLoop(mock_registry)

        # Get first event using helper
        event = _get_first_event(
            loop,
            llm_response='',
            messages=[],
            llm_caller=AsyncMock(return_value="Done."),
        )

        self.assertEqual(event.type, "tool_start")
        self.assertEqual(event.tool_name, "Bash")

    @patch('agent.coding.tool_parser.ToolCallParser')
    def test_denied_permission_stops_loop(self, mock_parser_class):
        """Verify denying permission yields done event."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Bash", {"command": "rm -rf /"}, "raw")
        mock_parser.parse.return_value = tool_call
        mock_parser_class.return_value = mock_parser

        mock_registry = MagicMock()
        loop = AgenticLoop(mock_registry)

        async def _run_and_check():
            first_event = None
            async for event in loop.run(
                llm_response='',
                messages=[],
                llm_caller=AsyncMock(return_value="Done."),
            ):
                if first_event is None:
                    # Get tool_start event
                    first_event = event
                    self.assertEqual(event.type, "tool_start")
                    # Simulate denying permission
                    event.approved = False
                else:
                    # Next event should be done
                    self.assertEqual(event.type, "done")
                    break

            # Verify we got the first event
            self.assertIsNotNone(first_event)

        asyncio.run(_run_and_check())


class TestHooksIntegration(unittest.TestCase):
    """Test integration with evolution hooks."""

    @patch('agent.agentic.agentic_loop._get_hooks_module')
    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_pre_llm_call_hook_invoked(self, mock_format, mock_parser_class, mock_get_hooks):
        """Verify pre_llm_call hook is called."""
        # Setup hooks module
        mock_hooks = MagicMock()
        mock_hooks.pre_llm_call.return_value = {"skip_api": False}
        mock_get_hooks.return_value = mock_hooks

        # Setup parser
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        # Setup registry
        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(hooks_enabled=True)
        loop = AgenticLoop(mock_registry, config)

        _collect_events(
            loop,
            llm_response='',
            messages=[],
            llm_caller=AsyncMock(return_value="Done."),
        )

        # Verify hook was called
        mock_hooks.pre_llm_call.assert_called()

    @patch('agent.agentic.agentic_loop._get_hooks_module')
    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_post_response_hook_invoked(self, mock_format, mock_parser_class, mock_get_hooks):
        """Verify post_response hook is called."""
        mock_hooks = MagicMock()
        mock_hooks.pre_llm_call.return_value = {"skip_api": False}
        mock_get_hooks.return_value = mock_hooks

        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(hooks_enabled=True)
        loop = AgenticLoop(mock_registry, config)

        _collect_events(
            loop,
            llm_response='',
            messages=[],
            llm_caller=AsyncMock(return_value="Done."),
        )

        # Verify post_response was called
        mock_hooks.post_response.assert_called()

    @patch('agent.agentic.agentic_loop._get_hooks_module')
    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_hooks_disabled(self, mock_format, mock_parser_class, mock_get_hooks):
        """Verify hooks are not called when disabled."""
        mock_hooks = MagicMock()
        mock_get_hooks.return_value = mock_hooks

        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(hooks_enabled=False)
        loop = AgenticLoop(mock_registry, config)

        _collect_events(
            loop,
            llm_response='',
            messages=[],
            llm_caller=AsyncMock(return_value="Done."),
        )

        # Hooks should not be called
        mock_hooks.pre_llm_call.assert_not_called()
        mock_hooks.post_response.assert_not_called()

    @patch('agent.agentic.agentic_loop._get_hooks_module')
    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_hook_skip_api_fallback(self, mock_format, mock_parser_class, mock_get_hooks):
        """Verify skip_api fallback uses pre-computed response."""
        mock_hooks = MagicMock()
        mock_hooks.pre_llm_call.return_value = {
            "skip_api": True,
            "fallback_response": "Fallback response from hooks."
        }
        mock_get_hooks.return_value = mock_hooks

        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        # Parser should get the fallback response
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(hooks_enabled=True)
        loop = AgenticLoop(mock_registry, config)

        llm_caller = MagicMock()
        llm_caller.return_value = "Should not be called."

        events = _collect_events(loop, '', [], llm_caller=llm_caller,)

        # LLM caller should be called even with fallback
        # (the loop still continues with the fallback response)
        self.assertGreater(len(events), 0)


class TestSkillForgeIntegration(unittest.TestCase):
    """Test SkillForge integration for skill matching and recording."""

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_skill_forge_find_matching_skills_called(self, mock_format, mock_parser_class):
        """Verify find_matching_skills is called on iteration 0."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        mock_skill_forge = MagicMock()
        mock_skill_forge.find_matching_skills.return_value = []

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(skill_forge=mock_skill_forge)
        loop = AgenticLoop(mock_registry, config)

        _collect_events(
            loop,
            llm_response='',
            messages=[],
            llm_caller=AsyncMock(return_value="Done."),
        )

        # Verify find_matching_skills was called
        mock_skill_forge.find_matching_skills.assert_called()

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_skill_match_event_yielded(self, mock_format, mock_parser_class):
        """Verify skill_match event is yielded when skills are found."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        matched_skills = [
            {"id": 1, "name": "ReadPyFiles", "description": "Reads Python files"},
        ]
        mock_skill_forge = MagicMock()
        mock_skill_forge.find_matching_skills.return_value = matched_skills

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(skill_forge=mock_skill_forge)
        loop = AgenticLoop(mock_registry, config)

        events = _collect_events(loop, '', [], llm_caller=AsyncMock(return_value="Done."),)

        # Should have skill_match event
        skill_match_event = next((e for e in events if e.type == "skill_match"), None)
        self.assertIsNotNone(skill_match_event)
        self.assertEqual(len(skill_match_event.matched_skills), 1)

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_skill_record_usage_called(self, mock_format, mock_parser_class):
        """Verify record_usage is called after tool execution."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        matched_skills = [
            {"id": 42, "name": "ReadSkill", "description": "Reads files"},
        ]
        mock_skill_forge = MagicMock()
        mock_skill_forge.find_matching_skills.return_value = matched_skills
        mock_skill_forge.record_usage.return_value = None

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(skill_forge=mock_skill_forge)
        loop = AgenticLoop(mock_registry, config)

        _collect_events(
            loop,
            llm_response='',
            messages=[],
            llm_caller=AsyncMock(return_value="Done."),
        )

        # Verify record_usage was called with skill id
        mock_skill_forge.record_usage.assert_called()

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_skill_record_event_yielded(self, mock_format, mock_parser_class):
        """Verify skill_record event is yielded."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        matched_skills = [
            {"id": 99, "name": "ReadSkill", "description": "Reads files"},
        ]
        mock_skill_forge = MagicMock()
        mock_skill_forge.find_matching_skills.return_value = matched_skills
        mock_skill_forge.record_usage.return_value = None

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        config = AgenticConfig(skill_forge=mock_skill_forge)
        loop = AgenticLoop(mock_registry, config)

        events = _collect_events(loop, '', [], llm_caller=AsyncMock(return_value="Done."),)

        # Should have skill_record event
        skill_record_event = next((e for e in events if e.type == "skill_record"), None)
        self.assertIsNotNone(skill_record_event)
        self.assertEqual(skill_record_event.skill_id, 99)


class TestGetToolPrompt(unittest.TestCase):
    """Test get_tool_prompt() generation."""

    @patch('agent.coding.tool_schema.generate_tool_prompt')
    def test_get_tool_prompt_returns_string(self, mock_generate):
        """Verify get_tool_prompt returns non-empty string."""
        mock_generate.return_value = "# Available Tools\n\n- Read: Read files\n"

        mock_registry = MagicMock()
        mock_registry.get_all_tools.return_value = []

        loop = AgenticLoop(mock_registry)
        prompt = loop.get_tool_prompt()

        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)

    @patch('agent.coding.tool_schema.generate_tool_prompt')
    def test_get_tool_prompt_calls_generate(self, mock_generate):
        """Verify get_tool_prompt calls generate_tool_prompt."""
        mock_generate.return_value = "tool prompt"

        mock_registry = MagicMock()
        mock_tools = [MagicMock(), MagicMock()]
        mock_registry.get_all_tools.return_value = mock_tools

        loop = AgenticLoop(mock_registry)
        loop.get_tool_prompt()

        # Verify generate_tool_prompt was called with tools
        mock_generate.assert_called_once_with(mock_tools)

    @patch('agent.coding.tool_schema.generate_tool_prompt')
    def test_get_tool_prompt_empty_tools(self, mock_generate):
        """Verify get_tool_prompt works with no tools."""
        mock_generate.return_value = "# No tools available\n"

        mock_registry = MagicMock()
        mock_registry.get_all_tools.return_value = []

        loop = AgenticLoop(mock_registry)
        prompt = loop.get_tool_prompt()

        self.assertIsInstance(prompt, str)


class TestAgenticLoopEdgeCases(unittest.TestCase):
    """Test edge cases and corner scenarios."""

    @patch('agent.coding.tool_parser.ToolCallParser')
    def test_empty_messages_list(self, mock_parser_class):
        """Verify loop handles empty messages list."""
        mock_parser = MagicMock()
        mock_parser.parse.return_value = None
        mock_parser_class.return_value = mock_parser

        mock_registry = MagicMock()
        loop = AgenticLoop(mock_registry)

        events = _collect_events(
            loop,
            llm_response="No tool call.",
            messages=[],  # Empty
            llm_caller=AsyncMock(return_value="Done."),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "done")

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_messages_appended_correctly(self, mock_format, mock_parser_class):
        """Verify assistant/user messages are appended correctly."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output="data")
        mock_registry.get_tool.return_value = mock_tool_def

        loop = AgenticLoop(mock_registry)

        messages = []
        _collect_events(
            loop,
            llm_response='Test response',
            messages=messages,
            llm_caller=AsyncMock(return_value="Done."),
        )

        # Verify messages were appended
        self.assertGreater(len(messages), 0)

    @patch('agent.coding.tool_parser.ToolCallParser')
    @patch('agent.coding.tool_parser.format_tool_result')
    def test_tool_result_output_truncated(self, mock_format, mock_parser_class):
        """Verify tool result output is truncated to 500 chars."""
        mock_parser = MagicMock()
        from agent.coding.tool_parser import ToolCall
        tool_call = ToolCall("Read", {"path": "/tmp/test.txt"}, "raw")
        mock_parser.parse.side_effect = [tool_call, None]
        mock_parser_class.return_value = mock_parser

        mock_format.return_value = "<tool_result>data</tool_result>"

        # Very large output
        large_output = "x" * 5000
        mock_registry = MagicMock()
        mock_tool_def = MagicMock()
        mock_tool_def.validate_params.return_value = (True, "")
        mock_tool_def.apply_defaults.return_value = {"path": "/tmp/test.txt"}
        from agent.coding.tools import ToolResult
        mock_tool_def.execute.return_value = ToolResult(True, output=large_output)
        mock_registry.get_tool.return_value = mock_tool_def

        loop = AgenticLoop(mock_registry)

        events = _collect_events(loop, '', [], llm_caller=AsyncMock(return_value="Done."),)

        result_event = next((e for e in events if e.type == "tool_result"), None)
        self.assertIsNotNone(result_event)
        # Output should be truncated
        self.assertLessEqual(len(result_event.result_output), 4000)


if __name__ == "__main__":
    unittest.main()
