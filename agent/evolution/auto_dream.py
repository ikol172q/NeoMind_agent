"""
AutoDream — Background memory consolidation service.

Inspired by Claude Code's AutoDream system. Runs during idle periods
to consolidate session memories into durable, cross-session knowledge.

Three-gate trigger system:
  1. Time gate: At least N minutes since last consolidation
  2. Volume gate: At least N conversation turns since last consolidation
  3. Idle gate: User has been idle for at least N seconds

Four-phase consolidation:
  Phase 1: Extract — Pull facts, patterns, and corrections from recent history
  Phase 2: Deduplicate — Merge with existing memories
  Phase 3: Synthesize — Combine related facts into higher-level insights
  Phase 4: Persist — Write consolidated memories to SharedMemory and Vault
"""

import os
import time
import json
import threading
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class AutoDream:
    """Background memory consolidation during idle periods."""

    # ── Gate Thresholds ─────────────────────────────────────────────
    MIN_INTERVAL_MINUTES = 30      # Gate 1: min time between consolidations
    MIN_TURNS_SINCE_LAST = 10      # Gate 2: min conversation turns
    IDLE_THRESHOLD_SECONDS = 60    # Gate 3: min idle time before trigger

    # ── Consolidation limits ────────────────────────────────────────
    MAX_HISTORY_WINDOW = 50        # Max recent messages to process
    MAX_CONSOLIDATED_PER_RUN = 10  # Max memories to write per consolidation

    def __init__(self, shared_memory=None, vault=None, learnings=None):
        self._shared_memory = shared_memory
        self._vault = vault
        self._learnings = learnings

        self._last_consolidation_time = 0.0
        self._turns_since_last = 0
        self._last_activity_time = time.time()
        self._running = False
        self._lock = threading.Lock()
        self._consolidated_count = 0

        # Dream journal — record of what was consolidated
        self._dream_journal: List[Dict[str, Any]] = []

        # State persistence
        self._state_path = Path(os.path.expanduser('~/.neomind/auto_dream_state.json'))
        self._load_state()

    def _load_state(self):
        """Load persisted state from disk."""
        try:
            if self._state_path.exists():
                with open(self._state_path) as f:
                    state = json.load(f)
                self._last_consolidation_time = state.get('last_consolidation_time', 0.0)
                self._consolidated_count = state.get('consolidated_count', 0)
        except Exception:
            pass

    def _save_state(self):
        """Persist state to disk."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'last_consolidation_time': self._last_consolidation_time,
                'consolidated_count': self._consolidated_count,
                'last_save': datetime.now(timezone.utc).isoformat(),
            }
            with open(self._state_path, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.debug(f"AutoDream: failed to save state: {e}")

    # ── Gate Checks ─────────────────────────────────────────────────

    def on_turn_complete(self):
        """Called after each conversation turn."""
        self._turns_since_last += 1
        self._last_activity_time = time.time()

    def on_user_activity(self):
        """Called on any user input."""
        self._last_activity_time = time.time()

    def _check_gates(self) -> bool:
        """Check if all three gates are open for consolidation."""
        now = time.time()

        # Gate 1: Time since last consolidation
        minutes_elapsed = (now - self._last_consolidation_time) / 60
        if minutes_elapsed < self.MIN_INTERVAL_MINUTES:
            return False

        # Gate 2: Enough conversation turns
        if self._turns_since_last < self.MIN_TURNS_SINCE_LAST:
            return False

        # Gate 3: User is idle
        idle_seconds = now - self._last_activity_time
        if idle_seconds < self.IDLE_THRESHOLD_SECONDS:
            return False

        return True

    def maybe_consolidate(self, conversation_history: List[Dict[str, Any]]) -> bool:
        """Check gates and run consolidation if all open.

        Called from the main loop's idle handler.

        Returns:
            True if consolidation was triggered
        """
        if self._running:
            return False
        if not self._check_gates():
            return False

        # Run consolidation in background thread
        thread = threading.Thread(
            target=self._run_consolidation,
            args=(conversation_history[-self.MAX_HISTORY_WINDOW:],),
            daemon=True,
        )
        thread.start()
        return True

    # ── Four-Phase Consolidation ────────────────────────────────────

    def _run_consolidation(self, recent_history: List[Dict[str, Any]]):
        """Execute four-phase memory consolidation."""
        with self._lock:
            if self._running:
                return
            self._running = True

        try:
            logger.info("AutoDream: starting memory consolidation")
            start = time.time()

            # Phase 1: Extract facts, patterns, corrections
            extracted = self._phase_extract(recent_history)
            if not extracted:
                logger.info("AutoDream: nothing to consolidate")
                return

            # Phase 2: Deduplicate against existing memories
            unique = self._phase_deduplicate(extracted)
            if not unique:
                logger.info("AutoDream: all items already known")
                return

            # Phase 3: Synthesize related items
            synthesized = self._phase_synthesize(unique)

            # Phase 4: Persist to memory stores
            count = self._phase_persist(synthesized)

            elapsed = time.time() - start
            self._last_consolidation_time = time.time()
            self._turns_since_last = 0
            self._consolidated_count += count
            self._save_state()

            # Record in dream journal
            self._dream_journal.append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'extracted': len(extracted),
                'unique': len(unique),
                'synthesized': len(synthesized),
                'persisted': count,
                'elapsed_seconds': round(elapsed, 2),
            })

            logger.info(f"AutoDream: consolidated {count} memories in {elapsed:.1f}s")

        except Exception as e:
            logger.error(f"AutoDream: consolidation failed: {e}")
        finally:
            self._running = False

    def _phase_extract(self, history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Phase 1: Extract facts, patterns, and corrections from conversation."""
        extracted = []

        for msg in history:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = ' '.join(
                    block.get('text', '') for block in content
                    if isinstance(block, dict) and block.get('type') == 'text'
                )

            if role == 'user':
                # Look for explicit corrections or preferences
                lower = content.lower()
                if any(kw in lower for kw in [
                    'remember that', 'don\'t forget', 'i prefer', 'always use',
                    'never use', 'my name is', 'i work', 'i like', 'i don\'t like',
                    'please note', 'for future reference', 'keep in mind',
                ]):
                    extracted.append({
                        'type': 'preference',
                        'content': content[:500],
                        'source': 'user_explicit',
                    })

                # Corrections
                if any(kw in lower for kw in [
                    'that\'s wrong', 'no, ', 'actually,', 'incorrect',
                    'not like that', 'fix this', 'that was a mistake',
                ]):
                    extracted.append({
                        'type': 'correction',
                        'content': content[:500],
                        'source': 'user_correction',
                    })

            elif role == 'assistant':
                # Look for tool results that indicate patterns
                if isinstance(msg.get('content'), list):
                    for block in msg['content']:
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            tool_name = block.get('name', '')
                            if tool_name in ('Read', 'Grep', 'Glob'):
                                # File access patterns
                                inp = block.get('input', {})
                                path = inp.get('path', inp.get('file_path', ''))
                                if path:
                                    extracted.append({
                                        'type': 'pattern',
                                        'content': f"Accessed file: {path}",
                                        'source': f'tool_{tool_name}',
                                    })

        return extracted[:self.MAX_CONSOLIDATED_PER_RUN * 2]  # Pre-limit

    def _phase_deduplicate(self, items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Phase 2: Remove items already present in memory."""
        unique = []
        existing_content = set()

        # Check SharedMemory for existing facts
        if self._shared_memory:
            try:
                facts = self._shared_memory.get_all_facts()
                for f in facts:
                    existing_content.add(f.get('fact', '').lower()[:100])
            except Exception:
                pass

        for item in items:
            key = item['content'].lower()[:100]
            if key not in existing_content:
                unique.append(item)
                existing_content.add(key)

        return unique

    def _phase_synthesize(self, items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Phase 3: Combine related items into higher-level insights.

        Simple heuristic: group by type and merge nearby items.
        """
        # Group by type
        by_type: Dict[str, List[Dict[str, str]]] = {}
        for item in items:
            by_type.setdefault(item['type'], []).append(item)

        synthesized = []
        for item_type, group in by_type.items():
            if len(group) <= 3:
                synthesized.extend(group)
            else:
                # Merge into a summary
                combined_content = '; '.join(item['content'][:200] for item in group[:5])
                synthesized.append({
                    'type': item_type,
                    'content': f"[Consolidated {len(group)} {item_type}s] {combined_content}",
                    'source': 'auto_dream_synthesis',
                })

        return synthesized[:self.MAX_CONSOLIDATED_PER_RUN]

    def _phase_persist(self, items: List[Dict[str, str]]) -> int:
        """Phase 4: Write consolidated memories to storage."""
        count = 0

        for item in items:
            try:
                if item['type'] == 'preference' and self._shared_memory:
                    self._shared_memory.remember_fact(
                        category='auto_dream',
                        fact=item['content'],
                        source_mode='auto_dream',
                    )
                    count += 1

                elif item['type'] == 'correction' and self._shared_memory:
                    self._shared_memory.record_feedback(
                        feedback_type='correction',
                        content=item['content'],
                        source_mode='auto_dream',
                    )
                    count += 1

                elif item['type'] == 'pattern' and self._shared_memory:
                    self._shared_memory.record_pattern(
                        pattern_type='file_access',
                        value=item['content'],
                        source_mode='auto_dream',
                    )
                    count += 1

                # Also write to vault journal if available
                if self._vault and hasattr(self._vault, 'get'):
                    writer = self._vault.get('writer')
                    if writer and hasattr(writer, 'append_journal'):
                        writer.append_journal(
                            f"[AutoDream] {item['type']}: {item['content'][:200]}"
                        )

            except Exception as e:
                logger.debug(f"AutoDream: failed to persist item: {e}")

        return count

    # ── Status & Journal ────────────────────────────────────────────

    @property
    def status(self) -> Dict[str, Any]:
        """Return current AutoDream status."""
        return {
            'running': self._running,
            'last_consolidation': self._last_consolidation_time,
            'turns_since_last': self._turns_since_last,
            'total_consolidated': self._consolidated_count,
            'gates_open': self._check_gates() if not self._running else False,
            'journal_entries': len(self._dream_journal),
        }

    @property
    def dream_journal(self) -> List[Dict[str, Any]]:
        """Return the dream journal."""
        return list(self._dream_journal)
