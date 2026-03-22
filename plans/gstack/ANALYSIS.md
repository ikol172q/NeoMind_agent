# gstack Deep Dive Analysis

## Executive Summary

**gstack** is an open-source AI-powered software factory created by Garry Tan (YC CEO) that transforms Claude Code into a structured virtual engineering team. It enables one person to ship 10,000-20,000 usable lines of production code daily by providing 21 specialized workflow skills and 6 power tools organized around a proven sprint methodology: Think → Plan → Build → Review → Test → Ship → Reflect.

The core technical innovation is a **persistent headless Chromium daemon** (CLI + HTTP server + Playwright) that provides sub-second browser latency for testing, enabling QA testing as an automated step in the development workflow.

---

## What gstack Does (Detailed)

### Problem Statement
Traditional AI copilots make you juggle a generic chat interface. You have to:
- Manage context manually between conversations
- Reason about when to code, test, review, and ship
- Make decisions without architectural guidance
- Test manually or skip testing entirely

### Solution: Virtual Engineering Team
gstack replaces the blank prompt with **21 structured roles** that mimic a real startup's decision-making hierarchy. Each skill is a specialized agent with opinionated workflows that feed data into downstream skills.

### The 21 Skills (Organized by Sprint Phase)

#### Phase 1: Think (Problem Framing)
- **`/office-hours`** — YC office hours questioning. Six forcing questions expose demand reality, status quo, desperate specificity, narrowest wedge, observation, and future-fit. Generates a design doc that feeds into all downstream skills.
- **`/plan-ceo-review`** — Product strategy review. Four modes (Expansion, Selective Expansion, Hold Scope, Reduction) that challenge scope and premises.
- **`/investigate`** — Systematic root-cause debugging. Traces data flow, tests hypotheses, auto-stops after 3 failed fixes.

#### Phase 2: Plan (Architecture)
- **`/plan-eng-review`** — Engineering architecture lockdown. ASCII diagrams for data flow, state machines, edge cases, error paths. Produces test matrix and failure mode analysis.
- **`/plan-design-review`** — Design audit. Rates 10 design dimensions (0-10), explains what a 10 looks like, proposes improvements. Detects AI slop.
- **`/design-consultation`** — Full design system builder. Researches competitive landscape, proposes safe + creative choices, generates realistic product mockups.

#### Phase 3: Build (Implementation)
- (No dedicated skill — Claude Code writes the code based on design docs from phases 1-2)

#### Phase 4: Review (Quality Gates)
- **`/review`** — Staff engineer code review. Finds bugs that pass CI but break in production. Auto-fixes obvious ones, flags completeness gaps. Smart routing (CEO doesn't review infra bugs, design review skipped for backend).
- **`/design-review`** — Design + code review combined. Same audit as `/plan-design-review`, then atomically fixes issues with before/after screenshots.

#### Phase 5: Test (Verification)
- **`/qa`** — QA lead with real browser. Tests web app, finds bugs, fixes them, auto-generates regression tests, re-verifies. Three tiers: Quick (critical/high), Standard (+ medium), Exhaustive (+ cosmetic).
- **`/qa-only`** — Report-only mode (no fixes), used when you want pure bug discovery.
- **`/browse`** — Raw headless browser access. 100+ commands for navigation, interaction, inspection, visual testing. ~100-200ms latency. Persistent state across calls.
- **`/setup-browser-cookies`** — Import cookies from Chrome/Arc/Brave/Edge into headless session for testing authenticated pages.

#### Phase 6: Ship (Release)
- **`/ship`** — Release engineer. Syncs main, runs tests, audits coverage, pushes, opens PR. Bootstraps test framework if missing. Auto-invokes `/document-release`.
- **`/document-release`** — Technical writer. Updates all docs (README, ARCHITECTURE, CONTRIBUTING, CLAUDE.md, TODOS) to match deployed code. Catches stale docs automatically.

#### Phase 7: Reflect (Observability)
- **`/retro`** — Team-aware retrospective. Per-person breakdowns, shipping streaks, test health trends, growth opportunities.
- **`/retro` analytics** — Local dashboard (`gstack-analytics`) showing personal usage patterns.

#### Cross-Cutting Utilities
- **`/codex`** — Second opinion from OpenAI's Codex CLI. Three modes: review (pass/fail gate), adversarial challenge, open consultation. Cross-model analysis when both `/review` (Claude) and `/codex` (OpenAI) have run.
- **`/gstack-upgrade`** — Self-updater. Detects global vs vendored install, syncs both, shows what changed.

#### Power Tools (Safety)
- **`/careful`** — Safety guardrails. Warns before destructive commands (rm -rf, DROP TABLE, force-push).
- **`/freeze`** — Edit lock. Restricts file edits to one directory while debugging.
- **`/guard`** — Full safety mode (careful + freeze combined).
- **`/unfreeze`** — Remove edit restrictions.

### Key Workflow Features

#### 1. Design Docs Flow Through System
```
/office-hours writes DESIGN.md
    ↓
/plan-ceo-review reads DESIGN.md, challenges scope
    ↓
/plan-eng-review reads DESIGN.md, locks architecture
    ↓
/plan-design-review reads DESIGN.md, audits visual
    ↓
Claude Code writes implementation based on all inputs
    ↓
/review reads code + DESIGN.md for context
    ↓
/qa tests against DESIGN.md's requirements
```

#### 2. Smart Review Routing
Instead of "always run all reviews," gstack tracks what's appropriate:
- CEO review: needed for product decisions, user-facing changes
- Design review: needed for UI changes, new pages
- Eng review: always needed for code quality
- QA: always needed for web app changes

#### 3. Parallel Sprints (10-15 at once)
With [Conductor](https://conductor.build), run multiple Claude Code sessions in parallel:
- Session 1: `/office-hours` on a new idea
- Session 2: `/review` on a PR
- Session 3: `/qa` on staging
- Sessions 4-15: Other branches/features

The sprint structure (Think → Plan → Build → Review → Test → Ship) makes parallelism safe — each agent knows exactly what to do and when to stop.

#### 4. Test Everything
Every `/ship` run produces a coverage audit. Every `/qa` bug fix generates a regression test. Goal: 100% test coverage. Tests are the cheapest "lake to boil" (marginal AI-assisted cost is near-zero).

---

## Architecture Breakdown

### System Overview

```
Claude Code (Agent)
    │
    ├─ SKILL.md files (21 skills, each a structured prompt)
    │
    ├─ Bash/CLI execution
    │       │
    │       └─ $B <command>  (compiled gstack CLI binary)
    │           │
    │           HTTP POST (localhost)
    │           Bearer token auth
    │           │
    │           ▼
    │     ┌──────────────────────────┐
    │     │  gstack browse server     │
    │     │  (Bun.serve HTTP daemon)  │
    │     ├──────────────────────────┤
    │     │ • Command dispatch        │
    │     │ • Error wrapping          │
    │     │ • Buffer flushing         │
    │     │ • Idle auto-shutdown      │
    │     │ • Port discovery          │
    │     │ • Auth token validation   │
    │     └────────────┬──────────────┘
    │                  │
    │                  │ Playwright CDPv1
    │                  │
    │                  ▼
    │          ┌─────────────────────────────┐
    │          │  Chromium (headless)        │
    │          ├─────────────────────────────┤
    │          │ • Persistent context        │
    │          │ • Tab management (multi)    │
    │          │ • Cookie persistence        │
    │          │ • Console/network/dialog    │
    │          │ • ARIA snapshot             │
    │          │ • Screenshot + annotation   │
    │          │ • Dialog auto-handling      │
    │          └─────────────────────────────┘
    │
    └─ Git operations (standard git CLI)
       └─ Code files (user repo)

```

### Core Components

#### 1. CLI (`browse/src/cli.ts`)
**Responsibility:** Thin wrapper that communicates with the persistent server

**Key Functions:**
- `ensureServer()` — Health check + auto-restart on stale/dead server
- `startServer()` — Spawn server as background process (Bun or Node on Windows)
- `sendCommand()` — HTTP POST command, retry on auth/connection failure
- Version detection — auto-restart server if binary is updated

**Technology:**
- Pure TypeScript/Bun (no framework)
- State file: `~/.gstack/browse.json` (PID, port, token)
- Localhost only (127.0.0.1), never network-exposed
- Bearer token auth (UUID)

**Key Code Pattern:**
```typescript
// Read state file or start server
const state = await ensureServer();

// Send HTTP POST with Bearer token
const resp = await fetch(`http://127.0.0.1:${state.port}/command`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${state.token}`,
  },
  body: JSON.stringify({ command, args }),
});
```

#### 2. Server (`browse/src/server.ts`)
**Responsibility:** Long-lived HTTP daemon that manages Chromium + routes commands

**Key Functions:**
- `Bun.serve()` — HTTP server on random port (10000-60000 range)
- Command routing — READ/WRITE/META command sets
- Buffer management — circular in-memory buffers (50K entries each) + async disk flush
- Idle timeout — 30min auto-shutdown if no activity
- Error wrapping — Playwright errors → agent-actionable messages

**Architecture:**
```typescript
const server = Bun.serve({
  fetch: async (req) => {
    // 1. Check auth (Bearer token)
    if (!validateAuth(req)) return 401;

    // 2. Route command
    const { command, args } = await req.json();
    let result: string;

    if (READ_COMMANDS.has(command)) {
      result = await handleReadCommand(command, args, browserManager);
    } else if (WRITE_COMMANDS.has(command)) {
      result = await handleWriteCommand(command, args, browserManager);
    } else if (META_COMMANDS.has(command)) {
      result = await handleMetaCommand(command, args, browserManager, shutdown);
    }

    // 3. Return plain text (not JSON — lighter on tokens)
    return new Response(result, { status: 200 });
  },
});
```

**Command Categories:**
```typescript
const READ_COMMANDS = new Set([
  'text', 'html', 'links', 'forms', 'accessibility',
  'console', 'network', 'dialog', 'cookies', 'storage',
  'js', 'eval', 'attrs', 'css', 'is', 'perf'
]);

const WRITE_COMMANDS = new Set([
  'goto', 'click', 'fill', 'select', 'type', 'hover',
  'scroll', 'press', 'upload', 'wait',
  'viewport', 'useragent', 'header', 'cookie',
  'dialog-accept', 'dialog-dismiss'
]);

const META_COMMANDS = new Set([
  'snapshot', 'screenshot', 'pdf', 'responsive', 'diff',
  'tabs', 'tab', 'newtab', 'closetab',
  'status', 'health', 'chain',
  'handoff', 'resume', 'stop', 'restart'
]);
```

#### 3. BrowserManager (`browse/src/browser-manager.ts`)
**Responsibility:** Lifecycle management of Chromium + Page + Context + Tab state

**Key Components:**
```typescript
class BrowserManager {
  private browser: Browser;              // Chromium process
  private context: BrowserContext;       // Cookie/storage/session container
  private pages: Map<number, Page>;      // Tab ID → Playwright Page
  private activeTabId: number;           // Current tab
  private refMap: Map<string, RefEntry>; // @e1/@e2/... locators
  private lastSnapshot: string;          // For diffing
  private extraHeaders: Record<string, string>;
  private customUserAgent: string | null;
}
```

**Key Methods:**
- `launch()` — Start Chromium, create context, wire page events (console/network/dialog)
- `newTab()` — Create new page, assign ID, wire events, optionally navigate
- `closeTab()` — Close page by ID
- `evalSnapshot()` — Get ARIA tree via `page.accessibility.snapshot()`
- `resolveRef()` — Look up @e3 → Locator + check staleness

**Event Wiring:**
```typescript
page.on('console', msg => addConsoleEntry(msg.type(), msg.text()));
page.on('response', res => addNetworkEntry(...));
page.on('dialog', dlg => {
  if (this.dialogAutoAccept) {
    dlg.accept(this.dialogPromptText);
  }
});
```

**Crash Handling:**
```typescript
this.browser.on('disconnected', () => {
  console.error('[browse] FATAL: Chromium crashed');
  process.exit(1);  // Don't try to self-heal — let CLI restart
});
```

#### 4. Snapshot & Refs (`browse/src/snapshot.ts`)
**Responsibility:** Convert ARIA tree into numbered @ref system for element selection

**Why Not DOM Mutation?**
The obvious approach is to inject `data-ref="@e1"` attributes. This breaks on:
- CSP (Content Security Policy) blocks DOM mutation
- React/Vue/Svelte hydration strips injected attributes
- Shadow DOM unreachable from outside

**Solution: Locators (No DOM Mutation)**
1. Call `page.accessibility.snapshot()` → YAML-like ARIA tree
2. Parse tree, assign refs sequentially: @e1, @e2, @e3...
3. Build Playwright Locator for each: `getByRole('button', { name: 'Submit' }).nth(2)`
4. Store Map<string, RefEntry> on BrowserManager
5. Return text tree with refs prepended

```typescript
interface RefEntry {
  locator: Locator;
  role: string;
  name: string;
}

// When agent runs: click @e3
// Server looks up: refMap.get('e3').locator.click()
```

**Ref Lifecycle:**
- Created: On `snapshot` command
- Cleared: On page navigation (`framenavigated` event)
- Staleness check: Before use, verify `locator.count() > 0`

**Extended Snapshot Features:**

| Flag | Purpose |
|------|---------|
| `-i` | Interactive elements only (buttons, links, inputs) |
| `-c` | Compact (remove empty structural nodes) |
| `-d N` | Limit tree depth |
| `-s SEL` | Scope to CSS selector |
| `-D` | Unified diff vs previous snapshot |
| `-a` | Annotated screenshot (red boxes with labels) |
| `-o PATH` | Output path for annotated screenshot |
| `-C` | Cursor-interactive (find divs with `cursor:pointer`, `onclick`) |

#### 5. Buffer System (`browse/src/buffers.ts`)
**Responsibility:** Non-blocking circular buffers for console/network/dialog logs

**Architecture:**
```
Browser events
    ↓
CircularBuffer (in-memory, 50K entries each)
    ↓
[Every 1 second]
    ↓
Async append to .gstack/browse-{console,network,dialog}.log
```

**Why Circular Buffers?**
- O(1) push (wrap index)
- Bounded memory (50K × 3 buffers)
- Never block HTTP request handling

**Flushing:**
```typescript
async function flushBuffers() {
  // Console
  const newEntries = consoleBuffer.last(newConsoleCount);
  fs.appendFileSync(CONSOLE_LOG_PATH, formatted);

  // Network
  const newNetries = networkBuffer.last(newNetworkCount);
  fs.appendFileSync(NETWORK_LOG_PATH, formatted);

  // Dialog
  ...
}

// Flush every 1 second
setInterval(flushBuffers, 1000);
```

**Result:**
- HTTP requests are never blocked by I/O
- Logs survive server crashes (up to 1s data loss)
- Memory is bounded
- Disk files are append-only, readable by external tools

#### 6. Commands (`browse/src/commands.ts`, etc.)
**Responsibility:** Implement ~100 browser commands

**Organization:**
- `commands.ts` — Metadata (descriptions, categories)
- `read-commands.ts` — No-mutation commands (text, html, links, js, etc.)
- `write-commands.ts` — Page mutation (click, fill, goto, type, etc.)
- `meta-commands.ts` — Server operations (snapshot, screenshot, chain, etc.)

**Example Command (read):**
```typescript
async function handleText(args: string[], bm: BrowserManager): Promise<string> {
  const page = bm.getActivePage();
  const text = await page.evaluate(() => {
    // Extract visible text, clean whitespace
    return document.body.innerText;
  });
  return text;
}
```

**Example Command (write):**
```typescript
async function handleClick(args: string[], bm: BrowserManager): Promise<string> {
  const [selector] = args;
  const page = bm.getActivePage();
  const locator = bm.resolveSelector(selector, page);
  await locator.click({ timeout: 15000 });
  return `Clicked`;
}
```

### Data Flow Example: `/qa` Testing

```
/qa (SKILL.md) invokes:
    │
    ├─ $B goto https://staging.myapp.com
    │   → HTTP POST → server.ts → browserManager.goto()
    │   → Chromium navigates, waits for 'domcontentloaded'
    │
    ├─ $B snapshot -i
    │   → page.accessibility.snapshot() → parse → @e refs
    │   → Returns interactive tree with @e1, @e2, @e3...
    │
    ├─ $B click @e3  # "Submit button"
    │   → refMap.get('e3').locator.click()
    │   → Chromium clicks, page mutates
    │   → Console/network/dialog events buffered
    │
    ├─ $B snapshot -D
    │   → New snapshot, diff vs previous
    │   → Returns unified diff showing what changed
    │
    ├─ $B console
    │   → Return in-memory console buffer
    │   → "GET /api/submit 200 OK" logged
    │
    ├─ $B is visible ".success-message"
    │   → locator.isVisible()
    │   → Returns "true" or "Element not found"
    │
    └─ Claude Code (SKILL.md) parses output:
        ├─ If bugs found → fix in source code
        ├─ Add regression test
        ├─ git commit
        ├─ Retry /qa to verify fix
        └─ Report: "3 bugs found, all fixed"
```

### Why Bun (Not Node.js)

From `ARCHITECTURE.md`:

1. **Compiled binaries** — `bun build --compile` produces single ~58MB executable. No `node_modules` at runtime, no PATH configuration.
2. **Native SQLite** — Cookie decryption reads Chromium's SQLite cookie database directly. Bun has `new Database()` built in.
3. **Native TypeScript** — Server runs as `bun run server.ts` during dev. No compilation step.
4. **Built-in HTTP server** — `Bun.serve()` is fast, simple, no Express/Fastify overhead.

**Windows Exception:**
On Windows, Playwright's Chromium has issues with Bun's pipe transport. Fallback: server runs under Node.js with Bun API polyfills.

---

## Tech Stack

### Languages & Frameworks
- **TypeScript** — All source code
- **Bun** — Runtime + bundler (compiles to binary)
- **Playwright** — Chromium control (Chrome DevTools Protocol)
- **Bash** — SKILL.md preamble + git operations

### Dependencies
```json
{
  "playwright": "^1.58.2",    // Chromium automation
  "diff": "^7.0.0"             // Unified diff generation
}
```

**Dev Dependencies:**
```json
{
  "@anthropic-ai/sdk": "^0.78.0"  // Claude API for E2E tests
}
```

### Infrastructure
- **Local only** — No remote server, everything on user's machine
- **State files** — `~/.gstack/` (config, state, logs, analytics)
- **Port selection** — Random 10000-60000 (supports 10 parallel sessions)
- **Telemetry (opt-in)** — Supabase database (usage data only, no code)

### Testing
- **E2E tests** — Spawn `claude -p` subprocess, capture NDJSON
- **Session runner** — Orchestrates Claude agent, tracks heartbeat + partial results
- **Eval store** — Accumulates test results, compares across runs
- **Three test tiers:**
  - Tier 1: Static validation (free, <2s)
  - Tier 2: E2E via Claude session (~$3.85, ~20min)
  - Tier 3: LLM-as-judge for quality scoring (~$0.15, ~30s)

---

## Key Technical Patterns

### 1. Persistent Daemon Model
**Why?** Avoid 2-3 second browser startup overhead on every command.

- First call: ~3 seconds (start Bun + Chromium)
- Subsequent calls: ~100-200ms (HTTP POST + Playwright action)
- Auto-shutdown: After 30min idle
- Auto-restart: On stale binary or dead server

**State Persistence:**
- Cookies stay logged in
- localStorage/sessionStorage preserved
- Tab structure maintained
- ARIA refs valid until navigation

### 2. Ref System (No DOM Injection)
**Why?** CSP + framework hydration would strip injected attributes.

- Uses Playwright Locators (ARIA-based, external to DOM)
- Refs: `@e1`, `@e2` for accessibility tree + `@c1`, `@c2` for cursor-interactive
- Automatic staleness detection (element count check before use)
- Clears on navigation, fresh snapshot required

### 3. Command Categorization
**READ** (no side effects, safe to retry)
**WRITE** (mutate page, not idempotent)
**META** (server operations, lifecycle)

This enables:
- Auto-routing based on command type
- Safety hints for agents
- Proper error recovery strategies

### 4. Error Wrapping for Agents
Instead of raw Playwright errors, translate to actionable guidance:

```typescript
// Raw: "Timed out waiting for locator to be visible"
// Wrapped: "Element not found or not interactable. Check your selector or run 'snapshot' for fresh refs."

// Raw: "Multiple elements matched"
// Wrapped: "Selector matched multiple elements. Be more specific or use @refs from 'snapshot'."
```

### 5. Circular Buffers for Logging
O(1) memory growth:
```typescript
class CircularBuffer<T> {
  private items: T[] = new Array(50000);
  private index: number = 0;
  private totalAdded: number = 0;

  push(item: T) {
    this.items[this.index % this.items.length] = item;
    this.index++;
    this.totalAdded++;
  }

  last(n: number): T[] {
    // Return last N items (handling wraparound)
  }
}
```

Console/network/dialog events logged with O(1) space, flushed async every 1 second.

### 6. SKILL.md Template System
Single source of truth for documentation:

```
SKILL.md.tmpl (hand-written prose + placeholders)
    ↓
gen-skill-docs.ts (reads source code)
    ↓
SKILL.md (committed, auto-generated sections)
```

Placeholders filled from code:
- `{{COMMAND_REFERENCE}}` — All commands from code
- `{{SNAPSHOT_FLAGS}}` — From snapshot.ts
- `{{PREAMBLE}}` — Session tracking + update check + telemetry
- `{{QA_METHODOLOGY}}` — Shared by /qa and /qa-only

**Benefit:** Docs never drift from code. If a command exists, it appears in docs.

### 7. Multi-Session Safety
With 10-15 parallel Conductor sessions:
- Each session has its own `.gstack/` state directory
- Separate browser servers per workspace (no port conflicts)
- Session tracking via `~/.gstack/sessions/$PPID` (auto-cleanup >2hr old)
- "ELI16 mode" activates when 3+ sessions running (re-ground context in every question)

### 8. Builder Ethos: Boil the Lake
Core principle injected into every skill:

**Compression Ratios (Human vs AI-Assisted):**
- Boilerplate: 100x (2 days → 15 min)
- Test writing: 50x (1 day → 15 min)
- Feature impl: 30x (1 week → 30 min)
- Bug fix + test: 20x (4 hours → 15 min)
- Architecture: 5x (2 days → 4 hours)
- Research: 3x (1 day → 3 hours)

**Implication:** "Skip the last 10% to save time" is legacy thinking. The last 10% (edge cases, tests, docs) costs seconds now, not days. Do the complete thing.

---

## How It Integrates with NeoMind

NeoMind is a multi-mode AI agent with:
- CLI interface + Telegram bot
- Finance personality
- OpenClaw integration (external tool execution)

### Strategic Integration Points

#### 1. Real Browser Automation
**Current State:** NeoMind needs to interact with web services (stock tickers, financial dashboards, etc.)

**gstack Contribution:** `/browse` skill provides:
- Persistent Chromium (sub-second latency)
- Financial data extraction from web UIs
- Screenshot evidence for trade verification
- Form automation (login, order entry, etc.)
- Regex-safe DOM inspection (no fragile CSS selectors)

**Usage Example:**
```bash
# In NeoMind's finance skill
$B goto https://trading.example.com
$B snapshot -i                          # Find login form
$B fill @e1 "$USERNAME"                 # Username
$B fill @e2 "$API_KEY"                  # API key (from secure store)
$B click @e3                            # Submit
$B is visible ".portfolio-dashboard"    # Verify login worked
$B snapshot -a -o /tmp/portfolio.png    # Screenshot for evidence
```

#### 2. Structured Testing in Finance Domain
**Current State:** Finance agents must be extremely reliable (bugs cost real money)

**gstack Contribution:** `/qa` skill adapted for finance:
- Regression test every trade execution
- Verify portfolio state before/after
- Screenshot evidence for audit trails
- Automatic health checks on market connectivity

**Implementation:**
```bash
# NeoMind finance QA tier
/qa https://staging.trading.app --tier exhaustive
# Tests: login persistence, order validation, position accuracy, settlement
```

#### 3. CLI + Skill Composition
**Current State:** NeoMind has CLI commands like `/trade`, `/analyze-portfolio`

**gstack Contribution:** Use gstack's SKILL.md system to:
- Add `/finance-briefing` (like `/office-hours` but for financial decisions)
- Add `/trade-review` (like `/review` but for trade validation)
- Add `/portfolio-audit` (like `/design-review` but for fund management)

**Example Skill (NeoMind + gstack hybrid):**
```yaml
---
name: finance-briefing
description: |
  Analyze market conditions and your portfolio using /office-hours methodology.
  Use when: "Is now a good time to buy?" "What should my allocation be?"
allowed-tools:
  - Bash
  - WebSearch
  - AskUserQuestion
---

[preamble: common to all NeoMind skills]

[office-hours-style questioning applied to portfolio decisions]

1. Current reality: What's your actual allocation right now?
2. Market conditions: Earnings season? Fed decisions? Geopolitical?
3. Desperate specificity: What's the specific trade, not the general thesis?
4. Narrowest wedge: What's the minimum viable portfolio move?
5. Data: Pull live data from financial APIs
6. Future fit: Does this align with your long-term goals?

[Produce: PORTFOLIO_DECISION.md → fed into /trade-review]
```

#### 4. Parallel Finance Workflows
With Conductor + gstack:
- Session 1: `/finance-briefing` on quarterly rebalancing
- Session 2: `/trade-review` on a proposed short position
- Session 3: `/qa` testing sandbox trading account
- Session 4: `/browse` monitoring live portfolio
- Session 5: Actual trading execution with full audit trail

#### 5. Evidence & Audit Trails
**gstack provides:**
- Annotated screenshots (`-a` flag) for every decision
- Unified diffs for portfolio state changes
- Console logs for all API calls
- Network traces for latency/failure analysis
- Regression test suite for trade validation

**NeoMind benefit:**
```bash
# Every trade execution produces evidence:
/qa-only --screenshot-evidence --network-trace --console-log

# Result: legal-grade audit trail
# "On 2026-03-21 14:32:01 UTC, traded AAPL, screenshot in /tmp, console log attached"
```

#### 6. Finance Personality + gstack Ethos
**Alignment:**
- gstack's "Boil the Lake" → Finance's "Complete Risk Analysis" (edge cases = tail risks)
- gstack's "Search Before Building" → Finance's "Research Before Trading"
- gstack's "Three Layers of Knowledge" → Finance's "Layer 1: Fundamental, Layer 2: Technical, Layer 3: Sentiment"

#### 7. Multi-Mode Delivery
**gstack is CLI-first, but NeoMind needs:**
- Telegram bot interface
- Web dashboard
- Scheduled workflows

**Bridge:**
```bash
# CLI remains the single source of truth
gstack-cli /finance-briefing --output json > /tmp/decision.json

# Telegram bot wraps it
telegram_send_analysis /tmp/decision.json

# Web dashboard displays results + evidence
dashboard_show_trade_evidence /tmp/portfolio.png
```

#### 8. Recommended NeoMind + gstack Architecture

```
NeoMind CLI / Telegram Bot
    │
    ├─ /trade (uses gstack /browse + /qa)
    │   └─ Execute on paper trading first
    │   └─ Screenshot evidence
    │   └─ Verify in real account
    │
    ├─ /analyze-portfolio (uses gstack /investigate + WebSearch)
    │   └─ Root cause analysis of underperformance
    │   └─ Systematic hypothesis testing
    │
    ├─ /briefing (uses gstack /office-hours-style questioning)
    │   └─ Market analysis with forcing questions
    │   └─ Generates PORTFOLIO_DECISION.md
    │
    ├─ /review-trade (uses gstack /review + custom finance rules)
    │   └─ Code review but for trade logic
    │   └─ Auto-fix obvious issues
    │   └─ Flag risk violations
    │
    ├─ /audit (uses gstack /document-release adapted)
    │   └─ Update portfolio docs to match actual state
    │   └─ Reconcile P&L
    │
    └─ /retro (uses gstack /retro adapted)
        └─ Weekly finance retrospective
        └─ Win/loss analysis
        └─ Sharpe ratio trends
```

#### 9. Integration with OpenClaw
**OpenClaw** = external tool executor. gstack integrates with it by:

```bash
# In NeoMind skill, call OpenClaw for external actions
openclaw-exec trade-on-fidelity \
  --symbol AAPL \
  --shares 100 \
  --price 150.25 \
  --evidence /tmp/decision.json

# While gstack provides the browser verification:
$B goto https://fidelity.com/accounts
$B screenshot /tmp/fidelity-confirm.png  # Evidence that trade appeared
```

---

## Summary: gstack in 30 Seconds

**What:** One repo, 21 specialized workflow skills, persistent browser daemon.

**Why:** Compress engineering team (CEO → Eng Mgr → Designer → QA → Release Eng) into one person with AI.

**How:** Structured sprint methodology (Think → Plan → Build → Review → Test → Ship → Reflect), where each skill feeds into the next, and a real Chromium daemon enables sub-second browser testing.

**Result:** 10,000+ lines of production code daily while maintaining CEO duties. 1,237 GitHub contributions in 2026 alone.

**For NeoMind:** Browser automation + structured testing + evidence trails + parallel workflows. Perfect for finance where reliability matters and audit trails are mandatory.

---

## Key Files & Paths

### Core Browser Implementation
- `/tmp/gstack/browse/src/cli.ts` — Thin HTTP client wrapper
- `/tmp/gstack/browse/src/server.ts` — Bun.serve HTTP daemon
- `/tmp/gstack/browse/src/browser-manager.ts` — Chromium lifecycle + tab mgmt
- `/tmp/gstack/browse/src/commands.ts` — Command registry + metadata
- `/tmp/gstack/browse/src/read-commands.ts` — ~50 read-only commands
- `/tmp/gstack/browse/src/write-commands.ts` — ~30 write commands
- `/tmp/gstack/browse/src/meta-commands.ts` — ~20 server operations
- `/tmp/gstack/browse/src/snapshot.ts` — ARIA tree + ref system
- `/tmp/gstack/browse/src/buffers.ts` — Circular log buffers

### Workflow Skills (Pick any to understand structure)
- `/tmp/gstack/office-hours/SKILL.md` — Problem framing
- `/tmp/gstack/review/SKILL.md` — Code review
- `/tmp/gstack/qa/SKILL.md` — Testing + fixing
- `/tmp/gstack/ship/SKILL.md` — Release engineering

### Architecture Documentation
- `/tmp/gstack/ARCHITECTURE.md` — Design decisions + system internals
- `/tmp/gstack/ETHOS.md` — Builder philosophy (Boil the Lake, Search Before Building)
- `/tmp/gstack/BROWSER.md` — Complete browse command reference
- `/tmp/gstack/README.md` — Quick start + overview

### Config & Build
- `/tmp/gstack/package.json` — Dependencies, build scripts
- `/tmp/gstack/browse/src/config.ts` — State file locations, path resolution
- `/tmp/gstack/SKILL.md.tmpl` — Template for doc generation
- `/tmp/gstack/scripts/gen-skill-docs.ts` — Auto-generate SKILL.md from code

---

## Design Philosophy

### 1. Composition Over Generality
Instead of "generic agent + tuning," gstack provides **21 specific roles**. Each role has one job, does it well, feeds into the next.

### 2. Markdown as Interface
Skills are SKILL.md files. No JSON configs, no YAML. Plain Markdown + frontmatter. Humans read it, agents execute it.

### 3. Command Sets Over Frameworks
Instead of using MCP or WebSocket streaming, gstack uses:
- Plain HTTP (debuggable with curl)
- Bearer token auth
- Plain text output (lighter on tokens than JSON)
- Categories of commands (READ/WRITE/META)

This is simpler, more reliable, and lighter than abstraction layers.

### 4. Fail Loudly, Not Gracefully
When Chromium crashes, the server exits. The CLI detects it and auto-restarts. No trying to self-heal — hidden failures are worse than visible ones.

### 5. Boil the Lake
When AI makes marginal cost near-zero, do the complete thing. 100% test coverage, all edge cases, full error paths. Don't ship the 90% shortcut.

### 6. Local-First
Everything runs on your machine. No remote server, no cloud dependency, no data leakage. State in `~/.gstack/`. Easy to inspect, debug, backup.

---

## Conclusion

gstack is a masterclass in:
1. **System architecture** — How to build reliable, scalable agent infrastructure
2. **Workflow design** — How to structure complex processes (Think → Plan → Build → Review → Test → Ship)
3. **AI-human collaboration** — How to give AI guardrails (SKILL.md roles, power tools) without constraining it
4. **Testing & QA** — How to make real browser testing part of the core development loop

For NeoMind, the immediate wins are:
- Real browser automation for financial data extraction
- Structured QA for trade validation
- Evidence trails for compliance/audit
- Parallel workflow execution

Longer term, adapting gstack's philosophy (Boil the Lake + Search Before Building) into finance decision-making could be transformative.
