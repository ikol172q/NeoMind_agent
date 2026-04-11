# Slash Command Taxonomy — v5 (2026-04-10)
## With Comprehensive Validation Suite

**Status:** Authoritative reference for remaining Phase B work
**Author:** Session of 2026-04-10, designed with Claude Opus 4.6

## Version history

- **v1** (2026-04-10, morning): First-pass 4-tier categorization. **Rejected** — lumped different problems together, no separation between feature cleanup vs architectural migration.
- **v2** (2026-04-10, midday): Refined to 18 slashes + 22 tools. **Rejected** — group-chat use case missing, several structural errors found during review.
- **v3** (2026-04-10, late-midday): 22 slashes + 23 tools, group chat via thin wrappers. **Rejected in Round 4** — grep audit exposed that ~8 commands I labeled "dead code" were actually real non-trivial features (`/sprint`, `/persona`, `/rag`, `/tune`, etc.).
- **v4** (2026-04-10, evening): Per-command grep-verified audit. **Taxonomy correct but missing validation framework.**
- **v5 (THIS DOCUMENT, 2026-04-10 late)**: v4 taxonomy preserved + **full Telethon validation suite** (~108 scenarios + 5 unit tests) + **per-commit validation gates** + **tester subagent orchestration pattern**. This is the version that execution follows.

## What changed in v5 vs v4

- **No taxonomy changes.** v4 categories stand: 9 Tier 1 + 5 Tier 2 + 4 Tier 3 + 11 Tier 4 + 4 deletions + 3 dual-entry.
- **Adds**: a full validation scenario library (108 Telethon scenarios + 5 unit tests) covering every change this session makes to the slash surface.
- **Adds**: per-phase validation gates — which scenario subset must PASS before advancing.
- **Adds**: tester subagent orchestration pattern — how to invoke validation cleanly without being both athlete and referee.
- **Adds**: rollback criteria.

---

## Execution status as of v5 write

### Already committed (this session)

| Commit | Scope | Validation done |
|---|---|---|
| `4847c6a` | Delete `_LLM_ROUTED_COMMANDS` + graceful slash fallthrough | 3 manual probes only — **insufficient**, owed R+F validation |
| `5c8d76e` | v4 audit doc only | docs, no validation needed |
| `ff141eb` | Delete `/setctx` `/archive` `/purge` `/memory`, promote `/tune` to Tier 1 menu | 4 manual probes only — **insufficient**, owed R+D+T validation |
| `eea40a0` | `ToolDefinition.allowed_modes` + `ToolRegistry.get_all_tools(mode)` | 1 in-process smoke test only — **insufficient**, owed R regression + unit test |

### Remaining Phase B work (not yet started)

| Sub-phase | Scope | Estimated effort |
|---|---|---|
| B.2 | Create `agent/tools/finance_tools.py` with 10 fin tool functions (nobody calls them yet) | ~40 min |
| B.3 | Register fin tools in telegram_bot's agentic loop with `allowed_modes={"fin"}` | ~15 min |
| B.4 | Pass current mode into `get_all_tools(mode)` at the tool-prompt build site | ~20 min |
| B.5 | Refactor 5 Tier 2 slash handlers (`_cmd_stock` etc.) into thin wrappers over the tool functions | ~30 min |
| B.6 | 3 dual-entry tools (`web_hn_top`, `finance_persona_debate`, `finance_rag_query`) | ~30 min |

### Final validation gate

Run the **full 108-scenario Telethon suite + 5 unit tests** against the final commit of Phase B. Must pass 100% of the 30 regression baseline, must pass 100% of the change-specific scenarios (F, D, T, A, N, E, G), must pass all 5 unit tests. Pre-existing flakes (max 4: S03/S06/U01/U02 from original baseline) are tolerated if and only if they were already failing pre-session.

---

## Final v4/v5 Taxonomy (unchanged since v4)

### 🟢 Tier 1 — User-facing meta (9 commands, visible in `/help` and `set_my_commands`)

| Command | Purpose |
|---|---|
| `/start` | Telegram onboarding |
| `/help` | Capability discovery grouped by ability |
| `/status` | mode + model + router + usage quick view |
| `/mode chat\|coding\|fin` | Personality switch |
| `/model <id>\|reset` | LLM switch within mode |
| `/think` | Thinking mode toggle |
| `/clear` | Archive + wipe conversation |
| `/usage` | LLM cost query |
| `/tune` | Edit NeoMind's prompt/config at runtime (self-evolution UX) |

### 🟢 Tier 2 — Fin quick-access (5 commands, thin wrappers over finance_* tools)

| Command | Tool |
|---|---|
| `/stock <symbol>` | `finance_get_stock` |
| `/crypto <symbol>` | `finance_get_crypto` |
| `/news <query>` | `finance_news_search` |
| `/digest` | `finance_market_digest` |
| `/market` | `finance_market_overview` |

### 🟡 Tier 3 — Fin write-state (4 commands, permanently slash)

`/alert` `/watchlist` `/portfolio` `/subscribe`

### 🔵 Tier 4 — Admin / advanced (11 commands, hidden from default `/help`, still accessible)

`/restart` `/evolve` `/admin` `/history` `/context` `/sprint` `/evidence` `/careful` `/persona` `/rag` `/skills` `/hooks`

### ❌ Deleted (4 commands)

`/setctx` `/memory` `/archive` `/purge` — all were pure aliases or had no real handler.

### 🔗 Dual-entry (3 — slash AND tool)

`/hn` ↔ `web_hn_top` · `/persona` ↔ `finance_persona_debate` · `/rag` ↔ `finance_rag_query`

### 🛠 Tools (23 total)

**Shared (4):** `web_search`, `web_fetch`, `web_extract_links`, `web_crawl`

**Fin-only (10):** `finance_get_stock`, `finance_get_crypto`, `finance_market_overview`, `finance_news_search`, `finance_market_digest`, `finance_compute`, `finance_economic_calendar`, `finance_risk_calc`, `finance_portfolio_show`, `finance_watchlist_show`

**Dual-entry (3):** `web_hn_top`, `finance_persona_debate`, `finance_rag_query`

**Coding-only (9, DEFERRED to Phase D next session):** `code_read_file`, `code_edit_file`, `code_run_command`, `code_grep`, `code_find_files`, `code_git`, `code_run_tests`, `code_apply_patch`, `code_write_file`

---

## Validation Framework

### Scenario library — 108 Telethon scenarios

The scenario library is stored in `/tmp/test_telegram_baseline.py` as a list of tuples `(sid, send, wait_seconds, expect_any_substrings, category)`. Tester subagent runs them via the existing `TelegramBotTester` driver from `/tmp/neomind_telegram_tester.py`.

#### Category R — Regression baseline (30 scenarios, already exists)

| SID | Send | Wait | Expect any |
|---|---|---|---|
| F01-F06 | Finance: /quant + DCF/Fama-French/Sharpe/moat no-search Q&A | 90-120s | domain keywords |
| M01-M06 | /mode fin, /model, /mode coding, /model, /mode fin, /status | 10-15s | model names, mode names |
| Q01-Q06 | Chinese Q&A no-search: 市盈率, 夏普, ETF, 美元微笑, DCA, risk parity | 90s | domain terms |
| S01-S06 | Search queries: 今天 SPY, 美元指数, Buffett quotes, BTC, CAPM, 财经新闻 | 60-90s | symbols, relevant terms |
| U01-U06 | /status, /context, /usage, /help, /think, /clear | 10-15s | command output signatures |

**Purpose:** Catch regression in any pre-existing functionality.

#### Category F — Graceful slash fallthrough (10 scenarios, NEW for this session)

Validates `4847c6a`: deleted pseudo-commands should produce natural-language responses.

| SID | Send | Wait | Expect any |
|---|---|---|---|
| F_F01 | `/summarize 苹果公司 一句话介绍` | 60s | `苹果`, `Apple`, `科技`, `iPhone` |
| F_F02 | `/explain 什么是 Black-Scholes 模型 不要搜索` | 90s | `Black-Scholes`, `期权`, `定价`, `波动率` |
| F_F03 | `/tldr 中国新能源汽车市场 2025 概况 不要搜索` | 90s | `电动`, `新能源`, `市场`, `比亚迪`, `特斯拉` |
| F_F04 | `/deep 对冲基金做空策略的核心思路 不要搜索` | 90s | `做空`, `对冲`, `策略`, `杠杆`, `风险` |
| F_F05 | `/refactor 这段话更简洁: "请问你能告诉我现在是几点吗"` | 45s | `几点` or 更短版本 or `现在` |
| F_F06 | `/translate 牛市 英文是什么 不要搜索` | 30s | `bull`, `market` |
| F_F07 | `/totallyfake 用一句话解释 CAPM 不要搜索` | 60s | `CAPM`, `beta`, `市场`, `Rf`, `无风险` |
| F_F08 | `/` (空 slash，只有斜杠) | 15s | `help` or `?` or `命令` or 任何非错误回复 |
| F_F09 | `/randomword 请给我今天心情不好的三个安慰` | 60s | `心情`, `安慰`, `加油` |
| F_F10 | `/unknownxyz 巴菲特最著名的投资原则` | 60s | `巴菲特`, `Buffett`, `价值` |

**Purpose:** Verify that removed slash commands and arbitrary unknown slashes graceful-fall through to natural-language processing.

#### Category D — Deletion graceful handling (6 scenarios, NEW)

Validates `ff141eb`: deleted commands `/setctx` `/archive` `/purge` `/memory` should not produce "unknown command" errors.

| SID | Send | Wait | Expect any |
|---|---|---|---|
| D01 | `/archive` | 30s | graceful reply, no "未知命令" or exception |
| D02 | `/purge 历史` | 30s | graceful reply, no error |
| D03 | `/setctx test value` | 30s | graceful reply, no error |
| D04 | `/memory` | 30s | graceful reply, no error |
| D05 | `/clear` (canonical still works) | 15s | `归档`, `清空`, `✓` |
| D06 | `/admin stats` (canonical admin still works) | 15s | `Stats`, `database`, `messages`, `总数`, `chats` |

**Purpose:** Verify the 4 deleted commands are handled gracefully and that canonical alternatives still work.

#### Category T — /tune sub-commands (8 scenarios, NEW)

Validates `ff141eb` promotion of `/tune` to Tier 1.

| SID | Send | Wait | Expect any |
|---|---|---|---|
| T01 | `/tune` (usage help) | 15s | `tune`, `prompt`, `reset`, `trigger` |
| T02 | `/tune status` | 15s | `配置`, `status`, `当前`, `默认`, `无` |
| T03 | `/tune prompt 回复请更简洁些` | 15s | `已`, `追加`, `prompt`, `更简洁` |
| T04 | `/tune status` (after T03) | 15s | `更简洁` (confirms prompt was persisted) |
| T05 | `/tune trigger add 半导体` | 15s | `已`, `添加`, `trigger`, `半导体` |
| T06 | `/tune reset` | 15s | `已重置`, `重置`, `reset`, `默认` |
| T07 | `/tune status` (after reset) | 15s | `默认`, `无`, `empty`, `(none)` |
| T08 | `/tune 让搜索结果更偏向中文新闻源` (natural language tune) | 45s | `已`, `中文`, `新闻`, `搜索`, `源` |

**Purpose:** Verify `/tune` is fully functional as a Tier 1 command, including the natural-language tune path.

#### Category A — Tier 4 admin command coverage (12 scenarios, NEW)

Validates that all "real handler" commands from the v4 audit still work.

| SID | Send | Wait | Expect any |
|---|---|---|---|
| A01 | `/sprint` (help) | 15s | `Sprint`, `new`, `status`, `next` |
| A02 | `/sprint new 研究 AAPL 估值` | 30s | `Sprint`, `✅`, `id`, `created` |
| A03 | `/sprint status` | 15s | `Sprint`, `phase`, `进度`, `status` |
| A04 | `/evidence` (recent entries) | 15s | `Evidence`, `trail`, `audit`, `entries`, `记录` |
| A05 | `/careful` (toggle) | 15s | `careful`, `ON`, `OFF`, `safety`, `guard` |
| A06 | `/persona list` | 15s | `persona`, `投资`, `价值`, `增长`, `contrarian` |
| A07 | `/rag stats` | 15s | `RAG`, `stats`, `索引`, `文档`, `enabled`, `未启用` |
| A08 | `/skills` | 15s | `skills`, `available`, `mode`, `skill`, `模式` |
| A09 | `/hn top` | 30s | `Hacker News`, `HN`, `top`, `upvotes`, `story` |
| A10 | `/hooks` | 15s | `hooks`, `钩子`, `diagnostic`, `registered`, `active` |
| A11 | `/history` | 15s | `messages`, `history`, `active`, `消息` |
| A12 | `/context` | 15s | `Context`, `context`, `tokens`, `window`, `占用` |

**Purpose:** Prove every real-handler command survives the cleanup and still produces its expected output.

#### Category N — Fin-mode natural-language tool triggering (15 scenarios, POST Phase B.2-B.5)

Validates that when the user asks a fin question in natural language, the LLM correctly emits `<tool_call>finance_*</tool_call>` and the agentic loop returns real data.

| SID | Send | Wait | Expect any |
|---|---|---|---|
| N01 | `苹果今天股价大概多少` | 60s | `Apple`, `AAPL`, `$`, 具体价格数字 |
| N02 | `特斯拉今天收盘价` | 60s | `TSLA`, `Tesla`, `$`, 价格 |
| N03 | `BTC 今天多少美元` | 60s | `BTC`, `Bitcoin`, `$`, 价格 |
| N04 | `ETH 今天现价` | 60s | `ETH`, `Ethereum`, `$` |
| N05 | `今天美股三大指数怎么样` | 90s | `S&P`, `纳斯达克`, `道琼斯`, `指数`, 数字 |
| N06 | `给我今天的市场摘要` | 120s | `市场`, `digest`, `今日`, 多个板块 |
| N07 | `帮我算一下 10000 元 8% 年化复利 10 年的终值` | 60s | `21589`, `21,589`, `$21`, 或 `1.08^10 = 2.158` |
| N08 | `初值 100 终值 200 五年的 CAGR 是多少` | 60s | `14.87`, `14.87%`, `CAGR` |
| N09 | `最近有什么关于半导体的新闻` | 90s | `半导体`, `芯片`, `新闻`, `TSMC` or `SMCI` |
| N10 | `下周有什么重要经济数据发布` | 60s | `CPI`, `PPI`, `NFP`, `PMI`, 或日期 |
| N11 | `AAPL 的 Sharpe ratio 大概是多少` (approximation question) | 60s | `Sharpe`, 数字 or 解释 |
| N12 | `我的持仓列表` | 30s | `portfolio`, `持仓`, `holdings`, `empty`, `空` |
| N13 | `我的关注列表` | 30s | `watchlist`, `关注`, `empty`, `list`, `空` |
| N14 | `从价值投资角度分析 AAPL` | 90s | `价值`, `Buffett`, `Graham`, `moat`, `安全边际` |
| N15 | `从文档里查 Apple 的最新营收指引` (RAG) | 60s | `Apple`, `营收`, `revenue`, `guidance`, `未启用` or 真实结果 |

**Purpose:** Verify the Phase B.5 thin-wrapper refactor keeps natural-language paths working AND that the LLM actually invokes the new `finance_*` tools.

#### Category E — Dual-entry equivalence (6 scenarios, POST Phase B.5)

Validates that `/stock AAPL` and "苹果今天多少钱" produce substantively equivalent data.

| SID | Send | Wait | Expect any | Then compare to |
|---|---|---|---|---|
| E01 | `/stock AAPL` | 30s | `AAPL`, `Apple`, `$`, price | E02 |
| E02 | `苹果今天多少钱` | 60s | `AAPL`, `Apple`, `$`, price | should contain same ticker + price |
| E03 | `/crypto BTC` | 30s | `BTC`, `Bitcoin`, `$`, price | E04 |
| E04 | `BTC 现价` | 60s | `BTC`, `Bitcoin`, `$`, price | should contain same price |
| E05 | `/persona list` | 15s | `价值`, `增长`, `contrarian` | E06 |
| E06 | `列出所有可用的投资人格` | 30s | `价值`, `增长`, `contrarian` | should list same personas |

**Purpose:** Prove the dual-entry architecture (slash + tool) returns consistent data from either entry point.

#### Category G — Group chat (8 scenarios, manual or skip if private-only)

These require a test group chat. Tester subagent skips them if it can't access a group context. Marked as **optional** in the suite.

| SID | Send (in group) | Wait | Expect any |
|---|---|---|---|
| G01 | `/status@neomindbot` | 15s | `status`, `kimi`, `router` |
| G02 | `@neomindbot 苹果今天多少` | 60s | `AAPL`, `$`, price |
| G03 | `/stock@neomindbot AAPL` | 30s | `AAPL`, `$`, price |
| G04 | `/clear@neomindbot` | 15s | `归档`, `clear` |
| G05 | random non-mention message | 10s | NO reply (bot should not auto-respond) |
| G06 | `/help@neomindbot` | 15s | `commands`, `help` |
| G07 | `@neomindbot 什么是 PE 不要搜索` | 60s | `市盈率`, `PE` |
| G08 | `/mode@neomindbot fin` | 15s | `fin`, `已切换` |

**Purpose:** Verify group chat slash/mention triggering works. Skip if no test group available.

#### Category C — Context / multi-turn (8 scenarios)

| SID | Send | Wait | Expect any |
|---|---|---|---|
| C01 | `假设我持有 100 股 AAPL` (setup context) | 45s | `持有`, `noted`, `了解`, `Apple`, `100` |
| C02 | `如果股价涨到 300 我赚多少` (follow-up, requires C01 context) | 60s | `赚`, `profit`, `收益`, 计算结果 |
| C03 | `/clear` | 15s | `归档`, `clear` |
| C04 | `如果股价涨到 300 我赚多少` (same question post-clear, no context) | 60s | clarify, `哪个股票`, `没有上下文`, 追问 |
| C05 | `今天天气不错` (short chat) | 30s | 任意合理回复 |
| C06 | `接着我们之前说的` (ambiguous follow-up) | 60s | clarify, `请问你指的是` |
| C07 | `/context` | 15s | `tokens`, `messages`, `占用` |
| C08 | very long query (~500 chars, 中英混合) | 120s | 合理回复 |

**Purpose:** Verify multi-turn context handling, clear behavior, and large-input handling.

#### Category X — Edge cases (10 scenarios)

| SID | Send | Wait | Expect any |
|---|---|---|---|
| X01 | `//status` (double slash) | 15s | fallthrough or status |
| X02 | `/` (bare slash) | 15s | graceful reply |
| X03 | `/stock` (no argument) | 15s | `Usage` or `用法` |
| X04 | `/stock XYZNOTREAL` (unknown symbol) | 30s | `not found`, `未找到`, `No data` |
| X05 | `/crypto` (no argument) | 15s | `Usage` or `用法` |
| X06 | `/mode invalidmode` (unknown mode) | 15s | `invalid`, `chat`, `coding`, `fin`, `unknown` |
| X07 | `/model nonexistent-model` | 15s | `not found`, `invalid`, 或 fallback 保留旧模型 |
| X08 | emoji-only message: `🚀🚀🚀` | 30s | 任意合理回复 |
| X09 | repeated identical question (rate-limit check): ask `你好` three times fast | 60s total | 三次都回应 |
| X10 | 超长输入 (~4000 chars) | 120s | 回复 or 超长错误 |

**Purpose:** Stress test edge cases without crashing.

### Unit tests (5, not Telethon)

Located in `tests/test_mode_gating.py` (to be created in Phase B.1 follow-up).

| Test | Verifies |
|---|---|
| `test_tool_with_fin_mode_only_visible_in_fin` | `ToolDefinition(allowed_modes={"fin"}).is_available_in_mode("fin") == True` and `"chat") == False` |
| `test_tool_without_allowed_modes_always_visible` | Legacy tools (no allowed_modes) visible in all modes |
| `test_none_mode_preserves_legacy_behavior` | `is_available_in_mode(None)` returns True regardless of allowed_modes |
| `test_registry_get_all_tools_filters_by_mode` | `ToolRegistry.get_all_tools(mode="fin")` returns only fin-visible tools |
| `test_registry_get_all_tools_none_returns_all` | `ToolRegistry.get_all_tools()` (default None) returns everything (backward compat) |

---

## Per-phase validation gates

### Gate 0 — Current state (retroactive)

Cover the 3 commits that weren't properly validated: `4847c6a`, `ff141eb`, `eea40a0`.

**Required to PASS before advancing:**
- ✅ R (30 regression) — must match or exceed 26/30 (the pre-cleanup baseline post-791dde81)
- ✅ F (10 fallthrough) — all PASS
- ✅ D (6 deletion graceful) — all PASS
- ✅ T (8 /tune sub-commands) — all PASS
- ✅ A (12 Tier 4 admin) — at least 10/12 PASS (allow 2 flakes for module-init issues)
- ✅ Unit tests (5) — all 5 PASS

**Total:** 66 Telethon + 5 unit = 71 checks.

**Estimated runtime:** ~45 minutes.

### Gate B.2 — After fin tools module written

After `agent/tools/finance_tools.py` is implemented (Phase B.2). At this point no fin tool is wired into the bot yet, so only unit-test the module itself.

**Required:**
- ✅ Import-smoke: module imports cleanly
- ✅ Per-function unit tests: each of the 10 fin tool functions returns expected shape on known inputs (mocked data hub)
- ✅ Gate 0 scenarios — re-run, must still pass (regression floor)

### Gate B.3 — After fin tools registered in agentic registry

Phase B.3 + B.4 together: tools registered with `allowed_modes={"fin"}`, mode passed into `get_all_tools()`.

**Required:**
- ✅ Gate 0 scenarios — still pass
- ✅ Unit test: `fin` mode sees `finance_*` tools, `chat` mode does not
- ✅ N (15 natural-language tool triggering) — at least 12/15 PASS (allow 3 flakes for LLM tool-call hallucinations)

### Gate B.5 — After Tier 2 slash refactored to thin wrappers

Phase B.5: `_cmd_stock`, `_cmd_crypto`, `_cmd_news`, `_cmd_digest`, `_cmd_market` now delegate to `finance_*` tools.

**Required:**
- ✅ Gate 0 + Gate B.3 scenarios — still pass
- ✅ E (6 dual-entry equivalence) — at least 5/6 PASS

### Gate B.6 — After dual-entry tools

Phase B.6: `web_hn_top`, `finance_persona_debate`, `finance_rag_query` registered as both slash and tool.

**Required:**
- ✅ Gate 0 + B.3 + B.5 scenarios — still pass
- ✅ A09 `/hn` still works (slash entry)
- ✅ A06 `/persona list` still works (slash entry)
- ✅ A07 `/rag stats` still works (slash entry)
- ✅ Natural-language "Hacker News top 5" triggers tool

### Final Gate — Phase B complete

**Required:**
- ✅ **All 108 Telethon scenarios + 5 unit tests run against final HEAD**
- ✅ R: at least 28/30 (allow 2 pre-existing flakes)
- ✅ F: 10/10
- ✅ D: 6/6
- ✅ T: 8/8
- ✅ A: 11/12
- ✅ N: 13/15
- ✅ E: 5/6
- ✅ C: 7/8
- ✅ X: 8/10
- ✅ G: skipped or 6/8 if test group available
- ✅ Unit tests: 5/5

**Failing any of these = Phase B NOT complete**, fixer returns to patch and the failed gate re-runs.

---

## Tester subagent orchestration pattern

Each validation gate runs via a **dedicated tester subagent** (fresh instance, no prior context). The pattern:

```
fixer (me): finish code change
fixer: syntax/import verification
fixer: git commit
                    ↓
tester subagent (new instance): 
  1. pre-flight: verify git HEAD, bot uptime, test plan integrity
  2. run the gate's required scenario set from /tmp/test_telegram_baseline.py
  3. monitor bot health every 2-3 min during run
  4. if agent.log is silent >3 min during active test → ABORT and report
  5. compare to expected PASS counts per gate
  6. report: PASS / FAIL + delta vs previous run + any lingering regressions
                    ↓
fixer: read report
if FAIL → diagnose, patch, re-commit, new tester subagent
if PASS → advance to next phase
```

**Key rules:**
- Tester must be a **new subagent per validation run** (no contamination from prior state)
- Tester must NOT edit any source code (role separation)
- Tester must NOT run destructive git commands
- Tester must use the venv python (`.venv/bin/python`)
- Tester reports must include: scenario counts by verdict, regression delta, hang detection, supervisord restarts during run

---

## Rollback criteria

If any gate FAILS and can't be patched within 2 attempts:

1. **Tier-A rollback (local)**: `git revert <commit>` + tester re-runs previous gate
2. **Tier-B rollback (multi-commit)**: `git reset --hard <last-passing>` **only if the working tree is clean** (committed WIP protection — see memory `feedback_never_reset_hard_with_wip.md`)
3. **Tier-C rollback (architecture)**: Abandon Phase B for this session, keep Phase A progress (commits `4847c6a`, `ff141eb`, `eea40a0`), revisit Phase B in next session with a cleaner design

---

## Scenario file layout

The scenarios above will be encoded into a Python file that the tester subagent executes:

**File:** `tests/qa_archive/plans/2026-04-10_comprehensive_validation_suite.py`
**Format:**
```python
SCENARIOS = [
    # Category R — regression baseline (30)
    ("F01", "/quant CAGR 100 200 5", 90, ["CAGR", "%", "14"], "regression"),
    ...
    # Category F — fallthrough (10)
    ("F_F01", "/summarize 苹果公司 一句话介绍", 60, ["苹果", "Apple", "科技"], "fallthrough"),
    ...
    # Category D — deletion graceful (6)
    ("D01", "/archive", 30, [""], "deletion_graceful"),  # empty expect = "any non-error"
    ...
]

SUBSETS = {
    "gate_0": ["R_*", "F_*", "D_*", "T_*", "A_*"],
    "gate_b3": ["R_*", "F_*", "D_*", "T_*", "A_*", "N_*"],
    "gate_b5": ["R_*", "F_*", "D_*", "T_*", "A_*", "N_*", "E_*"],
    "gate_final": ["*"],
}
```

This file is the **single source of truth** for the validation suite. Tester subagents reference it by subset name.

---

## What this plan guarantees

1. **Every commit is validated against a real Telegram scenario set**, not just manual probes.
2. **Every new feature has explicit validation scenarios** that verify it works AS DESIGNED.
3. **Regression is caught at every gate**, not just at the end.
4. **Mode-gating, thin wrapper, dual-entry, fallthrough — every architectural change has a scenario**.
5. **Tester subagent discipline is enforced**: no ad-hoc manual probes claimed as "validation".
6. **Rollback path exists** for every gate.
7. **The validation scenarios are version-controlled** so next session can re-run the same gates.

## What this plan does NOT guarantee

- **Voice input path** — can't be simulated via Telethon, requires real phone
- **Image upload path** — same
- **Multi-user group chat dynamics** — scenarios G01-G08 are optional, require test group
- **Network flake scenarios beyond X10** — can't deterministically simulate DDG hangs etc.
- **Coding mode tool behavior** — deferred to Phase D (next session)

These are known limitations and are documented as non-goals for this session.

---

## Appendix A — Memory links

This plan is reinforced by the following memories in `~/.claude/projects/.../memory/`:

- `feedback_never_reset_hard_with_wip.md` — protect uncommitted WIP
- `feedback_never_categorize_without_grep.md` — verify dead code via grep before deletion
- `feedback_per_commit_tester_validation.md` — every commit needs tester subagent + change-specific scenarios
- `feedback_fin_mode_is_chat_not_slash.md` — user prefers natural language in fin mode
- `feedback_skip_stock_command_in_qa.md` + `feedback_skip_crypto_command_in_qa.md` (superseded by above)
- `feedback_verify_bot_health.md` — probe bot every ~3 min during long tests
- `feedback_use_neo_venv.md` — always use `.venv/bin/python`
