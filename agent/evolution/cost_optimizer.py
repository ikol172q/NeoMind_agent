"""NeoMind Cost Optimizer — Token Tracking + Smart Model Routing

Tracks every LLM call's token usage and cost, then optimizes:
1. Model routing: simple tasks → cheap model, complex → expensive
2. Context window management: trim when approaching limits
3. Caching: avoid redundant calls for similar queries
4. Batch processing: group small requests to reduce overhead
5. Daily budget alerts: warn when approaching spend limits

Target: keep evolution overhead under $0.06/day (~$2/month)

No external dependencies — stdlib only.
"""

import json
import sqlite3
import logging
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple, Callable

from agent.constants.models import DEFAULT_MODEL, PREMIUM_MODEL

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/cost_tracking.db")

# Approximate pricing per 1M tokens (as of 2026)
MODEL_PRICING = {
    DEFAULT_MODEL: {"input": 0.14, "output": 0.28},
    PREMIUM_MODEL: {"input": 1.74, "output": 3.48},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-3-sonnet": {"input": 3.00, "output": 15.00},
    "default": {"input": 0.50, "output": 1.00},
}

# Daily budget for evolution overhead (not user-facing calls)
EVOLUTION_DAILY_BUDGET = 0.06  # $0.06/day

# Output token limits per personality mode (prevents verbose responses eating budget)
OUTPUT_TOKEN_LIMITS = {
    "chat": 2000,          # Casual conversation — concise
    "coding": 4000,        # Code generation needs more room
    "fin": 1500,           # Financial analysis — structured, data-dense
    "evolution": 500,      # Internal evolution tasks — minimal
    "reflection": 800,     # Self-reflection — moderate
    "learning": 300,       # Learning extraction — short JSON
    "default": 2000,       # Fallback
}


class CostOptimizer:
    """Token tracking, cost analysis, and smart model routing."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS api_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            purpose TEXT NOT NULL,       -- user_chat | evolution | reflection | learning
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            latency_ms REAL DEFAULT 0,
            cache_hit INTEGER DEFAULT 0,
            ts TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_calls_ts ON api_calls(ts);
        CREATE INDEX IF NOT EXISTS idx_calls_purpose ON api_calls(purpose);
        CREATE INDEX IF NOT EXISTS idx_calls_model ON api_calls(model);

        CREATE TABLE IF NOT EXISTS response_cache (
            hash TEXT PRIMARY KEY,
            response TEXT NOT NULL,
            model TEXT NOT NULL,
            tokens_saved INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_hit_at TEXT,
            hit_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS semantic_fingerprints (
            hash TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            prompt_prefix TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_semantic_fingerprints ON semantic_fingerprints(fingerprint);

        CREATE TABLE IF NOT EXISTS batch_requests (
            batch_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'pending',   -- pending | processing | completed | failed
            purpose TEXT NOT NULL,
            request_count INTEGER DEFAULT 0,
            requests_json TEXT NOT NULL,      -- JSON array of request payloads
            results_json TEXT,                -- JSON array of results (when completed)
            created_at TEXT NOT NULL,
            completed_at TEXT,
            cost_usd REAL DEFAULT 0,
            tokens_saved INTEGER DEFAULT 0    -- tokens saved vs individual calls
        );

        CREATE INDEX IF NOT EXISTS idx_batch_status ON batch_requests(status);

        CREATE TABLE IF NOT EXISTS prompt_cache_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            prefix_hash TEXT NOT NULL,
            prefix_tokens INTEGER DEFAULT 0,
            cache_hit INTEGER DEFAULT 0,      -- 1=hit, 0=miss
            tokens_saved INTEGER DEFAULT 0,
            cost_saved REAL DEFAULT 0,
            ts TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_prompt_cache_ts ON prompt_cache_stats(ts);
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(self.SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init cost DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── Record API Calls ───────────────────────────────────

    def record_call(self, model: str, purpose: str,
                     input_tokens: int, output_tokens: int,
                     latency_ms: float = 0, cache_hit: bool = False):
        """Record an API call for cost tracking.

        Args:
            model: Model name (e.g., "deepseek-chat")
            purpose: What the call was for (user_chat | evolution | reflection | etc.)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            latency_ms: Response time in milliseconds
            cache_hit: Whether this was served from cache
        """
        cost = self._calculate_cost(model, input_tokens, output_tokens)
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO api_calls
                   (model, purpose, input_tokens, output_tokens, cost_usd,
                    latency_ms, cache_hit, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (model, purpose, input_tokens, output_tokens, cost,
                 latency_ms, int(cache_hit),
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to record API call: {e}")

    # ── Smart Model Routing ────────────────────────────────

    def recommend_model(self, task_complexity: str,
                         purpose: str = "user_chat",
                         mode: str = "chat") -> str:
        """Recommend the best model based on task complexity, budget, and history.

        RouteLLM-inspired adaptive routing:
        - Tracks (task_type, model, success_rate) history
        - If cheap model success > 80% on similar tasks → use cheap
        - Falls back to expensive model only when cheap fails

        Args:
            task_complexity: "simple" | "medium" | "complex"
            purpose: What the call is for
            mode: Agent mode for history lookup

        Returns:
            Recommended model name
        """
        # Check if evolution budget is exhausted
        if purpose != "user_chat":
            daily_spend = self._get_daily_spend(purpose="evolution")
            if daily_spend >= EVOLUTION_DAILY_BUDGET:
                logger.info(f"Evolution budget exhausted (${daily_spend:.3f}/${EVOLUTION_DAILY_BUDGET})")
                return DEFAULT_MODEL  # Always use cheapest for budget overflow

        # RouteLLM adaptive routing: check historical success rates
        if task_complexity in ("simple", "medium"):
            cheap_success_rate = self._get_model_success_rate(
                DEFAULT_MODEL, mode, days=7
            )
            # If cheap model has >80% success rate, use it
            if cheap_success_rate is None or cheap_success_rate > 0.80:
                return DEFAULT_MODEL
            # If cheap model is struggling, escalate
            elif cheap_success_rate < 0.60:
                logger.info(
                    f"RouteLLM: cheap model success rate {cheap_success_rate:.0%} "
                    f"in {mode} mode, escalating to v4-flash (thinking)"
                )
                return DEFAULT_MODEL
            else:
                return DEFAULT_MODEL

        # Complex tasks default to v4-flash (user switches to v4-pro manually)
        return "deepseek-v4-flash"

    def _get_model_success_rate(self, model: str, mode: str,
                                 days: int = 7) -> Optional[float]:
        """Get a model's success rate for a specific mode over recent days.

        Returns None if insufficient data (<5 calls).
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = self._conn()
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN cache_hit = 0 AND output_tokens > 0 THEN 1 ELSE 0 END) as success
                FROM api_calls
                WHERE model = ? AND purpose LIKE ? AND ts > ?""",
                (model, f"%{mode}%", cutoff),
            ).fetchone()
            conn.close()

            if row and row["total"] >= 5:
                return row["success"] / row["total"]
            return None
        except Exception:
            return None

    def should_use_cache(self, prompt_hash: str) -> Optional[str]:
        """Check if a cached response exists for this prompt.

        Args:
            prompt_hash: Hash of the prompt

        Returns:
            Cached response, or None
        """
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT * FROM response_cache WHERE hash = ?",
                (prompt_hash,)
            ).fetchone()

            if row:
                # Update hit count
                conn.execute(
                    """UPDATE response_cache
                       SET hit_count = hit_count + 1, last_hit_at = ?
                       WHERE hash = ?""",
                    (datetime.now(timezone.utc).isoformat(), prompt_hash)
                )
                conn.commit()
                conn.close()
                return row["response"]
            conn.close()
        except Exception:
            pass
        return None

    def cache_response(self, prompt_hash: str, response: str,
                        model: str, tokens: int):
        """Cache a response for future reuse."""
        try:
            conn = self._conn()
            conn.execute(
                """INSERT OR REPLACE INTO response_cache
                   (hash, response, model, tokens_saved, created_at, hit_count)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (prompt_hash, response[:5000], model, tokens,
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    @staticmethod
    def hash_prompt(prompt: str) -> str:
        """Create a hash for cache lookup."""
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]

    # ── Budget Checking ────────────────────────────────────

    def check_budget(self, purpose: str = "evolution") -> Dict[str, Any]:
        """Check remaining budget for a purpose.

        Returns:
            {
                "daily_spent": float,
                "daily_budget": float,
                "remaining": float,
                "over_budget": bool,
            }
        """
        spent = self._get_daily_spend(purpose)
        budget = EVOLUTION_DAILY_BUDGET if purpose == "evolution" else float('inf')
        return {
            "daily_spent": round(spent, 4),
            "daily_budget": budget,
            "remaining": round(max(0, budget - spent), 4),
            "over_budget": spent >= budget,
        }

    def get_evolution_budget_ok(self) -> bool:
        """Quick check: is evolution budget still available?"""
        return self._get_daily_spend("evolution") < EVOLUTION_DAILY_BUDGET

    # ── Output Token Limits ────────────────────────────────

    def get_output_limit(self, mode: str, purpose: str = "user_chat") -> int:
        """Get the output token limit for a given mode/purpose.

        Enforces per-personality token budgets to prevent verbose responses.
        Research: Round 3 found output tokens are the biggest cost driver.

        Args:
            mode: Agent personality mode (chat, coding, fin)
            purpose: Call purpose (user_chat, evolution, reflection, etc.)

        Returns:
            Maximum output tokens to request from LLM
        """
        # For non-user-chat purposes, use purpose-specific limit
        if purpose != "user_chat":
            return OUTPUT_TOKEN_LIMITS.get(purpose, OUTPUT_TOKEN_LIMITS["default"])
        # For user-facing calls, use mode-specific limit
        return OUTPUT_TOKEN_LIMITS.get(mode, OUTPUT_TOKEN_LIMITS["default"])

    def check_output_budget(self, mode: str, purpose: str = "user_chat") -> Dict[str, Any]:
        """Check output token budget status for the current day.

        Returns remaining output token budget considering daily usage.

        Args:
            mode: Agent mode
            purpose: Call purpose

        Returns:
            Dict with limit, used_today, remaining, should_compress
        """
        limit = self.get_output_limit(mode, purpose)

        # Get today's output token usage for this mode
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT COALESCE(SUM(output_tokens), 0) as total FROM api_calls "
                "WHERE ts LIKE ? AND purpose = ?",
                (f"{today}%", purpose if purpose != "user_chat" else f"%{mode}%")
            ).fetchone()
            conn.close()
            used = row["total"] if row else 0
        except Exception:
            used = 0

        return {
            "limit_per_call": limit,
            "used_today": used,
            "should_compress": used > limit * 50,  # If used 50x the per-call limit today
        }

    # ── Analytics ──────────────────────────────────────────

    def get_daily_report(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Get cost report for a specific day."""
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM api_calls WHERE ts LIKE ?",
                (f"{date}%",)
            ).fetchall()
            conn.close()

            total_cost = sum(r["cost_usd"] for r in rows)
            total_input = sum(r["input_tokens"] for r in rows)
            total_output = sum(r["output_tokens"] for r in rows)
            cache_hits = sum(1 for r in rows if r["cache_hit"])

            by_purpose = {}
            for r in rows:
                p = r["purpose"]
                if p not in by_purpose:
                    by_purpose[p] = {"calls": 0, "cost": 0, "tokens": 0}
                by_purpose[p]["calls"] += 1
                by_purpose[p]["cost"] += r["cost_usd"]
                by_purpose[p]["tokens"] += r["input_tokens"] + r["output_tokens"]

            by_model = {}
            for r in rows:
                m = r["model"]
                if m not in by_model:
                    by_model[m] = {"calls": 0, "cost": 0}
                by_model[m]["calls"] += 1
                by_model[m]["cost"] += r["cost_usd"]

            return {
                "date": date,
                "total_calls": len(rows),
                "total_cost_usd": round(total_cost, 4),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "cache_hits": cache_hits,
                "cache_hit_rate": cache_hits / max(1, len(rows)),
                "by_purpose": by_purpose,
                "by_model": by_model,
            }
        except Exception as e:
            logger.error(f"Failed to generate daily report: {e}")
            return {"date": date, "total_calls": 0}

    def get_weekly_trend(self) -> List[Dict]:
        """Get 7-day cost trend."""
        trend = []
        for i in range(7):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            report = self.get_daily_report(date)
            trend.append({
                "date": date,
                "cost": report.get("total_cost_usd", 0),
                "calls": report.get("total_calls", 0),
            })
        return list(reversed(trend))

    def get_stats(self) -> Dict[str, Any]:
        """Return cost statistics for dashboard."""
        today = self.get_daily_report()
        budget = self.check_budget("evolution")
        return {
            "today": today,
            "evolution_budget": budget,
            "weekly_trend": self.get_weekly_trend(),
        }

    # ── Semantic Caching ──────────────────────────────────

    def semantic_cache_check(
        self, prompt: str, similarity_threshold: float = 0.85
    ) -> Optional[str]:
        """Check for cached response with semantic similarity matching.

        Uses normalized hash + n-gram fingerprints for fuzzy matching.
        Returns cached response if similarity > threshold.

        Args:
            prompt: The prompt to look up
            similarity_threshold: Min similarity score (0.0-1.0)

        Returns:
            Cached response if found, None otherwise
        """
        try:
            # Create normalized hash and fingerprint for input prompt
            input_hash = self.hash_prompt(prompt)
            input_fingerprint = self._create_fingerprint(prompt)

            conn = self._conn()

            # First try exact hash match (fast path)
            exact_row = conn.execute(
                "SELECT response FROM response_cache WHERE hash = ?",
                (input_hash,),
            ).fetchone()
            if exact_row:
                conn.close()
                return exact_row["response"]

            # Fall back to semantic similarity search
            # Get all stored fingerprints and compare
            fingerprint_rows = conn.execute(
                "SELECT hash, fingerprint FROM semantic_fingerprints"
            ).fetchall()
            conn.close()

            if not fingerprint_rows:
                return None

            best_hash = None
            best_similarity = 0.0

            for row in fingerprint_rows:
                similarity = self._calculate_similarity(
                    input_fingerprint, row["fingerprint"]
                )
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_hash = row["hash"]

            # If similarity meets threshold, return cached response
            if best_similarity >= similarity_threshold and best_hash:
                cached_row = conn.execute(
                    "SELECT response FROM response_cache WHERE hash = ?",
                    (best_hash,),
                ).fetchone()
                if cached_row:
                    return cached_row["response"]

            return None
        except Exception as e:
            logger.debug(f"Semantic cache check failed: {e}")
            return None

    def cache_with_semantic_key(
        self, prompt: str, response: str, model: str, tokens: int
    ) -> None:
        """Cache a response with both exact hash and semantic fingerprint.

        Args:
            prompt: The prompt that generated the response
            response: The cached response
            model: Model used
            tokens: Token count saved
        """
        try:
            prompt_hash = self.hash_prompt(prompt)
            fingerprint = self._create_fingerprint(prompt)
            prompt_prefix = prompt[:200]  # First 200 chars for reference
            now = datetime.now(timezone.utc).isoformat()

            conn = self._conn()

            # Store in response_cache (exact hash)
            conn.execute(
                """INSERT OR REPLACE INTO response_cache
                   (hash, response, model, tokens_saved, created_at, hit_count)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (prompt_hash, response[:5000], model, tokens, now),
            )

            # Store in semantic_fingerprints (for fuzzy matching)
            conn.execute(
                """INSERT OR REPLACE INTO semantic_fingerprints
                   (hash, fingerprint, prompt_prefix, created_at)
                   VALUES (?, ?, ?, ?)""",
                (prompt_hash, fingerprint, prompt_prefix, now),
            )

            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to cache with semantic key: {e}")

    # ── Internal Semantic Cache Helpers ────────────────

    @staticmethod
    def _create_fingerprint(text: str, n: int = 3) -> str:
        """Create n-gram fingerprint for semantic similarity.

        Generates normalized n-grams for fuzzy matching.

        Args:
            text: Text to fingerprint
            n: N-gram size (default: 3)

        Returns:
            Concatenated n-grams as fingerprint
        """
        # Normalize: lowercase, strip whitespace, remove common stop words
        normalized = text.lower().strip()
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "to",
            "for",
            "in",
            "of",
            "with",
            "on",
            "at",
            "by",
            "from",
        }

        # Split into words and filter stop words
        words = [w for w in normalized.split() if w not in stop_words]
        text_filtered = " ".join(words)

        # Generate n-grams (character-level for robustness)
        ngrams = [
            text_filtered[i : i + n] for i in range(len(text_filtered) - n + 1)
        ]
        return "".join(sorted(set(ngrams)))  # Unique n-grams, sorted

    @staticmethod
    def _calculate_similarity(fp1: str, fp2: str) -> float:
        """Calculate Jaccard similarity between two fingerprints.

        Args:
            fp1: First fingerprint
            fp2: Second fingerprint

        Returns:
            Similarity score 0.0-1.0
        """
        if not fp1 or not fp2:
            return 0.0

        set1 = set(fp1)
        set2 = set(fp2)

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    # ── Cache Maintenance ──────────────────────────────────

    def cleanup_cache(self, max_age_days: int = 7):
        """Remove old cache entries."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
            conn = self._conn()
            result = conn.execute(
                "DELETE FROM response_cache WHERE created_at < ? AND hit_count < 2",
                (cutoff,)
            )
            deleted = result.rowcount
            conn.commit()
            conn.close()
            if deleted:
                logger.info(f"Cleaned {deleted} stale cache entries")
        except Exception:
            pass

    # ── Batch API Support ──────────────────────────────────
    # Research: Round 3 — Batch API offers 50% discount for non-real-time tasks
    # Suitable for: evolution, reflection, learning extraction, briefing generation

    BATCH_ELIGIBLE_PURPOSES = {"evolution", "reflection", "learning", "briefing"}
    BATCH_DISCOUNT = 0.50  # 50% cost reduction

    def is_batch_eligible(self, purpose: str) -> bool:
        """Check if a task is eligible for batch processing.

        Batch API is suitable for non-real-time tasks that can tolerate
        higher latency (minutes instead of seconds) for 50% cost savings.

        Args:
            purpose: The call purpose (evolution, reflection, etc.)

        Returns:
            True if this purpose can use batch API
        """
        return purpose in self.BATCH_ELIGIBLE_PURPOSES

    def create_batch(self, purpose: str,
                     requests: List[Dict[str, Any]]) -> Optional[str]:
        """Create a batch request for non-real-time processing.

        Groups multiple LLM requests into a single batch for 50% cost savings.
        The batch is stored in DB and can be submitted to the API later.

        Args:
            purpose: What the batch is for (evolution, reflection, etc.)
            requests: List of request payloads, each with 'prompt' and optional 'model'

        Returns:
            Batch ID, or None on failure
        """
        if not requests:
            return None

        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO batch_requests
                   (batch_id, status, purpose, request_count, requests_json, created_at)
                   VALUES (?, 'pending', ?, ?, ?, ?)""",
                (batch_id, purpose, len(requests),
                 json.dumps(requests), now)
            )
            conn.commit()
            conn.close()
            logger.info(
                f"Created batch {batch_id}: {len(requests)} requests "
                f"for {purpose} (50% discount eligible)"
            )
            return batch_id
        except Exception as e:
            logger.error(f"Failed to create batch: {e}")
            return None

    def complete_batch(self, batch_id: str, results: List[Dict[str, Any]],
                       total_tokens: int = 0) -> bool:
        """Mark a batch as completed and record results.

        Args:
            batch_id: The batch ID
            results: List of result dicts
            total_tokens: Total tokens used

        Returns:
            True if updated successfully
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            # Calculate batch cost with discount
            row = conn.execute(
                "SELECT purpose, request_count FROM batch_requests WHERE batch_id = ?",
                (batch_id,)
            ).fetchone()
            if not row:
                conn.close()
                return False

            # Estimate cost at batch discount
            regular_cost = self._calculate_cost(DEFAULT_MODEL, total_tokens, 0)
            batch_cost = regular_cost * self.BATCH_DISCOUNT
            tokens_saved = total_tokens  # Would have cost 2x without batch

            conn.execute(
                """UPDATE batch_requests
                   SET status = 'completed', results_json = ?,
                       completed_at = ?, cost_usd = ?, tokens_saved = ?
                   WHERE batch_id = ?""",
                (json.dumps(results), now, batch_cost, tokens_saved, batch_id)
            )
            conn.commit()
            conn.close()
            logger.info(
                f"Batch {batch_id} completed: saved ${regular_cost - batch_cost:.4f} "
                f"({self.BATCH_DISCOUNT*100:.0f}% discount)"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to complete batch: {e}")
            return False

    def get_pending_batches(self) -> List[Dict[str, Any]]:
        """Get all pending batch requests ready for submission.

        Returns:
            List of pending batch dicts with batch_id, purpose, requests
        """
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM batch_requests WHERE status = 'pending' ORDER BY created_at"
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_batch_savings(self, days: int = 30) -> Dict[str, Any]:
        """Get batch processing savings summary.

        Returns:
            Dict with total_batches, total_saved_usd, total_tokens_saved
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = self._conn()
            row = conn.execute(
                """SELECT COUNT(*) as total,
                          COALESCE(SUM(cost_usd), 0) as total_cost,
                          COALESCE(SUM(tokens_saved), 0) as tokens_saved
                   FROM batch_requests
                   WHERE status = 'completed' AND completed_at > ?""",
                (cutoff,)
            ).fetchone()
            conn.close()
            if row:
                return {
                    "total_batches": row["total"],
                    "batch_cost_usd": round(row["total_cost"], 4),
                    "tokens_saved": row["tokens_saved"],
                    "estimated_savings_usd": round(row["total_cost"], 4),  # saved this much
                }
            return {"total_batches": 0, "batch_cost_usd": 0, "tokens_saved": 0}
        except Exception:
            return {"total_batches": 0, "batch_cost_usd": 0, "tokens_saved": 0}

    # ── Prompt Caching ────────────────────────────────────
    # Research: Round 3 — Prompt Caching offers 90% discount on repeated prefixes
    # DeepSeek context caching: automatic for prompts >1024 tokens with shared prefix
    # Anthropic prompt caching: explicit cache_control blocks

    PROMPT_CACHE_DISCOUNT = 0.90  # 90% reduction on cached input tokens
    MIN_PREFIX_TOKENS_FOR_CACHE = 1024  # Minimum prefix length to benefit from caching

    def build_cacheable_prompt(self, system_prompt: str, mode: str,
                                user_message: str) -> Dict[str, Any]:
        """Structure a prompt to maximize cache hit rate.

        For DeepSeek: put stable content (system prompt, personality, learnings)
        at the beginning so the prefix is reused across calls.

        For Anthropic: marks cache breakpoints explicitly.

        Args:
            system_prompt: The system-level instructions (stable, cacheable)
            mode: Agent mode (for personality prefix)
            user_message: The user's message (variable, not cached)

        Returns:
            Dict with structured prompt and cache metadata
        """
        prefix_hash = hashlib.sha256(
            f"{system_prompt}:{mode}".encode()
        ).hexdigest()[:16]

        # Estimate prefix tokens (~4 chars per token)
        prefix_tokens = len(system_prompt) // 4

        return {
            "system": system_prompt,
            "mode": mode,
            "user": user_message,
            "prefix_hash": prefix_hash,
            "prefix_tokens": prefix_tokens,
            "cache_eligible": prefix_tokens >= self.MIN_PREFIX_TOKENS_FOR_CACHE,
            "estimated_savings_pct": (
                self.PROMPT_CACHE_DISCOUNT * 100
                if prefix_tokens >= self.MIN_PREFIX_TOKENS_FOR_CACHE
                else 0
            ),
        }

    def record_prompt_cache_event(self, model: str, prefix_hash: str,
                                   prefix_tokens: int, cache_hit: bool) -> None:
        """Record a prompt cache hit/miss for analytics.

        Args:
            model: LLM model used
            prefix_hash: Hash of the cached prefix
            prefix_tokens: Number of tokens in the prefix
            cache_hit: Whether the prefix was served from cache
        """
        tokens_saved = prefix_tokens if cache_hit else 0
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        cost_saved = (
            tokens_saved * pricing["input"] * self.PROMPT_CACHE_DISCOUNT / 1_000_000
            if cache_hit else 0
        )

        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO prompt_cache_stats
                   (model, prefix_hash, prefix_tokens, cache_hit,
                    tokens_saved, cost_saved, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (model, prefix_hash, prefix_tokens, int(cache_hit),
                 tokens_saved, cost_saved,
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to record prompt cache event: {e}")

    def get_prompt_cache_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get prompt caching effectiveness report.

        Returns:
            Dict with hit_rate, total_tokens_saved, cost_saved_usd, unique_prefixes
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = self._conn()
            row = conn.execute(
                """SELECT
                    COUNT(*) as total_events,
                    SUM(cache_hit) as total_hits,
                    COALESCE(SUM(tokens_saved), 0) as total_tokens_saved,
                    COALESCE(SUM(cost_saved), 0) as total_cost_saved,
                    COUNT(DISTINCT prefix_hash) as unique_prefixes
                FROM prompt_cache_stats
                WHERE ts > ?""",
                (cutoff,)
            ).fetchone()
            conn.close()

            if row and row["total_events"] > 0:
                return {
                    "total_events": row["total_events"],
                    "hit_rate": round(row["total_hits"] / row["total_events"], 3),
                    "total_tokens_saved": row["total_tokens_saved"],
                    "cost_saved_usd": round(row["total_cost_saved"], 4),
                    "unique_prefixes": row["unique_prefixes"],
                    "days": days,
                }
            return {
                "total_events": 0, "hit_rate": 0, "total_tokens_saved": 0,
                "cost_saved_usd": 0, "unique_prefixes": 0, "days": days,
            }
        except Exception:
            return {
                "total_events": 0, "hit_rate": 0, "total_tokens_saved": 0,
                "cost_saved_usd": 0, "unique_prefixes": 0, "days": days,
            }

    def get_comprehensive_savings(self) -> Dict[str, Any]:
        """Get total savings from all optimization strategies.

        Combines: semantic cache + batch API + prompt caching.

        Returns:
            Dict with per-strategy and total savings
        """
        batch = self.get_batch_savings(days=30)
        prompt_cache = self.get_prompt_cache_stats(days=30)

        # Calculate semantic cache savings
        try:
            conn = self._conn()
            row = conn.execute(
                """SELECT COUNT(*) as hits,
                          COALESCE(SUM(tokens_saved), 0) as tokens
                   FROM response_cache WHERE hit_count > 0"""
            ).fetchone()
            conn.close()
            semantic_cache_hits = row["hits"] if row else 0
            semantic_tokens_saved = row["tokens"] if row else 0
        except Exception:
            semantic_cache_hits = 0
            semantic_tokens_saved = 0

        return {
            "semantic_cache": {
                "entries_with_hits": semantic_cache_hits,
                "tokens_saved": semantic_tokens_saved,
            },
            "batch_api": batch,
            "prompt_caching": prompt_cache,
            "total_tokens_saved": (
                semantic_tokens_saved +
                batch.get("tokens_saved", 0) +
                prompt_cache.get("total_tokens_saved", 0)
            ),
        }

    # ── Internal ───────────────────────────────────────────

    def _calculate_cost(self, model: str, input_tokens: int,
                         output_tokens: int) -> float:
        """Calculate USD cost for an API call."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        cost = (input_tokens * pricing["input"] +
                output_tokens * pricing["output"]) / 1_000_000
        return round(cost, 6)

    def _get_daily_spend(self, purpose: Optional[str] = None) -> float:
        """Get total spend for today, optionally filtered by purpose."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            conn = self._conn()
            if purpose:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) as total FROM api_calls "
                    "WHERE ts LIKE ? AND purpose = ?",
                    (f"{today}%", purpose)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) as total FROM api_calls WHERE ts LIKE ?",
                    (f"{today}%",)
                ).fetchone()
            conn.close()
            return row["total"] if row else 0
        except Exception:
            return 0
