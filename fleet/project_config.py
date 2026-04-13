"""
Project ↔ Team alias layer.

A 'project' in user-facing config maps 1:1 to a 'team' in the Swarm system.
This module provides the translation so users can think in 'projects' while
the runtime uses the existing team infrastructure.

Contract: contracts/persona_fleet/02_project_alias.md
"""

from __future__ import annotations

from typing import Optional, Dict, Any, List

from agent.agentic.swarm import TeamManager, VALID_PERSONAS

VALID_ROLES = frozenset({"leader", "worker", "reviewer", "observer"})


def create_project(
    project_id: str,
    leader_name: str,
    leader_persona: str = "chat",
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a project (= team) with a leader.

    Args:
        project_id: Project identifier (becomes team_name internally).
        leader_name: Name of the leader agent.
        leader_persona: Persona for the leader (default: "chat").
        base_dir: Optional base directory for team storage.

    Returns:
        Team data dict from TeamManager.create_team().

    Raises:
        ValueError: if project_id already exists or leader_persona is invalid.
    """
    if not project_id or not project_id.strip():
        raise ValueError("project_id cannot be empty")
    if leader_persona not in VALID_PERSONAS:
        raise ValueError(
            f"Invalid persona '{leader_persona}'. "
            f"Must be one of: {', '.join(sorted(VALID_PERSONAS))}"
        )

    mgr = TeamManager(base_dir=base_dir)
    return mgr.create_team(
        team_name=project_id.strip(),
        leader_name=leader_name,
        leader_persona=leader_persona,
    )


def add_project_member(
    project_id: str,
    member_name: str,
    persona: str,
    role: str = "worker",
    base_dir: Optional[str] = None,
) -> Any:
    """Add a member to a project.

    Args:
        project_id: Project identifier.
        member_name: Name of the new member.
        persona: Persona to assign ("chat", "coding", "fin").
        role: Role in the team ("leader", "worker", "reviewer", "observer").
        base_dir: Optional base directory.

    Returns:
        TeammateIdentity from TeamManager.add_member().

    Raises:
        ValueError: if project doesn't exist, persona invalid, or role invalid.
    """
    if persona not in VALID_PERSONAS:
        raise ValueError(
            f"Invalid persona '{persona}'. "
            f"Must be one of: {', '.join(sorted(VALID_PERSONAS))}"
        )
    if role not in VALID_ROLES:
        raise ValueError(
            f"Invalid role '{role}'. "
            f"Must be one of: {', '.join(sorted(VALID_ROLES))}"
        )

    mgr = TeamManager(base_dir=base_dir)
    return mgr.add_member(
        team_name=project_id,
        member_name=member_name,
        persona=persona,
    )


def get_project(
    project_id: str,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Get project data (= team data).

    Returns None if project doesn't exist.
    """
    mgr = TeamManager(base_dir=base_dir)
    return mgr.get_team(project_id)


def delete_project(
    project_id: str,
    base_dir: Optional[str] = None,
) -> None:
    """Delete a project and all its data."""
    mgr = TeamManager(base_dir=base_dir)
    mgr.delete_team(project_id)
