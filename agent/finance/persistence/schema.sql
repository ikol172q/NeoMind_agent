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

-- ─── Strategy pipeline v2 (2026-04-29) ────────────────────────────────
--
-- Four tables that back the regime-based strategy distillation pipeline.
-- See docs/design/2026-04-29_strategy-pipeline-v2.md for the full
-- architecture; this is just the schema.

-- raw_market_data: every OHLCV bar that lands in our universe.  The
-- single source of truth for everything downstream — every regime
-- score and every strategy fit is derived from rows here.  ~50MB
-- after 1y backfill of the 3-tier watchlist (~520 tickers × 252 days).
CREATE TABLE IF NOT EXISTS raw_market_data (
    symbol         TEXT NOT NULL,
    trade_date     TEXT NOT NULL,         -- 'YYYY-MM-DD' UTC
    open           REAL,
    high           REAL,
    low            REAL,
    close          REAL,
    adjusted_close REAL,
    volume         INTEGER,
    source         TEXT NOT NULL,         -- 'yfinance' / 'manual' / ...
    fetched_at     TEXT NOT NULL,
    raw_blob_sha   TEXT,                  -- raw://<sha256> for full provenance
    tier           INTEGER NOT NULL CHECK (tier IN (1,2,3)),
                                          -- 1=user watchlist, 2=anchors, 3=breadth pool
    PRIMARY KEY (symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_rmd_date  ON raw_market_data(trade_date);
CREATE INDEX IF NOT EXISTS idx_rmd_tier  ON raw_market_data(tier, trade_date);

-- regime_fingerprints: one row per fingerprint_date, holding the 5
-- bucket scores + their components + the raw inputs that produced
-- them.  Permanent retention — used both for UI display and for
-- k-NN historical-similarity search.
CREATE TABLE IF NOT EXISTS regime_fingerprints (
    fingerprint_date         TEXT PRIMARY KEY,    -- 'YYYY-MM-DD' UTC
    risk_appetite_score      REAL,
    volatility_regime_score  REAL,
    breadth_score            REAL,
    event_density_score      REAL,
    flow_score               REAL,
    components_json          TEXT,                -- {"vix_pct_rank": {"1w": 0.35, ...}, ...}
    inputs_json              TEXT,                -- {"vix_close": 14.2, ...}
    sources_json             TEXT,                -- {"vix": "yfinance@2026-04-29T20:30Z", ...}
    computed_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rf_computed ON regime_fingerprints(computed_at DESC);

-- decision_traces: every strategy recommendation we surface, with
-- full breakdown + sources + constraint check + portfolio fit.
-- This is the audit / "where did this number come from" entry point.
CREATE TABLE IF NOT EXISTS decision_traces (
    trace_id              TEXT PRIMARY KEY,       -- uuid4
    fingerprint_date      TEXT NOT NULL,
    strategy_id           TEXT NOT NULL,
    score                 REAL NOT NULL,          -- final posterior 0-10
    rank                  INTEGER NOT NULL,       -- 1 = top, 2-8 = alternatives
    alternative_weight    REAL NOT NULL,          -- score / top_score (1.0 for top)
    formula               TEXT NOT NULL,          -- e.g. 'closed_form_BS_v1' or 'hybrid_β=0.62'
    breakdown_json        TEXT NOT NULL,          -- {"E_pnl": ..., "P_profit": ..., ...}
    lattice_node_refs     TEXT NOT NULL,          -- JSON array of L0/L1/L2/L3 node ids
    knn_neighbor_dates    TEXT,                   -- JSON array of fingerprint_dates
    constraint_check_json TEXT NOT NULL,
    portfolio_fit_json    TEXT,
    computed_at           TEXT NOT NULL,
    FOREIGN KEY (fingerprint_date) REFERENCES regime_fingerprints(fingerprint_date)
);
CREATE INDEX IF NOT EXISTS idx_dt_date     ON decision_traces(fingerprint_date);
CREATE INDEX IF NOT EXISTS idx_dt_strategy ON decision_traces(strategy_id);
CREATE INDEX IF NOT EXISTS idx_dt_rank     ON decision_traces(fingerprint_date, rank);

-- knn_lookups: every neighbor returned for a Bayesian shrinkage
-- prior calculation, with the similarity score that justified its
-- inclusion.  Lets the UI show "we looked at these N similar days
-- when computing this fit number".
CREATE TABLE IF NOT EXISTS knn_lookups (
    lookup_id          TEXT PRIMARY KEY,           -- uuid4
    target_date        TEXT NOT NULL,
    neighbor_date      TEXT NOT NULL,
    similarity_score   REAL NOT NULL,              -- 0-1 (cosine or 1-mahalanobis)
    weight_in_prior    REAL NOT NULL,              -- normalized softmax weight
    used_for_strategy  TEXT NOT NULL,
    computed_at        TEXT NOT NULL,
    FOREIGN KEY (target_date)   REFERENCES regime_fingerprints(fingerprint_date),
    FOREIGN KEY (neighbor_date) REFERENCES regime_fingerprints(fingerprint_date)
);
CREATE INDEX IF NOT EXISTS idx_knn_target ON knn_lookups(target_date, used_for_strategy);

-- backtest_results: schema v3 (2026-04-30) — for every historical
-- (fingerprint_date × strategy_id), compute the model's predicted
-- score AND the realized P&L over a forward holding window.  This
-- lets the UI show "system loved covered_call_etf in vol-spike days,
-- but in 73% of those days the strategy actually lost money" — i.e.,
-- recall / calibration on real history.
--
-- realized_pnl_pct is a strategy-class-aware proxy (see backtest.py
-- _proxy_pnl) NOT real P&L from option chains (which we don't have).
-- Treat as directional / first-order signal.
CREATE TABLE IF NOT EXISTS backtest_results (
    result_id           TEXT PRIMARY KEY,         -- uuid4
    fingerprint_date    TEXT NOT NULL,
    strategy_id         TEXT NOT NULL,
    predicted_score     REAL NOT NULL,            -- scorer's 0-10 fit
    rank                INTEGER NOT NULL,         -- 1=top, 2-N=alternative
    hold_days           INTEGER NOT NULL,         -- 30 default
    realized_pnl_pct    REAL,                     -- forward return proxy, fraction (0.05 = 5%)
    underlying_return   REAL,                     -- raw market forward return for the asset_class anchor
    method              TEXT NOT NULL,            -- 'proxy_v1'
    notes_json          TEXT,                     -- {"anchor": "SPY", "window": "2024-04-01..2024-05-01", ...}
    computed_at         TEXT NOT NULL,
    FOREIGN KEY (fingerprint_date) REFERENCES regime_fingerprints(fingerprint_date)
);
CREATE INDEX IF NOT EXISTS idx_bt_date     ON backtest_results(fingerprint_date);
CREATE INDEX IF NOT EXISTS idx_bt_strategy ON backtest_results(strategy_id);
CREATE INDEX IF NOT EXISTS idx_bt_rank     ON backtest_results(fingerprint_date, rank);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bt_unique
    ON backtest_results(fingerprint_date, strategy_id, hold_days);

-- ─── Phase L: NeoMind Live — push signal system ─────────────────
--
-- user_watchlist: the user's hand-curated tickers.  Auto-supply-chain
-- expansion is computed on demand, not stored, so it stays fresh.
CREATE TABLE IF NOT EXISTS user_watchlist (
    ticker     TEXT PRIMARY KEY,
    added_at   TEXT NOT NULL,
    note       TEXT,
    importance INTEGER DEFAULT 1   -- 1 = normal, 2 = priority (more frequent scanning)
);

-- signal_events: every individual scanner emission.  Multi-source
-- confluence is computed downstream from these rows.
CREATE TABLE IF NOT EXISTS signal_events (
    event_id          TEXT PRIMARY KEY,        -- uuid4
    scanner_name      TEXT NOT NULL,            -- 'watchlist' / 'news' / '13f' / 'stock_act' / 'earnings'
    ticker            TEXT,                     -- nullable for theme-level events
    theme             TEXT,                     -- e.g. 'china_ai_capex', 'fomc_may'
    signal_type       TEXT NOT NULL,            -- 'price_break' / 'rsi_extreme' / 'ma_cross' / 'whale_buy' / 'policy' / 'earnings_beat' / etc.
    severity          TEXT NOT NULL,            -- 'high' / 'med' / 'low'
    title             TEXT NOT NULL,            -- one-line headline
    body_json         TEXT,                     -- structured payload
    source_url        TEXT,                     -- click-through to evidence
    source_timestamp  TEXT,                     -- when underlying event happened (UTC)
    detected_at       TEXT NOT NULL             -- when scanner saw it (UTC)
);
CREATE INDEX IF NOT EXISTS idx_se_detected ON signal_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_se_ticker   ON signal_events(ticker);
CREATE INDEX IF NOT EXISTS idx_se_scanner  ON signal_events(scanner_name);

-- signal_confluences: when ≥2 independent scanners agree on the same
-- ticker / theme within a 24-72h window, we promote a confluence
-- record.  The frontend's "Today's 3 signals" reads from this table.
CREATE TABLE IF NOT EXISTS signal_confluences (
    confluence_id   TEXT PRIMARY KEY,           -- uuid4
    ticker          TEXT,
    theme           TEXT,
    headline        TEXT NOT NULL,
    n_sources       INTEGER NOT NULL,
    color           TEXT NOT NULL,              -- 'green' / 'amber' / 'red' / 'gray'
    interpretation  TEXT,
    detected_at     TEXT NOT NULL,
    expires_at      TEXT NOT NULL,              -- 24-72h ttl
    event_ids_json  TEXT NOT NULL,              -- JSON array of contributing event_ids
    dismissed       INTEGER DEFAULT 0           -- user can dismiss
);
CREATE INDEX IF NOT EXISTS idx_sc_detected ON signal_confluences(detected_at DESC);

-- ─── Initial schema_version row ───────────────────────────────────────
-- Inserted by db.py on first ensure_schema() call, not here, so the
-- "applied_at" timestamp is honest.
