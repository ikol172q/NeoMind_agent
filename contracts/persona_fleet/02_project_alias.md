# Contract 02 — Project = Team Alias

**Phase:** 2
**Status:** SPEC — not implemented
**Scope:** New file `fleet/project_config.py` (thin alias layer)

---

## Summary

The user's mental model uses "project" as the bounded context for a fleet of agent instances. Internally, NeoMind uses "team". These are the same concept. We add a thin alias layer so user-facing config and launcher use "project" while all internals stay on "team".

---

## Changes Required

### New file: `fleet/project_config.py`

```python
"""Project ↔ Team alias layer.

A 'project' in user-facing config maps 1:1 to a 'team' in the Swarm system.
This module provides the translation so users can think in 'projects' while
the runtime uses the existing team infrastructure.
"""

from typing import Optional, Dict, Any
from agent.agentic.swarm import TeamManager

VALID_PERSONAS = {"chat", "coding", "fin"}
VALID_ROLES = {"leader", "worker", "reviewer", "observer"}

def create_project(project_id: str, leader_name: str,
                   leader_persona: str = "chat",
                   base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Create a project (= team) with a leader.
    
    Args:
        project_id: Project identifier (becomes team_name internally)
        leader_name: Name of the leader agent
        leader_persona: Persona for the leader (default: "chat")
        base_dir: Optional base directory for team storage
    
    Returns:
        Team data dict from TeamManager.create_team()
    
    Raises:
        ValueError: if project_id already exists or leader_persona is invalid
    """

def add_project_member(project_id: str, member_name: str,
                       persona: str, role: str = "worker",
                       base_dir: Optional[str] = None) -> Any:
    """Add a member to a project.
    
    Args:
        project_id: Project identifier
        member_name: Name of the new member
        persona: Persona to assign ("chat", "coding", "fin")
        role: Role in the team ("leader", "worker", "reviewer", "observer")
        base_dir: Optional base directory
    
    Returns:
        TeammateIdentity from TeamManager.add_member()
    
    Raises:
        ValueError: if project doesn't exist, persona invalid, or role invalid
    """

def get_project(project_id: str,
                base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get project data (= team data).
    
    Returns None if project doesn't exist.
    """

def delete_project(project_id: str,
                   base_dir: Optional[str] = None) -> None:
    """Delete a project and all its data."""
```

---

## Backward Compatibility

- Pure addition — no existing code changes
- Teams created without this layer still work (they just don't have a "project" alias)
- Projects created through this layer are standard teams in `~/.neomind/teams/{project_id}/`

---

## Test Contract (Pair A implements these)

### Unit Tests

1. **`test_create_project`**: `create_project("my-proj", "leader-1", "chat")` → returns team data with `name="my-proj"`, leader has `persona="chat"`.

2. **`test_create_project_invalid_persona`**: `create_project("x", "y", "invalid")` → `ValueError`.

3. **`test_add_project_member`**: `add_project_member("my-proj", "coder-1", "coding")` → member exists in team with `persona="coding"`.

4. **`test_get_project`**: Create project → `get_project("my-proj")` returns data with correct members.

5. **`test_get_project_nonexistent`**: `get_project("nonexistent")` → returns `None`.

6. **`test_delete_project`**: Create → delete → `get_project()` returns `None`.

7. **`test_project_is_team`**: Create project → verify team files exist at `~/.neomind/teams/{project_id}/team.json`.
