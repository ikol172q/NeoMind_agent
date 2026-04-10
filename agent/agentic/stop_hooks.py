"""
Stop Hooks Pipeline — Ordered post-turn hooks for NeoMind.

After each LLM turn completes, run a pipeline of hooks:
1. Session notes extraction
2. AutoDream consolidation check
3. Evolution scheduler check
4. Custom hooks (user-defined)

Each hook runs in its own try/except to prevent one failure
from blocking others.
"""

import logging
import time
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


class StopHook:
    """A single post-turn hook."""

    def __init__(self, name: str, fn: Callable, priority: int = 50,
                 enabled: bool = True):
        self.name = name
        self.fn = fn
        self.priority = priority
        self.enabled = enabled


class StopHookPipeline:
    """Ordered pipeline of post-turn hooks.

    Usage:
        pipeline = StopHookPipeline()
        pipeline.register('session_notes', update_notes, priority=10)
        pipeline.register('auto_dream', check_dream, priority=20)
        pipeline.run_all(messages=history, turn_count=5)
    """

    def __init__(self):
        self._hooks: List[StopHook] = []
        self._last_run_results: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, fn: Callable, priority: int = 50,
                 enabled: bool = True):
        """Register a hook. Lower priority = runs first."""
        self._hooks.append(StopHook(name, fn, priority, enabled))
        self._hooks.sort(key=lambda h: h.priority)

    def unregister(self, name: str):
        """Remove a hook by name."""
        self._hooks = [h for h in self._hooks if h.name != name]

    def run_all(self, **kwargs) -> Dict[str, Dict[str, Any]]:
        """Run all enabled hooks in priority order.

        Each hook receives **kwargs (messages, turn_count, etc.)
        Each hook is isolated — one failure doesn't block others.

        Returns dict of {hook_name: {success, elapsed_ms, error?}}
        """
        results = {}

        for hook in self._hooks:
            if not hook.enabled:
                results[hook.name] = {'success': True, 'skipped': True}
                continue

            start = time.time()
            try:
                hook.fn(**kwargs)
                elapsed = int((time.time() - start) * 1000)
                results[hook.name] = {
                    'success': True,
                    'elapsed_ms': elapsed,
                }
            except Exception as e:
                elapsed = int((time.time() - start) * 1000)
                logger.debug(f"Stop hook '{hook.name}' failed: {e}")
                results[hook.name] = {
                    'success': False,
                    'elapsed_ms': elapsed,
                    'error': str(e),
                }

        self._last_run_results = results
        return results

    @property
    def last_results(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._last_run_results)

    def list_hooks(self) -> List[Dict[str, Any]]:
        """List all registered hooks."""
        return [
            {
                'name': h.name,
                'priority': h.priority,
                'enabled': h.enabled,
            }
            for h in self._hooks
        ]


def create_default_pipeline(services=None) -> StopHookPipeline:
    """Create the default stop hook pipeline with built-in hooks.

    Args:
        services: ServiceRegistry instance for accessing services

    Returns:
        Configured StopHookPipeline
    """
    pipeline = StopHookPipeline()

    # Hook 1: Session notes extraction (priority 10 — runs first)
    def _session_notes_hook(**kwargs):
        if services and services.session_notes:
            messages = kwargs.get('messages', [])
            tool_count = kwargs.get('tool_count', 0)
            total_chars = sum(len(str(m.get('content', ''))) for m in messages)
            services.session_notes.maybe_update(
                messages=messages,
                tool_count=tool_count,
                est_tokens=total_chars // 4,
            )

    pipeline.register('session_notes', _session_notes_hook, priority=10)

    # Hook 2: AutoDream consolidation check (priority 20)
    def _auto_dream_hook(**kwargs):
        if services and services.auto_dream:
            dream = services.auto_dream
            dream.on_turn_complete()
            messages = kwargs.get('messages', [])
            if messages:
                dream.maybe_consolidate(messages)

    pipeline.register('auto_dream', _auto_dream_hook, priority=20)

    # Hook 3: Evolution scheduler (priority 30)
    def _evolution_hook(**kwargs):
        if services:
            sched = services.evolution_scheduler
            if sched:
                turn_count = kwargs.get('turn_count', 0)
                sched.on_turn_complete(turn_count)

    pipeline.register('evolution', _evolution_hook, priority=30)

    return pipeline
