"""
execution/order_manager.py
==========================
Manages the lifecycle of orders: submission, tracking, cancellation.
Routes to paper broker or live execution client based on mode.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.events import EventType, bus
from core.models import (
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Position,
    Side,
    Signal,
    SignalDirection,
    TradingMode,
)
from core.state import TradingState

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Single entry point for order submission regardless of trading mode.
    In paper mode: routes to paper_broker.
    In live mode: routes to execution_client (requires explicit live flag).
    """

    def __init__(
        self,
        config: dict,
        state: TradingState,
        mode: TradingMode = TradingMode.PAPER,
        paper_broker=None,
        execution_client=None,
    ) -> None:
        self.config = config
        self.state = state
        self.mode = mode
        self.paper_broker = paper_broker
        self.execution_client = execution_client
        exec_cfg = config.get("execution", {})
        self.order_type_cfg: str = exec_cfg.get("order_type", "limit")
        self.limit_slippage_bps: float = exec_cfg.get("limit_slippage_bps", 5)
        self.order_timeout: int = exec_cfg.get("order_timeout_seconds", 30)

    # ------------------------------------------------------------------
    # Entry order
    # ------------------------------------------------------------------

    async def submit_entry(self, signal: Signal, quantity: float) -> Optional[Order]:
        """
        Create and submit an entry order for a given signal.
        Returns the Order if submitted, None if blocked.
        """
        if quantity <= 0:
            return None

        # Duplicate check — already have this order?
        for order in self.state.open_orders.values():
            if order.symbol == signal.symbol and order.is_open:
                logger.warning("Duplicate order blocked for %s", signal.symbol)
                return None

        side = Side.LONG if signal.direction == SignalDirection.LONG else Side.SHORT
        price = self._compute_limit_price(signal.entry_price, side)

        order = Order(
            id=str(uuid.uuid4()),
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.LIMIT if self.order_type_cfg == "limit" else OrderType.MARKET,
            quantity=quantity,
            price=price,
            signal_id=signal.id,
            strategy_name=signal.strategy_name,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        logger.info(
            "Submitting %s order [%s] side=%s qty=%.4f price=%s",
            order.order_type.value, signal.symbol, side.value, quantity,
            f"{price:.4f}" if price else "MARKET",
        )

        if self.mode == TradingMode.PAPER:
            return await self._submit_paper(order, signal)
        else:
            return await self._submit_live(order, signal)

    # ------------------------------------------------------------------
    # Close position
    # ------------------------------------------------------------------

    async def close_position(
        self, position: Position, reason: str = "", price: Optional[float] = None
    ) -> Optional[Order]:
        """Close an open position with a market order."""
        logger.info("Closing position [%s] reason=%s price=%s", position.symbol, reason, price)

        # Fall back to avg entry price so paper fills never get a None price
        fill_price = price or position.avg_entry_price

        close_side = Side.SHORT if position.side == Side.LONG else Side.LONG
        order = Order(
            id=str(uuid.uuid4()),
            symbol=position.symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            price=fill_price,
            reduce_only=True,
            strategy_name=position.strategy_name,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            meta={"close_reason": reason},
        )

        if self.mode == TradingMode.PAPER:
            return await self._submit_paper(order, None)
        else:
            return await self._submit_live(order, None)

    # ------------------------------------------------------------------
    # Paper routing
    # ------------------------------------------------------------------

    async def _submit_paper(self, order: Order, signal: Optional[Signal]) -> Optional[Order]:
        if self.paper_broker is None:
            logger.error("Paper broker not set")
            return None
        try:
            fill = self.paper_broker.fill_order(order, signal)
            if fill:
                self.state.open_orders.pop(order.id, None)
                order.status = OrderStatus.FILLED
                order.filled_quantity = fill.quantity
                order.avg_fill_price = fill.price
                order.fees_paid = fill.fee
                self.state.add_fill(fill)
                bus.emit(EventType.ORDER_FILLED, source="paper", payload=fill)

                # Update position in state
                self._update_state_from_fill(fill, signal)
            return order
        except Exception as exc:  # noqa: BLE001
            logger.exception("Paper fill error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Live routing
    # ------------------------------------------------------------------

    async def _submit_live(self, order: Order, signal: Optional[Signal]) -> Optional[Order]:
        if self.execution_client is None:
            logger.error("ExecutionClient not set for live mode")
            return None
        try:
            oid = self.execution_client.place_order(order)
            order.exchange_order_id = oid
            order.status = OrderStatus.OPEN
            self.state.open_orders[order.id] = order
            bus.emit(EventType.ORDER_SUBMITTED, source="live", payload=order)
            return order
        except Exception as exc:  # noqa: BLE001
            logger.exception("Live order submission failed: %s", exc)
            order.status = OrderStatus.REJECTED
            bus.emit(EventType.ORDER_REJECTED, source="live", payload=order)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_limit_price(
        self, mid_price: Optional[float], side: Side
    ) -> Optional[float]:
        if mid_price is None or self.order_type_cfg == "market":
            return None
        slippage = (self.limit_slippage_bps / 10_000) * mid_price
        if side == Side.LONG:
            return mid_price + slippage  # willing to pay a bit more to fill
        return mid_price - slippage  # willing to receive a bit less

    def _update_state_from_fill(self, fill: Fill, signal: Optional[Signal]) -> None:
        """Update TradingState positions from a confirmed fill."""
        symbol = fill.symbol
        existing = self.state.positions.get(symbol)

        if fill.side == Side.LONG:
            if existing is None:
                # New long position
                pos = Position(
                    symbol=symbol,
                    side=Side.LONG,
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    strategy_name=fill.strategy_name,
                    opened_at=fill.timestamp,
                )
                if signal:
                    pos.stop_loss = signal.stop_loss
                    pos.take_profit = signal.take_profit
                self.state.update_position(pos)
                bus.emit(EventType.POSITION_OPENED, source="order_manager", payload=pos)
            else:
                # Close short or add to long
                existing.quantity = max(0, existing.quantity - fill.quantity)
                if existing.quantity <= 1e-8:
                    self.state.positions.pop(symbol, None)
                    bus.emit(EventType.POSITION_CLOSED, source="order_manager", payload=existing)
        else:
            if existing is None:
                # New short position
                pos = Position(
                    symbol=symbol,
                    side=Side.SHORT,
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    strategy_name=fill.strategy_name,
                    opened_at=fill.timestamp,
                )
                if signal:
                    pos.stop_loss = signal.stop_loss
                    pos.take_profit = signal.take_profit
                self.state.update_position(pos)
                bus.emit(EventType.POSITION_OPENED, source="order_manager", payload=pos)
            else:
                existing.quantity = max(0, existing.quantity - fill.quantity)
                if existing.quantity <= 1e-8:
                    self.state.positions.pop(symbol, None)
                    bus.emit(EventType.POSITION_CLOSED, source="order_manager", payload=existing)
