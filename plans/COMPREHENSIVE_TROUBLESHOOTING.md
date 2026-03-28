# NeoMind Comprehensive Troubleshooting Guide

**Last Updated:** 2026-03-27
**Scope:** Installation, testing, configuration, deployment, and all major modules
**Status:** Master troubleshooting reference — consolidated from field experience

---

## Table of Contents

1. [Installation & Environment Setup](#installation--environment-setup)
2. [Dependency & Version Issues](#dependency--version-issues)
3. [Test Failures & Debugging](#test-failures--debugging)
4. [Core Module Issues](#core-module-issues)
5. [Finance Subsystem Troubleshooting](#finance-subsystem-troubleshooting)
6. [Search & Data Issues](#search--data-issues)
7. [Vault & Persistence Issues](#vault--persistence-issues)
8. [Configuration Problems](#configuration-problems)
9. [Database & SQLite Issues](#database--sqlite-issues)
10. [Network & API Issues](#network--api-issues)
11. [Docker & Deployment Issues](#docker--deployment-issues)
12. [Provider Switching & Multi-Model](#provider-switching--multi-model-issues)
13. [Memory & Performance Issues](#memory--performance-issues)
14. [Debug Commands & Logging](#debug-commands--logging)

---

## Installation & Environment Setup

### Python & Virtual Environment

#### `python: command not found` on macOS

**Symptom:** `python main.py` → "command not found"
**Fix:** Use `python3` — macOS doesn't alias `python` to `python3`
**Root cause:** System Python is disabled in newer macOS versions

```bash
# Always use python3 on macOS
python3 main.py
python3 -m pytest tests/

# Or create alias in ~/.zshrc:
alias python="python3"
alias pip="pip3"
source ~/.zshrc
```

#### `ensurepip` fails when creating venv

**Symptom:** `python3 -m venv .venv` fails with ensurepip error
**Fix:** Use `--system-site-packages` flag
**Root cause:** Some Linux distros don't include ensurepip

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install --upgrade pip
```

#### venv points to system Python after recreation

**Symptom:** `which python3` shows `/usr/bin/python3` even inside venv
**Fix:** Clean removal and recreation

```bash
# Hard reset
rm -rf .venv
rm -rf __pycache__ .pytest_cache
python3 -m venv .venv
source .venv/bin/activate

# Verify
which python3  # Should show: /path/to/.venv/bin/python3
python3 --version
```

#### pip too old for pyproject.toml editable install

**Symptom:** `pip install -e .` fails with "editable install" error
**Fix:** Upgrade pip first

```bash
# Update pip to support PEP 660 (editable installs)
pip install --upgrade pip setuptools wheel

# Then retry
pip install -e .
```

#### Permission denied on pip install

**Symptom:** `ERROR: Could not install packages due to an OSError: [Errno 13]`
**Fix:** Use `--user` flag or check venv activation

```bash
# Check venv is activated
echo $VIRTUAL_ENV  # Should print venv path, not empty

# If not activated:
source .venv/bin/activate

# If still failing, reinstall venv
rm -rf .venv
python3 -m venv .venv --clear
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### API Keys & Credentials

#### ModuleNotFoundError: No module named 'dotenv'

**Symptom:** `ModuleNotFoundError: No module named 'dotenv'` on startup
**Fix:** Install correct package (not `dotenv`, but `python-dotenv`)

```bash
pip install python-dotenv  # Correct
pip uninstall dotenv      # Remove wrong package if installed
```

#### Environment variables not loading

**Symptom:** Set `DEEPSEEK_API_KEY=...` in terminal, but agent doesn't see it
**Fix:** Ensure `.env` file is in project root and loaded

```bash
# Check .env file exists
cat .env | grep DEEPSEEK_API_KEY

# Verify it loads in Python
python3 -c "
from dotenv import load_dotenv
import os
load_dotenv()
key = os.getenv('DEEPSEEK_API_KEY', 'NOT_FOUND')
print(f'API Key: {key[:10]}...' if key != 'NOT_FOUND' else key)
"
```

#### No API key for provider error

**Symptom:** `✗ No API key for provider 'deepseek'. Set DEEPSEEK_API_KEY in .env`
**Fix:** Add the key to `.env`

```bash
# Edit .env
nano .env

# Add these lines:
DEEPSEEK_API_KEY=sk_xxxx...
ZAI_API_KEY=your_z.ai_key
ANTHROPIC_API_KEY=sk_xxxx...

# Save and reload
source .venv/bin/activate
python3 main.py
```

#### `.env` file ignored by git

**Symptom:** Committing sensitive keys to GitHub
**Fix:** Ensure `.gitignore` includes `.env`

```bash
cat .gitignore | grep ".env"
# If not present:
echo ".env" >> .gitignore
echo "*.key" >> .gitignore
echo "*.pem" >> .gitignore
git add .gitignore
git commit -m "Protect sensitive files"
```

---

## Dependency & Version Issues

### Missing Required Packages

#### aiohttp import fails

**Symptom:** `ModuleNotFoundError: No module named 'aiohttp'`
**Fix:** Install aiohttp

```bash
pip install aiohttp
```

**Root cause:** Was listed as optional; now required for async HTTP

#### ripgrep not found (grep tool slower)

**Symptom:** `/grep` command is slow; check logs for "ripgrep not found"
**Fix:** Install ripgrep for 5-10x speedup

```bash
# macOS
brew install ripgrep

# Ubuntu/Debian
sudo apt install ripgrep

# From cargo
cargo install ripgrep

# Verify
which rg
rg --version
```

### Package Version Conflicts

#### Hydra/OmegaConf errors after import

**Symptom:** `GlobalHydra is already initialized` on reimport
**Status:** RESOLVED in this version
**Note:** Hydra was removed entirely. Replaced with plain PyYAML. If you see this error, you're on an old version.

```bash
# Update to latest
git pull origin main
pip install -e . --upgrade
```

#### PyYAML requires C compiler

**Symptom:** `error: unable to execute 'gcc': No such file or directory` during pip install
**Fix:** Install build tools

```bash
# macOS
xcode-select --install

# Ubuntu/Debian
sudo apt install build-essential python3-dev

# Then retry
pip install PyYAML
```

### Optional Dependencies

#### Crawl4AI not installed (web crawler slows down)

**Symptom:** Web scraping falls back to slow method or errors
**Status:** KNOWN — Crawl4AI is optional
**Fix:** Install if you need JavaScript rendering

```bash
pip install crawl4ai
# Or install minimal version:
pip install crawl4ai-lite
```

#### Playwright/Selenium not installed (browser tests fail)

**Symptom:** `test_browser_daemon_full.py` skipped
**Status:** KNOWN — browser automation is optional
**Fix:** Install if you need browser-based testing

```bash
pip install playwright
playwright install  # Downloads browser binaries

# Or use Selenium:
pip install selenium
# Then install ChromeDriver or GeckoDriver
```

---

## Test Failures & Debugging

### Test Timeouts

#### `test_search.py` times out >60s

**Symptom:** Test hangs or times out after 60 seconds
**Status:** KNOWN ISSUE
**Root cause:** Live DuckDuckGo and Bing searches are slow
**Workaround:** Exclude from normal test runs

```bash
# Skip known slow tests
python -m pytest tests/ \
  --ignore=tests/test_search.py \
  --ignore=tests/test_search_sources_full.py \
  -v

# To test search explicitly with longer timeout:
python -m pytest tests/test_search.py \
  --timeout=120 -v

# Or mock the search responses
python -m pytest tests/test_search.py \
  -k "not live" -v
```

#### `test_hackernews_full.py` hangs or rate-limited

**Symptom:** Test hangs when scraping Hacker News
**Status:** KNOWN ISSUE
**Root cause:** HN rate limiting, IP blocking
**Workaround:** Mock HN responses; excluded from default runs

```bash
# Skip HN tests
python -m pytest tests/ \
  --ignore=tests/test_hackernews_full.py -v

# Test with mock data instead
python -m pytest tests/test_news_digest_full.py -v
```

#### `test_search_sources_full.py` takes >60s to initialize

**Symptom:** Test hangs during source registry initialization
**Status:** KNOWN ISSUE
**Root cause:** Loads all 50+ search sources at once
**Workaround:** Run separately with extended timeout

```bash
python -m pytest tests/test_search_sources_full.py \
  --timeout=120 -v
```

### Import & Configuration Errors

#### ModuleNotFoundError when running tests

**Symptom:** `ModuleNotFoundError: No module named 'agent'` during pytest
**Fix:** Install package in editable mode

```bash
pip install -e .
python -m pytest tests/test_core.py -v
```

#### Config loads but mode not switching

**Symptom:** Switch to coding mode, but system prompt stays in chat mode
**Root cause:** Mode config not reloading after switch
**Fix:** Ensure agent_config is reloaded

```python
# In your code:
from agent_config import agent_config
agent_config.switch_mode('coding')  # Reloads config
agent_config.load_config()  # Force reload all settings
```

#### Test tries to use real API (not mocked)

**Symptom:** Test makes actual HTTP request to OpenAI/Anthropic
**Root cause:** Mock not set up correctly
**Fix:** Check mock patch path

```python
# WRONG: patches the import location
@patch('agent.core.requests.get')  # Won't work

# RIGHT: patches where it's used
@patch('requests.get')  # Works if used as `import requests`

# Or use requests_mock library
import requests_mock

def test_with_mock():
    with requests_mock.Mocker() as m:
        m.get('http://api.example.com/data', json={'result': 'ok'})
        response = requests.get('http://api.example.com/data')
        assert response.json() == {'result': 'ok'}
```

### Assertion & Logic Errors

#### Test passes locally but fails in CI

**Symptom:** `pytest tests/test_x.py` works on your machine, fails in GitHub Actions
**Root causes:**
- Timezone differences (use `freezegun` for time tests)
- Missing environment variables in CI
- Different Python version
- Race conditions in concurrent tests

**Fixes:**

```python
# Wrong: depends on system timezone
def test_timestamp():
    now = datetime.now()
    assert now.hour == 14  # Fails if running in different TZ

# Right: mock time
from freezegun import freeze_time

@freeze_time("2026-03-27 14:30:00")
def test_timestamp():
    now = datetime.now()
    assert now.hour == 14  # Always passes
```

For CI environment variables:

```yaml
# .github/workflows/test.yml
jobs:
  test:
    env:
      DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
      ZAI_API_KEY: ${{ secrets.ZAI_API_KEY }}
    steps:
      - run: python -m pytest tests/
```

#### Test database corrupted

**Symptom:** SQLite errors: `database disk image malformed`
**Fix:** Delete and recreate database

```bash
# Find and remove corrupted .db files
find . -name "*.db" -delete
find . -name "*.db-journal" -delete

# Restart — new clean databases will be created
python3 main.py
```

---

## Core Module Issues

### Context Manager & Token Counting

#### Token count never updates in status bar

**Symptom:** Status shows `tokens:151` and stays frozen
**Root cause:** Token count cache not invalidating
**Fix:** Force recount on each call

```python
# agent/context_manager.py should be using:
def count_conversation_tokens(self):
    """Recalculate every time (no cache)"""
    return sum(len(m['content'].split()) * 1.3 for m in self.messages)
```

#### Context window filling too fast

**Symptom:** "Context window 95% full" warning appears after 5 messages
**Root cause:** Token counter overcounting or message storage includes dupes
**Fix:** Check message deduplication

```python
# Ensure conversations don't store messages twice
messages = [msg for msg in self.messages if msg not in self.messages[:self.messages.index(msg)]]
```

### Code Analyzer & File Parsing

#### Code analyzer hangs on large files

**Symptom:** `/analyze 10MB_file.py` hangs indefinitely
**Root cause:** No file size limit in analyzer
**Fix:** Add size check

```python
# agent/code_analyzer.py should check:
MAX_FILE_SIZE = 5_000_000  # 5MB limit

def analyze(filepath):
    size = os.path.getsize(filepath)
    if size > MAX_FILE_SIZE:
        return f"File too large ({size/1e6:.1f}MB), skipping analysis"
```

#### Parser fails on mixed indentation

**Symptom:** Analyzing code with tabs+spaces gives parse error
**Root cause:** Python parser strict on indentation
**Fix:** Normalize indentation first

```python
import re

def normalize_indentation(code):
    """Convert tabs to spaces"""
    return re.sub(r'^\t+', lambda m: '    ' * len(m.group(0)), code, flags=re.MULTILINE)
```

### Safety & Validation

#### Safety checks trigger false positives

**Symptom:** `/rm temp_file.txt` blocked even though you confirmed it
**Root cause:** Safety rules too broad
**Fix:** Review and refine rules

```python
# agent/safety.py — check DANGEROUS_PATTERNS
DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+/',  # OK: prevents rm -rf /
    r'rm\s+\*.txt',   # TOO BROAD: blocks all txt deletes
]
```

#### Bypass attempts not caught

**Symptom:** User tries `rm /path && echo 'done'` — safety doesn't catch it
**Fix:** Analyze full command, not just prefix

```python
def is_destructive(command):
    """Check full command chain"""
    # Split by && || ; and check each part
    parts = re.split(r'[;|&]+', command)
    return any(is_dangerous_cmd(part.strip()) for part in parts)
```

---

## Finance Subsystem Troubleshooting

### Response Validation & Five Iron Rules

#### False positives: Valid text flagged as unverified price

**Symptom:** "Please verify this price: $50" flagged as hallucinated data
**Root cause:** PRICE_PATTERNS regex too broad
**Fix:** Tighten patterns or add context awareness

```python
# agent/finance/response_validator.py

PRICE_PATTERNS = [
    # Too broad — matches any $ + number
    r'\$[\d,]+\.?\d*',
    # Better — only standalone prices
    r'\b\$[\d,]{1,3}(?:,\d{3})*(?:\.\d{2})?\b(?!\s*[a-z])',
]

# Or exclude certain contexts
PRICE_EXCLUDE_PATTERNS = [
    r'`.*?\$.*?`',  # Code blocks
    r'".*?\$.*?"',  # Quoted text
    r'\(.*?\$.*?\)', # Parenthetical
]
```

#### Rule 4 (Recommendations) triggers on non-advice

**Symptom:** Confidence level discussed in analysis flagged as unvetted recommendation
**Root cause:** Pattern matches "confidence" in neutral contexts
**Fix:** Require recommendation keywords first

```python
def check_rule_4(text):
    """Only flag if recommendation + confidence/horizon"""
    has_recommendation = any(kw in text.lower() for kw in
        ['recommend', 'buy', 'sell', 'hold', 'suggest', 'advise'])
    has_confidence = 'confidence' in text.lower() or '%' in text

    return has_recommendation and has_confidence  # Both required
```

#### Source timestamps not detected

**Symptom:** Data marked as "unsourced" even with timestamp
**Root cause:** Timestamp pattern too restrictive
**Fix:** Expand pattern

```python
SOURCE_PATTERNS = [
    # Original: UTC/CST only
    r'\(.*?[23:][0-9]{1,2}\s+[UA]TC.*?\)',
    # Expanded: ISO 8601, Unix, natural language
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',  # ISO 8601
    r'timestamp.*?\d+',  # Unix timestamp
    r'(this morning|yesterday|last week)',  # Natural language
]
```

#### Price regex hangs on large responses

**Symptom:** Validation never completes on 50KB+ response
**Root cause:** Regex catastrophic backtracking
**Fix:** Compile patterns once, use atomic groups

```python
# Compile at module level, not in loop
COMPILED_PRICES = [re.compile(p) for p in PRICE_PATTERNS]

# Use atomic groups to prevent backtracking
PRICE_PATTERNS = [
    r'\$(?>[0-9,]+(?>\.\d{2})?)\b',  # Atomic groups (?>...)
]
```

### Quantitative Engine

#### Black-Scholes returns NaN

**Symptom:** Option pricing returns NaN, crashes downstream
**Root cause:** Input validation missing (negative prices, zero volatility)
**Fix:** Add input guards

```python
def black_scholes(S, K, T, r, sigma):
    """Option pricing with validation"""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        raise ValueError(f"Invalid inputs: S={S}, K={K}, T={T}, sigma={sigma}")

    # Calculate...
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    # Check for NaN
    if math.isnan(d1):
        raise ValueError(f"Calculation failed: d1={d1}")

    return option_price
```

#### Compound return calculation wrong

**Symptom:** Compound return over 10 years with 10% annual = 100%, should be ~259%
**Root cause:** Using simple math instead of (1+r)^n
**Fix:** Use correct formula

```python
def compound_return(principal, annual_rate, years):
    """Calculate compound return correctly"""
    return principal * ((1 + annual_rate) ** years) - principal

# Test
assert compound_return(100, 0.10, 10) == pytest.approx(135.95, rel=0.01)
```

### Investment Personas

#### Persona conflicts detected but not resolved

**Symptom:** "Growth persona says buy, value persona says sell" — conflicting advice
**Root cause:** No conflict resolution logic
**Fix:** Implement consensus scoring

```python
def resolve_persona_conflict(persona_recommendations):
    """
    Return consensus recommendation with confidence level

    Args:
        persona_recommendations: {'growth': 'buy', 'value': 'sell', ...}

    Returns:
        {'recommendation': 'buy', 'confidence': 0.67, 'agreement': 2/3}
    """
    from collections import Counter
    votes = Counter(persona_recommendations.values())
    winner = votes.most_common(1)[0][0]
    agreement = votes.most_common(1)[0][1] / len(persona_recommendations)

    return {
        'recommendation': winner,
        'confidence': agreement,
        'dissenting': [p for p, r in persona_recommendations.items() if r != winner]
    }
```

#### Unknown persona requested

**Symptom:** `/persona quantum_trader` → "Unknown persona"
**Fix:** Add persona or provide list

```python
AVAILABLE_PERSONAS = {
    'growth': GrowthPersona(),
    'value': ValuePersona(),
    'income': IncomePersona(),
    'speculative': SpeculativePersona(),
}

if persona_name not in AVAILABLE_PERSONAS:
    available = ', '.join(AVAILABLE_PERSONAS.keys())
    print(f"Unknown persona. Available: {available}")
```

### Data Hub & Source Aggregation

#### Conflicting data from multiple sources

**Symptom:** Reuters says AAPL=$195, Bloomberg says $194
**Root cause:** Naive dedup that keeps only one source
**Fix:** Show conflicts, weighted by source reliability

```python
def aggregate_prices(price_data):
    """
    Input: [
        {'source': 'Reuters', 'price': 195.42, 'reliability': 0.95},
        {'source': 'Bloomberg', 'price': 194.98, 'reliability': 0.93},
    ]
    """
    if len(price_data) == 0:
        return None
    if len(price_data) == 1:
        return price_data[0]

    # Check for conflicts
    prices = [d['price'] for d in price_data]
    if max(prices) - min(prices) > 1:  # >$1 difference
        return {
            'conflict': True,
            'sources': price_data,
            'weighted_price': sum(d['price']*d['reliability'] for d in price_data) / sum(d['reliability'] for d in price_data),
            'recommendation': f"Sources disagree. Reliable: {max(price_data, key=lambda x: x['reliability'])['source']}"
        }

    return {'price': sum(d['price'] for d in price_data) / len(price_data)}
```

#### Stale cache served as fresh data

**Symptom:** Stock drops 8% on earnings, but system shows pre-earnings price (30 min cache TTL)
**Root cause:** Cache TTL not adaptive
**Fix:** Dynamic TTL based on volatility/events

```python
def get_cache_ttl(symbol, context=None):
    """Adaptive cache TTL"""
    # Earnings window: 60 seconds
    if is_earnings_window(symbol):
        return 60
    # Market hours: 5 minutes
    if is_market_hours():
        return 300
    # After hours: 30 minutes
    if is_after_hours():
        return 1800
    # Crypto 24/7: always 5 minutes
    if is_crypto(symbol):
        return 300
    # Weekend: 4 hours
    return 14400
```

---

## Search & Data Issues

### Search Engine Failures

#### Empty results when query should match

**Symptom:** Search for "AAPL stock price" returns no results
**Root cause:** Query routing sent to wrong provider; provider down
**Fix:** Check provider status and fallback

```bash
# Debug search routing:
python3 -c "
from agent.search.router import SearchRouter
router = SearchRouter()
result = router.route_query('AAPL stock price')
print(f'Routing to: {result.provider}')
print(f'Provider health: {result.healthy}')
"
```

#### Search timeout >60s

**Symptom:** Search hangs, times out after 60 seconds
**Root cause:** Provider slow or unresponsive
**Fix:** Set shorter timeout, add fallback

```python
# agent/search/engine.py
SEARCH_TIMEOUT = 10  # seconds, not 60

@timeout(SEARCH_TIMEOUT)
def search(query):
    try:
        return provider1.search(query)
    except TimeoutError:
        return provider2.search(query)  # Fallback
```

#### DuckDuckGo returns HTTP 202 (rate limited)

**Symptom:** Search fails with "Rate limit exceeded"
**Status:** KNOWN — DDG rate limits ~1 req/sec
**Workaround:** Use alternative provider or delay requests

```python
# Implement request queuing to avoid exceeding rate limit
from queue import Queue
import time

search_queue = Queue()

def search_with_backoff(query):
    """Search with rate limiting"""
    search_queue.put(query)
    time.sleep(1.1)  # >1 sec between requests
    return perform_search(search_queue.get())
```

### Source Registry & Provider Issues

#### Unknown search provider

**Symptom:** `/search --provider xyz` → "Unknown provider"
**Fix:** List available providers

```python
def list_providers():
    from agent.search.sources import SOURCE_REGISTRY
    providers = SOURCE_REGISTRY.list_providers()
    print("Available providers:")
    for name, provider in providers.items():
        print(f"  - {name}: {provider.description}")
```

### Vector Store & Semantic Search

#### Vector search returns low-relevance results

**Symptom:** Semantic search for "stock price" returns articles about bonds
**Root cause:** Embedding model poor quality or wrong vectors
**Fix:** Evaluate embeddings, retrain if needed

```bash
# Check embedding quality
python3 -c "
from agent.search.vector_store import VectorStore
vs = VectorStore()

# Test similarity
q = vs.embed('stock price')
result = vs.search(q, top_k=1)
print(f'Top result similarity: {result[0].score}')

if result[0].score < 0.7:
    print('⚠️ Low similarity! Consider retraining embeddings.')
"
```

#### Embedding dimension mismatch

**Symptom:** `ValueError: shape mismatch` in vector operations
**Root cause:** Using different embedding models
**Fix:** Ensure consistent embedding model

```python
# agent/search/vector_store.py
EMBEDDING_MODEL = "text-embedding-3-small"  # Fixed, consistent

def embed(text):
    """Always use same model"""
    from openai import OpenAI
    client = OpenAI()
    return client.embeddings.create(
        input=text,
        model=EMBEDDING_MODEL
    ).data[0].embedding
```

---

## Vault & Persistence Issues

### Obsidian Vault Integration

#### Changes not detected in vault

**Symptom:** User edits MEMORY.md in Obsidian, system doesn't see changes
**Root cause:** Vault watcher polling interval or mtime granularity (1s filesystem resolution)
**Fix:** Check watcher, increase polling

```python
# agent/vault/watcher.py
POLL_INTERVAL = 0.5  # Check every 500ms instead of 1s

def check_for_changes(self):
    """Poll for changes"""
    for filename in self.WATCHED_FILES:
        try:
            current_mtime = os.path.getmtime(self.vault_dir / filename)
            stored_mtime = self._stored_mtimes.get(filename)

            # Account for filesystem resolution
            if current_mtime and stored_mtime and (current_mtime - stored_mtime) > 0.1:
                self._stored_mtimes[filename] = current_mtime
                return True
        except OSError:
            pass  # File doesn't exist, not an error

    return False
```

#### Vault file permission errors

**Symptom:** `OSError: [Errno 13] Permission denied` when accessing vault files
**Fix:** Check vault directory permissions

```bash
# Check permissions
ls -la /path/to/vault/

# If vault is read-only:
chmod u+w /path/to/vault/
chmod u+w /path/to/vault/MEMORY.md
```

#### Wikilinks double-wrapped or corrupted

**Symptom:** `[[[$AAPL]]]` instead of `[[$AAPL]]` in notes
**Root cause:** Wikification called twice, or not protected against double-wrapping
**Fix:** Add guard in writer

```python
# agent/vault/writer.py
def _wikify(self, text):
    """Convert stock tickers to wikilinks (idempotent)"""
    # Protect already-wrapped links
    text = re.sub(r'\[\[(\[\[.*?\]\])\]\]', r'[\1]', text)  # Unwrap double-wrap

    # Apply wikification
    text = re.sub(r'\b(\$[A-Z]{1,5})\b(?!\])', r'[[\1]]', text)
    text = re.sub(r'\b(\d{6})\b(?!\])', r'[[\1]]', text)

    return text
```

#### Vault promoter not promoting patterns

**Symptom:** Pattern count >= 3 but still not in MEMORY.md
**Root cause:** Pattern type not in SECTION_MAP or write failed silently
**Fix:** Check configuration and add debugging

```python
# agent/vault/promoter.py
SECTION_MAP = {
    'price_accuracy': '## Price Accuracy',
    'risk_management': '## Risk Management',
    'market_timing': '## Market Timing',
}

def promote_patterns(self):
    """Promote high-confidence patterns"""
    patterns = self.shared_memory.get_all_patterns(min_count=3)

    for pattern in patterns:
        section = SECTION_MAP.get(pattern.type, '## Other Patterns')
        try:
            self.vault_writer.append_to_memory(section, pattern.text)
            print(f"✓ Promoted: {pattern.text[:50]}...")
        except Exception as e:
            print(f"✗ Failed to promote {pattern.type}: {e}")
```

### SharedMemory & Pattern Tracking

#### SQLite database locked

**Symptom:** `sqlite3.OperationalError: database is locked`
**Root cause:** Another process has database open; no timeout set
**Fix:** Add timeout and retry logic

```python
import sqlite3

# Open with timeout (wait up to 5 seconds for lock)
conn = sqlite3.connect(
    'patterns.db',
    timeout=5.0,  # Wait 5s before failing
    isolation_level=None  # Autocommit mode
)

# Or with retries:
def execute_with_retry(db_path, query, max_retries=3):
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(db_path, timeout=1.0)
            cursor = conn.cursor()
            return cursor.execute(query)
        except sqlite3.OperationalError:
            if attempt < max_retries - 1:
                time.sleep(0.5)
            else:
                raise
        finally:
            conn.close()
```

#### Duplicate patterns in database

**Symptom:** Same behavior recorded multiple times with same count
**Root cause:** Deduplication not working in insert
**Fix:** Add unique constraint

```sql
-- agent/memory/shared_memory.py (DB schema)
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    pattern_text TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    UNIQUE(pattern_type, pattern_text)  -- Prevent duplicates
);

-- Or deduplicate on insert:
INSERT OR IGNORE INTO patterns(type, text, count) VALUES (?, ?, 1);
UPDATE patterns SET count = count + 1 WHERE type = ? AND text = ?;
```

---

## Configuration Problems

### Config Loading & Mode Switching

#### Mode switch doesn't update system prompt

**Symptom:** Switch from chat → coding, but system prompt doesn't change
**Root cause:** Config not reloading after switch
**Fix:** Reload config explicitly

```python
# In agent/core.py
def switch_mode(self, new_mode):
    """Switch modes and reload everything"""
    from agent_config import agent_config

    agent_config.switch_mode(new_mode)
    agent_config.load_config()  # Force reload

    # Update system prompt from new mode
    self.system_prompt = agent_config.get_system_prompt()
    self.tools = agent_config.get_available_tools()
```

#### Config validation fails but error unclear

**Symptom:** YAML config is invalid, error message unhelpful
**Fix:** Improve error messages

```python
import yaml

def load_config(config_path):
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Validate required fields
        required = ['mode', 'model', 'max_context']
        missing = [k for k in required if k not in config]
        if missing:
            raise ValueError(f"Config missing required fields: {missing}")

        return config

    except yaml.YAMLError as e:
        print(f"❌ YAML syntax error in {config_path}:")
        print(f"   Line {e.problem_mark.line}: {e.problem}")
        raise
```

#### Missing required API key in mode config

**Symptom:** Coding mode enabled, but `QUANT_ENGINE_KEY` not in .env
**Fix:** Check all required keys on startup

```python
# agent_config.py
def validate_api_keys(mode):
    """Ensure all keys required by this mode are set"""
    required_keys = {
        'chat': ['DEEPSEEK_API_KEY'],
        'coding': ['DEEPSEEK_API_KEY', 'QUANT_ENGINE_KEY'],
        'finance': ['DEEPSEEK_API_KEY', 'QUANT_ENGINE_KEY', 'FINNHUB_API_KEY'],
    }

    for key in required_keys.get(mode, []):
        if not os.getenv(key):
            raise RuntimeError(f"Missing {key} for {mode} mode. Set in .env")
```

---

## Database & SQLite Issues

### Database Corruption & Recovery

#### "database disk image malformed"

**Symptom:** SQLite error, database won't open
**Root cause:** Incomplete transaction, power loss, or permissions
**Fix:** Rebuild or recreate

```bash
# Attempt repair
sqlite3 patterns.db "PRAGMA integrity_check;"

# If repair fails, delete and recreate
rm patterns.db
rm patterns.db-journal
# Database auto-recreates on next run
python3 main.py
```

#### Transaction never commits

**Symptom:** Changes inserted but never saved to disk
**Root cause:** No explicit commit or rollback
**Fix:** Use context manager

```python
import sqlite3

# Wrong: no commit
conn = sqlite3.connect('data.db')
conn.execute("INSERT INTO table VALUES (?)", (value,))

# Right: explicit commit
conn = sqlite3.connect('data.db')
try:
    conn.execute("INSERT INTO table VALUES (?)", (value,))
    conn.commit()
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()

# Or use context manager (auto-commits):
with sqlite3.connect('data.db') as conn:
    conn.execute("INSERT INTO table VALUES (?)", (value,))
    # Auto-commits on exit
```

#### Table schema mismatch

**Symptom:** `no such column: column_name` when querying
**Root cause:** Database schema outdated; migration not applied
**Fix:** Run migrations

```python
def migrate_db(db_path):
    """Apply schema migrations"""
    with sqlite3.connect(db_path) as conn:
        # Add missing columns if needed
        try:
            conn.execute("ALTER TABLE patterns ADD COLUMN confidence REAL DEFAULT 0.5")
        except sqlite3.OperationalError:
            pass  # Column already exists

        conn.commit()
```

---

## Network & API Issues

### Provider & API Failures

#### API key invalid or expired

**Symptom:** `✗ Unauthorized: Invalid API key` from any provider
**Fix:** Regenerate key

```bash
# DeepSeek
# Go to https://platform.deepseek.com/account/api_keys
# Generate new key, update .env

# z.ai (GLM models)
# Go to https://open.z.ai/app/apikeys
# Generate new key, update .env

# Anthropic
# Go to https://console.anthropic.com/
# Create new key, update .env
```

#### All providers down or unavailable

**Symptom:** All model requests fail, no fallback available
**Root cause:** No provider health checks; fallback logic missing
**Fix:** Implement fallback chain

```python
# agent/core.py
PROVIDER_FALLBACK = [
    ('deepseek', 'deepseek-chat'),
    ('zai', 'glm-4-air'),
    ('anthropic', 'claude-3-sonnet'),
]

def find_working_provider(preferred_provider=None):
    """Find first available provider"""
    for provider, model in PROVIDER_FALLBACK:
        try:
            if is_provider_available(provider):
                return provider, model
        except:
            continue

    raise RuntimeError("No providers available")
```

#### Network timeout on API call

**Symptom:** Request hangs 30+ seconds then fails
**Root cause:** No timeout set, or timeout too long
**Fix:** Add reasonable timeouts

```python
import requests

# Wrong: no timeout
response = requests.get('https://api.example.com/data')

# Right: reasonable timeout
response = requests.get(
    'https://api.example.com/data',
    timeout=10  # 10 seconds
)

# With retry on timeout:
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry = Retry(connect=3, backoff_factor=0.5, status_forcelist=[408, 429, 500])
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)
```

#### SSL certificate validation failure

**Symptom:** `requests.exceptions.SSLError: certificate verify failed`
**Root cause:** Old CA bundle or self-signed cert
**Fix:** Update CA bundle or trust cert

```python
# Update CA bundle
pip install --upgrade certifi

# Or bypass verification (DANGEROUS, only for dev)
import urllib3
urllib3.disable_warnings()
response = requests.get('https://...', verify=False)
```

---

## Docker & Deployment Issues

### Docker Build & Runtime

#### Docker build fails on pip install

**Symptom:** `ERROR: failed to solve with frontend dockerfile.v0`
**Root cause:** Missing build dependencies in Dockerfile
**Fix:** Add required packages

```dockerfile
# Dockerfile
FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Then pip install should work
```

#### Container crashes on startup

**Symptom:** Container exits immediately
**Fix:** Check logs and startup command

```bash
# See what went wrong
docker logs container_name

# Run with interactive terminal to debug
docker run -it neomind_image /bin/bash

# Check entrypoint script
cat docker-entrypoint.sh
```

#### Environment variables not passed to container

**Symptom:** Container can't find API keys
**Fix:** Pass with -e or env-file

```bash
# Method 1: -e flag
docker run -e DEEPSEEK_API_KEY=sk_xxx ... neomind

# Method 2: --env-file
docker run --env-file .env neomind

# Method 3: docker-compose
# docker-compose.yml
services:
  neomind:
    image: neomind
    env_file: .env
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
```

#### Permission denied inside container

**Symptom:** `PermissionError` when reading vault files
**Root cause:** Container running as wrong user
**Fix:** Run as correct user

```dockerfile
# Dockerfile
RUN useradd -m neomind
USER neomind

# Or in docker-compose:
services:
  neomind:
    user: "1000:1000"  # uid:gid
```

---

## Provider Switching & Multi-Model Issues

### Model & Provider Configuration

#### "No answer" — model response is completely blank

**Symptom:** You ask a question, spinner runs, but no text appears
**Root causes:** (Fixed through 4 rounds of debugging)
1. System prompt told model "Do NOT write prose" → only tool blocks output → filter suppressed everything
2. Auto-read file injection broken → file_content loaded but never appended
3. Agentic loop created two consecutive user messages → confused model

**Fixes:**

```python
# 1. System prompt must require explanatory prose
# agent/config/coding.yaml
system_prompt: |
  Provide clear explanations BEFORE code.
  Then show the code blocks.

# 2. Verify file content injected:
def query_with_file(self, question, file_path):
    with open(file_path) as f:
        file_content = f.read()

    # VERIFY this actually gets into the message
    messages.append({
        'role': 'user',
        'content': f"{question}\n<file>{file_content}</file>"
    })

# 3. Combine tool result + continuation into single message
# Don't send tool result as one message, then re-prompt as another
messages.append({
    'role': 'user',
    'content': f"Tool result:\n{tool_output}\n\nContinue analysis."
})
```

#### Model fails to follow tool format

**Symptom:** Asked for `<tool_call>` format, model outputs Python scripts instead
**Root cause:** Model not trained on this format; DeepSeek doesn't follow custom structures reliably
**Fix:** Use bash blocks instead

```python
# agent/core.py
# Don't ask for XML:
# ❌ system_prompt: "Use <tool_call>format"

# Do ask for bash:
# ✓ system_prompt: "Use ```bash blocks"
system_prompt = "Output ```bash code blocks for commands"

# Parse bash blocks, Python blocks as fallback
```

#### Model context limit reached but truncation brutal

**Symptom:** Response cuts off mid-sentence, no graceful warning
**Root cause:** Hard cutoff at token limit, no reserve for error messages
**Fix:** Leave buffer

```python
def generate_completion(self, messages, max_tokens=None):
    model_spec = self._get_model_spec(self.model)
    context_available = model_spec['max_context']
    tokens_used = sum(count_tokens(m['content']) for m in messages)

    # Leave 10% buffer for response + error handling
    safe_limit = int(context_available * 0.90)

    if tokens_used > safe_limit:
        raise RuntimeError(
            f"Context 90% full ({tokens_used}/{safe_limit}). "
            f"Compress conversation or start new session."
        )

    # Generate with max_output as limit
    return api_call(messages, max_tokens=model_spec['max_output'])
```

#### Switching provider mid-conversation breaks context

**Symptom:** Switch from DeepSeek to Claude, model doesn't know previous conversation
**Root cause:** Models have different context interpretation
**Fix:** Don't allow mid-conversation switching

```python
def switch_provider(self, new_provider):
    """Prevent mid-conversation provider switch"""
    if len(self.messages) > 1:
        raise RuntimeError(
            "Cannot switch providers mid-conversation. "
            "Start a new session: /clear, then /switch"
        )

    self.provider = new_provider
```

#### DeepSeek `thinking` parameter fails on other providers

**Symptom:** API error about unsupported `thinking` parameter
**Root cause:** z.ai (GLM) doesn't support DeepSeek's extended thinking
**Fix:** Conditional parameter

```python
def generate_completion(self, messages, **kwargs):
    params = {
        'model': self.model,
        'messages': messages,
        'max_tokens': kwargs.get('max_tokens', 8000),
    }

    # Only add thinking for DeepSeek
    if 'deepseek' in self.model.lower() and kwargs.get('enable_thinking'):
        params['thinking'] = {'type': 'enabled', 'budget_tokens': 5000}

    return openai_client.chat.completions.create(**params)
```

#### Model limits feel wrong after switching

**Symptom:** Context warnings trigger too early after model switch
**Root cause:** Model specs not per-provider
**Fix:** Maintain per-model specs

```python
# agent/core.py
_MODEL_SPECS = {
    'deepseek-chat': {
        'max_context': 128_000,
        'max_output': 8_000,
        'default_max': 8_000,
    },
    'glm-4-air': {
        'max_context': 100_000,
        'max_output': 4_000,
        'default_max': 4_000,
    },
    'claude-3-sonnet': {
        'max_context': 200_000,
        'max_output': 4_000,
        'default_max': 4_000,
    },
}

def _get_model_spec(self, model):
    return self._MODEL_SPECS.get(model, {
        'max_context': 128_000,
        'max_output': 8_000,
        'default_max': 8_000,
    })
```

---

## Memory & Performance Issues

### High Memory Usage

#### Memory usage grows unbounded during long sessions

**Symptom:** Process uses 2GB+ after 1 hour
**Root cause:** Message history never trimmed; vector cache unbounded
**Fix:** Add memory limits

```python
# agent/context_manager.py
MAX_MEMORY = 512 * 1024 * 1024  # 512 MB

def check_memory():
    """Monitor memory usage"""
    import psutil
    process = psutil.Process()
    memory_mb = process.memory_info().rss / (1024 * 1024)

    if memory_mb > MAX_MEMORY / (1024 * 1024):
        print(f"⚠️ Memory {memory_mb:.0f}MB exceeds limit. Compressing...")
        self.compress_conversation()

# Compress conversation when memory tight
def compress_conversation(self):
    """Summarize old messages to save space"""
    summary = self.summarize_messages(self.messages[:-10])
    self.messages = [
        {'role': 'system', 'content': f"Previous context: {summary}"}
    ] + self.messages[-10:]
```

#### Search results cached indefinitely

**Symptom:** Disk fills with cached search results
**Root cause:** Cache never expires
**Fix:** Implement TTL with cleanup

```python
# agent/search/cache.py
CACHE_TTL = 24 * 3600  # 24 hours

def cleanup_old_cache(self):
    """Remove cache entries older than TTL"""
    import os
    import time

    now = time.time()
    for cache_file in glob.glob(self.cache_dir / '*.json'):
        age = now - os.path.getmtime(cache_file)
        if age > self.CACHE_TTL:
            os.unlink(cache_file)
```

### High CPU Usage

#### CPU spins at 100% during idle

**Symptom:** Process using full CPU core when idle
**Root cause:** Polling loop with no sleep; busy-waiting
**Fix:** Add sleep/blocking

```python
# agent/vault/watcher.py
import time

def watch_for_changes(self):
    """Watch with sleep between polls"""
    while True:
        if self.check_for_changes():
            self.on_change()

        time.sleep(1)  # Don't poll every microsecond
```

#### Regex matching hangs CPU

**Symptom:** `/grep` command uses 100% CPU for 30+ seconds
**Root cause:** Catastrophic backtracking in regex
**Fix:** Optimize regex or use time limit

```python
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("Regex match took too long")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(5)  # 5 second timeout

try:
    match = complex_regex.search(large_text)
finally:
    signal.alarm(0)  # Cancel alarm
```

---

## Debug Commands & Logging

### Built-in Debug Tools

#### Check configuration loads correctly

```bash
python3 -c "
from agent_config import agent_config

print(f'Mode: {agent_config.mode}')
print(f'Model: {agent_config.model}')
print(f'Max context: {agent_config.max_context}')
print(f'Tools available: {len(agent_config.get_available_tools())}')
"
```

#### Verify API keys are present

```bash
python3 -c "
import os
from dotenv import load_dotenv

load_dotenv()

for key in ['DEEPSEEK_API_KEY', 'ZAI_API_KEY', 'ANTHROPIC_API_KEY']:
    val = os.getenv(key, '')
    status = f'SET ({val[:8]}...)' if val else 'MISSING'
    print(f'{key}: {status}')
"
```

#### Check provider resolution

```bash
python3 -c "
from agent.core import NeoMindAgent

for model in ['deepseek-chat', 'glm-4-air', 'claude-3-sonnet']:
    spec = NeoMindAgent._get_model_spec(model)
    print(f'{model}:')
    print(f'  Context: {spec[\"max_context\"]//1000}K')
    print(f'  Output: {spec[\"max_output\"]//1000}K')
"
```

#### Test search provider routing

```bash
python3 -c "
from agent.search.router import SearchRouter
from agent.search.sources import SOURCE_REGISTRY

router = SearchRouter()

# Check what providers are available
for name, provider in SOURCE_REGISTRY.list_providers().items():
    print(f'{name}: healthy={provider.is_healthy()}')

# Test routing
result = router.route_query('AAPL stock price')
print(f'\\nRouting query to: {result.provider}')
"
```

#### Test vault connection

```bash
python3 -c "
from agent.vault.reader import VaultReader
from pathlib import Path
import os

vault_dir = os.getenv('VAULT_DIR', '/path/to/vault')
if not Path(vault_dir).exists():
    print(f'✗ Vault not found: {vault_dir}')
    exit(1)

reader = VaultReader(vault_dir)

# Check watched files
for watched_file in ['MEMORY.md', 'current-goals.md', 'SOUL.md']:
    path = Path(vault_dir) / watched_file
    exists = path.exists()
    readable = path.is_file() and os.access(path, os.R_OK)
    print(f'{watched_file}: exists={exists}, readable={readable}')
"
```

### Logging & Diagnostics

#### Enable debug logging globally

```bash
# In agent_config.yaml or at runtime:
logging:
  level: DEBUG
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Now all loggers emit DEBUG and above
```

#### Enable logging for specific module

```python
import logging

# Enable debug for search module only
logging.getLogger('agent.search').setLevel(logging.DEBUG)

# Enable debug for finance module
logging.getLogger('agent.finance').setLevel(logging.DEBUG)
```

#### View current log files

```bash
# Find log files
find . -name "*.log" -type f -exec ls -lh {} \;

# View recent logs
tail -100 logs/neomind.log
tail -f logs/neomind.log  # Follow in real-time

# Search logs for errors
grep ERROR logs/neomind.log | tail -50
grep "Traceback" logs/neomind.log | tail -20
```

#### Test PII sanitizer (ensure logs are safe)

```bash
python3 -c "
from agent.logging.pii_sanitizer import sanitize

text = 'User SSN 123-45-6789 and API key sk_live_xxx'
safe = sanitize(text)
print(f'Original: {text}')
print(f'Sanitized: {safe}')
"
```

### Performance Profiling

#### Find slow functions

```bash
# Run with profiling
python -m cProfile -s cumtime main.py > profile.txt 2>&1

# View results
head -50 profile.txt
```

#### Memory profile

```bash
pip install memory-profiler

python -m memory_profiler main.py
```

#### Measure test execution time

```bash
python -m pytest tests/ --durations=20  # Show 20 slowest tests
python -m pytest tests/test_response_validator_full.py -v --durations=10
```

---

## Common Error Messages & Fixes

| Error Message | Cause | Fix |
|---------------|-------|-----|
| `ModuleNotFoundError: No module named 'agent'` | Package not installed | `pip install -e .` |
| `sqlite3.OperationalError: database is locked` | Concurrent access, no timeout | Add `timeout=5.0` to sqlite3.connect() |
| `KeyError: 'DEEPSEEK_API_KEY'` | API key not in .env | Add `DEEPSEEK_API_KEY=...` to .env |
| `requests.ConnectionError: HTTPSConnectionPool` | Network unreachable | Check internet, firewall, proxy |
| `TimeoutError: search took >60s` | Provider slow or down | Use fallback provider, reduce timeout |
| `ValueError: unbalanced parenthesis` | Malformed user input | Validate/sanitize input |
| `json.JSONDecodeError: Expecting value` | API returned non-JSON | Check API docs, add error handling |
| `yaml.YAMLError: mapping values not allowed` | YAML syntax error | Validate YAML at yamllint.com |
| `PermissionError: [Errno 13] Permission denied` | File/dir not readable | Check file permissions with `ls -l` |
| `OSError: [Errno 28] No space left on device` | Disk full | Clean up logs, cache, old databases |
| `ImportError: cannot import name 'X'` | Module doesn't export name | Check source file exports X; verify import path |
| `TypeError: unsupported operand type(s)` | Type mismatch | Add type checking, explicit conversion |
| `RecursionError: maximum recursion depth exceeded` | Circular call or large data | Check for loops; increase recursion limit cautiously |

---

## Quick Troubleshooting Checklist

When something breaks:

```bash
# 1. Check venv
echo $VIRTUAL_ENV
source .venv/bin/activate

# 2. Check dependencies
pip list | grep -E "prompt_toolkit|rich|aiohttp|PyYAML"

# 3. Check config
python3 -c "from agent_config import agent_config; print(agent_config.mode)"

# 4. Check API keys
grep "API_KEY" .env | head -3

# 5. Check logs
tail -50 logs/*.log

# 6. Run fast tests
python -m pytest tests/ --ignore=tests/test_*_full.py -x

# 7. Check git status
git status
git log --oneline | head -5

# 8. Nuclear option (clean rebuild)
rm -rf .venv __pycache__ .pytest_cache *.db-journal
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python3 main.py
```

---

## Escalation Path

If troubleshooting doesn't resolve the issue:

1. **Check this guide** — Most common issues are here
2. **Check test logs** — `pytest tests/ -v --tb=short` shows detailed errors
3. **Check GitHub issues** — Similar issues may have solutions
4. **Enable debug logging** — `logging.basicConfig(level=logging.DEBUG)`
5. **Create minimal reproduction** — Isolate the problem
6. **File an issue** — Include logs, config, steps to reproduce

---

## Contributing to This Guide

Found a new issue or solution? Please update this document:

1. Add issue to appropriate section
2. Include: Symptom, Root Cause, Fix
3. Add code examples if helpful
4. Commit: `git commit -m "docs: troubleshooting for [issue]"`

**This guide should be continuously updated as new issues are discovered and fixed.**
