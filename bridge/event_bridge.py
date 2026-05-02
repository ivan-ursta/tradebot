"""bridge/event_bridge.py — Adapter between synchronous EventBus and asyncio."""

from __future__ import annotations

import asyncio

from core.events import Event, EventType

TRACKED_EVENTS = {
    EventType.SIGNAL_GENERATED,
    EventType.SIGNAL_REJECTED,
    EventType.ORDER_FILLED,
    EventType.POSITION_OPENED,
    EventType.POSITION_CLOSED,
    EventType.POSITION_UPDATED,
    EventType.KILL_SWITCH_ACTIVATED,
    EventType.DAILY_PNL_UPDATED,
    EventType.ACCOUNT_STATE_UPDATED,
    EventType.STOP_LOSS_TRIGGERED,
    EventType.TAKE_PROFIT_TRIGGERED,
    EventType.RISK_CHECK_FAILED,
    EventType.ERROR,
}


class EventBridge:
    """
    Bridges the synchronous EventBus to an asyncio.Queue.
    The handler runs in the asyncio thread (EventBus is synchronous and
    runs in the same thread as the asyncio loop), so put_nowait is safe.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=500)

    def install(self) -> None:
        from core.events import bus
        bus.subscribe_all(self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.type not in TRACKED_EVENTS:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # drop oldest; UI is non-critical

    async def get(self) -> Event:
        return await self._queue.get()
