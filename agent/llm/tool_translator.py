"""
Tool Schema Translator — LLM-agnostic tool calling abstraction.

Provides:
1. Unified OpenAI-compatible tool format
2. Selective tool injection (max 8 per request)
3. Fallback for models without function calling support

NeoMind uses OpenAI format as the canonical representation.
When targeting models with different formats, this module translates.
"""

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_TOOLS_PER_REQUEST = 8


class ToolSchemaTranslator:
    """Translates between tool schema formats and selects relevant tools.

    The NeoMind tool registry stores schemas in OpenAI format:
    {
        "type": "function",
        "function": {
            "name": "tool_name",
            "description": "...",
            "parameters": {...}
        }
    }
    """

    def __init__(self, tools: Optional[list[dict]] = None):
        self._all_tools = tools or []
        # Core tools always included
        self._core_tool_names = set()
        # Mode-specific tool names
        self._mode_tools: dict[str, set[str]] = {
            "chat": set(),
            "coding": set(),
            "fin": set(),
        }

    def register_tool(self, schema: dict, core: bool = False,
                      modes: Optional[list[str]] = None) -> None:
        """Register a tool schema."""
        self._all_tools.append(schema)
        name = schema.get("function", {}).get("name", "")
        if core:
            self._core_tool_names.add(name)
        if modes:
            for mode in modes:
                if mode in self._mode_tools:
                    self._mode_tools[mode].add(name)

    def get_active_tools(self, mode: str, query: str = "",
                          max_tools: int = MAX_TOOLS_PER_REQUEST) -> list[dict]:
        """Select the most relevant tools for the current request.

        Strategy:
        1. Always include core tools
        2. Add mode-specific tools
        3. Add query-relevant tools (keyword matching)
        4. Deduplicate and cap at max_tools
        """
        selected = []
        seen_names = set()

        # 1. Core tools
        for tool in self._all_tools:
            name = tool.get("function", {}).get("name", "")
            if name in self._core_tool_names and name not in seen_names:
                selected.append(tool)
                seen_names.add(name)

        # 2. Mode-specific tools
        mode_names = self._mode_tools.get(mode, set())
        for tool in self._all_tools:
            name = tool.get("function", {}).get("name", "")
            if name in mode_names and name not in seen_names:
                selected.append(tool)
                seen_names.add(name)

        # 3. Query-relevant tools
        if query:
            query_lower = query.lower()
            for tool in self._all_tools:
                func = tool.get("function", {})
                name = func.get("name", "")
                if name in seen_names:
                    continue
                desc = func.get("description", "").lower()
                if any(word in desc for word in query_lower.split()[:5]):
                    selected.append(tool)
                    seen_names.add(name)

        return selected[:max_tools]

    def to_openai_format(self, tools: list[dict]) -> list[dict]:
        """Ensure tools are in OpenAI format (canonical)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.get("function", {}).get("name", t.get("name", "")),
                    "description": t.get("function", {}).get(
                        "description", t.get("description", "")
                    ),
                    "parameters": t.get("function", {}).get(
                        "parameters", t.get("parameters", {})
                    ),
                },
            }
            for t in tools
        ]

    def get_tool_count(self) -> int:
        return len(self._all_tools)


class ToolCallFallback:
    """Simulate tool calling for models without native function calling support.

    Injects a structured prompt that asks the model to respond with JSON
    tool calls, then parses the response.

    Usage:
        fallback = ToolCallFallback(tools)
        augmented_prompt = fallback.augment_prompt(original_prompt)
        # ... send to LLM ...
        tool_call = fallback.parse_response(llm_output)
    """

    FALLBACK_PROMPT_TEMPLATE = """You have access to tools. To use a tool, respond ONLY with JSON:

```json
{{"tool": "tool_name", "params": {{"key": "value"}}}}
```

Available tools:
{tool_descriptions}

IMPORTANT:
- Always use tools when you need real data. Never guess.
- If no tool is needed, respond normally without JSON.
- Only one tool call per response.
"""

    def __init__(self, tools: list[dict]):
        self.tools = tools

    def augment_prompt(self, prompt: str) -> str:
        """Add tool calling instructions to the prompt."""
        descriptions = []
        for tool in self.tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {})
            param_names = list(params.get("properties", {}).keys())
            descriptions.append(
                f"- **{name}**: {desc}\n"
                f"  Parameters: {', '.join(param_names) if param_names else 'none'}"
            )

        tool_text = "\n".join(descriptions)
        instruction = self.FALLBACK_PROMPT_TEMPLATE.format(
            tool_descriptions=tool_text
        )

        return instruction + "\n\n" + prompt

    def parse_response(self, response: str) -> Optional[dict]:
        """Try to extract a tool call from the model's response.

        Returns: {"tool": "name", "params": {...}} or None
        """
        # Try to find JSON block in response
        json_match = re.search(
            r'```(?:json)?\s*\n({.*?})\s*\n```',
            response, re.DOTALL
        )

        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if "tool" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # Try raw JSON at start of response
        try:
            stripped = response.strip()
            if stripped.startswith("{"):
                data = json.loads(stripped)
                if "tool" in data:
                    return data
        except json.JSONDecodeError:
            pass

        return None
