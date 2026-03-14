"""
Zoro (Market Scanner) - Multi-Timeframe Analysis & Signal Confirmation

Sub-agent负责多时间框架分析和信号确认。
Monitors multiple timeframes, confirms signals,
and provides sharp market insights.

Role: Market Scanner & Signal Confirmation
Reports to: Orchestrator (Pat)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.get_logger("zoro_scanner")


class ZoroScannerAgent:
    """Market scanner - multi-timeframe analysis."""

    def __init__(self):
        self.name = "Zoro"
        self.role = "Market Scanner"
        self.active = False

    async def start(self):
        """Start the scanner agent."""
        self.active = True
        logger.info("⚔️ Zoro (Market Scanner) - Online")

    def analyze_timeframes(self, data_1m: dict, data_5m: dict, data_15m: dict) -> dict[str, Any]:
        """Analyze multiple timeframes for confirmation."""
        signals = []
        strength = 0

        # Check 1m
        if data_1m.get("rsi", 50) < 40:
            signals.append("1m: Oversold")
            strength += 1
        elif data_1m.get("rsi", 50) > 60:
            signals.append("1m: Overbought")
            strength -= 1

        # Check 5m
        if data_5m.get("rsi", 50) < 40:
            signals.append("5m: Oversold")
            strength += 2
        elif data_5m.get("rsi", 50) > 60:
            signals.append("5m: Overbought")
            strength -= 2

        # Check 15m
        if data_15m.get("rsi", 50) < 40:
            signals.append("15m: Oversold")
            strength += 3
        elif data_15m.get("rsi", 50) > 60:
            signals.append("15m: Overbought")
            strength -= 3

        # Determine overall signal
        if strength >= 4:
            recommendation = "STRONG_BUY"
        elif strength >= 2:
            recommendation = "BUY"
        elif strength <= -4:
            recommendation = "STRONG_SELL"
        elif strength <= -2:
            recommendation = "SELL"
        else:
            recommendation = "NEUTRAL"

        return {
            "agent": "Zoro",
            "type": "multi_tf_analysis",
            "signals": signals,
            "strength": strength,
            "recommendation": recommendation,
        }

    def confirm_signal(self, signal: dict[str, Any], market_data: dict[str, Any]) -> dict[str, Any]:
        """Confirm a signal with additional analysis."""
        confirmation = {
            "confirmed": True,
            "confidence_modifier": 0,
            "reasons": [],
        }

        # Check volume
        vol_ratio = market_data.get("vol_ratio", 1)
        if vol_ratio > 2:
            confirmation["confidence_modifier"] += 0.1
            confirmation["reasons"].append("High volume")
        elif vol_ratio < 0.5:
            confirmation["confidence_modifier"] -= 0.1
            confirmation["reasons"].append("Low volume")

        # Check price action
        price = market_data.get("price", 0)
        ema = market_data.get("ema50", 0)

        if signal.get("type") == "LONG":
            if price > ema:
                confirmation["confidence_modifier"] += 0.1
                confirmation["reasons"].append("Price above EMA")
            else:
                confirmation["confidence_modifier"] -= 0.1
                confirmation["reasons"].append("Price below EMA")

        # Apply modifier to original confidence
        original_confidence = signal.get("confidence", 0.5)
        confirmation["adjusted_confidence"] = min(1.0, max(0.0,
            original_confidence + confirmation["confidence_modifier"]))

        if confirmation["adjusted_confidence"] < 0.4:
            confirmation["confirmed"] = False

        return confirmation

    async def stop(self):
        """Stop the scanner agent."""
        self.active = False
        logger.info("⚔️ Zoro (Market Scanner) - Offline")
