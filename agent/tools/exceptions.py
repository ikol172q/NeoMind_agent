"""
Exceptions for the tool system.
"""


class ToolError(Exception):
    """Base exception for all tool-related errors."""
    pass


class ToolValidationError(ToolError):
    """Raised when tool input validation fails."""
    pass


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""
    pass


class ToolNotFoundError(ToolError):
    """Raised when a tool is not found in the registry."""
    pass


class ToolRegistryError(ToolError):
    """Raised when there's an issue with the tool registry."""
    pass


class ToolRateLimitError(ToolError):
    """Raised when a tool is rate limited."""
    pass


class ToolAuthError(ToolError):
    """Raised when tool requires authentication that's not provided."""
    pass