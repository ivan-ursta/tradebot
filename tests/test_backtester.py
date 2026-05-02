"""
tests/test_backtester.py
========================
Integration tests for the backtesting engine and metrics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backtesting.backtester import Backtester
from backtesting.metrics import compute_metrics, overfitting_warning, BacktestMetrics
from execution.fee_model import HYPERLIQUID_DEFAULT
from strategies.momentum_breakout import MomentumBreakout
from strategies.mean_reversion import MeanReversion


CONFIG = {
    "momentum_breakout": {
        "donchian_period": 10,
        "volume_ma_period": 10,
        "volume_spike_mult": 1.3,
        "atr_period": 10,
        "atr_filter_mult": 0.5,
        "trend_ema_fast": 5,
        "trend_ema_slow": 10,
        "trend_ema_confirm": False,  # disable for more signals in test
    },
    "mean_reversion": {
        "bb_period": 10,
        "bb_std": 2.0,
        "rsi_period": 10,
        "rsi_oversold": 35,
        "rsi_overbought": 65,
        "max_vol_for_reversion": 0.5,
        "max_adx_for_reversion": 50,
    },
    "risk": {
        "stop_loss_atr_mult": 2.0,
        "take_profit_atr_mult": 3.0,
        "max_risk_per_trade": 0.01,
        "max_leverage": 5,
        "min_order_size_usd": 5.0,
        "max_signal_age_seconds": 3600,
    },
    "backtesting": {
        "fee_rate": 0.0004,
        "slippage_bps": 5,
        "initial_capital": 10_000,
        "min_trades_for_validity": 5,
    },
}


def make_df(n: int = 500, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    timestamps = [datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)]
    prices = 50_000 + np.cumsum(np.random.normal(0, 100, n))
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + np.abs(np.random.normal(0, 150, n)),
            "low": prices - np.abs(np.random.normal(0, 150, n)),
            "close": prices + np.random.normal(0, 50, n),
            "volume": np.random.uniform(100, 1000, n),
        },
        index=pd.DatetimeIndex(timestamps),
    )
    df["high"] = df[["open", "close", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "low"]].min(axis=1)
    return df


class TestBacktester:
    def test_runs_without_error(self):
        df = make_df()
        strategy = MomentumBreakout(CONFIG)
        bt = Backtester(CONFIG, strategy, fee_schedule=HYPERLIQUID_DEFAULT, initial_capital=10_000)
        result = bt.run(df, "BTC")
        assert result is not None
        assert result.equity_curve is not None
        assert len(result.equity_curve) > 0

    def test_equity_curve_same_length_as_input(self):
        df = make_df(300)
        strategy = MomentumBreakout(CONFIG)
        bt = Backtester(CONFIG, strategy, fee_schedule=HYPERLIQUID_DEFAULT, initial_capital=10_000)
        result = bt.run(df, "BTC")
        assert len(result.equity_curve) == len(df)

    def test_equity_starts_near_initial_capital(self):
        df = make_df(300)
        strategy = MomentumBreakout(CONFIG)
        bt = Backtester(CONFIG, strategy, fee_schedule=HYPERLIQUID_DEFAULT, initial_capital=10_000)
        result = bt.run(df, "BTC")
        # First bar equity should equal initial capital (no trades yet)
        assert abs(float(result.equity_curve.iloc[0]) - 10_000) < 100

    def test_metrics_computed(self):
        df = make_df()
        strategy = MomentumBreakout(CONFIG)
        bt = Backtester(CONFIG, strategy, fee_schedule=HYPERLIQUID_DEFAULT, initial_capital=10_000)
        result = bt.run(df, "BTC")
        m = result.metrics
        assert m is not None
        assert isinstance(m.sharpe_ratio, float)
        assert isinstance(m.max_drawdown_pct, float)

    def test_fees_reduce_returns(self):
        """Backtest with high fees should produce lower returns than zero fees."""
        df = make_df(seed=99)
        strategy = MomentumBreakout(CONFIG)

        from execution.fee_model import FeeSchedule
        no_fee = FeeSchedule(maker_rate=0, taker_rate=0)
        high_fee = FeeSchedule(maker_rate=0.002, taker_rate=0.004)

        bt_no = Backtester(CONFIG, strategy, fee_schedule=no_fee, initial_capital=10_000)
        bt_hi = Backtester(CONFIG, MomentumBreakout(CONFIG), fee_schedule=high_fee, initial_capital=10_000)

        r_no = bt_no.run(df, "BTC")
        r_hi = bt_hi.run(df, "BTC")

        ret_no = float(r_no.equity_curve.iloc[-1])
        ret_hi = float(r_hi.equity_curve.iloc[-1])
        assert ret_no >= ret_hi  # zero fees ≥ high fees


class TestMetrics:
    def _make_equity(self, initial: float = 10_000, returns: list = None) -> pd.Series:
        if returns is None:
            returns = [0.01, -0.005, 0.02, -0.01, 0.015] * 50
        equity = [initial]
        for r in returns:
            equity.append(equity[-1] * (1 + r))
        idx = pd.date_range("2024-01-01", periods=len(equity), freq="D")
        return pd.Series(equity, index=idx)

    def test_sharpe_positive_for_profitable_strategy(self):
        # Use realistic returns with variance so std > 0
        import random
        random.seed(7)
        returns = [random.gauss(0.003, 0.01) for _ in range(200)]
        equity = self._make_equity(returns=returns)
        m = compute_metrics(equity, [0.3] * 30, initial_capital=10_000, min_trades=5)
        assert m.sharpe_ratio > 0

    def test_max_drawdown_positive(self):
        # Equity goes up then drops
        returns = [0.01] * 100 + [-0.02] * 30 + [0.01] * 50
        equity = self._make_equity(returns=returns)
        m = compute_metrics(equity, [], initial_capital=10_000, min_trades=0)
        assert m.max_drawdown_pct > 0

    def test_overfitting_detection(self):
        is_metrics = BacktestMetrics(sharpe_ratio=3.0, win_rate_pct=70, max_drawdown_pct=5)
        oos_metrics = BacktestMetrics(sharpe_ratio=0.5, win_rate_pct=45, max_drawdown_pct=20)
        warnings = overfitting_warning(is_metrics, oos_metrics)
        assert any("Sharpe" in w for w in warnings)

    def test_validity_flag_low_trades(self):
        equity = self._make_equity()
        m = compute_metrics(equity, [0.01] * 5, initial_capital=10_000, min_trades=30)
        assert not m.is_valid
        assert "5 trades" in m.validity_note
