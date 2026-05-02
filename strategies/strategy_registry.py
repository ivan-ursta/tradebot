"""
strategies/strategy_registry.py
=================================
Registry mapping strategy names to classes.
Add new strategies here and reference them by name in config.yaml.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Type

from strategies.base import BaseStrategy
from strategies.funding_filter_momentum import FundingFilterMomentum
from strategies.market_making import MarketMaking
from strategies.mean_reversion import MeanReversion
from strategies.momentum_breakout import MomentumBreakout

logger = logging.getLogger(__name__)

STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "momentum_breakout": MomentumBreakout,
    "mean_reversion": MeanReversion,
    "funding_filter_momentum": FundingFilterMomentum,
    "market_making": MarketMaking,
}


def build_strategies(config: dict) -> List[BaseStrategy]:
    """
    Instantiate strategies listed in config['strategy']['active'].
    Returns list of strategy instances.
    """
    active_names: List[str] = config.get("strategy", {}).get("active", ["momentum_breakout"])
    strategies = []
    for name in active_names:
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            logger.error("Unknown strategy '%s'. Available: %s", name, list(STRATEGY_REGISTRY))
            continue
        instance = cls(config)
        strategies.append(instance)
        logger.info("Loaded strategy: %s", name)
    if not strategies:
        raise ValueError("No valid strategies loaded. Check config['strategy']['active'].")
    return strategies
