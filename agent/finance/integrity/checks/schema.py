"""Schema-level integrity: version, dedup uniqueness, FK presence.

These should pass even on an empty DB. If any fail, the schema or the
DAO is broken, which is upstream of every other class of bug.

Each ``check_*`` function takes a sqlite3 connection and returns
``{"pass": bool, "detail": str, "offenders": [..]?}``. The
registration list lives in ``agent/finance/integrity/core.py``.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict

from agent.finance.persistence import SCHEMA_VERSION


def check_schema_version(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT MAX(version) AS v FROM schema_version"
    ).fetchone()
    db_version = row["v"] if row else None
    if db_version is None:
        return {
            "pass": False,
            "detail": "schema_version table empty",
            "offenders": [{"reason": "no rows in schema_version"}],
        }
    if db_version != SCHEMA_VERSION:
        return {
            "pass": False,
            "detail": f"DB at v{db_version}, code at v{SCHEMA_VERSION}",
            "offenders": [{
                "db_version": db_version,
                "code_version": SCHEMA_VERSION,
            }],
        }
    return {"pass": True, "detail": f"v{SCHEMA_VERSION} on both"}


def check_signal_dedup_unique(conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = list(conn.execute(
        """
        SELECT dedup_key, COUNT(*) AS n FROM strategy_signals
        GROUP BY dedup_key HAVING n > 1
        """
    ))
    total = conn.execute("SELECT COUNT(*) AS n FROM strategy_signals").fetchone()["n"]
    if rows:
        return {
            "pass": False,
            "detail": f"{len(rows)} dedup_key collisions across {total} signals",
            "offenders": [{"dedup_key": r["dedup_key"], "count": r["n"]} for r in rows],
        }
    return {
        "pass": True,
        "detail": f"{total} / {total} signals have unique dedup_key",
    }


def check_lot_idempotency_unique(conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = list(conn.execute(
        """
        SELECT idempotency_key, COUNT(*) AS n FROM tax_lots
        WHERE idempotency_key IS NOT NULL
        GROUP BY idempotency_key HAVING n > 1
        """
    ))
    total_keyed = conn.execute(
        "SELECT COUNT(*) AS n FROM tax_lots WHERE idempotency_key IS NOT NULL"
    ).fetchone()["n"]
    if rows:
        return {
            "pass": False,
            "detail": f"{len(rows)} idempotency_key collisions across {total_keyed} keyed lots",
            "offenders": [{"key": r["idempotency_key"], "count": r["n"]} for r in rows],
        }
    return {
        "pass": True,
        "detail": f"{total_keyed} / {total_keyed} keyed lots have unique idempotency_key",
    }


def check_market_data_pk_unique(conn: sqlite3.Connection) -> Dict[str, Any]:
    # SQLite enforces PK uniqueness, but a dropped-and-recreated PK or a
    # bulk import from another tool could leave dups. Cheap to verify.
    rows = list(conn.execute(
        """
        SELECT symbol, market, trade_date, COUNT(*) AS n
        FROM market_data_daily
        GROUP BY symbol, market, trade_date HAVING n > 1
        """
    ))
    total = conn.execute("SELECT COUNT(*) AS n FROM market_data_daily").fetchone()["n"]
    if rows:
        return {
            "pass": False,
            "detail": f"{len(rows)} PK collisions across {total} bars",
            "offenders": [
                {"symbol": r["symbol"], "trade_date": r["trade_date"], "count": r["n"]}
                for r in rows[:20]
            ],
        }
    return {
        "pass": True,
        "detail": f"{total} / {total} bars have unique (symbol, market, trade_date)",
    }
