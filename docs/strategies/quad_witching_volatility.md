# Quad Witching Volatility Setup

## What it is
"Quad witching" refers to the simultaneous expiration of four classes of
derivatives — stock-index futures, stock-index options, single-stock futures,
and single-stock options — on the third Friday of March, June, September, and
December. The mechanical position-unwinding around these dates can produce
elevated volatility, especially near strikes with large open interest ("pin
risk"). Trade: identify pinned strikes pre-expiry, structure defined-risk
options trades to capture either pinning or breakout from pinning.

## When it works
- **High open interest concentration**: when a major strike has 10x typical
  OI, pinning is more likely.
- **Low realized vol going in**: gives room for the breakout/breakdown trade.
- **Index-level (SPX/SPY) trades** are more reliable than single-stock.

## When it fails
- **Edge is small**: pin risk often resolves quietly with no clean trade
  signature.
- **Slippage** in options around expiry is real — bid/ask widens.
- **PDT-relevant**: layered intraday adjustments around expiry can produce
  multiple round trips quickly.
- **This is largely an educational strategy** — the real edge requires
  market-maker-level positioning data.

## Tax & compliance considerations
- Equity options on SPY/QQQ: short-term capital gains, ordinary rates.
- **§1256 alternative**: SPX (cash-settled S&P index) options qualify for
  60% LTCG / 40% STCG REGARDLESS of holding period (IRS Pub 550, IRC §1256).
  Worth running on SPX if scaling up.
- Wash-sale rules apply to equity options.

## $10k feasibility
Feasible at small size. Long debit spreads ($200-500) are appropriate.
Per user constraint, only defined-risk structures.

## First-week starter checklist
1. Mark next 4 quad-witch dates: third Friday of Mar/Jun/Sep/Dec.
2. 3 days prior, look at SPY option chain for the expiring monthly contract.
3. Identify if SPY is within 0.5% of a high-OI strike. If yes, "pin risk" is
   in play.
4. Express view: if pinning expected, sell a tight iron condor; if breakout
   expected, buy a long straddle expiring the following week.
5. Size to <2% of account at risk per setup. Educational position; real
   alpha is small.

## Further reading
- Investopedia: https://www.investopedia.com/terms/q/quadruplewitching.asp
- CBOE expiration calendar: https://www.cboe.com/optionsexpirationcalendar/
- Options Industry Council: https://www.optionseducation.org/
- IRS Pub 550 (§1256 contracts): https://www.irs.gov/pub/irs-pdf/p550.pdf
