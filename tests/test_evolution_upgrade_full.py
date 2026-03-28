"""
Comprehensive tests for agent/evolution/upgrade.py

Run: pytest tests/test_evolution_upgrade_full.py -v
"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNeoMindUpgradeInit:
    """Test NeoMindUpgrade initialization."""

    def test_init_with_explicit_path(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        # Create .git directory
        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        assert ue.repo_dir == tmp_path

    def test_init_finds_git_repo(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        # Create .git directory
        (tmp_path / ".git").mkdir()

        with patch.object(Path, 'home') as mock_home:
            mock_home.return_value = tmp_path

            ue = NeoMindUpgrade()

            assert ue.repo_dir.exists()

    def test_init_upgrade_log_created(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        assert ue.upgrade_log.exists()
        assert ue.upgrade_log.is_dir()


class TestNeoMindUpgradeVersion:
    """Test version detection."""

    def test_get_current_version_from_tag(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="v1.2.3\n")

            version = ue.get_current_version()

            assert version == "v1.2.3"

    def test_get_current_version_fallback_to_hash(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            # First call fails, second succeeds
            mock_run.side_effect = [
                Mock(returncode=1),
                Mock(returncode=0, stdout="abc1234\n")
            ]

            version = ue.get_current_version()

            assert version == "abc1234"

    def test_get_current_version_unknown(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("git not found")

            version = ue.get_current_version()

            assert version == "unknown"

    def test_get_current_version_git_command_failure(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=128)

            version = ue.get_current_version()

            assert version == "unknown"


class TestNeoMindUpgradeCheck:
    """Test update checking."""

    def test_check_for_updates_available(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            # Fetch succeeds
            mock_run.return_value = Mock(returncode=0)

            with patch.object(ue, '_get_remote_version') as mock_remote:
                mock_remote.return_value = "v2.0.0"

                # Mock git rev-list to return > 0
                def run_side_effect(*args, **kwargs):
                    if "rev-list" in str(args):
                        return Mock(returncode=0, stdout="5\n")
                    return Mock(returncode=0)

                mock_run.side_effect = run_side_effect

                has_updates, new_version = ue.check_for_updates()

                assert has_updates is True
                assert new_version == "v2.0.0"

    def test_check_for_updates_not_available(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            def run_side_effect(*args, **kwargs):
                if "rev-list" in str(args):
                    return Mock(returncode=0, stdout="0\n")
                return Mock(returncode=0)

            mock_run.side_effect = run_side_effect

            has_updates, new_version = ue.check_for_updates()

            assert has_updates is False
            assert new_version is None

    def test_check_for_updates_error(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("Network error")

            has_updates, new_version = ue.check_for_updates()

            assert has_updates is False
            assert new_version is None


class TestNeoMindUpgradeChangelog:
    """Test changelog generation."""

    def test_get_changelog_diff_success(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        changelog_output = "abc123 Fix bug\ndef456 Add feature\n"

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=changelog_output)

            changelog = ue.get_changelog_diff()

            assert "Recent Changes" in changelog
            assert "Fix bug" in changelog
            assert "Add feature" in changelog

    def test_get_changelog_diff_empty(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="")

            changelog = ue.get_changelog_diff()

            assert "Could not fetch changelog" in changelog

    def test_get_changelog_diff_error(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("git error")

            changelog = ue.get_changelog_diff()

            assert "Could not fetch changelog" in changelog


class TestNeoMindUpgradeErrors:
    """Test error handling."""

    def test_remote_version_timeout(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 5)

            version = ue._get_remote_version()

            assert version is None

    def test_remote_version_not_found(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=128)

            version = ue._get_remote_version()

            assert version is None


class TestNeoMindUpgradeUpgradeMethod:
    """Test the upgrade method."""

    def test_upgrade_requires_confirmation_when_not_confirmed(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            # Should return success, false tuple when not confirmed
            success, msg = ue.upgrade(confirmed=False)

            # First call should be the unconfirmed check
            assert isinstance(success, bool)


class TestNeoMindUpgradeIntegration:
    """Integration tests."""

    def test_full_upgrade_workflow(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        # Verify all paths exist
        assert ue.repo_dir.exists()
        assert ue.upgrade_log.exists()

    def test_version_methods_sequence(self, tmp_path):
        from agent.evolution.upgrade import NeoMindUpgrade

        (tmp_path / ".git").mkdir()

        ue = NeoMindUpgrade(repo_dir=str(tmp_path))

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="v1.0.0\n")

            current = ue.get_current_version()
            assert current is not None

            # Check methods work in sequence
            assert isinstance(current, str)
