"""
Session Notes — Auto-maintained structured notes on the current session.

Different from AutoDream (which is cross-session consolidation). This module
tracks what's happening in the CURRENT session so that:
1. Context survives compaction (notes are re-injected after compact)
2. /resume can restore meaningful context
3. Users can review what happened in a session

Structured into 9 sections following Claude Code's SessionMemory pattern.

Triggers:
- After N tool calls (default 25)
- After M estimated tokens (default 30K)
"""

import os
import json
import time
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

SECTION_TEMPLATE = """# Session Notes

## Current State
_What is currently happening in this session_

## Task Specification
_What the user asked for and the approach taken_

## Files and Functions
_Key files and functions being worked on_

## Workflow
_Steps completed and remaining_

## Errors & Corrections
_Errors encountered and how they were resolved_

## Codebase Documentation
_Important things learned about the codebase_

## Learnings
_Non-obvious insights discovered during this session_

## Key Results
_Outputs, artifacts, and deliverables produced_
"""

MAX_SECTION_CHARS = 2000
MAX_TOTAL_CHARS = 12000


class SessionNotes:
    """Auto-maintained session notes.

    Usage:
        notes = SessionNotes(session_id="abc123")
        notes.maybe_update(messages, tool_count=30, est_tokens=40000)
        context = notes.get_context_injection()
    """

    def __init__(self, session_id: str = None,
                 update_tool_threshold: int = 25,
                 update_token_threshold: int = 30000,
                 init_token_threshold: int = 15000):
        self._session_id = session_id or str(int(time.time()))
        self._notes_dir = Path(os.path.expanduser('~/.neomind/session_notes'))
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        self._notes_path = self._notes_dir / f"{self._session_id}.md"

        self._update_tool_threshold = update_tool_threshold
        self._update_token_threshold = update_token_threshold
        self._init_token_threshold = init_token_threshold

        self._initialized = False
        self._last_update_tool_count = 0
        self._last_update_token_count = 0
        self._content = ""

    def maybe_update(self, messages: List[Dict[str, Any]],
                     tool_count: int = 0, est_tokens: int = 0,
                     llm_fn=None) -> bool:
        """Check if notes should be updated and extract if so.

        Returns True if notes were updated.
        """
        if not self._initialized:
            if est_tokens >= self._init_token_threshold:
                self._initialized = True
                self._extract_notes(messages, llm_fn)
                self._last_update_tool_count = tool_count
                self._last_update_token_count = est_tokens
                return True
            return False

        # Check thresholds
        tools_since = tool_count - self._last_update_tool_count
        tokens_since = est_tokens - self._last_update_token_count

        if tools_since >= self._update_tool_threshold or tokens_since >= self._update_token_threshold:
            self._extract_notes(messages, llm_fn)
            self._last_update_tool_count = tool_count
            self._last_update_token_count = est_tokens
            return True

        return False

    def _extract_notes(self, messages: List[Dict[str, Any]], llm_fn=None):
        """Extract structured notes from recent messages."""
        # If no LLM available, do heuristic extraction
        if llm_fn is None:
            self._extract_heuristic(messages)
        else:
            self._extract_with_llm(messages, llm_fn)

        # Persist to disk
        self._save()

    def _extract_heuristic(self, messages: List[Dict[str, Any]]):
        """Heuristic note extraction without LLM call."""
        sections = {
            'Current State': '',
            'Task Specification': '',
            'Files and Functions': [],
            'Workflow': [],
            'Errors & Corrections': [],
            'Key Results': [],
        }

        for msg in messages[-50:]:  # Last 50 messages
            role = msg.get('role', '')
            content = msg.get('content', '')
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get('type') == 'tool_use':
                            tool = block.get('name', '')
                            inp = block.get('input', {})
                            if tool in ('Read', 'Edit', 'Write'):
                                path = inp.get('path', inp.get('file_path', ''))
                                if path and path not in sections['Files and Functions']:
                                    sections['Files and Functions'].append(path)
                            elif tool == 'Bash':
                                cmd = inp.get('command', '')[:80]
                                sections['Workflow'].append(f"Ran: {cmd}")
                        elif block.get('type') == 'tool_result':
                            if block.get('is_error'):
                                sections['Errors & Corrections'].append(
                                    str(block.get('content', ''))[:200]
                                )
                        elif block.get('type') == 'text':
                            text = block.get('text', '')
                            if role == 'user' and not sections['Task Specification']:
                                sections['Task Specification'] = text[:500]
                continue

            if role == 'user' and not sections['Task Specification']:
                sections['Task Specification'] = str(content)[:500]

        # Build notes content
        lines = ["# Session Notes\n"]
        if sections['Task Specification']:
            lines.append(f"## Task Specification\n{sections['Task Specification']}\n")
        if sections['Files and Functions']:
            lines.append("## Files and Functions\n" + "\n".join(f"- {f}" for f in sections['Files and Functions'][:20]) + "\n")
        if sections['Workflow']:
            lines.append("## Workflow\n" + "\n".join(f"- {w}" for w in sections['Workflow'][-15:]) + "\n")
        if sections['Errors & Corrections']:
            lines.append("## Errors & Corrections\n" + "\n".join(f"- {e}" for e in sections['Errors & Corrections'][-5:]) + "\n")

        self._content = "\n".join(lines)[:MAX_TOTAL_CHARS]

    def _extract_with_llm(self, messages: List[Dict[str, Any]], llm_fn):
        """Extract notes using LLM (more structured, higher quality)."""
        # Build a condensed representation of recent messages
        condensed = []
        for msg in messages[-30:]:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if isinstance(content, list):
                parts = []
                for b in content:
                    if isinstance(b, dict):
                        if b.get('type') == 'text':
                            parts.append(b.get('text', '')[:300])
                        elif b.get('type') == 'tool_use':
                            parts.append(f"[Tool: {b.get('name', '')}({str(b.get('input', {}))[:100]})]")
                content = ' '.join(parts)
            condensed.append(f"[{role}]: {str(content)[:400]}")

        prompt = (
            "Extract structured session notes from this conversation. "
            "Keep each section under 200 words. Use the template:\n\n"
            f"{SECTION_TEMPLATE}\n\n"
            "--- CONVERSATION ---\n"
            + "\n".join(condensed[-20:])
        )

        try:
            import asyncio
            if asyncio.iscoroutinefunction(llm_fn):
                self._content = asyncio.get_event_loop().run_until_complete(llm_fn(prompt))
            else:
                self._content = llm_fn(prompt)
            self._content = self._content[:MAX_TOTAL_CHARS]
        except Exception as e:
            logger.debug(f"LLM note extraction failed, using heuristic: {e}")
            self._extract_heuristic(messages)

    def _save(self):
        """Persist notes to disk."""
        try:
            with open(self._notes_path, 'w', encoding='utf-8') as f:
                f.write(self._content)
        except Exception as e:
            logger.debug(f"Failed to save session notes: {e}")

    def get_context_injection(self) -> str:
        """Return notes content for system prompt injection."""
        if not self._content:
            return ""
        return f"\n\n[Session Notes — auto-generated context]\n{self._content}"

    @property
    def content(self) -> str:
        return self._content

    def load(self, session_id: str = None) -> Optional[str]:
        """Load notes from a previous session."""
        sid = session_id or self._session_id
        path = self._notes_dir / f"{sid}.md"
        if path.exists():
            with open(path, 'r') as f:
                return f.read()
        return None
