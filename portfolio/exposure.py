"""
portfolio/exposure.py
=====================
Computes and monitors portfolio exposure metrics.
"""

from __future__ import annotations

from typing import Dict, List

from core.models import Position, Side


def compute_gross_exposure(positions: List[Position]) -> float:
    """Sum of all position notional values (long + short)."""
    return sum(p.notional_value for p in positions)


def compute_net_exposure(positions: List[Position]) -> float:
    """Net directional exposure: longs - shorts."""
    net = 0.0
    for p in positions:
        if p.side == Side.LONG:
            net += p.notional_value
        else:
            net -= p.notional_value
    return net


def compute_exposure_by_symbol(positions: List[Position]) -> Dict[str, float]:
    """Notional value per symbol."""
    return {p.symbol: p.notional_value for p in positions}


def compute_leverage(gross_exposure: float, equity: float) -> float:
    """Portfolio-level leverage."""
    return gross_exposure / equity if equity > 0 else 0.0


def check_correlation_concentration(
    positions: List[Position],
    equity: float,
    max_correlated_fraction: float = 0.20,
) -> List[str]:
    """
    Placeholder for correlation-based concentration check.
    Returns list of warnings for positions that exceed thresholds.
    TODO: integrate actual asset correlation matrix (e.g., from rolling returns).
    """
    warnings = []
    for p in positions:
        frac = p.notional_value / equity if equity > 0 else 0.0
        if frac > max_correlated_fraction:
            warnings.append(
                f"{p.symbol}: {frac:.1%} of equity exceeds max correlated exposure {max_correlated_fraction:.1%}"
            )
    return warnings
