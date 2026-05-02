"""
research/regime_analysis.py
============================
Four-step diagnostic to determine whether DonchianBreakout is:
  (A) a selective market strategy, or
  (B) a regime-dependent strategy.

Steps
-----
  1. Market suitability  — rank all 6 symbols by robustness
  2. Regime dependency   — split trade results by market regime at entry
  3. Failure analysis    — deep-dive ETH/OP (why fail) and AVAX/SOL (why drawdown)
  4. Recommendation      — evidence-based path forward

Usage
-----
    cd /home/dell/trade
    python -m research.regime_analysis

No optimisation.  No grid search.  Pure diagnosis.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from research.engine import BacktestResult, TradeRecord, run_backtest
from research.walk_forward import run_walk_forward
from research.strategies.donchian_breakout import generate_signals, make_signal_fn, NAME as DONCHIAN

# ── Config (identical to run_binance_research.py) ──────────────────────────
SYMBOLS      = ["BTC", "ETH", "SOL", "AVAX", "ARB", "OP"]
TIMEFRAME    = "1h"
INITIAL_CAP  = 10_000.0
FEE_RATE     = 0.0004
SLIPPAGE_BPS = 5.0
WF_WINDOWS   = 5
TRAIN_FRAC   = 0.6
BARS_PER_YEAR = 8_760

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"


# ═══════════════════════════════════════════════════════════════════════════
# Regime indicators
# ═══════════════════════════════════════════════════════════════════════════

def _wilder_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False).mean()


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX(period).  Returns Series aligned to df.index."""
    h, lo, c = df["high"], df["low"], df["close"]
    prev_h = h.shift(1)
    prev_lo = lo.shift(1)
    prev_c = c.shift(1)

    tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    plus_dm  = (h - prev_h).clip(lower=0).where((h - prev_h) > (prev_lo - lo), 0)
    minus_dm = (prev_lo - lo).clip(lower=0).where((prev_lo - lo) > (h - prev_h), 0)

    atr14   = _wilder_ema(tr, period)
    plus_di  = 100 * _wilder_ema(plus_dm,  period) / atr14.replace(0, np.nan)
    minus_di = 100 * _wilder_ema(minus_dm, period) / atr14.replace(0, np.nan)

    dx = (100 * (plus_di - minus_di).abs() /
          (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    return _wilder_ema(dx, period)


def compute_regime_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Append regime columns to df (returns a copy, does not mutate).

    Columns added
    -------------
    adx          — ADX(14)
    atr14        — ATR(14)  [Wilder EMA of TR]
    atr_median   — rolling 50-bar median of atr14 (shifted 1 to avoid look-ahead)
    atr_ratio    — atr14 / atr_median
    ema200       — EMA(200)
    pct_vs_ema   — (close - ema200) / ema200  (signed distance from trend)

    Regime flags (bool)
    -------------------
    reg_trend     — ADX > 25
    reg_chop      — ADX < 20
    reg_expand    — atr_ratio > 1.25
    reg_compress  — atr_ratio < 0.80
    """
    d = df.copy()
    h, lo, c = d["high"], d["low"], d["close"]
    prev_c = c.shift(1)

    tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    d["atr14"]      = _wilder_ema(tr, 14)
    d["atr_median"] = d["atr14"].shift(1).rolling(50).median()
    d["atr_ratio"]  = d["atr14"] / d["atr_median"].replace(0, np.nan)
    d["adx"]        = compute_adx(df, 14)
    d["ema200"]     = c.ewm(span=200, adjust=False).mean()
    d["pct_vs_ema"] = (c - d["ema200"]) / d["ema200"]

    d["reg_trend"]    = d["adx"] > 25
    d["reg_chop"]     = d["adx"] < 20
    d["reg_expand"]   = d["atr_ratio"] > 1.25
    d["reg_compress"] = d["atr_ratio"] < 0.80
    return d


def label_regime(adx: float, atr_ratio: float) -> str:
    """Single-label regime for display (priority order)."""
    if adx > 30 and atr_ratio > 1.25:
        return "strong_trend+expand"
    if adx > 25:
        return "trending"
    if adx < 20 and atr_ratio < 0.80:
        return "chop+compress"
    if adx < 20:
        return "choppy"
    if atr_ratio > 1.25:
        return "transitional+expand"
    return "transitional"


# ═══════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════

def load_cached(symbol: str) -> pd.DataFrame:
    path = CACHE_DIR / f"binance_{symbol}_1h.csv"
    if not path.exists():
        raise FileNotFoundError(f"Cache missing: {path}. Run run_binance_research.py first.")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


# ═══════════════════════════════════════════════════════════════════════════
# Trade enrichment
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RichTrade:
    symbol:      str
    side:        str
    entry_time:  pd.Timestamp
    exit_time:   pd.Timestamp
    return_pct:  float
    bars_held:   int
    is_win:      bool
    adx:         float
    atr_ratio:   float
    pct_vs_ema:  float
    regime:      str


def enrich_trades(
    trades: List[TradeRecord],
    df_regime: pd.DataFrame,
    symbol: str,
) -> List[RichTrade]:
    """Join trade records with regime state at entry bar."""
    idx = df_regime.index
    out: List[RichTrade] = []
    for t in trades:
        # Find the bar at or just before entry_time
        loc = idx.searchsorted(t.entry_time, side="right") - 1
        if loc < 0 or loc >= len(idx):
            continue
        row = df_regime.iloc[loc]
        adx       = float(row.get("adx",       np.nan))
        atr_ratio = float(row.get("atr_ratio",  np.nan))
        pct_ema   = float(row.get("pct_vs_ema", np.nan))

        out.append(RichTrade(
            symbol=symbol,
            side=t.side,
            entry_time=t.entry_time,
            exit_time=t.exit_time,
            return_pct=t.return_pct,
            bars_held=t.bars_held,
            is_win=(t.return_pct > 0),
            adx=adx,
            atr_ratio=atr_ratio,
            pct_vs_ema=pct_ema,
            regime=label_regime(adx, atr_ratio),
        ))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Metrics helpers
# ═══════════════════════════════════════════════════════════════════════════

def _pf(rets: List[float]) -> float:
    wins   = sum(r for r in rets if r > 0)
    losses = abs(sum(r for r in rets if r <= 0))
    return wins / losses if losses > 0 else float("inf")


def _sharpe(equity: pd.Series, periods_per_year: int = BARS_PER_YEAR) -> float:
    bar_ret = equity.pct_change().dropna()
    if bar_ret.std(ddof=1) == 0:
        return 0.0
    return bar_ret.mean() / bar_ret.std(ddof=1) * math.sqrt(periods_per_year)


def _maxdd(equity: pd.Series) -> float:
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    return abs(float(dd.min())) * 100


def _trade_stats(rets: List[float]) -> dict:
    if not rets:
        return dict(n=0, win_rate=0, pf=0, avg=0, avg_win=0, avg_loss=0, exp=0)
    wins   = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    wr     = len(wins) / len(rets) * 100
    pf     = _pf(rets)
    avg_w  = float(np.mean(wins))   if wins   else 0.0
    avg_l  = float(np.mean(losses)) if losses else 0.0
    exp    = wr / 100 * avg_w + (1 - wr / 100) * avg_l
    return dict(
        n=len(rets), win_rate=wr, pf=pf,
        avg=float(np.mean(rets)), avg_win=avg_w, avg_loss=avg_l, exp=exp,
    )


def _robustness_score(
    pf: float, sharpe: float, maxdd: float,
    profitable_windows: int, win_rate: float,
) -> int:
    """0–5 composite robustness score."""
    score = 0
    if pf     > 1.10: score += 1
    if sharpe > 0.30: score += 1
    if maxdd  < 35.0: score += 1
    if profitable_windows >= 3: score += 1
    if win_rate > 30.0:  score += 1
    return score


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — Market suitability
# ═══════════════════════════════════════════════════════════════════════════

def step1_market_suitability(
    all_results: Dict[str, Tuple[BacktestResult, List[dict]]],
) -> None:
    sep = "=" * 100

    print(f"\n{sep}")
    print("STEP 1 — MARKET SUITABILITY  (ranked by robustness, not return)")
    print(sep)

    rows = []
    for sym, (result, wf_windows) in all_results.items():
        rets = result.trade_returns
        eq   = result.equity_curve
        if not rets or eq.empty:
            continue

        st  = _trade_stats(rets)
        sh  = _sharpe(eq)
        dd  = _maxdd(eq)
        tot_ret = (eq.iloc[-1] - INITIAL_CAP) / INITIAL_CAP * 100
        years   = len(eq) / BARS_PER_YEAR
        cagr    = ((eq.iloc[-1] / INITIAL_CAP) ** (1 / years) - 1) * 100 if years > 0 else 0.0

        prof_wins  = sum(1 for w in wf_windows if w["oos_return"] > 0)
        pf_above_1 = sum(1 for w in wf_windows if w["oos_pf"] > 1.0)

        rsc = _robustness_score(st["pf"], sh, dd, prof_wins, st["win_rate"])

        rows.append(dict(
            symbol=sym,
            total_ret=tot_ret,
            cagr=cagr,
            sharpe=sh,
            maxDD=dd,
            pf=st["pf"],
            win_rate=st["win_rate"],
            trades=st["n"],
            avg_trade=st["avg"],
            expectancy=st["exp"],
            prof_windows=f"{prof_wins}/{len(wf_windows)}",
            pf_windows=f"{pf_above_1}/{len(wf_windows)}",
            robust=rsc,
        ))

    rows.sort(key=lambda r: r["robust"], reverse=True)

    hdr = (
        f"{'Sym':<5} {'Return%':>8} {'CAGR%':>7} {'Sharpe':>7} {'MaxDD%':>7} "
        f"{'PF':>5} {'WinR%':>6} {'Trades':>7} {'AvgTrd%':>8} {'Expect%':>8} "
        f"{'WinWF':>6} {'PF>1WF':>7} {'Score':>6}"
    )
    print(f"\n{hdr}")
    print("-" * len(hdr))
    for r in rows:
        flag = " ◄ REJECT" if r["pf"] < 0.90 else (" ◄ WEAK" if r["pf"] < 1.05 else "")
        print(
            f"{r['symbol']:<5} {r['total_ret']:>+8.2f} {r['cagr']:>+7.2f} "
            f"{r['sharpe']:>7.2f} {r['maxDD']:>7.2f} {r['pf']:>5.2f} "
            f"{r['win_rate']:>6.1f} {r['trades']:>7d} {r['avg_trade']:>+8.3f} "
            f"{r['expectancy']:>+8.3f} {r['prof_windows']:>6} {r['pf_windows']:>7} "
            f"{r['robust']:>6d}/5{flag}"
        )

    print()
    print("Score breakdown: PF>1.10 | Sharpe>0.30 | MaxDD<35% | ≥3/5 WF wins | WinRate>30%")


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — Regime dependency
# ═══════════════════════════════════════════════════════════════════════════

def step2_regime_dependency(all_rich: Dict[str, List[RichTrade]]) -> None:
    sep = "=" * 100
    print(f"\n{sep}")
    print("STEP 2 — REGIME DEPENDENCY  (trade outcomes split by market regime at entry)")
    print(sep)

    # ── 2a. Bar-time allocation by regime ─────────────────────────────────
    print("\n  2a. Time Spent in Each Regime (% of total bars, across all symbols)")
    print()

    regime_keys = [
        ("reg_trend",    "Trending     (ADX>25)      "),
        ("reg_chop",     "Choppy       (ADX<20)      "),
        ("reg_expand",   "Vol Expand   (ATR/med>1.25)"),
        ("reg_compress", "Vol Compress (ATR/med<0.80)"),
    ]

    bar_header = f"  {'Regime':<34}" + "".join(f"{s:>7}" for s in SYMBOLS)
    print(bar_header)
    print("  " + "-" * (34 + 7 * len(SYMBOLS)))

    # We need the df_regime per symbol — pass it in separately
    # (stored in all_rich metadata via the first RichTrade approach)
    # Instead, compute from the global cache on the fly
    regime_pcts: Dict[str, Dict[str, float]] = {}
    for sym in SYMBOLS:
        try:
            df = load_cached(sym)
            dr = compute_regime_cols(df)
            regime_pcts[sym] = {
                "reg_trend":    dr["reg_trend"].mean() * 100,
                "reg_chop":     dr["reg_chop"].mean() * 100,
                "reg_expand":   dr["reg_expand"].mean() * 100,
                "reg_compress": dr["reg_compress"].mean() * 100,
            }
        except Exception:
            regime_pcts[sym] = {}

    for key, label in regime_keys:
        row = f"  {label:<34}"
        for sym in SYMBOLS:
            val = regime_pcts.get(sym, {}).get(key, float("nan"))
            row += f"{val:>6.1f}%"
        print(row)

    # ── 2b. Trade results by regime label ─────────────────────────────────
    print(f"\n  2b. Trade Performance by Entry Regime (all symbols pooled)\n")

    all_rich_flat = [t for trades in all_rich.values() for t in trades]
    regime_groups: Dict[str, List[float]] = {}
    for t in all_rich_flat:
        regime_groups.setdefault(t.regime, []).append(t.return_pct)

    hdr = (
        f"  {'Regime':<26} {'Trades':>7} {'WinRate%':>9} {'PF':>6} "
        f"{'AvgTrade%':>10} {'AvgWin%':>8} {'AvgLoss%':>9} {'Expect%':>9}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for regime, rets in sorted(regime_groups.items(), key=lambda x: -len(x[1])):
        st = _trade_stats(rets)
        print(
            f"  {regime:<26} {st['n']:>7d} {st['win_rate']:>9.1f} {st['pf']:>6.2f} "
            f"{st['avg']:>+10.3f} {st['avg_win']:>+8.3f} {st['avg_loss']:>+9.3f} "
            f"{st['exp']:>+9.3f}"
        )

    # ── 2c. Per-symbol regime breakdown ───────────────────────────────────
    print(f"\n  2c. Per-Symbol Trade Performance by Regime\n")

    for sym in SYMBOLS:
        rich = all_rich.get(sym, [])
        if not rich:
            continue
        sym_groups: Dict[str, List[float]] = {}
        for t in rich:
            sym_groups.setdefault(t.regime, []).append(t.return_pct)

        print(f"  ── {sym} ──")
        hdr2 = (
            f"  {'Regime':<26} {'Trades':>7} {'WinRate%':>9} {'PF':>6} "
            f"{'AvgTrd%':>8} {'Expect%':>8}"
        )
        print(hdr2)
        print("  " + "-" * (len(hdr2) - 2))
        for regime, rets in sorted(sym_groups.items(), key=lambda x: -len(x[1])):
            st = _trade_stats(rets)
            flag = "  ◄ edge" if st["exp"] > 0.10 and st["n"] >= 8 else ""
            print(
                f"  {regime:<26} {st['n']:>7d} {st['win_rate']:>9.1f} {st['pf']:>6.2f} "
                f"{st['avg']:>+8.3f} {st['exp']:>+8.3f}{flag}"
            )
        print()

    # ── 2d. ADX and ATR quantile bands ────────────────────────────────────
    print(f"\n  2d. Trade Performance by ADX Quartile (all symbols pooled)\n")

    adx_vals  = [t.adx  for t in all_rich_flat if not math.isnan(t.adx)]
    atr_vals  = [t.atr_ratio for t in all_rich_flat if not math.isnan(t.atr_ratio)]

    if adx_vals:
        q25_adx, q50_adx, q75_adx = np.percentile(adx_vals, [25, 50, 75])
        print(f"  ADX distribution: p25={q25_adx:.1f}  p50={q50_adx:.1f}  p75={q75_adx:.1f}")

        def adx_band(v: float) -> str:
            if v < q25_adx: return f"ADX <{q25_adx:.0f} (weak)"
            if v < q50_adx: return f"ADX {q25_adx:.0f}–{q50_adx:.0f} (mod)"
            if v < q75_adx: return f"ADX {q50_adx:.0f}–{q75_adx:.0f} (str)"
            return f"ADX >{q75_adx:.0f} (vstr)"

        band_groups: Dict[str, List[float]] = {}
        for t in all_rich_flat:
            if math.isnan(t.adx): continue
            band_groups.setdefault(adx_band(t.adx), []).append(t.return_pct)

        hdr3 = f"  {'ADX Band':<26} {'Trades':>7} {'WinRate%':>9} {'PF':>6} {'Expect%':>9}"
        print(f"\n{hdr3}")
        print("  " + "-" * (len(hdr3) - 2))
        for band in sorted(band_groups.keys()):
            rets = band_groups[band]
            st = _trade_stats(rets)
            flag = "  ◄ edge" if st["exp"] > 0.05 and st["pf"] > 1.10 else ""
            print(
                f"  {band:<26} {st['n']:>7d} {st['win_rate']:>9.1f} "
                f"{st['pf']:>6.2f} {st['exp']:>+9.3f}{flag}"
            )

    print()

    if atr_vals:
        q25_atr, q50_atr, q75_atr = np.percentile(atr_vals, [25, 50, 75])
        print(
            f"  ATR/median distribution: p25={q25_atr:.2f}  "
            f"p50={q50_atr:.2f}  p75={q75_atr:.2f}"
        )

        def atr_band(v: float) -> str:
            if v < q25_atr: return f"ATR/med <{q25_atr:.2f} (low)"
            if v < q50_atr: return f"ATR/med {q25_atr:.2f}–{q50_atr:.2f}"
            if v < q75_atr: return f"ATR/med {q50_atr:.2f}–{q75_atr:.2f}"
            return f"ATR/med >{q75_atr:.2f} (high)"

        atr_band_groups: Dict[str, List[float]] = {}
        for t in all_rich_flat:
            if math.isnan(t.atr_ratio): continue
            atr_band_groups.setdefault(atr_band(t.atr_ratio), []).append(t.return_pct)

        hdr4 = f"  {'ATR/Median Band':<28} {'Trades':>7} {'WinRate%':>9} {'PF':>6} {'Expect%':>9}"
        print(f"\n{hdr4}")
        print("  " + "-" * (len(hdr4) - 2))
        for band in sorted(atr_band_groups.keys()):
            rets = atr_band_groups[band]
            st = _trade_stats(rets)
            flag = "  ◄ edge" if st["exp"] > 0.05 and st["pf"] > 1.10 else ""
            print(
                f"  {band:<28} {st['n']:>7d} {st['win_rate']:>9.1f} "
                f"{st['pf']:>6.2f} {st['exp']:>+9.3f}{flag}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — Failure and fragility analysis
# ═══════════════════════════════════════════════════════════════════════════

def _consecutive_stats(rets: List[float]) -> Tuple[int, int, float]:
    """Max consecutive losses, max consecutive wins, max single loss."""
    max_loss_streak = max_win_streak = cur_loss = cur_win = 0
    max_single_loss = 0.0
    for r in rets:
        if r <= 0:
            cur_loss += 1
            cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
            max_single_loss = min(max_single_loss, r)
        else:
            cur_win += 1
            cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
    return max_loss_streak, max_win_streak, max_single_loss


def _holding_analysis(rich: List[RichTrade]) -> pd.DataFrame:
    """Distribution of holding periods for wins vs losses."""
    if not rich:
        return pd.DataFrame()
    wins   = [t.bars_held for t in rich if t.is_win]
    losses = [t.bars_held for t in rich if not t.is_win]
    rows = []
    for label, vals in [("Winners", wins), ("Losers", losses)]:
        if vals:
            rows.append({
                "Group":   label,
                "Count":   len(vals),
                "Median":  f"{np.median(vals):.0f}h",
                "Mean":    f"{np.mean(vals):.0f}h",
                "p10":     f"{np.percentile(vals, 10):.0f}h",
                "p90":     f"{np.percentile(vals, 90):.0f}h",
                "Max":     f"{max(vals):.0f}h",
            })
    return pd.DataFrame(rows).set_index("Group")


def _quarterly_pf(result: BacktestResult, df_regime: pd.DataFrame) -> pd.DataFrame:
    """Compute PF and trade count per calendar quarter."""
    trades = result.trades
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        rows.append({"quarter": t.entry_time.to_period("Q"), "ret": t.return_pct})
    qdf = pd.DataFrame(rows).groupby("quarter")["ret"].apply(list)
    out = []
    for q, rets in qdf.items():
        st = _trade_stats(list(rets))
        out.append({"quarter": str(q), "trades": st["n"], "pf": f"{st['pf']:.2f}",
                    "win%": f"{st['win_rate']:.0f}", "exp%": f"{st['exp']:+.3f}"})
    return pd.DataFrame(out).set_index("quarter")


def step3_failure_analysis(
    all_results: Dict[str, Tuple[BacktestResult, List[dict]]],
    all_rich: Dict[str, List[RichTrade]],
    all_df_regime: Dict[str, pd.DataFrame],
) -> None:
    sep = "=" * 100
    print(f"\n{sep}")
    print("STEP 3 — FAILURE AND FRAGILITY ANALYSIS")
    print(sep)

    # ── Failing markets: ETH and OP ───────────────────────────────────────
    for sym in ["ETH", "OP"]:
        result, wf_windows = all_results.get(sym, (None, []))
        rich = all_rich.get(sym, [])
        dr   = all_df_regime.get(sym, pd.DataFrame())
        if result is None or not result.trades:
            continue

        rets  = result.trade_returns
        st    = _trade_stats(rets)
        max_l, max_w, worst = _consecutive_stats(rets)

        print(f"\n{'─'*60}")
        print(f"  WHY {sym} FAILS")
        print(f"{'─'*60}")
        print(f"  Full-period stats:  trades={st['n']}  WR={st['win_rate']:.1f}%  "
              f"PF={st['pf']:.2f}  exp={st['exp']:+.3f}%")
        print(f"  Max losing streak : {max_l} trades   Worst single trade: {worst:+.2f}%")
        print(f"  Max winning streak: {max_w} trades")

        # Regime breakdown
        reg_groups: Dict[str, List[float]] = {}
        for t in rich:
            reg_groups.setdefault(t.regime, []).append(t.return_pct)
        print(f"\n  Trade count and expectancy by regime:")
        hdr = f"  {'Regime':<26} {'Trades':>6} {'WinR%':>7} {'PF':>6} {'Expect%':>9}"
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for regime, r in sorted(reg_groups.items(), key=lambda x: -len(x[1])):
            s2 = _trade_stats(r)
            print(f"  {regime:<26} {s2['n']:>6d} {s2['win_rate']:>7.1f} "
                  f"{s2['pf']:>6.2f} {s2['exp']:>+9.3f}")

        # Holding period
        print(f"\n  Holding period distribution:")
        hp = _holding_analysis(rich)
        if not hp.empty:
            print(hp.to_string())

        # Quarterly breakdown
        print(f"\n  Quarterly PF breakdown (see where losses concentrate):")
        qpf = _quarterly_pf(result, dr)
        if not qpf.empty:
            print(qpf.to_string())

        # Trend regime characterisation
        if not dr.empty:
            pct_trend = dr["reg_trend"].mean() * 100
            pct_chop  = dr["reg_chop"].mean() * 100
            pct_exp   = dr["reg_expand"].mean() * 100
            print(f"\n  Market character (% of time in each regime):")
            print(f"    Trending (ADX>25) : {pct_trend:.1f}%")
            print(f"    Choppy   (ADX<20) : {pct_chop:.1f}%")
            print(f"    Expanding vol     : {pct_exp:.1f}%")

        # ADX at entry for losses vs wins
        adx_wins   = [t.adx for t in rich if t.is_win  and not math.isnan(t.adx)]
        adx_losses = [t.adx for t in rich if not t.is_win and not math.isnan(t.adx)]
        if adx_wins and adx_losses:
            print(f"\n  ADX at entry — Winners: median={np.median(adx_wins):.1f}"
                  f"   Losers: median={np.median(adx_losses):.1f}")
        atr_wins   = [t.atr_ratio for t in rich if t.is_win  and not math.isnan(t.atr_ratio)]
        atr_losses = [t.atr_ratio for t in rich if not t.is_win and not math.isnan(t.atr_ratio)]
        if atr_wins and atr_losses:
            print(f"  ATR/med at entry — Winners: median={np.median(atr_wins):.2f}"
                  f"   Losers: median={np.median(atr_losses):.2f}")

    # ── Fragile profitable markets: AVAX and SOL ──────────────────────────
    for sym in ["AVAX", "SOL"]:
        result, wf_windows = all_results.get(sym, (None, []))
        rich = all_rich.get(sym, [])
        dr   = all_df_regime.get(sym, pd.DataFrame())
        if result is None or not result.trades:
            continue

        rets = result.trade_returns
        st   = _trade_stats(rets)
        max_l, max_w, worst = _consecutive_stats(rets)

        print(f"\n{'─'*60}")
        print(f"  WHY {sym} WORKS BUT HAS EXCESSIVE DRAWDOWN")
        print(f"{'─'*60}")
        print(f"  Full-period stats: trades={st['n']}  WR={st['win_rate']:.1f}%  "
              f"PF={st['pf']:.2f}  exp={st['exp']:+.3f}%")
        print(f"  Max losing streak : {max_l} trades   Worst single trade: {worst:+.2f}%")

        # Win/loss magnitude asymmetry
        wins_r   = [r for r in rets if r > 0]
        losses_r = [r for r in rets if r <= 0]
        print(f"  Win  magnitude: mean={np.mean(wins_r):+.2f}%  p90={np.percentile(wins_r,90):+.2f}%"
              f"  max={max(wins_r):+.2f}%")
        print(f"  Loss magnitude: mean={np.mean(losses_r):+.2f}%  p10={np.percentile(losses_r,10):+.2f}%"
              f"  min={min(losses_r):+.2f}%")

        # Walk-forward consistency
        print(f"\n  Walk-forward window returns:")
        for w in wf_windows:
            profit = "+" if w["oos_return"] > 0 else " "
            bar = "█" * int(abs(w["oos_return"]) / 5) if abs(w["oos_return"]) <= 100 else "█" * 20
            print(f"    W{w['window']}: {profit}{w['oos_return']:>+7.2f}%  "
                  f"PF={w['oos_pf']:.2f}  DD={w['oos_dd']:.1f}%  trades={w['oos_trades']}  {bar}")

        # Quarterly breakdown
        print(f"\n  Quarterly PF breakdown:")
        qpf = _quarterly_pf(result, dr)
        if not qpf.empty:
            print(qpf.to_string())

        # Where does the drawdown come from?
        cum_ret = 1.0
        max_cum = 1.0
        max_dd_trade = 0.0
        for r in rets:
            cum_ret *= (1 + r / 100)
            max_cum = max(max_cum, cum_ret)
            dd = (max_cum - cum_ret) / max_cum * 100
            max_dd_trade = max(max_dd_trade, dd)
        print(f"\n  Drawdown driven by: max_single_loss={worst:+.2f}%  "
              f"max_consecutive_loss_streak={max_l} trades")
        print(f"  → Drawdown is {'streak-driven (several small losses)' if max_l >= 5 else 'spike-driven (one or two large losses)'}")

        # Regime at drawdown periods
        if rich:
            loss_regimes = [t.regime for t in rich if not t.is_win]
            from collections import Counter
            top_loss = Counter(loss_regimes).most_common(3)
            print(f"  Regime at loss entries (top 3): {top_loss}")


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — Recommendation
# ═══════════════════════════════════════════════════════════════════════════

def step4_recommendation(
    all_results: Dict[str, Tuple[BacktestResult, List[dict]]],
    all_rich: Dict[str, List[RichTrade]],
) -> None:
    sep = "=" * 100
    print(f"\n{sep}")
    print("STEP 4 — RECOMMENDATION")
    print(sep)

    # Collect evidence
    robust_scores = {}
    for sym, (result, wf_windows) in all_results.items():
        rets = result.trade_returns
        eq   = result.equity_curve
        if not rets or eq.empty:
            robust_scores[sym] = 0
            continue
        st = _trade_stats(rets)
        sh = _sharpe(eq)
        dd = _maxdd(eq)
        prof_wins = sum(1 for w in wf_windows if w["oos_return"] > 0)
        robust_scores[sym] = _robustness_score(st["pf"], sh, dd, prof_wins, st["win_rate"])

    # Regime edge evidence
    all_flat = [t for trades in all_rich.values() for t in trades]
    trending_trades = [t for t in all_flat if t.adx > 25]
    chop_trades     = [t for t in all_flat if t.adx < 20]
    expand_trades   = [t for t in all_flat if t.atr_ratio > 1.25 and not math.isnan(t.atr_ratio)]
    compress_trades = [t for t in all_flat if t.atr_ratio < 0.80 and not math.isnan(t.atr_ratio)]

    trend_pf    = _pf([t.return_pct for t in trending_trades]) if trending_trades else 0
    chop_pf     = _pf([t.return_pct for t in chop_trades])     if chop_trades     else 0
    expand_pf   = _pf([t.return_pct for t in expand_trades])   if expand_trades   else 0
    compress_pf = _pf([t.return_pct for t in compress_trades]) if compress_trades else 0

    trend_exp   = float(np.mean([t.return_pct for t in trending_trades]))  if trending_trades  else 0
    chop_exp    = float(np.mean([t.return_pct for t in chop_trades]))      if chop_trades      else 0

    print(f"""
  EVIDENCE SUMMARY
  ──────────────────────────────────────────────────────────────────────────

  A. Market-level robustness scores (0-5)
     {', '.join(f'{sym}={robust_scores[sym]}' for sym in SYMBOLS)}

  B. Regime-level edge (pooled across all 6 symbols)
     Trending  (ADX>25) : PF={trend_pf:.2f}  trades={len(trending_trades)}  avg={trend_exp:+.3f}%
     Choppy    (ADX<20) : PF={chop_pf:.2f}  trades={len(chop_trades)}  avg={chop_exp:+.3f}%
     Expanding (ATR>1.25): PF={expand_pf:.2f}  trades={len(expand_trades)}
     Compressed(ATR<0.80): PF={compress_pf:.2f}  trades={len(compress_trades)}

  C. Cross-market consistency
     Profitable WF-OOS: {sum(1 for s,(r,ws) in all_results.items() if r.equity_curve.iloc[-1]>INITIAL_CAP)}/6 markets
     Average WF-OOS PF: {np.mean([_pf(r.trade_returns) for _,(r,_) in all_results.items() if r.trade_returns]):.2f}
""")

    # Decision logic
    reject_syms  = [sym for sym, sc in robust_scores.items() if sc <= 1]
    weak_syms    = [sym for sym, sc in robust_scores.items() if 2 <= sc <= 2]
    strong_syms  = [sym for sym, sc in robust_scores.items() if sc >= 3]
    regime_edge  = trend_pf > 1.15 and chop_pf < 0.95

    print("  DECISION")
    print("  ────────────────────────────────────────────────────────────")

    if len(reject_syms) >= 4:
        print("  PATH: Reject the strategy entirely, OR pursue as single-market")
    elif regime_edge and len(strong_syms) >= 2:
        print("  PATH: B — Regime-dependent strategy with market filter")
        print(f"         Trade only: {strong_syms}")
        print(f"         Gate on: ADX > 25 at entry (or equivalently: require trending regime)")
        print(f"         Skip entirely: {reject_syms}")
    else:
        print("  PATH: A — Selective market strategy")
        print(f"         Candidate markets: {strong_syms}")
        print(f"         Reject: {reject_syms}")

    print("""
  SPECIFIC RECOMMENDATIONS
  ────────────────────────────────────────────────────────────────────────

  1. Markets to trade (if any):
       Requires robustness score ≥ 3/5 AND ≥ 3/5 profitable WF windows.
       → Trade only markets meeting both criteria.

  2. Regime gate (if regime edge exists):
       Add: require ADX > 25 at entry bar (explicitly, not just EMA200).
       The EMA200 filter catches trend DIRECTION but not trend STRENGTH.
       A trending market with ADX < 20 is range-bound — breakouts whipsaw.
       Cost: fewer trades.  Benefit: higher expectancy.

  3. What NOT to do yet:
       ✗ Do not add more entry filters (no RSI, no MACD, no volume ratio tuning).
       ✗ Do not optimise Donchian channel length.
       ✗ Do not increase leverage to recover drawdown.

  4. Next honest step:
       Run the ADX-gated version on ONLY the highest-scoring markets,
       count trades, check WF consistency, and only proceed if PF > 1.3
       on OOS data with ≥ 30 trades per window.
       If that fails → reject the strategy.
""")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")

    signal_fn = make_signal_fn()

    all_results:   Dict[str, Tuple[BacktestResult, List[dict]]] = {}
    all_rich:      Dict[str, List[RichTrade]]  = {}
    all_df_regime: Dict[str, pd.DataFrame]     = {}

    print("Loading data and running backtests…  ", end="", flush=True)

    for sym in SYMBOLS:
        print(sym, end=" ", flush=True)
        df = load_cached(sym)
        dr = compute_regime_cols(df)
        all_df_regime[sym] = dr

        # Full-period backtest
        sigs   = signal_fn(df)
        result = run_backtest(df, sigs, sym, INITIAL_CAP, FEE_RATE, SLIPPAGE_BPS)

        # Walk-forward for per-window data
        wf = run_walk_forward(
            df, signal_fn, symbol=sym, strategy=DONCHIAN,
            n_windows=WF_WINDOWS, train_frac=TRAIN_FRAC, timeframe=TIMEFRAME,
            initial_capital=INITIAL_CAP, fee_rate=FEE_RATE, slippage_bps=SLIPPAGE_BPS,
        )
        wf_rows = [
            dict(
                window=w.window_num,
                oos_return=w.oos_metrics.total_return_pct,
                oos_pf=w.oos_metrics.profit_factor,
                oos_dd=w.oos_metrics.max_drawdown_pct,
                oos_trades=w.oos_metrics.trades,
            )
            for w in wf.windows
        ]
        all_results[sym] = (result, wf_rows)

        # Enrich trades with regime
        rich = enrich_trades(result.trades, dr, sym)
        all_rich[sym] = rich

    print("done.\n")

    step1_market_suitability(all_results)
    step2_regime_dependency(all_rich)
    step3_failure_analysis(all_results, all_rich, all_df_regime)
    step4_recommendation(all_results, all_rich)


if __name__ == "__main__":
    main()
