"""
strategies/funding_filter_momentum.py
======================================
Funding-Rate Filtered Momentum strategy.

Philosophy:
  Funding is used ONLY as a filter / sentiment context, never as a sole signal.
  Extreme positive funding → market is overcrowded long → filter longs (not a short signal alone).
  Extreme negative funding → filter shorts.
  Short-term EMA momentum provides the actual directional signal.

Entry logic (long):
  - Fast EMA > Slow EMA (momentum up)
  - RSI > rsi_entry_long (not overbought)
  - Funding NOT extremely positive (overcrowded long is a filter against going long)
  - Only available when funding data is provided; falls back to pure momentum otherwise

Exit logic:
  - Fast EMA crosses below Slow EMA
  - RSI reversal toward 50
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from core.models import MarketRegime, Position, Signal, SignalDirection
from core.state import TradingState
from indicators.momentum import rsi
from indicators.trend import ema
from indicators.volatility import atr
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class FundingFilterMomentum(BaseStrategy):
    """
    EMA momentum with funding rate used as an overcrowding filter.
    Funding data is optional — strategy degrades gracefully to pure momentum
    when funding information is unavailable.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg = config.get("funding_filter_momentum", {})
        self.funding_threshold: float = cfg.get("funding_threshold_pct", 0.01)
        self.ema_fast: int = cfg.get("momentum_ema_fast", 5)
        self.ema_slow: int = cfg.get("momentum_ema_slow", 20)
        self.rsi_period: int = cfg.get("rsi_period", 14)
        self.rsi_entry_long: float = cfg.get("rsi_entry_long", 50)
        self.rsi_entry_short: float = cfg.get("rsi_entry_short", 50)
        self._min_rows = max(self.ema_slow, self.rsi_period) + 10

    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if not self._check_data_sufficiency(df, self._min_rows):
            return None
        df = df.copy()
        df["ema_fast"] = ema(df["close"], self.ema_fast)
        df["ema_slow"] = ema(df["close"], self.ema_slow)
        df["ema_cross"] = (df["ema_fast"] > df["ema_slow"]).astype(int)
        df["rsi"] = rsi(df["close"], self.rsi_period)
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)
        # funding_rate column should be injected externally if available
        if "funding_rate" not in df.columns:
            df["funding_rate"] = 0.0
        return df

    # ------------------------------------------------------------------

    def generate_signal(
        self, df: pd.DataFrame, state: TradingState
    ) -> Optional[Signal]:
        row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else row
        symbol = ""

        ema_fast = float(row["ema_fast"]) if not pd.isna(row["ema_fast"]) else None
        ema_slow = float(row["ema_slow"]) if not pd.isna(row["ema_slow"]) else None
        rsi_val = float(row["rsi"]) if not pd.isna(row["rsi"]) else None
        atr_val = float(row["atr"]) if not pd.isna(row["atr"]) else None
        funding = float(row.get("funding_rate", 0.0) or 0.0)
        close = float(row["close"])

        if None in (ema_fast, ema_slow, rsi_val, atr_val):
            return self._flat_signal(symbol)

        # Detect fresh EMA cross (not a sustained state)
        prev_ema_fast = float(prev_row["ema_fast"]) if not pd.isna(prev_row["ema_fast"]) else ema_fast
        prev_ema_slow = float(prev_row["ema_slow"]) if not pd.isna(prev_row["ema_slow"]) else ema_slow
        bullish_cross = (ema_fast > ema_slow) and (prev_ema_fast <= prev_ema_slow)
        bearish_cross = (ema_fast < ema_slow) and (prev_ema_fast >= prev_ema_slow)

        # --- Long ---
        # Filter: if funding is very positive, market is crowded long → skip
        funding_filter_long = funding > self.funding_threshold
        if bullish_cross and rsi_val >= self.rsi_entry_long and not funding_filter_long:
            sl = close - 2 * atr_val
            tp = close + 3 * atr_val
            self._logger.info(
                "LONG funding-momentum signal close=%.4f rsi=%.1f funding=%.4f",
                close, rsi_val, funding,
            )
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction=SignalDirection.LONG,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                regime=MarketRegime.TRENDING_UP,
                meta={"funding": funding, "rsi": rsi_val},
            )

        # --- Short ---
        funding_filter_short = funding < -self.funding_threshold
        if bearish_cross and rsi_val <= self.rsi_entry_short and not funding_filter_short:
            sl = close + 2 * atr_val
            tp = close - 3 * atr_val
            self._logger.info(
                "SHORT funding-momentum signal close=%.4f rsi=%.1f funding=%.4f",
                close, rsi_val, funding,
            )
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction=SignalDirection.SHORT,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                regime=MarketRegime.TRENDING_DOWN,
                meta={"funding": funding, "rsi": rsi_val},
            )

        return self._flat_signal(symbol)

    # ------------------------------------------------------------------

    def should_exit(
        self, df: pd.DataFrame, position: Position, state: TradingState
    ) -> bool:
        row = df.iloc[-1]
        ema_fast = row.get("ema_fast")
        ema_slow = row.get("ema_slow")
        rsi_val = row.get("rsi")

        if pd.isna(ema_fast) or pd.isna(ema_slow):
            return False

        if position.side.value == "long":
            return float(ema_fast) < float(ema_slow)
        else:
            return float(ema_fast) > float(ema_slow)
