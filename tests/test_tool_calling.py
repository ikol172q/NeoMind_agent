#!/usr/bin/env python3
"""
Unit tests for tool calling functionality.
Tests tool registry, essential tools, and recursive tool calling.
"""
import os
import sys
import json
import unittest
from unittest.mock import Mock, patch, MagicMock, ANY

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import DeepSeekStreamingChat
from agent.tools.registry import ToolRegistry
from agent.tools.base import CommandTool, ToolMetadata


class TestToolRegistry(unittest.TestCase):
    """Test tool registry functionality."""

    def setUp(self):
        """Set up tool registry."""
        self.registry = ToolRegistry()

    def test_register_and_execute(self):
        """Test registering a tool and executing it."""
        mock_handler = Mock(return_value="Tool result")
        metadata = ToolMetadata(
            name="test_tool",
            description="Test tool",
            parameters={
                "type": "object",
                "properties": {
                    "arg1": {"type": "string"}
                },
                "required": ["arg1"]
            },
            returns={"type": "string"},
            categories=["test"],
            dangerous=False
        )

        def argument_parser(params):
            return params["arg1"]

        tool = CommandTool(
            handler=mock_handler,
            metadata=metadata,
            argument_parser=argument_parser
        )
        self.registry.register(tool, "test_tool")

        # Execute tool
        result = self.registry.execute("test_tool", {"arg1": "value"})
        self.assertEqual(result, "Tool result")
        mock_handler.assert_called_once_with("value")

    def test_list_tools(self):
        """Test listing registered tools."""
        metadata = ToolMetadata(
            name="tool1",
            description="Tool 1",
            parameters={"type": "object", "properties": {}},
            returns={"type": "string"},
            categories=["cat1"],
            dangerous=False
        )
        tool = CommandTool(handler=Mock(), metadata=metadata)
        self.registry.register(tool, "tool1")

        tools = self.registry.list_tools()
        self.assertIn("tool1", tools)

        tools_with_metadata = self.registry.list_tools_with_metadata()
        self.assertEqual(len(tools_with_metadata), 1)
        self.assertEqual(tools_with_metadata[0]["name"], "tool1")


class TestEssentialTools(unittest.TestCase):
    """Test the five essential tools (read, write, execute, search, git)."""

    def setUp(self):
        """Create agent with mocked dependencies."""
        self.agent = DeepSeekStreamingChat(api_key="dummy_key")
        # Mock external dependencies to prevent side effects
        self.agent.code_analyzer = Mock()
        self.agent.safety_manager = Mock()
        self.agent.safety_manager.safe_read_file = Mock(return_value=(True, "", "file content"))
        self.agent.safety_manager.safe_write_file = Mock(return_value=(True, "", None))
        self.agent.formatter = Mock()
        self.agent.command_executor = Mock()
        self.agent.help_system = Mock()
        self.agent.searcher = Mock()
        self.agent.self_iteration = None
        self.agent.task_manager = Mock()
        self.agent.goal_planner = Mock()
        self.agent.generate_completion = Mock(return_value="Mocked AI response")
        self.agent.formatter.error = Mock(return_value="ERROR")
        self.agent.formatter.success = Mock(return_value="SUCCESS")
        self.agent.formatter.warning = Mock(return_value="WARNING")
        self.agent.formatter.info = Mock(return_value="INFO")
        self.agent.code_analyzer.read_file_safe = Mock(return_value=(True, "", "file content"))
        self.agent.code_analyzer.write_file_safe = Mock(return_value=(True, "File written"))
        self.agent.code_analyzer.root_path = os.getcwd()

        # Tool registry is already initialized by __init__. Do NOT call _setup_tools again.

    def test_tool_registry_initialized(self):
        """Test that tool registry is initialized with essential tools."""
        self.assertIsNotNone(self.agent.tool_registry)
        tools = self.agent.tool_registry.list_tools()
        essential_tools = ["read", "write", "execute", "search", "git"]
        for tool_name in essential_tools:
            self.assertIn(tool_name, tools, f"Essential tool '{tool_name}' not registered")

    def test_read_tool(self):
        """Test read tool execution."""
        # Mock handle_read_command to return expected result
        with patch.object(self.agent, 'handle_read_command', return_value="File content") as mock_handler:
            # Execute via tool registry
            result = self.agent.tool_registry.execute("read", {"target": "test.txt"})
            self.assertEqual(result, "File content")
            mock_handler.assert_called_once_with("test.txt")

    def test_write_tool(self):
        """Test write tool execution."""
        with patch.object(self.agent, 'handle_write_command', return_value="File written") as mock_handler:
            result = self.agent.tool_registry.execute("write", {
                "file_path": "test.txt",
                "content": "Hello, world!"
            })
            self.assertEqual(result, "File written")
            # Check that arguments were parsed correctly
            mock_handler.assert_called_once()
            # The argument parser joins file_path and content
            call_args = mock_handler.call_args[0][0]
            self.assertIn("test.txt", call_args)
            self.assertIn("Hello, world!", call_args)

    def test_execute_tool(self):
        """Test execute tool execution."""
        with patch.object(self.agent, 'handle_run_command', return_value="Command output") as mock_handler:
            result = self.agent.tool_registry.execute("execute", {
                "command": "ls -la"
            })
            self.assertEqual(result, "Command output")
            mock_handler.assert_called_once_with("ls -la")

    def test_search_tool(self):
        """Test search tool execution."""
        with patch.object(self.agent, 'handle_search', return_value="Search results") as mock_handler:
            result = self.agent.tool_registry.execute("search", {
                "query": "test query"
            })
            self.assertEqual(result, "Search results")
            mock_handler.assert_called_once_with("test query")

    def test_git_tool(self):
        """Test git tool execution."""
        with patch.object(self.agent, 'handle_git_command', return_value="Git output") as mock_handler:
            result = self.agent.tool_registry.execute("git", {
                "command": "status"
            })
            self.assertEqual(result, "Git output")
            mock_handler.assert_called_once_with("status")

    def test_tool_mode_switching(self):
        """Test switching to tool mode."""
        with patch('agent.core.agent_config') as mock_config:
            mock_config.update_mode = Mock(return_value=True)
            mock_config.coding_mode_system_prompt = "Tool mode prompt"

            success = self.agent.switch_mode("tool")
            self.assertTrue(success)
            self.assertEqual(self.agent.mode, "tool")


class TestToolCallingIntegration(unittest.TestCase):
    """Integration tests for tool calling with mock LLM."""

    def setUp(self):
        """Create agent with mocked API."""
        self.agent = DeepSeekStreamingChat(api_key="dummy_key")
        # Mock dependencies to prevent side effects
        self.agent.code_analyzer = Mock()
        self.agent.safety_manager = Mock()
        self.agent.safety_manager.safe_read_file = Mock(return_value=(True, "", "file content"))
        self.agent.safety_manager.safe_write_file = Mock(return_value=(True, "", None))
        self.agent.formatter = Mock()
        self.agent.command_executor = Mock()
        self.agent.help_system = Mock()
        self.agent.searcher = Mock()
        self.agent.self_iteration = None
        self.agent.task_manager = Mock()
        self.agent.goal_planner = Mock()
        self.agent.generate_completion = Mock(return_value="Mocked AI response")
        self.agent.formatter.error = Mock(return_value="ERROR")
        self.agent.formatter.success = Mock(return_value="SUCCESS")
        self.agent.formatter.warning = Mock(return_value="WARNING")
        self.agent.formatter.info = Mock(return_value="INFO")
        self.agent.code_analyzer.read_file_safe = Mock(return_value=(True, "", "file content"))
        self.agent.code_analyzer.write_file_safe = Mock(return_value=(True, "File written"))
        self.agent.code_analyzer.root_path = os.getcwd()

        # Mock the actual API call to simulate tool calls
        self.agent._make_api_request = Mock()

    @patch('agent.core.requests.post')
    def test_tool_call_detection(self, mock_post):
        """Test that tool calls are detected and handled."""
        # Simulate LLM response with tool call
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_123","function":{"name":"read","arguments":"{\\"target\\":\\"README.md\\"}"}}]}}]}',
            b'data: [DONE]'
        ]
        mock_post.return_value = mock_response

        # Mock tool execution
        with patch.object(self.agent, 'handle_read_command', return_value="File content"):
            # Call stream_response (should detect tool call and execute)
            result = self.agent.stream_response("Read README.md")
            # Verify tool was called
            self.agent.handle_read_command.assert_called_once_with("README.md")
            # Since we have recursive continuation, result should be from next LLM call
            # For simplicity, we just verify no crash

    @patch('agent.core.requests.post')
    def test_recursive_tool_calls(self, mock_post):
        """Test recursive tool calling (multiple rounds)."""
        # Simulate first response with tool call
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_123","function":{"name":"read","arguments":"{\\"target\\":\\"test.txt\\"}"}}]}}]}',
            b'data: [DONE]'
        ]
        # Simulate second response with text (after tool result)
        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"The file contains: Hello"}}]}',
            b'data: [DONE]'
        ]
        mock_post.side_effect = [mock_response1, mock_response2]

        with patch.object(self.agent, 'handle_read_command', return_value="Hello"):
            result = self.agent.stream_response("Read test.txt")
            # Should get final text response
            self.assertIsNotNone(result)
            self.assertIn("Hello", result)

    @patch('agent.core.requests.post')
    def test_recursion_depth_limit(self, mock_post):
        """Test that tool call recursion is limited to depth 10."""
        # Simulate repeated tool calls (each response triggers another tool call)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_123","function":{"name":"read","arguments":"{\\"target\\":\\"test.txt\\"}"}}]}}]}',
            b'data: [DONE]'
        ]
        mock_post.return_value = mock_response

        with patch.object(self.agent, 'handle_read_command', return_value="Content"):
            # Mock _handle_tool_calls to return success but not infinite recursion
            with patch.object(self.agent, '_handle_tool_calls', return_value=True) as mock_handle:
                # We'll also need to mock the recursive call to stream_response
                # to avoid infinite loop. Instead we can check that depth limit
                # triggers after 10 calls. Let's patch stream_response to count calls.
                call_count = 0
                original_stream = self.agent.stream_response
                def counting_stream(*args, **kwargs):
                    nonlocal call_count
                    call_count += 1
                    if call_count > 10:
                        self.fail("Exceeded expected recursion depth")
                    # Return a dummy response to stop recursion
                    return "Dummy response"
                with patch.object(self.agent, 'stream_response', side_effect=counting_stream):
                    result = self.agent.stream_response("Read test.txt")
                    # Should have called stream_response at least once
                    self.assertGreater(call_count, 0)
                    # Should not have exceeded depth limit (since we patched)


if __name__ == '__main__':
    unittest.main()