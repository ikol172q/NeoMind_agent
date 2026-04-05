"""
Structured tool call parser for neomind agent.

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

    # Structured format: <tool_call>{"tool": "X", "params": {...}}</tool_call>
    # Tolerates mismatched closing tags like </tool_result> (LLM hallucination)
    _STRUCTURED_RE = re.compile(
        r'<tool_call>\s*(\{.*?\})\s*</tool_(?:call|result)>',
        re.DOTALL,
    )

    # Fallback: <tool_call>JSON without closing tag (LLM forgot to close)
    # Allows one level of nested braces for {"params": {"key": "val"}}
    _UNCLOSED_RE = re.compile(
        r'<tool_call>\s*(\{(?:[^{}]|\{[^{}]*\})*\})',
        re.DOTALL,
    )

    # XML-wrapped format (LLMs like DeepSeek often output this instead):
    #   <tool_call>
    #   <ToolName>
    #   {"param1": "value1"}
    #   </ToolName>
    #   </tool_call>
    # Tolerates mismatched closing tags like </tool_result>
    _XML_WRAPPED_RE = re.compile(
        r'<tool_call>\s*<(\w+)>\s*(\{.*?\})\s*</\1>\s*</tool_(?:call|result)>',
        re.DOTALL,
    )

    # Legacy bash code blocks
    _LEGACY_BASH_RE = re.compile(
        r'```(?:bash|shell|sh|console)\s*\n(.*?)```',
        re.DOTALL,
    )

    # Python code blocks (fallback — LLM sometimes writes Python instead of bash)
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

        # Try unclosed <tool_call> — LLM sometimes forgets closing tag
        if '<tool_call>' in response:
            m = self._UNCLOSED_RE.search(response)
            if m:
                result = self._parse_structured(m)
                if result:
                    return result

        # Try XML-wrapped format: <tool_call><ToolName>{params}</ToolName></tool_call>
        # Common with DeepSeek and other models that prefer XML nesting
        m = self._XML_WRAPPED_RE.search(response)
        if m:
            result = self._parse_xml_wrapped(m)
            if result:
                return result

        # Try bash blocks (iterate to skip hallucinated ones)
        for m in self._LEGACY_BASH_RE.finditer(response):
            result = self._parse_legacy_bash(m, response)
            if result:
                return result

        # Last resort: python blocks (LLM fallback)
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

    def _parse_xml_wrapped(self, match: re.Match) -> Optional[ToolCall]:
        """Parse XML-wrapped format: <tool_call><ToolName>{params}</ToolName></tool_call>.

        Some LLMs (notably DeepSeek) output tool calls as:
            <tool_call>
            <Read>
            {"path": "/some/file.py"}
            </Read>
            </tool_call>

        Instead of the expected JSON format. This method handles that.
        """
        tool_name = match.group(1)  # captured by (\w+)
        try:
            params = json.loads(match.group(2))
        except json.JSONDecodeError:
            return None

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


def format_tool_display(tool_name: str, result, elapsed_ms: int = 0) -> str:
    """Format a tool result for CLI display (human-readable, per-tool formatting).

    Unlike format_tool_result (which is for LLM context), this is for the user's
    terminal. Each tool type gets distinct formatting.

    Args:
        tool_name: Name of the tool
        result: ToolResult from execution
        elapsed_ms: Execution time in milliseconds

    Returns:
        Formatted string for terminal display
    """
    status = "✓" if result.success else "✗"
    time_str = f" ({elapsed_ms}ms)" if elapsed_ms > 0 else ""
    meta = getattr(result, 'metadata', {}) or {}

    if tool_name in ('Bash', 'PowerShell'):
        cmd = meta.get('command', '')[:60]
        exit_code = meta.get('exit_code', 0)
        code_badge = f"exit={exit_code}" if not result.success else ""
        return f"{status} {tool_name}{time_str} $ {cmd} {code_badge}".strip()

    elif tool_name == 'Read':
        path = meta.get('file_path', '?')
        lines = meta.get('lines_in_output', '?')
        dedup = " (cached)" if meta.get('deduplicated') else ""
        return f"{status} Read{time_str} {path} ({lines} lines){dedup}"

    elif tool_name == 'Write':
        path = meta.get('file_path', '?')
        bytes_w = meta.get('bytes_written', '?')
        return f"{status} Write{time_str} {path} ({bytes_w} bytes)"

    elif tool_name == 'Edit':
        path = meta.get('file_path', '?')
        return f"{status} Edit{time_str} {path}"

    elif tool_name == 'Grep':
        pattern = meta.get('pattern', '?')
        return f"{status} Grep{time_str} '{pattern}'"

    elif tool_name == 'Glob':
        pattern = meta.get('pattern', '?')
        count = meta.get('files_matched', '?')
        return f"{status} Glob{time_str} {pattern} → {count} files"

    elif tool_name in ('WebSearch', 'WebFetch'):
        query = meta.get('query', meta.get('url', '?'))[:50]
        return f"{status} {tool_name}{time_str} {query}"

    elif tool_name == 'SyntheticOutput':
        schema = meta.get('schema_name', '?')
        return f"{status} SyntheticOutput{time_str} schema={schema}"

    elif tool_name == 'Snip':
        label = meta.get('label', '?')
        return f"{status} Snip{time_str} '{label}'"

    else:
        return f"{status} {tool_name}{time_str}"
