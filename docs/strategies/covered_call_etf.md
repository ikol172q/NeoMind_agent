# ETF Covered Call

## What it is
A covered call combines a long stock/ETF position (100 shares per contract)
with a short call option against it. You collect the call premium upfront.
If the underlying stays below the strike at expiry, the call expires worthless
and you keep the premium AND the shares. If the underlying rises above the
strike, the shares are called away — you've capped your upside but you keep
the premium plus any gain to the strike. Best deployed on ETFs the user is
content to hold long-term (XLF, IWM, QQQ, SPY) or already owns.

## When it works
- **Sideways-to-mildly-bullish markets**: calls expire worthless, premium
  captured monthly.
- **High implied volatility**: richer premium = better income.
- **Quality underlyings the user wants to own**: assignment is acceptable.

## When it fails
- **Strong rallies**: shares called away at strike; you miss the run-up.
  This is the "I sold the rocket" regret.
- **Sharp drawdowns**: premium offsets only a small fraction of stock loss.
- **Pre-earnings high IV**: tempting premium, but risk of gap.
- **Special dividends / corporate actions** can complicate assignment.

## Tax & compliance considerations
- Critical IRS rule (Pub 550): **a "qualified covered call" does NOT suspend
  the long-term holding period** of the underlying stock. A QCC is an
  out-of-the-money call with at least 30 days to expiry, struck above the
  prior day's close, and meeting strike-price tables in IRS Pub 550.
- An **unqualified** (deeply ITM) covered call DOES suspend the holding
  period — meaning if the call is assigned or you close it, you may convert
  what would have been LTCG into STCG. Stay with OTM, monthly, near-the-
  money-or-higher to keep QCC status.
- Premium recognized when option is closed, expires, or assigned.
- Wash-sale interaction: if call is assigned at a loss-equivalent strike,
  combined with a stock buyback within 30 days, wash-sale can apply.

## $10k feasibility
Feasible but tight on price. Need 100 shares of underlying:
- SPY at ~$550 = $55,000 — out of reach.
- QQQ at ~$500 = $50,000 — out of reach.
- IWM at ~$220 = $22,000 — out of reach.
- XLF at ~$45 = $4,500 — workable.
- KWEB at ~$30 = $3,000 — workable.
At $10k, prefer lower-priced ETFs OR consider Poor Man's Covered Call
(LEAPS-based, capital-efficient) — see separate entry.

## First-week starter checklist
1. Pick an ETF you'd like to own and that fits your budget for 100 shares
   (XLF or KWEB at $10k).
2. Buy 100 shares.
3. Sell a 30-45 DTE call at delta ~0.20-0.25, struck at least 5% OTM.
4. Set rule: close at 50% of max profit, or roll to next month at 21 DTE
   if untested.
5. Track every cycle in a log: entry date, strike, premium, outcome.

## Further reading
- Investopedia: https://www.investopedia.com/terms/c/coveredcall.asp
- OIC strategy page: https://www.optionseducation.org/strategies/all-strategies/covered-call-buy-write-or-overwrite
- IRS Pub 550 (QCC rules): https://www.irs.gov/pub/irs-pdf/p550.pdf
- TastyLive on covered calls: https://www.tastylive.com/concepts-strategies/covered-call
