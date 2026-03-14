"""Strategy Agent — Claude Opus integration for order approval.

Tier 3 (Commander). Only called when MiniMax sets needs_claude=true.
Sends compressed JSON context, receives binary APPROVE/REJECT decision.
Enforces 30-minute cooldown and daily call budget.

Architecture ref: AGENT_ORCHESTRATOR.md Section 4,
MODEL_ROUTING.md Claude Budget Policy.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp
import anthropic

import config
from services.event_bus import EventBus
from services.state import PositionState
from strategies.dca_config import CLAUDE_COOLDOWN_MINUTES

logger = logging.getLogger(__name__)

# Daily budget tracking
MAX_DAILY_CALLS: int = 10

# Claude system prompt — concise, binary question pattern
STRATEGY_SYSTEM_PROMPT = """You are a crypto futures trading strategist.
You receive compressed market data and a specific binary question.
You MUST respond with ONLY a valid JSON object, no explanation, no markdown.

Response format:
{
  "decision": "APPROVE" | "REJECT",
  "params": {
    "side": "BUY" | "SELL",
    "size_pct": 0.01,
    "limit_offset_pct": 0.001
  },
  "reasoning": "brief 1-sentence reason",
  "ttl_minutes": 30
}

Rules:
- APPROVE means proceed with the trade
- REJECT means do not trade, wait for better conditions
- params.size_pct is fraction of balance (0.10 = 10%)
- params.limit_offset_pct is how far below current price to set limit order
- ttl_minutes is how long this decision is valid (for caching)
- Be conservative — when in doubt, REJECT
- Consider risk/reward, position size, and market conditions
- DCA-2 at -6% is higher risk — require stronger conviction"""


class StrategyAgent:
    """Reviews signals that require Claude Opus approval.

    Called sparingly — only for first entry, abnormal conditions,
    max DCA reached, or SL override requests. Enforces cooldown
    and daily call budget.

    Args:
        event_bus: EventBus instance for subscribing and emitting.
        state: Shared PositionState for reading position context.
    """

    def __init__(self, event_bus: EventBus, state: PositionState) -> None:
        self._bus = event_bus
        self._state = state
        self._client: anthropic.AsyncAnthropic | None = None
        self._http_session: aiohttp.ClientSession | None = None
        self._daily_calls: int = 0
        self._daily_reset: datetime = datetime.now(UTC)
        self._cached_decision: dict[str, Any] | None = None
        self._cache_expiry: datetime | None = None

    async def start(self) -> None:
        """Initialize the Anthropic client and Groq fallback session."""
        self._http_session = aiohttp.ClientSession()
        if config.ANTHROPIC_API_KEY:
            self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            logger.info("StrategyAgent initialized with Claude %s", config.CLAUDE_MODEL)
        else:
            logger.warning("ANTHROPIC_API_KEY not set — using Groq fallback only")
        logger.info("StrategyAgent Groq fallback ready (%s)", config.GROQ_MODEL)

    def register(self) -> None:
        """Register event handlers on the EventBus."""
        self._bus.on("SIGNAL_RESULT", self.handle_signal)
        logger.info("StrategyAgent registered for SIGNAL_RESULT")

    async def handle_signal(self, data: dict[str, Any]) -> None:
        """Handle a SIGNAL_RESULT that may require Claude review.

        Only processes signals where needs_claude=true.
        Enforces cooldown and budget before calling Claude.

        Args:
            data: Signal result dictionary with needs_claude flag.
        """
        needs_claude = data.get("needs_claude", False)
        if not needs_claude:
            # Auto-approved by MiniMax — forward to execution
            signal_type = data.get("type")
            if signal_type == "LONG":
                await self._bus.emit_async(
                    "ORDER_APPROVED",
                    {
                        "signal": data,
                        "source": "minimax_auto",
                        "params": {
                            "side": "BUY",
                            "size_pct": self._get_dynamic_size_pct(data.get("confidence", 0.5)),
                        },
                    },
                )
            elif signal_type == "SHORT":
                # SHORT means close position if open, otherwise ignore (no shorting)
                if self._state.status != IDLE:
                    await self._bus.emit_async(
                        "ORDER_APPROVED",
                        {
                            "signal": data,
                            "source": "minimax_auto",
                            "params": {
                                "side": "SELL",
                                "size_pct": 1.0,  # Close full position
                            },
                        },
                    )
                else:
                    # No position to close - ignore SHORT signal
                    logger.info("SHORT signal ignored - no open position")
            return

        # Check if Claude can be called
        if not self._can_call_claude():
            logger.warning("Claude call blocked — cooldown or budget exceeded")
            return

        # Check cached decision
        cached = self._get_cached_decision()
        if cached:
            logger.info("Using cached Claude decision: %s", cached.get("decision"))
            await self._process_decision(cached, data)
            return

        # Call Claude
        decision = await self._call_claude(data)
        if decision:
            await self._process_decision(decision, data)

    def _can_call_claude(self) -> bool:
        """Check cooldown timer and daily budget.

        Returns:
            True if Claude can be called.
        """
        now = datetime.now(UTC)

        # Reset daily counter if new day
        if now.date() != self._daily_reset.date():
            self._daily_calls = 0
            self._daily_reset = now

        # Daily budget check
        if self._daily_calls >= MAX_DAILY_CALLS:
            logger.warning(
                "Daily Claude budget exhausted (%d/%d)",
                self._daily_calls,
                MAX_DAILY_CALLS,
            )
            return False

        # Cooldown check
        if self._state.last_claude_call:
            elapsed = (now - self._state.last_claude_call).total_seconds() / 60
            if elapsed < CLAUDE_COOLDOWN_MINUTES:
                remaining = CLAUDE_COOLDOWN_MINUTES - elapsed
                logger.info("Claude cooldown active — %.1f min remaining", remaining)
                return False

        return True

    def _get_cached_decision(self) -> dict[str, Any] | None:
        """Return cached Claude decision if still valid.

        Returns:
            Cached decision dict, or None if expired/missing.
        """
        if not self._cached_decision or not self._cache_expiry:
            return None
        if datetime.now(UTC) > self._cache_expiry:
            self._cached_decision = None
            self._cache_expiry = None
            return None
        return self._cached_decision

    async def _call_claude(self, signal_data: dict[str, Any]) -> dict[str, Any] | None:
        """Call Claude Opus with compressed context.

        Args:
            signal_data: Signal result with market_context.

        Returns:
            Parsed decision dict, or None on failure.
        """
        # Build compressed context (MODEL_ROUTING.md spec)
        context = signal_data.get("market_context", {})
        context["signal"] = signal_data.get("type", "HOLD")
        context["confidence"] = signal_data.get("confidence", 0.5)
        context["question"] = self._determine_question(signal_data)

        # If Claude client not available, use Groq directly
        if not self._client:
            logger.info("Claude not available — using Groq fallback")
            return await self._call_groq_fallback(context)

        logger.info(
            "Calling Claude: question=%s | context=%s",
            context.get("question"),
            json.dumps(context),
        )

        try:
            response = await self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=300,
                system=STRATEGY_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": json.dumps(context)},
                ],
            )

            # Record the call
            self._state.record_claude_call()
            self._daily_calls += 1

            # Parse response
            content = (
                getattr(response.content[0], "text", "") if response.content else ""
            )
            decision = self._parse_decision(content)

            if decision:
                # Cache the decision
                from datetime import timedelta

                ttl = decision.get("ttl_minutes", 30)
                self._cached_decision = decision
                self._cache_expiry = datetime.now(UTC) + timedelta(
                    minutes=ttl,
                )

                logger.info(
                    "Claude decision: %s (call %d/%d today) reason=%s",
                    decision.get("decision"),
                    self._daily_calls,
                    MAX_DAILY_CALLS,
                    decision.get("reasoning", ""),
                )

            return decision

        except anthropic.APIError as e:
            logger.error("Claude API error: %s — falling back to Groq", e)
            return await self._call_groq_fallback(context)
        except Exception:
            logger.exception("Unexpected error calling Claude — falling back to Groq")
            return await self._call_groq_fallback(context)

    async def _call_groq_fallback(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Fallback to Groq when Claude is unavailable.

        Args:
            context: Compressed market context with question.

        Returns:
            Parsed decision dict, or None on failure.
        """
        if not self._http_session or not config.GROQ_API_KEY:
            logger.warning("Groq fallback not available")
            return None

        url = f"{config.GROQ_BASE_URL}/chat/completions"
        payload = {
            "model": config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": STRATEGY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context)},
            ],
            "temperature": 0.1,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            async with self._http_session.post(
                url,
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "Groq fallback error: HTTP %d — %s", resp.status, body[:300]
                    )
                    return None
                result = await resp.json()

            choices = result.get("choices", [])
            if not choices:
                logger.error("Groq fallback returned no choices")
                return None

            content = choices[0].get("message", {}).get("content", "")
            decision = self._parse_decision(content)

            if decision:
                self._daily_calls += 1
                logger.info(
                    "Groq fallback decision: %s reason=%s",
                    decision.get("decision"),
                    decision.get("reasoning", ""),
                )
            return decision

        except aiohttp.ClientError as e:
            logger.error("Groq fallback network error: %s", e)
            return None
        except Exception:
            logger.exception("Groq fallback unexpected error")
            return None

    def _determine_question(self, signal_data: dict[str, Any]) -> str:
        """Determine the binary question to ask Claude.

        Args:
            signal_data: Signal result dictionary.

        Returns:
            Question string (e.g. "APPROVE_FIRST_ENTRY?").
        """
        from services.state import IDLE

        if self._state.status == IDLE:
            return "APPROVE_FIRST_ENTRY?"
        if self._state.dca_level >= 2:
            return f"APPROVE_DCA_{self._state.dca_level + 1}?"
        if signal_data.get("type") == "SHORT":
            return "CLOSE_POSITION?"
        return "APPROVE_TRADE?"

    @staticmethod
    def _parse_decision(content: str) -> dict[str, Any] | None:
        """Parse Claude's response into a decision dictionary.

        Args:
            content: Raw response text from Claude.

        Returns:
            Parsed decision dict, or None on parse failure.
        """
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

        try:
            decision: dict[str, Any] = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse Claude response: %s", content[:300])
            return None

        if decision.get("decision") not in ("APPROVE", "REJECT"):
            logger.error("Invalid Claude decision: %s", decision.get("decision"))
            return None

        return decision

    async def _process_decision(
        self,
        decision: dict[str, Any],
        signal_data: dict[str, Any],
    ) -> None:
        """Process Claude's decision and emit appropriate event.

        Args:
            decision: Claude's APPROVE/REJECT decision.
            signal_data: Original signal result.
        """
        if decision.get("decision") == "APPROVE":
            params = decision.get("params", {})
            signal_type = signal_data.get("type", "LONG")
            confidence = signal_data.get("confidence", 0.5)

            if signal_type == "SHORT":
                # SHORT = close position if open, otherwise ignore
                if self._state.status != IDLE:
                    params["side"] = "SELL"
                    params["size_pct"] = 1.0  # Close full position
                else:
                    logger.info("SHORT ignored - no position to close")
                    return  # Don't emit ORDER_APPROVED
            else:
                # LONG = open position
                params["side"] = "BUY"
                # Use dynamic sizing based on confidence
                params["size_pct"] = self._get_dynamic_size_pct(confidence)

            await self._bus.emit_async(
                "ORDER_APPROVED",
                {
                    "signal": signal_data,
                    "source": "claude_approved",
                    "params": params,
                },
            )
        else:
            logger.info(
                "Claude REJECTED trade: %s",
                decision.get("reasoning", "no reason"),
            )

    def _get_dca_size_pct(self) -> float:
        """Get position size percentage for current DCA level.

        Returns:
            Size as fraction of balance.
        """
        from strategies.dca_config import BASE_POSITION_PCT, DCA_LEVELS

        level = self._state.dca_level + 1
        for dca in DCA_LEVELS:
            if dca["level"] == level:
                return BASE_POSITION_PCT * dca["size_multiplier"]
        return BASE_POSITION_PCT

    def _get_dynamic_size_pct(self, confidence: float) -> float:
        """Get position size based on AI confidence.

        Higher confidence = bigger position
        Lower confidence = smaller position

        Args:
            confidence: AI confidence score (0.0 - 1.0)

        Returns:
            Size as fraction of balance.
        """
        from strategies.dca_config import BASE_POSITION_PCT

        # Dynamic sizing based on confidence
        if confidence >= 0.85:
            return BASE_POSITION_PCT * 1.5  # 15% for high confidence
        elif confidence >= 0.70:
            return BASE_POSITION_PCT  # 10% for medium confidence
        elif confidence >= 0.55:
            return BASE_POSITION_PCT * 0.5  # 5% for low confidence
        else:
            return BASE_POSITION_PCT * 0.25  # 2.5% for very low confidence
