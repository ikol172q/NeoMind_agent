# NeoMind Component Usage Guide

Comprehensive documentation for each major component in the NeoMind agent system. Each component covers: purpose, usage examples, API reference, pros, cons, and limitations.

---

## 1. Finance Response Validator

**File:** `agent/finance/response_validator.py`

### Purpose

Enforces the Five Iron Rules for financial mode responses to prevent hallucinated financial data and ensure compliance with strict accuracy standards. Acts as a gatekeeper before any LLM response in `fin` mode is delivered to the user.

**The Five Iron Rules:**
1. No financial numbers from LLM memory (must come from tool calls)
2. No approximate calculations (must use QuantEngine)
3. Every data point has source + timestamp
4. Recommendations need confidence + time horizon + scenarios
5. Source conflicts are shown, never silently resolved

### Usage Examples

```python
from agent.finance.response_validator import FinanceResponseValidator, get_finance_validator

# Create validator instance
validator = FinanceResponseValidator(strict=False)

# Validate a response
result = validator.validate(
    response="Apple stock was at $195.42 (source: Finnhub, 2024-03-15 14:30 UTC)",
    tool_results=[
        {"content": "$195.42", "source": "yfinance"}
    ]
)

if not result.passed:
    # In non-strict mode, append disclaimer
    disclaimer = validator.build_disclaimer(result)
    response += disclaimer

# Or use singleton for consistency
validator = get_finance_validator(strict=True)
```

### API Reference

#### `class FinanceResponseValidator`

**Constructor:**
```python
FinanceResponseValidator(strict: bool = False)
```
- `strict=True`: Block responses with unverified data
- `strict=False`: Add warnings but allow through (default)

**Methods:**

```python
def validate(
    response: str,
    tool_results: Optional[List[Dict]] = None
) -> ValidationResult
```
Returns `ValidationResult` with:
- `passed: bool` — Overall pass/fail
- `warnings: List[str]` — Non-blocking warnings
- `blocked: bool` — True if response was blocked (strict mode)
- `unverified_prices: List[str]` — Prices without tool origin
- `approximate_calcs: List[str]` — Approximate math detected
- `unsourced_data: List[str]` — Data without attribution
- `missing_time_horizons: bool` — Recommendation lacks time frames
- `missing_confidence: bool` — Recommendation lacks confidence level
- `missing_disclaimer: bool` — Recommendation lacks disclaimer

```python
def build_disclaimer(result: ValidationResult) -> str
```
Generates a Chinese/English bilingual disclaimer to append to response.

#### `get_finance_validator(strict: bool = False)`

Singleton accessor for consistent validator instance.

### Price Extraction Patterns

The validator detects financial amounts in multiple formats:
- `$195.42`, `¥1,234.56`, `HK$85.20`, `€123.45`, `£99.00`
- `12345 USD`, `98765 CNY`, `500 BTC`

### Recommendation Detection

Triggers Rule 4 checks when response contains keywords:
- English: "recommend", "suggest", "bullish", "bearish", "buy", "sell", etc.
- Chinese: "建议", "看好", "看空", "应该", etc.

### Pros

- **Bilingual support** — Detects rules violations in both English and Chinese
- **Extensible rules** — PRICE_PATTERNS, SOURCE_PATTERNS configurable
- **Two validation modes** — Strict (block) or warn-only
- **Granular feedback** — Identifies specific violation types
- **No external dependencies** — Pure regex-based, zero latency overhead

### Cons

- **Regex-based, not semantic** — Can't understand financial intent, only patterns
- **False positives possible** — May flag example prices (e.g., "for instance, $100")
- **No ML classification** — Can't learn from correction patterns
- **Limited to regex patterns** — May miss sophisticated hallucinations
- **Language-specific patterns** — Some rules optimized for English/Chinese only

### Limitations

1. **Price exclusion heuristics** — Attempts to skip example/hypothetical prices but not perfect
2. **Source attribution requires exact format** — Must match `(source:`, `(Finnhub,`, etc.
3. **Conflict detection is simplistic** — Requires explicit conflict keywords ("however", "but")
4. **No context understanding** — Can't distinguish valid vs. hallucinated data based on meaning
5. **Threshold-based, not adaptive** — Time horizon and confidence checks are boolean, not scored

### Example: Full Validation Flow

```python
response_text = """
I recommend buying AAPL at $195.42. This stock has shown strong growth
(source: Finnhub, 2024-03-15 14:30 UTC). I'm 75% confident this will
outperform the S&P 500 over a 6-month horizon. Please note this is not
financial advice and is informational purposes only.
"""

tool_results = [
    {"content": "AAPL price: $195.42 (Finnhub)"}
]

result = validator.validate(response_text, tool_results)
# result.passed == True (all rules satisfied)
# result.warnings == []
```

---

## 2. Vault Watcher

**File:** `agent/vault/watcher.py`

### Purpose

Implements lightweight, polling-based bidirectional sync with Obsidian vault. Tracks modification times of key vault files (MEMORY.md, current-goals.md, SOUL.md) and detects when they've been edited in Obsidian. When changes detected, returns updated content for re-injection into system prompt.

### Usage Examples

```python
from agent.vault.watcher import VaultWatcher

# Initialize watcher
watcher = VaultWatcher(vault_dir="/path/to/vault")

# Check for changes (call periodically, e.g., every 50 conversation turns)
changed_content = watcher.check_for_changes()
if changed_content:
    print(f"Files changed: {list(changed_content.keys())}")
    for filename, content in changed_content.items():
        print(f"{filename} updated: {len(content)} bytes")

# Get formatted context string for re-injection into system prompt
context = watcher.get_changed_context(mode="chat")
if context:
    # Re-inject updated context
    agent.add_to_history("system", context)
    watcher.mark_seen()  # Update stored mtimes

# Integration pattern
def on_checkpoint():
    """Called every 50 turns or at session end."""
    watcher = VaultWatcher()
    changed_context = watcher.get_changed_context("chat")
    if changed_context:
        system.inject(changed_context)
        watcher.mark_seen()
```

### API Reference

#### `class VaultWatcher`

**Constructor:**
```python
VaultWatcher(vault_dir: str = None)
```
- `vault_dir`: Path to vault directory (defaults to configured vault)
- Initializes mtime tracking for all watched files

**Watched Files:**
- `MEMORY.md` — Long-term memory
- `current-goals.md` — Weekly improvement targets
- `SOUL.md` — Identity and personality

**Methods:**

```python
def check_for_changes() -> Optional[Dict[str, str]]
```
Returns dict mapping filename → new content if changes detected, else None.

```python
def get_changed_context(mode: str = "chat") -> Optional[str]
```
Returns formatted context string with updated files, or None if no changes.
- Strips YAML frontmatter automatically
- Groups changes into titled sections
- Returns None if no changes (efficiency)

```python
def mark_seen() -> None
```
Updates stored mtimes to current filesystem values. Call after re-injecting context.

### File Monitoring

- **Granularity:** 1-second mtime precision (filesystem-dependent)
- **Deletion detection:** Returns `None` value if file was deleted
- **New files:** Detected when previously None mtime changes to real value
- **Graceful errors:** Logs warnings, continues if stat() fails

### Pros

- **Zero external dependencies** — Uses only `os.stat()`, stdlib only
- **Lightweight polling** — No background threads or event listeners
- **Cross-platform** — Works on Windows, Linux, macOS
- **Graceful degradation** — Handles missing files, permission errors
- **Simple state management** — Just mtime dict, easy to debug

### Cons

- **Polling-based, not realtime** — Changes detected on next check interval
- **1-second mtime granularity** — Some filesystems round to nearest second
- **No event queue** — Only last state tracked, rapid changes could be lost
- **Requires file permissions** — Can't detect changes if not readable
- **No sync conflicts** — If both Obsidian and agent edit simultaneously, last-write-wins

### Limitations

1. **Mtime-only tracking** — Can't detect changes made within 1 second of last check
2. **YAML stripping is naive** — Simple string split, not semantic YAML parsing
3. **No conflict resolution** — If vault and agent both modify file, one overwrites
4. **Polling interval is manual** — Caller must decide when to check (typically 50 turns)
5. **No change history** — Only current state tracked, no diffs or versioning

### Typical Integration

```python
# At session checkpoint (every 50 turns or end)
watcher = VaultWatcher()
changed = watcher.get_changed_context(mode="chat")
if changed:
    # Re-inject into system prompt
    history.append({"role": "system", "content": changed})
    watcher.mark_seen()  # Now won't be detected again
```

---

## 3. Vault Writer

**File:** `agent/vault/writer.py`

### Purpose

Writes structured markdown files to the Obsidian vault with YAML frontmatter and automatic wikilink conversion. Handles journal entries, goals, memory updates, and retros. Gracefully handles missing vault directory (no-op writes).

### Usage Examples

```python
from agent.vault.writer import VaultWriter

writer = VaultWriter(vault_dir="/path/to/vault")

# Ensure vault structure exists
writer.ensure_structure()

# Write daily journal entry
tasks = [
    {"description": "Analyzed AAPL financials", "status": "completed"},
    {"description": "Debug auth module", "status": "completed"},
]
errors = ["Cache miss on yfinance call (retry 1)"]
learnings = [
    "AAPL shows strong support at $150",
    "Cache TTL should be 5 minutes for stock data"
]

path = writer.write_journal_entry(
    mode="fin",
    tasks=tasks,
    errors=errors,
    learnings=learnings,
    tools_used=["yfinance", "Bash"],
    tags=["stocks", "trading", "performance"],
    user_satisfaction="satisfied",
    tokens_used=12500,
    session_duration_min=45
)
# Returns: "journal/2024-03-15.md"

# Append validated learning to MEMORY.md
writer.append_to_memory(
    section="Trading Patterns",
    entry="AAPL responds well to CPI announcements on Thursdays"
)

# Write weekly goals
improvements = [
    {
        "goal": "Reduce unnecessary API calls",
        "current": "~5 calls per session",
        "target": "~2 calls per session",
        "metric": "Average calls per conversation",
        "action": "Implement local caching for 5-minute windows",
        "timeline": "1 week"
    }
]
writer.write_goals(improvements)

# Write weekly retro report
retro_content = "## Week of 2024-03-15\n\n### Accomplishments\n..."
writer.write_retro(retro_content)
```

### API Reference

#### `class VaultWriter`

**Constructor:**
```python
VaultWriter(vault_dir: str = None)
```
- `vault_dir`: Path to vault (defaults to configured location)
- Creates vault directory if it doesn't exist

**Core Methods:**

```python
def ensure_structure()
```
Creates vault subdirectories (journal/, retros/, learnings/, research/) and initial root files if missing.

```python
def write_journal_entry(
    mode: str,
    tasks: List[Dict[str, Any]],
    errors: List[str],
    learnings: List[str],
    tools_used: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    user_satisfaction: str = "neutral",
    tokens_used: int = 0,
    session_duration_min: int = 0
) -> str
```
Writes daily journal entry with YAML frontmatter. Returns relative path (e.g., "journal/2024-03-15.md").

**Frontmatter fields:**
- `type: journal`
- `date, mode, tasks_completed, tasks_failed, errors, user_satisfaction`
- `tools_used: [list], tags: [list]`
- `tokens_used, session_duration_min`

If file exists, appends new session section with separator.

```python
def write_goals(improvements: List[Dict[str, str]])
```
Writes or overwrites `current-goals.md` with weekly improvement targets.

Each improvement dict should have:
- `goal, current, target, metric, action, timeline`

```python
def append_to_memory(section: str, entry: str)
```
Appends entry to MEMORY.md under a section heading. Only for validated patterns (3+ occurrences). Auto-deduplicates, auto-wikifies tickers and codes.

```python
def write_retro(report_content: str, date: str = None)
```
Writes retro report to `retros/retro-{date}.md`.

### Wikilink Conversion (`_wikify`)

Automatically converts recognized entities to Obsidian wikilinks:

```python
text = "I traded $AAPL at $150. Also 600519 is interesting."
wikified = writer._wikify(text)
# Result: "I traded [[$AAPL]] at $150. Also [[600519]] is interesting."
```

**Wikification rules:**
- Stock tickers: `$AAPL` → `[[$AAPL]]`
- 6-digit Chinese codes: `600519` → `[[600519]]`
- Protects code blocks (``` ... ```)
- Protects existing wikilinks
- Excludes common English words

### YAML Frontmatter

All vault files include YAML frontmatter for Obsidian Dataview queryability:

```yaml
---
type: journal
date: 2024-03-15
mode: fin
tasks_completed: 3
tasks_failed: 0
errors: 1
user_satisfaction: satisfied
tools_used: [yfinance, Bash]
tags: [trading, stocks]
tokens_used: 12500
session_duration_min: 45
---
```

### Pros

- **Obsidian-native format** — YAML + markdown, queryable with Dataview
- **Automatic wikilinks** — Creates graph view connections for tickers/codes
- **Deduplication** — Won't add duplicate entries to MEMORY.md
- **Graceful degradation** — All writes are no-ops if vault missing
- **Structured metadata** — YAML frontmatter enables powerful queries

### Cons

- **Regex-based wikification** — Not semantic, can miss entities or over-link
- **Limited entity types** — Only supports tickers and 6-digit Chinese codes
- **No conflict resolution** — If vault and agent edit simultaneously, overwrites
- **YAML is naive** — Simple string manipulation, not semantic parsing
- **No versioning** — Overwrites files without backup

### Limitations

1. **Wikilinks only for tickers + codes** — Other entity types (companies, people) not wikified
2. **YAML escaping is minimal** — Special characters in values could break YAML
3. **Dedup is text-based** — Won't catch semantically identical but differently-worded entries
4. **Frontmatter assumptions** — Assumes YAML format, fails if file is malformed
5. **No atomic writes** — Partial writes possible on disk full

### File Structure

```
vault/
├── MEMORY.md                    # Long-term memory (append-only)
├── SOUL.md                      # Identity and personality
├── current-goals.md             # Weekly improvement targets
├── .gitignore
├── journal/
│   ├── 2024-03-15.md           # Daily entry, multiple sessions
│   ├── 2024-03-14.md
│   └── ...
├── retros/
│   ├── retro-2024-03-15.md
│   └── ...
├── learnings/
└── research/
```

---

## 4. Vault Promoter

**File:** `agent/vault/promoter.py`

### Purpose

Moves validated patterns from SharedMemory database to MEMORY.md vault file. Implements the "3+ occurrences" rule to prevent one-off or hallucinated observations from becoming permanent memory. Called by weekly retro process.

### Usage Examples

```python
from agent.vault.promoter import promote_patterns
from agent.memory.shared_memory import SharedMemory
from agent.vault.writer import VaultWriter

# Get instances
shared_memory = SharedMemory()
vault_writer = VaultWriter()

# Promote validated patterns
promoted_count = promote_patterns(shared_memory, vault_writer)
print(f"Promoted {promoted_count} patterns to MEMORY.md")

# Example: Pattern with count >= 3 gets promoted
# DB Entry: {
#   "pattern_type": "frequent_stock",
#   "pattern_value": "AAPL",
#   "count": 5,
#   "source_mode": "fin"
# }
# becomes:
# In MEMORY.md: "## Trading Patterns\n- AAPL (observed 5x, source: fin)"
```

### API Reference

#### `promote_patterns(shared_memory, vault_writer=None) -> int`

```python
def promote_patterns(shared_memory, vault_writer=None) -> int
```

**Arguments:**
- `shared_memory`: SharedMemory instance with `get_all_patterns()` method
- `vault_writer`: Optional VaultWriter (creates new one if None)

**Returns:**
- Integer count of patterns promoted

**Promotion Rules:**
- Only patterns with `count >= PROMOTION_THRESHOLD` (3) are promoted
- Each pattern_type maps to a MEMORY.md section via SECTION_MAP
- Entry format: `{value} (observed {count}x, source: {mode})`

### Section Mapping

```python
SECTION_MAP = {
    "frequent_stock": "Trading Patterns",
    "coding_language": "Coding Preferences",
    "tool": "Tool Preferences",
    "topic": "Conversation Topics",
    "language": "Language Preferences",
}
```

Unknown types default to "Other Patterns" section.

### Promotion Flow

1. **Query patterns** — `shared_memory.get_all_patterns()`
2. **Filter** — Keep only `count >= 3`
3. **Deduplicate** — `vault_writer.append_to_memory()` handles
4. **Update MEMORY.md** — Via VaultWriter with wikilinks
5. **Log** — Record promotion count

### Pros

- **Prevents hallucination** — 3x threshold means pattern is truly observed
- **Section-mapped** — Automatically organizes into appropriate MEMORY.md sections
- **Cross-mode visibility** — fin mode AAPL pattern visible to chat mode
- **Deduplication included** — VaultWriter prevents duplicate entries
- **Simple, predictable logic** — Easy to audit and debug

### Cons

- **Fixed threshold, not configurable** — 3 occurrences hardcoded
- **No decay mechanism** — Patterns never fade even if user stops using them
- **No semantic clustering** — "AAPL" and "Apple" are different patterns
- **No ranking** — All promoted patterns equally weighted
- **Blind to context** — "AAPL" from 6 months ago counts same as recent

### Limitations

1. **No temporal decay** — Patterns become permanent once promoted
2. **No pattern clustering** — Similar patterns (AAPL, APPL typo) are separate
3. **No confidence scoring** — Promotion is binary (3x or not)
4. **One-way promotion** — Patterns never un-promoted
5. **No pattern lifecycle** — No archival or deprecation mechanism

### Integration with Weekly Retro

```python
# In auto_evolve.run_weekly_retro()
from agent.vault.promoter import promote_patterns

# ... generate retro report ...

# Promote validated patterns
promoted = promote_patterns(self.shared_memory)
report.patterns_promoted = promoted
```

---

## 5. Evolution Scheduler

**File:** `agent/evolution/scheduler.py`

### Purpose

Lightweight session-based scheduler for auto-evolution tasks. Integrates with NeoMind's natural lifecycle points (session start/end, every N conversation turns) to decide if daily/weekly tasks should run. No external dependencies, zero background processes.

### Usage Examples

```python
from agent.evolution.scheduler import EvolutionScheduler
from agent.evolution.auto_evolve import AutoEvolve

# Initialize
auto_evolve = AutoEvolve()
scheduler = EvolutionScheduler(auto_evolve)

# At session start
actions = scheduler.on_session_start()
# Returns: ["Health: 8 checks passed", "Daily audit: 156 calls, 2 errors"]

# Every 50 conversation turns
actions = scheduler.on_turn_complete(turn_number=50)
# Usually empty unless daily audit is due

# At session end
actions = scheduler.on_session_end()
# Returns: ["Daily audit: 156 calls, 2 errors"]
```

### API Reference

#### `class EvolutionScheduler`

**Constructor:**
```python
EvolutionScheduler(auto_evolve)
```
- `auto_evolve`: AutoEvolve instance for running evolution tasks

**State:**
- `daily_ran_this_session: bool` — Guard against duplicate daily runs
- `weekly_ran_this_session: bool` — Guard against duplicate weekly runs
- `turn_check_interval: int` — Turns between checks (default 50)
- `last_turn_checked: int` — Last turn when interval check ran

**Methods:**

```python
def on_session_start() -> List[str]
```
Called at new session start. Runs:
1. Health check (always)
2. Daily audit (if 24+ hours since last run)
3. Weekly retro (if 7+ days since last run)

Returns list of action descriptions for logging.

```python
def on_turn_complete(turn_number: int) -> List[str]
```
Called after each conversation turn. Checks every N turns if daily audit should run. Useful for long-running sessions. Usually returns empty list.

```python
def on_session_end() -> List[str]
```
Called at session exit. Ensures daily audit runs at least once per day.

```python
def check_and_run_pending() -> List[str]
```
Utility to manually check and run any pending evolution tasks.

### Scheduling Rules

- **Health check** — Always runs, non-blocking
- **Daily audit** — Runs if `auto_evolve.should_run_daily()` returns True (24+ hours since last)
- **Weekly retro** — Runs if `auto_evolve.should_run_weekly()` returns True (7+ days since last)
- **Guards** — `daily_ran_this_session` prevents duplicate runs in same session

### Pros

- **Zero external dependencies** — Uses stdlib only, no APScheduler or similar
- **Integrates with natural lifecycle** — Hooks into session start/end/turns
- **Guardrails against duplicates** — `_ran_this_session` flags prevent re-running
- **Non-blocking** — All tasks wrapped in try/except
- **Simple state management** — No background threads, just booleans

### Cons

- **Not wall-clock based** — Depends on sessions being active
- **Daily guard resets per session** — If user has 2 sessions, audit might run twice in 1 day
- **Polling-based interval check** — Every 50 turns is arbitrary
- **Manual turn tracking** — Caller must pass turn number
- **No external event hooks** — Can't trigger from timer or external event

### Limitations

1. **Session-dependent** — If user doesn't have sessions, tasks don't run
2. **No persistence across restarts** — `_ran_this_session` resets on new EvolutionScheduler
3. **No actual scheduling** — Just checkpoints, not true scheduling
4. **Manual integration required** — Caller must call at right lifecycle points
5. **Turn-interval arbitrary** — 50-turn default may not fit all use cases

### Typical Integration

```python
# In NeoMind main loop
scheduler = EvolutionScheduler(auto_evolve)

# Session start
actions = scheduler.on_session_start()
for action in actions:
    logger.info(f"Evolution: {action}")

# Every 50 turns
if turn_number % 50 == 0:
    actions = scheduler.on_turn_complete(turn_number)
    if actions:
        for action in actions:
            logger.info(f"Evolution: {action}")

# Session end
actions = scheduler.on_session_end()
for action in actions:
    logger.info(f"Evolution: {action}")
```

---

## 6. Evolution Dashboard

**File:** `agent/evolution/dashboard.py`

### Purpose

Generates a self-contained HTML dashboard for evolution metrics, health status, and performance analytics. Includes Chart.js visualizations, dark theme, and fallback handling for missing data sources.

### Usage Examples

```python
from agent.evolution.dashboard import generate_dashboard, collect_metrics

# Generate dashboard HTML and write to file
html = generate_dashboard(output_path="~/.neomind/dashboard.html")

# Or just get the HTML string
html = generate_dashboard()
print(f"Generated {len(html)} bytes of HTML")

# Collect metrics without generating HTML
metrics = collect_metrics()
print(f"Daily stats: {metrics['daily_stats']}")
print(f"Patterns: {metrics['patterns']}")

# From CLI
# python -m agent.evolution.dashboard [output_path]
```

### API Reference

#### `collect_metrics() -> Dict[str, Any]`

Gathers metrics from all sources with fallback empty data if unavailable.

**Returns:**
```python
{
    "timestamp": "2024-03-15T14:30:00.123456",
    "health": {
        "checks_passed": 8,
        "checks_failed": 0,
        "last_successful_run": "2024-03-15T08:00:00",
        "issues": []
    },
    "daily_stats": [
        {
            "date": "2024-03-15",
            "events": 156,
            "llm_calls": 12,
            "errors": 2,
            "commands": 45,
            "tokens": 125000
        }
    ],
    "mode_distribution": {
        "chat": 45,
        "coding": 30,
        "fin": 25
    },
    "patterns": [
        {"type": "frequent_stock", "value": "AAPL", "count": 23},
        {"type": "coding_language", "value": "Python", "count": 19}
    ],
    "evidence_recent": [
        {
            "action": "trade",
            "ts": "2024-03-15T10:23:45",
            "input": "Buy 100 AAPL",
            "output": "Order confirmed",
            "severity": "info"
        }
    ],
    "evolution_timeline": [
        ("Health Check", "2024-03-15T08:00:00"),
        ("Daily Audit", "2024-03-15T08:05:00"),
        ("Weekly Retro", "2024-03-14T10:00:00")
    ],
    "learning_log": [
        {
            "type": "pattern",
            "timestamp": "2024-03-15",
            "content": "AAPL responds to earnings"
        }
    ]
}
```

**Data Sources:**
1. AutoEvolve state file (health, timeline, learnings)
2. Unified logger (daily stats, mode distribution)
3. SharedMemory patterns DB (top patterns)
4. Evidence trail (recent actions)

Each source has try/except for graceful fallback.

#### `generate_dashboard(output_path: Optional[str] = None) -> str`

Generates complete self-contained HTML dashboard.

**Arguments:**
- `output_path`: Optional file path to write HTML (e.g., "~/.neomind/dashboard.html")

**Returns:**
- HTML string with embedded CSS/JS (no external file dependencies except CDN)

**Features:**
- **Chart.js visualizations** — Daily activity bar chart, mode distribution doughnut
- **Dark theme** — Slate blues and grays
- **Health status indicator** — Green/yellow/red with animation
- **Responsive layout** — Grid-based, works on mobile
- **Embedded styles** — No external CSS file needed
- **Self-contained** — Single HTML file, easy to share/archive

### Dashboard Sections

1. **System Health** — Status indicator, checks passed/failed, last run time, issues list
2. **Daily Activity (7 Days)** — Bar chart of LLM calls and errors
3. **Mode Distribution** — Doughnut chart of chat/coding/fin usage
4. **Top Learning Patterns** — Grid of most frequently observed patterns
5. **Recent Evidence Trail** — Timeline of recent actions with severity indicators
6. **Evolution Timeline** — History of evolution runs (startup, daily, weekly)
7. **Recent Learnings** — Last 20 learning entries with timestamps

### Metrics Collection Flow

```
collect_metrics()
├── AutoEvolve: health, timeline, learnings
├── UnifiedLogger: daily_stats (7 days), mode_distribution
├── SharedMemory patterns DB: top patterns (20 limit)
└── Evidence trail: recent entries (10 limit)
```

Each source wrapped in try/except:
- Unavailable source → returns empty/default value
- Corrupted data → logged and skipped
- Missing DB → returns no patterns
- Logger not initialized → returns empty stats

### Pros

- **Self-contained HTML** — No external files, works offline
- **Chart.js visualization** — Interactive, responsive charts
- **Dark theme** — Easy on eyes for monitoring
- **Zero dependencies** — Falls back gracefully if sources missing
- **Static snapshot** — Can be archived or shared as single file

### Cons

- **Static snapshot, not live** — Must manually refresh or regenerate
- **Requires manual refresh** — No real-time updates or websocket
- **Limited customization** — Colors and layout hardcoded
- **Chart.js from CDN** — Requires internet for Chart.js library
- **No drill-down** — Can't click patterns to see details

### Limitations

1. **Snapshot-in-time** — Shows data as of generation time, not live
2. **7-day window fixed** — Can't adjust date range in dashboard
3. **10 pattern limit** — Top patterns capped, can't scroll
4. **No export options** — Can't export data as CSV/JSON
5. **Browser-only** — HTML requires modern browser to view

### CLI Usage

```bash
# Generate and save to default location (~/.neomind/dashboard.html)
python -m agent.evolution.dashboard

# Save to custom location
python -m agent.evolution.dashboard /tmp/neomind-dashboard.html

# Then open in browser
open /tmp/neomind-dashboard.html
```

---

## 7. Crawl4AI Adapter

**File:** `agent/web/crawl4ai_adapter.py`

### Purpose

Provides async web crawling with JavaScript rendering capabilities. Wraps crawl4ai's AsyncWebCrawler to match BFSCrawler API. Gracefully falls back to synchronous BFSCrawler if crawl4ai is not installed. Includes stealth mode to avoid detection.

### Usage Examples

```python
from agent.web.crawl4ai_adapter import Crawl4AIAdapter
import asyncio

# Create adapter
adapter = Crawl4AIAdapter(
    delay=1.0,                    # 1 second delay between requests
    browser_type="chromium",      # or "firefox", "webkit"
    headless=True,                # Run headless (no UI)
    use_stealth=True              # Apply playwright-stealth
)

# Async crawl
async def crawl_site():
    report = await adapter.crawl(
        start_url="https://example.com",
        max_depth=2,              # Follow links up to 2 hops deep
        max_pages=10,             # Hard cap at 10 pages
        allow_external=False      # Stay within example.com domain
    )

    print(f"Crawled {len(report.pages)} pages")
    for page in report.pages:
        print(f"  [{page.depth}] {page.title} ({page.word_count} words)")

    return report

# Run async function
report = asyncio.run(crawl_site())

# Falls back to sync if crawl4ai not installed
if report.pages:
    print(report.pages[0].content[:500])
```

### API Reference

#### `class Crawl4AIAdapter`

**Constructor:**
```python
Crawl4AIAdapter(
    extractor: Optional[WebExtractor] = None,
    cache: Optional[URLCache] = None,
    delay: float = 1.0,
    browser_type: str = "chromium",
    headless: bool = True,
    use_stealth: bool = True
)
```

**Arguments:**
- `extractor`: WebExtractor instance for content extraction
- `cache`: Optional URLCache for deduplication
- `delay`: Seconds between requests (politeness, default 1.0)
- `browser_type`: "chromium", "firefox", or "webkit"
- `headless`: Run browser headless (default True)
- `use_stealth`: Apply playwright-stealth to avoid detection

**Methods:**

```python
async def crawl(
    start_url: str,
    max_depth: int = 1,
    max_pages: int = 10,
    allow_external: bool = False
) -> CrawlReport
```

**Arguments:**
- `start_url`: Entry point URL (auto-prefixed with https:// if needed)
- `max_depth`: How many link-hops deep (0 = start page only)
- `max_pages`: Hard cap on total pages to fetch
- `allow_external`: If True, follow cross-domain links

**Returns:**
- `CrawlReport` with list of `CrawlResult` pages

### Fallback Behavior

If crawl4ai is not installed:
1. **Log warning** — "crawl4ai not installed, falling back to BFSCrawler"
2. **Use sync BFSCrawler** — Returns to synchronous mode
3. **Same API** — Returns compatible CrawlReport

Installation for crawl4ai:
```bash
pip install 'neomind[web]'
# or
pip install crawl4ai playwright
```

### Stealth Mode

If `use_stealth=True` and playwright-stealth is installed:
- Applies stealth measures to avoid bot detection
- Removes headless indicators
- Patches navigator properties
- Silently continues if stealth setup fails

### Pros

- **Graceful fallback to sync** — Works even if crawl4ai not installed
- **Stealth mode** — Avoids bot detection on strict sites
- **JS rendering** — Can crawl JavaScript-heavy sites
- **Cross-browser support** — chromium, firefox, webkit options
- **Configurable politeness** — Adjustable delay between requests

### Cons

- **Requires crawl4ai + playwright deps** — Heavy browser footprint
- **Heavy resource usage** — Browser instance consumes memory
- **Headless still detectable** — Some sites block headless browsers anyway
- **Stealth not perfect** — Advanced bot detection can still catch it
- **Async-only for crawl4ai** — Must use asyncio or async/await

### Limitations

1. **Stealth may fail silently** — No error if stealth application fails
2. **Browser instance lifecycle** — Context manager required
3. **JS rendering timeout** — Hangs possible on slow JS-heavy sites
4. **No custom headers** — Can't set User-Agent or other headers easily
5. **Single-threaded** — Only one async context per adapter instance

### BFS Crawling Algorithm

```
1. Start with (start_url, depth=0) in queue
2. While queue not empty and visited < max_pages:
   a. Pop (url, depth) from front of queue
   b. Skip if visited or depth > max_depth
   c. Skip if external and allow_external=False
   d. Crawl with crawl4ai (or fallback to sync)
   e. Extract content with WebExtractor
   f. Add page to report
   g. Find links in content, add to queue with depth+1
3. Return CrawlReport with all pages
```

### CrawlReport Structure

```python
@dataclass
class CrawlReport:
    start_url: str
    pages: List[CrawlResult]
    total_time_seconds: float
    pages_crawled: int
    pages_failed: int
    avg_content_length: float
```

---

## 8. Skill Loader

**File:** `agent/skills/loader.py`

### Purpose

Parses and manages SKILL.md files from the skills directory tree. Loads shared and mode-specific skills, provides filtering by mode, and formats skill lists for display. SKILL.md format includes YAML frontmatter for metadata and markdown body for prompt content.

### Usage Examples

```python
from agent.skills.loader import SkillLoader

# Initialize and load all skills
loader = SkillLoader()
loaded_count = loader.load_all()
print(f"Loaded {loaded_count} skills")

# Get a specific skill
office_hours = loader.get("office-hours")
if office_hours:
    system_prompt_injection = office_hours.to_system_prompt()
    # Use in LLM context

# Get skills available for a mode
coding_skills = loader.get_skills_for_mode("coding")
for skill in coding_skills:
    print(f"  {skill.name}: {skill.description}")

# List all skills (formatted for display)
print(loader.format_skill_list(mode="fin"))

# Check skill count
print(f"Total skills: {loader.count}")
```

### SKILL.md File Format

```markdown
---
name: office-hours
description: Deep requirement mining with forcing questions
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, WebSearch]
version: 1.0.0
---

# Office Hours

You are conducting a structured requirement analysis session...

## Rules
1. Ask clarifying questions
2. Probe assumptions
3. ...

(rest of prompt body)
```

**YAML Metadata:**
- `name` — Unique skill identifier (required, used in `/skillname`)
- `description` — One-line summary for listing
- `modes` — List of personality modes that can use this (chat/coding/fin)
- `allowed-tools` — Optional list of tools this skill uses
- `version` — Semantic version (default 1.0.0)

**Body:**
- Markdown content after frontmatter
- Used as system prompt injection when skill invoked
- Can include instructions, examples, rules

### API Reference

#### `class SkillLoader`

**Constructor:**
```python
SkillLoader(skills_dir: Optional[str] = None)
```
- `skills_dir`: Path to skills directory (defaults to skills/ relative to loader.py)

**Methods:**

```python
def load_all() -> int
```
Scans all category directories (shared/, chat/, coding/, fin/) for SKILL.md files. Returns count loaded.

```python
def get(name: str) -> Optional[Skill]
```
Get a skill by name (returns None if not found). Auto-loads if not yet loaded.

```python
def get_skills_for_mode(mode: str) -> List[Skill]
```
Get all skills available for a specific mode (chat/coding/fin). Auto-loads if needed.

```python
def list_skills(mode: Optional[str] = None) -> List[Dict]
```
Get list of skill metadata dicts. Optionally filtered by mode. Returns:
```python
[
    {
        "name": "office-hours",
        "description": "Deep requirement mining",
        "modes": ["chat", "coding", "fin"],
        "category": "shared",
        "version": "1.0.0"
    }
]
```

```python
def format_skill_list(mode: Optional[str] = None) -> str
```
Format skill list for display with category grouping and icons:
```
🔗 SHARED
  /office-hours — Deep requirement mining  [chat, coding, fin]
  /research — Comprehensive topic research  [chat, coding, fin]

💬 CHAT
  /storytelling — Creative narrative generation  [chat]

💻 CODING
  /refactor — Code quality improvements  [coding]

📈 FIN
  /trading-analysis — Technical analysis  [fin]
```

#### `class Skill`

**Dataclass fields:**
```python
@dataclass
class Skill:
    name: str                    # e.g., "office-hours"
    description: str             # One-liner
    body: str                    # Prompt body (markdown)
    modes: List[str]             # [chat, coding, fin]
    allowed_tools: List[str]     # [Bash, Read, WebSearch]
    version: str                 # 1.0.0
    path: str                    # Filesystem path
    category: str                # shared, chat, coding, fin
```

**Methods:**

```python
def to_system_prompt() -> str
```
Convert skill into a system prompt injection:
```
## Active Skill: office-hours
Deep requirement mining with forcing questions

(prompt body content)
```

### Directory Structure

```
skills/
├── shared/
│   ├── office-hours/
│   │   └── SKILL.md
│   ├── research/
│   │   └── SKILL.md
│   └── ...
├── chat/
│   ├── storytelling/
│   │   └── SKILL.md
│   └── ...
├── coding/
│   ├── refactor/
│   │   └── SKILL.md
│   └── ...
└── fin/
    ├── trading-analysis/
    │   └── SKILL.md
    └── ...
```

Each skill is a directory containing SKILL.md.

### Pros

- **YAML+markdown format** — Human-readable, version-controllable
- **Multi-mode support** — Skills can apply to 1 or more personality modes
- **Category organization** — Shared vs. mode-specific
- **Lazy loading** — Loads on first use, not at startup
- **Easy to author** — Simple text format, no code required

### Cons

- **Filesystem-based only** — Can't load from databases or APIs
- **No hot-reload** — Must restart to load new skills
- **Singleton pattern** — Single shared loader instance
- **No dependency resolution** — Can't specify skill prerequisites
- **No versioning** — Can't have multiple versions of same skill

### Limitations

1. **No hot-reload** — New SKILL.md files not detected until loader restart
2. **Parsing is naive** — Simple regex split, not semantic YAML parser
3. **No skill validation** — Doesn't check if referenced tools exist
4. **No skill inheritance** — Can't extend or compose skills
5. **Frontmatter required** — No fallback if YAML missing

### Typical Integration

```python
# In NeoMind initialization
loader = SkillLoader()
loader.load_all()

# When user invokes /skillname
if command.startswith("/"):
    skill_name = command[1:]  # Remove leading /
    skill = loader.get(skill_name)
    if skill and skill_mode in skill.modes:
        system_prompt += skill.to_system_prompt()
    else:
        print(f"Skill {skill_name} not found or not available in {skill_mode} mode")
```

---

## 9. Shared Memory

**File:** `agent/memory/shared_memory.py`

### Purpose

Cross-personality persistent memory system. Stores user preferences, facts, patterns, and feedback in a shared SQLite database. All three personalities (chat, coding, finance) can read and write. Minimal dependencies (stdlib + sqlite3 only) with WAL mode for concurrent access.

### Usage Examples

```python
from agent.memory.shared_memory import SharedMemory

# Initialize (creates ~/.neomind/shared_memory.db if not exists)
memory = SharedMemory()

# Store preferences (cross-mode visibility)
memory.set_preference('timezone', 'America/Los_Angeles', source_mode='chat')
memory.set_preference('language', 'en', source_mode='chat')
memory.set_preference('preferred_model', 'claude-3-opus', source_mode='chat')

# Retrieve preferences
timezone = memory.get_preference('timezone', default='UTC')
all_prefs = memory.get_all_preferences()

# Remember facts about the user
memory.remember_fact('work', 'SDE at Google', source_mode='chat')
memory.remember_fact('education', 'BS in CS from Stanford', source_mode='chat')
memory.remember_fact('interests', 'Options trading, cryptocurrency', source_mode='fin')

# Record behavioral patterns (for validation/promotion)
memory.record_pattern('frequent_stock', 'AAPL', source_mode='fin')
memory.record_pattern('frequent_stock', 'AAPL', source_mode='fin')  # increments count
memory.record_pattern('frequent_stock', 'AAPL', source_mode='fin')  # count=3, ready for promotion
memory.record_pattern('coding_language', 'Python', source_mode='coding')

# Get all patterns
patterns = memory.get_all_patterns()
for p in patterns:
    if p['count'] >= 3:
        print(f"Ready for promotion: {p['pattern_value']} ({p['count']}x)")

# Record user feedback
memory.record_feedback(
    feedback_type='correction',
    content='I prefer async/await over callbacks',
    source_mode='coding'
)

# Get context summary (for system prompt injection)
context = memory.get_context_summary(mode='coding')
# Returns formatted string with relevant preferences, facts, patterns

# Export/import for backup
export_data = memory.export_json()
with open('memory_backup.json', 'w') as f:
    json.dump(export_data, f)

# Later, import from backup
memory.import_json(export_data)
```

### API Reference

#### `class SharedMemory`

**Constructor:**
```python
SharedMemory(db_path: Optional[str] = None)
```
- `db_path`: Path to SQLite database (defaults to ~/.neomind/shared_memory.db)
- Creates directory with restricted permissions (0o700 on Unix)
- Initializes WAL mode for concurrent access

**Database Schema:**

```sql
-- Preferences (key-value)
CREATE TABLE preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    updated_at TEXT NOT NULL
)

-- Facts (tagged observations)
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    fact TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    created_at TEXT NOT NULL
)

-- Patterns (frequency-tracked observations)
CREATE TABLE patterns (
    id INTEGER PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    pattern_value TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    source_mode TEXT NOT NULL,
    updated_at TEXT NOT NULL
)

-- Feedback (corrections and preferences)
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    feedback_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    created_at TEXT NOT NULL
)
```

### Preferences API

```python
def set_preference(key: str, value: str, source_mode: str) -> None
```
Store or update a preference (upsert).

```python
def get_preference(key: str, default: Optional[str] = None) -> Optional[str]
```
Get a preference value or default.

```python
def get_all_preferences() -> Dict[str, Any]
```
Get all preferences with metadata:
```python
{
    'timezone': {
        'value': 'America/Los_Angeles',
        'source_mode': 'chat',
        'updated_at': '2024-03-15T10:23:45.123456+00:00'
    }
}
```

### Facts API

```python
def remember_fact(category: str, fact: str, source_mode: str) -> None
```
Record a fact about the user (e.g., work, education, interests).

```python
def get_facts(category: Optional[str] = None) -> List[Dict]
```
Get facts, optionally filtered by category.

### Patterns API

```python
def record_pattern(pattern_type: str, pattern_value: str, source_mode: str) -> None
```
Record a behavioral pattern. Increments count if already exists.

```python
def get_all_patterns() -> List[Dict]
```
Get all patterns (used by vault_promoter to find promotion candidates).

### Feedback API

```python
def record_feedback(feedback_type: str, content: str, source_mode: str) -> None
```
Record user corrections and preferences.

```python
def get_feedback(feedback_type: Optional[str] = None) -> List[Dict]
```
Get feedback, optionally filtered by type.

### Context Summary API

```python
def get_context_summary(mode: str = "chat") -> str
```
Returns formatted text for system prompt injection:
```
## Shared Memory Context

### Preferences
- timezone: America/Los_Angeles
- language: en

### Recent Facts
- work: SDE at Google (from chat)
- education: BS in CS (from chat)

### Frequent Patterns
- AAPL (observed 5x in fin mode)
- Python (observed 8x in coding mode)

### Recent Feedback
- correction: prefer async/await (from coding)
```

Mode-aware: Prioritizes learnings from the current mode.

### Export/Import API

```python
def export_json() -> Dict[str, Any]
```
Export all data as JSON dict for backup.

```python
def import_json(data: Dict[str, Any]) -> None
```
Import data from JSON (overwrites existing).

### Pros

- **Thread-safe** — Uses thread-local connections
- **WAL mode** — Allows concurrent reads while writing
- **Cross-mode visibility** — Any mode can read all data
- **Minimal dependencies** — stdlib + sqlite3 only
- **Atomic writes** — SQLite handles consistency
- **Exportable** — JSON import/export for backup

### Cons

- **SQLite-bound** — Not suitable for distributed deployments
- **No semantic search** — Pattern matching is exact string match
- **Flat schema** — No hierarchical relationships
- **No full-text search** — Can't search fact text efficiently
- **String-only values** — Preferences limited to text

### Limitations

1. **No semantic search** — "Apple" and "AAPL" are different patterns
2. **No decay** — Patterns never fade, even if stale
3. **No clustering** — Similar patterns are separate entries
4. **Pattern count is simple** — No confidence scoring or weighting
5. **No deletion** — No way to remove old patterns (only via SQL)

### Thread Safety

- Each thread gets its own connection (thread-local storage)
- WAL mode allows concurrent reads
- Writes are serialized by SQLite
- Timeout set to 5 seconds to avoid deadlocks

### Typical Integration

```python
# At session start
memory = SharedMemory()
context = memory.get_context_summary(mode="coding")
system_prompt += context

# During session
memory.record_pattern("coding_language", "Python", source_mode="coding")
memory.record_feedback("correction", "...", source_mode="coding")

# At session end
memory.record_feedback("satisfaction", "very satisfied", source_mode="coding")
```

---

## 10. Unified Logger + PII Sanitizer

**File:** `agent/logging/unified_logger.py` and `agent/logging/pii_sanitizer.py`

### Purpose

Central JSONL logging system for all NeoMind operations with automatic PII redaction. Every operation is logged to daily JSONL files with type, mode, and custom fields. PIISanitizer detects and masks emails, phone numbers, API keys, SSNs, credit cards, and other sensitive data before logging.

### Usage Examples

```python
from agent.logging.unified_logger import get_unified_logger, UnifiedLogger
from agent.logging.pii_sanitizer import PIISanitizer
from datetime import date

# Get logger (singleton)
logger = get_unified_logger()

# Log LLM call
logger.log_llm_call(
    model="claude-3-opus",
    prompt_tokens=1200,
    completion_tokens=450,
    latency_ms=1234.5,
    mode="coding"
)

# Log command execution
logger.log_command(
    cmd="git commit -m 'Add feature'",
    exit_code=0,
    duration_ms=523,
    mode="coding",
    cwd="/home/user/project"
)

# Log file operation
logger.log_file_op(
    operation="write",
    path="/home/user/project/main.py",
    mode="coding",
    size_bytes=1024
)

# Log error
logger.log_error(
    error_type="FileNotFoundError",
    message="Config file not found",
    severity="warning",
    mode="chat",
    traceback="..."
)

# Log search operation
logger.log_search(
    query="python async patterns",
    results_count=42,
    source="web",
    mode="coding"
)

# Log provider switch
logger.log_provider_switch(
    from_provider="openai",
    to_provider="anthropic",
    updated_by="user"
)

# Query logs by date
today = date.today()
daily_logs = logger.query(start_date=today, log_type="llm_call")

# Get statistics
daily_stats = logger.get_daily_stats(today)
print(f"Total events: {daily_stats['total_events']}")
print(f"Errors: {daily_stats['errors']}")
print(f"Total tokens: {daily_stats.get('total_tokens', 0)}")
print(f"By mode: {daily_stats['by_mode']}")
```

### API Reference

#### `class UnifiedLogger`

**Constructor:**
```python
UnifiedLogger(log_dir: Optional[str] = None)
```
- `log_dir`: Directory for logs (defaults to ~/.neomind/logs)
- Auto-sanitizes PII with PIISanitizer in strict mode

**Log Methods:**

```python
def log(log_type: str, mode: str = "unknown", **kwargs) -> None
```
Generic log entry. Auto-adds timestamp, sanitizes all kwargs.

```python
def log_llm_call(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    mode: str = "unknown",
    **extra
) -> None
```
Log an LLM API call.

```python
def log_command(
    cmd: str,
    exit_code: int,
    duration_ms: float,
    mode: str = "unknown",
    **extra
) -> None
```
Log shell command execution. Sets `success` to `exit_code == 0`.

```python
def log_file_op(
    operation: str,
    path: str,
    mode: str = "unknown",
    **extra
) -> None
```
Log file operation (read/write/delete/append).

```python
def log_error(
    error_type: str,
    message: str,
    severity: str = "error",
    mode: str = "unknown",
    **extra
) -> None
```
Log error event. Severity levels: debug, info, warning, error, critical.

```python
def log_search(
    query: str,
    results_count: int,
    source: str = "unknown",
    mode: str = "unknown",
    **extra
) -> None
```
Log search operation.

```python
def log_provider_switch(
    from_provider: str,
    to_provider: str,
    updated_by: str = "system",
    **extra
) -> None
```
Log provider/model switch.

**Query Methods:**

```python
def query(
    log_type: Optional[str] = None,
    mode: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> List[Dict]
```
Query logs by type, mode, and date range.

```python
def get_daily_stats(target_date: date) -> Dict
```
Get statistics for a specific day:
```python
{
    "date": "2024-03-15",
    "total_events": 156,
    "by_type": {
        "llm_call": 12,
        "command": 45,
        "file_op": 50,
        "error": 2,
        ...
    },
    "by_mode": {
        "chat": 60,
        "coding": 50,
        "fin": 40,
        "unknown": 6
    },
    "errors": 2,
    "total_commands": 45,
    "total_tokens": 125000  # Sum of prompt + completion tokens
}
```

```python
def get_weekly_stats() -> Dict
```
Get statistics for past 7 days.

#### `get_unified_logger(log_dir: Optional[str] = None) -> UnifiedLogger`

Singleton accessor for consistent logger instance.

### JSONL Log Format

Each line is a JSON entry with auto-populated fields:

```json
{"ts": "2024-03-15T14:30:45.123456", "type": "llm_call", "mode": "coding", "model": "claude-3-opus", "prompt_tokens": 1200, "completion_tokens": 450, "latency_ms": 1234.5, "total_tokens": 1650}
```

**Standard fields:**
- `ts` — ISO 8601 timestamp
- `type` — Log entry type (llm_call, command, file_op, error, search, etc.)
- `mode` — Execution mode (chat, coding, fin, cli, unknown)
- All other kwargs added as fields
- All string values sanitized for PII

### PII Sanitizer

#### `class PIISanitizer`

**Constructor:**
```python
PIISanitizer(mode: str = "strict")
```
- `mode="strict"` — Replace all PII with redaction tokens
- `mode="normal"` — Only warn, don't replace

**Methods:**

```python
def sanitize(text: str) -> str
```
Replace PII in text with redaction tokens.

```python
def sanitize_dict(d: Dict[str, Any]) -> Dict[str, Any]
```
Recursively sanitize all string values in a dict.

```python
def detect(text: str) -> List[Tuple[str, str]]
```
Return list of (pii_type, matched_text) found (without redacting).

### Detected PII Types

- **email** — name@example.com pattern
- **phone_us** — (123) 456-7890, +1-123-456-7890, etc.
- **phone_cn** — 1X-XXXX-XXXX, +86-1X-XXXX-XXXX, etc.
- **phone_intl** — +CC-NNN...
- **credit_card** — Visa, Mastercard, Amex, Discover patterns
- **ssn** — XXX-XX-XXXX
- **api_key** — sk_*, key_*, token_*, api_*, secret_*, etc.
- **password_in_url** — user:password@host
- **ipv4** — 192.168.1.1 pattern

### Redaction Tokens

| PII Type | Token |
|----------|-------|
| email | `[REDACTED_EMAIL]` |
| phone_* | `[REDACTED_PHONE]` |
| credit_card | `[REDACTED_CC]` |
| ssn | `[REDACTED_SSN]` |
| api_key | `[REDACTED_KEY]` |
| password_in_url | `[REDACTED_PASSWORD]` |
| ipv4 | `[REDACTED_IP]` |

### Log File Structure

```
~/.neomind/logs/
├── 2024-03-15.jsonl      # Daily rotation, new file each day
├── 2024-03-14.jsonl
├── 2024-03-13.jsonl
└── ...
```

Each line is a complete JSON entry (JSONL format for streaming).

### Pros

- **Daily rotation** — Automatic new file each day
- **Auto PII cleanup** — No manual redaction needed
- **Query interface** — Search logs by type, mode, date
- **Statistics** — Daily/weekly summaries built-in
- **Minimal overhead** — Single logger instance, efficient writes

### Cons

- **JSONL, not structured DB** — Can't do complex SQL queries
- **No log shipping** — Logs stay local, no cloud integration
- **Regex-based PII detection** — Can miss sophisticated patterns
- **No rotation within day** — Single file per day, no size limits
- **No audit trail** — Doesn't log who logged what

### Limitations

1. **Regex-based PII** — May have false positives/negatives
2. **No log retention policy** — Files never auto-deleted
3. **Single file per day** — Large days can have huge files
4. **No structured querying** — Must parse JSONL manually
5. **No real-time streaming** — Logs written after operation

### Typical Integration

```python
# At module init
from agent.logging import get_unified_logger

logger = get_unified_logger()

# In operation
import time
t0 = time.time()
result = some_operation()
duration_ms = (time.time() - t0) * 1000

logger.log(
    "operation_complete",
    mode="coding",
    operation="compile",
    success=result.ok,
    duration_ms=duration_ms
)

# At end of day
stats = logger.get_daily_stats(date.today())
print(f"Today: {stats['total_events']} events, {stats['errors']} errors")
```

---

## Integration Patterns

### Typical Evolution Lifecycle

```
Session Start
├─ scheduler.on_session_start()
│  ├─ Health check
│  ├─ Daily audit (if 24+ hrs)
│  └─ Weekly retro (if 7+ days)
├─ Load vault context (watcher.get_changed_context)
├─ Load shared memory (get_context_summary)
└─ Ready for chat

During Session
├─ Record patterns (shared_memory.record_pattern)
├─ Log operations (unified_logger.log_*)
└─ Every 50 turns: scheduler.on_turn_complete()

Validate Finance Responses (if fin mode)
├─ validator.validate()
├─ If needed: validator.build_disclaimer()
└─ Append to response

Session End
├─ Write journal entry (vault_writer.write_journal_entry)
├─ scheduler.on_session_end()
├─ Promote patterns (promote_patterns)
└─ Close logger

Weekly Retro
├─ Audit logs (unified_logger.get_weekly_stats)
├─ Generate report
├─ Promote patterns (count >= 3)
├─ Write goals (vault_writer.write_goals)
├─ Generate dashboard (evolution_dashboard)
└─ Archive report (vault_writer.write_retro)
```

### Cross-Component Dependencies

```
NeoMind Main Loop
├─ Finance Mode
│  ├─ FinanceResponseValidator (validation)
│  ├─ SharedMemory (patterns)
│  └─ UnifiedLogger (logging)
├─ Vault Sync
│  ├─ VaultWatcher (detect changes)
│  ├─ VaultWriter (write outputs)
│  └─ VaultPromoter (promote patterns)
├─ Web Crawling
│  └─ Crawl4AIAdapter (with fallback)
├─ Evolution
│  ├─ EvolutionScheduler (timing)
│  ├─ SharedMemory (patterns)
│  ├─ VaultWriter (outputs)
│  └─ EvolutionDashboard (metrics)
└─ Skills
   └─ SkillLoader (load skill prompts)
```

---

## Troubleshooting

### Finance Validator

**Issue:** Unverified prices flagged incorrectly
- **Cause:** Price appears without source attribution
- **Fix:** Use VerifiedDataPoint.render() or add `(source: <name>)` suffix

**Issue:** Approximate math detected when actual result from QuantEngine
- **Cause:** Regex found "approximately" keyword
- **Fix:** Remove approximation words, explicitly state "(QuantEngine computed)"

### Vault Watcher

**Issue:** Changes in Obsidian not detected
- **Cause:** Polling interval too long, or mtime rounding
- **Fix:** Call check_for_changes() more frequently, check file permissions

**Issue:** Infinite loop of re-injections
- **Cause:** forget to call mark_seen() after re-injection
- **Fix:** Always call watcher.mark_seen() after get_changed_context()

### Vault Writer

**Issue:** Wikilinks not created
- **Cause:** Entity doesn't match patterns ($TICKER or 6-digit code)
- **Fix:** Use exact ticker format ($AAPL) or check for typos

**Issue:** MEMORY.md has duplicate entries
- **Cause:** Dedup is exact text match
- **Fix:** Use identical wording for same fact

### Shared Memory

**Issue:** Preferences not shared across modes
- **Cause:** Mode isolation in SharedMemory setup
- **Fix:** SharedMemory is shared by design, check set_preference mode param

**Issue:** Patterns not promoted
- **Cause:** Count < 3 threshold
- **Fix:** Record pattern 3+ times before promotion attempt

### Unified Logger

**Issue:** PII not sanitized
- **Cause:** Mode not set to "strict"
- **Fix:** UnifiedLogger creates sanitizer with strict mode by default

**Issue:** Missing logs
- **Cause:** Log file not flushed
- **Fix:** UnifiedLogger auto-flushes after each write

---

## Configuration

All components respect environment variables for overrides:

```bash
# Vault paths
export NEOMIND_VAULT_DIR="/path/to/vault"
export NEOMIND_MEMORY_DIR="/path/to/db"

# Logging
export NEOMIND_LOG_DIR="~/.neomind/logs"

# Crawl4AI
export CRAWL4AI_BROWSER_TYPE="firefox"
export CRAWL4AI_HEADLESS="true"
```

---

## Performance Notes

- **Finance Validator:** O(1) regex checks, <5ms per response
- **Vault Watcher:** O(n) stat calls where n=watched files (3), <10ms
- **Vault Writer:** O(m) where m=entry size, ~50ms including disk I/O
- **Vault Promoter:** O(p) where p=patterns count, ~10ms for typical case
- **Evolution Scheduler:** O(1) checkpoint, actual work delegated to AutoEvolve
- **Crawl4AI Adapter:** Depends on site complexity, 1-60 seconds per page
- **Skill Loader:** O(s) directory scan on load_all(), ~50ms for 30 skills
- **Shared Memory:** O(1) for get/set, O(n) for get_all_patterns(), concurrent safe
- **Unified Logger:** O(1) write, ~1ms per log entry
- **PII Sanitizer:** O(t*r) where t=text length, r=regex patterns (~9), <10ms typical

---

## Version History

| Component | Version | Date | Changes |
|-----------|---------|------|---------|
| Finance Validator | 1.0 | 2024-03-01 | Initial five-rule system |
| Vault Watcher | 1.0 | 2024-03-01 | Polling-based mtime tracking |
| Vault Writer | 1.1 | 2024-03-10 | Added wikification |
| Vault Promoter | 1.0 | 2024-03-05 | Pattern promotion with 3x threshold |
| Evolution Scheduler | 1.0 | 2024-03-08 | Session-based task scheduling |
| Evolution Dashboard | 1.0 | 2024-03-12 | HTML dashboard with Chart.js |
| Crawl4AI Adapter | 1.0 | 2024-03-06 | Async crawling with stealth |
| Skill Loader | 1.0 | 2024-03-03 | SKILL.md parsing |
| Shared Memory | 1.1 | 2024-03-11 | Added WAL mode, thread safety |
| Unified Logger | 1.0 | 2024-03-02 | JSONL logging with PII sanitizer |

---

End of Component Usage Guide
