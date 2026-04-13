"""
Tests for Phase 2 — Project = Team Alias.

Contract: contracts/persona_fleet/02_project_alias.md
"""

import os
import shutil
import tempfile
import pytest

from fleet.project_config import (
    create_project,
    add_project_member,
    get_project,
    delete_project,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="neomind_test_proj_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestProjectAlias:

    def test_create_project(self, tmp_dir):
        """Contract test 1: create_project creates a team with correct leader persona."""
        data = create_project("my-proj", "leader-1", "chat", base_dir=tmp_dir)
        assert data["name"] == "my-proj"
        assert data["leader"] == "leader-1"
        assert data["members"][0]["persona"] == "chat"
        assert data["members"][0]["is_leader"] is True

    def test_create_project_invalid_persona(self, tmp_dir):
        """Contract test 2: invalid persona raises ValueError."""
        with pytest.raises(ValueError, match="Invalid persona"):
            create_project("x", "y", "invalid", base_dir=tmp_dir)

    def test_create_project_empty_id(self, tmp_dir):
        """Empty project_id raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            create_project("", "leader", "chat", base_dir=tmp_dir)

    def test_add_project_member(self, tmp_dir):
        """Contract test 3: add_project_member stores persona."""
        create_project("my-proj", "leader-1", "chat", base_dir=tmp_dir)
        identity = add_project_member(
            "my-proj", "coder-1", "coding", base_dir=tmp_dir
        )
        assert identity.persona == "coding"
        assert identity.agent_name == "coder-1"

    def test_add_project_member_invalid_persona(self, tmp_dir):
        """Invalid persona in add_project_member raises ValueError."""
        create_project("my-proj", "leader-1", "chat", base_dir=tmp_dir)
        with pytest.raises(ValueError, match="Invalid persona"):
            add_project_member("my-proj", "x", "bad", base_dir=tmp_dir)

    def test_add_project_member_invalid_role(self, tmp_dir):
        """Invalid role in add_project_member raises ValueError."""
        create_project("my-proj", "leader-1", "chat", base_dir=tmp_dir)
        with pytest.raises(ValueError, match="Invalid role"):
            add_project_member(
                "my-proj", "x", "coding", role="invalid", base_dir=tmp_dir
            )

    def test_get_project(self, tmp_dir):
        """Contract test 4: get_project returns team data."""
        create_project("my-proj", "leader-1", "chat", base_dir=tmp_dir)
        add_project_member("my-proj", "coder-1", "coding", base_dir=tmp_dir)
        data = get_project("my-proj", base_dir=tmp_dir)
        assert data is not None
        assert data["name"] == "my-proj"
        assert len(data["members"]) == 2

    def test_get_project_nonexistent(self, tmp_dir):
        """Contract test 5: nonexistent project returns None."""
        assert get_project("nonexistent", base_dir=tmp_dir) is None

    def test_delete_project(self, tmp_dir):
        """Contract test 6: delete removes the project."""
        create_project("my-proj", "leader-1", "chat", base_dir=tmp_dir)
        delete_project("my-proj", base_dir=tmp_dir)
        assert get_project("my-proj", base_dir=tmp_dir) is None

    def test_project_is_team(self, tmp_dir):
        """Contract test 7: project maps to team files on disk."""
        create_project("my-proj", "leader-1", "chat", base_dir=tmp_dir)
        team_file = os.path.join(tmp_dir, "teams", "my-proj", "team.json")
        assert os.path.exists(team_file)
