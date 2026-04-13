# Contract 05 — Multi-Instance Fleet Launcher

**Phase:** 5
**Status:** SPEC — not implemented
**Scope:** New files `fleet/launch_project.py` + `fleet/project_schema.py`

---

## Summary

A launcher that reads a `project.yaml` config and spawns N agent instances as asyncio tasks in one process, each bound to its assigned persona via `AgentConfigManager`. For solo-user scale, asyncio is sufficient (no docker-per-instance).

---

## Project Config Schema

```yaml
# projects/<id>/project.yaml
project_id: build-trading-bot
description: "Build a stock price fetcher with backtesting"

leader: manager-1

members:
  - name: manager-1
    persona: chat
    role: leader
  - name: coder-1
    persona: coding
    role: worker
  - name: coder-2
    persona: coding
    role: worker
  - name: coder-3
    persona: coding
    role: worker
  - name: quant-1
    persona: fin
    role: worker
  - name: quant-2
    persona: fin
    role: worker

# Optional settings
settings:
  max_concurrent_tasks: 3
  stuck_timeout_minutes: 10
  auto_shutdown_on_complete: true
```

---

## Interface

### `fleet/project_schema.py`

```python
@dataclass
class MemberConfig:
    name: str
    persona: str     # "chat" | "coding" | "fin"
    role: str        # "leader" | "worker" | "reviewer" | "observer"

@dataclass
class ProjectConfig:
    project_id: str
    description: str
    leader: str
    members: List[MemberConfig]
    settings: Dict[str, Any]

def load_project_config(path: str) -> ProjectConfig:
    """Load and validate a project.yaml file.
    
    Raises:
        FileNotFoundError: if path doesn't exist
        ValueError: if config is invalid (missing fields, invalid personas, etc.)
    """

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
```

### `fleet/launch_project.py`

```python
class FleetLauncher:
    """Launch and manage a fleet of agent instances for a project."""

    def __init__(self, config: ProjectConfig, base_dir: Optional[str] = None):
        """
        Args:
            config: Validated project configuration
            base_dir: Optional base dir for team storage
        """

    async def start(self) -> None:
        """Start all agent instances as asyncio tasks.
        
        1. Creates the team via TeamManager (with personas)
        2. Sets up Mailbox for each member
        3. Sets up SharedTaskQueue for the team
        4. Spawns each member as an asyncio task with its own AgentConfigManager
           configured for the member's persona
        5. The leader's task includes ChatSupervisor
        """

    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop all instances.
        
        1. Sends shutdown message to all member mailboxes
        2. Waits for tasks to complete (up to timeout)
        3. Cancels remaining tasks
        4. Cleans up team resources
        """

    def get_status(self) -> Dict[str, Any]:
        """Get current fleet status.
        
        Returns:
            {
                "project_id": "build-trading-bot",
                "running": True,
                "members": {
                    "manager-1": {"persona": "chat", "role": "leader", "status": "running"},
                    "coder-1": {"persona": "coding", "role": "worker", "status": "running"},
                    ...
                },
                "tasks": {"available": 2, "claimed": 1, "completed": 5}
            }
        """

    async def submit_task(self, description: str,
                          target_persona: Optional[str] = None) -> str:
        """Submit a task to the fleet (delegates to leader's ChatSupervisor).
        
        Returns task_id.
        """
```

---

## Instance Isolation

Each asyncio task runs with:
- Its own `AgentConfigManager` instance (NOT the global singleton) configured via `switch_mode(persona)`
- Its own `Mailbox` (identified by member name)
- Shared `SharedTaskQueue` (team-level)
- Shared `SharedMemory` (with source_instance and project_id tags from Contract 04)

**Critical**: the global `agent_config` singleton must NOT be used by fleet instances. Each instance creates its own `AgentConfigManager(mode=persona)`.

---

## Dependencies

- Contract 01 (persona binding) — `TeamManager.add_member(team, name, persona)`
- Contract 02 (project alias) — `create_project()`, `add_project_member()`
- Contract 03 (chat supervisor) — `ChatSupervisor` for the leader instance
- Contract 04 (cross-persona memory) — `SharedMemory` with source_instance/project_id

---

## Test Contract (Pair A implements these)

### Unit Tests

1. **`test_load_project_config`**: Load a valid `project.yaml` → `ProjectConfig` with correct fields.

2. **`test_load_invalid_config_missing_leader`**: Config without leader → `ValueError`.

3. **`test_load_invalid_config_duplicate_names`**: Two members with same name → validation error.

4. **`test_load_invalid_persona`**: Member with `persona: "invalid"` → validation error.

5. **`test_validate_project_config_valid`**: Valid config → empty error list.

6. **`test_validate_project_config_no_leader_role`**: No member has role=leader → error.

7. **`test_fleet_launcher_init`**: Create `FleetLauncher(config)` → no error.

### Integration Tests

8. **`test_fleet_start_stop`**: Start a 3-member fleet → verify all tasks running → stop → verify all cleaned up.

9. **`test_fleet_submit_task`**: Start fleet → submit task → verify task appears in queue → verify a worker claims it.

10. **`test_fleet_instance_isolation`**: Start fleet with coding + fin workers → verify each instance's `AgentConfigManager` is set to the correct mode → verify they don't share state.

11. **`test_fleet_cross_persona_memory`**: Start fleet → coding worker writes a fact → fin worker reads it with source envelope → source says "coding".

12. **`test_fleet_full_lifecycle`**: Start fleet → submit multi-step task → leader dispatches to workers → workers complete → leader aggregates → fleet shuts down cleanly.
