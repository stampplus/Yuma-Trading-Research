"""Tests for services.state.PositionState."""

from __future__ import annotations

from services.state import CLOSING, IDLE, OPEN, PositionState


class TestPositionState:
    """Test PositionState lifecycle and calculations."""

    def test_initial_state_is_idle(self) -> None:
        state = PositionState()
        assert state.status == IDLE
        assert state.dca_level == 0
        assert state.entries == []
        assert state.avg_entry is None
        assert state.total_qty() == 0.0

    def test_add_entry_sets_open_status(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)

        assert state.status == OPEN
        assert state.dca_level == 1
        assert len(state.entries) == 1
        assert state.avg_entry == 67000.0
        assert state.total_qty() == 0.001

    def test_add_multiple_entries_calculates_avg(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)
        state.add_entry(price=65000.0, qty=0.0015)

        assert state.dca_level == 2
        assert len(state.entries) == 2

        # Weighted average: (67000*0.001 + 65000*0.0015) / (0.001+0.0015)
        # = (67 + 97.5) / 0.0025 = 164.5 / 0.0025 = 65800
        assert state.avg_entry == 65800.0
        assert state.total_qty() == 0.0025

    def test_three_dca_levels(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)
        state.add_entry(price=65000.0, qty=0.0015)
        state.add_entry(price=63000.0, qty=0.002)

        assert state.dca_level == 3
        assert len(state.entries) == 3
        assert abs(state.total_qty() - 0.0045) < 1e-10

        # Weighted avg: (67000*0.001 + 65000*0.0015 + 63000*0.002) / 0.0045
        # = (67 + 97.5 + 126) / 0.0045 = 290.5 / 0.0045 ≈ 64555.56
        assert state.avg_entry is not None
        assert abs(state.avg_entry - 64555.56) < 1.0

    def test_close_position_resets_state(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)
        state.add_entry(price=65000.0, qty=0.0015)
        state.close_position()

        assert state.status == IDLE
        assert state.dca_level == 0
        assert state.entries == []
        assert state.avg_entry is None
        assert state.total_qty() == 0.0
        assert state.tp_orders == []
        assert state.sl_order is None

    def test_set_closing(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)
        state.set_closing()

        assert state.status == CLOSING
        # Position data should still be intact
        assert state.dca_level == 1
        assert len(state.entries) == 1

    def test_record_claude_call(self) -> None:
        state = PositionState()
        assert state.last_claude_call is None

        state.record_claude_call()
        assert state.last_claude_call is not None

    def test_to_dict_idle(self) -> None:
        state = PositionState()
        d = state.to_dict()

        assert d["status"] == IDLE
        assert d["size"] == 0.0
        assert d["avg"] is None
        assert d["dca_level"] == 0
        assert d["entries"] == 0

    def test_to_dict_with_position(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)
        d = state.to_dict()

        assert d["status"] == OPEN
        assert d["size"] == 0.001
        assert d["avg"] == 67000.0
        assert d["dca_level"] == 1
        assert d["entries"] == 1

    def test_entries_have_timestamps(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)

        entry = state.entries[0]
        assert "timestamp" in entry
        assert entry["price"] == 67000.0
        assert entry["qty"] == 0.001

    def test_last_price_via_entries(self) -> None:
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)
        state.add_entry(price=65000.0, qty=0.0015)

        last_entry = state.entries[-1]
        assert last_entry["price"] == 65000.0
