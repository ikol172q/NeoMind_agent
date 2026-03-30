"""NeoMind Behavior Drift Detector — PSI-Based Monitoring

Monitors agent behavior metrics over time and detects drift
using Population Stability Index (PSI).

PSI = Σ (actual_pct - expected_pct) * ln(actual_pct / expected_pct)
  PSI < 0.1  → No significant drift
  PSI 0.1-0.25 → Moderate drift, needs attention
  PSI > 0.25 → Significant drift, action required

Research: Round 5 — without monitoring, agents show 20-30% performance
degradation within 6 months due to distribution shift in inputs,
model updates, and accumulated self-modifications.

No external dependencies — stdlib only.
"""

import json
import math
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/drift_monitoring.db")

# PSI thresholds
PSI_NO_DRIFT = 0.1
PSI_MODERATE = 0.25

# Metrics to monitor
MONITORED_METRICS = [
    "response_latency_ms",
    "output_tokens_per_request",
    "task_success_rate",
    "cache_hit_rate",
    "error_rate",
    "user_satisfaction",
    "cost_per_request",
]

# How many bins for PSI calculation
PSI_BINS = 10

# Baseline window: first 7 days of data
BASELINE_WINDOW_DAYS = 7

# Current window: most recent 7 days
CURRENT_WINDOW_DAYS = 7


class DriftDetector:
    """Monitors agent behavior metrics and detects drift using PSI.

    Usage:
        detector = DriftDetector()

        # Record metric samples
        detector.record("response_latency_ms", 150.0)
        detector.record("task_success_rate", 0.92)

        # Check for drift
        report = detector.check_drift()
        if report["overall_status"] == "drift_detected":
            alert(report)
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS metric_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            mode TEXT DEFAULT 'all',
            ts TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_metric_ts ON metric_samples(metric, ts);
        CREATE INDEX IF NOT EXISTS idx_metric_mode ON metric_samples(metric, mode);

        CREATE TABLE IF NOT EXISTS baseline_stats (
            metric TEXT PRIMARY KEY,
            mean REAL,
            std REAL,
            min_val REAL,
            max_val REAL,
            bin_edges TEXT,          -- JSON array of bin edges
            bin_counts TEXT,         -- JSON array of expected bin counts (normalized)
            sample_count INTEGER,
            computed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS drift_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric TEXT NOT NULL,
            psi_score REAL NOT NULL,
            status TEXT NOT NULL,    -- no_drift | moderate | significant
            baseline_period TEXT,
            current_period TEXT,
            ts TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_drift_ts ON drift_events(ts);
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(self.SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init drift DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def record(self, metric: str, value: float, mode: str = "all") -> None:
        """Record a metric sample.

        Args:
            metric: Metric name (e.g., "response_latency_ms")
            value: Metric value
            mode: Agent mode this was recorded in
        """
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO metric_samples (metric, value, mode, ts) VALUES (?, ?, ?, ?)",
                (metric, value, mode, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to record metric: {e}")

    def compute_baseline(self, metric: str,
                          days: int = BASELINE_WINDOW_DAYS) -> bool:
        """Compute baseline statistics for a metric.

        Uses the first N days of data as the baseline distribution.

        Args:
            metric: Metric name
            days: How many days of data to use as baseline

        Returns:
            True if baseline computed successfully
        """
        try:
            conn = self._conn()

            # Get earliest data point
            earliest = conn.execute(
                "SELECT MIN(ts) FROM metric_samples WHERE metric = ?",
                (metric,)
            ).fetchone()[0]

            if not earliest:
                conn.close()
                return False

            cutoff = (datetime.fromisoformat(earliest) + timedelta(days=days)).isoformat()

            rows = conn.execute(
                "SELECT value FROM metric_samples WHERE metric = ? AND ts <= ? ORDER BY value",
                (metric, cutoff)
            ).fetchall()

            if len(rows) < PSI_BINS * 2:  # Need minimum samples
                conn.close()
                return False

            values = [r[0] for r in rows]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = math.sqrt(variance) if variance > 0 else 1.0
            min_val = min(values)
            max_val = max(values)

            # Compute histogram bin edges
            bin_width = (max_val - min_val) / PSI_BINS if max_val > min_val else 1.0
            bin_edges = [min_val + i * bin_width for i in range(PSI_BINS + 1)]

            # Compute normalized bin counts
            bin_counts = [0] * PSI_BINS
            for v in values:
                idx = min(int((v - min_val) / bin_width), PSI_BINS - 1)
                bin_counts[idx] += 1

            total = sum(bin_counts)
            bin_pcts = [max(c / total, 0.001) for c in bin_counts]  # Floor at 0.001 to avoid log(0)

            conn.execute(
                """INSERT OR REPLACE INTO baseline_stats
                   (metric, mean, std, min_val, max_val, bin_edges, bin_counts,
                    sample_count, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (metric, mean, std, min_val, max_val,
                 json.dumps(bin_edges), json.dumps(bin_pcts),
                 len(values), datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            conn.close()
            logger.info(f"Baseline computed for {metric}: mean={mean:.2f}, std={std:.2f}, n={len(values)}")
            return True
        except Exception as e:
            logger.error(f"Failed to compute baseline for {metric}: {e}")
            return False

    def calculate_psi(self, metric: str,
                       days: int = CURRENT_WINDOW_DAYS) -> Optional[float]:
        """Calculate PSI between baseline and current distribution.

        PSI = Σ (actual_pct - expected_pct) * ln(actual_pct / expected_pct)

        Args:
            metric: Metric name
            days: Current window size in days

        Returns:
            PSI score, or None if insufficient data
        """
        try:
            conn = self._conn()

            # Load baseline
            baseline = conn.execute(
                "SELECT * FROM baseline_stats WHERE metric = ?",
                (metric,)
            ).fetchone()

            if not baseline:
                conn.close()
                return None

            expected_pcts = json.loads(baseline["bin_counts"])
            bin_edges = json.loads(baseline["bin_edges"])

            # Get current window data
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            rows = conn.execute(
                "SELECT value FROM metric_samples WHERE metric = ? AND ts > ?",
                (metric, cutoff)
            ).fetchall()
            conn.close()

            if len(rows) < PSI_BINS:
                return None

            values = [r[0] for r in rows]
            min_val = bin_edges[0]
            max_val = bin_edges[-1]
            bin_width = (max_val - min_val) / PSI_BINS if max_val > min_val else 1.0

            # Compute current bin counts
            actual_counts = [0] * PSI_BINS
            for v in values:
                idx = min(max(int((v - min_val) / bin_width), 0), PSI_BINS - 1)
                actual_counts[idx] += 1

            total = sum(actual_counts)
            actual_pcts = [max(c / total, 0.001) for c in actual_counts]

            # Calculate PSI
            psi = sum(
                (a - e) * math.log(a / e)
                for a, e in zip(actual_pcts, expected_pcts)
            )

            return round(psi, 4)
        except Exception as e:
            logger.error(f"Failed to calculate PSI for {metric}: {e}")
            return None

    def check_drift(self) -> Dict[str, Any]:
        """Run drift detection across all monitored metrics.

        Returns:
            Comprehensive drift report
        """
        results = {}
        overall_status = "no_drift"

        for metric in MONITORED_METRICS:
            psi = self.calculate_psi(metric)
            if psi is None:
                results[metric] = {"status": "insufficient_data", "psi": None}
                continue

            if psi > PSI_MODERATE:
                status = "significant"
                overall_status = "drift_detected"
            elif psi > PSI_NO_DRIFT:
                status = "moderate"
                if overall_status != "drift_detected":
                    overall_status = "moderate_drift"
            else:
                status = "no_drift"

            results[metric] = {"status": status, "psi": psi}

            # Record drift event
            try:
                conn = self._conn()
                conn.execute(
                    "INSERT INTO drift_events (metric, psi_score, status, ts) VALUES (?, ?, ?, ?)",
                    (metric, psi, status, datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

        return {
            "overall_status": overall_status,
            "metrics": results,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "thresholds": {"no_drift": PSI_NO_DRIFT, "moderate": PSI_MODERATE},
        }

    def get_drift_history(self, days: int = 30,
                           limit: int = 100) -> List[Dict]:
        """Get drift event history."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM drift_events WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                (cutoff, limit)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get drift monitoring statistics."""
        try:
            conn = self._conn()
            sample_count = conn.execute(
                "SELECT COUNT(*) FROM metric_samples"
            ).fetchone()[0]
            baseline_count = conn.execute(
                "SELECT COUNT(*) FROM baseline_stats"
            ).fetchone()[0]
            drift_events = conn.execute(
                "SELECT COUNT(*) FROM drift_events WHERE status != 'no_drift'"
            ).fetchone()[0]
            conn.close()

            return {
                "total_samples": sample_count,
                "baselines_computed": baseline_count,
                "drift_events": drift_events,
                "monitored_metrics": MONITORED_METRICS,
            }
        except Exception:
            return {"total_samples": 0, "baselines_computed": 0}
