"""
core/engine.py
==============
Main trading engine — coordinates data collection, strategy evaluation,
risk checks, and order submission in a single event loop iteration.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from core.events import EventType, bus
from core.models import MarketRegime, SignalDirection, TradingMode
from core.state import TradingState

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    Orchestrates one full strategy cycle per bar:
      1. Fetch candle data
      2. Prepare features
      3. Evaluate strategy signals
      4. Run risk checks
      5. Submit orders
      6. Update state
    """

    def __init__(
        self,
        config: dict,
        state: TradingState,
        market_data_client,
        execution_client,
        strategies: list,
        risk_manager,
        position_sizer,
        order_manager,
        mode: TradingMode = TradingMode.PAPER,
    ) -> None:
        self.config = config
        self.state = state
        self.market_data = market_data_client
        self.execution = execution_client
        self.strategies = strategies
        self.risk = risk_manager
        self.position_sizer = position_sizer
        self.order_manager = order_manager
        self.mode = mode
        self._running = False
        self._symbols: List[str] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, symbols: List[str]) -> None:
        self._symbols = symbols
        self._running = True
        bus.emit(EventType.STARTUP, source="engine", payload={"symbols": symbols, "mode": self.mode})
        logger.info("Engine started | mode=%s | symbols=%s", self.mode, symbols)

        timeframe = self.config.get("strategy", {}).get("timeframe", "15m")
        interval_seconds = self._timeframe_to_seconds(timeframe)

        while self._running:
            try:
                await self._run_cycle(timeframe)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Engine cycle error: %s", exc)
                bus.emit(EventType.ERROR, source="engine", payload=str(exc))

            await asyncio.sleep(interval_seconds)

    async def stop(self) -> None:
        self._running = False
        bus.emit(EventType.SHUTDOWN, source="engine")
        logger.info("Engine stopped")

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------

    async def _run_cycle(self, timeframe: str) -> None:
        if self.state.kill_switch_active:
            logger.warning("Kill switch active — skipping cycle")
            return

        for symbol in self._symbols:
            await self._process_symbol(symbol, timeframe)

    async def _process_symbol(self, symbol: str, timeframe: str) -> None:
        # 1. Fetch candles
        candles_df = await self._fetch_candles(symbol, timeframe)
        if candles_df is None or len(candles_df) < self.config["markets"]["min_candle_history"]:
            logger.debug("Insufficient candle data for %s", symbol)
            return

        # 2. Evaluate current positions for exits
        await self._check_exits(symbol, candles_df)

        # 3. Run each active strategy
        for strategy in self.strategies:
            if self.state.is_in_cooldown(strategy.name):
                continue
            await self._evaluate_strategy(strategy, symbol, candles_df)

    async def _fetch_candles(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        try:
            limit = max(
                self.config["markets"]["min_candle_history"] + 50,
                200,
            )
            return await self.market_data.get_candles(symbol, timeframe, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch candles for %s: %s", symbol, exc)
            return None

    async def _evaluate_strategy(self, strategy, symbol: str, df: pd.DataFrame) -> None:
        try:
            # Prepare features
            featured_df = strategy.prepare_features(df)
            if featured_df is None or featured_df.empty:
                return

            # Generate signal
            signal = strategy.generate_signal(featured_df, self.state)
            if signal is None or not signal.is_actionable():
                return

            signal.symbol = symbol
            self.state.add_signal(signal)
            bus.emit(EventType.SIGNAL_GENERATED, source=strategy.name, payload=signal)
            logger.info(
                "Signal: %s %s %s entry=%.4f sl=%.4f tp=%.4f",
                strategy.name, symbol, signal.direction.value,
                signal.entry_price or 0,
                signal.stop_loss or 0,
                signal.take_profit or 0,
            )

            # Skip if already in position for this symbol
            if symbol in self.state.positions:
                logger.debug("Already in position for %s — skipping entry", symbol)
                return

            # Risk checks
            risk_ok, reason = self.risk.check_entry(signal, self.state)
            if not risk_ok:
                bus.emit(EventType.SIGNAL_REJECTED, source="risk", payload={"signal": signal, "reason": reason})
                logger.info("Signal rejected [%s]: %s", symbol, reason)
                return

            # Size position
            quantity = self.position_sizer.calculate_size(signal, self.state)
            if quantity <= 0:
                logger.debug("Position size zero for %s — skipping", symbol)
                return

            # Submit order
            await self.order_manager.submit_entry(signal, quantity)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Strategy eval error [%s/%s]: %s", strategy.name, symbol, exc)

    async def _check_exits(self, symbol: str, df: pd.DataFrame) -> None:
        position = self.state.positions.get(symbol)
        if position is None:
            return

        current_price = float(df["close"].iloc[-1])
        position.mark_to_market(current_price)

        # Stop loss
        if position.stop_loss:
            if (position.side.value == "long" and current_price <= position.stop_loss) or \
               (position.side.value == "short" and current_price >= position.stop_loss):
                logger.warning("Stop loss triggered for %s at %.4f", symbol, current_price)
                bus.emit(EventType.STOP_LOSS_TRIGGERED, source="engine",
                         payload={"symbol": symbol, "price": current_price})
                await self.order_manager.close_position(position, reason="stop_loss")
                return

        # Take profit
        if position.take_profit:
            if (position.side.value == "long" and current_price >= position.take_profit) or \
               (position.side.value == "short" and current_price <= position.take_profit):
                logger.info("Take profit triggered for %s at %.4f", symbol, current_price)
                bus.emit(EventType.TAKE_PROFIT_TRIGGERED, source="engine",
                         payload={"symbol": symbol, "price": current_price})
                await self.order_manager.close_position(position, reason="take_profit")
                return

        # Strategy exit signal
        for strategy in self.strategies:
            if strategy.name == position.strategy_name:
                featured_df = strategy.prepare_features(df)
                if featured_df is not None and strategy.should_exit(featured_df, position, self.state):
                    logger.info("Strategy exit signal for %s", symbol)
                    await self.order_manager.close_position(position, reason="strategy_exit")
                    return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _timeframe_to_seconds(tf: str) -> int:
        mapping = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
        }
        return mapping.get(tf, 900)
