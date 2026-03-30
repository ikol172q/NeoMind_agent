#!/usr/bin/env python3
"""
NeoMind Data Collector — Independent background process.
数据驱动的个人能力延伸系统 — 24/7 数据采集引擎

Managed by supervisord. Shares data with agent via SQLite WAL.
This process is independent: agent restart does not affect it.

Usage:
    python -u agent/data/collector.py
"""

import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ─── Logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [collector] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("data-collector")

# ─── Database paths ───
DB_DIR = Path(os.environ.get("NEOMIND_DB_DIR", "/data/neomind/db"))
MARKET_DB = DB_DIR / "market_data.db"
NEWS_DB = DB_DIR / "news_data.db"
BRIEFINGS_DB = DB_DIR / "briefings.db"

# ─── Graceful shutdown ───
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    _shutdown = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# ─── Database initialization ───

def _init_db(db_path: Path, schema_sql: str) -> sqlite3.Connection:
    """Initialize a SQLite database with WAL mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(schema_sql)
    conn.row_factory = sqlite3.Row
    return conn


MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_ohlcv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    ts TIMESTAMP NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    source TEXT NOT NULL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, ts, source)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_ts ON price_ohlcv(symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_market ON price_ohlcv(market);

CREATE TABLE IF NOT EXISTS macro_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator TEXT NOT NULL,
    value REAL NOT NULL,
    period TEXT,
    release_date DATE,
    source TEXT NOT NULL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(indicator, period, source)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    period TEXT,
    updated_at TIMESTAMP,
    source TEXT NOT NULL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, metric, period, source)
);

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    last_sync_ts TIMESTAMP,
    last_id TEXT,
    status TEXT,
    error_msg TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

NEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT UNIQUE,
    source TEXT,
    published_at TIMESTAMP,
    symbols TEXT,
    category TEXT,
    language TEXT DEFAULT 'en',
    sentiment_score REAL,
    impact_score REAL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);

CREATE TABLE IF NOT EXISTS sentiment_daily (
    symbol TEXT,
    date DATE,
    avg_sentiment REAL,
    news_count INTEGER,
    top_headline TEXT,
    UNIQUE(symbol, date)
);

-- FTS5 full-text search index for news
CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
    headline,
    summary,
    content='news',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS5 in sync with news table
CREATE TRIGGER IF NOT EXISTS news_ai AFTER INSERT ON news BEGIN
    INSERT INTO news_fts(rowid, headline, summary)
    VALUES (new.id, new.headline, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS news_ad AFTER DELETE ON news BEGIN
    INSERT INTO news_fts(news_fts, rowid, headline, summary)
    VALUES ('delete', old.id, old.headline, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS news_au AFTER UPDATE ON news BEGIN
    INSERT INTO news_fts(news_fts, rowid, headline, summary)
    VALUES ('delete', old.id, old.headline, old.summary);
    INSERT INTO news_fts(rowid, headline, summary)
    VALUES (new.id, new.headline, new.summary);
END;
"""

BRIEFINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    date DATE NOT NULL,
    content TEXT NOT NULL,
    key_events TEXT,
    market_mood TEXT,
    action_items TEXT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed_by TEXT,
    consumed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_briefings_date ON briefings(date DESC);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    decision_type TEXT,
    symbol TEXT,
    reasoning TEXT,
    confidence REAL,
    data_sources TEXT,
    outcome TEXT DEFAULT 'pending',
    outcome_detail TEXT,
    outcome_recorded_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_decisions_mode ON decisions(mode);
"""


class DataCollector:
    """
    Independent background data collection process.

    Responsibilities:
    - Collect price data from financial APIs
    - Collect news and compute sentiment
    - Generate daily/weekly briefings
    - Maintain sync state and handle errors
    - Clean up old data per retention policy
    """

    def __init__(self):
        self.market_conn: Optional[sqlite3.Connection] = None
        self.news_conn: Optional[sqlite3.Connection] = None
        self.briefings_conn: Optional[sqlite3.Connection] = None

        # Rate limiter and compliance
        from agent.data.rate_limiter import RateLimiter
        from agent.data.compliance import ComplianceChecker

        self.rate_limiter = RateLimiter()
        self.compliance = ComplianceChecker(
            rate_limiter=self.rate_limiter,
            api_keys=self._load_api_keys(),
        )

        # Default watchlist (user can customize via config)
        self._watchlist = self._load_watchlist()

        # Task schedule (simplified APScheduler-compatible)
        self._tasks: list[dict] = []

    def _load_api_keys(self) -> dict:
        """Load API keys from environment."""
        return {
            "FINNHUB_API_KEY": os.environ.get("FINNHUB_API_KEY", ""),
            "ALPHA_VANTAGE_API_KEY": os.environ.get("ALPHA_VANTAGE_API_KEY", ""),
            "NEWSAPI_API_KEY": os.environ.get("NEWSAPI_API_KEY", ""),
            "FRED_API_KEY": os.environ.get("FRED_API_KEY", ""),
        }

    def _load_watchlist(self) -> dict:
        """Load watchlist from config or use defaults."""
        config_path = DB_DIR / "watchlist.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load watchlist: {e}")

        # Default watchlist — conservative, can be expanded
        return {
            "US": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA"],
            "CRYPTO": ["bitcoin", "ethereum"],
            "MACRO": [
                "US_CPI", "US_GDP", "FED_RATE", "US_UNEMPLOYMENT",
                "US_10Y_YIELD", "DXY",
            ],
        }

    def init_databases(self) -> None:
        """Initialize all databases with schemas."""
        logger.info("Initializing databases...")
        self.market_conn = _init_db(MARKET_DB, MARKET_SCHEMA)
        self.news_conn = _init_db(NEWS_DB, NEWS_SCHEMA)
        self.briefings_conn = _init_db(BRIEFINGS_DB, BRIEFINGS_SCHEMA)
        logger.info(
            f"Databases ready: market={MARKET_DB}, news={NEWS_DB}, "
            f"briefings={BRIEFINGS_DB}"
        )

    # ─── Data Collection Methods ───

    def collect_prices_finnhub(self) -> int:
        """Collect latest prices from Finnhub for US stocks."""
        source = "finnhub"
        allowed, reason = self.compliance.pre_request_check(source)
        if not allowed:
            logger.debug(f"Skipping {source}: {reason}")
            return 0

        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not api_key:
            return 0

        import requests
        count = 0
        for symbol in self._watchlist.get("US", []):
            if _shutdown:
                break

            if not self.rate_limiter.wait_if_needed(source, timeout=30):
                break

            try:
                resp = requests.get(
                    f"https://finnhub.io/api/v1/quote",
                    params={"symbol": symbol, "token": api_key},
                    timeout=10,
                )
                self.compliance.post_response_check(source, resp.status_code)

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("c") and data["c"] > 0:
                        now = datetime.utcnow().isoformat()
                        self.market_conn.execute(
                            """INSERT OR REPLACE INTO price_ohlcv
                            (symbol, market, ts, open, high, low, close, volume, source)
                            VALUES (?, 'US', ?, ?, ?, ?, ?, ?, ?)""",
                            (symbol, now, data.get("o"), data.get("h"),
                             data.get("l"), data["c"], 0, source),
                        )
                        count += 1

            except requests.RequestException as e:
                logger.warning(f"Finnhub error for {symbol}: {e}")
                self._update_sync_state(source, "error", str(e))

        if count > 0:
            self.market_conn.commit()
            self._update_sync_state(source, "ok")
            logger.info(f"Collected {count} prices from {source}")

        return count

    def collect_crypto_coingecko(self) -> int:
        """Collect crypto prices from CoinGecko (free, no key required)."""
        source = "coingecko"
        allowed, reason = self.compliance.pre_request_check(source)
        if not allowed:
            logger.debug(f"Skipping {source}: {reason}")
            return 0

        import requests
        coins = self._watchlist.get("CRYPTO", [])
        if not coins:
            return 0

        if not self.rate_limiter.wait_if_needed(source, timeout=30):
            return 0

        try:
            ids = ",".join(coins)
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": ids,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
                timeout=10,
            )
            self.compliance.post_response_check(source, resp.status_code)

            if resp.status_code == 200:
                data = resp.json()
                now = datetime.utcnow().isoformat()
                count = 0
                for coin_id, info in data.items():
                    price = info.get("usd", 0)
                    if price > 0:
                        self.market_conn.execute(
                            """INSERT OR REPLACE INTO price_ohlcv
                            (symbol, market, ts, close, source)
                            VALUES (?, 'CRYPTO', ?, ?, ?)""",
                            (coin_id.upper(), now, price, source),
                        )
                        count += 1

                self.market_conn.commit()
                self._update_sync_state(source, "ok")
                logger.info(f"Collected {count} crypto prices from {source}")
                return count

        except requests.RequestException as e:
            logger.warning(f"CoinGecko error: {e}")
            self._update_sync_state(source, "error", str(e))

        return 0

    def collect_news_finnhub(self) -> int:
        """Collect market news from Finnhub."""
        source = "finnhub"
        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not api_key:
            return 0

        allowed, reason = self.compliance.pre_request_check(source)
        if not allowed:
            return 0

        import requests

        if not self.rate_limiter.wait_if_needed(source, timeout=30):
            return 0

        try:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

            resp = requests.get(
                "https://finnhub.io/api/v1/news",
                params={
                    "category": "general",
                    "minId": 0,
                    "token": api_key,
                },
                timeout=15,
            )
            self.compliance.post_response_check(source, resp.status_code)

            if resp.status_code == 200:
                articles = resp.json()
                count = 0
                for article in articles[:50]:  # Cap at 50 per fetch
                    headline = article.get("headline", "").strip()
                    url = article.get("url", "")
                    if not headline or not url:
                        continue

                    pub_ts = article.get("datetime", 0)
                    pub_date = datetime.fromtimestamp(pub_ts).isoformat() if pub_ts else None
                    summary = article.get("summary", "")[:500]
                    category = article.get("category", "")
                    related = article.get("related", "")
                    symbols_json = json.dumps(
                        related.split(",") if related else []
                    )

                    try:
                        self.news_conn.execute(
                            """INSERT OR IGNORE INTO news
                            (headline, summary, url, source, published_at,
                             symbols, category, language)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'en')""",
                            (headline, summary, url, source, pub_date,
                             symbols_json, category),
                        )
                        count += 1
                    except sqlite3.IntegrityError:
                        pass  # Duplicate URL

                if count > 0:
                    self.news_conn.commit()
                    logger.info(f"Collected {count} news articles from {source}")
                return count

        except requests.RequestException as e:
            logger.warning(f"Finnhub news error: {e}")

        return 0

    def collect_macro_fred(self) -> int:
        """Collect macro indicators from FRED."""
        source = "fred"
        api_key = os.environ.get("FRED_API_KEY", "")
        if not api_key:
            # FRED has some free endpoints without key, but limited
            return 0

        allowed, reason = self.compliance.pre_request_check(source)
        if not allowed:
            return 0

        import requests

        # Map our indicator names to FRED series IDs
        fred_series = {
            "US_CPI": "CPIAUCSL",
            "US_GDP": "GDP",
            "FED_RATE": "FEDFUNDS",
            "US_UNEMPLOYMENT": "UNRATE",
            "US_10Y_YIELD": "DGS10",
        }

        count = 0
        for indicator, series_id in fred_series.items():
            if _shutdown:
                break
            if not self.rate_limiter.wait_if_needed(source, timeout=30):
                break

            try:
                resp = requests.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series_id,
                        "api_key": api_key,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": 1,
                    },
                    timeout=10,
                )
                self.compliance.post_response_check(source, resp.status_code)

                if resp.status_code == 200:
                    data = resp.json()
                    obs = data.get("observations", [])
                    if obs:
                        latest = obs[0]
                        value_str = latest.get("value", ".")
                        if value_str != ".":
                            value = float(value_str)
                            period = latest.get("date", "")
                            self.market_conn.execute(
                                """INSERT OR REPLACE INTO macro_indicators
                                (indicator, value, period, release_date, source)
                                VALUES (?, ?, ?, ?, ?)""",
                                (indicator, value, period, period, source),
                            )
                            count += 1

            except (requests.RequestException, ValueError) as e:
                logger.warning(f"FRED error for {indicator}: {e}")

        if count > 0:
            self.market_conn.commit()
            self._update_sync_state(source, "ok")
            logger.info(f"Collected {count} macro indicators from {source}")

        return count

    # ─── Briefing Generation ───

    def generate_daily_briefing(self) -> Optional[int]:
        """Generate a daily market briefing from collected data."""
        today = datetime.utcnow().strftime("%Y-%m-%d")

        # Check if already generated today
        existing = self.briefings_conn.execute(
            "SELECT id FROM briefings WHERE type='daily' AND date=?",
            (today,),
        ).fetchone()
        if existing:
            return None

        # Gather data for briefing
        parts = []
        key_events = []

        # Latest prices
        prices = self.market_conn.execute(
            """SELECT symbol, close, market, ts FROM price_ohlcv
            WHERE ts > datetime('now', '-24 hours')
            ORDER BY ts DESC""",
        ).fetchall()

        if prices:
            seen = set()
            price_lines = []
            for row in prices:
                sym = row["symbol"]
                if sym not in seen:
                    seen.add(sym)
                    price_lines.append(
                        f"- {sym} ({row['market']}): ${row['close']:.2f}"
                    )
            if price_lines:
                parts.append("## Latest Prices\n" + "\n".join(price_lines[:15]))

        # Latest news
        news = self.news_conn.execute(
            """SELECT headline, source, published_at FROM news
            WHERE published_at > datetime('now', '-24 hours')
            ORDER BY published_at DESC LIMIT 10""",
        ).fetchall()

        if news:
            news_lines = [f"- [{n['source']}] {n['headline']}" for n in news]
            parts.append("## Top News\n" + "\n".join(news_lines))
            key_events = [n["headline"] for n in news[:5]]

        # Macro indicators
        macro = self.market_conn.execute(
            "SELECT indicator, value, period FROM macro_indicators ORDER BY collected_at DESC LIMIT 10",
        ).fetchall()

        if macro:
            seen_macro = set()
            macro_lines = []
            for m in macro:
                if m["indicator"] not in seen_macro:
                    seen_macro.add(m["indicator"])
                    macro_lines.append(
                        f"- {m['indicator']}: {m['value']:.2f} ({m['period']})"
                    )
            if macro_lines:
                parts.append("## Macro Indicators\n" + "\n".join(macro_lines))

        if not parts:
            parts.append("No significant data collected in the last 24 hours.")

        content = f"# Daily Briefing — {today}\n\n" + "\n\n".join(parts)

        # Determine market mood (simple heuristic)
        mood = "neutral"

        briefing_id = self.briefings_conn.execute(
            """INSERT INTO briefings (type, date, content, key_events, market_mood)
            VALUES ('daily', ?, ?, ?, ?)""",
            (today, content, json.dumps(key_events), mood),
        ).lastrowid
        self.briefings_conn.commit()

        logger.info(f"Generated daily briefing #{briefing_id} for {today}")
        return briefing_id

    # ─── Full-Text Search ───

    def search_news(self, query: str, limit: int = 20) -> list:
        """Search news articles using FTS5 full-text search.

        Args:
            query: FTS5 search query (supports operators: AND, OR, NOT, phrases)
            limit: Maximum number of results to return

        Returns:
            List of news rows matching the query
        """
        try:
            results = self.news_conn.execute(
                """SELECT n.* FROM news n
                   JOIN news_fts ON news_fts.rowid = n.id
                   WHERE news_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [dict(row) for row in results]
        except Exception as e:
            logger.warning(f"FTS5 search error: {e}")
            return []

    def rebuild_fts_index(self) -> None:
        """Rebuild FTS5 index from existing news data.

        Useful for initial population if there's existing data without FTS entries.
        """
        try:
            self.news_conn.execute("INSERT INTO news_fts(news_fts) VALUES('rebuild')")
            self.news_conn.commit()
            logger.info("FTS5 index rebuilt successfully")
        except Exception as e:
            logger.warning(f"Failed to rebuild FTS5 index: {e}")

    # ─── Maintenance ───

    def cleanup_old_data(self) -> dict:
        """Clean up data per retention policy."""
        stats = {}

        # Market data: 90 days
        cursor = self.market_conn.execute(
            "DELETE FROM price_ohlcv WHERE collected_at < datetime('now', '-90 days')"
        )
        stats["market_prices_deleted"] = cursor.rowcount
        self.market_conn.commit()

        # News data: 30 days
        cursor = self.news_conn.execute(
            "DELETE FROM news WHERE collected_at < datetime('now', '-30 days')"
        )
        stats["news_deleted"] = cursor.rowcount
        self.news_conn.commit()

        # Sentiment: 90 days
        cursor = self.news_conn.execute(
            "DELETE FROM sentiment_daily WHERE date < date('now', '-90 days')"
        )
        stats["sentiment_deleted"] = cursor.rowcount
        self.news_conn.commit()

        # Briefings: 180 days
        cursor = self.briefings_conn.execute(
            "DELETE FROM briefings WHERE date < date('now', '-180 days')"
        )
        stats["briefings_deleted"] = cursor.rowcount
        self.briefings_conn.commit()

        # Vacuum if significant deletions
        total_deleted = sum(stats.values())
        if total_deleted > 100:
            for conn in [self.market_conn, self.news_conn, self.briefings_conn]:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        if total_deleted > 0:
            logger.info(f"Cleanup: {stats}")

        return stats

    def _update_sync_state(self, source: str, status: str,
                            error_msg: str = "") -> None:
        """Update the sync state for a data source."""
        self.market_conn.execute(
            """INSERT OR REPLACE INTO sync_state (source, last_sync_ts, status, error_msg, updated_at)
            VALUES (?, datetime('now'), ?, ?, datetime('now'))""",
            (source, status, error_msg),
        )
        self.market_conn.commit()

    # ─── Main Loop ───

    def run_collection_cycle(self) -> dict:
        """Run one full collection cycle."""
        results = {}

        # Prices
        results["finnhub_prices"] = self.collect_prices_finnhub()
        results["crypto_prices"] = self.collect_crypto_coingecko()

        # News
        results["finnhub_news"] = self.collect_news_finnhub()

        # Macro (less frequent — only if not collected today)
        last_macro = self.market_conn.execute(
            "SELECT updated_at FROM sync_state WHERE source='fred'"
        ).fetchone()
        if not last_macro or (
            datetime.fromisoformat(last_macro["updated_at"]) <
            datetime.utcnow() - timedelta(hours=6)
        ):
            results["fred_macro"] = self.collect_macro_fred()

        # Generate briefing if not yet done today
        briefing_id = self.generate_daily_briefing()
        if briefing_id:
            results["daily_briefing"] = briefing_id

        return results

    def run(self) -> None:
        """Main entry point — runs forever with scheduled intervals."""
        logger.info("=" * 60)
        logger.info("NeoMind Data Collector starting...")
        logger.info(f"  Watchlist: {self._watchlist}")
        logger.info(f"  DB dir: {DB_DIR}")
        logger.info("=" * 60)

        self.init_databases()

        # Initial collection
        try:
            results = self.run_collection_cycle()
            logger.info(f"Initial collection complete: {results}")
        except Exception as e:
            logger.error(f"Initial collection error: {e}", exc_info=True)

        # Main loop — collect every 15 minutes for prices, hourly for news
        cycle = 0
        while not _shutdown:
            try:
                # Sleep in 10s intervals for responsive shutdown
                for _ in range(90):  # 90 * 10s = 15 minutes
                    if _shutdown:
                        break
                    time.sleep(10)

                if _shutdown:
                    break

                cycle += 1
                logger.info(f"Collection cycle #{cycle}")

                results = self.run_collection_cycle()
                logger.info(f"Cycle #{cycle} results: {results}")

                # Cleanup daily at cycle ~96 (~24h)
                if cycle % 96 == 0:
                    self.cleanup_old_data()

            except Exception as e:
                logger.error(f"Collection cycle error: {e}", exc_info=True)
                # Don't crash — sleep and retry
                time.sleep(60)

        # Graceful shutdown
        logger.info("Shutting down data collector...")
        for conn in [self.market_conn, self.news_conn, self.briefings_conn]:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        logger.info("Data collector stopped.")


def main():
    collector = DataCollector()
    collector.run()


if __name__ == "__main__":
    main()
