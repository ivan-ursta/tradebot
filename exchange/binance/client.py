"""
exchange/binance/client.py
==========================
Base Binance USDT-M Futures REST client.

Credentials are loaded from environment variables only:
    BINANCE_API_KEY     — required for authenticated endpoints
    BINANCE_API_SECRET  — required for authenticated endpoints

Safety guards
-------------
- Live order placement is gated by BINANCE_LIVE_TRADING_ENABLED=true
- Testnet is the default for authenticated sessions
- Public (read-only) endpoints never require credentials
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

# ── Endpoints ──────────────────────────────────────────────────────────────
FUTURES_MAINNET = "https://fapi.binance.com"
FUTURES_TESTNET = "https://testnet.binancefuture.com"

# Public data is always fetched from mainnet (testnet has sparse history)
FUTURES_PUBLIC = "https://fapi.binance.com"

WS_MAINNET = "wss://fstream.binance.com"
WS_TESTNET  = "wss://stream.binancefuture.com"

# Symbol map: short name (as used internally) → Binance futures symbol
SYMBOL_MAP: Dict[str, str] = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "SOL":  "SOLUSDT",
    "AVAX": "AVAXUSDT",
    "ARB":  "ARBUSDT",
    "OP":   "OPUSDT",
    "BNB":  "BNBUSDT",
    "DOGE": "DOGEUSDT",
    "LINK": "LINKUSDT",
    "ADA":  "ADAUSDT",
}


def to_binance_symbol(symbol: str) -> str:
    """Convert internal short symbol to Binance futures symbol (e.g. BTC → BTCUSDT)."""
    if symbol in SYMBOL_MAP:
        return SYMBOL_MAP[symbol]
    # If already looks like a full Binance symbol, return as-is
    if symbol.endswith("USDT") or symbol.endswith("BUSD"):
        return symbol
    return symbol + "USDT"


def from_binance_symbol(binance_sym: str) -> str:
    """Convert Binance symbol back to internal short name."""
    reverse = {v: k for k, v in SYMBOL_MAP.items()}
    return reverse.get(binance_sym, binance_sym.replace("USDT", "").replace("BUSD", ""))


class BinanceClient:
    """
    Thin wrapper around Binance USDT-M Futures REST API.

    Usage
    -----
    # Public data (no credentials required)
    client = BinanceClient()
    client.connect()

    # Authenticated (testnet by default)
    client = BinanceClient(use_testnet=True)
    client.connect(live=True)
    """

    def __init__(self, use_testnet: bool = True) -> None:
        self._use_testnet = use_testnet
        self._api_key: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._session: Optional[requests.Session] = None
        self._is_live: bool = False
        self._auth_base: str = FUTURES_TESTNET if use_testnet else FUTURES_MAINNET

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def connect(self, live: bool = False) -> None:
        """
        Initialise HTTP session.
        live=True enables authenticated (order-placing) endpoints.
        """
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "trade-bot/1.0"})

        if live:
            self._api_key = os.environ.get("BINANCE_API_KEY", "")
            self._api_secret = os.environ.get("BINANCE_API_SECRET", "")
            if not self._api_key or not self._api_secret:
                raise EnvironmentError(
                    "BINANCE_API_KEY and BINANCE_API_SECRET must be set for live mode"
                )
            live_flag = os.environ.get("BINANCE_LIVE_TRADING_ENABLED", "false").lower()
            if live_flag != "true":
                raise RuntimeError(
                    "BINANCE_LIVE_TRADING_ENABLED env var must be 'true' to enable live "
                    "trading. Set it explicitly after thorough paper-trading validation."
                )
            self._session.headers.update({"X-MBX-APIKEY": self._api_key})
            self._is_live = True
            logger.warning(
                "LIVE BINANCE TRADING ENABLED on %s",
                "testnet" if self._use_testnet else "MAINNET",
            )
        else:
            logger.info(
                "Binance client connected (read-only, public endpoints, %s)",
                "testnet auth base" if self._use_testnet else "mainnet auth base",
            )

    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def is_live(self) -> bool:
        return self._is_live

    @property
    def use_testnet(self) -> bool:
        return self._use_testnet

    @property
    def ws_base(self) -> str:
        return WS_TESTNET if self._use_testnet else WS_MAINNET

    # ── Public (unsigned) request ──────────────────────────────────────────

    def public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET against the public Binance Futures mainnet endpoint (no auth needed)."""
        if self._session is None:
            raise RuntimeError("Call connect() first")
        url = FUTURES_PUBLIC + path
        resp = self._session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── Authenticated (signed) requests ────────────────────────────────────

    def signed_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed_request("GET", path, params)

    def signed_post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed_request("POST", path, params)

    def signed_delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed_request("DELETE", path, params)

    def _signed_request(
        self, method: str, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        if not self._is_live:
            raise RuntimeError("Signed requests require connect(live=True)")
        if self._session is None:
            raise RuntimeError("Call connect() first")

        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 5000

        query = urlencode(p)
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        p["signature"] = signature

        url = self._auth_base + path
        resp = self._session.request(method, url, params=p, timeout=10)
        resp.raise_for_status()
        return resp.json()
