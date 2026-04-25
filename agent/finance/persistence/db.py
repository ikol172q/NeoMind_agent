"""SQLite connection + migration runner for the fin persistence layer.

Usage:

    from agent.finance.persistence import connect, ensure_schema

    ensure_schema()               # idempotent, safe at startup
    with connect() as conn:
        conn.execute("INSERT INTO ...")
        conn.commit()

Design notes:

- ``ensure_schema()`` runs ``schema.sql`` (which is full of
  ``CREATE TABLE IF NOT EXISTS``) and stamps a ``schema_version`` row.
  Calling it again is a no-op.
- The DB file lives at ``~/.neomind/fin/fin.db`` by default (override
  with ``NEOMIND_FIN_DB``). Directory is created with 0o700 to match
  ``agent/memory/shared_memory.py``.
- ``connect()`` returns a stdlib ``sqlite3.Connection`` configured
  with ``foreign_keys=ON``, WAL journal, and ``Row`` factory so callers
  get dict-like rows.
- We deliberately don't use SQLAlchemy. The schema is small and
  hand-written SQL keeps the cognitive load low for a single-developer
  fin platform — the day we hit a real ORM problem we add it.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Bumped manually when schema.sql adds a backwards-incompatible change.
# Compatible additions (new tables, new nullable columns) keep the same
# version. Breaking changes (renamed columns, dropped tables) increment.
SCHEMA_VERSION = 1

DEFAULT_DB_PATH = Path.home() / ".neomind" / "fin" / "fin.db"
_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def get_db_path() -> Path:
    """Resolve the SQLite file location.

    Order of precedence:
      1. ``NEOMIND_FIN_DB`` env var (full path)
      2. ``~/.neomind/fin/fin.db``
    """
    override = os.getenv("NEOMIND_FIN_DB")
    if override:
        return Path(override).expanduser()
    return DEFAULT_DB_PATH


def _prepare_dir(db_path: Path) -> None:
    """Create the parent dir at 0o700, like agent/memory/shared_memory."""
    parent = db_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(parent, 0o700)
    except OSError:
        # Filesystems that don't honour chmod (some FUSE mounts, NTFS).
        # Not fatal — the DB itself is still created mode 0600 by default.
        logger.debug("chmod 0o700 not honoured on %s", parent)


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a SQLite connection with project-wide pragmas applied.

    Caller is responsible for ``commit()`` / ``close()``. Use as a
    context manager (``with connect() as conn:``) for auto-commit on
    success, rollback on exception.
    """
    path = db_path or get_db_path()
    _prepare_dir(path)
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def ensure_schema(db_path: Optional[Path] = None) -> int:
    """Apply the schema if not already present. Returns current version.

    Idempotent: safe to call on every process startup. Reads schema.sql
    once and executes its ``CREATE TABLE IF NOT EXISTS`` statements.
    Stamps ``schema_version`` if missing.

    Raises ``RuntimeError`` if the on-disk schema_version is *higher*
    than this code knows about — that means the DB was last touched
    by a newer build, and we refuse to operate on it lest we corrupt
    data.
    """
    if not _SCHEMA_FILE.exists():
        raise FileNotFoundError(
            f"schema.sql missing at {_SCHEMA_FILE} — package is broken"
        )

    sql = _SCHEMA_FILE.read_text(encoding="utf-8")

    with connect(db_path) as conn:
        # executescript is the right tool for a multi-statement schema.
        conn.executescript(sql)

        cur = conn.execute("SELECT MAX(version) AS v FROM schema_version")
        row = cur.fetchone()
        existing_version = row["v"] if row and row["v"] is not None else None

        if existing_version is None:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO schema_version (version, applied_at, description) "
                "VALUES (?, ?, ?)",
                (SCHEMA_VERSION, now, "initial schema"),
            )
            logger.info("fin DB initialised at v%d (%s)", SCHEMA_VERSION, get_db_path())
        elif existing_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"fin DB at {get_db_path()} is at schema v{existing_version} "
                f"but this build only knows v{SCHEMA_VERSION}. Refusing to "
                f"operate to avoid corruption — upgrade the build or "
                f"point NEOMIND_FIN_DB at a different file."
            )
        elif existing_version < SCHEMA_VERSION:
            # Future migration runner hooks in here. For V1 we have a
            # single version and the IF NOT EXISTS DDL is enough.
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO schema_version (version, applied_at, description) "
                "VALUES (?, ?, ?)",
                (SCHEMA_VERSION, now, f"upgrade from v{existing_version}"),
            )
            logger.info(
                "fin DB upgraded v%d → v%d (%s)",
                existing_version, SCHEMA_VERSION, get_db_path(),
            )
        else:
            logger.debug("fin DB schema already at v%d", existing_version)

    return SCHEMA_VERSION
