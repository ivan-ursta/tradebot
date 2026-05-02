"""
tests/test_execution.py
=======================
Unit tests for fill simulation, slippage, and fee models.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from core.models import Order, OrderType, Side
from execution.fee_model import FeeSchedule, compute_round_trip_cost
from execution.fill_simulator import FillSimulator
from execution.slippage import SlippageModel, apply_slippage


def make_order(
    symbol: str = "BTC",
    side: Side = Side.LONG,
    order_type: OrderType = OrderType.MARKET,
    qty: float = 0.1,
    price: float | None = None,
) -> Order:
    return Order(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        price=price,
        strategy_name="test",
    )


def make_bar(open_: float, high: float, low: float, close: float, ts=None) -> pd.Series:
    ts = ts or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return pd.Series(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1000},
        name=ts,
    )


class TestFillSimulator:
    def setup_method(self):
        self.sim = FillSimulator({}, fee_rate=0.0004, slippage_bps=5)

    def test_market_buy_fills_above_open(self):
        order = make_order(side=Side.LONG, order_type=OrderType.MARKET)
        bar = make_bar(50000, 51000, 49500, 50500)
        fill = self.sim.simulate_fill(order, bar)
        assert fill is not None
        assert fill.price > 50000  # slippage applied
        assert fill.fee > 0
        assert fill.side == Side.LONG

    def test_market_sell_fills_below_open(self):
        order = make_order(side=Side.SHORT, order_type=OrderType.MARKET)
        bar = make_bar(50000, 51000, 49500, 50500)
        fill = self.sim.simulate_fill(order, bar)
        assert fill is not None
        assert fill.price < 50000  # slippage applied

    def test_limit_buy_fills_when_price_dips(self):
        order = make_order(side=Side.LONG, order_type=OrderType.LIMIT, price=49800)
        bar = make_bar(50000, 50500, 49700, 50200)  # low=49700 < limit=49800
        fill = self.sim.simulate_fill(order, bar)
        assert fill is not None

    def test_limit_buy_does_not_fill_when_price_stays_above(self):
        order = make_order(side=Side.LONG, order_type=OrderType.LIMIT, price=49000)
        bar = make_bar(50000, 50500, 49500, 50200)  # low=49500 > limit=49000
        fill = self.sim.simulate_fill(order, bar)
        assert fill is None

    def test_limit_sell_fills_when_price_rises(self):
        order = make_order(side=Side.SHORT, order_type=OrderType.LIMIT, price=50500)
        bar = make_bar(50000, 50700, 49800, 50200)  # high=50700 > limit=50500
        fill = self.sim.simulate_fill(order, bar)
        assert fill is not None


class TestSlippage:
    def test_buy_slippage_increases_price(self):
        price = apply_slippage(50000, is_buy=True, bps=10)
        assert price > 50000

    def test_sell_slippage_decreases_price(self):
        price = apply_slippage(50000, is_buy=False, bps=10)
        assert price < 50000

    def test_zero_slippage(self):
        price = apply_slippage(50000, is_buy=True, model=SlippageModel.ZERO)
        assert price == 50000

    def test_fixed_bps_amount(self):
        price = apply_slippage(50000, is_buy=True, bps=10)
        expected = 50000 * (1 + 10 / 10_000)
        assert abs(price - expected) < 0.01


class TestFeeModel:
    def test_taker_fee(self):
        schedule = FeeSchedule(taker_rate=0.0004)
        fee = schedule.compute_fee(10_000, is_taker=True)
        assert abs(fee - 4.0) < 0.001

    def test_maker_fee_lower(self):
        schedule = FeeSchedule(maker_rate=0.0002, taker_rate=0.0004)
        maker = schedule.compute_fee(10_000, is_taker=False)
        taker = schedule.compute_fee(10_000, is_taker=True)
        assert maker < taker

    def test_round_trip_cost(self):
        cost = compute_round_trip_cost(50_000, 51_000, 0.1)
        # entry: 50000*0.1*0.0004 = 2.0; exit: 51000*0.1*0.0004 = 2.04 → total ~4.04
        assert cost == pytest.approx(4.04, abs=0.01)
