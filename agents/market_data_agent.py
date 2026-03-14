"""Market Data Agent — WebSocket consumer and MarketEvent emitter.

Pure code agent (Tier 1, no AI). Receives kline data from the Binance
WebSocket client, maintains a price buffer, computes technical indicators
(RSI, EMA), and emits normalized MarketEvent through the EventBus on
every candle close.

Architecture ref: Section 2 (Market Data Agent), Section 4 (Data Flow).
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import aiohttp

import config
from services.event_bus import EventBus

logger = logging.getLogger(__name__)

# Event constants
MARKET_EVENT = "MARKET_EVENT"
KLINE_UPDATE = "KLINE_UPDATE"

# Buffer 240 candles (4 hours of 1m candles)
PRICE_BUFFER_SIZE: int = 240


def compute_ema(prices: list[float], period: int) -> float | None:
    """Compute Exponential Moving Average.

    Args:
        prices: List of close prices (oldest first).
        period: EMA period.

    Returns:
        EMA value, or None if not enough data.
    """
    if len(prices) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period  # Seed with SMA
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 2)


def compute_rsi(prices: list[float], period: int = 14) -> float | None:
    """Compute Relative Strength Index.

    Uses the standard Wilder smoothing method.

    Args:
        prices: List of close prices (oldest first).
        period: RSI period (default 14).

    Returns:
        RSI value (0-100), or None if not enough data.
    """
    if len(prices) < period + 1:
        return None

    deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]

    # Initial average gain/loss
    gains = [d if d > 0 else 0 for d in deltas[:period]]
    losses = [-d if d < 0 else 0 for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder smoothing for remaining deltas
    for d in deltas[period:]:
        gain = d if d > 0 else 0
        loss = -d if d < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


class MarketDataAgent:
    """Consumes kline data and emits normalized MarketEvent.

    Maintains a rolling buffer of recent candle closes. On every
    closed candle, computes RSI(14) and EMA(50), then emits
    a MARKET_EVENT. On every kline update, emits KLINE_UPDATE.

    Args:
        event_bus: EventBus instance for emitting events.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._price_buffer: deque[float] = deque(maxlen=PRICE_BUFFER_SIZE)
        self._volume_buffer: deque[float] = deque(maxlen=PRICE_BUFFER_SIZE)
        self._candle_count: int = 0

    async def handle_kline(self, kline: dict[str, Any]) -> None:
        """Process a parsed kline event from the WebSocket client.

        Emits KLINE_UPDATE on every tick. On candle close, appends
        to the price buffer and emits a full MARKET_EVENT.

        Args:
            kline: Parsed kline dictionary from BinanceWebSocketClient.
        """
        symbol = kline["symbol"]
        close_price = kline["close"]
        volume = kline["volume"]
        is_closed = kline["is_closed"]

        # Emit raw kline update on every tick
        await self._bus.emit_async(KLINE_UPDATE, kline)

        if not is_closed:
            return

        # Candle closed — update buffers
        self._price_buffer.append(close_price)
        self._volume_buffer.append(volume)
        self._candle_count += 1

        # Build and emit MarketEvent
        market_event = self._build_market_event(kline)

        logger.info(
            "Candle #%d closed: %s %.2f vol=%.2f rsi=%s ema50=%s",
            self._candle_count,
            symbol,
            close_price,
            volume,
            market_event.get("rsi_14"),
            market_event.get("ema_50"),
        )
        await self._bus.emit_async(MARKET_EVENT, market_event)

    async def fetch_historical(self, limit: int = 60) -> None:
        """Fetch historical candles to populate buffers quickly.

        Fetches the last N closed candles from Binance REST API so that
        indicators (RSI, EMA) can be calculated immediately without
        waiting for live data.

        Args:
            limit: Number of candles to fetch (default 60 for EMA50).
        """
        url = f"{config.BINANCE_REST_BASE}/fapi/v1/klines"
        params = {
            "symbol": config.SYMBOL,
            "interval": "1m",
            "limit": limit,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Failed to fetch historical candles: HTTP %d", resp.status
                        )
                        return

                    data = await resp.json()
                    for candle in data:
                        # Binance kline: [open_time, open, high, low, close, volume, ...]
                        close_price = float(candle[4])
                        volume = float(candle[5])
                        self._price_buffer.append(close_price)
                        self._volume_buffer.append(volume)

                    logger.info(
                        "Loaded %d historical candles | buffer size: %d",
                        len(data),
                        len(self._price_buffer),
                    )

        except aiohttp.ClientError as e:
            logger.warning("Network error fetching historical candles: %s", e)
        except Exception:
            logger.exception("Unexpected error fetching historical candles")

    def _build_market_event(self, kline: dict[str, Any]) -> dict[str, Any]:
        """Build a normalized MarketEvent from a closed candle.

        Includes OHLCV data, RSI(14), EMA(50), and buffer statistics.

        Args:
            kline: Parsed kline dictionary (must be a closed candle).

        Returns:
            MarketEvent dictionary.
        """
        prices = list(self._price_buffer)
        volumes = list(self._volume_buffer)

        event: dict[str, Any] = {
            "symbol": kline["symbol"],
            "interval": kline["interval"],
            "timestamp": kline["event_time"],
            "open": kline["open"],
            "high": kline["high"],
            "low": kline["low"],
            "close": kline["close"],
            "volume": kline["volume"],
            "quote_volume": kline["quote_volume"],
            "trades": kline["trades"],
            "candle_count": self._candle_count,
            "buffer_size": len(prices),
        }

        # Price change from previous candle
        if len(prices) >= 2:
            event["price_change_pct"] = round(
                (prices[-1] - prices[-2]) / prices[-2] * 100,
                4,
            )

        # Technical indicators (pure code, Tier 1)
        event["rsi_14"] = compute_rsi(prices, period=14)
        event["ema_50"] = compute_ema(prices, period=50)

        # SMA 50 for comparison
        if len(prices) >= 50:
            event["sma_50"] = round(sum(prices[-50:]) / 50, 2)

        # Volume ratio (current vs avg of last 20 candles)
        if len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            event["vol_ratio"] = round(volumes[-1] / avg_vol, 2) if avg_vol > 0 else 1.0

        return event

    @property
    def candle_count(self) -> int:
        """Return the number of closed candles processed."""
        return self._candle_count

    @property
    def buffer_size(self) -> int:
        """Return the current number of prices in the buffer."""
        return len(self._price_buffer)

    @property
    def last_price(self) -> float | None:
        """Return the most recent close price, or None if buffer is empty."""
        return self._price_buffer[-1] if self._price_buffer else None
