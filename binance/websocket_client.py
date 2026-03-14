"""Binance Futures WebSocket client with auto-reconnect.

Connects to wss://fstream.binance.com and streams kline data.
Parses raw messages and invokes a callback with structured data.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import websockets

import config

logger = logging.getLogger(__name__)

# Callback type: receives parsed kline dict
KlineCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# Reconnect backoff settings
INITIAL_BACKOFF_S: float = 1.0
MAX_BACKOFF_S: float = 60.0
BACKOFF_MULTIPLIER: float = 2.0


class BinanceWebSocketClient:
    """Manages a WebSocket connection to Binance Futures streams.

    Handles connection, message parsing, and automatic reconnection
    with exponential backoff on disconnection.

    Args:
        streams: List of stream names (e.g. ["btcusdt@kline_1m"]).
        on_kline: Async callback invoked with parsed kline data.
    """

    def __init__(
        self,
        streams: list[str],
        on_kline: KlineCallback,
    ) -> None:
        self._streams = streams
        self._on_kline = on_kline
        self._ws: Any = None
        self._running: bool = False
        self._backoff: float = INITIAL_BACKOFF_S

    @property
    def url(self) -> str:
        """Build the combined stream URL."""
        stream_path = "/".join(self._streams)
        return f"{config.BINANCE_WS_BASE}/stream?streams={stream_path}"

    async def start(self) -> None:
        """Start the WebSocket connection loop.

        Connects to Binance and processes messages indefinitely.
        Reconnects automatically on disconnection.
        """
        self._running = True
        logger.info("WebSocket client starting — url=%s", self.url)

        while self._running:
            try:
                await self._connect_and_listen()
            except websockets.ConnectionClosed as e:
                logger.warning("WebSocket connection closed: %s", e)
            except (OSError, TimeoutError) as e:
                logger.error("WebSocket connection error: %s", e)
            except Exception:
                logger.exception("Unexpected WebSocket error")

            if self._running:
                logger.info("Reconnecting in %.1fs...", self._backoff)
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_S)

    async def stop(self) -> None:
        """Stop the WebSocket connection loop."""
        self._running = False
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket client stopped")

    async def _connect_and_listen(self) -> None:
        """Connect to the WebSocket and process messages."""
        async with websockets.connect(self.url) as ws:
            self._ws = ws
            self._backoff = INITIAL_BACKOFF_S  # Reset on successful connect
            logger.info("WebSocket connected to %s", self.url)

            async for raw_message in ws:
                if not self._running:
                    break
                await self._handle_message(raw_message)

    async def _handle_message(self, raw_message: str | bytes) -> None:
        """Parse a raw WebSocket message and dispatch to callback.

        Args:
            raw_message: Raw message string from WebSocket.
        """
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("Failed to parse WebSocket message: %s", raw_message[:200])
            return

        # Combined stream format: {"stream": "btcusdt@kline_1m", "data": {...}}
        data = message.get("data", message)
        event_type = data.get("e")

        if event_type == "kline":
            kline = self._parse_kline(data)
            await self._on_kline(kline)
        else:
            logger.debug("Unhandled event type: %s", event_type)

    @staticmethod
    def _parse_kline(data: dict[str, Any]) -> dict[str, Any]:
        """Parse raw Binance kline event into a clean dictionary.

        Args:
            data: Raw kline event data from Binance WebSocket.

        Returns:
            Normalized kline dictionary with readable field names.
        """
        k = data["k"]
        return {
            "symbol": k["s"],
            "interval": k["i"],
            "open_time": k["t"],
            "close_time": k["T"],
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
            "quote_volume": float(k["q"]),
            "trades": k["n"],
            "is_closed": k["x"],
            "event_time": data["E"],
        }
