# NeoMind Component Troubleshooting Guide

**Last Updated:** 2026-03-27
**Scope:** Comprehensive troubleshooting for all NeoMind components implemented in recent sessions

---

## Table of Contents

1. [Finance Response Validator (FRV)](#finance-response-validator)
2. [Vault Watcher (VW)](#vault-watcher)
3. [Vault Writer (VWR)](#vault-writer)
4. [Vault Promoter (VP)](#vault-promoter)
5. [Evolution Scheduler (ES)](#evolution-scheduler)
6. [Evolution Dashboard (ED)](#evolution-dashboard)
7. [Crawl4AI Adapter (CA)](#crawl4ai-adapter)
8. [Skill Loader (SL)](#skill-loader)
9. [Shared Memory (SM)](#shared-memory)
10. [Unified Logger + PII Sanitizer (UL, PII)](#unified-logger--pii-sanitizer)

---

## Finance Response Validator

**Location:** `agent/finance/response_validator.py`

**Purpose:** Enforces the Five Iron Rules for financial correctness in LLM responses.

**Rules Enforced:**
- Rule 1: No financial numbers from LLM memory (must come from tool calls)
- Rule 2: No approximate calculations (must go through QuantEngine)
- Rule 3: Every data point has source + timestamp
- Rule 4: Recommendations need confidence + time horizon + scenarios
- Rule 5: Source conflicts are shown, never silently resolved

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| False positives on price detection | Valid text marked as unverified prices | Regex pattern too broad matching numbers that aren't prices | Add context-aware filters or use PRICE_EXCLUDE_PATTERNS for fees, hypotheticals | FRV-001 |
| Excluded context not working | Prices in code blocks still flagged | Code block protection regex not matching all formats | Ensure `\`\`\`....\`\`\`` protection runs before price patterns | FRV-002 |
| Rule 4 triggering on non-recommendations | Confidence/time horizon warnings on analysis | Pattern matching "confidence" in neutral contexts | Verify recommendation keywords (buy, sell, hold, recommend) present first | FRV-003 |
| Wikilinks in prices marked as suspicious | `$[[AAPL]]` flagged incorrectly | Price patterns match before wikilink unwrapping | Unwrap wikilinks before price validation | FRV-004 |
| Source timestamps not detected | Data marked as unsourced when timestamps present | Timestamp pattern too restrictive (UTC/CST only) | Expand SOURCE_PATTERNS to include ISO 8601, Unix timestamps | FRV-005 |
| Approximate calculation false negatives | "~$50k" and approximations pass validation | Pattern matches missing edge cases | Add patterns for "roughly", "approximately" in all supported languages | FRV-006 |
| Missing disclaimer warnings | Rule 4 doesn't flag missing disclaimers | Disclaimer detection not implemented | Check for legal disclaimers in response; add explicit check | FRV-007 |
| Price regex performance | Validation hangs on large responses | PRICE_PATTERNS compiled at module level but not cached | Cache compiled patterns as class attributes; use set() for lookups | FRV-008 |
| Chinese number detection fails | "1000元" not flagged as financial amount | Pattern only matches ASCII symbols | Add pattern for Chinese currency symbols (¥, 元, 块) | FRV-009 |
| Duplicate warnings in summary | Same issue listed twice in validation result | summary() method not deduping warnings list | Check warnings list for duplicates before appending | FRV-010 |

### Debug Steps

1. **Enable verbose logging:**
   ```python
   import logging
   logging.getLogger("neomind.finance").setLevel(logging.DEBUG)
   validator = FinanceResponseValidator()
   result = validator.validate(response)
   print(result.summary())
   ```

2. **Test price pattern matching:**
   ```python
   from agent.finance.response_validator import PRICE_PATTERNS
   text = "Apple stock is trading at $195.42"
   for pattern in PRICE_PATTERNS:
       if pattern.search(text):
           print(f"Matched: {pattern.pattern}")
   ```

3. **Check excluded context:**
   ```python
   # Verify PRICE_EXCLUDE_PATTERNS is applied
   # before price detection in validate()
   ```

---

## Vault Watcher

**Location:** `agent/vault/watcher.py`

**Purpose:** Polling-based mtime detection for Obsidian vault file changes.

**Tracked Files:**
- MEMORY.md
- current-goals.md
- SOUL.md

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| Changes not detected | User edits in Obsidian not reflected in system prompt | mtime granularity (filesystem clock resolution ~1s) | Use higher-resolution time checks; compare file content hash as fallback | VW-001 |
| File permission errors | OSError when calling os.stat() on vault files | Vault directory permissions restrictive or vault deleted | Check vault_dir exists and is readable; wrap stat() in try/except | VW-002 |
| Stale mtimes after crash | Changes detected even though files unchanged (false positives) | mtime persisted in _stored_mtimes not cleared on restart | Call _update_stored_mtimes() explicitly on init or session start | VW-003 |
| Watched file doesn't exist | _stored_mtimes[filename] = None but check_for_changes() breaks | File created after watcher init not registered | Check all WATCHED_FILES exist before init; lazy-load mtimes per file | VW-004 |
| get_changed_context() returns None unexpectedly | Vault content changed but method returns nothing | VaultReader.get_section() failed silently | Verify VaultReader instance; check file encoding (UTF-8) | VW-005 |

### Debug Steps

1. **Check current mtimes:**
   ```python
   from agent.vault.watcher import VaultWatcher
   watcher = VaultWatcher(vault_dir="/path/to/vault")
   print(watcher._stored_mtimes)
   ```

2. **Force file check:**
   ```python
   import os
   filepath = Path("/data/vault/MEMORY.md")
   print(f"mtime: {os.path.getmtime(filepath)}")
   print(f"Stored: {watcher._stored_mtimes.get('MEMORY.md')}")
   ```

3. **Test change detection loop:**
   ```python
   # Edit file in Obsidian, then:
   changed = watcher.check_for_changes()
   print(f"Changed: {changed}")
   ```

---

## Vault Writer

**Location:** `agent/vault/writer.py`

**Purpose:** Structured markdown writing with wikilinks, journal entries, and memory appends.

**Key Features:**
- Automatic wikification of stock tickers and Chinese stock codes
- YAML frontmatter for Obsidian Databases
- Code block protection (no transformation inside \`\`\`)
- Wikilink deduplication

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| Wikilinks double-wrapping | `[[[$AAPL]]]` instead of `[[$AAPL]]` | _wikify() called twice on same text | Ensure wikification happens once per write; add guard flag | VWR-001 |
| Frontmatter parsing | YAML frontmatter syntax invalid or missing | datetime.now() output not ISO 8601 or quotes missing | Use datetime.isoformat() with timezone; validate YAML before write | VWR-002 |
| Code block protection fails | Stock tickers inside \`\`\`code\`\`\` converted to wikilinks | Code block preservation regex not matching all delimiters | Ensure `r"```[\s\S]*?```"` uses DOTALL mode; test edge cases | VWR-003 |
| Wikilink dedup not working | Duplicate `[[$AAPL]]` entries in same file | dedup logic only checks within current append, not whole file | Read file before append; deduplicate against existing content | VWR-004 |
| Chinese stock codes not wikified | "600519" not converted to "[[600519]]" | Pattern requires exactly 6 digits but validation skips short codes | Check pattern `r"^\d{6}$"`; remove leading zero requirement if flexible | VWR-005 |
| Append to non-existent section | ValueError when appending to section that doesn't exist | append_to_memory() assumes section exists | Create section if missing; use safe append with section generation | VWR-006 |
| COMMON_WORDS filtering broken | "THE", "AND" still wikified despite COMMON_WORDS set | Word filtering case-sensitive or applied after wikification | Apply case-insensitive check before wiki pattern match | VWR-007 |
| File write permission denied | OSError on write to vault file | Vault directory not writable or file locked | Check permissions with `ls -l`; close Obsidian if vault locked | VWR-008 |

### Debug Steps

1. **Test wikification:**
   ```python
   from agent.vault.writer import VaultWriter
   writer = VaultWriter()
   text = "I bought $AAPL and 600519 shares"
   result = writer._wikify(text)
   print(result)  # Should be: "I bought [[$AAPL]] and [[600519]] shares"
   ```

2. **Check code block protection:**
   ```python
   text = "```python\nprice = $100\n```\nBuy $AAPL"
   result = writer._wikify(text)
   # $100 should NOT be wikified; $AAPL should be
   ```

3. **Verify frontmatter format:**
   ```python
   from datetime import datetime
   fm = f"---\ncreated: {datetime.now().isoformat()}\n---"
   print(fm)  # Verify valid YAML
   ```

---

## Vault Promoter

**Location:** `agent/vault/promoter.py`

**Purpose:** Promotion of validated behavioral patterns from SharedMemory to MEMORY.md.

**Promotion Logic:**
- Pattern count must be >= 3 (PROMOTION_THRESHOLD)
- Mapped to MEMORY.md sections via SECTION_MAP
- Prevents hallucinated or one-off observations from becoming long-term memory

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| Promotion threshold not met | Patterns with count=2 not promoted | PROMOTION_THRESHOLD = 3 is strict | Lower threshold if patterns are reliable; check count tracking | VP-001 |
| Section mapping wrong | Pattern promoted to "Other Patterns" when custom section exists | pattern_type not in SECTION_MAP | Add pattern_type to SECTION_MAP or use generic catch-all | VP-002 |
| SharedMemory read failures | Exception when calling get_all_patterns() | SharedMemory DB locked or query syntax error | Check DB file exists and is readable; verify SQL schema | VP-003 |
| Promoted patterns not in MEMORY.md | promote_patterns() returns count > 0 but MEMORY.md unchanged | append_to_memory() failed silently | Add exception handling; verify vault_writer instance | VP-004 |
| Duplicate promoted entries | Same pattern appears twice in MEMORY.md | Dedup logic in VaultWriter not working or patterns table has duplicates | Clear duplicates from SharedMemory; ensure append_to_memory() dedupes | VP-005 |

### Debug Steps

1. **Check patterns in SharedMemory:**
   ```python
   from agent.memory.shared_memory import SharedMemory
   memory = SharedMemory()
   patterns = memory.get_all_patterns()
   for p in patterns:
       print(f"{p['pattern_type']}: {p['pattern_value']} (count={p['count']})")
   ```

2. **Test promotion:**
   ```python
   from agent.vault.promoter import promote_patterns
   from agent.vault.writer import VaultWriter
   count = promote_patterns(memory, VaultWriter())
   print(f"Promoted {count} patterns")
   ```

3. **Verify section mapping:**
   ```python
   from agent.vault.promoter import SECTION_MAP
   print(SECTION_MAP)  # Check all pattern_types are mapped
   ```

---

## Evolution Scheduler

**Location:** `agent/evolution/scheduler.py`

**Purpose:** Session-based scheduling for auto-evolution tasks (health check, daily audit, weekly retro).

**Lifecycle Hooks:**
- `on_session_start()`: Runs health check + daily/weekly if due
- `on_turn_complete(turn_number)`: Every 50 turns, check daily audit
- `on_session_end()`: Final daily audit + pattern promotion

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| Duplicate runs in session | Health check or daily audit runs twice | daily_ran_this_session guard not set or reset incorrectly | Set guard to True immediately after run; don't reset in session | ES-001 |
| Timing issues (24h threshold) | Daily audit runs on session 2 even if 20 hours since last | Time comparison logic compares timestamps incorrectly | Use datetime.now(timezone.utc) for all comparisons; store UTC timestamps | ES-002 |
| Guard flags not reset | Weekly runs lock up; guard persists across sessions | Guard flags _daily_ran_this_session not cleared on new session | Reset guards in __init__; don't persist in state file | ES-003 |
| AutoEvolve instance None | AttributeError: NoneType has no attribute run_startup_check | scheduler initialized without AutoEvolve | Pass AutoEvolve instance; check it's not None before calling | ES-004 |
| Tasks blocked by exceptions | Evolution stops silently; actions_taken incomplete | Exception handling too broad (bare except) or swallowed | Log all exceptions; use try/except per task, not wrap whole method | ES-005 |

### Debug Steps

1. **Check guard state:**
   ```python
   from agent.evolution.scheduler import EvolutionScheduler
   scheduler = EvolutionScheduler(auto_evolve)
   print(f"Daily ran: {scheduler.daily_ran_this_session}")
   print(f"Weekly ran: {scheduler.weekly_ran_this_session}")
   ```

2. **Trace execution:**
   ```python
   actions = scheduler.on_session_start()
   for action in actions:
       print(f"  - {action}")
   ```

3. **Check turn-based triggers:**
   ```python
   scheduler.on_turn_complete(50)   # Should trigger check
   scheduler.on_turn_complete(25)   # Should not trigger
   ```

---

## Evolution Dashboard

**Location:** `agent/evolution/dashboard.py`

**Purpose:** HTML dashboard generation from evolution, logging, and evidence data.

**Data Sources:**
- AutoEvolve state (health, timeline, learning log)
- UnifiedLogger (LLM calls, commands, errors)
- SharedMemory patterns (top patterns by count)
- Evidence DB (if available)

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| Missing data sources | Dashboard shows empty sections | AutoEvolve import fails or state file missing | Verify agent/evolution/auto_evolve.py exists; check state path | ED-001 |
| Malformed HTML | Dashboard renders broken or styled incorrectly | Template literals missing closing tags or quote mismatches | Validate HTML in generated file; check Chart.js script tags | ED-002 |
| Chart.js loading failures | Charts don't render; "Chart is not defined" in console | CDN link broken or blocked by CORS | Use local Chart.js library or different CDN URL | ED-003 |
| Learning log data missing | Learning log section empty | learning_log file doesn't exist or last 20 lines empty | Check learnings are being recorded; handle missing file gracefully | ED-004 |
| Pattern query errors | Patterns section fails with SQL error | Schema mismatch or patterns table doesn't exist | Verify SharedMemory schema; handle missing table | ED-005 |

### Debug Steps

1. **Test data collection:**
   ```python
   from agent.evolution.dashboard import collect_metrics
   metrics = collect_metrics()
   print(f"Health: {metrics['health']}")
   print(f"Patterns: {len(metrics['patterns'])} found")
   ```

2. **Generate and validate HTML:**
   ```python
   from agent.evolution.dashboard import generate_dashboard
   html = generate_dashboard()
   # Save to file and check for syntax errors
   with open("/tmp/dashboard.html", "w") as f:
       f.write(html)
   ```

3. **Check Chart.js availability:**
   ```python
   # Verify CDN URL is reachable
   # Or use local library path
   ```

---

## Crawl4AI Adapter

**Location:** `agent/web/crawl4ai_adapter.py`

**Purpose:** Async crawling with fallback to BFSCrawler.

**Features:**
- AsyncWebCrawler wrapping for JS rendering
- playwright-stealth mode for detection avoidance
- Domain filtering and politeness delays
- Graceful fallback if crawl4ai not installed

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| crawl4ai not installed | ImportError on crawl() or fallback to BFSCrawler | crawl4ai not in environment | Install: `pip install crawl4ai` or `pip install 'neomind[web]'` | CA-001 |
| Stealth mode failures | Bot detection triggers despite use_stealth=True | playwright-stealth not installed or Playwright version mismatch | Install: `pip install playwright-stealth`; verify Playwright version | CA-002 |
| Domain filtering not working | Crawler visits blocked domains | Domain filter logic missing or regex incorrect | Add domain whitelist/blacklist to crawl() method | CA-003 |
| Browser crashes in headless mode | Crashes on large pages or rapid crawls | Memory exhaustion or browser process limits | Use headless=False for debugging; add page timeout/resource limits | CA-004 |
| Fallback to BFSCrawler not working | Tries to use AsyncWebCrawler even when not installed | HAS_CRAWL4AI flag set incorrectly | Verify ImportError caught; check try/except block | CA-005 |

### Debug Steps

1. **Check crawl4ai availability:**
   ```python
   from agent.web.crawl4ai_adapter import HAS_CRAWL4AI, HAS_STEALTH
   print(f"crawl4ai: {HAS_CRAWL4AI}")
   print(f"stealth: {HAS_STEALTH}")
   ```

2. **Test crawl with fallback:**
   ```python
   import asyncio
   from agent.web.crawl4ai_adapter import Crawl4AIAdapter

   adapter = Crawl4AIAdapter()
   report = asyncio.run(adapter.crawl("https://example.com"))
   print(f"Status: {report.status}")
   ```

3. **Enable browser debugging:**
   ```python
   adapter = Crawl4AIAdapter(headless=False)
   # Watch browser window during crawl
   ```

---

## Skill Loader

**Location:** `agent/skills/loader.py`

**Purpose:** Parsing SKILL.md files and registry management.

**SKILL.md Format:**
```
---
name: office-hours
description: Deep requirement mining
modes: [chat, coding, fin]
allowed-tools: [Bash, Read, WebSearch]
version: 1.0.0
---

# Office Hours
(prompt body in markdown)
```

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| YAML parse errors | yaml.YAMLError on load_all() | Frontmatter syntax invalid (tabs, improper quotes) | Check frontmatter is valid YAML; use YAML validator | SL-001 |
| Missing frontmatter | Skill name = "" or body = entire file | No `---` delimiters or malformed split | Ensure file starts with `---`; split on first `---` pair | SL-002 |
| Mode filtering wrong | Skill not available in expected mode | modes list in frontmatter doesn't include the mode | Verify modes: [chat, coding, fin]; check filtering logic | SL-003 |
| Body parsing includes frontmatter | Skill body starts with "---" or YAML | Regex split not removing frontmatter correctly | Use proper frontmatter extraction; split on `---` three times | SL-004 |
| Registry lookup fails | get("office-hours") returns None despite file exists | Skills directory not scanned or name mismatch | Call load_all() first; verify skill name matches filename | SL-005 |

### Debug Steps

1. **Check SKILL.md parsing:**
   ```python
   from agent.skills.loader import SkillLoader
   loader = SkillLoader()
   loader.load_all()

   skill = loader.get("office-hours")
   print(f"Skill: {skill}")
   print(f"Modes: {skill.modes}")
   print(f"Body length: {len(skill.body)}")
   ```

2. **Validate YAML frontmatter:**
   ```python
   import yaml
   with open("/path/to/SKILL.md") as f:
       content = f.read()
       frontmatter = content.split("---")[1]
       try:
           yaml.safe_load(frontmatter)
           print("YAML valid")
       except yaml.YAMLError as e:
           print(f"YAML error: {e}")
   ```

3. **Test mode filtering:**
   ```python
   fin_skills = loader.get_skills_for_mode("fin")
   print(f"Finance skills: {[s.name for s in fin_skills]}")
   ```

---

## Shared Memory

**Location:** `agent/memory/shared_memory.py`

**Purpose:** SQLite-backed cross-personality memory (chat/coding/fin).

**Storage Model:**
- Preferences: user-level settings (timezone, language, name)
- Facts: semantic knowledge (work, education, interests)
- Patterns: behavioral patterns (frequent stocks, coding languages)
- Feedback: user corrections and preferences

**Features:**
- WAL mode for concurrent access
- Atomic writes for data integrity
- Thread-safe with locks
- Cross-mode visibility

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| DB locked error | sqlite3.OperationalError: database is locked | WAL mode not enabled or multiple writers without locks | Enable WAL mode on init; use locks for writes | SM-001 |
| Schema migration | Columns missing or table structure wrong | Schema defined but not executed on init | Call _init_schema() in __init__; check SCHEMA dict | SM-002 |
| WAL mode issues | .db-shm or .db-wal files growing large | WAL checkpoints not happening | Add checkpoint calls; clear old WAL files manually | SM-003 |
| Thread safety | Concurrent writes corrupt DB | No locking between threads | Use threading.Lock(); wrap writes in lock context | SM-004 |
| Data loss after crash | Entries lost; DB partially written | No PRAGMA commit or transactions incomplete | Use explicit BEGIN/COMMIT; add integrity checks | SM-005 |
| Query performance | Lookups slow on large patterns table | No indexes on frequently queried columns | Add indexes: CREATE INDEX idx_pattern_type ON patterns(pattern_type) | SM-006 |
| Encoding issues | Unicode characters stored as mojibake | Wrong encoding on connection or insert | Use utf-8 encoding; verify with .decode('utf-8') | SM-007 |
| Stale connections | Connection reuse fails after idle period | Connection not closed/reopened or timeout | Close connection after each operation; use context manager | SM-008 |

### Debug Steps

1. **Check database health:**
   ```python
   from agent.memory.shared_memory import SharedMemory
   memory = SharedMemory()

   # Test write/read
   memory.set_preference("test_key", "test_value", "chat")
   value = memory.get_preference("test_key")
   print(f"Read back: {value}")
   ```

2. **Check WAL mode:**
   ```python
   import sqlite3
   conn = sqlite3.connect(memory.db_path)
   cursor = conn.cursor()
   cursor.execute("PRAGMA journal_mode")
   mode = cursor.fetchone()[0]
   print(f"Journal mode: {mode}")  # Should be "wal"
   ```

3. **Verify schema:**
   ```python
   cursor.execute(
       "SELECT name FROM sqlite_master WHERE type='table'"
   )
   tables = cursor.fetchall()
   print(f"Tables: {tables}")  # Should have preferences, facts, patterns, feedback
   ```

4. **Test pattern recording:**
   ```python
   memory.record_pattern("frequent_stock", "AAPL", "fin")
   memory.record_pattern("frequent_stock", "AAPL", "fin")
   memory.record_pattern("frequent_stock", "AAPL", "fin")

   patterns = memory.get_all_patterns()
   aapl = [p for p in patterns if p["pattern_value"] == "AAPL"][0]
   print(f"AAPL count: {aapl['count']}")  # Should be 3
   ```

---

## Unified Logger + PII Sanitizer

**Location:** `agent/logging/unified_logger.py`, `agent/logging/pii_sanitizer.py`

**Purpose:** JSONL logging with automatic PII redaction.

**Log Types:**
- llm_call: model, tokens, latency
- command: exit_code, duration
- file_op: size, operation type
- error: type, message, traceback
- search: query, result count

**PII Types Detected:**
- Email addresses
- Phone numbers (US, CN, international)
- Credit card numbers
- SSN / ID numbers
- API keys
- Passwords in URLs
- IP addresses (optional)

### Common Issues

| Issue | Symptoms | Root Cause | Fix | Error Code |
|-------|----------|-----------|-----|-----------|
| Log rotation | Old logs never deleted | Daily rotation implemented but cleanup missing | Add cleanup of logs older than 30 days | UL-001 |
| False PII detection | Valid text redacted (e.g., "2001-01-01" as SSN) | SSN regex too permissive (\d{3}-\d{2}-\d{4}) | Tighten pattern to require dashes in specific places | PII-001 |
| Email not redacted | user@example.com appears in logs | Email pattern missing or disabled | Verify email regex in PATTERNS; ensure sanitize() applied | PII-002 |
| Query performance | Log searches slow on large files | No indexing or inefficient line parsing | Use sqlite3 for logs instead of JSONL; add indexes | UL-002 |
| Disk space issues | Log directory grows unbounded | Log rotation disabled or frequency too low | Set max log size or daily rotation; archive old logs | UL-003 |
| API key redaction misses | Tokens like "sk_live_123abc" not redacted | api_key pattern incomplete | Expand pattern to cover more token formats | PII-003 |

### Debug Steps

1. **Test PII sanitization:**
   ```python
   from agent.logging.pii_sanitizer import PIISanitizer
   sanitizer = PIISanitizer(mode="strict")

   text = "Call me at 555-123-4567 or email@example.com"
   redacted = sanitizer.sanitize(text)
   print(redacted)  # Should be "Call me at [REDACTED_PHONE] or [REDACTED_EMAIL]"
   ```

2. **Test pattern matching:**
   ```python
   patterns = sanitizer.PATTERNS
   test_email = "john.doe@company.com"
   if patterns['email'].search(test_email):
       print("Email detected")

   test_ssn = "123-45-6789"
   if patterns['ssn'].search(test_ssn):
       print("SSN detected")
   ```

3. **Check logging:**
   ```python
   from agent.logging.unified_logger import UnifiedLogger
   logger = UnifiedLogger()

   logger.log_llm_call(
       model="claude-3-sonnet",
       prompt_tokens=100,
       completion_tokens=50,
       latency_ms=500.0,
       mode="chat"
   )

   # Check log file
   import json
   with open(logger.log_dir / logger._get_filename(), "r") as f:
       for line in f:
           entry = json.loads(line)
           print(f"{entry['ts']}: {entry['type']}")
   ```

4. **Verify no PII in logs:**
   ```python
   # After logging operations, scan logs for sensitive patterns
   logger.log("test", mode="chat", email="user@example.com")

   log_file = logger.log_dir / logger._get_filename()
   with open(log_file, "r") as f:
       content = f.read()
       if "user@example.com" in content:
           print("WARNING: PII not sanitized!")
       else:
           print("PII sanitized correctly")
   ```

---

## General Troubleshooting Workflow

### 1. Identify Component

Use error code prefix (FRV-, VW-, VWR-, VP-, ES-, ED-, CA-, SL-, SM-, UL-, PII-) to locate component section.

### 2. Check Prerequisites

- Verify vault directory exists and is readable
- Confirm dependencies installed (crawl4ai, playwright, etc.)
- Check database files exist and are writable
- Validate YAML/JSON syntax if applicable

### 3. Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("neomind")
logger.setLevel(logging.DEBUG)
```

### 4. Run Component Tests

```bash
# From repo root
pytest tests/test_<component>_full.py -v
pytest tests/test_<component>.py -v
```

### 5. Check Related Components

- Vault components may fail if VaultReader unavailable
- Promoter depends on SharedMemory and VaultWriter
- Scheduler depends on AutoEvolve
- Dashboard depends on multiple data sources

### 6. Validate Configuration

- Check vault_dir in _config.py
- Verify NEOMIND_* environment variables set
- Confirm API credentials for finance tools
- Check browser/playwright installation

### 7. Monitor Logs

```bash
# Watch live logs
tail -f ~/.neomind/logs/$(date +%Y-%m-%d).jsonl | jq .

# Search for errors
grep "error\|Error\|ERROR" ~/.neomind/logs/*.jsonl
```

---

## Error Code Reference

| Prefix | Component |
|--------|-----------|
| FRV-001-010 | Finance Response Validator |
| VW-001-005 | Vault Watcher |
| VWR-001-008 | Vault Writer |
| VP-001-005 | Vault Promoter |
| ES-001-005 | Evolution Scheduler |
| ED-001-005 | Evolution Dashboard |
| CA-001-005 | Crawl4AI Adapter |
| SL-001-005 | Skill Loader |
| SM-001-008 | Shared Memory |
| UL-001-003 | Unified Logger |
| PII-001-003 | PII Sanitizer |

---

## Contact & Escalation

For unresolved issues:

1. Check `agent/core.py` for integration points
2. Review test files for expected behavior
3. Check recent session logs in `.neomind/logs/`
4. Verify component versions in `requirements.txt`
5. Review `plans/FINANCE_CORRECTNESS_RULES.md` for finance-specific rules
6. See `plans/OBSIDIAN_TROUBLESHOOTING.md` for vault-specific issues
