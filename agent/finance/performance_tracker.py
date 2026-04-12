"""
Performance Tracker for NeoMind Agent Finance.

Tracks and analyzes trading performance with comprehensive metrics.
Supports daily PnL tracking, risk-adjusted returns, and detailed reporting.

Created: 2026-04-02 (Phase 3 - Finance 赚钱引擎)
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional
from dataclasses import dataclass, field


@dataclass
class DailySnapshot:
    """Snapshot of portfolio state at end of day."""
    date: str  # YYYY-MM-DD
    equity: float
    cash: float
    positions_value: float
    daily_pnl: float
    daily_return_pct: float
    cumulative_return_pct: float
    trades_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics."""
    # Return metrics
    total_return_pct: float
    annualized_return_pct: float
    # Risk metrics
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    volatility_pct: float
    # Trade metrics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_holding_period_days: float
    # Summary
    best_day_pct: float
    worst_day_pct: float
    positive_days: int
    negative_days: int


class PerformanceTracker:
    """
    Performance tracking and analytics engine.

    Features:
    - Daily equity snapshots
    - Risk-adjusted return metrics (Sharpe, Sortino)
    - Drawdown analysis
    - Trade-level statistics
    - Formatted reporting
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        risk_free_rate: float = 0.02
    ):
        """
        Initialize performance tracker.

        Args:
            initial_capital: Starting capital
            risk_free_rate: Annual risk-free rate for Sharpe/Sortino
        """
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        self._snapshots: List[DailySnapshot] = []
        self._trades: List[Dict[str, Any]] = []

    def record_snapshot(
        self,
        date: str,
        equity: float,
        cash: float,
        positions_value: float,
        trades_count: int = 0
    ) -> DailySnapshot:
        """
        Record a daily portfolio snapshot.

        Args:
            date: Date string in YYYY-MM-DD format
            equity: Total equity value
            cash: Cash balance
            positions_value: Value of open positions
            trades_count: Number of trades executed today

        Returns:
            Created DailySnapshot
        """
        if self._snapshots:
            prev_equity = self._snapshots[-1].equity
            daily_pnl = equity - prev_equity
            daily_return_pct = (daily_pnl / prev_equity) * 100 if prev_equity > 0 else 0.0
        else:
            daily_pnl = equity - self.initial_capital
            daily_return_pct = (daily_pnl / self.initial_capital) * 100 if self.initial_capital > 0 else 0.0

        cumulative_return_pct = (
            (equity - self.initial_capital) / self.initial_capital
        ) * 100 if self.initial_capital > 0 else 0.0

        snapshot = DailySnapshot(
            date=date,
            equity=equity,
            cash=cash,
            positions_value=positions_value,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return_pct,
            cumulative_return_pct=cumulative_return_pct,
            trades_count=trades_count,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def record_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        pnl: float = 0.0,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Record a completed trade.

        Args:
            symbol: Instrument symbol
            side: Trade side ('buy' or 'sell')
            quantity: Trade quantity
            price: Execution price
            pnl: Realized PnL from this trade
            **kwargs: Additional trade metadata

        Returns:
            Trade record dict
        """
        trade_record: Dict[str, Any] = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': price,
            'pnl': pnl,
            'timestamp': datetime.now().isoformat(),
        }
        trade_record.update(kwargs)
        self._trades.append(trade_record)
        return trade_record

    def calculate_metrics(self) -> PerformanceMetrics:
        """
        Calculate comprehensive performance metrics.

        Returns:
            PerformanceMetrics with all calculated fields
        """
        # Daily returns
        daily_returns = [s.daily_return_pct / 100 for s in self._snapshots]
        equity_curve = [s.equity for s in self._snapshots]

        # Return metrics
        if self._snapshots:
            total_return_pct = self._snapshots[-1].cumulative_return_pct
        else:
            total_return_pct = 0.0

        num_days = len(self._snapshots)
        if num_days > 1:
            years = num_days / 252
            total_return_frac = total_return_pct / 100
            if total_return_frac > -1:
                annualized_return_pct = ((1 + total_return_frac) ** (1 / years) - 1) * 100
            else:
                annualized_return_pct = -100.0
        else:
            annualized_return_pct = 0.0

        # Risk metrics
        sharpe_ratio = self._calculate_sharpe(daily_returns)
        sortino_ratio = self._calculate_sortino(daily_returns)

        if equity_curve:
            max_dd_pct, max_dd_duration = self._calculate_max_drawdown(equity_curve)
        else:
            max_dd_pct, max_dd_duration = 0.0, 0

        volatility_pct = self._std(daily_returns) * math.sqrt(252) * 100 if daily_returns else 0.0

        # Trade metrics
        trade_pnls = [t['pnl'] for t in self._trades]
        winning = [p for p in trade_pnls if p > 0]
        losing = [p for p in trade_pnls if p < 0]

        total_trades = len(self._trades)
        winning_trades = len(winning)
        losing_trades = len(losing)
        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        profit_factor = self._calculate_profit_factor()
        avg_win = sum(winning) / len(winning) if winning else 0.0
        avg_loss = sum(losing) / len(losing) if losing else 0.0
        largest_win = max(winning) if winning else 0.0
        largest_loss = min(losing) if losing else 0.0

        # Average holding period from trade metadata
        holding_periods = [
            t['holding_period_days'] for t in self._trades
            if 'holding_period_days' in t
        ]
        avg_holding_period_days = (
            sum(holding_periods) / len(holding_periods) if holding_periods else 0.0
        )

        # Day-level summary
        if daily_returns:
            best_day_pct = max(daily_returns) * 100
            worst_day_pct = min(daily_returns) * 100
        else:
            best_day_pct = 0.0
            worst_day_pct = 0.0

        positive_days = sum(1 for r in daily_returns if r > 0)
        negative_days = sum(1 for r in daily_returns if r < 0)

        return PerformanceMetrics(
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_duration_days=max_dd_duration,
            volatility_pct=volatility_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            avg_holding_period_days=avg_holding_period_days,
            best_day_pct=best_day_pct,
            worst_day_pct=worst_day_pct,
            positive_days=positive_days,
            negative_days=negative_days,
        )

    # ------------------------------------------------------------------
    # Internal math helpers (stdlib only, no numpy)
    # ------------------------------------------------------------------

    @staticmethod
    def _mean(values: List[float]) -> float:
        """Calculate arithmetic mean."""
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _std(values: List[float]) -> float:
        """Calculate sample standard deviation."""
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        return math.sqrt(variance)

    def _calculate_sharpe(self, returns: List[float], periods: int = 252) -> float:
        """
        Calculate annualized Sharpe ratio.

        Sharpe = mean(excess_returns) / std(returns) * sqrt(periods)

        Args:
            returns: List of periodic returns (as decimals)
            periods: Annualization factor (252 for daily)

        Returns:
            Sharpe ratio
        """
        if len(returns) < 2:
            return 0.0

        daily_rf = self.risk_free_rate / periods
        excess_returns = [r - daily_rf for r in returns]

        mean_excess = self._mean(excess_returns)
        std_returns = self._std(returns)

        if std_returns == 0:
            return 0.0

        return (mean_excess / std_returns) * math.sqrt(periods)

    def _calculate_sortino(self, returns: List[float], periods: int = 252) -> float:
        """
        Calculate annualized Sortino ratio.

        Sortino = mean(excess_returns) / downside_std * sqrt(periods)

        Args:
            returns: List of periodic returns (as decimals)
            periods: Annualization factor (252 for daily)

        Returns:
            Sortino ratio
        """
        if len(returns) < 2:
            return 0.0

        daily_rf = self.risk_free_rate / periods
        excess_returns = [r - daily_rf for r in returns]
        mean_excess = self._mean(excess_returns)

        # Downside deviation: only negative returns
        downside = [r for r in returns if r < 0]
        if not downside:
            # No downside returns means infinite Sortino; cap it
            return 0.0 if mean_excess <= 0 else 99.99

        downside_variance = sum(r ** 2 for r in downside) / len(downside)
        downside_std = math.sqrt(downside_variance)

        if downside_std == 0:
            return 0.0

        return (mean_excess / downside_std) * math.sqrt(periods)

    @staticmethod
    def _calculate_max_drawdown(equity_curve: List[float]) -> Tuple[float, int]:
        """
        Calculate maximum drawdown percentage and duration.

        Args:
            equity_curve: List of equity values

        Returns:
            Tuple of (max_drawdown_pct, max_drawdown_duration_days)
        """
        if len(equity_curve) < 2:
            return 0.0, 0

        peak = equity_curve[0]
        max_dd = 0.0
        max_dd_duration = 0
        current_dd_start: Optional[int] = None

        for i, equity in enumerate(equity_curve):
            if equity >= peak:
                # New peak - reset drawdown tracking
                if current_dd_start is not None:
                    duration = i - current_dd_start
                    max_dd_duration = max(max_dd_duration, duration)
                peak = equity
                current_dd_start = None
            else:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
                if current_dd_start is None:
                    current_dd_start = i

        # Handle ongoing drawdown at end of series
        if current_dd_start is not None:
            duration = len(equity_curve) - current_dd_start
            max_dd_duration = max(max_dd_duration, duration)

        return max_dd, max_dd_duration

    def _calculate_profit_factor(self) -> float:
        """
        Calculate profit factor = gross_profits / gross_losses.

        Returns:
            Profit factor (0.0 if no losses)
        """
        gross_profits = sum(t['pnl'] for t in self._trades if t['pnl'] > 0)
        gross_losses = abs(sum(t['pnl'] for t in self._trades if t['pnl'] < 0))

        if gross_losses == 0:
            return 0.0 if gross_profits == 0 else float('inf')

        return gross_profits / gross_losses

    def generate_report(self) -> str:
        """
        Generate a formatted text performance report.

        Returns:
            Multi-line string with performance summary
        """
        metrics = self.calculate_metrics()

        # Format profit factor display
        if metrics.profit_factor == float('inf'):
            pf_display = "inf"
        else:
            pf_display = f"{metrics.profit_factor:.2f}"

        lines = [
            "=" * 60,
            "  PERFORMANCE REPORT",
            "=" * 60,
            "",
            "--- Return Metrics ---",
            f"  Total Return:        {metrics.total_return_pct:>10.2f}%",
            f"  Annualized Return:   {metrics.annualized_return_pct:>10.2f}%",
            f"  Best Day:            {metrics.best_day_pct:>10.2f}%",
            f"  Worst Day:           {metrics.worst_day_pct:>10.2f}%",
            f"  Positive Days:       {metrics.positive_days:>10d}",
            f"  Negative Days:       {metrics.negative_days:>10d}",
            "",
            "--- Risk Metrics ---",
            f"  Sharpe Ratio:        {metrics.sharpe_ratio:>10.2f}",
            f"  Sortino Ratio:       {metrics.sortino_ratio:>10.2f}",
            f"  Max Drawdown:        {metrics.max_drawdown_pct:>10.2f}%",
            f"  Max DD Duration:     {metrics.max_drawdown_duration_days:>10d} days",
            f"  Volatility (ann.):   {metrics.volatility_pct:>10.2f}%",
            "",
            "--- Trade Metrics ---",
            f"  Total Trades:        {metrics.total_trades:>10d}",
            f"  Winning Trades:      {metrics.winning_trades:>10d}",
            f"  Losing Trades:       {metrics.losing_trades:>10d}",
            f"  Win Rate:            {metrics.win_rate_pct:>10.2f}%",
            f"  Profit Factor:       {pf_display:>10s}",
            f"  Avg Win:             ${metrics.avg_win:>9.2f}",
            f"  Avg Loss:            ${metrics.avg_loss:>9.2f}",
            f"  Largest Win:         ${metrics.largest_win:>9.2f}",
            f"  Largest Loss:        ${metrics.largest_loss:>9.2f}",
            f"  Avg Holding Period:  {metrics.avg_holding_period_days:>10.1f} days",
            "",
            "=" * 60,
        ]

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """
        Export tracker state as a JSON-serializable dict.

        Returns:
            Dict containing snapshots, trades, and calculated metrics
        """
        metrics = self.calculate_metrics()

        return {
            'initial_capital': self.initial_capital,
            'risk_free_rate': self.risk_free_rate,
            'snapshots': [
                {
                    'date': s.date,
                    'equity': s.equity,
                    'cash': s.cash,
                    'positions_value': s.positions_value,
                    'daily_pnl': s.daily_pnl,
                    'daily_return_pct': s.daily_return_pct,
                    'cumulative_return_pct': s.cumulative_return_pct,
                    'trades_count': s.trades_count,
                    'metadata': s.metadata,
                }
                for s in self._snapshots
            ],
            'trades': self._trades,
            'metrics': {
                'total_return_pct': metrics.total_return_pct,
                'annualized_return_pct': metrics.annualized_return_pct,
                'sharpe_ratio': metrics.sharpe_ratio,
                'sortino_ratio': metrics.sortino_ratio,
                'max_drawdown_pct': metrics.max_drawdown_pct,
                'max_drawdown_duration_days': metrics.max_drawdown_duration_days,
                'volatility_pct': metrics.volatility_pct,
                'total_trades': metrics.total_trades,
                'winning_trades': metrics.winning_trades,
                'losing_trades': metrics.losing_trades,
                'win_rate_pct': metrics.win_rate_pct,
                'profit_factor': metrics.profit_factor if metrics.profit_factor != float('inf') else None,
                'avg_win': metrics.avg_win,
                'avg_loss': metrics.avg_loss,
                'largest_win': metrics.largest_win,
                'largest_loss': metrics.largest_loss,
                'avg_holding_period_days': metrics.avg_holding_period_days,
                'best_day_pct': metrics.best_day_pct,
                'worst_day_pct': metrics.worst_day_pct,
                'positive_days': metrics.positive_days,
                'negative_days': metrics.negative_days,
            },
        }


__all__ = [
    'PerformanceTracker',
    'PerformanceMetrics',
    'DailySnapshot',
]


if __name__ == "__main__":
    # Test the performance tracker
    print("=== Performance Tracker Test ===\n")

    tracker = PerformanceTracker(initial_capital=100000.0)

    # Simulate 10 days of trading
    daily_equities = [
        100000, 100500, 101200, 100800, 101500,
        102000, 101000, 101800, 102500, 103000,
    ]

    for i, eq in enumerate(daily_equities):
        date = f"2026-03-{20 + i:02d}"
        cash = eq * 0.3
        positions_value = eq * 0.7
        tracker.record_snapshot(date, eq, cash, positions_value, trades_count=2)

    # Record some trades
    tracker.record_trade("AAPL", "buy", 100, 150.0, pnl=0.0)
    tracker.record_trade("AAPL", "sell", 100, 155.0, pnl=500.0, holding_period_days=3)
    tracker.record_trade("GOOGL", "buy", 10, 2800.0, pnl=0.0)
    tracker.record_trade("GOOGL", "sell", 10, 2750.0, pnl=-500.0, holding_period_days=2)
    tracker.record_trade("MSFT", "buy", 50, 300.0, pnl=0.0)
    tracker.record_trade("MSFT", "sell", 50, 310.0, pnl=500.0, holding_period_days=4)
    tracker.record_trade("TSLA", "buy", 20, 200.0, pnl=0.0)
    tracker.record_trade("TSLA", "sell", 20, 210.0, pnl=200.0, holding_period_days=1)

    # Generate report
    report = tracker.generate_report()
    print(report)

    # Verify dict export
    data = tracker.to_dict()
    print(f"\nSnapshots exported: {len(data['snapshots'])}")
    print(f"Trades exported:   {len(data['trades'])}")

    print("\nPerformance Tracker test passed!")
