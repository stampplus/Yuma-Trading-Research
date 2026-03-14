# AGENT_ORCHESTRATOR.md — Multi-Agent Orchestration

## 1. Orchestration Philosophy

This system follows a **military command structure** for AI orchestration.
Claude Opus is the commander. MiniMax agents are the soldiers. Code agents
are the machinery.

```
Claude Opus 4.6        COMMANDER       Plans, decides, overrides
       |
       v
MiniMax 2.5 agents     WORKERS         Analyze, classify, score
       |
       v
Code agents            ENGINES         Parse, compute, execute
```

**Why this hierarchy works:**

- **Cost** -- Claude costs ~100x more per token than MiniMax. The commander
  gives orders once; the workers execute hundreds of times per day.
- **Speed** -- MiniMax responds in ~200ms. Claude takes ~2s. Routine
  decisions cannot wait for Claude.
- **Accuracy** -- Claude's reasoning is stronger, but 95% of trading
  signals are routine. MiniMax handles routine. Claude handles edge cases.
- **Scalability** -- Adding more symbols or strategies adds MiniMax load,
  not Claude load. Claude's daily budget stays flat.

**Core rule:** Claude tells MiniMax *what to do*. MiniMax tells code
*when to act*. Code never waits for AI on deterministic tasks.

---

## 2. Agent Hierarchy

### Tier 1 -- Command Agent (Claude Opus 4.6)

| Field | Value |
|-------|-------|
| Agent | `StrategyAgent` |
| Model | `claude-opus-4-6` |
| Responsibility | Final order approval, risk overrides, parameter adjustments, abnormal market handling |
| Trigger events | `POSITION_OPEN_REQUEST`, `DCA_FINAL_LEVEL`, `EMERGENCY_RISK`, `MANUAL_OVERRIDE` |
| Frequency | ~2-5 calls/day |
| File | `agents/strategy_agent.py` |

### Tier 2 -- Worker Agents (MiniMax 2.5 High-Speed)

#### SignalAgent

| Field | Value |
|-------|-------|
| Agent | `SignalAgent` |
| Model | `minimax-2.5-high-speed` |
| Responsibility | Classify market state, detect entry signals, evaluate DCA conditions, set `needs_claude` flag |
| Trigger events | `MARKET_EVENT` |
| Output events | `SIGNAL_RESULT` |
| Frequency | ~50-100 calls/day (every candle close) |
| File | `agents/signal_agent.py` |

#### RiskAgent (Phase 4)

| Field | Value |
|-------|-------|
| Agent | `RiskAgent` |
| Model | `minimax-2.5-high-speed` |
| Responsibility | Soft stop-loss evaluation, trend confirmation for exits, volatility regime detection |
| Trigger events | `MARKET_EVENT`, `SIGNAL_RESULT` |
| Output events | `RISK_ALERT` |
| Frequency | On-demand, when SignalAgent flags risk |
| File | `agents/risk_agent.py` (future) |

#### MarketAnalysisAgent (Phase 4)

| Field | Value |
|-------|-------|
| Agent | `MarketAnalysisAgent` |
| Model | `minimax-2.5-high-speed` |
| Responsibility | Market regime detection (trending/ranging/volatile), cross-timeframe analysis |
| Trigger events | `MARKET_EVENT` (on 15m and 1h candle close) |
| Output events | `REGIME_UPDATE` |
| Frequency | ~96 calls/day (every 15m candle) |
| File | `agents/market_analysis_agent.py` (future) |

### Tier 3 -- Code Agents (Pure Code)

#### MarketDataAgent

| Field | Value |
|-------|-------|
| Agent | `MarketDataAgent` |
| Model | None (pure code) |
| Responsibility | WebSocket connection, kline parsing, price buffering, indicator computation, event emission |
| Trigger events | WebSocket messages (continuous) |
| Output events | `KLINE_UPDATE`, `MARKET_EVENT` |
| File | `agents/market_data_agent.py` |

#### ExecutionAgent

| Field | Value |
|-------|-------|
| Agent | `ExecutionAgent` |
| Model | None (pure code) |
| Responsibility | Order placement via REST API, TP/SL management, fill tracking, position state updates |
| Trigger events | `ORDER_APPROVED`, `ORDER_FILL`, `ACCOUNT_UPDATE` |
| Output events | `POSITION_OPENED`, `POSITION_CLOSED` |
| File | `agents/execution_agent.py` |

---

## 3. Control Flow Architecture

### MVP Pipeline (Current)

```
Binance WebSocket
       |
       |  kline_1m stream (continuous)
       v
+------------------+
|  MarketDataAgent  |  [Code]  Parse kline, compute indicators, buffer prices
+--------+---------+
         |
         |  MARKET_EVENT (on candle close, ~1440/day)
         v
+------------------+
|   SignalAgent     |  [MiniMax]  Classify signal, evaluate DCA, set needs_claude
+--------+---------+
         |
         |  SIGNAL_RESULT
         v
    needs_claude?
    /           \
  false         true
   |              |
   |     +--------v---------+
   |     |  StrategyAgent   |  [Claude]  Approve/reject/adjust (rare)
   |     +--------+---------+
   |              |
   v              v
+------------------+
|  ExecutionAgent   |  [Code]  Place order, set TP/SL, track fills
+------------------+
         |
         v
  Binance REST API
  POST /fapi/v1/order
```

**Critical path:** Most signals flow `MarketData -> Signal -> Execution`,
bypassing Claude entirely. Claude is only on the critical path when
`needs_claude=true`.

### Phase 4 Pipeline (Future)

```
Binance WebSocket
       |
       v
+------------------+
|  MarketDataAgent  |  [Code]
+--------+---------+
         |
         |  MARKET_EVENT
         v
+------------------+     +------------------+     +-------------------+
|   SignalAgent     | --> |    RiskAgent      | --> | MarketAnalysis    |
|   [MiniMax]       |     |   [MiniMax]       |     | Agent [MiniMax]   |
+--------+---------+     +--------+---------+     +---------+---------+
         |                        |                          |
         v                        v                          v
    +----+------------------------+------ results aggregate --+
    |
    v
  needs_claude?
    |
   true --> StrategyAgent [Claude] --> aggregates MiniMax results --> decision
    |
  false --> ExecutionAgent [Code] directly
```

---

## 4. Claude Command Pattern

When Claude is invoked, it receives a structured command context containing
the aggregated results from MiniMax workers. Claude does not re-analyze raw
market data. It evaluates pre-processed intelligence.

### Command Input (sent to Claude)

```json
{
  "command": "APPROVE_ENTRY",
  "symbol": "BTCUSDT",
  "context": {
    "px": 66891,
    "chg_4h": -0.81,
    "vol_ratio": 1.4,
    "rsi_1h": 38,
    "funding": 0.0005
  },
  "position": {
    "status": "IDLE",
    "size": 0,
    "avg": null,
    "dca_level": 0
  },
  "signal": {
    "type": "LONG",
    "confidence": 0.78,
    "source": "SignalAgent"
  },
  "question": "APPROVE_FIRST_ENTRY?"
}
```

### Command Output (returned by Claude)

```json
{
  "decision": "APPROVE",
  "params": {
    "side": "BUY",
    "size_pct": 0.01,
    "limit_offset_pct": 0.001
  },
  "reasoning": "RSI oversold, price below EMA50, funding neutral",
  "ttl_minutes": 30
}
```

### Multi-Agent Command (Phase 4)

Claude can issue analysis tasks to multiple MiniMax agents at once:

```json
{
  "task": "analyze_market_state",
  "symbol": "BTCUSDT",
  "agents": ["SignalAgent", "RiskAgent", "MarketAnalysisAgent"],
  "deadline_ms": 500
}
```

Each agent returns its result independently. Claude aggregates:

```json
{
  "SignalAgent":         {"type": "LONG", "confidence": 0.78},
  "RiskAgent":           {"risk_level": "NORMAL", "vol_regime": "LOW"},
  "MarketAnalysisAgent": {"regime": "RANGING", "trend_strength": 0.3}
}
```

Claude makes a single decision from the combined picture.

---

## 5. MiniMax Worker Model

MiniMax agents are **stateless classifiers**. They receive structured input,
return structured output, and do not maintain conversation history.

### Tasks handled by MiniMax

| Task | Input | Output |
|------|-------|--------|
| Signal classification | OHLCV + indicators | `{type: LONG/SHORT/HOLD, confidence}` |
| DCA level evaluation | Price drop %, position state | `{trigger: bool, level, size_mult}` |
| Trend detection | Price buffer, EMA, RSI | `{trend: UP/DOWN/FLAT, strength}` |
| Confidence scoring | Combined indicators | `{confidence: 0.0-1.0}` |
| Regime detection | Multi-timeframe data | `{regime: TRENDING/RANGING/VOLATILE}` |
| Soft SL evaluation | Price vs EMA + trend | `{close_position: bool, reason}` |

### MiniMax rules

1. Every MiniMax call receives **compressed JSON**, never prose.
2. Every MiniMax response must include a `confidence` score (0.0-1.0).
3. If `confidence < 0.6`, the signal is marked `needs_claude: true`.
4. MiniMax never places orders. It only produces signals.
5. MiniMax never reads position state directly. State is passed in the
   input context by the calling agent.

---

## 6. Claude Escalation Rules

MiniMax must escalate to Claude when **any** of these conditions are true:

| # | Condition | Event Emitted | Reason |
|---|-----------|---------------|--------|
| 1 | First position entry (status=IDLE, signal=LONG) | `POSITION_OPEN_REQUEST` | New risk exposure requires strategic approval |
| 2 | Max DCA level reached (dca_level would become 3) | `DCA_FINAL_LEVEL` | Last-resort add, maximum risk reached |
| 3 | Abnormal volatility detected by MiniMax | `EMERGENCY_RISK` | Outside normal parameters, no fixed rule applies |
| 4 | MARGIN_CALL from Binance user stream | `EMERGENCY_RISK` | Liquidation imminent, judgment required |
| 5 | Signal confidence below threshold (< 0.6) | `SIGNAL_RESULT` with `needs_claude: true` | MiniMax is uncertain, needs stronger reasoning |
| 6 | Operator manual override request | `MANUAL_OVERRIDE` | Human-in-the-loop decision |

### Everything else bypasses Claude

| Scenario | Executor | Why Claude is NOT needed |
|----------|----------|--------------------------|
| DCA-1 at -3% | MiniMax + Code | Within parameters, auto-execute |
| Normal TP hit at +2% | Code | LIMIT order already placed, deterministic |
| Normal TP hit at +4% | Code | LIMIT order already placed, deterministic |
| Hard SL at -9% | Code | STOP_MARKET already placed, deterministic |
| Kline parsing | Code | JSON parsing, no reasoning |
| Indicator computation | Code | Pure math |
| Order placement | Code | REST API call with known parameters |

### Escalation Decision Tree

```
Signal from MiniMax
       |
       v
  Is it HOLD?
  +--YES--> STOP (no action, no Claude)
  |
  NO
  |
  v
  Is position IDLE and signal LONG?
  +--YES--> ESCALATE to Claude (first entry)
  |
  NO
  |
  v
  Is DCA level at max (3)?
  +--YES--> ESCALATE to Claude (final level)
  |
  NO
  |
  v
  Is confidence < 0.6?
  +--YES--> ESCALATE to Claude (uncertain)
  |
  NO
  |
  v
  Is market flagged abnormal?
  +--YES--> ESCALATE to Claude (risk review)
  |
  NO
  |
  v
  EXECUTE via code (auto DCA-1, normal operation)
```

---

## 7. Event Orchestration

All inter-agent communication uses the `EventBus` (observer pattern).
Agents subscribe to events and emit new events. There are no direct
agent-to-agent calls.

### Event Flow Map

```
KLINE_UPDATE          MarketDataAgent --> (any subscriber, used for live price display)
       |
MARKET_EVENT          MarketDataAgent --> SignalAgent
       |
SIGNAL_RESULT         SignalAgent --> StrategyAgent (if needs_claude=true)
       |                           --> ExecutionAgent (if needs_claude=false)
       |
RISK_ALERT            RiskAgent --> StrategyAgent (future)
       |
ORDER_APPROVED        StrategyAgent --> ExecutionAgent
       |
ORDER_FILL            UserStreamManager --> ExecutionAgent
       |
ACCOUNT_UPDATE        UserStreamManager --> ExecutionAgent
       |
MARGIN_CALL           UserStreamManager --> StrategyAgent (emergency)
       |
POSITION_OPENED       ExecutionAgent --> (logging, future AlertAgent)
       |
POSITION_CLOSED       ExecutionAgent --> (logging, state reset)
```

### Event Subscription Table

| Event | Producer | Consumer(s) |
|-------|----------|-------------|
| `KLINE_UPDATE` | `MarketDataAgent` | Live display, monitoring |
| `MARKET_EVENT` | `MarketDataAgent` | `SignalAgent` |
| `SIGNAL_RESULT` | `SignalAgent` | `StrategyAgent`, `ExecutionAgent` |
| `RISK_ALERT` | `RiskAgent` (future) | `StrategyAgent` |
| `ORDER_APPROVED` | `StrategyAgent` | `ExecutionAgent` |
| `ORDER_FILL` | `UserStreamManager` | `ExecutionAgent` |
| `ACCOUNT_UPDATE` | `UserStreamManager` | `ExecutionAgent` |
| `MARGIN_CALL` | `UserStreamManager` | `StrategyAgent` |
| `POSITION_OPENED` | `ExecutionAgent` | Logging, alerts |
| `POSITION_CLOSED` | `ExecutionAgent` | Logging, state reset |
| `POSITION_OPEN_REQUEST` | `SignalAgent` | `StrategyAgent` |
| `DCA_FINAL_LEVEL` | `SignalAgent` | `StrategyAgent` |
| `EMERGENCY_RISK` | `RiskAgent` / `UserStreamManager` | `StrategyAgent` |
| `MANUAL_OVERRIDE` | Operator CLI | `StrategyAgent` |

---

## 8. Token Efficiency Strategy

### Techniques

| # | Technique | Saves | How |
|---|-----------|-------|-----|
| 1 | **MiniMax gatekeeper** | ~95% of Claude calls | MiniMax classifies first; only edge cases reach Claude |
| 2 | **Event-driven calls** | ~90% vs polling | Claude called on state transitions, never on ticks |
| 3 | **JSON compression** | ~10x tokens per call | ~200 tokens vs ~2,000 for same information |
| 4 | **Decision caching** | ~50% of remaining calls | Reuse Claude's last answer until state invalidates it |
| 5 | **30-min cooldown** | Prevents burst calls | `PositionState.last_claude_call` enforced in code |
| 6 | **Batch context** | Eliminates mid-candle calls | Wait for candle close, never call on partial data |
| 7 | **Single binary question** | ~50% per call | One question per call, not open-ended conversation |

### Budget Targets

| Metric | Daily Target | Hard Ceiling |
|--------|-------------|--------------|
| Claude calls | < 5 | 10 max |
| Claude tokens | < 5,000 | 10,000 max |
| Tokens per call | ~200 | 1,000 max |
| MiniMax calls | ~50-100 | Uncapped |
| MiniMax tokens | ~30,000 | Uncapped |

### Cost Comparison

```
Without optimization:
  1,440 candles/day x ~2,000 tokens = 2,880,000 Claude tokens/day

With this architecture:
  5 calls/day x ~200 tokens = 1,000 Claude tokens/day

Reduction: 99.97%
```

---

## 9. Multi-Agent Coordination

### Current MVP (Single Worker)

```
MarketDataAgent (code)
       |
       v
  SignalAgent (MiniMax) --- single worker, handles all signals
       |
       v
  StrategyAgent (Claude) --- rare, conditional
       |
       v
  ExecutionAgent (code)
```

### Phase 4 (Multiple Workers)

Claude coordinates multiple MiniMax agents by issuing a single analysis
command. The agents execute in parallel and return independent results.

```
Claude issues command:
+----------------------------------------------------------+
|  "Analyze BTCUSDT market state before approving DCA-2"   |
+----------------------------------------------------------+
       |                    |                    |
       v                    v                    v
  SignalAgent          RiskAgent         MarketAnalysis
  [MiniMax]            [MiniMax]         Agent [MiniMax]
       |                    |                    |
       v                    v                    v
  {type: LONG,        {risk: NORMAL,      {regime: RANGING,
   confidence: 0.78}   vol: LOW}           strength: 0.3}
       |                    |                    |
       +--------------------+--------------------+
                            |
                            v
                    Claude aggregates:
              +----------------------------+
              |  All 3 agents agree:       |
              |  LONG + NORMAL + RANGING   |
              |  --> APPROVE DCA-2         |
              +----------------------------+
```

### Coordination Rules

1. Claude never re-analyzes raw data that MiniMax already processed.
2. MiniMax agents execute in parallel with a shared deadline (~500ms).
3. If any MiniMax agent fails to respond, Claude decides with partial data.
4. Claude's aggregation logic weights `confidence` scores from each agent.
5. The aggregated decision is cached until the next candle close.

---

## 10. Architecture Diagram

```
+=========================================================================+
|                          ORCHESTRATION LAYER                             |
|                                                                         |
|  +-------------------------------+                                      |
|  |     Claude Opus 4.6           |    COMMANDER                         |
|  |     (StrategyAgent)           |    ~2-5 calls/day                    |
|  |                               |    Approves, rejects, overrides      |
|  |  Receives:                    |                                      |
|  |    Compressed JSON context    |                                      |
|  |    MiniMax pre-processed      |                                      |
|  |    signals                    |                                      |
|  |  Returns:                     |                                      |
|  |    APPROVE / REJECT / ADJUST  |                                      |
|  +---------------+---------------+                                      |
|                  |                                                       |
|                  | ORDER_APPROVED (only when consulted)                  |
|                  v                                                       |
|  +-----------------------------------------------+                      |
|  |          MiniMax 2.5 Worker Pool               |    WORKERS           |
|  |                                                |    ~50-100 calls/day |
|  |  +-------------+  +----------+  +-----------+ |                      |
|  |  | SignalAgent  |  | RiskAgent|  | MarketAna | |                      |
|  |  | (MVP)        |  | (Phs 4) |  | (Phs 4)   | |                      |
|  |  +------+------+  +----+-----+  +-----+-----+ |                      |
|  |         |               |              |       |                      |
|  +-----------------------------------------------+                      |
|            |               |              |                              |
|            +-------+-------+------+-------+                              |
|                    |                                                     |
|                    | SIGNAL_RESULT                                       |
|                    v                                                     |
|  +-----------------------------------------------+                      |
|  |          Code Agent Layer                      |    ENGINES           |
|  |                                                |    Continuous        |
|  |  +----------------+     +------------------+  |                      |
|  |  | MarketDataAgent |     |  ExecutionAgent  |  |                      |
|  |  | (WebSocket,     |     |  (REST API,      |  |                      |
|  |  |  indicators)    |     |   TP/SL, state)  |  |                      |
|  |  +--------+-------+     +---------+--------+  |                      |
|  +-----------------------------------------------+                      |
|            |                          |                                  |
+=========================================================================+
             |                          |
             v                          v
     Binance WebSocket           Binance REST API
     (market data in)            (orders out)
```

### Data Flow Summary

```
Binance WS --> MarketDataAgent [code, continuous]
                    |
                    | MARKET_EVENT (candle close)
                    v
               SignalAgent [MiniMax, ~100/day]
                    |
                    | SIGNAL_RESULT {type, confidence, needs_claude}
                    v
              needs_claude?
               /         \
           false          true
             |              |
             |         StrategyAgent [Claude, ~5/day]
             |              |
             v              v
          ExecutionAgent [code, event-driven]
                    |
                    v
             Binance REST API
```
