# Poor Man's Covered Call (LEAPS Diagonal)

## What it is
The "Poor Man's Covered Call" (PMCC) approximates a covered call without
the capital outlay of buying 100 shares. Instead, buy a deep-in-the-money,
long-dated call (LEAPS — Long-term Equity AnticiPation Securities, typically
12-24 months to expiry, 75-80 delta). The LEAPS acts as a stock substitute.
Then sell a 30-DTE OTM call against it monthly. Mathematically a long
diagonal call spread; defined-risk (max loss = LEAPS debit minus collected
short-call premiums).

## When it works
- **Capital efficiency**: 75-delta LEAPS on QQQ might cost $5,000 vs $50,000
  for 100 shares.
- **Sideways-to-mildly-bullish underlyings**: same regime as covered call.
- **Liquid options markets**: SPY, QQQ, AAPL, MSFT, NVDA all have deep
  LEAPS chains.

## When it fails
- **Sharp declines**: LEAPS can lose 50%+ when underlying drops materially.
  Unlike 100 shares (which only loses real-time delta), LEAPS has gamma
  acceleration in declines.
- **Early assignment around dividends**: short calls ITM the day before
  ex-div can be exercised; you'd need to exercise the LEAPS or be left
  short the underlying.
- **Less forgiving than covered call**: with shares, you can hold through
  drawdowns. LEAPS expire.
- **IV crush** when entering at high IV hurts the LEAPS first.

## Tax & compliance considerations
- LEAPS held >12 months → potentially LTCG (IRS Pub 550).
- Short calls against LEAPS: similar to covered-call rules. **A "qualified
  covered call" against the LEAPS does NOT suspend the LEAPS's long-term
  holding period**; an UNQUALIFIED (deep-ITM) short call DOES suspend it.
- Wash-sale: closing the short call at a loss and opening another within
  30 days on the same underlying triggers wash-sale.
- This is **complex** for tax — recommend professional consultation,
  especially for the LEAPS holding-period interaction.

## $10k feasibility
Feasible. A 75-delta 12-month LEAPS on QQQ might cost $5,000-7,000. Reserve
$2,000-3,000 for monthly short calls and to weather adverse moves. Suitable
to deploy ~50-70% of $10k.

## First-week starter checklist
1. Pick a liquid underlying you're bullish on long-term (QQQ, SPY).
2. Buy a 12-month 75-80 delta call (deep ITM). Cost ~$5,000 for QQQ.
3. Sell a 30 DTE 25-30 delta call against it. Collect ~$200-400 premium.
4. Roll the short call monthly. Adjust strike based on underlying drift.
5. Plan an exit: close LEAPS 60-90 days before expiration (avoid theta
   acceleration), or roll to a new LEAPS.

## Further reading
- Investopedia: https://www.investopedia.com/terms/p/poor-mans-covered-call.asp
- TastyLive PMCC: https://www.tastylive.com/concepts-strategies/poor-mans-covered-call
- OIC long calls: https://www.optionseducation.org/strategies/all-strategies/long-call
- IRS Pub 550 (QCC, holding period): https://www.irs.gov/pub/irs-pdf/p550.pdf
