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
SCHEMA_VERSION = 4  # 2026-04-30: NeoMind Live — user_watchlist + signal_events + signal_confluences

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


class _AutoClosingConnection(sqlite3.Connection):
    """退出 ``with`` 块时: 先按 stdlib 语义提交/回滚, **然后关闭连接**。

    🔴 2026-07-31 真事故 (与 neomind-dashboard 的满血版同步修复):
    stdlib 的 ``with <sqlite3.Connection>`` **只管事务, 不关连接**。本仓 + dashboard
    合计 **568 处**写成 ``with connect() as conn:``, 全都以为出块就还回去了。
    短命脚本靠进程退出兜底, 所以长期没暴露; **长驻进程**每次调用泄漏 1 条连接 ×
    3 个 fd (db / -wal / -shm)。

    实测: scheduler 进程 (launchd, maxfiles 256) 攒到 **4,368 个 fd / 3,729 个 fin.db
    句柄**, 自 2026-07-28 起每个 job 都死在 ``Errno 24 Too many open files``
    → ``unable to open database file``, **35 个 job 里 34 个停摆 3 天**。

    改基类安全的依据 (2026-07-31 实测): 568 处**全部**是 ``with connect() as ...``,
    裸 ``x = connect()`` 0 处, 嵌套 ``with conn:`` 0 处 —— 没有跨多个 with 块复用连接的调用点。
    """

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a SQLite connection with project-wide pragmas applied.

    **用作 context manager**: ``with connect() as conn:`` —— 成功提交 / 异常回滚,
    并且**退出时自动关闭**(见 ``_AutoClosingConnection``)。
    需要跨多个 ``with`` 块复用同一条连接时, 用 ``contextlib.closing`` 显式管理。
    """
    path = db_path or get_db_path()
    _prepare_dir(path)
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None,
                           factory=_AutoClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


_SCHEMA_VERIFIED: dict[str, bool] = {}


def ensure_schema(db_path: Optional[Path] = None) -> int:
    """Apply the schema if not already present. Returns current version.

    Idempotent: safe to call on every process startup. Reads schema.sql
    once and executes its ``CREATE TABLE IF NOT EXISTS`` statements.
    Stamps ``schema_version`` if missing.

    Raises ``RuntimeError`` if the on-disk schema_version is *higher*
    than this code knows about — that means the DB was last touched
    by a newer build, and we refuse to operate on it lest we corrupt
    data.

    Performance: short-circuits on hot loops by remembering per-process
    that the schema has been validated for a given path. The first call
    runs the full executescript; subsequent calls return immediately.
    """
    cache_key = str(db_path) if db_path else str(get_db_path())
    if _SCHEMA_VERIFIED.get(cache_key):
        return SCHEMA_VERSION

    if not _SCHEMA_FILE.exists():
        raise FileNotFoundError(
            f"schema.sql missing at {_SCHEMA_FILE} — package is broken"
        )

    sql = _SCHEMA_FILE.read_text(encoding="utf-8")

    with connect(db_path) as conn:
        # executescript is the right tool for a multi-statement schema.
        conn.executescript(sql)

        # ── In-place column migrations ──────────────────────────────
        # The schema.sql CREATE TABLE statements all use IF NOT EXISTS
        # so existing tables don't pick up new columns. Add them here.
        # SQLite < 3.35 has no IF NOT EXISTS for ALTER TABLE, so we
        # gate via PRAGMA table_info (free, runs in microseconds).
        def _ensure_column(table: str, col: str, col_def: str) -> None:
            cur = conn.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in cur.fetchall()}
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                    logger.info("DB migration: added %s.%s", table, col)
                except Exception as exc:
                    logger.warning("DB migration: %s.%s failed: %s",
                                   table, col, exc)

        # 2026-05-04 — learning library: add kind / availability /
        # purchase_url so books can be a separate UI surface.
        _ensure_column("learning_cases", "kind",
                       "TEXT NOT NULL DEFAULT 'case'")
        _ensure_column("learning_cases", "availability", "TEXT")
        _ensure_column("learning_cases", "purchase_url", "TEXT")

        # 2026-05-07 — hub-and-spoke watchlist tiers.
        # Existing 9 rows default to tier='core' (intentional — they
        # were hand-added before the tier concept existed and are the
        # user's actual core names). parent_ticker/last_reviewed_at
        # stay NULL on existing rows (semantically correct: cores
        # have no parent; "never reviewed" is honest).
        _ensure_column("user_watchlist", "tier",
                       "TEXT NOT NULL DEFAULT 'core'")
        _ensure_column("user_watchlist", "parent_ticker", "TEXT")
        _ensure_column("user_watchlist", "last_reviewed_at", "TEXT")

        # 2026-05-10 — Phase W (decision feedback loop).
        # See plans/2026-05-10_lattice-onion-integration.md §6.
        # Notes can OPTIONALLY link to the trigger that prompted them
        # (a signal_event, a fact, or an active thesis). Three nullable
        # FK-style columns — never enforced at DB level since signals
        # may be deleted by retention jobs and we want note to outlive
        # its trigger.
        _ensure_column("stock_notes", "trigger_signal_id", "TEXT")
        _ensure_column("stock_notes", "trigger_fact_id", "INTEGER")
        _ensure_column("stock_notes", "trigger_thesis_id", "TEXT")

        # 2026-05-10 — Phase W Pillar 2 (algorithm correctness):
        # confidence + polarity + requires_reextract on extracted facts.
        # confidence: 0.0-1.0 LLM self-report or substring-match strength.
        # polarity: 'pro'/'contra'/'neutral' for PRO vs CONTRA forced
        #           display. NULL on existing rows (will be backfilled
        #           by re-extract OR remain unknown).
        # requires_reextract: 1 when extractor model bumped or user
        #           flagged via fact_corrections. UI shows warning.
        _ensure_column("stock_anchored_facts", "confidence", "REAL")
        _ensure_column("stock_anchored_facts", "polarity", "TEXT")
        _ensure_column("stock_anchored_facts", "requires_reextract",
                       "INTEGER NOT NULL DEFAULT 0")

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
            # Only log once per process — was hot-loop spam before.
            if not _SCHEMA_VERIFIED:
                logger.info("fin DB schema verified at v%d (%s)",
                            existing_version, cache_key)

    _SCHEMA_VERIFIED[cache_key] = True
    return SCHEMA_VERSION
