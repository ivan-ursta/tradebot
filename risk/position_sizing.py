"""
risk/position_sizing.py
========================
Volatility-adjusted position sizing based on:
  - Account equity
  - Risk per trade (fraction of equity)
  - Stop distance
  - ATR normalisation
  - Exchange precision rounding
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from core.models import MarketInfo, Signal, SignalDirection
from core.state import TradingState

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    Calculates position size such that hitting the stop loss
    costs at most `max_risk_per_trade * equity`.
    """

    def __init__(self, config: dict) -> None:
        self.max_risk_fraction: float = config.get("risk", {}).get("max_risk_per_trade", 0.01)
        self.max_leverage: float = config.get("risk", {}).get("max_leverage", 5.0)
        self.min_order_usd: float = config.get("risk", {}).get("min_order_size_usd", 10.0)

    def calculate_size(
        self,
        signal: Signal,
        state: TradingState,
        market_info: Optional[MarketInfo] = None,
    ) -> float:
        """
        Returns position quantity (in base asset units).
        Returns 0.0 if sizing is not possible.
        """
        if signal.entry_price is None or signal.entry_price <= 0:
            logger.warning("Cannot size: no entry price in signal")
            return 0.0

        if signal.stop_loss is None:
            logger.warning("Cannot size: no stop loss in signal")
            return 0.0

        equity = state.equity
        if equity <= 0:
            return 0.0

        # Dollar risk budget for this trade
        risk_dollars = equity * self.max_risk_fraction * signal.confidence

        # Stop distance in price terms
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        if stop_distance <= 0:
            logger.warning("Cannot size: zero stop distance")
            return 0.0

        # Raw quantity: risk_dollars / stop_distance
        raw_qty = risk_dollars / stop_distance

        # Cap by leverage constraint
        max_notional = equity * self.max_leverage
        max_qty_by_leverage = max_notional / signal.entry_price
        raw_qty = min(raw_qty, max_qty_by_leverage)

        # Enforce minimum order size
        notional = raw_qty * signal.entry_price
        if notional < self.min_order_usd:
            logger.debug("Sized order too small (%.2f USD < %.2f minimum)", notional, self.min_order_usd)
            return 0.0

        # Round to exchange precision
        if market_info:
            raw_qty = market_info.round_quantity(raw_qty)

        logger.debug(
            "Position size: equity=%.2f risk_pct=%.2f%% stop_dist=%.4f qty=%.4f notional=%.2f",
            equity, self.max_risk_fraction * 100, stop_distance, raw_qty, raw_qty * signal.entry_price,
        )
        return raw_qty

    def calculate_size_fixed_usd(
        self,
        usd_amount: float,
        entry_price: float,
        market_info: Optional[MarketInfo] = None,
    ) -> float:
        """Alternative: fixed USD notional → quantity."""
        if entry_price <= 0:
            return 0.0
        qty = usd_amount / entry_price
        if market_info:
            qty = market_info.round_quantity(qty)
        return qty
