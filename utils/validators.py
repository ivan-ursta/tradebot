"""
utils/validators.py
===================
Input validation helpers for config, orders, and market data.
"""

from __future__ import annotations

from typing import Any, Dict, List


def validate_config(config: dict) -> List[str]:
    """
    Validate critical config fields.
    Returns a list of error messages (empty = valid).
    """
    errors = []

    mode = config.get("trading", {}).get("mode", "")
    if mode not in ("paper", "live"):
        errors.append(f"trading.mode must be 'paper' or 'live', got '{mode}'")

    risk = config.get("risk", {})
    rpt = risk.get("max_risk_per_trade", 0)
    if not (0 < rpt <= 0.05):
        errors.append(f"risk.max_risk_per_trade should be between 0 and 0.05, got {rpt}")

    max_lev = risk.get("max_leverage", 1)
    if max_lev > 20:
        errors.append(f"risk.max_leverage={max_lev} is dangerously high")

    active = config.get("strategy", {}).get("active", [])
    if not active:
        errors.append("strategy.active must contain at least one strategy name")

    return errors


def validate_ohlcv(df) -> bool:
    """Return True if DataFrame has required OHLCV columns with no NaNs in last row."""
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(df.columns)):
        return False
    last = df.iloc[-1]
    return not last[list(required)].isna().any()


def validate_order(symbol: str, quantity: float, price: float | None, min_size: float) -> str:
    """
    Validate order parameters. Returns error message or empty string.
    """
    if not symbol:
        return "Symbol is empty"
    if quantity <= 0:
        return f"Quantity must be positive, got {quantity}"
    if quantity * (price or 1) < min_size:
        return f"Order notional below minimum {min_size}"
    if price is not None and price <= 0:
        return f"Price must be positive, got {price}"
    return ""
