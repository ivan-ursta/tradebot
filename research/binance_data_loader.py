"""
research/binance_data_loader.py
================================
Downloads OHLCV candles from Binance USDT-M Futures public REST API.
No API key required — klines are public market data.

Usage
-----
    from research.binance_data_loader import load_all

    data = load_all(["BTC", "ETH", "SOL", "AVAX", "ARB", "OP"],
                    timeframe="1h", years=3.0)

Caches to data/cache/binance_{symbol}_{timeframe}.csv.
Pass force_refresh=True to re-download.

Symbol mapping
--------------
Internal short names map to Binance USDT-M futures tickers:
  BTC  → BTCUSDT    ETH  → ETHUSDT   SOL  → SOLUSDT
  AVAX → AVAXUSDT   ARB  → ARBUSDT   OP   → OPUSDT
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
FUTURES_BASE = "https://fapi.binance.com"
KLINES_PATH  = "/fapi/v1/klines"
MAX_PER_REQ  = 1_500   # Binance Futures max candles per request

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"

BARS_PER_YEAR: Dict[str, int] = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040,
    "30m": 17_520, "1h": 8_760,   "4h": 2_190, "1d": 365,
}

MS_PER_INTERVAL: Dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}

# Internal symbol → Binance futures ticker
SYMBOL_MAP: Dict[str, str] = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "SOL":  "SOLUSDT",
    "AVAX": "AVAXUSDT",
    "ARB":  "ARBUSDT",
    "OP":   "OPUSDT",
}


def _cache_path(symbol: str, timeframe: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"binance_{symbol}_{timeframe}.csv"


def fetch_candles(
    symbol: str,
    timeframe: str = "1h",
    years: float = 3.0,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles for one symbol.
    Returns DataFrame with UTC DatetimeIndex, columns: open high low close volume.
    """
    cache_file = _cache_path(symbol, timeframe)

    if cache_file.exists() and not force_refresh:
        logger.info("[cache] binance/%s/%s ← %s", symbol, timeframe, cache_file.name)
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        logger.info("[cache] %d candles loaded", len(df))
        return df

    binance_sym = SYMBOL_MAP.get(symbol, symbol + "USDT")
    interval    = timeframe
    ms_per_bar  = MS_PER_INTERVAL.get(timeframe, 3_600_000)
    total_bars  = int(BARS_PER_YEAR.get(timeframe, 8_760) * years)

    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - total_bars * ms_per_bar

    logger.info(
        "[fetch] binance/%s/%s — requesting ~%d candles (%.1f yrs)",
        symbol, timeframe, total_bars, years,
    )

    session = requests.Session()
    session.headers.update({"User-Agent": "trade-bot-research/1.0"})

    all_rows: list = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol":    binance_sym,
            "interval":  interval,
            "startTime": current_start,
            "endTime":   end_ms,
            "limit":     MAX_PER_REQ,
        }
        try:
            resp = session.get(FUTURES_BASE + KLINES_PATH, params=params, timeout=15)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as exc:
            logger.error("[fetch] request error for %s: %s", symbol, exc)
            break

        if not raw:
            break

        all_rows.extend(raw)
        last_open_ms = int(raw[-1][0])
        current_start = last_open_ms + ms_per_bar

        logger.debug(
            "[fetch] %s/%s  chunk=%d  total=%d  last=%s",
            symbol, timeframe, len(raw), len(all_rows),
            pd.Timestamp(last_open_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d"),
        )

        if len(raw) < MAX_PER_REQ:
            break

        # Polite rate-limit pause (Binance allows 1200 weight/min; klines = 10)
        time.sleep(0.1)

    session.close()

    if not all_rows:
        logger.error("[fetch] no data returned for binance/%s/%s", symbol, timeframe)
        return pd.DataFrame()

    df = _parse_klines(all_rows)
    logger.info("[fetch] %d candles received for binance/%s/%s", len(df), symbol, timeframe)
    df.to_csv(cache_file)
    return df


def _parse_klines(raw: list) -> pd.DataFrame:
    """Parse Binance kline rows: [open_time, o, h, l, c, v, ...]."""
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
            logger.warning("Skipping malformed kline: %s", exc)
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df[~df.index.duplicated(keep="last")]


def load_all(
    symbols: List[str],
    timeframe: str = "1h",
    years: float = 3.0,
    force_refresh: bool = False,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch all symbols sequentially (polite to Binance rate limits).
    Returns {symbol: DataFrame}.
    """
    result: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = fetch_candles(sym, timeframe, years, force_refresh)
            if not df.empty:
                result[sym] = df
            else:
                logger.warning("[fetch] %s returned empty data — skipped", sym)
        except Exception as exc:
            logger.warning("[fetch] %s failed: %s — skipped", sym, exc)
    return result
