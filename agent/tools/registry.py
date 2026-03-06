"""
Tool registry for managing and executing tools.

Provides central registry for all tools with JSON Schema validation,
execution tracking, and safety integration.
"""

import json
import inspect
from typing import Dict, List, Any, Optional, Callable, Type, Union
import threading
import time

from .base import Tool, AsyncTool, CommandTool, ToolMetadata, ToolError, ToolValidationError, ToolExecutionError
from .exceptions import ToolNotFoundError, ToolRegistryError

# Import safety functions
from ..safety import safe_read_file, safe_write_file, safe_delete_file, is_path_safe, log_operation


class ToolRegistry:
    """Central registry for tools."""

    def __init__(self, safety_manager=None):
        """
        Initialize tool registry.

        Args:
            safety_manager: Optional SafetyManager instance for tool safety.
        """
        self.tools: Dict[str, Tool] = {}
        self.tool_metadata: Dict[str, ToolMetadata] = {}
        self.execution_history: List[Dict[str, Any]] = []
        self.safety_manager = safety_manager
        self._lock = threading.RLock()
        self._tool_categories: Dict[str, List[str]] = {}

    def register(self, tool: Union[Tool, Type[Tool]], name: Optional[str] = None) -> None:
        """
        Register a tool or tool class.

        Args:
            tool: Tool instance or Tool class to register.
            name: Optional custom name for the tool. Defaults to tool.metadata.name.

        Raises:
            ToolRegistryError: If tool registration fails.
        """
        with self._lock:
            try:
                # If it's a class, instantiate it
                if inspect.isclass(tool) and issubclass(tool, Tool):
                    tool_instance = tool()
                else:
                    tool_instance = tool

                if not isinstance(tool_instance, Tool):
                    raise ToolRegistryError(f"Object {tool} is not a Tool instance")

                tool_name = name or tool_instance.metadata.name

                if tool_name in self.tools:
                    raise ToolRegistryError(f"Tool '{tool_name}' already registered")

                self.tools[tool_name] = tool_instance
                self.tool_metadata[tool_name] = tool_instance.metadata

                # Update category index
                for category in tool_instance.metadata.categories:
                    if category not in self._tool_categories:
                        self._tool_categories[category] = []
                    self._tool_categories[category].append(tool_name)

                self._log_operation("register", tool_name, True, {
                    "categories": tool_instance.metadata.categories,
                    "dangerous": tool_instance.metadata.dangerous,
                })

            except Exception as e:
                self._log_operation("register", str(tool), False, {"error": str(e)})
                raise ToolRegistryError(f"Failed to register tool: {e}") from e

    def unregister(self, name: str) -> bool:
        """
        Unregister a tool.

        Args:
            name: Name of tool to unregister.

        Returns:
            True if tool was unregistered, False if not found.
        """
        with self._lock:
            if name not in self.tools:
                return False

            tool = self.tools[name]
            # Remove from categories
            for category in tool.metadata.categories:
                if category in self._tool_categories and name in self._tool_categories[category]:
                    self._tool_categories[category].remove(name)
                    if not self._tool_categories[category]:
                        del self._tool_categories[category]

            del self.tools[name]
            del self.tool_metadata[name]

            self._log_operation("unregister", name, True)
            return True

    def get_tool(self, name: str) -> Tool:
        """
        Get a tool by name.

        Args:
            name: Name of tool to retrieve.

        Returns:
            Tool instance.

        Raises:
            ToolNotFoundError: If tool not found.
        """
        with self._lock:
            if name not in self.tools:
                raise ToolNotFoundError(f"Tool '{name}' not found")
            return self.tools[name]

    def get_tool_metadata(self, name: str) -> ToolMetadata:
        """
        Get metadata for a tool.

        Args:
            name: Name of tool.

        Returns:
            ToolMetadata instance.

        Raises:
            ToolNotFoundError: If tool not found.
        """
        with self._lock:
            if name not in self.tool_metadata:
                raise ToolNotFoundError(f"Tool '{name}' not found")
            return self.tool_metadata[name]

    def list_tools(self, category: Optional[str] = None) -> List[str]:
        """
        List all registered tool names, optionally filtered by category.

        Args:
            category: Optional category filter.

        Returns:
            List of tool names.
        """
        with self._lock:
            if category:
                return self._tool_categories.get(category, [])
            return list(self.tools.keys())

    def list_tools_with_metadata(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all tools with their metadata.

        Args:
            category: Optional category filter.

        Returns:
            List of dicts with name and metadata.
        """
        with self._lock:
            tools = []
            for name, metadata in self.tool_metadata.items():
                if category and category not in metadata.categories:
                    continue
                tools.append({
                    "name": name,
                    "metadata": metadata,
                })
            return tools

    def to_openai_format(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Convert registered tools to OpenAI-compatible format.

        Args:
            category: Optional category filter.

        Returns:
            List of tool definitions in OpenAI format.
        """
        with self._lock:
            tools = []
            for name, tool in self.tools.items():
                if category and category not in tool.metadata.categories:
                    continue
                tools.append(tool.to_openai_format())
            return tools

    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        validate: bool = True,
        safety_check: bool = True
    ) -> Any:
        """
        Execute a tool with given arguments.

        Args:
            tool_name: Name of tool to execute.
            arguments: Dictionary of arguments for the tool.
            validate: Whether to validate arguments against schema.
            safety_check: Whether to perform safety checks (if tool is dangerous).

        Returns:
            Tool execution result.

        Raises:
            ToolNotFoundError: If tool not found.
            ToolValidationError: If arguments don't match schema.
            ToolExecutionError: If execution fails.
        """
        with self._lock:
            start_time = time.time()

            try:
                # Get tool
                tool = self.get_tool(tool_name)

                # Safety check for dangerous tools
                if safety_check and tool.metadata.dangerous:
                    if not self._safety_check(tool_name, arguments):
                        raise ToolExecutionError(f"Safety check failed for dangerous tool: {tool_name}")

                # Validate input
                if validate:
                    tool.validate_input(**arguments)

                # Execute tool
                self._log_operation("execute_start", tool_name, True, {
                    "arguments": arguments,
                })

                if isinstance(tool, AsyncTool):
                    import asyncio
                    result = asyncio.run(tool.execute_async(**arguments))
                else:
                    result = tool.execute(**arguments)

                execution_time = time.time() - start_time

                # Log successful execution
                self.execution_history.append({
                    "timestamp": start_time,
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "execution_time": execution_time,
                    "success": True,
                })

                self._log_operation("execute_complete", tool_name, True, {
                    "execution_time": execution_time,
                    "result_type": type(result).__name__,
                })

                return result

            except (ToolValidationError, ToolExecutionError) as e:
                # Re-raise these as-is
                execution_time = time.time() - start_time
                self.execution_history.append({
                    "timestamp": start_time,
                    "tool": tool_name,
                    "arguments": arguments,
                    "error": str(e),
                    "execution_time": execution_time,
                    "success": False,
                })
                self._log_operation("execute_failed", tool_name, False, {
                    "error": str(e),
                    "execution_time": execution_time,
                })
                raise

            except Exception as e:
                # Wrap unexpected errors
                execution_time = time.time() - start_time
                error_msg = f"Unexpected error executing tool {tool_name}: {e}"
                self.execution_history.append({
                    "timestamp": start_time,
                    "tool": tool_name,
                    "arguments": arguments,
                    "error": error_msg,
                    "execution_time": execution_time,
                    "success": False,
                })
                self._log_operation("execute_failed", tool_name, False, {
                    "error": error_msg,
                    "execution_time": execution_time,
                })
                raise ToolExecutionError(error_msg) from e

    def _safety_check(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """
        Perform safety check for dangerous tools.

        Args:
            tool_name: Name of tool.
            arguments: Tool arguments.

        Returns:
            True if safe, False otherwise.
        """
        if not self.safety_manager:
            # No safety manager - log warning but allow
            self._log_operation("safety_check_skipped", tool_name, True, {
                "reason": "no_safety_manager",
            })
            return True

        # TODO: Implement specific safety checks based on tool type
        # For now, just log
        self._log_operation("safety_check", tool_name, True, {
            "arguments": arguments,
        })
        return True

    def _log_operation(self, action: str, tool_name: str, success: bool, details: Optional[Dict] = None):
        """
        Log tool operation to audit log.

        Args:
            action: Operation being performed.
            tool_name: Name of tool.
            success: Whether operation succeeded.
            details: Optional additional details.
        """
        try:
            log_operation(
                f"tool_{action}",
                tool_name,
                success,
                json.dumps(details) if details else ""
            )
        except:
            pass  # Silently fail on logging errors

    def clear_history(self) -> None:
        """Clear execution history."""
        with self._lock:
            self.execution_history = []

    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get execution history.

        Args:
            limit: Optional limit on number of entries.

        Returns:
            List of execution history entries.
        """
        with self._lock:
            history = self.execution_history.copy()
            if limit:
                history = history[-limit:]
            return history

    def get_tool_stats(self) -> Dict[str, Any]:
        """
        Get statistics about tool usage.

        Returns:
            Dictionary with tool statistics.
        """
        with self._lock:
            stats = {
                "total_tools": len(self.tools),
                "total_executions": len(self.execution_history),
                "successful_executions": sum(1 for e in self.execution_history if e.get("success", False)),
                "failed_executions": sum(1 for e in self.execution_history if not e.get("success", True)),
                "tools_by_category": {cat: len(tools) for cat, tools in self._tool_categories.items()},
            }

            # Execution time stats
            if self.execution_history:
                execution_times = [e.get("execution_time", 0) for e in self.execution_history]
                stats["avg_execution_time"] = sum(execution_times) / len(execution_times)
                stats["max_execution_time"] = max(execution_times)
                stats["min_execution_time"] = min(execution_times)

            return stats


# Global registry instance
_default_registry: Optional[ToolRegistry] = None


def get_default_registry() -> ToolRegistry:
    """Get or create the default global tool registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
    return _default_registry


def register_tool(tool: Union[Tool, Type[Tool]], name: Optional[str] = None) -> None:
    """Register a tool with the default registry."""
    get_default_registry().register(tool, name)


def execute_tool(tool_name: str, arguments: Dict[str, Any], **kwargs) -> Any:
    """Execute a tool using the default registry."""
    return get_default_registry().execute(tool_name, arguments, **kwargs)