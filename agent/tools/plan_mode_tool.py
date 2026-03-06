"""
Plan mode tool for entering planning state.

This tool switches the agent into planning mode where it can generate
and manage plans without immediately executing them.
"""

import json
from typing import Dict, Any, Optional
from .base import Tool, ToolMetadata
import agent_config


class EnterPlanModeTool(Tool):
    """Tool for entering plan mode."""

    @classmethod
    def _default_metadata(cls) -> ToolMetadata:
        return ToolMetadata(
            name="enter_plan_mode",
            description="Switch to plan mode for generating and managing plans without immediate execution.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "Goal or task to plan for"
                    },
                    "scope": {
                        "type": "string",
                        "description": "Scope of the plan (e.g., 'code', 'infrastructure', 'testing')",
                        "enum": ["code", "infrastructure", "testing", "documentation", "other"],
                        "default": "code"
                    }
                },
                "required": ["goal"]
            },
            returns={
                "type": "string",
                "description": "Confirmation message and plan mode instructions"
            },
            categories=["planning"],
            dangerous=False
        )

    def __init__(self, agent_instance=None):
        """
        Initialize plan mode tool.

        Args:
            agent_instance: Reference to the main agent instance for mode switching.
        """
        super().__init__()
        self.agent = agent_instance

    def execute(self, **kwargs) -> str:
        """
        Enter plan mode.

        Args:
            goal: Goal or task to plan for.
            scope: Scope of the plan.

        Returns:
            Confirmation message and instructions.
        """
        goal = kwargs.get("goal", "")
        scope = kwargs.get("scope", "code")

        if not self.agent:
            return "Error: Plan mode tool not connected to agent instance."

        # Store planning context
        self.agent.planning_context = {
            "goal": goal,
            "scope": scope,
            "entered_at": self._get_timestamp(),
            "plan_steps": [],
            "dependencies": [],
            "resources_needed": []
        }

        # Switch to plan mode system prompt
        plan_system_prompt = self._get_plan_mode_system_prompt(goal, scope)

        # Clear existing system prompts and set plan mode prompt
        if hasattr(self.agent, 'conversation_history'):
            self.agent.conversation_history = [
                msg for msg in self.agent.conversation_history
                if msg.get("role") != "system"
            ]
            self.agent.add_to_history("system", plan_system_prompt)

        # Set plan mode flag
        self.agent.is_in_plan_mode = True

        return f"""✅ Entered plan mode for goal: {goal}

📋 **Plan Mode Instructions:**
1. Analyze the goal and break it down into actionable steps
2. Consider dependencies between steps
3. Identify required resources and potential risks
4. Create a step-by-step execution plan
5. Use `/exit_plan_mode` when ready to execute or save the plan

🔍 **Scope:** {scope}
🎯 **Goal:** {goal}

You can now start planning. Ask clarifying questions if needed."""

    def _get_plan_mode_system_prompt(self, goal: str, scope: str) -> str:
        """Generate plan mode system prompt."""
        return f"""You are now in **PLAN MODE**.

**Goal:** {goal}
**Scope:** {scope}

Your task is to create a comprehensive, actionable plan. Follow these steps:

1. **Understand the Goal**: Clarify requirements and constraints
2. **Break Down Tasks**: Divide into smaller, manageable steps
3. **Identify Dependencies**: Determine task order and prerequisites
4. **Estimate Resources**: Consider time, tools, and knowledge needed
5. **Identify Risks**: Anticipate potential issues and mitigation strategies
6. **Create Execution Plan**: Step-by-step instructions for implementation

**Output Format:**
- Use markdown for clear structure
- Number each step sequentially
- Include estimated time/complexity for each step
- Note dependencies between steps
- Specify tools or resources needed

When your plan is complete, use the `exit_plan_mode` tool to summarize and proceed."""

    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        import datetime
        return datetime.datetime.now().isoformat()


def create_enter_plan_mode_tool(agent_instance) -> EnterPlanModeTool:
    """Factory function to create plan mode tool with agent reference."""
    return EnterPlanModeTool(agent_instance=agent_instance)