# Calendar Spread (Long Time Diagonal)

## What it is
A calendar spread (also "horizontal" or "time" spread) buys a longer-dated
option and sells a shorter-dated option at the same strike. The long
option keeps its time premium longer; the short option decays faster.
Profit if the underlying stays near the strike AND implied volatility rises
or stays flat. Max loss = the net debit paid (defined-risk per user
constraint). Used as a directional/neutral premium-decay strategy.

## When it works
- **Underlying pins near strike at the front-month expiry**.
- **IV term structure is favorable**: front-month IV elevated relative to
  back-month.
- **Pre-event setups**: pre-FOMC, pre-earnings on indexes (NOT individual
  stocks where directional risk dominates).

## When it fails
- **Big directional moves**: the trade needs the underlying near the strike.
  Whipsaws kill it.
- **Term-structure shifts**: if back-month IV collapses faster than
  front-month, the trade loses even with correct direction.
- **Complex Greeks**: vega-positive, theta-positive, but gamma-negative —
  beginners often size wrong.
- **Expiry liquidity**: closing spreads in low-volume strikes is painful.

## Tax & compliance considerations
- Equity options held <12 months → short-term capital gains/losses (IRS
  Pub 550).
- Each leg's P&L is generally tracked separately on 1099-B.
- A calendar spread on a single underlying typically does NOT trigger
  straddle rules (different expirations), but DIAGONAL spreads with
  asymmetric strikes can trigger §1092 straddle treatment in edge cases —
  consult a tax pro.
- §1256 60/40 applies if run on SPX (cash-settled index), NOT on SPY.

## $10k feasibility
Feasible. Net debit per spread typically $100-300. $10k supports
multiple concurrent spreads.

## First-week starter checklist
1. Pick a liquid underlying you expect to pin (SPY, QQQ near a major level,
   pre-FOMC).
2. Buy 60-DTE ATM call (or put), sell 30-DTE same strike.
3. Net debit becomes max loss — risk no more than 2% of account per
   spread.
4. Plan: close at 25-50% of max debit profit, or roll the short call if
   it expires near the money.
5. Paper-trade 4-6 cycles before real capital — Greeks can surprise.

## Further reading
- Investopedia: https://www.investopedia.com/terms/c/calendarspread.asp
- OIC: https://www.optionseducation.org/strategies/all-strategies/calendar-spread
- TastyLive: https://www.tastylive.com/concepts-strategies/calendar-spread
- IRS Pub 550 (straddle, §1092): https://www.irs.gov/pub/irs-pdf/p550.pdf
