"""
Exit plan mode tool for summarizing and executing plans.

This tool exits plan mode, summarizes the generated plan, and optionally
executes or saves it.
"""

import json
from typing import Dict, Any, Optional, List
from .base import Tool, ToolMetadata


class ExitPlanModeTool(Tool):
    """Tool for exiting plan mode and summarizing results."""

    @classmethod
    def _default_metadata(cls) -> ToolMetadata:
        return ToolMetadata(
            name="exit_plan_mode",
            description="Exit plan mode, summarize the generated plan, and optionally execute or save it.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "What to do with the plan",
                        "enum": ["summarize", "save", "execute", "cancel"],
                        "default": "summarize"
                    },
                    "plan_name": {
                        "type": "string",
                        "description": "Name for saving the plan (required if action=save)"
                    },
                    "execute_steps": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Which plan steps to execute (e.g., [1, 2, 3])"
                    }
                },
                "required": []
            },
            returns={
                "type": "string",
                "description": "Plan summary and next steps"
            },
            categories=["planning"],
            dangerous=False
        )

    def __init__(self, agent_instance=None):
        """
        Initialize exit plan mode tool.

        Args:
            agent_instance: Reference to the main agent instance.
        """
        super().__init__()
        self.agent = agent_instance

    def execute(self, **kwargs) -> str:
        """
        Exit plan mode and handle the plan.

        Args:
            action: What to do with the plan (summarize, save, execute, cancel).
            plan_name: Name for saving the plan.
            execute_steps: Which steps to execute.

        Returns:
            Plan summary and next steps.
        """
        action = kwargs.get("action", "summarize")
        plan_name = kwargs.get("plan_name", "")
        execute_steps = kwargs.get("execute_steps", [])

        if not self.agent:
            return "Error: Exit plan mode tool not connected to agent instance."

        if not getattr(self.agent, 'is_in_plan_mode', False):
            return "Not currently in plan mode. Use `enter_plan_mode` first."

        # Extract plan from conversation
        plan_summary = self._extract_plan_from_conversation()
        planning_context = getattr(self.agent, 'planning_context', {})

        # Handle action
        result = self._handle_action(action, plan_summary, planning_context,
                                    plan_name, execute_steps)

        # Exit plan mode
        self.agent.is_in_plan_mode = False
        if hasattr(self.agent, 'planning_context'):
            delattr(self.agent, 'planning_context')

        # Restore previous system prompt or default
        self._restore_system_prompt()

        return result

    def _extract_plan_from_conversation(self) -> Dict[str, Any]:
        """Extract plan information from conversation history."""
        if not hasattr(self.agent, 'conversation_history'):
            return {"steps": [], "dependencies": [], "resources": []}

        # Simple extraction - look for structured plan in last few messages
        plan_data = {
            "steps": [],
            "dependencies": [],
            "resources": [],
            "estimated_time": None,
            "risks": []
        }

        # This is a simple implementation. In practice, you might want
        # more sophisticated plan parsing or store plan in a structured way.
        for msg in self.agent.conversation_history[-10:]:  # Last 10 messages
            content = msg.get("content", "")
            if "step" in content.lower() or "plan" in content.lower():
                # Try to extract steps (very basic)
                lines = content.split('\n')
                for line in lines:
                    line_lower = line.lower()
                    if any(marker in line_lower for marker in ["step ", "1.", "2.", "3.", "4.", "5."]):
                        if len(line.strip()) > 10:  # Not just a header
                            plan_data["steps"].append(line.strip())

        return plan_data

    def _handle_action(self, action: str, plan_summary: Dict[str, Any],
                      planning_context: Dict[str, Any], plan_name: str,
                      execute_steps: List[int]) -> str:
        """Handle the requested action."""
        goal = planning_context.get("goal", "Unknown goal")
        scope = planning_context.get("scope", "code")

        if action == "cancel":
            return f"❌ Plan cancelled for: {goal}\n\nPlanning session ended."

        # Build summary
        summary = f"""📋 **Plan Summary**
🎯 **Goal:** {goal}
🔍 **Scope:** {scope}
📝 **Steps Identified:** {len(plan_summary.get('steps', []))}
⏱️ **Generated:** {planning_context.get('entered_at', 'Unknown time')}

"""

        if plan_summary.get("steps"):
            summary += "\n**Key Steps:**\n"
            for i, step in enumerate(plan_summary["steps"][:5], 1):
                summary += f"  {i}. {step[:100]}{'...' if len(step) > 100 else ''}\n"
            if len(plan_summary["steps"]) > 5:
                summary += f"  ... and {len(plan_summary['steps']) - 5} more steps\n"

        if action == "summarize":
            summary += "\n💡 **Next:** Use `/task create` to create tasks from this plan, or `/plan execute` to begin execution."
            return summary

        elif action == "save":
            if not plan_name:
                return "Error: plan_name is required when action=save"

            # Save plan to file
            save_path = self._save_plan_to_file(plan_name, plan_summary, planning_context)
            summary += f"\n💾 **Saved to:** {save_path}"
            summary += f"\n📁 **Plan Name:** {plan_name}"
            summary += "\n💡 **Next:** Load this plan later with `/plan load {name}`"
            return summary

        elif action == "execute":
            # Create tasks from plan
            task_count = self._create_tasks_from_plan(plan_summary, execute_steps)
            summary += f"\n🚀 **Created {task_count} task(s) for execution**"
            summary += "\n📋 **Next:** Check `/task list` to see created tasks, then `/task execute` to begin."
            return summary

        return summary

    def _save_plan_to_file(self, plan_name: str, plan_summary: Dict[str, Any],
                          planning_context: Dict[str, Any]) -> str:
        """Save plan to JSON file."""
        import os
        import json
        from datetime import datetime

        plan_data = {
            "name": plan_name,
            "goal": planning_context.get("goal", ""),
            "scope": planning_context.get("scope", "code"),
            "created_at": datetime.now().isoformat(),
            "planning_session": planning_context.get("entered_at", ""),
            "summary": plan_summary,
            "full_conversation": getattr(self.agent, 'conversation_history', [])[-20:]  # Last 20 messages
        }

        # Create plans directory if needed
        plans_dir = os.path.join(os.getcwd(), ".ikol1729_agent", "plans")
        os.makedirs(plans_dir, exist_ok=True)

        # Sanitize filename
        safe_name = "".join(c for c in plan_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')[:50]
        filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(plans_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(plan_data, f, indent=2, ensure_ascii=False)

        return filepath

    def _create_tasks_from_plan(self, plan_summary: Dict[str, Any],
                               execute_steps: List[int]) -> int:
        """Create tasks from plan steps."""
        if not hasattr(self.agent, 'task_manager'):
            return 0

        steps = plan_summary.get("steps", [])
        if execute_steps:
            # Filter to selected steps
            steps = [steps[i-1] for i in execute_steps if 0 < i <= len(steps)]

        task_count = 0
        for i, step in enumerate(steps, 1):
            try:
                self.agent.task_manager.create_task(
                    title=f"Plan Step {i}: {step[:50]}...",
                    description=step,
                    status="pending"
                )
                task_count += 1
            except:
                pass

        return task_count

    def _restore_system_prompt(self):
        """Restore previous system prompt."""
        if not hasattr(self.agent, 'conversation_history'):
            return

        # Remove plan mode system prompt
        self.agent.conversation_history = [
            msg for msg in self.agent.conversation_history
            if msg.get("role") != "system"
        ]

        # Add default system prompt based on mode
        from agent_config import agent_config
        if self.agent.mode == "coding":
            prompt = agent_config.coding_mode_system_prompt
        elif self.agent.mode == "tool":
            prompt = agent_config.tool_mode_system_prompt
        else:
            prompt = agent_config.system_prompt

        if prompt:
            self.agent.add_to_history("system", prompt)


def create_exit_plan_mode_tool(agent_instance) -> ExitPlanModeTool:
    """Factory function to create exit plan mode tool with agent reference."""
    return ExitPlanModeTool(agent_instance=agent_instance)