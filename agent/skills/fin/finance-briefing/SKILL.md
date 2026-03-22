---
name: finance-briefing
description: Market analysis using forcing questions — structure decisions before acting
modes: [fin]
allowed-tools: [Bash, Read, WebSearch]
version: 1.0.0
---

# Finance Briefing — Structured Decision Framework

You are conducting a structured investment analysis, adapted from YC office hours methodology.
Before any portfolio action, work through these 6 forcing questions.

## The 6 Financial Forcing Questions

### 1. Current Reality
"What is your ACTUAL allocation right now?"
- Pull real portfolio data (not from memory)
- Compare stated allocation vs actual
- Flag any drift from target

### 2. Market Context
"What is happening in the market TODAY that is relevant?"
- Macro: Fed, rates, inflation, GDP
- Sector: what's moving and why
- Use multi-source news (EN + ZH)
- Separate FACTS from NARRATIVES

### 3. Desperate Specificity
"What is the EXACT trade, not the thesis?"
- "I'm bullish on AI" → "Buy 50 shares of NVDA at market, hold 6 months"
- Quantify: symbol, shares/dollars, order type, time horizon
- No vague "maybe I should..."

### 4. Narrowest Wedge
"What is the minimum viable trade?"
- Don't go all-in. What's the smallest meaningful position?
- Kelly criterion or fixed-fraction sizing
- Start with paper trade if uncertain

### 5. Evidence Check
"What does the DATA say?"
- Earnings (actual vs estimate)
- Technicals (price, volume, RSI, moving averages)
- Sentiment (news flow, social, options flow)
- Quantify with QuantEngine — no gut feelings

### 6. Future Fit
"Does this align with your 1-year investment goals?"
- Target allocation: are you under/over exposed?
- Time horizon: does this trade's horizon match your plan?
- Risk tolerance: does adding this position increase portfolio risk beyond comfort?

## Output: PORTFOLIO_DECISION Document

```
## Decision: [BUY/SELL/HOLD] [SYMBOL]
- Action: [specific trade details]
- Size: [shares/dollars, % of portfolio]
- Rationale: [linked to forcing question answers]
- Risk: [what could go wrong, max loss]
- Time horizon: [specific]
- Confidence: [%]
- Review date: [when to re-evaluate]
```

This document feeds into `/trade-review` for validation before execution.

## Rules

- Ask questions ONE AT A TIME
- NEVER skip the evidence check — gut feeling is not analysis
- ALL numbers through QuantEngine
- Cross-reference at least 2 sources for any factual claim
