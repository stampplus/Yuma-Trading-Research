"""Tests for agents.strategy_agent.StrategyAgent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agents.strategy_agent import StrategyAgent
from services.event_bus import EventBus
from services.state import PositionState
from strategies.dca_config import CLAUDE_COOLDOWN_MINUTES


class TestStrategyAgentCooldown:
    """Test Claude cooldown and budget enforcement."""

    def _make_agent(self) -> tuple[StrategyAgent, PositionState]:
        bus = EventBus()
        state = PositionState()
        agent = StrategyAgent(bus, state)
        return agent, state

    def test_can_call_when_no_previous_calls(self) -> None:
        agent, state = self._make_agent()
        assert agent._can_call_claude() is True

    def test_blocked_during_cooldown(self) -> None:
        agent, state = self._make_agent()
        state.record_claude_call()
        assert agent._can_call_claude() is False

    def test_allowed_after_cooldown_expires(self) -> None:
        agent, state = self._make_agent()
        # Set last call to 31 minutes ago
        state.last_claude_call = datetime.now(UTC) - timedelta(
            minutes=CLAUDE_COOLDOWN_MINUTES + 1,
        )
        assert agent._can_call_claude() is True

    def test_daily_budget_blocks_when_exhausted(self) -> None:
        agent, state = self._make_agent()
        agent._daily_calls = 10  # MAX_DAILY_CALLS
        assert agent._can_call_claude() is False

    def test_daily_budget_resets_on_new_day(self) -> None:
        agent, state = self._make_agent()
        agent._daily_calls = 10
        agent._daily_reset = datetime.now(UTC) - timedelta(days=1)
        assert agent._can_call_claude() is True


class TestStrategyAgentParsing:
    """Test Claude response parsing."""

    def test_valid_approve_parsed(self) -> None:
        content = (
            '{"decision": "APPROVE", "params": {"side": "BUY",'
            ' "size_pct": 0.01}, "reasoning": "test", "ttl_minutes": 30}'
        )
        result = StrategyAgent._parse_decision(content)
        assert result is not None
        assert result["decision"] == "APPROVE"
        assert result["params"]["side"] == "BUY"

    def test_valid_reject_parsed(self) -> None:
        content = '{"decision": "REJECT", "reasoning": "too risky"}'
        result = StrategyAgent._parse_decision(content)
        assert result is not None
        assert result["decision"] == "REJECT"

    def test_invalid_decision_returns_none(self) -> None:
        content = '{"decision": "MAYBE", "reasoning": "uncertain"}'
        result = StrategyAgent._parse_decision(content)
        assert result is None

    def test_invalid_json_returns_none(self) -> None:
        content = "Not valid JSON"
        result = StrategyAgent._parse_decision(content)
        assert result is None

    def test_markdown_fenced_json_parsed(self) -> None:
        content = (
            '```json\n{"decision": "APPROVE", "params": {}, "reasoning": "ok"}\n```'
        )
        result = StrategyAgent._parse_decision(content)
        assert result is not None
        assert result["decision"] == "APPROVE"


class TestStrategyAgentQuestion:
    """Test question determination logic."""

    def test_idle_state_asks_first_entry(self) -> None:
        agent, state = self._make_agent()
        q = agent._determine_question({"type": "LONG"})
        assert q == "APPROVE_FIRST_ENTRY?"

    def test_dca2_asks_correct_level(self) -> None:
        agent, state = self._make_agent()
        state.add_entry(price=67000.0, qty=0.001)
        state.add_entry(price=65000.0, qty=0.0015)
        q = agent._determine_question({"type": "LONG"})
        assert q == "APPROVE_DCA_3?"

    def test_short_signal_asks_close(self) -> None:
        agent, state = self._make_agent()
        state.add_entry(price=67000.0, qty=0.001)
        q = agent._determine_question({"type": "SHORT"})
        assert q == "CLOSE_POSITION?"

    def _make_agent(self) -> tuple[StrategyAgent, PositionState]:
        bus = EventBus()
        state = PositionState()
        agent = StrategyAgent(bus, state)
        return agent, state


class TestStrategyAgentAutoForward:
    """Test that non-Claude signals are forwarded to execution."""

    @pytest.mark.asyncio
    async def test_auto_forward_on_minimax_approve(self) -> None:
        bus = EventBus()
        state = PositionState()
        state.add_entry(price=67000.0, qty=0.001)  # So LONG doesn't escalate
        agent = StrategyAgent(bus, state)
        agent.register()

        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on("ORDER_APPROVED", capture)

        await bus.emit_async(
            "SIGNAL_RESULT",
            {
                "type": "LONG",
                "confidence": 0.85,
                "needs_claude": False,
            },
        )

        assert len(received) == 1
        assert received[0]["source"] == "minimax_auto"

    @pytest.mark.asyncio
    async def test_hold_signal_not_forwarded(self) -> None:
        bus = EventBus()
        state = PositionState()
        agent = StrategyAgent(bus, state)
        agent.register()

        received: list[dict] = []

        async def capture(data: dict) -> None:
            received.append(data)

        bus.on("ORDER_APPROVED", capture)

        await bus.emit_async(
            "SIGNAL_RESULT",
            {
                "type": "HOLD",
                "confidence": 0.9,
                "needs_claude": False,
            },
        )

        assert len(received) == 0
