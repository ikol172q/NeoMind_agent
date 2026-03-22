# agent/skills/loader.py
"""
Skill Loader — parses SKILL.md files and manages the skill registry.

SKILL.md format (inspired by gstack):
```
---
name: office-hours
description: Deep requirement mining with forcing questions
modes: [chat, coding, fin]     # which personalities can use this
allowed-tools: [Bash, Read, WebSearch]
version: 1.0.0
---

# Office Hours

You are conducting a structured requirement analysis session...
(rest of the prompt body)
```

The loader:
1. Scans skill directories (shared/ + mode-specific/)
2. Parses YAML frontmatter + markdown body
3. Builds a registry of available skills per mode
4. Injects skill prompts into LLM context when /skill_name is invoked
"""

import os
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class Skill:
    """A parsed SKILL.md file."""
    name: str
    description: str = ""
    body: str = ""                     # the prompt (markdown content after frontmatter)
    modes: List[str] = field(default_factory=lambda: ["chat", "coding", "fin"])
    allowed_tools: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    path: str = ""                     # filesystem path to SKILL.md
    category: str = "shared"           # shared, chat, coding, fin

    def to_system_prompt(self) -> str:
        """Convert skill into a system prompt injection."""
        return (
            f"## Active Skill: {self.name}\n"
            f"{self.description}\n\n"
            f"{self.body}"
        )

    def __repr__(self):
        return f"Skill({self.name}, modes={self.modes}, {len(self.body)} chars)"


class SkillLoader:
    """Loads and manages SKILL.md files from the skills directory tree.

    Usage:
        loader = SkillLoader()
        loader.load_all()

        # Get skills available for a specific mode
        fin_skills = loader.get_skills_for_mode("fin")

        # Get a specific skill
        skill = loader.get("office-hours")

        # List all skills
        loader.list_skills()
    """

    def __init__(self, skills_dir: Optional[str] = None):
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            self.skills_dir = Path(__file__).parent

        self._skills: Dict[str, Skill] = {}
        self._loaded = False

    def load_all(self) -> int:
        """Scan and load all SKILL.md files. Returns count loaded."""
        self._skills.clear()
        count = 0

        # Scan: shared/ + chat/ + coding/ + fin/
        for category in ["shared", "chat", "coding", "fin"]:
            category_dir = self.skills_dir / category
            if not category_dir.is_dir():
                continue

            for skill_dir in category_dir.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_file = skill_dir / "SKILL.md"
                if not skill_file.exists():
                    continue

                try:
                    skill = self._parse_skill_file(skill_file, category)
                    if skill:
                        self._skills[skill.name] = skill
                        count += 1
                except Exception as e:
                    print(f"⚠️  Failed to load skill {skill_file}: {e}")

        self._loaded = True
        return count

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        if not self._loaded:
            self.load_all()
        return self._skills.get(name)

    def get_skills_for_mode(self, mode: str) -> List[Skill]:
        """Get all skills available for a specific mode."""
        if not self._loaded:
            self.load_all()
        return [s for s in self._skills.values() if mode in s.modes]

    def list_skills(self, mode: Optional[str] = None) -> List[Dict]:
        """List all skills (optionally filtered by mode)."""
        if not self._loaded:
            self.load_all()

        skills = self._skills.values()
        if mode:
            skills = [s for s in skills if mode in s.modes]

        return [
            {
                "name": s.name,
                "description": s.description,
                "modes": s.modes,
                "category": s.category,
                "version": s.version,
            }
            for s in sorted(skills, key=lambda x: (x.category, x.name))
        ]

    def format_skill_list(self, mode: Optional[str] = None) -> str:
        """Format skill list for display."""
        skills = self.list_skills(mode)
        if not skills:
            return "No skills loaded."

        lines = []
        current_cat = ""
        for s in skills:
            if s["category"] != current_cat:
                current_cat = s["category"]
                icon = {"shared": "🔗", "chat": "💬", "coding": "💻", "fin": "📈"}.get(current_cat, "📦")
                lines.append(f"\n{icon} {current_cat.upper()}")
            modes_str = " ".join(s["modes"])
            lines.append(f"  /{s['name']} — {s['description']}  [{modes_str}]")

        return "\n".join(lines)

    @property
    def count(self) -> int:
        if not self._loaded:
            self.load_all()
        return len(self._skills)

    # ── Parsing ──────────────────────────────────────────────────

    def _parse_skill_file(self, path: Path, category: str) -> Optional[Skill]:
        """Parse a SKILL.md file into a Skill object.

        Format:
        ---
        name: skill-name
        description: What this skill does
        modes: [chat, coding, fin]
        allowed-tools: [Bash, Read]
        version: 1.0.0
        ---

        # Skill Title

        Prompt body here...
        """
        content = path.read_text(encoding="utf-8")

        # Split frontmatter and body
        frontmatter, body = self._split_frontmatter(content)

        if not frontmatter:
            # No frontmatter — use directory name as skill name
            return Skill(
                name=path.parent.name,
                body=content.strip(),
                category=category,
                path=str(path),
            )

        # Parse YAML frontmatter
        try:
            meta = yaml.safe_load(frontmatter)
            if not isinstance(meta, dict):
                meta = {}
        except yaml.YAMLError:
            meta = {}

        name = meta.get("name", path.parent.name)

        # Determine modes
        modes = meta.get("modes", None)
        if modes is None:
            # Default: shared skills available in all modes, otherwise just the category
            if category == "shared":
                modes = ["chat", "coding", "fin"]
            else:
                modes = [category]
        if isinstance(modes, str):
            modes = [modes]

        return Skill(
            name=name,
            description=meta.get("description", ""),
            body=body.strip(),
            modes=modes,
            allowed_tools=meta.get("allowed-tools", []),
            version=meta.get("version", "1.0.0"),
            path=str(path),
            category=category,
        )

    @staticmethod
    def _split_frontmatter(content: str):
        """Split YAML frontmatter from markdown body.

        Returns (frontmatter_str, body_str). frontmatter_str is None if no frontmatter.
        """
        content = content.strip()
        if not content.startswith("---"):
            return None, content

        # Find closing ---
        end = content.find("---", 3)
        if end == -1:
            return None, content

        frontmatter = content[3:end].strip()
        body = content[end + 3:].strip()
        return frontmatter, body


# ── Module-level singleton ───────────────────────────────────────

_loader_instance: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """Get or create the global skill loader singleton."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = SkillLoader()
        _loader_instance.load_all()
    return _loader_instance
