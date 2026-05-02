"""
indicators/microstructure.py
============================
Microstructure features: spread, mid-price, order book imbalance.
These are computed from order book snapshots when available;
otherwise OHLCV-based approximations are used.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from core.models import OrderBook


# ---------------------------------------------------------------------------
# Order book based (real-time)
# ---------------------------------------------------------------------------


def compute_spread(book: OrderBook) -> Optional[float]:
    """Absolute bid-ask spread."""
    return book.spread


def compute_spread_fraction(book: OrderBook) -> Optional[float]:
    """Spread as fraction of mid-price."""
    return book.spread_fraction


def order_book_imbalance(book: OrderBook, depth: int = 5) -> float:
    """
    Top-N level imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol).
    Range: -1 (ask-heavy) to +1 (bid-heavy).
    """
    bid_vol = sum(lvl.size for lvl in book.bids[:depth])
    ask_vol = sum(lvl.size for lvl in book.asks[:depth])
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def weighted_mid_price(book: OrderBook, depth: int = 1) -> Optional[float]:
    """
    Volume-weighted mid from top N levels on each side.
    More stable than simple mid during rapid price movement.
    """
    if not book.bids or not book.asks:
        return None
    bid_levels = book.bids[:depth]
    ask_levels = book.asks[:depth]
    bid_vol = sum(l.size for l in bid_levels)
    ask_vol = sum(l.size for l in ask_levels)
    total = bid_vol + ask_vol
    if total == 0:
        return book.mid_price
    bid_price = sum(l.price * l.size for l in bid_levels)
    ask_price = sum(l.price * l.size for l in ask_levels)
    return (bid_price + ask_price) / total


# ---------------------------------------------------------------------------
# OHLCV-based approximations (no book required)
# ---------------------------------------------------------------------------


def bar_spread_estimate(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    Corwin-Schultz-style spread estimate from daily high/low.
    Very rough approximation; prefer real book data when available.
    """
    log_hl = np.log(high / low)
    spread = 2 * (np.exp(log_hl / 2) - 1) / (1 + np.exp(log_hl / 2))
    return spread


def price_impact_estimate(
    close: pd.Series,
    volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    """
    Amihud illiquidity ratio: |return| / volume.
    Higher = larger price impact per unit of volume (less liquid).
    """
    ret = close.pct_change().abs()
    avg_vol = volume.rolling(window=period).mean().replace(0, np.nan)
    return ret / avg_vol
