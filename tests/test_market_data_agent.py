"""Tests for agents.market_data_agent.MarketDataAgent and indicators."""

from __future__ import annotations

import pytest

from agents.market_data_agent import (
    KLINE_UPDATE,
    MARKET_EVENT,
    MarketDataAgent,
    compute_ema,
    compute_rsi,
)
from services.event_bus import EventBus


def _make_kline(
    close: float = 67000.0,
    is_closed: bool = True,
    volume: float = 100.0,
) -> dict:
    """Create a mock kline dictionary."""
    return {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "open_time": 1700000000000,
        "close_time": 1700000059999,
        "open": 66900.0,
        "high": 67100.0,
        "low": 66800.0,
        "close": close,
        "volume": volume,
        "quote_volume": 6700000.0,
        "trades": 500,
        "is_closed": is_closed,
        "event_time": 1700000060000,
    }


class TestComputeRSI:
    """Test RSI computation."""

    def test_returns_none_with_insufficient_data(self) -> None:
        assert compute_rsi([100.0] * 10, period=14) is None

    def test_returns_100_when_all_gains(self) -> None:
        prices = [float(i) for i in range(20)]  # 0.0, 1.0, 2.0, ... 19.0
        rsi = compute_rsi(prices, period=14)
        assert rsi == 100.0

    def test_returns_value_in_range(self) -> None:
        prices = [float(100 + (i % 5) - 2) for i in range(30)]
        rsi = compute_rsi(prices, period=14)
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_downtrend_produces_low_rsi(self) -> None:
        prices = [100.0 - i * 0.5 for i in range(30)]
        rsi = compute_rsi(prices, period=14)
        assert rsi is not None
        assert rsi < 30


class TestComputeEMA:
    """Test EMA computation."""

    def test_returns_none_with_insufficient_data(self) -> None:
        assert compute_ema([100.0] * 5, period=50) is None

    def test_returns_value_with_exact_period(self) -> None:
        prices = [100.0] * 50
        ema = compute_ema(prices, period=50)
        assert ema == 100.0

    def test_tracks_uptrend(self) -> None:
        prices = [100.0 + i for i in range(60)]
        ema = compute_ema(prices, period=50)
        assert ema is not None
        assert ema > prices[0]
        assert ema < prices[-1]


class TestMarketDataAgent:
    """Test MarketDataAgent kline processing and event emission."""

    @pytest.mark.asyncio
    async def test_closed_candle_emits_market_event(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)
        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on(MARKET_EVENT, capture)

        kline = _make_kline(close=67000.0, is_closed=True)
        await agent.handle_kline(kline)

        assert len(received) == 1
        assert received[0]["symbol"] == "BTCUSDT"
        assert received[0]["close"] == 67000.0
        assert received[0]["candle_count"] == 1

    @pytest.mark.asyncio
    async def test_open_candle_does_not_emit_market_event(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)
        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on(MARKET_EVENT, capture)

        kline = _make_kline(is_closed=False)
        await agent.handle_kline(kline)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_open_candle_emits_kline_update(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)
        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on(KLINE_UPDATE, capture)

        kline = _make_kline(is_closed=False)
        await agent.handle_kline(kline)

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_candle_count_increments(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)

        assert agent.candle_count == 0

        for _i in range(3):
            await agent.handle_kline(_make_kline(is_closed=True))

        assert agent.candle_count == 3

    @pytest.mark.asyncio
    async def test_price_buffer_fills(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)

        assert agent.buffer_size == 0
        assert agent.last_price is None

        await agent.handle_kline(_make_kline(close=67000.0, is_closed=True))
        assert agent.buffer_size == 1
        assert agent.last_price == 67000.0

        await agent.handle_kline(_make_kline(close=67100.0, is_closed=True))
        assert agent.buffer_size == 2
        assert agent.last_price == 67100.0

    @pytest.mark.asyncio
    async def test_price_change_pct_in_market_event(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)
        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on(MARKET_EVENT, capture)

        await agent.handle_kline(_make_kline(close=67000.0, is_closed=True))
        await agent.handle_kline(_make_kline(close=67670.0, is_closed=True))

        assert len(received) == 2
        assert "price_change_pct" in received[1]
        assert abs(received[1]["price_change_pct"] - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_market_event_contains_required_fields(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)
        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on(MARKET_EVENT, capture)

        await agent.handle_kline(_make_kline(is_closed=True))

        event = received[0]
        required_fields = [
            "symbol",
            "interval",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades",
            "candle_count",
            "buffer_size",
            "rsi_14",
            "ema_50",
        ]
        for field in required_fields:
            assert field in event, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_rsi_computed_after_enough_candles(self) -> None:
        bus = EventBus()
        agent = MarketDataAgent(bus)
        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on(MARKET_EVENT, capture)

        # Need at least 15 candles for RSI(14)
        for i in range(20):
            price = 67000.0 + i * 10
            await agent.handle_kline(_make_kline(close=price, is_closed=True))

        # RSI should be computed after 15+ candles
        last_event = received[-1]
        assert last_event["rsi_14"] is not None
        assert 0 <= last_event["rsi_14"] <= 100
