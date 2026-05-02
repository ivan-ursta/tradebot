"""
research/engine.py
==================
Lightweight event-driven backtesting engine (research edition).

Strategy contract
-----------------
A strategy is a callable:  signals(df) -> pd.DataFrame

Required columns:
  'entry'        — go long on the NEXT bar's open
  'exit'         — close long on the NEXT bar's open

Optional columns (bidirectional strategies):
  'short_entry'  — go short on the NEXT bar's open
  'short_exit'   — close short on the NEXT bar's open

Position model
--------------
- One position at a time (no pyramiding)
- 100 % of equity per trade (research mode)
- Long  entry fill : next_open × (1 + slippage)
- Long  exit  fill : next_open × (1 - slippage)
- Short entry fill : next_open × (1 - slippage)   ← sell at slightly below open
- Short exit  fill : next_open × (1 + slippage)   ← buy back at slightly above open
- Fees        : taker_rate applied on entry and exit notional
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

LONG = "long"
SHORT = "short"


@dataclass
class TradeRecord:
    symbol: str
    side: str              # 'long' or 'short'
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    return_pct: float      # net of fees + slippage
    bars_held: int


@dataclass
class BacktestResult:
    symbol: str = ""
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    initial_capital: float = 10_000.0

    @property
    def trade_returns(self) -> list[float]:
        return [t.return_pct for t in self.trades]


def run_backtest(
    df: pd.DataFrame,
    signals: pd.DataFrame,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0004,
    slippage_bps: float = 5.0,
) -> BacktestResult:
    """
    Execute a backtest supporting both long-only and bidirectional strategies.

    Parameters
    ----------
    df        : OHLCV DataFrame (UTC DatetimeIndex)
    signals   : DataFrame with 'entry'/'exit' columns; optionally 'short_entry'/'short_exit'
    """
    if df.empty or signals.empty:
        return BacktestResult(symbol=symbol, initial_capital=initial_capital)

    slip = slippage_bps / 10_000
    round_trip_cost = fee_rate * 2

    opens = df["open"].values
    closes = df["close"].values
    ts = df.index

    entry_arr = signals["entry"].fillna(False).values
    exit_arr = signals["exit"].fillna(False).values

    has_short = "short_entry" in signals.columns and "short_exit" in signals.columns
    short_entry_arr = signals["short_entry"].fillna(False).values if has_short else None
    short_exit_arr = signals["short_exit"].fillna(False).values if has_short else None

    n = len(df)
    equity = initial_capital
    equity_pts: list[tuple] = []
    trades: list[TradeRecord] = []

    side: Optional[str] = None
    entry_price = 0.0
    entry_time: Optional[pd.Timestamp] = None
    entry_bar = 0

    for i in range(n - 1):
        equity_pts.append((ts[i], equity))

        if side is None:
            # Check long entry
            if entry_arr[i]:
                entry_price = opens[i + 1] * (1.0 + slip)
                entry_time = ts[i + 1]
                entry_bar = i + 1
                side = LONG
            # Check short entry (only if not just entered long)
            elif has_short and short_entry_arr[i]:
                entry_price = opens[i + 1] * (1.0 - slip)
                entry_time = ts[i + 1]
                entry_bar = i + 1
                side = SHORT

        elif side == LONG:
            if exit_arr[i]:
                exit_price = opens[i + 1] * (1.0 - slip)
                raw = (exit_price - entry_price) / entry_price
                net = raw - round_trip_cost
                trades.append(TradeRecord(
                    symbol=symbol, side=LONG,
                    entry_time=entry_time, exit_time=ts[i + 1],
                    entry_price=entry_price, exit_price=exit_price,
                    return_pct=net * 100, bars_held=i + 1 - entry_bar,
                ))
                equity *= (1.0 + net)
                side = None

        elif side == SHORT:
            if has_short and short_exit_arr[i]:
                exit_price = opens[i + 1] * (1.0 + slip)
                # Short P&L: profit when price falls
                raw = (entry_price - exit_price) / entry_price
                net = raw - round_trip_cost
                trades.append(TradeRecord(
                    symbol=symbol, side=SHORT,
                    entry_time=entry_time, exit_time=ts[i + 1],
                    entry_price=entry_price, exit_price=exit_price,
                    return_pct=net * 100, bars_held=i + 1 - entry_bar,
                ))
                equity *= (1.0 + net)
                side = None

    # Force-close any open position at last bar
    if side == LONG:
        exit_price = closes[-1] * (1.0 - slip)
        raw = (exit_price - entry_price) / entry_price
        net = raw - round_trip_cost
        trades.append(TradeRecord(
            symbol=symbol, side=LONG,
            entry_time=entry_time, exit_time=ts[-1],
            entry_price=entry_price, exit_price=exit_price,
            return_pct=net * 100, bars_held=n - 1 - entry_bar,
        ))
        equity *= (1.0 + net)
    elif side == SHORT:
        exit_price = closes[-1] * (1.0 + slip)
        raw = (entry_price - exit_price) / entry_price
        net = raw - round_trip_cost
        trades.append(TradeRecord(
            symbol=symbol, side=SHORT,
            entry_time=entry_time, exit_time=ts[-1],
            entry_price=entry_price, exit_price=exit_price,
            return_pct=net * 100, bars_held=n - 1 - entry_bar,
        ))
        equity *= (1.0 + net)

    equity_pts.append((ts[-1], equity))

    eq = pd.Series(
        [v for _, v in equity_pts],
        index=[t for t, _ in equity_pts],
        name="equity",
    )
    return BacktestResult(
        symbol=symbol,
        trades=trades,
        equity_curve=eq,
        initial_capital=initial_capital,
    )
