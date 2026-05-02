"""
research/strategies/volatility_expansion.py
=============================================
Volatility Expansion — Bollinger Band squeeze breakout.

Logic:
  Compression : BB width < N-period lowest BB width  (bands squeezed)
  Expansion   : BB width crosses back above that level
  Entry       : first expansion bar where price closes above upper band
  Exit        : price closes back inside the bands (upper → mid)

Rationale: volatility is mean-reverting. After compression, expansions
tend to produce directional moves. No trend filter added at this stage.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

NAME = "VolatilityExpansion"

DEFAULT_PARAMS = dict(bb_period=20, bb_std=2.0, squeeze_lookback=20)


def generate_signals(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    squeeze_lookback: int = 20,
) -> pd.DataFrame:
    """
    Parameters
    ----------
    bb_period       : Bollinger Band period
    bb_std          : number of standard deviations for bands
    squeeze_lookback: period over which to measure 'lowest' BB width
    """
    c = df["close"]

    mid = c.rolling(bb_period).mean()
    std = c.rolling(bb_period).std(ddof=0)
    upper = mid + bb_std * std
    lower = mid - bb_std * std
    bb_width = (upper - lower) / mid  # normalised

    # Squeeze = current width < N-period lowest width (shifted to avoid look-ahead)
    min_width = bb_width.shift(1).rolling(squeeze_lookback).min()
    was_squeezed = bb_width.shift(1) <= min_width   # previous bar was at squeeze

    # Expansion breakout: price above upper band while expanding from squeeze
    entry = was_squeezed & (c > upper)

    # Exit: price drops back to midline
    exit_ = c < mid

    return pd.DataFrame({"entry": entry, "exit": exit_}, index=df.index)


def make_signal_fn(**kwargs) -> Callable[[pd.DataFrame], pd.DataFrame]:
    params = {**DEFAULT_PARAMS, **kwargs}
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        return generate_signals(df, **params)
    fn.__name__ = NAME
    return fn
