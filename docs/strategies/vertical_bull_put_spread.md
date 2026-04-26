# Bull Put Credit Spread

## What it is
A bull put spread (also "short put vertical") is a defined-risk bullish
strategy. Sell an OTM put (closer to the underlying) and buy a further-OTM
put with the same expiration. Collect a net credit. Maximum profit = net
credit, achieved if the underlying stays above the short strike at expiry.
Maximum loss = (width of strikes − net credit) × 100, achieved if the
underlying drops below the long strike. The bought put caps the loss — this
is what makes the strategy "defined-risk" (per the user's hard rule).

## When it works
- **Range-bound to mildly bullish markets**: expire OTM with full credit.
- **High IV-rank**: richer credit relative to width.
- **Liquid underlyings**: SPY, QQQ, IWM have tight option markets.
- **Mechanical management**: close at 50% of max profit captures most of the
  edge with less tail risk.

## When it fails
- **Asymmetric P&L**: small credit vs. wide max loss. One bad cycle erases
  multiple wins.
- **Gap-down events**: underlying jumps through both strikes overnight.
- **Assignment risk near expiry**: in-the-money short puts can be early-
  exercised, especially around dividends.
- **Volatility expansion** (VIX spike) hurts even when direction is correct.

## Tax & compliance considerations
- Equity options: short-term capital gains/losses (IRS Pub 550).
- §1256 does NOT apply to equity options. SPX index options DO qualify
  for 60/40 LTCG/STCG treatment — a meaningful advantage if scaling up.
- Closed positions: simple gain/loss on the spread.
- Wash-sale rules apply. Re-opening a similar spread within 30 days at a
  loss may trigger wash-sale.

## $10k feasibility
Trivial. Buying power for a $5-wide spread is approximately $400-450 per
contract (width minus credit). $10k can run multiple concurrent spreads.

## First-week starter checklist
1. Pick a liquid underlying with high IV-rank (SPY/QQQ when VIX > 18, or
   single-name like AAPL/NVDA pre-earnings).
2. Sell 30-45 DTE put at delta ~0.20-0.30; buy 5 strikes lower for defined
   risk.
3. Target a net credit of ~30% of the width (e.g., $1.50 credit on a $5
   spread).
4. Plan: close at 50% of max profit. Defend by rolling out at 21 DTE if
   tested.
5. Risk no more than 2-3% of account per spread ($200-300 at $10k).

## Further reading
- Investopedia: https://www.investopedia.com/terms/b/bullputspread.asp
- OIC: https://www.optionseducation.org/strategies/all-strategies/bull-put-spread-credit-put-spread
- TastyLive: https://www.tastylive.com/concepts-strategies/short-put-vertical
- IRS Pub 550 (options, §1256): https://www.irs.gov/pub/irs-pdf/p550.pdf
