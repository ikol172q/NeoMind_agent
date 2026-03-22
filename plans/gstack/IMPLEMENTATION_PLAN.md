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

| Phase | Days | Deliverable | All 3 Personalities Get |
|-------|------|-------------|------------------------|
| P0: Skill System | 2 | `agent/skills/loader.py` + SKILL.md format | Extensible skill loading |
| P1: Browser Daemon | 3 | `agent/browser/` + `/browse` command | Web browsing in all modes |
| P2: Safety Guards | 1 | `agent/workflow/guards.py` | Destructive op protection |
| P3: Sprint Framework | 2 | `agent/workflow/sprint.py` | Structured task workflows |
| P4: Review + Evidence | 2 | `agent/workflow/review.py` + `evidence.py` | Self-check + audit trail |
| P5: Coding Skills | 3 | `/eng-review` `/qa` `/ship` | coding: full dev pipeline |
| P6: Finance Skills | 3 | `/trade-review` `/finance-briefing` `/qa-trading` | fin: investment pipeline |
| P7: Chat Skills | 2 | `/office-hours` deep questioning | chat: structured analysis |

Total: ~18 days

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
