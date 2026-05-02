"""
exchange/execution_client.py
=============================
Live order execution via Hyperliquid SDK.
All methods validate responses and log every action.
NEVER place orders without explicit risk-check approval upstream.
"""

from __future__ import annotations

import logging
from typing import Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.models import Order, OrderStatus, OrderType, Side
from exchange.hyperliquid_client import HyperliquidClient

logger = logging.getLogger(__name__)


class ExecutionClient:
    """
    Wraps Hyperliquid Exchange for live order placement.
    Only used when mode == LIVE and LIVE_TRADING_ENABLED == 'true'.
    """

    def __init__(self, client: HyperliquidClient) -> None:
        self._hl = client

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def place_order(self, order: Order) -> str:
        """
        Place a market or limit order.
        Returns the exchange-assigned order ID.
        Raises on failure after retries.
        """
        if not self._hl.is_live:
            raise RuntimeError("ExecutionClient.place_order called but not in live mode")

        is_buy = order.side == Side.LONG
        coin = order.symbol

        if order.order_type == OrderType.MARKET:
            response = self._hl.exchange.market_open(
                coin=coin,
                is_buy=is_buy,
                sz=order.quantity,
                slippage=0.005,  # 0.5% max slippage for market orders
                cloid=None,
            )
        else:
            if order.price is None:
                raise ValueError(f"Limit order for {coin} has no price set")
            response = self._hl.exchange.order(
                coin=coin,
                is_buy=is_buy,
                sz=order.quantity,
                limit_px=order.price,
                order_type={"limit": {"tif": "Gtc"}},
                reduce_only=order.reduce_only,
            )

        HyperliquidClient._validate_response(response, f"place_order({coin})")

        # Extract order id from response
        statuses = response.get("response", {}).get("data", {}).get("statuses", [])
        if statuses:
            oid = statuses[0].get("resting", {}).get("oid") or statuses[0].get("filled", {}).get("oid")
            if oid:
                logger.info(
                    "Order placed [%s] side=%s qty=%.4f price=%s oid=%s",
                    coin, order.side.value, order.quantity, order.price, oid,
                )
                return str(oid)

        raise RuntimeError(f"Could not extract order ID from response: {response}")

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel_order(self, symbol: str, exchange_order_id: str) -> bool:
        """Cancel an open order. Returns True if successfully cancelled."""
        if not self._hl.is_live:
            raise RuntimeError("Not in live mode")
        try:
            response = self._hl.exchange.cancel(
                coin=symbol, oid=int(exchange_order_id)
            )
            HyperliquidClient._validate_response(response, f"cancel_order({symbol},{exchange_order_id})")
            logger.info("Order cancelled [%s] oid=%s", symbol, exchange_order_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Cancel failed [%s/%s]: %s", symbol, exchange_order_id, exc)
            return False

    def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all open orders for a symbol. Returns count cancelled."""
        if not self._hl.is_live:
            raise RuntimeError("Not in live mode")
        try:
            open_orders = self._hl.info.open_orders(self._hl.wallet_address)
            cancelled = 0
            for o in open_orders:
                if o.get("coin") == symbol:
                    oid = str(o.get("oid", ""))
                    if self.cancel_order(symbol, oid):
                        cancelled += 1
            return cancelled
        except Exception as exc:  # noqa: BLE001
            logger.error("Cancel-all error [%s]: %s", symbol, exc)
            return 0

    # ------------------------------------------------------------------
    # Close position (market)
    # ------------------------------------------------------------------

    def close_position_market(self, symbol: str, quantity: float, side: Side) -> bool:
        """
        Close an open position using a reduce-only market order.
        side is the POSITION side (LONG to close → sell).
        """
        if not self._hl.is_live:
            raise RuntimeError("Not in live mode")
        is_buy = side == Side.SHORT  # close long → sell; close short → buy
        try:
            response = self._hl.exchange.market_close(
                coin=symbol,
                sz=quantity,
                slippage=0.01,
            )
            HyperliquidClient._validate_response(response, f"close_position({symbol})")
            logger.info("Position closed [%s] side=%s qty=%.4f", symbol, side.value, quantity)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Close position failed [%s]: %s", symbol, exc)
            return False

    # ------------------------------------------------------------------
    # Order status
    # ------------------------------------------------------------------

    def get_order_status(self, symbol: str, exchange_order_id: str) -> Optional[OrderStatus]:
        try:
            fills = self._hl.info.user_fills(self._hl.wallet_address)
            for f in fills:
                if str(f.get("oid")) == exchange_order_id:
                    return OrderStatus.FILLED
            # Check open orders
            open_orders = self._hl.info.open_orders(self._hl.wallet_address)
            for o in open_orders:
                if str(o.get("oid")) == exchange_order_id:
                    return OrderStatus.OPEN
            return OrderStatus.CANCELLED
        except Exception as exc:  # noqa: BLE001
            logger.error("get_order_status error: %s", exc)
            return None
