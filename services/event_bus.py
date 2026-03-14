"""Simple in-process event emitter for inter-agent communication.

No external dependencies. All events use UPPER_SNAKE_CASE string constants
and pass data as dictionaries.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Async handler: receives event data dict, returns None
AsyncHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
# Sync handler: receives event data dict, returns None
SyncHandler = Callable[[dict[str, Any]], None]
Handler = AsyncHandler | SyncHandler


class EventBus:
    """Simple in-process event bus using the observer pattern.

    Supports both sync and async handlers. Async handlers are awaited
    when emitting via ``emit_async``.

    Usage::

        bus = EventBus()
        bus.on("DCA_TRIGGER", execution_agent.handle)
        bus.on("MARGIN_CALL", strategy_agent.emergency_review)
        await bus.emit_async("DCA_TRIGGER", {"level": 1, "price": 65000})
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event_type: str, handler: Handler) -> None:
        """Register a handler for an event type.

        Args:
            event_type: UPPER_SNAKE_CASE event name.
            handler: Sync or async callable accepting a data dict.
        """
        self._listeners[event_type].append(handler)
        logger.debug("Registered handler %s for event %s", handler.__name__, event_type)

    def off(self, event_type: str, handler: Handler) -> None:
        """Remove a handler for an event type.

        Args:
            event_type: UPPER_SNAKE_CASE event name.
            handler: Previously registered handler to remove.
        """
        try:
            self._listeners[event_type].remove(handler)
            logger.debug(
                "Removed handler %s for event %s",
                handler.__name__,
                event_type,
            )
        except ValueError:
            logger.warning(
                "Handler %s not found for event %s",
                handler.__name__,
                event_type,
            )

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event synchronously.

        Sync handlers are called directly. Async handlers are scheduled
        on the running event loop.

        Args:
            event_type: UPPER_SNAKE_CASE event name.
            data: Event payload as a dictionary.
        """
        handlers = self._listeners.get(event_type, [])
        if not handlers:
            logger.debug("No handlers for event %s", event_type)
            return

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    loop = asyncio.get_running_loop()
                    loop.create_task(handler(data))
                else:
                    handler(data)
            except RuntimeError:
                # No running loop — skip async handlers in sync context
                if not asyncio.iscoroutinefunction(handler):
                    handler(data)
            except Exception:
                logger.exception(
                    "Error in handler %s for event %s",
                    handler.__name__,
                    event_type,
                )

    async def emit_async(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event, awaiting all async handlers.

        Args:
            event_type: UPPER_SNAKE_CASE event name.
            data: Event payload as a dictionary.
        """
        handlers = self._listeners.get(event_type, [])
        if not handlers:
            logger.debug("No handlers for event %s", event_type)
            return

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception:
                logger.exception(
                    "Error in handler %s for event %s",
                    handler.__name__,
                    event_type,
                )

    def listener_count(self, event_type: str) -> int:
        """Return the number of handlers registered for an event type."""
        return len(self._listeners.get(event_type, []))

    def clear(self) -> None:
        """Remove all registered handlers."""
        self._listeners.clear()
