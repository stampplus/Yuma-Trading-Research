"""Shared position state — single source of truth.

PositionState tracks the full position lifecycle:
IDLE -> OPEN -> CLOSING -> IDLE.

Never mutate state outside of the methods provided here.
All updates are atomic.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

# Position status constants
IDLE = "IDLE"
OPEN = "OPEN"
CLOSING = "CLOSING"


class EntryRecord(TypedDict):
    """A single position entry record."""

    price: float
    qty: float
    timestamp: str


class PositionState:
    """Singleton state manager for position lifecycle.

    Attributes:
        status: Current position status (IDLE, OPEN, CLOSING).
        entries: List of entry records with price, qty, timestamp.
        avg_entry: Weighted average entry price, or None if no position.
        dca_level: Current DCA level (0 = no position, 1 = entry, 2 = DCA-1, 3 = DCA-2).
        tp_orders: List of active take-profit order IDs.
        sl_order: Active stop-loss order ID, or None.
        last_claude_call: Timestamp of last Claude API call for cooldown enforcement.
    """

    def __init__(self) -> None:
        self.status: str = IDLE
        self.entries: list[EntryRecord] = []
        self.avg_entry: float | None = None
        self.dca_level: int = 0
        self.tp_orders: list[str] = []
        self.sl_order: str | None = None
        self.last_claude_call: datetime | None = None

    def add_entry(self, price: float, qty: float) -> None:
        """Record a new position entry and recalculate average.

        Args:
            price: Entry price.
            qty: Entry quantity.
        """
        entry: EntryRecord = {
            "price": price,
            "qty": qty,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.entries.append(entry)
        self.dca_level += 1
        self.status = OPEN
        self._recalculate_avg()
        logger.info(
            "Entry added: price=%.2f qty=%.4f level=%d avg=%.2f",
            price,
            qty,
            self.dca_level,
            self.avg_entry or 0.0,
        )

    def close_position(self) -> None:
        """Reset state to IDLE after position is fully closed."""
        logger.info(
            "Position closed: avg_entry=%.2f levels=%d entries=%d",
            self.avg_entry or 0.0,
            self.dca_level,
            len(self.entries),
        )
        self.status = IDLE
        self.entries = []
        self.avg_entry = None
        self.dca_level = 0
        self.tp_orders = []
        self.sl_order = None

    def set_closing(self) -> None:
        """Mark position as closing (TP/SL triggered)."""
        self.status = CLOSING
        logger.info("Position status -> CLOSING")

    def record_claude_call(self) -> None:
        """Record timestamp of a Claude API call for cooldown tracking."""
        self.last_claude_call = datetime.now(UTC)
        logger.info("Claude call recorded at %s", self.last_claude_call.isoformat())

    def total_qty(self) -> float:
        """Return total position quantity across all entries."""
        return sum(e["qty"] for e in self.entries)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to a dictionary for logging or AI context.

        Returns compressed format per architecture spec.
        """
        return {
            "status": self.status,
            "size": round(self.total_qty(), 4),
            "avg": round(self.avg_entry, 2) if self.avg_entry else None,
            "dca_level": self.dca_level,
            "entries": len(self.entries),
        }

    def _recalculate_avg(self) -> None:
        """Recalculate weighted average entry price from all entries."""
        if not self.entries:
            self.avg_entry = None
            return
        total_cost = sum(e["price"] * e["qty"] for e in self.entries)
        total_qty = sum(e["qty"] for e in self.entries)
        self.avg_entry = round(total_cost / total_qty, 2) if total_qty > 0 else None
