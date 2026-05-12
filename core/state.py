"""
core/state.py
=============
Shared runtime state container passed to strategies and risk modules.
Provides a single source of truth for positions, equity, regime, and
recent signals during live / paper execution.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from core.models import (
    AccountState,
    Fill,
    MarketRegime,
    Order,
    Position,
    Signal,
    Side,
)

logger = logging.getLogger(__name__)


@dataclass
class DailyStats:
    date: str
    starting_equity: float
    current_equity: float
    realized_pnl: float = 0.0
    trade_count: int = 0
    win_count: int = 0

    @property
    def daily_pnl_pct(self) -> float:
        if self.starting_equity == 0:
            return 0.0
        return (self.current_equity - self.starting_equity) / self.starting_equity

    @property
    def win_rate(self) -> float:
        if self.trade_count == 0:
            return 0.0
        return self.win_count / self.trade_count


class TradingState:
    """
    Centralised mutable state for the trading session.
    Strategies and risk modules read from this; the engine writes to it.
    """

    def __init__(self, starting_equity: float = 10_000.0) -> None:
        # Account
        self.equity: float = starting_equity
        self.available_balance: float = starting_equity
        self.peak_equity: float = starting_equity
        self.starting_equity: float = starting_equity

        # Positions keyed by symbol
        self.positions: Dict[str, Position] = {}

        # Open orders keyed by order id
        self.open_orders: Dict[str, Order] = {}

        # Recent fills (capped)
        self.recent_fills: Deque[Fill] = deque(maxlen=500)

        # Regime per symbol
        self.regimes: Dict[str, MarketRegime] = {}

        # Recent signals per symbol (last N)
        self.recent_signals: Dict[str, Deque[Signal]] = {}

        # Kill switch
        self.kill_switch_active: bool = False
        self.kill_switch_reason: str = ""

        # Cooldown per strategy
        self.cooldown_until: Dict[str, datetime] = {}

        # Consecutive losses per strategy
        self.consecutive_losses: Dict[str, int] = {}

        # Daily stats
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily: DailyStats = DailyStats(
            date=today,
            starting_equity=starting_equity,
            current_equity=starting_equity,
        )

        # Last account snapshot from exchange
        self.last_account_state: Optional[AccountState] = None

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    @property
    def current_drawdown(self) -> float:
        """Fraction below peak equity (positive value means drawdown)."""
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    @property
    def open_position_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.quantity > 0)

    @property
    def total_exposure_usd(self) -> float:
        return sum(p.notional_value for p in self.positions.values())

    @property
    def total_exposure_fraction(self) -> float:
        if self.equity <= 0:
            return 0.0
        leverage = 1.0
        if hasattr(self, "config_ref"):
            leverage = float(self.config_ref.get("risk", {}).get("max_leverage", 1.0))
        return (self.total_exposure_usd / max(leverage, 1.0)) / self.equity

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def update_equity(self, new_equity: float) -> None:
        self.equity = new_equity
        self.daily.current_equity = new_equity
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity

    def update_position(self, position: Position) -> None:
        if position.quantity <= 0:
            self.positions.pop(position.symbol, None)
        else:
            self.positions[position.symbol] = position

    def add_fill(self, fill: Fill) -> None:
        self.recent_fills.append(fill)

    def record_trade_result(self, pnl: float, strategy_name: str) -> None:
        self.daily.trade_count += 1
        self.daily.realized_pnl += pnl
        if pnl > 0:
            self.daily.win_count += 1
            self.consecutive_losses[strategy_name] = 0
        else:
            self.consecutive_losses[strategy_name] = (
                self.consecutive_losses.get(strategy_name, 0) + 1
            )

    def add_signal(self, signal: Signal) -> None:
        if signal.symbol not in self.recent_signals:
            self.recent_signals[signal.symbol] = deque(maxlen=20)
        self.recent_signals[signal.symbol].append(signal)

    def set_regime(self, symbol: str, regime: MarketRegime) -> None:
        self.regimes[symbol] = regime

    def get_regime(self, symbol: str) -> MarketRegime:
        return self.regimes.get(symbol, MarketRegime.UNKNOWN)

    def activate_kill_switch(self, reason: str) -> None:
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    def set_cooldown(self, strategy_name: str, until: datetime) -> None:
        self.cooldown_until[strategy_name] = until
        logger.warning("Cooldown set for %s until %s", strategy_name, until)

    def is_in_cooldown(self, strategy_name: str) -> bool:
        until = self.cooldown_until.get(strategy_name)
        if until is None:
            return False
        return datetime.now(timezone.utc) < until.replace(tzinfo=timezone.utc) if until.tzinfo is None else datetime.now(timezone.utc) < until

    def reset_daily(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily = DailyStats(
            date=today,
            starting_equity=self.equity,
            current_equity=self.equity,
        )
        logger.info("Daily stats reset for %s, equity=%.2f", today, self.equity)
