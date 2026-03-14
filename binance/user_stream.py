"""Binance User Data Stream manager.

Handles listen key lifecycle and WebSocket connection for
ORDER_TRADE_UPDATE, ACCOUNT_UPDATE, and MARGIN_CALL events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

import config
from binance.rest_client import BinanceRestClient
from services.event_bus import EventBus

logger = logging.getLogger(__name__)

# Listen key renewal interval (30 minutes, Binance requirement)
LISTEN_KEY_RENEW_INTERVAL_S: int = 1800


class UserStreamManager:
    """Manages the Binance User Data Stream.

    Handles listen key creation, renewal (every 30 min), and
    WebSocket subscription for fill/account events.

    Args:
        event_bus: EventBus instance for emitting user stream events.
        rest_client: BinanceRestClient for listen key management.
    """

    def __init__(self, event_bus: EventBus, rest_client: BinanceRestClient) -> None:
        self._bus = event_bus
        self._rest = rest_client
        self._listen_key: str | None = None
        self._running: bool = False
        self._renew_task: asyncio.Task[None] | None = None
        self._ws_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the user data stream.

        1. Gets a listen key via REST API.
        2. Connects to the user data WebSocket.
        3. Schedules listen key renewal every 30 min.
        """
        try:
            self._listen_key = await self._rest.get_listen_key()
        except Exception:
            logger.exception("Failed to get listen key — user stream disabled")
            return

        if not self._listen_key:
            logger.warning("Empty listen key — user stream disabled")
            return

        self._running = True
        self._ws_task = asyncio.create_task(self._ws_loop())
        self._renew_task = asyncio.create_task(self._renew_loop())
        logger.info("UserStreamManager started")

    async def stop(self) -> None:
        """Stop the user data stream and clean up."""
        self._running = False

        import contextlib

        if self._renew_task:
            self._renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renew_task
            self._renew_task = None

        if self._ws_task:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None

        self._listen_key = None
        logger.info("UserStreamManager stopped")

    async def _ws_loop(self) -> None:
        """WebSocket connection loop with reconnection."""
        backoff = 1.0

        while self._running and self._listen_key:
            url = f"{config.BINANCE_WS_BASE}/ws/{self._listen_key}"
            try:
                async with websockets.connect(url) as ws:
                    backoff = 1.0
                    logger.info("User stream connected")
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw_msg)
            except websockets.ConnectionClosed as e:
                logger.warning("User stream disconnected: %s", e)
            except (OSError, TimeoutError) as e:
                logger.error("User stream connection error: %s", e)
            except Exception:
                logger.exception("Unexpected user stream error")

            if self._running:
                logger.info("User stream reconnecting in %.1fs...", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _renew_loop(self) -> None:
        """Renew listen key every 30 minutes."""
        while self._running:
            await asyncio.sleep(LISTEN_KEY_RENEW_INTERVAL_S)
            if not self._running:
                break
            try:
                await self._rest.renew_listen_key()
                logger.debug("Listen key renewed")
            except Exception:
                logger.exception("Failed to renew listen key")

    async def _handle_message(self, raw_message: str | bytes) -> None:
        """Parse a user data stream message and route to EventBus.

        Routes events:
            - ORDER_TRADE_UPDATE -> "ORDER_FILL"
            - ACCOUNT_UPDATE -> "ACCOUNT_UPDATE"
            - MARGIN_CALL -> "MARGIN_CALL"

        Args:
            raw_message: Raw WebSocket message.
        """
        try:
            data: dict[str, Any] = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("Failed to parse user stream message")
            return

        event_type = data.get("e", "")

        if event_type == "ORDER_TRADE_UPDATE":
            logger.info(
                "Order update: symbol=%s side=%s status=%s",
                data.get("o", {}).get("s"),
                data.get("o", {}).get("S"),
                data.get("o", {}).get("X"),
            )
            await self._bus.emit_async("ORDER_FILL", data)
        elif event_type == "ACCOUNT_UPDATE":
            logger.info("Account update received")
            await self._bus.emit_async("ACCOUNT_UPDATE", data)
        elif event_type == "MARGIN_CALL":
            logger.warning("MARGIN CALL received!")
            await self._bus.emit_async("MARGIN_CALL", data)
        else:
            logger.debug("Unhandled user stream event: %s", event_type)
