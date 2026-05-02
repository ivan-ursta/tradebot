"""
strategies/mean_reversion.py
=============================
Mean Reversion strategy using Bollinger Bands + RSI.

Entry logic:
  - Price touches or closes below lower BB AND RSI oversold → long
  - Price touches or closes above upper BB AND RSI overbought → short
  - DISABLED when: trend is strong (ADX > threshold) or vol regime is high
  - DISABLED when: realized volatility too high

Exit logic:
  - Price returns to Bollinger midline (SMA)
  - Or RSI crosses neutral (50)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from core.models import MarketRegime, Position, Signal, SignalDirection
from core.state import TradingState
from indicators.momentum import rsi
from indicators.trend import adx
from indicators.volatility import atr, bollinger_bands, realized_volatility
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class MeanReversion(BaseStrategy):
    """
    Bollinger Band + RSI mean reversion.
    Explicitly range-bound; disabled when trend or vol is strong.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg = config.get("mean_reversion", {})
        self.bb_period: int = cfg.get("bb_period", 20)
        self.bb_std: float = cfg.get("bb_std", 2.0)
        self.rsi_period: int = cfg.get("rsi_period", 14)
        self.rsi_oversold: float = cfg.get("rsi_oversold", 30)
        self.rsi_overbought: float = cfg.get("rsi_overbought", 70)
        self.max_vol: float = cfg.get("max_vol_for_reversion", 0.03)
        self.max_adx: float = cfg.get("max_adx_for_reversion", 25)
        self._min_rows = max(self.bb_period, self.rsi_period, 14) + 20

    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if not self._check_data_sufficiency(df, self._min_rows):
            return None
        df = df.copy()
        bb = bollinger_bands(df["close"], self.bb_period, self.bb_std)
        df["bb_upper"] = bb["upper"]
        df["bb_mid"] = bb["mid"]
        df["bb_lower"] = bb["lower"]
        df["bb_pct_b"] = bb["pct_b"]
        df["bb_bandwidth"] = bb["bandwidth"]
        df["rsi"] = rsi(df["close"], self.rsi_period)
        adx_df = adx(df["high"], df["low"], df["close"], 14)
        df["adx"] = adx_df["adx"]
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)
        df["realized_vol"] = realized_volatility(df["close"], 20, annualize=True)
        return df

    # ------------------------------------------------------------------

    def generate_signal(
        self, df: pd.DataFrame, state: TradingState
    ) -> Optional[Signal]:
        row = df.iloc[-1]
        symbol = ""

        # Regime filters — disable in trending or high-vol conditions
        adx_val = row.get("adx")
        rv = row.get("realized_vol")
        if not pd.isna(adx_val) and float(adx_val) > self.max_adx:
            self._logger.debug("ADX too high (%.1f > %.1f), mean reversion disabled", adx_val, self.max_adx)
            return self._flat_signal(symbol)
        if not pd.isna(rv) and float(rv) > self.max_vol:
            self._logger.debug("RV too high (%.3f > %.3f), mean reversion disabled", rv, self.max_vol)
            return self._flat_signal(symbol)

        close = float(row["close"])
        bb_lower = float(row["bb_lower"]) if not pd.isna(row["bb_lower"]) else None
        bb_upper = float(row["bb_upper"]) if not pd.isna(row["bb_upper"]) else None
        bb_mid = float(row["bb_mid"]) if not pd.isna(row["bb_mid"]) else None
        rsi_val = float(row["rsi"]) if not pd.isna(row["rsi"]) else None
        atr_val = float(row["atr"]) if not pd.isna(row["atr"]) else None

        if None in (bb_lower, bb_upper, bb_mid, rsi_val, atr_val):
            return self._flat_signal(symbol)

        # Long: price at or below lower band AND RSI oversold
        if close <= bb_lower and rsi_val <= self.rsi_oversold:
            sl = close - atr_val * 1.5
            tp = bb_mid  # mean reversion target
            self._logger.info("LONG mean-reversion signal close=%.4f bb_lower=%.4f rsi=%.1f", close, bb_lower, rsi_val)
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction=SignalDirection.LONG,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                regime=MarketRegime.RANGING,
                meta={"rsi": rsi_val, "bb_lower": bb_lower},
            )

        # Short: price at or above upper band AND RSI overbought
        if close >= bb_upper and rsi_val >= self.rsi_overbought:
            sl = close + atr_val * 1.5
            tp = bb_mid
            self._logger.info("SHORT mean-reversion signal close=%.4f bb_upper=%.4f rsi=%.1f", close, bb_upper, rsi_val)
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction=SignalDirection.SHORT,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                regime=MarketRegime.RANGING,
                meta={"rsi": rsi_val, "bb_upper": bb_upper},
            )

        return self._flat_signal(symbol)

    # ------------------------------------------------------------------

    def should_exit(
        self, df: pd.DataFrame, position: Position, state: TradingState
    ) -> bool:
        row = df.iloc[-1]
        close = float(row["close"])
        bb_mid = row.get("bb_mid")
        rsi_val = row.get("rsi")

        if pd.isna(bb_mid):
            return False

        mid = float(bb_mid)
        rsi_f = float(rsi_val) if not pd.isna(rsi_val) else 50.0

        if position.side.value == "long":
            return close >= mid or rsi_f >= 50
        else:
            return close <= mid or rsi_f <= 50
