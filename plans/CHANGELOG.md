# NeoMind Agent — Changelog & Fix Tracker

## Version 0.3.0 — 2026-03-21 (Finance + Telegram + gstack Integration)

### Features Added

| # | Feature | Files | Tests |
|---|---------|-------|-------|
| F-001 | Finance personality (fin mode) — 16 commands | `agent/config/fin.yaml`, `agent/finance/*` (17 files) | config switching tests |
| F-002 | Hybrid search v2 — query expansion, TF-IDF, temporal ranking, Google News RSS | `agent/finance/hybrid_search.py` | TF-IDF + expansion tests |
| F-003 | HTML dashboard generator (Chart.js) | `agent/finance/dashboard.py` | render tests |
| F-004 | Telegram bot — independent bot identity | `agent/finance/telegram_bot.py` | 48 tests |
| F-005 | OpenClaw integration — gateway + skill + memory bridge | `agent/finance/openclaw_*.py`, `memory_bridge.py` | protocol + handoff tests |
| F-006 | Docker deployment (CLI + Telegram daemon) | `Dockerfile`, `docker-compose*.yml`, `docker-entrypoint.sh` | build validation |
| F-007 | Per-chat mode (SQLite) | `agent/finance/chat_store.py` | 5 per-chat mode tests |
| F-008 | Streaming thinking with expandable blockquote | `telegram_bot.py` `_ask_llm_streaming` | manual Telegram test |
| F-009 | Auto-compact (90% trigger, 30% target) | `telegram_bot.py` `_auto_compact_if_needed_db` | compact tests |
| F-010 | Provider fallback (DeepSeek → z.ai) | `telegram_bot.py` `_get_provider_chain` | provider chain tests |
| F-011 | Hacker News integration + /subscribe auto-push | `agent/finance/hackernews.py` | fetch + format tests |
| F-012 | Skill system (SKILL.md loader + 10 skills) | `agent/skills/` | 17 skill tests |
| F-013 | Browser daemon (Playwright persistent Chromium) | `agent/browser/daemon.py` | import tests |
| F-014 | Safety guards (/careful /freeze /guard) | `agent/workflow/guards.py` | 12 guard tests |
| F-015 | Sprint framework (Think→Plan→Build→Review→Test→Ship) | `agent/workflow/sprint.py` | 7 sprint tests |
| F-016 | Evidence trail (JSONL audit log) | `agent/workflow/evidence.py` | 8 evidence tests |
| F-017 | Review dispatcher (mode-aware) | `agent/workflow/review.py` | 4 review tests |
| F-018 | LiteLLM + Ollama optional provider | `core.py`, `telegram_bot.py` | 6 provider tests |
| F-019 | /provider command (runtime switch) | `telegram_bot.py` | manual test |

### Bugs Found & Fixed

| # | Bug | Root Cause | Fix | Found By |
|---|-----|-----------|-----|----------|
| B-001 | `Page` type undefined without Playwright | Type annotation at class-definition time | Stub types in except block | import test |
| B-002 | Sprint `_save()` TypeError str/str | `SPRINTS_DIR` can be str not Path | `Path(self.SPRINTS_DIR)` | simulation test |
| B-003 | Thinking content not distinct in Telegram | `<i>` tag insufficient | `<blockquote expandable>` | manual test |
| B-004 | Auto-compact 291→291 (no reduction) | Summary as long as originals | Remove summaries, just drop old messages | manual test |
| B-005 | "哈咯" not recognized | Hardcoded greeting list | Removed all hardcoded rules, route through LLM | manual test |
| B-006 | Mode global not per-chat | Single `_current_mode` variable | SQLite `chats.mode` column per chat_id | design review |
| B-007 | DeepSeek timeout kills bot | No fallback provider | Provider chain: DeepSeek → z.ai | production timeout |
| B-008 | `.dockerignore` excluded entrypoint | Listed in ignore but Dockerfile COPY needs it | Removed from `.dockerignore` | Docker build fail |
| B-009 | `pip install -e .[finance]` fails in Docker | deps stage missing source files | Single-stage build with direct pip install | Docker build fail |
| B-010 | README had fake-looking real token format | `7123456789:AAF4x9...` too realistic | Changed to `<placeholder>` | security audit |
| B-011 | `/history` missing from Telegram | No command for active messages | Added as `/admin history` alias | feature gap review |
| B-012 | Bot not responding in group | Telegram Privacy Mode on by default | Document: disable via BotFather /setprivacy | production test |
| B-013 | `/model` typo not caught | No unknown command handler | Added typo suggestion handler | manual test |
| B-014 | Compact doesn't re-trigger after LLM response | Only pre-check, not post-check | Added post-response compact check | manual test |

### Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/test_telegram_bot.py` | 48 | ChatStore, MessageRouter, AutoCompact, AgentCollaborator, Persistence |
| `tests/test_skills.py` | 17 | Skill loading, parsing, per-mode filtering, singleton |
| `tests/test_workflow.py` | 30 | Guards, Sprint, Evidence, Review |
| **Total** | **95** | |

### Module Count

29 Python modules, 10 SKILL.md files, 4 YAML configs, all import clean.
