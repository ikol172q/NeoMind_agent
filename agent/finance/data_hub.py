# agent/finance/data_hub.py
"""
Finance Data Hub — aggregates financial data from multiple free sources.

Provides unified interface for stocks (US + China), crypto, and options.
All data returns include source attribution and timestamps.

Data sources:
  US Stocks:   Finnhub (primary), yfinance (fallback)
  China/HK:    AKShare (primary), Tushare (fallback)
  Crypto:      CoinGecko (primary), Binance API (fallback)
  Options:     yfinance (primary)
"""

import os
import time
import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor

try:
    import finnhub
    HAS_FINNHUB = True
except ImportError:
    HAS_FINNHUB = False
    finnhub = None

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    yf = None

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False
    ak = None

import requests


# ── Data Classes ──────────────────────────────────────────────────────

@dataclass
class VerifiedDataPoint:
    """Every piece of financial data MUST carry this metadata.

    Rule 3: Every data point has source + timestamp.
    """
    value: Any
    source: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    freshness: str = "unknown"    # "real-time", "15-min delayed", "daily close", "cached"
    confidence: float = 1.0
    data_type: str = "fact"       # "fact", "estimate", "opinion"
    unit: str = "USD"

    def render(self) -> str:
        delay = f", {self.freshness}" if self.freshness != "real-time" else ""
        ts = self.timestamp.strftime('%Y-%m-%d %H:%M UTC')
        return f"{self.value} (source: {self.source}, as of {ts}{delay})"


@dataclass
class StockQuote:
    """Unified stock quote from any source."""
    symbol: str
    price: VerifiedDataPoint = None
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    prev_close: float = 0.0
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    name: str = ""
    market: str = "us"
    currency: str = "USD"
    market_status: str = "unknown"  # "open", "closed", "pre-market", "after-hours"


@dataclass
class CryptoQuote:
    """Unified crypto quote."""
    coin_id: str
    symbol: str
    name: str
    price: VerifiedDataPoint = None
    change_24h_pct: float = 0.0
    volume_24h: float = 0.0
    market_cap: float = 0.0
    rank: int = 0
    currency: str = "USD"


@dataclass
class NewsItem:
    """A financial news item from any source."""
    title: str
    url: str = ""
    source: str = ""
    language: str = "en"
    published: Optional[datetime] = None
    summary: str = ""
    symbols: List[str] = field(default_factory=list)
    category: str = ""  # earnings, macro, policy, crypto, etc.
    impact_score: float = 0.0


# ── Cache ─────────────────────────────────────────────────────────────

class DataCache:
    """Simple TTL cache for financial data."""

    def __init__(self):
        self._cache: Dict[str, tuple] = {}

    def get(self, key: str, ttl: int = 300) -> Optional[Any]:
        if key in self._cache:
            value, ts = self._cache[key]
            if time.time() - ts < ttl:
                return value
        return None

    def set(self, key: str, value: Any):
        self._cache[key] = (value, time.time())


# ── Market Hours ──────────────────────────────────────────────────────

def get_market_status(market: str = "us") -> str:
    """Determine if market is currently open."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    if market == "us":
        # NYSE/NASDAQ: 9:30-16:00 ET (14:30-21:00 UTC, roughly)
        if weekday >= 5:
            return "closed (weekend)"
        hour_utc = now.hour
        if 14 <= hour_utc < 21:
            return "open"
        elif 13 <= hour_utc < 14:
            return "pre-market"
        elif 21 <= hour_utc < 24:
            return "after-hours"
        return "closed"

    elif market in ("cn", "a-share"):
        # Shanghai/Shenzhen: 9:30-11:30, 13:00-15:00 CST (UTC+8)
        if weekday >= 5:
            return "closed (weekend)"
        cst_hour = (now.hour + 8) % 24
        if 9 <= cst_hour < 11 or (cst_hour == 11 and now.minute < 30):
            return "open (morning session)"
        elif 13 <= cst_hour < 15:
            return "open (afternoon session)"
        elif 11 <= cst_hour < 13:
            return "closed (lunch break)"
        return "closed"

    elif market == "hk":
        # HKEX: 9:30-12:00, 13:00-16:00 HKT (UTC+8)
        if weekday >= 5:
            return "closed (weekend)"
        hkt_hour = (now.hour + 8) % 24
        if 9 <= hkt_hour < 12:
            return "open (morning)"
        elif 13 <= hkt_hour < 16:
            return "open (afternoon)"
        return "closed"

    elif market == "crypto":
        return "open (24/7)"

    return "unknown"


# ── Main Data Hub ─────────────────────────────────────────────────────

class FinanceDataHub:
    """
    Aggregates financial data from multiple free sources.
    Provides unified interface with automatic fallback.
    """

    def __init__(self, config=None):
        self.config = config
        self.cache = DataCache()
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Finnhub client (primary US quote source)
        self.finnhub_client = None
        finnhub_key = os.getenv("FINNHUB_API_KEY")
        if not HAS_FINNHUB:
            logger.warning(
                "finnhub-python package not installed; US quotes will skip Finnhub "
                "and fall back to Alpha Vantage / yfinance."
            )
        elif not finnhub_key:
            logger.warning(
                "FINNHUB_API_KEY env var not set; Finnhub primary source disabled. "
                "Set it to enable real-time quotes. Falling back to Alpha Vantage / yfinance."
            )
        else:
            try:
                self.finnhub_client = finnhub.Client(api_key=finnhub_key)
            except Exception as exc:
                logger.warning("Finnhub client init failed: %s", exc)
                self.finnhub_client = None

        # Alpha Vantage (secondary US quote source between Finnhub and yfinance).
        # Free tier: 5 req/min, 500/day. Env var: ALPHAVANTAGE_API_KEY.
        self.alphavantage_key = os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.alphavantage_key:
            logger.info(
                "ALPHAVANTAGE_API_KEY not set; Alpha Vantage fallback disabled. "
                "This is optional — yfinance will still back up Finnhub."
            )

    # ── Stock Quotes ──────────────────────────────────────────────────

    async def get_quote(self, symbol: str, market: str = "us") -> Optional[StockQuote]:
        """
        Get stock quote with automatic source selection.

        Tries: Finnhub → yfinance (for US)
               AKShare → yfinance (for China/HK)
        """
        cache_key = f"quote_{symbol}_{market}"
        cached = self.cache.get(cache_key, ttl=300)
        if cached:
            return cached

        quote = None

        if market == "us":
            # Try Finnhub first (official API, more reliable)
            if self.finnhub_client:
                quote = await self._get_finnhub_quote(symbol)

            # Fallback 1: Alpha Vantage (if key configured)
            if not quote and self.alphavantage_key:
                quote = await self._get_alphavantage_quote(symbol)

            # Fallback 2: yfinance (no key needed, less reliable)
            if not quote and HAS_YFINANCE:
                quote = await self._get_yfinance_quote(symbol, market)

        elif market in ("cn", "a-share", "hk"):
            # Try AKShare for Chinese/HK stocks
            if HAS_AKSHARE:
                quote = await self._get_akshare_quote(symbol, market)

            # Fallback to yfinance
            if not quote and HAS_YFINANCE:
                yf_symbol = symbol if market == "hk" else f"{symbol}.SS"
                quote = await self._get_yfinance_quote(yf_symbol, market)

        if quote:
            quote.market_status = get_market_status(market)
            self.cache.set(cache_key, quote)

        return quote

    async def _get_finnhub_quote(self, symbol: str) -> Optional[StockQuote]:
        """Fetch quote from Finnhub."""
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                self._executor,
                self.finnhub_client.quote, symbol
            )
            if not data or data.get("c", 0) == 0:
                return None

            return StockQuote(
                symbol=symbol,
                price=VerifiedDataPoint(
                    value=data["c"],
                    source="Finnhub",
                    freshness="15-min delayed" if not os.getenv("FINNHUB_PREMIUM") else "real-time",
                ),
                change=round(data["c"] - data["pc"], 2),
                change_pct=round((data["c"] - data["pc"]) / data["pc"] * 100, 2) if data["pc"] else 0,
                high=data.get("h", 0),
                low=data.get("l", 0),
                open=data.get("o", 0),
                prev_close=data.get("pc", 0),
                market="us",
            )
        except Exception:
            return None

    async def _get_alphavantage_quote(self, symbol: str) -> Optional[StockQuote]:
        """Fetch quote from Alpha Vantage GLOBAL_QUOTE endpoint (fallback).

        Free tier: 5 req/min, 500/day. Returns None on any failure so the
        caller can chain to the next source.
        """
        if not self.alphavantage_key:
            return None

        def _sync_fetch() -> Optional[Dict]:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": self.alphavantage_key,
            }
            # One retry on 429 (rate limited) with 12s backoff — AV free tier
            # is 5/min, so 12s is a safe minimum.
            for attempt in range(2):
                try:
                    resp = requests.get(url, params=params, timeout=10.0)
                except requests.RequestException as exc:
                    logger.debug("Alpha Vantage request error: %s", exc)
                    return None
                if resp.status_code == 429 and attempt == 0:
                    time.sleep(12)
                    continue
                if resp.status_code != 200:
                    logger.debug(
                        "Alpha Vantage HTTP %s for %s", resp.status_code, symbol
                    )
                    return None
                try:
                    payload = resp.json()
                except ValueError:
                    return None
                # AV returns {"Note": "..."} on throttle and {"Global Quote": {...}} on success
                if "Note" in payload or "Information" in payload:
                    logger.debug("Alpha Vantage throttle/info: %s", payload)
                    return None
                return payload.get("Global Quote")
            return None

        try:
            loop = asyncio.get_event_loop()
            gq = await loop.run_in_executor(self._executor, _sync_fetch)
        except Exception as exc:
            logger.debug("Alpha Vantage executor error: %s", exc)
            return None

        if not gq:
            return None

        def _num(key: str, default: float = 0.0) -> float:
            raw = gq.get(key, "")
            if isinstance(raw, str):
                raw = raw.strip().rstrip("%")
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default

        price = _num("05. price")
        if price <= 0:
            return None
        prev_close = _num("08. previous close")
        change = _num("09. change")
        change_pct = _num("10. change percent")

        return StockQuote(
            symbol=symbol.upper(),
            price=VerifiedDataPoint(
                value=price,
                source="AlphaVantage",
                freshness="15-min delayed",
                unit="USD",
            ),
            change=change,
            change_pct=change_pct,
            volume=int(_num("06. volume")),
            high=_num("03. high"),
            low=_num("04. low"),
            open=_num("02. open"),
            prev_close=prev_close,
            market="us",
            currency="USD",
        )

    async def _get_yfinance_quote(self, symbol: str, market: str = "us") -> Optional[StockQuote]:
        """Fetch quote from yfinance (fallback)."""
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                self._executor,
                self._sync_yfinance_quote, symbol
            )
            if not data:
                return None

            currency = "USD"
            if market in ("cn", "a-share"):
                currency = "CNY"
            elif market == "hk":
                currency = "HKD"

            return StockQuote(
                symbol=symbol,
                price=VerifiedDataPoint(
                    value=data.get("price", 0),
                    source="yfinance",
                    freshness="15-min delayed",
                    unit=currency,
                ),
                change=data.get("change", 0),
                change_pct=data.get("change_pct", 0),
                volume=data.get("volume", 0),
                high=data.get("high", 0),
                low=data.get("low", 0),
                open=data.get("open", 0),
                prev_close=data.get("prev_close", 0),
                market_cap=data.get("market_cap"),
                pe_ratio=data.get("pe_ratio"),
                name=data.get("name", ""),
                market=market,
                currency=currency,
            )
        except Exception:
            return None

    def _sync_yfinance_quote(self, symbol: str) -> Optional[Dict]:
        """Synchronous yfinance fetch (runs in thread pool)."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if not info or "regularMarketPrice" not in info:
                return None
            return {
                "price": info.get("regularMarketPrice", 0),
                "change": info.get("regularMarketChange", 0),
                "change_pct": info.get("regularMarketChangePercent", 0),
                "volume": info.get("regularMarketVolume", 0),
                "high": info.get("regularMarketDayHigh", 0),
                "low": info.get("regularMarketDayLow", 0),
                "open": info.get("regularMarketOpen", 0),
                "prev_close": info.get("regularMarketPreviousClose", 0),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "name": info.get("longName", ""),
            }
        except Exception:
            return None

    async def _get_akshare_quote(self, symbol: str, market: str) -> Optional[StockQuote]:
        """Fetch Chinese stock quote from AKShare."""
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                self._executor,
                self._sync_akshare_quote, symbol, market
            )
            return data
        except Exception:
            return None

    def _sync_akshare_quote(self, symbol: str, market: str) -> Optional[StockQuote]:
        """Synchronous AKShare fetch."""
        try:
            if market in ("cn", "a-share"):
                df = ak.stock_zh_a_spot_em()
                row = df[df["代码"] == symbol]
                if row.empty:
                    return None
                row = row.iloc[0]
                price = float(row.get("最新价", 0))
                return StockQuote(
                    symbol=symbol,
                    price=VerifiedDataPoint(
                        value=price,
                        source="AKShare",
                        freshness="15-min delayed",
                        unit="CNY",
                    ),
                    change=float(row.get("涨跌额", 0)),
                    change_pct=float(row.get("涨跌幅", 0)),
                    volume=int(row.get("成交量", 0)),
                    high=float(row.get("最高", 0)),
                    low=float(row.get("最低", 0)),
                    open=float(row.get("今开", 0)),
                    name=str(row.get("名称", "")),
                    market=market,
                    currency="CNY",
                )
        except Exception:
            return None

    # ── Crypto Quotes ─────────────────────────────────────────────────

    async def get_crypto(self, coin_id: str) -> Optional[CryptoQuote]:
        """
        Get crypto price from CoinGecko (primary) or Binance (fallback).
        """
        cache_key = f"crypto_{coin_id}"
        cached = self.cache.get(cache_key, ttl=300)
        if cached:
            return cached

        quote = await self._get_coingecko_quote(coin_id)
        if not quote:
            quote = await self._get_binance_quote(coin_id)

        if quote:
            self.cache.set(cache_key, quote)
        return quote

    async def _get_coingecko_quote(self, coin_id: str) -> Optional[CryptoQuote]:
        """Fetch from CoinGecko public API (no auth needed, 30 calls/min)."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self._executor, self._sync_coingecko, coin_id
            )
        except Exception:
            return None

    def _sync_coingecko(self, coin_id: str) -> Optional[CryptoQuote]:
        """Synchronous CoinGecko fetch."""
        try:
            resp = requests.get(
                f"https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": coin_id,
                    "order": "market_cap_desc",
                    "per_page": 1,
                    "page": 1,
                    "sparkline": "false",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data:
                return None
            d = data[0]

            return CryptoQuote(
                coin_id=d["id"],
                symbol=d["symbol"].upper(),
                name=d["name"],
                price=VerifiedDataPoint(
                    value=d["current_price"],
                    source="CoinGecko",
                    freshness="real-time",
                ),
                change_24h_pct=d.get("price_change_percentage_24h", 0),
                volume_24h=d.get("total_volume", 0),
                market_cap=d.get("market_cap", 0),
                rank=d.get("market_cap_rank", 0),
            )
        except Exception:
            return None

    async def _get_binance_quote(self, coin_id: str) -> Optional[CryptoQuote]:
        """Fallback: Binance public API (no auth, unlimited)."""
        # Map common coin IDs to Binance symbols
        symbol_map = {
            "bitcoin": "BTCUSDT",
            "ethereum": "ETHUSDT",
            "solana": "SOLUSDT",
            "ripple": "XRPUSDT",
            "dogecoin": "DOGEUSDT",
        }
        binance_symbol = symbol_map.get(coin_id.lower())
        if not binance_symbol:
            binance_symbol = f"{coin_id.upper()}USDT"

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self._executor,
                self._sync_binance, coin_id, binance_symbol
            )
        except Exception:
            return None

    def _sync_binance(self, coin_id: str, symbol: str) -> Optional[CryptoQuote]:
        try:
            resp = requests.get(
                f"https://api.binance.com/api/v3/ticker/24hr",
                params={"symbol": symbol},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            d = resp.json()

            return CryptoQuote(
                coin_id=coin_id,
                symbol=symbol.replace("USDT", ""),
                name=coin_id.title(),
                price=VerifiedDataPoint(
                    value=float(d["lastPrice"]),
                    source="Binance",
                    freshness="real-time",
                ),
                change_24h_pct=float(d.get("priceChangePercent", 0)),
                volume_24h=float(d.get("quoteVolume", 0)),
            )
        except Exception:
            return None

    # ── Financial News ────────────────────────────────────────────────

    async def get_news(
        self,
        symbol: Optional[str] = None,
        category: str = "general",
    ) -> List[NewsItem]:
        """Get financial news from Finnhub."""
        if not self.finnhub_client:
            return []

        try:
            loop = asyncio.get_event_loop()
            if symbol:
                news = await loop.run_in_executor(
                    self._executor,
                    lambda: self.finnhub_client.company_news(
                        symbol,
                        _from=datetime.now().strftime("%Y-%m-%d"),
                        to=datetime.now().strftime("%Y-%m-%d"),
                    )
                )
            else:
                news = await loop.run_in_executor(
                    self._executor,
                    lambda: self.finnhub_client.general_news(category)
                )

            return [
                NewsItem(
                    title=n.get("headline", ""),
                    url=n.get("url", ""),
                    source=n.get("source", "finnhub"),
                    published=datetime.fromtimestamp(n["datetime"], tz=timezone.utc) if n.get("datetime") else None,
                    summary=n.get("summary", "")[:300],
                    symbols=[symbol] if symbol else [],
                    category=n.get("category", category),
                )
                for n in (news or [])[:20]
            ]
        except Exception:
            return []

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> str:
        """Get human-readable status of all data sources."""
        lines = ["Finance Data Sources", "=" * 50]

        # US Stocks
        lines.append("\n  US Stocks:")
        if self.finnhub_client:
            lines.append("    ✅ Finnhub (primary, 60 calls/min)")
        else:
            lines.append("    ⚠️  Finnhub: not configured (set FINNHUB_API_KEY)")
        if HAS_YFINANCE:
            lines.append("    ✅ yfinance (fallback)")
        else:
            lines.append("    ❌ yfinance: not installed")

        # China/HK
        lines.append("\n  China / HK:")
        if HAS_AKSHARE:
            lines.append("    ✅ AKShare (primary, free)")
        else:
            lines.append("    ❌ AKShare: not installed")

        # Crypto
        lines.append("\n  Crypto:")
        lines.append("    ✅ CoinGecko (primary, 30/min)")
        lines.append("    ✅ Binance (fallback, unlimited)")

        # Market status
        lines.append("\n  Market Status:")
        for market in ["us", "cn", "hk", "crypto"]:
            status = get_market_status(market)
            label = {"us": "US", "cn": "China A", "hk": "Hong Kong", "crypto": "Crypto"}[market]
            lines.append(f"    {label}: {status}")

        return "\n".join(lines)

    # ── Social Sentiment ─────────────────────────────────────────────

    async def get_social_sentiment(
        self,
        symbol: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch social sentiment data from Finnhub.

        Returns aggregated Reddit + Twitter mention/sentiment for a symbol.
        Finnhub endpoint: /stock/social-sentiment  (free tier supported)

        Reference: https://finnhub.io/docs/api/social-sentiment

        Returns:
            Dict with keys: symbol, reddit_mentions, reddit_score,
                            twitter_mentions, twitter_score, overall_score,
                            source, timestamp
            or None if unavailable.
        """
        # Check cache first (works even if finnhub_client is unavailable)
        cache_key = f"social_sentiment_{symbol}"
        cached = self.cache.get(cache_key, ttl=1800)  # 30-min cache
        if cached:
            return cached

        if not self.finnhub_client:
            return None

        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                self._executor,
                lambda: self.finnhub_client.stock_social_sentiment(symbol)
            )

            if not data:
                return None

            # Aggregate Reddit data
            reddit = data.get("reddit", [])
            reddit_mentions = sum(r.get("mention", 0) for r in reddit[-24:])
            reddit_pos = sum(r.get("positiveMention", 0) for r in reddit[-24:])
            reddit_neg = sum(r.get("negativeMention", 0) for r in reddit[-24:])
            reddit_total = reddit_pos + reddit_neg
            reddit_score = (reddit_pos / reddit_total) if reddit_total > 0 else 0.5

            # Aggregate Twitter data
            twitter = data.get("twitter", [])
            twitter_mentions = sum(t.get("mention", 0) for t in twitter[-24:])
            twitter_pos = sum(t.get("positiveMention", 0) for t in twitter[-24:])
            twitter_neg = sum(t.get("negativeMention", 0) for t in twitter[-24:])
            twitter_total = twitter_pos + twitter_neg
            twitter_score = (twitter_pos / twitter_total) if twitter_total > 0 else 0.5

            # Overall: weighted average (Twitter higher volume → lower weight per mention)
            total_mentions = reddit_mentions + twitter_mentions
            if total_mentions > 0:
                overall_score = (
                    reddit_score * reddit_mentions * 1.2 +
                    twitter_score * twitter_mentions
                ) / (reddit_mentions * 1.2 + twitter_mentions)
            else:
                overall_score = 0.5

            result = {
                "symbol": symbol,
                "reddit_mentions": reddit_mentions,
                "reddit_score": round(reddit_score, 3),
                "twitter_mentions": twitter_mentions,
                "twitter_score": round(twitter_score, 3),
                "total_mentions": total_mentions,
                "overall_score": round(overall_score, 3),
                # Buzz level: how much attention relative to normal
                "buzz_level": "high" if total_mentions > 100 else "medium" if total_mentions > 20 else "low",
                "source": "Finnhub Social Sentiment",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.cache.set(cache_key, result)
            return result

        except Exception:
            return None
