# agent/finance/usage_tracker.py
"""
LLM Usage Tracker — SQLite-backed, real-time, persists across container restarts.

Records every LLM call:
- Provider + model (litellm:local, deepseek:deepseek-chat, etc.)
- Token count (estimated from response length)
- Latency (ms)
- Cost estimate
- Success/failure
- Chat ID (which conversation triggered it)

Stored on Docker volume → survives restart.
xbar reads this DB directly → no log parsing.
"""

import os
import time
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass


# Default DB path — prefer named volume for performance.
def _default_usage_db_path() -> str:
    explicit = os.getenv("NEOMIND_USAGE_DB")
    if explicit:
        return explicit
    vol_path = Path("/data/neomind/db/usage.db")
    if vol_path.parent.exists():
        return str(vol_path)
    return str(Path(os.getenv("HOME", "/data")) / ".neomind" / "usage.db")

DEFAULT_DB_PATH = _default_usage_db_path()

# Cost per call estimates (rough, for display only)
COST_PER_1K_TOKENS = {
    "local": 0,              # Ollama = free
    "deepseek-chat": 0.00014,      # $0.14/M input
    "deepseek-reasoner": 0.00055,   # $0.55/M input
    "glm-4.5-flash": 0.0001,
    "glm-5": 0.0003,
}


@dataclass
class UsageRecord:
    provider: str       # "litellm", "deepseek", "zai"
    model: str          # "local", "deepseek-chat", etc.
    tokens_est: int     # estimated tokens (from response chars)
    latency_ms: int     # round-trip time in milliseconds
    cost_est: float     # estimated cost in USD
    success: bool
    chat_id: int = 0
    error: str = ""
    timestamp: str = ""


class UsageTracker:
    """SQLite-backed LLM usage tracking.

    Usage:
        tracker = UsageTracker()
        tracker.record("litellm", "local", tokens=150, latency_ms=800, success=True, chat_id=123)
        today = tracker.get_today()
        # → {"calls": 5, "tokens": 2340, "cost": 0.0, "by_model": {"local": 4, "deepseek-chat": 1}}
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS usage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                provider    TEXT NOT NULL,
                model       TEXT NOT NULL,
                tokens_est  INTEGER DEFAULT 0,
                latency_ms  INTEGER DEFAULT 0,
                cost_est    REAL DEFAULT 0,
                success     INTEGER DEFAULT 1,
                chat_id     INTEGER DEFAULT 0,
                error       TEXT DEFAULT '',
                timestamp   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(timestamp);
            CREATE INDEX IF NOT EXISTS idx_usage_model ON usage(model);
        """)
        self._conn.commit()

    # ── Record ───────────────────────────────────────────────

    def record(self, provider: str, model: str, tokens: int = 0,
               latency_ms: int = 0, success: bool = True,
               chat_id: int = 0, error: str = ""):
        """Record a single LLM call."""
        now = datetime.now(timezone.utc).isoformat()

        # Estimate cost
        cost_rate = COST_PER_1K_TOKENS.get(model, 0.0001)
        cost = (tokens / 1000) * cost_rate

        self._conn.execute("""
            INSERT INTO usage (provider, model, tokens_est, latency_ms, cost_est,
                               success, chat_id, error, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (provider, model, tokens, latency_ms, cost, 1 if success else 0,
              chat_id, error, now))
        self._conn.commit()

    # ── Query ────────────────────────────────────────────────

    def get_today(self) -> Dict:
        """Get today's usage summary."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._get_summary(f"timestamp >= '{today}'")

    def get_range(self, days: int = 7) -> Dict:
        """Get usage for the last N days."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        return self._get_summary(f"timestamp >= '{since}'")

    def _get_summary(self, where: str) -> Dict:
        rows = self._conn.execute(f"""
            SELECT provider, model, tokens_est, latency_ms, cost_est, success, error
            FROM usage WHERE {where}
        """).fetchall()

        calls = len(rows)
        tokens = sum(r["tokens_est"] for r in rows)
        cost = sum(r["cost_est"] for r in rows)
        success = sum(1 for r in rows if r["success"])
        failed = calls - success
        avg_latency = int(sum(r["latency_ms"] for r in rows) / max(calls, 1))

        by_model = {}
        by_provider = {}
        for r in rows:
            m = r["model"]
            p = r["provider"]
            by_model[m] = by_model.get(m, 0) + 1
            by_provider[p] = by_provider.get(p, 0) + 1

        errors = [r["error"] for r in rows if r["error"]][-5:]  # last 5 errors

        return {
            "calls": calls,
            "tokens": tokens,
            "cost": round(cost, 6),
            "success": success,
            "failed": failed,
            "avg_latency_ms": avg_latency,
            "by_model": by_model,
            "by_provider": by_provider,
            "recent_errors": errors,
        }

    def get_recent(self, limit: int = 20) -> List[Dict]:
        """Get most recent usage records."""
        rows = self._conn.execute("""
            SELECT provider, model, tokens_est, latency_ms, cost_est, success, chat_id, error, timestamp
            FROM usage ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── For xbar (external read) ─────────────────────────────

    def format_xbar_summary(self) -> str:
        """Format today's usage for xbar display. Returns pipe-separated string."""
        today = self.get_today()
        model_str = ", ".join(f"{m}:{c}" for m, c in today["by_model"].items()) if today["by_model"] else "无"
        return (
            f"{today['calls']}|{today['tokens']}|{today['cost']:.4f}|"
            f"{today['avg_latency_ms']}|{today['success']}|{today['failed']}|{model_str}"
        )

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ── Singleton ────────────────────────────────────────────────

_tracker: Optional[UsageTracker] = None

def get_usage_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
