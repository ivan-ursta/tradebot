"""bridge/ws_broadcaster.py — WebSocket fan-out to browser clients."""

from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import web

from bridge.event_bridge import EventBridge
from bridge.serializers import serialize_event, serialize_state
from core.state import TradingState

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = 5  # seconds


class WSBroadcaster:
    def __init__(self, event_bridge: EventBridge, state: TradingState) -> None:
        self._event_bridge = event_bridge
        self._state = state
        self._clients: set[web.WebSocketResponse] = set()

    async def handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("WebSocket client connected (%d total)", len(self._clients))
        try:
            # Send immediate snapshot on connect
            snapshot = json.dumps({
                "type": "state_snapshot",
                "data": serialize_state(self._state),
            })
            await ws.send_str(snapshot)
            async for _ in ws:
                pass  # consume ping/pong frames; ignore any client messages
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            logger.info("WebSocket client disconnected (%d remaining)", len(self._clients))
        return ws

    async def broadcast_events_loop(self) -> None:
        while True:
            try:
                event = await self._event_bridge.get()
                payload = json.dumps({
                    "type": "event",
                    "data": serialize_event(event),
                })
                await self._send_all(payload)
            except Exception as exc:
                logger.error("broadcast_events_loop error: %s", exc)

    async def broadcast_snapshot_loop(self) -> None:
        while True:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            try:
                payload = json.dumps({
                    "type": "state_snapshot",
                    "data": serialize_state(self._state),
                })
                await self._send_all(payload)
            except Exception as exc:
                logger.error("broadcast_snapshot_loop error: %s", exc)

    async def _send_all(self, payload: str) -> None:
        dead: set[web.WebSocketResponse] = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead
