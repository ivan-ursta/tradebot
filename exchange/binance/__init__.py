"""
exchange/binance
================
Binance USDT-M Futures adapter.

Components
----------
BinanceClient       — base REST client (credentials, signing, rate-guard)
BinanceMarketData   — public candles, ticker, order-book, WebSocket streams
BinanceExecution    — authenticated order placement / cancellation
BinanceAccount      — authenticated account state, positions, open orders
"""

from exchange.binance.client import BinanceClient
from exchange.binance.market_data import BinanceMarketData
from exchange.binance.execution import BinanceExecution
from exchange.binance.account import BinanceAccount

__all__ = [
    "BinanceClient",
    "BinanceMarketData",
    "BinanceExecution",
    "BinanceAccount",
]
