"""
backtesting/walk_forward.py
============================
Walk-forward analysis: trains on expanding/rolling window,
tests on the immediately following out-of-sample window.
Checks for parameter stability and overfitting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

import pandas as pd

from backtesting.backtester import Backtester, BacktestResult
from backtesting.metrics import BacktestMetrics, overfitting_warning
from execution.fee_model import HYPERLIQUID_DEFAULT

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    window_number: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_result: BacktestResult
    test_result: BacktestResult
    overfitting_warnings: List[str] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    strategy_name: str
    symbol: str
    windows: List[WalkForwardWindow] = field(default_factory=list)
    combined_oos_metrics: BacktestMetrics | None = None

    def summary(self) -> str:
        lines = [f"Walk-Forward Analysis: {self.strategy_name} / {self.symbol}"]
        lines.append(f"Windows tested: {len(self.windows)}")
        if self.combined_oos_metrics:
            lines.append(f"Combined OOS: {self.combined_oos_metrics.summary()}")
        for w in self.windows:
            oos_m = w.test_result.metrics
            lines.append(
                f"  Window {w.window_number}: OOS Sharpe={oos_m.sharpe_ratio:.2f} "
                f"Return={oos_m.total_return_pct:.1f}% DD={oos_m.max_drawdown_pct:.1f}%"
                + (" ⚠ " + " | ".join(w.overfitting_warnings) if w.overfitting_warnings else "")
            )
        return "\n".join(lines)


class WalkForwardAnalyzer:
    """
    Performs walk-forward validation on a fixed strategy + data split.
    Uses anchored (expanding) windows for robustness.
    """

    def __init__(
        self,
        config: dict,
        strategy_factory,  # callable(config) -> BaseStrategy
        n_windows: int = 5,
        initial_capital: float = 10_000.0,
    ) -> None:
        self.config = config
        self.strategy_factory = strategy_factory
        self.n_windows = n_windows
        self.initial_capital = initial_capital

    def run(self, df: pd.DataFrame, symbol: str = "BTC") -> WalkForwardResult:
        """
        Split df into n_windows consecutive segments.
        For each window: train on [0..train_end], test on [train_end..test_end].
        """
        n = len(df)
        window_size = n // (self.n_windows + 1)
        if window_size < 100:
            logger.warning("Walk-forward window too small (%d bars). Need more data.", window_size)

        result = WalkForwardResult(
            strategy_name=self.strategy_factory(self.config).name,
            symbol=symbol,
        )
        oos_equity_curves = []
        oos_trade_returns = []

        for w in range(self.n_windows):
            train_start = 0  # anchored — always from beginning
            train_end = (w + 1) * window_size
            test_start = train_end
            test_end = min(test_start + window_size, n)

            if test_end <= test_start + 20:
                continue  # not enough OOS data

            train_df = df.iloc[train_start:train_end]
            test_df = df.iloc[test_start:test_end]

            strategy = self.strategy_factory(self.config)
            backtester = Backtester(
                self.config, strategy,
                fee_schedule=HYPERLIQUID_DEFAULT,
                slippage_bps=self.config.get("backtesting", {}).get("slippage_bps", 5),
                initial_capital=self.initial_capital,
            )

            train_result = backtester.run(train_df, symbol)
            test_result = backtester.run(test_df, symbol)

            # Overfitting check
            of_warnings: List[str] = []
            if train_result.metrics and test_result.metrics:
                of_warnings = overfitting_warning(train_result.metrics, test_result.metrics)
                if of_warnings and of_warnings[0].startswith("No obvious"):
                    of_warnings = []

            window_result = WalkForwardWindow(
                window_number=w + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                train_result=train_result,
                test_result=test_result,
                overfitting_warnings=of_warnings,
            )
            result.windows.append(window_result)

            if len(test_result.equity_curve) > 0:
                oos_equity_curves.append(test_result.equity_curve)
            oos_trade_returns.extend([t.return_pct for t in test_result.trades])

        # Combined OOS equity
        if oos_equity_curves:
            combined_equity = pd.concat(oos_equity_curves)
            from backtesting.metrics import compute_metrics
            result.combined_oos_metrics = compute_metrics(
                combined_equity,
                oos_trade_returns,
                initial_capital=self.initial_capital,
                min_trades=self.config.get("backtesting", {}).get("min_trades_for_validity", 30),
            )

        logger.info(result.summary())
        return result
