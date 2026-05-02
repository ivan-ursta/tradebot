"""
paper/binance_paper_runner.py
==============================
Live paper trading session on Binance USDT-M Futures public market data.

Strategy : DonchianBreakout + ADX(14) > 25 gate
Markets  : SOL, AVAX  (validated by 3yr WF-OOS research)
Data     : Binance USDT-M Futures 1h candles  (public REST, no credentials)
Fills    : Simulated at next bar's open price + slippage (mirrors backtester)
Orders   : No real orders ever submitted

Position model
--------------
  - One position per symbol (no pyramiding)
  - Entry at next bar open + slippage after signal bar
  - Exit at next bar open + slippage after exit signal
  - Sizing: risk 1% of equity per trade, stop = 2× ATR(14)
  - Hard stop: 2× ATR below entry (long) / above (short)

State
-----
  Persisted to data/paper_state.json after every bar.
  On restart the runner reloads open positions and continues.

Usage
-----
    cd /home/dell/trade
    python -m paper.binance_paper_runner                 # default $10,000
    python -m paper.binance_paper_runner --capital 5000  # custom capital
    python -m paper.binance_paper_runner --symbols SOL   # single market
    python -m paper.binance_paper_runner --reset         # wipe state, start fresh

Ctrl-C prints a session summary and exits cleanly.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from research.binance_data_loader import fetch_candles
from research.strategies.donchian_breakout import generate_signals, GATED_PARAMS

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
SYMBOLS        = ["SOL", "AVAX"]
TIMEFRAME      = "1h"
CANDLE_BARS    = 300           # lookback window for indicator warmup
FEE_RATE       = 0.0004        # 4 bps taker
SLIPPAGE_BPS   = 5.0           # 0.05% per side
RISK_PER_TRADE = 0.01          # 1% of equity per trade
ATR_SL_MULT    = 2.0           # stop = entry ± 2 × ATR
MIN_NOTIONAL   = 20.0          # minimum trade size ($)
STATE_FILE     = Path(__file__).parent.parent / "data" / "paper_state.json"
MS_PER_HOUR    = 3_600_000
POLL_INTERVAL  = 60            # seconds between candle checks

# ── ATR helper ─────────────────────────────────────────────────────────────

def _atr14(df: pd.DataFrame) -> pd.Series:
    h, lo, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - lo, (h - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


# ── State dataclasses ──────────────────────────────────────────────────────

@dataclass
class OpenPosition:
    symbol:      str
    side:        str           # "long" or "short"
    quantity:    float
    entry_price: float
    entry_fee:   float
    stop_loss:   float
    entry_time:  str           # ISO string

    @property
    def is_long(self) -> bool:
        return self.side == "long"


@dataclass
class ClosedTrade:
    symbol:      str
    side:        str
    entry_price: float
    exit_price:  float
    quantity:    float
    fees:        float
    net_pnl:     float
    return_pct:  float
    bars_held:   int
    exit_reason: str
    entry_time:  str
    exit_time:   str


@dataclass
class PendingEntry:
    """A signal has fired; we will fill on the NEXT bar's open."""
    symbol:   str
    side:     str
    signal_bar_time: str   # ISO of the bar where signal fired


@dataclass
class SessionState:
    starting_capital: float
    cash:             float
    positions:        Dict[str, dict]       = field(default_factory=dict)
    pending_entries:  Dict[str, dict]       = field(default_factory=dict)
    closed_trades:    List[dict]            = field(default_factory=list)
    last_bar_times:   Dict[str, str]        = field(default_factory=dict)
    start_time:       str                   = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, s: str) -> "SessionState":
        d = json.loads(s)
        return cls(**d)

    def equity(self, prices: Dict[str, float]) -> float:
        equity = self.cash
        for sym, pos_d in self.positions.items():
            pos  = OpenPosition(**pos_d)
            px   = prices.get(sym, pos.entry_price)
            if pos.is_long:
                equity += (px - pos.entry_price) * pos.quantity
            else:
                equity += (pos.entry_price - px) * pos.quantity
        return equity


# ── Sizing ─────────────────────────────────────────────────────────────────

def size_position(
    equity: float, entry_price: float, atr: float, side: str
) -> tuple[float, float]:
    """
    Returns (quantity, stop_loss_price).
    Risk = RISK_PER_TRADE × equity.
    Stop distance = ATR_SL_MULT × ATR.
    """
    stop_dist = ATR_SL_MULT * atr
    if stop_dist <= 0:
        return 0.0, 0.0
    risk_dollars = equity * RISK_PER_TRADE
    qty = risk_dollars / stop_dist
    # Apply slippage to entry so cost is realistic
    slip = SLIPPAGE_BPS / 10_000
    fill_price = entry_price * (1 + slip) if side == "long" else entry_price * (1 - slip)
    # Cap at 20× risk-to-notional (sanity)
    max_qty = equity * 0.20 / fill_price
    qty = min(qty, max_qty)
    if qty * fill_price < MIN_NOTIONAL:
        return 0.0, 0.0
    stop = (fill_price - stop_dist) if side == "long" else (fill_price + stop_dist)
    return qty, stop


# ── Display ────────────────────────────────────────────────────────────────

def _bar(value: float, width: int = 20, scale: float = 100.0) -> str:
    filled = min(width, max(0, int(abs(value) / scale * width)))
    char   = "█" if value >= 0 else "▒"
    return char * filled + "░" * (width - filled)


def print_status(state: SessionState, prices: Dict[str, float], bar_time: str) -> None:
    eq     = state.equity(prices)
    ret    = (eq - state.starting_capital) / state.starting_capital * 100
    trades = [ClosedTrade(**t) for t in state.closed_trades]
    wins   = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    pf     = (sum(t.net_pnl for t in wins) / abs(sum(t.net_pnl for t in losses))
              if losses and sum(t.net_pnl for t in losses) != 0 else float("inf"))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'═'*64}")
    print(f"  PAPER SESSION  │  {now}")
    print(f"  Strategy: DonchianBreakout + ADX>25  │  SOL / AVAX")
    print(f"{'─'*64}")
    print(f"  Capital    : ${state.starting_capital:,.2f}")
    print(f"  Equity     : ${eq:,.2f}  ({ret:+.2f}%)  {_bar(ret, 20, 50)}")
    print(f"  Cash       : ${state.cash:,.2f}")
    print(f"  Trades     : {len(trades)}  wins={len(wins)}  losses={len(losses)}"
          f"  PF={pf:.2f}"
          + (f"  WR={len(wins)/len(trades)*100:.0f}%" if trades else ""))
    print(f"  Last bar   : {bar_time}")
    print(f"{'─'*64}")

    if state.positions:
        print("  OPEN POSITIONS:")
        for sym, pos_d in state.positions.items():
            pos = OpenPosition(**pos_d)
            px  = prices.get(sym, pos.entry_price)
            upnl = ((px - pos.entry_price) if pos.is_long
                    else (pos.entry_price - px)) * pos.quantity
            print(f"    {sym:<5}  {pos.side:<5}  qty={pos.quantity:.4f}"
                  f"  entry={pos.entry_price:.4f}  now={px:.4f}"
                  f"  uPnL={upnl:+.2f}  SL={pos.stop_loss:.4f}")
    else:
        print("  OPEN POSITIONS: none")

    if state.pending_entries:
        print("  PENDING (fill on next open):")
        for sym, pe_d in state.pending_entries.items():
            pe = PendingEntry(**pe_d)
            print(f"    {sym:<5}  {pe.side}  → fill at next bar open")

    if trades:
        print(f"{'─'*64}")
        print("  RECENT TRADES (last 5):")
        for t in trades[-5:]:
            print(f"    {t.symbol:<5}  {t.side:<5}  "
                  f"entry={t.entry_price:.4f}  exit={t.exit_price:.4f}"
                  f"  pnl={t.net_pnl:+.2f}  ({t.return_pct:+.2f}%)"
                  f"  [{t.exit_reason}]")

    print(f"{'═'*64}")


# ── Core bar processing ────────────────────────────────────────────────────

def process_bar(
    sym: str,
    df: pd.DataFrame,
    state: SessionState,
    sigs: pd.DataFrame,
) -> None:
    """
    Process one newly closed bar for `sym`.
    Mutates state in place.
    """
    if len(df) < 2:
        return

    # Current bar (just closed) and the NEXT bar (where we fill)
    # In live paper mode "next bar" = the bar that just opened (df.iloc[-1])
    # since we're at the boundary.  Entry fills at the current bar's open.
    cur_bar  = df.iloc[-1]
    cur_open = float(cur_bar["open"])
    cur_high = float(cur_bar["high"])
    cur_low  = float(cur_bar["low"])
    cur_close = float(cur_bar["close"])
    bar_time = str(df.index[-1])

    atr_series = _atr14(df)
    atr = float(atr_series.iloc[-1])

    slip = SLIPPAGE_BPS / 10_000
    equity = state.equity({sym: cur_close})

    # ── 1. Fill any pending entry from the PREVIOUS bar ──────────────────
    if sym in state.pending_entries:
        pe   = PendingEntry(**state.pending_entries.pop(sym))
        side = pe.side
        fill_px = cur_open * (1 + slip) if side == "long" else cur_open * (1 - slip)
        qty, stop = size_position(equity, fill_px, atr, side)
        if qty > 0 and sym not in state.positions:
            fee = fill_px * qty * FEE_RATE
            state.cash -= (fill_px * qty + fee) if side == "long" else -(fill_px * qty - fee)
            state.positions[sym] = asdict(OpenPosition(
                symbol=sym, side=side, quantity=qty,
                entry_price=fill_px, entry_fee=fee, stop_loss=stop,
                entry_time=bar_time,
            ))
            logger.info("[PAPER] ENTRY  %s %-5s qty=%.4f @ %.4f  SL=%.4f",
                        sym, side, qty, fill_px, stop)

    # ── 2. Check stop-loss and exit signals on open position ──────────────
    if sym in state.positions:
        pos = OpenPosition(**state.positions[sym])
        close_reason: Optional[str] = None
        close_px = cur_close

        # Hard stop (intra-bar)
        if pos.is_long and cur_low <= pos.stop_loss:
            close_reason = "stop_loss"
            close_px = min(pos.stop_loss, cur_open)   # gap fill at open if gapped through
        elif not pos.is_long and cur_high >= pos.stop_loss:
            close_reason = "stop_loss"
            close_px = max(pos.stop_loss, cur_open)

        # Strategy exit signal (Donchian channel break or EMA200 break)
        if close_reason is None:
            sig_row = sigs.iloc[-1]
            if pos.is_long and bool(sig_row.get("exit", False)):
                close_reason = "strategy_exit"
            elif not pos.is_long and bool(sig_row.get("short_exit", False)):
                close_reason = "strategy_exit"

        if close_reason:
            exit_slip = SLIPPAGE_BPS / 10_000
            exit_px = close_px * (1 - exit_slip) if pos.is_long else close_px * (1 + exit_slip)
            fee = exit_px * pos.quantity * FEE_RATE

            if pos.is_long:
                state.cash += exit_px * pos.quantity - fee
                gross_pnl = (exit_px - pos.entry_price) * pos.quantity
            else:
                state.cash -= exit_px * pos.quantity + fee
                gross_pnl = (pos.entry_price - exit_px) * pos.quantity

            net_pnl  = gross_pnl - fee - pos.entry_fee
            cost     = pos.entry_price * pos.quantity
            ret_pct  = net_pnl / cost * 100 if cost > 0 else 0.0

            # Rough bars held
            try:
                entry_ts = pd.Timestamp(pos.entry_time)
                exit_ts  = df.index[-1]
                if entry_ts.tzinfo is None:
                    entry_ts = entry_ts.tz_localize("UTC")
                bars_held = max(1, int((exit_ts - entry_ts).total_seconds() / 3600))
            except Exception:
                bars_held = 1

            state.closed_trades.append(asdict(ClosedTrade(
                symbol=sym, side=pos.side,
                entry_price=pos.entry_price, exit_price=exit_px,
                quantity=pos.quantity, fees=fee + pos.entry_fee,
                net_pnl=net_pnl, return_pct=ret_pct,
                bars_held=bars_held, exit_reason=close_reason,
                entry_time=pos.entry_time, exit_time=bar_time,
            )))
            del state.positions[sym]
            logger.info("[PAPER] EXIT   %s %-5s @ %.4f  pnl=%+.2f (%+.2f%%)  [%s]",
                        sym, pos.side, exit_px, net_pnl, ret_pct, close_reason)

    # ── 3. Check for new entry signal ─────────────────────────────────────
    if sym not in state.positions and sym not in state.pending_entries:
        sig_row = sigs.iloc[-1]
        if bool(sig_row.get("entry", False)):
            state.pending_entries[sym] = asdict(PendingEntry(
                symbol=sym, side="long", signal_bar_time=bar_time))
            logger.info("[PAPER] SIGNAL %s LONG  → fill next open", sym)
        elif bool(sig_row.get("short_entry", False)):
            state.pending_entries[sym] = asdict(PendingEntry(
                symbol=sym, side="short", signal_bar_time=bar_time))
            logger.info("[PAPER] SIGNAL %s SHORT → fill next open", sym)

    state.last_bar_times[sym] = bar_time


# ── Session summary ────────────────────────────────────────────────────────

def print_final_summary(state: SessionState, prices: Dict[str, float]) -> None:
    trades = [ClosedTrade(**t) for t in state.closed_trades]
    eq     = state.equity(prices)
    ret    = (eq - state.starting_capital) / state.starting_capital * 100
    wins   = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    pf     = (sum(t.net_pnl for t in wins) / abs(sum(t.net_pnl for t in losses))
              if losses and sum(t.net_pnl for t in losses) != 0 else float("inf"))
    exp    = float(np.mean([t.return_pct for t in trades])) if trades else 0.0
    avg_h  = float(np.mean([t.bars_held for t in trades])) if trades else 0.0

    print(f"\n{'═'*64}")
    print("  PAPER SESSION FINAL SUMMARY")
    print(f"{'─'*64}")
    print(f"  Strategy  : DonchianBreakout + ADX>25")
    print(f"  Markets   : {', '.join(SYMBOLS)}")
    print(f"  Start     : {state.start_time}")
    print(f"  End       : {datetime.now(timezone.utc).isoformat()}")
    print(f"{'─'*64}")
    print(f"  Capital   : ${state.starting_capital:,.2f}")
    print(f"  Equity    : ${eq:,.2f}  ({ret:+.2f}%)")
    print(f"  Trades    : {len(trades)}")
    if trades:
        print(f"  Win rate  : {len(wins)/len(trades)*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
        print(f"  P. Factor : {pf:.2f}")
        print(f"  Expectancy: {exp:+.3f}%")
        print(f"  Avg hold  : {avg_h:.1f} bars")
        print(f"{'─'*64}")
        print("  All trades:")
        for t in trades:
            print(f"    {t.symbol:<5} {t.side:<5} "
                  f"{t.entry_time[:10]}→{t.exit_time[:10]} "
                  f"pnl={t.net_pnl:+7.2f} ({t.return_pct:+.2f}%) [{t.exit_reason}]")
    print(f"{'═'*64}\n")


# ── Main loop ──────────────────────────────────────────────────────────────

def run(
    symbols: List[str],
    starting_capital: float,
    reset: bool,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load or create state
    if not reset and STATE_FILE.exists():
        try:
            state = SessionState.from_json(STATE_FILE.read_text())
            print(f"[resume] Loaded existing session from {STATE_FILE}")
        except Exception as exc:
            print(f"[warn] Could not load state ({exc}), starting fresh")
            state = None
    else:
        state = None

    if state is None:
        state = SessionState(
            starting_capital=starting_capital,
            cash=starting_capital,
            start_time=datetime.now(timezone.utc).isoformat(),
        )
        print(f"[start] New paper session — capital=${starting_capital:,.2f}")

    # Graceful shutdown
    shutdown_flag = {"stop": False}

    def _on_signal(signum, frame):
        shutdown_flag["stop"] = True
        print("\n[shutdown] Ctrl-C received, wrapping up…")

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    print(f"[run] Polling every {POLL_INTERVAL}s for new 1h bars. Ctrl-C to stop.\n")

    last_prices: Dict[str, float] = {}

    while not shutdown_flag["stop"]:
        any_new = False

        for sym in symbols:
            try:
                df = fetch_candles(sym, TIMEFRAME, years=CANDLE_BARS / 8760,
                                   force_refresh=True)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", sym, exc)
                continue

            if df.empty:
                continue

            last_prices[sym] = float(df["close"].iloc[-1])
            bar_time = str(df.index[-1])

            # Only process if this bar is new
            if state.last_bar_times.get(sym) == bar_time:
                continue

            any_new = True
            sigs = generate_signals(df, **GATED_PARAMS)
            process_bar(sym, df, state, sigs)

        if any_new:
            # Save state
            STATE_FILE.write_text(state.to_json())
            # Derive display bar time from the most recently processed symbol
            bar_display = max(state.last_bar_times.values()) if state.last_bar_times else "—"
            print_status(state, last_prices, bar_display)

        if not shutdown_flag["stop"]:
            time.sleep(POLL_INTERVAL)

    # Final summary
    print_final_summary(state, last_prices)
    STATE_FILE.write_text(state.to_json())
    print(f"[done] State saved to {STATE_FILE}")


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Binance paper trading — DonchianBreakout + ADX>25 on SOL/AVAX"
    )
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--capital", type=float, default=10_000.0,
                        help="Starting paper capital in USD (default: 10000)")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe existing session state and start fresh")
    args = parser.parse_args()
    run(args.symbols, args.capital, args.reset)


if __name__ == "__main__":
    main()
