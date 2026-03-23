# Obsidian Vault Integration — Implementation Plan & Test Plan

> **Date:** 2026-03-22
> **Companion doc:** `2026-03-22_obsidian-vault-integration.md` (tracker with research & rationale)
> **Companion doc:** `OBSIDIAN_TROUBLESHOOTING.md` (failure modes & fixes)

---

## PRE-REQUISITES

### On Irene's Mac (one-time, manual)

```bash
# 1. Download & install Obsidian (free)
# https://obsidian.md/download

# 2. Create vault folder
mkdir -p ~/neomind-vault
cd ~/neomind-vault && git init

# 3. Open Obsidian → "Open folder as vault" → select ~/neomind-vault

# 4. Harden Obsidian:
#    Settings → General → disable "Automatic updates"
#    Settings → Community plugins → ensure "Restricted mode" is ON
#    macOS System Settings → Network → Firewall → Options
#      → add Obsidian.app → set to "Block incoming connections"
#    (Optional) Install Little Snitch → block ALL Obsidian connections

# 5. Verify: Obsidian should show an empty vault with no plugins
```

### In docker-compose.yml

```yaml
services:
  neomind:
    volumes:
      - ./data:/data                      # existing
      - ~/neomind-vault:/data/vault:rw    # NEW: vault bind mount
```

---

## PHASE 1: Vault Foundation

### Step 1.1: Create vault package (`agent/vault/`)

**File: `agent/vault/__init__.py`**
```python
"""NeoMind Vault — Markdown-based long-term memory.

Reads and writes to ~/neomind-vault (or /data/vault in Docker).
Obsidian on the host can browse this folder as a vault.
NeoMind does not depend on Obsidian — it reads/writes plain .md files.
"""
from agent.vault.reader import VaultReader
from agent.vault.writer import VaultWriter

__all__ = ["VaultReader", "VaultWriter"]
```

**File: `agent/vault/reader.py`**

Core class — reads MEMORY.md, current-goals.md, yesterday's journal at startup.

```python
"""VaultReader — Reads vault files and produces context for system prompt injection.

Usage:
    reader = VaultReader(vault_dir="/data/vault")
    context = reader.get_startup_context(mode="fin")
    # → returns string to append to system prompt
"""
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Default vault location: /data/vault in Docker, ~/.neomind/vault locally
DEFAULT_VAULT_DIR = os.environ.get(
    "NEOMIND_VAULT_DIR",
    "/data/vault" if os.path.isdir("/data") else str(Path.home() / "neomind-vault"),
)


class VaultReader:
    """Reads vault markdown files for system prompt injection."""

    def __init__(self, vault_dir: str = DEFAULT_VAULT_DIR):
        self.vault_dir = Path(vault_dir)

    def get_startup_context(self, mode: str = "chat", max_tokens: int = 1500) -> str:
        """Read vault files and return context string for system prompt.

        Reads (in priority order):
        1. MEMORY.md — curated long-term knowledge
        2. current-goals.md — active improvement targets
        3. journal/yesterday.md — yesterday's execution log

        Args:
            mode: Current personality mode (chat/coding/fin)
            max_tokens: Approximate token budget (1 token ≈ 4 chars)

        Returns:
            Formatted context string, or empty string if vault doesn't exist.
        """
        if not self.vault_dir.is_dir():
            logger.info(f"Vault dir not found: {self.vault_dir}")
            return ""

        sections = []
        char_budget = max_tokens * 4  # rough token-to-char conversion

        # 1. MEMORY.md (highest priority)
        memory = self._read_file("MEMORY.md")
        if memory:
            sections.append(f"## Long-Term Memory\n{memory}")

        # 2. current-goals.md
        goals = self._read_file("current-goals.md")
        if goals:
            sections.append(f"## Current Improvement Targets\n{goals}")

        # 3. Yesterday's journal
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        journal = self._read_file(f"journal/{yesterday}.md")
        if journal:
            sections.append(f"## Yesterday's Journal ({yesterday})\n{journal}")

        if not sections:
            return ""

        # Combine and truncate to budget
        combined = "\n\n---\n\n".join(sections)
        if len(combined) > char_budget:
            combined = combined[:char_budget] + "\n\n[... truncated for token budget]"

        return f"\n\n# Vault Context (from NeoMind's persistent memory)\n\n{combined}"

    def _read_file(self, relative_path: str) -> str:
        """Read a file from the vault, return content or empty string."""
        filepath = self.vault_dir / relative_path
        try:
            if filepath.is_file():
                content = filepath.read_text(encoding="utf-8").strip()
                # Strip YAML frontmatter for injection (Obsidian metadata)
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
                return content
        except Exception as e:
            logger.warning(f"Failed to read vault file {relative_path}: {e}")
        return ""

    def read_raw(self, relative_path: str) -> str:
        """Read raw file content including frontmatter."""
        filepath = self.vault_dir / relative_path
        try:
            if filepath.is_file():
                return filepath.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read {relative_path}: {e}")
        return ""

    def list_journal_entries(self, days: int = 7) -> list:
        """List recent journal entry filenames."""
        journal_dir = self.vault_dir / "journal"
        if not journal_dir.is_dir():
            return []
        entries = sorted(journal_dir.glob("*.md"), reverse=True)
        return [e.name for e in entries[:days]]

    def vault_exists(self) -> bool:
        """Check if vault directory exists and has been initialized."""
        return (self.vault_dir / "MEMORY.md").is_file()
```

**File: `agent/vault/writer.py`**

Core class — writes journal entries with YAML frontmatter.

```python
"""VaultWriter — Writes structured markdown files to the vault.

All files use YAML frontmatter for Obsidian Bases queryability.
Uses [[wikilinks]] for Obsidian graph view connections.
"""
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_VAULT_DIR = os.environ.get(
    "NEOMIND_VAULT_DIR",
    "/data/vault" if os.path.isdir("/data") else str(Path.home() / "neomind-vault"),
)


class VaultWriter:
    """Writes structured markdown to the vault."""

    def __init__(self, vault_dir: str = DEFAULT_VAULT_DIR):
        self.vault_dir = Path(vault_dir)

    def ensure_structure(self):
        """Create vault folder structure if it doesn't exist."""
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
                "# Obsidian local config (not versioned)\n.obsidian/\n"
            )

    def write_journal_entry(
        self,
        mode: str,
        tasks: list,
        errors: list,
        learnings: list,
        tools_used: list = None,
        tags: list = None,
        user_satisfaction: str = "neutral",
        tokens_used: int = 0,
        session_duration_min: int = 0,
    ) -> str:
        """Write a daily journal entry with YAML frontmatter.

        Returns the relative path of the written file.
        """
        self.ensure_structure()
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.vault_dir / "journal" / f"{today}.md"

        # Build YAML frontmatter
        frontmatter = {
            "type": "journal",
            "date": today,
            "mode": mode,
            "tasks_completed": len([t for t in tasks if t.get("status") != "failed"]),
            "tasks_failed": len([t for t in tasks if t.get("status") == "failed"]),
            "errors": len(errors),
            "user_satisfaction": user_satisfaction,
            "tools_used": tools_used or [],
            "tags": tags or [],
            "tokens_used": tokens_used,
            "session_duration_min": session_duration_min,
        }

        yaml_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                yaml_lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
            else:
                yaml_lines.append(f"{k}: {v}")
        yaml_lines.append("---")

        # Build markdown body
        body_lines = [f"\n# Journal — {today}\n"]

        body_lines.append("## Tasks")
        for i, task in enumerate(tasks, 1):
            status = "✅" if task.get("status") != "failed" else "❌"
            body_lines.append(f"{i}. {status} {task.get('description', 'unknown')}")

        if errors:
            body_lines.append("\n## Errors")
            for err in errors:
                body_lines.append(f"- {err}")

        if learnings:
            body_lines.append("\n## Learnings")
            for learning in learnings:
                body_lines.append(f"- {learning}")

        content = "\n".join(yaml_lines) + "\n" + "\n".join(body_lines) + "\n"

        # Append if file already exists (multiple sessions per day)
        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
            # Append new session as a section
            session_time = datetime.now().strftime("%H:%M")
            content = existing + f"\n\n---\n\n## Session {session_time}\n" + "\n".join(body_lines[1:]) + "\n"

        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Wrote journal entry: {filepath}")
        return f"journal/{today}.md"

    def write_goals(self, improvements: list):
        """Write current-goals.md (overwritten each week by retro)."""
        self.ensure_structure()
        today = datetime.now().strftime("%Y-%m-%d")

        lines = [
            "---",
            "type: goals",
            "generated_by: weekly_retro",
            f"date: {today}",
            "---",
            "",
            "# Current Improvement Targets",
            "",
        ]

        for i, imp in enumerate(improvements, 1):
            lines.append(f"## {i}. {imp.get('goal', 'Goal')}")
            lines.append(f"- **Current:** {imp.get('current', '...')}")
            lines.append(f"- **Target:** {imp.get('target', '...')}")
            lines.append(f"- **Metric:** {imp.get('metric', '...')}")
            lines.append(f"- **Action:** {imp.get('action', '...')}")
            lines.append(f"- **Timeline:** {imp.get('timeline', '1 week')}")
            lines.append("")

        filepath = self.vault_dir / "current-goals.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Wrote goals: {filepath}")

    def append_to_memory(self, section: str, entry: str):
        """Append a validated learning to MEMORY.md under a section heading.

        Only call this for patterns with 3+ occurrences.
        """
        self.ensure_structure()
        filepath = self.vault_dir / "MEMORY.md"
        content = filepath.read_text(encoding="utf-8") if filepath.exists() else ""

        # Check for duplicate
        if entry in content:
            logger.debug(f"Entry already in MEMORY.md: {entry[:50]}...")
            return

        # Find section or create it
        section_header = f"## {section}"
        if section_header in content:
            # Insert after section header
            idx = content.index(section_header) + len(section_header)
            # Find next line
            next_newline = content.index("\n", idx)
            content = content[:next_newline] + f"\n- {entry}" + content[next_newline:]
        else:
            # Append new section
            content = content.rstrip() + f"\n\n{section_header}\n- {entry}\n"

        # Update frontmatter entry count
        if "entries:" in content:
            import re
            count = content.count("\n- ")
            content = re.sub(r"entries: \d+", f"entries: {count}", content)

        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Appended to MEMORY.md [{section}]: {entry[:60]}...")

    def write_retro(self, report_content: str, date: str = None):
        """Write weekly retro to vault/retros/."""
        self.ensure_structure()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        filepath = self.vault_dir / "retros" / f"retro-{date}.md"
        filepath.write_text(report_content, encoding="utf-8")
        logger.info(f"Wrote retro: {filepath}")

    def _write_initial_memory(self):
        content = """---
type: memory
last_updated: {date}
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
""".format(date=datetime.now().strftime("%Y-%m-%d"))
        (self.vault_dir / "MEMORY.md").write_text(content, encoding="utf-8")

    def _write_initial_goals(self):
        content = """---
type: goals
generated_by: initial
date: {date}
---

# Current Improvement Targets

No targets yet. First weekly retro will generate them.
""".format(date=datetime.now().strftime("%Y-%m-%d"))
        (self.vault_dir / "current-goals.md").write_text(content, encoding="utf-8")

    def _write_initial_soul(self):
        content = """---
type: soul
version: 1
last_updated: {date}
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
""".format(date=datetime.now().strftime("%Y-%m-%d"))
        (self.vault_dir / "SOUL.md").write_text(content, encoding="utf-8")
```

### Step 1.2: Wire into `core.py`

**Modify: `agent/core.py` around line 320**

```python
# EXISTING (line 320):
if agent_config.system_prompt:
    self.add_to_history("system", agent_config.system_prompt)

# ADD AFTER:
# ── Vault context injection (reads MEMORY.md, current-goals.md, yesterday's journal)
try:
    from agent.vault.reader import VaultReader
    self._vault_reader = VaultReader()
    vault_context = self._vault_reader.get_startup_context(mode=self.mode)
    if vault_context:
        self.add_to_history("system", vault_context)
        logger.info("Injected vault context into system prompt")
except Exception as e:
    self._vault_reader = None
    logger.debug(f"Vault reader not available: {e}")
```

### Step 1.3: Journal writing at session end

**Modify: `agent/core.py`** — add session tracking + journal write

Add a `_write_session_journal()` method and call it from the session cleanup/exit path.

---

## PHASE 2: Close the Self-Improvement Loop

### Step 2.1: Modify `auto_evolve.py`

**In `run_weekly_retro()` (around line 420):**

```python
# EXISTING:
retro_file = self.evolution_dir / f"retro-{week_end}.md"
retro_content = self._format_retro(report)
with open(retro_file, "w") as f:
    f.write(retro_content)

# ADD AFTER:
# Also write to vault for Obsidian browsing
try:
    from agent.vault.writer import VaultWriter
    vault = VaultWriter()
    vault.write_retro(retro_content, date=week_end)
    vault.write_goals(report.improvements)
    logger.info("Wrote retro and goals to vault")
except Exception as e:
    logger.warning(f"Vault write failed (non-fatal): {e}")
```

### Step 2.2: Pattern promotion

**New file: `agent/vault/promoter.py`**

```python
"""Promoter — Moves validated patterns from SharedMemory to vault MEMORY.md.

A pattern is "validated" when it has been observed 3+ times.
This prevents hallucinated or one-off observations from becoming
long-term memory.
"""
import logging
from agent.vault.writer import VaultWriter

logger = logging.getLogger(__name__)

PROMOTION_THRESHOLD = 3

SECTION_MAP = {
    "frequent_stock": "Trading Patterns",
    "coding_language": "Coding Preferences",
    "tool": "Tool Preferences",
    "topic": "Conversation Topics",
}


def promote_patterns(shared_memory, vault_writer: VaultWriter = None):
    """Scan SharedMemory patterns table for entries with count >= threshold.

    Promotes them to the appropriate MEMORY.md section.
    """
    if vault_writer is None:
        vault_writer = VaultWriter()

    try:
        patterns = shared_memory.get_all_patterns()
    except Exception as e:
        logger.warning(f"Failed to read patterns: {e}")
        return 0

    promoted = 0
    for p in patterns:
        if p.get("count", 0) >= PROMOTION_THRESHOLD:
            section = SECTION_MAP.get(p["pattern_type"], "Other Patterns")
            entry = f"{p['pattern_value']} (observed {p['count']}x, source: {p.get('source_mode', 'unknown')})"
            vault_writer.append_to_memory(section, entry)
            promoted += 1

    if promoted:
        logger.info(f"Promoted {promoted} patterns to MEMORY.md")
    return promoted
```

### Step 2.3: Call promoter from weekly retro

Add to `auto_evolve.py` `run_weekly_retro()`:

```python
# After writing retro and goals to vault
try:
    from agent.memory.shared_memory import SharedMemory
    from agent.vault.promoter import promote_patterns
    mem = SharedMemory()
    promoted = promote_patterns(mem, vault)
    report.patterns_promoted = promoted
except Exception as e:
    logger.warning(f"Pattern promotion failed (non-fatal): {e}")
```

---

## PHASE 3: Obsidian-Friendly Enhancements

### Step 3.1: Add `[[wikilinks]]` to journal entries

In `VaultWriter.write_journal_entry()`, add a helper:

```python
def _wikify(self, text: str) -> str:
    """Add [[wikilinks]] to known entities for Obsidian graph view."""
    # Link stock tickers (uppercase 1-5 letters)
    import re
    text = re.sub(r'\b([A-Z]{1,5})\b', lambda m: f"[[{m.group(1)}]]"
                  if m.group(1) in self._known_tickers else m.group(1), text)
    # Link to learnings files
    for keyword, target in [
        ("trading pattern", "trading-patterns"),
        ("coding lesson", "coding-lessons"),
    ]:
        text = text.replace(keyword, f"[[{target}|{keyword}]]")
    return text
```

### Step 3.2: Create initial vault files

Create `SOUL.md`, `MEMORY.md`, `current-goals.md`, `.gitignore` using `VaultWriter.ensure_structure()`.

---

## TEST PLAN

### Unit Tests: `tests/test_vault_reader.py`

```
test_reader_empty_vault          — vault dir doesn't exist → returns ""
test_reader_memory_only          — only MEMORY.md exists → returns its content
test_reader_goals_only           — only current-goals.md → returns its content
test_reader_journal_only         — only yesterday's journal → returns its content
test_reader_all_three            — all 3 files → returns combined, MEMORY first
test_reader_strips_frontmatter   — YAML frontmatter is stripped from injected context
test_reader_preserves_frontmatter_in_raw — read_raw() keeps frontmatter
test_reader_truncates_to_budget  — content exceeding max_tokens is truncated
test_reader_handles_unicode      — Chinese/emoji in vault files
test_reader_handles_missing_journal — no journal for yesterday → graceful skip
test_reader_handles_corrupt_file — invalid UTF-8 → graceful skip, no crash
test_reader_list_journal_entries — returns sorted list of recent journal filenames
test_reader_vault_exists         — returns True when MEMORY.md present
test_reader_vault_not_exists     — returns False when vault empty
```

### Unit Tests: `tests/test_vault_writer.py`

```
test_writer_ensure_structure     — creates all subdirectories and root files
test_writer_journal_entry        — writes journal with correct YAML frontmatter
test_writer_journal_append       — second session on same day appends, doesn't overwrite
test_writer_goals                — write_goals() creates correct markdown
test_writer_append_memory        — append_to_memory() adds entry under correct section
test_writer_append_memory_dedup  — duplicate entry is NOT added twice
test_writer_append_memory_new_section — new section created if doesn't exist
test_writer_memory_entry_count   — frontmatter entries count updated correctly
test_writer_retro                — write_retro() creates file in retros/ folder
test_writer_initial_files        — ensure_structure creates SOUL.md, MEMORY.md, etc.
test_writer_unicode              — Chinese characters in journal entries
test_writer_empty_tasks          — empty task list doesn't crash
test_writer_handles_readonly_fs  — graceful error if vault is read-only
```

### Unit Tests: `tests/test_vault_promoter.py`

```
test_promoter_threshold          — patterns with count < 3 are NOT promoted
test_promoter_above_threshold    — patterns with count >= 3 ARE promoted
test_promoter_dedup              — same pattern promoted twice → only one entry
test_promoter_correct_section    — frequent_stock → "Trading Patterns", etc.
test_promoter_unknown_type       — unknown pattern type → "Other Patterns"
test_promoter_empty_patterns     — no patterns → returns 0, no crash
test_promoter_shared_memory_error — SharedMemory unavailable → graceful fail
test_promoter_returns_count      — returns correct count of promoted patterns
```

### Integration Tests: `tests/test_vault_integration.py`

```
test_full_loop_write_read        — write journal → read it back → correct content
test_full_loop_retro_to_goals    — write retro → write goals → read goals at startup → injected
test_full_loop_promote_pattern   — record pattern 3x → run promoter → MEMORY.md updated → read at startup → in context
test_startup_injection           — VaultReader context appears in conversation_history after __init__
test_vault_survives_restart      — write data, create new VaultReader instance → data persists
test_concurrent_write_read       — writer and reader can operate simultaneously without corruption
```

### Manual Verification Checklist

```
[ ] Obsidian sees ~/neomind-vault as a vault
[ ] Graph view shows connections between journal entries via [[wikilinks]]
[ ] Bases can query journal entries by date, mode, errors, tags
[ ] Search finds content across all vault files
[ ] Backlinks show all references to a given note
[ ] MEMORY.md editable by Irene in Obsidian → NeoMind reads changes at next startup
[ ] Restricted Mode is ON → no community plugins active
[ ] Network is BLOCKED → Obsidian cannot connect to internet
[ ] Auto-update is DISABLED
[ ] Git log shows audit trail of all vault changes
```

### Performance Tests

```
test_reader_performance_100_files  — VaultReader startup < 100ms with 100 journal files
test_reader_performance_1000_files — VaultReader startup < 500ms with 1000 journal files
test_writer_performance            — VaultWriter.write_journal_entry < 50ms
```

---

## ROLLBACK PLAN

If the vault integration causes issues:

1. **Remove vault injection from core.py** — delete the 15-line block added after line 320
2. NeoMind reverts to its previous behavior (system prompt only, no vault context)
3. Vault files remain on disk — no data loss
4. Obsidian continues to work as a standalone viewer

The vault is strictly **additive** — removing it doesn't break any existing functionality.

---

## SUCCESS CRITERIA

| Metric | Threshold | How to measure |
|--------|-----------|----------------|
| All existing tests pass | 1424/1424 | `pytest` |
| New vault tests pass | 40+/40+ | `pytest tests/test_vault*.py` |
| Startup time increase | < 200ms | Timestamp before/after vault injection |
| Journal written every session | 100% | Check `vault/journal/` for today's file |
| Weekly retro writes goals | 100% | Check `vault/current-goals.md` updated Sunday |
| Goals injected at startup | 100% | Check conversation_history for vault context |
| MEMORY.md grows over time | At least 1 entry/week | Check entry count in frontmatter |
| Obsidian graph shows connections | Manual | Open graph view, verify nodes and edges |

---

## TIMELINE

| Day | Phase | Deliverable | Status |
|-----|-------|-------------|--------|
| 1 | Phase 1 | `agent/vault/` package, VaultReader, VaultWriter, core.py injection | ✅ Done |
| 2 | Phase 2 | auto_evolve.py changes, promoter.py, goals writing | ✅ Done |
| 3 | Phase 3 + 4 | Initial vault files, all unit + integration tests | ✅ Done |
| 3 | Phase 3 | Wikilinks in journal entries | ⬜ Deferred |
| 4 | Phase 4 | Manual Docker + Obsidian verification | ✅ Done 2026-03-22 |
| 5 | Buffer | Bug fixes (logger→_status_print, NEOMIND_DISABLE_VAULT, session journal hook) | ✅ Done |

---

## FUTURE ROADMAP (not in this sprint)

| Phase | When | What | Reference |
|-------|------|------|-----------|
| 5 | Vault > 500 files | Add memsearch for semantic search | [memsearch](https://github.com/zilliztech/memsearch) |
| 6 | After Phase 5 stable | JSON Canvas generation for visual workflows | [jsoncanvas.org](https://jsoncanvas.org/) |
| 7 | If needed | Consider Obsidian CLI integration (requires app running) | [Obsidian CLI](https://help.obsidian.md/cli) |
| 8 | If plugins trusted | Consider Dataview for advanced queries | [Dataview](https://blacksmithgu.github.io/obsidian-dataview/) |
| 9 | If plugins trusted | Consider Journalit for trading dashboards | [Journalit](https://github.com/Cursivez/journalit) |
