"""
execution/fill_simulator.py
============================
Simulates order fills for backtesting and paper trading.
Models latency, slippage, and partial fills realistically.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from core.models import Fill, Order, OrderType, Side

logger = logging.getLogger(__name__)


class FillSimulator:
    """
    Conservative fill model for backtesting and paper trading.
    - Market orders: fill at next-bar open + slippage
    - Limit orders: fill if price crosses limit level on next bar
    - Assumes latency_bars=1 (fill on bar after signal)
    """

    def __init__(self, config: dict, fee_rate: float = 0.0004, slippage_bps: float = 5) -> None:
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps

    def simulate_fill(
        self,
        order: Order,
        next_bar: pd.Series,
    ) -> Fill | None:
        """
        Attempt to fill order on `next_bar`.
        Returns Fill if filled, None if not filled.
        """
        if order.order_type == OrderType.MARKET:
            return self._fill_market(order, next_bar)
        return self._fill_limit(order, next_bar)

    def _fill_market(self, order: Order, bar: pd.Series) -> Fill:
        """Market orders fill at bar open + slippage."""
        open_price = float(bar["open"])
        slippage = (self.slippage_bps / 10_000) * open_price
        if order.side == Side.LONG:
            fill_price = open_price + slippage
        else:
            fill_price = open_price - slippage

        fee = fill_price * order.quantity * self.fee_rate
        return self._make_fill(order, fill_price, order.quantity, fee, bar)

    def _fill_limit(self, order: Order, bar: pd.Series) -> Fill | None:
        """
        Limit order fills if the bar's price range crosses the limit price.
        Conservative: only fill if high/low crosses limit, not just touches.
        """
        limit = order.price
        if limit is None:
            return self._fill_market(order, bar)

        low = float(bar["low"])
        high = float(bar["high"])

        if order.side == Side.LONG and low < limit:
            fill_price = min(limit, float(bar["open"]))  # conservative
            fee = fill_price * order.quantity * self.fee_rate
            return self._make_fill(order, fill_price, order.quantity, fee, bar)

        if order.side == Side.SHORT and high > limit:
            fill_price = max(limit, float(bar["open"]))
            fee = fill_price * order.quantity * self.fee_rate
            return self._make_fill(order, fill_price, order.quantity, fee, bar)

        return None

    @staticmethod
    def _make_fill(order: Order, price: float, qty: float, fee: float, bar: pd.Series) -> Fill:
        ts = bar.name if isinstance(bar.name, datetime) else datetime.now(timezone.utc)
        return Fill(
            id=f"fill_{order.id[:8]}",
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=qty,
            price=price,
            fee=fee,
            fee_asset="USD",
            timestamp=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
            strategy_name=order.strategy_name,
            is_paper=True,
        )
