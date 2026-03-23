# NeoMind × Obsidian Vault Integration — Tracker & Plan

> **Date:** 2026-03-22
> **Status:** IMPLEMENTED — Phase 1-4 complete, tested in Docker, verified 2026-03-22
> **Author:** NeoMind + Irene (deep research session, ~35 web searches)
> **Priority:** P1 — closes the self-improvement loop, NeoMind's #1 architectural gap

---

## WHY WE ARE DOING THIS

### The Problem (read this first, future NeoMind)

NeoMind has a sophisticated self-evolution engine (`auto_evolve.py`, 738 lines) that:
- Runs daily audits and weekly retrospectives
- Generates 3 concrete improvement targets per week
- Stores user feedback, preferences, patterns, and facts in SQLite
- Logs every action to an evidence trail (append-only JSONL)

**But the loop is BROKEN at the last mile.** Here's the evidence:

1. `auto_evolve.py` line 420 writes `retro-{date}.md` to `~/.neomind/evolution/`
2. **Nobody reads it back.** Next session starts fresh.
3. `learn_from_feedback()` stores preferences in `feedback.db`
4. `core.py` line 320 only injects `agent_config.system_prompt` at startup
5. **Never queries SharedMemory or evolution state** for learned preferences
6. Result: NeoMind learns, writes it down, then forgets everything next session

### The Solution

A **markdown vault** that NeoMind writes to AND reads from, creating a closed-loop self-improvement cycle. Obsidian (free, on Irene's Mac) serves as the human-readable viewer for this vault.

### Why Obsidian Specifically (not just plain markdown)

We researched extensively. Four **built-in core features** (no plugins needed) provide irreplaceable value to Irene as the human operator:

| Feature | What it does for Irene | Plugin required? |
|---------|----------------------|-----------------|
| **Graph View** | Visualizes connections between trading patterns, coding lessons, user feedback. Reveals patterns NeoMind made that Irene didn't explicitly ask for | No — core |
| **Bases** (v1.9.10+) | Turns YAML frontmatter into queryable/sortable/filterable tables. Instant dashboard of all trading sessions, error rates, tool usage | No — core |
| **Indexed Search** | Instant full-text search over entire vault with context snippets. "What did NeoMind say about Tesla last month?" — one keystroke | No — core |
| **Backlinks** | Shows all files that reference a given note. If NeoMind mentions "earnings volatility" in 5 journal entries, Obsidian surfaces all 5 | No — core |

NeoMind itself doesn't depend on Obsidian at all — it reads/writes standard `.md` files. Obsidian is Irene's window into NeoMind's brain.

---

## RESEARCH SUMMARY

### 35 Searches Conducted — Key Findings

#### Security (Irene's #1 concern: "100% secure")

| Finding | Source | Implication |
|---------|--------|-------------|
| Obsidian collects zero telemetry | [Obsidian Privacy Policy](https://obsidian.md/privacy) | Safe to use |
| Cure53 security audit passed | [Obsidian Security](https://obsidian.md/security) | Professionally vetted |
| CVE-2023-2110: Local file disclosure via crafted markdown | [STAR Labs Advisory](https://starlabs.sg/advisories/23/23-2110/) | Mitigated: NeoMind writes the files, no untrusted input |
| 2026 RCE via malicious links | [Obsidian Forum](https://forum.obsidian.md/t/rce-found-similar-to-cve-2026-20841-in-obsidian/111160) | Mitigated: no untrusted files enter the vault |
| Community plugins have UNRESTRICTED access to filesystem | [Plugin Security](https://help.obsidian.md/plugin-security) | **Critical: use Restricted Mode, ZERO plugins** |
| CVE-2025-53109: MCP path traversal via symlinks | [SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2025-53109/) | **Critical: do NOT use MCP server** |
| Obsidian has no built-in air-gap mode | [Forum Discussion](https://forum.obsidian.md/t/after-disabled-auto-update-application-still-connects-to-github-at-startup-update-check-plugins/50435) | Must block network via macOS firewall or Little Snitch |

**Decision:** Restricted Mode + network blocked + no MCP server + no plugins = maximum security

#### Cost (Irene's #2 concern: "don't want to pay too much")

| Item | Cost | Needed? |
|------|------|---------|
| Obsidian app | $0 (free, including commercial) | Yes |
| Obsidian Sync | $4-5/mo | **No** — Docker volume mount replaces this |
| Obsidian Publish | $8-10/mo | **No** — not publishing notes |
| Commercial license | $0 (optional since Feb 2025) | No |
| memsearch (future) | $0 (open source) | Later, when vault > 500 files |

**Decision:** $0 total, permanently

#### Tax/Legal (Irene's #3 concern: "no tax/law issues")

| Finding | Source | Implication |
|---------|--------|-------------|
| IRS requires cost basis records for 6+ years | [IRS Pub 550](https://www.irs.gov/publications/p550) | Git-versioned vault satisfies this |
| SEC/FINRA WORM rules only apply to registered broker-dealers | [FINRA Rules](https://www.finra.org/rules-guidance/key-topics/books-records) | Not applicable to personal investors |
| Electronic records in any format are acceptable for individuals | [IRS Topic 429](https://www.irs.gov/taxtopics/tc429) | Markdown + git is legally sound |
| Git provides cryptographic audit trail (SHA hashes) | [Kosli Blog](https://www.kosli.com/blog/using-git-for-a-compliance-audit-trail/) | Better than most record-keeping |
| Obsidian EULA: you own your data, Obsidian has no IP claims | [Obsidian ToS](https://obsidian.md/terms) | Full data ownership confirmed |

**Decision:** No tax/legal issues for personal investor use

#### Vendor Lock-in (long-term concern)

| Finding | Source | Implication |
|---------|--------|-------------|
| Files are plain Markdown with YAML frontmatter | [Obsidian Forum](https://forum.obsidian.md/t/are-we-moving-away-from-portability-how-much-is-obsidian-locking-our-notes-in/19329) | Zero lock-in for core content |
| `[[wikilinks]]` are the only Obsidian-specific syntax | Same thread | Simple regex converts to standard links |
| NeoMind never imports or depends on Obsidian | Our architecture | NeoMind works identically without Obsidian |
| Obsidian: $2M ARR, 18 employees, ~$300M valuation | [Latka](https://getlatka.com/companies/obsidian.md) | Sustainable indie company, not going away |

**Decision:** Zero lock-in. If Obsidian vanishes, we still have a folder of .md files

#### Self-Improvement Patterns (making NeoMind better)

| Pattern | Source | Adopted? |
|---------|--------|----------|
| SOUL.md + MEMORY.md dual-layer architecture | [OpenClaw Memory](https://docs.openclaw.ai/concepts/memory) | Yes — MEMORY.md for curated knowledge |
| Daily journal with YAML frontmatter | [Context Studios](https://www.contextstudios.ai/blog/how-to-build-a-self-learning-ai-agent-system-our-actual-architecture) | Yes — journal/ folder with structured metadata |
| 3-occurrence threshold before promoting patterns | Context Studios | Yes — prevents hallucinated learnings |
| Read-write memory with feedback loops (not read-only RAG) | Context Studios | Yes — NeoMind writes AND reads back |
| Heartbeat cycle: daily logs → weekly synthesis → MEMORY.md | [OpenClaw Engram](https://github.com/joshuaswarren/openclaw-engram) | Yes — weekly retro promotes validated patterns |
| Human-in-the-loop via editable markdown | [DEV Community](https://dev.to/imaginex/ai-agent-memory-management-when-markdown-files-are-all-you-need-5ekk) | Yes — Irene can edit any .md file |
| memsearch: semantic search over markdown, local CPU embeddings | [Zilliz memsearch](https://github.com/zilliztech/memsearch) | Future — when vault grows large |

---

## WHAT CHANGED IN OUR THINKING (Incremental Conclusions)

### Round 1 (Initial Assessment)
- **Conclusion:** "You don't need Obsidian, just use plain markdown files"
- **Reasoning:** NeoMind is headless; it doesn't need a GUI
- **Gap:** Undervalued Irene's need to SEE NeoMind's brain

### Round 2 (After 20 searches)
- **Conclusion shifted:** "Use Obsidian as your viewer, but NeoMind doesn't depend on it"
- **New findings:** Obsidian CLI (Feb 2026) has 80+ commands, Bases is built-in, graph view is irreplaceable for humans
- **Corrected:** Previous undervaluation of Obsidian's human-facing features
- **Corrected:** Previous overcounting of MCP security risk (now patched, but still unnecessary)

### Round 3 (After 35 searches, final)
- **Conclusion stabilized:** Use Obsidian in Restricted Mode with network blocked. NeoMind writes standard markdown to a Docker volume mount. Zero cost, maximum security, zero lock-in
- **New findings:** Electron CVEs exist but don't apply when no untrusted files enter vault. Community plugins are dangerous (unrestricted filesystem access) — Restricted Mode eliminates this. No air-gap mode built-in — must use OS-level firewall. IRS individual investor rules are simple (no WORM needed). Git audit trail is legally defensible. Obsidian company is sustainable ($2M ARR)
- **No further changes expected** — all major concerns addressed

---

## ARCHITECTURE

```
┌─ Irene's Mac ─────────────────────────────────────────────┐
│                                                            │
│  ┌─ Docker Container (NeoMind) ─────────────────────────┐ │
│  │  Python: reads vault/*.md at session startup          │ │
│  │  Python: writes vault/*.md during/after tasks         │ │
│  │  No network access to Obsidian app                    │ │
│  │  No MCP server, no REST API, no HTTP                  │ │
│  └──────────────────────┬───────────────────────────────┘ │
│                         │ Docker bind mount (rw)           │
│                         ▼                                  │
│  ┌─ ~/neomind-vault/ (local folder on Mac) ─────────────┐ │
│  │                                                       │ │
│  │  MEMORY.md          ← curated long-term knowledge     │ │
│  │  current-goals.md   ← active improvement targets      │ │
│  │  SOUL.md            ← NeoMind identity & rules        │ │
│  │                                                       │ │
│  │  journal/                                             │ │
│  │  └── 2026-03-22.md  ← daily execution log + YAML     │ │
│  │                                                       │ │
│  │  retros/                                              │ │
│  │  └── retro-2026-03-16.md  ← weekly retrospectives    │ │
│  │                                                       │ │
│  │  learnings/                                           │ │
│  │  ├── trading-patterns.md                              │ │
│  │  ├── coding-lessons.md                                │ │
│  │  └── user-preferences.md                              │ │
│  │                                                       │ │
│  │  research/                                            │ │
│  │  └── (deep research outputs)                          │ │
│  │                                                       │ │
│  │  .git/              ← cryptographic audit trail       │ │
│  └──────────────────────┬───────────────────────────────┘ │
│                         │ Obsidian reads (filesystem)      │
│                         ▼                                  │
│  ┌─ Obsidian.app ───────────────────────────────────────┐ │
│  │  Restricted Mode (zero community plugins)             │ │
│  │  Network BLOCKED (macOS firewall / Little Snitch)     │ │
│  │  Auto-update DISABLED                                 │ │
│  │  Built-in only: Graph + Bases + Search + Backlinks    │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  🔒 FileVault (full disk encryption at rest)               │
│  🔒 macOS firewall (Obsidian outbound blocked)             │
│  🔒 No cloud sync, no MCP, no REST API, no plugins        │
│  🔒 Git SHA audit trail (tamper-evident history)           │
└────────────────────────────────────────────────────────────┘
```

### Data Flow: Self-Improvement Loop

```
Session Start
  │
  ├─ Read vault/MEMORY.md            (long-term curated knowledge)
  ├─ Read vault/current-goals.md     (3 active improvement targets)
  ├─ Read vault/journal/yesterday.md (yesterday's execution log)
  │
  ▼
Inject into system prompt (alongside agent_config.system_prompt)
  │
  ▼
Execute tasks (trading, coding, chat)
  │
  ├─ Log to evidence trail (existing)
  ├─ Update SharedMemory (existing)
  │
  ▼
Session End
  │
  └─ Write vault/journal/2026-03-22.md  (YAML frontmatter + summary)
      │
      ▼
Weekly Retro (Sunday, auto_evolve.run_weekly_retro)
  │
  ├─ Read past 7 journal entries
  ├─ Read last retro
  ├─ Generate 3 improvement targets
  │
  ├─ Write vault/current-goals.md         (overwrite with new targets)
  ├─ Write vault/retros/retro-2026-03-22.md
  │
  ├─ Promote validated patterns (3+ occurrences) → append to vault/MEMORY.md
  ├─ Promote validated patterns → append to vault/learnings/*.md
  │
  ▼
Next session reads updated files → compounding improvement
```

---

## VAULT STRUCTURE SPECIFICATION

### Root Files

#### `SOUL.md`
NeoMind's identity, values, and operating rules. Written once, edited rarely.

```markdown
---
type: soul
version: 1
last_updated: 2026-03-22
---

# NeoMind — Soul

## Identity
I am NeoMind, a three-personality AI agent (chat, coding, fin) for Irene.

## Core Values
- Data stays local. No cloud leaks. Ever.
- Financial data MUST come from tool calls, never LLM memory.
- Corrections > praise in learning priority.
- Admit mistakes. Don't hallucinate confidence.

## Operating Rules
- Read MEMORY.md and current-goals.md at every session start
- Write journal entry at every session end
- Never promote a pattern to MEMORY.md with < 3 occurrences
- Always check FINANCE_CORRECTNESS_RULES.md before any trade-related output
```

#### `MEMORY.md`
Curated long-term knowledge. Auto-updated by weekly retro, manually editable by Irene.

```markdown
---
type: memory
last_updated: 2026-03-22
entries: 0
---

# NeoMind — Long-Term Memory

## About Irene
(Facts learned from conversations, promoted after 3+ occurrences)

## Trading Patterns
(Validated patterns from fin mode, e.g., "AAPL tends to gap up after earnings beat")

## Coding Preferences
(Validated preferences, e.g., "Irene prefers Python type hints")

## Corrections & Lessons
(Important mistakes to never repeat)
```

#### `current-goals.md`
Active improvement targets. Overwritten each Sunday by weekly retro.

```markdown
---
type: goals
generated_by: weekly_retro
date: 2026-03-22
---

# Current Improvement Targets

## 1. Reduce response length in chat mode
- **Current:** avg 450 tokens/response
- **Target:** avg 250 tokens/response
- **Metric:** token count per response in journal entries
- **Action:** Check user preference for brevity before generating
- **Timeline:** 1 week

## 2. ...
## 3. ...
```

### journal/ Folder

Each file: `journal/YYYY-MM-DD.md`

```markdown
---
type: journal
date: 2026-03-22
mode: fin
tasks_completed: 3
tasks_failed: 0
errors: 0
user_satisfaction: positive
tools_used: [web_search, stock_price, portfolio_check]
tags: [AAPL, earnings, analysis]
tokens_used: 12500
session_duration_min: 45
---

# Journal — 2026-03-22

## Tasks
1. Analyzed AAPL Q1 earnings → user satisfied
2. Checked portfolio allocation → no rebalance needed
3. Researched Obsidian integration → detailed report

## Errors
(none)

## Learnings
- User prefers concise trading summaries with bullet points for fin mode
- AAPL earnings beat consensus by 8% → pattern: 3rd consecutive beat

## Links
- Related: [[trading-patterns]]
- Related: [[AAPL]]
```

### retros/ Folder

Each file: `retros/retro-YYYY-MM-DD.md` (generated by `auto_evolve.run_weekly_retro`)

### learnings/ Folder

Domain-specific curated knowledge:
- `trading-patterns.md` — validated trading patterns with evidence counts
- `coding-lessons.md` — recurring mistakes and their fixes
- `user-preferences.md` — Irene's confirmed preferences (distinct from SharedMemory SQLite for long-form context)

### research/ Folder

Deep research outputs NeoMind produces (like this very Obsidian analysis). Stored for future reference and RAG retrieval.

---

## INCREMENTAL CHANGES (all files that need modification)

### Phase 1: Vault Foundation (Day 1) — ✅ COMPLETE

| # | File | Change | Lines | Status |
|---|------|--------|-------|--------|
| 1 | `docker-compose.yml` | Add bind mount: `~/neomind-vault:/data/vault` | ~3 | ✅ |
| 2 | **NEW** `agent/vault/reader.py` | VaultReader class: read MEMORY.md, current-goals.md, yesterday's journal | 154 | ✅ |
| 3 | **NEW** `agent/vault/writer.py` | VaultWriter class: write journal entries with YAML frontmatter | 317 | ✅ |
| 4 | **NEW** `agent/vault/__init__.py` | Package exports with graceful degradation | 21 | ✅ |
| 5 | **NEW** `agent/vault/_config.py` | Shared vault dir resolution (env → Docker → local) | 20 | ✅ |
| 6 | `agent/core.py` (line ~323) | At startup: call VaultReader, inject vault context into system prompt | ~25 | ✅ |
| 7 | `agent/core.py` (write_session_journal) | At session end: call VaultWriter to write daily journal | ~25 | ✅ |
| 8 | `cli/neomind_interface.py` | Hook write_session_journal() into both CLI exit paths | ~8 | ✅ |

### Phase 2: Close the Self-Improvement Loop (Day 2) — ✅ COMPLETE

| # | File | Change | Lines | Status |
|---|------|--------|-------|--------|
| 9 | `agent/evolution/auto_evolve.py` (run_weekly_retro) | Write retro + goals to vault, promote patterns | ~20 | ✅ |
| 10 | **NEW** `agent/vault/promoter.py` | Pattern promotion logic: 3-occurrence threshold, dedup, section mapping | 72 | ✅ |

### Phase 3: Obsidian-Friendly Enhancements (Day 3) — ⚠️ PARTIAL

| # | File | Change | Lines | Status |
|---|------|--------|-------|--------|
| 11 | `agent/vault/writer.py` | `[[wikilinks]]` in journal entries | ~15 | ⬜ deferred |
| 12 | `vault/SOUL.md` | Initial SOUL.md file (NeoMind identity) — auto-created by ensure_structure() | ~30 | ✅ |
| 13 | `vault/MEMORY.md` | Initial empty MEMORY.md with schema — auto-created by ensure_structure() | ~20 | ✅ |
| 14 | `vault/current-goals.md` | Initial empty goals file — auto-created by ensure_structure() | ~10 | ✅ |
| 15 | `vault/.gitignore` | Ignore `.obsidian/` — auto-created by ensure_structure() | ~3 | ✅ |

### Phase 4: Tests (Day 3-4) — ✅ COMPLETE

| # | File | Change | Lines | Status |
|---|------|--------|-------|--------|
| 16 | **NEW** `tests/test_vault_reader.py` | 17 unit tests for VaultReader | ~170 | ✅ |
| 17 | **NEW** `tests/test_vault_writer.py` | 18 unit tests for VaultWriter | ~200 | ✅ |
| 18 | **NEW** `tests/test_vault_promoter.py` | 10 unit tests for pattern promotion | ~120 | ✅ |
| 19 | **NEW** `tests/test_vault_integration.py` | 6 integration tests: full round-trip | ~90 | ✅ |
| 20 | **NEW** `tests/conftest.py` | NEOMIND_DISABLE_VAULT=1 for test isolation | ~7 | ✅ |

**Test results (2026-03-22): 1479 passed, 0 failed, 67 skipped (including 51 new vault tests)**

### Phase 5: Future — Semantic Search (When vault > 500 files)

| # | File | Change | Lines |
|---|------|--------|-------|
| F1 | `requirements.txt` | Add `memsearch[local]` | ~1 |
| F2 | **NEW** `agent/vault/search.py` | VaultSearch class wrapping memsearch for semantic queries | ~60 |
| F3 | `agent/core.py` | Add `/vault-search <query>` command | ~10 |

**Total: ~20 files changed/created, ~800 lines of code**

---

## REFERENCES (Future NeoMind: bookmark these)

### Architecture & Patterns
- [OpenClaw Memory Architecture](https://docs.openclaw.ai/concepts/memory) — SOUL.md / MEMORY.md pattern
- [Context Studios Self-Learning Agent](https://www.contextstudios.ai/blog/how-to-build-a-self-learning-ai-agent-system-our-actual-architecture) — read-write memory + 3-occurrence threshold
- [Self-Improving Agent (ClawHub)](https://clawhub.ai/ivangdavila/self-improving) — heartbeat reflection cycle
- [AI Agent Memory: When Markdown Is All You Need](https://dev.to/imaginex/ai-agent-memory-management-when-markdown-files-are-all-you-need-5ekk) — file-based memory trade-offs
- [SOUL.md Guide](https://dev.to/techfind777/the-complete-guide-to-soulmd-give-your-ai-agent-a-personality-ldj) — agent identity file

### Obsidian Resources
- [Obsidian Official](https://obsidian.md/) — download, docs, CLI
- [Obsidian CLI Docs](https://help.obsidian.md/cli) — 80+ commands (requires app running)
- [Obsidian Bases](https://help.obsidian.md/bases) — built-in database views (v1.9.10+)
- [Obsidian Graph View](https://help.obsidian.md/plugins/graph) — knowledge visualization
- [Obsidian Privacy Policy](https://obsidian.md/privacy) — zero telemetry
- [Obsidian Security](https://obsidian.md/security) — Cure53 audit reports
- [Obsidian Plugin Security](https://help.obsidian.md/plugin-security) — why Restricted Mode matters
- [JSON Canvas Spec](https://jsoncanvas.org/) — open format for visual workflows

### Security
- [CVE-2023-2110](https://starlabs.sg/advisories/23/23-2110/) — Obsidian local file disclosure
- [CVE-2025-53109](https://www.sentinelone.com/vulnerability-database/cve-2025-53109/) — MCP path traversal
- [Docker Bind Mount Security](https://redfoxsec.com/blog/insecure-volume-mounts-in-docker/) — best practices
- [Little Snitch](https://www.obdev.at/products/littlesnitch/index.html) — macOS app-level firewall

### Tax/Legal
- [IRS Publication 550](https://www.irs.gov/publications/p550) — investment income record requirements
- [IRS Topic 429](https://www.irs.gov/taxtopics/tc429) — traders in securities
- [FINRA Record-Keeping](https://www.finra.org/investors/insights/recordkeeping) — only for broker-dealers
- [Git as Compliance Audit Trail](https://www.kosli.com/blog/using-git-for-a-compliance-audit-trail/) — legal defensibility

### Future Tools
- [memsearch (Zilliz)](https://github.com/zilliztech/memsearch) — markdown-first semantic search, local embeddings
- [OpenClaw Engram](https://github.com/joshuaswarren/openclaw-engram) — local-first memory plugin
- [Obsidian Dataview](https://blacksmithgu.github.io/obsidian-dataview/) — advanced query plugin (only if Restricted Mode is relaxed later)

### Trading-Specific
- [Journalit Plugin](https://github.com/Cursivez/journalit) — Obsidian trading journal (only if plugins are enabled later)
- [Traders Using Obsidian](https://forum.obsidian.md/t/traders-share-how-youre-using-obsidian/72606) — community experiences

---

## DECISION LOG

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-22 | Use Obsidian in Restricted Mode | Eliminates plugin attack surface while keeping core features |
| 2026-03-22 | Block Obsidian network via macOS firewall | No built-in air-gap mode; OS-level control required |
| 2026-03-22 | No MCP server | CVE-2025-53109 + unnecessary complexity; direct file I/O is safer |
| 2026-03-22 | No Obsidian Sync | Docker volume mount handles "sync"; no cloud needed |
| 2026-03-22 | Git-version the vault | Legal audit trail + tamper evidence + rollback capability |
| 2026-03-22 | 3-occurrence threshold for MEMORY.md promotion | Prevents hallucinated patterns from becoming "knowledge" |
| 2026-03-22 | YAML frontmatter on all vault files | Enables Obsidian Bases queries without plugins |
| 2026-03-22 | `[[wikilinks]]` in journal entries | Enables Obsidian graph view + backlinks with zero effort |
| 2026-03-22 | memsearch deferred to Phase 5 | Not needed until vault > 500 files; grep suffices for now |
