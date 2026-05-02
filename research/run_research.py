"""
research/run_research.py
========================
Main research runner — Step 1 through 7 of the research protocol.

Usage:
    cd /home/dell/trade
    python -m research.run_research
    python -m research.run_research --refresh   # force re-download data
    python -m research.run_research --symbol BTC ETH

What it does:
  1. Fetches 2 years of 1h candles for each symbol (cached to disk)
  2. Runs three strategies: DonchianBreakout, VolatilityExpansion, MomentumContinuation
  3. For each (symbol, strategy): IS / OOS split + walk-forward (5 windows)
  4. Prints a cross-market summary table
  5. Identifies any strategy × symbol pairs that pass the edge screen
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from research.data_loader import load_all
from research.engine import run_backtest
from research.metrics import ResearchMetrics, compute
from research.walk_forward import run_walk_forward
from research.strategies.donchian_breakout import (
    generate_signals as donchian_signals,
    make_signal_fn as donchian_fn,
    NAME as DONCHIAN,
)
from research.strategies.volatility_expansion import (
    generate_signals as volexp_signals,
    make_signal_fn as volexp_fn,
    NAME as VOLEXP,
)
from research.strategies.momentum_continuation import (
    generate_signals as momcont_signals,
    make_signal_fn as momcont_fn,
    NAME as MOMCONT,
)
from utils.logger import setup_logging

logger = logging.getLogger(__name__)

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "ARB", "OP"]
TIMEFRAME = "1h"
YEARS = 2.0
INITIAL_CAPITAL = 10_000.0
FEE_RATE = 0.0004
SLIPPAGE_BPS = 5.0
WF_WINDOWS = 5
TRAIN_FRAC = 0.6   # IS split


STRATEGIES = [
    (DONCHIAN,  donchian_signals,  donchian_fn()),
    (VOLEXP,    volexp_signals,    volexp_fn()),
    (MOMCONT,   momcont_signals,   momcont_fn()),
]


def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """60/40 IS/OOS split."""
    cut = int(len(df) * TRAIN_FRAC)
    return df.iloc[:cut], df.iloc[cut:]


def _run_strategy(
    name: str,
    signal_fn_simple,
    signal_fn_wf,
    df: pd.DataFrame,
    symbol: str,
):
    """Return (IS metrics, OOS metrics, WF-combined metrics, WalkForwardResult)."""
    is_df, oos_df = _split(df)

    # IS
    is_sigs = signal_fn_simple(is_df)
    is_result = run_backtest(is_df, is_sigs, symbol, INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_BPS)
    is_m = compute(is_result, TIMEFRAME, symbol, name, "IS")

    # OOS
    oos_sigs = signal_fn_simple(oos_df)
    oos_result = run_backtest(oos_df, oos_sigs, symbol, INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_BPS)
    oos_m = compute(oos_result, TIMEFRAME, symbol, name, "OOS")

    # Walk-forward
    wf = run_walk_forward(
        df, signal_fn_wf, symbol=symbol, strategy=name,
        n_windows=WF_WINDOWS, train_frac=TRAIN_FRAC, timeframe=TIMEFRAME,
        initial_capital=INITIAL_CAPITAL, fee_rate=FEE_RATE, slippage_bps=SLIPPAGE_BPS,
    )

    print(wf.summary())
    return is_m, oos_m, wf.combined_oos, wf


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    col_order = ["symbol", "strategy", "period", "return%", "sharpe", "sortino",
                 "maxDD%", "PF", "winRate%", "expect%", "trades", "edge?", "note"]
    df = df.reindex(columns=[c for c in col_order if c in df.columns])
    print(df.to_string(index=False))


def _print_edge_summary(candidates: list[ResearchMetrics]) -> None:
    if not candidates:
        print("\n" + "=" * 60)
        print("EDGE SCREEN: No strategy × symbol pair passed the screen.")
        print("Criteria: PF≥1.3, Sharpe≥0.5, MaxDD≤30%, Trades≥30")
        print("=" * 60)
        return

    print("\n" + "=" * 60)
    print(f"EDGE SCREEN: {len(candidates)} candidate(s) passed:")
    for m in candidates:
        print(
            f"  {m.strategy:<26} {m.symbol:<5}  "
            f"return={m.total_return_pct:+.2f}%  "
            f"sharpe={m.sharpe:.2f}  PF={m.profit_factor:.2f}  "
            f"DD={m.max_drawdown_pct:.2f}%  trades={m.trades}"
        )
    print("=" * 60)


def main(symbols: list[str], force_refresh: bool = False) -> None:
    setup_logging()

    print(f"\n{'='*60}")
    print(f"RESEARCH FRAMEWORK — Hyperliquid Perpetuals")
    print(f"Symbols   : {symbols}")
    print(f"Timeframe : {TIMEFRAME}  |  History: {YEARS:.0f} years")
    print(f"Strategies: {[s[0] for s in STRATEGIES]}")
    print(f"{'='*60}\n")

    # ── 1. Load data ────────────────────────────────────────────────
    print("Loading market data (this may take a minute on first run)...")
    data = load_all(symbols, TIMEFRAME, YEARS, force_refresh)

    if not data:
        print("ERROR: No data loaded. Check connectivity.")
        return

    print(f"Data loaded for: {list(data.keys())}\n")
    for sym, df in data.items():
        print(f"  {sym}: {len(df)} candles  "
              f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")
    print()

    # ── 2. Run strategies ───────────────────────────────────────────
    all_rows: list[dict] = []
    oos_candidates: list[ResearchMetrics] = []
    wf_candidates: list[ResearchMetrics] = []

    # window_3_rows: list of (symbol, strategy, w3_metrics) for diagnostic
    window_3_rows: list[dict] = []

    for sym, df in data.items():
        print(f"\n{'─'*60}")
        print(f"SYMBOL: {sym}  ({len(df)} bars)")
        print(f"{'─'*60}")

        for strat_name, sig_fn_simple, sig_fn_wf in STRATEGIES:
            print(f"\n  ▸ {strat_name}")

            try:
                is_m, oos_m, wf_m, wf = _run_strategy(
                    strat_name,
                    lambda df_, fn=sig_fn_simple: fn(df_),
                    sig_fn_wf,
                    df,
                    sym,
                )
            except Exception as exc:
                logger.exception("Error running %s on %s: %s", strat_name, sym, exc)
                continue

            for m in (is_m, oos_m, wf_m):
                all_rows.append(m.row())

            if oos_m.passes_edge_screen:
                oos_candidates.append(oos_m)
            if wf_m.passes_edge_screen:
                wf_candidates.append(wf_m)

            # Capture Window 3 for diagnostic (index 2 = window 3)
            if len(wf.windows) >= 3:
                w3 = wf.windows[2].oos_metrics
                window_3_rows.append({
                    "symbol": sym,
                    "strategy": strat_name,
                    "W3 return%": f"{w3.total_return_pct:+.2f}",
                    "W3 PF": f"{w3.profit_factor:.2f}",
                    "W3 trades": w3.trades,
                    "W3 maxDD%": f"{w3.max_drawdown_pct:.2f}",
                })

    # ── 3. Cross-market summary ─────────────────────────────────────
    print(f"\n\n{'='*60}")
    print("CROSS-MARKET RESULTS SUMMARY")
    print(f"{'='*60}\n")
    _print_table(all_rows)

    # ── 4. Edge screen ──────────────────────────────────────────────
    print("\n--- OOS Edge Screen ---")
    _print_edge_summary(oos_candidates)

    print("\n--- Walk-Forward Edge Screen ---")
    _print_edge_summary(wf_candidates)

    # ── 5. Cross-market consistency ─────────────────────────────────
    print(f"\n{'='*60}")
    print("CROSS-MARKET CONSISTENCY (OOS Profit Factor by strategy)")
    print(f"{'='*60}")

    oos_rows = [r for r in all_rows if r["period"] == "OOS"]
    if oos_rows:
        pf_df = pd.DataFrame(oos_rows)[["strategy", "symbol", "PF", "trades", "return%", "edge?"]]
        print(pf_df.to_string(index=False))

    # ── 6. WF summary table (all symbols, DonchianBreakout) ─────────
    wf_rows = [r for r in all_rows if r["period"] == "WF-OOS" and r["strategy"] == "DonchianBreakout"]
    if wf_rows:
        print(f"\n{'='*60}")
        print("WF-OOS SUMMARY — DonchianBreakout (all symbols)")
        print(f"{'='*60}")
        wf_summary = pd.DataFrame(wf_rows)[["symbol", "return%", "sharpe", "maxDD%", "PF", "trades", "edge?"]]
        print(wf_summary.to_string(index=False))

        pos_wf = sum(1 for r in wf_rows if float(r["return%"]) > 0)
        pf_above_1 = sum(1 for r in wf_rows if float(r["PF"]) >= 1.0)
        avg_pf = sum(float(r["PF"]) for r in wf_rows) / len(wf_rows)
        total_trades = sum(int(r["trades"]) for r in wf_rows)
        print(f"\n  Markets with positive WF-OOS return : {pos_wf}/{len(wf_rows)}")
        print(f"  Markets with WF-OOS PF ≥ 1.0       : {pf_above_1}/{len(wf_rows)}")
        print(f"  Average WF-OOS PF                   : {avg_pf:.2f}")
        print(f"  Total WF-OOS trades                 : {total_trades}")

    # ── 7. Window 3 diagnostic ───────────────────────────────────────
    if window_3_rows:
        w3_donchian = [r for r in window_3_rows if r["strategy"] == "DonchianBreakout"]
        if w3_donchian:
            print(f"\n{'='*60}")
            print("WINDOW 3 DIAGNOSTIC — DonchianBreakout (choppy period)")
            print(f"{'='*60}")
            print(pd.DataFrame(w3_donchian).to_string(index=False))

    print(f"\n{'='*60}")
    print("Research run complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quant Research Framework")
    parser.add_argument(
        "--symbol", nargs="+",
        default=SYMBOLS,
        help="Symbols to test (default: BTC ETH SOL AVAX ARB OP)",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Force re-download of market data (ignore cache)",
    )
    args = parser.parse_args()
    main(args.symbol, args.refresh)
