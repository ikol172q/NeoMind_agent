"""
LLM-Based Memory Selection — Select relevant memories per query.

Instead of injecting ALL memories into every prompt, this module uses
a lightweight LLM call to select the 5 most relevant memories.

Saves tokens and improves relevance significantly.
"""

import logging
import hashlib
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

MAX_SELECTIONS = 5
CACHE_MAX = 50  # Max cached selections


class MemorySelector:
    """Select relevant memories for a query using LLM.

    Usage:
        selector = MemorySelector(llm_fn=my_llm_call)
        relevant = selector.select(query="fix the login bug", memories=[...])
    """

    def __init__(self, llm_fn: Optional[Callable] = None, max_selections: int = MAX_SELECTIONS):
        self._llm_fn = llm_fn
        self._max_selections = max_selections
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    def select(self, query: str, memories: List[Dict[str, Any]],
               already_surfaced: set = None) -> List[Dict[str, Any]]:
        """Select the most relevant memories for a query.

        Args:
            query: The user's current query/task
            memories: All available memories [{category, fact/content, source_mode, ...}]
            already_surfaced: Set of memory IDs already shown this session

        Returns:
            List of up to max_selections most relevant memories
        """
        if not memories:
            return []

        # Filter already-surfaced memories
        surfaced = already_surfaced or set()
        candidates = [m for m in memories if self._memory_id(m) not in surfaced]

        if not candidates:
            return []

        # If few candidates, return all
        if len(candidates) <= self._max_selections:
            return candidates

        # Check cache
        cache_key = self._cache_key(query)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Try LLM-based selection
        if self._llm_fn:
            selected = self._select_with_llm(query, candidates)
            if selected:
                self._update_cache(cache_key, selected)
                return selected

        # Fallback: recency-based selection (most recent first)
        selected = self._select_by_recency(candidates)
        self._update_cache(cache_key, selected)
        return selected

    def _select_with_llm(self, query: str, candidates: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Use LLM to select relevant memories."""
        # Build compact headers for LLM
        headers = []
        for i, m in enumerate(candidates[:30]):  # Limit to 30 candidates for token budget
            category = m.get('category', m.get('type', '?'))
            content = str(m.get('fact', m.get('content', '')))[:100]
            headers.append(f"[{i}] ({category}) {content}")

        prompt = (
            f"Given this query: \"{query[:200]}\"\n\n"
            f"Which of these memories are most relevant? "
            f"Return ONLY the indices (e.g., 0,3,7) of the top {self._max_selections} "
            f"most relevant memories. If fewer are relevant, return fewer.\n\n"
            + "\n".join(headers)
        )

        try:
            import asyncio
            if asyncio.iscoroutinefunction(self._llm_fn):
                response = asyncio.get_event_loop().run_until_complete(self._llm_fn(prompt))
            else:
                response = self._llm_fn(prompt)

            # Parse indices from response
            indices = self._parse_indices(response, len(candidates))
            if indices:
                return [candidates[i] for i in indices[:self._max_selections]]
        except Exception as e:
            logger.debug(f"LLM memory selection failed: {e}")

        return None

    def _select_by_recency(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fallback: select most recent memories."""
        # Sort by timestamp if available, else by position
        def sort_key(m):
            ts = m.get('updated_at', m.get('created_at', ''))
            return ts if ts else ''

        sorted_mems = sorted(candidates, key=sort_key, reverse=True)
        return sorted_mems[:self._max_selections]

    def _parse_indices(self, response: str, max_idx: int) -> List[int]:
        """Parse memory indices from LLM response."""
        import re
        numbers = re.findall(r'\d+', response)
        indices = []
        for n in numbers:
            idx = int(n)
            if 0 <= idx < max_idx and idx not in indices:
                indices.append(idx)
        return indices

    @staticmethod
    def _memory_id(memory: Dict[str, Any]) -> str:
        """Generate a stable ID for a memory."""
        content = str(memory.get('fact', memory.get('content', '')))
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _cache_key(self, query: str) -> str:
        """Generate cache key from query."""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()[:16]

    def _update_cache(self, key: str, selected: List[Dict[str, Any]]):
        """Update cache with LRU eviction."""
        self._cache[key] = selected
        if len(self._cache) > CACHE_MAX:
            # Remove oldest entry
            oldest = next(iter(self._cache))
            del self._cache[oldest]

    def add_staleness_warnings(self, memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add staleness caveat to memories older than 1 day.

        Modifies memories in-place by adding '_staleness_caveat' field.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        for m in memories:
            ts_str = m.get('updated_at', m.get('created_at', ''))
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                days_old = (now - ts).days
                if days_old >= 1:
                    if days_old == 1:
                        m['_staleness_caveat'] = "This memory is 1 day old"
                    elif days_old < 7:
                        m['_staleness_caveat'] = f"This memory is {days_old} days old"
                    elif days_old < 30:
                        weeks = days_old // 7
                        m['_staleness_caveat'] = f"This memory is {weeks} week{'s' if weeks > 1 else ''} old — verify before acting"
                    else:
                        months = days_old // 30
                        m['_staleness_caveat'] = f"This memory is {months} month{'s' if months > 1 else ''} old — may be outdated"
            except Exception:
                pass
        return memories
