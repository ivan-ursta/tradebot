"""
execution/slippage.py
=====================
Slippage models for backtesting realism.
"""

from __future__ import annotations

from enum import Enum


class SlippageModel(str, Enum):
    FIXED_BPS = "fixed_bps"
    VOLUME_SCALED = "volume_scaled"
    ZERO = "zero"


def apply_slippage(
    price: float,
    is_buy: bool,
    model: SlippageModel = SlippageModel.FIXED_BPS,
    bps: float = 5,
    order_size_usd: float = 0,
    bar_volume_usd: float = 0,
) -> float:
    """
    Apply slippage to an execution price.

    Args:
        price: Pre-slippage price
        is_buy: True for buy orders, False for sells
        model: Which slippage model to use
        bps: Fixed basis points for FIXED_BPS model
        order_size_usd: Order size for VOLUME_SCALED model
        bar_volume_usd: Bar volume for VOLUME_SCALED model

    Returns:
        Adjusted fill price.
    """
    if model == SlippageModel.ZERO:
        return price

    if model == SlippageModel.FIXED_BPS:
        slippage_pct = bps / 10_000
        return price * (1 + slippage_pct) if is_buy else price * (1 - slippage_pct)

    if model == SlippageModel.VOLUME_SCALED:
        # Square-root market impact model: impact ∝ sqrt(order_size / bar_volume)
        if bar_volume_usd <= 0 or order_size_usd <= 0:
            return apply_slippage(price, is_buy, SlippageModel.FIXED_BPS, bps)
        participation = order_size_usd / bar_volume_usd
        impact_bps = bps * (participation ** 0.5) * 100  # scale
        slippage_pct = impact_bps / 10_000
        return price * (1 + slippage_pct) if is_buy else price * (1 - slippage_pct)

    return price
