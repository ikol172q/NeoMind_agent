"""
Formalized tool definition framework for neomind agent.

Provides typed tool schemas with parameter validation, permission levels,
and auto-generated system prompt sections. This replaces the prompt-only
approach with structured, validated tool calls.

Architecture:
    ToolParam      → Defines a single parameter (name, type, required, default)
    ToolDefinition → Complete tool definition (name, params, permission, execute fn)
    PermissionLevel → Risk categories (READ_ONLY, WRITE, EXECUTE, DESTRUCTIVE)
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Tuple


class PermissionLevel(Enum):
    """Tool permission categories — controls when user confirmation is needed.

    READ_ONLY:   Never asks permission (file reads, searches, listings)
    WRITE:       Asks in 'normal' mode (file writes, edits)
    EXECUTE:     Asks in 'normal' mode (shell commands)
    DESTRUCTIVE: Asks even in 'auto_accept' mode (rm -rf, git reset --hard)
    """
    READ_ONLY = "read_only"
    WRITE = "write"
    EXECUTE = "execute"
    DESTRUCTIVE = "destructive"


class ParamType(Enum):
    """Supported parameter types for tool validation."""
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"


class ToolParam:
    """A single tool parameter definition with type and constraint info.

    Args:
        name: Parameter name (must match the execute function's kwarg)
        param_type: Expected type (STRING, INTEGER, BOOLEAN, FLOAT)
        description: Human-readable description for the system prompt
        required: Whether the parameter must be provided
        default: Default value when not provided (only for optional params)
        enum: List of allowed values (constraint)
    """

    def __init__(
        self,
        name: str,
        param_type: ParamType,
        description: str,
        required: bool = True,
        default: Any = None,
        enum: Optional[List[str]] = None,
    ):
        self.name = name
        self.param_type = param_type
        self.description = description
        self.required = required
        self.default = default
        self.enum = enum

    def __repr__(self) -> str:
        req = "required" if self.required else f"optional={self.default}"
        return f"ToolParam({self.name}: {self.param_type.value}, {req})"


class ToolDefinition:
    """Complete definition of a tool with schema, validation, and execution.

    Each tool in the registry is a ToolDefinition that binds:
    - A name and description (for system prompt generation)
    - Typed parameters with validation rules
    - A permission level (for the permission manager)
    - An execute function (the actual implementation)
    - Usage examples (for few-shot learning in the prompt)

    Args:
        name: Tool name as the LLM will reference it (e.g. "Read", "Bash")
        description: One-line description for the system prompt
        parameters: List of ToolParam definitions
        permission_level: Risk category for permission checks
        execute: Callable that implements the tool. Must accept **kwargs matching params.
        examples: List of example tool calls for the system prompt
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: List[ToolParam],
        permission_level: PermissionLevel,
        execute: Callable,
        examples: Optional[List[Dict[str, Any]]] = None,
        deferred: bool = False,
        always_load: bool = True,
        is_open_world: bool = False,
        interrupt_behavior: str = 'cancel',
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.permission_level = permission_level
        self.execute = execute
        self.examples = examples or []
        self.deferred = deferred            # If True, not in initial prompt — use ToolSearch
        self.always_load = always_load      # If True, always in system prompt
        self.is_open_world_flag = is_open_world  # Fetches external/untrusted data
        self.interrupt_behavior_mode = interrupt_behavior  # 'cancel' or 'block'

        # Build lookup for fast param access
        self._param_map: Dict[str, ToolParam] = {p.name: p for p in parameters}

    def is_read_only(self, params: Optional[Dict[str, Any]] = None) -> bool:
        """Check if this tool (with given params) is a read-only operation.

        Used by permission system and coordinator to decide tool restrictions.
        """
        return self.permission_level == PermissionLevel.READ_ONLY

    def is_destructive(self, params: Optional[Dict[str, Any]] = None) -> bool:
        """Check if this tool (with given params) is a destructive operation.

        Checks both static permission level and dynamic parameter patterns.
        """
        if self.permission_level == PermissionLevel.DESTRUCTIVE:
            return True
        # Dynamic check for Bash/PowerShell with dangerous commands
        if self.name in ('Bash', 'PowerShell') and params:
            command = params.get('command', '')
            destructive_patterns = [
                'rm -rf', 'rm -fr', 'git reset --hard', 'git push --force',
                'DROP TABLE', 'DROP DATABASE', 'TRUNCATE', 'dd if=', 'mkfs',
            ]
            cmd_lower = command.lower()
            return any(p.lower() in cmd_lower for p in destructive_patterns)
        return False

    def is_concurrency_safe(self) -> bool:
        """Check if this tool is safe to run concurrently with other tools."""
        if self.permission_level == PermissionLevel.READ_ONLY:
            return True
        if self.name in ('TaskCreate', 'TaskGet', 'TaskList', 'TaskUpdate'):
            return True
        return False

    def requires_user_interaction(self) -> bool:
        """Check if this tool requires direct user interaction (e.g., AskUser).

        Tools with this flag should defer loading and never auto-approve.
        """
        return self.name in ('AskUser', 'AskUserQuestion')

    def is_open_world(self, params: Optional[Dict[str, Any]] = None) -> bool:
        """Check if this tool fetches external/untrusted data.

        Open-world tools may expose the system to prompt injection from
        external content. Used for injection warnings in context.
        """
        return self.is_open_world_flag

    def get_interrupt_behavior(self) -> str:
        """Return interrupt behavior: 'cancel' or 'block'.

        - cancel: Ctrl+C kills the tool immediately (default)
        - block: Ctrl+C queues until tool finishes (for writes in progress)
        """
        return self.interrupt_behavior_mode

    def get_activity_description(self, params: Dict[str, Any] = None) -> str:
        """Return a human-readable description of what this tool is currently doing.

        Shown in the CLI spinner during execution.
        """
        if not params:
            return self.name
        # Tool-specific descriptions
        if self.name == 'Read':
            return f"Reading {params.get('path', '?')}"
        elif self.name == 'Write':
            return f"Writing {params.get('path', '?')}"
        elif self.name == 'Edit':
            return f"Editing {params.get('path', '?')}"
        elif self.name in ('Bash', 'PowerShell'):
            cmd = params.get('command', '?')[:40]
            return f"Running {cmd}"
        elif self.name == 'Grep':
            return f"Searching for '{params.get('pattern', '?')}'"
        elif self.name == 'Glob':
            return f"Finding files matching {params.get('pattern', '?')}"
        elif self.name == 'WebFetch':
            return f"Fetching {params.get('url', '?')[:40]}"
        elif self.name == 'WebSearch':
            return f"Searching web for '{params.get('query', '?')}'"
        return self.name

    def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate parameters against the tool's schema.

        Checks:
        - All required parameters are present
        - No unknown parameters
        - Type correctness (string, int, bool, float)
        - Enum constraints

        Args:
            params: Dict of parameter name → value from the parsed tool call

        Returns:
            (True, "") on success, (False, error_message) on failure
        """
        # Silently strip unknown parameters instead of erroring.
        # LLMs sometimes hallucinate extra params (e.g. "reason") —
        # rejecting them wastes a round-trip. Just ignore them.
        known_names = {p.name for p in self.parameters}
        unknown_keys = [k for k in params if k not in known_names]
        for k in unknown_keys:
            del params[k]

        # Check required parameters and validate types
        for p in self.parameters:
            if p.name not in params:
                if p.required:
                    return False, f"Missing required parameter: '{p.name}'"
                continue  # Optional and not provided — fine

            val = params[p.name]

            # Type checking
            type_checks = {
                ParamType.STRING: (str, "string"),
                ParamType.INTEGER: (int, "integer"),
                ParamType.BOOLEAN: (bool, "boolean"),
                ParamType.FLOAT: ((int, float), "number"),  # int is valid as float
            }

            if p.param_type in type_checks:
                expected_type, type_name = type_checks[p.param_type]
                # Special case: bool is subclass of int in Python, exclude it for INTEGER
                if p.param_type == ParamType.INTEGER and isinstance(val, bool):
                    return False, (
                        f"Parameter '{p.name}' must be {type_name}, "
                        f"got {type(val).__name__}"
                    )
                if not isinstance(val, expected_type):
                    return False, (
                        f"Parameter '{p.name}' must be {type_name}, "
                        f"got {type(val).__name__}"
                    )

            # Enum constraint
            if p.enum is not None and val not in p.enum:
                return False, (
                    f"Parameter '{p.name}' must be one of {p.enum}, "
                    f"got '{val}'"
                )

        return True, ""

    def apply_defaults(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fill in default values for optional parameters not provided.

        Returns a new dict with defaults applied (does not modify input).
        """
        result = dict(params)
        for p in self.parameters:
            if p.name not in result and not p.required and p.default is not None:
                result[p.name] = p.default
        return result

    def to_prompt_schema(self) -> str:
        """Generate the schema description for injection into the system prompt.

        Format:
            **ToolName**: Description
              Parameters:
                - param1 (type, required): description
                - param2 (type, optional, default=X): description [values: a, b, c]
        """
        lines = [f"**{self.name}**: {self.description}"]
        if self.parameters:
            lines.append("  Parameters:")
            for p in self.parameters:
                if p.required:
                    req_str = "required"
                else:
                    req_str = f"optional, default={p.default}"
                line = f"    - {p.name} ({p.param_type.value}, {req_str}): {p.description}"
                if p.enum:
                    line += f" [values: {', '.join(str(v) for v in p.enum)}]"
                lines.append(line)
        else:
            lines.append("  Parameters: none")

        # Add examples if present
        if self.examples:
            lines.append("  Examples:")
            for ex in self.examples:
                import json
                lines.append(f'    {json.dumps({"tool": self.name, "params": ex})}')

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"ToolDefinition({self.name}, "
            f"params={len(self.parameters)}, "
            f"permission={self.permission_level.value})"
        )


def generate_tool_prompt(tools: List[ToolDefinition]) -> str:
    """Generate the complete TOOL SYSTEM section for the system prompt.

    This is auto-generated from registered tool definitions — single source of truth.
    When a new tool is added, it automatically appears in the prompt.

    Args:
        tools: List of all registered ToolDefinition objects

    Returns:
        Complete system prompt section including format instructions,
        tool schemas, rules, and examples
    """
    tool_schemas = "\n\n".join(t.to_prompt_schema() for t in tools)

    return f"""TOOL SYSTEM:
You have access to these tools. To use a tool, output EXACTLY ONE tool call
in this format, then STOP and wait for results:

<tool_call>
{{"tool": "ToolName", "params": {{"param1": "value1", "param2": 42}}}}
</tool_call>

After the tool call, STOP. The system will execute it and return:

<tool_result>
tool: ToolName
status: OK | ERROR
output: |
  (actual output here)
</tool_result>

Then you will be re-prompted to continue based on the real results.

AVAILABLE TOOLS:

{tool_schemas}

RULES:
- Output ONE tool call per response, then STOP
- Do NOT guess or hallucinate tool output — wait for real results
- Read a file before editing it
- Break complex tasks into steps — one tool call per step
- For shell commands, use the Bash tool (persistent session: cd/export carry across calls)
- Prefer Read/Edit/Write tools over bash cat/sed for file operations (structured output)
- Prefer Grep/Glob over bash grep/find (faster, structured output)
- When the user asks you to do something, DO IT immediately with a tool call. Do NOT ask for confirmation or list options — just execute.
- 用户让你做事就直接做，不要问"你想要 1. 覆盖 2. 创建新的 3. ..."——直接执行最合理的操作"""
