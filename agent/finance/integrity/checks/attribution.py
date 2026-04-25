"""Attribution-level integrity: every fact carries provenance.

This is the **storage-side** counterpart to ``response_validator.py``'s
**Five Iron Rules** — specifically Rule 3: "Every data point has
source + timestamp". response_validator catches LLM responses that
emit numbers without source citations; the checks here catch DB
rows missing the same metadata.

Both must hold. An LLM that cites a source flawlessly while the
underlying data layer has empty ``source`` columns has the same
end-state as the inverse: unauditable. So we enforce at both ends.

Mirrors the project-wide ``VerifiedDataPoint`` convention from
``data_hub.py``.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict


def check_market_data_attributed(conn: sqlite3.Connection) -> Dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) AS n FROM market_data_daily").fetchone()["n"]
    bad = list(conn.execute(
        """
        SELECT symbol, trade_date, source, fetched_at FROM market_data_daily
        WHERE source IS NULL OR source = '' OR fetched_at IS NULL OR fetched_at = ''
        LIMIT 50
        """
    ))
    if bad:
        return {
            "pass": False,
            "detail": f"{len(bad)} / {total} bars missing source or fetched_at",
            "offenders": [
                {"symbol": r["symbol"], "trade_date": r["trade_date"],
                 "source": r["source"], "fetched_at": r["fetched_at"]}
                for r in bad
            ],
        }
    return {
        "pass": True,
        "detail": f"{total} / {total} bars carry source + fetched_at",
    }


def check_signal_run_fk(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Schema's FOREIGN KEY only enforces this on insert when foreign_keys
    pragma is on. A run row that gets deleted (status=cancelled cleanup
    later) can leave dangling refs. SET NULL is the on-delete action,
    so this should always pass — but check explicitly because the
    invariant matters more than the mechanism.
    """
    bad = list(conn.execute(
        """
        SELECT s.signal_id, s.run_id FROM strategy_signals s
        WHERE s.run_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM analysis_runs r WHERE r.run_id = s.run_id
          )
        LIMIT 50
        """
    ))
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM strategy_signals WHERE run_id IS NOT NULL"
    ).fetchone()["n"]
    if bad:
        return {
            "pass": False,
            "detail": f"{len(bad)} / {total} signals point at missing runs",
            "offenders": [{"signal_id": r["signal_id"], "run_id": r["run_id"]} for r in bad],
        }
    return {
        "pass": True,
        "detail": f"{total} / {total} signal→run references resolve",
    }


def check_scheduler_registry_alignment(conn: sqlite3.Connection) -> Dict[str, Any]:
    from agent.finance.scheduler.core import build_default_registry
    reg = build_default_registry()
    registered = set(reg.names())
    in_db = {
        r["job_name"] for r in conn.execute("SELECT job_name FROM scheduler_jobs")
    }

    missing_db = registered - in_db
    orphan_db = in_db - registered

    offenders = []
    if missing_db:
        offenders.extend({"job": j, "issue": "registered but no DB row"} for j in missing_db)
    if orphan_db:
        offenders.extend({"job": j, "issue": "DB row exists but not registered (stale?)"} for j in orphan_db)

    if offenders:
        return {
            "pass": False,
            "detail": f"{len(missing_db)} missing DB row, {len(orphan_db)} orphan DB row",
            "offenders": offenders,
        }
    return {
        "pass": True,
        "detail": f"{len(registered)} / {len(registered)} jobs aligned",
    }
