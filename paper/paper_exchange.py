"""
paper/paper_exchange.py
=======================
Thin adapter that presents a paper broker as an "exchange-like" interface
so the engine can interact with it identically regardless of mode.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from core.models import AccountState, Order, Position
from paper.paper_broker import PaperBroker

logger = logging.getLogger(__name__)


class PaperExchange:
    """
    Mimics a real exchange interface for paper trading.
    Delegates to PaperBroker for fills and balance.
    """

    def __init__(self, broker: PaperBroker) -> None:
        self.broker = broker

    def get_balance(self) -> float:
        return self.broker.get_balance()

    def get_positions(self) -> List[Position]:
        return list(self.broker.portfolio.positions.values())

    def get_open_orders(self) -> List[Order]:
        return []  # Paper broker fills immediately; no open orders

    def get_account_state(self, prices: Dict[str, float]) -> AccountState:
        from datetime import datetime, timezone
        equity = self.broker.get_equity(prices)
        positions = self.get_positions()
        from core.models import AccountState
        return AccountState(
            timestamp=datetime.now(timezone.utc),
            equity=equity,
            available_balance=self.broker.get_balance(),
            used_margin=sum(p.notional_value for p in positions),
            unrealized_pnl=sum(p.unrealized_pnl for p in positions),
            positions=positions,
        )

    def print_session_summary(self, prices: Dict[str, float]) -> None:
        summary = self.broker.summary(prices)
        pnl = self.broker.pnl_tracker
        logger.info(
            "[PAPER SESSION] equity=%.2f return=%.2f%% realized_pnl=%.2f "
            "trades=%d win_rate=%.1f%% profit_factor=%.2f",
            summary["equity"],
            summary["total_return_pct"],
            pnl.total_pnl,
            len(pnl.trades),
            pnl.win_rate * 100,
            pnl.profit_factor,
        )
