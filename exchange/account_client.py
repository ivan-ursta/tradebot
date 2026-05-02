"""
exchange/account_client.py
==========================
Fetches account state: balances, positions, open orders.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from core.models import AccountState, Order, OrderStatus, OrderType, Position, Side
from exchange.hyperliquid_client import HyperliquidClient

logger = logging.getLogger(__name__)


class AccountClient:
    """Read-only account state from Hyperliquid."""

    def __init__(self, client: HyperliquidClient) -> None:
        self._hl = client

    def get_account_state(self) -> Optional[AccountState]:
        """Fetch full account snapshot."""
        try:
            state = self._hl.info.user_state(self._hl.wallet_address)
            if not state:
                return None

            margin_summary = state.get("marginSummary", {})
            equity = float(margin_summary.get("accountValue", 0))
            available = float(state.get("withdrawable", equity))
            used_margin = float(margin_summary.get("totalMarginUsed", 0))
            unrealized_pnl = float(margin_summary.get("totalUnrealizedPnl", 0))

            positions = self._parse_positions(state.get("assetPositions", []))

            return AccountState(
                timestamp=datetime.now(timezone.utc),
                equity=equity,
                available_balance=available,
                used_margin=used_margin,
                unrealized_pnl=unrealized_pnl,
                positions=positions,
                open_orders=[],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("get_account_state error: %s", exc)
            return None

    def get_positions(self) -> List[Position]:
        try:
            state = self._hl.info.user_state(self._hl.wallet_address)
            return self._parse_positions(state.get("assetPositions", []))
        except Exception as exc:  # noqa: BLE001
            logger.error("get_positions error: %s", exc)
            return []

    def get_open_orders(self) -> List[Order]:
        try:
            raw_orders = self._hl.info.open_orders(self._hl.wallet_address)
            result = []
            for o in raw_orders:
                try:
                    result.append(
                        Order(
                            exchange_order_id=str(o.get("oid", "")),
                            symbol=o.get("coin", ""),
                            side=Side.LONG if o.get("side", "B") == "B" else Side.SHORT,
                            order_type=OrderType.LIMIT,
                            quantity=float(o.get("sz", 0)),
                            price=float(o.get("limitPx", 0)) or None,
                            status=OrderStatus.OPEN,
                        )
                    )
                except (KeyError, ValueError) as exc:
                    logger.warning("Malformed open order: %s — %s", o, exc)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("get_open_orders error: %s", exc)
            return []

    @staticmethod
    def _parse_positions(raw: list) -> List[Position]:
        positions = []
        for item in raw:
            pos = item.get("position", {})
            try:
                coin = pos.get("coin", "")
                szi = float(pos.get("szi", 0))
                if szi == 0:
                    continue
                side = Side.LONG if szi > 0 else Side.SHORT
                entry_px = float(pos.get("entryPx", 0) or 0)
                unrealized = float(pos.get("unrealizedPnl", 0) or 0)
                liq_px_raw = pos.get("liquidationPx")
                liq_px = float(liq_px_raw) if liq_px_raw is not None else None
                leverage_raw = pos.get("leverage", {})
                leverage = float(leverage_raw.get("value", 1)) if isinstance(leverage_raw, dict) else 1.0

                positions.append(
                    Position(
                        symbol=coin,
                        side=side,
                        quantity=abs(szi),
                        avg_entry_price=entry_px,
                        unrealized_pnl=unrealized,
                        liquidation_price=liq_px,
                        leverage=leverage,
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Malformed position: %s — %s", pos, exc)
        return positions
