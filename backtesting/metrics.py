"""
backtesting/metrics.py
======================
Risk-adjusted performance metrics for strategy evaluation.
Computed from equity curve or trade list.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    """All performance metrics for a single backtest run."""

    # Returns
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0

    # Risk-adjusted
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Drawdown
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_bars: int = 0

    # Trade stats
    total_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    expectancy: float = 0.0

    # Exposure
    exposure_time_pct: float = 0.0

    # Validity flag
    is_valid: bool = True
    validity_note: str = ""

    def summary(self) -> str:
        return (
            f"Return={self.total_return_pct:.2f}% | "
            f"Sharpe={self.sharpe_ratio:.2f} | "
            f"Sortino={self.sortino_ratio:.2f} | "
            f"MaxDD={self.max_drawdown_pct:.2f}% | "
            f"Calmar={self.calmar_ratio:.2f} | "
            f"WinRate={self.win_rate_pct:.1f}% | "
            f"PF={self.profit_factor:.2f} | "
            f"Trades={self.total_trades}"
        )


def compute_metrics(
    equity_curve: pd.Series,
    trade_returns: List[float],
    initial_capital: float = 10_000.0,
    periods_per_year: int = 252,
    min_trades: int = 30,
) -> BacktestMetrics:
    """
    Compute all metrics from an equity curve and list of per-trade returns (%).

    Args:
        equity_curve: DatetimeIndex Series of portfolio equity values
        trade_returns: List of per-trade return percentages
        initial_capital: Starting capital
        periods_per_year: Used for annualisation (252 for daily, 8760 for hourly, etc.)
        min_trades: Below this count, flag results as potentially unreliable

    Returns:
        BacktestMetrics
    """
    m = BacktestMetrics()

    if len(equity_curve) < 2:
        m.is_valid = False
        m.validity_note = "Equity curve too short"
        return m

    # ---- Returns ----
    final_equity = float(equity_curve.iloc[-1])
    m.total_return_pct = (final_equity - initial_capital) / initial_capital * 100

    n_bars = len(equity_curve)
    years = n_bars / periods_per_year
    if years > 0 and final_equity > 0:
        m.cagr_pct = ((final_equity / initial_capital) ** (1 / years) - 1) * 100

    # ---- Daily returns for ratio calcs ----
    returns = equity_curve.pct_change().dropna()

    if len(returns) < 2:
        m.is_valid = False
        return m

    mean_ret = returns.mean()
    std_ret = returns.std(ddof=1)
    downside_std = returns[returns < 0].std(ddof=1)

    rf_daily = 0.0  # risk-free rate per bar (simplified to 0)

    if std_ret > 0:
        m.sharpe_ratio = (mean_ret - rf_daily) / std_ret * math.sqrt(periods_per_year)

    if downside_std > 0:
        m.sortino_ratio = (mean_ret - rf_daily) / downside_std * math.sqrt(periods_per_year)

    # ---- Drawdown ----
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    m.max_drawdown_pct = abs(float(drawdown.min())) * 100

    # Drawdown duration
    is_in_dd = drawdown < 0
    max_dur = 0
    cur_dur = 0
    for v in is_in_dd:
        if v:
            cur_dur += 1
            max_dur = max(max_dur, cur_dur)
        else:
            cur_dur = 0
    m.max_drawdown_duration_bars = max_dur

    if m.max_drawdown_pct > 0 and m.cagr_pct > 0:
        m.calmar_ratio = m.cagr_pct / m.max_drawdown_pct

    # ---- Trade stats ----
    m.total_trades = len(trade_returns)
    if trade_returns:
        wins = [r for r in trade_returns if r > 0]
        losses = [r for r in trade_returns if r <= 0]
        m.win_rate_pct = len(wins) / len(trade_returns) * 100
        m.avg_trade_pct = float(np.mean(trade_returns))
        m.avg_win_pct = float(np.mean(wins)) if wins else 0.0
        m.avg_loss_pct = float(np.mean(losses)) if losses else 0.0

        gross_wins = sum(wins)
        gross_losses = abs(sum(losses))
        m.profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")
        m.expectancy = m.win_rate_pct / 100 * m.avg_win_pct + (1 - m.win_rate_pct / 100) * m.avg_loss_pct

    # ---- Validity ----
    if m.total_trades < min_trades:
        m.is_valid = False
        m.validity_note = f"Only {m.total_trades} trades (need {min_trades} for statistical significance)"

    if m.max_drawdown_pct > 50:
        m.validity_note += " | WARNING: Max drawdown > 50%"

    return m


def overfitting_warning(
    in_sample: BacktestMetrics,
    out_of_sample: BacktestMetrics,
) -> list[str]:
    """
    Checks for signs of overfitting by comparing in-sample vs out-of-sample metrics.
    Returns a list of warning messages.
    """
    warnings = []
    if in_sample.sharpe_ratio > 0 and out_of_sample.sharpe_ratio < in_sample.sharpe_ratio * 0.5:
        warnings.append(
            f"Sharpe degradation: IS={in_sample.sharpe_ratio:.2f} → OOS={out_of_sample.sharpe_ratio:.2f} "
            f"(>{50:.0f}% drop, possible overfit)"
        )
    if in_sample.win_rate_pct - out_of_sample.win_rate_pct > 15:
        warnings.append(
            f"Win rate degradation: IS={in_sample.win_rate_pct:.1f}% → OOS={out_of_sample.win_rate_pct:.1f}%"
        )
    if out_of_sample.max_drawdown_pct > in_sample.max_drawdown_pct * 2:
        warnings.append(
            f"Drawdown explosion: IS={in_sample.max_drawdown_pct:.1f}% → OOS={out_of_sample.max_drawdown_pct:.1f}%"
        )
    if not warnings:
        warnings.append("No obvious overfitting signals detected (not a guarantee)")
    return warnings
