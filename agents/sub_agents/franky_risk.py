"""
Franky (Risk Manager) - Risk Management & Position Safety

Sub-agent负责风险管理和仓位安全。
Monitors positions, checks drawdown, enforces risk limits,
and ensures portfolio safety.

Role: Risk Management
Reports to: Orchestrator (Pat)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("franky_risk")


class FrankyRiskAgent:
    """Risk management agent - enforces safety rules."""

    def __init__(self, max_drawdown: float = 0.15, max_position_pct: float = 0.25):
        self.name = "Franky"
        self.role = "Risk Manager"
        self.active = False
        self.max_drawdown = max_drawdown  # 15% max drawdown
        self.max_position_pct = max_position_pct  # 25% max position

    async def start(self):
        """Start the risk agent."""
        self.active = True
        logger.info("🔧 Franky (Risk Manager) - Online")

    def check_position_size(self, position_pct: float) -> dict[str, Any]:
        """Check if position size is within limits."""
        result = {
            "approved": True,
            "reason": "",
            "agent": "Franky",
        }

        if position_pct > self.max_position_pct:
            result["approved"] = False
            result["reason"] = f"Position {position_pct:.1%} exceeds max {self.max_position_pct:.1%}"

        return result

    def check_drawdown(self, current_drawdown: float) -> dict[str, Any]:
        """Check if drawdown is within limits."""
        result = {
            "approved": True,
            "action": "continue",
            "reason": "",
            "agent": "Franky",
        }

        if current_drawdown >= self.max_drawdown:
            result["approved"] = False
            result["action"] = "stop_all"
            result["reason"] = f"Max drawdown {self.max_drawdown:.1%} reached"

        elif current_drawdown >= self.max_drawdown * 0.8:
            result["action"] = "reduce_size"
            result["reason"] = f"Approaching max drawdown ({current_drawdown:.1%})"

        return result

    def check_leverage(self, leverage: int) -> dict[str, Any]:
        """Check if leverage is safe."""
        result = {
            "approved": True,
            "reason": "",
            "agent": "Franky",
        }

        if leverage > 20:
            result["approved"] = False
            result["reason"] = f"Leverage {leverage}x too high (max 20x)"

        return result

    def assess_trade_risk(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Assess risk level of a potential trade."""
        risk_score = 0
        reasons = []

        # Check position size
        size_pct = trade.get("size_pct", 0)
        if size_pct > 0.2:
            risk_score += 3
            reasons.append("Large position")

        # Check confidence
        confidence = trade.get("confidence", 0.5)
        if confidence < 0.6:
            risk_score += 2
            reasons.append("Low confidence")

        # Determine risk level
        if risk_score >= 4:
            level = "HIGH"
        elif risk_score >= 2:
            level = "MEDIUM"
        else:
            level = "LOW"

        return {
            "agent": "Franky",
            "risk_level": level,
            "risk_score": risk_score,
            "reasons": reasons,
        }

    async def stop(self):
        """Stop the risk agent."""
        self.active = False
        logger.info("🔧 Franky (Risk Manager) - Offline")
