-- NeoMind fin persistence — SQLite schema V1
--
-- Design principles:
--   1. Tax/compliance is first-class. tax_lots / wash_sale_events /
--      pdt_round_trips exist from V1 even when empty. Adding these
--      retroactively means migrating historical trades — much harder.
--   2. Every fact carries (source, fetched_at) so we can reason about
--      data freshness and provenance, matching the project-wide
--      VerifiedDataPoint convention from data_hub.py.
--   3. Cron-style state lives in DB, not on disk-as-files: scheduler
--      restarts must NOT lose "last_run_at".
--   4. Soft enums via CHECK constraints — fast, no extra tables, easy
--      to evolve.
--   5. Foreign keys declared and enforced (PRAGMA foreign_keys=ON in
--      db.py). Composite PKs preferred over surrogate where natural.
--   6. **Idempotency** is enforced in schema, not relied on from DAO
--      callers. A scheduler that retries, a backfill that overlaps,
--      and a debug rerun must NEVER produce duplicate rows for the
--      same conceptual fact. Mechanisms:
--        - Natural composite PKs (market_data_daily, tickers_universe)
--        - UNIQUE constraints on tuples that identify "the same thing"
--          across runs (strategy_signals.dedup_key, wash_sale_events,
--          pdt_round_trips, tax_lots.idempotency_key)
--        - DAO writes use INSERT OR REPLACE (when later runs supersede)
--          or ON CONFLICT DO UPDATE (when we want "last_seen_at" /
--          "seen_count" semantics on a stable canonical row).
--      The dedup_key columns are content hashes computed by the DAO,
--      stable across processes; see dao.py.
--
-- Schema version handshake (see db.py):
--   schema_version row tells the runtime which migration applied last.
--   A mismatch blocks startup with a clear "run migration X" message.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- ─── Schema versioning ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS schema_version (
    version       INTEGER PRIMARY KEY,
    applied_at    TEXT NOT NULL,         -- ISO 8601 UTC
    description   TEXT
);

-- ─── Universe: what we track ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tickers_universe (
    symbol         TEXT NOT NULL,
    market         TEXT NOT NULL CHECK (market IN ('us','cn','hk','crypto','global')),
    asset_class    TEXT NOT NULL CHECK (asset_class IN ('stock','etf','adr','option','crypto','futures','bond','fund')),
    active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    sector         TEXT,
    industry       TEXT,
    name           TEXT,
    added_at       TEXT NOT NULL,
    notes          TEXT,
    PRIMARY KEY (symbol, market)
);

CREATE INDEX IF NOT EXISTS idx_universe_active   ON tickers_universe(active);
CREATE INDEX IF NOT EXISTS idx_universe_class    ON tickers_universe(asset_class);

-- ─── Market data: daily OHLCV ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS market_data_daily (
    symbol            TEXT NOT NULL,
    market            TEXT NOT NULL,
    trade_date        TEXT NOT NULL,         -- 'YYYY-MM-DD' market local
    open              REAL,
    high              REAL,
    low               REAL,
    close             REAL,
    adjusted_close    REAL,
    volume            INTEGER,
    source            TEXT NOT NULL,
    fetched_at        TEXT NOT NULL,
    PRIMARY KEY (symbol, market, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_md_daily_date ON market_data_daily(trade_date);

-- ─── Analysis runs: every batch (scheduled or manual) ─────────────────

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id            TEXT PRIMARY KEY,       -- uuid4
    run_type          TEXT NOT NULL CHECK (run_type IN ('scheduled','manual','force_rerun','backfill')),
    job_name          TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    completed_at      TEXT,
    status            TEXT NOT NULL CHECK (status IN ('running','completed','failed','cancelled')) DEFAULT 'running',
    error_message     TEXT,
    universe_size     INTEGER,
    rows_written      INTEGER,
    duration_seconds  REAL,
    metadata_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_job   ON analysis_runs(job_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON analysis_runs(status);

-- ─── Strategy signals: every actionable output ─────────────────────────
--
-- Dedup model: two signals are "the same" if their dedup_key matches.
-- DAO computes dedup_key = sha256 of a canonical tuple
--   (symbol, market, strategy_id, horizon, signal_type,
--    target_price_rounded, stop_loss_rounded)
-- truncated to 16 hex chars. Reason text is *not* in the key — same
-- actionable advice with reworded reason still dedups.
--
-- On dedup hit: created_at stays (= first-seen), last_seen_at updates,
-- seen_count increments, run_id is overwritten to the *latest* run
-- (so the UI can show "this signal is still being produced as of run X").

CREATE TABLE IF NOT EXISTS strategy_signals (
    signal_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key         TEXT NOT NULL UNIQUE,
    run_id            TEXT,
    symbol            TEXT NOT NULL,
    market            TEXT NOT NULL,
    strategy_id       TEXT NOT NULL,           -- e.g., 'covered_call_etf', 'earnings_drift', 'lattice_call'
    horizon           TEXT NOT NULL CHECK (horizon IN ('intraday','swing','days','weeks','months','long_term')),
    signal_type       TEXT NOT NULL CHECK (signal_type IN ('buy','hold','sell','open','close','reduce','add','watch')),
    confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    risk_level        TEXT NOT NULL CHECK (risk_level IN ('low','medium','high')),
    reason            TEXT NOT NULL,
    target_price      REAL,
    stop_loss         REAL,
    max_loss_amount   REAL,                    -- for defined-risk options strategies
    tax_warning       TEXT,                    -- e.g., 'wash sale risk: bought back 12d ago'
    pdt_relevant      INTEGER NOT NULL DEFAULT 0 CHECK (pdt_relevant IN (0,1)),
    sources_json      TEXT,                    -- JSON array of {source, url, ts}
    created_at        TEXT NOT NULL,           -- first observed
    last_seen_at      TEXT NOT NULL,           -- most recent run that emitted this signal
    seen_count        INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol  ON strategy_signals(symbol, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_strat   ON strategy_signals(strategy_id, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_recent  ON strategy_signals(last_seen_at DESC);

-- ─── Tax lots: lot-by-lot position tracking ───────────────────────────

CREATE TABLE IF NOT EXISTS tax_lots (
    lot_id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Idempotency for repeated CSV ingestion / API replay. NULL is
    -- allowed for lots that originate within NeoMind itself (paper
    -- trades, manual entry through UI) where dedup is naturally
    -- handled by the caller. UNIQUE-ness is enforced via a partial
    -- index below so multiple NULLs don't collide.
    idempotency_key              TEXT,
    account_id                   TEXT NOT NULL DEFAULT 'main',
    symbol                       TEXT NOT NULL,
    market                       TEXT NOT NULL,
    asset_class                  TEXT NOT NULL,
    is_simulated                 INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0,1)),

    open_date                    TEXT NOT NULL,    -- 'YYYY-MM-DD'
    open_price                   REAL NOT NULL,
    open_quantity                REAL NOT NULL,
    open_fees                    REAL NOT NULL DEFAULT 0,

    close_date                   TEXT,
    close_price                  REAL,
    close_quantity               REAL,             -- may be partial
    close_fees                   REAL,

    cost_basis_method            TEXT NOT NULL DEFAULT 'FIFO' CHECK (cost_basis_method IN ('FIFO','LIFO','SpecID','HIFO')),
    wash_sale_basis_adjustment   REAL NOT NULL DEFAULT 0,    -- $ added to basis from wash sale rule
    holding_period_qualified     TEXT CHECK (holding_period_qualified IN ('short_term','long_term')),

    realized_gain_loss           REAL,             -- computed at close
    is_section_1256              INTEGER NOT NULL DEFAULT 0 CHECK (is_section_1256 IN (0,1)),

    notes                        TEXT,
    created_at                   TEXT NOT NULL,
    updated_at                   TEXT NOT NULL
);

-- Partial unique index — enforces dedup only when caller supplied a key.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_lots_idem
    ON tax_lots(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lots_open    ON tax_lots(symbol, market, close_date) WHERE close_date IS NULL;
CREATE INDEX IF NOT EXISTS idx_lots_close   ON tax_lots(close_date) WHERE close_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lots_account ON tax_lots(account_id);

-- ─── Wash sale events: every detection ────────────────────────────────

CREATE TABLE IF NOT EXISTS wash_sale_events (
    event_id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    sell_lot_id                  INTEGER NOT NULL,
    replacement_lot_id           INTEGER NOT NULL,
    disallowed_loss              REAL NOT NULL,
    basis_addition               REAL NOT NULL,
    days_between                 INTEGER NOT NULL,        -- |sell_date - replacement_date|
    rule_version                 TEXT NOT NULL DEFAULT 'irs_2024',
    detected_at                  TEXT NOT NULL,
    detection_run_id             TEXT,
    notes                        TEXT,
    -- Idempotency: a re-run of the detector against the same lot pair
    -- under the same rule version must not produce a second event.
    UNIQUE (sell_lot_id, replacement_lot_id, rule_version),
    FOREIGN KEY (sell_lot_id) REFERENCES tax_lots(lot_id),
    FOREIGN KEY (replacement_lot_id) REFERENCES tax_lots(lot_id),
    FOREIGN KEY (detection_run_id) REFERENCES analysis_runs(run_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_wash_sell    ON wash_sale_events(sell_lot_id);
CREATE INDEX IF NOT EXISTS idx_wash_repl    ON wash_sale_events(replacement_lot_id);

-- ─── PDT round-trip log (for the <$25k account constraint) ────────────

CREATE TABLE IF NOT EXISTS pdt_round_trips (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT NOT NULL DEFAULT 'main',
    symbol          TEXT NOT NULL,
    market          TEXT NOT NULL,
    open_lot_id     INTEGER NOT NULL,
    close_lot_id    INTEGER,                        -- may be partial-close
    trade_date      TEXT NOT NULL,                  -- date of the closing leg
    detected_at     TEXT NOT NULL,
    notes           TEXT,
    -- Idempotency: a re-run of the detector for the same pair on the
    -- same date must collapse to one row.
    UNIQUE (open_lot_id, close_lot_id, trade_date),
    FOREIGN KEY (open_lot_id) REFERENCES tax_lots(lot_id),
    FOREIGN KEY (close_lot_id) REFERENCES tax_lots(lot_id)
);

CREATE INDEX IF NOT EXISTS idx_pdt_account_date ON pdt_round_trips(account_id, trade_date DESC);

-- ─── Holding period snapshots (for "days to LT qualification" UI) ─────

CREATE TABLE IF NOT EXISTS holding_period_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id            INTEGER NOT NULL,
    snapshot_date     TEXT NOT NULL,
    days_held         INTEGER NOT NULL,
    days_to_long_term INTEGER NOT NULL,             -- max(0, 365 - days_held + 1)
    qualified_today   TEXT CHECK (qualified_today IN ('short_term','long_term')),
    FOREIGN KEY (lot_id) REFERENCES tax_lots(lot_id) ON DELETE CASCADE,
    UNIQUE (lot_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_hps_date ON holding_period_snapshots(snapshot_date);

-- ─── Scheduler job state (cron-like) ──────────────────────────────────

CREATE TABLE IF NOT EXISTS scheduler_jobs (
    job_name           TEXT PRIMARY KEY,
    cron_expression    TEXT,                        -- e.g., '0 22 * * 1-5' (after US close)
    enabled            INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    description        TEXT,
    last_run_id        TEXT,
    last_run_at        TEXT,
    last_run_status    TEXT CHECK (last_run_status IN ('completed','failed','cancelled')),
    next_run_at        TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (last_run_id) REFERENCES analysis_runs(run_id) ON DELETE SET NULL
);

-- ─── Initial schema_version row ───────────────────────────────────────
-- Inserted by db.py on first ensure_schema() call, not here, so the
-- "applied_at" timestamp is honest.
