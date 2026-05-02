"""
core/models.py
==============
Shared domain models used across the entire system.
All data classes are immutable where possible (frozen=True).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candle:
    """OHLCV candle."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str

    def is_valid(self) -> bool:
        return (
            self.high >= self.low
            and self.high >= self.open
            and self.high >= self.close
            and self.low <= self.open
            and self.low <= self.close
            and self.volume >= 0
        )


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    timestamp: datetime
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_fraction(self) -> Optional[float]:
        mid = self.mid_price
        spread = self.spread
        if mid and spread and mid > 0:
            return spread / mid
        return None


@dataclass(frozen=True)
class Ticker:
    symbol: str
    timestamp: datetime
    last_price: float
    bid: Optional[float]
    ask: Optional[float]
    volume_24h: Optional[float]
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """Trading signal produced by a strategy."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    strategy_name: str = ""
    symbol: str = ""
    direction: SignalDirection = SignalDirection.FLAT
    timestamp: datetime = field(default_factory=datetime.utcnow)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 1.0          # 0–1 scalar for position sizing
    regime: MarketRegime = MarketRegime.UNKNOWN
    meta: dict = field(default_factory=dict)

    def is_actionable(self) -> bool:
        return self.direction != SignalDirection.FLAT


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@dataclass
class Order:
    """Represents a submitted or pending order."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    exchange_order_id: Optional[str] = None
    symbol: str = ""
    side: Side = Side.LONG
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    price: Optional[float] = None           # limit price
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    filled_quantity: float = 0.0
    avg_fill_price: Optional[float] = None
    fees_paid: float = 0.0
    signal_id: Optional[str] = None
    strategy_name: str = ""
    reduce_only: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    @property
    def is_done(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED)

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)


# ---------------------------------------------------------------------------
# Fills / Trades
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fill:
    """Represents a confirmed execution."""

    id: str
    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float
    fee_asset: str
    timestamp: datetime
    strategy_name: str
    is_paper: bool = True


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """Live or paper position."""

    symbol: str
    side: Side
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    liquidation_price: Optional[float] = None
    leverage: float = 1.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None
    opened_at: datetime = field(default_factory=datetime.utcnow)
    strategy_name: str = ""

    @property
    def notional_value(self) -> float:
        return abs(self.quantity * self.avg_entry_price)

    def mark_to_market(self, current_price: float) -> float:
        """Calculate unrealized PnL at current_price."""
        if self.side == Side.LONG:
            pnl = (current_price - self.avg_entry_price) * self.quantity
        else:
            pnl = (self.avg_entry_price - current_price) * self.quantity
        self.unrealized_pnl = pnl
        return pnl


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


@dataclass
class AccountState:
    timestamp: datetime
    equity: float
    available_balance: float
    used_margin: float
    unrealized_pnl: float
    positions: list[Position] = field(default_factory=list)
    open_orders: list[Order] = field(default_factory=list)

    @property
    def total_position_value(self) -> float:
        return sum(p.notional_value for p in self.positions)


# ---------------------------------------------------------------------------
# Market info
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    min_order_size: float
    tick_size: float
    lot_size: float
    max_leverage: float
    is_active: bool
    contract_type: str = "perpetual"

    def round_price(self, price: float) -> float:
        if self.tick_size <= 0:
            return price
        return round(round(price / self.tick_size) * self.tick_size, 10)

    def round_quantity(self, qty: float) -> float:
        if self.lot_size <= 0:
            return qty
        return round(round(qty / self.lot_size) * self.lot_size, 10)
