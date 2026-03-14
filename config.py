"""Global configuration for the Binance Futures DCA Trading System.

Loads secrets from .env file. Never commit .env or credentials.
Uses Binance Futures Testnet by default.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")

# --- Binance API ---
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")

# --- Binance Production endpoints ---
BINANCE_WS_BASE: str = "wss://fstream.binance.com"
BINANCE_REST_BASE: str = "https://fapi.binance.com"

# --- MiniMax API (legacy, kept for reference) ---
MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_GROUP_ID: str = os.getenv("MINIMAX_GROUP_ID", "")
MINIMAX_MODEL: str = "MiniMax-Text-01"
MINIMAX_BASE_URL: str = "https://api.minimax.chat/v1"

# --- Groq API (Signal Agent) ---
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = "llama-3.3-70b-versatile"
GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

# --- Anthropic API ---
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = "claude-opus-4-20250514"
CLAUDE_HAIKU_MODEL: str = "claude-haiku-4-20250414"

# --- Telegram ---
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Symbol settings ---
SYMBOL: str = "BTCUSDC"
LEVERAGE: int = 10
MARGIN_TYPE: str = "ISOLATED"

# --- WebSocket streams (MVP: kline_1m only) ---
WS_STREAMS: list[str] = [
    f"{SYMBOL.lower()}@kline_1m",
]

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
