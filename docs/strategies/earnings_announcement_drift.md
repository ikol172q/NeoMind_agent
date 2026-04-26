# Earnings-Announcement Volatility Trade

## What it is
A short-duration trade structured around a single company's earnings release.
Two flavors: directional (buy or sell shares pre-report based on conviction)
and volatility-arbitrage (compare the option-implied move to the historical
average; trade where pricing diverges). For the user's defined-risk constraint,
this catalog version uses long-premium options (defined max loss = debit) or
defined-risk credit spreads — never naked positions.

## When it works
- **Underpriced volatility**: when implied move is materially below average
  historical move, long-straddle / long-strangle setups can pay.
- **Asymmetric setups**: when fundamentals strongly support a beat AND
  implied vol is reasonable.
- **Mid-cap names with less institutional coverage**: more inefficient
  pricing.

## When it fails
- **Implied moves are usually correctly priced** by market makers. Edge is
  small unless you have differential information.
- **IV crush** post-report can torch long-premium setups even when direction
  is right.
- **Single-name binary risk**: one report can drop the stock 20%+ overnight.
- **PDT-relevant** if you trade multiple cycles per quarter.

## Tax & compliance considerations
- Equity options: short-term capital gains/losses (most positions <12 months).
- §1256 treatment does NOT apply to single-stock equity options.
- Wash-sale rules apply to option positions across substantially identical
  contracts (IRS Pub 550).
- Multi-leg positions in the same name across cycles can cascade wash sales.

## $10k feasibility
Feasible with discipline. Risk per trade should be ≤ 2% of account ($200) —
this means buying 1-2 contracts of a $1-2 debit spread, not directional
single-leg purchases. Stick to defined-risk structures per user constraint.

## First-week starter checklist
1. Build a watchlist of 5 high-liquidity options names (AAPL, NVDA, AMZN,
   GOOG, META).
2. Track implied move (from straddle pricing) vs historical average move
   over the past 8 quarters.
3. When implied move is <80% of historical average, consider long
   straddle/strangle.
4. Use only defined-risk structures. Risk no more than $200 per setup at
   $10k.
5. Paper-trade 4-8 cycles before risking real capital.

## Further reading
- Investopedia (straddles/strangles): https://www.investopedia.com/articles/active-trading/030415/play-earnings-season-strangles-and-straddles.asp
- CME implied move guide: https://www.cmegroup.com/education/courses/introduction-to-options/calculating-the-implied-move.html
- Options Industry Council: https://www.optionseducation.org/
- IRS Pub 550 (options taxation): https://www.irs.gov/pub/irs-pdf/p550.pdf
