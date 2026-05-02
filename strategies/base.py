"""
strategies/base.py
==================
Abstract base class for all trading strategies.
Subclasses must implement the abstract methods.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from core.models import Position, Signal, SignalDirection
from core.state import TradingState

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    Every strategy must inherit from this class and implement
    the required interface methods.

    Lifecycle on each bar:
        1. prepare_features(df)   — compute indicators
        2. generate_signal(df, state) — decide direction or FLAT
        3. should_exit(df, pos, state) — check for exit on existing position
        4. on_fill(fill) — react to confirmed fills
        5. on_bar_close(df, state) — optional housekeeping
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self.name: str = self.__class__.__name__
        self._logger = logging.getLogger(f"strategy.{self.name}")

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def prepare_features(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Accept raw OHLCV DataFrame, return enriched DataFrame with
        all indicator columns needed by generate_signal / should_exit.
        Return None if insufficient data.
        """

    @abstractmethod
    def generate_signal(
        self, df: pd.DataFrame, state: TradingState
    ) -> Optional[Signal]:
        """
        Evaluate the latest bar and return a Signal or None.
        Should return Signal with direction=FLAT if no trade is warranted.
        Must NEVER place orders directly — only return signals.
        """

    @abstractmethod
    def should_exit(
        self, df: pd.DataFrame, position: Position, state: TradingState
    ) -> bool:
        """
        Given current features and an open position, return True if the
        strategy's own exit logic fires (separate from stop/TP in risk module).
        """

    # ------------------------------------------------------------------
    # Optional hooks (override as needed)
    # ------------------------------------------------------------------

    def on_fill(self, fill) -> None:
        """Called when an order fill is confirmed."""

    def on_bar_close(self, df: pd.DataFrame, state: TradingState) -> None:
        """Called at the end of every bar regardless of signal outcome."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _flat_signal(self, symbol: str = "") -> Signal:
        return Signal(strategy_name=self.name, symbol=symbol, direction=SignalDirection.FLAT)

    def _check_data_sufficiency(self, df: pd.DataFrame, min_rows: int) -> bool:
        if df is None or len(df) < min_rows:
            self._logger.debug("Insufficient data: %d rows (need %d)", len(df) if df is not None else 0, min_rows)
            return False
        return True

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(config={self.config})"
