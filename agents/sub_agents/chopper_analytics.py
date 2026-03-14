"""
Chopper (Analytics Doctor) - Performance Analysis & Health Check

Sub-agent负责绩效分析和健康检查。
Monitors trading performance, analyzes metrics,
and provides health diagnostics.

Role: Analytics & Performance
Reports to: Orchestrator (Pat)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("chopper_analytics")


class ChopperAnalyticsAgent:
    """Analytics agent - tracks performance and health."""

    def __init__(self):
        self.name = "Chopper"
        self.role = "Analytics Doctor"
        self.active = False
        self.trades = []
        self.daily_stats = {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0,
        }

    async def start(self):
        """Start the analytics agent."""
        self.active = True
        logger.info("🏥 Chopper (Analytics Doctor) - Online")

    def record_trade(self, trade: dict[str, Any]) -> None:
        """Record a completed trade."""
        self.trades.append({
            **trade,
            "timestamp": datetime.now(),
        })

        self.daily_stats["trades"] += 1
        if trade.get("pnl", 0) > 0:
            self.daily_stats["wins"] += 1
        else:
            self.daily_stats["losses"] += 1
        self.daily_stats["total_pnl"] += trade.get("pnl", 0)

    def get_win_rate(self) -> float:
        """Calculate current win rate."""
        total = self.daily_stats["wins"] + self.daily_stats["losses"]
        if total == 0:
            return 0
        return self.daily_stats["wins"] / total

    def get_performance_report(self) -> dict[str, Any]:
        """Generate performance report."""
        win_rate = self.get_win_rate()
        total_trades = self.daily_stats["trades"]
        total_pnl = self.daily_stats["total_pnl"]

        # Calculate metrics
        avg_win = 0
        avg_loss = 0

        wins = [t.get("pnl", 0) for t in self.trades if t.get("pnl", 0) > 0]
        losses = [t.get("pnl", 0) for t in self.trades if t.get("pnl", 0) < 0]

        if wins:
            avg_win = sum(wins) / len(wins)
        if losses:
            avg_loss = sum(losses) / len(losses)

        return {
            "agent": "Chopper",
            "type": "performance_report",
            "period": "session",
            "total_trades": total_trades,
            "wins": self.daily_stats["wins"],
            "losses": self.daily_stats["losses"],
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": abs(avg_win / avg_loss) if avg_loss != 0 else 0,
        }

    def health_check(self) -> dict[str, Any]:
        """Perform system health check."""
        issues = []
        warnings = []

        win_rate = self.get_win_rate()
        if win_rate < 0.3:
            issues.append("Win rate critically low")
        elif win_rate < 0.4:
            warnings.append("Win rate below optimal")

        daily_trades = self.daily_stats["trades"]
        if daily_trades > 50:
            warnings.append("High trade frequency")

        return {
            "agent": "Chopper",
            "type": "health_check",
            "status": "healthy" if not issues else "critical",
            "issues": issues,
            "warnings": warnings,
        }

    def get_recommendations(self) -> list[str]:
        """Get improvement recommendations."""
        recommendations = []
        win_rate = self.get_win_rate()

        if win_rate < 0.4:
            recommendations.append("Consider stricter entry conditions")
        if self.daily_stats["losses"] > self.daily_stats["wins"]:
            recommendations.append("Review loss-making trades for patterns")
        if self.daily_stats["trades"] > 30:
            recommendations.append("Consider reducing trade frequency")

        return recommendations

    async def stop(self):
        """Stop the analytics agent."""
        self.active = False
        logger.info("🏥 Chopper (Analytics Doctor) - Offline")
