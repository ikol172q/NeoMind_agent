"""Lightweight polling-based vault file watcher for bidirectional sync with Obsidian.

Tracks mtime of key vault files (MEMORY.md, current-goals.md, SOUL.md).
When a change is detected (e.g., user edits in Obsidian), returns the updated
content for re-injection into the system prompt.

No external dependencies — uses os.stat() for mtime checks.
Designed to be called periodically (e.g., every 50 conversation turns
or at session checkpoints).

Usage:
    watcher = VaultWatcher(vault_dir="/data/vault")
    changed_context = watcher.get_changed_context(mode="chat")
    if changed_context:
        agent.add_to_history("system", changed_context)
        watcher.mark_seen()
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict

from agent.vault._config import get_vault_dir
from agent.vault.reader import VaultReader

logger = logging.getLogger(__name__)


class VaultWatcher:
    """Lightweight polling-based vault file watcher.

    Tracks mtime of key vault files. When a change is detected,
    returns the updated content for re-injection into the system prompt.
    """

    # Files to watch for changes
    WATCHED_FILES = [
        "MEMORY.md",
        "current-goals.md",
        "SOUL.md",
    ]

    def __init__(self, vault_dir: str = None):
        """Initialize watcher with initial mtimes.

        Args:
            vault_dir: Path to vault directory. Uses get_vault_dir() if None.
        """
        if vault_dir is None:
            vault_dir = get_vault_dir()
        self.vault_dir = Path(vault_dir)
        self.reader = VaultReader(vault_dir)

        # Store initial mtimes
        self._stored_mtimes = {}
        self._update_stored_mtimes()

    def _update_stored_mtimes(self) -> None:
        """Update stored mtimes to current filesystem values."""
        for filename in self.WATCHED_FILES:
            filepath = self.vault_dir / filename
            try:
                if filepath.is_file():
                    mtime = os.path.getmtime(filepath)
                    self._stored_mtimes[filename] = mtime
                else:
                    self._stored_mtimes[filename] = None
            except Exception as e:
                logger.warning(f"Failed to get mtime for {filename}: {e}")
                self._stored_mtimes[filename] = None

    def check_for_changes(self) -> Optional[Dict[str, str]]:
        """Check for file changes and return changed content.

        Returns:
            Dict mapping filename to new content for changed files,
            or None if no changes detected.
        """
        changed_files = {}

        for filename in self.WATCHED_FILES:
            filepath = self.vault_dir / filename
            try:
                if not filepath.is_file():
                    # File doesn't exist or was deleted
                    if self._stored_mtimes.get(filename) is not None:
                        changed_files[filename] = None  # Marked as deleted
                    continue

                current_mtime = os.path.getmtime(filepath)
                stored_mtime = self._stored_mtimes.get(filename)

                # Check if mtime has changed
                if stored_mtime is None or current_mtime != stored_mtime:
                    # File is new or modified
                    content = filepath.read_text(encoding="utf-8")
                    changed_files[filename] = content
            except Exception as e:
                logger.warning(f"Failed to check {filename}: {e}")

        return changed_files if changed_files else None

    def get_changed_context(self, mode: str = "chat") -> Optional[str]:
        """Get formatted context string for changed files.

        If changes detected, uses VaultReader to format content.
        Returns None if no changes.

        Args:
            mode: Current personality mode (chat/coding/fin)

        Returns:
            Formatted context string for re-injection, or None if no changes.
        """
        changed = self.check_for_changes()
        if not changed:
            return None

        # Format changed files as a system message
        sections = []
        for filename, content in changed.items():
            if content is None:
                continue  # Skip deleted files

            # Strip YAML frontmatter if present
            body = content
            if body.startswith("---"):
                parts = body.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2].strip()

            # Human-readable section title
            if filename == "MEMORY.md":
                title = "Long-Term Memory"
            elif filename == "current-goals.md":
                title = "Current Improvement Targets"
            elif filename == "SOUL.md":
                title = "Identity and Personality"
            else:
                title = filename

            sections.append(f"## {title}\n{body}")

        if not sections:
            return None

        combined = "\n\n---\n\n".join(sections)
        return (
            f"\n\n# Updated Vault Context (changes detected in Obsidian)\n\n{combined}"
        )

    def mark_seen(self) -> None:
        """Update stored mtimes to current filesystem values.

        Call this after re-injecting changed context so changes
        are no longer detected on the next check.
        """
        self._update_stored_mtimes()
        logger.debug("Vault watcher updated stored mtimes")
