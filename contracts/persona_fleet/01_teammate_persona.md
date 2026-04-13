# Contract 01 — Persona ↔ Teammate Binding

**Phase:** 1
**Status:** SPEC — not implemented
**Scope:** `agent/agentic/swarm.py` + `agent/tools/collaboration_tools.py`

---

## Summary

Add a `persona` field to teammate registration so that when a team member boots, the runtime knows which personality (chat/coding/fin) to load for that instance.

---

## Changes Required

### 1. `agent/agentic/swarm.py`

#### `TeammateIdentity` dataclass

**Before:**
```python
@dataclass
class TeammateIdentity:
    agent_id: str
    agent_name: str
    team_name: str
    color: str = "default"
    is_leader: bool = False
```

**After:**
```python
@dataclass
class TeammateIdentity:
    agent_id: str
    agent_name: str
    team_name: str
    color: str = "default"
    is_leader: bool = False
    persona: Optional[str] = None  # "chat" | "coding" | "fin" | None (legacy)
```

#### `TeamManager.create_team()`

**Before:** leader member dict is `{'name': leader_name, 'color': TEAM_COLORS[0], 'is_leader': True}`

**After:** add `'persona': leader_persona` to the dict.

**Signature change:**
```python
def create_team(self, team_name: str, leader_name: str,
                leader_persona: Optional[str] = None) -> Dict[str, Any]:
```

#### `TeamManager.add_member()`

**Before:** member dict is `{'name': member_name, 'color': ..., 'is_leader': False}`

**After:** add `'persona': persona` to the dict.

**Signature change:**
```python
def add_member(self, team_name: str, member_name: str,
               persona: Optional[str] = None) -> TeammateIdentity:
```

The returned `TeammateIdentity` must have `.persona` set.

### 2. `agent/tools/collaboration_tools.py`

#### `TeamMember` dataclass

**Before:**
```python
@dataclass
class TeamMember:
    member_id: str
    role: TeamRole
    joined_at: datetime = field(default_factory=datetime.now)
```

**After:**
```python
@dataclass
class TeamMember:
    member_id: str
    role: TeamRole
    persona: Optional[str] = None  # "chat" | "coding" | "fin" | None
    joined_at: datetime = field(default_factory=datetime.now)
```

#### `TeamManager.create_team()` (collaboration_tools version)

Add `personas: Optional[Dict[str, str]] = None` parameter (maps member_id → persona).

#### `TeamManager.add_member()` (collaboration_tools version)

Add `persona: Optional[str] = None` parameter.

---

## Backward Compatibility

- `persona=None` is the default everywhere → existing teams created without persona still work
- Old `team.json` files without `persona` in member dicts load fine (`.get('persona')` returns None)
- No schema migration needed for the file-based swarm storage (JSON is schema-flexible)

---

## Validation Rules

- `persona` must be one of: `None`, `"chat"`, `"coding"`, `"fin"`
- Invalid persona values should raise `ValueError` with a clear message
- At team creation time, the valid persona list comes from `agent/modes/` — but for Phase 1 we hardcode `{"chat", "coding", "fin"}` since there's no dynamic persona registry yet

---

## Test Contract (Pair A implements these)

### Unit Tests

1. **`test_teammate_identity_persona_field`**: Create a `TeammateIdentity(agent_id="x", agent_name="y", team_name="z", persona="coding")` — assert `.persona == "coding"`.

2. **`test_teammate_identity_persona_default_none`**: Create without persona — assert `.persona is None`.

3. **`test_swarm_create_team_with_persona`**: `TeamManager().create_team("proj", "leader", leader_persona="chat")` → read back `team.json` → leader member has `persona: "chat"`.

4. **`test_swarm_add_member_with_persona`**: Add member with `persona="coding"` → returned `TeammateIdentity.persona == "coding"` AND `team.json` member dict has `persona: "coding"`.

5. **`test_swarm_add_member_without_persona`**: Add member without persona → `.persona is None` → backward-compat.

6. **`test_swarm_invalid_persona_raises`**: `add_member("team", "name", persona="invalid")` → `ValueError`.

7. **`test_collab_team_member_persona`**: `TeamMember(member_id="x", role=TeamRole.WORKER, persona="fin")` → `.persona == "fin"`.

8. **`test_collab_create_team_with_personas`**: Create team via collaboration_tools `TeamManager` with `personas={"a": "chat", "b": "coding"}` → verify each member has correct persona.

9. **`test_collab_add_member_with_persona`**: `add_member("team", "agent-3", role="worker", persona="fin")` → member has `.persona == "fin"`.

10. **`test_legacy_team_json_loads_without_persona`**: Manually write a `team.json` without persona fields → `get_team()` succeeds → members have `persona=None`.

### Integration Test

11. **`test_mixed_persona_team`**: Create a team with 3 coding + 2 fin + 1 chat leader → verify 6 members, each with correct persona, via both swarm `TeamManager` and collab `TeamManager`.
