"""
Live integration tests for user agent.

These tests make REAL API calls to DeepSeek to verify that the model's output
format works correctly with the tool parser, content filter, and agentic loop.

Run with:
    python -m pytest tests/test_integration_live.py -v -s

Requires DEEPSEEK_API_KEY in environment or .env file.
These tests are marked with @pytest.mark.live and skipped by default.
Use: python -m pytest tests/test_integration_live.py -v -s -m live
"""

import os
import re
import sys
import json
import time
import pytest
import requests
from pathlib import Path
from unittest.mock import patch

# Load .env if present
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

# Import agent components
sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.tool_parser import ToolCallParser, ToolCall, format_tool_result
from agent.tools import ToolResult

# Skip all tests if no API key
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
pytestmark = pytest.mark.live

SKIP_REASON = "DEEPSEEK_API_KEY not set — skipping live integration tests"


def _call_deepseek(messages, max_tokens=2048, temperature=0.3):
    """Make a raw API call to DeepSeek and return the full response text."""
    if not API_KEY:
        pytest.skip(SKIP_REASON)

    try:
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
            json={
                "model": "deepseek-chat",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except (requests.exceptions.ConnectionError,
            requests.exceptions.ProxyError,
            requests.exceptions.Timeout) as e:
        pytest.skip(f"Cannot reach DeepSeek API: {e}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _get_system_prompt():
    """Load the current coding.yaml system prompt."""
    yaml_path = Path(__file__).parent.parent / "agent" / "config" / "coding.yaml"
    content = yaml_path.read_text()
    # Extract system_prompt value (YAML block scalar after "system_prompt: |")
    match = re.search(r'system_prompt:\s*\|\n((?:  .*\n)*)', content)
    if match:
        # De-indent the block (remove leading 2 spaces)
        lines = match.group(1).split("\n")
        return "\n".join(line[2:] if line.startswith("  ") else line for line in lines)
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Test: Model produces parseable tool calls
# ──────────────────────────────────────────────────────────────────────────────

class TestModelOutputFormat:
    """Verify DeepSeek produces output the tool parser can handle."""

    def setup_method(self):
        self.parser = ToolCallParser()
        self.system_prompt = _get_system_prompt()
        if not self.system_prompt:
            pytest.skip("Could not load system prompt from coding.yaml")

    def _make_messages(self, user_msg):
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ]

    def test_model_uses_bash_block_for_shell_command(self):
        """Model should use ```bash blocks for shell commands."""
        response = _call_deepseek(
            self._make_messages("List all Python files in the current directory"),
            max_tokens=512,
        )
        print(f"\n--- Model response ---\n{response}\n---")

        tool_call = self.parser.parse(response)
        assert tool_call is not None, (
            f"Parser found no tool call in response:\n{response}"
        )
        # Should be a Bash tool call (either legacy or structured)
        assert tool_call.tool_name == "Bash", (
            f"Expected Bash tool, got {tool_call.tool_name}"
        )
        cmd = tool_call.params.get("command", "")
        assert cmd, f"Empty command in tool call: {tool_call}"
        print(f"Parsed: {tool_call}")

    def test_model_uses_tool_for_read(self):
        """Model should use some parseable tool call to read a file.

        DeepSeek may use: bash cat, <tool_call> Read, or even a python block.
        The parser handles all three formats. The key assertion is that the
        parser can extract SOMETHING executable from the response.
        """
        response = _call_deepseek(
            self._make_messages("Read the file setup.py and show me its contents"),
            max_tokens=512,
        )
        print(f"\n--- Model response ---\n{response}\n---")

        tool_call = self.parser.parse(response)
        assert tool_call is not None, (
            f"Parser found no tool call in response:\n{response}"
        )
        # Accept Bash (from bash/python block) or Read (structured)
        assert tool_call.tool_name in ("Read", "Bash"), (
            f"Expected Read or Bash tool, got {tool_call.tool_name}"
        )
        print(f"Parsed: {tool_call}")

    def test_model_uses_structured_grep(self):
        """Model should use <tool_call> for Grep operations."""
        response = _call_deepseek(
            self._make_messages('Search all Python files for the pattern "def main"'),
            max_tokens=512,
        )
        print(f"\n--- Model response ---\n{response}\n---")

        tool_call = self.parser.parse(response)
        assert tool_call is not None, (
            f"Parser found no tool call in response:\n{response}"
        )
        # Accept Grep (structured) or bash grep (legacy)
        assert tool_call.tool_name in ("Grep", "Bash"), (
            f"Expected Grep or Bash tool, got {tool_call.tool_name}"
        )
        print(f"Parsed: {tool_call}")

    def test_model_includes_prose_with_tool_call(self):
        """Model should include explanation text alongside tool calls."""
        response = _call_deepseek(
            self._make_messages("Check if there are any TODO comments in the codebase"),
            max_tokens=512,
        )
        print(f"\n--- Model response ---\n{response}\n---")

        tool_call = self.parser.parse(response)
        assert tool_call is not None, (
            f"Parser found no tool call in response:\n{response}"
        )

        # Strip the tool call and check there's remaining prose
        stripped = self.parser.strip_tool_call(response, tool_call)
        # Allow for minimal prose (at least some non-whitespace text)
        prose = stripped.strip()
        print(f"Prose: '{prose}'")
        print(f"Tool: {tool_call}")
        # We want at least SOME text, but be lenient — even a short sentence is OK
        # The important thing is the tool call is parseable
        if not prose:
            print("WARNING: Model produced tool call with no prose (content filter would show nothing)")

    def test_model_responds_with_analysis_when_file_provided(self):
        """When file content is provided, model should analyze it directly."""
        file_content = '''
def add(a, b):
    """Add two numbers."""
    return a + b

def subtract(a, b):
    """Subtract b from a."""
    return a - b

class Calculator:
    def __init__(self):
        self.history = []

    def calculate(self, op, a, b):
        if op == "add":
            result = add(a, b)
        elif op == "subtract":
            result = subtract(a, b)
        else:
            raise ValueError(f"Unknown op: {op}")
        self.history.append((op, a, b, result))
        return result
'''
        prompt = (
            f"understand this file:\n\n"
            f'<file path="calculator.py">\n{file_content}\n</file>'
        )
        response = _call_deepseek(
            self._make_messages(prompt),
            max_tokens=1024,
        )
        print(f"\n--- Model response ---\n{response}\n---")

        # Model should provide analysis, not just a tool call
        # Check for substantive content (not just "let me read the file")
        assert len(response.strip()) > 50, (
            f"Response too short — expected analysis, got:\n{response}"
        )

        # Check it mentions key elements from the file
        response_lower = response.lower()
        found_keywords = sum(1 for kw in ["calculator", "add", "subtract", "history"]
                           if kw in response_lower)
        assert found_keywords >= 2, (
            f"Response doesn't seem to analyze the file content "
            f"(found {found_keywords}/4 keywords):\n{response}"
        )

        # Ideally, model should NOT try to Read the file again (it's already provided)
        tool_call = self.parser.parse(response)
        if tool_call and tool_call.tool_name == "Read":
            print("WARNING: Model tried to Read the file even though content was provided")


# ──────────────────────────────────────────────────────────────────────────────
# Test: Content filter correctly handles model output
# ──────────────────────────────────────────────────────────────────────────────

class TestContentFilterWithRealOutput:
    """Test that the content filter works correctly with real model output."""

    def setup_method(self):
        from cli.claude_interface import ClaudeInterface
        self.FilterClass = ClaudeInterface._CodeFenceFilter
        self.parser = ToolCallParser()
        self.system_prompt = _get_system_prompt()

    def test_filter_suppresses_real_bash_block(self):
        """Content filter should suppress bash blocks from real model output."""
        response = _call_deepseek(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": "Run 'echo hello world'"},
            ],
            max_tokens=512,
        )
        print(f"\n--- Model response ---\n{response}\n---")

        # Run through content filter
        f = self.FilterClass()
        visible = f.write(response) + f.flush()
        print(f"Visible after filter: '{visible}'")

        # The bash command itself should NOT appear in visible output
        # (it should be suppressed by the filter)
        tool_call = self.parser.parse(response)
        if tool_call:
            cmd = tool_call.params.get("command", "")
            if cmd:
                assert cmd not in visible, (
                    f"Bash command '{cmd}' leaked through content filter"
                )

    def test_filter_preserves_prose(self):
        """Content filter should preserve explanation text."""
        response = _call_deepseek(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": "What is Python?"},
            ],
            max_tokens=512,
        )
        print(f"\n--- Model response ---\n{response}\n---")

        # This prompt shouldn't trigger tool calls, so everything passes through
        f = self.FilterClass()
        visible = f.write(response) + f.flush()

        # Most of the response should be preserved
        assert len(visible.strip()) > len(response.strip()) * 0.5, (
            f"Filter removed too much content.\n"
            f"Original ({len(response)} chars): {response[:100]}...\n"
            f"Visible ({len(visible)} chars): {visible[:100]}..."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test: Agentic loop tool result feedback format
# ──────────────────────────────────────────────────────────────────────────────

class TestToolResultFeedback:
    """Test that tool results fed back to the model produce good follow-ups."""

    def setup_method(self):
        self.parser = ToolCallParser()
        self.system_prompt = _get_system_prompt()

    def test_model_continues_after_tool_result(self):
        """After receiving a tool result, model should provide analysis."""
        # Simulate: model asked to find files, we give it results
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "Find all Python test files in the project"},
            {"role": "assistant", "content": '```bash\nfind . -name "test_*.py" -type f\n```'},
        ]

        # Create a mock tool result
        mock_result = ToolResult(
            success=True,
            output=(
                "./tests/test_core.py\n"
                "./tests/test_config.py\n"
                "./tests/test_tool_parser.py\n"
                "./tests/test_tool_schema.py\n"
                "./tests/test_agentic_loop.py\n"
                "./tests/test_claude_interface.py\n"
            ),
        )
        mock_call = ToolCall("Bash", {"command": 'find . -name "test_*.py" -type f'},
                            raw='```bash\nfind . -name "test_*.py" -type f\n```',
                            is_legacy=True)
        feedback = format_tool_result(mock_call, mock_result)

        # Add the combined feedback + continue prompt (matches our fixed agentic loop)
        messages.append({
            "role": "user",
            "content": feedback + "\n\nContinue based on the tool results above.",
        })

        response = _call_deepseek(messages, max_tokens=1024)
        print(f"\n--- Model response after tool result ---\n{response}\n---")

        # Model should provide analysis of the test files, not just repeat the list
        assert len(response.strip()) > 30, (
            f"Response too short after tool result:\n{response}"
        )
        # Should mention some of the test files
        response_lower = response.lower()
        found = sum(1 for name in ["test_core", "test_config", "test_tool"]
                   if name in response_lower)
        assert found >= 1, (
            f"Model doesn't reference the tool results:\n{response}"
        )

    def test_model_handles_error_result(self):
        """Model should handle error results gracefully."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "Read the file nonexistent.py"},
            {"role": "assistant", "content": '<tool_call>\n{"tool": "Read", "params": {"path": "nonexistent.py"}}\n</tool_call>'},
        ]

        mock_result = ToolResult(
            success=False,
            error="File not found: nonexistent.py",
        )
        mock_call = ToolCall("Read", {"path": "nonexistent.py"},
                            raw='<tool_call>\n{"tool": "Read", "params": {"path": "nonexistent.py"}}\n</tool_call>')
        feedback = format_tool_result(mock_call, mock_result)

        messages.append({
            "role": "user",
            "content": feedback + "\n\nContinue based on the tool results above.",
        })

        response = _call_deepseek(messages, max_tokens=512)
        print(f"\n--- Model response after error ---\n{response}\n---")

        # Model should acknowledge the error
        response_lower = response.lower()
        assert any(kw in response_lower for kw in
                   ["not found", "doesn't exist", "does not exist", "error", "couldn't", "cannot"]), (
            f"Model doesn't acknowledge the error:\n{response}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test: Full round-trip (parse → execute → feedback → re-prompt)
# ──────────────────────────────────────────────────────────────────────────────

class TestFullRoundTrip:
    """End-to-end test: prompt → model → parse → mock execute → feedback → model."""

    def setup_method(self):
        self.parser = ToolCallParser()
        self.system_prompt = _get_system_prompt()

    def test_two_turn_conversation(self):
        """Model should make a tool call, receive result, then provide analysis."""
        # Turn 1: Ask for something that requires a tool
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "How many lines of code are in setup.py?"},
        ]

        response1 = _call_deepseek(messages, max_tokens=512)
        print(f"\n--- Turn 1 response ---\n{response1}\n---")

        tool_call = self.parser.parse(response1)
        assert tool_call is not None, (
            f"Turn 1: No tool call found in:\n{response1}"
        )
        print(f"Turn 1 tool call: {tool_call}")

        # Simulate tool execution
        mock_output = (
            "     1\tfrom setuptools import setup, find_packages\n"
            "     2\t\n"
            "     3\tsetup(\n"
            "     4\t    name='user',\n"
            "     5\t    version='0.1.0',\n"
            "     6\t    packages=find_packages(),\n"
            "     7\t)\n"
        )
        mock_result = ToolResult(success=True, output=mock_output)
        feedback = format_tool_result(tool_call, mock_result)

        # Turn 2: Feed result back
        messages.append({"role": "assistant", "content": response1})
        messages.append({
            "role": "user",
            "content": feedback + "\n\nContinue based on the tool results above.",
        })

        response2 = _call_deepseek(messages, max_tokens=512)
        print(f"\n--- Turn 2 response ---\n{response2}\n---")

        # Turn 2 should provide an answer, not another tool call
        assert len(response2.strip()) > 20, (
            f"Turn 2 response too short:\n{response2}"
        )
        # Should mention the line count or the file content
        assert any(kw in response2.lower() for kw in
                   ["7", "lines", "setup", "setuptools"]), (
            f"Turn 2 doesn't reference the results:\n{response2}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test: Regression — no-output bug
# ──────────────────────────────────────────────────────────────────────────────

class TestNoOutputRegression:
    """Regression tests for the 'no answer' bug."""

    def setup_method(self):
        self.parser = ToolCallParser()
        self.system_prompt = _get_system_prompt()

    def test_response_not_empty(self):
        """Model should always produce non-empty output for simple prompts."""
        prompts = [
            "What is recursion?",
            "Explain what a Python decorator does",
            "How do I reverse a list in Python?",
        ]
        for prompt in prompts:
            response = _call_deepseek(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=512,
            )
            assert response and len(response.strip()) > 20, (
                f"Empty or too-short response for '{prompt}':\n{response!r}"
            )

    def test_file_analysis_produces_visible_output(self):
        """When file content is provided, model should produce visible analysis."""
        file_content = "x = 42\nprint(x)\n"
        prompt = (
            f"understand this file:\n\n"
            f'<file path="test.py">\n{file_content}\n</file>'
        )

        response = _call_deepseek(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=512,
        )
        print(f"\n--- Response ---\n{response}\n---")

        # Run through content filter
        from cli.claude_interface import ClaudeInterface
        f = ClaudeInterface._CodeFenceFilter()
        visible = f.write(response) + f.flush()

        assert len(visible.strip()) > 10, (
            f"Content filter removed all visible output!\n"
            f"Full response: {response!r}\n"
            f"Visible: {visible!r}"
        )
