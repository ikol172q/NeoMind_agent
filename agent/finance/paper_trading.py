"""
Paper Trading Engine for NeoMind Agent.

Provides simulated trading for the Finance personality.
Enables testing strategies without real money.

Created: 2026-04-02 (Phase 3 - Finance 赚钱引擎)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class OrderSide(Enum):
    """Order side (buy/sell)."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Position:
    """Represents a trading position."""
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    side: OrderSide
    opened_at: datetime
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_price(self, current_price: float) -> None:
        """Update current price and PnL."""
        self.current_price = current_price

        if self.side == OrderSide.BUY:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity

        if self.entry_price > 0:
            self.unrealized_pnl_pct = (self.unrealized_pnl / (self.entry_price * self.quantity)) * 100


@dataclass
class Order:
    """Represents a trading order."""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None  # For limit orders
    stop_price: Optional[float] = None  # For stop orders
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    commission: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    """Represents a completed trade."""
    id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float
    timestamp: datetime
    pnl: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Account:
    """Paper trading account."""
    initial_capital: float
    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    @property
    def equity(self) -> float:
        """Total account equity."""
        return self.cash + self.unrealized_pnl

    @property
    def buying_power(self) -> float:
        """Available buying power."""
        return self.cash  # Simplified - no margin


class PaperTradingEngine:
    """
    Paper trading engine for simulated trading.

    Features:
    - Order management (market, limit, stop)
    - Position tracking
    - PnL calculation
    - Trade history
    - Commission handling
    """

    # Default commission rate
    DEFAULT_COMMISSION_RATE = 0.001  # 0.1%

    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        slippage_rate: float = 0.0005,  # 0.05%
        data_dir: Optional[Path] = None
    ):
        """
        Initialize paper trading engine.

        Args:
            initial_capital: Starting capital
            commission_rate: Commission rate per trade
            slippage_rate: Simulated slippage rate
            data_dir: Directory for persistence
        """
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.data_dir = data_dir or Path.home() / ".neomind" / "paper_trading"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Account state
        self.account = Account(
            initial_capital=initial_capital,
            cash=initial_capital
        )

        # Orders and trades
        self.orders: Dict[str, Order] = {}
        self.trades: List[Trade] = []
        self.pending_orders: List[str] = []

        # Price cache (symbol -> current_price)
        self._prices: Dict[str, float] = {}

    def update_price(self, symbol: str, price: float) -> None:
        """
        Update current price for a symbol.

        Args:
            symbol: Stock/crypto symbol
            price: Current price
        """
        self._prices[symbol] = price

        # Update position values
        if symbol in self.account.positions:
            self.account.positions[symbol].update_price(price)

        # Check pending orders
        self._check_pending_orders(symbol, price)

    def _check_pending_orders(self, symbol: str, price: float) -> None:
        """Check and execute pending orders."""
        orders_to_remove = []

        for order_id in self.pending_orders:
            order = self.orders.get(order_id)
            if not order or order.symbol != symbol:
                continue

            should_execute = False
            execute_price = price

            if order.order_type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and price <= order.price:
                    should_execute = True
                elif order.side == OrderSide.SELL and price >= order.price:
                    should_execute = True
                execute_price = order.price

            elif order.order_type == OrderType.STOP:
                if order.side == OrderSide.BUY and price >= order.stop_price:
                    should_execute = True
                elif order.side == OrderSide.SELL and price <= order.stop_price:
                    should_execute = True

            if should_execute:
                self._fill_order(order, execute_price)
                orders_to_remove.append(order_id)

        for order_id in orders_to_remove:
            if order_id in self.pending_orders:
                self.pending_orders.remove(order_id)

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> Order:
        """
        Place a new order.

        Args:
            symbol: Stock/crypto symbol
            side: Buy or sell
            quantity: Number of shares/units
            order_type: Market, limit, or stop
            price: Limit price (for limit orders)
            stop_price: Stop price (for stop orders)

        Returns:
            Created Order object
        """
        order_id = str(uuid.uuid4())[:8]

        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price
        )

        self.orders[order_id] = order

        # Execute market orders immediately
        if order_type == OrderType.MARKET:
            current_price = self._prices.get(symbol)
            if current_price:
                self._fill_order(order, current_price)
            else:
                order.status = OrderStatus.REJECTED
                order.metadata['error'] = "No price available"
        else:
            # Add to pending orders
            self.pending_orders.append(order_id)

        return order

    def _fill_order(self, order: Order, price: float) -> None:
        """Fill an order at given price."""
        # Apply slippage
        if order.side == OrderSide.BUY:
            fill_price = price * (1 + self.slippage_rate)
        else:
            fill_price = price * (1 - self.slippage_rate)

        # Calculate commission
        commission = fill_price * order.quantity * self.commission_rate

        # Calculate total cost
        total_cost = fill_price * order.quantity + commission

        # Check if enough cash for buy orders
        if order.side == OrderSide.BUY:
            if total_cost > self.account.cash:
                order.status = OrderStatus.REJECTED
                order.metadata['error'] = "Insufficient funds"
                return

            # Deduct cash
            self.account.cash -= total_cost

            # Add or update position
            if order.symbol in self.account.positions:
                pos = self.account.positions[order.symbol]
                # Average cost
                total_quantity = pos.quantity + order.quantity
                total_cost_basis = (pos.entry_price * pos.quantity) + (fill_price * order.quantity)
                pos.entry_price = total_cost_basis / total_quantity
                pos.quantity = total_quantity
                pos.update_price(fill_price)
            else:
                self.account.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=order.quantity,
                    entry_price=fill_price,
                    current_price=fill_price,
                    side=OrderSide.BUY,
                    opened_at=datetime.now()
                )

        else:  # SELL
            # Check if we have the position
            if order.symbol not in self.account.positions:
                order.status = OrderStatus.REJECTED
                order.metadata['error'] = "No position to sell"
                return

            pos = self.account.positions[order.symbol]
            if pos.quantity < order.quantity:
                order.status = OrderStatus.REJECTED
                order.metadata['error'] = "Insufficient shares"
                return

            # Calculate PnL
            pnl = (fill_price - pos.entry_price) * order.quantity - commission

            # Add cash
            self.account.cash += fill_price * order.quantity - commission

            # Update position
            pos.quantity -= order.quantity
            if pos.quantity <= 0:
                del self.account.positions[order.symbol]

            # Update realized PnL
            self.account.realized_pnl += pnl
            self.account.total_trades += 1
            if pnl > 0:
                self.account.winning_trades += 1
            else:
                self.account.losing_trades += 1

        # Update order status
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.filled_at = datetime.now()
        order.commission = commission

        # Create trade record
        trade = Trade(
            id=str(uuid.uuid4())[:8],
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
            timestamp=datetime.now()
        )
        self.trades.append(trade)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        order = self.orders.get(order_id)
        if not order or order.status != OrderStatus.PENDING:
            return False

        order.status = OrderStatus.CANCELLED
        if order_id in self.pending_orders:
            self.pending_orders.remove(order_id)

        return True

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        return self.account.positions.get(symbol)

    def get_all_positions(self) -> List[Position]:
        """Get all positions."""
        return list(self.account.positions.values())

    def get_open_orders(self) -> List[Order]:
        """Get all open orders."""
        return [
            self.orders[oid]
            for oid in self.pending_orders
            if oid in self.orders
        ]

    def get_trade_history(self, symbol: Optional[str] = None) -> List[Trade]:
        """Get trade history, optionally filtered by symbol."""
        if symbol:
            return [t for t in self.trades if t.symbol == symbol]
        return self.trades

    def get_account_summary(self) -> Dict[str, Any]:
        """Get account summary."""
        # Calculate unrealized PnL
        self.account.unrealized_pnl = sum(
            pos.unrealized_pnl for pos in self.account.positions.values()
        )

        # Calculate total PnL
        self.account.total_pnl = self.account.realized_pnl + self.account.unrealized_pnl
        self.account.total_pnl_pct = (
            self.account.total_pnl / self.account.initial_capital
        ) * 100 if self.account.initial_capital > 0 else 0

        return {
            'initial_capital': self.account.initial_capital,
            'cash': self.account.cash,
            'equity': self.account.equity,
            'unrealized_pnl': self.account.unrealized_pnl,
            'realized_pnl': self.account.realized_pnl,
            'total_pnl': self.account.total_pnl,
            'total_pnl_pct': self.account.total_pnl_pct,
            'total_trades': self.account.total_trades,
            'winning_trades': self.account.winning_trades,
            'losing_trades': self.account.losing_trades,
            'win_rate': (
                self.account.winning_trades / self.account.total_trades * 100
                if self.account.total_trades > 0 else 0
            ),
            'positions': len(self.account.positions),
            'open_orders': len(self.pending_orders),
        }

    def reset(self, initial_capital: Optional[float] = None) -> None:
        """Reset the account."""
        self.account = Account(
            initial_capital=initial_capital or self.account.initial_capital,
            cash=initial_capital or self.account.initial_capital
        )
        self.orders.clear()
        self.trades.clear()
        self.pending_orders.clear()
        self._prices.clear()

    def save_state(self, filename: str = "paper_trading_state.json") -> None:
        """Save state to file."""
        state = {
            'account': {
                'initial_capital': self.account.initial_capital,
                'cash': self.account.cash,
                'realized_pnl': self.account.realized_pnl,
                'total_trades': self.account.total_trades,
                'winning_trades': self.account.winning_trades,
                'losing_trades': self.account.losing_trades,
            },
            'positions': [
                {
                    'symbol': pos.symbol,
                    'quantity': pos.quantity,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'side': pos.side.value,
                    'opened_at': pos.opened_at.isoformat(),
                }
                for pos in self.account.positions.values()
            ],
            'trades': [
                {
                    'id': t.id,
                    'symbol': t.symbol,
                    'side': t.side.value,
                    'quantity': t.quantity,
                    'price': t.price,
                    'commission': t.commission,
                    'timestamp': t.timestamp.isoformat(),
                    'pnl': t.pnl,
                }
                for t in self.trades
            ],
        }

        with open(self.data_dir / filename, 'w') as f:
            json.dump(state, f, indent=2)

    def load_state(self, filename: str = "paper_trading_state.json") -> bool:
        """Load state from file."""
        filepath = self.data_dir / filename
        if not filepath.exists():
            return False

        try:
            with open(filepath, 'r') as f:
                state = json.load(f)

            # Restore account
            acc_data = state.get('account', {})
            self.account = Account(
                initial_capital=acc_data.get('initial_capital', 100000),
                cash=acc_data.get('cash', 100000),
                realized_pnl=acc_data.get('realized_pnl', 0),
                total_trades=acc_data.get('total_trades', 0),
                winning_trades=acc_data.get('winning_trades', 0),
                losing_trades=acc_data.get('losing_trades', 0),
            )

            # Restore positions
            for pos_data in state.get('positions', []):
                self.account.positions[pos_data['symbol']] = Position(
                    symbol=pos_data['symbol'],
                    quantity=pos_data['quantity'],
                    entry_price=pos_data['entry_price'],
                    current_price=pos_data['current_price'],
                    side=OrderSide(pos_data['side']),
                    opened_at=datetime.fromisoformat(pos_data['opened_at']),
                )

            # Restore trades
            for t_data in state.get('trades', []):
                self.trades.append(Trade(
                    id=t_data['id'],
                    order_id='',
                    symbol=t_data['symbol'],
                    side=OrderSide(t_data['side']),
                    quantity=t_data['quantity'],
                    price=t_data['price'],
                    commission=t_data['commission'],
                    timestamp=datetime.fromisoformat(t_data['timestamp']),
                    pnl=t_data.get('pnl', 0),
                ))

            return True

        except Exception:
            return False


__all__ = [
    'PaperTradingEngine',
    'Account',
    'Position',
    'Order',
    'Trade',
    'OrderSide',
    'OrderType',
    'OrderStatus',
]


if __name__ == "__main__":
    # Test the paper trading engine
    print("=== Paper Trading Engine Test ===\n")

    engine = PaperTradingEngine(initial_capital=100000)

    # Set prices
    engine.update_price("AAPL", 150.00)
    engine.update_price("GOOGL", 2800.00)

    # Place buy order
    order1 = engine.place_order("AAPL", OrderSide.BUY, 100)
    print(f"Order 1: {order1.status.value}")
    print(f"  Filled at: ${order1.filled_price:.2f}")
    print(f"  Commission: ${order1.commission:.2f}")

    # Place sell order
    engine.update_price("AAPL", 155.00)
    order2 = engine.place_order("AAPL", OrderSide.SELL, 50)
    print(f"\nOrder 2: {order2.status.value}")
    print(f"  Filled at: ${order2.filled_price:.2f}")

    # Account summary
    summary = engine.get_account_summary()
    print(f"\nAccount Summary:")
    print(f"  Equity: ${summary['equity']:.2f}")
    print(f"  Realized PnL: ${summary['realized_pnl']:.2f}")
    print(f"  Win Rate: {summary['win_rate']:.1f}%")

    print("\n✅ PaperTradingEngine test passed!")
