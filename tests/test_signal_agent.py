"""Tests for agents.signal_agent.SignalAgent."""

from __future__ import annotations

from agents.signal_agent import SignalAgent
from services.event_bus import EventBus
from services.state import IDLE, PositionState


class TestSignalAgentEscalation:
    """Test the needs_claude escalation logic (pure code, no API calls)."""

    def _make_agent(self) -> tuple[SignalAgent, PositionState]:
        bus = EventBus()
        state = PositionState()
        agent = SignalAgent(bus, state)
        return agent, state

    def test_hold_signal_does_not_escalate(self) -> None:
        agent, state = self._make_agent()
        signal = {"type": "HOLD", "confidence": 0.9}
        assert agent._should_escalate(signal) is False

    def test_first_entry_escalates(self) -> None:
        agent, state = self._make_agent()
        assert state.status == IDLE
        signal = {"type": "LONG", "confidence": 0.8}
        assert agent._should_escalate(signal) is True

    def test_normal_dca_does_not_escalate(self) -> None:
        agent, state = self._make_agent()
        state.add_entry(price=67000.0, qty=0.001)  # Level 1
        signal = {"type": "LONG", "confidence": 0.8}
        # DCA level 1, within normal params, high confidence
        assert agent._should_escalate(signal) is False

    def test_max_dca_level_escalates(self) -> None:
        agent, state = self._make_agent()
        state.add_entry(price=67000.0, qty=0.001)
        state.add_entry(price=65000.0, qty=0.0015)
        state.add_entry(price=63000.0, qty=0.002)
        assert state.dca_level == 3  # MAX_DCA_LEVELS
        signal = {"type": "LONG", "confidence": 0.9}
        assert agent._should_escalate(signal) is True

    def test_low_confidence_escalates(self) -> None:
        agent, state = self._make_agent()
        state.add_entry(price=67000.0, qty=0.001)
        signal = {"type": "LONG", "confidence": 0.4}
        assert agent._should_escalate(signal) is True

    def test_high_confidence_dca1_does_not_escalate(self) -> None:
        agent, state = self._make_agent()
        state.add_entry(price=67000.0, qty=0.001)
        signal = {"type": "LONG", "confidence": 0.85}
        assert agent._should_escalate(signal) is False

    def test_short_during_open_position_escalates(self) -> None:
        agent, state = self._make_agent()
        state.add_entry(price=67000.0, qty=0.001)
        signal = {"type": "SHORT", "confidence": 0.8}
        assert agent._should_escalate(signal) is True


class TestSignalAgentParsing:
    """Test MiniMax response parsing."""

    def test_valid_json_parsed(self) -> None:
        content = '{"type": "LONG", "confidence": 0.78, "reasoning": "RSI oversold"}'
        result = SignalAgent._parse_signal_response(content)
        assert result is not None
        assert result["type"] == "LONG"
        assert result["confidence"] == 0.78

    def test_markdown_fenced_json_parsed(self) -> None:
        content = '```json\n{"type": "HOLD", "confidence": 0.5}\n```'
        result = SignalAgent._parse_signal_response(content)
        assert result is not None
        assert result["type"] == "HOLD"

    def test_invalid_json_returns_none(self) -> None:
        content = "This is not JSON"
        result = SignalAgent._parse_signal_response(content)
        assert result is None

    def test_invalid_signal_type_defaults_to_hold(self) -> None:
        content = '{"type": "INVALID", "confidence": 0.5}'
        result = SignalAgent._parse_signal_response(content)
        assert result is not None
        assert result["type"] == "HOLD"

    def test_invalid_confidence_defaults_to_half(self) -> None:
        content = '{"type": "LONG", "confidence": "bad"}'
        result = SignalAgent._parse_signal_response(content)
        assert result is not None
        assert result["confidence"] == 0.5

    def test_context_building(self) -> None:
        bus = EventBus()
        state = PositionState()
        agent = SignalAgent(bus, state)

        market_event = {
            "symbol": "BTCUSDT",
            "close": 67000.0,
            "open": 66900.0,
            "high": 67100.0,
            "low": 66800.0,
            "volume": 100.0,
            "rsi_14": 38.5,
            "ema_50": 66500.0,
            "price_change_pct": -0.15,
            "vol_ratio": 1.2,
        }

        ctx = agent._build_context(market_event)
        assert ctx["sym"] == "BTCUSDT"
        assert ctx["px"] == 67000.0
        assert ctx["rsi_14"] == 38.5
        assert ctx["ema_50"] == 66500.0
        assert "position" in ctx
        assert ctx["position"]["status"] == IDLE
