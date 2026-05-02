"""
strategies/momentum_breakout.py
================================
Momentum Breakout strategy.

Entry logic:
  - Close breaks above Donchian upper (long) or below Donchian lower (short)
  - Volume spike confirms breakout
  - Fast EMA > Slow EMA confirms uptrend (long) or inverted for short
  - ATR must exceed minimum threshold (avoid flat markets)
  - Avoid entries in HIGH volatility regime (position sizing handles this, but
    we also add a regime filter here)

Exit logic (strategy-level, in addition to risk-module stop/TP):
  - Close crosses back through Donchian midpoint
  - Or fast EMA crosses below slow EMA (for long)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from core.models import MarketRegime, Position, Signal, SignalDirection
from core.state import TradingState
from indicators.trend import adx, donchian_channel, ema, trend_strength
from indicators.volatility import atr, volatility_regime
from indicators.volume import volume_spike
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class MomentumBreakout(BaseStrategy):
    """
    Donchian channel breakout with volume and trend confirmation.
    Suitable for: trending liquid perp markets.
    Not suitable for: ranging, low-volume, or extremely high-vol regimes.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg = config.get("momentum_breakout", {})
        self.donchian_period: int = cfg.get("donchian_period", 20)
        self.vol_ma_period: int = cfg.get("volume_ma_period", 20)
        self.vol_spike_mult: float = cfg.get("volume_spike_mult", 1.5)
        self.atr_period: int = cfg.get("atr_period", 14)
        self.atr_filter_mult: float = cfg.get("atr_filter_mult", 1.0)
        self.ema_fast: int = cfg.get("trend_ema_fast", 9)
        self.ema_slow: int = cfg.get("trend_ema_slow", 21)
        self.ema_confirm: bool = cfg.get("trend_ema_confirm", True)
        self.adx_period: int = cfg.get("adx_period", 14)
        self.adx_threshold: float = cfg.get("adx_threshold", 20.0)
        self.confirm_bars: int = cfg.get("breakout_confirm_bars", 2)
        self._min_rows = max(self.donchian_period, self.ema_slow, self.atr_period, self.adx_period) + self.confirm_bars + 5

    # ------------------------------------------------------------------
    # Feature preparation
    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if not self._check_data_sufficiency(df, self._min_rows):
            return None
        df = df.copy()
        # Donchian channel (exclude current bar — use prior N bars for signal)
        dc = donchian_channel(df["high"].shift(1), df["low"].shift(1), self.donchian_period)
        df["dc_upper"] = dc["upper"]
        df["dc_lower"] = dc["lower"]
        df["dc_mid"] = dc["mid"]
        # EMA trend
        df["ema_fast"] = ema(df["close"], self.ema_fast)
        df["ema_slow"] = ema(df["close"], self.ema_slow)
        df["trend_strength"] = trend_strength(df["close"], self.ema_fast, self.ema_slow)
        # ATR
        df["atr"] = atr(df["high"], df["low"], df["close"], self.atr_period)
        # Volume spike
        df["vol_spike"] = volume_spike(df["volume"], self.vol_ma_period, self.vol_spike_mult)
        # Volatility regime
        df["vol_regime"] = volatility_regime(df["close"], period=20)
        # ADX — trend strength filter
        adx_df = adx(df["high"], df["low"], df["close"], self.adx_period)
        df["adx"] = adx_df["adx"]
        return df

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(
        self, df: pd.DataFrame, state: TradingState
    ) -> Optional[Signal]:
        row = df.iloc[-1]
        symbol = ""  # filled by engine

        # Skip in extreme volatility regime
        if row.get("vol_regime") == "high":
            return self._flat_signal(symbol)

        close = float(row["close"])
        dc_upper = float(row["dc_upper"]) if not pd.isna(row["dc_upper"]) else None
        dc_lower = float(row["dc_lower"]) if not pd.isna(row["dc_lower"]) else None
        dc_mid = float(row["dc_mid"]) if not pd.isna(row["dc_mid"]) else None
        atr_val = float(row["atr"]) if not pd.isna(row["atr"]) else None
        ema_fast = float(row["ema_fast"]) if not pd.isna(row["ema_fast"]) else None
        ema_slow = float(row["ema_slow"]) if not pd.isna(row["ema_slow"]) else None
        adx_val = float(row["adx"]) if not pd.isna(row.get("adx", float("nan"))) else None
        vol_spike_flag = bool(row["vol_spike"])

        if None in (dc_upper, dc_lower, dc_mid, atr_val, ema_fast, ema_slow):
            return self._flat_signal(symbol)

        # ATR filter — avoid very flat markets
        if atr_val < (close * 0.001):  # less than 0.1% of price → flat
            return self._flat_signal(symbol)

        # ADX filter — only trade when market is trending
        if adx_val is not None and adx_val < self.adx_threshold:
            return self._flat_signal(symbol)

        # Require close to be at least 0.05% beyond the channel boundary
        min_breakout_distance = close * 0.0005

        trend_up = ema_fast > ema_slow
        trend_down = ema_fast < ema_slow

        # 2-bar breakout confirmation: all N confirm_bars must have closed beyond the channel
        confirm_long = all(
            float(df.iloc[-(k + 1)]["close"]) > float(df.iloc[-(k + 1)]["dc_upper"]) + min_breakout_distance
            for k in range(self.confirm_bars)
        )
        confirm_short = all(
            float(df.iloc[-(k + 1)]["close"]) < float(df.iloc[-(k + 1)]["dc_lower"]) - min_breakout_distance
            for k in range(self.confirm_bars)
        )

        # --- Long entry ---
        long_breakout = confirm_long
        long_trend = (not self.ema_confirm) or trend_up
        if long_breakout and long_trend and vol_spike_flag:
            sl_mult = state.config_ref.get("risk", {}).get("stop_loss_atr_mult", 2.0) if hasattr(state, "config_ref") else 2.0
            tp_mult = state.config_ref.get("risk", {}).get("take_profit_atr_mult", 3.0) if hasattr(state, "config_ref") else 3.0
            sl = close - atr_val * sl_mult
            tp = close + atr_val * tp_mult
            self._logger.debug("LONG breakout signal close=%.4f dc_upper=%.4f atr=%.2f", close, dc_upper, atr_val)
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction=SignalDirection.LONG,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                regime=MarketRegime.TRENDING_UP,
                meta={"atr": atr_val, "dc_upper": dc_upper, "vol_spike": vol_spike_flag},
            )

        # --- Short entry ---
        short_breakout = confirm_short
        short_trend = (not self.ema_confirm) or trend_down
        if short_breakout and short_trend and vol_spike_flag:
            sl_mult = state.config_ref.get("risk", {}).get("stop_loss_atr_mult", 2.0) if hasattr(state, "config_ref") else 2.0
            tp_mult = state.config_ref.get("risk", {}).get("take_profit_atr_mult", 3.0) if hasattr(state, "config_ref") else 3.0
            sl = close + atr_val * sl_mult
            tp = close - atr_val * tp_mult
            self._logger.debug("SHORT breakout signal close=%.4f dc_lower=%.4f atr=%.2f", close, dc_lower, atr_val)
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                direction=SignalDirection.SHORT,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                regime=MarketRegime.TRENDING_DOWN,
                meta={"atr": atr_val, "dc_lower": dc_lower, "vol_spike": vol_spike_flag},
            )

        return self._flat_signal(symbol)

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def should_exit(
        self, df: pd.DataFrame, position: Position, state: TradingState
    ) -> bool:
        row = df.iloc[-1]
        ema_fast = row.get("ema_fast")
        ema_slow = row.get("ema_slow")

        if pd.isna(ema_fast) or pd.isna(ema_slow):
            return False

        # Exit only on EMA trend reversal — avoids cutting winners on dc_mid noise
        if position.side.value == "long":
            return float(ema_fast) < float(ema_slow)
        else:
            return float(ema_fast) > float(ema_slow)
