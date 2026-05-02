"""
backtesting/backtester.py
=========================
Bar-by-bar backtesting engine.

Design:
  - Processes each bar sequentially (no look-ahead bias)
  - Fills on the NEXT bar's open after a signal (latency_bars=1)
  - Applies fees and slippage to every fill
  - Tracks equity curve, open positions, and closed trades
  - Supports long/short
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backtesting.metrics import BacktestMetrics, compute_metrics
from core.models import Fill, Order, OrderStatus, OrderType, Position, Side, Signal, SignalDirection
from execution.fill_simulator import FillSimulator
from execution.fee_model import FeeSchedule, HYPERLIQUID_DEFAULT
from execution.slippage import SlippageModel, apply_slippage
from portfolio.portfolio import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    symbol: str
    strategy: str
    side: str
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    quantity: float
    fees: float
    gross_pnl: float
    net_pnl: float
    return_pct: float
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    metrics: Optional[BacktestMetrics] = None
    config_snapshot: dict = field(default_factory=dict)


class Backtester:
    """
    Single-strategy, single-symbol backtester.
    For multi-symbol / multi-strategy, run multiple instances and compare.
    """

    def __init__(
        self,
        config: dict,
        strategy,
        fee_schedule: FeeSchedule = HYPERLIQUID_DEFAULT,
        slippage_bps: float = 5,
        initial_capital: float = 10_000.0,
        latency_bars: int = 1,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.fee_schedule = fee_schedule
        self.slippage_bps = slippage_bps
        self.initial_capital = initial_capital
        self.latency_bars = latency_bars
        self._fill_sim = FillSimulator(config, fee_schedule.taker_rate, slippage_bps)
        self._risk_cfg = config.get("risk", {})

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        symbol: str = "BTC",
    ) -> BacktestResult:
        """
        Run backtest on df (OHLCV DataFrame with DatetimeIndex).
        Returns BacktestResult with trades, equity curve, and metrics.
        """
        result = BacktestResult(strategy_name=self.strategy.name, symbol=symbol)

        equity = self.initial_capital
        cash = self.initial_capital
        position: Optional[BacktestPosition] = None
        equity_series = []
        trades: List[BacktestTrade] = []
        pending_order: Optional[Tuple[Order, Signal, int]] = None  # (order, signal, fill_bar_idx)

        atr_mult_sl = self._risk_cfg.get("stop_loss_atr_mult", 2.0)
        atr_mult_tp = self._risk_cfg.get("take_profit_atr_mult", 3.0)

        for i in range(len(df)):
            bar = df.iloc[i]
            close = float(bar["close"])

            # ---- Process pending order (fill on current bar if latency_bars passed) ----
            if pending_order and i >= pending_order[2]:
                order, signal, _ = pending_order
                fill = self._fill_sim.simulate_fill(order, bar)
                if fill:
                    cost = fill.price * fill.quantity + fill.fee
                    if fill.side == Side.LONG:
                        cash -= cost
                        position = BacktestPosition(
                            symbol=symbol,
                            side=Side.LONG,
                            entry_price=fill.price,
                            quantity=fill.quantity,
                            entry_bar=i,
                            entry_time=fill.timestamp,
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit,
                            strategy=self.strategy.name,
                            entry_fee=fill.fee,
                        )
                    else:
                        cash += fill.price * fill.quantity - fill.fee
                        position = BacktestPosition(
                            symbol=symbol,
                            side=Side.SHORT,
                            entry_price=fill.price,
                            quantity=fill.quantity,
                            entry_bar=i,
                            entry_time=fill.timestamp,
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit,
                            strategy=self.strategy.name,
                            entry_fee=fill.fee,
                        )
                pending_order = None

            # ---- Check stops / TP / strategy exits ----
            if position:
                close_reason = None
                close_price = close

                if position.stop_loss:
                    if position.side == Side.LONG and float(bar["low"]) <= position.stop_loss:
                        close_reason = "stop_loss"
                        # Gap-down past stop → fill at open; no gap → fill at stop
                        close_price = min(position.stop_loss, float(bar["open"]))
                    elif position.side == Side.SHORT and float(bar["high"]) >= position.stop_loss:
                        close_reason = "stop_loss"
                        # Gap-up past stop → fill at open; no gap → fill at stop
                        close_price = max(position.stop_loss, float(bar["open"]))

                if position.take_profit and not close_reason:
                    if position.side == Side.LONG and float(bar["high"]) >= position.take_profit:
                        close_reason = "take_profit"
                        close_price = min(position.take_profit, float(bar["high"]))
                    elif position.side == Side.SHORT and float(bar["low"]) <= position.take_profit:
                        close_reason = "take_profit"
                        close_price = max(position.take_profit, float(bar["low"]))

                # Strategy exit
                if not close_reason and i >= self.strategy._min_rows:
                    featured_sub = self.strategy.prepare_features(df.iloc[max(0, i - 200) : i + 1])
                    if featured_sub is not None and len(featured_sub) > 0:
                        from core.state import TradingState
                        mock_state = TradingState(equity)
                        pos_obj = Position(
                            symbol=symbol,
                            side=position.side,
                            quantity=position.quantity,
                            avg_entry_price=position.entry_price,
                            stop_loss=position.stop_loss,
                            take_profit=position.take_profit,
                        )
                        if self.strategy.should_exit(featured_sub, pos_obj, mock_state):
                            close_reason = "strategy_exit"

                if close_reason:
                    slip_close = apply_slippage(
                        close_price,
                        is_buy=(position.side == Side.SHORT),
                        bps=self.slippage_bps,
                    )
                    close_fee = self.fee_schedule.compute_fee(slip_close * position.quantity)

                    if position.side == Side.LONG:
                        gross_pnl = (slip_close - position.entry_price) * position.quantity
                        cash += slip_close * position.quantity - close_fee
                    else:
                        gross_pnl = (position.entry_price - slip_close) * position.quantity
                        cash -= slip_close * position.quantity + close_fee

                    net_pnl = gross_pnl - close_fee - position.entry_fee
                    cost_basis = position.entry_price * position.quantity
                    ret_pct = net_pnl / cost_basis * 100 if cost_basis > 0 else 0.0

                    ts = bar.name if isinstance(bar.name, datetime) else datetime.now(timezone.utc)
                    trades.append(
                        BacktestTrade(
                            symbol=symbol,
                            strategy=self.strategy.name,
                            side=position.side.value,
                            entry_bar=position.entry_bar,
                            exit_bar=i,
                            entry_price=position.entry_price,
                            exit_price=slip_close,
                            quantity=position.quantity,
                            fees=close_fee + position.entry_fee,
                            gross_pnl=gross_pnl,
                            net_pnl=net_pnl,
                            return_pct=ret_pct,
                            entry_time=position.entry_time,
                            exit_time=ts if isinstance(ts, datetime) else datetime.now(timezone.utc),
                            exit_reason=close_reason,
                        )
                    )
                    position = None

            # ---- Generate new signal (only if no position) ----
            if position is None and pending_order is None and i >= self.strategy._min_rows:
                sub_df = df.iloc[max(0, i - 300) : i + 1]
                featured_df = self.strategy.prepare_features(sub_df)
                if featured_df is not None and len(featured_df) > 0:
                    from core.state import TradingState
                    mock_state = TradingState(equity)
                    mock_state.config_ref = self.config
                    signal = self.strategy.generate_signal(featured_df, mock_state)

                    if signal and signal.is_actionable():
                        # Size the order
                        if signal.stop_loss and signal.entry_price:
                            stop_dist = abs(signal.entry_price - signal.stop_loss)
                            risk_dollars = equity * self._risk_cfg.get("max_risk_per_trade", 0.01)
                            qty = risk_dollars / stop_dist if stop_dist > 0 else 0
                            min_usd = self._risk_cfg.get("min_order_size_usd", 10)
                            if qty * (signal.entry_price or close) >= min_usd:
                                side = Side.LONG if signal.direction == SignalDirection.LONG else Side.SHORT
                                slipped_entry = apply_slippage(
                                    signal.entry_price or close,
                                    is_buy=(side == Side.LONG),
                                    bps=self.slippage_bps,
                                )
                                # Hard cap: qty must not risk more than max_risk_per_trade * equity
                                # even if stop distance is tiny (prevents runaway leverage)
                                max_loss_dollars = equity * self._risk_cfg.get("max_risk_per_trade", 0.01)
                                stop_dist = abs(slipped_entry - signal.stop_loss) if signal.stop_loss else slipped_entry * 0.02
                                qty = min(qty, max_loss_dollars / stop_dist) if stop_dist > 0 else qty
                                # Also cap notional at max_leverage * equity
                                max_notional = equity * self._risk_cfg.get("max_leverage", 5)
                                qty = min(qty, max_notional / slipped_entry)
                                entry_fee = self.fee_schedule.compute_fee(slipped_entry * qty)
                                order = Order(
                                    id=str(uuid.uuid4()),
                                    symbol=symbol,
                                    side=side,
                                    order_type=OrderType.MARKET,
                                    quantity=qty,
                                    price=slipped_entry,
                                    signal_id=signal.id,
                                    strategy_name=self.strategy.name,
                                )
                                # Store entry fee in signal meta for later
                                signal.meta["entry_fee"] = entry_fee
                                pending_order = (order, signal, i + self.latency_bars)

            # ---- Mark equity ----
            # cash for longs = initial - entry_notional; for shorts = initial + entry_notional.
            # Adding current_price * qty (long) or subtracting (short) recovers true equity.
            if position:
                if position.side == Side.LONG:
                    equity = cash + close * position.quantity
                else:
                    equity = cash - close * position.quantity
            else:
                equity = cash
            equity_series.append((df.index[i], equity))

            # Ruin check — stop simulation if equity drops below 10% of start
            if equity < self.initial_capital * 0.10:
                logger.warning("Backtest ruin at bar %d — equity=%.2f, stopping simulation", i, equity)
                break

        # Build equity curve
        eq_idx, eq_vals = zip(*equity_series) if equity_series else ([], [])
        result.equity_curve = pd.Series(eq_vals, index=eq_idx, name="equity")
        result.trades = trades

        # Compute metrics
        trade_returns = [t.return_pct for t in trades]
        bt_cfg = self.config.get("backtesting", {})
        result.metrics = compute_metrics(
            result.equity_curve,
            trade_returns,
            initial_capital=self.initial_capital,
            min_trades=bt_cfg.get("min_trades_for_validity", 30),
        )

        logger.info(
            "Backtest complete [%s/%s] %s",
            self.strategy.name, symbol, result.metrics.summary() if result.metrics else "no metrics",
        )
        return result


@dataclass
class BacktestPosition:
    """Internal tracking for an open backtest position."""
    symbol: str
    side: Side
    entry_price: float
    quantity: float
    entry_bar: int
    entry_time: Optional[datetime]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    strategy: str
    entry_fee: float = 0.0
