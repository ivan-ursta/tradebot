# TradeBot — Crypto Perpetuals Trading System

A production-style, modular Python trading system for crypto perpetual markets (Hyperliquid + Binance),
with a full-featured React web dashboard for monitoring, backtesting, and configuration.

**This system does NOT guarantee profits. All trading carries significant risk of loss.**

---

## Quick Start (Docker)

```bash
cp .env.example .env        # add your exchange credentials
docker compose up --build   # build and start everything
```

Open **http://localhost:3001** — the dashboard is ready.

---

## Architecture

```
React dashboard (web/client/)
        ↕  REST + WebSocket
Node.js gateway (web/server/)   ← serves static React build in Docker
        ↕  HTTP proxy
Python bridge (bridge/)         ← aiohttp REST + WebSocket server on :8765
        ↕  in-process
Trading Engine (core/, strategies/, risk/, execution/)
        ↕
Exchange APIs (Hyperliquid SDK / Binance REST+WS)
```

- **Python** owns all trading logic, state, and file exports. Runs as its own Docker container.
- **Node.js** is a pure proxy — no Python, no file access, just forwards requests to the bridge.
- **React** is display-only — all state arrives via WebSocket snapshots (every 5s) or REST polls.

---

## Dashboard Pages

| Page | Description |
|---|---|
| **Overview** | Live equity, drawdown, PnL, daily stats, kill-switch status |
| **Chart** | Real-time candlestick chart (lightweight-charts v5) with trade markers |
| **Positions** | Open positions with live PnL and manual close button |
| **Trade History** | Paginated trade log with symbol/strategy filters |
| **Equity Chart** | Historical equity curve from SQLite |
| **Signals Feed** | Live strategy signal stream via WebSocket |
| **Strategies** | Per-strategy state, consecutive losses, cooldown timers |
| **Backtest** | Run backtests in-browser, live log tail, metrics cards, OOS equity curve |
| **Config** | View current config.yaml |
| **Settings** | Edit all trading parameters live (risk, strategy, markets, paper config) |

---

## Project Layout

```
app/           — CLI entry point and runner orchestration
config/        — YAML configuration and logging config
core/          — Domain models, event bus, engine, shared state
exchange/      — Hyperliquid SDK adapter + Binance adapters
strategies/    — Strategy classes (breakout, mean reversion, funding momentum, MM)
indicators/    — Trend, momentum, volatility, volume, microstructure
risk/          — Position sizing, stops, portfolio limits, kill switch
portfolio/     — Portfolio accounting, PnL tracking, exposure
execution/     — Order manager, fill simulation, slippage, fee model
backtesting/   — Bar-by-bar backtester, metrics, optimizer, walk-forward
paper/         — Paper broker and simulated exchange
storage/       — SQLite persistence, CSV export
bridge/        — aiohttp REST + WebSocket server (Python ↔ Node.js)
web/server/    — Node.js/Express gateway
web/client/    — React + Vite + Tailwind dashboard
tests/         — Unit and integration tests (47 tests, no exchange required)
```

---

## Manual Setup (without Docker)

### 1. Install Python dependencies

```bash
python3 -m pip install -r requirements.txt --break-system-packages
```

### 2. Install Node dependencies

```bash
cd web/server && npm install
cd web/client && npm install
```

### 3. Configure credentials

```bash
cp .env.example .env
# Add Hyperliquid wallet address and/or Binance API keys
# Leave LIVE_TRADING_ENABLED=false (default)
```

### 4. Validate config

```bash
python3 -m app.main validate
```

### 5. Run (3 terminals)

```bash
# Terminal 1 — Python engine + bridge
python3 -m app.main paper

# Terminal 2 — Node.js gateway
cd web/server && node src/index.js

# Terminal 3 — React dev server (hot reload)
cd web/client && npm run dev
# open http://localhost:5173
```

---

## CLI Commands

```bash
python3 -m app.main paper                      # paper trading
python3 -m app.main backtest --symbol SOL      # backtest SOL
python3 -m app.main live                       # live trading (requires LIVE_TRADING_ENABLED=true)
python3 -m app.main validate                   # validate config
```

---

## Exchanges

| Exchange | Data | Execution | Notes |
|---|---|---|---|
| **Binance** | ✓ 3yr history | ✓ | Default for research and backtesting |
| **Hyperliquid** | ✓ Real-time | ✓ | Validated for live perp trading |

Set `trading.exchange: binance` or `trading.exchange: hyperliquid` in `config/config.yaml`.

---

## Strategies

| Strategy | Market Condition | Notes |
|---|---|---|
| `momentum_breakout` | Trending, high volume | Donchian channel breakout with volume gate |
| `mean_reversion` | Range-bound, low ADX | Auto-disabled in trending conditions |
| `funding_filter_momentum` | Any, with EMA cross | Uses funding rate as overcrowding filter |
| `market_making` | Liquid, low volatility | Requires low latency; use with caution |

Validated markets: **SOL** and **AVAX** on Hyperliquid 15m perps. BTC, ETH, OP, ARB were rejected by walk-forward analysis.

Set `strategy.active` in `config/config.yaml` to enable one or more strategies.

---

## Risk Management

All risk controls are mandatory and run before every order:

- **Max risk per trade**: 1% of equity (configurable)
- **Stop loss**: ATR-based, computed at signal time
- **Take profit**: ATR-based
- **Max daily loss**: 5% triggers session halt
- **Kill switch**: 15% drawdown from peak halts all trading
- **Cooldown**: 3 consecutive losses → 1-hour pause per strategy
- **Max positions**: 3 concurrent
- **Max leverage**: 5× cap

---

## Backtesting

Run from CLI:

```bash
python3 -m app.main backtest --symbol SOL
```

Or from the **Backtest** page in the dashboard.

Outputs:
- In-sample (60%), validation (20%), out-of-sample (20%) metrics
- Overfitting warnings (Sharpe degradation, win-rate collapse)
- Walk-forward analysis (5 windows)
- OOS trade CSV + equity curve CSV exported to `data/exports/`

**Metrics**: Total return, Sharpe, Sortino, Calmar, Max drawdown, Win rate, Profit factor, Trade count.

---

## Testing

```bash
python3 -m pytest tests/ -v
```

47 tests covering strategies, risk, fill simulation, fees, and backtester correctness.
No exchange connection required — all tests use synthetic data.

---

## Research

```bash
python3 -m research.run_binance_research          # 3yr Binance data, DonchianBreakout baseline
python3 -m research.run_binance_research --refresh  # re-download data
python3 -m research.adx_gate_test                 # ADX > 25 gate validation on SOL/AVAX
```

---

## Safety Rules

1. Never enable live trading without completing paper trading first.
2. Never set `LIVE_TRADING_ENABLED=true` without walk-forward validation.
3. Never set `max_risk_per_trade` above 2% without documented reason.
4. Never disable stop losses.
5. Never increase leverage above 5× without explicit risk analysis.
6. All credentials loaded from environment variables only — never hardcoded.

---

## Disclaimer

This software is for educational and research purposes.
Past backtest performance does not predict future results.
Cryptocurrency trading involves substantial risk of loss.
The authors provide no warranty or guarantee of profitability.
