# Collar (Protective Put + Covered Call)

## What it is
A collar is the combination of three positions: long 100 shares, long an
OTM put (the protective floor), and short an OTM call (paying for the put).
Result: a defined corridor of returns. Below the put strike, your downside
is capped. Above the call strike, your upside is capped. Net cost is often
near zero or a small debit. Used by long-term holders who want to lock in
recent gains without selling (which would trigger LTCG tax) — a "sleep at
night" hedge for concentrated positions.

## When it works
- **After large unrealized gains**: protect gains without taxable sale.
- **Defined-risk corridor for nervous markets**: known floor + capped ceiling.
- **Pre-major-event hedging**: an upcoming earnings date or macro event.

## When it fails
- **Strong rallies**: shares called away at the cap. The "I sold the rocket"
  outcome.
- **Multiple legs increase commissions and slippage** vs simple stock.
- **Tax complexity**: married-put rules can suspend the holding period —
  this is the central gotcha of collar tax.

## Tax & compliance considerations
- **Married put rule (IRS Pub 550, §1233)**: buying a put on a stock you
  already hold long-term can RESET your holding period under certain
  conditions. The exact rules depend on whether the put is purchased at
  the same time as the stock (married put) vs after holding it long-term.
  If you've held the stock >12 months, buying a protective put generally
  does NOT reset; if held <12 months, the put suspends the holding period.
- **Qualified covered call rules (IRS Pub 550)**: the short call must be
  OTM, ≥30 days to expiry, and within strike-table limits to be "qualified"
  and not suspend the LTCG holding period.
- THIS IS A COMPLEX AREA — consult a tax professional before initiating
  collars on positions with significant unrealized gains.
- Recognized at close, expiry, or assignment of each leg.

## $10k feasibility
Feasible only if you already own (or can buy) 100 shares of the underlying.
At $10k, this means lower-priced ETFs/stocks: XLF (~$45), KWEB (~$30), or
single-name positions in $30-100 range.

## First-week starter checklist
1. Identify a long-term position (or buy one) of 100 shares — XLF or KWEB
   work at $10k.
2. Buy a 60-90 DTE protective put 5-7% OTM. Cost: ~1-2% of position value.
3. Sell a 30 DTE call 5% OTM, monthly. Premium covers most of the put cost.
4. Manage monthly: roll the short call. Hold the put until expiry or close
   if regime changes.
5. Track tax holding period carefully. Consult a tax pro on first setup.

## Further reading
- Investopedia: https://www.investopedia.com/terms/c/collar.asp
- OIC: https://www.optionseducation.org/strategies/all-strategies/collar
- IRS Pub 550 (married puts, QCC, holding period): https://www.irs.gov/pub/irs-pdf/p550.pdf
- Fidelity collar primer: https://www.fidelity.com/learning-center/investment-products/options/options-strategy-guide/collar
