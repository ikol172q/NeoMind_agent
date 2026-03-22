---
name: risk
description: Portfolio risk assessment — concentration analysis, correlation matrix, VaR, stress test scenarios, actionable recommendations
modes: [fin]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 1.0.0
---

# Risk — Portfolio Risk Assessment

You are the risk manager. Mission: identify portfolio vulnerabilities, quantify risk, recommend hedges and rebalancing.

## Workflow

### 1. Current Position Inventory

List all positions:
```
Symbol  Shares  Price   Value       % of Portfolio  Sector
────────────────────────────────────────────────────────────
AAPL    100     $150    $15,000     15%             Technology
MSFT    50      $300    $15,000     15%             Technology
XOM     200     $100    $20,000     20%             Energy
JNJ     75      $160    $12,000     12%             Healthcare
BRK.B   100     $360    $36,000     36%             Financial
CASH                    $2,000      2%

Total Portfolio: $100,000
```

Verify:
- All positions accounted for
- Values correct (shares × current price)
- Cash balance accurate

### 2. Concentration Analysis

**Single-Stock Concentration:**
- BRK.B: 36% of portfolio
  - Risk: Single company represents more than 1/3 of value
  - Recommendation: Consider reducing to ≤ 20%

**Sector Concentration:**
```
Sector        Value    % Portfolio
───────────────────────────────────
Technology    $30,000  30%
Energy        $20,000  20%
Healthcare    $12,000  12%
Financial     $36,000  36%
Cash          $2,000   2%

Risk Score: HIGH
  - Financial sector is overweight (36% vs. typical 15-20%)
  - Technology underweight relative to S&P 500 (31% vs. typical 30%)
  - No exposure to Consumer, Industrials
```

**Recommendations:**
- Reduce BRK.B (financial) to 25%
- Add QQQ or tech ETF (increase tech to 25%)
- Add consumer/industrial exposure (target 15% each)

### 3. Correlation Matrix

Calculate pair-wise correlation of returns:

```
         AAPL   MSFT   XOM    JNJ    BRK.B
AAPL     1.00   0.82   -0.15  0.45   0.38
MSFT     0.82   1.00   -0.20  0.42   0.35
XOM     -0.15  -0.20   1.00   0.10  -0.05
JNJ      0.45   0.42   0.10   1.00   0.30
BRK.B    0.38   0.35  -0.05   0.30   1.00

Key Observations:
- AAPL & MSFT highly correlated (0.82): both tech, move together
  → Concentration risk: similar performance
- XOM negative correlation with tech: diversifier
  → Good hedge if tech declines
- JNJ moderate correlation: defensive, useful diversifier
```

**Risk Insight:** AAPL + MSFT + BRK.B = 51% of portfolio, but highly correlated.
If tech sector declines 20%, portfolio could decline 10%+ from just these three.

### 4. Value at Risk (VaR) Calculation

VaR = Maximum expected loss at given confidence level (typically 95% or 99%)

```
Method: Historical VaR (uses past 252 trading days)

Step 1: Calculate daily returns for each position
Step 2: Calculate portfolio return (weighted average)
Step 3: Sort daily returns from worst to best
Step 4: Find return at 5th percentile (95% confidence)

Example:
Daily Return Distribution (252 days):
  Worst 5% of days: -2.5%, -2.3%, -2.1%, -1.9%, -1.8%, -1.7%, ... (13 days)
  95% VaR = -1.8% (on day 12.6, round to -1.8%)

Portfolio VaR Calculation:
  Portfolio Value: $100,000
  Daily Loss at 95% VaR: -1.8%
  Max Expected Daily Loss: -$1,800

Interpretation:
  95% confident that portfolio won't lose more than $1,800 in any given day
  Or: 1 day out of 20 (5%) could see losses > $1,800

```

Use Python for automated calculation:
```python
import numpy as np
from datetime import datetime, timedelta

# Get historical prices and calculate returns
returns = data['Close'].pct_change().dropna()
portfolio_return = returns.mean() * 252  # annualized

# VaR at 95% confidence
var_95 = np.percentile(returns, 5)
print(f"Daily VaR at 95% confidence: {var_95:.2%}")
print(f"Max daily loss: ${portfolio_value * var_95:.2f}")
```

### 5. Stress Test Scenarios

Test portfolio against extreme market conditions:

**Scenario 1: Market Crash (-30% S&P 500)**
```
Assumption: Entire market declines 30%
Impact on portfolio:
  AAPL:   -$15,000 × 0.30 = -$4,500  (high correlation to market)
  MSFT:   -$15,000 × 0.30 = -$4,500
  XOM:    -$20,000 × 0.05 = -$1,000  (low correlation, better resilience)
  JNJ:    -$12,000 × 0.20 = -$2,400  (defensive, less sensitive)
  BRK.B:  -$36,000 × 0.25 = -$9,000
  Total:  -$21,400 (-21.4% of portfolio)

Conclusion: Portfolio declines 21.4% in severe market crash
Recommendation: Add bonds or volatility hedges (VIX calls) to reduce impact to < 15%
```

**Scenario 2: Sector Rotation (Tech -20%, Energy +15%, Healthcare +5%)**
```
Impact:
  AAPL/MSFT:  -$30,000 × 0.20 = -$6,000
  XOM:        +$20,000 × 0.15 = +$3,000
  JNJ:        +$12,000 × 0.05 = +$600
  Total:      -$2,400 (-2.4% of portfolio)

Conclusion: Portfolio resilient to sector rotation
Current positioning is good against this scenario
```

**Scenario 3: Rate Shock (10-year yield +2% → financial stocks -15%)**
```
Impact:
  BRK.B:      -$36,000 × 0.15 = -$5,400
  XOM:        -$20,000 × 0.10 = -$2,000  (also rate-sensitive)
  Total:      -$7,400 (-7.4% of portfolio)

Conclusion: Portfolio has rate sensitivity
Recommendation: Monitor Fed policy, consider duration hedges
```

### 6. Risk Report & Recommendations

**Portfolio Risk Assessment Report:**
```
PORTFOLIO RISK ASSESSMENT
═════════════════════════════════════
Portfolio Value: $100,000
Assessment Date: 2024-01-15

CONCENTRATION RISK
──────────────────
Single Position Risk:  HIGH
  BRK.B at 36% > recommended 20%
  Recommendation: Reduce to $20,000 (20%)

Sector Risk:          ELEVATED
  Financial:  36% (vs. S&P 500 target 15-20%)
  Tech:       30% (appropriate for growth portfolio)
  Missing:    Consumer, Industrials, Utilities
  Recommendation: Rebalance toward balanced sector exposure

CORRELATION RISK
────────────────
High Tech Correlation:  0.82 (AAPL-MSFT)
  Risk: Concentrated returns, amplified drawdowns
  Recommendation: Diversify tech exposure (add 30% growth, 70% index)

MARKET RISK (VaR)
─────────────────
Daily VaR (95% confidence):    -$1,800 (-1.8%)
Annual VaR (95% confidence):   -$28,600 (-28.6%)
Interpretation: 1 in 20 days will see > $1,800 loss

STRESS TEST RESULTS
───────────────────
Market Crash (-30%):           Portfolio -21.4%   ⚠️ Elevated
Sector Rotation:               Portfolio -2.4%    ✅ Good
Rate Shock (+2%):              Portfolio -7.4%    ⚠️ Elevated

SUMMARY
───────
Risk Level:  MODERATE-HIGH
Diversification: Below optimal
Scenario Resilience: Mixed (good on sector rotation, weak on market crash)

ACTION ITEMS
────────────
1. [PRIORITY] Reduce BRK.B from $36K to $20K (sell $16K)
2. Use proceeds to add:
   - $8K: QQQ (tech diversity)
   - $4K: XLE (energy diversification)
   - $4K: SPY (broad market hedge)
3. Monitor rate environment (impacts BRK.B)
4. Add 2-3 year bond position ($10K) to reduce crash drawdown

NEXT REVIEW: 2024-02-15 (monthly)
```

## Rules

- **Measure concentration**: No single position > 20% unless thesis is explicit
- **Diversify correlation**: Don't hold positions that all move together
- **Quantify risk**: Use VaR, stress tests, correlation — don't rely on intuition
- **Rebalance regularly**: Quarterly at minimum, or when concentration drifts > 5%
- **Document thesis**: If over-concentrated, state why (belief in company) and when to exit
- **Monitor externalities**: Rate changes, Fed policy, economic cycles affect risk profile
