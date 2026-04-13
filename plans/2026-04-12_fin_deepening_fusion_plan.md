# Fin Persona Deepening — Fusion Plan (Investment v1 → NeoMind fin)

**Date:** 2026-04-12
**Status:** DRAFT — awaiting user approval before any code change
**Supersedes:** none. **Honors:** `~/Desktop/Investment/plans/2026-04-11_neomind-investment-system-plan-v1.md` (merge essence, not architecture)
**Relates to:** `plans/2026-04-11_personality_fleet_merge_plan.md` (73/73 committed 2026-04-12)

---

## 0. Premise (why this plan exists)

The user ran a 10-round Proposer/Reviewer debate on 2026-04-11 and produced an Investment-system v1 plan at `~/Desktop/Investment/`. That plan assumed NeoMind is a black-box HTTP chat service and built a new FastAPI project around it. **That premise is wrong:** post-audit, `agent/finance/` already holds ~4800 LOC of real production code covering 80% of what Investment v1 proposed, and the freshly-committed persona-fleet merge (7 commits, 73/73 tests green) already gives us manager+multi-agent infrastructure that Investment v1 does not.

The right move is to **deepen the existing fin persona** by merging Investment v1's remaining essentials (circuit breaker, Pydantic signals, KPI/fail-fast, tech indicators, minimal dashboard, prompt versioning) into `agent/finance/`, run fin as a member of a fleet project, and isolate per-investment-project data under `~/Desktop/Investment/<project_id>/` so none of it ever enters the NeoMind git repo.

---

## 1. Ground truth (from audit, 2026-04-12)

### 1.1 Already production in `agent/finance/` (9 modules, ~4800 LOC)

| Module | LOC | What it actually does | Tested |
|---|---|---|---|
| `data_hub.py` | 667 | Async quotes: Finnhub → yfinance fallback (US/HK/A), CoinGecko+Binance crypto, 300s cache, `VerifiedDataPoint` wrapping | partial (mocked) |
| `paper_trading.py` | 586 | Full in-memory trading sim: market/limit/stop orders, positions, PnL, JSON persistence | yes |
| `fin_rag.py` | 654 | FAISS-based doc RAG for 10-K / earnings; lazy model load | yes |
| `backtest.py` | 471 | Own OHLCV replay engine; Sharpe, max-DD, win-rate, profit factor | yes |
| `performance_tracker.py` | 559 | Daily snapshots, Sharpe/Sortino/max-DD, stdlib math only | no |
| `quant_engine.py` | 520 | Black-Scholes + Greeks, DCF, scenario/VaR, Kelly, Sharpe | no |
| `response_validator.py` | 490 | Five Iron Rules enforcement, **regex-based** | no |
| `risk_manager.py` | 440 | Kelly/fixed/volatility sizing, drawdown cap, sector limits | yes |
| `investment_personas.py` | 364 | 3 personas (Value / Growth / Macro) — pure prompts + rubric scoring + consensus vote | no |

### 1.2 Backward-compat shims (18 files, 7 LOC each) — DO NOT DELETE

`agent_collab, chat_store, config_editor, dashboard, diagram_gen, hackernews, hybrid_search, memory_bridge, mobile_sync, news_digest, openclaw_gateway, openclaw_skill, provider_state, rss_feeds, secure_memory, source_registry, telegram_bot, usage_tracker` — each is a 7-line redirect that reassigns `sys.modules[__name__] = _real` to pull in the real implementation from `agent/{services,integration}/`.

**Correction (2026-04-12, post-grep):** an earlier read of `agent/finance/` (by an Explore subagent that only checked `agent/modes/finance.py` + `agent/config/fin.yaml`) classified these 18 files as "orphaned dead weight". **That classification was wrong.** A full-repo grep for `agent.finance.<shim>` found 20+ real callers:

- **Production path**: `docker-entrypoint.sh:190` runs `from agent.finance.telegram_bot import run_telegram_bot, HAS_TELEGRAM` as the Docker Telegram-bot startup. Deleting `agent/finance/telegram_bot.py` kills prod bot — direct violation of non-negotiable #1.
- **Module audit**: `agent/workflow/audit.py:171-179` hardcodes 14 of the 18 shim paths in its module-import audit.
- **Test suites**: 17 test files (`test_telegram_bot`, `test_telegram_live`, `test_rss_feeds_full`, `test_hackernews_full`, `test_config_editor_full`, `test_news_digest_full`, `test_secure_memory_full`, `test_diagram_gen_full`, `test_openclaw_skill_full`, `test_dashboard_full`, `test_usage_tracker_full`, `test_memory_bridge_full`, `test_openclaw_gateway_full`, `test_hybrid_search_full`, `test_chat_store_full`, `test_agent_collab_full`, `test_source_registry_full`, `test_mobile_sync_full`). Several use `unittest.mock.patch("agent.finance.<shim>.<attr>")` which binds to the shim's module object — deleting the shim makes the patch target unresolvable and crashes 25+ assertions on import.

**Decision: leave all 18 shims untouched.** They are legitimate backward-compat redirects from a prior refactor (real impls moved to `agent/services/` and `agent/integration/` but callers were not migrated). They cost 126 LOC total, zero runtime overhead, and removing them is pure churn with zero user value. The fin-deepening work in Phases 1-6 writes new code using the real paths (`agent.services.X` / `agent.integration.X`) and never touches the shims.

**Lesson for future audits:** "imported in X module" is not a complete answer to "is this dead?". Always grep the full repo including `tests/`, `scripts/`, `docker-entrypoint.sh`, and `supervisord.conf` before declaring code orphaned.

### 1.3 Gap vs Investment plan v1

| Investment v1 essential | In fin/? | Gap |
|---|---|---|
| Pydantic structured signal output | regex only | **YES — replace** |
| Finnhub real adapter | yes | minor (env key validation) |
| Alpha Vantage fallback | no | **YES — add** |
| Alpaca paper broker | no; in-memory only | **optional** — keep in-memory for now |
| SQLite analysis persistence | no (paper_trading JSON only) | **YES — add** |
| Minimal web dashboard | dashboard.py is shim | **YES — build real** |
| Circuit breaker (Round 6) | no | **YES — add** |
| Technical indicators (RSI/MACD/BB) | no | **YES — add** |
| VectorBT backtest | own engine | skip (own works) |
| Quantitative KPI + 2-wk fail-fast | no | **YES — add** |
| Prompt version table + ECE calibration | no | **YES — Phase 7** |
| Multi-agent manager | no | **YES — use fleet** |

### 1.4 Fleet launcher known limitation

`fleet/launch_project.py::FleetLauncher._run_member` is currently a mailbox+task-queue poll loop. It does NOT yet instantiate an `AgentConfigManager(mode=persona)` per member or call the LLM. This is flagged in the commit message and must be resolved before fleet can run fin as a real worker.

---

## 2. Non-negotiables (inherited from personality-fleet plan)

1. Docker + 2 Telegram bots (prod + canary) — never down.
2. Self-evolution ≠ prod downtime — Phase D (12.1s budget) stays valid.
3. CLI must feel like Claude CLI.
4. Three-layer testing every phase: pytest + Telethon + iTerm2.
5. No secrets / PII in commits. `.gitleaks.toml` must pass.
6. `agent/services/llm_provider.py` is the router — do not re-test.
7. **NEW — Data firewall:** every trade, analysis, hypothesis, journal entry, backtest output for a real investment project lives under `~/Desktop/Investment/<project_id>/`. Nothing from there is ever committed to NeoMind git. `agent/finance/investment_projects.py` validates paths at write-time.

---

## 3. Data firewall — `~/Desktop/Investment/<project_id>/` layout

```
~/Desktop/Investment/
├── _meta/
│   └── README.md                  # this convention, human-readable
├── <project_id>/                  # e.g. "us-growth-2026Q2", "a-share-value", "btc-momentum"
│   ├── README.md                  # hypothesis, success criteria, stop conditions
│   ├── watchlist.yaml             # symbols under this project
│   ├── trades.jsonl               # append-only trade log (paper or real)
│   ├── analyses/
│   │   └── 2026-04-12_AAPL_152230.json   # one file per analysis call, SignalSchema
│   ├── backtests/
│   │   └── 2026-04-12_strategy-v1.json   # backtest report
│   ├── journal/
│   │   └── 2026-04-12.md          # daily reflections
│   └── kpi/
│       └── weekly.jsonl           # rolling KPI snapshots (accuracy, S/N, latency)
```

**Rules enforced by `agent/finance/investment_projects.py`:**
- Path must resolve under `~/Desktop/Investment/` (rejected otherwise).
- `project_id` must match `[a-z0-9_-]{2,40}`.
- Writes go through helper APIs only (`append_trade`, `write_analysis`, `log_journal`).
- Reads are allowed from `agent/finance/*` but never cached into NeoMind's own DBs.
- NeoMind's `.gitignore` stays unchanged; `~/Desktop/Investment/` is outside the repo so it is implicitly excluded.

---

## 4. Phased plan

Each phase ends with: (a) all 3 test layers green; (b) evidence file in `tests/qa_archive/results/`; (c) this doc's status log updated; (d) explicit sign-off request.

### Phase 0 — Tracking convention + data firewall (~45 min)

**Note:** Original Phase 0 had a "0.1 shim cleanup" step. Dropped after re-audit on 2026-04-12 proved the 18 "shims" are backward-compat redirects with 20+ real callers including `docker-entrypoint.sh` (prod bot startup) and 17 test files. See §1.2 for the correction. Phase 0 now jumps straight to the data firewall work.

- **0.A** Write `agent/finance/investment_projects.py` (~180 LOC): `register_project(project_id, description)`, `append_trade(project_id, trade_dict)`, `write_analysis(project_id, symbol, signal_dict)`, `log_journal(project_id, markdown)`, `kpi_snapshot(project_id, metrics)`. Path validation rejects anything outside `~/Desktop/Investment/`. `project_id` regex `[a-z0-9_-]{2,40}`. JSONL appends use file locking (fcntl) for atomicity.
- **0.B** Create `~/Desktop/Investment/_meta/README.md` (human-readable convention doc) and scaffold the first real project `us-growth-2026Q2/` with empty subdirs (`analyses/`, `backtests/`, `journal/`, `kpi/`) + a placeholder `README.md` + `watchlist.yaml`. **Must not touch** the existing files `~/Desktop/Investment/NeoMind投资系统资源全景图.md` or `~/Desktop/Investment/plans/*` — those are the user's brainstorm archive.
- **0.C** Tests: `tests/test_investment_projects.py` — path traversal rejection (`..` / absolute paths outside Investment/), JSONL append atomicity (concurrent writers), write/read roundtrip, invalid project_id regex rejection, register idempotence, reject writes targeting `/Users/<user>/Desktop/NeoMind_agent/` (belt-and-suspenders check against the NeoMind repo).
- **Gate:** pytest green (new tests + 73 fleet tests + existing finance tests unchanged); smoke-import `agent.finance.investment_projects` clean; manual `ls ~/Desktop/Investment/us-growth-2026Q2/` shows expected tree; `git status` in NeoMind repo shows only the intended files.

### Phase 1 — Pydantic signal schema + validator upgrade (~2 h)
- **1.1** Define `agent/finance/signal_schema.py`: `StockQuote`, `AgentAnalysis (signal∈{buy,hold,sell}, confidence 1-10, reason, target_price?, risk_level, sources[])`, `AnalysisResult`.
- **1.2** Add `parse_signal(raw_llm_output) -> AgentAnalysis` with three-layer fallback (strict JSON → lenient JSON → conservative hold + log) — matches Round 2 decision in Investment v1.
- **1.3** Extend `response_validator.py`: Five Iron Rules now run on the parsed `AgentAnalysis` as well as the free-text (Pydantic catches structural issues; regex catches number hallucinations).
- **1.4** `data_hub.py` hardening: Finnhub env-key validation on init; Alpha Vantage adapter added as fallback between Finnhub and yfinance; timeout explicit (10s); retry-on-429 with backoff.
- **1.5** Tests: schema round-trip; fallback ladder; Finnhub + AV + yfinance adapter unit tests (mock httpx); one integration test that hits live Finnhub (skip if `FINNHUB_API_KEY` unset).
- **Gate:** pytest green + live-API test documented.

### Phase 2 — Risk deepening (Round 6) (~2 h)
- **2.1** Add `CircuitBreaker` class to `risk_manager.py`: states CLOSED → OPEN (after N failures) → HALF_OPEN (after `cooldown_s`) → CLOSED (after M successes). Thread-safe.
- **2.2** Make `RiskAssessment.allowed=False` **enforced, not advisory**: `paper_trading.submit_order()` must call `risk_manager.check(order)` and raise on reject.
- **2.3** Default sizing: Fractional Kelly 0.25× (Round 6).
- **2.4** Tests: state machine transitions, enforced rejection, Kelly bound, daily-loss cap trigger.
- **Gate:** pytest + existing paper_trading tests still green.

### Phase 3 — Technical indicators + KPI / fail-fast (~2-3 h)
- **3.1** Add `quant_engine.indicators` module: RSI, MACD, Bollinger Bands, EMA, SMA, ATR. Pure Python (no TA-Lib). Vectorized where sensible but OK to loop.
- **3.2** Extend `performance_tracker.py` with `kpi_snapshot(project_id, window_days=14) -> {accuracy, signal_noise, latency_p50, latency_p95}`. Writes to `~/Desktop/Investment/<id>/kpi/weekly.jsonl`.
- **3.3** Fail-fast hook: if a project's `accuracy < 0.50` over the last 14 days, write a `fail_fast` memory entry (`SharedMemory.record_feedback('fail_fast', ...)`) so the fin persona sees it on next boot and downgrades to rules-only mode.
- **3.4** Tests: indicator numerics vs known values; KPI calc vs hand-crafted history; fail-fast trigger.
- **Gate:** pytest green.

### Phase 4 — Fleet runs fin for real (~3 h, touches committed code)
- **4.1** Fix `fleet/launch_project.py::FleetLauncher._run_member`: when a worker claims a task, instantiate a **local** `AgentConfigManager` (not the global singleton), call `switch_mode(member.persona)`, run one LLM loop against the task description, then report back via XML notification to the leader's mailbox. This closes the gap flagged in the Phase 5 commit message.
- **4.2** Write `projects/fin-core/project.yaml`:
  ```yaml
  project_id: fin-core
  description: "Fin persona core — realtime + research + dev support"
  leader: mgr-1
  members:
    - { name: mgr-1,      persona: chat,   role: leader }
    - { name: fin-rt,     persona: fin,    role: worker }   # realtime / scanner
    - { name: fin-rsrch,  persona: fin,    role: worker }   # news + research
    - { name: dev-1,      persona: coding, role: worker }   # dev support
    - { name: dev-2,      persona: coding, role: worker }
  settings:
    stuck_timeout_minutes: 5
    max_concurrent_tasks: 3
  ```
- **4.3** End-to-end test: `submit_task("analyze AAPL using data_hub + quant_engine indicators, return SignalSchema JSON")` → fin-rt claims → calls data_hub → parses signal → reports → leader aggregates → verify `~/Desktop/Investment/fin-core/analyses/` has the result file.
- **4.4** End-to-end test: `submit_task("add volume-weighted RSI to quant_engine.indicators")` → dev-1 claims → edits code → reports → verify edit.
- **4.5** Canary deploy via `EvolutionTransaction` to prove prod path unaffected; forward + revert.
- **Gate:** pytest + Telethon + iTerm2 3-layer; canary revert leg green.

### Phase 5 — Minimal local dashboard (~2 h)
- **5.1** `agent/finance/dashboard_server.py` (~250 LOC): FastAPI on `localhost:8001`. Endpoints: `GET /` (HTML), `GET /api/quote/{sym}`, `POST /api/analyze/{sym}?project_id=`, `GET /api/history?project_id=`, `GET /api/health`. Uses `data_hub` directly for quotes, uses `FleetLauncher.submit_task` for analyze (async — returns task_id; UI polls).
- **5.2** HTML: dark-theme single page (copy Investment v1's `index.html` template), symbol input, quote + analyze buttons, history table, project selector dropdown.
- **5.3** Every analysis writes to `~/Desktop/Investment/<active_project>/analyses/` via `investment_projects.write_analysis`.
- **5.4** CLI: `neomind fin start` launches fleet + dashboard together. `neomind fin stop` graceful shutdown.
- **5.5** Tests: endpoint smoke (TestClient), HTML renders, path validation on project selector.
- **Gate:** pytest + manual browser check (`http://localhost:8001` → input AAPL → see quote → click analyze → see signal → see history).

### Phase 6 — Prompt versioning + ECE calibration (~2 h, stretch)
- **6.1** Add `fin_prompt_versions` table to `shared_memory` (schema migration, backward-compat): id, version_tag, prompt_text, created_at, active.
- **6.2** Log every fin analysis with `prompt_version` + `confidence` + `outcome` (filled later when the 3-day later price movement is known).
- **6.3** Weekly ECE (Expected Calibration Error) job — `agent/finance/prompt_calibration.py`. Alerts via fin memory + logs when `ECE > 0.15`.
- **6.4** Tests: version table CRUD, ECE numeric correctness vs hand-crafted history, migration idempotence.
- **Gate:** pytest green.

### Phase 7 — Documentation + operator runbook (~1 h)
- Update `docs/` with: how to create a new investment project (`neomind fin new-project <id>`), how to read daily KPI, how to roll back a prompt version, how the data firewall works, where the three bots sit.
- Update `README.md` fin section with one paragraph + links.

---

## 5. Testing policy (unchanged from personality-fleet plan)

Every phase:
1. **pytest** — all new phase tests green; no regression in 73 fleet tests or 13 existing finance tests.
2. **Telethon canary** — fin-persona `gate_b3` subset against `@neomind_canary_bot`.
3. **iTerm2 or tmux-95%** — 3-scenario fin CLI smoke.
4. Phase 4 additionally runs the canary→promote→revert loop to prove prod bot untouched.

---

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase 4 fleet LLM loop breaks single-bot mode | medium | high | Feature-flag `FLEET_LLM_LOOP_ENABLED`; default off until canary green |
| `~/Desktop/Investment/` path accidentally leaks to git | low | critical | Phase 0.2 path validator + pre-commit hook greps for that path |
| Live Finnhub rate-limit under fleet (fin-rt + fin-rsrch + dashboard) | medium | medium | 300s cache in data_hub stays; add per-second throttle; Alpha Vantage fallback |
| Circuit breaker false-trips in normal volatility | medium | medium | Tunable threshold; start conservative (5 fails / 60s cooldown) |
| Pydantic migration breaks existing fin callers | low | medium | `AgentAnalysis.from_legacy(text)` shim for one release cycle |
| Prompt versioning adds cost from extra logging | low | low | Log locally to SQLite, no LLM call |
| fleet launcher race condition on concurrent task claim | low | medium | SharedTaskQueue already uses atomic claim; stress-test in Phase 4 |

---

## 7. Cost model (inherits Investment v1 Round 2)

| Line item | Day 1 | Month 1 |
|---|---|---|
| Finnhub | $0 | $0 (60 req/min free) |
| Alpha Vantage | $0 | $0 (500/day free, fallback only) |
| LLM (local DeepSeek/z.ai via router) | $0 | $0–$15 depending on fleet task volume |
| Dashboard hosting | $0 | $0 (localhost) |
| **Total** | **$0** | **$0–$15** |

---

## 8. User answers (locked 2026-04-12)

1. **Go.** Plan approved.
2. **Priority order:** 0 → 1 → 2 → 3 → 4 → 5, 6 deferred. **Guardrail: fleet must stay persona-agnostic.** `fin-core` is one of many projects; `coding` must still be able to spin up its own fleet project (e.g., `coding-refactor-sprint`). Phase 4's `FleetLauncher._run_member` LLM loop must be persona-generic — no hardcoded fin imports, no fin-only tests in fleet/. If Phase 4 grows more complex than planned, pause and discuss with user.
3. **First real project:** `us-growth-2026Q2`. Phase 0.3 scaffolds it.
4. **LLM budget:** local router only (router already has local LLM + cloud API fallback chain), **$15/month cap**. Phase 4 must not bypass the router.
5. **Canary tolerance:** `gate_b3` OK at every phase end, **BUT** fin-only gate_b3 is insufficient for the "no other persona regresses" constraint. Every phase also runs: (a) coding CLI 3-scenario smoke (tests/integration/cli_tester_iterm2.py), (b) chat Telethon smoke (1-2 scenarios), (c) at Phase 4 only, a `coding-fleet-smoke` project.yaml end-to-end test to prove fleet works for non-fin personas too. If any other personality or baseline feature regresses, that phase fails gate.

---

## 9. Status log (append only)

| Date | Phase | Status | Evidence | Notes |
|---|---|---|---|---|
| 2026-04-12 | plan authored | DRAFT | this file | awaiting user approval |
| 2026-04-12 | user Q&A locked | APPROVED | §8 | 5 answers + persona-agnostic fleet guardrail + expanded regression tests |
| 2026-04-12 | Phase 0.1 dropped | CORRECTED | §1.2 + §4 Phase 0 | grep proved 18 "shims" have 20+ real callers incl. docker-entrypoint.sh; renumbered Phase 0 to 0.A/0.B/0.C (firewall + scaffold + tests only) |
