"""
Base classes for tools in ikol1729_agent.

Defines abstract Tool, AsyncTool, and CommandTool classes that all tools must implement.
Tools follow OpenAI-compatible JSON Schema for parameter definitions.
"""

import abc
import json
from typing import Any, Dict, List, Optional, Type, Callable
from dataclasses import dataclass, field
import inspect
import functools


@dataclass
class ToolMetadata:
    """Metadata for a tool."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    returns: Dict[str, Any]  # JSON Schema for return value
    version: str = "1.0.0"
    categories: List[str] = field(default_factory=list)
    requires_auth: bool = False
    dangerous: bool = False
    rate_limited: bool = False


class ToolError(Exception):
    """Base exception for tool errors."""
    pass


class ToolValidationError(ToolError):
    """Raised when tool input validation fails."""
    pass


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""
    pass


class Tool(abc.ABC):
    """Abstract base class for all tools."""

    def __init__(self, metadata: Optional[ToolMetadata] = None):
        self.metadata = metadata or self._default_metadata()
        self._validate_metadata()

    @classmethod
    @abc.abstractmethod
    def _default_metadata(cls) -> ToolMetadata:
        """Return default metadata for this tool."""
        pass

    def _validate_metadata(self) -> None:
        """Validate that metadata has required fields."""
        required = ["name", "description", "parameters", "returns"]
        for field in required:
            if not getattr(self.metadata, field, None):
                raise ToolValidationError(
                    f"Tool metadata missing required field: {field}"
                )

        # Validate JSON Schema structure
        if not isinstance(self.metadata.parameters, dict):
            raise ToolValidationError("parameters must be a dict")
        if not isinstance(self.metadata.returns, dict):
            raise ToolValidationError("returns must be a dict")

    @abc.abstractmethod
    def execute(self, **kwargs) -> Any:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters validated against schema.

        Returns:
            Tool execution result.

        Raises:
            ToolValidationError: If parameters don't match schema.
            ToolExecutionError: If execution fails.
        """
        pass

    def __call__(self, **kwargs) -> Any:
        """Make tool callable."""
        return self.execute(**kwargs)

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert tool to OpenAI-compatible format."""
        return {
            "type": "function",
            "function": {
                "name": self.metadata.name,
                "description": self.metadata.description,
                "parameters": self.metadata.parameters,
            }
        }

    def validate_input(self, **kwargs) -> bool:
        """
        Validate input parameters against schema.

        This is a basic validation. Subclasses can override for more complex validation.
        """
        # Basic type checking - can be enhanced with jsonschema library
        if not self.metadata.parameters.get("properties"):
            return True

        properties = self.metadata.parameters["properties"]
        required = self.metadata.parameters.get("required", [])

        # Check required parameters
        for param in required:
            if param not in kwargs:
                raise ToolValidationError(f"Missing required parameter: {param}")

        # Check parameter types (basic)
        for param, value in kwargs.items():
            if param not in properties:
                raise ToolValidationError(f"Unknown parameter: {param}")

            param_schema = properties[param]
            param_type = param_schema.get("type")

            if param_type == "string":
                if not isinstance(value, str):
                    raise ToolValidationError(f"Parameter {param} must be string")
            elif param_type == "integer":
                if not isinstance(value, int):
                    raise ToolValidationError(f"Parameter {param} must be integer")
            elif param_type == "number":
                if not isinstance(value, (int, float)):
                    raise ToolValidationError(f"Parameter {param} must be number")
            elif param_type == "boolean":
                if not isinstance(value, bool):
                    raise ToolValidationError(f"Parameter {param} must be boolean")
            elif param_type == "array":
                if not isinstance(value, list):
                    raise ToolValidationError(f"Parameter {param} must be array")
            elif param_type == "object":
                if not isinstance(value, dict):
                    raise ToolValidationError(f"Parameter {param} must be object")

        return True


class AsyncTool(Tool):
    """Abstract base class for async tools."""

    @abc.abstractmethod
    async def execute_async(self, **kwargs) -> Any:
        """Async version of execute."""
        pass

    async def __call__(self, **kwargs) -> Any:
        """Make async tool callable."""
        return await self.execute_async(**kwargs)

    def execute(self, **kwargs) -> Any:
        """Sync wrapper for async execution (blocks)."""
        import asyncio
        return asyncio.run(self.execute_async(**kwargs))


class CommandTool(Tool):
    """
    Tool that wraps an existing command handler function.

    This allows gradual migration from command handlers to tools.
    """

    @classmethod
    def _default_metadata(cls) -> ToolMetadata:
        """Return default metadata for command tools."""
        # This should be overridden by subclasses or metadata passed to constructor
        return ToolMetadata(
            name="command_tool",
            description="A tool that wraps a command handler",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            returns={"type": "string"},
        )

    def __init__(
        self,
        handler: Callable[[str], str],
        metadata: ToolMetadata,
        argument_parser: Optional[Callable[[Dict[str, Any]], str]] = None
    ):
        """
        Args:
            handler: Original command handler function that takes a string argument.
            metadata: Tool metadata.
            argument_parser: Function to convert tool parameters to command string.
                If None, a default parser is used.
        """
        super().__init__(metadata)
        self.handler = handler
        self.argument_parser = argument_parser or self._default_argument_parser

    @staticmethod
    def _default_argument_parser(params: Dict[str, Any]) -> str:
        """Default parser: join all parameters with spaces."""
        parts = []
        for key, value in params.items():
            if isinstance(value, bool):
                if value:
                    parts.append(f"--{key}")
            elif isinstance(value, list):
                for item in value:
                    parts.append(str(item))
            else:
                parts.append(str(value))
        return " ".join(parts)

    def execute(self, **kwargs) -> Any:
        """Execute by converting parameters to command string and calling handler."""
        self.validate_input(**kwargs)
        command_str = self.argument_parser(kwargs)
        return self.handler(command_str)


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    returns: Optional[Dict[str, Any]] = None,
    categories: Optional[List[str]] = None,
    requires_auth: bool = False,
    dangerous: bool = False,
    rate_limited: bool = False,
):
    """
    Decorator to convert a function into a Tool.

    Example:
        @tool(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
            returns={"type": "string"},
        )
        def read_file(path: str) -> str:
            ...
    """
    def decorator(func):
        # Infer metadata from function signature if not provided
        tool_name = name or func.__name__
        tool_description = description or func.__doc__ or f"Tool: {tool_name}"

        # Default parameters schema from function signature
        if parameters is None:
            sig = inspect.signature(func)
            properties = {}
            required = []

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue

                param_type = str(param.annotation) if param.annotation != inspect.Parameter.empty else "string"
                param_default = param.default if param.default != inspect.Parameter.empty else None

                properties[param_name] = {
                    "type": param_type,
                    "description": f"Parameter: {param_name}",
                }

                if param_default is None:
                    required.append(param_name)

            tool_parameters = {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        else:
            tool_parameters = parameters

        # Default returns schema
        tool_returns = returns or {"type": "string"}

        metadata = ToolMetadata(
            name=tool_name,
            description=tool_description,
            parameters=tool_parameters,
            returns=tool_returns,
            categories=categories or [],
            requires_auth=requires_auth,
            dangerous=dangerous,
            rate_limited=rate_limited,
        )

        # Create wrapper class
        class DecoratedTool(Tool):
            def _default_metadata(cls):
                return metadata

            def execute(self, **kwargs):
                return func(**kwargs)

        # Set class name
        DecoratedTool.__name__ = f"{tool_name.title()}Tool"
        DecoratedTool.__doc__ = tool_description

        return DecoratedTool()

    return decorator