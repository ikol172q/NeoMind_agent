"""
Task tool for delegating work to specialized subagents.

This tool routes tasks to appropriate subagents (Explore, Plan, Bash)
based on the task type and parameters.
"""

import json
import re
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

from .base import Tool, ToolMetadata
from ..subagents import ExploreAgent, PlanAgent, BashAgent


class TaskType(Enum):
    """Types of tasks that can be delegated."""
    EXPLORE = "explore"
    PLAN = "plan"
    BASH = "bash"
    UNKNOWN = "unknown"


class TaskTool(Tool):
    """Tool for delegating tasks to subagents."""

    @classmethod
    def _default_metadata(cls) -> ToolMetadata:
        return ToolMetadata(
            name="task",
            description="Delegate tasks to specialized subagents (explore, plan, bash) based on task type.",
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Description of the task to delegate"
                    },
                    "type": {
                        "type": "string",
                        "description": "Type of subagent to use",
                        "enum": ["explore", "plan", "bash", "auto"],
                        "default": "auto"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Parameters for the subagent",
                        "additionalProperties": True
                    }
                },
                "required": ["description"]
            },
            returns={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "subagent": {"type": "string"},
                    "result": {"type": "object"},
                    "summary": {"type": "string"},
                    "execution_time": {"type": "number"}
                },
                "required": ["success", "subagent"]
            },
            categories=["delegation", "subagents"],
            dangerous=False
        )

    def __init__(self, agent_instance=None):
        """
        Initialize task tool.

        Args:
            agent_instance: Reference to main agent for context.
        """
        super().__init__()
        self.agent = agent_instance
        self.subagents = self._initialize_subagents()

    def _initialize_subagents(self) -> Dict[str, Any]:
        """Initialize subagents."""
        subagents = {
            "explore": ExploreAgent(),
            "plan": PlanAgent(),
            "bash": BashAgent()
        }

        # Configure bash agent with safety manager if available
        if self.agent and hasattr(self.agent, 'safety_manager'):
            subagents["bash"].set_safety_manager(self.agent.safety_manager)

        return subagents

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Delegate task to appropriate subagent.

        Args:
            description: Description of the task.
            type: Type of subagent to use (or "auto" for automatic detection).
            parameters: Parameters for the subagent.

        Returns:
            Delegation results.
        """
        import time
        start_time = time.time()

        try:
            self.validate_input(**kwargs)

            description = kwargs.get("description", "")
            task_type = kwargs.get("type", "auto")
            parameters = kwargs.get("parameters", {})

            # Determine task type if auto
            if task_type == "auto":
                task_type = self._detect_task_type(description, parameters)
            else:
                # Validate task type
                try:
                    TaskType(task_type)
                except ValueError:
                    return {
                        "success": False,
                        "subagent": "unknown",
                        "error": f"Invalid task type: {task_type}. Use: explore, plan, bash, or auto.",
                        "execution_time": time.time() - start_time
                    }

            # Get appropriate subagent
            subagent = self.subagents.get(task_type)
            if not subagent:
                return {
                    "success": False,
                    "subagent": task_type,
                    "error": f"No subagent available for type: {task_type}",
                    "execution_time": time.time() - start_time
                }

            # Merge description into parameters if needed
            subagent_params = parameters.copy()
            if "goal" not in subagent_params and task_type == "plan":
                subagent_params["goal"] = description
            if "query" not in subagent_params and task_type == "explore":
                subagent_params["query"] = description

            # Execute subagent
            result = subagent.execute(description, subagent_params)
            execution_time = time.time() - start_time

            # Format result
            formatted_result = self._format_result(task_type, result, execution_time)

            return formatted_result

        except Exception as e:
            return {
                "success": False,
                "subagent": "unknown",
                "error": str(e),
                "execution_time": time.time() - start_time
            }

    def _detect_task_type(self, description: str, parameters: Dict[str, Any]) -> str:
        """
        Detect appropriate task type from description and parameters.

        Args:
            description: Task description.
            parameters: Task parameters.

        Returns:
            Detected task type.
        """
        description_lower = description.lower()
        params_str = json.dumps(parameters).lower()

        # Check for exploration keywords
        explore_keywords = [
            "explore", "search", "find", "look for", "analyze", "scan",
            "directory", "file", "codebase", "structure", "dependencies",
            "what files", "list files", "show files", "browse"
        ]
        if any(keyword in description_lower for keyword in explore_keywords):
            return TaskType.EXPLORE.value

        # Check for planning keywords
        plan_keywords = [
            "plan", "strategy", "roadmap", "schedule", "timeline",
            "break down", "decompose", "steps", "tasks", "milestones",
            "how to", "approach", "methodology", "design", "architecture"
        ]
        if any(keyword in description_lower for keyword in plan_keywords):
            return TaskType.PLAN.value

        # Check for bash/system keywords
        bash_keywords = [
            "run", "execute", "command", "shell", "terminal", "bash",
            "install", "update", "upgrade", "check", "status", "system",
            "process", "disk", "memory", "cpu", "network", "ping",
            "copy", "move", "delete", "create", "make", "build",
            "compile", "test", "deploy", "start", "stop", "restart"
        ]
        if any(keyword in description_lower for keyword in bash_keywords):
            return TaskType.BASH.value

        # Check parameters for clues
        if "command" in parameters or "operation" in parameters:
            if "command" in parameters:
                cmd = str(parameters["command"]).lower()
                if any(cmd.startswith(x) for x in ["ls", "find", "grep", "cat", "echo"]):
                    return TaskType.BASH.value
            if parameters.get("operation") in ["search", "analyze", "structure"]:
                return TaskType.EXPLORE.value

        # Default to explore for general investigation
        return TaskType.EXPLORE.value

    def _format_result(self, task_type: str, result: Dict[str, Any],
                      execution_time: float) -> Dict[str, Any]:
        """
        Format subagent result for return.

        Args:
            task_type: Type of subagent used.
            result: Subagent execution result.
            execution_time: Total execution time.

        Returns:
            Formatted result.
        """
        formatted = {
            "success": result.get("success", False),
            "subagent": task_type,
            "result": result,
            "execution_time": execution_time
        }

        # Add summary based on task type
        if task_type == TaskType.EXPLORE.value:
            formatted["summary"] = self._format_explore_summary(result)
        elif task_type == TaskType.PLAN.value:
            formatted["summary"] = self._format_plan_summary(result)
        elif task_type == TaskType.BASH.value:
            formatted["summary"] = self._format_bash_summary(result)
        else:
            formatted["summary"] = "Task execution completed."

        return formatted

    def _format_explore_summary(self, result: Dict[str, Any]) -> str:
        """Format exploration result summary."""
        if not result.get("success"):
            return "❌ Exploration failed."

        summary = "🔍 **Exploration Results**\n\n"

        if "summary" in result:
            summary += result["summary"] + "\n\n"

        # Add key findings
        if "analysis" in result:
            analysis = result["analysis"]
            if "total_files" in analysis:
                summary += f"• Total files: {analysis['total_files']}\n"
            if "total_size" in analysis:
                mb = analysis['total_size'] / (1024 * 1024)
                summary += f"• Total size: {mb:.1f} MB\n"

        if "results" in result and result["results"]:
            count = len(result["results"])
            summary += f"• Found {count} matching items\n"

        return summary.strip()

    def _format_plan_summary(self, result: Dict[str, Any]) -> str:
        """Format planning result summary."""
        if not result.get("success"):
            return "❌ Planning failed."

        summary = "📋 **Planning Results**\n\n"

        if "summary" in result:
            summary += result["summary"] + "\n"
        elif "plan" in result:
            plan = result["plan"]
            if "goal" in plan:
                summary += f"**Goal:** {plan['goal'][:100]}...\n"
            if "estimated_effort" in plan:
                summary += f"**Estimated Effort:** {plan['estimated_effort']}\n"
            if "steps" in plan:
                summary += f"**Steps:** {len(plan['steps'])} key steps\n"
            if "risks" in plan:
                summary += f"**Risks Identified:** {len(plan['risks'])}\n"

        return summary.strip()

    def _format_bash_summary(self, result: Dict[str, Any]) -> str:
        """Format bash execution summary."""
        if not result.get("success"):
            error_msg = result.get("stderr", result.get("error", "Unknown error"))
            return f"❌ Command failed: {error_msg[:200]}..."

        summary = "✅ **Command Execution Successful**\n\n"

        exit_code = result.get("exit_code", 0)
        summary += f"**Exit Code:** {exit_code}\n"

        if "stdout" in result and result["stdout"]:
            output = result["stdout"].strip()
            lines = output.split('\n')
            if len(lines) == 1:
                summary += f"**Output:** {output[:200]}{'...' if len(output) > 200 else ''}\n"
            else:
                summary += f"**Output:** {len(lines)} lines\n"
                # Show first few lines
                for line in lines[:3]:
                    if line.strip():
                        summary += f"  {line[:100]}{'...' if len(line) > 100 else ''}\n"
                if len(lines) > 3:
                    summary += f"  ... and {len(lines) - 3} more lines\n"

        if "warnings" in result and result["warnings"]:
            summary += "\n**⚠️ Warnings:**\n"
            for warning in result["warnings"][:3]:
                summary += f"• {warning}\n"

        return summary.strip()

    def list_subagents(self) -> Dict[str, Any]:
        """List available subagents and their capabilities."""
        subagent_info = {}
        for name, subagent in self.subagents.items():
            subagent_info[name] = {
                "description": subagent.metadata.description,
                "capabilities": subagent.metadata.capabilities,
                "categories": subagent.metadata.categories,
                "max_execution_time": subagent.metadata.max_execution_time
            }

        return {
            "success": True,
            "subagents": subagent_info,
            "count": len(subagent_info),
            "summary": f"Available subagents: {', '.join(self.subagents.keys())}"
        }


def create_task_tool(agent_instance) -> TaskTool:
    """Factory function to create task tool with agent reference."""
    return TaskTool(agent_instance=agent_instance)