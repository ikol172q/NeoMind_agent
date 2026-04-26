# Iron Condor on Index ETF

## What it is
An iron condor is a market-neutral, defined-risk options structure: combine
a bull put spread (below the underlying) with a bear call spread (above the
underlying), all in the same expiration. You collect two net credits. Max
profit = total credit (achieved if the underlying stays between the short
strikes at expiry). Max loss = (width of one side − total credit) × 100,
achieved if the underlying breaks decisively in either direction. Best run
on liquid index ETFs (SPY, QQQ, IWM) where directional moves are dampened
by basket diversification.

## When it works
- **Range-bound markets**: classic 30-60 day cycles between earnings.
- **High IV-rank entry**: rich premium on both sides.
- **Mechanical management at 50% of max profit**: take winners early.
- **Defending tested side at 21 DTE**: reduces gamma risk near expiry.

## When it fails
- **Trend regimes**: persistent directional moves blow through one side.
  2022 H1 was brutal for short-vol strategies.
- **Volatility expansion**: even if price stays within the wings, IV spike
  can produce mark-to-market losses requiring close.
- **Pin risk near expiry**: small moves can flip P&L dramatically.
- **Asymmetric P&L**: many small wins, occasional max loss erases multiple
  cycles.

## Tax & compliance considerations
- Equity-options ICs (on SPY/QQQ/IWM) are short-term capital gains/losses.
- **SPX index options ICs qualify for §1256 60/40 treatment** — 60% LTCG +
  40% STCG regardless of holding period (IRS Pub 550, IRC §1256). This is
  a **major** tax advantage — worth running on SPX once familiar.
- Wash-sale: equity-option ICs can trigger wash-sale on overlap with prior
  closed losses.
- Multi-leg P&L reporting requires careful 1099-B reconciliation.

## $10k feasibility
Feasible. A $5-wide iron condor on SPY uses ~$400-450 buying power per
contract. $10k supports several concurrent ICs across underlyings.

## First-week starter checklist
1. Pick SPY or QQQ when IV-rank > 30.
2. Identify expected move (1 SD) from option chain or use deltas.
3. Sell 30-45 DTE iron condor: short strikes at delta ~0.16 each side, long
   strikes 5 wider on each side. Total credit ~30% of width.
4. Plan: close at 50% of max profit. If one side tested at 21 DTE, roll
   the untested side closer (collect more credit) or close the trade.
5. Risk per IC ≤ 3% of account ($300 at $10k).

## Further reading
- Investopedia: https://www.investopedia.com/terms/i/ironcondor.asp
- OIC: https://www.optionseducation.org/strategies/all-strategies/iron-condor
- TastyLive: https://www.tastylive.com/concepts-strategies/iron-condor
- IRS §1256 contracts (Pub 550): https://www.irs.gov/pub/irs-pdf/p550.pdf
