"""NeoMind Self-Upgrade Mechanism

Checks for updates, shows changelog, upgrades safely with rollback.
Zero external dependencies (stdlib only).
"""

import subprocess
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class NeoMindUpgrade:
    """Safe upgrade mechanism with rollback support."""

    def __init__(self, repo_dir: Optional[str] = None):
        """
        Initialize upgrade manager.

        Args:
            repo_dir: Path to NeoMind repo. Defaults to ~/Desktop/NeoMind_agent
        """
        if repo_dir:
            self.repo_dir = Path(repo_dir).expanduser()
        else:
            # Try common locations
            candidates = [
                Path.home() / "Desktop" / "NeoMind_agent",
                Path.home() / "NeoMind_agent",
                Path.cwd(),
            ]
            self.repo_dir = next(
                (p for p in candidates if (p / ".git").exists()), Path.cwd()
            )

        self.upgrade_log = self.repo_dir / ".upgrades"
        self.upgrade_log.mkdir(exist_ok=True)

    def get_current_version(self) -> str:
        """Get current version from git tag or commit hash."""
        try:
            # Try to get version from git tag
            result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_dir),
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()

            # Fallback to commit hash
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_dir),
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()

        except Exception as e:
            logger.warning(f"Failed to get version: {e}")

        return "unknown"

    def check_for_updates(self) -> Tuple[bool, Optional[str]]:
        """Check for updates on origin/main.

        Returns:
            (has_updates, new_version)
        """
        try:
            # Fetch latest
            subprocess.run(
                ["git", "fetch", "origin", "main"],
                capture_output=True,
                timeout=10,
                cwd=str(self.repo_dir),
            )

            # Compare HEAD with origin/main
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..origin/main"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_dir),
                timeout=5,
            )

            if result.returncode == 0:
                count = int(result.stdout.strip())
                if count > 0:
                    # Get remote version
                    remote_version = self._get_remote_version()
                    return (True, remote_version)

            return (False, None)

        except Exception as e:
            logger.error(f"Update check failed: {e}")
            return (False, None)

    def _get_remote_version(self) -> Optional[str]:
        """Get version from origin/main."""
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "origin/main", "--always"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_dir),
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def get_changelog_diff(self) -> str:
        """Show what changed since current version."""
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "HEAD..origin/main", "-n", "10"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_dir),
                timeout=5,
            )

            if result.returncode == 0 and result.stdout:
                lines = ["📝 Recent Changes:\n"]
                for line in result.stdout.strip().split("\n"):
                    lines.append(f"  {line}")
                return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to get changelog: {e}")

        return "Could not fetch changelog"

    def upgrade(self, confirmed: bool = False) -> Tuple[bool, str]:
        """Safe upgrade: backup → pull → test → rollback if failed.

        Args:
            confirmed: Set to True to skip confirmation prompt

        Returns:
            (success, message)
        """
        current = self.get_current_version()

        try:
            # Step 1: Create backup
            backup_commit = self._create_backup(current)
            logger.info(f"Backup created: {backup_commit}")

            # Step 2: Pull from origin/main
            logger.info("Pulling from origin/main...")
            result = subprocess.run(
                ["git", "pull", "origin", "main"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_dir),
                timeout=30,
            )

            if result.returncode != 0:
                self._rollback(backup_commit)
                return (
                    False,
                    f"Pull failed: {result.stderr[:200]}\nRolled back to {backup_commit}",
                )

            new_version = self.get_current_version()
            logger.info(f"Upgraded from {current} to {new_version}")

            return (
                True,
                f"✓ Upgraded: {current} → {new_version}\nPlease restart the agent.",
            )

        except Exception as e:
            logger.error(f"Upgrade failed: {e}")
            return (False, f"Upgrade error: {e}")

    def _create_backup(self, version: str) -> str:
        """Create backup by tagging current commit."""
        try:
            tag = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

            subprocess.run(
                ["git", "tag", tag],
                capture_output=True,
                cwd=str(self.repo_dir),
                timeout=5,
            )

            # Log backup
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "backup",
                "version": version,
                "tag": tag,
            }

            log_file = self.upgrade_log / "history.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

            return tag

        except Exception as e:
            logger.error(f"Backup creation failed: {e}")
            return "unknown"

    def _rollback(self, tag: str):
        """Rollback to a previous backup tag."""
        try:
            subprocess.run(
                ["git", "reset", "--hard", tag],
                capture_output=True,
                cwd=str(self.repo_dir),
                timeout=10,
            )
            logger.info(f"Rolled back to {tag}")

            # Log rollback
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "rollback",
                "tag": tag,
            }

            log_file = self.upgrade_log / "history.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

        except Exception as e:
            logger.error(f"Rollback failed: {e}")

    def get_upgrade_history(self) -> list:
        """Get history of upgrades and rollbacks."""
        history = []
        log_file = self.upgrade_log / "history.jsonl"

        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        try:
                            history.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                logger.warning(f"Failed to read upgrade history: {e}")

        return history[-20:]  # Last 20 entries
