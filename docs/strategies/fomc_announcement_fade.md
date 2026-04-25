# FOMC Day Volatility Fade

## What it is
The FOMC (Federal Open Market Committee) issues policy statements 8 times
per year at 2:00pm ET, followed by a 2:30pm Powell press conference. Index
ETFs (SPY, QQQ) often see large directional moves in the first 30-60 minutes,
which historically reverse in part within 1-3 days. The "fade" trade: wait
for the post-statement reaction, identify which direction overshot, take a
counter-position with a tight stop. Hold typically 1-3 days.

## When it works
- **Choppy / range-bound markets**: 2015, mid-2024 — fades follow through.
- **When the statement matches expectations**: initial reaction is often
  noise.
- **Defined risk via option spreads**: limit downside if the trend continues.

## When it fails
- **Trend days**: when Powell's tone shifts the regime (the 2018 Q4 hawkish
  pivot, 2022 Jackson Hole speech), the move extends and the fade gets
  steamrolled.
- **PDT-relevant**: 8 FOMC cycles per year is fine; layered intraday entries
  can multiply round trips.
- **Slippage during the announcement minute** is brutal — bid/ask widens.
- **Option IV crush** post-announcement can erase long-premium fades even
  with correct direction.

## Tax & compliance considerations
- Same-day or 1-2 day holds → all gains short-term, ordinary-income rates.
- Wash-sale risk high if you re-trade SPY/QQQ within 30 days at a loss.
- Consider SPX-style index options for §1256 60/40 treatment — but SPX has
  larger contract size, less retail-friendly.
- IRS Pub 550 governs.

## $10k feasibility
Feasible. Single position per FOMC cycle, defined-risk structure (debit spread
or vertical credit spread). Risk per trade ≤ 2% of account.

## First-week starter checklist
1. Mark the next 8 FOMC dates in your calendar (Federal Reserve website).
2. The day before, review the CME FedWatch tool to see what's priced in.
3. On FOMC day, do nothing in the first 15 minutes after 2:00pm — let
   liquidity stabilize.
4. If SPY moves >1% in either direction within 30 min and the move appears
   driven by Powell tone (not statement substance), enter a defined-risk
   counter-position (vertical spread).
5. Hard exit by next day's close. Log the trade.

## Further reading
- Federal Reserve FOMC calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Investopedia FOMC: https://www.investopedia.com/terms/f/fomc.asp
- CME FedWatch tool: https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
- FINRA PDT rule: https://www.finra.org/investors/learn-to-invest/advanced-investing/day-trading-margin-requirements-know-rules
