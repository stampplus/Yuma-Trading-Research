"""
Nami (Research Analyst) - Market Research & Strategy Analysis

Sub-agent负责市场研究和策略分析。
Monitors market conditions, researches new strategies,
and provides insights for improvement.

Role: Research & Analysis
Reports to: Orchestrator (Pat)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("nami_research")


class NamiResearchAgent:
    """Research agent - analyzes market conditions and strategies."""

    def __init__(self):
        self.name = "Nami"
        self.role = "Research Analyst"
        self.active = False

    async def start(self):
        """Start the research agent."""
        self.active = True
        logger.info("🧭 Nami (Research Analyst) - Online")

    async def analyze_market(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """Analyze current market conditions."""
        analysis = {
            "agent": "Nami",
            "type": "market_analysis",
            "findings": [],
            "recommendations": [],
        }

        # Analyze RSI
        rsi = market_data.get("rsi", 50)
        if rsi < 30:
            analysis["findings"].append("Oversold - potential buy opportunity")
        elif rsi > 70:
            analysis["findings"].append("Overbought - potential sell opportunity")

        # Analyze trend
        price = market_data.get("price", 0)
        ema = market_data.get("ema50", 0)
        if price < ema:
            analysis["findings"].append("Price below EMA50 - bearish")
        else:
            analysis["findings"].append("Price above EMA50 - bullish")

        return analysis

    async def research_strategy(self, performance_data: dict[str, Any]) -> dict[str, Any]:
        """Research and suggest strategy improvements."""
        win_rate = performance_data.get("win_rate", 0)
        avg_pnl = performance_data.get("avg_pnl", 0)

        recommendations = []

        if win_rate < 0.4:
            recommendations.append("Consider tightening entry conditions")
        if avg_pnl < 0:
            recommendations.append("Review stop loss strategy")

        return {
            "agent": "Nami",
            "type": "strategy_research",
            "win_rate": win_rate,
            "recommendations": recommendations,
        }

    async def stop(self):
        """Stop the research agent."""
        self.active = False
        logger.info("🧭 Nami (Research Analyst) - Offline")
