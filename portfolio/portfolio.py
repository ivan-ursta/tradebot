"""
portfolio/portfolio.py
======================
Portfolio state management: tracks positions, realised/unrealised PnL,
and provides equity accounting for the paper broker and live engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.models import Fill, Order, Position, Side

logger = logging.getLogger(__name__)


class Portfolio:
    """
    Tracks all positions and cash balance.
    Suitable for both paper and live sessions.
    """

    def __init__(self, starting_balance: float = 10_000.0) -> None:
        self.cash: float = starting_balance
        self.starting_balance: float = starting_balance
        self.positions: Dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.total_fees_paid: float = 0.0
        self.fills: List[Fill] = []

    # ------------------------------------------------------------------
    # Fill processing
    # ------------------------------------------------------------------

    def apply_fill(self, fill: Fill) -> None:
        """Update portfolio state from a confirmed fill."""
        self.fills.append(fill)
        self.total_fees_paid += fill.fee
        self.cash -= fill.fee  # fee always debited from cash

        symbol = fill.symbol
        existing = self.positions.get(symbol)

        if fill.side == Side.LONG:
            self._apply_long_fill(symbol, fill, existing)
        else:
            self._apply_short_fill(symbol, fill, existing)

    def _apply_long_fill(
        self, symbol: str, fill: Fill, existing: Optional[Position]
    ) -> None:
        cost = fill.quantity * fill.price
        self.cash -= cost

        if existing is None or existing.side == Side.LONG:
            # Open or add to long
            if existing is None:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=Side.LONG,
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    strategy_name=fill.strategy_name,
                )
            else:
                total_qty = existing.quantity + fill.quantity
                existing.avg_entry_price = (
                    existing.avg_entry_price * existing.quantity + fill.price * fill.quantity
                ) / total_qty
                existing.quantity = total_qty
        else:
            # Closing short
            pnl = (existing.avg_entry_price - fill.price) * fill.quantity
            self.realized_pnl += pnl
            self.cash += existing.avg_entry_price * fill.quantity + pnl  # return margin + pnl
            remaining = existing.quantity - fill.quantity
            if remaining <= 1e-8:
                del self.positions[symbol]
                logger.info("Position closed [%s] realized_pnl=%.4f", symbol, pnl)
            else:
                existing.quantity = remaining
                existing.realized_pnl += pnl

    def _apply_short_fill(
        self, symbol: str, fill: Fill, existing: Optional[Position]
    ) -> None:
        if existing is None or existing.side == Side.SHORT:
            # Open or add to short (we receive proceeds from shorting)
            proceeds = fill.quantity * fill.price
            self.cash += proceeds
            if existing is None:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=Side.SHORT,
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    strategy_name=fill.strategy_name,
                )
            else:
                total_qty = existing.quantity + fill.quantity
                existing.avg_entry_price = (
                    existing.avg_entry_price * existing.quantity + fill.price * fill.quantity
                ) / total_qty
                existing.quantity = total_qty
        else:
            # Closing long
            proceeds = fill.quantity * fill.price
            self.cash += proceeds
            pnl = (fill.price - existing.avg_entry_price) * fill.quantity
            self.realized_pnl += pnl
            remaining = existing.quantity - fill.quantity
            if remaining <= 1e-8:
                del self.positions[symbol]
                logger.info("Position closed [%s] realized_pnl=%.4f", symbol, pnl)
            else:
                existing.quantity = remaining
                existing.realized_pnl += pnl

    # ------------------------------------------------------------------
    # Mark to market
    # ------------------------------------------------------------------

    def mark_to_market(self, prices: Dict[str, float]) -> float:
        """Compute total equity = cash + unrealized PnL of all positions."""
        unrealized = 0.0
        for symbol, pos in self.positions.items():
            price = prices.get(symbol)
            if price:
                unrealized += pos.mark_to_market(price)
        return self.cash + unrealized

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def summary(self, prices: Dict[str, float]) -> dict:
        equity = self.mark_to_market(prices)
        return {
            "equity": equity,
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "total_fees": self.total_fees_paid,
            "open_positions": self.open_position_count,
            "total_return_pct": (equity - self.starting_balance) / self.starting_balance * 100,
        }
