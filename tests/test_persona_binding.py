"""
Tests for Phase 1 — Persona ↔ Teammate Binding.

Contract: contracts/persona_fleet/01_teammate_persona.md
Tests both swarm.py (file-based TeamManager) and
collaboration_tools.py (in-memory TeamManager).
"""

import json
import os
import shutil
import tempfile
import pytest

from agent.agentic.swarm import (
    TeammateIdentity,
    TeamManager as SwarmTeamManager,
    VALID_PERSONAS,
)
from agent.tools.collaboration_tools import (
    TeamMember,
    TeamRole,
    TeamManager as CollabTeamManager,
    VALID_PERSONAS as COLLAB_VALID_PERSONAS,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for swarm team storage."""
    d = tempfile.mkdtemp(prefix="neomind_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def swarm_mgr(tmp_dir):
    """SwarmTeamManager with isolated temp directory."""
    return SwarmTeamManager(base_dir=tmp_dir)


@pytest.fixture
def collab_mgr():
    """CollabTeamManager (in-memory)."""
    return CollabTeamManager()


# ── TeammateIdentity dataclass tests ─────────────────────────────────


class TestTeammateIdentityPersona:

    def test_persona_field_set(self):
        """Contract test 1: persona field can be set."""
        t = TeammateIdentity(
            agent_id="x", agent_name="y", team_name="z", persona="coding"
        )
        assert t.persona == "coding"

    def test_persona_default_none(self):
        """Contract test 2: default persona is None (backward compat)."""
        t = TeammateIdentity(agent_id="a", agent_name="b", team_name="c")
        assert t.persona is None

    def test_all_valid_personas(self):
        """All three valid persona values work."""
        for p in ("chat", "coding", "fin"):
            t = TeammateIdentity(
                agent_id="x", agent_name="y", team_name="z", persona=p
            )
            assert t.persona == p

    def test_valid_personas_constant(self):
        """VALID_PERSONAS contains exactly chat, coding, fin."""
        assert VALID_PERSONAS == frozenset({"chat", "coding", "fin"})
        assert COLLAB_VALID_PERSONAS == frozenset({"chat", "coding", "fin"})


# ── Swarm TeamManager tests ─────────────────────────────────────────


class TestSwarmTeamManagerPersona:

    def test_create_team_with_persona(self, swarm_mgr, tmp_dir):
        """Contract test 3: create_team stores leader persona in team.json."""
        team_data = swarm_mgr.create_team("proj", "leader", leader_persona="chat")
        assert team_data["members"][0]["persona"] == "chat"

        # Verify it's persisted to disk
        team_file = os.path.join(tmp_dir, "teams", "proj", "team.json")
        disk_data = json.loads(open(team_file).read())
        assert disk_data["members"][0]["persona"] == "chat"

    def test_create_team_without_persona(self, swarm_mgr):
        """create_team without persona → leader has persona=None."""
        team_data = swarm_mgr.create_team("proj2", "leader")
        assert team_data["members"][0]["persona"] is None

    def test_create_team_invalid_persona_raises(self, swarm_mgr):
        """Contract test (from 6): invalid leader_persona raises ValueError."""
        with pytest.raises(ValueError, match="Invalid persona"):
            swarm_mgr.create_team("proj", "leader", leader_persona="invalid")

    def test_add_member_with_persona(self, swarm_mgr, tmp_dir):
        """Contract test 4: add_member stores persona and returns it."""
        swarm_mgr.create_team("proj", "leader", leader_persona="chat")
        identity = swarm_mgr.add_member("proj", "coder-1", persona="coding")

        assert identity.persona == "coding"
        assert identity.agent_name == "coder-1"
        assert identity.team_name == "proj"

        # Verify in team.json
        team_file = os.path.join(tmp_dir, "teams", "proj", "team.json")
        disk_data = json.loads(open(team_file).read())
        member = [m for m in disk_data["members"] if m["name"] == "coder-1"][0]
        assert member["persona"] == "coding"

    def test_add_member_without_persona(self, swarm_mgr):
        """Contract test 5: add_member without persona → backward compat."""
        swarm_mgr.create_team("proj", "leader")
        identity = swarm_mgr.add_member("proj", "worker-1")
        assert identity.persona is None

    def test_add_member_invalid_persona_raises(self, swarm_mgr):
        """Contract test 6: invalid persona raises ValueError."""
        swarm_mgr.create_team("proj", "leader")
        with pytest.raises(ValueError, match="Invalid persona"):
            swarm_mgr.add_member("proj", "worker-1", persona="invalid")

    def test_legacy_team_json_loads_without_persona(self, swarm_mgr, tmp_dir):
        """Contract test 10: old team.json without persona field loads fine."""
        # Manually write a legacy team.json (no persona fields)
        team_dir = os.path.join(tmp_dir, "teams", "legacy-team")
        os.makedirs(os.path.join(team_dir, "inboxes"), exist_ok=True)
        legacy_data = {
            "name": "legacy-team",
            "leader": "old-leader",
            "members": [
                {"name": "old-leader", "color": "blue", "is_leader": True},
                {"name": "old-worker", "color": "green", "is_leader": False},
            ],
            "created_at": 1000000000.0,
        }
        with open(os.path.join(team_dir, "team.json"), "w") as f:
            json.dump(legacy_data, f)

        # get_team should work and members have persona=None
        team = swarm_mgr.get_team("legacy-team")
        assert team is not None
        for member in team["members"]:
            assert member.get("persona") is None

    def test_mixed_persona_team(self, swarm_mgr):
        """Contract test 11: create a team with 3 coding + 2 fin + 1 chat leader."""
        swarm_mgr.create_team("big-proj", "manager-1", leader_persona="chat")
        swarm_mgr.add_member("big-proj", "coder-1", persona="coding")
        swarm_mgr.add_member("big-proj", "coder-2", persona="coding")
        swarm_mgr.add_member("big-proj", "coder-3", persona="coding")
        swarm_mgr.add_member("big-proj", "quant-1", persona="fin")
        swarm_mgr.add_member("big-proj", "quant-2", persona="fin")

        team = swarm_mgr.get_team("big-proj")
        assert len(team["members"]) == 6

        personas = [m.get("persona") for m in team["members"]]
        assert personas.count("chat") == 1
        assert personas.count("coding") == 3
        assert personas.count("fin") == 2


# ── Collaboration Tools TeamManager tests ────────────────────────────


class TestCollabTeamManagerPersona:

    def test_team_member_persona_field(self):
        """Contract test 7: TeamMember dataclass has persona field."""
        tm = TeamMember(member_id="x", role=TeamRole.WORKER, persona="fin")
        assert tm.persona == "fin"

    def test_team_member_persona_default(self):
        """TeamMember without persona defaults to None."""
        tm = TeamMember(member_id="x", role=TeamRole.WORKER)
        assert tm.persona is None

    def test_create_team_with_personas(self, collab_mgr):
        """Contract test 8: create team with personas mapping."""
        result = collab_mgr.create_team(
            "squad",
            description="Test squad",
            members=["a", "b", "c"],
            roles={"a": "leader", "b": "worker", "c": "worker"},
            personas={"a": "chat", "b": "coding", "c": "fin"},
        )
        assert result.success
        team = result.data
        assert team.members["a"].persona == "chat"
        assert team.members["b"].persona == "coding"
        assert team.members["c"].persona == "fin"

    def test_create_team_without_personas(self, collab_mgr):
        """Backward compat: create team without personas → all None."""
        result = collab_mgr.create_team(
            "squad2",
            members=["a", "b"],
            roles={"a": "leader", "b": "worker"},
        )
        assert result.success
        assert result.data.members["a"].persona is None
        assert result.data.members["b"].persona is None

    def test_create_team_invalid_persona(self, collab_mgr):
        """Invalid persona in create_team → error result."""
        result = collab_mgr.create_team(
            "squad3",
            members=["a"],
            personas={"a": "invalid"},
        )
        assert not result.success
        assert result.error == "invalid_persona"

    def test_add_member_with_persona(self, collab_mgr):
        """Contract test 9: add_member with persona."""
        collab_mgr.create_team("squad", members=["a"], roles={"a": "leader"})
        result = collab_mgr.add_member("squad", "agent-3", role="worker", persona="fin")
        assert result.success
        assert result.data.members["agent-3"].persona == "fin"

    def test_add_member_invalid_persona(self, collab_mgr):
        """add_member with invalid persona → error."""
        collab_mgr.create_team("squad", members=["a"], roles={"a": "leader"})
        result = collab_mgr.add_member(
            "squad", "agent-3", role="worker", persona="bad"
        )
        assert not result.success
        assert result.error == "invalid_persona"

    def test_add_member_without_persona(self, collab_mgr):
        """add_member without persona → backward compat."""
        collab_mgr.create_team("squad", members=["a"], roles={"a": "leader"})
        result = collab_mgr.add_member("squad", "agent-3")
        assert result.success
        assert result.data.members["agent-3"].persona is None

    def test_mixed_persona_team_collab(self, collab_mgr):
        """Contract test 11 (collab version): mixed persona team."""
        result = collab_mgr.create_team(
            "big-squad",
            members=["mgr", "c1", "c2", "c3", "f1", "f2"],
            roles={
                "mgr": "leader",
                "c1": "worker", "c2": "worker", "c3": "worker",
                "f1": "worker", "f2": "worker",
            },
            personas={
                "mgr": "chat",
                "c1": "coding", "c2": "coding", "c3": "coding",
                "f1": "fin", "f2": "fin",
            },
        )
        assert result.success
        team = result.data
        assert len(team.members) == 6

        persona_counts = {}
        for m in team.members.values():
            p = m.persona or "none"
            persona_counts[p] = persona_counts.get(p, 0) + 1
        assert persona_counts == {"chat": 1, "coding": 3, "fin": 2}
