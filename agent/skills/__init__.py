# agent/skills/__init__.py
"""
NeoMind Skill System — structured workflow prompts.

Skills are SKILL.md files with YAML frontmatter + markdown body.
The loader parses them and injects into the LLM context when invoked.

Directory layout:
    agent/skills/shared/      → available in all modes
    agent/skills/chat/        → chat mode only
    agent/skills/coding/      → coding mode only
    agent/skills/fin/         → fin mode only
"""

from .loader import SkillLoader, Skill, get_skill_loader

__all__ = ['SkillLoader', 'Skill', 'get_skill_loader']
