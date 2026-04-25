# NeoMind Fin — Strategy Catalog Index

This catalog targets a US-based individual investor with ~$10k starting capital.
Every entry is presented neutrally — the platform user picks. Each markdown file
follows the same template (What it is / When it works / When it fails / Tax /
$10k feasibility / Starter checklist / Further reading).

Hard constraints baked into every entry:
- **PDT awareness**: under $25k equity, max 3 day-trade round trips per rolling
  5 business days (FINRA Rule 4210).
- **Defined-risk options only**: no naked calls, no naked puts. The catalog
  includes only covered calls, cash-secured puts, vertical spreads, iron
  condors, collars, calendars, and LEAPS diagonals.
- **Honest failure modes**: every "When it fails" section is concrete.

Total strategies: **35**.

---

## View 1 — By time horizon

### Long-term (held ≥ 1 year, "set and forget" or annual rebalance)
| Strategy | Difficulty | Asset class | Min capital |
|---|---|---|---|
| [Dollar-Cost Averaging into Total Market](./dollar_cost_averaging_index.md) | 1 | ETF | $100 |
| [Dividend-Growth ETF (SCHD/VIG/DGRO)](./dividend_growth_etf.md) | 1 | ETF | $200 |
| [Target-Date Retirement Fund](./target_date_fund.md) | 1 | ETF | $1 |
| [Bogleheads Three-Fund Portfolio](./lazy_portfolio_three_fund.md) | 2 | ETF | $500 |
| [Permanent Portfolio (Harry Browne)](./permanent_portfolio.md) | 2 | Mixed | $1,000 |
| [Treasury Bond Ladder](./bond_ladder_treasury.md) | 2 | Mixed | $1,000 |
| [International Developed Markets ETF](./international_developed_etf.md) | 1 | ETF | $200 |
| [MCHI Buy-and-Hold (Broad China)](./mchi_long_hold.md) | 2 | ETF (China) | $500 |
| [Bitcoin DCA](./btc_dca.md) | 1 | Crypto | $50 |
| [Ethereum DCA](./eth_dca.md) | 1 | Crypto | $50 |

### Mid-term (held weeks to months)
| Strategy | Difficulty | Asset class | Min capital |
|---|---|---|---|
| [Sector Rotation (Business-Cycle)](./sector_rotation.md) | 3 | ETF | $5,000 |
| [Cross-Sectional Momentum](./relative_strength_momentum.md) | 3 | ETF | $3,000 |
| [Value Factor ETF (VTV/VLUE)](./value_factor_etf.md) | 2 | ETF | $500 |
| [Low-Volatility Factor (USMV/SPLV)](./low_volatility_factor.md) | 2 | ETF | $500 |
| [Small-Cap Value (AVUV/IJS)](./small_cap_value.md) | 2 | ETF | $500 |
| [Quality Factor (QUAL/SPHQ)](./quality_factor.md) | 2 | ETF | $500 |
| [52-Week-High Breakout Swing](./swing_breakout_52w_high.md) | 3 | Stock | $3,000 |
| [Post-Earnings Announcement Drift](./post_earnings_drift.md) | 4 | Stock | $3,000 |
| [Merger Arbitrage (Cash Deals)](./merger_arbitrage.md) | 4 | Stock | $5,000 |
| [US/China Sector Rotation (SOXX/KWEB/MCHI)](./sector_etf_rotation_us_china.md) | 4 | ETF (Global) | $5,000 |
| [KWEB Momentum (China Internet)](./kweb_momentum.md) | 4 | ETF (China) | $2,000 |

### Short-term (held days to a few weeks; PDT-relevant)
| Strategy | Difficulty | Asset class | Min capital |
|---|---|---|---|
| [Mean-Reversion Oversold (RSI-2)](./mean_reversion_oversold.md) | 3 | ETF | $3,000 |
| [Earnings-Announcement Volatility Trade](./earnings_announcement_drift.md) | 4 | Stock | $3,000 |
| [Russell Reconstitution Trade](./russell_rebalance.md) | 4 | Stock | $3,000 |
| [FOMC Day Volatility Fade](./fomc_announcement_fade.md) | 4 | ETF | $3,000 |
| [IPO Lockup-Expiration Short Bias](./ipo_lockup_expiry.md) | 5 | Stock | $5,000 |
| [Quad Witching Volatility Setup](./quad_witching_volatility.md) | 5 | Options | $3,000 |

### Defined-risk options (the user's "safety valve" rule)
| Strategy | Difficulty | Defined Risk | Min capital |
|---|---|---|---|
| [ETF Covered Call](./covered_call_etf.md) | 2 | Yes | $5,000 |
| [ETF Cash-Secured Put](./cash_secured_put_etf.md) | 2 | Yes | $3,000 |
| [Bull Put Credit Spread](./vertical_bull_put_spread.md) | 3 | Yes | $1,000 |
| [Bear Call Credit Spread](./vertical_bear_call_spread.md) | 3 | Yes | $1,000 |
| [Iron Condor on Index ETF](./iron_condor_index.md) | 3 | Yes | $2,000 |
| [Collar (Protective Put + Covered Call)](./collar_protective_put.md) | 3 | Yes | $5,000 |
| [Calendar Spread](./calendar_spread.md) | 4 | Yes | $1,000 |
| [Poor Man's Covered Call (LEAPS Diagonal)](./poor_mans_covered_call.md) | 4 | Yes | $2,000 |
| [FXI Defined-Risk Volatility Play](./fxi_volatility_play.md) | 4 | Yes | $1,500 |

---

## View 2 — By difficulty

### Difficulty 1 — Beginner, no decisions required
- [Dollar-Cost Averaging into Total Market](./dollar_cost_averaging_index.md)
- [Dividend-Growth ETF](./dividend_growth_etf.md)
- [Target-Date Retirement Fund](./target_date_fund.md)
- [International Developed Markets ETF](./international_developed_etf.md)
- [Bitcoin DCA](./btc_dca.md)
- [Ethereum DCA](./eth_dca.md)

### Difficulty 2 — Beginner, requires a one-time allocation choice
- [Three-Fund Portfolio](./lazy_portfolio_three_fund.md)
- [Permanent Portfolio](./permanent_portfolio.md)
- [Treasury Bond Ladder](./bond_ladder_treasury.md)
- [Value Factor ETF](./value_factor_etf.md)
- [Low-Volatility Factor](./low_volatility_factor.md)
- [Small-Cap Value](./small_cap_value.md)
- [Quality Factor](./quality_factor.md)
- [MCHI Buy-and-Hold](./mchi_long_hold.md)
- [ETF Covered Call](./covered_call_etf.md)
- [ETF Cash-Secured Put](./cash_secured_put_etf.md)

### Difficulty 3 — Intermediate, requires monitoring
- [Sector Rotation](./sector_rotation.md)
- [Cross-Sectional Momentum](./relative_strength_momentum.md)
- [52-Week-High Breakout Swing](./swing_breakout_52w_high.md)
- [Mean-Reversion Oversold](./mean_reversion_oversold.md)
- [Bull Put Credit Spread](./vertical_bull_put_spread.md)
- [Bear Call Credit Spread](./vertical_bear_call_spread.md)
- [Iron Condor on Index ETF](./iron_condor_index.md)
- [Collar](./collar_protective_put.md)

### Difficulty 4 — Advanced, requires research and active management
- [Post-Earnings Announcement Drift](./post_earnings_drift.md)
- [Earnings-Announcement Volatility Trade](./earnings_announcement_drift.md)
- [Merger Arbitrage](./merger_arbitrage.md)
- [Russell Reconstitution Trade](./russell_rebalance.md)
- [FOMC Day Volatility Fade](./fomc_announcement_fade.md)
- [US/China Sector Rotation](./sector_etf_rotation_us_china.md)
- [KWEB Momentum](./kweb_momentum.md)
- [Calendar Spread](./calendar_spread.md)
- [Poor Man's Covered Call](./poor_mans_covered_call.md)
- [FXI Defined-Risk Volatility Play](./fxi_volatility_play.md)

### Difficulty 5 — Expert, edge is small or specialized
- [IPO Lockup-Expiration](./ipo_lockup_expiry.md)
- [Quad Witching Volatility](./quad_witching_volatility.md)

---

## Cross-reference: PDT-relevant strategies (caution at $10k)

These strategies can produce more than 3 day-trade round trips per 5 business
days if executed actively. Under FINRA Rule 4210, this triggers Pattern Day
Trader status, which requires $25,000 minimum equity. At $10k, run them slow
or accept multi-day holds.

- Sector Rotation, Cross-Sectional Momentum, 52-Week-High Breakout Swing
- Mean-Reversion Oversold (RSI-2), Post-Earnings Drift
- Earnings-Announcement Volatility, Russell Reconstitution
- FOMC Fade, IPO Lockup, Quad Witching
- US/China Sector Rotation, KWEB Momentum

## Cross-reference: §1256 candidates (60/40 tax treatment)

Index options like SPX, NDX, RUT and broad-based futures qualify for §1256
treatment (60% LTCG / 40% STCG regardless of holding period — IRS Pub 550).
The strategies below are typically run on equity-option underlyings (SPY, QQQ)
and DO NOT qualify, but converting to SPX/NDX would. Worth flagging if the
user scales up.

- Iron Condor on Index ETF
- Calendar Spread
- Bull/Bear Vertical Spreads (when run on SPX instead of SPY)
