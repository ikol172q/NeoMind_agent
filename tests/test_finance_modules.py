"""
Finance Module Tests for NeoMind Agent.

Tests for paper_trading, backtest, and risk_manager modules.

Created: 2026-04-02 (Phase 3 Testing)
"""
import os, sys, unittest, asyncio
from datetime import datetime, timedelta
from unittest import mock

_test_dir = os.path.dirname(os.path.abspath(__file__))
_agent_dir = os.path.dirname(_test_dir)
sys.path.insert(0, _agent_dir)

from agent.finance.paper_trading import (
    PaperTradingEngine,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    Order,
    Trade,
    Account,
)
from agent.finance.backtest import (
    BacktestEngine,
    BacktestConfig,
    BacktestResult,
    OHLCVBar,
)
from agent.finance.risk_manager import (
    RiskManager,
    RiskLimits,
    RiskAssessment,
    RiskLevel,
    PositionSizing,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bars(symbol: str, prices: list, start: datetime = None) -> list:
    """Generate OHLCVBar list from a sequence of close prices."""
    start = start or datetime(2025, 1, 1)
    bars = []
    for i, price in enumerate(prices):
        bars.append(OHLCVBar(
            timestamp=start + timedelta(days=i),
            open=price * 0.999,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=100_000,
        ))
    return bars


# ===========================================================================
# TestPaperTrading
# ===========================================================================

class TestPaperTrading(unittest.TestCase):
    """Tests for PaperTradingEngine."""

    def setUp(self):
        self.engine = PaperTradingEngine(
            initial_capital=100_000.0,
            commission_rate=0.001,
            slippage_rate=0.0,  # zero slippage for deterministic tests
        )

    # -- 1. Create engine with initial capital --
    def test_initial_capital(self):
        self.assertEqual(self.engine.account.initial_capital, 100_000.0)
        self.assertEqual(self.engine.account.cash, 100_000.0)
        self.assertEqual(self.engine.account.equity, 100_000.0)
        self.assertEqual(len(self.engine.account.positions), 0)

    # -- 2. Place market buy order --
    def test_market_buy(self):
        self.engine.update_price("AAPL", 150.0)
        order = self.engine.place_order("AAPL", OrderSide.BUY, 10)

        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.filled_quantity, 10)
        self.assertAlmostEqual(order.filled_price, 150.0, places=2)
        # Commission: 150 * 10 * 0.001 = 1.50
        self.assertAlmostEqual(order.commission, 1.50, places=2)

    # -- 3. Place market sell order --
    def test_market_sell(self):
        self.engine.update_price("AAPL", 150.0)
        self.engine.place_order("AAPL", OrderSide.BUY, 10)

        self.engine.update_price("AAPL", 160.0)
        sell_order = self.engine.place_order("AAPL", OrderSide.SELL, 10)

        self.assertEqual(sell_order.status, OrderStatus.FILLED)
        self.assertEqual(sell_order.filled_quantity, 10)
        self.assertAlmostEqual(sell_order.filled_price, 160.0, places=2)

    # -- 4. Position tracking --
    def test_position_tracking(self):
        self.engine.update_price("AAPL", 150.0)
        self.engine.place_order("AAPL", OrderSide.BUY, 20)

        pos = self.engine.get_position("AAPL")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.quantity, 20)
        self.assertAlmostEqual(pos.entry_price, 150.0, places=2)

        # Partial sell should reduce position
        self.engine.place_order("AAPL", OrderSide.SELL, 5)
        pos = self.engine.get_position("AAPL")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.quantity, 15)

        # Sell remaining should remove position
        self.engine.place_order("AAPL", OrderSide.SELL, 15)
        pos = self.engine.get_position("AAPL")
        self.assertIsNone(pos)

    # -- 5. Cash management after trades --
    def test_cash_management(self):
        self.engine.update_price("AAPL", 100.0)
        self.engine.place_order("AAPL", OrderSide.BUY, 10)

        # Cost = 100 * 10 + 100*10*0.001 = 1000 + 1 = 1001
        expected_cash = 100_000.0 - 1001.0
        self.assertAlmostEqual(self.engine.account.cash, expected_cash, places=2)

        # Sell at same price
        self.engine.place_order("AAPL", OrderSide.SELL, 10)
        # Proceeds = 100*10 - 100*10*0.001 = 1000 - 1 = 999
        expected_cash += 999.0
        self.assertAlmostEqual(self.engine.account.cash, expected_cash, places=2)

    # -- 6. Portfolio summary accuracy --
    def test_portfolio_summary(self):
        self.engine.update_price("AAPL", 100.0)
        self.engine.place_order("AAPL", OrderSide.BUY, 50)

        # Price goes up
        self.engine.update_price("AAPL", 110.0)
        summary = self.engine.get_account_summary()

        self.assertEqual(summary['positions'], 1)
        # Unrealized PnL: (110 - 100) * 50 = 500
        self.assertAlmostEqual(summary['unrealized_pnl'], 500.0, places=2)
        self.assertAlmostEqual(summary['realized_pnl'], 0.0, places=2)
        self.assertEqual(summary['total_trades'], 0)  # no sell yet

    # -- 7. Order validation: reject negative quantity --
    def test_reject_sell_without_position(self):
        self.engine.update_price("AAPL", 100.0)
        order = self.engine.place_order("AAPL", OrderSide.SELL, 10)
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("No position to sell", order.metadata.get('error', ''))

    def test_reject_sell_more_than_held(self):
        self.engine.update_price("AAPL", 100.0)
        self.engine.place_order("AAPL", OrderSide.BUY, 5)
        order = self.engine.place_order("AAPL", OrderSide.SELL, 10)
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("Insufficient shares", order.metadata.get('error', ''))

    # -- 8. Reject buy with insufficient funds --
    def test_reject_insufficient_funds(self):
        self.engine.update_price("AAPL", 100.0)
        # Trying to buy 1100 shares = $110,000 + commission > $100,000
        order = self.engine.place_order("AAPL", OrderSide.BUY, 1100)
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("Insufficient funds", order.metadata.get('error', ''))

    # -- 9. Reject market buy when no price available --
    def test_reject_no_price(self):
        order = self.engine.place_order("UNKNOWN", OrderSide.BUY, 1)
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("No price available", order.metadata.get('error', ''))

    # -- 10. Equity curve / account equity updates --
    def test_equity_updates_on_price_change(self):
        self.engine.update_price("AAPL", 100.0)
        self.engine.place_order("AAPL", OrderSide.BUY, 100)

        initial_summary = self.engine.get_account_summary()
        initial_equity = initial_summary['equity']

        # Price goes up
        self.engine.update_price("AAPL", 120.0)
        summary = self.engine.get_account_summary()
        # Unrealized: (120 - 100) * 100 = 2000
        self.assertAlmostEqual(summary['unrealized_pnl'], 2000.0, places=2)
        # Equity should increase relative to right after buying
        self.assertGreater(summary['equity'], initial_equity)


# ===========================================================================
# TestBacktestEngine
# ===========================================================================

class TestBacktestEngine(unittest.TestCase):
    """Tests for BacktestEngine."""

    def _make_config(self, days=30, capital=100_000.0,
                     commission=0.001, slippage=0.0):
        start = datetime(2025, 1, 1)
        end = start + timedelta(days=days)
        return BacktestConfig(
            start_date=start,
            end_date=end,
            initial_capital=capital,
            commission_rate=commission,
            slippage_rate=slippage,
        )

    # -- 1. Run backtest with simple strategy --
    def test_basic_buy_and_hold(self):
        """Buy on day 1, hold to end. Prices go up linearly."""
        config = self._make_config(days=10, slippage=0.0)
        engine = BacktestEngine(config)

        # Prices: 100, 101, 102, ... 109
        prices = [100 + i for i in range(10)]
        engine.load_data("TEST", _make_bars("TEST", prices))

        bought = [False]

        def strategy(eng, ts, current_prices):
            orders = []
            if not bought[0] and "TEST" in current_prices:
                orders.append(Order(
                    id="",
                    symbol="TEST",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=100,
                ))
                bought[0] = True
            return orders

        result = engine.run(strategy)
        self.assertIsInstance(result, BacktestResult)
        self.assertEqual(len(result.equity_curve), 10)
        # Equity curve should have been recorded and final equity should
        # reflect the unrealized gains from price appreciation (100->109)
        first_equity = result.equity_curve[0]['equity']
        final_equity = result.equity_curve[-1]['equity']
        # As prices rise from 100 to 109, equity should increase over time
        self.assertGreater(final_equity, first_equity)

    # -- 2. Metrics calculation accuracy --
    def test_metrics_with_trades(self):
        """Buy then sell -- check trade counts and win rate."""
        config = self._make_config(days=5, slippage=0.0, commission=0.0)
        engine = BacktestEngine(config)

        prices = [100, 105, 110, 115, 120]
        engine.load_data("TEST", _make_bars("TEST", prices))

        step = [0]

        def strategy(eng, ts, current_prices):
            orders = []
            step[0] += 1
            if step[0] == 1 and "TEST" in current_prices:
                orders.append(Order(id="", symbol="TEST", side=OrderSide.BUY,
                                    order_type=OrderType.MARKET, quantity=10))
            elif step[0] == 3 and "TEST" in current_prices:
                orders.append(Order(id="", symbol="TEST", side=OrderSide.SELL,
                                    order_type=OrderType.MARKET, quantity=10))
            return orders

        result = engine.run(strategy)
        # Two trades: 1 buy + 1 sell
        self.assertEqual(result.total_trades, 2)

    # -- 3. Edge case: no trades --
    def test_no_trades(self):
        config = self._make_config(days=5)
        engine = BacktestEngine(config)
        engine.load_data("TEST", _make_bars("TEST", [100]*5))

        def strategy(eng, ts, current_prices):
            return []

        result = engine.run(strategy)
        self.assertEqual(result.total_trades, 0)
        self.assertAlmostEqual(result.total_return, 0.0, places=4)
        self.assertEqual(result.win_rate, 0)

    # -- 4. Edge case: all losses --
    def test_all_losses(self):
        """Buy high, sell low repeatedly -- account should lose money."""
        config = self._make_config(days=6, slippage=0.0, commission=0.0)
        engine = BacktestEngine(config)

        # Sawtooth: high, low, high, low, high, low
        prices = [110, 90, 110, 90, 110, 90]
        engine.load_data("TEST", _make_bars("TEST", prices))

        step = [0]

        def strategy(eng, ts, current_prices):
            orders = []
            step[0] += 1
            if step[0] in (1, 3) and "TEST" in current_prices:
                orders.append(Order(id="", symbol="TEST", side=OrderSide.BUY,
                                    order_type=OrderType.MARKET, quantity=10))
            elif step[0] in (2, 4) and "TEST" in current_prices:
                pos = eng.get_current_position("TEST")
                if pos:
                    orders.append(Order(id="", symbol="TEST", side=OrderSide.SELL,
                                        order_type=OrderType.MARKET, quantity=pos.quantity))
            return orders

        result = engine.run(strategy)
        # There should be trades (buys + sells)
        self.assertGreater(result.total_trades, 0)
        # Buying at 110, selling at 90 => net loss on account
        self.assertGreater(
            engine.engine.account.losing_trades, 0,
            "Account should track losing trades from buy-high/sell-low"
        )
        self.assertEqual(engine.engine.account.winning_trades, 0)

    # -- 5. Commission / slippage impact --
    def test_commission_slippage_impact(self):
        """Same strategy with and without costs should differ."""
        prices = [100 + i for i in range(10)]

        def buy_and_sell(eng, ts, current_prices):
            orders = []
            if not hasattr(buy_and_sell, '_step'):
                buy_and_sell._step = 0
            buy_and_sell._step += 1
            if buy_and_sell._step == 1 and "TEST" in current_prices:
                orders.append(Order(id="", symbol="TEST", side=OrderSide.BUY,
                                    order_type=OrderType.MARKET, quantity=100))
            elif buy_and_sell._step == 9 and "TEST" in current_prices:
                pos = eng.get_current_position("TEST")
                if pos:
                    orders.append(Order(id="", symbol="TEST", side=OrderSide.SELL,
                                        order_type=OrderType.MARKET, quantity=pos.quantity))
            return orders

        # No costs
        cfg_free = self._make_config(days=10, commission=0.0, slippage=0.0)
        eng_free = BacktestEngine(cfg_free)
        eng_free.load_data("TEST", _make_bars("TEST", prices))
        buy_and_sell._step = 0
        result_free = eng_free.run(buy_and_sell)

        # With costs
        cfg_cost = self._make_config(days=10, commission=0.01, slippage=0.01)
        eng_cost = BacktestEngine(cfg_cost)
        eng_cost.load_data("TEST", _make_bars("TEST", prices))
        buy_and_sell._step = 0
        result_cost = eng_cost.run(buy_and_sell)

        # The costly version should have lower final equity
        free_final = result_free.equity_curve[-1]['equity']
        cost_final = result_cost.equity_curve[-1]['equity']
        self.assertGreater(free_final, cost_final)


# ===========================================================================
# TestRiskManager
# ===========================================================================

class TestRiskManager(unittest.TestCase):
    """Tests for RiskManager."""

    def _make_position(self, symbol, qty, price):
        return Position(
            symbol=symbol,
            quantity=qty,
            entry_price=price,
            current_price=price,
            side=OrderSide.BUY,
            opened_at=datetime.now(),
        )

    def setUp(self):
        self.limits = RiskLimits(
            max_position_size_pct=0.10,
            max_sector_exposure_pct=0.30,
            max_total_exposure_pct=0.95,
            max_daily_loss_pct=0.03,
            max_drawdown_pct=0.15,
            max_leverage=1.0,
        )
        self.rm = RiskManager(limits=self.limits, account_value=100_000.0)

    # -- 1. Position limit check --
    def test_position_size_within_limit(self):
        assessment = self.rm.assess_trade("AAPL", OrderSide.BUY, 60, 150.0)
        # 60 * 150 = 9000 => 9% < 10% limit
        self.assertTrue(assessment.allowed)

    def test_position_size_exceeds_limit(self):
        assessment = self.rm.assess_trade("AAPL", OrderSide.BUY, 100, 150.0)
        # 100 * 150 = 15000 => 15% > 10% limit
        self.assertFalse(assessment.allowed)
        self.assertTrue(any("Position size" in w for w in assessment.warnings))

    # -- 2. Sector concentration check --
    def test_sector_concentration_warning(self):
        # Already hold MSFT (Technology) worth $25,000
        positions = {
            "MSFT": self._make_position("MSFT", 100, 250.0),
        }
        # Buying AAPL (also Technology) for $10,000 => sector total = $35,000 = 35% > 30%
        assessment = self.rm.assess_trade(
            "AAPL", OrderSide.BUY, 66, 150.0,
            current_positions=positions,
        )
        self.assertTrue(any("Sector" in w for w in assessment.warnings))
        self.assertEqual(assessment.risk_level, RiskLevel.HIGH)

    # -- 3. Leverage / total exposure limit check --
    def test_total_exposure_exceeds_limit(self):
        # Already 90% invested
        positions = {
            "AAPL": self._make_position("AAPL", 300, 300.0),  # $90,000
        }
        # Buying another $8,000 => total = $98,000 = 98% > 95%
        assessment = self.rm.assess_trade(
            "JPM", OrderSide.BUY, 50, 160.0,
            current_positions=positions,
        )
        self.assertTrue(any("Total exposure" in w for w in assessment.warnings))

    # -- 4. Stop loss / drawdown proximity check --
    def test_drawdown_warning(self):
        # Simulate drawdown > 80% of limit (0.15 * 0.8 = 0.12)
        self.rm.update_account_value(100_000.0)
        self.rm.update_account_value(87_000.0)  # 13% drawdown > 12% threshold

        assessment = self.rm.assess_trade("AAPL", OrderSide.BUY, 5, 150.0)
        self.assertTrue(any("Drawdown" in w or "drawdown" in w.lower()
                            for w in assessment.warnings))

    # -- 5. Order approval flow: approved vs blocked --
    def test_small_trade_approved(self):
        assessment = self.rm.assess_trade("AAPL", OrderSide.BUY, 5, 150.0)
        # 5 * 150 = 750 => 0.75% well within limit
        self.assertTrue(assessment.allowed)
        self.assertEqual(assessment.risk_level, RiskLevel.LOW)
        self.assertEqual(len(assessment.warnings), 0)

    def test_daily_loss_blocks_trade(self):
        # Record a big daily loss exceeding the 3% limit ($3,000)
        self.rm.record_trade("AAPL", OrderSide.SELL, -4000.0)

        assessment = self.rm.assess_trade("GOOGL", OrderSide.BUY, 1, 150.0)
        self.assertFalse(assessment.allowed)
        self.assertEqual(assessment.risk_level, RiskLevel.CRITICAL)
        self.assertTrue(any("Daily loss" in w or "daily" in w.lower()
                            for w in assessment.warnings))

    # -- 6. Warning vs block distinction --
    def test_warning_without_block(self):
        """Sector warning should not block if position size is within limits."""
        # Sector exposure slightly over limit but position size OK
        positions = {
            "MSFT": self._make_position("MSFT", 120, 250.0),  # $30,000 = 30%
        }
        # Add small AAPL buy => sector goes over 30% but position is small
        assessment = self.rm.assess_trade(
            "AAPL", OrderSide.BUY, 10, 150.0,  # $1,500 = 1.5%
            current_positions=positions,
        )
        # Should have sector warning but still be allowed
        # (sector excess is a warning/HIGH risk, not a block)
        self.assertTrue(assessment.allowed)
        self.assertTrue(any("Sector" in w for w in assessment.warnings))
        self.assertIn(assessment.risk_level, (RiskLevel.HIGH, RiskLevel.MEDIUM))

    # -- 7. Position sizing: fixed method --
    def test_fixed_position_sizing(self):
        sizing = self.rm.calculate_position_size("AAPL", 150.0, method="fixed")
        # 10% of $100k = $10k => 10000/150 = 66 shares
        self.assertEqual(sizing.shares, 66)
        self.assertAlmostEqual(sizing.pct_of_portfolio, 0.10)

    # -- 8. Position sizing: volatility method --
    def test_volatility_position_sizing(self):
        sizing = self.rm.calculate_position_size(
            "AAPL", 150.0, volatility=0.3, method="volatility"
        )
        # risk_per_share = 150 * 0.3 = 45
        # shares = (100000 * 0.01) / 45 = 22
        self.assertEqual(sizing.shares, 22)
        self.assertGreater(sizing.dollar_amount, 0)

    # -- 9. Risk report generation --
    def test_risk_report(self):
        self.rm.record_trade("AAPL", OrderSide.BUY, 500.0)
        self.rm.record_trade("GOOGL", OrderSide.BUY, -200.0)

        report = self.rm.get_risk_report()
        self.assertIn('account_value', report)
        self.assertIn('current_drawdown', report)
        self.assertIn('limits', report)
        self.assertIn('recent_performance', report)
        self.assertIn('risk_status', report)
        self.assertEqual(report['recent_performance']['trades_30d'], 2)


if __name__ == "__main__":
    unittest.main()
