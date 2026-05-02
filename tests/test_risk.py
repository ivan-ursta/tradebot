"""
tests/test_risk.py
==================
Unit tests for risk management modules.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import Position, Side, Signal, SignalDirection
from core.state import TradingState
from risk.kill_switch import KillSwitch, RiskManager
from risk.portfolio_limits import PortfolioLimits
from risk.position_sizing import PositionSizer
from risk.stops import StopManager


CONFIG = {
    "risk": {
        "max_risk_per_trade": 0.01,
        "max_total_exposure": 0.30,
        "max_single_market_exposure": 0.10,
        "max_open_positions": 3,
        "max_daily_loss": 0.05,
        "kill_switch_drawdown": 0.15,
        "stop_loss_atr_mult": 2.0,
        "take_profit_atr_mult": 3.0,
        "trailing_stop_atr_mult": 0.0,
        "cooldown_after_losses": 3,
        "cooldown_duration_seconds": 3600,
        "max_leverage": 5,
        "min_order_size_usd": 10.0,
        "max_signal_age_seconds": 60,
    }
}


class TestPositionSizer:
    def test_basic_sizing(self):
        sizer = PositionSizer(CONFIG)
        state = TradingState(10_000)
        signal = Signal(
            strategy_name="test",
            symbol="BTC",
            direction=SignalDirection.LONG,
            entry_price=50_000,
            stop_loss=49_000,
        )
        qty = sizer.calculate_size(signal, state)
        # risk = 10000 * 0.01 = 100; stop_dist = 1000; qty = 0.1
        assert abs(qty - 0.1) < 0.001

    def test_zero_for_missing_stop(self):
        sizer = PositionSizer(CONFIG)
        state = TradingState(10_000)
        signal = Signal(
            strategy_name="test",
            symbol="BTC",
            direction=SignalDirection.LONG,
            entry_price=50_000,
            stop_loss=None,
        )
        qty = sizer.calculate_size(signal, state)
        assert qty == 0.0

    def test_leverage_cap(self):
        sizer = PositionSizer(CONFIG)
        state = TradingState(10_000)
        # Very tight stop → large raw size → should be capped by leverage
        signal = Signal(
            strategy_name="test",
            symbol="BTC",
            direction=SignalDirection.LONG,
            entry_price=50_000,
            stop_loss=49_999,  # $1 stop → raw qty = 100
        )
        qty = sizer.calculate_size(signal, state)
        max_notional = 10_000 * 5  # max_leverage=5
        assert qty * 50_000 <= max_notional + 0.001


class TestPortfolioLimits:
    def _make_signal(self, symbol="BTC"):
        return Signal(
            strategy_name="test",
            symbol=symbol,
            direction=SignalDirection.LONG,
            entry_price=50_000,
            stop_loss=49_000,
        )

    def test_allows_clean_entry(self):
        limits = PortfolioLimits(CONFIG)
        state = TradingState(10_000)
        signal = self._make_signal()
        ok, reason = limits.check_entry(signal, state)
        assert ok, reason

    def test_blocks_at_max_positions(self):
        limits = PortfolioLimits(CONFIG)
        state = TradingState(10_000)
        # Fill up positions
        for s in ["BTC", "ETH", "SOL"]:
            state.positions[s] = Position(symbol=s, side=Side.LONG, quantity=0.1, avg_entry_price=1000)
        signal = self._make_signal("ARB")
        ok, reason = limits.check_entry(signal, state)
        assert not ok
        assert "Max open positions" in reason

    def test_blocks_duplicate_symbol(self):
        limits = PortfolioLimits(CONFIG)
        state = TradingState(10_000)
        state.positions["BTC"] = Position(symbol="BTC", side=Side.LONG, quantity=0.1, avg_entry_price=50000)
        signal = self._make_signal("BTC")
        ok, reason = limits.check_entry(signal, state)
        assert not ok

    def test_blocks_when_kill_switch_active(self):
        limits = PortfolioLimits(CONFIG)
        state = TradingState(10_000)
        state.activate_kill_switch("test reason")
        signal = self._make_signal()
        ok, reason = limits.check_entry(signal, state)
        assert not ok
        assert "Kill switch" in reason

    def test_blocks_on_daily_loss(self):
        limits = PortfolioLimits(CONFIG)
        state = TradingState(10_000)
        state.daily.starting_equity = 10_000
        state.daily.current_equity = 9_400  # -6% loss
        signal = self._make_signal()
        ok, reason = limits.check_entry(signal, state)
        assert not ok
        assert "Daily loss" in reason


class TestStopManager:
    def test_long_stop_below_entry(self):
        sm = StopManager(CONFIG)
        sl = sm.compute_stop_loss(50_000, 200, Side.LONG)
        assert sl < 50_000
        assert sl == pytest.approx(50_000 - 200 * 2.0)

    def test_short_stop_above_entry(self):
        sm = StopManager(CONFIG)
        sl = sm.compute_stop_loss(50_000, 200, Side.SHORT)
        assert sl > 50_000

    def test_long_tp_above_entry(self):
        sm = StopManager(CONFIG)
        tp = sm.compute_take_profit(50_000, 200, Side.LONG)
        assert tp > 50_000
        assert tp == pytest.approx(50_000 + 200 * 3.0)

    def test_stop_triggered_long(self):
        sm = StopManager(CONFIG)
        pos = Position(symbol="BTC", side=Side.LONG, quantity=1, avg_entry_price=50000, stop_loss=49000)
        assert sm.is_stop_triggered(pos, 48999)
        assert not sm.is_stop_triggered(pos, 49001)

    def test_tp_triggered_long(self):
        sm = StopManager(CONFIG)
        pos = Position(symbol="BTC", side=Side.LONG, quantity=1, avg_entry_price=50000, take_profit=53000)
        assert sm.is_tp_triggered(pos, 53001)
        assert not sm.is_tp_triggered(pos, 52999)


class TestKillSwitch:
    def test_activates_on_drawdown(self):
        ks = KillSwitch(CONFIG)
        state = TradingState(10_000)
        state.peak_equity = 10_000
        state.equity = 8_400  # 16% drawdown > 15% threshold
        active, reason = ks.evaluate(state)
        assert active
        assert "drawdown" in reason.lower()

    def test_no_activation_below_threshold(self):
        ks = KillSwitch(CONFIG)
        state = TradingState(10_000)
        state.peak_equity = 10_000
        state.equity = 9_000  # 10% drawdown < 15% threshold
        active, reason = ks.evaluate(state)
        assert not active

    def test_cooldown_set_after_losses(self):
        ks = KillSwitch(CONFIG)
        state = TradingState(10_000)
        state.consecutive_losses["test_strat"] = 3
        ks.check_strategy_cooldown("test_strat", state)
        assert state.is_in_cooldown("test_strat")
