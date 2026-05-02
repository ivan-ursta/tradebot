"""
indicators/volatility.py
========================
Volatility indicators: ATR, Bollinger Bands, realized vol, regime.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from indicators.trend import true_range


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    tr = true_range(high, low, close)
    return tr.ewm(com=period - 1, adjust=False).mean()


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_mult: float = 2.0,
) -> pd.DataFrame:
    """
    Bollinger Bands.
    Returns DataFrame with columns: upper, mid, lower, bandwidth, %b.
    """
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {"upper": upper, "mid": mid, "lower": lower, "bandwidth": bandwidth, "pct_b": pct_b}
    )


def realized_volatility(
    close: pd.Series, period: int = 20, annualize: bool = True
) -> pd.Series:
    """
    Realized (historical) volatility from log returns.
    Returns annualised fraction if annualize=True (assuming ~252 bars/year
    for daily; caller should adjust if using intraday bars).
    """
    log_ret = np.log(close / close.shift(1))
    rv = log_ret.rolling(window=period).std(ddof=1)
    if annualize:
        rv = rv * np.sqrt(252)
    return rv


def range_expansion(
    high: pd.Series,
    low: pd.Series,
    period: int = 10,
) -> pd.Series:
    """
    Ratio of current bar range to N-period average range.
    > 1.5 suggests expansion; < 0.5 suggests compression.
    """
    bar_range = high - low
    avg_range = bar_range.rolling(window=period).mean()
    return bar_range / avg_range.replace(0, np.nan)


def volatility_regime(
    close: pd.Series,
    period: int = 20,
    low_pct: float = 0.33,
    high_pct: float = 0.67,
) -> pd.Series:
    """
    Classify realized vol into LOW / MEDIUM / HIGH regime.
    Returns a Series of strings: 'low', 'medium', 'high'.
    Uses rolling percentile of the last 252 bars to set thresholds.
    """
    rv = realized_volatility(close, period, annualize=True)
    # Use 252-bar rolling quantiles as dynamic thresholds
    q_low = rv.rolling(window=252, min_periods=period).quantile(low_pct)
    q_high = rv.rolling(window=252, min_periods=period).quantile(high_pct)

    regime = pd.Series("medium", index=close.index, dtype=str)
    regime[rv <= q_low] = "low"
    regime[rv >= q_high] = "high"
    return regime


def keltner_channels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    ema_period: int = 20,
    atr_period: int = 14,
    atr_mult: float = 2.0,
) -> pd.DataFrame:
    """
    Keltner Channels.
    Returns DataFrame with columns: upper, mid, lower.
    """
    mid = close.ewm(span=ema_period, adjust=False).mean()
    atr_val = atr(high, low, close, atr_period)
    upper = mid + atr_mult * atr_val
    lower = mid - atr_mult * atr_val
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower})
