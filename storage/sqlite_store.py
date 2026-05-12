"""
storage/sqlite_store.py
=======================
SQLite persistence for trades, candles, and session stats.
Uses SQLAlchemy Core (no ORM overhead).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Boolean,
    Text,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine

from core.models import Fill
from portfolio.pnl import TradePnL

logger = logging.getLogger(__name__)

metadata = MetaData()

fills_table = Table(
    "fills",
    metadata,
    Column("id", String, primary_key=True),
    Column("order_id", String),
    Column("symbol", String),
    Column("side", String),
    Column("quantity", Float),
    Column("price", Float),
    Column("fee", Float),
    Column("timestamp", DateTime),
    Column("strategy_name", String),
    Column("is_paper", Boolean),
)

trades_table = Table(
    "trades",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("symbol", String),
    Column("strategy", String),
    Column("side", String),
    Column("entry_price", Float),
    Column("exit_price", Float),
    Column("quantity", Float),
    Column("gross_pnl", Float),
    Column("fees", Float),
    Column("net_pnl", Float),
    Column("entry_time", DateTime),
    Column("exit_time", DateTime),
)

candles_table = Table(
    "candles",
    metadata,
    Column("symbol", String),
    Column("timeframe", String),
    Column("timestamp", DateTime),
    Column("open", Float),
    Column("high", Float),
    Column("low", Float),
    Column("close", Float),
    Column("volume", Float),
)

equity_table = Table(
    "equity_snapshots",
    metadata,
    Column("timestamp", DateTime, primary_key=True),
    Column("equity", Float),
    Column("cash", Float),
    Column("realized_pnl", Float),
    Column("mode", String),
)

signals_table = Table(
    "signals",
    metadata,
    Column("id", String, primary_key=True),
    Column("timestamp", DateTime),
    Column("symbol", String),
    Column("strategy_name", String),
    Column("direction", String),
    Column("entry_price", Float),
    Column("stop_loss", Float),
    Column("take_profit", Float),
    Column("confidence", Float),
    Column("regime", String),
)


class SQLiteStore:
    """
    Thread-safe SQLite storage.
    """

    def __init__(self, db_path: str = "data/trading.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._engine: Engine = create_engine(f"sqlite:///{db_path}", echo=False)
        metadata.create_all(self._engine)
        logger.info("SQLite store initialised: %s", db_path)

    # ------------------------------------------------------------------
    # Fills
    # ------------------------------------------------------------------

    def save_fill(self, fill: Fill) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(fills_table).prefix_with("OR IGNORE").values(
                    id=fill.id,
                    order_id=fill.order_id,
                    symbol=fill.symbol,
                    side=fill.side.value,
                    quantity=fill.quantity,
                    price=fill.price,
                    fee=fill.fee,
                    timestamp=fill.timestamp,
                    strategy_name=fill.strategy_name,
                    is_paper=fill.is_paper,
                )
            )

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def save_trade(self, trade: TradePnL) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(trades_table).values(
                        symbol=trade.symbol,
                        strategy=trade.strategy,
                        side=trade.side,
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        quantity=trade.quantity,
                        gross_pnl=trade.gross_pnl,
                        fees=trade.fees,
                        net_pnl=trade.net_pnl,
                        entry_time=trade.entry_time,
                        exit_time=trade.exit_time,
                    )
                )
        except Exception:
            logger.exception("Failed to save trade %s/%s", trade.symbol, trade.strategy)

    def get_trades(self, symbol: Optional[str] = None, strategy: Optional[str] = None) -> list:
        with self._engine.connect() as conn:
            q = select(trades_table)
            if symbol:
                q = q.where(trades_table.c.symbol == symbol)
            if strategy:
                q = q.where(trades_table.c.strategy == strategy)
            return conn.execute(q).fetchall()

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def save_signal(self, signal) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(signals_table).prefix_with("OR IGNORE").values(
                        id=signal.id,
                        timestamp=signal.timestamp,
                        symbol=signal.symbol,
                        strategy_name=signal.strategy_name,
                        direction=signal.direction.value if hasattr(signal.direction, "value") else str(signal.direction),
                        entry_price=signal.entry_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        confidence=signal.confidence,
                        regime=signal.regime.value if hasattr(signal.regime, "value") else str(signal.regime),
                    )
                )
        except Exception:
            logger.exception("Failed to save signal %s/%s", signal.symbol, signal.strategy_name)

    def get_signals(self, limit: int = 200, symbol: Optional[str] = None) -> list:
        with self._engine.connect() as conn:
            q = select(signals_table).order_by(signals_table.c.timestamp.desc())
            if symbol:
                q = q.where(signals_table.c.symbol == symbol)
            q = q.limit(limit)
            return conn.execute(q).fetchall()

    # ------------------------------------------------------------------
    # Equity snapshots
    # ------------------------------------------------------------------

    def save_equity_snapshot(
        self, timestamp: datetime, equity: float, cash: float, realized_pnl: float, mode: str
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(equity_table).prefix_with("OR REPLACE").values(
                    timestamp=timestamp,
                    equity=equity,
                    cash=cash,
                    realized_pnl=realized_pnl,
                    mode=mode,
                )
            )
