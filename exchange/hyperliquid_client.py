"""
exchange/hyperliquid_client.py
==============================
Base Hyperliquid client wrapper.
Loads credentials from environment, never from code.
All methods validate responses before returning.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)

# Hyperliquid mainnet endpoints
MAINNET_API = "https://api.hyperliquid.xyz"
TESTNET_API = "https://api.hyperliquid-testnet.xyz"


class HyperliquidClient:
    """
    Thin wrapper around the official hyperliquid-python-sdk.
    Exposes info (read) and exchange (write) clients.
    Credentials are loaded from environment variables only.
    """

    def __init__(self, use_testnet: bool = False) -> None:
        self._use_testnet = use_testnet
        self._base_url = TESTNET_API if use_testnet else MAINNET_API
        self._info: Optional[Info] = None
        self._exchange: Optional[Exchange] = None
        self._wallet_address: Optional[str] = None
        self._is_live: bool = False

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def connect(self, live: bool = False) -> None:
        """
        Initialise SDK clients.
        live=True connects the Exchange (write) client.
        live=False only connects the Info (read-only) client.
        """
        private_key = os.environ.get("HL_PRIVATE_KEY", "")
        wallet_address = os.environ.get("HL_WALLET_ADDRESS", "")

        if not wallet_address:
            raise EnvironmentError("HL_WALLET_ADDRESS not set in environment")

        self._wallet_address = wallet_address

        # Info client is always available (no auth required for public data)
        self._info = Info(self._base_url, skip_ws=True)
        logger.info("Hyperliquid Info client connected (%s)", "testnet" if self._use_testnet else "mainnet")

        if live:
            if not private_key:
                raise EnvironmentError(
                    "HL_PRIVATE_KEY not set — cannot connect live Exchange client"
                )
            live_flag = os.environ.get("LIVE_TRADING_ENABLED", "false").lower()
            if live_flag != "true":
                raise RuntimeError(
                    "LIVE_TRADING_ENABLED env var must be 'true' to enable live trading. "
                    "Set it explicitly after thorough paper-trading validation."
                )
            account = eth_account.Account.from_key(private_key)
            self._exchange = Exchange(account, self._base_url)
            self._is_live = True
            logger.warning(
                "LIVE TRADING ENABLED — wallet %s on %s",
                wallet_address,
                "testnet" if self._use_testnet else "MAINNET",
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def info(self) -> Info:
        if self._info is None:
            raise RuntimeError("Client not connected. Call connect() first.")
        return self._info

    @property
    def exchange(self) -> Exchange:
        if self._exchange is None:
            raise RuntimeError(
                "Exchange client not available. connect(live=True) was not called, "
                "or live trading is disabled."
            )
        return self._exchange

    @property
    def wallet_address(self) -> str:
        if not self._wallet_address:
            raise RuntimeError("Client not connected.")
        return self._wallet_address

    @property
    def is_live(self) -> bool:
        return self._is_live

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_response(response: dict, operation: str) -> None:
        """Raise on unsuccessful exchange responses."""
        if not isinstance(response, dict):
            raise ValueError(f"{operation}: unexpected response type {type(response)}")
        status = response.get("status")
        if status and status != "ok":
            raise RuntimeError(f"{operation} failed: {response}")
