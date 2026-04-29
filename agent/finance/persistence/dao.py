"""Data Access Objects for the fin persistence layer.

All write functions are **idempotent under repeated runs**:

    - ``upsert_market_data_daily`` uses INSERT OR REPLACE on the natural
      composite PK (symbol, market, trade_date). Re-running yesterday's
      pull replaces yesterday's row with the latest fetch — yfinance's
      adjusted_close is the most common reason values change between
      fetches (post-dividend / split adjustments propagate backwards).
    - ``add_universe_tickers`` uses INSERT OR IGNORE on the PK
      (symbol, market). Re-running with the same ticker list is a no-op.
    - ``record_signal`` computes a content-hash dedup_key and uses
      INSERT … ON CONFLICT DO UPDATE to bump ``last_seen_at`` and
      ``seen_count`` instead of inserting a second row. ``run_id`` is
      overwritten with the latest run, so the UI can answer "is this
      signal still being produced?".
    - ``add_tax_lot`` accepts an optional ``idempotency_key`` (CSV row
      hash, broker statement reference, etc.). Repeated ingest of the
      same statement won't duplicate lots.

Run-tracking helpers (``start_analysis_run`` / ``complete_analysis_run``)
do NOT dedup — every run is a real event and the schema records each
one. Dedup happens on the produced signals, not on the runs themselves.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ── time helper ──────────────────────────────────────────────────────


def _now_iso() -> str:
    """UTC timestamp in ISO 8601, second precision. Stable across processes."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── dedup key helpers ────────────────────────────────────────────────


def _round_for_key(value: Optional[float], decimals: int = 2) -> str:
    """Stable string form for hashing — None → '', floats → fixed decimals.

    We round prices to cents (2dp) so a signal regenerated with
    target_price=150.4900001 vs 150.49 still dedups. For broader
    bucketing (e.g., a "this strategy is firing on AAPL with target
    around $150") use coarser binning at the call site.
    """
    if value is None:
        return ""
    return f"{value:.{decimals}f}"


def compute_signal_dedup_key(
    *,
    symbol: str,
    market: str,
    strategy_id: str,
    horizon: str,
    signal_type: str,
    target_price: Optional[float],
    stop_loss: Optional[float],
) -> str:
    """16-hex-char content hash for strategy_signals.dedup_key.

    Two signals are "the same" iff this tuple matches. Reason text is
    intentionally NOT included — same actionable advice with reworded
    reason still dedups. Confidence and risk_level also aren't in the
    key: a signal that flips from confidence=0.6 to 0.7 across runs is
    still "the same advice" — its evolution is captured by
    ``last_seen_at`` and ``seen_count``.
    """
    canonical = "|".join([
        symbol.upper(),
        market.lower(),
        strategy_id.lower(),
        horizon.lower(),
        signal_type.lower(),
        _round_for_key(target_price),
        _round_for_key(stop_loss),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_lot_idempotency_key(
    *,
    account_id: str,
    symbol: str,
    market: str,
    open_date: str,
    open_price: float,
    open_quantity: float,
    source_ref: str = "",
) -> str:
    """24-hex-char content hash for tax_lots.idempotency_key.

    ``source_ref`` should be something stable from the upstream record
    (broker statement row id, CSV line hash). Without it, two genuinely
    distinct lots that happen to share (account, symbol, date, price,
    qty) would collide — pass at minimum the source filename + line
    number when ingesting.
    """
    canonical = "|".join([
        account_id,
        symbol.upper(),
        market.lower(),
        open_date,
        f"{open_price:.4f}",
        f"{open_quantity:.6f}",
        source_ref,
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


# ── universe DAO ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class TickerSpec:
    symbol: str
    market: str
    asset_class: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    notes: Optional[str] = None


def add_universe_tickers(conn: sqlite3.Connection, tickers: Iterable[TickerSpec]) -> int:
    """Insert tickers, skipping any that already exist. Returns rows added."""
    now = _now_iso()
    rows = [
        (t.symbol.upper(), t.market.lower(), t.asset_class.lower(),
         t.name, t.sector, t.industry, now, t.notes)
        for t in tickers
    ]
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO tickers_universe
            (symbol, market, asset_class, name, sector, industry, added_at, notes)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    return cur.rowcount or 0


def list_active_universe(
    conn: sqlite3.Connection,
    market: Optional[str] = None,
    asset_class: Optional[str] = None,
) -> List[sqlite3.Row]:
    """Return active tickers, optionally filtered by market/asset_class."""
    sql = "SELECT * FROM tickers_universe WHERE active = 1"
    args: List[Any] = []
    if market:
        sql += " AND market = ?"
        args.append(market.lower())
    if asset_class:
        sql += " AND asset_class = ?"
        args.append(asset_class.lower())
    sql += " ORDER BY symbol"
    return list(conn.execute(sql, args))


# ── market_data_daily DAO ────────────────────────────────────────────


def upsert_market_data_daily(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    market: str,
    bars: Sequence[Dict[str, Any]],
    source: str,
) -> int:
    """Idempotently upsert daily OHLCV rows. ``bars`` shape matches
    ``data_hub.FinanceDataHub.get_history`` output:
    ``[{"date", "open", "high", "low", "close", "volume", ...}, ...]``.

    INSERT OR REPLACE on (symbol, market, trade_date) is the right
    semantics here: yfinance's adjusted_close changes after splits or
    dividends, and we want the latest authoritative version. Returns
    rows written.
    """
    fetched = _now_iso()
    sym = symbol.upper()
    mkt = market.lower()

    rows = []
    for b in bars:
        # b["date"] is ISO-ish from yfinance — keep just the YYYY-MM-DD.
        raw_date = str(b.get("date", ""))
        trade_date = raw_date[:10]
        if not trade_date or len(trade_date) != 10 or trade_date[4] != "-":
            logger.debug("skipping bar with malformed date: %r", raw_date)
            continue
        rows.append((
            sym, mkt, trade_date,
            b.get("open"),
            b.get("high"),
            b.get("low"),
            b.get("close"),
            b.get("adjusted_close") if "adjusted_close" in b else b.get("close"),
            int(b["volume"]) if b.get("volume") is not None else None,
            source,
            fetched,
        ))

    if not rows:
        return 0

    conn.executemany(
        """
        INSERT OR REPLACE INTO market_data_daily
            (symbol, market, trade_date, open, high, low, close,
             adjusted_close, volume, source, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    return len(rows)


def get_latest_market_data(
    conn: sqlite3.Connection, symbol: str, market: str = "us", limit: int = 60
) -> List[sqlite3.Row]:
    """Return last N daily bars for a symbol, newest first."""
    return list(conn.execute(
        """
        SELECT * FROM market_data_daily
        WHERE symbol = ? AND market = ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (symbol.upper(), market.lower(), limit),
    ))


# ── analysis_runs DAO ────────────────────────────────────────────────


def start_analysis_run(
    conn: sqlite3.Connection,
    *,
    job_name: str,
    run_type: str = "scheduled",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Open a new run row, return its run_id (uuid4). Caller must call
    ``complete_analysis_run`` (or ``fail_analysis_run``) when done.
    """
    run_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO analysis_runs
            (run_id, run_type, job_name, started_at, status, metadata_json)
        VALUES (?,?,?,?,?,?)
        """,
        (
            run_id, run_type, job_name, _now_iso(), "running",
            json.dumps(metadata) if metadata else None,
        ),
    )
    return run_id


def complete_analysis_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str = "completed",
    error_message: Optional[str] = None,
    universe_size: Optional[int] = None,
    rows_written: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Close a run row. Computes duration_seconds from started_at.

    ``metadata`` (optional) is merged into ``metadata_json`` so a job
    can record its rich summary (counts, sample rows, explanation)
    next to the run row — that's what the UI's "Last Audit" panel reads
    when answering "what did this run actually do?".
    """
    cur = conn.execute(
        "SELECT started_at, metadata_json FROM analysis_runs WHERE run_id = ?",
        (run_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"unknown run_id {run_id}")

    started = datetime.fromisoformat(row["started_at"])
    completed = datetime.now(timezone.utc)
    duration = (completed - started).total_seconds()

    if metadata is not None:
        # Merge: keep prior keys (e.g. "limit" from start_analysis_run),
        # let summary keys overwrite. JSON-stringify only at the end.
        prior_raw = row["metadata_json"]
        prior: Dict[str, Any] = {}
        if prior_raw:
            try:
                prior = json.loads(prior_raw) or {}
                if not isinstance(prior, dict):
                    prior = {"_legacy": prior}
            except Exception:  # pragma: no cover — defensive
                prior = {}
        prior.update(metadata)
        merged_json: Optional[str] = json.dumps(prior, default=str)
    else:
        merged_json = None

    conn.execute(
        """
        UPDATE analysis_runs
           SET completed_at = ?, status = ?, error_message = ?,
               universe_size = COALESCE(?, universe_size),
               rows_written = COALESCE(?, rows_written),
               duration_seconds = ?,
               metadata_json = COALESCE(?, metadata_json)
         WHERE run_id = ?
        """,
        (
            completed.isoformat(timespec="seconds"),
            status, error_message, universe_size, rows_written, duration,
            merged_json,
            run_id,
        ),
    )


def list_recent_runs(
    conn: sqlite3.Connection,
    job_name: Optional[str] = None,
    limit: int = 20,
    *,
    started_after: Optional[str] = None,
    started_before: Optional[str] = None,
) -> List[sqlite3.Row]:
    """List runs, newest-first.

    Optional ``started_after`` / ``started_before`` are inclusive ISO 8601
    bounds.  Both are compared lexicographically against the
    ``started_at`` column, which is fine because the column is always
    written as zulu-suffixed ISO (``2026-04-28T04:39:32Z`` / ``+00:00``)
    and lex-order matches chronological order for that format.

    Pass either or both to scope the query (e.g. "all runs from
    2026-04-26 onwards", "all runs in 2026-04 week").
    """
    sql = "SELECT * FROM analysis_runs"
    where: List[str] = []
    args: List[Any] = []
    if job_name:
        where.append("job_name = ?")
        args.append(job_name)
    if started_after:
        where.append("started_at >= ?")
        args.append(started_after)
    if started_before:
        where.append("started_at <= ?")
        args.append(started_before)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC LIMIT ?"
    args.append(limit)
    return list(conn.execute(sql, args))


# ── strategy_signals DAO ─────────────────────────────────────────────


def record_signal(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    market: str,
    strategy_id: str,
    horizon: str,
    signal_type: str,
    confidence: float,
    risk_level: str,
    reason: str,
    target_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    max_loss_amount: Optional[float] = None,
    tax_warning: Optional[str] = None,
    pdt_relevant: bool = False,
    sources: Optional[List[Dict[str, Any]]] = None,
    run_id: Optional[str] = None,
) -> int:
    """UPSERT a signal. Returns ``signal_id``.

    On dedup hit (same key as an existing row): keeps original
    ``created_at``, updates ``last_seen_at``, increments ``seen_count``,
    and overwrites ``run_id`` with the latest run + ``confidence`` /
    ``reason`` / etc. so the UI shows freshest evaluation.

    The ``confidence`` evolution is therefore lossy across runs — if you
    need a time series of confidence values, write a separate
    ``signal_confidence_history`` table; but for "is this advice still
    live?" the current model is enough.
    """
    key = compute_signal_dedup_key(
        symbol=symbol, market=market, strategy_id=strategy_id,
        horizon=horizon, signal_type=signal_type,
        target_price=target_price, stop_loss=stop_loss,
    )
    now = _now_iso()
    sources_json = json.dumps(sources) if sources else None

    conn.execute(
        """
        INSERT INTO strategy_signals
            (dedup_key, run_id, symbol, market, strategy_id, horizon,
             signal_type, confidence, risk_level, reason, target_price,
             stop_loss, max_loss_amount, tax_warning, pdt_relevant,
             sources_json, created_at, last_seen_at, seen_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        ON CONFLICT(dedup_key) DO UPDATE SET
            run_id          = excluded.run_id,
            confidence      = excluded.confidence,
            risk_level      = excluded.risk_level,
            reason          = excluded.reason,
            max_loss_amount = excluded.max_loss_amount,
            tax_warning     = excluded.tax_warning,
            pdt_relevant    = excluded.pdt_relevant,
            sources_json    = excluded.sources_json,
            last_seen_at    = excluded.last_seen_at,
            seen_count      = strategy_signals.seen_count + 1
        """,
        (
            key, run_id, symbol.upper(), market.lower(), strategy_id,
            horizon, signal_type, float(confidence), risk_level, reason,
            target_price, stop_loss, max_loss_amount, tax_warning,
            1 if pdt_relevant else 0, sources_json, now, now,
        ),
    )

    cur = conn.execute(
        "SELECT signal_id FROM strategy_signals WHERE dedup_key = ?", (key,),
    )
    return int(cur.fetchone()["signal_id"])


def list_recent_signals(
    conn: sqlite3.Connection,
    *,
    symbol: Optional[str] = None,
    strategy_id: Optional[str] = None,
    limit: int = 50,
) -> List[sqlite3.Row]:
    """Most recently *seen* signals — ordered by last_seen_at DESC."""
    sql = "SELECT * FROM strategy_signals WHERE 1=1"
    args: List[Any] = []
    if symbol:
        sql += " AND symbol = ?"
        args.append(symbol.upper())
    if strategy_id:
        sql += " AND strategy_id = ?"
        args.append(strategy_id)
    sql += " ORDER BY last_seen_at DESC LIMIT ?"
    args.append(limit)
    return list(conn.execute(sql, args))


# ── tax_lots DAO ─────────────────────────────────────────────────────


def add_tax_lot(
    conn: sqlite3.Connection,
    *,
    account_id: str = "main",
    symbol: str,
    market: str,
    asset_class: str,
    open_date: str,
    open_price: float,
    open_quantity: float,
    open_fees: float = 0.0,
    is_simulated: bool = False,
    cost_basis_method: str = "FIFO",
    notes: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Optional[int]:
    """Insert a new lot. If ``idempotency_key`` is provided AND a lot
    with that key already exists, returns ``None`` (no insert).
    Otherwise returns the new lot_id.
    """
    now = _now_iso()
    try:
        cur = conn.execute(
            """
            INSERT INTO tax_lots
                (idempotency_key, account_id, symbol, market, asset_class,
                 is_simulated, open_date, open_price, open_quantity,
                 open_fees, cost_basis_method, notes, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                idempotency_key, account_id, symbol.upper(), market.lower(),
                asset_class.lower(), 1 if is_simulated else 0,
                open_date, float(open_price), float(open_quantity),
                float(open_fees), cost_basis_method, notes, now, now,
            ),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        if "uniq_lots_idem" in str(exc) or "UNIQUE constraint" in str(exc):
            logger.info(
                "tax_lot dedup hit on idempotency_key=%s — no new row",
                idempotency_key,
            )
            return None
        raise
