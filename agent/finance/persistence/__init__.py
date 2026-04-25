"""NeoMind fin persistence layer.

Adds a queryable SQLite store for market data, analysis runs, strategy
signals, and tax/compliance state. Sits **next to** the existing
analyses-as-files store under ``~/Desktop/Investment/<project>/``;
does not replace it. Both can coexist:

  - File store: human-readable per-analysis JSON, the data firewall.
  - SQLite store: queryable, indexed, supports scheduled pulls and
    cross-symbol analysis.

Default location: ``~/.neomind/fin/fin.db``
  (consistent with ``agent/memory/`` using ``~/.neomind/``)

Override via ``NEOMIND_FIN_DB`` env var.

Schema versioning is handled by ``db.ensure_schema()`` — call it once
at startup before any DAO use. Idempotent; safe across restarts.

Tax & compliance is a **first-class citizen** of this schema, not an
afterthought. Tables ``tax_lots``, ``wash_sale_events``,
``holding_period_snapshots``, and ``pdt_round_trips`` exist from V1
because retrofitting them across thousands of rows of historical
trades is far more painful than carrying a few empty columns from
day one.
"""

from agent.finance.persistence.db import (
    DEFAULT_DB_PATH,
    SCHEMA_VERSION,
    connect,
    ensure_schema,
    get_db_path,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "SCHEMA_VERSION",
    "connect",
    "ensure_schema",
    "get_db_path",
]
