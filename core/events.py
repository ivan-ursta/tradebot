"""
core/events.py
==============
Simple synchronous event bus for inter-module communication.
Components publish events; subscribers react without tight coupling.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    # Market data
    CANDLE_CLOSED = "candle_closed"
    TICKER_UPDATE = "ticker_update"
    ORDER_BOOK_UPDATE = "order_book_update"

    # Strategy
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_REJECTED = "signal_rejected"

    # Orders
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    ORDER_EXPIRED = "order_expired"

    # Risk
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    TRAILING_STOP_UPDATED = "trailing_stop_updated"
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    RISK_CHECK_FAILED = "risk_check_failed"

    # Position
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATED = "position_updated"

    # Account
    DAILY_PNL_UPDATED = "daily_pnl_updated"
    ACCOUNT_STATE_UPDATED = "account_state_updated"

    # System
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""
    payload: Any = None


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

Handler = Callable[[Event], None]


class EventBus:
    """
    Synchronous publish/subscribe event bus.
    Thread-safety note: not thread-safe by default; wrap with locks if
    running strategies in separate threads.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Handler]] = defaultdict(list)
        self._global_handlers: list[Handler] = []

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Subscribe handler to a specific event type."""
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed %s to %s", handler.__qualname__, event_type.value)

    def subscribe_all(self, handler: Handler) -> None:
        """Subscribe handler to ALL event types."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    def publish(self, event: Event) -> None:
        """Dispatch event to all registered handlers."""
        handlers = self._handlers.get(event.type, []) + self._global_handlers
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Handler %s raised on event %s: %s",
                    handler.__qualname__,
                    event.type.value,
                    exc,
                )

    def emit(
        self,
        event_type: EventType,
        source: str = "",
        payload: Any = None,
    ) -> None:
        """Convenience wrapper: create and publish in one call."""
        self.publish(Event(type=event_type, source=source, payload=payload))


# Singleton bus — import and use everywhere
bus = EventBus()
