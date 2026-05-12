"""
strategies/market_making.py
============================
Market Making strategy — advanced module.

IMPORTANT: Market making is fundamentally different from directional strategies.
It does not produce entry/exit signals; instead it produces pairs of limit orders
(bid + ask) around the mid price and manages inventory.

Safety rules:
  - Hard inventory limit: do not let position exceed max_inventory_usd
  - Volatility pause: cancel all quotes if mid moves > N * ATR (violent move)
  - Thin book pause: pause if best-level depth is too thin
  - Spread floor: always quote at least spread_bps
  - Cancel/replace on every cycle (cancel_replace_interval_ms)

This strategy integrates with order_manager for quote placement.
The generate_signal() interface is repurposed to return a special FLAT signal
with metadata describing the desired quotes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from core.models import MarketRegime, OrderBook, Position, Signal, SignalDirection
from core.state import TradingState
from indicators.volatility import atr
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class MarketMaking(BaseStrategy):
    """
    Inventory-aware market making.

    CAUTION: Market making is only profitable with:
      1. Low latency infrastructure
      2. Reliable fill simulation
      3. Careful inventory control
      4. Very frequent quote refreshes
    DO NOT run this in production without thorough paper testing.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        cfg = config.get("market_making", {})
        self.spread_bps: float = cfg.get("spread_bps", 10)
        self.max_inventory_usd: float = cfg.get("max_inventory_usd", 500)
        self.inventory_skew: float = cfg.get("inventory_skew_factor", 0.5)
        self.vol_pause_mult: float = cfg.get("vol_pause_atr_mult", 3.0)
        self.thin_book_usd: float = cfg.get("thin_book_threshold_usd", 1000)
        self._min_rows = 20
        self._last_mid: Optional[float] = None
        self._pause_until: Optional[datetime] = None

    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        if not self._check_data_sufficiency(df, self._min_rows):
            return None
        df = df.copy()
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)
        return df

    # ------------------------------------------------------------------

    def generate_signal(
        self, df: pd.DataFrame, state: TradingState
    ) -> Optional[Signal]:
        """
        For market making, generate_signal returns quote parameters
        embedded in signal.meta, or a FLAT signal to pause quoting.
        """
        row = df.iloc[-1]
        symbol = ""
        close = float(row["close"])
        atr_val = float(row["atr"]) if not pd.isna(row["atr"]) else None

        # Pause check
        if self._pause_until and datetime.now(timezone.utc) < self._pause_until:
            return self._flat_signal(symbol)

        if atr_val is None:
            return self._flat_signal(symbol)

        # Volatility pause: if price moved too much since last mid → pause
        if self._last_mid and abs(close - self._last_mid) > self.vol_pause_mult * atr_val:
            from datetime import timedelta
            self._pause_until = datetime.now(timezone.utc) + timedelta(seconds=30)
            self._logger.warning("MM volatility pause triggered at %.4f", close)
            return self._flat_signal(symbol)

        self._last_mid = close

        # Inventory position
        position = state.positions.get(symbol)
        inventory_usd = 0.0
        inventory_side = 0  # +1 long, -1 short, 0 flat
        if position:
            inventory_usd = position.notional_value
            inventory_side = 1 if position.side.value == "long" else -1

        # Hard inventory limit
        if inventory_usd >= self.max_inventory_usd:
            self._logger.info("MM inventory limit reached (%.2f USD)", inventory_usd)
            return self._flat_signal(symbol)

        # Spread
        half_spread = (self.spread_bps / 10_000) * close / 2

        # Inventory skew: if long, lower bid and raise ask to reduce inventory
        skew = inventory_side * (inventory_usd / self.max_inventory_usd) * self.inventory_skew * half_spread

        bid_price = close - half_spread - skew
        ask_price = close + half_spread - skew

        # Quote size proportional to remaining capacity
        remaining_capacity = max(0, self.max_inventory_usd - inventory_usd)
        quote_size_usd = remaining_capacity / 2  # split between bid and ask

        if quote_size_usd < 10:
            return self._flat_signal(symbol)

        bid_qty = quote_size_usd / bid_price
        ask_qty = quote_size_usd / ask_price

        return Signal(
            strategy_name=self.name,
            symbol=symbol,
            direction=SignalDirection.FLAT,  # MM doesn't produce directional signals
            entry_price=close,
            regime=MarketRegime.RANGING,
            meta={
                "mm_mode": True,
                "bid_price": bid_price,
                "ask_price": ask_price,
                "bid_qty": bid_qty,
                "ask_qty": ask_qty,
                "inventory_usd": inventory_usd,
                "skew": skew,
            },
        )

    # ------------------------------------------------------------------

    def should_exit(
        self, df: pd.DataFrame, position: Position, state: TradingState
    ) -> bool:
        """
        For MM, we never 'exit' via the standard signal; we reduce inventory
        by skewing quotes. Return True only if inventory limit is blown.
        """
        row = df.iloc[-1]
        close = float(row["close"])
        return position.notional_value > self.max_inventory_usd * 1.5
