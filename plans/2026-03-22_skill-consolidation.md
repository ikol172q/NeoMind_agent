# Skill Consolidation — 2026-03-22

## Rationale

After completing gstack Phase 1-5 integration (19 skills), a review identified
redundancies and missing capabilities. This consolidation reduces overlap while
adding genuinely missing personal assistant features.

## Merges Performed

### 1. self-audit + security-audit → `audit` (v2.0.0)
- **Before**: Two separate skills doing audit work — one general quality, one security-focused
- **After**: Single `audit` skill with expanding scope strategy where Cycle 3 = security (mode-specific)
- **Why**: self-audit's scope expansion already covered security in cycle 3; having a separate security-audit was redundant

### 2. office-hours + finance-briefing → `office-hours` (v2.0.0)
- **Before**: Two skills using identical 6-forcing-questions methodology with different terminology
- **After**: Single `office-hours` skill with mode-specific guidance (chat: DECISION DOC, fin: PORTFOLIO DECISION)
- **Why**: Same framework, different output format. One skill with mode awareness is cleaner.

### 3. ship + deploy → `ship` (v2.0.0)
- **Before**: ship = "tag + changelog + PR", deploy = "push + smoke test + monitor"
- **After**: Single `ship` skill with Part A (release prep) and Part B (deploy + monitor)
- **Why**: For personal projects, these are always sequential. No reason to split.

### 4. autoplan simplified (v2.0.0)
- **Before**: Fake multi-agent orchestration (chat → coding → fin "personalities" talking to each other)
- **After**: Single-pass multi-perspective analysis (3 lenses: intent, feasibility, cost/benefit)
- **Why**: NeoMind runs one mode at a time; pretending to be three agents was misleading

## New Skills Added

### 5. `memo` (chat+all modes)
- Quick notes, TODOs, reminders stored in SharedMemory
- Cross-mode: save in chat, recall in coding/fin
- **Why needed**: Personal assistant without note-taking is incomplete

### 6. `digest` (shared)
- Daily/weekly activity summary from evidence trail + logs
- **Why needed**: NeoMind logs everything but had no way to summarize it for the user

### 7. `teach` (shared)
- User explicitly teaches NeoMind facts, preferences, corrections
- Stores to SharedMemory with proper categorization
- **Why needed**: SharedMemory existed but no skill guided the interaction

## Result

| Before | After |
|--------|-------|
| 19 skills | 16 active + 4 deprecated stubs |
| 3 redundant pairs | 0 redundancies |
| 0 personal assistant skills | 3 (memo, digest, teach) |

### Final Skill Inventory (16 active)

**Shared (8):** audit, autoplan, browse, careful, digest, investigate, retro, teach
**Chat (2):** memo, office-hours
**Coding (4):** eng-review, perf, qa, ship
**Finance (4):** backtest, qa-trading, risk, trade-review

Plus neomind-upgrade (shared, for self-evolution).
Total: 17 active skills.
