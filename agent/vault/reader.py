"""VaultReader — Reads vault files and produces context for system prompt injection.

Reads MEMORY.md, current-goals.md, and yesterday's journal at startup.
Strips YAML frontmatter before injecting (frontmatter is for Obsidian Bases).
Truncates to token budget to avoid blowing up the context window.

Usage:
    reader = VaultReader(vault_dir="/data/vault")
    context = reader.get_startup_context(mode="fin")
    # → returns string to append to system prompt

Troubleshooting: plans/OBSIDIAN_TROUBLESHOOTING.md (OV-010 through OV-013)
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List

from agent.vault._config import get_vault_dir

logger = logging.getLogger(__name__)


class VaultReader:
    """Reads vault markdown files for system prompt injection."""

    def __init__(self, vault_dir: str = None):
        if vault_dir is None:
            vault_dir = get_vault_dir()
        self.vault_dir = Path(vault_dir)

    def get_startup_context(self, mode: str = "chat", max_tokens: int = 1500) -> str:
        """Read vault files and return context string for system prompt.

        Reads (in priority order):
        1. MEMORY.md — curated long-term knowledge
        2. current-goals.md — active improvement targets
        3. journal/yesterday.md — yesterday's execution log

        Args:
            mode: Current personality mode (chat/coding/fin)
            max_tokens: Approximate token budget (1 token ~ 4 chars)

        Returns:
            Formatted context string, or empty string if vault doesn't exist.
        """
        if not self.vault_dir.is_dir():
            logger.info(f"Vault dir not found: {self.vault_dir}")
            return ""

        sections = []
        char_budget = max_tokens * 4  # rough token-to-char conversion

        # 1. MEMORY.md (highest priority)
        memory = self._read_file_body("MEMORY.md")
        if memory:
            sections.append(f"## Long-Term Memory\n{memory}")

        # 2. current-goals.md
        goals = self._read_file_body("current-goals.md")
        if goals:
            sections.append(f"## Current Improvement Targets\n{goals}")

        # 3. Yesterday's journal
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        journal = self._read_file_body(f"journal/{yesterday}.md")
        if journal:
            sections.append(f"## Yesterday's Journal ({yesterday})\n{journal}")

        if not sections:
            return ""

        # Combine and truncate to budget
        combined = "\n\n---\n\n".join(sections)
        if len(combined) > char_budget:
            combined = combined[:char_budget] + "\n\n[... truncated for token budget]"

        return f"\n\n# Vault Context (from NeoMind's persistent memory)\n\n{combined}"

    def _read_file_body(self, relative_path: str) -> str:
        """Read a file from the vault, strip YAML frontmatter, return body.

        Returns empty string if file doesn't exist or can't be read.
        """
        filepath = self.vault_dir / relative_path
        try:
            if filepath.is_file():
                content = filepath.read_text(encoding="utf-8").strip()
                if not content:
                    return ""
                # Strip YAML frontmatter for injection
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
                return content
        except Exception as e:
            logger.warning(f"Failed to read vault file {relative_path}: {e}")
        return ""

    def read_raw(self, relative_path: str) -> str:
        """Read raw file content including frontmatter.

        Useful for processing that needs YAML metadata (e.g., retro analysis).
        """
        filepath = self.vault_dir / relative_path
        try:
            if filepath.is_file():
                return filepath.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read {relative_path}: {e}")
        return ""

    def list_journal_entries(self, days: int = 7) -> List[str]:
        """List recent journal entry filenames, sorted newest first."""
        journal_dir = self.vault_dir / "journal"
        if not journal_dir.is_dir():
            return []
        entries = sorted(journal_dir.glob("*.md"), reverse=True)
        return [e.name for e in entries[:days]]

    def read_journal_entries(self, days: int = 7) -> List[dict]:
        """Read recent journal entries with metadata.

        Returns list of dicts with 'filename', 'raw', 'body' keys.
        """
        results = []
        for filename in self.list_journal_entries(days):
            raw = self.read_raw(f"journal/{filename}")
            body = self._read_file_body(f"journal/{filename}")
            if raw:
                results.append({
                    "filename": filename,
                    "raw": raw,
                    "body": body,
                })
        return results

    def read_last_retro(self) -> Optional[str]:
        """Read the most recent retro file body."""
        retros_dir = self.vault_dir / "retros"
        if not retros_dir.is_dir():
            return None
        retros = sorted(retros_dir.glob("retro-*.md"), reverse=True)
        if not retros:
            return None
        return self._read_file_body(f"retros/{retros[0].name}")

    def vault_exists(self) -> bool:
        """Check if vault directory exists and has been initialized."""
        return self.vault_dir.is_dir() and (self.vault_dir / "MEMORY.md").is_file()
