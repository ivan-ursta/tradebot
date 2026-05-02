"""
risk/kill_switch.py
====================
Kill switch and cooldown logic.
Activated on: max drawdown, daily loss limit, N consecutive losses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple

from core.events import EventType, bus
from core.state import TradingState

logger = logging.getLogger(__name__)


class KillSwitch:
    """
    Monitors trading session health and activates protective stops.
    """

    def __init__(self, config: dict) -> None:
        risk = config.get("risk", {})
        self.max_daily_loss: float = risk.get("max_daily_loss", 0.05)
        self.kill_switch_dd: float = risk.get("kill_switch_drawdown", 0.15)
        self.cooldown_after_losses: int = risk.get("cooldown_after_losses", 3)
        self.cooldown_duration: int = risk.get("cooldown_duration_seconds", 3600)

    def evaluate(self, state: TradingState) -> Tuple[bool, str]:
        """
        Evaluate whether kill switch should fire.
        Also triggers per-strategy cooldowns.
        Returns (kill_switch_active, reason).
        """
        if state.kill_switch_active:
            return True, state.kill_switch_reason

        # Drawdown check
        dd = state.current_drawdown
        if dd >= self.kill_switch_dd:
            reason = f"Peak drawdown {dd:.2%} reached kill-switch threshold {self.kill_switch_dd:.2%}"
            state.activate_kill_switch(reason)
            bus.emit(EventType.KILL_SWITCH_ACTIVATED, source="kill_switch", payload=reason)
            return True, reason

        # Daily loss check
        if state.daily.daily_pnl_pct <= -self.max_daily_loss:
            reason = f"Daily loss {state.daily.daily_pnl_pct:.2%} exceeded limit -{self.max_daily_loss:.2%}"
            state.activate_kill_switch(reason)
            bus.emit(EventType.KILL_SWITCH_ACTIVATED, source="kill_switch", payload=reason)
            return True, reason

        return False, ""

    def check_strategy_cooldown(self, strategy_name: str, state: TradingState) -> None:
        """
        After each trade result, check if strategy needs cooldown.
        """
        losses = state.consecutive_losses.get(strategy_name, 0)
        if losses >= self.cooldown_after_losses:
            until = datetime.now(timezone.utc) + timedelta(seconds=self.cooldown_duration)
            state.set_cooldown(strategy_name, until)
            logger.warning(
                "Strategy %s cooling down for %ds after %d consecutive losses",
                strategy_name, self.cooldown_duration, losses,
            )


class RiskManager:
    """
    Aggregate risk manager that combines portfolio limits and kill switch.
    The engine calls check_entry() before every order.
    """

    def __init__(self, config: dict, portfolio_limits, kill_switch: KillSwitch) -> None:
        self.portfolio_limits = portfolio_limits
        self.kill_switch = kill_switch
        self.config = config
        risk = config.get("risk", {})
        self.max_signal_age: int = risk.get("max_signal_age_seconds", 60)

    def check_entry(self, signal, state: TradingState) -> Tuple[bool, str]:
        """Full pre-entry risk gate."""
        # 1. Kill switch
        ks_active, ks_reason = self.kill_switch.evaluate(state)
        if ks_active:
            return False, ks_reason

        # 2. Signal age (stale signal rejection)
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - signal.timestamp.replace(tzinfo=timezone.utc)
               if signal.timestamp.tzinfo is None else
               datetime.now(timezone.utc) - signal.timestamp).total_seconds()
        if age > self.max_signal_age:
            return False, f"Signal stale: {age:.0f}s > {self.max_signal_age}s"

        # 3. Portfolio limits
        allowed, reason = self.portfolio_limits.check_entry(signal, state)
        if not allowed:
            return False, reason

        return True, ""

    def on_trade_result(self, strategy_name: str, pnl: float, state: TradingState) -> None:
        state.record_trade_result(pnl, strategy_name)
        self.kill_switch.check_strategy_cooldown(strategy_name, state)
        self.kill_switch.evaluate(state)
