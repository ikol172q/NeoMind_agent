# NeoMind + gstack Integration: Recommendations

## Quick Assessment

### What gstack Does Exceptionally Well
1. **Real Chromium automation** — Persistent daemon with ~100ms latency (critical for real-time finance)
2. **Structured workflow design** — 21 specialized skills ordered by sprint phase
3. **Evidence trails** — Screenshots, console logs, network traces for every action
4. **Testing integration** — `/qa` with automatic regression test generation
5. **Parallel execution** — 10-15 concurrent workflows via Conductor

### NeoMind's Current Gaps That gstack Solves
- Browser automation (NeoMind needs to interact with financial UIs)
- Structured decision-making (finance requires audit trails + evidence)
- Real testing (paper trading before live execution)
- Parallel workflows (market moves fast; sequential is too slow)

---

## Integration Recommendations

### Phase 1: Adopt `/browse` for Financial Data Extraction (IMMEDIATE)

**Goal:** Get NeoMind's "eyes" on financial websites

**Implementation:**
```bash
# NeoMind CLI command: /check-market
# Uses gstack /browse skill

$B goto https://finance.yahoo.com/quote/AAPL
$B snapshot -i                          # Find price element
$B text                                 # Extract all prices
$B screenshot /tmp/aapl.png             # Evidence

# Result: NeoMind has real-time data + screenshot proof
```

**Time to implement:** 1-2 days
**Impact:** High — enables direct web scraping vs API-only
**Risk:** Low — gstack /browse is stable, tested

### Phase 2: Build `/trade-review` Skill (1 WEEK)

**Goal:** Structured trade validation (like gstack's `/review` but for finance)

**Implementation:**
```yaml
---
name: trade-review
version: 1.0.0
description: |
  Pre-execution trade review. Validates order parameters, checks risk limits,
  verifies compliance. Use before any real money trade.
allowed-tools:
  - Bash
  - Read
  - Edit
  - WebSearch
  - AskUserQuestion
---

# Adapted from gstack /review, but checks:
# 1. Order size vs portfolio (position limit check)
# 2. Execution price vs market (front-running check)
# 3. Settlement risk (T+2 delivery, fails, etc.)
# 4. Margin requirements (if leveraged)
# 5. Tax implications (wash sale, lot selection)

[Auto-fix obvious issues]
[Flag risk violations]
[Generate trade confirmation doc]
```

**Time to implement:** 4-5 days
**Impact:** Critical — blocks bad trades before execution
**Dependencies:** Phase 1 (/browse working)

### Phase 3: Build `/finance-briefing` Skill (1 WEEK)

**Goal:** Market analysis using YC office hours methodology

**Implementation:**
```yaml
---
name: finance-briefing
description: |
  Market context + portfolio decision framework.
  Adapted from /office-hours for financial decisions.
---

## Six Forcing Questions (adapted):

1. Current reality: What's your actual allocation right now?
   ↓ Live portfolio pull via /browse

2. Market conditions: What's happening TODAY?
   ↓ WebSearch + financial APIs

3. Desperate specificity: What is the ACTUAL trade, not the thesis?
   ↓ Pull specific stock/sector/macro data

4. Narrowest wedge: What's the minimum viable move?
   ↓ Calculate position size via quantitative framework

5. Observation: What does the data say?
   ↓ Pull earnings, technicals, sentiment

6. Future fit: Does this align with your long-term goals?
   ↓ Check vs asset allocation policy

Result: PORTFOLIO_DECISION.md → feeds into /trade-review
```

**Time to implement:** 3-4 days
**Impact:** Medium-high — structures decision-making
**Dependencies:** Phase 1 (/browse) + financial data APIs

### Phase 4: Adapt `/qa` for Trading (2 WEEKS)

**Goal:** Regression testing for trades (paper → live validation)

**Implementation:**
```bash
# NeoMind /qa-trading command:
# 1. Execute trade on paper account
# 2. Verify position appears in portfolio
# 3. Check P&L updates correctly
# 4. Verify settlement timeline
# 5. Auto-generate regression test
# 6. Run same trade on live if all pass

/qa-trading \
  --symbol AAPL \
  --shares 100 \
  --order-type market \
  --paper-first \
  --screenshot-evidence \
  --regression-test

# Output: Evidence + test file + live execution log
```

**Time to implement:** 10-12 days
**Impact:** Critical — catches edge cases before real money
**Dependencies:** Phases 1-2

### Phase 5: Parallel Conductor Integration (2 WEEKS)

**Goal:** Run multiple NeoMind workflows in parallel

**Implementation:**
```bash
# Conductor spawns 5 parallel NeoMind sessions:

Session 1: /finance-briefing (market analysis)
Session 2: /investigate (underperformance root cause)
Session 3: /trade-review (pending orders)
Session 4: /qa-trading (paper test before live)
Session 5: /audit (reconcile P&L)

# All run in parallel, each with own browser daemon
# Check on summary dashboards, drill into specific sessions
```

**Time to implement:** 8-10 days (orchestration layer)
**Impact:** High — enables rapid decision cycles
**Dependencies:** Phases 1-4

---

## File Structure for NeoMind + gstack

```
neomind/
├── .claude/skills/gstack/          # gstack installed locally
│   ├── browse/                      # Browser automation (unchanged)
│   ├── review/                      # Code review (unchanged)
│   ├── qa/                          # Testing (unchanged)
│   └── ...
│
├── .claude/skills/neomind/          # NeoMind-specific skills
│   ├── finance-briefing/SKILL.md    # [NEW] Market analysis
│   ├── trade-review/SKILL.md        # [NEW] Trade validation
│   ├── qa-trading/SKILL.md          # [NEW] Trade regression testing
│   ├── audit/SKILL.md               # [NEW] Reconciliation
│   └── ...
│
├── src/
│   ├── commands/
│   │   ├── trade.ts                 # Execution logic
│   │   ├── analyze-portfolio.ts
│   │   └── ...
│   ├── integrations/
│   │   ├── gstack-browse.ts         # Wrapper for /browse
│   │   ├── fidelity-api.ts
│   │   ├── alpaca-api.ts
│   │   └── ...
│   ├── finance/
│   │   ├── trade-validator.ts       # Risk checks
│   │   ├── position-calculator.ts
│   │   └── ...
│   └── ...
│
├── CLAUDE.md
│   gstack section: reference all 21 gstack skills
│   neomind section: reference new finance-briefing, trade-review, qa-trading, audit
│
└── tests/
    ├── e2e/
    │   ├── trade-execution.test.ts   # End-to-end trade tests
    │   ├── portfolio-reconciliation.test.ts
    │   └── ...
    └── ...
```

---

## CLAUDE.md Configuration

```markdown
## gstack

Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.

Available gstack skills:
/office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /review, /ship, /browse, /qa, /qa-only, /design-review,
/setup-browser-cookies, /retro, /investigate, /document-release, /codex, /careful,
/freeze, /guard, /unfreeze, /gstack-upgrade.

For finance workflows, also use NeoMind-specific skills below.

## NeoMind Finance Workflows

Available NeoMind skills:
/finance-briefing, /trade-review, /qa-trading, /audit, /portfolio-alert

Key integrations:
- /browse: Portfolio extraction, market data from web UIs
- /trade-review: Adapted from /review, checks: position limits, execution price, settlement risk, margin, taxes
- /qa-trading: Adapted from /qa, validates: paper execution, P&L updates, regression tests, then live execution
- /finance-briefing: Adapted from /office-hours, applies market analysis framework
- /audit: Adapted from /document-release, reconciles: portfolio state, P&L, settlement
```

---

## Technical Implementation Guide

### 1. Wrapper Module for gstack Calls

**`src/integrations/gstack-browse.ts`:**
```typescript
import { execSync } from 'child_process';

export interface BrowseCommand {
  cmd: string;
  args: string[];
}

export async function executeBrowseCommand(
  cmd: string,
  args: string[]
): Promise<string> {
  // Wrapper around: $B <cmd> <args>
  // Handles output parsing, error translation for finance context
  try {
    const result = execSync(`$B ${cmd} ${args.join(' ')}`, {
      encoding: 'utf-8',
    });
    return result;
  } catch (err: any) {
    throw new Error(`Browse command failed: ${err.message}`);
  }
}

// Usage in trade-review SKILL.md:
// $B goto https://brokeraccount.com
// $B snapshot -i
// $B click @e3  (submit order)
// $B is visible ".confirmation"  (verify success)
```

### 2. Trade Validator Using gstack Evidence

**`src/finance/trade-validator.ts`:**
```typescript
export async function validateTrade(tradeParams: TradeParams): Promise<TradeValidation> {
  // Step 1: /browse to portfolio
  const portfolio = await executeBrowseCommand('goto', ['https://portfolio.example.com']);

  // Step 2: Extract position limits
  const snapshot = await executeBrowseCommand('snapshot', ['-i']);
  const currentPosition = parseSnapshot(snapshot);

  // Step 3: Check against risk limits
  const validation = {
    maxPosition: 50000,          // Dollar limit
    currentPosition: currentPosition.value,
    proposedTrade: tradeParams.value,
    wouldExceed: currentPosition.value + tradeParams.value > 50000,
  };

  // Step 4: Screenshot evidence
  if (validation.wouldExceed) {
    await executeBrowseCommand('screenshot', ['/tmp/position-limit-exceeded.png']);
  }

  return validation;
}
```

### 3. NeoMind Trade-Review Skill

**`neomind/.claude/skills/neomind/trade-review/SKILL.md`:**
```markdown
---
name: trade-review
version: 1.0.0
description: |
  Pre-execution trade review. Validates order parameters against risk limits,
  compliance rules, and market conditions. Use before any real money trade.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - AskUserQuestion
---

## Checks (in order)

### 1. Position Limit Check
\`\`\`bash
$B goto https://portfolio.broker.com
$B snapshot -i                          # Find position table
$B text | grep "AAPL"                   # Extract current size
# Verify: proposed trade + current position < limit
\`\`\`

### 2. Execution Price Check
\`\`\`bash
$B goto https://market.example.com
$B snapshot -i
$B click @e2                            # Get live quote
$B text                                 # Extract bid/ask
# Verify: order price within 1% of market
\`\`\`

### 3. Settlement Risk Check
\`\`\`bash
# Check: T+2 settlement, no fails expected, margin available
# Auto-fail if margin would drop below 25%
\`\`\`

## Result

If all pass:
- Write TRADE_APPROVED.md
- Claude proceeds to execution

If issues found:
- Auto-fix obvious ones (e.g., adjust price)
- Flag risk violations (e.g., position limit)
- AskUserQuestion for final approval
```

---

## Testing Strategy

### E2E Test Example: Trade Execution

**`tests/e2e/trade-execution.test.ts`:**
```typescript
describe('Trade Execution Flow', () => {
  it('should validate trade before execution', async () => {
    // 1. /finance-briefing: Market context
    const briefing = await runSkill('/finance-briefing', {
      mode: 'market-analysis',
    });
    expect(briefing.hasMajorEvents).toBe(false);

    // 2. /trade-review: Pre-execution validation
    const review = await runSkill('/trade-review', {
      symbol: 'AAPL',
      shares: 100,
      orderType: 'market',
    });
    expect(review.status).toBe('approved');

    // 3. /qa-trading: Paper test
    const paperTest = await runSkill('/qa-trading', {
      symbol: 'AAPL',
      shares: 100,
      account: 'paper',
    });
    expect(paperTest.executed).toBe(true);
    expect(paperTest.positionAppeared).toBe(true);
    expect(paperTest.regressionTestGenerated).toBe(true);

    // 4. Live execution (only if all above pass)
    const liveExecution = await executeTrade({
      symbol: 'AAPL',
      shares: 100,
      screenshot: true,
    });
    expect(liveExecution.success).toBe(true);
    expect(fs.existsSync(liveExecution.evidencePath)).toBe(true);
  });
});
```

---

## Security Considerations

### 1. Cookie Management
```bash
# Import broker cookies securely
$B setup-browser-cookies  # Opens interactive picker
# User selects which cookies to import (not automated)
# Cookies stored in-process, never written to disk
```

### 2. Credential Handling
```typescript
// NEVER pass API keys to gstack
// Instead: Use environment variables + credential vaults

const apiKey = process.env.ALPACA_API_KEY;  // From secure vault
const tradeResponse = await alpacaAPI.submitOrder({
  symbol: 'AAPL',
  qty: 100,
  apiKey,  // Not exposed to browser/gstack
});

// gstack only gets: order confirmation screenshot
$B screenshot /tmp/trade-confirmation.png
```

### 3. Audit Trail
```bash
# Every decision is logged with evidence
~/.gstack/analytics/skill-usage.jsonl
# Contains: skill, timestamp, duration, outcome
# + /tmp/*.png screenshots
# + console logs with timestamps

# Produces: legal-grade audit trail for compliance
```

---

## Implementation Roadmap

### Week 1: Foundation
- [ ] Day 1-2: Integrate gstack /browse into NeoMind
- [ ] Day 3-5: Build /trade-review skill
- [ ] Day 6-7: Test /browse + /trade-review together

### Week 2: Finance Workflows
- [ ] Day 8-10: Build /finance-briefing skill
- [ ] Day 11-12: Integrate with market data APIs
- [ ] Day 13-14: End-to-end testing

### Week 3: Advanced Testing
- [ ] Day 15-17: Adapt /qa for trading (/qa-trading)
- [ ] Day 18-19: Paper trading validation tests
- [ ] Day 20-21: Live execution with safeguards

### Week 4: Parallelization
- [ ] Day 22-24: Conductor integration
- [ ] Day 25-26: Dashboard for parallel sessions
- [ ] Day 27-28: Load testing

---

## Success Metrics

### Phase 1 (/browse)
- [ ] Can extract live prices from 3+ financial websites
- [ ] Latency < 500ms per command
- [ ] 95% reliability over 1 week

### Phase 2 (/trade-review)
- [ ] Blocks 100% of trades that violate position limits
- [ ] Catches settlement risk 100% of cases
- [ ] Manually approves < 1% of valid trades

### Phase 3 (/finance-briefing)
- [ ] Produces actionable portfolio decisions
- [ ] Evidence trails 100% complete
- [ ] Users prefer to briefing over manual analysis

### Phase 4 (/qa-trading)
- [ ] Paper trades match live execution 99%+
- [ ] Regression tests cover 90%+ of edge cases
- [ ] Zero bugs slip through to live trading

### Phase 5 (Conductor)
- [ ] Run 10 parallel sessions without conflicts
- [ ] Total decision cycle time < 5 minutes
- [ ] Dashboard shows all 10 sessions in real-time

---

## Risk Mitigation

### 1. Browser Automation Risk
**Risk:** gstack /browse crashes mid-trade
**Mitigation:** Fallback to manual execution, screenshot evidence before execution

### 2. Decision Logic Bug Risk
**Risk:** /trade-review incorrectly approves risky trade
**Mitigation:** Always require human final approval for live trades, limit size

### 3. Market Impact Risk
**Risk:** Parallel execution causes slippage
**Mitigation:** Enforce minimum time between trades, use limit orders

---

## Conclusion

gstack is a strong fit for NeoMind because:

1. **Real browser automation** — Financial UI interactions are complex, screenshots are mandatory
2. **Structured workflows** — Finance demands audit trails; gstack is built for this
3. **Testing integration** — Paper trading first is non-negotiable; gstack has /qa built in
4. **Parallel execution** — Markets move fast; 10-15 concurrent workflows are needed
5. **Evidence trails** — Compliance requires proof of every decision; gstack provides it

Recommended approach:
- Phase 1-2 (Weeks 1-2): Get /browse + /trade-review working
- Phase 3-4 (Weeks 3-4): Add /finance-briefing + /qa-trading
- Phase 5+ (Weeks 5+): Conductor parallelization + advanced features

Total effort: 4-6 weeks to full integration. High confidence in success.
