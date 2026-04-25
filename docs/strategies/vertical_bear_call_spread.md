# Bear Call Credit Spread

## What it is
The mirror of the bull put spread. Sell an OTM call (closer to the
underlying) and buy a further-OTM call with the same expiration. Collect
a net credit. Maximum profit = net credit, achieved if the underlying
stays BELOW the short strike at expiry. Maximum loss = (width − credit) ×
100, achieved if the underlying rises above the long strike. The bought
call caps the loss — defined-risk per user constraint.

## When it works
- **Range-bound to mildly bearish markets**: short calls expire OTM.
- **At resistance levels**: well-defined technical ceilings make for
  good short-call placement.
- **High IV after rally**: when implied vol spikes, credits are richer.
- **Mechanical management**: close at 50% of max profit.

## When it fails
- **Strong rallies**: 2020 H2, 2023 AI rally, 2024 Q4 — short calls get
  blown through.
- **Earnings gaps**: short call near earnings → IV crush is offset by
  underlying gap.
- **Early assignment around dividends**: ITM short calls on dividend-paying
  underlyings can be exercised the day before ex-div. Roll out or close
  before ex-div.
- **Asymmetric P&L**: small credit, wide max loss.

## Tax & compliance considerations
- Equity options: short-term capital gains/losses (IRS Pub 550).
- §1256 does NOT apply to equity options. SPX index options DO qualify
  for 60/40 treatment — meaningful if scaling.
- Wash-sale rules apply.
- If the short call is assigned, the difference between strike and
  underlying becomes a loss; combined with closing the long call, net out
  to (width − credit) max loss.

## $10k feasibility
Trivial. Buying power per contract ~$400-450 for a $5-wide spread.

## First-week starter checklist
1. Pick a liquid underlying you think is range-bound or weakening at
   resistance (SPY, QQQ, IWM at swing high).
2. Sell 30-45 DTE call at delta ~0.20-0.30; buy 5 strikes higher for
   defined risk.
3. Target net credit ~30% of width.
4. Plan: close at 50% of max profit. Avoid running through ex-dividend
   on stocks that pay material dividends (SPY ex-div risk is mild but
   real).
5. Risk no more than 2-3% of account per spread.

## Further reading
- Investopedia: https://www.investopedia.com/terms/b/bearcallspread.asp
- OIC: https://www.optionseducation.org/strategies/all-strategies/bear-call-spread-credit-call-spread
- TastyLive: https://www.tastylive.com/concepts-strategies/short-call-vertical
- IRS Pub 550 (options, §1256): https://www.irs.gov/pub/irs-pdf/p550.pdf
