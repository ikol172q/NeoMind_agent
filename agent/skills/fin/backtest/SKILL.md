---
name: backtest
description: Backtesting engine — define strategy, pull historical data, simulate trades, calculate Sharpe/drawdown/win-rate
modes: [fin]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 1.0.0
---

# Backtest — Investment Strategy Validation

You are the quant engineer. Mission: validate trading strategies against historical data before risking real capital.

## Workflow

### 1. Define Strategy Parameters

Clearly specify the trading strategy:

**Entry Signals:**
- What triggers a buy? (e.g., price crosses moving average, RSI < 30, earnings beat)
- Time frame for entry (e.g., daily, weekly, on signal)
- Position size per trade (e.g., fixed $10K or % of portfolio)

**Exit Signals:**
- What triggers a sell? (e.g., stop-loss at -5%, take-profit at +15%, time-based exit)
- Duration: how long do we hold? (e.g., until signal, 30 days, max)

**Risk Parameters:**
- Max position size: % of portfolio per trade
- Max drawdown allowed: when do we stop trading?
- Rebalance frequency: daily, weekly, monthly?

**Example:**
```
Strategy: Moving Average Crossover
─────────────────────────────────
Symbol: AAPL
Entry: Close > 50-day MA (on daily candle close)
Exit: Stop-loss at -5%, or take-profit at +15%
Position Size: 2% of portfolio per trade
Max Positions: 3 simultaneous
Backtest Period: 2018-01-01 to 2024-01-01
```

### 2. Pull Historical Data

```bash
# Python example using yfinance
import yfinance as yf
data = yf.download("AAPL", start="2018-01-01", end="2024-01-01")
# columns: Open, High, Low, Close, Volume, Adj Close
```

Or use financial data API:
- yfinance (free, Yahoo Finance)
- Alpha Vantage
- IEX Cloud
- Quandl

Verify data:
- No missing dates (weekends/holidays should be absent)
- Price data reasonable (no extreme outliers)
- Volume data available
- Date range matches strategy period

### 3. Simulate Trades with Paper Execution

Implement backtest logic:
```
For each day in historical period:
  1. Calculate signals (MA crossover, RSI, etc.)
  2. If buy signal + position limit not reached:
     - Open position at day's close price
     - Record entry date, entry price, position size
  3. For each open position:
     - Check exit conditions (stop-loss, take-profit, time-based)
     - If exit signal:
       - Close position at exit price
       - Record exit date, exit price, P&L
  4. Update portfolio value

Do NOT execute real trades. This is paper trading only.
```

Output trade log:
```
Date_Entry  Symbol  Entry_Price  Shares  Exit_Date   Exit_Price  P&L      Return%
──────────────────────────────────────────────────────────────────────────────────
2018-02-15  AAPL    150.00       66      2018-03-22  157.50      495.00   5.0%
2018-04-10  AAPL    149.50       67      2018-06-05  144.75      -317.75  -3.2%
```

### 4. Calculate Metrics

**Performance Metrics:**
```
Total Return:           ([Final Value - Initial Value] / Initial Value) × 100%
Annual Return:          Total Return / Years
Sharpe Ratio:           (Annual Return - Risk-Free Rate) / Annual Volatility
Sortino Ratio:          (Annual Return - Risk-Free Rate) / Downside Volatility
Max Drawdown:           Largest peak-to-trough decline during period
Win Rate:               % of trades that were profitable
Profit Factor:          Sum of gains / Sum of losses
Number of Trades:       Total trades executed

# Example calculation
Initial Portfolio:      $100,000
Final Portfolio:        $145,230
Total Return:           45.23%
Annual Return:          6.46% (over 7 years)
Sharpe Ratio:           1.28
Max Drawdown:           -18.5% (occurred 2020-03-15)
Win Rate:               62% (31 wins / 50 trades)
Avg Win:                $2,840
Avg Loss:               -$1,210
Profit Factor:          2.34
```

### 5. Compare with Benchmark (S&P 500)

```bash
# Download SPY (S&P 500) for same period
benchmark = yf.download("SPY", start="2018-01-01", end="2024-01-01")
benchmark_return = (benchmark['Adj Close'][-1] / benchmark['Adj Close'][0]) - 1
```

Compare:
```
Metric              Strategy    Benchmark   Outperformance
────────────────────────────────────────────────────────────
Total Return        45.23%      98.50%      -53.27%
Annual Return       6.46%       11.29%      -4.83%
Sharpe Ratio        1.28        1.15        +0.13
Max Drawdown        -18.5%      -33.8%      Better (lower)
Win Rate            62%         N/A         (Buy-hold doesn't have trades)
```

### 6. Report with Charts

**Backtest Report Format:**
```
BACKTEST REPORT
───────────────
Strategy: Moving Average Crossover (AAPL)
Period: 2018-01-01 to 2024-01-01 (7 years)
Initial Capital: $100,000

PERFORMANCE SUMMARY
───────────────────
Total Return:       45.23%
Annual Return:      6.46%
Sharpe Ratio:       1.28
Max Drawdown:       -18.5%
Win Rate:           62% (31/50 trades)
Profit Factor:      2.34

vs BENCHMARK (S&P 500)
──────────────────────
Strategy Return:    45.23%
Benchmark Return:   98.50%
Outperformance:     -53.27%
Alpha:              -7.41% annually

TRADE STATISTICS
────────────────
Total Trades:       50
Avg Win:            $2,840
Avg Loss:           -$1,210
Largest Win:        $8,500 (17-May-2020)
Largest Loss:       -$3,200 (18-Mar-2020)

EQUITY CURVE
──────────────────────────────────────────
[Chart showing portfolio value over time]

DRAWDOWN HISTORY
──────────────────────────────────────────
[Chart showing peak-to-trough declines]

CONCLUSION
───────────
The strategy outperformed SPY on risk-adjusted basis (Sharpe 1.28 vs 1.15),
but underperformed on absolute returns (-53pp). Consider:
- Entry signal timing (currently lagging market)
- Exit strategy (taking profits too early?)
- Risk management rules

Next Steps:
  1. Optimize MA periods (test 20/60, 30/90)
  2. Test on other symbols
  3. Compare with alternative exit strategies
```

## Rules

- **Use actual historical data**: Don't make assumptions about past prices
- **Realistic execution**: Account for slippage, commissions, taxes
- **Consistent entry/exit**: Same rules for all trades (no curve-fitting to past)
- **Out-of-sample validation**: Test on data not used to develop the strategy
- **Avoid overfitting**: Strategy that works on 2018-2020 may fail in 2024
- **Document assumptions**: Commission cost, slippage, minimum order size, etc.

## Tools

- Python: backtrader, zipline, backtesting.py
- Excel: manual calculation or Python export to Excel
- Online: TradingView Pine Script, QuantConnect, Backtrader Cloud
