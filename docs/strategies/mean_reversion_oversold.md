# Mean-Reversion Oversold Bounce (RSI-2)

## What it is
A short-term mean-reversion system popularized by Larry Connors. The classical
RSI-2 setup: only trade long-side, only on uptrending instruments (price above
200-day moving average), enter when 2-period RSI drops below 10 (i.e., 2 days
of severe selling), exit when price closes back above its 5-day moving average.
Holding period typically 1-5 days. Applied to broad-index ETFs (SPY, QQQ, IWM)
to limit single-stock idiosyncratic risk.

## When it works
- **Trending bull markets with shallow pullbacks**: 2017, 2024 — high hit
  rate, ~70-75% of trades profitable.
- **Liquid, mean-reverting underlyings**: SPY/QQQ/IWM/XLF.
- **Defined exit rule prevents over-staying**: discipline > prediction.

## When it fails
- **Strong-trend selloffs**: Q4 2018, March 2020. RSI(2) goes deeply oversold
  and stays there for 5+ days. Without a stop, drawdowns are severe.
- **Without 200-DMA filter**: long bear markets eat the strategy alive.
- **Many small wins, occasional large loss** — typical R:R is asymmetric in
  the WRONG direction unless stops are enforced.
- **Tight PDT bind**: 1-5 day hold cycles + active rotation easily exceed
  PDT under $25k.

## Tax & compliance considerations
- All gains short-term → ordinary-income rates.
- Wash-sale risk is high: re-entering SPY within 30 days of an exit-at-loss
  triggers wash-sale (IRS Pub 550 §1091).
- ETFs that hold the same underlyings (SPY ↔ IVV ↔ VOO) are almost
  certainly substantially identical for wash-sale purposes — swapping does
  NOT cleanly avoid the rule.

## $10k feasibility
Feasible if you trade only 1 ETF position at a time and keep round-trip
count under 3 per 5 business days. Strategy becomes infeasible to run on
its full design (5+ concurrent setups) without $25k.

## First-week starter checklist
1. Pick basket: SPY, QQQ, IWM. Pull daily OHLCV for the last 2 years.
2. Backtest by hand: count how often 200-DMA + RSI(2)<10 + close > 5-DMA
   exit fired, and what return resulted.
3. Paper-trade 4 weeks before risking capital.
4. When live: 1 position only, exit by rule, log every trade including
   reason for any deviation.
5. Track day-trade count. Stop the strategy if you hit 2 round trips in
   a 5-day window.

## Further reading
- Investopedia: https://www.investopedia.com/terms/m/meanreversion.asp
- Investopedia RSI primer: https://www.investopedia.com/articles/active-trading/052014/how-use-rsi-relative-strength-index.asp
- Larry Connors "Short Term Trading Strategies That Work" (2009)
- FINRA PDT rule: https://www.finra.org/investors/learn-to-invest/advanced-investing/day-trading-margin-requirements-know-rules
