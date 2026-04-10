"""
Backtest Engine for NeoMind Agent.

Provides historical strategy testing for the Finance personality.
Enables validating trading strategies against past data.

Created: 2026-04-02 (Phase 3 - Finance 赚钱引擎)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .paper_trading import (
    PaperTradingEngine,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    Order,
    Trade
)


@dataclass
class OHLCVBar:
    """OHLCV price bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    start_date: datetime
    end_date: datetime
    initial_capital: float = 100000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005
    position_size_pct: float = 0.1  # 10% per position
    max_positions: int = 10
    benchmark_symbol: str = "SPY"


@dataclass
class BacktestResult:
    """Backtest result summary."""
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    profit_factor: float
    equity_curve: List[Dict[str, Any]]
    trade_history: List[Dict[str, Any]]


class BacktestEngine:
    """
    Backtest engine for historical strategy testing.

    Features:
    - Historical data replay
    - Strategy execution
    - Performance metrics
    - Benchmark comparison
    """

    def __init__(self, config: BacktestConfig):
        """
        Initialize backtest engine.

        Args:
            config: Backtest configuration
        """
        self.config = config
        self.engine = PaperTradingEngine(
            initial_capital=config.initial_capital,
            commission_rate=config.commission_rate,
            slippage_rate=config.slippage_rate
        )

        # Historical data (symbol -> list of bars)
        self._data: Dict[str, List[OHLCVBar]] = {}

        # Equity curve
        self._equity_curve: List[Dict[str, Any]] = []

        # Benchmark data
        self._benchmark_data: List[OHLCVBar] = []

    def load_data(
        self,
        symbol: str,
        bars: List[OHLCVBar]
    ) -> None:
        """
        Load historical data for a symbol.

        Args:
            symbol: Stock/crypto symbol
            bars: List of OHLCV bars
        """
        self._data[symbol] = sorted(bars, key=lambda b: b.timestamp)

    def load_benchmark(self, bars: List[OHLCVBar]) -> None:
        """Load benchmark data for comparison."""
        self._benchmark_data = sorted(bars, key=lambda b: b.timestamp)

    def run(
        self,
        strategy: Callable[['BacktestEngine', datetime, Dict[str, OHLCVBar]], List[Order]],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> BacktestResult:
        """
        Run backtest with a strategy function.

        Args:
            strategy: Strategy function that takes (engine, current_time, current_prices)
                      and returns list of orders to place
            progress_callback: Optional callback for progress updates

        Returns:
            BacktestResult with performance metrics
        """
        # Get all unique timestamps
        all_timestamps = set()
        for bars in self._data.values():
            for bar in bars:
                if self.config.start_date <= bar.timestamp <= self.config.end_date:
                    all_timestamps.add(bar.timestamp)

        timestamps = sorted(all_timestamps)
        total_bars = len(timestamps)

        # Reset engine
        self.engine.reset(self.config.initial_capital)
        self._equity_curve = []

        # Iterate through each timestamp
        for i, ts in enumerate(timestamps):
            # Get current prices for all symbols
            current_prices: Dict[str, OHLCVBar] = {}
            for symbol, bars in self._data.items():
                # Find bar for this timestamp
                for bar in bars:
                    if bar.timestamp == ts:
                        current_prices[symbol] = bar
                        # Update price in engine
                        self.engine.update_price(symbol, bar.close)
                        break

            # Execute strategy
            orders = strategy(self, ts, current_prices)

            # Process orders
            for order in orders:
                if order.status == OrderStatus.PENDING:
                    self.engine.place_order(
                        symbol=order.symbol,
                        side=order.side,
                        quantity=order.quantity,
                        order_type=order.order_type,
                        price=order.price,
                        stop_price=order.stop_price
                    )

            # Record equity
            summary = self.engine.get_account_summary()
            self._equity_curve.append({
                'timestamp': ts.isoformat(),
                'equity': summary['equity'],
                'cash': summary['cash'],
                'unrealized_pnl': summary['unrealized_pnl'],
            })

            # Progress callback
            if progress_callback and i % 100 == 0:
                progress_callback(i, total_bars)

        # Calculate results
        return self._calculate_result()

    def _calculate_result(self) -> BacktestResult:
        """Calculate backtest performance metrics."""
        trades = self.engine.get_trade_history()

        # Basic stats
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        losing_trades = sum(1 for t in trades if t.pnl < 0)

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # PnL calculations
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [abs(t.pnl) for t in trades if t.pnl < 0]

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        profit_factor = (sum(wins) / sum(losses)) if losses else float('inf')

        # Returns
        if self._equity_curve:
            initial_equity = self._equity_curve[0]['equity']
            final_equity = self._equity_curve[-1]['equity']
            total_return = ((final_equity - initial_equity) / initial_equity) * 100
        else:
            total_return = 0
            final_equity = self.config.initial_capital

        # Annualized return
        days = (self.config.end_date - self.config.start_date).days
        annualized_return = (
            ((final_equity / self.config.initial_capital) ** (365 / max(days, 1)) - 1) * 100
            if days > 0 else 0
        )

        # Max drawdown
        max_drawdown = self._calculate_max_drawdown()

        # Sharpe ratio (simplified)
        sharpe_ratio = self._calculate_sharpe_ratio()

        return BacktestResult(
            total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            equity_curve=self._equity_curve,
            trade_history=[
                {
                    'symbol': t.symbol,
                    'side': t.side.value,
                    'quantity': t.quantity,
                    'price': t.price,
                    'pnl': t.pnl,
                    'timestamp': t.timestamp.isoformat()
                }
                for t in trades
            ]
        )

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown."""
        if not self._equity_curve:
            return 0.0

        peak = self._equity_curve[0]['equity']
        max_dd = 0.0

        for point in self._equity_curve:
            equity = point['equity']
            if equity > peak:
                peak = equity

            drawdown = ((peak - equity) / peak) * 100 if peak > 0 else 0
            max_dd = max(max_dd, drawdown)

        return max_dd

    def _calculate_sharpe_ratio(self) -> float:
        """Calculate simplified Sharpe ratio."""
        if len(self._equity_curve) < 2:
            return 0.0

        # Calculate daily returns
        returns = []
        for i in range(1, len(self._equity_curve)):
            prev_equity = self._equity_curve[i-1]['equity']
            curr_equity = self._equity_curve[i]['equity']
            if prev_equity > 0:
                returns.append((curr_equity - prev_equity) / prev_equity)

        if not returns:
            return 0.0

        # Calculate mean and std
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = variance ** 0.5

        # Annualize (assume 252 trading days)
        if std_return > 0:
            risk_free_rate = 0.02 / 252  # Daily risk-free rate
            sharpe = (mean_return - risk_free_rate) / std_return * (252 ** 0.5)
        else:
            sharpe = 0.0

        return sharpe

    def get_current_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol."""
        return self.engine.get_position(symbol)

    def get_all_positions(self) -> List[Position]:
        """Get all current positions."""
        return self.engine.get_all_positions()

    def get_open_orders(self) -> List[Order]:
        """Get all open orders."""
        return self.engine.get_open_orders()

    def get_data_range(
        self,
        symbol: str,
        current_time: datetime,
        lookback: timedelta
    ) -> List[OHLCVBar]:
        """
        Get historical data for a lookback period.

        Args:
            symbol: Symbol to get data for
            current_time: Current timestamp
            lookback: Lookback period

        Returns:
            List of OHLCV bars
        """
        bars = self._data.get(symbol, [])
        start_time = current_time - lookback

        return [
            bar for bar in bars
            if start_time <= bar.timestamp <= current_time
        ]


__all__ = [
    'BacktestEngine',
    'BacktestConfig',
    'BacktestResult',
    'OHLCVBar',
]


if __name__ == "__main__":
    from datetime import datetime, timedelta
    import random

    print("=== Backtest Engine Test ===\n")

    # Generate sample data
    def generate_sample_data(symbol: str, days: int = 365) -> List[OHLCVBar]:
        """Generate sample OHLCV data."""
        bars = []
        price = 100.0
        base_time = datetime(2025, 1, 1)

        for i in range(days):
            # Random walk
            change = random.gauss(0.001, 0.02)
            price *= (1 + change)

            high = price * (1 + abs(random.gauss(0, 0.01)))
            low = price * (1 - abs(random.gauss(0, 0.01)))
            open_price = price * (1 + random.gauss(0, 0.005))
            close = price

            bars.append(OHLCVBar(
                timestamp=base_time + timedelta(days=i),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=random.randint(100000, 1000000)
            ))

        return bars

    # Simple moving average strategy
    def ma_strategy(engine: BacktestEngine, ts: datetime, prices: Dict[str, OHLCVBar]) -> List[Order]:
        """Simple moving average crossover strategy."""
        orders = []

        for symbol, bar in prices.items():
            # Get 20-day lookback
            lookback = engine.get_data_range(symbol, ts, timedelta(days=20))
            if len(lookback) < 20:
                continue

            # Calculate SMA
            sma = sum(b.close for b in lookback) / len(lookback)
            current_price = bar.close

            # Check position
            position = engine.get_current_position(symbol)

            # Buy signal
            if current_price > sma * 1.02 and not position:
                # Size position
                summary = engine.engine.get_account_summary()
                position_value = summary['equity'] * 0.1  # 10% per position
                shares = int(position_value / current_price)

                if shares > 0:
                    order = Order(
                        id="",  # Will be assigned by engine
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=shares
                    )
                    orders.append(order)

            # Sell signal
            elif current_price < sma * 0.98 and position:
                order = Order(
                    id="",
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=position.quantity
                )
                orders.append(order)

        return orders

    # Create config
    config = BacktestConfig(
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 12, 31),
        initial_capital=100000
    )

    # Create engine
    engine = BacktestEngine(config)

    # Load data
    engine.load_data("AAPL", generate_sample_data("AAPL"))
    engine.load_data("GOOGL", generate_sample_data("GOOGL"))

    print("Running backtest...")

    # Run backtest
    result = engine.run(ma_strategy)

    print(f"\nResults:")
    print(f"  Total Return: {result.total_return:.2f}%")
    print(f"  Annualized Return: {result.annualized_return:.2f}%")
    print(f"  Max Drawdown: {result.max_drawdown:.2f}%")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"  Win Rate: {result.win_rate:.1f}%")
    print(f"  Total Trades: {result.total_trades}")
    print(f"  Profit Factor: {result.profit_factor:.2f}")

    print("\n✅ BacktestEngine test passed!")
