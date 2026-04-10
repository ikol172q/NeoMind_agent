"""
Prompt Composer — Multi-section system prompt construction.

Builds the system prompt from independent sections with:
- Priority-based override chain
- Dynamic cache boundary marker
- Per-section token accounting
- Prompt dump for audit

Sections:
  1. Base identity & rules (cacheable)
  2. Tool descriptions (auto-generated)
  3. Dynamic boundary marker
  4. Context (git status, OS, date)
  5. Memory (selected relevant memories)
  6. Output style (user-customized format)
  7. Coordinator/agent-specific overrides
"""

import os
import time
import json
import logging
import platform
import subprocess
from typing import List, Dict, Optional, Any, Tuple

logger = logging.getLogger(__name__)

DYNAMIC_BOUNDARY = "\n<!-- SYSTEM_PROMPT_DYNAMIC_BOUNDARY -->\n"


class PromptSection:
    """A single section of the system prompt."""

    def __init__(self, name: str, content: str, cacheable: bool = True,
                 priority: int = 50):
        self.name = name
        self.content = content
        self.cacheable = cacheable
        self.priority = priority  # Lower = appears first
        self.token_estimate = len(content) // 4

    def __repr__(self):
        return f"PromptSection({self.name}, {self.token_estimate} tokens, cache={self.cacheable})"


class PromptComposer:
    """Composes system prompt from multiple sections with priority chain.

    Override chain (first non-None wins):
      override_prompt → coordinator_prompt → agent_prompt → custom_prompt → default_prompt

    Plus: append_prompt always appends regardless of which source was used.

    Usage:
        composer = PromptComposer()
        composer.set_base_prompt("You are NeoMind...")
        composer.set_tools_section(tool_descriptions)
        composer.set_context(git_status, os_info, date)
        composer.set_memory(selected_memories)
        prompt = composer.build()
        accounting = composer.get_token_accounting()
    """

    def __init__(self):
        self._sections: Dict[str, PromptSection] = {}
        self._override_prompt: Optional[str] = None
        self._coordinator_prompt: Optional[str] = None
        self._agent_prompt: Optional[str] = None
        self._custom_prompt: Optional[str] = None
        self._append_prompt: Optional[str] = None
        self._last_build: Optional[str] = None
        self._dump_enabled = os.environ.get('NEOMIND_DUMP_PROMPTS', '') == '1'
        self._dump_dir = os.path.expanduser('~/.neomind/prompt-dumps')

    def set_section(self, name: str, content: str, cacheable: bool = True,
                    priority: int = 50):
        """Set or update a prompt section."""
        self._sections[name] = PromptSection(name, content, cacheable, priority)

    def set_base_prompt(self, content: str):
        """Set the base identity/rules section (always cacheable)."""
        self.set_section('base', content, cacheable=True, priority=10)

    def set_tools_section(self, tool_descriptions: str):
        """Set the auto-generated tool descriptions section."""
        self.set_section('tools', tool_descriptions, cacheable=True, priority=20)

    def set_context(self, git_status: str = "", os_info: str = "",
                    date_str: str = ""):
        """Set the dynamic context section (not cacheable)."""
        parts = []
        if date_str:
            parts.append(f"Current date: {date_str}")
        if os_info:
            parts.append(f"System: {os_info}")
        if git_status:
            parts.append(f"Git status:\n{git_status}")
        if parts:
            self.set_section('context', "\n".join(parts), cacheable=False, priority=60)

    def set_memory(self, memory_text: str):
        """Set the selected memory section (not cacheable).

        Also injects memory taxonomy guidance if not already present.
        """
        if memory_text:
            # Include taxonomy guidance alongside memories
            try:
                from agent.memory.memory_taxonomy import build_taxonomy_prompt
                taxonomy = build_taxonomy_prompt()
                combined = taxonomy + "\n\n" + memory_text
            except ImportError:
                combined = memory_text
            self.set_section('memory', combined, cacheable=False, priority=70)

    def set_output_style(self, style_text: str):
        """Set the output style section."""
        if style_text:
            self.set_section('output_style', style_text, cacheable=False, priority=80)

    def set_override_prompt(self, prompt: str):
        """Set the highest-priority override (replaces everything except append)."""
        self._override_prompt = prompt

    def set_coordinator_prompt(self, prompt: str):
        """Set coordinator mode prompt."""
        self._coordinator_prompt = prompt

    def set_agent_prompt(self, prompt: str):
        """Set agent-specific prompt."""
        self._agent_prompt = prompt

    def set_custom_prompt(self, prompt: str):
        """Set user's custom prompt."""
        self._custom_prompt = prompt

    def set_append_prompt(self, prompt: str):
        """Set text that always appends regardless of source."""
        self._append_prompt = prompt

    def inject_project_guidance(self, workspace_root: Optional[str] = None):
        """Auto-discover and inject NEOMIND.md / project.md guidance.

        Searches for project-level and global guidance files:
          1. {workspace}/.neomind/project.md — project-specific
          2. {workspace}/NEOMIND.md — project-specific (alt)
          3. ~/.neomind/NEOMIND.md — global guidance

        Content is appended as a low-priority section so it appears after
        other sections but before the dynamic boundary.
        """
        guidance_parts = []

        # Project-level guidance
        if workspace_root:
            candidates = [
                os.path.join(workspace_root, ".neomind", "project.md"),
                os.path.join(workspace_root, "NEOMIND.md"),
            ]
            for path in candidates:
                try:
                    if os.path.isfile(path):
                        content = open(path, "r", encoding="utf-8").read().strip()
                        if content:
                            guidance_parts.append(
                                f"<!-- Project guidance from {os.path.basename(path)} -->\n{content}"
                            )
                            logger.info(f"Injected project guidance from {path}")
                except Exception as e:
                    logger.debug(f"Failed to read project guidance {path}: {e}")

        # Global guidance
        global_path = os.path.expanduser("~/.neomind/NEOMIND.md")
        try:
            if os.path.isfile(global_path):
                content = open(global_path, "r", encoding="utf-8").read().strip()
                if content:
                    guidance_parts.append(
                        f"<!-- Global guidance from NEOMIND.md -->\n{content}"
                    )
                    logger.info(f"Injected global guidance from {global_path}")
        except Exception as e:
            logger.debug(f"Failed to read global guidance {global_path}: {e}")

        if guidance_parts:
            combined = "\n\n".join(guidance_parts)
            self.set_section('project_guidance', combined, cacheable=True, priority=45)

    def build(self) -> str:
        """Build the final system prompt from all sections.

        Returns the composed prompt string.
        """
        # Determine the base via priority chain
        base = (
            self._override_prompt
            or self._coordinator_prompt
            or self._agent_prompt
            or self._custom_prompt
            or self._build_from_sections()
        )

        # Always append if set
        if self._append_prompt:
            base = base + "\n\n" + self._append_prompt

        self._last_build = base

        # Dump for audit if enabled
        if self._dump_enabled:
            self._dump_prompt(base)

        return base

    def _build_from_sections(self) -> str:
        """Build prompt from registered sections with cache boundary."""
        sorted_sections = sorted(self._sections.values(), key=lambda s: s.priority)

        parts = []
        boundary_inserted = False

        for section in sorted_sections:
            if not boundary_inserted and not section.cacheable:
                parts.append(DYNAMIC_BOUNDARY)
                boundary_inserted = True
            parts.append(f"<!-- section: {section.name} -->\n{section.content}")

        if not boundary_inserted:
            parts.append(DYNAMIC_BOUNDARY)

        return "\n\n".join(parts)

    def get_token_accounting(self) -> List[Dict[str, Any]]:
        """Get per-section token accounting.

        Returns list of {name, tokens, cacheable, priority} dicts.
        """
        sections = sorted(self._sections.values(), key=lambda s: s.priority)
        total = sum(s.token_estimate for s in sections)

        result = []
        for s in sections:
            result.append({
                'name': s.name,
                'tokens': s.token_estimate,
                'cacheable': s.cacheable,
                'priority': s.priority,
                'pct': round(s.token_estimate / total * 100, 1) if total > 0 else 0,
            })

        result.append({
            'name': 'TOTAL',
            'tokens': total,
            'cacheable': None,
            'priority': None,
            'pct': 100.0,
        })

        return result

    def format_token_accounting(self) -> str:
        """Format token accounting for /context display."""
        accounting = self.get_token_accounting()
        lines = ["System Prompt Sections:"]
        for entry in accounting:
            if entry['name'] == 'TOTAL':
                lines.append(f"  {'─' * 40}")
                lines.append(f"  TOTAL: {entry['tokens']:,} tokens")
            else:
                cache = "C" if entry['cacheable'] else "D"
                lines.append(f"  [{cache}] {entry['name']}: {entry['tokens']:,} tokens ({entry['pct']}%)")
        return "\n".join(lines)

    def _dump_prompt(self, prompt: str):
        """Dump the full prompt to disk for audit."""
        try:
            os.makedirs(self._dump_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(self._dump_dir, f"{timestamp}.jsonl")
            entry = {
                'timestamp': timestamp,
                'prompt_length': len(prompt),
                'sections': [s.name for s in self._sections.values()],
                'prompt': prompt[:50000],  # Cap at 50K chars
            }
            with open(filepath, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            logger.debug(f"Prompt dump failed: {e}")


def collect_system_context() -> Tuple[str, str, str]:
    """Collect dynamic system context (git status, OS info, current date).

    Returns (git_status, os_info, date_str)
    """
    # Date
    date_str = time.strftime("%Y-%m-%d")

    # OS info
    os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"

    # Git status (truncated)
    git_status = ""
    try:
        result = subprocess.run(
            ['git', 'status', '--short'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            git_status = result.stdout.strip()[:2000]
            if len(result.stdout) > 2000:
                git_status += "\n... (truncated)"
    except Exception:
        pass

    return git_status, os_info, date_str
