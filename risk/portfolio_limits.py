"""
risk/portfolio_limits.py
=========================
Portfolio-level risk checks: exposure, positions, daily loss.
"""

from __future__ import annotations

import logging
from typing import Tuple

from core.models import Signal
from core.state import TradingState

logger = logging.getLogger(__name__)


class PortfolioLimits:
    """
    Enforces portfolio-level constraints.
    All check methods return (allowed: bool, reason: str).
    """

    def __init__(self, config: dict) -> None:
        risk = config.get("risk", {})
        self.max_open_positions: int = risk.get("max_open_positions", 3)
        self.max_total_exposure: float = risk.get("max_total_exposure", 0.30)
        self.max_single_exposure: float = risk.get("max_single_market_exposure", 0.10)
        self.max_daily_loss: float = risk.get("max_daily_loss", 0.05)
        self.kill_switch_dd: float = risk.get("kill_switch_drawdown", 0.15)

    def check_entry(
        self, signal: Signal, state: TradingState
    ) -> Tuple[bool, str]:
        """
        Run all portfolio checks for a proposed entry.
        Returns (True, "") if allowed; (False, reason) if blocked.
        """
        # Kill switch
        if state.kill_switch_active:
            return False, f"Kill switch active: {state.kill_switch_reason}"

        # Max positions
        if state.open_position_count >= self.max_open_positions:
            return False, f"Max open positions reached ({self.max_open_positions})"

        # Already in position for this symbol
        if signal.symbol in state.positions:
            return False, f"Already in position for {signal.symbol}"

        # Daily loss limit
        daily_pnl_pct = state.daily.daily_pnl_pct
        if daily_pnl_pct <= -self.max_daily_loss:
            return False, f"Daily loss limit hit ({daily_pnl_pct:.2%} <= -{self.max_daily_loss:.2%})"

        # Drawdown kill switch
        dd = state.current_drawdown
        if dd >= self.kill_switch_dd:
            state.activate_kill_switch(f"Drawdown {dd:.2%} >= threshold {self.kill_switch_dd:.2%}")
            return False, f"Kill switch triggered by drawdown {dd:.2%}"

        # Total exposure
        if state.total_exposure_fraction >= self.max_total_exposure:
            return False, f"Total exposure {state.total_exposure_fraction:.2%} >= max {self.max_total_exposure:.2%}"

        # Single market exposure check (after position is opened, would we exceed?)
        if signal.entry_price and state.equity > 0:
            approx_notional = signal.entry_price * 1  # quantity TBD; just check direction
            # This is approximate — actual check happens after sizing
            pass

        return True, ""

    def check_exposure_post_size(
        self,
        symbol: str,
        notional: float,
        state: TradingState,
    ) -> Tuple[bool, str]:
        """Check after position sizing whether exposure limits are respected."""
        equity = state.equity
        if equity <= 0:
            return False, "Zero equity"
        single_frac = notional / equity
        if single_frac > self.max_single_exposure:
            return False, f"Single market exposure {single_frac:.2%} > max {self.max_single_exposure:.2%}"
        projected_total = state.total_exposure_fraction + single_frac
        if projected_total > self.max_total_exposure:
            return False, f"Projected total exposure {projected_total:.2%} > max {self.max_total_exposure:.2%}"
        return True, ""
