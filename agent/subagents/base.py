"""
Base classes for subagents in user_agent.

Subagents are specialized agents that handle specific types of tasks
delegated by the main agent via the Task tool.
"""

import abc
import json
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
import uuid
import time


@dataclass
class SubagentMetadata:
    """Metadata for a subagent."""
    name: str
    description: str
    capabilities: List[str]
    input_schema: Dict[str, Any]  # JSON Schema for expected input
    output_schema: Dict[str, Any]  # JSON Schema for expected output
    version: str = "1.0.0"
    categories: List[str] = field(default_factory=list)
    max_execution_time: int = 300  # seconds
    requires_isolation: bool = False


class SubagentError(Exception):
    """Base exception for subagent errors."""
    pass


class SubagentTimeoutError(SubagentError):
    """Raised when subagent execution times out."""
    pass


class SubagentValidationError(SubagentError):
    """Raised when subagent input validation fails."""
    pass


class Subagent(abc.ABC):
    """Abstract base class for all subagents."""

    def __init__(self, metadata: Optional[SubagentMetadata] = None):
        self.metadata = metadata or self._default_metadata()
        self.execution_id = str(uuid.uuid4())[:8]
        self._validate_metadata()

    @classmethod
    @abc.abstractmethod
    def _default_metadata(cls) -> SubagentMetadata:
        """Return default metadata for this subagent."""
        pass

    def _validate_metadata(self) -> None:
        """Validate that metadata has required fields."""
        required = ["name", "description", "capabilities", "input_schema", "output_schema"]
        for field_name in required:
            if not getattr(self.metadata, field_name, None):
                raise SubagentValidationError(
                    f"Subagent metadata missing required field: {field_name}"
                )

    @abc.abstractmethod
    def execute(self, task_description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the subagent with given task and parameters.

        Args:
            task_description: Description of the task to perform.
            parameters: Parameters validated against input_schema.

        Returns:
            Execution result matching output_schema.

        Raises:
            SubagentValidationError: If parameters don't match schema.
            SubagentError: If execution fails.
        """
        pass

    def validate_input(self, parameters: Dict[str, Any]) -> bool:
        """
        Validate input parameters against schema.

        Args:
            parameters: Parameters to validate.

        Returns:
            True if valid.

        Raises:
            SubagentValidationError: If validation fails.
        """
        schema = self.metadata.input_schema
        if not schema.get("properties"):
            return True

        properties = schema["properties"]
        required = schema.get("required", [])

        # Check required parameters
        for param in required:
            if param not in parameters:
                raise SubagentValidationError(f"Missing required parameter: {param}")

        # Basic type checking
        for param, value in parameters.items():
            if param not in properties:
                raise SubagentValidationError(f"Unknown parameter: {param}")

            param_schema = properties[param]
            param_type = param_schema.get("type")

            if param_type == "string":
                if not isinstance(value, str):
                    raise SubagentValidationError(f"Parameter {param} must be string")
            elif param_type == "integer":
                if not isinstance(value, int):
                    raise SubagentValidationError(f"Parameter {param} must be integer")
            elif param_type == "number":
                if not isinstance(value, (int, float)):
                    raise SubagentValidationError(f"Parameter {param} must be number")
            elif param_type == "boolean":
                if not isinstance(value, bool):
                    raise SubagentValidationError(f"Parameter {param} must be boolean")
            elif param_type == "array":
                if not isinstance(value, list):
                    raise SubagentValidationError(f"Parameter {param} must be array")
            elif param_type == "object":
                if not isinstance(value, dict):
                    raise SubagentValidationError(f"Parameter {param} must be object")

        return True

    def execute_with_timeout(self, task_description: str,
                            parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute subagent with timeout protection.

        Args:
            task_description: Description of the task.
            parameters: Parameters for the subagent.

        Returns:
            Execution result.

        Raises:
            SubagentTimeoutError: If execution times out.
        """
        try:
            return asyncio.run(self._execute_with_timeout_async(
                task_description, parameters
            ))
        except asyncio.TimeoutError:
            raise SubagentTimeoutError(
                f"Subagent {self.metadata.name} timed out after "
                f"{self.metadata.max_execution_time} seconds"
            )

    async def _execute_with_timeout_async(self, task_description: str,
                                         parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Async wrapper for execution with timeout."""
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self.execute(task_description, parameters)
            ),
            timeout=self.metadata.max_execution_time
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert subagent to dictionary representation."""
        return {
            "name": self.metadata.name,
            "description": self.metadata.description,
            "capabilities": self.metadata.capabilities,
            "categories": self.metadata.categories,
            "execution_id": self.execution_id,
            "metadata": {
                "input_schema": self.metadata.input_schema,
                "output_schema": self.metadata.output_schema,
                "max_execution_time": self.metadata.max_execution_time,
                "requires_isolation": self.metadata.requires_isolation,
            }
        }


class AsyncSubagent(Subagent):
    """Abstract base class for async subagents."""

    @abc.abstractmethod
    async def execute_async(self, task_description: str,
                           parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Async version of execute."""
        pass

    def execute(self, task_description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Sync wrapper for async execution."""
        return asyncio.run(self.execute_async(task_description, parameters))