"""
indicators/momentum.py
======================
Momentum indicators: RSI, MACD, ROC, breakout strength.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (Wilder smoothing).
    Returns values 0–100.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    MACD indicator.
    Returns DataFrame with columns: macd, signal, histogram.
    """
    fast_ema = close.ewm(span=fast, adjust=False).mean()
    slow_ema = close.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def rate_of_change(close: pd.Series, period: int = 10) -> pd.Series:
    """
    Rate of change: (close - close[n]) / close[n].
    Returns fractional change.
    """
    past = close.shift(period)
    return (close - past) / past.replace(0, np.nan)


def breakout_strength(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    period: int = 20,
) -> pd.Series:
    """
    Breakout strength: normalised distance of close from N-period Donchian midpoint.
    Value > 0 → close above midpoint, < 0 → below.
    Magnitude indicates how far into breakout territory we are.
    """
    rolling_high = high.rolling(window=period).max()
    rolling_low = low.rolling(window=period).min()
    mid = (rolling_high + rolling_low) / 2
    half_range = (rolling_high - rolling_low) / 2
    return (close - mid) / half_range.replace(0, np.nan)


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    """
    Stochastic Oscillator.
    Returns DataFrame with columns: k, d.
    """
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(window=d_period).mean()
    return pd.DataFrame({"k": k, "d": d})


def momentum(close: pd.Series, period: int = 10) -> pd.Series:
    """Raw price momentum: close - close[n]."""
    return close - close.shift(period)
