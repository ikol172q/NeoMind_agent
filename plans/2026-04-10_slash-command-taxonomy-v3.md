# Slash Command Taxonomy — v3 (2026-04-10)

**Status:** Approved for implementation
**Author:** Session of 2026-04-10, designed with Claude Opus 4.6
**Version history:**
- v1 (2026-04-10 early): First-pass 4-tier categorization. Rejected — lumped different problems together.
- v2 (2026-04-10 mid): Refined to 18 slashes + 22 tools, surfaced 7 structural errors from v1. Rejected — group-chat use case missing, several more issues.
- **v3 (2026-04-10 late, THIS DOCUMENT):** Final. 22 slashes + 23 tools. Group chat supported via thin-wrapper pattern. Survived 5+ review rounds.

## Problem Statement

As of commit `91dde81`, the NeoMind Telegram bot registered ~70 slash commands across three sources:

1. 30 explicit `CommandHandler` registrations
2. 15 finance commands registered via a loop (`/stock`, `/crypto`, `/news`, …)
3. 40+ pseudo-commands in `_LLM_ROUTED_COMMANDS` that simply forwarded the text to the LLM

Problems with the legacy surface:
- Most commands were **half-baked**: 40+ "pseudo-commands" in `_LLM_ROUTED_COMMANDS` had no real handler; they prepended a slash to a prompt and fed it to the LLM
- The command set was **discovered, not designed**: no coherent interaction model, no mode awareness, no user-vs-LLM separation
- `/help` listed ~70 commands, most of which users never type and most of which duplicate natural language
- Several commands were **stale legacy** (`/provider` no longer valid after the LLM Router refactor)
- No separation between **"what the user types"** and **"what NeoMind can invoke internally"**

## Guiding Principles

1. **Chat-first, tool-augmented, admin-separate.** The bot is a natural-language assistant. Slash commands exist only for meta control, destructive ops, write-state protection, admin fast-paths, and group-chat convenience.
2. **Capabilities live in tools, not slashes.** Data lookups, computations, and side-effect-free operations belong in the agentic tool registry so the LLM can invoke them mid-reasoning. Slashes that expose these same capabilities are **thin wrappers** over the tool functions, never duplicate implementations.
3. **Mode-gated tools.** A `chat` mode LLM should not see `finance_get_stock` in its tool list. The tool registry filters by `allowed_modes` so each personality gets exactly the tools it needs.
4. **Graceful migration.** Unknown slash commands auto-strip the `/` prefix and fall through to natural-language processing, so user muscle memory survives even for deleted commands.
5. **Don't over-engineer for features that don't exist yet.** Keep the command surface minimal now so later additions have headroom.
6. **Multi-channel input support.** Voice, images, typing — slash must be optional for all core capabilities so voice users aren't locked out.

## Final Taxonomy

### Tier 1 — User-facing meta (8 commands, shown in default `/help`)

These control the bot itself. Natural language has no reliable substitute for explicit, destructive, or canonical state changes.

| Command | Purpose | Why slash (not natural language) |
|---|---|---|
| `/start` | Telegram convention, onboarding | Platform requirement |
| `/help` | Capability discovery, grouped by ability | Canonical, high frequency |
| `/status` | mode + model + router + usage quick view | High-frequency canonical diagnostic |
| `/mode chat\|coding\|fin` | Switch personality | Explicit state change |
| `/model <id>\|reset` | Switch LLM within current mode | Technical model names |
| `/think` | Toggle thinking mode | Boolean toggle |
| `/clear` | Archive + wipe current conversation | **Destructive, must be explicit** |
| `/usage` | Today / week / month LLM cost | Canonical cost query |

### Tier 2 — Fin mode quick-access (5 commands, shown in `/help`)

Thin slash wrappers over `finance_*` tools. Value comes from:
1. **Group chat**: team members expect `/stock AAPL@bot` as a primary interaction mode
2. **Speed**: direct handler = ~0.5s, vs LLM tool roundtrip = ~6s
3. **Cost**: direct handler = 0 tokens, vs LLM roundtrip = ~$0.002/call
4. **Determinism**: no LLM ambiguity

| Command | Bound tool | Group chat value |
|---|---|---|
| `/stock <symbol>` | `finance_get_stock` | Team watchlist pings |
| `/crypto <symbol>` | `finance_get_crypto` | Same |
| `/news <query>` | `finance_news_search` | Drop a query, skim headlines |
| `/digest` | `finance_market_digest` | Daily team briefing |
| `/market` | `finance_market_overview` | Quick market check |

**Critical design constraint:** each slash handler is a ~5-line thin wrapper that calls the underlying tool function and formats the return dict for Telegram. The tool function is the single source of truth for the capability.

### Tier 3 — Fin write-state (4 commands, permanently slash)

State-mutating operations where NLU false-positives would corrupt user data. These do NOT get tool versions until a read-your-write UI exists.

| Command | Why permanent slash |
|---|---|
| `/alert <symbol> above\|below <price>` | Multi-param write with triggering semantics |
| `/watchlist add\|remove\|list [symbol]` | Write state; ambiguous entity resolution |
| `/portfolio add\|remove\|show [args]` | Multi-param write; data hygiene critical |
| `/subscribe daily\|weekly\|off` | Push notification state |

### Tier 4 — Admin / ops (5 commands, hidden from default `/help`)

Shown only via `/help admin` or when admin-authenticated. Used for operations and self-modification management.

| Command | Purpose |
|---|---|
| `/restart` | Graceful agent process restart via supervisord |
| `/evolve list\|last\|status\|revert` | Self-evolution transaction management |
| `/history list\|archive\|purge` | Conversation history (merges old `/archive`, `/purge`) |
| `/context` | Context window usage diagnostic |
| `/admin` | Admin operations (needs code verification) |

**Total slash commands: 22** (down from ~70).

---

## Agentic Tools Registry

Tools are invoked by the LLM via `<tool_call>name</tool_call>` syntax during agentic reasoning. The registry filters by `allowed_modes` so each personality sees only relevant tools.

### Naming convention

`{domain}_{verb}_{object}` where domain is one of `web`, `finance`, `code`.

### Shared tools (4) — `allowed_modes = {chat, coding, fin}`

All modes can access these.

| Tool | Signature | Replaces |
|---|---|---|
| `web_search` | `(query: str, max_results: int = 5) -> list[SearchResult]` | Existing `WebSearch` |
| `web_fetch` | `(url: str) -> PageContent` | `/read` slash |
| `web_extract_links` | `(url: str) -> list[Link]` | `/links` slash |
| `web_crawl` | `(url: str, depth: int = 2) -> list[PageContent]` | `/crawl` slash |

### Fin-only tools (10) — `allowed_modes = {fin}`

The centerpiece of fin-mode evolution.

| Tool | Signature | Replaces |
|---|---|---|
| `finance_get_stock` | `(symbol: str, market: str = "us") -> StockData` | `/stock` handler core |
| `finance_get_crypto` | `(coin_id: str) -> CryptoData` | `/crypto` handler core |
| `finance_market_overview` | `() -> MarketSnapshot` | `/market` |
| `finance_news_search` | `(query: str, days: int = 3) -> list[Article]` | `/news` |
| `finance_market_digest` | `() -> Digest` | `/digest` |
| `finance_compute` | `(formula: str, **args) -> ComputeResult` | `/quant`, `/compute`, `/risk` — unified: cagr, compound, sharpe, sortino, npv, irr, bs |
| `finance_economic_calendar` | `(days: int = 7) -> list[Event]` | `/calendar` |
| `finance_risk_calc` | `(...) -> RiskMetrics` | `/risk` variants |
| `finance_portfolio_show` | `() -> PortfolioSummary` | Read-only portfolio view |
| `finance_watchlist_show` | `() -> list[WatchItem]` | Read-only watchlist view |

### Coding-only tools (9) — `allowed_modes = {coding}` — **DEFERRED TO PHASE D / NEXT SESSION**

Requires permission framework, diff-preview UX, and rollback system. Not in scope for this session.

| Tool | Signature | Future purpose |
|---|---|---|
| `code_read_file` | `(path: str) -> str` | Read source file |
| `code_edit_file` | `(path: str, old: str, new: str) -> Diff` | Precise edit |
| `code_run_command` | `(cmd: str, timeout: int) -> Output` | Shell execution (permission-gated) |
| `code_grep` | `(pattern: str, glob: str) -> list[Match]` | Code search |
| `code_find_files` | `(glob: str) -> list[Path]` | File search |
| `code_git` | `(op: str, args: list) -> GitResult` | git status/diff/log/show |
| `code_run_tests` | `(path: str) -> TestReport` | pytest/npm test |
| `code_apply_patch` | `(patch: str) -> ApplyResult` | Unified diff apply |
| `code_write_file` | `(path: str, content: str) -> None` | Create new file |

**Total tools: 23** (14 in this session, 9 deferred).

---

## What Gets Deleted (~45 commands)

### Group A — `_LLM_ROUTED_COMMANDS` set (~35 commands)

Delete the set entirely. The `_handle_unknown_command` fallthrough is changed to:

```python
# OLD: return "未知命令" error
# NEW: if text starts with /, strip the slash and treat as natural language
if text.startswith("/"):
    bare = text[1:]  # strip slash, keep rest
    await self._process_and_reply(update, bare, "natural_fallthrough")
```

This means any deleted slash command like `/summarize this paragraph` becomes `summarize this paragraph` which the LLM handles naturally. **Zero migration friction, zero user breakage, zero deprecation period needed.**

Commands in this group: `/summarize`, `/reason`, `/debug`, `/explain`, `/refactor`, `/translate`, `/generate`, `/search`, `/plan`, `/task`, `/execute`, `/auto`, `/skill`, `/freeze`, `/unfreeze`, `/guard`, `/verbose`, `/webmap`, `/logs`, `/deep`, `/compare`, `/draft`, `/brainstorm`, `/tldr`, `/explore`, `/code`, `/write`, `/edit`, `/run`, `/git`, `/diff`, `/browse`, `/undo`, `/test`, `/apply`, `/grep`, `/find`, `/fix`, `/analyze`, `/read`, `/links`, `/crawl`.

### Group B — Legacy / experimental / unused (~10 commands)

Delete the CommandHandler registration and the `_cmd_X` method. Fallthrough covers muscle memory.

| Command | Deletion reason |
|---|---|
| `/provider` | Legacy: LLM Router refactor made `direct`/`litellm` obsolete |
| `/persona` | Duplicate of `/mode` |
| `/rag` | Should be automatic (LLM decides when to retrieve) |
| `/tune` | Experimental prompt tuner |
| `/skills` | Merge capability discovery into `/help` |
| `/sprint`, `/evidence`, `/careful` | Unclear purpose — grep-verify then delete |
| `/setctx` | Debug-only; merge into `/admin` if needed |
| `/memory` | Admin dump; merge into `/admin` |
| `/archive`, `/purge` | Merged into `/history` subcommands |
| `/hooks` | Merge diagnostic info into `/status` |
| `/hn` | If it works, convert to shared tool `web_hn_top(n)`; else delete |
| `/sources` | Merge source list into `/status` |
| `/chart`, `/calendar`, `/predict` | Convert to fin tool IF implemented, else delete |

---

## Personality Coverage Matrix

| Personality | Slash access | Tool access | LLM native capability | Net change |
|---|---|---|---|---|
| **chat** | 8 meta | 4 web | Knowledge Q&A, reasoning, translation, summarization | +0 slashes, -20 pseudo, same capability (was already all natural language under the hood) |
| **coding** | 8 meta | 4 web (+9 code deferred) | Code explanation, review, debugging suggestions | Same capability this session; future gain: real file edit + shell via Phase D |
| **fin** | 8 meta + 5 fin quick + 4 fin write | 4 web + 10 fin | Finance knowledge, valuation reasoning, historical case recall | +10 tools accessible via natural language AND direct slash; write ops still protected |

---

## Execution Plan

### Phase A — Command cleanup + fallthrough change (~30 min, low risk)

1. Delete `_LLM_ROUTED_COMMANDS` set
2. Rewrite `_handle_unknown_command` fallthrough to strip-slash + natural-language process
3. Delete legacy handlers from Group B (after grep verification)
4. Merge `/archive`, `/purge` into `/history` subcommands
5. Rewrite `/help` to group by capability with natural-language examples
6. Update `set_my_commands` (Telegram autocomplete menu) to show only Tier 1+2
7. **Commit A** → tester subagent verifies baseline still passes

### Phase B — ToolRegistry mode-gating + fin tools (~60 min, medium risk)

1. Add `allowed_modes: Set[str]` field to `ToolDefinition`
2. Filter tools by mode when building LLM prompt
3. Implement 4 shared `web_*` tools (mostly refactor of existing WebSearch)
4. Implement 10 `finance_*` tools (wrap FinanceDataHub + quant module)
5. Convert Tier 2 slash handlers into thin wrappers over the new tools
6. Add QA scenarios that test indirect LLM → tool invocation in fin mode
7. **Commit B** → tester subagent verifies fin-mode natural language triggers tool calls

### Phase C — Cleanup closure (~20 min, low risk)

1. Grep-verify usage of `/admin`, `/hooks`, `/history`, `/sprint`, `/evidence`, `/careful`, `/hn`, `/chart`, `/calendar`, `/predict`
2. Delete or keep per evidence
3. Final `/help` polish
4. **Commit C** → tester subagent runs clean baseline

### Phase D — Coding tools (**DEFERRED**, separate multi-session project)

Requires:
- Permission framework for destructive operations
- Diff preview UX for edits
- Rollback mechanism
- Confirmation flow for multi-step operations

Not in scope for this session. Stub list above for reference.

---

## Open Questions (resolved)

- **Private chat only or group chat too?** → Both. Influenced Tier 2 inclusion.
- **Graceful migration or hard delete?** → Graceful via slash-strip fallthrough. Zero breakage.
- **Coding tools this session or next?** → Next. Too large + needs permission framework.

## Non-goals

- **NOT** redesigning the bot's core message flow
- **NOT** adding new features, only restructuring existing ones
- **NOT** touching the evolution machinery (Phase 1 from earlier this session)
- **NOT** changing LLM provider or router configuration

## Safety guarantees

1. **Every step is a separate commit** → any phase can be reverted independently.
2. **Tester subagent verifies each commit** → no regression slips through.
3. **Slash-strip fallthrough** → any deleted command still works for the user via natural language.
4. **Thin wrapper pattern** → slash handlers and LLM tools share the same underlying implementation, no drift possible.
5. **Mode-gated tools** → LLM cannot accidentally call irrelevant tools (e.g., `finance_get_stock` in chat mode).
6. **Tier 3 (write-state) is untouched** → user data operations stay protected.

---

## Appendix A — Full deletion audit

Commands to remove from the code:

**From `_LLM_ROUTED_COMMANDS` set (delete the set entirely):**
`/summarize /reason /debug /explain /refactor /translate /generate /search /plan /task /execute /auto /skill /freeze /unfreeze /guard /verbose /read /links /crawl /webmap /logs /deep /compare /draft /brainstorm /tldr /explore /stock /portfolio /market /news /watchlist /quant /code /write /edit /run /git /diff /browse /undo /test /apply /grep /find /fix /analyze`

**From explicit `CommandHandler` (delete registration + method):**
`/provider /persona /rag /tune /skills /sprint /evidence /careful /setctx /memory /archive /purge /hooks /read /links /crawl /hn /chart /calendar /predict /compare /fix /analyze /undo /browse /sources /risk`

**Re-registered as thin wrappers (Tier 2):**
`/stock /crypto /news /digest /market`

## Appendix B — Review log

- **Round 1**: Input channel coverage. All 6 channels (voice/image/typing × private/group) covered. Known limitation: voice cannot switch modes without natural-language intent detection. Not a regression.
- **Round 2**: Personality coverage matrix. Chat and fin at full capability. Coding at same capability as before (deferred tools are FUTURE upgrade, not a regression).
- **Round 3**: Thin wrapper contract. Tool functions return typed dicts; slash handlers format for Telegram; LLM calls get the dict. Single source of truth confirmed.
- **Round 4** (implicit, done during v2→v3 transition): Group chat implications. Added Tier 2 fin quick-access to preserve group chat UX.
- **Round 5** (implicit): Consistency cross-check. No command appears in two conflicting tiers. Fallthrough path handles all deleted commands gracefully.
