"""
research/data_loader.py
=======================
Fetches OHLCV data from Hyperliquid with disk caching.
Cached as CSV; pass force_refresh=True to re-download.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Ensure project root is on path when run standalone
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"

_BARS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "30m": 17_520,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


def _cache_path(symbol: str, timeframe: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{symbol}_{timeframe}.csv"


async def fetch_candles(
    symbol: str,
    timeframe: str = "1h",
    years: float = 2.0,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles for one symbol.
    Returns DataFrame with UTC DatetimeIndex, columns: open high low close volume.
    """
    cache_file = _cache_path(symbol, timeframe)

    if cache_file.exists() and not force_refresh:
        logger.info("[cache] %s/%s ← %s", symbol, timeframe, cache_file.name)
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        logger.info("[cache] %d candles loaded", len(df))
        return df

    from hyperliquid.info import Info
    from exchange.market_data_client import MarketDataClient

    bars_per_year = _BARS_PER_YEAR.get(timeframe, 8_760)
    limit = int(bars_per_year * years)
    logger.info("[fetch] %s/%s — requesting %d candles (%.1f yrs)", symbol, timeframe, limit, years)

    # Info client requires no credentials — candles are public market data
    class _BareClient:
        """Minimal stub so MarketDataClient can call _fetch_candles_sync."""
        info = Info("https://api.hyperliquid.xyz", skip_ws=True)

    md = MarketDataClient(_BareClient())  # type: ignore[arg-type]

    df = await md.get_candles(symbol, timeframe, limit=limit)

    if df is None or df.empty:
        logger.error("[fetch] no data returned for %s/%s", symbol, timeframe)
        return pd.DataFrame()

    logger.info("[fetch] %d candles received for %s/%s", len(df), symbol, timeframe)
    df.to_csv(cache_file)
    return df


def load_all(
    symbols: list[str],
    timeframe: str = "1h",
    years: float = 2.0,
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Fetch all symbols concurrently. Returns {symbol: DataFrame}."""

    async def _gather() -> dict[str, pd.DataFrame]:
        results = await asyncio.gather(
            *[fetch_candles(s, timeframe, years, force_refresh) for s in symbols],
            return_exceptions=True,
        )
        out: dict[str, pd.DataFrame] = {}
        for sym, res in zip(symbols, results):
            if isinstance(res, pd.DataFrame) and not res.empty:
                out[sym] = res
            else:
                logger.warning("[fetch] %s skipped — %s", sym, res)
        return out

    return asyncio.run(_gather())
