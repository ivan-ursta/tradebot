"""
research/strategies/momentum_continuation.py
=============================================
Momentum Continuation — trade in the direction of the established trend.

Logic:
  Trend filter : close > slow EMA  (higher-timeframe proxy)
  Entry trigger: fast EMA crosses above mid EMA while above slow EMA
                 (pullback reentry into trend)
  Exit         : fast EMA crosses below mid EMA  OR  close < slow EMA

Rationale: trend-following without breakout false positives.
Uses only EMAs — no oscillators — to keep signal clean.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

NAME = "MomentumContinuation"

DEFAULT_PARAMS = dict(fast=9, mid=21, slow=50)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def generate_signals(
    df: pd.DataFrame,
    fast: int = 9,
    mid: int = 21,
    slow: int = 50,
) -> pd.DataFrame:
    """
    Parameters
    ----------
    fast  : fast EMA period
    mid   : mid EMA period  (trend confirmation)
    slow  : slow EMA period (regime filter)
    """
    c = df["close"]

    ema_fast = _ema(c, fast)
    ema_mid = _ema(c, mid)
    ema_slow = _ema(c, slow)

    above_slow = c > ema_slow

    # Cross-up: fast crosses above mid
    cross_up = (ema_fast > ema_mid) & (ema_fast.shift(1) <= ema_mid.shift(1))
    # Cross-down: fast crosses below mid
    cross_down = (ema_fast < ema_mid) & (ema_fast.shift(1) >= ema_mid.shift(1))

    entry = cross_up & above_slow
    exit_ = cross_down | (c < ema_slow)

    return pd.DataFrame({"entry": entry, "exit": exit_}, index=df.index)


def make_signal_fn(**kwargs) -> Callable[[pd.DataFrame], pd.DataFrame]:
    params = {**DEFAULT_PARAMS, **kwargs}
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        return generate_signals(df, **params)
    fn.__name__ = NAME
    return fn
