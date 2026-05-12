"""bridge/serializers.py — Convert internal dataclasses to JSON-safe dicts."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from core.events import Event, EventType
from core.models import Fill, Position, Signal
from core.state import TradingState


def _safe_float(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _dt(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat() + "Z"
    return str(v)


def serialize_position(pos: Position) -> dict:
    return {
        "symbol": pos.symbol,
        "side": pos.side.value if hasattr(pos.side, "value") else pos.side,
        "quantity": _safe_float(pos.quantity),
        "avg_entry_price": _safe_float(pos.avg_entry_price),
        "unrealized_pnl": _safe_float(pos.unrealized_pnl),
        "realized_pnl": _safe_float(pos.realized_pnl),
        "notional_value": _safe_float(pos.notional_value),
        "leverage": _safe_float(getattr(pos, "leverage", 1.0)),
        "stop_loss": _safe_float(getattr(pos, "stop_loss", None)),
        "take_profit": _safe_float(getattr(pos, "take_profit", None)),
        "strategy_name": getattr(pos, "strategy_name", None),
        "opened_at": _dt(getattr(pos, "opened_at", None)),
    }


def serialize_fill(fill: Fill) -> dict:
    return {
        "id": fill.id,
        "order_id": fill.order_id,
        "symbol": fill.symbol,
        "side": fill.side.value if hasattr(fill.side, "value") else fill.side,
        "quantity": _safe_float(fill.quantity),
        "price": _safe_float(fill.price),
        "fee": _safe_float(fill.fee),
        "fee_asset": getattr(fill, "fee_asset", "USD"),
        "timestamp": _dt(fill.timestamp),
        "strategy_name": fill.strategy_name,
        "is_paper": fill.is_paper,
    }


def serialize_signal(signal: Signal) -> dict:
    return {
        "id": getattr(signal, "id", None),
        "strategy_name": signal.strategy_name,
        "symbol": signal.symbol,
        "direction": signal.direction.value if hasattr(signal.direction, "value") else signal.direction,
        "timestamp": _dt(signal.timestamp),
        "entry_price": _safe_float(signal.entry_price),
        "stop_loss": _safe_float(signal.stop_loss),
        "take_profit": _safe_float(signal.take_profit),
        "confidence": _safe_float(signal.confidence),
        "regime": signal.regime.value if hasattr(signal.regime, "value") else str(signal.regime),
        "meta": signal.meta or {},
    }


def serialize_state(state: TradingState) -> dict:
    positions = {
        sym: serialize_position(pos)
        for sym, pos in state.positions.items()
    }
    recent_fills = [serialize_fill(f) for f in list(state.recent_fills)[-20:]]
    cooldowns = {
        k: _dt(v) for k, v in state.cooldown_until.items()
    }
    regimes = {
        k: v.value if hasattr(v, "value") else str(v)
        for k, v in state.regimes.items()
    }
    return {
        "equity": _safe_float(state.equity),
        "available_balance": _safe_float(state.available_balance),
        "peak_equity": _safe_float(state.peak_equity),
        "starting_equity": _safe_float(state.starting_equity),
        "current_drawdown": _safe_float(state.current_drawdown),
        "open_position_count": state.open_position_count,
        "total_exposure_usd": _safe_float(state.total_exposure_usd),
        "total_exposure_fraction": _safe_float(state.total_exposure_fraction),
        "kill_switch_active": state.kill_switch_active,
        "kill_switch_reason": state.kill_switch_reason,
        "positions": positions,
        "recent_fills": recent_fills,
        "regimes": regimes,
        "consecutive_losses": dict(state.consecutive_losses),
        "cooldown_until": cooldowns,
        "daily": {
            "date": state.daily.date,
            "starting_equity": _safe_float(state.daily.starting_equity),
            "current_equity": _safe_float(state.daily.current_equity),
            "realized_pnl": _safe_float(state.daily.realized_pnl),
            "trade_count": state.daily.trade_count,
            "win_count": state.daily.win_count,
            "daily_pnl_pct": _safe_float(state.daily.daily_pnl_pct),
            "win_rate": _safe_float(state.daily.win_rate),
        },
    }


def serialize_event(event: Event) -> dict:
    payload = _serialize_payload(event.type, event.payload)
    return {
        "event_type": event.type.value,
        "timestamp": _dt(event.timestamp),
        "source": event.source,
        "payload": payload,
    }


def _serialize_payload(event_type: EventType, payload: Any) -> Any:
    if payload is None:
        return None
    if event_type == EventType.SIGNAL_GENERATED and hasattr(payload, "strategy_name"):
        return serialize_signal(payload)
    if event_type in (EventType.POSITION_OPENED, EventType.POSITION_CLOSED, EventType.POSITION_UPDATED):
        if hasattr(payload, "symbol"):
            return serialize_position(payload)
    if event_type == EventType.ORDER_FILLED:
        if hasattr(payload, "order_id"):
            return serialize_fill(payload)
    if isinstance(payload, dict):
        result = {}
        for k, v in payload.items():
            if hasattr(v, "strategy_name"):  # Signal object
                result[k] = serialize_signal(v)
            elif hasattr(v, "symbol") and hasattr(v, "side"):  # Position object
                result[k] = serialize_position(v)
            elif isinstance(v, float):
                result[k] = _safe_float(v)
            else:
                result[k] = v
        return result
    if isinstance(payload, str):
        return payload
    return str(payload)
