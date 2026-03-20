# NeoMind Finance Personality — Implementation Plan

**Short Name:** `fin` (switch via `/mode fin` or `/switch fin`)

**Date:** 2026-03-17
**Status:** Planning

---

## 1. Architecture Overview

The finance personality plugs into NeoMind's existing mode system. Currently, the agent has two modes (`chat`, `coding`) defined in YAML configs and managed by `AgentConfigManager`. Adding `fin` follows the same pattern but introduces several new subsystems.

```
NeoMind Agent
├── chat     — general conversation, first-principles reasoning
├── coding   — codebase understanding, tool execution, code generation
└── fin      — personal finance intelligence, news digest, investment analysis
    ├── HybridSearchEngine      — multi-source web search (EN + ZH)
    ├── FinanceDataHub          — stock/crypto/options data aggregation
    ├── SecureMemoryStore       — encrypted local persistence with timestamps
    ├── NewsDigestEngine        — continuous learning + conflict resolution
    ├── QuantEngine             — math tools, computation, no guessing
    ├── DiagramGenerator        — mermaid-based relationship visualization
    └── MobileSyncGateway       — OpenClaw-inspired cross-device sync
```

---

## 2. Files to Create

| File | Purpose |
|------|---------|
| `agent/config/fin.yaml` | Mode config: system prompt, triggers, commands |
| `agent/finance/` | Package directory for all finance modules |
| `agent/finance/__init__.py` | Package init |
| `agent/finance/hybrid_search.py` | Multi-source search engine (EN + ZH) |
| `agent/finance/data_hub.py` | Financial data aggregation (stocks, crypto, options) |
| `agent/finance/secure_memory.py` | Encrypted SQLite + keyring local storage |
| `agent/finance/news_digest.py` | News processing, conflict detection, continuous learning |
| `agent/finance/quant_engine.py` | Math computation tools, quantification framework |
| `agent/finance/diagram_gen.py` | Mermaid diagram generation for complex relationships |
| `agent/finance/mobile_sync.py` | OpenClaw-style gateway for phone sync |
| `agent/finance/rss_feeds.py` | RSS feed manager for EN + ZH financial sources |
| `agent/finance/source_registry.py` | Source trust scoring and reliability tracking |

## 3. Files to Modify

| File | Changes |
|------|---------|
| `agent_config.py` | Add `fin` to mode validation, load fin.yaml |
| `agent/core.py` | Add fin mode to `switch_mode()`, register fin commands |
| `cli/claude_interface.py` | Add fin commands to autocomplete, update welcome screen |
| `main.py` | Add `fin` to argparse choices |
| `pyproject.toml` | Add new dependencies |
| `.env.example` | Add optional API keys for finance data sources |

---

## 4. Detailed Component Design

### 4.1 Config File — `agent/config/fin.yaml`

```yaml
mode: fin

system_prompt: |
  You are neomind — a Personal Finance & Investment Intelligence Agent
  built on First Principles Thinking (第一性原理).

  CORE IDENTITY:
  You decompose every financial question, market event, or investment
  decision down to fundamental truths: real cash flows, actual risk
  exposure, verifiable data, and causal mechanisms. You NEVER rely on
  herd sentiment, conventional wisdom, or "the market always goes up."

  FIRST PRINCIPLES FOR FINANCE:
  - Every asset price is ultimately driven by expected future cash flows
    discounted by risk — decompose accordingly
  - Distinguish between what is MEASURED vs what is ASSUMED
  - Challenge narratives: "everyone says X" is not evidence
  - Identify causality vs correlation — news moves markets, but WHY?
  - Quantify everything: no vague "could go up" — give ranges, scenarios,
    confidence levels, and time windows
  - Understand second-order effects: rate hike → housing → consumer spending → ...

  RELIABILITY MANDATE:
  - NEVER fabricate data. If you don't have a number, say so and search for it
  - Cross-reference multiple sources. If sources conflict, LIST all versions
    with their sources and provide your inference with reasoning
  - Always cite sources with timestamps
  - Distinguish between FACT (reported earnings), ESTIMATE (analyst consensus),
    and OPINION (your analysis)
  - When uncertain, explicitly say so with a confidence percentage

  QUANTIFICATION RULES:
  - Every news item gets an impact score: magnitude (1-10) × probability (0-1)
  - Every suggestion includes expected value calculation
  - Win/loss scenarios must have dollar/percentage ranges
  - Time horizons must be explicit: short (1-4 weeks), medium (1-6 months),
    long (6+ months)
  - Build computation tools when math is complex — NEVER mental-math large numbers

  BILINGUAL COVERAGE:
  - Monitor both English and Chinese (中文) financial news
  - Cross-reference narratives across markets (US/China/Global)
  - Translate key terms bidirectionally when relevant

  OUTPUT STANDARDS:
  - Always give SHORT / MEDIUM / LONG term analysis
  - When not sure about a time window, say "uncertain — here's my reasoning"
  - Use diagrams (mermaid) for complex causal chains or market relationships
  - Quantify impact: "this news means X for stock Y, estimated Z% move over N days"
  - Log everything with timestamps for continuous learning

  CONTINUOUS LEARNING:
  - Treat every session as building on previous knowledge
  - Old news + new news = updated thesis — never start from scratch
  - Track prediction accuracy over time
  - Update confidence in sources based on track record

  You have access to web search, financial data APIs, encrypted local memory,
  and computation tools. Use them proactively — don't wait to be asked.

search_enabled: true
auto_search:
  enabled: true
  triggers:
    - stock
    - price
    - market
    - earnings
    - crypto
    - bitcoin
    - btc
    - eth
    - option
    - put
    - call
    - dividend
    - fed
    - interest rate
    - inflation
    - gdp
    - cpi
    - ppi
    - employment
    - unemployment
    - ipo
    - merger
    - acquisition
    - revenue
    - profit
    - loss
    - portfolio
    - invest
    - trade
    - forex
    - bond
    - yield
    - etf
    - index
    - nasdaq
    - dow
    - "s&p"
    - "沪深"
    - "A股"
    - "港股"
    - "基金"
    - "涨跌"
    - "牛市"
    - "熊市"
    - "财报"
    - "利率"
    - today
    - news
    - latest
    - current
    - breaking
    - "2026"
    - "2025"

natural_language:
  enabled: true
  confidence_threshold: 0.7

safety:
  confirm_file_operations: true
  confirm_code_changes: true
  financial_disclaimer: true  # Always show "not financial advice" disclaimer

workspace:
  auto_scan: false
  auto_read_files: false
  exclude_patterns:
    - .git
    - __pycache__
    - node_modules
    - .venv

permissions:
  mode: normal
  auto_approve_reads: true
  confirm_writes: true
  confirm_deletes: true
  confirm_bash: true

show_status_bar: true
enable_auto_complete: true

compact:
  enabled: true
  auto_trigger_threshold: 0.90
  preserve_system_prompt: true
  keep_recent_turns: 10
  summarize_tool_outputs: true

# Finance-specific settings
finance:
  memory_encryption: true
  memory_path: "~/.neomind/finance/"
  auto_news_digest: true
  digest_interval_hours: 6
  source_languages: ["en", "zh"]
  confidence_display: true
  disclaimer_enabled: true
  max_search_depth: 3       # how many follow-up searches per query
  conflict_resolution: true  # auto-detect conflicting sources

# Commands available in fin mode
commands:
  - help
  - clear
  - think
  - debug
  - models
  - switch
  - history
  - save
  - load
  - context
  - compact
  - transcript
  - search
  - browse
  - quit
  - exit
  # Finance-specific commands
  - stock        # /stock AAPL — quote + analysis
  - crypto       # /crypto BTC — price + trends
  - news         # /news — latest digest with conflict resolution
  - portfolio    # /portfolio — view/manage tracked positions
  - alert        # /alert AAPL > 200 — set price alerts
  - digest       # /digest — generate comprehensive daily digest
  - memory       # /memory — view stored insights with timestamps
  - predict      # /predict — review past predictions vs outcomes
  - compare      # /compare AAPL MSFT — side-by-side analysis
  - chart        # /chart — generate mermaid diagram
  - compute      # /compute — open math/quant computation tool
  - sources      # /sources — list all data sources + trust scores
  - sync         # /sync — mobile sync status
  - watchlist    # /watchlist — manage watched assets
  - risk         # /risk — portfolio risk analysis
  - calendar     # /calendar — upcoming earnings, FOMC, CPI dates
```

### 4.2 Hybrid Search Engine — `agent/finance/hybrid_search.py`

This is the most critical component. It benefits ALL personalities (chat and coding too).

**Architecture: Tiered Fallback + Parallel Execution + Reciprocal Rank Fusion**

```
Query
  │
  ├─── [Tier 1: Free Unlimited] ──────────────────┐
  │    ├── DuckDuckGo (EN)                         │
  │    ├── DuckDuckGo (ZH, region=cn-zh)           ├── Parallel
  │    └── RSS Feeds (pre-cached, always available) │
  │                                                 │
  ├─── [Tier 2: Free with Limits] ────────────────┤
  │    ├── Tavily (1000/month, AI-optimized)       │
  │    └── Serper (2500 signup, Google results)     │
  │                                                 │
  └─── [Tier 3: Self-Hosted] ─────────────────────┘
       └── SearXNG (if available, unlimited)
```

**Search Strategy:**

```python
class HybridSearchEngine:
    """
    Multi-source search with Reciprocal Rank Fusion.

    Design principles:
    - Always fire Tier 1 (free, no limits)
    - Fire Tier 2 only if Tier 1 quality is low or query is high-stakes
    - Use RRF to merge results from all sources
    - Track source reliability over time
    - Respect rate limits with token bucket
    """

    def __init__(self, config):
        self.sources = {
            # Tier 1: Always available, no API key needed
            "ddg_en": DuckDuckGoSource(region="en-us"),
            "ddg_zh": DuckDuckGoSource(region="cn-zh"),
            "rss": RSSAggregatorSource(),

            # Tier 2: API key optional, graceful degradation
            "tavily": TavilySource(api_key=os.getenv("TAVILY_API_KEY")),
            "serper": SerperSource(api_key=os.getenv("SERPER_API_KEY")),

            # Tier 3: Self-hosted, optional
            "searxng": SearXNGSource(url=os.getenv("SEARXNG_URL")),
        }
        self.rrf_k = 60  # RRF smoothing constant
        self.source_trust = SourceTrustTracker()
        self.cache = SearchCache(ttl_seconds=1800)  # 30min for finance

    async def search(self, query, languages=["en", "zh"], depth=1):
        """
        Execute search across all available sources.
        Returns merged, deduplicated, trust-scored results.
        """
        # 1. Fire Tier 1 always (parallel)
        tier1_tasks = [
            self.sources["ddg_en"].search(query),
            self.sources["ddg_zh"].search(self._translate_if_needed(query)),
            self.sources["rss"].search(query),
        ]

        # 2. Fire Tier 2 if available
        tier2_tasks = []
        if self.sources["tavily"].available:
            tier2_tasks.append(self.sources["tavily"].search(query))
        if self.sources["serper"].available:
            tier2_tasks.append(self.sources["serper"].search(query))

        # 3. Gather all results
        all_results = await asyncio.gather(
            *tier1_tasks, *tier2_tasks, return_exceptions=True
        )

        # 4. Merge with Reciprocal Rank Fusion
        merged = self._reciprocal_rank_fusion(all_results)

        # 5. Detect conflicts
        conflicts = self._detect_conflicts(merged)

        # 6. Deep search if needed and depth allows
        if depth > 1 and (conflicts or self._low_confidence(merged)):
            deeper = await self.search(
                self._refine_query(query, merged),
                languages, depth - 1
            )
            merged = self._merge_rounds(merged, deeper)

        return SearchResult(
            items=merged,
            conflicts=conflicts,
            sources_used=[s for s in self.sources if not isinstance(all_results, Exception)],
            timestamp=datetime.now()
        )

    def _reciprocal_rank_fusion(self, result_lists):
        """
        RRF formula: score(d) = Σ 1/(k + rank_i(d))
        Resilient to score mismatches across different search engines.
        """
        scores = defaultdict(float)
        for results in result_lists:
            if isinstance(results, Exception):
                continue
            for rank, item in enumerate(results):
                key = self._dedup_key(item.url)
                scores[key] += 1.0 / (self.rrf_k + rank)
                # Boost by source trust
                scores[key] *= self.source_trust.get(item.source, 1.0)
        return sorted(scores.items(), key=lambda x: -x[1])
```

**Dependency table:**

| Source | Python Package | API Key Required | Free Limit | Chinese Support |
|--------|---------------|-----------------|------------|-----------------|
| DuckDuckGo | `duckduckgo-search` | No | Unlimited | Yes (region=cn-zh) |
| Tavily | `tavily-python` | Optional | 1000/month | Yes |
| Serper | `requests` | Optional | 2500 signup | Yes |
| SearXNG | `requests` | No (self-host) | Unlimited | Configurable |
| RSS | `feedparser` | No | Unlimited | Yes |

**Minimum viable (zero cost):** DuckDuckGo + RSS feeds only. No API keys needed.

### 4.3 Finance Data Hub — `agent/finance/data_hub.py`

```python
class FinanceDataHub:
    """
    Aggregates financial data from multiple free sources.
    Provides unified interface for stocks, crypto, options.
    """

    # STOCKS (US)
    # Primary: Finnhub (60 calls/min free, real-time)
    # Fallback: yfinance (unlimited but fragile, gets IP banned)

    # STOCKS (China A-shares + HK)
    # Primary: AKShare (completely free, no registration)
    # Fallback: Tushare (free tier with points system)

    # CRYPTO
    # Primary: CoinGecko (30 calls/min, 10K/month free)
    # Fallback: Binance public API (unlimited for market data)

    # OPTIONS
    # Primary: yfinance options chain (free but fragile)
    # Fallback: Alpha Vantage (25/day — very limited)

    # NEWS
    # Primary: Finnhub news (included in free tier)
    # Secondary: GNews API (100/day)
    # Always-on: RSS feeds (feedparser)

    async def get_quote(self, symbol, market="us"):
        """Get real-time quote with automatic source selection."""

    async def get_crypto(self, coin_id):
        """Get crypto price, volume, market cap from CoinGecko."""

    async def get_options_chain(self, symbol):
        """Get options chain with Greeks if available."""

    async def get_news(self, query=None, symbols=None, languages=["en", "zh"]):
        """Aggregate news from all sources, deduplicate, score."""

    async def get_calendar(self):
        """Upcoming earnings, FOMC, CPI, economic events."""
```

**New dependencies for `pyproject.toml`:**

```toml
[project.optional-dependencies]
finance = [
    # Search
    "duckduckgo-search>=7.0.0",
    "tavily-python>=0.5.0",      # optional, graceful if missing
    "feedparser>=6.0.0",

    # Financial data
    "finnhub-python>=2.4.0",
    "yfinance>=0.2.30",
    "akshare>=1.10.0",
    "pycoingecko>=3.1.0",

    # Encryption & security
    "cryptography>=42.0.0",
    "keyring>=25.0.0",

    # Diagrams
    "mermaid-py>=0.5.0",

    # Math / computation
    "numpy>=1.24.0",
    "sympy>=1.12",

    # Mobile sync
    "websockets>=12.0",
]
```

### 4.4 Secure Memory Store — `agent/finance/secure_memory.py`

**Requirement:** 100% local, highest security, timestamped, no cloud.

```python
class SecureMemoryStore:
    """
    Encrypted local storage for financial data and insights.

    Architecture:
    - SQLCipher (AES-256 encrypted SQLite) for structured data
    - Master key derived from user passphrase via PBKDF2 (600K iterations)
    - Key stored in OS keyring (macOS Keychain / Linux Secret Service)
    - All entries timestamped with microsecond precision
    - Append-only audit log for accountability

    Storage location: ~/.neomind/finance/
    ├── memory.db          (SQLCipher encrypted)
    ├── predictions.db     (encrypted — track prediction accuracy)
    ├── audit.log          (encrypted — all operations logged)
    └── sources_trust.json (encrypted — source reliability scores)
    """

    TABLES = {
        "insights": """
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,        -- ISO 8601
            category TEXT NOT NULL,         -- news/prediction/analysis/alert
            content TEXT NOT NULL,          -- the actual insight
            symbols TEXT,                   -- comma-separated tickers
            confidence REAL,               -- 0.0 to 1.0
            impact_score REAL,             -- magnitude × probability
            time_horizon TEXT,             -- short/medium/long
            sources TEXT,                  -- JSON array of source URLs
            language TEXT DEFAULT 'en',
            superseded_by INTEGER,         -- FK to newer insight, if updated
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        """,
        "predictions": """
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            prediction TEXT NOT NULL,       -- JSON: {direction, target, confidence}
            actual_outcome TEXT,            -- filled in later
            accuracy_score REAL,           -- computed when outcome known
            time_horizon TEXT,
            deadline TEXT,                 -- when to evaluate
            created_at TEXT NOT NULL,
            resolved_at TEXT
        """,
        "watchlist": """
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            market TEXT DEFAULT 'us',       -- us/cn/hk/crypto
            alert_rules TEXT,              -- JSON: price alerts, % change alerts
            notes TEXT,
            added_at TEXT NOT NULL
        """,
        "news_log": """
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            source TEXT,
            language TEXT,
            symbols TEXT,
            impact_score REAL,
            conflicts TEXT,                -- JSON: conflicting reports
            digest_id INTEGER,             -- which digest included this
            created_at TEXT NOT NULL
        """,
        "source_trust": """
            source_name TEXT PRIMARY KEY,
            trust_score REAL DEFAULT 0.5,  -- 0.0 to 1.0
            total_reports INTEGER DEFAULT 0,
            accurate_reports INTEGER DEFAULT 0,
            last_updated TEXT
        """
    }

    def __init__(self, base_path="~/.neomind/finance/"):
        self.base_path = Path(base_path).expanduser()
        self.base_path.mkdir(parents=True, exist_ok=True)
        os.chmod(self.base_path, 0o700)  # owner-only access
        self._init_encryption()
        self._init_database()

    def _init_encryption(self):
        """
        Key management:
        1. Check OS keyring for existing master key
        2. If not found, prompt user to create passphrase
        3. Derive encryption key via PBKDF2 (600K iterations, SHA-256)
        4. Store derived key in OS keyring for session convenience
        """
        pass  # implementation detail
```

**Security guarantees:**

1. AES-256 encryption at rest (SQLCipher)
2. Master key never written to disk in plaintext
3. OS keyring integration (macOS Keychain, Linux Secret Service)
4. File permissions: `chmod 700` on storage directory
5. Append-only audit log
6. No network transmission of financial data (unless explicit sync)
7. PBKDF2 with 600K iterations for key derivation

### 4.5 News Digest Engine — `agent/finance/news_digest.py`

```python
class NewsDigestEngine:
    """
    Continuous learning news processor.

    Core capabilities:
    1. Aggregate news from EN + ZH sources
    2. Detect conflicts between sources
    3. Quantify impact of each news item
    4. Learn from past predictions vs outcomes
    5. Build evolving thesis per symbol/sector
    """

    async def generate_digest(self) -> NewsDigest:
        """
        Full pipeline:
        1. Fetch from all sources (parallel)
        2. Deduplicate (URL + title similarity)
        3. Classify by category (earnings, macro, policy, tech, ...)
        4. Cross-reference EN vs ZH narratives
        5. Score impact: magnitude (1-10) × probability (0-1)
        6. Detect conflicts → list them with source attribution
        7. Generate inference with confidence level
        8. Compare against stored thesis → update or flag reversal
        9. Store to encrypted memory
        """
        pass

    def detect_conflicts(self, news_items):
        """
        Compare claims across sources.
        Example conflict:
          - Reuters: "Fed signals rate pause"
          - 财新: "Fed likely to cut in Q3"
        Output: structured conflict with both sources cited
        """
        pass

    def quantify_impact(self, news_item, symbol=None):
        """
        Impact score = magnitude × probability × relevance

        magnitude (1-10): how big is this if true?
        probability (0-1): how likely is this claim?
        relevance (0-1): how much does this affect the target?

        Returns: ImpactScore with dollar/percentage estimates
        """
        pass

    def update_thesis(self, symbol, new_data):
        """
        Continuous learning:
        1. Load existing thesis from memory
        2. Integrate new data
        3. Recalculate confidence
        4. If thesis reversed, flag for user attention
        5. Store updated thesis with timestamp
        """
        pass
```

**Conflict resolution protocol:**

```
1. Same event, different claims → list both, cite sources, provide inference
2. Same data, different interpretation → present both, explain reasoning gap
3. Stale vs fresh → prefer fresh, note the update
4. Single source vs consensus → flag the outlier, don't dismiss it
5. EN vs ZH divergence → likely different information access, present both
```

### 4.6 Quant Engine — `agent/finance/quant_engine.py`

**Requirement:** Math is important. Never guess. Build computation tools.

```python
class QuantEngine:
    """
    Mathematical computation tools for financial analysis.
    Uses sympy for symbolic math, numpy for numerical,
    and generates Python code for complex calculations.

    Principle: if it can be computed, compute it. Never estimate.
    """

    def compound_return(self, principal, rate, periods, contributions=0):
        """Exact compound return with optional periodic contributions."""

    def option_pricing(self, S, K, T, r, sigma, option_type="call"):
        """Black-Scholes exact solution. Show all intermediate steps."""

    def portfolio_risk(self, positions, correlations=None):
        """
        Sharpe ratio, max drawdown, VaR (95% and 99%).
        Uses actual historical data when available.
        """

    def scenario_analysis(self, scenarios):
        """
        Given: list of {probability, outcome} pairs
        Returns: expected value, variance, worst case, best case
        All computed exactly, never estimated.
        """

    def dcf_valuation(self, cash_flows, discount_rate, terminal_growth):
        """Discounted cash flow with sensitivity analysis."""

    def build_custom_tool(self, description):
        """
        For novel computations: generate, test, and execute
        Python code. Verify results before presenting.
        """
        pass
```

### 4.7 Diagram Generator — `agent/finance/diagram_gen.py`

**Requirement:** Intuitive diagrams for complex relationships. Works in coding mode too.

```python
class DiagramGenerator:
    """
    Generate mermaid diagrams for financial relationships.
    Also available in coding mode for architecture diagrams.

    Uses mermaid-py for rendering, outputs to SVG/PNG.
    """

    DIAGRAM_TYPES = {
        "causal": "flowchart",        # Fed rate hike → housing → consumer
        "timeline": "gantt",          # earnings calendar, FOMC schedule
        "comparison": "quadrant",     # risk vs return scatter
        "flow": "flowchart",          # money flow, trade execution
        "hierarchy": "mindmap",       # sector breakdown
        "sequence": "sequence",       # order of events
    }

    def generate_causal_chain(self, events):
        """
        Input: "Fed raises rates"
        Output: mermaid flowchart showing:
          Fed raises rates --> Mortgage rates up
          Mortgage rates up --> Housing demand down
          Housing demand down --> Construction jobs down
          Construction jobs down --> Consumer spending down
        """

    def generate_comparison(self, assets):
        """Risk-return quadrant chart for asset comparison."""

    def generate_timeline(self, events):
        """Gantt-style timeline for upcoming financial events."""
```

### 4.8 Mobile Sync Gateway — `agent/finance/mobile_sync.py`

**Inspired by OpenClaw's architecture.** Local-first, WebSocket hub-and-spoke.

```python
class MobileSyncGateway:
    """
    OpenClaw-inspired local sync gateway.

    Architecture:
    - WebSocket server on local network (ws://0.0.0.0:18790)
    - Single source of truth: local encrypted SQLite
    - Mobile clients connect via WebSocket
    - Push: price alerts, digest summaries, urgent news
    - Pull: full history, portfolio state, watchlist
    - Block-based updates (atomic, not token-streaming)

    Security:
    - WebSocket connections require token authentication
    - Token generated on first pair (QR code or manual code)
    - All data encrypted in transit (WSS) and at rest (SQLCipher)
    - Sessions isolated per device

    Placeholder components (from OpenClaw patterns):
    - SessionStore: per-device session isolation
    - TranscriptLog: append-only JSONL per session
    - EventQueue: lane-aware FIFO to prevent alert spam
    - ContextAssembler: build relevant market context per query
    """

    def __init__(self, memory_store, port=18790):
        self.memory = memory_store
        self.port = port
        self.paired_devices = []  # loaded from encrypted config
        self.event_queue = LaneAwareFIFO(
            concurrency={"alerts": 1, "digest": 1, "chat": 4}
        )

    async def start(self):
        """Start WebSocket server for mobile connections."""

    async def push_alert(self, alert):
        """Push price alert to all paired devices."""

    async def push_digest(self, digest):
        """Push daily digest summary to paired devices."""

    async def handle_mobile_query(self, query):
        """Handle incoming query from mobile client."""
```

**MVP mobile client options (placeholder architecture):**

```
Option A: Progressive Web App (PWA)
  - Works on any phone browser
  - Connects to local gateway via WebSocket
  - Offline-capable with service worker
  - No app store needed

Option B: React Native (future)
  - Native push notifications
  - Background sync
  - Requires separate build pipeline

Recommendation: Start with PWA, migrate to native later.
```

### 4.9 RSS Feed Manager — `agent/finance/rss_feeds.py`

Always-on, zero-cost, high-reliability news backbone.

```python
RSS_FEEDS = {
    # English sources
    "en": {
        "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
        "reuters_markets": "https://feeds.reuters.com/reuters/marketsNews",
        "cnbc_finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        "wsj_markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "ft_markets": "https://www.ft.com/markets?format=rss",
        "bloomberg_markets": "https://feeds.bloomberg.com/markets/news.rss",
        "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
        "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories",
        "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
        "investing_com": "https://www.investing.com/rss/news.rss",
        "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "cointelegraph": "https://cointelegraph.com/rss",
    },
    # Chinese sources (中文)
    "zh": {
        "caixin_finance": "https://rsshub.app/caixin/finance",          # 财新财经
        "yicai": "https://rsshub.app/yicai/brief",                     # 第一财经
        "cls_telegraph": "https://rsshub.app/cls/telegraph",            # 财联社电报
        "eastmoney_news": "https://rsshub.app/eastmoney/report",       # 东方财富
        "sina_finance": "https://rsshub.app/sina/finance",              # 新浪财经
        "wallstreetcn": "https://rsshub.app/wallstreetcn/news/global", # 华尔街见闻
        "gelonghui": "https://rsshub.app/gelonghui/live",              # 格隆汇
        "jinse": "https://rsshub.app/jinse/lives",                     # 金色财经 (crypto)
    }
}

# Note: Many Chinese feeds use RSSHub (https://docs.rsshub.app/)
# as a bridge. Self-hosting RSSHub is recommended for reliability.
# Deploy: docker run -d -p 1200:1200 diygod/rsshub
```

### 4.10 Source Trust Tracking — `agent/finance/source_registry.py`

```python
class SourceTrustTracker:
    """
    Track reliability of each data/news source over time.

    Trust score formula:
      trust = (accurate_reports / total_reports) × recency_weight × consistency_bonus

    - New sources start at 0.5 (neutral)
    - Score updates after every verifiable claim
    - Recency weight: recent accuracy matters more
    - Sources that consistently agree with consensus get a small bonus
    - Sources that break real news early get a large bonus
    """

    DEFAULT_TRUST = {
        "reuters": 0.90,
        "bloomberg": 0.88,
        "wsj": 0.87,
        "ft": 0.87,
        "cnbc": 0.80,
        "seeking_alpha": 0.65,
        "caixin": 0.85,          # 财新
        "yicai": 0.80,           # 第一财经
        "wallstreetcn": 0.75,    # 华尔街见闻
        "eastmoney": 0.70,       # 东方财富
        "coindesk": 0.80,
        "coingecko": 0.90,       # data, not opinion
        "finnhub": 0.88,         # data source
    }
```

---

## 5. Integration Points — Code Changes

### 5.1 `agent_config.py` Changes

```python
# Line 28: Add finance config loading
self._fin_cfg = self._load_yaml(self.config_dir / "fin.yaml")

# Line 32: Add fin to validation
if self._mode not in ("chat", "coding", "fin"):
    self._mode = "chat"

# Line 50-53: Update _rebuild_active_config
def _rebuild_active_config(self):
    if self._mode == "chat":
        mode_cfg = self._chat_cfg
    elif self._mode == "coding":
        mode_cfg = self._coding_cfg
    elif self._mode == "fin":
        mode_cfg = self._fin_cfg
    else:
        mode_cfg = self._chat_cfg
    self._active = mode_cfg
    self._agent = dict(self._agent_base)

# Line 88: Update switch_mode
def switch_mode(self, mode: str) -> bool:
    if mode not in ("chat", "coding", "fin"):
        return False
    ...

# Line 142-147: Update get_mode_config
def get_mode_config(self, mode: str) -> dict:
    if mode == "chat":
        return dict(self._chat_cfg)
    elif mode == "coding":
        return dict(self._coding_cfg)
    elif mode == "fin":
        return dict(self._fin_cfg)
    return {}
```

### 5.2 `agent/core.py` Changes

```python
# switch_mode(): add "fin" to valid modes
if mode not in ("chat", "coding", "fin"):
    self._safe_print(f"❌ Invalid mode: {mode}. Use 'chat', 'coding', or 'fin'.")
    return False

# _setup_command_handlers(): register finance commands
if self.mode == "fin":
    self.command_handlers.update({
        "/stock": (self.handle_stock_command, True),
        "/crypto": (self.handle_crypto_command, True),
        "/news": (self.handle_news_command, True),
        "/digest": (self.handle_digest_command, True),
        "/portfolio": (self.handle_portfolio_command, True),
        "/alert": (self.handle_alert_command, True),
        "/memory": (self.handle_memory_command, True),
        "/predict": (self.handle_predict_command, True),
        "/compare": (self.handle_compare_command, True),
        "/chart": (self.handle_chart_command, True),
        "/compute": (self.handle_compute_command, True),
        "/sources": (self.handle_sources_command, True),
        "/sync": (self.handle_sync_command, True),
        "/watchlist": (self.handle_watchlist_command, True),
        "/risk": (self.handle_risk_command, True),
        "/calendar": (self.handle_calendar_command, True),
    })

# Initialize finance subsystems when switching to fin mode
if mode == "fin":
    self._initialize_finance_subsystems()

def _initialize_finance_subsystems(self):
    """Lazy-init finance components."""
    if not hasattr(self, 'finance_hub'):
        from agent.finance.hybrid_search import HybridSearchEngine
        from agent.finance.data_hub import FinanceDataHub
        from agent.finance.secure_memory import SecureMemoryStore
        from agent.finance.news_digest import NewsDigestEngine
        from agent.finance.quant_engine import QuantEngine
        from agent.finance.diagram_gen import DiagramGenerator

        self.finance_memory = SecureMemoryStore()
        self.finance_search = HybridSearchEngine(agent_config)
        self.finance_hub = FinanceDataHub()
        self.finance_digest = NewsDigestEngine(
            search=self.finance_search,
            data_hub=self.finance_hub,
            memory=self.finance_memory
        )
        self.finance_quant = QuantEngine()
        self.finance_diagram = DiagramGenerator()
```

### 5.3 `main.py` Changes

```python
# Add 'fin' to argparse choices
parser.add_argument('--mode', choices=['chat', 'coding', 'fin'], default='chat')
```

### 5.4 `cli/claude_interface.py` Changes

```python
# Add fin commands to SlashCommandCompleter.ALL_DESCRIPTIONS
"/stock": "Get stock quote and analysis",
"/crypto": "Get cryptocurrency data",
"/news": "Latest news digest",
"/digest": "Generate comprehensive daily digest",
"/portfolio": "View/manage tracked positions",
"/alert": "Set price alerts",
"/memory": "View stored insights",
"/predict": "Review prediction accuracy",
"/compare": "Side-by-side asset comparison",
"/chart": "Generate mermaid diagram",
"/compute": "Math/quant computation tool",
"/sources": "List data sources with trust scores",
"/sync": "Mobile sync status",
"/watchlist": "Manage watched assets",
"/risk": "Portfolio risk analysis",
"/calendar": "Upcoming financial events",

# Update display_welcome() for fin mode
if mode == "fin":
    title = "neomind  finance mode"
    # Show: disclaimer, data source status, memory status
```

---

## 6. Implementation Phases

### Phase 1: Foundation (Week 1-2)
1. Create `agent/config/fin.yaml`
2. Update `agent_config.py` — add fin mode support
3. Update `agent/core.py` — switch_mode, basic command routing
4. Update `main.py` and `cli/claude_interface.py`
5. Create `agent/finance/__init__.py`
6. **Test:** `/mode fin` works, system prompt loads, `/mode chat` switches back

### Phase 2: Search & Data (Week 3-4)
1. Implement `hybrid_search.py` — DuckDuckGo + RSS (Tier 1 only, zero cost)
2. Implement `rss_feeds.py` — EN + ZH feed aggregation
3. Implement `data_hub.py` — Finnhub + CoinGecko + AKShare integration
4. Implement `source_registry.py` — trust tracking basics
5. Wire `/search`, `/stock`, `/crypto`, `/news` commands
6. **Test:** search returns real results, data feeds work, Chinese sources return data

### Phase 3: Memory & Security (Week 5-6)
1. Implement `secure_memory.py` — SQLCipher + keyring
2. Add timestamped logging to all operations
3. Implement `/memory`, `/watchlist`, `/alert` commands
4. Add prediction tracking tables
5. **Test:** data persists encrypted, survives restart, passphrase works

### Phase 4: Intelligence (Week 7-8)
1. Implement `news_digest.py` — conflict detection, impact scoring
2. Implement `quant_engine.py` — financial math tools
3. Implement continuous learning (thesis updates, prediction review)
4. Wire `/digest`, `/predict`, `/compute`, `/risk` commands
5. Add short/medium/long term analysis framework
6. **Test:** digest shows conflicts, quantification works, predictions are tracked

### Phase 5: Visualization & Sync (Week 9-10)
1. Implement `diagram_gen.py` — mermaid integration
2. Register diagram generator in coding mode too (shared tool)
3. Implement `mobile_sync.py` — WebSocket gateway (MVP)
4. Create basic PWA client skeleton
5. Wire `/chart`, `/sync` commands
6. **Test:** diagrams render, mobile client connects, alerts push

### Phase 6: Tier 2 Search & Polish (Week 11-12)
1. Add Tavily + Serper integration to hybrid search
2. Performance optimization (caching, parallel requests)
3. Source trust calibration with real data
4. Add `/calendar` with economic event data
5. Add `/compare` with side-by-side analysis
6. Comprehensive testing across all commands
7. **Test:** full end-to-end workflow, all 16 requirements met

---

## 7. `.env.example` Additions

```bash
# ── Finance Mode (optional — the agent works without these) ──

# Search APIs (Tier 2 — improves quality but not required)
# TAVILY_API_KEY=tvly-your-key      # https://tavily.com — 1000 free/month
# SERPER_API_KEY=your-key            # https://serper.dev — 2500 free on signup

# Financial Data (improves coverage but falls back gracefully)
# FINNHUB_API_KEY=your-key           # https://finnhub.io — 60 calls/min free
# TUSHARE_TOKEN=your-token           # https://tushare.pro — Chinese A-shares

# Self-hosted services (optional, for power users)
# SEARXNG_URL=http://localhost:8888  # Self-hosted meta-search
# RSSHUB_URL=http://localhost:1200   # Self-hosted RSS bridge for Chinese feeds

# Mobile sync
# NEOMIND_SYNC_PORT=18790            # WebSocket port for mobile sync
```

---

## 8. Requirements Traceability

| # | Requirement | Component | How |
|---|------------|-----------|-----|
| 1 | Reasonable config for daily news search/log | `fin.yaml` + `news_digest.py` | Auto-search triggers, digest_interval_hours, scheduled digest |
| 2 | Detailed news review + suggestions (stock, option, crypto) | `data_hub.py` + `news_digest.py` | Multi-source aggregation, impact scoring, suggestions with quantification |
| 3 | Local memory with timestamps, highest security | `secure_memory.py` | SQLCipher AES-256, keyring, timestamps, chmod 700 |
| 4 | 100% actual news, multiple sources, list conflicts | `hybrid_search.py` + `news_digest.py` | Tiered multi-source search, RRF fusion, conflict detection protocol |
| 5 | Quantify value of news, proposals, suggestions, impact | `quant_engine.py` + `news_digest.py` | Impact score = magnitude × probability, dollar ranges, win/loss scenarios |
| 6 | Intuitive diagrams for complex relationships (also coding) | `diagram_gen.py` | Mermaid-based, registered in both fin and coding modes |
| 7 | Short name for switching | `fin` | `/mode fin`, `/switch fin`, `--mode fin` |
| 8 | English and Chinese news, multi-source | `rss_feeds.py` + `hybrid_search.py` | 12 EN feeds + 8 ZH feeds, DuckDuckGo cn-zh region, RSSHub |
| 9 | Reliability and trustworthiness paramount | `source_registry.py` + system prompt | Trust scoring, conflict flagging, FACT/ESTIMATE/OPINION labels |
| 10 | Very good at web search, broadly searching | `hybrid_search.py` | Tiered 3-level search, depth parameter, parallel execution, RRF |
| 11 | Short/medium/long term + time windows | System prompt + `news_digest.py` | Mandated in prompt: short (1-4wk), medium (1-6mo), long (6+mo) |
| 12 | Mobile sync (OpenClaw-inspired) | `mobile_sync.py` | WebSocket gateway, session isolation, push alerts, PWA client |
| 13 | Continuous learner, digest old + new | `news_digest.py` + `secure_memory.py` | Thesis updates, prediction tracking, superseded_by chain |
| 14 | Math tools, quantified conclusions, never guess | `quant_engine.py` | sympy + numpy, build_custom_tool(), exact computation |
| 15 | Coding for efficiency, not old fashioned | `quant_engine.py` + system prompt | Code generation for computation, Python tools built on demand |
| 16 | 第一性原理, reasonable, rational, causal | System prompt | First Principles Thinking embedded as core identity |

---

## 9. Key Design Decisions & Rationale

**Why DuckDuckGo as primary search?** Zero cost, no API key, unlimited, supports Chinese via region parameter. Tavily/Serper are better quality but have limits — they enhance, not replace.

**Why SQLCipher over regular SQLite + field encryption?** Full-database encryption prevents metadata leakage (table names, column names, row counts). Financial data deserves this level of protection.

**Why RSSHub for Chinese feeds?** Most Chinese financial sites don't provide RSS. RSSHub is an open-source bridge that generates RSS from any website. Self-hosting ensures reliability and zero cost.

**Why Reciprocal Rank Fusion?** Different search engines return different score scales. RRF only uses rank positions, making it robust across heterogeneous sources without normalization.

**Why OpenClaw's gateway pattern?** Local-first means financial data never touches third-party sync services. WebSocket provides real-time push for alerts. Session isolation prevents data leaks in multi-user setups.

**Why mermaid for diagrams?** Text-based (LLM-friendly), renders in terminals via CLI tools, produces SVG/PNG, well-supported ecosystem, works in both coding and finance modes.

**Why separate `QuantEngine` instead of inline math?** LLMs are notoriously bad at arithmetic. A dedicated engine ensures all math is computed by actual code, verified, and shown with intermediate steps. "Never guess if you can compute" is a core principle.

---

## 10. Companion Documents

This plan is part of a three-document set. All three must be read together:

| Document | Purpose |
|----------|---------|
| `FINANCE_PERSONALITY_PLAN.md` | Architecture, components, code changes, phases (this file) |
| `FINANCE_CORRECTNESS_RULES.md` | The Five Iron Rules, data validation pipeline, comprehensive unit tests, runtime validators |
| `FINANCE_TROUBLESHOOTING.md` | Risk registry (55+ tracked issues), edge cases, testing matrix, dependency risks, monitoring checklist |

**The correctness document is the most important.** It defines the non-negotiable rules that ensure the agent never fabricates financial data, never guesses math, and always shows source provenance. Every developer working on this must read it first.
