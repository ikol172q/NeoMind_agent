"""
Structured tool call parser for ikol1729 agent.

Parses tool calls from LLM responses in two formats:
1. Structured: <tool_call>{"tool": "Read", "params": {...}}</tool_call>
2. Legacy: ```bash ... ``` code blocks (mapped to Bash tool)

The structured format is preferred — it enables schema validation before
execution. The legacy format is kept for backward compatibility and as
a fallback when the model doesn't follow instructions perfectly.
"""

import re
import json
from typing import Optional


class ToolCall:
    """A parsed tool call extracted from LLM output.

    Attributes:
        tool_name: Name of the tool to invoke (e.g. "Read", "Bash")
        params: Dict of parameter name → value
        raw: Original text matched (for stripping from display)
        is_legacy: True if parsed from bash code block (not structured format)
    """

    def __init__(self, tool_name: str, params: dict, raw: str,
                 is_legacy: bool = False):
        self.tool_name = tool_name
        self.params = params
        self.raw = raw
        self.is_legacy = is_legacy

    def __repr__(self) -> str:
        fmt = "legacy" if self.is_legacy else "structured"
        return f"ToolCall({self.tool_name}, params={self.params}, format={fmt})"

    def preview(self, max_len: int = 60) -> str:
        """Short preview string for spinner/permission display."""
        if self.tool_name == "Bash":
            cmd = self.params.get("command", "")
            first_line = cmd.split("\n")[0]
            return first_line[:max_len]
        else:
            # For structured tools, show tool(key_param)
            key_param = list(self.params.values())[0] if self.params else ""
            if isinstance(key_param, str) and len(key_param) > max_len:
                key_param = key_param[:max_len - 3] + "..."
            return f"{self.tool_name}({key_param})"


class ToolCallParser:
    """Parse tool calls from LLM responses.

    Supports three formats with priority:
    1. Structured: <tool_call>{"tool": "Read", "params": {...}}</tool_call>
    2. Bash blocks: ```bash ... ``` code blocks → mapped to Bash(command=...)
    3. Python blocks: ```python ... ``` → wrapped as Bash(python3 -c '...')

    Only extracts the FIRST tool call from a response.
    The LLM is instructed to output one tool call per response.
    """

    # Structured format: <tool_call>{JSON}</tool_call>
    _STRUCTURED_RE = re.compile(
        r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
        re.DOTALL,
    )

    # Legacy bash code blocks
    _LEGACY_BASH_RE = re.compile(
        r'```(?:bash|shell|sh|console)\s*\n(.*?)```',
        re.DOTALL,
    )

    # Python code blocks (fallback — DeepSeek sometimes writes Python instead of bash)
    _PYTHON_RE = re.compile(
        r'```python\s*\n(.*?)```',
        re.DOTALL,
    )

    def parse(self, response: str) -> Optional[ToolCall]:
        """Parse the FIRST tool call from an LLM response.

        Tries structured format first, then bash blocks, then python blocks.
        Returns None if no tool call found.

        Args:
            response: Full LLM response text

        Returns:
            ToolCall if found, None otherwise
        """
        # Try structured format first (highest priority)
        m = self._STRUCTURED_RE.search(response)
        if m:
            result = self._parse_structured(m)
            if result:
                return result

        # Try bash blocks (iterate to skip hallucinated ones)
        for m in self._LEGACY_BASH_RE.finditer(response):
            result = self._parse_legacy_bash(m, response)
            if result:
                return result

        # Last resort: python blocks (DeepSeek fallback)
        for m in self._PYTHON_RE.finditer(response):
            result = self._parse_python_block(m, response)
            if result:
                return result

        return None

    def _parse_structured(self, match: re.Match) -> Optional[ToolCall]:
        """Parse a <tool_call> JSON block.

        Expected format:
            {"tool": "ToolName", "params": {"key": "value"}}

        Handles:
        - Missing "params" key (defaults to {})
        - Invalid JSON (returns None)
        - Missing "tool" key (returns None)
        """
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        tool_name = data.get("tool", "")
        if not tool_name or not isinstance(tool_name, str):
            return None

        params = data.get("params", {})
        if not isinstance(params, dict):
            return None

        return ToolCall(
            tool_name=tool_name,
            params=params,
            raw=match.group(0),
            is_legacy=False,
        )

    def _parse_legacy_bash(self, match: re.Match,
                           full_response: str) -> Optional[ToolCall]:
        """Parse a ```bash code block as a Bash tool call.

        Filters out:
        - Empty blocks
        - Comment-only blocks
        - Blocks followed by hallucinated output (another ``` block)
        """
        code = match.group(1).strip()
        if not code:
            return None

        # Skip comment-only blocks
        executable_lines = [
            line for line in code.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        if not executable_lines:
            return None

        # Check for hallucinated inline output: if the text after this code block
        # starts with another ``` block (no language tag), the LLM hallucinated results
        end_pos = match.end()
        after = full_response[end_pos:end_pos + 200].strip()
        if after.startswith("```\n") or after.startswith("```\r"):
            return None

        return ToolCall(
            tool_name="Bash",
            params={"command": code},
            raw=match.group(0),
            is_legacy=True,
        )

    def _parse_python_block(self, match: re.Match,
                            full_response: str) -> Optional[ToolCall]:
        """Parse a ```python code block as a Bash tool call (wrapped in python3 -c).

        This is a last-resort fallback for when the model outputs Python code
        instead of using bash commands. We wrap the Python code in a python3
        invocation so it can still be executed.

        Filters out:
        - Empty blocks
        - Blocks that look like examples/documentation (contain "# Example:" etc.)
        - Blocks followed by hallucinated output
        """
        code = match.group(1).strip()
        if not code:
            return None

        # Skip blocks that look like documentation examples
        first_line = code.split("\n")[0].strip().lower()
        if first_line.startswith("# example") or first_line.startswith("# usage"):
            return None

        # Skip comment-only blocks
        executable_lines = [
            line for line in code.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        if not executable_lines:
            return None

        # Check for hallucinated inline output
        end_pos = match.end()
        after = full_response[end_pos:end_pos + 200].strip()
        if after.startswith("```\n") or after.startswith("```\r"):
            return None

        # Wrap in python3 -c with proper escaping
        # Use heredoc style to avoid quote escaping issues
        command = f"python3 << 'PYEOF'\n{code}\nPYEOF"

        return ToolCall(
            tool_name="Bash",
            params={"command": command},
            raw=match.group(0),
            is_legacy=True,
        )

    def strip_tool_call(self, response: str, tool_call: ToolCall) -> str:
        """Remove the tool call from the response text.

        Useful for display — shows the LLM's prose without the tool invocation.
        """
        return response.replace(tool_call.raw, "").strip()


def format_tool_result(tool_call: ToolCall, result) -> str:
    """Format a tool execution result as structured feedback for the LLM.

    Produces a <tool_result> block that the LLM can parse:

        <tool_result>
        tool: Read
        status: OK
        output: |
          (actual output here, indented)
        </tool_result>

    Args:
        tool_call: The tool call that was executed
        result: ToolResult from execution

    Returns:
        Formatted string to add to conversation history as a "user" message
    """
    status = "OK" if result.success else "ERROR"

    # Build output section
    output_text = result.output[:3000] if result.output else "(no output)"
    if result.error and not result.success:
        output_text = f"STDERR: {result.error}\n{output_text}"

    # Indent output for YAML-like block scalar
    indented = "\n".join(f"  {line}" for line in output_text.split("\n"))

    parts = [
        "<tool_result>",
        f"tool: {tool_call.tool_name}",
        f"status: {status}",
        f"output: |",
        indented,
    ]

    # Include metadata if present
    if hasattr(result, "metadata") and result.metadata:
        parts.append(f"metadata: {json.dumps(result.metadata)}")

    parts.append("</tool_result>")

    return "\n".join(parts)
