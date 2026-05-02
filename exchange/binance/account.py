"""
exchange/binance/account.py
============================
Read-only account state from Binance USDT-M Futures.
Mirrors the interface of exchange.AccountClient.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from core.models import AccountState, Order, OrderStatus, OrderType, Position, Side
from exchange.binance.client import BinanceClient, from_binance_symbol, to_binance_symbol

logger = logging.getLogger(__name__)

_ACCOUNT_PATH     = "/fapi/v2/account"
_POSITION_PATH    = "/fapi/v2/positionRisk"
_OPEN_ORDERS_PATH = "/fapi/v1/openOrders"


class BinanceAccount:
    """
    Wraps Binance Futures REST for account state queries.
    Requires connect(live=True) on the underlying BinanceClient.
    """

    def __init__(self, client: BinanceClient) -> None:
        self._client = client

    def get_account_state(self) -> Optional[AccountState]:
        """Fetch full account snapshot: equity, margin, unrealized PnL, positions."""
        try:
            data = self._client.signed_get(_ACCOUNT_PATH)
            equity      = float(data.get("totalWalletBalance", 0))
            available   = float(data.get("availableBalance", equity))
            used_margin = float(data.get("totalInitialMargin", 0))
            unrealized  = float(data.get("totalUnrealizedProfit", 0))

            positions = self._parse_positions(data.get("positions", []))

            return AccountState(
                timestamp=datetime.now(timezone.utc),
                equity=equity + unrealized,   # mark-to-market equity
                available_balance=available,
                used_margin=used_margin,
                unrealized_pnl=unrealized,
                positions=positions,
                open_orders=[],
            )
        except Exception as exc:
            logger.error("get_account_state error: %s", exc)
            return None

    def get_positions(self) -> List[Position]:
        """Return all non-zero positions."""
        try:
            raw = self._client.signed_get(_POSITION_PATH)
            return self._parse_positions(raw)
        except Exception as exc:
            logger.error("get_positions error: %s", exc)
            return []

    def get_open_orders(self) -> List[Order]:
        """Return all open orders across all symbols."""
        try:
            raw = self._client.signed_get(_OPEN_ORDERS_PATH)
            result: List[Order] = []
            for o in raw:
                try:
                    side_str = o.get("side", "BUY")
                    otype = o.get("type", "LIMIT")
                    result.append(Order(
                        exchange_order_id=str(o["orderId"]),
                        symbol=from_binance_symbol(o.get("symbol", "")),
                        side=Side.LONG if side_str == "BUY" else Side.SHORT,
                        order_type=OrderType.MARKET if otype == "MARKET" else OrderType.LIMIT,
                        quantity=float(o.get("origQty", 0)),
                        price=float(o["price"]) if float(o.get("price", 0)) > 0 else None,
                        status=OrderStatus.OPEN,
                    ))
                except (KeyError, ValueError) as exc:
                    logger.warning("Malformed open order: %s — %s", o, exc)
            return result
        except Exception as exc:
            logger.error("get_open_orders error: %s", exc)
            return []

    @staticmethod
    def _parse_positions(raw: list) -> List[Position]:
        positions: List[Position] = []
        for item in raw:
            try:
                amt = float(item.get("positionAmt", 0))
                if amt == 0:
                    continue
                sym = from_binance_symbol(item.get("symbol", ""))
                side = Side.LONG if amt > 0 else Side.SHORT
                entry_px  = float(item.get("entryPrice", 0) or 0)
                unrealized = float(item.get("unrealizedProfit", 0) or 0)
                liq_px_raw = item.get("liquidationPrice")
                liq_px = float(liq_px_raw) if liq_px_raw and float(liq_px_raw) > 0 else None
                leverage   = float(item.get("leverage", 1) or 1)
                positions.append(Position(
                    symbol=sym,
                    side=side,
                    quantity=abs(amt),
                    avg_entry_price=entry_px,
                    unrealized_pnl=unrealized,
                    liquidation_price=liq_px,
                    leverage=leverage,
                ))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Malformed position: %s — %s", item, exc)
        return positions
