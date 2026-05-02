"""
portfolio/pnl.py
================
PnL tracking and daily statistics.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class TradePnL:
    symbol: str
    strategy: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    fees: float
    net_pnl: float
    entry_time: datetime
    exit_time: datetime

    @property
    def return_pct(self) -> float:
        cost = self.entry_price * self.quantity
        return self.net_pnl / cost * 100 if cost > 0 else 0.0


class PnLTracker:
    """
    Maintains a log of closed trade PnLs and computes running stats.
    """

    def __init__(self) -> None:
        self.trades: List[TradePnL] = []
        self._daily_pnl: Dict[str, float] = defaultdict(float)

    def record_trade(self, trade: TradePnL) -> None:
        self.trades.append(trade)
        day_key = trade.exit_time.strftime("%Y-%m-%d")
        self._daily_pnl[day_key] += trade.net_pnl
        logger.info(
            "Trade closed [%s/%s] %s pnl=%.4f fees=%.4f net=%.4f",
            trade.symbol, trade.strategy, trade.side,
            trade.gross_pnl, trade.fees, trade.net_pnl,
        )

    @property
    def total_pnl(self) -> float:
        return sum(t.net_pnl for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        winners = sum(1 for t in self.trades if t.net_pnl > 0)
        return winners / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_wins = sum(t.net_pnl for t in self.trades if t.net_pnl > 0)
        gross_losses = abs(sum(t.net_pnl for t in self.trades if t.net_pnl < 0))
        return gross_wins / gross_losses if gross_losses > 0 else float("inf")

    @property
    def average_trade(self) -> float:
        return self.total_pnl / len(self.trades) if self.trades else 0.0

    def daily_summary(self) -> Dict[str, float]:
        return dict(self._daily_pnl)
