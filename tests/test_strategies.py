"""
tests/test_strategies.py
========================
Unit tests for strategy signal generation.
Uses synthetic OHLCV data so no exchange connection is needed.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from core.models import MarketRegime, SignalDirection
from core.state import TradingState
from strategies.momentum_breakout import MomentumBreakout
from strategies.mean_reversion import MeanReversion
from strategies.funding_filter_momentum import FundingFilterMomentum


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONFIG = {
    "momentum_breakout": {
        "donchian_period": 10,
        "volume_ma_period": 10,
        "volume_spike_mult": 1.5,
        "atr_period": 10,
        "atr_filter_mult": 1.0,
        "trend_ema_fast": 5,
        "trend_ema_slow": 10,
        "trend_ema_confirm": True,
    },
    "mean_reversion": {
        "bb_period": 10,
        "bb_std": 2.0,
        "rsi_period": 10,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "max_vol_for_reversion": 0.5,
        "max_adx_for_reversion": 50,
    },
    "funding_filter_momentum": {
        "funding_threshold_pct": 0.01,
        "momentum_ema_fast": 5,
        "momentum_ema_slow": 10,
        "rsi_period": 10,
        "rsi_entry_long": 40,
        "rsi_entry_short": 60,
    },
    "risk": {
        "stop_loss_atr_mult": 2.0,
        "take_profit_atr_mult": 3.0,
        "max_risk_per_trade": 0.01,
    },
}


def make_trending_df(n: int = 150, trend_up: bool = True) -> pd.DataFrame:
    """Generate synthetic trending OHLCV data."""
    np.random.seed(42)
    timestamps = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    base = 50_000.0
    if trend_up:
        prices = base + np.cumsum(np.random.normal(10, 50, n))
    else:
        prices = base - np.cumsum(np.random.normal(10, 50, n))

    df = pd.DataFrame(
        {
            "open": prices - np.abs(np.random.normal(0, 20, n)),
            "high": prices + np.abs(np.random.normal(0, 80, n)),
            "low": prices - np.abs(np.random.normal(0, 80, n)),
            "close": prices,
            "volume": np.random.uniform(100, 500, n),
        },
        index=pd.DatetimeIndex(timestamps),
    )
    df["high"] = df[["open", "close", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "low"]].min(axis=1)
    return df


def make_ranging_df(n: int = 150) -> pd.DataFrame:
    """Generate synthetic range-bound OHLCV data."""
    np.random.seed(123)
    timestamps = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    base = 50_000.0
    prices = base + np.random.normal(0, 100, n)
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + np.abs(np.random.normal(0, 50, n)),
            "low": prices - np.abs(np.random.normal(0, 50, n)),
            "close": prices,
            "volume": np.random.uniform(100, 300, n),
        },
        index=pd.DatetimeIndex(timestamps),
    )
    df["high"] = df[["open", "close", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "low"]].min(axis=1)
    return df


# ---------------------------------------------------------------------------
# MomentumBreakout tests
# ---------------------------------------------------------------------------


class TestMomentumBreakout:
    def setup_method(self):
        self.strategy = MomentumBreakout(CONFIG)
        self.state = TradingState(10_000)
        self.state.config_ref = CONFIG

    def test_prepare_features_returns_dataframe(self):
        df = make_trending_df()
        result = self.strategy.prepare_features(df)
        assert result is not None
        assert "dc_upper" in result.columns
        assert "ema_fast" in result.columns
        assert "atr" in result.columns
        assert "vol_spike" in result.columns

    def test_prepare_features_insufficient_data(self):
        df = make_trending_df(5)  # too few rows
        result = self.strategy.prepare_features(df)
        assert result is None

    def test_generate_signal_returns_signal(self):
        df = make_trending_df()
        featured = self.strategy.prepare_features(df)
        signal = self.strategy.generate_signal(featured, self.state)
        assert signal is not None
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT, SignalDirection.FLAT)

    def test_generate_signal_has_stop_loss_when_long(self):
        """Any long signal must have a stop loss set."""
        df = make_trending_df(n=200)
        featured = self.strategy.prepare_features(df)
        for i in range(len(featured) - 10, len(featured)):
            sub = featured.iloc[:i]
            if len(sub) < self.strategy._min_rows:
                continue
            signal = self.strategy.generate_signal(sub, self.state)
            if signal and signal.direction == SignalDirection.LONG:
                assert signal.stop_loss is not None
                assert signal.stop_loss < signal.entry_price
                break

    def test_no_entry_in_high_vol_regime(self):
        """Strategy should return FLAT when vol_regime is high."""
        df = make_trending_df()
        featured = self.strategy.prepare_features(df)
        if featured is not None:
            # Force high vol regime on last row
            featured = featured.copy()
            featured.iloc[-1, featured.columns.get_loc("vol_regime")] = "high"
            signal = self.strategy.generate_signal(featured, self.state)
            assert signal.direction == SignalDirection.FLAT


# ---------------------------------------------------------------------------
# MeanReversion tests
# ---------------------------------------------------------------------------


class TestMeanReversion:
    def setup_method(self):
        self.strategy = MeanReversion(CONFIG)
        self.state = TradingState(10_000)

    def test_prepare_features(self):
        df = make_ranging_df()
        result = self.strategy.prepare_features(df)
        assert result is not None
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns
        assert "rsi" in result.columns
        assert "adx" in result.columns

    def test_high_adx_disables_strategy(self):
        """Mean reversion should return FLAT when ADX is too high."""
        df = make_ranging_df()
        featured = self.strategy.prepare_features(df)
        if featured is not None:
            featured = featured.copy()
            featured.iloc[-1, featured.columns.get_loc("adx")] = 60.0  # strong trend
            signal = self.strategy.generate_signal(featured, self.state)
            assert signal.direction == SignalDirection.FLAT

    def test_signal_direction_sensible(self):
        df = make_ranging_df()
        featured = self.strategy.prepare_features(df)
        if featured is not None:
            signal = self.strategy.generate_signal(featured, self.state)
            assert signal is not None


# ---------------------------------------------------------------------------
# FundingFilterMomentum tests
# ---------------------------------------------------------------------------


class TestFundingFilterMomentum:
    def setup_method(self):
        self.strategy = FundingFilterMomentum(CONFIG)
        self.state = TradingState(10_000)

    def test_prepare_features_adds_funding(self):
        df = make_trending_df()
        result = self.strategy.prepare_features(df)
        assert result is not None
        assert "funding_rate" in result.columns
        assert "ema_fast" in result.columns
        assert "rsi" in result.columns

    def test_high_positive_funding_blocks_long(self):
        """Extreme positive funding should filter out long signals."""
        df = make_trending_df()
        featured = self.strategy.prepare_features(df)
        if featured is not None:
            featured = featured.copy()
            # Force a bullish EMA cross at last 2 bars
            featured.iloc[-2, featured.columns.get_loc("ema_fast")] = 100
            featured.iloc[-2, featured.columns.get_loc("ema_slow")] = 200
            featured.iloc[-1, featured.columns.get_loc("ema_fast")] = 210
            featured.iloc[-1, featured.columns.get_loc("ema_slow")] = 200
            # But extreme positive funding
            featured.iloc[-1, featured.columns.get_loc("funding_rate")] = 0.05
            signal = self.strategy.generate_signal(featured, self.state)
            # Should NOT generate a long signal
            assert signal.direction != SignalDirection.LONG
