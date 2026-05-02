"""
risk/stops.py
=============
Stop loss, take profit, and trailing stop management.
Computes and updates stop levels for open positions.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.models import Position, Side

logger = logging.getLogger(__name__)


class StopManager:
    """
    Manages stop loss and take profit levels.
    All methods are pure functions — they return new levels, not modify state.
    The engine/order manager applies the changes.
    """

    def __init__(self, config: dict) -> None:
        risk = config.get("risk", {})
        self.sl_atr_mult: float = risk.get("stop_loss_atr_mult", 2.0)
        self.tp_atr_mult: float = risk.get("take_profit_atr_mult", 3.0)
        self.trailing_atr_mult: float = risk.get("trailing_stop_atr_mult", 0.0)

    # ------------------------------------------------------------------
    # Initial stop levels
    # ------------------------------------------------------------------

    def compute_stop_loss(
        self,
        entry_price: float,
        atr: float,
        side: Side,
    ) -> float:
        dist = atr * self.sl_atr_mult
        if side == Side.LONG:
            return entry_price - dist
        return entry_price + dist

    def compute_take_profit(
        self,
        entry_price: float,
        atr: float,
        side: Side,
    ) -> float:
        dist = atr * self.tp_atr_mult
        if side == Side.LONG:
            return entry_price + dist
        return entry_price - dist

    # ------------------------------------------------------------------
    # Trailing stop
    # ------------------------------------------------------------------

    def update_trailing_stop(
        self,
        position: Position,
        current_price: float,
        atr: float,
    ) -> Optional[float]:
        """
        Update trailing stop for a position.
        Returns the new trailing stop level, or None if trailing is disabled.
        """
        if self.trailing_atr_mult <= 0:
            return None

        trail_dist = atr * self.trailing_atr_mult

        if position.side == Side.LONG:
            new_trail = current_price - trail_dist
            if position.trailing_stop is None or new_trail > position.trailing_stop:
                logger.debug(
                    "Trailing stop updated LONG %s: %.4f → %.4f",
                    position.symbol, position.trailing_stop or 0, new_trail,
                )
                return new_trail
        else:
            new_trail = current_price + trail_dist
            if position.trailing_stop is None or new_trail < position.trailing_stop:
                logger.debug(
                    "Trailing stop updated SHORT %s: %.4f → %.4f",
                    position.symbol, position.trailing_stop or 0, new_trail,
                )
                return new_trail

        return position.trailing_stop

    # ------------------------------------------------------------------
    # Stop triggered check
    # ------------------------------------------------------------------

    @staticmethod
    def is_stop_triggered(position: Position, current_price: float) -> bool:
        """Check if stop loss OR trailing stop has been triggered."""
        if position.side == Side.LONG:
            if position.stop_loss and current_price <= position.stop_loss:
                return True
            if position.trailing_stop and current_price <= position.trailing_stop:
                return True
        else:
            if position.stop_loss and current_price >= position.stop_loss:
                return True
            if position.trailing_stop and current_price >= position.trailing_stop:
                return True
        return False

    @staticmethod
    def is_tp_triggered(position: Position, current_price: float) -> bool:
        if position.take_profit is None:
            return False
        if position.side == Side.LONG:
            return current_price >= position.take_profit
        return current_price <= position.take_profit
