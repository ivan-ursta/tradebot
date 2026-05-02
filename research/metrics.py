"""
research/metrics.py
===================
Standalone performance metrics for the research framework.
Computes all statistics from a BacktestResult; no external dependencies
beyond numpy / pandas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from research.engine import BacktestResult

# Annualisation factors
_PERIODS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "30m": 17_520,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 252,
}

MIN_TRADES_FOR_VALIDITY = 30


@dataclass
class ResearchMetrics:
    symbol: str = ""
    strategy: str = ""
    period: str = ""           # e.g. "IS", "OOS", "WF-combined"

    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown_pct: float = 0.0
    calmar: float = 0.0
    profit_factor: float = 0.0
    win_rate_pct: float = 0.0
    expectancy_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    trades: int = 0
    exposure_pct: float = 0.0

    is_valid: bool = True
    note: str = ""

    # Thresholds for a "candidate edge"
    EDGE_PF = 1.3
    EDGE_SHARPE = 0.5      # relaxed from 1.0 — cross-market raw edge screen
    EDGE_MAX_DD = 30.0

    @property
    def passes_edge_screen(self) -> bool:
        return (
            self.trades >= MIN_TRADES_FOR_VALIDITY
            and self.profit_factor >= self.EDGE_PF
            and self.sharpe >= self.EDGE_SHARPE
            and self.max_drawdown_pct <= self.EDGE_MAX_DD
        )

    def row(self) -> dict:
        """Return a flat dict for DataFrame display."""
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "period": self.period,
            "return%": f"{self.total_return_pct:+.2f}",
            "sharpe": f"{self.sharpe:.2f}",
            "sortino": f"{self.sortino:.2f}",
            "maxDD%": f"{self.max_drawdown_pct:.2f}",
            "PF": f"{self.profit_factor:.2f}",
            "winRate%": f"{self.win_rate_pct:.1f}",
            "expect%": f"{self.expectancy_pct:.3f}",
            "trades": self.trades,
            "edge?": "YES" if self.passes_edge_screen else "---",
            "note": self.note,
        }


def compute(
    result: BacktestResult,
    timeframe: str = "1h",
    symbol: str = "",
    strategy: str = "",
    period: str = "",
) -> ResearchMetrics:
    """Compute ResearchMetrics from a BacktestResult."""
    m = ResearchMetrics(symbol=symbol, strategy=strategy, period=period)
    m.trades = len(result.trades)

    if m.trades == 0 or result.equity_curve.empty:
        m.is_valid = False
        m.note = "no trades"
        return m

    periods_per_year = _PERIODS_PER_YEAR.get(timeframe, 8_760)
    eq = result.equity_curve
    initial = result.initial_capital

    # Total return
    m.total_return_pct = (eq.iloc[-1] - initial) / initial * 100

    # CAGR
    n_bars = len(eq)
    years = n_bars / periods_per_year
    if years > 0 and eq.iloc[-1] > 0:
        m.cagr_pct = ((eq.iloc[-1] / initial) ** (1.0 / years) - 1.0) * 100

    # Bar-level returns
    bar_rets = eq.pct_change().dropna()
    if len(bar_rets) < 2:
        m.is_valid = False
        m.note = "curve too short"
        return m

    mu = bar_rets.mean()
    sigma = bar_rets.std(ddof=1)
    downside = bar_rets[bar_rets < 0].std(ddof=1)

    if sigma > 0:
        m.sharpe = mu / sigma * math.sqrt(periods_per_year)
    if downside > 0:
        m.sortino = mu / downside * math.sqrt(periods_per_year)

    # Drawdown
    rolling_max = eq.cummax()
    dd = (eq - rolling_max) / rolling_max
    m.max_drawdown_pct = abs(float(dd.min())) * 100

    if m.max_drawdown_pct > 0 and m.cagr_pct > 0:
        m.calmar = m.cagr_pct / m.max_drawdown_pct

    # Trade stats
    rets = result.trade_returns
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]

    m.win_rate_pct = len(wins) / len(rets) * 100 if rets else 0.0
    m.avg_win_pct = float(np.mean(wins)) if wins else 0.0
    m.avg_loss_pct = float(np.mean(losses)) if losses else 0.0

    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    m.profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    wr = m.win_rate_pct / 100
    m.expectancy_pct = wr * m.avg_win_pct + (1 - wr) * m.avg_loss_pct

    # Exposure
    bars_in_trade = sum(t.bars_held for t in result.trades)
    m.exposure_pct = bars_in_trade / n_bars * 100 if n_bars > 0 else 0.0

    # Validity
    if m.trades < MIN_TRADES_FOR_VALIDITY:
        m.is_valid = False
        m.note = f"only {m.trades} trades (need {MIN_TRADES_FOR_VALIDITY})"

    return m
