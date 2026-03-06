"""
Skill registry for managing and loading skills.

Provides central registry for all skills with caching, dependency resolution,
and content injection.
"""

import threading
import time
from typing import Dict, List, Optional, Any, Set
import json
from pathlib import Path

from .base import Skill, SkillMetadata, SkillError, SkillLoadError


class SkillRegistry:
    """Central registry for skills."""

    def __init__(self):
        self.skills: Dict[str, Skill] = {}
        self.skill_metadata: Dict[str, SkillMetadata] = {}
        self._lock = threading.RLock()
        self._skill_dependencies: Dict[str, List[str]] = {}
        self._skill_dependents: Dict[str, List[str]] = {}
        self._load_history: List[Dict[str, Any]] = []

    def register(self, skill: Skill, name: Optional[str] = None) -> None:
        """
        Register a skill.

        Args:
            skill: Skill instance to register.
            name: Optional custom name for the skill. Defaults to skill.metadata.name.

        Raises:
            SkillError: If registration fails.
        """
        with self._lock:
            try:
                skill_name = name or skill.metadata.name

                if skill_name in self.skills:
                    raise SkillError(f"Skill '{skill_name}' already registered")

                self.skills[skill_name] = skill
                self.skill_metadata[skill_name] = skill.metadata

                # Build dependency graph
                self._skill_dependencies[skill_name] = skill.metadata.dependencies.copy()
                for dep in skill.metadata.dependencies:
                    if dep not in self._skill_dependents:
                        self._skill_dependents[dep] = []
                    self._skill_dependents[dep].append(skill_name)

                self._log_operation("register", skill_name, True)

            except Exception as e:
                self._log_operation("register", str(skill), False, {"error": str(e)})
                raise SkillError(f"Failed to register skill: {e}") from e

    def unregister(self, name: str) -> bool:
        """
        Unregister a skill.

        Args:
            name: Name of skill to unregister.

        Returns:
            True if skill was unregistered, False if not found.
        """
        with self._lock:
            if name not in self.skills:
                return False

            # Remove from dependency graph
            if name in self._skill_dependencies:
                deps = self._skill_dependencies.pop(name)
                # Remove from dependents lists of dependencies
                for dep in deps:
                    if dep in self._skill_dependents and name in self._skill_dependents[dep]:
                        self._skill_dependents[dep].remove(name)

            # Remove from dependents mapping
            if name in self._skill_dependents:
                dependents = self._skill_dependents.pop(name)
                # Remove from dependencies lists of dependents
                for dep in dependents:
                    if dep in self._skill_dependencies and name in self._skill_dependencies[dep]:
                        self._skill_dependencies[dep].remove(name)

            del self.skills[name]
            del self.skill_metadata[name]

            self._log_operation("unregister", name, True)
            return True

    def get_skill(self, name: str) -> Skill:
        """
        Get a skill by name.

        Args:
            name: Name of skill to retrieve.

        Returns:
            Skill instance.

        Raises:
            SkillError: If skill not found.
        """
        with self._lock:
            if name not in self.skills:
                raise SkillError(f"Skill '{name}' not found")
            return self.skills[name]

    def get_skill_content(self, name: str, include_dependencies: bool = True) -> str:
        """
        Get content for a skill, optionally including dependencies.

        Args:
            name: Name of skill.
            include_dependencies: If True, include content from dependencies.

        Returns:
            Combined skill content.

        Raises:
            SkillError: If skill not found or loading fails.
        """
        with self._lock:
            if name not in self.skills:
                raise SkillError(f"Skill '{name}' not found")

            skill = self.skills[name]
            content_parts = []

            # Load dependencies first (if requested)
            if include_dependencies:
                deps = self._get_dependency_order(name)
                for dep_name in deps:
                    if dep_name != name:  # Skip the skill itself
                        dep_skill = self.skills[dep_name]
                        try:
                            dep_content = dep_skill.get_content()
                            content_parts.append(f"=== {dep_name} ===\n{dep_content}\n")
                        except Exception as e:
                            raise SkillLoadError(f"Failed to load dependency '{dep_name}' for skill '{name}': {e}") from e

            # Load the requested skill
            try:
                skill_content = skill.get_content()
                content_parts.append(f"=== {name} ===\n{skill_content}\n")
            except Exception as e:
                raise SkillLoadError(f"Failed to load skill '{name}': {e}") from e

            return "\n".join(content_parts)

    def _get_dependency_order(self, skill_name: str) -> List[str]:
        """
        Get topological order of skills starting from dependencies.

        Args:
            skill_name: Name of target skill.

        Returns:
            List of skill names in dependency order (dependencies first).
        """
        visited: Set[str] = set()
        order: List[str] = []

        def visit(name: str):
            if name in visited:
                return
            visited.add(name)
            # Visit dependencies first
            for dep in self._skill_dependencies.get(name, []):
                if dep in self.skills:
                    visit(dep)
            order.append(name)

        visit(skill_name)
        return order

    def load_skills_for_tool(self, tool_name: str, tool_categories: List[str]) -> str:
        """
        Load skills relevant to a tool based on categories.

        Args:
            tool_name: Name of tool.
            tool_categories: Categories of the tool.

        Returns:
            Combined skill content relevant to the tool.
        """
        with self._lock:
            relevant_skills = []
            for skill_name, skill in self.skills.items():
                # Check if skill tags match tool categories
                skill_tags = set(skill.metadata.tags)
                tool_cats = set(tool_categories)
                if skill_tags & tool_cats:  # Intersection
                    relevant_skills.append(skill_name)

            if not relevant_skills:
                return ""

            content_parts = []
            for skill_name in relevant_skills:
                try:
                    skill_content = self.skills[skill_name].get_content()
                    content_parts.append(f"=== {skill_name} ===\n{skill_content}\n")
                except Exception as e:
                    # Log but continue with other skills
                    self._log_operation("load_failed", skill_name, False, {"error": str(e)})

            return "\n".join(content_parts)

    def list_skills(self) -> List[str]:
        """List all registered skill names."""
        with self._lock:
            return list(self.skills.keys())

    def list_skills_with_metadata(self) -> List[Dict[str, Any]]:
        """List all skills with their metadata."""
        with self._lock:
            return [
                {
                    "name": name,
                    "metadata": metadata,
                    "is_loaded": self.skills[name]._loaded_content is not None,
                }
                for name, metadata in self.skill_metadata.items()
            ]

    def clear_cache(self, skill_name: Optional[str] = None) -> None:
        """
        Clear cache for a specific skill or all skills.

        Args:
            skill_name: Optional name of skill to clear. If None, clear all.
        """
        with self._lock:
            if skill_name:
                if skill_name in self.skills:
                    self.skills[skill_name].clear_cache()
            else:
                for skill in self.skills.values():
                    skill.clear_cache()

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about skills."""
        with self._lock:
            stats = {
                "total_skills": len(self.skills),
                "loaded_skills": sum(1 for s in self.skills.values() if s._loaded_content is not None),
                "skills_by_type": {},
                "total_loads": len(self._load_history),
            }

            # Count by skill type
            for skill in self.skills.values():
                skill_type = skill.metadata.skill_type.value
                stats["skills_by_type"][skill_type] = stats["skills_by_type"].get(skill_type, 0) + 1

            return stats

    def _log_operation(self, action: str, skill_name: str, success: bool, details: Optional[Dict] = None):
        """Log skill operation."""
        self._load_history.append({
            "timestamp": time.time(),
            "action": action,
            "skill": skill_name,
            "success": success,
            "details": details or {},
        })

    def load_from_directory(self, directory: Path) -> List[str]:
        """
        Load skills from a directory containing SKILL.md files.

        Args:
            directory: Directory to scan for SKILL.md files.

        Returns:
            List of skill names that were successfully registered.
        """
        from .loader import SkillLoader
        loader = SkillLoader([directory])
        loader.scan()
        return loader.load_into_registry(self)


# Global registry instance
_default_registry: Optional[SkillRegistry] = None


def get_default_skill_registry() -> SkillRegistry:
    """Get or create the default global skill registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SkillRegistry()
    return _default_registry


def register_skill(skill: Skill, name: Optional[str] = None) -> None:
    """Register a skill with the default registry."""
    get_default_skill_registry().register(skill, name)