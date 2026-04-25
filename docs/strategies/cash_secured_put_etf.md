# ETF Cash-Secured Put

## What it is
A cash-secured put (CSP) sells a put option on an ETF you'd be willing to
own, while setting aside enough cash to buy 100 shares at the strike if
assigned. You collect the premium upfront. If the underlying stays above
the strike at expiry, the put expires worthless — you keep the premium. If
it drops below, you're assigned 100 shares at the strike (effective basis
= strike − premium). The strategy combines income generation with a
"discount entry" mechanic for a stock you wanted anyway.

## When it works
- **Range-bound to mildly bullish markets**: puts expire worthless; premium
  banked.
- **High IV environments**: VIX > 20 → richer put premium.
- **ETFs you'd own anyway**: XLF, IWM, KWEB, SPY (if budget) — assignment
  becomes a feature, not a bug.

## When it fails
- **Sharp selloffs**: assigned at the strike, then stock keeps falling.
  You're long-the-bottom.
- **Premium feels like income** — investors forget it's risk compensation.
- **Earnings / macro events** can spike IV after entry, producing paper
  losses (mark-to-market).
- **Capital tied up** as cash collateral may underperform versus deploying
  the cash productively.

## Tax & compliance considerations
- Premium taxed when option closes, expires, or is assigned (IRS Pub 550).
- If put expires worthless: short-term capital gain.
- If put is assigned: you reduce the BASIS of the acquired shares by the
  premium received. Holding period of the new shares starts at assignment
  date.
- If put is closed: short-term capital gain/loss for the difference.
- Wash-sale interaction with prior losses on the same underlying.

## $10k feasibility
Feasible. Cash collateral = strike × 100. ETFs in your budget at $10k
(strike × 100 ≤ $10k):
- KWEB $30 strike = $3,000 collateral. 
- XLF $35 strike = $3,500 collateral.
- IWM $200 strike = $20,000 — out of reach.
- SPY $550 strike = $55,000 — out of reach (use SPY put on a lower strike
  if budget allows).

Run 1-2 CSPs concurrently with $5k-7k cash collateral.

## First-week starter checklist
1. Pick an ETF you'd be happy to own at a slight discount (XLF, KWEB).
2. Sell a 30-45 DTE put at delta ~0.20-0.30. This is roughly the strike
   you'd be assigned at ~25% probability.
3. Set aside the cash collateral (strike × 100).
4. Plan: close at 50% of max profit, OR accept assignment if breached at
   expiry.
5. If assigned, plan the next move: hold long, or sell a covered call
   (the "wheel" strategy).

## Further reading
- Investopedia: https://www.investopedia.com/terms/c/cash-secured-put.asp
- OIC: https://www.optionseducation.org/strategies/all-strategies/cash-secured-put
- TastyLive on CSPs: https://www.tastylive.com/concepts-strategies/cash-secured-put
- IRS Pub 550 (option taxation): https://www.irs.gov/pub/irs-pdf/p550.pdf
