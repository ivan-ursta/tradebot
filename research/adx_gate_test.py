"""
research/adx_gate_test.py
==========================
Decision gate test: does requiring ADX > 25 at entry recover the edge
on SOL and AVAX?

Rule added
----------
  ADX(14) > 25 at entry bar — all other parameters unchanged.

Pass criteria (per market)
--------------------------
  OOS PF  ≥ 1.30  on every walk-forward window with ≥ 10 trades
  ≥ 3 / 5 WF windows have PF ≥ 1.30
  Combined WF-OOS PF ≥ 1.30
  ≥ 30 combined OOS trades

If BOTH markets pass → proceed.
If either fails → reject the strategy.

Usage
-----
    cd /home/dell/trade
    python -m research.adx_gate_test
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from research.engine import run_backtest, BacktestResult, TradeRecord
from research.walk_forward import run_walk_forward
from research.metrics import compute, ResearchMetrics
from research.strategies.donchian_breakout import generate_signals, DEFAULT_PARAMS, NAME as DONCHIAN

CACHE_DIR   = Path(__file__).parent.parent / "data" / "cache"
SYMBOLS     = ["SOL", "AVAX"]
TIMEFRAME   = "1h"
INITIAL_CAP = 10_000.0
FEE_RATE    = 0.0004
SLIP_BPS    = 5.0
WF_WINDOWS  = 5
TRAIN_FRAC  = 0.6

ADX_THRESHOLD = 25   # the one new rule

# Pass criteria
PASS_PF          = 1.30
PASS_MIN_TRADES  = 30   # combined OOS
PASS_MIN_WIN_WF  = 3    # of 5 windows must have PF ≥ 1.30 (when ≥ 10 trades)


# ── ADX helper (Wilder's method, same as regime_analysis.py) ──────────────

def _wilder_ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(alpha=1 / p, adjust=False).mean()


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, lo, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - lo,
        (h - c.shift(1)).abs(),
        (lo - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    plus_dm  = (h - h.shift(1)).clip(lower=0).where(
        (h - h.shift(1)) > (lo.shift(1) - lo), 0)
    minus_dm = (lo.shift(1) - lo).clip(lower=0).where(
        (lo.shift(1) - lo) > (h - h.shift(1)), 0)
    atr_s   = _wilder_ema(tr, period)
    plus_di  = 100 * _wilder_ema(plus_dm,  period) / atr_s.replace(0, np.nan)
    minus_di = 100 * _wilder_ema(minus_dm, period) / atr_s.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() /
          (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    return _wilder_ema(dx, period)


# ── Signal wrappers ───────────────────────────────────────────────────────

def baseline_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Original DonchianBreakout — no ADX gate."""
    return generate_signals(df, **DEFAULT_PARAMS)


def gated_signals(df: pd.DataFrame) -> pd.DataFrame:
    """DonchianBreakout + ADX > 25 gate (the one new rule)."""
    sigs = generate_signals(df, **DEFAULT_PARAMS)
    adx  = compute_adx(df, 14)
    ok   = adx > ADX_THRESHOLD
    sigs["entry"]       = sigs["entry"]       & ok
    sigs["short_entry"] = sigs["short_entry"] & ok
    return sigs


# ── Helpers ───────────────────────────────────────────────────────────────

def load_cached(sym: str) -> pd.DataFrame:
    p = CACHE_DIR / f"binance_{sym}_1h.csv"
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def _pf(rets: List[float]) -> float:
    wins   = sum(r for r in rets if r > 0)
    losses = abs(sum(r for r in rets if r <= 0))
    return wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)


def _maxdd(eq: pd.Series) -> float:
    roll = eq.cummax()
    return abs(float(((eq - roll) / roll).min())) * 100


def _sharpe(eq: pd.Series) -> float:
    r = eq.pct_change().dropna()
    return float(r.mean() / r.std(ddof=1) * math.sqrt(8760)) if r.std(ddof=1) > 0 else 0.0


# ── Printing helpers ──────────────────────────────────────────────────────

SEP  = "=" * 80
SEP2 = "─" * 80


def _print_wf_table(label: str, wf, symbol: str) -> List[dict]:
    print(f"\n  {label}:")
    hdr = f"  {'Win':>4}  {'IS Ret%':>8}  {'OOS Ret%':>9}  {'OOS PF':>7}  {'OOS DD%':>8}  {'Trades':>7}  Pass?"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    rows = []
    for w in wf.windows:
        oos       = w.oos_metrics
        n_trades  = int(oos.trades)
        pf        = float(oos.profit_factor)
        if n_trades < 10:
            flag = "skip<10t"
        elif pf >= PASS_PF:
            flag = "PASS"
        else:
            flag = "FAIL"
        print(
            f"  {w.window_num:>4}  {w.is_metrics.total_return_pct:>+8.2f}%  "
            f"{oos.total_return_pct:>+9.2f}%  {pf:>7.2f}  "
            f"{oos.max_drawdown_pct:>7.2f}%  {n_trades:>7d}  {flag}"
        )
        rows.append(dict(
            window=w.window_num, oos_return=oos.total_return_pct,
            oos_pf=float(oos.profit_factor), oos_dd=oos.max_drawdown_pct,
            oos_trades=int(oos.trades),
        ))
    c = wf.combined_oos
    if c:
        print("  " + "-" * (len(hdr) - 2))
        print(
            f"  {'COMB':>4}  {'':>8}   {c.total_return_pct:>+9.2f}%  "
            f"{c.profit_factor:>7.2f}  {c.max_drawdown_pct:>7.2f}%  "
            f"{c.trades:>7d}"
        )
    return rows


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{SEP}")
    print("ADX GATE TEST — DonchianBreakout + ADX(14) > 25 at entry")
    print(f"Markets : {SYMBOLS}")
    print(f"Rule    : entry signals additionally require ADX(14) > {ADX_THRESHOLD}")
    print(f"Pass    : combined WF-OOS PF ≥ {PASS_PF}, ≥ {PASS_MIN_TRADES} trades,")
    print(f"          ≥ {PASS_MIN_WIN_WF}/5 windows with PF ≥ {PASS_PF} (when ≥ 10 trades)")
    print(SEP)

    verdicts: Dict[str, bool] = {}

    for sym in SYMBOLS:
        print(f"\n{SEP2}")
        print(f"  {sym}")
        print(SEP2)

        df = load_cached(sym)
        print(f"  Data: {len(df)} bars  "
              f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")

        # ── Baseline (for comparison) ─────────────────────────────────────
        wf_base = run_walk_forward(
            df, baseline_signals, symbol=sym, strategy="Baseline",
            n_windows=WF_WINDOWS, train_frac=TRAIN_FRAC, timeframe=TIMEFRAME,
            initial_capital=INITIAL_CAP, fee_rate=FEE_RATE, slippage_bps=SLIP_BPS,
        )
        _print_wf_table("Baseline (no ADX gate)", wf_base, sym)

        # ── Gated ────────────────────────────────────────────────────────
        wf_gate = run_walk_forward(
            df, gated_signals, symbol=sym, strategy="ADX-gated",
            n_windows=WF_WINDOWS, train_frac=TRAIN_FRAC, timeframe=TIMEFRAME,
            initial_capital=INITIAL_CAP, fee_rate=FEE_RATE, slippage_bps=SLIP_BPS,
        )
        rows = _print_wf_table(f"ADX-gated (ADX > {ADX_THRESHOLD})", wf_gate, sym)

        # ── Trade count delta ────────────────────────────────────────────
        base_trades = sum(w.oos_metrics.trades for w in wf_base.windows)
        gate_trades = sum(w.oos_metrics.trades for w in wf_gate.windows)
        pct_kept    = gate_trades / base_trades * 100 if base_trades > 0 else 0
        print(f"\n  Trade count (OOS total): {base_trades} → {gate_trades} "
              f"({pct_kept:.0f}% kept, {base_trades - gate_trades} filtered out)")

        # ── Pass / fail ──────────────────────────────────────────────────
        comb = wf_gate.combined_oos
        comb_pf     = comb.profit_factor if comb else 0.0
        comb_trades = comb.trades        if comb else 0
        win_windows = sum(
            1 for r in rows
            if r["oos_trades"] >= 10 and r["oos_pf"] >= PASS_PF
        )
        eligible_windows = sum(1 for r in rows if r["oos_trades"] >= 10)

        print(f"\n  ── Verdict for {sym} ──")
        print(f"  Combined WF-OOS PF    : {comb_pf:.2f}  (need ≥ {PASS_PF})")
        print(f"  Combined OOS trades   : {comb_trades}  (need ≥ {PASS_MIN_TRADES})")
        print(f"  Windows PF ≥ {PASS_PF}    : {win_windows}/{eligible_windows} eligible  "
              f"(need ≥ {PASS_MIN_WIN_WF})")

        passed = (
            comb_pf     >= PASS_PF
            and comb_trades >= PASS_MIN_TRADES
            and win_windows >= PASS_MIN_WIN_WF
        )
        verdicts[sym] = passed
        print(f"  → {'✓ PASS' if passed else '✗ FAIL'}")

    # ── Side-by-side comparison table ─────────────────────────────────────
    print(f"\n{SEP}")
    print("COMPARISON — Baseline vs ADX-gated (Combined WF-OOS)")
    print(SEP)

    col = f"  {'Symbol':<6}  {'Version':<16}  {'Return%':>9}  {'Sharpe':>7}  "  \
          f"{'MaxDD%':>7}  {'PF':>6}  {'Trades':>7}  {'WinR%':>7}"
    print(col)
    print("  " + "-" * (len(col) - 2))

    for sym in SYMBOLS:
        df = load_cached(sym)
        for label, fn in [("Baseline", baseline_signals), (f"ADX>{ADX_THRESHOLD}", gated_signals)]:
            sigs   = fn(df)
            result = run_backtest(df, sigs, sym, INITIAL_CAP, FEE_RATE, SLIP_BPS)
            rets   = result.trade_returns
            eq     = result.equity_curve
            if not rets or eq.empty:
                continue
            tot_ret  = (eq.iloc[-1] - INITIAL_CAP) / INITIAL_CAP * 100
            wins     = [r for r in rets if r > 0]
            losses   = [r for r in rets if r <= 0]
            pf       = _pf(rets)
            win_rate = len(wins) / len(rets) * 100 if rets else 0
            sharpe   = _sharpe(eq)
            maxdd    = _maxdd(eq)
            print(
                f"  {sym:<6}  {label:<16}  {tot_ret:>+9.2f}%  {sharpe:>7.2f}  "
                f"{maxdd:>7.2f}%  {pf:>6.2f}  {len(rets):>7d}  {win_rate:>7.1f}%"
            )
        print()

    # ── Overall verdict ───────────────────────────────────────────────────
    print(SEP)
    print("FINAL VERDICT")
    print(SEP)
    for sym, passed in verdicts.items():
        print(f"  {sym:6s}: {'PASS ✓' if passed else 'FAIL ✗'}")
    print()

    all_pass = all(verdicts.values())
    if all_pass:
        print("  OUTCOME: Both markets PASS.")
        print("  → ADX gate recovers viable edge on SOL and AVAX.")
        print("  → Next step: add ADX gate to donchian_breakout.py as a named parameter,")
        print(f"    trade SOL + AVAX only, run paper trading on Binance testnet.")
    else:
        failed = [s for s, p in verdicts.items() if not p]
        print(f"  OUTCOME: {', '.join(failed)} FAIL{'s' if len(failed)==1 else ''}.")
        print("  → The strategy does not meet the minimum bar even on its best markets.")
        print("  → Decision: reject DonchianBreakout as-is.")
        print("  → Do not add more filters. Research a different strategy.")
    print(SEP)


if __name__ == "__main__":
    main()
