"""
utils/time_utils.py
===================
Time and date utilities.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def datetime_to_ms(dt: datetime) -> int:
    return int(to_utc(dt).timestamp() * 1000)


def timeframe_to_seconds(tf: str) -> int:
    mapping = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
    }
    return mapping.get(tf, 900)


def timeframe_to_ms(tf: str) -> int:
    return timeframe_to_seconds(tf) * 1000


def bars_ago(tf: str, n: int) -> datetime:
    """Return the datetime n bars ago for a given timeframe."""
    return utcnow() - timedelta(seconds=timeframe_to_seconds(tf) * n)
