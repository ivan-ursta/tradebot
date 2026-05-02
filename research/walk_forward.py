"""
research/walk_forward.py
========================
Rolling walk-forward validation.

For N windows, each window covers (train_bars + test_bars) of data.
Windows step forward by test_bars (non-overlapping OOS).

Returns per-window metrics and a combined OOS BacktestResult.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from research.engine import BacktestResult, TradeRecord, run_backtest
from research.metrics import ResearchMetrics, compute

logger = logging.getLogger(__name__)

SignalFn = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass
class WFWindow:
    window_num: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    is_metrics: ResearchMetrics
    oos_metrics: ResearchMetrics


@dataclass
class WalkForwardResult:
    symbol: str = ""
    strategy: str = ""
    windows: list[WFWindow] = field(default_factory=list)
    combined_oos: ResearchMetrics = field(default_factory=ResearchMetrics)

    def summary(self) -> str:
        lines = [
            f"\nWalk-Forward: {self.strategy} / {self.symbol}",
            f"{'Win':>4}  {'IS Ret%':>8}  {'OOS Ret%':>9}  {'OOS Sharpe':>10}  "
            f"{'OOS PF':>7}  {'OOS DD%':>8}  {'Trades':>6}",
            "-" * 65,
        ]
        for w in self.windows:
            is_r = f"{w.is_metrics.total_return_pct:+.2f}%"
            oos_r = f"{w.oos_metrics.total_return_pct:+.2f}%"
            lines.append(
                f"{w.window_num:>4}  {is_r:>8}  {oos_r:>9}  "
                f"{w.oos_metrics.sharpe:>10.2f}  "
                f"{w.oos_metrics.profit_factor:>7.2f}  "
                f"{w.oos_metrics.max_drawdown_pct:>7.2f}%  "
                f"{w.oos_metrics.trades:>6}"
            )
        lines.append("-" * 65)
        c = self.combined_oos
        lines.append(
            f"{'COMB':>4}  {'':>8}  "
            f"{c.total_return_pct:>+9.2f}%  "
            f"{c.sharpe:>10.2f}  "
            f"{c.profit_factor:>7.2f}  "
            f"{c.max_drawdown_pct:>7.2f}%  "
            f"{c.trades:>6}"
        )
        return "\n".join(lines)


def run_walk_forward(
    df: pd.DataFrame,
    signal_fn: SignalFn,
    symbol: str = "",
    strategy: str = "",
    n_windows: int = 5,
    train_frac: float = 0.6,
    timeframe: str = "1h",
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0004,
    slippage_bps: float = 5.0,
) -> WalkForwardResult:
    """
    Rolling walk-forward over `n_windows` windows.
    Each window = (train_bars + test_bars); windows step by test_bars.
    """
    n = len(df)
    # Total bars per window, tiled across dataset
    window_bars = n // n_windows
    train_bars = int(window_bars * train_frac)
    test_bars = window_bars - train_bars

    wf = WalkForwardResult(symbol=symbol, strategy=strategy)
    all_oos_trades: list[TradeRecord] = []
    all_oos_equity: list[pd.Series] = []

    for w in range(n_windows):
        train_start = w * test_bars
        train_end = train_start + train_bars
        test_end = train_end + test_bars

        if test_end > n:
            break

        train_df = df.iloc[train_start:train_end]
        test_df = df.iloc[train_end:test_end]

        # IS
        is_sigs = signal_fn(train_df)
        is_result = run_backtest(train_df, is_sigs, symbol, initial_capital, fee_rate, slippage_bps)
        is_m = compute(is_result, timeframe, symbol, strategy, f"IS-W{w+1}")

        # OOS
        oos_sigs = signal_fn(test_df)
        oos_result = run_backtest(test_df, oos_sigs, symbol, initial_capital, fee_rate, slippage_bps)
        oos_m = compute(oos_result, timeframe, symbol, strategy, f"OOS-W{w+1}")

        all_oos_trades.extend(oos_result.trades)
        all_oos_equity.append(oos_result.equity_curve)

        wf.windows.append(WFWindow(
            window_num=w + 1,
            train_start=train_df.index[0],
            train_end=train_df.index[-1],
            test_start=test_df.index[0],
            test_end=test_df.index[-1],
            is_metrics=is_m,
            oos_metrics=oos_m,
        ))

    # Build combined OOS result
    if all_oos_equity:
        # Chain equity curves: each starts at 1, multiply sequentially
        combined_eq = _chain_equity(all_oos_equity, initial_capital)
        combined_result = BacktestResult(
            symbol=symbol,
            trades=all_oos_trades,
            equity_curve=combined_eq,
            initial_capital=initial_capital,
        )
        wf.combined_oos = compute(combined_result, timeframe, symbol, strategy, "WF-OOS")

    return wf


def _chain_equity(curves: list[pd.Series], initial: float) -> pd.Series:
    """Chain equity curves so that each starts where the previous ended."""
    result_vals = []
    result_idx = []
    running = initial
    for curve in curves:
        if curve.empty:
            continue
        first = curve.iloc[0]
        scaled = curve / first * running
        result_vals.extend(scaled.tolist())
        result_idx.extend(curve.index.tolist())
        running = scaled.iloc[-1]
    if not result_vals:
        return pd.Series(dtype=float)
    return pd.Series(result_vals, index=result_idx, name="equity")
