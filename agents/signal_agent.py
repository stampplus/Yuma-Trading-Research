"""Signal Agent — Groq (Llama 3.3 70B) integration for signal classification.

Tier 2 (free LLM worker). Receives MARKET_EVENT from EventBus, sends
compressed JSON context to Groq for signal classification, and emits
SIGNAL_RESULT with type, confidence, and needs_claude flag.

Architecture ref: Section 2 (Signal Agent), AGENT_ORCHESTRATOR.md Section 5.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

import config
from services.event_bus import EventBus
from services.state import IDLE, PositionState
from strategies.dca_config import MAX_DCA_LEVELS

logger = logging.getLogger(__name__)

# Event constants
SIGNAL_RESULT = "SIGNAL_RESULT"

# MiniMax system prompt for signal classification
SIGNAL_SYSTEM_PROMPT = """You are a crypto futures trading signal classifier.
You receive compressed market data in JSON format and return a trading signal.

You MUST respond with ONLY a valid JSON object, no explanation, no markdown.

Response format:
{
  "type": "LONG" | "SHORT" | "HOLD",
  "confidence": 0.0 to 1.0,
  "reasoning": "brief 1-sentence reason"
}

STRICT TRADING RULES:
- LONG when RSI < 50 (slightly oversold)
- SHORT when RSI > 55 (slightly overbought)
- Any volume is OK
- This is aggressive DCA - enter on most pullbacks

Remember: DCA strategy - buy the dip!"""

# Confidence threshold below which Claude is consulted
CONFIDENCE_THRESHOLD: float = 0.6


class SignalAgent:
    """Evaluates market events via Groq (Llama 3.3) and produces trading signals.

    Calls Groq on every MARKET_EVENT (candle close).
    Sets needs_claude flag based on escalation rules from
    AGENT_ORCHESTRATOR.md Section 6.

    Args:
        event_bus: EventBus instance for subscribing and emitting.
        state: PositionState for escalation logic.
    """

    def __init__(self, event_bus: EventBus, state: PositionState) -> None:
        self._bus = event_bus
        self._state = state
        self._session: aiohttp.ClientSession | None = None
        # Trade cooldown to reduce fees - minimum seconds between trades
        self._last_trade_time: float = 0
        self._min_trade_interval: int = 60  # Minimum 60 seconds between trades

    async def start(self) -> None:
        """Initialize the HTTP session for Gemini API calls."""
        self._session = aiohttp.ClientSession()
        logger.info("SignalAgent HTTP session initialized")

    async def stop(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    def register(self) -> None:
        """Register event handlers on the EventBus."""
        self._bus.on("MARKET_EVENT", self.handle_market_event)
        logger.info("SignalAgent registered for MARKET_EVENT")

    async def handle_market_event(self, data: dict[str, Any]) -> None:
        """Handle a MARKET_EVENT from the Market Data Agent.

        Sends compressed context to MiniMax, parses the signal result,
        determines escalation, and emits SIGNAL_RESULT.

        Args:
            data: MarketEvent dictionary with price, indicators, etc.
        """
        # Check trade cooldown
        import time
        current_time = time.time()
        if current_time - self._last_trade_time < self._min_trade_interval:
            # Skip signal if too soon after last trade (reduce fees)
            logger.debug("Trade cooldown active, skipping signal")
            return
        # Build compressed context for MiniMax (MODEL_ROUTING.md spec)
        context = self._build_context(data)

        # Call MiniMax for signal classification
        signal = await self._classify_signal(context)
        if signal is None:
            return

        # Determine escalation (AGENT_ORCHESTRATOR.md Section 6)
        signal["needs_claude"] = self._should_escalate(signal)
        signal["symbol"] = data.get("symbol", config.SYMBOL)
        signal["market_context"] = context

        logger.info(
            "Signal: type=%s confidence=%.2f needs_claude=%s | %s",
            signal.get("type"),
            signal.get("confidence", 0),
            signal.get("needs_claude"),
            signal.get("reasoning", ""),
        )

        # Update last trade time if not HOLD
        if signal.get("type") != "HOLD":
            self._last_trade_time = current_time
            logger.info("Trade executed, cooldown started: %d seconds", self._min_trade_interval)

        await self._bus.emit_async(SIGNAL_RESULT, signal)

    def _build_context(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build compressed JSON context for MiniMax.

        Args:
            data: MarketEvent dictionary.

        Returns:
            Compressed context dict (~200 tokens).
        """
        ctx: dict[str, Any] = {
            "sym": data.get("symbol", config.SYMBOL),
            "px": round(data.get("close", 0), 2),
            "open": round(data.get("open", 0), 2),
            "high": round(data.get("high", 0), 2),
            "low": round(data.get("low", 0), 2),
            "vol": round(data.get("volume", 0), 2),
        }

        # Add indicators if available
        if data.get("rsi_14") is not None:
            ctx["rsi_14"] = data["rsi_14"]
        if data.get("ema_50") is not None:
            ctx["ema_50"] = data["ema_50"]
        if data.get("price_change_pct") is not None:
            ctx["chg_pct"] = data["price_change_pct"]
        if data.get("vol_ratio") is not None:
            ctx["vol_ratio"] = data["vol_ratio"]

        # Add position state
        ctx["position"] = self._state.to_dict()

        return ctx

    async def _classify_signal(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Call AI API for signal classification.

        Uses Groq, Claude, or local RSI logic based on config.

        Args:
            context: Compressed market context.

        Returns:
            Parsed signal dict, or None on failure.
        """
        if not self._session:
            logger.warning("SignalAgent session not initialized, skipping")
            return None

        # Check which model to use
        model_choice = getattr(config, 'SIGNAL_MODEL', 'groq')

        if model_choice == 'claude':
            return await self._classify_with_claude(context)
        elif model_choice == 'local':
            return self._classify_local(context)
        else:
            return await self._classify_with_groq(context)

    def _classify_local(self, context: dict[str, Any]) -> dict[str, Any]:
        """Use local RSI-based logic for signal classification (free, instant).

        This is a simple but effective strategy based on RSI thresholds.
        """
        rsi = context.get('rsi_14', 50)
        price = context.get('price', 0)
        ema50 = context.get('ema_50', price)
        vol_ratio = context.get('vol_ratio', 1.0)

        # RSI-based signal
        if rsi < 40:
            signal_type = "LONG"
            reasoning = f"RSI oversold at {rsi:.1f}"
            confidence = 0.80 if rsi < 30 else 0.70
        elif rsi > 60:
            signal_type = "SHORT"
            reasoning = f"RSI overbought at {rsi:.1f}"
            confidence = 0.80 if rsi > 70 else 0.70
        else:
            signal_type = "HOLD"
            reasoning = f"RSI neutral at {rsi:.1f}"
            confidence = 0.60

        # Adjust confidence based on volume
        if vol_ratio > 1.5:
            confidence = min(0.95, confidence + 0.1)
            reasoning += ", high volume"
        elif vol_ratio < 0.5:
            confidence = max(0.40, confidence - 0.1)
            reasoning += ", low volume"

        logger.info(f"Local signal: {signal_type} confidence={confidence:.2f} RSI={rsi:.1f}")

        return {
            "type": signal_type,
            "confidence": confidence,
            "reasoning": reasoning,
            "needs_claude": False,
        }

    async def _classify_with_claude(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Call Claude API for signal classification."""

        if not config.ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set, falling back to Groq")
            return await self._classify_with_groq(context)

        url = "https://api.anthropic.com/v1/messages"

        payload = {
            "model": config.CLAUDE_MODEL,
            "max_tokens": 300,
            "system": SIGNAL_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": json.dumps(context)}],
        }

        headers = {
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Claude API error: HTTP %d — %s", resp.status, body[:300])
                    # Fallback to Groq
                    return await self._classify_with_groq(context)

                result = await resp.json()
                content = result.get("content", [{}])[0].get("text", "")
                return self._parse_signal_response(content)

        except Exception as e:
            logger.error("Claude classification failed: %s", e)
            return await self._classify_with_groq(context)

    async def _classify_with_groq(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Call Groq API (Llama 3.3 70B) for signal classification."""

        if not config.GROQ_API_KEY:
            logger.warning("GROQ_API_KEY not set, skipping signal classification")
            return None

        url = f"{config.GROQ_BASE_URL}/chat/completions"

        payload = {
            "model": config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SIGNAL_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context)},
            ],
            "temperature": 0.1,
            "max_tokens": 150,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "Groq API error: HTTP %d — %s",
                        resp.status,
                        body[:300],
                    )
                    return None

                result = await resp.json()

            # Extract content from OpenAI-compatible format
            choices = result.get("choices", [])
            if not choices:
                logger.error("Groq returned no choices: %s", result)
                return None

            content = choices[0].get("message", {}).get("content", "")

            # Parse JSON response
            return self._parse_signal_response(content)

        except aiohttp.ClientError as e:
            logger.error("Groq network error: %s", e)
            return None
        except Exception:
            logger.exception("Unexpected error calling Groq")
            return None

        if not config.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set, skipping signal classification")
            return None

        url = (
            f"{config.GEMINI_BASE_URL}/models/{config.GEMINI_MODEL}"
            f":generateContent?key={config.GEMINI_API_KEY}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"{SIGNAL_SYSTEM_PROMPT}\n\n"
                                f"Market data:\n{json.dumps(context)}"
                            ),
                        },
                    ],
                },
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 150,
                "responseMimeType": "application/json",
            },
        }

        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "Gemini API error: HTTP %d — %s",
                        resp.status,
                        body[:300],
                    )
                    return None

                result = await resp.json()

            # Extract the response content from Gemini format
            candidates = result.get("candidates", [])
            if not candidates:
                logger.error("Gemini returned no candidates: %s", result)
                return None

            content = (
                candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            )

            # Parse JSON response
            return self._parse_signal_response(content)

        except aiohttp.ClientError as e:
            logger.error("Gemini network error: %s", e)
            return None
        except Exception:
            logger.exception("Unexpected error calling Gemini")
            return None

    @staticmethod
    def _parse_signal_response(content: str) -> dict[str, Any] | None:
        """Parse MiniMax response into a signal dictionary.

        Args:
            content: Raw response text from MiniMax.

        Returns:
            Parsed signal dict, or None on parse failure.
        """
        # Strip markdown code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

        try:
            parsed: dict[str, Any] = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse Groq response as JSON: %s", content[:200])
            return None

        # Validate required fields
        signal_type = parsed.get("type", "HOLD")
        if signal_type not in ("LONG", "SHORT", "HOLD"):
            parsed["type"] = "HOLD"

        confidence = parsed.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
            parsed["confidence"] = 0.5

        return parsed

    def _should_escalate(self, signal: dict[str, Any]) -> bool:
        """Determine if this signal should be escalated to Claude.

        Follows AGENT_ORCHESTRATOR.md Section 6 escalation rules:
        1. First position entry (IDLE + LONG signal)
        2. Max DCA level reached
        3. Confidence below threshold
        4. Signal type is HOLD — no escalation needed

        Args:
            signal: Parsed signal dictionary.

        Returns:
            True if Claude should review this signal.
        """
        signal_type: str = str(signal.get("type", "HOLD"))
        confidence: float = float(signal.get("confidence", 0.5))

        # HOLD signals never need Claude
        if signal_type == "HOLD":
            return False

        # SHORT signals during open position — escalate for review
        if signal_type == "SHORT" and self._state.status != IDLE:
            return True

        # First entry — Claude must approve
        if self._state.status == IDLE and signal_type == "LONG":
            return True

        # Max DCA level — Claude must approve
        if self._state.dca_level >= MAX_DCA_LEVELS:
            return True

        # Low confidence — Claude decides
        return confidence < CONFIDENCE_THRESHOLD
