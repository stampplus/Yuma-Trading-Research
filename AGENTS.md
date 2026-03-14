# AGENTS.md — Binance Futures DCA Trading System

## Project Overview

Python-based multi-agent trading system for Binance USDT-M Futures using a DCA
(Dollar Cost Averaging) entry strategy. MVP targets a single symbol (BTCUSDC)
with 3-10x leverage, ISOLATED margin, and an event-driven pipeline:
`Market Data Agent -> Signal Agent (Groq Llama) -> Strategy Agent (Groq/Claude) -> Execution Agent -> Binance REST API`.

---

## Build / Run / Test Commands

### Setup
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### Run
```bash
python main.py
```

### Testing
```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_signal_agent.py

# Run a single test function
pytest tests/test_signal_agent.py::test_dca_trigger -v

# Run with coverage
pytest --cov=. --cov-report=term-missing
```

### Linting / Formatting
```bash
ruff check .      # Lint
ruff format .     # Format
mypy . --strict  # Type checking
```

---

## Code Style Guidelines

### Language & Version
- **Python 3.11+** with `from __future__ import annotations` at the top of every module
- Use type hints on all function signatures and return types

### Naming Conventions
| Element        | Convention      | Example                           |
|----------------|----------------|-----------------------------------|
| Variables      | `snake_case`   | `avg_entry`, `dca_level`         |
| Functions      | `snake_case`   | `set_leverage()`, `get_listen_key()` |
| Classes        | `PascalCase`   | `EventBus`, `PositionState`      |
| Constants      | `UPPER_CASE`   | `IDLE`, `DCA_TRIGGER`            |
| Module files   | `snake_case.py`| `market_data_agent.py`           |
| Test files     | `test_*.py`    | `test_signal_agent.py`           |

### Import Ordering (isort style)
```python
# 1. Standard library
import asyncio
import json
from datetime import datetime

# 2. Third-party packages
import aiohttp
from binance.client import Client

# 3. Local modules
from services.event_bus import EventBus
from services.state import PositionState
```

### Formatting Rules
- **Indentation:** 4 spaces (no tabs)
- **Line length:** 88 characters max (ruff default)
- **Quotes:** Double quotes for strings
- **Trailing commas:** Always in multi-line collections
- **Docstrings:** Google style, required on public classes/functions

### Type Annotations
```python
def calculate_avg_entry(entries: list[dict[str, float]]) -> float:
    """Calculate weighted average entry price from position entries."""
    ...
```
- Use built-in generics (`list`, `dict`) over `typing` equivalents
- Use `X | None` for nullable types
- Use `TypedDict` for structured dictionaries (order params, market events)

### Error Handling
- Use specific exception types, **never bare `except:`**
- Wrap all Binance API calls with retry logic and exponential backoff
- Log errors with full context before re-raising
- WebSocket disconnections must auto-reconnect with backoff
- Order failures must be logged with order params for audit
```python
try:
    response = await rest_client.place_order(order_params)
except BinanceAPIError as e:
    logger.error("Order failed: %s | params: %s", e, order_params)
    raise
```

---

## Architecture

### Event Bus Pattern
All inter-agent communication uses `EventBus`:
```python
bus.emit("DCA_TRIGGER", {"level": 1, "price": 65000})
```
- Events: `UPPER_SNAKE_CASE` string constants
- Event data: always a dictionary

### State Management
- `PositionState` is the single source of truth for position data
- States: `IDLE`, `OPEN`, `CLOSING`
- Never mutate state outside the owning service module

---

## AI Agent Integration

### Signal Agent (Groq Llama 3.3 70B)
- Free tier, fast inference
- Called on every candle close (1min)
- Returns: `type` (LONG/SHORT/HOLD), `confidence`, `needs_claude`

### Strategy Agent (Claude Opus or Groq fallback)
- Called when `needs_claude=True` (first entry, max DCA, low confidence)
- Has Groq fallback when Anthropic credits unavailable
- Enforce 30-min cooldown, < 10 calls/day budget
- Sends compressed JSON context (~200 tokens max)

### Context Compression
```json
{"sym": "BTCUSDC", "px": 72500, "rsi_14": 42, "vol_ratio": 1.3,
 "position": {"size": 0.002, "avg": 72500}, "dca_level": 0}
```

---

## DCA Strategy (MVP)

- **Symbol:** BTCUSDC | **Leverage:** 3-10x | **Margin:** ISOLATED
- **Position:** 1% of balance per entry | **Max DCA:** 3 levels
- **Entry:** RSI < 45, price < EMA50, MiniMax=LONG
- **DCA-1:** -3% (auto) | **DCA-2:** -6% (approval) | **DCA-3:** -9% (stop)
- **TP:** +2% close 50% | +4% close rest | **SL:** -9% hard stop

---

## Key Principles

1. **Safety first** — ISOLATED margin, pre-trade liquidation checks, hard stops
2. **Event-driven** — react to state transitions, not price ticks
3. **Minimize AI costs** — Groq free tier, Claude only when needed
4. **Audit everything** — log all orders, state changes, AI decisions
5. **Start minimal** — ship working prototype, scale later
