"""
indicators/volume.py
====================
Volume indicators: rolling volume, spikes, relative volume, OBV.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Rolling average volume over N bars."""
    return volume.rolling(window=period).mean()


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    Current volume relative to rolling average.
    > 1.0 means above average; > 2.0 is a spike.
    """
    avg = rolling_volume(volume, period)
    return volume / avg.replace(0, np.nan)


def volume_spike(
    volume: pd.Series,
    period: int = 20,
    threshold: float = 1.5,
) -> pd.Series:
    """Boolean mask: True when volume > threshold * rolling_avg."""
    rel = relative_volume(volume, period)
    return rel >= threshold


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    On-Balance Volume.
    Cumulative volume directional flow.
    """
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def volume_weighted_price(
    close: pd.Series,
    volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    """Rolling VWAP approximation over a window."""
    pv = close * volume
    return pv.rolling(window=period).sum() / volume.rolling(window=period).sum().replace(0, np.nan)


def money_flow_index(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Money Flow Index (volume-weighted RSI).
    Returns 0–100 values.
    """
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    delta = typical_price.diff()

    pos_mf = money_flow.where(delta > 0, 0.0)
    neg_mf = money_flow.where(delta < 0, 0.0)

    pos_sum = pos_mf.rolling(window=period).sum()
    neg_sum = neg_mf.rolling(window=period).sum().replace(0, np.nan)

    mf_ratio = pos_sum / neg_sum
    return 100 - (100 / (1 + mf_ratio))
