"""
execution/fee_model.py
======================
Fee models for backtesting and paper trading.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeeSchedule:
    """
    Represents a tiered fee schedule.
    Hyperliquid default: 0.02% maker / 0.04% taker (in bps).
    """
    maker_rate: float = 0.0002  # 2 bps
    taker_rate: float = 0.0004  # 4 bps

    def compute_fee(self, notional: float, is_taker: bool = True) -> float:
        rate = self.taker_rate if is_taker else self.maker_rate
        return notional * rate


HYPERLIQUID_DEFAULT = FeeSchedule(maker_rate=0.0002, taker_rate=0.0004)


def compute_round_trip_cost(
    entry_price: float,
    exit_price: float,
    quantity: float,
    fee_schedule: FeeSchedule = HYPERLIQUID_DEFAULT,
    entry_taker: bool = True,
    exit_taker: bool = True,
) -> float:
    """Total fees for a round-trip trade."""
    entry_fee = fee_schedule.compute_fee(entry_price * quantity, entry_taker)
    exit_fee = fee_schedule.compute_fee(exit_price * quantity, exit_taker)
    return entry_fee + exit_fee
