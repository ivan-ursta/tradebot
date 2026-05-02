"""
research/atr_direction_ablation.py
====================================
Ablation study: ATR direction / volatility expansion filter.

Tests whether adding an ATR direction condition on top of the existing
ATR level gate (ATR > rolling median) improves the bidirectional
Donchian breakout strategy.

Baseline : ATR(14) > rolling_median_ATR(50)   [current strategy]
Variant 1: baseline AND ATR(14) > ATR(14)[1]                  (ATR rising)
Variant 2: baseline AND SMA(ATR,3)[0] > SMA(ATR,3)[1]         (SMA slope positive)
Variant 3: baseline AND ATR(14)/rolling_median_ATR > 1.10      (expansion threshold)

Runs 5-window walk-forward across: BTC, ETH, SOL, AVAX, ARB, OP
Prints clean before/after comparison with Window 3 diagnostics.

Usage:
    cd /home/dell/trade
    python -m research.atr_direction_ablation
    python -m research.atr_direction_ablation --refresh
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from research.data_loader import load_all
from research.walk_forward import run_walk_forward, WalkForwardResult
from utils.logger import setup_logging

logger = logging.getLogger(__name__)

SYMBOLS    = ["BTC", "ETH", "SOL", "AVAX", "ARB", "OP"]
TIMEFRAME  = "1h"
YEARS      = 2.0
INITIAL_CAPITAL = 10_000.0
FEE_RATE   = 0.0004
SLIPPAGE_BPS = 5.0
WF_WINDOWS = 5
TRAIN_FRAC = 0.6

# ── Shared ATR helper ─────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    h, lo, prev_c = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ── Signal generators — one per variant ──────────────────────────────────────

def _base_signals(
    df: pd.DataFrame,
    *,
    n: int = 20,
    m: int = 10,
    vol_mult: float = 1.5,
    vol_period: int = 20,
    regime_ema: int = 200,
    atr_period: int = 14,
    atr_median_window: int = 50,
    # variant knobs (ignored by baseline)
    atr_slope_window: int = 3,
    expansion_threshold: float = 1.10,
    variant: str = "baseline",
) -> pd.DataFrame:
    """
    Shared signal logic.  `variant` selects which extra ATR condition to apply.

    variant in {"baseline", "v1_rising", "v2_slope", "v3_threshold"}
    """
    h, lo, c, v = df["high"], df["low"], df["close"], df["volume"]

    upper       = h.shift(1).rolling(n).max()
    lower       = lo.shift(1).rolling(m).min()
    upper_exit  = h.shift(1).rolling(m).max()
    lower_exit  = lo.shift(1).rolling(n).min()

    vol_ma    = v.rolling(vol_period).mean()
    vol_spike = v > vol_mult * vol_ma

    if regime_ema > 0:
        ema      = c.ewm(span=regime_ema, adjust=False).mean()
        uptrend  = c > ema
        downtrend = c < ema
    else:
        uptrend   = pd.Series(True, index=df.index)
        downtrend = pd.Series(True, index=df.index)

    # ATR level gate (present in all variants)
    atr        = _atr(df, atr_period)
    atr_median = atr.shift(1).rolling(atr_median_window).median()
    atr_level_ok = atr > atr_median

    # ATR direction condition — varies by variant
    if variant == "baseline":
        atr_dir_ok = pd.Series(True, index=df.index)

    elif variant == "v1_rising":
        # ATR(14) > ATR(14)[1]  — current bar ATR higher than previous
        atr_dir_ok = atr > atr.shift(1)

    elif variant == "v2_slope":
        # SMA(ATR, 3) slope positive
        atr_sma    = atr.rolling(atr_slope_window).mean()
        atr_dir_ok = atr_sma > atr_sma.shift(1)

    elif variant == "v3_threshold":
        # ATR / rolling_median_ATR > expansion_threshold
        # Guard against zero median (first bars)
        ratio      = atr / atr_median.replace(0, float("nan"))
        atr_dir_ok = ratio > expansion_threshold

    else:
        raise ValueError(f"Unknown variant: {variant!r}")

    atr_expanding = atr_level_ok & atr_dir_ok

    entry       = (c > upper)  & vol_spike & uptrend   & atr_expanding
    exit_       = (c < lower_exit) | ~uptrend
    short_entry = (c < lower)  & vol_spike & downtrend & atr_expanding
    short_exit  = (c > upper_exit) | ~downtrend

    return pd.DataFrame(
        {"entry": entry, "exit": exit_, "short_entry": short_entry, "short_exit": short_exit},
        index=df.index,
    )


def _make_fn(variant: str, **kwargs) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def fn(df: pd.DataFrame) -> pd.DataFrame:
        return _base_signals(df, variant=variant, **kwargs)
    fn.__name__ = f"DonchianBreakout[{variant}]"
    return fn


# ── Walk-forward runner ───────────────────────────────────────────────────────

def _run_wf(df: pd.DataFrame, symbol: str, variant: str) -> WalkForwardResult:
    fn = _make_fn(variant)
    return run_walk_forward(
        df, fn,
        symbol=symbol,
        strategy=f"DonchianBreakout[{variant}]",
        n_windows=WF_WINDOWS,
        train_frac=TRAIN_FRAC,
        timeframe=TIMEFRAME,
        initial_capital=INITIAL_CAPITAL,
        fee_rate=FEE_RATE,
        slippage_bps=SLIPPAGE_BPS,
    )


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _wf_row(symbol: str, variant: str, wf: WalkForwardResult) -> dict:
    m = wf.combined_oos
    return {
        "symbol":  symbol,
        "variant": variant,
        "return%": round(m.total_return_pct, 2),
        "PF":      round(m.profit_factor,    2),
        "maxDD%":  round(m.max_drawdown_pct, 2),
        "trades":  m.trades,
    }


def _w3_row(symbol: str, variant: str, wf: WalkForwardResult) -> dict | None:
    if len(wf.windows) < 3:
        return None
    w3 = wf.windows[2].oos_metrics
    return {
        "symbol":  symbol,
        "variant": variant,
        "W3 return%": round(w3.total_return_pct, 2),
        "W3 PF":      round(w3.profit_factor,    2),
        "W3 maxDD%":  round(w3.max_drawdown_pct, 2),
        "W3 trades":  w3.trades,
    }


def _sep(char: str = "=", width: int = 76) -> str:
    return char * width


# ── Main ──────────────────────────────────────────────────────────────────────

def main(symbols: list[str], force_refresh: bool = False) -> None:
    setup_logging()

    VARIANTS = [
        ("baseline",     "Baseline  : ATR > median"),
        ("v1_rising",    "Variant 1 : ATR > ATR[1]"),
        ("v2_slope",     "Variant 2 : SMA(ATR,3) slope > 0"),
        ("v3_threshold", "Variant 3 : ATR/median > 1.10"),
    ]

    print(_sep())
    print("ATR DIRECTION / VOLATILITY EXPANSION — ABLATION STUDY")
    print(f"Symbols  : {symbols}")
    print(f"Variants : {len(VARIANTS)}  (baseline + 3 ATR direction filters)")
    print(_sep())
    print()

    print("Loading market data …")
    data = load_all(symbols, TIMEFRAME, YEARS, force_refresh)
    if not data:
        print("ERROR: No data loaded.")
        return
    for sym, df in data.items():
        print(f"  {sym}: {len(df)} bars  {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}")
    print()

    # Results storage: {variant_key: {symbol: WalkForwardResult}}
    results: dict[str, dict[str, WalkForwardResult]] = {v[0]: {} for v in VARIANTS}

    for sym, df in data.items():
        print(_sep("-"))
        print(f"SYMBOL: {sym}  ({len(df)} bars)")
        print(_sep("-"))
        for variant_key, variant_label in VARIANTS:
            print(f"  ▸ {variant_label} …")
            try:
                wf = _run_wf(df, sym, variant_key)
                results[variant_key][sym] = wf
                m = wf.combined_oos
                print(
                    f"    WF-OOS → return={m.total_return_pct:+.2f}%  "
                    f"PF={m.profit_factor:.2f}  "
                    f"DD={m.max_drawdown_pct:.2f}%  "
                    f"trades={m.trades}"
                )
            except Exception as exc:
                logger.exception("Error %s on %s: %s", variant_key, sym, exc)
        print()

    # ── Section 1: Per-symbol before vs after ────────────────────────────────
    print(_sep())
    print("SECTION 1 — PER-SYMBOL WF-OOS  (before vs after)")
    print(_sep())

    for sym in symbols:
        rows = []
        for variant_key, variant_label in VARIANTS:
            wf = results[variant_key].get(sym)
            if wf:
                rows.append(_wf_row(sym, variant_label, wf))
        if rows:
            print(f"\n  {sym}:")
            df_out = pd.DataFrame(rows).set_index("variant")
            print(df_out.to_string())

    # ── Section 2: Window 3 diagnostics ─────────────────────────────────────
    print()
    print(_sep())
    print("SECTION 2 — WINDOW 3 DIAGNOSTIC  (choppy-period resistance)")
    print(_sep())

    w3_rows: list[dict] = []
    for sym in symbols:
        for variant_key, variant_label in VARIANTS:
            wf = results[variant_key].get(sym)
            if wf:
                row = _w3_row(sym, variant_label, wf)
                if row:
                    row["variant"] = variant_label
                    w3_rows.append(row)

    if w3_rows:
        w3_df = pd.DataFrame(w3_rows)
        for sym in symbols:
            sub = w3_df[w3_df["symbol"] == sym]
            if not sub.empty:
                print(f"\n  {sym}:")
                print(sub.drop("symbol", axis=1).set_index("variant").to_string())

    # ── Section 3: Aggregate summary ─────────────────────────────────────────
    print()
    print(_sep())
    print("SECTION 3 — AGGREGATE SUMMARY  (across all symbols)")
    print(_sep())
    print()
    print(f"  {'Variant':<38} {'Pos':>4} {'PF≥1':>5} {'AvgPF':>7} {'Trades':>7}")
    print(f"  {'-'*38} {'-'*4} {'-'*5} {'-'*7} {'-'*7}")

    summary_rows: list[dict] = []
    for variant_key, variant_label in VARIANTS:
        wf_map = results[variant_key]
        if not wf_map:
            continue
        pfs     = [wf_map[s].combined_oos.profit_factor for s in symbols if s in wf_map]
        rets    = [wf_map[s].combined_oos.total_return_pct for s in symbols if s in wf_map]
        trades  = [wf_map[s].combined_oos.trades for s in symbols if s in wf_map]
        pos     = sum(1 for r in rets if r > 0)
        pf_ge1  = sum(1 for p in pfs if p >= 1.0)
        avg_pf  = sum(pfs) / len(pfs) if pfs else 0.0
        tot_tr  = sum(trades)
        print(f"  {variant_label:<38} {pos:>4}/{len(symbols)} {pf_ge1:>4}/{len(symbols)} {avg_pf:>7.2f} {tot_tr:>7}")
        summary_rows.append({
            "variant": variant_label,
            "pos_markets": pos,
            "pf_ge1_markets": pf_ge1,
            "avg_pf": avg_pf,
            "total_trades": tot_tr,
        })

    # ── Section 4: Honest conclusion ─────────────────────────────────────────
    print()
    print(_sep())
    print("SECTION 4 — HONEST CONCLUSION")
    print(_sep())
    print()

    if not summary_rows:
        print("  No results to analyse.")
        return

    # Best variant by avg PF (excluding baseline)
    non_baseline = [r for r in summary_rows if "Baseline" not in r["variant"]]
    if non_baseline:
        best = max(non_baseline, key=lambda r: r["avg_pf"])
        baseline_pf = summary_rows[0]["avg_pf"]
        baseline_pos = summary_rows[0]["pos_markets"]
        best_pf  = best["avg_pf"]
        best_pos = best["pos_markets"]
        delta_pf = best_pf - baseline_pf
        delta_pos = best_pos - baseline_pos

        print(f"  Best ATR direction variant : {best['variant']}")
        print(f"  Avg PF vs baseline         : {best_pf:.2f} vs {baseline_pf:.2f}  ({delta_pf:+.2f})")
        print(f"  Positive markets           : {best_pos}/{len(symbols)} vs {baseline_pos}/{len(symbols)}  ({delta_pos:+d})")
        print()

        # Window 3 assessment
        w3_base = [r for r in w3_rows if "Baseline" in r["variant"]]
        w3_best = [r for r in w3_rows if r["variant"] == best["variant"]]
        if w3_base and w3_best:
            base_w3_pos = sum(1 for r in w3_base if r["W3 return%"] > 0)
            best_w3_pos = sum(1 for r in w3_best if r["W3 return%"] > 0)
            base_w3_avg_pf = sum(r["W3 PF"] for r in w3_base) / len(w3_base)
            best_w3_avg_pf = sum(r["W3 PF"] for r in w3_best) / len(w3_best)
            print(f"  Window 3 — positive markets: {best_w3_pos}/{len(symbols)} vs baseline {base_w3_pos}/{len(symbols)}")
            print(f"  Window 3 — avg PF          : {best_w3_avg_pf:.2f} vs baseline {base_w3_avg_pf:.2f}")
            w3_improved = best_w3_avg_pf > base_w3_avg_pf
            print(f"  Window 3 materially improved: {'YES' if w3_improved else 'NO'}")
        print()

        # Breadth: is improvement broad or isolated?
        best_wf  = results[best["variant"].split(":")[0].strip().lower().replace(" ", "_").replace("variant_1", "v1_rising").replace("variant_2", "v2_slope").replace("variant_3", "v3_threshold")]
        # Re-derive variant key from label
        vkey_map = {label: key for key, label in VARIANTS}
        best_vkey = vkey_map.get(best["variant"])
        if best_vkey:
            best_wf = results[best_vkey]
            per_sym_delta = []
            for s in symbols:
                if s in best_wf and s in results["baseline"]:
                    dp = (best_wf[s].combined_oos.profit_factor
                          - results["baseline"][s].combined_oos.profit_factor)
                    per_sym_delta.append((s, dp))
            improving_syms = [s for s, dp in per_sym_delta if dp > 0]
            print(f"  Improvement breadth: {len(improving_syms)}/{len(symbols)} markets improved PF")
            for s, dp in per_sym_delta:
                arrow = "▲" if dp > 0 else "▼" if dp < 0 else "─"
                print(f"    {s:<6} PF delta {dp:+.2f} {arrow}")
        print()

        # Robustness verdict
        avg_best_pf = best["avg_pf"]
        best_pos_ct = best["pos_markets"]
        if avg_best_pf >= 1.15 and best_pos_ct >= 4:
            verdict = "PROMISING — consider paper trading with this filter"
        elif avg_best_pf >= 1.05 and best_pos_ct >= 3:
            verdict = "CAUTIOUSLY PROMISING — continue ablation before paper trading"
        else:
            verdict = "STILL RESEARCH ONLY — filter insufficient; further work needed"
        print(f"  Robustness verdict: {verdict}")
    else:
        print("  No non-baseline variants to compare.")

    print()
    print(_sep())
    print("Ablation study complete.")
    print(_sep())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATR direction ablation study")
    parser.add_argument("--symbol", nargs="+", default=SYMBOLS)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    main(args.symbol, args.refresh)
