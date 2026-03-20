# Finance Personality — Troubleshooting Tracker & Risk Registry

**Date:** 2026-03-17
**Status:** Active — update as issues are discovered and resolved

---

## How To Use This Document

Every known risk, failure mode, and edge case is tracked here. During development, when you hit an issue, check this document first. If the issue is new, add it. If it's resolved, update the status and add the fix.

Status legend: `OPEN` = unresolved, `MITIGATED` = workaround in place, `RESOLVED` = permanently fixed, `WATCH` = monitoring

---

## 1. CRITICAL: Financial Correctness Failures

These are the highest-priority issues. Getting money decisions wrong has real consequences.

### TR-001: LLM Hallucinating Financial Data

| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Status** | OPEN — must be addressed in Phase 2 |
| **Category** | Data Integrity |
| **Description** | LLMs hallucinate financial data in up to 41% of finance queries (industry research). The model delivers stale training data with the same confidence as live data. A user asking "what's AAPL trading at?" gets a training-data price, not the real one. |
| **Root Cause** | LLM knowledge cutoff. Model has no concept of "I don't know the current price." |
| **Impact** | User makes buy/sell decision on fabricated price. Direct financial loss. |
| **Fix** | MANDATORY: Every data point (price, volume, P/E, earnings) MUST come from a tool call, never from LLM memory. The system prompt enforces this, but the code must also validate. |

**Implementation checklist:**

```
[ ] System prompt includes: "NEVER answer a price/data question from memory. Always use /stock or /crypto tool."
[ ] Pre-response validator: if response contains $ + number but no tool was called, block it and re-route to tool
[ ] Every data response includes source + timestamp: "AAPL: $195.42 (Finnhub, 2026-03-17 14:32 UTC)"
[ ] Add "data freshness" warning if data is older than market hours (>15 min during trading)
[ ] Unit test: mock LLM response with stale price, verify system catches and corrects it
```

### TR-002: Stale Cache Served as Fresh Data

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — must be addressed in Phase 2 |
| **Category** | Data Integrity |
| **Description** | Search cache (30 min TTL) or data cache returns old price during volatile market. Example: stock drops 8% on earnings miss, but cache still shows pre-earnings price. |
| **Root Cause** | Cache TTL too long for high-volatility moments. |
| **Impact** | User sees stale price, misses a crash or rally. |
| **Fix** | Adaptive cache TTL. |

**Implementation:**

```python
def get_cache_ttl(symbol, context):
    """
    Dynamic TTL based on market conditions:
    - During earnings season for this symbol: 60 seconds
    - During market hours: 5 minutes
    - After hours: 30 minutes
    - Weekend: 4 hours
    - Crypto (24/7): always 5 minutes
    """
    if is_earnings_window(symbol):
        return 60
    if is_market_hours():
        return 300
    if is_crypto(symbol):
        return 300
    return 1800
```

### TR-003: Conflicting Sources Not Flagged

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — must be addressed in Phase 4 |
| **Category** | Data Integrity |
| **Description** | Two sources report different facts (e.g., Reuters says "Fed pauses" vs 财新 says "Fed likely to cut"). If the system picks one without showing the conflict, user gets a biased view. |
| **Root Cause** | Naive deduplication that keeps only the highest-ranked result. |
| **Impact** | User makes one-sided decision based on incomplete picture. |
| **Fix** | Conflict detection must be a FIRST-CLASS feature, not an afterthought. |

**Conflict detection algorithm:**

```
1. Extract claims from each news item (entity + predicate + value)
2. Group by entity (e.g., "Fed", "AAPL", "inflation")
3. For each entity, compare predicates:
   - Same predicate, different values → CONFLICT
   - Same predicate, different magnitude → SOFT CONFLICT
   - Contradictory predicates → HARD CONFLICT
4. Always show conflicts to user with both sources cited
5. Provide inference with confidence level: "Based on source reliability
   scores (Reuters 0.90 vs 东方财富 0.70), Reuters claim is more likely,
   but the ZH source may have access to different PBoC channels."
```

### TR-004: Quantification Errors — Wrong Math

| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Status** | OPEN — must be addressed in Phase 4 |
| **Category** | Computation |
| **Description** | LLM does mental math for compound returns, option pricing, or risk calculations. Gets it wrong. User trusts the number. |
| **Root Cause** | LLMs are unreliable at arithmetic, especially multi-step calculations. |
| **Impact** | Wrong expected return, wrong risk assessment, wrong position sizing. |
| **Fix** | ALL math must go through QuantEngine. LLM drafts the formula, QuantEngine computes it, result is verified. |

**Implementation checklist:**

```
[ ] QuantEngine.compute() wraps every calculation in try/except with result validation
[ ] Results are cross-checked: e.g., compound_return(100, 0.10, 10) must equal ~259.37, not 200
[ ] For Black-Scholes: validate against known test cases before serving user results
[ ] Add "computation trace" showing every step: input → formula → intermediate → result
[ ] If QuantEngine fails, say "I cannot compute this reliably" — never fall back to LLM math
```

### TR-005: Survivorship Bias in Backtesting

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | WATCH |
| **Category** | Analysis Integrity |
| **Description** | When analyzing historical performance, only surviving companies are considered. Delisted stocks are missing from historical data. |
| **Root Cause** | Free data sources (yfinance, AKShare) typically don't include delisted stocks. |
| **Impact** | Historical analysis looks better than reality. "The market always goes up" ignores companies that went to zero. |
| **Fix** | System prompt includes warning. When doing historical analysis, explicitly note: "This analysis only includes currently-listed securities. Delisted companies are not reflected, which may introduce survivorship bias." |

---

## 2. Search & Data Source Failures

### TR-010: DuckDuckGo Rate Limiting (HTTP 202)

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | MITIGATED (by design) |
| **Category** | Search Infrastructure |
| **Description** | DuckDuckGo returns HTTP 202 RatelimitException when requests are too frequent. This is the primary free search engine. |
| **Root Cause** | DDG scraping endpoint has undocumented rate limits (~1 req/sec). |
| **Impact** | Search fails silently or returns empty results during active sessions. |

**Mitigations (layered):**

```
1. Rate limiter: Token bucket, 1 request per 1.5 seconds per DDG instance
2. Retry with exponential backoff: 2s → 4s → 8s, max 3 retries
3. Backend rotation: try "auto" → "html" → "lite" backends
4. Proxy support: DDGS(proxy="socks5://...") if configured
5. Fallback chain: DDG fails → RSS (always available) → Tavily/Serper (if configured)
6. Keep duckduckgo-search at latest version (rate limit fixes in recent versions)
7. Cache aggressively: same query within 30 min → serve from cache
```

**Test scenario:**

```
[ ] Fire 20 rapid searches → verify rate limiter prevents 202
[ ] Kill DDG entirely → verify RSS + Tier 2 fallback works
[ ] Verify user sees "Search degraded: using cached/RSS results" warning
```

### TR-011: yfinance IP Ban / Rate Limit (HTTP 429)

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | MITIGATED (by design) |
| **Category** | Data Source |
| **Description** | yfinance scrapes Yahoo Finance. Yahoo bans IPs that make too many requests. HTTP 429 errors. Entire data source goes down. |
| **Root Cause** | yfinance is not an official API. Yahoo has tightened scraping controls in 2025. |
| **Impact** | No US stock data, options chains, or historical prices. |

**Mitigations:**

```
1. yfinance is FALLBACK only. Primary is Finnhub (official API, 60/min free)
2. Request batching: group multiple symbol lookups into single session
3. Aggressive caching: stock quotes cached 5 min, historical data cached 1 hour
4. Version pinning: yfinance>=0.2.54 (Yahoo workaround included)
5. Graceful degradation: if yfinance dies, log warning, serve Finnhub-only data
6. Never use yfinance for real-time during market hours — Finnhub is primary
```

### TR-012: RSS Feed Downtime / URL Changes

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — need health monitoring |
| **Category** | Data Source |
| **Description** | RSS feed URLs change without notice. RSSHub instances go down. Some feeds return empty or malformed XML. |
| **Root Cause** | RSS is web scraping with extra steps. Source websites change structure. |
| **Impact** | Missing news from specific sources. Blind spots in coverage. |

**Mitigations:**

```
1. Feed health checker: on startup, ping all feeds, mark dead ones as inactive
2. RSSHub self-hosting recommended: docker run -d -p 1200:1200 diygod/rsshub
3. Fallback RSSHub instance: rsshub.app (public) as secondary
4. Feed rotation: if a feed fails 3 times consecutively, disable for 1 hour
5. /sources command shows feed health: ✅ alive, ⚠️ degraded, ❌ dead
6. Alert user if >50% of feeds in one language are down
```

### TR-013: AKShare API Breaking Changes

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | WATCH |
| **Category** | Data Source |
| **Description** | AKShare frequently restructures interfaces (e.g., pledged share ratio interface was completely restructured). Function signatures and return formats change between versions. |
| **Root Cause** | Active open-source project with rapid iteration. Upstream data sources (East Money, Sina) also change. |
| **Impact** | Chinese A-share data stops working after update. |

**Mitigations:**

```
1. Pin AKShare version in pyproject.toml with known-good version
2. Wrapper functions that normalize AKShare output to internal format
3. Try/except around every AKShare call with informative error
4. Consider akshare-one (standardized wrapper) for more stable interface
5. Integration test: run on CI, catch breaking changes before they reach user
```

### TR-014: CoinGecko Rate Limit (30 calls/min)

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | MITIGATED |
| **Category** | Data Source |
| **Description** | CoinGecko free tier: 30 calls/min, 10K/month. Heavy crypto users may hit this. |

**Mitigations:**

```
1. Token bucket: max 25 calls/min (leave headroom)
2. Cache crypto prices for 5 min (crypto is 24/7, no after-hours staleness)
3. Batch requests: /coins/markets accepts multiple IDs in one call
4. Fallback: Binance public API (unlimited for market data, no auth needed)
```

---

## 3. Security & Memory Failures

### TR-020: SQLCipher / pysqlcipher3 Installation Failure on macOS

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | MITIGATED |
| **Category** | Installation |
| **Description** | pysqlcipher3 requires compiling C extensions against libsqlcipher. Fails on macOS with "sqlcipher/sqlite3.h file not found". Build toolchain issues. |
| **Root Cause** | Missing brew install sqlcipher, or header paths not discoverable. |

**Mitigations:**

```
1. Primary: use sqlcipher3-binary (pre-compiled wheels, no build needed)
   pip install sqlcipher3-binary
2. Fallback: if sqlcipher unavailable, use standard sqlite3 + Fernet field-level encryption
   - Less secure (metadata visible) but functional
   - Warn user: "Full-database encryption unavailable. Using field-level encryption."
3. Document in TROUBLESHOOTING.md:
   brew install sqlcipher
   pip install sqlcipher3-binary
4. Test on clean macOS + Linux during Phase 3
```

### TR-021: Keyring Backend Not Available

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — need fallback |
| **Category** | Security |
| **Description** | Python keyring library requires a backend (macOS Keychain, GNOME Keyring, KWallet). Headless Linux or WSL may not have one. |
| **Root Cause** | No GUI keyring service running on headless systems. |

**Mitigations:**

```
1. Detect keyring availability on init:
   try:
       keyring.get_password("neomind_test", "test")
   except keyring.errors.NoKeyringError:
       # Fallback to encrypted file-based key storage
       use_file_keystore()
2. File keystore: ~/.neomind/.keystore (PBKDF2-encrypted, chmod 600)
3. Prompt user for passphrase on every session start (no keyring = no auto-unlock)
4. Never store passphrase in plaintext anywhere
5. Warn user: "OS keyring unavailable. You'll be prompted for passphrase each session."
```

### TR-022: Memory Database Corruption

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — need backup strategy |
| **Category** | Data Integrity |
| **Description** | Power loss, crash, or disk issue corrupts SQLite database. All financial memory lost. |
| **Root Cause** | SQLite write-ahead log can be corrupted on unclean shutdown. |

**Mitigations:**

```
1. WAL mode enabled (default in SQLCipher) — reduces corruption risk
2. Automatic daily backup: ~/.neomind/finance/backups/memory_YYYY-MM-DD.db
3. Keep last 7 daily backups, rotate older ones
4. PRAGMA integrity_check on startup — if corrupt, restore from latest backup
5. Export command: /memory export → JSON dump for manual backup
6. Transaction safety: all multi-table operations wrapped in transactions
```

---

## 4. Analysis & Decision Quality Failures

### TR-030: Recency Bias — Overweighting Latest News

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — address in Phase 4 |
| **Category** | Analysis Quality |
| **Description** | Agent gives too much weight to the most recent headline, ignoring historical context. "Stock drops 5% today" triggers sell recommendation, ignoring that it's up 40% over 6 months. |
| **Root Cause** | News digest prioritizes recency. LLM context is dominated by latest info. |

**Fix:**

```
1. Context assembly MUST include:
   - Latest news (last 24h)
   - Stored thesis (accumulated over weeks/months)
   - Historical price context (1-week, 1-month, 6-month, 1-year changes)
   - Previous predictions and their accuracy
2. System prompt reinforcement: "A single day's move means nothing without context.
   Always anchor analysis in the broader trend."
3. Impact scoring includes time-decay: old but important events retain score
```

### TR-031: Confirmation Bias — Thesis Lock-In

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — address in Phase 4 |
| **Category** | Analysis Quality |
| **Description** | Once the agent forms a bullish/bearish thesis, it interprets all new news to confirm that thesis. Fails to recognize when conditions have changed. |
| **Root Cause** | Continuous learning with thesis updates can create anchoring effects. |

**Fix:**

```
1. "Devil's Advocate" protocol: for every strong thesis, explicitly generate
   the counter-thesis with equal effort
2. Thesis reversal detector: if 3+ conflicting data points arrive since last
   thesis update, flag for mandatory review
3. Confidence decay: thesis confidence decreases by 5% per week unless
   reinforced by new supporting evidence
4. Track "thesis age" — if >30 days without update, mark as "stale thesis"
5. /predict review shows: "You were bullish on AAPL for 45 days.
   3 predictions correct, 1 wrong. Current confidence: 62%"
```

### TR-032: Missing Disclaimer / Liability

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — must be in Phase 1 |
| **Category** | Legal |
| **Description** | Finance agent gives specific buy/sell recommendations without "not financial advice" disclaimer. |

**Fix:**

```
1. Every session start in fin mode shows:
   "⚠️ NeoMind Finance is an analysis tool, not a licensed financial advisor.
    All outputs are for informational purposes only. Always consult a
    qualified professional before making investment decisions."
2. Every recommendation includes confidence level + disclaimer
3. Never use absolute language: "you should buy" → "analysis suggests bullish case
   with 65% confidence based on [sources]"
4. financial_disclaimer: true in fin.yaml enforces this
```

### TR-033: Chinese Market Nuances Missed

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — address in Phase 2 |
| **Category** | Analysis Quality |
| **Description** | A-shares have unique rules: T+1 trading, 10% daily price limits (20% for STAR market), trading halts, ST/\*ST designations. Agent trained primarily on US market patterns may give wrong advice for Chinese market. |

**Fix:**

```
1. Market-specific rules in system prompt:
   - A-shares: T+1, 10%/20% limits, ST rules, lunch break (11:30-13:00 CST)
   - HK: T+0, no daily limits, stamp duty, northbound/southbound connect
   - US: T+0 (settled T+1), PDT rule for <$25K accounts, pre/post market
2. When analyzing Chinese stocks, always note regulatory differences
3. Cross-market arbitrage awareness: same company listed in HK + A-share = AH premium
4. Macro factors unique to China: PBoC policy, CSRC regulations, 国务院 policy signals
```

### TR-034: Prediction Accuracy Not Tracked

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — address in Phase 4 |
| **Category** | Continuous Learning |
| **Description** | Agent makes predictions but never checks if they were right. Without feedback loop, there's no learning. |

**Fix:**

```
1. Every prediction stored with:
   - deadline: when to evaluate
   - target: specific, measurable outcome
   - confidence: how sure at time of prediction
2. Scheduled review: on startup, check all past-deadline predictions
3. Auto-fetch actual outcomes and compute accuracy score
4. Update source trust: sources that informed correct predictions get trust boost
5. Update agent confidence: if accuracy < 50%, system prompt adds extra caution
6. /predict command shows full prediction history with scorecard
```

---

## 5. Infrastructure & Performance Failures

### TR-040: All Search Sources Down Simultaneously

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — need offline mode |
| **Category** | Availability |
| **Description** | Network outage or all sources rate-limited at once. Agent has no data. |

**Fix:**

```
1. Offline mode: fall back to encrypted memory store
   "I cannot reach any data sources right now. Here's what I last knew as of [timestamp]:"
2. Clearly label all data as stale: "[CACHED 2h ago] AAPL: $195.42"
3. Refuse to give buy/sell recommendations on stale data:
   "My data is [N hours] old. I won't make recommendations on stale data.
    Here's what I knew before the outage: ..."
4. Retry queue: background task retries sources every 60 seconds
5. Alert user when connectivity returns: "Data sources restored. Refreshing..."
```

### TR-041: Memory Store Grows Too Large

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | WATCH |
| **Category** | Performance |
| **Description** | After months of daily digests, the SQLite database becomes large and slow. |

**Fix:**

```
1. Archival: news older than 90 days → compressed archive table
2. Thesis compaction: superseded insights are summarized into current thesis
3. VACUUM command monthly (or when db > 100MB)
4. Prediction cleanup: resolved predictions archived after 30 days
5. /memory stats: show db size, record count, oldest entry
```

### TR-042: Mobile Sync Security — Unauthorized Device

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — address in Phase 5 |
| **Category** | Security |
| **Description** | WebSocket server on local network could be accessed by any device on the same WiFi. |

**Fix:**

```
1. Device pairing: first connection requires 6-digit code displayed on host
2. Token-based auth: paired devices get a JWT, stored in device keychain
3. Rate limit: max 3 pairing attempts per hour
4. Device list: /sync devices shows all paired devices with last-seen time
5. Revoke: /sync revoke <device_id> removes a paired device
6. WSS (TLS): self-signed cert generated on first run for encrypted transport
7. Bind to localhost by default, require explicit --sync-public flag for LAN
```

---

## 6. Edge Cases & Gotchas

### TR-050: Market Hours Confusion

```
Issue: User asks "how's the market doing?" at 3 AM.
Risk: Agent fetches yesterday's close and presents it as current.
Fix: Always state market status:
     "US markets are currently CLOSED. Last close (2026-03-16): ..."
     "Shanghai market is currently in lunch break (11:30-13:00 CST)."
     "Crypto markets are 24/7. Current price as of [timestamp]: ..."
```

### TR-051: Currency Confusion

```
Issue: User asks about a Chinese stock. Price shown in RMB.
      User also has US stocks. Prices in USD.
      Comparison without currency conversion is misleading.
Risk: User thinks a ¥150 stock is cheaper than a $200 stock.
Fix: Always show currency symbol with prices.
     When comparing cross-market: auto-convert and show both:
     "BABA (HK): HK$85.20 (~US$10.93 at 7.80 HKD/USD)"
```

### TR-052: Split / Dividend Adjusted Prices

```
Issue: Historical price chart shows AAPL at $0.10 in 1990.
Risk: User thinks stock was incredibly cheap, not understanding splits.
Fix: Always use adjusted prices for historical comparison.
     Note when a stock has split: "AAPL has split 5 times. Adjusted price shown."
```

### TR-053: Options Expiry Time Zones

```
Issue: Options expire at 4:00 PM ET on expiry date.
Risk: User in different timezone miscalculates expiry timing.
Fix: Always show expiry in user's local timezone AND ET:
     "Expires: 2026-03-20 4:00 PM ET (2026-03-21 5:00 AM CST)"
```

### TR-054: Crypto Token Name Collisions

```
Issue: "SOL" could be Solana or another token.
       "LUNA" was Terra Luna (collapsed) and later Luna 2.0.
Risk: Agent fetches wrong token's data.
Fix: Use CoinGecko IDs (not symbols) internally.
     When ambiguous, ask: "Did you mean Solana (SOL) or Solar (SOL)?"
     Maintain mapping table: common names → CoinGecko IDs.
```

### TR-055: Weekend / Holiday Data Gaps

```
Issue: User asks for stock news on Saturday. No fresh data.
Risk: Agent hallucinates or presents Friday data as "current."
Fix: Detect weekends/holidays. Respond:
     "Markets are closed for the weekend. Here's Friday's recap + upcoming
      events for Monday. Crypto markets are still active."
```

### TR-056: Chinese Regulatory Sensitive Topics

```
Issue: Discussion of Chinese government economic policy, PBoC decisions,
       or CSRC actions may involve politically sensitive framing.
Risk: Sources may self-censor or present biased perspectives.
Fix: Always present multiple sources. Note when Chinese state media
     and independent media diverge. Never take a political position —
     present the economic implications factually.
```

---

## 7. Testing Matrix

Each phase must pass these tests before proceeding:

### Phase 1 Tests (Foundation)
```
[ ] /mode fin switches successfully, prompt loads
[ ] /mode chat switches back, no state leakage
[ ] /mode coding still works unchanged
[ ] Status bar shows "fin" mode correctly
[ ] Welcome screen shows financial disclaimer
[ ] Unknown commands in fin mode show help, not crash
```

### Phase 2 Tests (Search & Data)
```
[ ] DDG search returns EN results for "AAPL stock"
[ ] DDG search returns ZH results for "A股行情"
[ ] RSS feeds: >80% of EN feeds return data
[ ] RSS feeds: >60% of ZH feeds return data (some use RSSHub)
[ ] Finnhub returns real-time AAPL quote
[ ] CoinGecko returns BTC price
[ ] AKShare returns 上证指数 data
[ ] /stock AAPL shows price with source + timestamp
[ ] /crypto BTC shows price with source + timestamp
[ ] Search with all Tier 1 sources down → graceful error message
[ ] Search results merged correctly (no duplicates, proper ranking)
[ ] Rate limiter prevents DDG 202 error under normal load
```

### Phase 3 Tests (Memory & Security)
```
[ ] First run: passphrase creation flow works
[ ] Second run: passphrase unlock works, data persists
[ ] Wrong passphrase: clear error, no data access
[ ] Database file is actually encrypted (hexdump shows no readable text)
[ ] chmod 700 on ~/.neomind/finance/
[ ] /memory shows timestamped entries
[ ] /watchlist add/remove works
[ ] /alert set/fire/dismiss works
[ ] Database backup creates daily snapshot
[ ] Corrupt database: auto-recovery from backup
[ ] Keyring unavailable: fallback to file keystore works
```

### Phase 4 Tests (Intelligence)
```
[ ] /digest generates news summary with EN + ZH sources
[ ] Conflicting sources detected and displayed
[ ] Impact scores computed (not from LLM, from QuantEngine)
[ ] /compute compound_return(1000, 0.07, 30) = 7612.26 (exact)
[ ] /compute Black-Scholes matches known test case
[ ] /predict stores prediction with deadline
[ ] Past-deadline prediction auto-evaluated on startup
[ ] Short/medium/long analysis present in every recommendation
[ ] Thesis update: new data modifies existing thesis, doesn't replace
[ ] Confidence decay: old thesis shows lower confidence
[ ] Devil's advocate: strong thesis triggers counter-argument generation
```

### Phase 5 Tests (Visualization & Sync)
```
[ ] /chart generates valid mermaid diagram for causal chain
[ ] Mermaid renders to SVG/PNG file
[ ] /chart works in coding mode too (shared tool)
[ ] WebSocket server starts on configured port
[ ] Device pairing with 6-digit code works
[ ] Push alert reaches paired device
[ ] Unauthorized device rejected
[ ] /sync status shows connected devices
```

### Phase 6 Tests (Integration)
```
[ ] Full workflow: search → analyze → quantify → recommend → store
[ ] Prediction accuracy tracked over 10+ test predictions
[ ] Source trust scores update based on accuracy
[ ] All 16 original requirements verified (see traceability matrix)
[ ] Stress test: 50 rapid queries don't crash or exhaust rate limits
[ ] Offline mode: network disabled → stale data served with warnings
[ ] Cross-market: US + China + crypto in same session
```

---

## 8. Dependency Risk Matrix

| Dependency | Risk Level | Failure Mode | Mitigation |
|-----------|-----------|-------------|------------|
| `duckduckgo-search` | HIGH | Rate limiting, breaking changes | Proxy, backend rotation, version pin, Tier 2 fallback |
| `yfinance` | HIGH | IP ban, Yahoo API changes | Finnhub primary, yfinance fallback only, cache aggressively |
| `finnhub-python` | LOW | API key invalid, rate limit | Free tier generous (60/min), key validation on startup |
| `akshare` | MEDIUM | API restructuring between versions | Pin version, wrapper functions, `akshare-one` as alternative |
| `pycoingecko` | LOW | Rate limit (30/min) | Batch requests, Binance API fallback |
| `sqlcipher3-binary` | MEDIUM | Build fails on some platforms | Binary wheel preferred, standard SQLite + Fernet fallback |
| `keyring` | MEDIUM | No backend on headless Linux | File-based keystore fallback |
| `feedparser` | LOW | Stable, rarely breaks | None needed |
| `mermaid-py` | LOW | Rendering issues | `mermaid-cli` as fallback, raw mermaid text as last resort |
| `sympy` | LOW | Stable, rarely breaks | None needed |
| `numpy` | LOW | Stable, rarely breaks | None needed |
| `websockets` | LOW | Stable, rarely breaks | None needed |
| `cryptography` | LOW | Stable, well-maintained | None needed |

---

## 9. Post-Launch Monitoring Checklist

After deployment, monitor these metrics weekly:

```
[ ] Search success rate (% of queries that return results)
[ ] Average search latency (should be < 5 seconds)
[ ] Data source uptime (per source, per day)
[ ] Cache hit rate (should be > 40% after first week)
[ ] Prediction accuracy (tracked over time)
[ ] Source trust score changes (detect degrading sources)
[ ] Memory database size (watch for unbounded growth)
[ ] User-reported incorrect data (log and investigate each one)
[ ] Rate limit hits (per source, per day)
[ ] Encryption test: verify db is still encrypted (monthly)
```

---

## 10. Known Limitations (Documented, Not Bugs)

These are inherent limitations that should be communicated to the user:

1. **Not a licensed financial advisor.** This is an analysis tool. The user makes all decisions.
2. **Free data has delays.** Finnhub free tier has 15-minute delay for US stocks. Real-time requires paid tier.
3. **Chinese data coverage varies.** AKShare covers most A-share and HK stocks but may miss some small-caps.
4. **Options data is limited.** Free options data (yfinance) doesn't include real-time Greeks or IV surface.
5. **Prediction accuracy is probabilistic.** Even 90% confidence means 10% chance of being wrong.
6. **Mobile sync requires same network.** Desktop and phone must be on same WiFi for local sync.
7. **LLM is not omniscient.** The agent can analyze data it receives, but it cannot access insider information, non-public filings, or data behind paywalls.
8. **Crypto is unregulated.** Extra caution for tokens with no track record or low market cap.
