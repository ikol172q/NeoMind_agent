"""Temporal-consistency invariants: dates and durations make sense."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict


def check_run_durations(conn: sqlite3.Connection) -> Dict[str, Any]:
    bad = list(conn.execute(
        """
        SELECT run_id, started_at, completed_at, duration_seconds
        FROM analysis_runs
        WHERE completed_at IS NOT NULL
          AND (completed_at < started_at OR duration_seconds < 0)
        LIMIT 50
        """
    ))
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM analysis_runs WHERE completed_at IS NOT NULL"
    ).fetchone()["n"]
    if bad:
        return {
            "pass": False,
            "detail": f"{len(bad)} / {total} runs with bad timing",
            "offenders": [
                {"run_id": r["run_id"], "started_at": r["started_at"],
                 "completed_at": r["completed_at"], "duration": r["duration_seconds"]}
                for r in bad
            ],
        }
    return {
        "pass": True,
        "detail": f"{total} / {total} completed runs have monotonic timing",
    }


def check_lot_dates(conn: sqlite3.Connection) -> Dict[str, Any]:
    bad = list(conn.execute(
        """
        SELECT lot_id, open_date, close_date FROM tax_lots
        WHERE close_date IS NOT NULL AND close_date < open_date
        LIMIT 50
        """
    ))
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM tax_lots WHERE close_date IS NOT NULL"
    ).fetchone()["n"]
    if bad:
        return {
            "pass": False,
            "detail": f"{len(bad)} / {total} closed lots with close < open",
            "offenders": [
                {"lot_id": r["lot_id"], "open": r["open_date"], "close": r["close_date"]}
                for r in bad
            ],
        }
    return {
        "pass": True,
        "detail": f"{total} / {total} closed lots have monotonic dates",
    }


def check_duration_arithmetic(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Catches the case where the runner stamps a duration from a
    different clock than the timestamps. Tolerance: 1ms because ISO
    string truncation costs us up to 1s, but timing errors > 1s
    indicate a real bug."""
    rows = list(conn.execute(
        """
        SELECT run_id, started_at, completed_at, duration_seconds
        FROM analysis_runs
        WHERE completed_at IS NOT NULL AND duration_seconds IS NOT NULL
        """
    ))
    offenders = []
    for r in rows:
        try:
            s = datetime.fromisoformat(r["started_at"])
            c = datetime.fromisoformat(r["completed_at"])
            expected = (c - s).total_seconds()
        except ValueError:
            offenders.append({"run_id": r["run_id"], "reason": "non-ISO timestamp"})
            continue
        actual = float(r["duration_seconds"])
        # 1.5s tolerance — second-precision ISO strings drop sub-second
        # info on both endpoints (=2s combined slack is the worst case).
        if abs(actual - expected) > 1.5:
            offenders.append({
                "run_id": r["run_id"], "expected": expected, "actual": actual,
            })
    if offenders:
        return {
            "pass": False,
            "detail": f"{len(offenders)} / {len(rows)} runs have duration drift > 1.5s",
            "offenders": offenders[:50],
        }
    return {
        "pass": True,
        "detail": f"{len(rows)} / {len(rows)} runs have consistent duration",
    }
