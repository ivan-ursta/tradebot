"""
exchange/binance/execution.py
==============================
Live order placement on Binance USDT-M Futures.

ONLY used when:
  - connect(live=True) was called on BinanceClient
  - BINANCE_LIVE_TRADING_ENABLED=true is set in the environment

All paper / simulation order flow uses the existing paper/ module instead.
"""

from __future__ import annotations

import logging
from typing import Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.models import Order, OrderStatus, OrderType, Side
from exchange.binance.client import BinanceClient, to_binance_symbol

logger = logging.getLogger(__name__)

_ORDER_PATH        = "/fapi/v1/order"
_OPEN_ORDERS_PATH  = "/fapi/v1/openOrders"
_ALL_ORDERS_PATH   = "/fapi/v1/allOrders"


class BinanceExecution:
    """
    Wraps Binance Futures REST for live order management.
    Mirrors the interface of exchange.ExecutionClient.
    """

    def __init__(self, client: BinanceClient) -> None:
        self._client = client

    # ── Order placement ───────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def place_order(self, order: Order) -> str:
        """
        Place a market or limit order.
        Returns the Binance orderId as string.
        Raises on failure after 3 retries.
        """
        if not self._client.is_live:
            raise RuntimeError("BinanceExecution.place_order called but not in live mode")

        binance_sym = to_binance_symbol(order.symbol)
        side_str = "BUY" if order.side == Side.LONG else "SELL"

        params: dict = {
            "symbol":    binance_sym,
            "side":      side_str,
            "type":      "MARKET" if order.order_type == OrderType.MARKET else "LIMIT",
            "quantity":  f"{order.quantity:.6f}",
        }

        if order.order_type == OrderType.LIMIT:
            if order.price is None:
                raise ValueError(f"Limit order for {order.symbol} has no price set")
            params["price"] = f"{order.price:.4f}"
            params["timeInForce"] = "GTC"

        if getattr(order, "reduce_only", False):
            params["reduceOnly"] = "true"

        response = self._client.signed_post(_ORDER_PATH, params)

        order_id = str(response.get("orderId", ""))
        if not order_id:
            raise RuntimeError(f"No orderId in response: {response}")

        logger.info(
            "Order placed [%s] side=%s qty=%.6f price=%s oid=%s",
            order.symbol, order.side.value, order.quantity, order.price, order_id,
        )
        return order_id

    # ── Cancellation ──────────────────────────────────────────────────────

    def cancel_order(self, symbol: str, exchange_order_id: str) -> bool:
        if not self._client.is_live:
            raise RuntimeError("Not in live mode")
        try:
            binance_sym = to_binance_symbol(symbol)
            self._client.signed_delete(
                _ORDER_PATH,
                {"symbol": binance_sym, "orderId": int(exchange_order_id)},
            )
            logger.info("Order cancelled [%s] oid=%s", symbol, exchange_order_id)
            return True
        except Exception as exc:
            logger.error("Cancel failed [%s/%s]: %s", symbol, exchange_order_id, exc)
            return False

    def cancel_all_orders(self, symbol: str) -> int:
        if not self._client.is_live:
            raise RuntimeError("Not in live mode")
        try:
            binance_sym = to_binance_symbol(symbol)
            resp = self._client.signed_delete(
                _OPEN_ORDERS_PATH, {"symbol": binance_sym}
            )
            count = len(resp) if isinstance(resp, list) else 0
            logger.info("Cancelled %d open orders for %s", count, symbol)
            return count
        except Exception as exc:
            logger.error("Cancel-all error [%s]: %s", symbol, exc)
            return 0

    # ── Close position ────────────────────────────────────────────────────

    def close_position_market(self, symbol: str, quantity: float, side: Side) -> bool:
        """
        Close a position with a reduce-only market order.
        side = the current POSITION side (LONG → we need to SELL to close).
        """
        if not self._client.is_live:
            raise RuntimeError("Not in live mode")
        binance_sym = to_binance_symbol(symbol)
        close_side = "SELL" if side == Side.LONG else "BUY"
        try:
            self._client.signed_post(_ORDER_PATH, {
                "symbol":     binance_sym,
                "side":       close_side,
                "type":       "MARKET",
                "quantity":   f"{quantity:.6f}",
                "reduceOnly": "true",
            })
            logger.info(
                "Position closed [%s] side=%s qty=%.6f", symbol, side.value, quantity
            )
            return True
        except Exception as exc:
            logger.error("Close position failed [%s]: %s", symbol, exc)
            return False

    # ── Order status ──────────────────────────────────────────────────────

    def get_order_status(self, symbol: str, exchange_order_id: str) -> Optional[OrderStatus]:
        try:
            binance_sym = to_binance_symbol(symbol)
            resp = self._client.signed_get(
                _ORDER_PATH,
                {"symbol": binance_sym, "orderId": int(exchange_order_id)},
            )
            status_str = resp.get("status", "")
            mapping = {
                "FILLED":           OrderStatus.FILLED,
                "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
                "NEW":              OrderStatus.OPEN,
                "CANCELED":         OrderStatus.CANCELLED,
                "EXPIRED":          OrderStatus.CANCELLED,
            }
            return mapping.get(status_str, OrderStatus.OPEN)
        except Exception as exc:
            logger.error("get_order_status error: %s", exc)
            return None
