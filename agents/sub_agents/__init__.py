"""
Sub-Agents Package - One Piece Trading Team

Sub-agents for the Yuma Trading System.

Team Structure (Reporting to CEO Yuma):
├── Pat (Orchestrator/COO)
│   ├── Nami (Research Analyst)
│   ├── Franky (Risk Manager)
│   ├── Chopper (Analytics Doctor)
│   └── Zoro (Market Scanner)
"""

from .pat_orchestrator import PatOrchestrator
from .nami_research import NamiResearchAgent
from .franky_risk import FrankyRiskAgent
from .chopper_analytics import ChopperAnalyticsAgent
from .zoro_scanner import ZoroScannerAgent

__all__ = [
    "PatOrchestrator",
    "NamiResearchAgent",
    "FrankyRiskAgent",
    "ChopperAnalyticsAgent",
    "ZoroScannerAgent",
]
