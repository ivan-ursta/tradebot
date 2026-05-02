"""
exchange/binance/market_data.py
================================
Binance USDT-M Futures market data:
  - Historical OHLCV candles (REST, paginated, public)
  - Live ticker / order book (REST, public)
  - Live candle stream (WebSocket)

All candle data is fetched from the public mainnet endpoint
(testnet has very sparse historical data).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

from core.models import OrderBook, OrderBookLevel, Ticker
from exchange.binance.client import BinanceClient, to_binance_symbol

logger = logging.getLogger(__name__)

# Binance Futures klines endpoint
_KLINES_PATH = "/fapi/v1/klines"
_TICKER_PATH = "/fapi/v1/ticker/price"
_DEPTH_PATH  = "/fapi/v1/depth"

_MAX_LIMIT_PER_REQUEST = 1_500   # Binance Futures max per klines call

_INTERVAL_MAP: Dict[str, str] = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
}

_INTERVAL_MS: Dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    "1w": 604_800_000,
}


class BinanceMarketData:
    """
    Async-friendly market data client for Binance USDT-M Futures.
    The underlying requests session is synchronous; heavy pagination
    is run in an executor so it does not block the event loop.
    """

    def __init__(self, client: BinanceClient) -> None:
        self._client = client

    # ── Candles / OHLCV ───────────────────────────────────────────────────

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        Fetch up to `limit` OHLCV candles ending at the current time.
        Automatically paginates if limit > 1500.
        Returns DataFrame with UTC DatetimeIndex, columns: open/high/low/close/volume.
        """
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: self._fetch_candles_sync(symbol, timeframe, limit),
        )
        return df

    def _fetch_candles_sync(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Synchronous paginated candle fetch.
        If start_ms/end_ms are given, fetches exactly that range (used by data loader).
        Otherwise fetches the most recent `limit` candles.
        """
        interval = _INTERVAL_MAP.get(timeframe, "1h")
        ms_per_bar = _INTERVAL_MS.get(timeframe, 3_600_000)
        binance_sym = to_binance_symbol(symbol)

        all_rows: list[list] = []

        if start_ms is not None and end_ms is not None:
            # Range-based fetch (used by historical data loader)
            current_start = start_ms
            while current_start < end_ms:
                params = {
                    "symbol": binance_sym,
                    "interval": interval,
                    "startTime": current_start,
                    "endTime": end_ms,
                    "limit": _MAX_LIMIT_PER_REQUEST,
                }
                try:
                    raw = self._client.public_get(_KLINES_PATH, params)
                except Exception as exc:
                    logger.error("Candle fetch error [%s/%s]: %s", symbol, interval, exc)
                    break
                if not raw:
                    break
                all_rows.extend(raw)
                last_open_ms = int(raw[-1][0])
                current_start = last_open_ms + ms_per_bar
                if len(raw) < _MAX_LIMIT_PER_REQUEST:
                    break
        else:
            # Recency-based fetch (most recent `limit` candles)
            import time as _time
            current_end = int(_time.time() * 1000)
            remaining = limit
            while remaining > 0:
                fetch_n = min(remaining, _MAX_LIMIT_PER_REQUEST)
                current_start = current_end - fetch_n * ms_per_bar
                params = {
                    "symbol": binance_sym,
                    "interval": interval,
                    "startTime": current_start,
                    "endTime": current_end,
                    "limit": fetch_n,
                }
                try:
                    raw = self._client.public_get(_KLINES_PATH, params)
                except Exception as exc:
                    logger.error("Candle fetch error [%s/%s]: %s", symbol, interval, exc)
                    break
                if not raw:
                    break
                all_rows = raw + all_rows
                remaining -= len(raw)
                current_end = int(raw[0][0]) - 1
                if len(raw) < fetch_n:
                    break

        if not all_rows:
            return pd.DataFrame()

        return self._parse_klines(all_rows)

    @staticmethod
    def _parse_klines(raw: list[list]) -> pd.DataFrame:
        """
        Parse Binance klines response.
        Format: [open_time, open, high, low, close, volume, close_time, ...]
        """
        records = []
        for row in raw:
            try:
                records.append({
                    "timestamp": pd.Timestamp(int(row[0]), unit="ms", tz="UTC"),
                    "open":   float(row[1]),
                    "high":   float(row[2]),
                    "low":    float(row[3]),
                    "close":  float(row[4]),
                    "volume": float(row[5]),
                })
            except (IndexError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed kline: %s — %s", row, exc)
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep="last")]
        return df

    # ── Ticker ────────────────────────────────────────────────────────────

    async def get_ticker(self, symbol: str) -> Optional[Ticker]:
        loop = asyncio.get_event_loop()
        try:
            binance_sym = to_binance_symbol(symbol)
            raw = await loop.run_in_executor(
                None,
                lambda: self._client.public_get(_TICKER_PATH, {"symbol": binance_sym}),
            )
            return Ticker(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                last_price=float(raw["price"]),
                bid=None,
                ask=None,
                volume_24h=None,
            )
        except Exception as exc:
            logger.error("Ticker fetch error [%s]: %s", symbol, exc)
            return None

    async def get_all_mids(self) -> Dict[str, float]:
        """Return {internal_symbol: mid_price} for all USDT futures."""
        loop = asyncio.get_event_loop()
        try:
            from exchange.binance.client import from_binance_symbol
            raw = await loop.run_in_executor(
                None,
                lambda: self._client.public_get(_TICKER_PATH),
            )
            result: Dict[str, float] = {}
            for item in raw:
                sym = item.get("symbol", "")
                if sym.endswith("USDT"):
                    short = from_binance_symbol(sym)
                    result[short] = float(item["price"])
            return result
        except Exception as exc:
            logger.error("get_all_mids error: %s", exc)
            return {}

    # ── Order book ────────────────────────────────────────────────────────

    async def get_order_book(self, symbol: str, depth: int = 10) -> Optional[OrderBook]:
        loop = asyncio.get_event_loop()
        try:
            binance_sym = to_binance_symbol(symbol)
            raw = await loop.run_in_executor(
                None,
                lambda: self._client.public_get(
                    _DEPTH_PATH, {"symbol": binance_sym, "limit": depth}
                ),
            )
            bids = tuple(
                OrderBookLevel(price=float(b[0]), size=float(b[1]))
                for b in raw.get("bids", [])
            )
            asks = tuple(
                OrderBookLevel(price=float(a[0]), size=float(a[1]))
                for a in raw.get("asks", [])
            )
            return OrderBook(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                bids=bids,
                asks=asks,
            )
        except Exception as exc:
            logger.error("Order book fetch error [%s]: %s", symbol, exc)
            return None

    # ── WebSocket ─────────────────────────────────────────────────────────

    async def stream_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        callback=None,
    ) -> None:
        """
        Subscribe to a live kline stream for one symbol.
        Calls callback(df_row: dict) on each closed candle.
        Runs indefinitely until cancelled.
        """
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed — cannot stream candles")
            return

        interval = _INTERVAL_MAP.get(timeframe, "1h")
        binance_sym = to_binance_symbol(symbol).lower()
        stream = f"{binance_sym}@kline_{interval}"
        url = f"{self._client.ws_base}/stream?streams={stream}"

        logger.info("Opening WebSocket kline stream: %s", url)
        import json
        async for ws in websockets.connect(url):
            try:
                async for message in ws:
                    data = json.loads(message)
                    kline = data.get("data", {}).get("k", {})
                    if not kline:
                        continue
                    if not kline.get("x", False):
                        # Candle not yet closed — skip
                        continue
                    row = {
                        "timestamp": pd.Timestamp(int(kline["t"]), unit="ms", tz="UTC"),
                        "open":   float(kline["o"]),
                        "high":   float(kline["h"]),
                        "low":    float(kline["l"]),
                        "close":  float(kline["c"]),
                        "volume": float(kline["v"]),
                    }
                    if callback:
                        await callback(row)
            except websockets.ConnectionClosed:
                logger.warning("WebSocket closed for %s, reconnecting…", symbol)
                await asyncio.sleep(1)
                continue
