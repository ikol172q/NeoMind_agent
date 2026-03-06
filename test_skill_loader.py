#!/usr/bin/env python3
"""Test SkillLoader functionality."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent.skills.loader import SkillLoader
from agent.skills.registry import get_default_skill_registry

def test_skill_loader():
    """Test loading skills from .claude/skills/."""
    skills_dir = Path(".claude/skills")
    if not skills_dir.exists():
        print(f"Skills directory not found: {skills_dir}")
        return

    loader = SkillLoader([skills_dir])
    loader.scan()

    print(f"Found {len(loader.skills)} skills:")
    for name, info in loader.skills.items():
        print(f"  - {name}: {info['meta'].get('description', 'No description')}")
        print(f"    Path: {info['path']}")
        print(f"    Body length: {len(info['body'])} chars")

    # Test creating a skill
    for name in loader.skills:
        try:
            skill = loader.create_skill(name)
            print(f"Created skill '{name}': {skill.metadata}")
            print(f"  Type: {skill.metadata.skill_type}")
            print(f"  Dependencies: {skill.metadata.dependencies}")
        except Exception as e:
            print(f"Failed to create skill '{name}': {e}")
            import traceback
            traceback.print_exc()
            break

    # Test registration
    registry = get_default_skill_registry()
    registered = loader.load_into_registry(registry)
    print(f"Registered {len(registered)} skills: {registered}")

    # List skills in registry
    print("\nSkills in registry:")
    for skill_name in registry.list_skills():
        print(f"  - {skill_name}")

if __name__ == "__main__":
    test_skill_loader()