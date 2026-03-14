"""
Pat (Orchestrator) - COO & Main Coordinator

Sub-agent负责协调所有其他子代理。
Coordinates all sub-agents and manages the trading operation.

Role: Chief Operating Officer (COO)
Reports to: CEO (Yuma)

Sub-agents under management:
- Nami (Research Analyst) - Market research & strategy
- Franky (Risk Manager) - Risk management
- Chopper (Analytics Doctor) - Performance analysis
- Zoro (Market Scanner) - Multi-timeframe confirmation
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .nami_research import NamiResearchAgent
from .franky_risk import FrankyRiskAgent
from .chopper_analytics import ChopperAnalyticsAgent
from .zoro_scanner import ZoroScannerAgent

logger = logging.getLogger("pat_orchestrator")


class PatOrchestrator:
    """Orchestrator - coordinates all sub-agents.

    Pat is the Chief Operating Officer (COO) who manages:
    - Nami: Research & Strategy
    - Franky: Risk Management
    - Chopper: Analytics & Performance
    - Zoro: Market Scanning

    Reports to CEO: Yuma
    """

    def __init__(self):
        self.name = "Pat"
        self.role = "Orchestrator (COO)"
        self.ceo = "Yuma"

        # Initialize sub-agents
        self.nami = NamiResearchAgent()
        self.franky = FrankyRiskAgent()
        self.chopper = ChopperAnalyticsAgent()
        self.zoro = ZoroScannerAgent()

        self.active = False

    async def start(self) -> None:
        """Start all sub-agents."""
        self.active = True
        logger.info("🎩 Pat (Orchestrator/COO) - Starting all agents...")

        await self.nami.start()
        await self.franky.start()
        await self.chopper.start()
        await self.zoro.start()

        logger.info("=" * 50)
        logger.info("🎩 PAT ORCHESTRATOR - ONLINE")
        logger.info("CEO: Yuma | COO: Pat")
        logger.info("Team: Nami, Franky, Chopper, Zoro")
        logger.info("=" * 50)

    async def stop(self) -> None:
        """Stop all sub-agents."""
        logger.info("🎩 Pat (Orchestrator) - Shutting down...")

        await self.nami.stop()
        await self.franky.stop()
        await self.chopper.stop()
        await self.zoro.stop()

        self.active = False
        logger.info("🎩 Pat (Orchestrator) - Offline")

    async def process_trade_signal(self, signal: dict[str, Any], market_data: dict[str, Any]) -> dict[str, Any]:
        """Process a trade signal through all sub-agents.

        Flow:
        1. Zoro confirms signal with multi-timeframe analysis
        2. Franky checks risk limits
        3. Nami researches market conditions
        4. Chopper records performance

        Returns:
            Approved/rejected with reason
        """
        logger.info("🎩 Pat - Processing trade signal through team...")

        # Step 1: Zoro scans market
        zoro_result = await self.zoro.confirm_signal(signal, market_data)
        if not zoro_result.get("confirmed", True):
            return {
                "approved": False,
                "reason": f"Zoro rejected: {zoro_result.get('reasons', [])}",
                "by": "Zoro",
            }

        # Step 2: Franky checks risk
        risk_check = self.franky.assess_trade_risk({
            "size_pct": signal.get("size_pct", 0.1),
            "confidence": signal.get("confidence", 0.5),
        })
        if risk_check.get("risk_level") == "HIGH":
            return {
                "approved": False,
                "reason": f"Franky risk too high: {risk_check.get('reasons', [])}",
                "by": "Franky",
            }

        # Step 3: Nami researches
        nami_analysis = await self.nami.analyze_market(market_data)

        # Step 4: All clear - approve
        final_confidence = zoro_result.get("adjusted_confidence", signal.get("confidence", 0.5))

        return {
            "approved": True,
            "confidence": final_confidence,
            "zoro_signals": zoro_result.get("reasons", []),
            "nami_findings": nami_analysis.get("findings", []),
            "risk_level": risk_check.get("risk_level", "LOW"),
        }

    async def analyze_performance(self) -> dict[str, Any]:
        """Get full performance analysis from Chopper."""
        return self.chopper.get_performance_report()

    async def health_check(self) -> dict[str, Any]:
        """Run full system health check."""
        chopper_health = self.chopper.health_check()

        return {
            "orchestrator": "Pat",
            "status": "operational",
            "sub_agents": {
                "nami": self.nami.active,
                "franky": self.franky.active,
                "chopper": self.chopper.active,
                "zoro": self.zoro.active,
            },
            "health": chopper_health,
            "ceo": self.ceo,
        }

    def record_trade(self, trade: dict[str, Any]) -> None:
        """Record trade to Chopper for analytics."""
        self.chopper.record_trade(trade)
