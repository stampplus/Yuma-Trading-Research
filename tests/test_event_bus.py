"""Tests for services.event_bus.EventBus."""

from __future__ import annotations

import pytest

from services.event_bus import EventBus


class TestEventBusSync:
    """Test synchronous event handling."""

    def test_emit_calls_registered_handler(self) -> None:
        bus = EventBus()
        received: list[dict] = []

        def handler(data: dict) -> None:
            received.append(data)

        bus.on("TEST_EVENT", handler)
        bus.emit("TEST_EVENT", {"key": "value"})

        assert len(received) == 1
        assert received[0] == {"key": "value"}

    def test_emit_calls_multiple_handlers(self) -> None:
        bus = EventBus()
        results: list[str] = []

        def handler_a(data: dict) -> None:
            results.append("a")

        def handler_b(data: dict) -> None:
            results.append("b")

        bus.on("TEST_EVENT", handler_a)
        bus.on("TEST_EVENT", handler_b)
        bus.emit("TEST_EVENT", {})

        assert results == ["a", "b"]

    def test_emit_no_handlers_does_not_raise(self) -> None:
        bus = EventBus()
        bus.emit("NO_HANDLERS", {"data": 1})  # Should not raise

    def test_off_removes_handler(self) -> None:
        bus = EventBus()
        received: list[dict] = []

        def handler(data: dict) -> None:
            received.append(data)

        bus.on("TEST_EVENT", handler)
        bus.off("TEST_EVENT", handler)
        bus.emit("TEST_EVENT", {"key": "value"})

        assert len(received) == 0

    def test_listener_count(self) -> None:
        bus = EventBus()

        def handler(data: dict) -> None:
            pass

        assert bus.listener_count("TEST_EVENT") == 0
        bus.on("TEST_EVENT", handler)
        assert bus.listener_count("TEST_EVENT") == 1
        bus.on("TEST_EVENT", handler)
        assert bus.listener_count("TEST_EVENT") == 2

    def test_clear_removes_all_handlers(self) -> None:
        bus = EventBus()

        def handler(data: dict) -> None:
            pass

        bus.on("EVENT_A", handler)
        bus.on("EVENT_B", handler)
        bus.clear()

        assert bus.listener_count("EVENT_A") == 0
        assert bus.listener_count("EVENT_B") == 0

    def test_different_events_are_independent(self) -> None:
        bus = EventBus()
        results_a: list[str] = []
        results_b: list[str] = []

        def handler_a(data: dict) -> None:
            results_a.append("a")

        def handler_b(data: dict) -> None:
            results_b.append("b")

        bus.on("EVENT_A", handler_a)
        bus.on("EVENT_B", handler_b)

        bus.emit("EVENT_A", {})
        assert results_a == ["a"]
        assert results_b == []

    def test_handler_error_does_not_stop_other_handlers(self) -> None:
        bus = EventBus()
        results: list[str] = []

        def bad_handler(data: dict) -> None:
            raise ValueError("oops")

        def good_handler(data: dict) -> None:
            results.append("ok")

        bus.on("TEST_EVENT", bad_handler)
        bus.on("TEST_EVENT", good_handler)
        bus.emit("TEST_EVENT", {})

        assert results == ["ok"]


class TestEventBusAsync:
    """Test asynchronous event handling."""

    @pytest.mark.asyncio
    async def test_emit_async_calls_async_handler(self) -> None:
        bus = EventBus()
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.on("TEST_EVENT", handler)
        await bus.emit_async("TEST_EVENT", {"key": "value"})

        assert len(received) == 1
        assert received[0] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_emit_async_calls_sync_handler(self) -> None:
        bus = EventBus()
        received: list[dict] = []

        def handler(data: dict) -> None:
            received.append(data)

        bus.on("TEST_EVENT", handler)
        await bus.emit_async("TEST_EVENT", {"key": "value"})

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_emit_async_mixed_handlers(self) -> None:
        bus = EventBus()
        results: list[str] = []

        def sync_handler(data: dict) -> None:
            results.append("sync")

        async def async_handler(data: dict) -> None:
            results.append("async")

        bus.on("TEST_EVENT", sync_handler)
        bus.on("TEST_EVENT", async_handler)
        await bus.emit_async("TEST_EVENT", {})

        assert "sync" in results
        assert "async" in results

    @pytest.mark.asyncio
    async def test_emit_async_handler_error_does_not_stop_others(self) -> None:
        bus = EventBus()
        results: list[str] = []

        async def bad_handler(data: dict) -> None:
            raise ValueError("oops")

        async def good_handler(data: dict) -> None:
            results.append("ok")

        bus.on("TEST_EVENT", bad_handler)
        bus.on("TEST_EVENT", good_handler)
        await bus.emit_async("TEST_EVENT", {})

        assert results == ["ok"]
