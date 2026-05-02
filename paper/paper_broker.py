"""
paper/paper_broker.py
=====================
Paper trading broker: simulates order fills at current market prices.
Maintains its own balance and trade journal.
No real orders are ever submitted.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.models import Fill, Order, OrderStatus, OrderType, Side, Signal
from execution.fee_model import FeeSchedule, HYPERLIQUID_DEFAULT
from execution.slippage import SlippageModel, apply_slippage
from portfolio.portfolio import Portfolio
from portfolio.pnl import PnLTracker, TradePnL

logger = logging.getLogger(__name__)


class PaperBroker:
    """
    Simulates real broker behaviour for paper trading.

    Features:
    - Immediate fill at current price + simulated slippage
    - Fee deduction
    - Balance tracking
    - Trade journal
    - Equity history
    """

    def __init__(
        self,
        starting_balance: float = 10_000.0,
        fee_schedule: FeeSchedule = HYPERLIQUID_DEFAULT,
        slippage_bps: float = 5,
        latency_ms: float = 50,
    ) -> None:
        self.portfolio = Portfolio(starting_balance)
        self.fee_schedule = fee_schedule
        self.slippage_bps = slippage_bps
        self.latency_ms = latency_ms
        self.pnl_tracker = PnLTracker()
        self._entry_records: Dict[str, dict] = {}  # symbol → entry info

    # ------------------------------------------------------------------
    # Fill simulation
    # ------------------------------------------------------------------

    def fill_order(self, order: Order, signal: Optional[Signal] = None) -> Optional[Fill]:
        """
        Simulate filling an order at current market price.
        Returns Fill on success, None on failure.
        """
        if order.quantity <= 0:
            logger.warning("Zero quantity order rejected")
            return None

        # Use limit price if set, otherwise use last known price from signal
        base_price = order.price or (signal.entry_price if signal else None)
        if base_price is None or base_price <= 0:
            logger.error("Cannot fill order: no price available for %s", order.symbol)
            return None

        # Apply slippage
        is_buy = order.side == Side.LONG
        fill_price = apply_slippage(
            base_price,
            is_buy=is_buy,
            model=SlippageModel.FIXED_BPS,
            bps=self.slippage_bps,
        )

        fee = self.fee_schedule.compute_fee(fill_price * order.quantity, is_taker=True)

        # Check sufficient balance for buys
        if is_buy:
            required = fill_price * order.quantity + fee
            if required > self.portfolio.cash:
                logger.warning(
                    "Insufficient paper balance: need %.2f, have %.2f",
                    required, self.portfolio.cash,
                )
                return None

        fill = Fill(
            id=str(uuid.uuid4()),
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            fee_asset="USD",
            timestamp=datetime.now(timezone.utc),
            strategy_name=order.strategy_name,
            is_paper=True,
        )

        # Apply to portfolio
        self.portfolio.apply_fill(fill)

        # Track entry for PnL calculation on close
        if order.reduce_only or (not is_buy and order.symbol in self._entry_records):
            self._record_close(fill)
        elif order.symbol not in self._entry_records:
            self._entry_records[order.symbol] = {
                "price": fill_price,
                "qty": order.quantity,
                "fee": fee,
                "time": fill.timestamp,
                "side": order.side,
                "strategy": order.strategy_name,
            }

        logger.info(
            "[PAPER] Fill: %s %s %.4f @ %.4f | fee=%.4f | balance=%.2f",
            order.symbol, order.side.value, order.quantity,
            fill_price, fee, self.portfolio.cash,
        )
        return fill

    def _record_close(self, fill: Fill) -> None:
        """Record a closed trade in PnL tracker."""
        entry = self._entry_records.pop(fill.symbol, None)
        if entry is None:
            return

        is_long_close = fill.side == Side.SHORT  # closing a long
        if is_long_close:
            gross_pnl = (fill.price - entry["price"]) * fill.quantity
        else:
            gross_pnl = (entry["price"] - fill.price) * fill.quantity

        net_pnl = gross_pnl - fill.fee - entry["fee"]
        cost = entry["price"] * fill.quantity

        trade = TradePnL(
            symbol=fill.symbol,
            strategy=fill.strategy_name,
            side=entry["side"].value,
            entry_price=entry["price"],
            exit_price=fill.price,
            quantity=fill.quantity,
            gross_pnl=gross_pnl,
            fees=fill.fee + entry["fee"],
            net_pnl=net_pnl,
            entry_time=entry["time"],
            exit_time=fill.timestamp,
        )
        self.pnl_tracker.record_trade(trade)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_equity(self, current_prices: Dict[str, float]) -> float:
        return self.portfolio.mark_to_market(current_prices)

    def get_balance(self) -> float:
        return self.portfolio.cash

    def summary(self, current_prices: Dict[str, float]) -> dict:
        return self.portfolio.summary(current_prices)
