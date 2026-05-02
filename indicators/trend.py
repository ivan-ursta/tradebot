"""
indicators/trend.py
===================
Trend indicators: EMA, SMA, slope, ADX, trend strength.
All functions accept and return pandas Series or DataFrames.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def dema(series: pd.Series, period: int) -> pd.Series:
    """Double EMA — reduces lag."""
    e = ema(series, period)
    return 2 * e - ema(e, period)


def trend_slope(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Linear regression slope over the last `period` bars.
    Positive = rising, negative = falling.
    Normalised by mean value to give a relative measure.
    """
    slopes = pd.Series(index=series.index, dtype=float)
    x = np.arange(period, dtype=float)
    for i in range(period - 1, len(series)):
        y = series.iloc[i - period + 1 : i + 1].values.astype(float)
        if np.isnan(y).any():
            continue
        m = np.polyfit(x, y, 1)[0]
        mean_val = np.mean(y)
        slopes.iloc[i] = m / mean_val if mean_val != 0 else 0.0
    return slopes


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """
    Average Directional Index.
    Returns DataFrame with columns: adx, plus_di, minus_di.
    """
    tr = true_range(high, low, close)

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_val = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_val.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_val.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(span=period, adjust=False).mean()

    return pd.DataFrame({"adx": adx_val, "plus_di": plus_di, "minus_di": minus_di})


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def donchian_channel(
    high: pd.Series, low: pd.Series, period: int = 20
) -> pd.DataFrame:
    """
    Donchian Channel: upper = highest high, lower = lowest low over period.
    Returns DataFrame with columns: upper, lower, mid.
    """
    upper = high.rolling(window=period).max()
    lower = low.rolling(window=period).min()
    mid = (upper + lower) / 2
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": mid})


def trend_strength(
    close: pd.Series,
    fast: int = 9,
    slow: int = 21,
) -> pd.Series:
    """
    Simple trend strength: (fast_ema - slow_ema) / slow_ema.
    Positive = bullish, negative = bearish, magnitude indicates strength.
    """
    fast_e = ema(close, fast)
    slow_e = ema(close, slow)
    return (fast_e - slow_e) / slow_e.replace(0, np.nan)
