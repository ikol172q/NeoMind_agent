"""
Project configuration schema for fleet launcher.

Defines the YAML schema for project.yaml files and provides
loading + validation.

Contract: contracts/persona_fleet/05_fleet_launcher.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from agent.agentic.swarm import VALID_PERSONAS

VALID_ROLES = frozenset({"leader", "worker", "reviewer", "observer"})


@dataclass
class MemberConfig:
    """Configuration for a single fleet member."""
    name: str
    persona: str     # "chat" | "coding" | "fin"
    role: str        # "leader" | "worker" | "reviewer" | "observer"


@dataclass
class ProjectConfig:
    """Full project configuration loaded from project.yaml."""
    project_id: str
    description: str
    leader: str
    members: List[MemberConfig]
    settings: Dict[str, Any] = field(default_factory=dict)


def validate_project_config(config: ProjectConfig) -> List[str]:
    """Validate a project config. Returns list of error messages (empty = valid).

    Checks:
    - project_id is non-empty
    - Exactly one leader
    - Leader name matches a member
    - All personas are valid
    - All roles are valid
    - No duplicate member names
    """
    errors: List[str] = []

    if not config.project_id or not config.project_id.strip():
        errors.append("project_id cannot be empty")

    # Check for duplicate names
    names = [m.name for m in config.members]
    seen = set()
    for n in names:
        if n in seen:
            errors.append(f"Duplicate member name: '{n}'")
        seen.add(n)

    # Count leaders
    leaders = [m for m in config.members if m.role == "leader"]
    if len(leaders) == 0:
        errors.append("No member has role='leader'")
    elif len(leaders) > 1:
        errors.append(f"Multiple leaders found: {[l.name for l in leaders]}")

    # Check leader name matches
    if config.leader and config.leader not in names:
        errors.append(
            f"Leader '{config.leader}' not found in members list"
        )

    # Validate each member
    for m in config.members:
        if m.persona not in VALID_PERSONAS:
            errors.append(
                f"Member '{m.name}' has invalid persona '{m.persona}'. "
                f"Must be one of: {', '.join(sorted(VALID_PERSONAS))}"
            )
        if m.role not in VALID_ROLES:
            errors.append(
                f"Member '{m.name}' has invalid role '{m.role}'. "
                f"Must be one of: {', '.join(sorted(VALID_ROLES))}"
            )

    return errors


def load_project_config(path: str) -> ProjectConfig:
    """Load and validate a project.yaml file.

    Args:
        path: Path to the project.yaml file.

    Returns:
        Validated ProjectConfig.

    Raises:
        FileNotFoundError: if path doesn't exist.
        ValueError: if config is invalid.
    """
    import os
    if not os.path.exists(path):
        raise FileNotFoundError(f"Project config not found: {path}")

    # Try YAML first, fall back to JSON
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except ImportError:
        import json
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("Project config must be a YAML/JSON object")

    # Parse members
    members = []
    for m in raw.get("members", []):
        if not isinstance(m, dict):
            raise ValueError(f"Each member must be a dict, got: {type(m)}")
        members.append(MemberConfig(
            name=m.get("name", ""),
            persona=m.get("persona", ""),
            role=m.get("role", "worker"),
        ))

    config = ProjectConfig(
        project_id=raw.get("project_id", ""),
        description=raw.get("description", ""),
        leader=raw.get("leader", ""),
        members=members,
        settings=raw.get("settings", {}),
    )

    errors = validate_project_config(config)
    if errors:
        raise ValueError(
            f"Invalid project config: {'; '.join(errors)}"
        )

    return config
