# Phase 4: Quick Start Guide

## What Just Happened?

NeoMind now has **self-evolution** — it learns and improves automatically.

## Key Files Created

| File | Purpose |
|------|---------|
| `agent/evolution/auto_evolve.py` | Self-evolution engine (1,100 LOC) |
| `agent/evolution/upgrade.py` | Safe upgrade system (300 LOC) |
| `tests/test_evolution.py` | 52 comprehensive tests (1,200 LOC) |
| `PHASE4_EVOLUTION.md` | Full documentation |

## Core Capabilities

### 1. Startup Health Check (< 2 seconds)
```python
from agent.evolution import AutoEvolve

evolve = AutoEvolve()
health = evolve.run_startup_check()
# Checks: configs load, databases intact, disk space OK
```

### 2. Daily Audit (analyzes yesterday)
```python
daily_report = evolve.run_daily_audit()
# Counts calls, detects errors, finds patterns
```

### 3. Weekly Retrospective (full analysis)
```python
weekly_report = evolve.run_weekly_retro()
# Generates improvement targets, saves retro-YYYY-MM-DD.md
```

### 4. Learn from Feedback (real-time)
```python
evolve.learn_from_feedback(
    feedback_type="complaint",
    content="Response too long",  # or "太长了"
    mode="chat"
)
# Detects preferences, stores in SQLite
```

### 5. Learn from Conversations (real-time)
```python
evolve.learn_from_conversation(
    user_msg="What stocks should I buy?",
    bot_response="Based on...",
    mode="fin"
)
# Detects language, topics, timezone, interests
```

### 6. Safe Upgrades
```python
upgrade = NeoMindUpgrade()
has_updates, version = upgrade.check_for_updates()
if has_updates:
    success, msg = upgrade.upgrade(confirmed=True)
    # Backup → Pull → Verify → Rollback if error
```

## Commands

```bash
# Evolution status
/evolve status           # Overall status
/evolve daily            # Run daily audit
/evolve weekly           # Run weekly retro
/evolve health           # Health check

# Update management
/upgrade check           # Check for updates
/upgrade changelog       # Show what changed
/upgrade perform --confirm  # Install updates
/upgrade history         # Show upgrade history
```

## How It Learns (Pattern Matching Only)

**No LLM calls** — uses simple regex and keyword matching:

```python
# Detects "too long" feedback
if "太长" in content or "too long" in content.lower():
    set_preference("max_tokens", "4096")

# Detects language
if re.search(r"[\u4e00-\u9fff]", user_msg):  # Chinese
    set_preference("language", "zh")

# Detects timezone
if "Shanghai" in text:
    set_preference("timezone", "Asia/Shanghai")

# Detects topics
if re.search(r"stock|trading|portfolio", text):
    record_pattern("topic", "finance")
```

## Storage

All data stored at: `~/.neomind/evolution/`

```
evolution/
├── evolution_state.json      # Overall state
├── feedback.db               # SQLite: preferences, patterns
├── learning.jsonl            # Append-only learning log
├── retro-2026-03-22.md      # Weekly retrospective
└── retro-2026-03-29.md
```

## Testing (52 Tests, All Pass)

```bash
python -m pytest tests/test_evolution.py -v
# 52 passed in 0.93s ✓
```

Test coverage:
- Health checks
- Daily/weekly audits
- Learning from feedback (7 specific tests)
- Learning from conversations (5 specific tests)
- Scheduling logic (6 tests)
- State persistence
- Safe upgrades
- Full integration sequences

## Integration with Core

Already wired into `agent/core.py`:

```python
# Initialization
try:
    self.evolution = AutoEvolve()
    health = self.evolution.run_startup_check()
except Exception:
    self.evolution = None  # Graceful degradation

# Commands
"/evolve": (self.handle_evolve_command, True),
"/upgrade": (self.handle_upgrade_command, True),
```

## Design Principles

✅ **Zero external dependencies** (stdlib only)
✅ **Fast startup** (health check < 2s)
✅ **Never crashes** (all errors gracefully handled)
✅ **Atomic writes** (no corruption)
✅ **Pattern matching only** (no LLM calls, no costs)
✅ **Works in Docker** (no file system assumptions)

## Example: User Correction Flow

```
User: "That response was too long"
↓
Agent: evolve.learn_from_feedback("complaint", "too long", "chat")
↓
Engine: Detects regex match for "too long"
↓
Store: UPDATE preferences SET value='4096' WHERE key='max_tokens'
↓
Next response: Agent uses shorter max_tokens automatically
```

## What Makes NeoMind Different

Unlike static chatbots:

| Aspect | Static Bot | NeoMind |
|--------|-----------|---------|
| Learns | ❌ No | ✅ Yes (from feedback & patterns) |
| Adapts | ❌ No | ✅ Yes (auto-adjusts preferences) |
| Improves | ❌ No | ✅ Yes (weekly retros) |
| Updates | ❌ Manual | ✅ Safe auto-upgrades |
| Self-aware | ❌ No | ✅ Yes (audits itself) |

## Next Steps

1. Test it: `python -m pytest tests/test_evolution.py -v`
2. Try it: `/evolve status` in chat
3. Learn more: Read `PHASE4_EVOLUTION.md`
4. Schedule: Set up cron jobs for daily/weekly runs (optional)
5. Enhance: Add LLM-generated improvement suggestions (future)

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────┐
│                   NeoMind Agent                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  On Start              During Use         Scheduled │
│  ───────────────────   ──────────────────  ────────│
│  ├─ Health Check       ├─ Conversations   ├─ Daily  │
│  ├─ Load State         ├─ Feedback        ├─ Weekly │
│  └─ Init DB            └─ Pattern Match   └─ Retro  │
│                                                     │
├─────────────────────────────────────────────────────┤
│     AutoEvolve Engine (agent/evolution/...)        │
│                                                     │
│  ├─ run_startup_check()    [Health]                │
│  ├─ run_daily_audit()      [Analyze]               │
│  ├─ run_weekly_retro()     [Improve]               │
│  ├─ learn_from_feedback()  [Adapt]                 │
│  ├─ learn_from_conversation() [Learn]              │
│  └─ get_evolution_summary() [Report]               │
│                                                     │
├─────────────────────────────────────────────────────┤
│  Storage (~/. neomind/evolution/)                  │
│                                                     │
│  ├─ evolution_state.json   [State]                 │
│  ├─ feedback.db            [SQLite]                │
│  ├─ learning.jsonl         [Log]                   │
│  └─ retro-*.md             [Reports]               │
└─────────────────────────────────────────────────────┘
```

## Questions?

See `PHASE4_EVOLUTION.md` for detailed documentation.

Enjoy NeoMind's self-improvement! 🚀
