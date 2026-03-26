# agent/search/metrics.py
"""
Search Quality Metrics — tracks search performance over time.

Records per-search stats:
  - Which sources were used / failed
  - Latency per source
  - Result count and extraction success rate
  - Query type classification
  - Cache hit rate

Persists to a JSON lines file (~/.neomind/search_metrics.jsonl).
Provides aggregate reports via `get_report()`.
"""

import os
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


class SearchMetrics:
    """Lightweight search quality tracker.

    Records each search event and computes aggregate stats.
    Zero external dependencies — pure Python.
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self._storage_dir = storage_dir or os.path.expanduser("~/.neomind")
        self._log_path = os.path.join(self._storage_dir, "search_metrics.jsonl")
        self._session_events: List[Dict] = []
        # Ensure directory exists
        try:
            os.makedirs(self._storage_dir, exist_ok=True)
        except Exception:
            self._log_path = None

    def record(
        self,
        query: str,
        query_type: str,
        sources_used: List[str],
        sources_failed: List[str],
        result_count: int,
        extraction_count: int,
        reranked: bool,
        cached: bool,
        latency_ms: float,
        expanded_queries: Optional[List[str]] = None,
    ):
        """Record a single search event."""
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "query": query[:200],  # truncate for storage
            "query_type": query_type,
            "sources_used": sources_used,
            "sources_failed": sources_failed,
            "result_count": result_count,
            "extraction_count": extraction_count,
            "reranked": reranked,
            "cached": cached,
            "latency_ms": round(latency_ms, 1),
            "expansion_count": len(expanded_queries) if expanded_queries else 1,
        }
        self._session_events.append(event)
        self._persist(event)

    def _persist(self, event: Dict):
        """Append event to JSONL log file."""
        if not self._log_path:
            return
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_session_stats(self) -> Dict:
        """Get stats for current session only."""
        return self._compute_stats(self._session_events)

    def get_all_stats(self) -> Dict:
        """Get stats from all persisted events."""
        events = self._load_all_events()
        return self._compute_stats(events)

    def _load_all_events(self) -> List[Dict]:
        """Load all events from disk."""
        events = []
        if not self._log_path or not os.path.exists(self._log_path):
            return events
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass
        return events

    def _compute_stats(self, events: List[Dict]) -> Dict:
        """Compute aggregate statistics from events."""
        if not events:
            return {"total_searches": 0, "message": "No search data yet."}

        total = len(events)
        latencies = [e["latency_ms"] for e in events]
        cache_hits = sum(1 for e in events if e.get("cached"))
        reranked = sum(1 for e in events if e.get("reranked"))
        total_results = sum(e.get("result_count", 0) for e in events)
        total_extractions = sum(e.get("extraction_count", 0) for e in events)

        # Source usage frequency
        source_counts = defaultdict(int)
        source_failures = defaultdict(int)
        for e in events:
            for s in e.get("sources_used", []):
                source_counts[s] += 1
            for s in e.get("sources_failed", []):
                source_failures[s] += 1

        # Query type distribution
        type_counts = defaultdict(int)
        for e in events:
            type_counts[e.get("query_type", "unknown")] += 1

        return {
            "total_searches": total,
            "avg_latency_ms": round(sum(latencies) / total, 1),
            "p50_latency_ms": round(sorted(latencies)[total // 2], 1),
            "p95_latency_ms": round(sorted(latencies)[int(total * 0.95)], 1) if total > 1 else latencies[0],
            "cache_hit_rate": round(cache_hits / total * 100, 1),
            "rerank_rate": round(reranked / total * 100, 1),
            "avg_results_per_search": round(total_results / total, 1),
            "avg_extractions_per_search": round(total_extractions / total, 1),
            "source_usage": dict(sorted(source_counts.items(), key=lambda x: -x[1])),
            "source_failures": dict(sorted(source_failures.items(), key=lambda x: -x[1])),
            "query_type_distribution": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        }

    def format_report(self, all_time: bool = False) -> str:
        """Format a human-readable metrics report."""
        stats = self.get_all_stats() if all_time else self.get_session_stats()

        if stats["total_searches"] == 0:
            return "No search data yet. Run some searches first."

        lines = [
            "Search Quality Metrics",
            "=" * 50,
            f"  Total searches: {stats['total_searches']}",
            f"  Avg latency: {stats['avg_latency_ms']}ms (P50: {stats['p50_latency_ms']}ms, P95: {stats['p95_latency_ms']}ms)",
            f"  Cache hit rate: {stats['cache_hit_rate']}%",
            f"  Rerank rate: {stats['rerank_rate']}%",
            f"  Avg results/search: {stats['avg_results_per_search']}",
            f"  Avg extractions/search: {stats['avg_extractions_per_search']}",
            "",
            "  Source usage:",
        ]
        for source, count in stats["source_usage"].items():
            fail = stats["source_failures"].get(source, 0)
            reliability = round((1 - fail / (count + fail)) * 100, 1) if (count + fail) > 0 else 100.0
            lines.append(f"    {source}: {count} uses ({reliability}% reliable)")

        if stats.get("source_failures"):
            lines.append("\n  Source failures:")
            for source, count in stats["source_failures"].items():
                lines.append(f"    {source}: {count} failures")

        lines.append("\n  Query type distribution:")
        for qtype, count in stats["query_type_distribution"].items():
            pct = round(count / stats["total_searches"] * 100, 1)
            lines.append(f"    {qtype}: {count} ({pct}%)")

        return "\n".join(lines)

    def clear(self):
        """Clear all metrics data."""
        self._session_events.clear()
        if self._log_path and os.path.exists(self._log_path):
            try:
                os.remove(self._log_path)
            except Exception:
                pass
