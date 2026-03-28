"""VaultWriter — Writes structured markdown files to the vault.

All files use YAML frontmatter for Obsidian Bases queryability.
Uses [[wikilinks]] for Obsidian graph view connections.
Graceful degradation: if vault dir doesn't exist, all writes are no-ops.

Troubleshooting: plans/OBSIDIAN_TROUBLESHOOTING.md (OV-020 through OV-022)
"""

import logging
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

from agent.vault._config import get_vault_dir

logger = logging.getLogger(__name__)

# Common English words to exclude from wikification
COMMON_WORDS = {
    "THE", "AND", "FOR", "NOT", "ARE", "WAS", "HAS", "HAVE", "THIS", "THAT",
    "WITH", "FROM", "TO", "BY", "ON", "IN", "IS", "BE", "AS", "AT", "OR",
    "AN", "A", "BEEN", "BUT", "CAN", "HAD", "THEM", "THAN", "THEN", "WHAT",
    "WHEN", "WHERE", "WHO", "WHICH", "WHY", "HOW", "ITS", "IF", "DO", "DOES",
    "DID", "GET", "GOES", "MADE", "MAKE", "SOME", "SUCH", "OUR", "OUT", "ABOUT",
}


class VaultWriter:
    """Writes structured markdown to the vault."""

    def __init__(self, vault_dir: str = None):
        self.vault_dir = Path(vault_dir) if vault_dir else Path(get_vault_dir())

    # ── Wikilinks ────────────────────────────────────────────────────────

    def _wikify(self, text: str) -> str:
        """Convert recognized entities to Obsidian [[wikilinks]].

        Converts:
        - Stock tickers ($AAPL) to [[$AAPL]]
        - 6-digit Chinese stock codes (600519) to [[600519]]

        Does not wikify:
        - Content inside code blocks (``` ... ```)
        - Content inside existing wikilinks ([[...]])
        - Common English words (THE, AND, FOR, etc.)
        """
        # Protect code blocks
        code_blocks = []
        def preserve_code(match):
            code_blocks.append(match.group(0))
            return f"__CODE_BLOCK_{len(code_blocks) - 1}__"

        text = re.sub(r"```[\s\S]*?```", preserve_code, text)

        # Protect existing wikilinks
        wikilinks = []
        def preserve_wikilink(match):
            wikilinks.append(match.group(0))
            return f"__WIKILINK_{len(wikilinks) - 1}__"

        text = re.sub(r"\[\[.*?\]\]", preserve_wikilink, text)

        # Wikify stock tickers: $AAPL, $BRK, etc. (1-5 uppercase letters)
        def wikify_ticker(match):
            ticker = match.group(0)
            # Don't wikify if already in wikilink format
            if ticker.startswith("[["):
                return ticker
            return f"[[{ticker}]]"

        text = re.sub(r"\$[A-Z]{1,5}\b", wikify_ticker, text)

        # Wikify 6-digit Chinese stock codes (600519, 000858, etc.)
        # Pattern: 6 digits that aren't already inside wikilinks
        def wikify_chinese_stock(match):
            code = match.group(0)
            if code.startswith("[["):
                return code
            return f"[[{code}]]"

        text = re.sub(r"\b([0-9]{6})\b", wikify_chinese_stock, text)

        # Restore code blocks
        for i, block in enumerate(code_blocks):
            text = text.replace(f"__CODE_BLOCK_{i}__", block)

        # Restore wikilinks
        for i, link in enumerate(wikilinks):
            text = text.replace(f"__WIKILINK_{i}__", link)

        return text

    def _wikify_learnings(self, learnings: List[str]) -> List[str]:
        """Apply wikification to each learning string.

        Args:
            learnings: List of learning strings

        Returns:
            List of wikified learning strings
        """
        return [self._wikify(learning) for learning in learnings]

    # ── Structure ────────────────────────────────────────────────────────

    def ensure_structure(self):
        """Create vault folder structure if it doesn't exist."""
        try:
            for subdir in ["journal", "retros", "learnings", "research"]:
                (self.vault_dir / subdir).mkdir(parents=True, exist_ok=True)

            # Create root files if missing
            if not (self.vault_dir / "MEMORY.md").exists():
                self._write_initial_memory()
            if not (self.vault_dir / "current-goals.md").exists():
                self._write_initial_goals()
            if not (self.vault_dir / "SOUL.md").exists():
                self._write_initial_soul()
            if not (self.vault_dir / ".gitignore").exists():
                (self.vault_dir / ".gitignore").write_text(
                    "# Obsidian local config (not versioned)\n.obsidian/\n",
                    encoding="utf-8",
                )
        except Exception as e:
            logger.warning(f"Failed to ensure vault structure: {e}")

    # ── Journal ──────────────────────────────────────────────────────────

    def write_journal_entry(
        self,
        mode: str,
        tasks: List[Dict[str, Any]],
        errors: List[str],
        learnings: List[str],
        tools_used: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        user_satisfaction: str = "neutral",
        tokens_used: int = 0,
        session_duration_min: int = 0,
    ) -> str:
        """Write a daily journal entry with YAML frontmatter.

        If a file for today already exists, appends a new session section.

        Returns the relative path of the written file, or "" on failure.
        """
        self.ensure_structure()
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.vault_dir / "journal" / f"{today}.md"

        tasks_completed = len([t for t in tasks if t.get("status") != "failed"])
        tasks_failed = len([t for t in tasks if t.get("status") == "failed"])

        try:
            if filepath.exists():
                # Append new session
                existing = filepath.read_text(encoding="utf-8")
                session_time = datetime.now().strftime("%H:%M")
                body = self._format_journal_body(tasks, errors, learnings)
                body = self._wikify(body)
                content = existing + f"\n\n---\n\n## Session {session_time}\n\n{body}\n"
            else:
                # New file with frontmatter
                fm = self._build_frontmatter({
                    "type": "journal",
                    "date": today,
                    "mode": mode,
                    "tasks_completed": tasks_completed,
                    "tasks_failed": tasks_failed,
                    "errors": len(errors),
                    "user_satisfaction": user_satisfaction,
                    "tools_used": tools_used or [],
                    "tags": tags or [],
                    "tokens_used": tokens_used,
                    "session_duration_min": session_duration_min,
                })
                body = self._format_journal_body(tasks, errors, learnings)
                body = self._wikify(body)
                content = f"{fm}\n# Journal — {today}\n\n{body}\n"

            filepath.write_text(content, encoding="utf-8")
            logger.info(f"Wrote journal entry: {filepath}")
            return f"journal/{today}.md"

        except Exception as e:
            logger.warning(f"Failed to write journal entry: {e}")
            return ""

    def _format_journal_body(
        self, tasks: List[Dict], errors: List[str], learnings: List[str]
    ) -> str:
        """Format the markdown body of a journal entry."""
        lines = []

        lines.append("## Tasks")
        if tasks:
            for i, task in enumerate(tasks, 1):
                status = "✅" if task.get("status") != "failed" else "❌"
                desc = task.get("description", "unknown task")
                lines.append(f"{i}. {status} {desc}")
        else:
            lines.append("(no tasks recorded)")

        if errors:
            lines.append("\n## Errors")
            for err in errors:
                lines.append(f"- {err}")

        if learnings:
            lines.append("\n## Learnings")
            for learning in learnings:
                lines.append(f"- {learning}")

        return "\n".join(lines)

    # ── Goals ────────────────────────────────────────────────────────────

    def write_goals(self, improvements: List[Dict[str, str]]):
        """Write current-goals.md (overwritten each week by retro).

        Args:
            improvements: list of dicts with keys:
                goal, current, target, metric, action, timeline
        """
        self.ensure_structure()
        today = datetime.now().strftime("%Y-%m-%d")

        fm = self._build_frontmatter({
            "type": "goals",
            "generated_by": "weekly_retro",
            "date": today,
        })

        lines = [fm, "# Current Improvement Targets\n"]

        if not improvements:
            lines.append("No targets generated this week (insufficient data).\n")
        else:
            for i, imp in enumerate(improvements, 1):
                lines.append(f"## {i}. {imp.get('goal', 'Goal')}")
                lines.append(f"- **Current:** {imp.get('current', '...')}")
                lines.append(f"- **Target:** {imp.get('target', '...')}")
                lines.append(f"- **Metric:** {imp.get('metric', '...')}")
                lines.append(f"- **Action:** {imp.get('action', '...')}")
                lines.append(f"- **Timeline:** {imp.get('timeline', '1 week')}")
                lines.append("")

        filepath = self.vault_dir / "current-goals.md"
        try:
            filepath.write_text("\n".join(lines), encoding="utf-8")
            logger.info(f"Wrote goals: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to write goals: {e}")

    # ── Memory ───────────────────────────────────────────────────────────

    def append_to_memory(self, section: str, entry: str):
        """Append a validated learning to MEMORY.md under a section heading.

        Only call this for patterns with 3+ occurrences (see promoter.py).
        Deduplicates: won't add if entry text already exists in the file.
        Wikifies the entry text for stock tickers and codes.
        """
        self.ensure_structure()
        filepath = self.vault_dir / "MEMORY.md"

        try:
            content = filepath.read_text(encoding="utf-8") if filepath.exists() else ""

            # Deduplicate
            if entry in content:
                logger.debug(f"Entry already in MEMORY.md: {entry[:50]}...")
                return

            # Wikify the entry
            wikified_entry = self._wikify(entry)

            # Find section or create it
            section_header = f"## {section}"
            if section_header in content:
                # Insert after section header line
                idx = content.index(section_header) + len(section_header)
                next_newline = content.index("\n", idx) if "\n" in content[idx:] else len(content)
                insert_pos = idx + (next_newline - idx)
                content = content[:insert_pos] + f"\n- {wikified_entry}" + content[insert_pos:]
            else:
                # Append new section at end
                content = content.rstrip() + f"\n\n{section_header}\n- {wikified_entry}\n"

            # Update frontmatter entry count
            count = content.count("\n- ")
            content = re.sub(r"entries: \d+", f"entries: {count}", content)

            # Update last_updated
            today = datetime.now().strftime("%Y-%m-%d")
            content = re.sub(r"last_updated: \d{4}-\d{2}-\d{2}", f"last_updated: {today}", content)

            filepath.write_text(content, encoding="utf-8")
            logger.info(f"Appended to MEMORY.md [{section}]: {entry[:60]}...")

        except Exception as e:
            logger.warning(f"Failed to append to MEMORY.md: {e}")

    # ── Retro ────────────────────────────────────────────────────────────

    def write_retro(self, report_content: str, date: str = None):
        """Write weekly retro to vault/retros/."""
        self.ensure_structure()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        filepath = self.vault_dir / "retros" / f"retro-{date}.md"
        try:
            filepath.write_text(report_content, encoding="utf-8")
            logger.info(f"Wrote retro: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to write retro: {e}")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_frontmatter(self, data: dict) -> str:
        """Build YAML frontmatter string from a dict."""
        lines = ["---"]
        for k, v in data.items():
            if isinstance(v, list):
                items = ", ".join(str(x) for x in v)
                lines.append(f"{k}: [{items}]")
            elif isinstance(v, bool):
                lines.append(f"{k}: {'true' if v else 'false'}")
            else:
                lines.append(f"{k}: {v}")
        lines.append("---\n")
        return "\n".join(lines)

    # ── Initial File Templates ───────────────────────────────────────────

    def _write_initial_memory(self):
        today = datetime.now().strftime("%Y-%m-%d")
        content = f"""---
type: memory
last_updated: {today}
entries: 0
---

# NeoMind — Long-Term Memory

## About Irene
(Facts learned from conversations, promoted after 3+ occurrences)

## Trading Patterns
(Validated patterns from fin mode)

## Coding Preferences
(Validated preferences from coding mode)

## Corrections & Lessons
(Important mistakes to never repeat)
"""
        (self.vault_dir / "MEMORY.md").write_text(content, encoding="utf-8")

    def _write_initial_goals(self):
        today = datetime.now().strftime("%Y-%m-%d")
        content = f"""---
type: goals
generated_by: initial
date: {today}
---

# Current Improvement Targets

No targets yet. First weekly retro will generate them.
"""
        (self.vault_dir / "current-goals.md").write_text(content, encoding="utf-8")

    def _write_initial_soul(self):
        today = datetime.now().strftime("%Y-%m-%d")
        content = f"""---
type: soul
version: 1
last_updated: {today}
---

# NeoMind — Soul

## Identity
I am NeoMind, a three-personality AI agent (chat, coding, fin) for Irene.

## Core Values
- Data stays local. No cloud leaks. Ever.
- Financial data MUST come from tool calls, never LLM memory.
- Corrections > praise in learning priority.
- Admit mistakes. Don't hallucinate confidence.

## Operating Rules
- Read MEMORY.md and current-goals.md at every session start.
- Write journal entry at every session end.
- Never promote a pattern to MEMORY.md with fewer than 3 occurrences.
- Always check FINANCE_CORRECTNESS_RULES.md before any trade-related output.
"""
        (self.vault_dir / "SOUL.md").write_text(content, encoding="utf-8")
