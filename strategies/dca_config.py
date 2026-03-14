"""DCA strategy parameters for BTCUSDT MVP.

All strategy constants are defined here. Values match the architecture
document (Section 6).
"""

from __future__ import annotations

from typing import TypedDict

# --- Position sizing ---
BASE_POSITION_PCT: float = 0.10  # 10% of balance per entry

# --- DCA levels ---
MAX_DCA_LEVELS: int = 3  # entry + 2 DCA adds


class DCALevel(TypedDict):
    """Configuration for a single DCA level."""

    level: int
    drop_pct: float  # price drop from entry to trigger (0.0 for initial)
    size_multiplier: float  # multiplier of base position size
    auto: bool  # True = auto-execute, False = requires Claude approval


DCA_LEVELS: list[DCALevel] = [
    {"level": 1, "drop_pct": 0.0, "size_multiplier": 1.0, "auto": True},
    {"level": 2, "drop_pct": 0.03, "size_multiplier": 1.5, "auto": True},
    {"level": 3, "drop_pct": 0.06, "size_multiplier": 2.0, "auto": False},
]

# --- Take profit (wider for more profit) ---
TP1_PCT: float = 0.015  # +1.5% from avg entry, close 50%
TP1_CLOSE_RATIO: float = 0.50
TP2_PCT: float = 0.03  # +3% from avg entry, close remaining
TP2_CLOSE_RATIO: float = 1.00

# --- Stop loss ---
HARD_SL_PCT: float = 0.09  # -9% from avg entry -> STOP_MARKET
SOFT_SL_PCT: float = 0.06  # -6% -> Claude reviews

# --- Entry conditions (stricter for quality) ---
RSI_THRESHOLD: float = 40.0  # RSI(14) must be below 40 (more oversold)
RSI_OVERRIDE: float = 65.0  # Or above 65 for SHORT signals
EMA_PERIOD: int = 50  # EMA(50, 1h) — price must be below for LONG
FUNDING_RATE_MAX: float = 0.001  # 0.1% max funding rate

# --- Trend confirmation (avoid sideways) ---
MIN_VOLUME_RATIO: float = 1.5  # Volume must be 1.5x average

# --- Claude cooldown ---
CLAUDE_COOLDOWN_MINUTES: int = 30

# --- Trade cooldown (reduce fees) ---
MIN_TRADE_INTERVAL_SECONDS: int = 60  # Minimum 60 seconds between trades
