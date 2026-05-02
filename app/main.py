"""
app/main.py
===========
CLI entry point for the trading bot.

Usage:
  python -m app.main --mode paper
  python -m app.main --mode backtest --symbol BTC
  python -m app.main --mode live   (requires LIVE_TRADING_ENABLED=true in .env)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.runner import load_config, run_backtest, run_paper_trading
from utils.logger import setup_logging
from utils.validators import validate_config

logger = logging.getLogger(__name__)


@click.group()
@click.option("--config", default="config/config.yaml", help="Config file path")
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    """Hyperliquid / trade.xyz trading bot."""
    ctx.ensure_object(dict)
    setup_logging()
    cfg = load_config(config)
    ctx.obj["config"] = cfg


@cli.command()
@click.pass_context
def paper(ctx: click.Context) -> None:
    """Run in paper trading mode (default, safe)."""
    config = ctx.obj["config"]
    config["trading"]["mode"] = "paper"
    asyncio.run(run_paper_trading(config))


@cli.command()
@click.option("--symbol", default="BTC", help="Symbol to backtest")
@click.pass_context
def backtest(ctx: click.Context, symbol: str) -> None:
    """Run backtesting + walk-forward analysis."""
    config = ctx.obj["config"]
    asyncio.run(run_backtest(config, symbol))


@cli.command()
@click.pass_context
def live(ctx: click.Context) -> None:
    """
    Run in LIVE trading mode.

    IMPORTANT: Live trading requires:
      1. LIVE_TRADING_ENABLED=true in your .env file
      2. Completed paper trading validation
      3. Walk-forward analysis showing OOS viability
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()

    if os.environ.get("LIVE_TRADING_ENABLED", "false").lower() != "true":
        click.echo(
            "ERROR: Live trading is disabled.\n"
            "Set LIVE_TRADING_ENABLED=true in .env ONLY after:\n"
            "  1. Paper trading for at least 2 weeks\n"
            "  2. Walk-forward validation with positive OOS metrics\n"
            "  3. Understanding all risk parameters in config.yaml",
            err=True,
        )
        sys.exit(1)

    config = ctx.obj["config"]
    config["trading"]["mode"] = "live"

    errors = validate_config(config)
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    click.confirm(
        f"⚠ LIVE TRADING — Are you sure you want to trade real funds on "
        f"{config['markets']['whitelist']}?",
        abort=True,
    )

    # Import live runner
    from app.runner import run_live_trading
    asyncio.run(run_live_trading(config))


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate config file."""
    config = ctx.obj["config"]
    errors = validate_config(config)
    if errors:
        click.echo("Config errors:")
        for e in errors:
            click.echo(f"  - {e}")
        sys.exit(1)
    else:
        click.echo("Config is valid.")


if __name__ == "__main__":
    cli()
