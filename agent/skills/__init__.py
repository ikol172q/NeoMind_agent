"""
Skills system for user_agent.

Skills provide dynamic knowledge loading for tools. Skills can be loaded on-demand
and injected into the context when tools require specific knowledge (APIs, docs, schemas).
"""

from .base import Skill, SkillMetadata, SkillError, SkillLoadError
from .registry import SkillRegistry, get_default_skill_registry, register_skill

__all__ = [
    "Skill",
    "SkillMetadata",
    "SkillError",
    "SkillLoadError",
    "SkillRegistry",
    "get_default_skill_registry",
    "register_skill",
]