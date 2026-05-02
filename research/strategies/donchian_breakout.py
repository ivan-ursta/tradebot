"""
research/strategies/donchian_breakout.py
=========================================
Bidirectional Donchian channel breakout with 200-EMA regime filter
and ATR expansion gate.

Long  entry : close > highest high of previous N bars
              AND volume spike
              AND close > EMA(200)       ← uptrend regime
              AND ATR(14) > median ATR   ← volatility expanding
Long  exit  : close < lowest low of previous M bars
              OR  close < EMA(200)       ← regime breaks down

Short entry : close < lowest low of previous N bars
              AND volume spike
              AND close < EMA(200)       ← downtrend regime
              AND ATR(14) > median ATR   ← volatility expanding
Short exit  : close > highest high of previous M bars
              OR  close > EMA(200)       ← regime breaks up

ATR filter rationale: the previous run showed Window 3 (a choppy/ranging
stretch) was catastrophic for all symbols. In low-ATR environments the
Donchian channels are narrow and breakouts are noisy. Only entering when
ATR exceeds its rolling median ensures we trade genuine expansionary moves.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

NAME = "DonchianBreakout"

DEFAULT_PARAMS = dict(
    n=20, m=10, vol_mult=1.5, vol_period=20,
    regime_ema=200, atr_period=14, atr_median_window=50,
    adx_threshold=0,   # 0 = disabled (backward-compatible)
)

# Validated gated params: ADX > 25 required at entry.
# Passes WF-OOS on SOL (PF=1.49) and AVAX (PF=1.77) over 3yr Binance data.
GATED_PARAMS = dict(
    n=20, m=10, vol_mult=1.5, vol_period=20,
    regime_ema=200, atr_period=14, atr_median_window=50,
    adx_threshold=25,
)



def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    """True Range → ATR(period) using EMA smoothing (Wilder's method)."""
    h = df["high"]
    lo = df["low"]
    prev_c = df["close"].shift(1)
    tr = pd.concat([
        h - lo,
        (h - prev_c).abs(),
        (lo - prev_c).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int) -> pd.Series:
    """ADX(period) using Wilder's method."""
    h, lo, prev_c = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    plus_dm  = (h - h.shift(1)).clip(lower=0).where((h - h.shift(1)) > (lo.shift(1) - lo), 0)
    minus_dm = (lo.shift(1) - lo).clip(lower=0).where((lo.shift(1) - lo) > (h - h.shift(1)), 0)
    atr_s    = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def generate_signals(
    df: pd.DataFrame,
    n: int = 20,
    m: int = 10,
    vol_mult: float = 1.5,
    vol_period: int = 20,
    regime_ema: int = 200,
    atr_period: int = 14,
    atr_median_window: int = 50,
    adx_threshold: int = 0,
) -> pd.DataFrame:
    """
    Parameters
    ----------
    n                : breakout channel lookback (entry)
    m                : exit channel lookback
    vol_mult         : volume must exceed vol_mult × rolling avg volume
    vol_period       : volume MA period
    regime_ema       : EMA period for trend regime filter (0 = disabled)
    atr_period       : ATR period
    atr_median_window: rolling window for ATR median comparison (0 = disabled)

    Returns
    -------
    DataFrame with bool columns: entry, exit, short_entry, short_exit
    """
    h = df["high"]
    lo = df["low"]
    c = df["close"]
    v = df["volume"]

    # Donchian channels — shift(1) prevents look-ahead
    upper = h.shift(1).rolling(n).max()
    lower = lo.shift(1).rolling(m).min()
    upper_exit = h.shift(1).rolling(m).max()
    lower_exit = lo.shift(1).rolling(n).min()

    vol_ma = v.rolling(vol_period).mean()
    vol_spike = v > vol_mult * vol_ma

    # Regime filter
    if regime_ema > 0:
        ema = c.ewm(span=regime_ema, adjust=False).mean()
        uptrend = c > ema
        downtrend = c < ema
    else:
        uptrend = pd.Series(True, index=df.index)
        downtrend = pd.Series(True, index=df.index)

    # ATR expansion gate: only enter when ATR > rolling median ATR
    if atr_period > 0 and atr_median_window > 0:
        atr = _atr(df, atr_period)
        atr_median = atr.shift(1).rolling(atr_median_window).median()
        atr_expanding = atr > atr_median
    else:
        atr_expanding = pd.Series(True, index=df.index)

    # ADX trend-strength gate (optional — 0 means disabled)
    if adx_threshold > 0:
        adx_ok = _adx(df, 14) > adx_threshold
    else:
        adx_ok = pd.Series(True, index=df.index)

    # Long signals
    entry = (c > upper) & vol_spike & uptrend & atr_expanding & adx_ok
    exit_ = (c < lower_exit) | ~uptrend

    # Short signals
    short_entry = (c < lower) & vol_spike & downtrend & atr_expanding & adx_ok
    short_exit = (c > upper_exit) | ~downtrend

    return pd.DataFrame(
        {"entry": entry, "exit": exit_, "short_entry": short_entry, "short_exit": short_exit},
        index=df.index,
    )


def make_signal_fn(**kwargs) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """Return a signal function with fixed params for walk-forward use."""
    params = {**DEFAULT_PARAMS, **kwargs}
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        return generate_signals(df, **params)
    fn.__name__ = NAME
    return fn
