"""
backtesting/optimizer.py
========================
Grid-search parameter optimizer for strategy configs.
IMPORTANT: Only optimise on training data. Always validate on held-out OOS data.
Includes warnings against overfitting and parameter instability.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from backtesting.backtester import Backtester
from backtesting.metrics import BacktestMetrics
from execution.fee_model import HYPERLIQUID_DEFAULT

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    best_params: Dict[str, Any]
    best_metrics: BacktestMetrics
    all_results: List[Dict] = field(default_factory=list)
    stability_score: float = 0.0  # fraction of param combos with positive Sharpe


class ParameterOptimizer:
    """
    Grid search over a parameter space for a given strategy.

    CRITICAL WARNINGS:
    1. Never select parameters based on OOS performance.
    2. Always use separate validation and test splits.
    3. Prefer parameters that are STABLE across many combos (robustness).
    4. Be suspicious of any result with Sharpe > 3.0 on in-sample data.
    5. More parameters = more overfitting risk.
    """

    def __init__(
        self,
        config: dict,
        strategy_factory,  # callable(config) -> BaseStrategy
        param_grid: Dict[str, List[Any]],
        objective: str = "sharpe_ratio",  # or "calmar_ratio", "sortino_ratio"
        initial_capital: float = 10_000.0,
    ) -> None:
        self.config = config
        self.strategy_factory = strategy_factory
        self.param_grid = param_grid
        self.objective = objective
        self.initial_capital = initial_capital

    def run(
        self,
        train_df: pd.DataFrame,
        symbol: str = "BTC",
    ) -> OptimizationResult:
        """
        Grid search over param_grid on train_df only.
        Returns best parameters and stability statistics.
        """
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        combinations = list(itertools.product(*values))

        logger.info(
            "Optimizer: testing %d parameter combinations for %s",
            len(combinations), symbol,
        )

        all_results = []
        best_score = float("-inf")
        best_params: Dict[str, Any] = {}
        best_metrics: Optional[BacktestMetrics] = None

        for combo in combinations:
            params = dict(zip(keys, combo))
            # Merge params into a config copy
            trial_config = self._merge_params(params)
            strategy = self.strategy_factory(trial_config)
            bt = Backtester(
                trial_config, strategy,
                fee_schedule=HYPERLIQUID_DEFAULT,
                slippage_bps=trial_config.get("backtesting", {}).get("slippage_bps", 5),
                initial_capital=self.initial_capital,
            )
            try:
                result = bt.run(train_df, symbol)
                metrics = result.metrics
                if metrics is None:
                    continue
                score = getattr(metrics, self.objective, 0.0)
                all_results.append({"params": params, "metrics": metrics, "score": score})
                if score > best_score and metrics.is_valid:
                    best_score = score
                    best_params = params
                    best_metrics = metrics
            except Exception as exc:  # noqa: BLE001
                logger.warning("Param combo %s failed: %s", params, exc)

        # Stability: fraction of valid combos with positive objective
        valid = [r for r in all_results if r["metrics"].is_valid]
        positive = [r for r in valid if r["score"] > 0]
        stability = len(positive) / len(valid) if valid else 0.0

        if stability < 0.5:
            logger.warning(
                "Low parameter stability (%.0f%% positive Sharpe). "
                "Results may be fragile — do not rely on best params alone.",
                stability * 100,
            )

        if best_metrics is None:
            logger.error("Optimizer found no valid parameter combinations")
            best_metrics = BacktestMetrics(is_valid=False, validity_note="No valid combos found")

        logger.info(
            "Best params: %s | %s | stability=%.1f%%",
            best_params,
            best_metrics.summary() if best_metrics else "N/A",
            stability * 100,
        )

        return OptimizationResult(
            best_params=best_params,
            best_metrics=best_metrics,
            all_results=all_results,
            stability_score=stability,
        )

    def _merge_params(self, params: Dict[str, Any]) -> dict:
        """Deep-ish merge of param overrides into config copy."""
        import copy
        config = copy.deepcopy(self.config)
        strategy_key = self.strategy_factory(config).name.lower()
        for k, v in params.items():
            if strategy_key in config:
                config[strategy_key][k] = v
        return config
