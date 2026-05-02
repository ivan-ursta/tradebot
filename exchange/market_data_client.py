"""
exchange/market_data_client.py
===============================
Fetches market data (candles, tickers, order book) from Hyperliquid.
Implements retry logic and response validation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.models import Candle, OrderBook, OrderBookLevel, Ticker
from exchange.hyperliquid_client import HyperliquidClient

logger = logging.getLogger(__name__)

# Hyperliquid candle interval names
_INTERVAL_MAP: Dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


class MarketDataClient:
    """
    Async-friendly wrapper for Hyperliquid market data endpoints.
    The underlying SDK is synchronous; we offload to executor where needed.
    """

    def __init__(self, client: HyperliquidClient) -> None:
        self._hl = client
        self._loop = asyncio.get_event_loop

    # ------------------------------------------------------------------
    # Candles / OHLCV
    # ------------------------------------------------------------------

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles with automatic pagination for large requests.
        The Hyperliquid API returns at most ~5000 candles per request;
        we chunk requests to satisfy any limit.
        Returns a DataFrame with DatetimeIndex (UTC).
        """
        interval = _INTERVAL_MAP.get(timeframe, "15m")
        interval_ms = self._interval_to_ms(timeframe)
        chunk_size = 5000  # max candles per API call
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - limit * interval_ms

        loop = asyncio.get_event_loop()
        all_raw: list = []

        # Paginate backwards in time if limit > chunk_size
        remaining = limit
        chunk_end = end_ms
        while remaining > 0:
            fetch_n = min(remaining, chunk_size)
            chunk_start = chunk_end - fetch_n * interval_ms
            raw = await loop.run_in_executor(
                None,
                lambda s=chunk_start, e=chunk_end: self._fetch_candles_sync(symbol, interval, s, e),
            )
            if not raw:
                break
            all_raw = raw + all_raw  # prepend older data
            remaining -= len(raw)
            chunk_end = int(raw[0]["t"]) - 1  # move window back
            if len(raw) < fetch_n:
                break  # no more history available

        if not all_raw:
            return pd.DataFrame()

        df = self._parse_candles(all_raw, symbol, timeframe)
        return df.tail(limit)

    def _fetch_candles_sync(
        self, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> list:
        try:
            return self._hl.info.candles_snapshot(
                symbol,
                interval,
                start_ms,
                end_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Candle fetch error [%s/%s]: %s", symbol, interval, exc)
            return []

    @staticmethod
    def _parse_candles(raw: list, symbol: str, timeframe: str) -> pd.DataFrame:
        records = []
        for c in raw:
            try:
                records.append(
                    {
                        "timestamp": pd.Timestamp(int(c["t"]), unit="ms", tz="UTC"),
                        "open": float(c["o"]),
                        "high": float(c["h"]),
                        "low": float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c["v"]),
                    }
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed candle: %s — %s", c, exc)
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep="last")]
        return df

    # ------------------------------------------------------------------
    # Ticker / latest price
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> Optional[Ticker]:
        loop = asyncio.get_event_loop()
        try:
            mids = await loop.run_in_executor(
                None, lambda: self._hl.info.all_mids()
            )
            price = mids.get(symbol)
            if price is None:
                return None
            return Ticker(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                last_price=float(price),
                bid=None,
                ask=None,
                volume_24h=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Ticker fetch error [%s]: %s", symbol, exc)
            return None

    async def get_all_mids(self) -> Dict[str, float]:
        loop = asyncio.get_event_loop()
        try:
            mids = await loop.run_in_executor(None, self._hl.info.all_mids)
            return {k: float(v) for k, v in mids.items()}
        except Exception as exc:  # noqa: BLE001
            logger.error("all_mids error: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Order book
    # ------------------------------------------------------------------

    async def get_order_book(self, symbol: str) -> Optional[OrderBook]:
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None, lambda: self._hl.info.l2_snapshot(symbol)
            )
            return self._parse_order_book(symbol, raw)
        except Exception as exc:  # noqa: BLE001
            logger.error("Order book fetch error [%s]: %s", symbol, exc)
            return None

    @staticmethod
    def _parse_order_book(symbol: str, raw: dict) -> Optional[OrderBook]:
        if not raw or "levels" not in raw:
            return None
        levels = raw["levels"]
        if len(levels) < 2:
            return None

        def parse_levels(side_data: list) -> tuple[OrderBookLevel, ...]:
            out = []
            for lvl in side_data:
                try:
                    out.append(OrderBookLevel(price=float(lvl["px"]), size=float(lvl["sz"])))
                except (KeyError, ValueError):
                    pass
            return tuple(out)

        bids = parse_levels(levels[0])
        asks = parse_levels(levels[1])
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            bids=bids,
            asks=asks,
        )

    # ------------------------------------------------------------------
    # Market metadata
    # ------------------------------------------------------------------

    async def get_market_info(self) -> list:
        """Return raw perp market metadata from Hyperliquid."""
        loop = asyncio.get_event_loop()
        try:
            meta = await loop.run_in_executor(None, self._hl.info.meta)
            return meta.get("universe", [])
        except Exception as exc:  # noqa: BLE001
            logger.error("Market info error: %s", exc)
            return []

    async def get_funding_rates(self) -> Dict[str, float]:
        """Return latest funding rates keyed by symbol."""
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: self._hl.info.funding_history(coin="BTC", startTime=0)
            )
            # Funding history returns per-symbol; use meta for current rates
            meta_and_ctx = await loop.run_in_executor(
                None, lambda: self._hl.info.meta_and_asset_ctxs()
            )
            if not meta_and_ctx or len(meta_and_ctx) < 2:
                return {}
            universe = meta_and_ctx[0].get("universe", [])
            ctxs = meta_and_ctx[1]
            result = {}
            for asset, ctx in zip(universe, ctxs):
                name = asset.get("name", "")
                funding = ctx.get("funding", "0")
                try:
                    result[name] = float(funding)
                except (ValueError, TypeError):
                    pass
            return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("Funding rate fetch error: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _interval_to_ms(timeframe: str) -> int:
        mapping = {
            "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
            "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
        }
        return mapping.get(timeframe, 900_000)
