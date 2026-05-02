"""
exchange/websocket_client.py
============================
WebSocket streaming client for real-time price and fill updates.
Reconnects automatically on disconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Dict, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

from core.events import EventType, bus

logger = logging.getLogger(__name__)

# Hyperliquid WS endpoint
WS_URL = "wss://api.hyperliquid.xyz/ws"


class WebSocketClient:
    """
    Async WebSocket client.
    Subscribes to Hyperliquid feed channels and dispatches
    events to the internal event bus.
    """

    def __init__(
        self,
        url: str = WS_URL,
        wallet_address: Optional[str] = None,
    ) -> None:
        self._url = url
        self._wallet_address = wallet_address
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._subscribed_symbols: Set[str] = set()
        self._running = False
        self._reconnect_delay = 5  # seconds
        self._price_callbacks: list[Callable] = []
        self._fill_callbacks: list[Callable] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_price(self, callback: Callable) -> None:
        self._price_callbacks.append(callback)

    def on_fill(self, callback: Callable) -> None:
        self._fill_callbacks.append(callback)

    async def subscribe_symbols(self, symbols: list[str]) -> None:
        self._subscribed_symbols.update(symbols)

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as exc:  # noqa: BLE001
                logger.warning("WebSocket disconnected: %s — reconnecting in %ds", exc, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        logger.info("Connecting to WebSocket: %s", self._url)
        async with websockets.connect(
            self._url,
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            self._ws = ws
            logger.info("WebSocket connected")

            # Subscribe to all-mids (global price ticker)
            await self._send(ws, {"method": "subscribe", "subscription": {"type": "allMids"}})

            # Subscribe to user fills if wallet address is set
            if self._wallet_address:
                await self._send(
                    ws,
                    {
                        "method": "subscribe",
                        "subscription": {
                            "type": "userFills",
                            "user": self._wallet_address,
                        },
                    },
                )

            # Subscribe to order books for tracked symbols
            for symbol in self._subscribed_symbols:
                await self._send(
                    ws,
                    {
                        "method": "subscribe",
                        "subscription": {"type": "l2Book", "coin": symbol},
                    },
                )

            async for raw in ws:
                await self._handle_message(raw)

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        channel = msg.get("channel", "")
        data = msg.get("data", {})

        if channel == "allMids":
            # data = {"mids": {"BTC": "65000.0", ...}}
            mids: Dict[str, str] = data.get("mids", {})
            for symbol, price_str in mids.items():
                if symbol in self._subscribed_symbols:
                    try:
                        price = float(price_str)
                        for cb in self._price_callbacks:
                            cb(symbol, price)
                        bus.emit(EventType.TICKER_UPDATE, source="websocket",
                                 payload={"symbol": symbol, "price": price})
                    except (ValueError, TypeError):
                        pass

        elif channel == "userFills":
            fills = data if isinstance(data, list) else []
            for fill in fills:
                for cb in self._fill_callbacks:
                    cb(fill)
                bus.emit(EventType.ORDER_FILLED, source="websocket", payload=fill)

        elif channel == "l2Book":
            bus.emit(EventType.ORDER_BOOK_UPDATE, source="websocket", payload=data)

    @staticmethod
    async def _send(ws, message: dict) -> None:
        try:
            await ws.send(json.dumps(message))
        except Exception as exc:  # noqa: BLE001
            logger.warning("WS send error: %s", exc)
