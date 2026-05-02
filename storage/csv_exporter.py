"""
storage/csv_exporter.py
========================
Export trades and equity curves to CSV for external analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import pandas as pd

from backtesting.backtester import BacktestTrade
from portfolio.pnl import TradePnL

logger = logging.getLogger(__name__)


class CSVExporter:
    def __init__(self, export_path: str = "data/exports/") -> None:
        self.export_path = Path(export_path)
        self.export_path.mkdir(parents=True, exist_ok=True)

    def export_trades(self, trades: List[TradePnL], filename: str = "trades.csv") -> str:
        if not trades:
            logger.warning("No trades to export")
            return ""
        rows = [
            {
                "symbol": t.symbol,
                "strategy": t.strategy,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "gross_pnl": t.gross_pnl,
                "fees": t.fees,
                "net_pnl": t.net_pnl,
                "return_pct": t.return_pct,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
            }
            for t in trades
        ]
        df = pd.DataFrame(rows)
        path = self.export_path / filename
        df.to_csv(path, index=False)
        logger.info("Exported %d trades to %s", len(trades), path)
        return str(path)

    def export_backtest_trades(
        self, trades: List[BacktestTrade], filename: str = "backtest_trades.csv"
    ) -> str:
        if not trades:
            return ""
        rows = [
            {
                "symbol": t.symbol,
                "strategy": t.strategy,
                "side": t.side,
                "entry_bar": t.entry_bar,
                "exit_bar": t.exit_bar,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "fees": t.fees,
                "net_pnl": t.net_pnl,
                "return_pct": t.return_pct,
                "exit_reason": t.exit_reason,
            }
            for t in trades
        ]
        df = pd.DataFrame(rows)
        path = self.export_path / filename
        df.to_csv(path, index=False)
        logger.info("Exported %d backtest trades to %s", len(trades), path)
        return str(path)

    def export_equity_curve(
        self, equity_curve: pd.Series, filename: str = "equity_curve.csv"
    ) -> str:
        path = self.export_path / filename
        equity_curve.to_csv(path, header=["equity"])
        logger.info("Exported equity curve (%d points) to %s", len(equity_curve), path)
        return str(path)
