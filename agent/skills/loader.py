"""
Skill loader for file-based skills (SKILL.md with YAML frontmatter).

Provides SkillLoader class that scans directories for SKILL.md files,
parses YAML frontmatter, and creates FileBasedSkill instances with
appropriate metadata.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from .base import Skill, SkillMetadata, SkillType, FileBasedSkill, SkillError


class SkillLoader:
    """Loads skills from SKILL.md files with YAML frontmatter."""

    def __init__(self, skill_directories: List[Path]):
        """
        Initialize skill loader with directories to scan.

        Args:
            skill_directories: List of Path objects to directories containing *.md files.
        """
        self.skill_directories = skill_directories
        self.skills: Dict[str, Dict[str, Any]] = {}  # name -> {meta, body, path}

    @staticmethod
    def _parse_yaml_frontmatter(yaml_text: str) -> Dict[str, Any]:
        """Parse YAML frontmatter text into a dictionary.

        Falls back to simple key:value parsing if yaml library not available.
        """
        if HAS_YAML:
            try:
                return yaml.safe_load(yaml_text) or {}
            except yaml.YAMLError:
                pass

        # Simple parsing for key: value lines
        result = {}
        for line in yaml_text.strip().splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                result[key.strip()] = value.strip()
        return result

    def scan(self) -> None:
        """Scan all configured directories for *.md files and parse them."""
        self.skills.clear()
        for directory in self.skill_directories:
            if not directory.exists():
                continue
            for skill_file in directory.rglob("*.md"):
                try:
                    self._parse_skill_file(skill_file)
                except Exception as e:
                    print(f"Warning: Failed to parse skill file {skill_file}: {e}")

    def _parse_skill_file(self, skill_file: Path) -> None:
        """Parse a single SKILL.md file with YAML frontmatter."""
        text = skill_file.read_text(encoding='utf-8')

        # Parse YAML frontmatter between --- delimiters
        meta = {}
        body = text
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
        if match:
            yaml_text = match.group(1)
            body = match.group(2).strip()
            meta = self._parse_yaml_frontmatter(yaml_text)

        # Ensure meta is a dict
        if not isinstance(meta, dict):
            meta = {}

        # Determine skill name
        name = meta.get('name', skill_file.parent.name)

        # Store parsed skill
        self.skills[name] = {
            'meta': meta,
            'body': body,
            'path': skill_file
        }

    def create_skill(self, name: str) -> Skill:
        """
        Create a Skill instance from a loaded skill definition.

        Args:
            name: Name of skill (as registered in loader).

        Returns:
            Skill instance.

        Raises:
            SkillError: If skill not found or metadata invalid.
        """
        if name not in self.skills:
            raise SkillError(f"Skill '{name}' not found in loaded skills")

        skill_info = self.skills[name]
        meta = skill_info['meta']
        body = skill_info['body']
        path = skill_info['path']

        # Map YAML fields to SkillMetadata
        skill_type_str = meta.get('skill_type', 'GENERAL').upper()
        try:
            skill_type = SkillType[skill_type_str]
        except KeyError:
            skill_type = SkillType.GENERAL

        # Parse dependencies (comma-separated string or list)
        dependencies = meta.get('dependencies', [])
        if isinstance(dependencies, str):
            dependencies = [d.strip() for d in dependencies.split(',') if d.strip()]

        # Parse tags (comma-separated string or list)
        tags = meta.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',') if t.strip()]

        # Create metadata
        metadata = SkillMetadata(
            name=meta.get('name', name),
            description=meta.get('description', 'File-based skill loaded from SKILL.md'),
            skill_type=skill_type,
            version=meta.get('version', '1.0.0'),
            tags=tags,
            size_estimate=meta.get('size_estimate'),
            cache_ttl=meta.get('cache_ttl', 3600),
            dependencies=dependencies,
        )

        # Create a FileBasedSkill that loads the body directly (not from file)
        # We'll create a custom subclass that returns the parsed body
        class ParsedFileSkill(FileBasedSkill):
            def load_content(self) -> str:
                return body

        skill = ParsedFileSkill(str(path), metadata)
        return skill

    def load_into_registry(self, registry) -> List[str]:
        """
        Load all scanned skills into a SkillRegistry.

        Args:
            registry: SkillRegistry instance.

        Returns:
            List of skill names that were successfully registered.
        """
        registered = []
        for name in self.skills:
            try:
                skill = self.create_skill(name)
                registry.register(skill, name)
                registered.append(name)
            except Exception as e:
                print(f"Warning: Failed to register skill '{name}': {e}")
        return registered

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all scanned skills with their metadata."""
        return [
            {
                'name': name,
                'meta': info['meta'],
                'path': str(info['path']),
                'body_preview': info['body'][:200] + '...' if len(info['body']) > 200 else info['body']
            }
            for name, info in self.skills.items()
        ]

    def get_skill_body(self, name: str) -> str:
        """Get the body content of a skill."""
        if name not in self.skills:
            raise SkillError(f"Skill '{name}' not found")
        return self.skills[name]['body']

    def get_skill_metadata(self, name: str) -> Dict[str, Any]:
        """Get the metadata of a skill."""
        if name not in self.skills:
            raise SkillError(f"Skill '{name}' not found")
        return self.skills[name]['meta']


# Convenience function
def load_skills_from_directory(directory: Path, registry=None) -> List[str]:
    """
    Load skills from a directory into the default registry.

    Args:
        directory: Directory to scan for SKILL.md files.
        registry: Optional SkillRegistry instance. If None, uses default registry.

    Returns:
        List of skill names registered.
    """
    from .registry import get_default_skill_registry
    if registry is None:
        registry = get_default_skill_registry()

    loader = SkillLoader([directory])
    loader.scan()
    return loader.load_into_registry(registry)