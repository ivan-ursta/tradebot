"""
app/runner.py
=============
Orchestrates the full application lifecycle:
  - Loads config and validates it
  - Connects exchange clients
  - Selects eligible markets
  - Builds strategies
  - Wires up risk, order manager, paper broker
  - Starts the trading engine or backtesting pipeline
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import List

import yaml
from aiohttp import web
from dotenv import load_dotenv

from core.engine import TradingEngine
from core.models import TradingMode
from core.state import TradingState
from exchange.account_client import AccountClient
from exchange.execution_client import ExecutionClient
from exchange.hyperliquid_client import HyperliquidClient
from exchange.market_data_client import MarketDataClient
from execution.fee_model import FeeSchedule, HYPERLIQUID_DEFAULT
from execution.order_manager import OrderManager
from paper.paper_broker import PaperBroker
from paper.paper_exchange import PaperExchange
from risk.kill_switch import KillSwitch, RiskManager
from risk.portfolio_limits import PortfolioLimits
from risk.position_sizing import PositionSizer
from strategies.strategy_registry import build_strategies
from storage.sqlite_store import SQLiteStore
from storage.csv_exporter import CSVExporter
from utils.validators import validate_config

logger = logging.getLogger(__name__)


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


async def select_eligible_markets(
    market_data: MarketDataClient,
    config: dict,
    whitelist: List[str],
) -> List[str]:
    """Filter whitelist by volume and spread criteria."""
    markets_cfg = config.get("markets", {})
    min_volume = markets_cfg.get("min_volume_usd", 5_000_000)
    max_spread = markets_cfg.get("max_spread_fraction", 0.002)
    min_candles = markets_cfg.get("min_candle_history", 100)
    timeframe = config.get("strategy", {}).get("timeframe", "15m")

    eligible = []
    mids = await market_data.get_all_mids()

    for symbol in whitelist:
        if symbol not in mids:
            logger.info("Skipping %s — not in mids feed", symbol)
            continue

        # Check candle availability
        df = await market_data.get_candles(symbol, timeframe, limit=min_candles + 10)
        if df is None or len(df) < min_candles:
            logger.info("Skipping %s — insufficient candle history (%d)", symbol, len(df) if df is not None else 0)
            continue

        # Check order book for spread
        book = await market_data.get_order_book(symbol)
        if book and book.spread_fraction:
            if book.spread_fraction > max_spread:
                logger.info("Skipping %s — spread too wide (%.4f%%)", symbol, book.spread_fraction * 100)
                continue

        eligible.append(symbol)
        logger.info("Market eligible: %s", symbol)

    if not eligible:
        logger.warning("No eligible markets found! Using whitelist as fallback.")
        eligible = whitelist

    return eligible


async def run_paper_trading(config: dict) -> None:
    """Main paper-trading loop."""
    load_dotenv()

    errors = validate_config(config)
    if errors:
        for e in errors:
            logger.error("Config error: %s", e)
        raise ValueError(f"Config validation failed: {errors}")

    # Exchange clients (read-only for paper)
    hl_client = HyperliquidClient()
    hl_client.connect(live=False)
    market_data = MarketDataClient(hl_client)

    # Select markets
    whitelist = config["markets"]["whitelist"]
    eligible_symbols = await select_eligible_markets(market_data, config, whitelist)
    logger.info("Trading symbols: %s", eligible_symbols)

    # State
    paper_cfg = config.get("paper", {})
    starting_balance = float(os.environ.get("PAPER_BALANCE", paper_cfg.get("starting_balance", 10_000)))
    state = TradingState(starting_equity=starting_balance)
    state.config_ref = config  # allow strategies to access config

    # Paper broker
    fee_schedule = FeeSchedule(taker_rate=paper_cfg.get("fee_rate", 0.0004))
    paper_broker = PaperBroker(
        starting_balance=starting_balance,
        fee_schedule=fee_schedule,
        slippage_bps=paper_cfg.get("slippage_bps", 5),
    )
    paper_exchange = PaperExchange(paper_broker)

    # Strategies
    strategies = build_strategies(config)

    # Risk
    portfolio_limits = PortfolioLimits(config)
    kill_switch = KillSwitch(config)
    risk_manager = RiskManager(config, portfolio_limits, kill_switch)

    # Position sizer
    sizer = PositionSizer(config)

    # Order manager (paper mode)
    order_manager = OrderManager(
        config=config,
        state=state,
        mode=TradingMode.PAPER,
        paper_broker=paper_broker,
    )

    # Storage
    db_path = config.get("storage", {}).get("db_path", "data/trading.db")
    store = SQLiteStore(db_path)

    # Engine
    engine = TradingEngine(
        config=config,
        state=state,
        market_data_client=market_data,
        execution_client=None,
        strategies=strategies,
        risk_manager=risk_manager,
        position_sizer=sizer,
        order_manager=order_manager,
        mode=TradingMode.PAPER,
    )

    logger.info("=" * 60)
    logger.info("Paper trading started | balance=%.2f | symbols=%s", starting_balance, eligible_symbols)
    logger.info("=" * 60)

    # --- Web dashboard bridge ---
    from bridge.event_bridge import EventBridge
    from bridge.ws_broadcaster import WSBroadcaster
    from bridge.http_server import create_bridge_app

    event_bridge = EventBridge()
    event_bridge.install()
    broadcaster = WSBroadcaster(event_bridge, state)
    bridge_app = create_bridge_app(
        state=state,
        engine=engine,
        order_manager=order_manager,
        event_bridge=event_bridge,
        broadcaster=broadcaster,
        paper_broker=paper_broker,
        store=store,
        config=config,
    )
    bridge_port = int(os.environ.get("BRIDGE_PORT", "8765"))
    bridge_host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    bridge_runner = web.AppRunner(bridge_app)
    await bridge_runner.setup()
    bridge_site = web.TCPSite(bridge_runner, bridge_host, bridge_port)
    await bridge_site.start()
    logger.info("Bridge server started on http://%s:%d", bridge_host, bridge_port)
    # --- End bridge setup ---

    try:
        await asyncio.gather(
            engine.start(eligible_symbols),
            broadcaster.broadcast_events_loop(),
            broadcaster.broadcast_snapshot_loop(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down paper trading session...")
    finally:
        await bridge_runner.cleanup()
        mids = await market_data.get_all_mids()
        paper_exchange.print_session_summary(mids)

        # Export trades
        exporter = CSVExporter(config.get("storage", {}).get("csv_export_path", "data/exports/"))
        trades = paper_broker.pnl_tracker.trades
        if trades:
            exporter.export_trades(trades, "paper_trades.csv")
        logger.info("Session ended. Trades exported.")


async def run_backtest(config: dict, symbol: str = "BTC") -> None:
    """
    Run a full backtest + walk-forward analysis for all active strategies.
    CPU-heavy bt.run() / wfa.run() calls are offloaded to a thread pool so
    the asyncio event loop (and the bridge HTTP server) stays responsive.
    """
    load_dotenv()
    hl_client = HyperliquidClient()
    hl_client.connect(live=False)
    market_data = MarketDataClient(hl_client)

    timeframe = config.get("strategy", {}).get("timeframe", "15m")
    bt_cfg = config.get("backtesting", {})
    initial_capital = bt_cfg.get("initial_capital", 10_000.0)

    logger.info("Fetching backtest data for %s/%s...", symbol, timeframe)
    df = await market_data.get_candles(symbol, timeframe, limit=5000)
    if df is None or len(df) < 200:
        logger.error("Insufficient data for backtest")
        return

    logger.info("Fetched %d candles", len(df))

    from backtesting.backtester import Backtester
    from backtesting.walk_forward import WalkForwardAnalyzer
    from execution.fee_model import FeeSchedule

    strategies = build_strategies(config)
    exporter = CSVExporter(config.get("storage", {}).get("csv_export_path", "data/exports/"))

    for strategy in strategies:
        logger.info("\n%s\nBacktesting: %s on %s\n%s", "=" * 50, strategy.name, symbol, "=" * 50)

        # Split data
        n = len(df)
        train_end = int(n * bt_cfg.get("train_fraction", 0.6))
        val_end = int(n * (bt_cfg.get("train_fraction", 0.6) + bt_cfg.get("validation_fraction", 0.2)))

        train_df = df.iloc[:train_end]
        val_df = df.iloc[train_end:val_end]
        test_df = df.iloc[val_end:]

        fee_schedule = FeeSchedule(taker_rate=bt_cfg.get("fee_rate", 0.0004))
        bt = Backtester(
            config, strategy,
            fee_schedule=fee_schedule,
            slippage_bps=bt_cfg.get("slippage_bps", 5),
            initial_capital=initial_capital,
        )

        def _print(msg: str) -> None:
            print(msg)
            logger.info(msg)

        loop = asyncio.get_event_loop()

        # Run CPU-heavy synchronous backtests in a thread pool so the event
        # loop (and the bridge HTTP server) stays responsive during the run.
        train_result = await loop.run_in_executor(None, bt.run, train_df, symbol)
        is_summary = train_result.metrics.summary() if train_result.metrics else "N/A"
        _print(f"\n{'='*60}")
        _print(f"Strategy : {strategy.name}  |  Symbol : {symbol}  |  TF : {timeframe}")
        _print(f"Data     : {len(df)} candles  |  Capital : ${initial_capital:,.0f}")
        _print(f"{'='*60}")
        _print(f"[IN-SAMPLE   {len(train_df):4d} bars]  {is_summary}")

        val_result = await loop.run_in_executor(None, bt.run, val_df, symbol)
        _print(f"[VALIDATION  {len(val_df):4d} bars]  {val_result.metrics.summary() if val_result.metrics else 'N/A'}")

        test_result = await loop.run_in_executor(None, bt.run, test_df, symbol)
        _print(f"[OUT-OF-SAMPLE {len(test_df):3d} bars]  {test_result.metrics.summary() if test_result.metrics else 'N/A'}")

        # Overfitting check
        if train_result.metrics and test_result.metrics:
            from backtesting.metrics import overfitting_warning
            oof_warnings = overfitting_warning(train_result.metrics, test_result.metrics)
            for w in oof_warnings:
                _print(f"⚠  OVERFIT CHECK: {w}")

        # Walk-forward
        _print(f"\n--- Walk-Forward Analysis ({bt_cfg.get('walk_forward_windows', 5)} windows) ---")

        def make_strategy(cfg):
            from strategies.strategy_registry import STRATEGY_REGISTRY
            cls = STRATEGY_REGISTRY.get(strategy.name.lower())
            # Try exact name match
            for k, v in STRATEGY_REGISTRY.items():
                if v.__name__ == strategy.__class__.__name__:
                    return v(cfg)
            return strategy.__class__(cfg)

        wfa = WalkForwardAnalyzer(
            config, make_strategy,
            n_windows=bt_cfg.get("walk_forward_windows", 5),
            initial_capital=initial_capital,
        )
        wf_result = await loop.run_in_executor(None, wfa.run, df, symbol)
        _print(wf_result.summary())

        # Export
        exporter.export_backtest_trades(test_result.trades, f"bt_{strategy.name}_{symbol}_oos.csv")
        exporter.export_equity_curve(test_result.equity_curve, f"equity_{strategy.name}_{symbol}.csv")

    logger.info("Backtest complete.")
