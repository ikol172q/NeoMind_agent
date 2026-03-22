# gstack → NeoMind Integration Plan

## Architecture: Shared Core + Per-Personality Skills

```
agent/
├── browser/                    # [P1] SHARED — Playwright persistent Chromium
│   ├── daemon.py               # HTTP server + Chromium lifecycle
│   ├── commands.py             # goto/click/fill/snapshot/screenshot
│   └── snapshot.py             # ARIA tree → @ref system
│
├── workflow/                   # [P3-P4] SHARED — structured workflow engine
│   ├── sprint.py               # Think→Plan→Build→Review→Test→Ship
│   ├── review.py               # Self-review (code/trade/content)
│   ├── evidence.py             # Screenshots + logs + audit trail
│   └── guards.py               # [P2] /careful /freeze /guard
│
├── skills/                     # [P0] Skill system (SKILL.md format)
│   ├── loader.py               # SKILL.md parser + skill registry
│   ├── shared/                 # Three personalities share these
│   │   ├── browse/SKILL.md
│   │   ├── careful/SKILL.md
│   │   └── investigate/SKILL.md
│   ├── chat/                   # chat personality
│   │   └── office-hours/SKILL.md
│   ├── coding/                 # coding personality
│   │   ├── eng-review/SKILL.md
│   │   ├── qa/SKILL.md
│   │   └── ship/SKILL.md
│   └── fin/                    # fin personality
│       ├── trade-review/SKILL.md
│       ├── finance-briefing/SKILL.md
│       └── qa-trading/SKILL.md
│
├── finance/                    # EXISTING — fin mode data layer
├── config/                     # EXISTING — YAML configs
└── core.py                     # EXISTING — main agent
```

## Phase Schedule

| Phase | Days | Deliverable | Status |
|-------|------|-------------|--------|
| P0: Skill System | 2 | `agent/skills/loader.py` + 10 SKILL.md files + 17 tests | ✅ DONE |
| P1: Browser Daemon | 3 | `agent/browser/daemon.py` — 40+ commands, snapshot refs | ✅ DONE |
| P2: Safety Guards | 1 | `agent/workflow/guards.py` — /careful /freeze /guard + 12 tests | ✅ DONE |
| P3: Sprint Framework | 2 | `agent/workflow/sprint.py` — 3 mode templates + 7 tests | ✅ DONE |
| P4: Review + Evidence | 2 | `agent/workflow/review.py` + `evidence.py` + 12 tests | ✅ DONE |
| P5: CLI Wiring | 1 | /skills /careful /freeze /guard /sprint /evidence in CLI | ✅ DONE |
| P6: Telegram Wiring | 1 | /skills /careful /sprint /evidence in Telegram | ✅ DONE |
| P7: Docker + Tests | 1 | Playwright in Dockerfile, 95 tests pass | ✅ DONE |

Total: 95 tests, 29 modules, 10 skills, all phases complete.

## Key Design Decisions

1. **Python, not TypeScript** — gstack is TS/Bun, NeoMind is Python. Absorb patterns, not code.
2. **Shared modules first** — browser, safety, sprint are mode-agnostic.
3. **SKILL.md format** — each skill is a prompt file with metadata frontmatter.
4. **"Boil the Lake"** — don't skip tests, reviews, evidence. AI makes marginal cost ~zero.
5. **Per-personality skill lists** — each mode declares which skills it can use.

## gstack Patterns Absorbed

| gstack Pattern | NeoMind Implementation |
|---------------|----------------------|
| Persistent Chromium daemon | `agent/browser/daemon.py` — Playwright + HTTP server |
| SKILL.md structured prompts | `agent/skills/loader.py` — YAML frontmatter + markdown body |
| ARIA snapshot → @ref system | `agent/browser/snapshot.py` — numbered element refs |
| /careful /freeze /guard | `agent/workflow/guards.py` — destructive op interception |
| Think→Plan→Build→Review→Test→Ship | `agent/workflow/sprint.py` — 7-phase task runner |
| Evidence trail (screenshots+logs) | `agent/workflow/evidence.py` — operation audit log |
| Smart review routing | `agent/workflow/review.py` — mode-aware review dispatch |
| QA with regression tests | `agent/skills/coding/qa/` — browser test + auto-fix |
| Office hours forcing questions | `agent/skills/chat/office-hours/` — deep requirement mining |
| Design docs flow through system | Sprint framework propagates context docs between phases |
