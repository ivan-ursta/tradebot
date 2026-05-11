"""bridge/http_server.py — aiohttp REST + WebSocket bridge server."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from bridge.serializers import serialize_position, serialize_state
from bridge.ws_broadcaster import WSBroadcaster

logger = logging.getLogger(__name__)


async def handle_status(request: web.Request) -> web.Response:
    state = request.app["state"]
    engine = request.app["engine"]
    paper_broker = request.app.get("paper_broker")

    pnl_data: dict = {}
    if paper_broker is not None:
        import math
        tracker = paper_broker.pnl_tracker
        pf = tracker.profit_factor
        pnl_data = {
            "total_pnl": tracker.total_pnl,
            "win_rate": tracker.win_rate,
            "profit_factor": None if (math.isnan(pf) or math.isinf(pf)) else pf,
            "trade_count": len(tracker.trades),
            "average_trade": tracker.average_trade,
        }

    data = {
        "mode": engine.mode.value if hasattr(engine, "mode") else "paper",
        "running": getattr(engine, "_running", False),
        "kill_switch_active": state.kill_switch_active,
        "kill_switch_reason": state.kill_switch_reason,
        "equity": state.equity,
        "available_balance": state.available_balance,
        "peak_equity": state.peak_equity,
        "starting_equity": state.starting_equity,
        "current_drawdown": state.current_drawdown,
        "open_position_count": state.open_position_count,
        "total_exposure_usd": state.total_exposure_usd,
        "daily_pnl_pct": state.daily.daily_pnl_pct,
        "daily_win_rate": state.daily.win_rate,
        "daily_trade_count": state.daily.trade_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **pnl_data,
    }
    return web.json_response(data)


async def handle_positions(request: web.Request) -> web.Response:
    state = request.app["state"]
    positions = [serialize_position(p) for p in state.positions.values() if p.quantity > 0]
    return web.json_response({"positions": positions, "count": len(positions)})


async def handle_strategies(request: web.Request) -> web.Response:
    state = request.app["state"]
    engine = request.app["engine"]

    strategy_names = [s.name for s in getattr(engine, "strategies", [])]
    cooldowns = {k: v.isoformat() + "Z" for k, v in state.cooldown_until.items()}
    regimes = {
        k: v.value if hasattr(v, "value") else str(v)
        for k, v in state.regimes.items()
    }

    strategies = []
    for name in strategy_names:
        strategies.append({
            "name": name,
            "consecutive_losses": state.consecutive_losses.get(name, 0),
            "cooldown_until": cooldowns.get(name),
            "in_cooldown": state.is_in_cooldown(name),
        })

    return web.json_response({
        "strategies": strategies,
        "regimes": regimes,
    })


async def handle_pnl(request: web.Request) -> web.Response:
    paper_broker = request.app.get("paper_broker")
    if paper_broker is None:
        return web.json_response({"error": "No paper broker"}, status=404)
    tracker = paper_broker.pnl_tracker
    import math
    pf = tracker.profit_factor
    daily = tracker.daily_summary()
    return web.json_response({
        "total_pnl": tracker.total_pnl,
        "win_rate": tracker.win_rate,
        "profit_factor": None if (math.isnan(pf) or math.isinf(pf)) else pf,
        "trade_count": len(tracker.trades),
        "average_trade": tracker.average_trade,
        "daily": {str(k): v for k, v in daily.items()},
    })


async def handle_close_position(request: web.Request) -> web.Response:
    symbol = request.match_info["symbol"].upper()
    state = request.app["state"]
    order_manager = request.app["order_manager"]

    if symbol not in state.positions:
        return web.json_response({"error": f"No open position for {symbol}"}, status=404)

    position = state.positions[symbol]
    try:
        order = await order_manager.close_position(position, reason="manual_close_via_ui")
        if order:
            return web.json_response({"closed": True, "symbol": symbol})
        return web.json_response({"error": "Close order failed"}, status=500)
    except Exception as exc:
        logger.exception("Error closing position %s", symbol)
        return web.json_response({"error": str(exc)}, status=500)


async def handle_trades(request: web.Request) -> web.Response:
    store = request.app.get("store")
    if store is None:
        return web.json_response({"trades": [], "total": 0})
    symbol = request.rel_url.query.get("symbol")
    strategy = request.rel_url.query.get("strategy")
    page = int(request.rel_url.query.get("page", "1"))
    limit = int(request.rel_url.query.get("limit", "50"))
    try:
        rows = store.get_trades(symbol=symbol, strategy=strategy)
        total = len(rows)
        start = (page - 1) * limit
        page_rows = rows[start: start + limit]
        trades = []
        for r in page_rows:
            row_dict = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
            for k, v in row_dict.items():
                if hasattr(v, "isoformat"):
                    row_dict[k] = v.isoformat() + "Z"
            trades.append(row_dict)
        return web.json_response({
            "trades": trades,
            "total": total,
            "page": page,
            "limit": limit,
        })
    except Exception as exc:
        logger.error("handle_trades error: %s", exc)
        return web.json_response({"trades": [], "total": 0})


async def handle_equity(request: web.Request) -> web.Response:
    store = request.app.get("store")
    if store is None:
        return web.json_response({"points": []})
    days = int(request.rel_url.query.get("days", "30"))
    try:
        from datetime import timedelta
        since = datetime.now(timezone.utc) - timedelta(days=days)
        from sqlalchemy import select, text
        from storage.sqlite_store import equity_table
        with store._engine.connect() as conn:
            q = select(equity_table).where(
                equity_table.c.timestamp >= since
            ).order_by(equity_table.c.timestamp)
            rows = conn.execute(q).fetchall()
        points = []
        for r in rows:
            row_dict = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
            for k, v in row_dict.items():
                if hasattr(v, "isoformat"):
                    row_dict[k] = v.isoformat() + "Z"
            points.append(row_dict)
        return web.json_response({"points": points})
    except Exception as exc:
        logger.error("handle_equity error: %s", exc)
        return web.json_response({"points": []})


async def handle_snapshot(request: web.Request) -> web.Response:
    state = request.app["state"]
    return web.json_response(serialize_state(state))


async def handle_candles(request: web.Request) -> web.Response:
    engine = request.app["engine"]
    symbol = request.match_info["symbol"].upper()
    timeframe = request.rel_url.query.get("timeframe", "15m")
    limit = min(int(request.rel_url.query.get("limit", "500")), 1000)

    try:
        df = await engine.market_data.get_candles(symbol, timeframe, limit)
        if df is None or df.empty:
            return web.json_response({"candles": [], "symbol": symbol, "timeframe": timeframe})

        candles = []
        for idx, row in df.iterrows():
            candles.append({
                "time": int(idx.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        return web.json_response({"candles": candles, "symbol": symbol, "timeframe": timeframe})
    except Exception as exc:
        logger.error("Candles fetch error %s/%s: %s", symbol, timeframe, exc)
        return web.json_response({"error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Backtest jobs — run in asyncio background tasks
# ---------------------------------------------------------------------------

_backtest_jobs: dict = {}
_job_counter = 0


async def handle_backtest_run(request: web.Request) -> web.Response:
    global _job_counter
    body = await request.json()
    symbol = body.get("symbol", "SOL").upper()

    _job_counter += 1
    job_id = f"bt_{int(asyncio.get_event_loop().time() * 1000)}_{_job_counter}"
    job = {"symbol": symbol, "running": True, "logs": [], "exit_code": None}
    _backtest_jobs[job_id] = job

    # Keep only last 5 jobs
    if len(_backtest_jobs) > 5:
        oldest = next(iter(_backtest_jobs))
        del _backtest_jobs[oldest]

    async def run():
        config = request.app["config"]
        try:
            from app.runner import run_backtest
            import io
            import contextlib

            # Capture log output via a queue-based handler
            import logging

            class ListHandler(logging.Handler):
                def emit(self, record):
                    job["logs"].append(self.format(record))

            handler = ListHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            # Hook root AND all non-propagating named loggers (logging.yaml sets propagate=false)
            hooked = [logging.getLogger()]
            for name in ("app", "backtesting", "strategies", "core", "paper", "execution"):
                lg = logging.getLogger(name)
                lg.addHandler(handler)
                hooked.append(lg)
            try:
                await run_backtest(config, symbol=symbol)
            finally:
                for lg in hooked:
                    lg.removeHandler(handler)

            job["exit_code"] = 0
        except Exception as exc:
            job["logs"].append(f"ERROR: {exc}")
            job["exit_code"] = 1
        finally:
            job["running"] = False

    asyncio.create_task(run())
    return web.json_response({"job_id": job_id, "symbol": symbol})


async def handle_backtest_status(request: web.Request) -> web.Response:
    job_id = request.match_info["job_id"]
    job = _backtest_jobs.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)
    since = int(request.rel_url.query.get("since", "0"))
    return web.json_response({
        "symbol": job["symbol"],
        "running": job["running"],
        "exit_code": job["exit_code"],
        "logs": job["logs"][since:],
        "total": len(job["logs"]),
    })


async def handle_backtest_results(request: web.Request) -> web.Response:
    symbol = request.match_info["symbol"].upper()
    exports_dir = Path("data/exports")

    def read_csv(p: Path):
        lines = p.read_text().strip().split("\n")
        headers = [h.strip() for h in lines[0].split(",")]
        rows = []
        for line in lines[1:]:
            vals = line.split(",")
            rows.append({headers[i]: vals[i].strip() if i < len(vals) else "" for i in range(len(headers))})
        return rows

    if not exports_dir.exists():
        return web.json_response({"error": "No results found. Run a backtest first."}, status=404)

    files = list(exports_dir.iterdir())
    equity_file = next((f for f in files if f.name.startswith("equity_") and f"_{symbol}.csv" in f.name), None)
    trades_file = next((f for f in files if f.name.startswith("bt_") and f"_{symbol}_oos.csv" in f.name), None)

    if not equity_file and not trades_file:
        return web.json_response({"error": "No results found. Run a backtest first."}, status=404)

    return web.json_response({
        "symbol": symbol,
        "equity": read_csv(equity_file) if equity_file else None,
        "trades": read_csv(trades_file) if trades_file else None,
    })


async def handle_backtest_list(request: web.Request) -> web.Response:
    exports_dir = Path("data/exports")
    if not exports_dir.exists():
        return web.json_response({"symbols": []})
    symbols = list({
        m.group(1).upper()
        for f in exports_dir.iterdir()
        if f.name.startswith("equity_")
        for m in [__import__("re").search(r"equity_[^_]+_(.+)\.csv$", f.name)]
        if m
    })
    return web.json_response({"symbols": symbols})


async def handle_get_symbols(request: web.Request) -> web.Response:
    engine = request.app["engine"]
    symbols = await engine.get_active_symbols()
    return web.json_response({"symbols": symbols, "count": len(symbols)})


async def handle_add_symbol(request: web.Request) -> web.Response:
    engine = request.app["engine"]
    try:
        body = await request.json()
        symbol = body.get("symbol", "").strip().upper()
        if not symbol:
            return web.json_response({"error": "symbol is required"}, status=400)
        result = await engine.add_symbol(symbol)
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error adding symbol")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_remove_symbol(request: web.Request) -> web.Response:
    engine = request.app["engine"]
    try:
        body = await request.json()
        symbol = body.get("symbol", "").strip().upper()
        if not symbol:
            return web.json_response({"error": "symbol is required"}, status=400)
        result = await engine.remove_symbol(symbol)
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error removing symbol")
        return web.json_response({"error": str(exc)}, status=500)


def create_bridge_app(
    state,
    engine,
    order_manager,
    event_bridge,
    broadcaster: WSBroadcaster,
    paper_broker=None,
    store=None,
    config=None,
) -> web.Application:
    app = web.Application()
    app["state"] = state
    app["engine"] = engine
    app["order_manager"] = order_manager
    app["event_bridge"] = event_bridge
    app["broadcaster"] = broadcaster
    app["paper_broker"] = paper_broker
    app["store"] = store
    app["config"] = config or {}

    app.router.add_get("/bridge/status", handle_status)
    app.router.add_get("/bridge/positions", handle_positions)
    app.router.add_get("/bridge/strategies", handle_strategies)
    app.router.add_get("/bridge/pnl", handle_pnl)
    app.router.add_get("/bridge/snapshot", handle_snapshot)
    app.router.add_get("/bridge/trades", handle_trades)
    app.router.add_get("/bridge/equity", handle_equity)
    app.router.add_post("/bridge/close/{symbol}", handle_close_position)
    app.router.add_get("/bridge/candles/{symbol}", handle_candles)
    app.router.add_get("/bridge/symbols",          handle_get_symbols)
    app.router.add_post("/bridge/symbols/add",     handle_add_symbol)
    app.router.add_post("/bridge/symbols/remove",  handle_remove_symbol)
    app.router.add_post("/bridge/backtest/run", handle_backtest_run)
    app.router.add_get("/bridge/backtest/status/{job_id}", handle_backtest_status)
    app.router.add_get("/bridge/backtest/results/{symbol}", handle_backtest_results)
    app.router.add_get("/bridge/backtest/list", handle_backtest_list)
    app.router.add_get("/bridge/ws", broadcaster.handler)

    return app
