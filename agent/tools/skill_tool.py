"""
Skill tool for loading and managing knowledge skills.

Provides tools to load, query, and manage skills that contain domain knowledge
(Python APIs, web APIs, project documentation, etc.).
"""

import json
from typing import Dict, Any, Optional

from .base import Tool, ToolMetadata
from ..skills.registry import get_default_skill_registry
from ..skills.examples import create_python_api_skill, create_web_api_skill, create_codebase_skill


class SkillTool(Tool):
    """Tool for loading and querying skills."""

    def _default_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="skill",
            description="Load and query knowledge skills. Skills provide domain knowledge (APIs, docs, schemas).",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: 'load', 'get', 'list', 'clear_cache', 'register_defaults'",
                        "enum": ["load", "get", "list", "clear_cache", "register_defaults"]
                    },
                    "skill_name": {
                        "type": "string",
                        "description": "Name of skill (required for 'load' and 'get')"
                    },
                    "include_dependencies": {
                        "type": "boolean",
                        "description": "Include dependency skills (default: true)",
                        "default": True
                    }
                },
                "required": ["action"]
            },
            returns={
                "type": "string",
                "description": "Skill content or operation result"
            },
            categories=["knowledge", "system"],
            dangerous=False
        )

    def execute(self, **kwargs) -> Any:
        action = kwargs["action"]
        skill_registry = get_default_skill_registry()

        if action == "register_defaults":
            return self._register_default_skills(skill_registry)

        elif action == "list":
            skills = skill_registry.list_skills_with_metadata()
            if not skills:
                return "No skills registered. Use 'register_defaults' to add example skills."

            result = ["Registered skills:"]
            for skill_info in skills:
                skill = skill_info
                result.append(f"- {skill['name']}: {skill['metadata'].description}")
                result.append(f"  Type: {skill['metadata'].skill_type.value}, Tags: {', '.join(skill['metadata'].tags)}")
                result.append(f"  Loaded: {skill['is_loaded']}")
            return "\n".join(result)

        elif action == "load":
            skill_name = kwargs.get("skill_name")
            if not skill_name:
                return "Error: skill_name is required for 'load' action"
            include_deps = kwargs.get("include_dependencies", True)

            try:
                content = skill_registry.get_skill_content(skill_name, include_deps)
                # Estimate tokens
                skill = skill_registry.get_skill(skill_name)
                token_estimate = skill.estimate_tokens(content)
                return f"✅ Loaded skill '{skill_name}' ({token_estimate} estimated tokens):\n\n{content}"
            except Exception as e:
                return f"❌ Failed to load skill '{skill_name}': {e}"

        elif action == "get":
            skill_name = kwargs.get("skill_name")
            if not skill_name:
                return "Error: skill_name is required for 'get' action"

            try:
                skill = skill_registry.get_skill(skill_name)
                content = skill.get_content()
                token_estimate = skill.estimate_tokens()
                return f"Skill '{skill_name}' ({token_estimate} tokens):\n\n{content}"
            except Exception as e:
                return f"❌ Failed to get skill '{skill_name}': {e}"

        elif action == "clear_cache":
            skill_name = kwargs.get("skill_name")
            if skill_name:
                skill_registry.clear_cache(skill_name)
                return f"Cleared cache for skill '{skill_name}'"
            else:
                skill_registry.clear_cache()
                return "Cleared cache for all skills"

        else:
            return f"Unknown action: {action}"

    def _register_default_skills(self, skill_registry) -> str:
        """Register default example skills."""
        try:
            # Check if already registered
            existing = skill_registry.list_skills()
            registered = []

            if "python_api" not in existing:
                python_skill = create_python_api_skill()
                skill_registry.register(python_skill)
                registered.append("python_api")

            if "web_api" not in existing:
                web_skill = create_web_api_skill()
                skill_registry.register(web_skill)
                registered.append("web_api")

            if "codebase" not in existing:
                codebase_skill = create_codebase_skill()
                skill_registry.register(codebase_skill)
                registered.append("codebase")

            if registered:
                return f"✅ Registered default skills: {', '.join(registered)}"
            else:
                return "Default skills already registered."

        except Exception as e:
            return f"❌ Failed to register default skills: {e}"


def create_skill_tool() -> SkillTool:
    """Create and return a SkillTool instance."""
    return SkillTool()