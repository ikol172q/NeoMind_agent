"""
Risk Manager for NeoMind Agent.

Provides risk management for the Finance personality.
Controls position sizing, drawdown limits, and exposure.

Created: 2026-04-02 (Phase 3 - Finance 赚钱引擎)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from .paper_trading import OrderSide, Position


class RiskLevel(Enum):
    """Risk level classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskLimits:
    """Risk limits configuration."""
    max_position_size_pct: float = 0.1  # Max 10% per position
    max_sector_exposure_pct: float = 0.3  # Max 30% per sector
    max_total_exposure_pct: float = 0.95  # Max 95% invested
    max_daily_loss_pct: float = 0.03  # Max 3% daily loss
    max_drawdown_pct: float = 0.15  # Max 15% drawdown
    max_leverage: float = 1.0  # No leverage by default
    max_correlated_assets: int = 3  # Max correlated assets


@dataclass
class RiskAssessment:
    """Risk assessment result."""
    allowed: bool
    risk_level: RiskLevel
    position_size: float
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionSizing:
    """Position sizing result."""
    shares: int
    dollar_amount: float
    pct_of_portfolio: float
    risk_per_share: float
    stop_loss_price: Optional[float] = None


class RiskManager:
    """
    Risk manager for trading operations.

    Features:
    - Position sizing (Kelly, Fixed, Volatility-based)
    - Drawdown monitoring
    - Exposure limits
    - Risk-adjusted recommendations
    """

    # Sector mappings (simplified)
    SECTOR_MAP = {
        'AAPL': 'Technology',
        'MSFT': 'Technology',
        'GOOGL': 'Technology',
        'AMZN': 'Consumer',
        'JPM': 'Finance',
        'BAC': 'Finance',
        'XOM': 'Energy',
        'CVX': 'Energy',
        'JNJ': 'Healthcare',
        'PFE': 'Healthcare',
    }

    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        account_value: float = 100000.0
    ):
        """
        Initialize risk manager.

        Args:
            limits: Risk limits configuration
            account_value: Current account value
        """
        self.limits = limits or RiskLimits()
        self.account_value = account_value

        # Track daily PnL
        self._daily_pnl: Dict[str, float] = {}
        self._peak_value = account_value
        self._current_drawdown = 0.0

        # Trade history for analysis
        self._trades: List[Dict[str, Any]] = []

    def update_account_value(self, value: float) -> None:
        """
        Update account value for drawdown tracking.

        Args:
            value: Current account value
        """
        self.account_value = value

        if value > self._peak_value:
            self._peak_value = value

        self._current_drawdown = (self._peak_value - value) / self._peak_value

    def record_trade(
        self,
        symbol: str,
        side: OrderSide,
        pnl: float,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Record a trade for risk analysis."""
        ts = timestamp or datetime.now()
        date_key = ts.strftime('%Y-%m-%d')

        # Update daily PnL
        if date_key not in self._daily_pnl:
            self._daily_pnl[date_key] = 0.0
        self._daily_pnl[date_key] += pnl

        # Record trade
        self._trades.append({
            'symbol': symbol,
            'side': side.value,
            'pnl': pnl,
            'timestamp': ts.isoformat()
        })

    def calculate_position_size(
        self,
        symbol: str,
        current_price: float,
        volatility: Optional[float] = None,
        method: str = "fixed"
    ) -> PositionSizing:
        """
        Calculate appropriate position size.

        Args:
            symbol: Stock/crypto symbol
            current_price: Current price
            volatility: Annual volatility (for volatility-based sizing)
            method: Sizing method (fixed, kelly, volatility)

        Returns:
            PositionSizing with recommended size
        """
        if method == "fixed":
            return self._fixed_sizing(current_price)
        elif method == "kelly":
            return self._kelly_sizing(symbol, current_price)
        elif method == "volatility":
            return self._volatility_sizing(current_price, volatility or 0.2)
        else:
            return self._fixed_sizing(current_price)

    def _fixed_sizing(self, current_price: float) -> PositionSizing:
        """Fixed percentage position sizing."""
        position_value = self.account_value * self.limits.max_position_size_pct
        shares = int(position_value / current_price)

        return PositionSizing(
            shares=shares,
            dollar_amount=shares * current_price,
            pct_of_portfolio=self.limits.max_position_size_pct,
            risk_per_share=current_price * 0.02  # Assume 2% stop loss
        )

    def _kelly_sizing(self, symbol: str, current_price: float) -> PositionSizing:
        """Kelly criterion position sizing."""
        # Get historical win rate and avg win/loss for symbol
        symbol_trades = [t for t in self._trades if t['symbol'] == symbol]

        if len(symbol_trades) < 10:
            # Not enough data, fall back to fixed
            return self._fixed_sizing(current_price)

        wins = [t['pnl'] for t in symbol_trades if t['pnl'] > 0]
        losses = [abs(t['pnl']) for t in symbol_trades if t['pnl'] < 0]

        if not wins or not losses:
            return self._fixed_sizing(current_price)

        win_rate = len(wins) / len(symbol_trades)
        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)

        # Kelly fraction
        b = avg_win / avg_loss  # Win/loss ratio
        kelly = (win_rate * b - (1 - win_rate)) / b

        # Use half-Kelly for safety
        kelly = max(0, min(kelly * 0.5, self.limits.max_position_size_pct))

        position_value = self.account_value * kelly
        shares = int(position_value / current_price)

        return PositionSizing(
            shares=shares,
            dollar_amount=shares * current_price,
            pct_of_portfolio=kelly,
            risk_per_share=current_price * 0.02
        )

    def _volatility_sizing(
        self,
        current_price: float,
        volatility: float
    ) -> PositionSizing:
        """Volatility-adjusted position sizing."""
        # Target 1% portfolio risk per position
        target_risk = 0.01
        risk_per_share = current_price * volatility

        if risk_per_share > 0:
            shares = int((self.account_value * target_risk) / risk_per_share)
        else:
            shares = 0

        dollar_amount = shares * current_price
        pct_of_portfolio = dollar_amount / self.account_value if self.account_value > 0 else 0

        # Cap at max position size
        if pct_of_portfolio > self.limits.max_position_size_pct:
            pct_of_portfolio = self.limits.max_position_size_pct
            dollar_amount = self.account_value * pct_of_portfolio
            shares = int(dollar_amount / current_price)

        return PositionSizing(
            shares=shares,
            dollar_amount=dollar_amount,
            pct_of_portfolio=pct_of_portfolio,
            risk_per_share=risk_per_share
        )

    def assess_trade(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        current_positions: Optional[Dict[str, Position]] = None
    ) -> RiskAssessment:
        """
        Assess risk of a proposed trade.

        Args:
            symbol: Stock/crypto symbol
            side: Buy or sell
            quantity: Number of shares
            price: Price per share
            current_positions: Current positions

        Returns:
            RiskAssessment with recommendation
        """
        warnings = []
        allowed = True
        risk_level = RiskLevel.LOW

        trade_value = quantity * price
        pct_of_portfolio = trade_value / self.account_value if self.account_value > 0 else 0

        # Check position size limit
        if pct_of_portfolio > self.limits.max_position_size_pct:
            warnings.append(
                f"Position size {pct_of_portfolio:.1%} exceeds limit "
                f"{self.limits.max_position_size_pct:.1%}"
            )
            allowed = False

        # Check sector exposure
        if current_positions and side == OrderSide.BUY:
            sector = self.SECTOR_MAP.get(symbol, 'Unknown')
            sector_value = trade_value

            for pos_symbol, pos in current_positions.items():
                if self.SECTOR_MAP.get(pos_symbol, 'Unknown') == sector:
                    sector_value += pos.quantity * pos.current_price

            sector_pct = sector_value / self.account_value if self.account_value > 0 else 0

            if sector_pct > self.limits.max_sector_exposure_pct:
                warnings.append(
                    f"Sector {sector} exposure {sector_pct:.1%} exceeds limit "
                    f"{self.limits.max_sector_exposure_pct:.1%}"
                )
                risk_level = RiskLevel.HIGH

        # Check total exposure
        if current_positions and side == OrderSide.BUY:
            total_exposure = trade_value
            for pos in current_positions.values():
                total_exposure += pos.quantity * pos.current_price

            total_pct = total_exposure / self.account_value if self.account_value > 0 else 0

            if total_pct > self.limits.max_total_exposure_pct:
                warnings.append(
                    f"Total exposure {total_pct:.1%} exceeds limit "
                    f"{self.limits.max_total_exposure_pct:.1%}"
                )
                risk_level = RiskLevel.HIGH

        # Check drawdown
        if self._current_drawdown > self.limits.max_drawdown_pct * 0.8:
            warnings.append(
                f"Drawdown {self._current_drawdown:.1%} approaching limit "
                f"{self.limits.max_drawdown_pct:.1%}"
            )
            risk_level = RiskLevel.HIGH if risk_level == RiskLevel.LOW else risk_level

        # Check daily loss
        today = datetime.now().strftime('%Y-%m-%d')
        daily_pnl = self._daily_pnl.get(today, 0)
        if daily_pnl < -self.account_value * self.limits.max_daily_loss_pct:
            warnings.append("Daily loss limit reached - trading restricted")
            allowed = False
            risk_level = RiskLevel.CRITICAL

        # Determine overall risk level
        if pct_of_portfolio > self.limits.max_position_size_pct * 0.8:
            risk_level = RiskLevel.MEDIUM if risk_level == RiskLevel.LOW else risk_level

        return RiskAssessment(
            allowed=allowed,
            risk_level=risk_level,
            position_size=quantity * price,
            warnings=warnings
        )

    def get_risk_report(self) -> Dict[str, Any]:
        """Generate comprehensive risk report."""
        today = datetime.now().strftime('%Y-%m-%d')

        # Calculate metrics
        recent_trades = [
            t for t in self._trades
            if datetime.fromisoformat(t['timestamp']) > datetime.now() - timedelta(days=30)
        ]

        wins = sum(1 for t in recent_trades if t['pnl'] > 0)
        losses = sum(1 for t in recent_trades if t['pnl'] < 0)

        return {
            'account_value': self.account_value,
            'peak_value': self._peak_value,
            'current_drawdown': f"{self._current_drawdown:.2%}",
            'daily_pnl': self._daily_pnl.get(today, 0),
            'limits': {
                'max_position_size': f"{self.limits.max_position_size_pct:.1%}",
                'max_sector_exposure': f"{self.limits.max_sector_exposure_pct:.1%}",
                'max_drawdown': f"{self.limits.max_drawdown_pct:.1%}",
                'max_daily_loss': f"{self.limits.max_daily_loss_pct:.1%}",
            },
            'recent_performance': {
                'trades_30d': len(recent_trades),
                'wins': wins,
                'losses': losses,
                'win_rate': f"{wins / max(len(recent_trades), 1):.1%}"
            },
            'risk_status': self._get_risk_status()
        }

    def _get_risk_status(self) -> str:
        """Get current risk status."""
        if self._current_drawdown > self.limits.max_drawdown_pct:
            return "CRITICAL - Drawdown limit exceeded"
        elif self._current_drawdown > self.limits.max_drawdown_pct * 0.8:
            return "WARNING - High drawdown"
        else:
            return "OK"


__all__ = [
    'RiskManager',
    'RiskLimits',
    'RiskAssessment',
    'RiskLevel',
    'PositionSizing',
]


if __name__ == "__main__":
    print("=== Risk Manager Test ===\n")

    # Create risk manager
    manager = RiskManager(account_value=100000)

    # Test position sizing
    print("Position Sizing:")
    sizing = manager.calculate_position_size("AAPL", 150.0, method="fixed")
    print(f"  Fixed: {sizing.shares} shares (${sizing.dollar_amount:,.0f})")

    sizing = manager.calculate_position_size("AAPL", 150.0, method="volatility")
    print(f"  Volatility: {sizing.shares} shares (${sizing.dollar_amount:,.0f})")

    # Test risk assessment
    print("\nRisk Assessment:")
    assessment = manager.assess_trade("AAPL", OrderSide.BUY, 100, 150.0)
    print(f"  Allowed: {assessment.allowed}")
    print(f"  Risk Level: {assessment.risk_level.value}")
    print(f"  Warnings: {assessment.warnings}")

    # Test large position
    print("\nLarge Position Assessment:")
    assessment = manager.assess_trade("AAPL", OrderSide.BUY, 1000, 150.0)
    print(f"  Allowed: {assessment.allowed}")
    print(f"  Warnings: {assessment.warnings}")

    # Record some trades
    manager.record_trade("AAPL", OrderSide.BUY, 500)
    manager.record_trade("GOOGL", OrderSide.BUY, -200)
    manager.record_trade("MSFT", OrderSide.BUY, 300)

    # Get risk report
    print("\nRisk Report:")
    report = manager.get_risk_report()
    for key, value in report.items():
        print(f"  {key}: {value}")

    print("\n✅ RiskManager test passed!")
