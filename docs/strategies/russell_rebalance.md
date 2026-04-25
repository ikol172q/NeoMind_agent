# Russell Reconstitution Trade

## What it is
Each June, FTSE Russell reconstitutes its Russell 1000, 2000, and 3000
indexes — adding and dropping names based on prior-May market cap. Index
funds tracking these benchmarks must mechanically rebalance, creating
predictable buying pressure on additions and selling pressure on deletions
in the days leading up to reconstitution day (last Friday of June). Trade:
go long upcoming additions and short upcoming deletions in late May / early
June; exit by reconstitution day.

## When it works
- **Wide preliminary list spread**: when a name is a clean addition with
  low pre-existing index participation.
- **Smaller names**: where forced index demand is large relative to ADV.
- **Years with smaller "frontrunning" arbitrage participation**.

## When it fails
- **Crowded trade**: arb has compressed the alpha materially since 2010.
  FTSE has also reformed methodology to reduce predictability.
- **Last-minute list changes**: preliminary lists can change between May
  publication and June reconstitution — busted thesis.
- **PDT-relevant**: typical execution uses 4-6 round trips in a 4-week
  window. At $10k this likely violates PDT.
- **Single-name idiosyncratic risk**: a deletion that gets buyout offer
  makes the short blow up.

## Tax & compliance considerations
- All gains short-term, ordinary-income rates.
- Per user constraint, NEVER short shares directly (requires margin and
  exposes to unlimited loss). Use defined-risk put debit spreads instead.
- Wash-sale risk if you re-trade same names year-over-year (most additions
  are different names each year, so risk is low in practice).

## $10k feasibility
Marginally feasible. Concentrated in 2-3 names of $2-3k each. PDT-bind is
the binding constraint. Execute slowly across 2-3 sessions to stay under
3 day-trades per 5 days.

## First-week starter checklist
(May timeframe, when FTSE publishes preliminary lists)
1. Download FTSE Russell preliminary additions/deletions list (mid-May).
2. Filter for clean adds: small caps with limited current index
   participation, deep liquid options markets.
3. Buy 2-3 add names in late May, ~$2,000-3,000 each.
4. For deletions you want to short: use a 30-DTE OTM put debit spread (NOT
   a naked short).
5. Exit ALL positions by Tuesday before reconstitution Friday — front-running
   the rebalance is where the alpha is.

## Further reading
- FTSE Russell reconstitution: https://www.ftserussell.com/research-insights/russell-reconstitution
- Investopedia: https://www.investopedia.com/articles/investing/070815/russell-reconstitution-explained.asp
- S&P research on index effects: https://www.spglobal.com/spdji/en/research/article/index-effects-on-stock-prices/
- FINRA PDT rule: https://www.finra.org/investors/learn-to-invest/advanced-investing/day-trading-margin-requirements-know-rules
