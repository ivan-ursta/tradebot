"""
research/run_binance_research.py
=================================
Baseline strategy research on Binance USDT-M Futures data.

Mirrors the Hyperliquid research protocol (run_research.py) exactly —
only the data source changes.  Strategy logic and evaluation framework
are byte-for-byte identical so results are directly comparable.

Strategy
--------
  DonchianBreakout  (research/strategies/donchian_breakout.py)
    - Bidirectional Donchian channel breakout
    - EMA-200 regime filter
    - ATR > rolling-median-ATR expansion gate
    - Volume spike filter

Evaluation
----------
  - 60/40 IS / OOS split
  - 5-window rolling walk-forward (non-overlapping OOS)
  - Same metrics: WF-OOS return, PF, max-DD, trades, Sharpe, win-rate, expectancy

Usage
-----
    cd /home/dell/trade
    python -m research.run_binance_research
    python -m research.run_binance_research --refresh           # re-download data
    python -m research.run_binance_research --symbol BTC ETH   # subset
    python -m research.run_binance_research --years 3          # default
    python -m research.run_binance_research --compare          # compare vs HL results
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from research.binance_data_loader import load_all as binance_load_all
from research.engine import run_backtest
from research.metrics import ResearchMetrics, compute
from research.walk_forward import run_walk_forward
from research.strategies.donchian_breakout import (
    generate_signals as donchian_signals,
    make_signal_fn as donchian_fn,
    NAME as DONCHIAN,
)
from utils.logger import setup_logging

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
SYMBOLS       = ["BTC", "ETH", "SOL", "AVAX", "ARB", "OP"]
TIMEFRAME     = "1h"
YEARS         = 3.0
INITIAL_CAP   = 10_000.0
FEE_RATE      = 0.0004   # 4 bps — Binance Futures taker (VIP 0)
SLIPPAGE_BPS  = 5.0
WF_WINDOWS    = 5
TRAIN_FRAC    = 0.6      # 60 % IS, 40 % OOS per window

STRATEGIES = [
    (DONCHIAN, donchian_signals, donchian_fn()),
]

# ── Helpers ────────────────────────────────────────────────────────────────

def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cut = int(len(df) * TRAIN_FRAC)
    return df.iloc[:cut], df.iloc[cut:]


def _run_strategy(
    name: str,
    signal_fn_simple,
    signal_fn_wf,
    df: pd.DataFrame,
    symbol: str,
) -> tuple[ResearchMetrics, ResearchMetrics, ResearchMetrics, object]:
    is_df, oos_df = _split(df)

    # In-sample
    is_sigs   = signal_fn_simple(is_df)
    is_result = run_backtest(is_df, is_sigs, symbol, INITIAL_CAP, FEE_RATE, SLIPPAGE_BPS)
    is_m      = compute(is_result, TIMEFRAME, symbol, name, "IS")

    # Out-of-sample
    oos_sigs   = signal_fn_simple(oos_df)
    oos_result = run_backtest(oos_df, oos_sigs, symbol, INITIAL_CAP, FEE_RATE, SLIPPAGE_BPS)
    oos_m      = compute(oos_result, TIMEFRAME, symbol, name, "OOS")

    # Walk-forward
    wf = run_walk_forward(
        df, signal_fn_wf,
        symbol=symbol, strategy=name,
        n_windows=WF_WINDOWS, train_frac=TRAIN_FRAC, timeframe=TIMEFRAME,
        initial_capital=INITIAL_CAP, fee_rate=FEE_RATE, slippage_bps=SLIPPAGE_BPS,
    )
    print(wf.summary())
    return is_m, oos_m, wf.combined_oos, wf


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    col_order = [
        "symbol", "strategy", "period", "return%", "sharpe", "sortino",
        "maxDD%", "PF", "winRate%", "expect%", "trades", "edge?", "note",
    ]
    df = df.reindex(columns=[c for c in col_order if c in df.columns])
    print(df.to_string(index=False))


def _print_edge_summary(candidates: list[ResearchMetrics], label: str) -> None:
    print(f"\n{'='*60}")
    print(f"EDGE SCREEN [{label}]")
    if not candidates:
        print("  No strategy × symbol pair passed (PF≥1.3, Sharpe≥0.5, DD≤30%, trades≥30).")
        print("=" * 60)
        return
    print(f"  {len(candidates)} candidate(s) passed:")
    for m in candidates:
        print(
            f"    {m.strategy:<26} {m.symbol:<5}  "
            f"return={m.total_return_pct:+.2f}%  "
            f"sharpe={m.sharpe:.2f}  PF={m.profit_factor:.2f}  "
            f"DD={m.max_drawdown_pct:.2f}%  trades={m.trades}"
        )
    print("=" * 60)


def _comparison_note(symbol: str) -> str:
    """
    If a matching Hyperliquid cache file exists, note the date range available there.
    This lets the user see how much extra history Binance provides.
    """
    hl_cache = Path(__file__).parent.parent / "data" / "cache" / f"{symbol}_1h.csv"
    if hl_cache.exists():
        try:
            hl = pd.read_csv(hl_cache, index_col=0, parse_dates=True)
            hl.index = pd.to_datetime(hl.index, utc=True)
            return (
                f"HL cache: {len(hl)} bars  "
                f"{hl.index[0].strftime('%Y-%m-%d')} → {hl.index[-1].strftime('%Y-%m-%d')}"
            )
        except Exception:
            pass
    return "(no HL cache found)"


# ── Main ───────────────────────────────────────────────────────────────────

def main(symbols: list[str], force_refresh: bool = False, compare: bool = False) -> None:
    setup_logging()

    print(f"\n{'='*60}")
    print(f"RESEARCH FRAMEWORK — Binance USDT-M Futures")
    print(f"Symbols   : {symbols}")
    print(f"Timeframe : {TIMEFRAME}  |  History: {YEARS:.0f} years")
    print(f"Strategies: {[s[0] for s in STRATEGIES]}")
    print(f"Fee rate  : {FEE_RATE*10000:.1f} bps taker")
    print(f"Slippage  : {SLIPPAGE_BPS:.1f} bps")
    print(f"{'='*60}\n")

    # 1. Load data ──────────────────────────────────────────────────────────
    print("Loading Binance market data (first run downloads ~3 years per symbol)…")
    data = binance_load_all(symbols, TIMEFRAME, YEARS, force_refresh)

    if not data:
        print("ERROR: No data loaded.  Check internet connectivity.")
        return

    print(f"\nData loaded for: {list(data.keys())}\n")
    for sym, df in data.items():
        hl_note = _comparison_note(sym) if compare else ""
        print(
            f"  Binance {sym}: {len(df):>6} candles  "
            f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}  "
            + (f"  |  {hl_note}" if hl_note else "")
        )
    print()

    # 2. Run strategies ─────────────────────────────────────────────────────
    all_rows:      list[dict]            = []
    oos_candidates: list[ResearchMetrics] = []
    wf_candidates:  list[ResearchMetrics] = []
    window_3_rows:  list[dict]            = []

    for sym, df in data.items():
        print(f"\n{'─'*60}")
        print(f"SYMBOL: {sym}  ({len(df)} bars  "
              f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')})")
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

            if len(wf.windows) >= 3:
                w3 = wf.windows[2].oos_metrics
                window_3_rows.append({
                    "symbol":    sym,
                    "strategy":  strat_name,
                    "W3 return%": f"{w3.total_return_pct:+.2f}",
                    "W3 PF":     f"{w3.profit_factor:.2f}",
                    "W3 trades": w3.trades,
                    "W3 maxDD%": f"{w3.max_drawdown_pct:.2f}",
                })

    # 3. Cross-market summary ───────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print("CROSS-MARKET RESULTS SUMMARY — Binance 3-year baseline")
    print(f"{'='*60}\n")
    _print_table(all_rows)

    # 4. Edge screens ───────────────────────────────────────────────────────
    _print_edge_summary(oos_candidates, "OOS")
    _print_edge_summary(wf_candidates,  "Walk-Forward OOS")

    # 5. WF-OOS summary (DonchianBreakout) ─────────────────────────────────
    wf_rows = [r for r in all_rows if r["period"] == "WF-OOS" and r["strategy"] == DONCHIAN]
    if wf_rows:
        print(f"\n{'='*60}")
        print(f"WF-OOS SUMMARY — {DONCHIAN} (all symbols, Binance {YEARS:.0f}yr)")
        print(f"{'='*60}")
        wf_df = pd.DataFrame(wf_rows)[
            ["symbol", "return%", "sharpe", "maxDD%", "PF", "winRate%", "trades", "edge?"]
        ]
        print(wf_df.to_string(index=False))

        pos_wf       = sum(1 for r in wf_rows if float(r["return%"]) > 0)
        pf_above_1   = sum(1 for r in wf_rows if float(r["PF"])      >= 1.0)
        avg_pf       = sum(float(r["PF"]) for r in wf_rows) / len(wf_rows)
        total_trades = sum(int(r["trades"]) for r in wf_rows)

        print(f"\n  Markets with positive WF-OOS return : {pos_wf}/{len(wf_rows)}")
        print(f"  Markets with WF-OOS PF ≥ 1.0       : {pf_above_1}/{len(wf_rows)}")
        print(f"  Average WF-OOS PF                   : {avg_pf:.2f}")
        print(f"  Total WF-OOS trades                 : {total_trades}")

    # 6. Window 3 diagnostic ───────────────────────────────────────────────
    w3_donchian = [r for r in window_3_rows if r["strategy"] == DONCHIAN]
    if w3_donchian:
        print(f"\n{'='*60}")
        print(f"WINDOW 3 DIAGNOSTIC — {DONCHIAN} (choppy / ranging period test)")
        print(f"{'='*60}")
        print(pd.DataFrame(w3_donchian).to_string(index=False))

    # 7. Comparison vs Hyperliquid (if requested) ──────────────────────────
    if compare:
        _print_hl_comparison(all_rows, symbols)

    print(f"\n{'='*60}")
    print("Binance research run complete.")
    print(f"  Data source : Binance USDT-M Futures (fapi.binance.com)")
    print(f"  Symbols     : {list(data.keys())}")
    print(f"  History     : {YEARS:.0f} years of 1h candles")
    print(f"  Strategy    : {DONCHIAN} (params unchanged from HL research)")
    print(f"  Fee/slip    : {FEE_RATE*10000:.1f} bps taker + {SLIPPAGE_BPS:.1f} bps slippage")
    print(f"{'='*60}\n")


def _print_hl_comparison(binance_rows: list[dict], symbols: list[str]) -> None:
    """
    Load the cached Hyperliquid research data and print a side-by-side comparison.
    Only works if research/run_research.py was previously executed.
    """
    hl_cache_dir = Path(__file__).parent.parent / "data" / "cache"

    print(f"\n{'='*60}")
    print("HYPERLIQUID vs BINANCE — WF-OOS Comparison (DonchianBreakout)")
    print(f"{'='*60}")
    print(
        f"{'Symbol':<6}  "
        f"{'HL return%':>12}  {'BN return%':>12}  "
        f"{'HL PF':>8}  {'BN PF':>8}  "
        f"{'HL DD%':>8}  {'BN DD%':>8}  "
        f"{'HL trades':>10}  {'BN trades':>10}"
    )
    print("-" * 100)

    bn_wf = {
        r["symbol"]: r
        for r in binance_rows
        if r["period"] == "WF-OOS" and r["strategy"] == DONCHIAN
    }

    # Try to load HL results from the atr_direction_ablation cache or from raw CSV caches
    # Fall back to showing "N/A" if not available
    hl_results_file = Path(__file__).parent / "atr_direction_ablation.py"
    # We can't load HL WF results dynamically without re-running, so show BN vs note
    for sym in symbols:
        bn = bn_wf.get(sym)
        if not bn:
            continue

        # Check for HL data availability
        hl_cache = hl_cache_dir / f"{sym}_1h.csv"
        if hl_cache.exists():
            try:
                hl_df = pd.read_csv(hl_cache, index_col=0, parse_dates=True)
                hl_df.index = pd.to_datetime(hl_df.index, utc=True)
                hl_note = f"{len(hl_df)} bars ({hl_df.index[0].strftime('%Y-%m-%d')}→{hl_df.index[-1].strftime('%Y-%m-%d')})"
            except Exception:
                hl_note = "cache exists (re-run run_research.py for metrics)"
        else:
            hl_note = "no HL cache — run python -m research.run_research first"

        print(
            f"{sym:<6}  "
            f"{'(see HL run)':>12}  {bn['return%']:>12}  "
            f"{'---':>8}  {bn['PF']:>8}  "
            f"{'---':>8}  {bn['maxDD%']:>8}  "
            f"{'---':>10}  {bn['trades']:>10}"
        )
        print(f"         HL history note: {hl_note}")

    print()
    print("To produce side-by-side metrics, run both scripts then compare:")
    print("  python -m research.run_research         # Hyperliquid (2yr)")
    print("  python -m research.run_binance_research # Binance     (3yr)")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Binance baseline research — DonchianBreakout on 3yr USDT-M Futures data"
    )
    parser.add_argument(
        "--symbol", nargs="+", default=SYMBOLS,
        help="Symbols to test (default: BTC ETH SOL AVAX ARB OP)",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Force re-download of market data (ignore disk cache)",
    )
    parser.add_argument(
        "--years", type=float, default=YEARS,
        help=f"Years of history to download (default: {YEARS})",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Print comparison table vs cached Hyperliquid results",
    )
    args = parser.parse_args()

    # Allow overriding years from CLI
    YEARS = args.years

    main(args.symbol, args.refresh, args.compare)
