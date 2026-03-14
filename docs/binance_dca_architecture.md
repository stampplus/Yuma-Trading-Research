# Binance Futures DCA Trading System — MVP Architecture

> **Design Philosophy:** Start minimal. Ship a working prototype. Scale later.  
> **Token Budget Rule:** Claude Opus is precious — treat each call like a $10 bill.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Multi-Agent Design](#2-multi-agent-design)
3. [Token-Efficient Design](#3-token-efficient-design)
4. [Data Flow Pipeline](#4-data-flow-pipeline)
5. [Binance API Usage](#5-binance-api-usage)
6. [DCA Strategy Design](#6-dca-strategy-design)
7. [Project Structure](#7-project-structure)
8. [Scaling Plan](#8-scaling-plan)

---

## 1. System Overview

### MVP Scope
- **1 symbol** (e.g. BTCUSDT)
- **Binance USDT-M Futures**
- **DCA entry strategy** with TP/SL
- **3 agents + pure code services**

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    TRADING SYSTEM MVP                    │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐                  │
│  │  Binance WS  │───▶│ Market Data  │                  │
│  │  (klines,    │    │   Agent      │                  │
│  │   bookTicker)│    │  [pure code] │                  │
│  └──────────────┘    └──────┬───────┘                  │
│                             │ price events              │
│                      ┌──────▼───────┐                  │
│                      │  Signal      │                  │
│                      │  Agent       │                  │
│                      │ [MiniMax 2.5]│                  │
│                      └──────┬───────┘                  │
│                             │ signal: BUY/HOLD/RISK     │
│                      ┌──────▼───────┐                  │
│                      │  Strategy    │ ◀── only when    │
│                      │  Agent       │     needed!      │
│                      │ [Claude Opus]│                  │
│                      └──────┬───────┘                  │
│                             │ approved order params    │
│                      ┌──────▼───────┐                  │
│                      │  Execution   │                  │
│                      │  Agent       │                  │
│                      │ [pure code]  │                  │
│                      └──────┬───────┘                  │
│                             │                          │
│                      ┌──────▼───────┐                  │
│                      │  Binance API │                  │
│                      │  (REST/WS)   │                  │
│                      └──────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Multi-Agent Design

### Agent Responsibilities

```
┌─────────────────────────────────────────────────────────────────┐
│ AGENT               │ MODEL         │ RESPONSIBILITY             │
├─────────────────────┼───────────────┼────────────────────────────┤
│ Market Data Agent   │ Pure code     │ WebSocket connection,      │
│                     │               │ price normalization,        │
│                     │               │ indicator calculation,      │
│                     │               │ event emission             │
├─────────────────────┼───────────────┼────────────────────────────┤
│ Signal Agent        │ MiniMax 2.5   │ Interpret market state,    │
│                     │ (cheap/fast)  │ classify signal type,      │
│                     │               │ decide if Claude needed,   │
│                     │               │ compute DCA levels         │
├─────────────────────┼───────────────┼────────────────────────────┤
│ Strategy Agent      │ Claude Opus   │ Final order approval,      │
│                     │ (expensive)   │ risk override decisions,   │
│                     │               │ parameter adjustments,     │
│                     │               │ abnormal market handling   │
├─────────────────────┼───────────────┼────────────────────────────┤
│ Execution Agent     │ Pure code     │ Place orders via REST,     │
│                     │               │ manage order lifecycle,    │
│                     │               │ handle retries/errors,     │
│                     │               │ track position state       │
└─────────────────────┴───────────────┴────────────────────────────┘
```

### Claude Opus — When to Call (Decision Tree)

```
Signal from MiniMax
        │
        ▼
   Is it HOLD?
  ┌──Yes──┐  No
  │       │   │
Skip     │   ▼
Claude   │  Is position already open?
         │  ┌──Yes──────────────────No──────┐
         │  │                               │
         │  ▼                               ▼
         │  Is it within normal      Is this a new
         │  DCA parameters?          entry signal?
         │  ┌──Yes──────No──┐        │
         │  │               │        ▼
         │  ▼               ▼      Call Claude ✓
         │ Skip           Call      (first entry)
         │ Claude         Claude ✓
         │              (risk review)
```

**Rule of thumb:** Claude is called for:
1. First entry into a new position
2. Abnormal market conditions flagged by MiniMax
3. Max DCA level reached (last-resort decision)
4. Stop-loss override requests

---

## 3. Token-Efficient Design

### 3.1 Reduce Claude Calls

| Technique | Description |
|-----------|-------------|
| **Event gating** | Only trigger Claude on state transitions, not price ticks |
| **MiniMax pre-filter** | MiniMax classifies 95%+ of signals; Claude only sees edge cases |
| **Cooldown timer** | Enforce minimum 30-min gap between Claude calls |
| **State caching** | Cache Claude's last decision and parameters; reuse until invalidated |
| **Batch context** | Never call Claude mid-candle; wait for candle close |

### 3.2 Compress Context Sent to Claude

**Bad (verbose):**
```
The BTC/USDT futures market has been showing signs of bearish pressure
over the last several hours. The price started at $67,432 and gradually
moved down to $66,891, with significant volume spikes at...
```

**Good (compressed):**
```json
{
  "sym": "BTCUSDT",
  "px": 66891,
  "chg_4h": -0.81,
  "vol_ratio": 1.4,
  "rsi_1h": 38,
  "position": { "size": 0.02, "avg": 67100, "pnl": -1.2 },
  "dca_level": 1,
  "signal": "BEARISH_CONTINUATION",
  "question": "APPROVE_DCA_2?"
}
```

**Context compression rules:**
- Always use JSON, never prose
- Numbers: 2 decimal places max
- No historical data beyond 4h lookback
- Ask one specific binary question per call
- Strip any data Claude doesn't need to answer

### 3.3 Event-Based vs Continuous Analysis

```
❌ Continuous (wasteful):
Every 60 seconds → send market state to Claude

✅ Event-based (efficient):
Candle closes → MiniMax analyzes
MiniMax detects threshold breach → emits DCA_TRIGGER event
DCA_TRIGGER event → only then, call Claude
```

**Events that trigger Claude:**
- `POSITION_OPEN_REQUEST` — first entry
- `DCA_FINAL_LEVEL` — max DCA reached  
- `EMERGENCY_RISK` — unusual vol/liquidation risk
- `MANUAL_OVERRIDE` — operator request

---

## 4. Data Flow Pipeline

### Full Pipeline Diagram

```
Binance WebSocket (wss://fstream.binance.com)
  │
  │  kline_1m, kline_15m streams
  │  bookTicker (best bid/ask)
  │
  ▼
┌────────────────────────────────────┐
│        Market Data Agent           │
│  • Maintains price buffer          │
│  • Computes: RSI, EMA, ATR, Vol   │
│  • Emits normalized MarketEvent    │
│  • NO AI calls here                │
└──────────────┬─────────────────────┘
               │
               │  MarketEvent {price, indicators, timestamp}
               ▼
┌────────────────────────────────────┐
│         Signal Agent (MiniMax)     │
│  • Receives MarketEvent            │
│  • Evaluates DCA conditions        │
│  • Returns: SignalResult           │
│    { type, dca_level, confidence,  │
│      needs_claude: bool }          │
└──────────────┬─────────────────────┘
               │
        ┌──────┴──────┐
        │             │
  needs_claude=false  needs_claude=true
        │             │
        ▼             ▼
   Skip Claude   ┌────────────────────────────────┐
        │        │     Strategy Agent (Claude)    │
        │        │  • Receives compressed context │
        │        │  • Approves/rejects/adjusts    │
        │        │  • Returns: OrderParams        │
        │        └──────────────┬─────────────────┘
        │                       │
        └──────────┬────────────┘
                   │
                   │  OrderParams (or null)
                   ▼
┌────────────────────────────────────┐
│       Execution Agent (code)       │
│  • Validates order params          │
│  • Places order via REST API       │
│  • Sets TP / SL orders             │
│  • Monitors fill via User Stream   │
│  • Updates position state          │
└──────────────┬─────────────────────┘
               │
               ▼
       Binance Futures REST API
       POST /fapi/v1/order
```

### State Machine (Position Lifecycle)

```
     ┌──────────┐
     │   IDLE   │◀──────────────────┐
     └────┬─────┘                   │
          │ DCA_TRIGGER             │ TP/SL hit
          ▼                         │
     ┌──────────┐              ┌────┴─────┐
     │  ENTRY_1 │──────────────▶  CLOSED  │
     └────┬─────┘              └──────────┘
          │ price drops X%          ▲
          ▼                         │
     ┌──────────┐                   │
     │  ENTRY_2 │                   │
     │  (DCA 1) │───────────────────┘
     └────┬─────┘   TP hit
          │ price drops Y%
          ▼
     ┌──────────┐
     │  ENTRY_3 │
     │  (DCA 2) │
     └──────────┘
          │ max level → call Claude
```

---

## 5. Binance API Usage

### 5.1 WebSocket Streams (Market Data)

```
Base: wss://fstream.binance.com/stream

Streams to subscribe:
┌─────────────────────────────────────────────────────┐
│ Stream Name              │ Purpose                   │
├──────────────────────────┼───────────────────────────┤
│ btcusdt@kline_1m         │ 1min candles for signals  │
│ btcusdt@kline_15m        │ 15min candles for trend   │
│ btcusdt@bookTicker       │ Real-time bid/ask spread  │
│ btcusdt@markPrice        │ Mark price + funding rate │
└──────────────────────────┴───────────────────────────┘

Combined stream URL:
wss://fstream.binance.com/stream?streams=btcusdt@kline_1m/btcusdt@markPrice
```

### 5.2 User Data Stream

```
1. Get listen key:
   POST /fapi/v1/listenKey

2. Subscribe:
   wss://fstream.binance.com/ws/<listenKey>

3. Renew every 30 min:
   PUT /fapi/v1/listenKey

Events received:
- ORDER_TRADE_UPDATE  → fill confirmations
- ACCOUNT_UPDATE      → balance changes
- MARGIN_CALL         → liquidation warning ⚠️
```

### 5.3 REST API — Order Placement

```
Base: https://fapi.binance.com

Key endpoints:
┌──────────────────────────────┬───────────────────────────────────────┐
│ Endpoint                     │ Usage                                 │
├──────────────────────────────┼───────────────────────────────────────┤
│ POST /fapi/v1/order          │ Place market / limit orders           │
│ DELETE /fapi/v1/order        │ Cancel individual order               │
│ DELETE /fapi/v1/allOpenOrders│ Cancel all open orders (emergency)   │
│ GET /fapi/v2/positionRisk    │ Check current position + liq price   │
│ GET /fapi/v2/balance         │ Check available margin                │
│ POST /fapi/v1/leverage       │ Set leverage for symbol               │
│ POST /fapi/v1/marginType     │ Set ISOLATED margin (safer for DCA)  │
└──────────────────────────────┴───────────────────────────────────────┘

Order placement example params:
{
  symbol: "BTCUSDT",
  side: "BUY",
  type: "LIMIT",
  timeInForce: "GTC",
  quantity: "0.002",
  price: "65000",
  reduceOnly: false
}
```

### 5.4 MVP Setup Calls (Run Once at Start)

```python
# Run at system startup
set_leverage(symbol, leverage=3)
set_margin_type(symbol, type="ISOLATED")
get_listen_key()
```

---

## 6. DCA Strategy Design

### 6.1 Strategy Parameters (MVP)

```
Symbol:          BTCUSDT
Leverage:        3x (conservative)
Margin Type:     ISOLATED (liquidation limited to allocated margin)
Base Position:   1% of balance per entry
Max DCA Levels:  3 (entry + 2 adds)
```

### 6.2 Entry Logic

```
Entry Condition (ALL must be true):
  ✓ RSI(14, 1h) < 45          → not overbought
  ✓ Price below EMA(50, 1h)   → short-term bearish
  ✓ No existing position      → flat
  ✓ Funding rate < 0.1%       → no extreme long bias
  ✓ MiniMax signal = LONG     → AI agrees

Entry Type: LIMIT order (0.1% below current price)
Position Size: 1% of available USDT balance
```

### 6.3 DCA Levels

```
┌────────────┬─────────────┬────────────────┬───────────────────┐
│ Level      │ Drop from   │ Position Add   │ Action            │
│            │ Entry       │                │                   │
├────────────┼─────────────┼────────────────┼───────────────────┤
│ Entry      │ —           │ 1.0x base      │ Auto (MiniMax)    │
│ DCA-1      │ -3%         │ 1.5x base      │ Auto (MiniMax)    │
│ DCA-2      │ -6%         │ 2.0x base      │ Claude approves   │
│ STOP       │ -9%         │ EXIT all       │ Auto (hard stop)  │
└────────────┴─────────────┴────────────────┴───────────────────┘

Average cost example (BTCUSDT at 67,000):
  Entry at 67,000: 0.001 BTC
  DCA-1 at 65,000: 0.0015 BTC
  DCA-2 at 63,000: 0.002 BTC   ← Claude reviews this add
  Average entry: ~64,800
  Required recovery for TP: ~66,300 (2.3%)
```

### 6.4 Take Profit

```
TP Logic:
  • TP-1: Close 50% of position at +2% from average entry
  • TP-2: Close remaining at +4% from average entry
  • Type: LIMIT orders, placed immediately after entry fill

Implementation:
  After entry fill confirmation (via User Stream):
    → Calculate average_entry_price
    → Place TP-1 LIMIT SELL at avg * 1.02
    → Place TP-2 LIMIT SELL at avg * 1.04
    → Both orders use reduceOnly: true
```

### 6.5 Stop Loss

```
Hard SL:   -9% from average entry → MARKET order (immediate)
Soft SL:   -6% AND candle close below EMA → Claude reviews

SL Implementation:
  • Use STOP_MARKET order type on Binance
  • Place immediately after position opens
  • Update SL price after each DCA fill (recalculate avg)

ORDER:
{
  type: "STOP_MARKET",
  side: "SELL",
  stopPrice: avg_entry * 0.91,
  closePosition: true   // closes 100% of position
}
```

### 6.6 Liquidation Protection

```
Pre-trade checks (before every order):
  1. Fetch positionRisk → check liquidationPrice
  2. Ensure liquidationPrice is > 15% away from entry
  3. If margin < 50% → pause new entries, alert operator

Margin call event (via User Stream):
  ON MARGIN_CALL:
    → Cancel all pending DCA orders immediately
    → Call Claude with emergency context
    → Claude decides: add margin OR close position
```

---

## 7. Project Structure

```
binance-dca-bot/
│
├── agents/
│   ├── market_data_agent.py     # WebSocket, price buffering, indicators
│   ├── signal_agent.py          # MiniMax 2.5 integration, signal logic
│   ├── strategy_agent.py        # Claude Opus integration, approval logic
│   └── execution_agent.py       # Order placement, state tracking
│
├── services/
│   ├── state.py                 # Shared position state (singleton)
│   ├── event_bus.py             # Simple in-process event emitter
│   └── logger.py                # Trade logging, audit trail
│
├── binance/
│   ├── websocket_client.py      # WS connection + reconnect logic
│   ├── rest_client.py           # Signed REST requests
│   └── user_stream.py           # Listen key mgmt + fill events
│
├── strategies/
│   └── dca_config.py            # DCA levels, TP/SL ratios, limits
│
├── prompts/
│   ├── minimax_signal.txt        # MiniMax system prompt
│   └── claude_strategy.txt       # Claude compressed context template
│
├── config.py                    # API keys, symbol, leverage settings
├── main.py                      # Startup, wires all agents together
└── README.md
```

### Event Bus (Simple In-Process)

```python
# event_bus.py — no external dependencies
class EventBus:
    def __init__(self):
        self._listeners = {}

    def on(self, event_type, handler):
        self._listeners.setdefault(event_type, []).append(handler)

    def emit(self, event_type, data):
        for handler in self._listeners.get(event_type, []):
            handler(data)

# Usage
bus = EventBus()
bus.on("DCA_TRIGGER", execution_agent.handle)
bus.on("MARGIN_CALL", strategy_agent.emergency_review)
bus.emit("DCA_TRIGGER", {"level": 1, "price": 65000})
```

### State Singleton

```python
# state.py — single source of truth
class PositionState:
    def __init__(self):
        self.status = "IDLE"          # IDLE | OPEN | CLOSING
        self.entries = []             # list of {price, qty, timestamp}
        self.avg_entry = None
        self.dca_level = 0
        self.tp_orders = []
        self.sl_order = None
        self.last_claude_call = None  # timestamp — enforce cooldown
```

---

## 8. Scaling Plan

### Phase 1 (MVP — Now)
```
✓ 1 symbol (BTCUSDT)
✓ 1 DCA strategy
✓ 3 agents
✓ Event-driven pipeline
✓ ~2-5 Claude calls/day
```

### Phase 2 (Multi-Symbol)
```
Change needed:
  • market_data_agent.py → subscribe to N symbol streams
  • state.py → Dict[symbol, PositionState] instead of singleton
  • execution_agent.py → queue orders per symbol
  • Add symbol config registry in strategies/

Claude calls: still low — each symbol only calls Claude on edge cases
MiniMax handles: all per-symbol signal routing
```

### Phase 3 (Multi-Strategy)
```
Add to strategies/:
  strategies/
    dca_config.py         # existing
    breakout_config.py    # new: breakout entry logic
    mean_revert_config.py # new: mean reversion

signal_agent.py selects strategy based on regime:
  trending market → breakout strategy
  ranging market  → DCA / mean reversion

Claude role: determine market regime (called once per 4h candle close)
```

### Phase 4 (Multi-Agent Expansion)
```
Add optional agents:
  agents/
    risk_agent.py          # Portfolio-level risk monitoring
    portfolio_agent.py     # Cross-symbol correlation checks
    alert_agent.py         # Telegram/Discord notifications
    backtest_agent.py      # Offline strategy validation

Claude only added to:
  risk_agent.py → portfolio-level decisions (rare)
  portfolio_agent.py → rebalancing decisions (very rare)
```

### Scaling Architecture

```
MVP (now):
  1 symbol → linear pipeline → 3 agents

Phase 2 (multi-symbol):
  N symbols → per-symbol event queues → shared agents with symbol context

Phase 3 (multi-strategy):
  Strategy router layer added between Signal and Execution agents

Phase 4 (full system):
  ┌──────────────────────────────────────────────┐
  │              Orchestrator                     │
  │         (routes events to agents)            │
  └──┬───────────┬───────────┬───────────────────┘
     │           │           │
  Symbol 1    Symbol 2    Symbol N
  pipeline    pipeline    pipeline
     │
  Per-symbol: Market Data → MiniMax → [Claude?] → Execution
```

---

## Token Budget Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    ESTIMATED DAILY TOKEN USAGE                   │
├───────────────────┬──────────────┬───────────────┬─────────────┤
│ Agent             │ Model        │ Calls/day     │ Tokens/day  │
├───────────────────┼──────────────┼───────────────┼─────────────┤
│ Signal Agent      │ MiniMax 2.5  │ ~50–100       │ ~30K        │
│ Strategy Agent    │ Claude Opus  │ ~2–5          │ ~2K–5K      │
│ Market Data       │ Pure code    │ continuous    │ 0           │
│ Execution         │ Pure code    │ event-driven  │ 0           │
└───────────────────┴──────────────┴───────────────┴─────────────┘

Claude Opus cost target: < 5,000 tokens/day
Key savings: compressed JSON context (~200 tokens/call vs ~2000)
```

---

*Architecture Version: MVP 1.0 | Target: OpenCode IDE | Symbol: BTCUSDT Futures*
