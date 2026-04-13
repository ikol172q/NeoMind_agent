"""
Tests for Phase 5 — Fleet Launcher + Project Schema.

Contract: contracts/persona_fleet/05_fleet_launcher.md
"""

import asyncio
import json
import os
import shutil
import tempfile
import pytest

from fleet.project_schema import (
    MemberConfig,
    ProjectConfig,
    validate_project_config,
    load_project_config,
)
from fleet.launch_project import FleetLauncher


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="neomind_test_fleet_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_valid_config() -> ProjectConfig:
    return ProjectConfig(
        project_id="test-proj",
        description="Test project",
        leader="mgr",
        members=[
            MemberConfig(name="mgr", persona="chat", role="leader"),
            MemberConfig(name="c1", persona="coding", role="worker"),
            MemberConfig(name="f1", persona="fin", role="worker"),
        ],
    )


# ── ProjectConfig validation tests ──────────────────────────────────


class TestProjectConfigValidation:

    def test_valid_config(self):
        """Contract test 5: valid config → empty error list."""
        config = _make_valid_config()
        errors = validate_project_config(config)
        assert errors == []

    def test_missing_leader_role(self):
        """Contract test 6: no leader → error."""
        config = ProjectConfig(
            project_id="x",
            description="",
            leader="mgr",
            members=[
                MemberConfig(name="mgr", persona="chat", role="worker"),
            ],
        )
        errors = validate_project_config(config)
        assert any("leader" in e.lower() for e in errors)

    def test_invalid_persona(self):
        """Contract test 4: invalid persona → error."""
        config = ProjectConfig(
            project_id="x",
            description="",
            leader="mgr",
            members=[
                MemberConfig(name="mgr", persona="chat", role="leader"),
                MemberConfig(name="bad", persona="invalid", role="worker"),
            ],
        )
        errors = validate_project_config(config)
        assert any("invalid" in e.lower() for e in errors)

    def test_duplicate_names(self):
        """Contract test 3: duplicate member names → error."""
        config = ProjectConfig(
            project_id="x",
            description="",
            leader="mgr",
            members=[
                MemberConfig(name="mgr", persona="chat", role="leader"),
                MemberConfig(name="mgr", persona="coding", role="worker"),
            ],
        )
        errors = validate_project_config(config)
        assert any("duplicate" in e.lower() for e in errors)

    def test_empty_project_id(self):
        """Empty project_id → error."""
        config = ProjectConfig(
            project_id="",
            description="",
            leader="mgr",
            members=[
                MemberConfig(name="mgr", persona="chat", role="leader"),
            ],
        )
        errors = validate_project_config(config)
        assert any("empty" in e.lower() for e in errors)

    def test_leader_not_in_members(self):
        """Leader name not in members → error."""
        config = ProjectConfig(
            project_id="x",
            description="",
            leader="ghost",
            members=[
                MemberConfig(name="mgr", persona="chat", role="leader"),
            ],
        )
        errors = validate_project_config(config)
        assert any("ghost" in e for e in errors)


class TestLoadProjectConfig:

    def test_load_valid_json(self, tmp_dir):
        """Contract test 1: load a valid project config from JSON."""
        config_path = os.path.join(tmp_dir, "project.json")
        data = {
            "project_id": "my-proj",
            "description": "Test",
            "leader": "mgr",
            "members": [
                {"name": "mgr", "persona": "chat", "role": "leader"},
                {"name": "c1", "persona": "coding", "role": "worker"},
            ],
        }
        with open(config_path, "w") as f:
            json.dump(data, f)

        config = load_project_config(config_path)
        assert config.project_id == "my-proj"
        assert len(config.members) == 2
        assert config.members[0].persona == "chat"

    def test_load_missing_file(self, tmp_dir):
        """Contract test 2: missing file → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_project_config(os.path.join(tmp_dir, "nope.json"))

    def test_load_invalid_config(self, tmp_dir):
        """Invalid config → ValueError."""
        config_path = os.path.join(tmp_dir, "bad.json")
        with open(config_path, "w") as f:
            json.dump({"project_id": "", "leader": "x", "members": []}, f)
        with pytest.raises(ValueError):
            load_project_config(config_path)


# ── FleetLauncher tests ─────────────────────────────────────────────


class TestFleetLauncher:

    def test_launcher_init(self, tmp_dir):
        """Contract test 7: FleetLauncher init with valid config."""
        config = _make_valid_config()
        launcher = FleetLauncher(config, base_dir=tmp_dir)
        assert launcher.config.project_id == "test-proj"

    @pytest.mark.asyncio
    async def test_fleet_start_stop(self, tmp_dir):
        """Contract test 8: start and stop a fleet cleanly."""
        config = _make_valid_config()
        launcher = FleetLauncher(config, base_dir=tmp_dir)

        await launcher.start()
        status = launcher.get_status()
        assert status["running"] is True
        assert len(status["members"]) == 3

        # All members should be running
        for name, info in status["members"].items():
            assert info["status"] == "running"

        await launcher.stop(timeout=5.0)
        assert launcher._running is False

    @pytest.mark.asyncio
    async def test_fleet_submit_task(self, tmp_dir):
        """Contract test 9: submit a task to the fleet."""
        config = _make_valid_config()
        launcher = FleetLauncher(config, base_dir=tmp_dir)

        await launcher.start()
        task_id = await launcher.submit_task("build feature X")
        assert task_id.startswith("task_")

        # Give workers a moment to claim
        await asyncio.sleep(1.0)

        status = launcher.get_status()
        # Task should have been claimed by a worker
        total_tasks = sum(status["tasks"].values())
        assert total_tasks >= 1

        await launcher.stop(timeout=5.0)

    @pytest.mark.asyncio
    async def test_fleet_instance_isolation(self, tmp_dir):
        """Contract test 10: each instance has its own persona context."""
        config = _make_valid_config()
        launcher = FleetLauncher(config, base_dir=tmp_dir)

        await launcher.start()

        # Check that team was created with correct personas
        from agent.agentic.swarm import TeamManager
        mgr = TeamManager(base_dir=tmp_dir)
        team = mgr.get_team("test-proj")
        assert team is not None

        personas = {m["name"]: m.get("persona") for m in team["members"]}
        assert personas["mgr"] == "chat"
        assert personas["c1"] == "coding"
        assert personas["f1"] == "fin"

        await launcher.stop(timeout=5.0)
