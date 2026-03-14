# MODEL_ROUTING.md — Executor Routing for the DCA Trading System

## Routing Philosophy

This system has three executor tiers. Every task must be assigned to the
**cheapest tier capable of handling it correctly**. The default executor is
pure code. AI is only introduced when deterministic logic is insufficient.

| Tier | Executor | Cost | Latency | Use when... |
|------|----------|------|---------|-------------|
| 1 | **Pure code** | Free | <1 ms | The task is deterministic and fully specified |
| 2 | **MiniMax 2.5 High-Speed** | Cheap | ~200 ms | The task requires pattern recognition or classification |
| 3 | **Claude Opus 4.6** | Expensive | ~2 s | The task requires strategic reasoning under uncertainty |

**Cardinal rule:** Never route to a higher tier when a lower tier can do the
job. If you are unsure, start with code. If code is insufficient, try MiniMax.
Claude is the last resort.

---

## Pipeline Architecture

```
Binance WebSocket
      |
      v
+---------------------+     +---------------------+     +---------------------+     +---------------------+
|  Market Data Agent  | --> |    Signal Agent      | --> |   Strategy Agent    | --> |  Execution Agent    |
|  [Pure code]        |     |  [MiniMax 2.5]       |     |  [Claude Opus]      |     |  [Pure code]        |
|                     |     |                      |     |  CONDITIONAL ONLY   |     |                     |
|  - WebSocket recv   |     |  - Signal classify   |     |  - First entry OK?  |     |  - Place orders     |
|  - Kline parsing    |     |  - DCA evaluation    |     |  - Risk override?   |     |  - Set TP/SL        |
|  - Indicator calc   |     |  - needs_claude flag |     |  - Abnormal market? |     |  - Track fills      |
|  - Buffer mgmt      |     |  - Confidence score  |     |  - Max DCA reached? |     |  - Update state     |
+---------------------+     +---------------------+     +---------------------+     +---------------------+
         |                            |                           |                           |
    Every tick               On candle close              Only when                    On approved
    (continuous)             (~50-100/day)              needs_claude=true              order params
                                                         (~2-5/day)
```

MiniMax acts as the **gatekeeper**. It sets `needs_claude: bool` on every
signal. Claude only sees the ~5% of signals that MiniMax cannot resolve alone.

---

## Task Routing Table

| Task Type | Executor | Model | Reason |
|-----------|----------|-------|--------|
| `market_data_processing` | Pure code | None | Deterministic: parse JSON, buffer prices, emit events |
| `indicator_calculation` | Pure code | None | Deterministic: RSI, EMA, ATR, volume ratios are math |
| `signal_detection` | MiniMax 2.5 | `minimax-2.5-high-speed` | Pattern recognition: classify market state, detect entry signals |
| `strategy_decision` | Claude Opus | `claude-opus-4-6` | Judgment under uncertainty: approve entries, override stops, handle abnormal conditions |
| `risk_management` | Split | See below | Normal risk = code. Abnormal risk = Claude |
| `order_execution` | Pure code | None | Deterministic: REST API calls, retries, state updates |
| `logging` | Pure code | None | Deterministic: structured writes, no interpretation needed |
| `testing` | Pure code | None | Deterministic: pytest assertions, mocks, fixtures |
| `debugging` | Pure code | None | Deterministic: read logs, inspect state, trace events |
| `code_generation` | Pure code | None | Developer task, not a runtime concern |
| `architecture_design` | Claude Opus | `claude-opus-4-6` | Offline planning only, never at runtime |

### Risk Management Breakdown

| Risk Scenario | Executor | Reason |
|---------------|----------|--------|
| Pre-trade liquidation check | Pure code | Compare `liquidationPrice` to entry, threshold is fixed |
| Hard stop-loss at -9% | Pure code | STOP_MARKET order, no judgment needed |
| Margin < 50% pause | Pure code | Compare margin ratio, threshold is fixed |
| Soft stop-loss at -6% + EMA | MiniMax 2.5 | Needs trend confirmation, not just a threshold |
| MARGIN_CALL event | Claude Opus | Judgment call: add margin vs close position |
| Abnormal volatility | Claude Opus | No fixed threshold, requires contextual reasoning |

---

## Automatic Routing Rules

These rules are evaluated **in order**. The first match wins.

```
1. if task is WebSocket parsing        --> code
2. if task is indicator math           --> code
3. if task is order placement          --> code
4. if task is TP/SL management         --> code
5. if task is state update             --> code
6. if task is logging or auditing      --> code
7. if task is signal classification    --> MiniMax
8. if task is DCA level evaluation     --> MiniMax
9. if task is trend/regime detection   --> MiniMax
10. if task is confidence scoring       --> MiniMax
11. if task is first position entry     --> Claude
12. if task is DCA-2 approval           --> Claude
13. if task is stop-loss override       --> Claude
14. if task is MARGIN_CALL response     --> Claude
15. if task is abnormal market flag     --> Claude
16. if none of the above match          --> code (safe default)
```

### MiniMax Gatekeeper Logic

MiniMax evaluates every `MARKET_EVENT` and returns a `SignalResult`:

```json
{
  "type": "LONG",
  "dca_level": 2,
  "confidence": 0.82,
  "needs_claude": false
}
```

`needs_claude` is set to `true` only when:

- Signal is `POSITION_OPEN_REQUEST` (first entry)
- DCA level would reach max (level 3)
- Confidence is below threshold for auto-execution
- Market conditions are flagged as abnormal
- MiniMax detects conditions outside its training distribution

If `needs_claude` is `false`, the signal bypasses Claude entirely and goes
straight to the Execution Agent.

---

## Claude Budget Policy

### Hard Limits

| Metric | Target | Hard Ceiling |
|--------|--------|--------------|
| Calls per day | < 5 | 10 max |
| Tokens per day | < 5,000 | 10,000 max |
| Tokens per call | ~200 | 1,000 max |
| Minimum gap between calls | 30 min | Enforced in code |

### Enforcement Mechanisms

1. **Cooldown timer** -- `PositionState.last_claude_call` tracks the timestamp.
   Strategy Agent rejects any call within 30 minutes of the previous one.
2. **MiniMax pre-filter** -- MiniMax handles 95%+ of signals. Claude never
   sees routine signals.
3. **Event gating** -- Claude is only called on state transitions, never on
   price ticks or open candles.
4. **Batch context** -- Wait for candle close before calling Claude. Never
   call mid-candle.
5. **Decision caching** -- Cache Claude's last decision. Reuse it until
   market state invalidates it (new candle close with significant change).
6. **Compressed JSON** -- Always send ~200 token JSON context, never prose.

### Context Template (sent to Claude)

```json
{
  "sym": "BTCUSDT",
  "px": 66891,
  "chg_4h": -0.81,
  "vol_ratio": 1.4,
  "rsi_1h": 38,
  "position": {"size": 0.02, "avg": 67100, "pnl": -1.2},
  "dca_level": 1,
  "signal": "BEARISH_CONTINUATION",
  "question": "APPROVE_DCA_2?"
}
```

Rules: JSON only. 2 decimal places max. No data beyond 4h lookback. One
binary question per call. Strip fields Claude does not need to answer.

---

## Events That Trigger Each Executor

### Pure Code (always, no gating)

| Event | Handler | Action |
|-------|---------|--------|
| WebSocket message | `BinanceWebSocketClient` | Parse kline, invoke callback |
| `KLINE_UPDATE` | `MarketDataAgent` | Update price buffer |
| Candle close | `MarketDataAgent` | Compute indicators, emit `MARKET_EVENT` |
| `ORDER_APPROVED` | `ExecutionAgent` | Place order via REST API |
| `ORDER_FILL` | `ExecutionAgent` | Update `PositionState`, place TP/SL |
| `ACCOUNT_UPDATE` | `ExecutionAgent` | Update balance tracking |

### MiniMax 2.5 (on candle close)

| Event | Handler | Action |
|-------|---------|--------|
| `MARKET_EVENT` | `SignalAgent` | Classify signal, set `needs_claude` flag |

### Claude Opus (conditional, rare)

| Event | Handler | Condition |
|-------|---------|-----------|
| `POSITION_OPEN_REQUEST` | `StrategyAgent` | First entry into new position |
| `DCA_FINAL_LEVEL` | `StrategyAgent` | Max DCA reached, last-resort decision |
| `EMERGENCY_RISK` | `StrategyAgent` | Unusual volatility or liquidation risk |
| `MANUAL_OVERRIDE` | `StrategyAgent` | Operator explicitly requests review |

---

## Anti-Patterns (never do these)

| Anti-Pattern | Why It Is Wrong | Correct Approach |
|-------------|-----------------|------------------|
| Call Claude on every candle close | Wastes budget, same answer 95% of the time | MiniMax classifies first, Claude only on edge cases |
| Send prose context to Claude | 10x token cost for same information | Compressed JSON (~200 tokens) |
| Call Claude for indicator calculation | Deterministic math, AI adds no value | Pure code: `RSI()`, `EMA()`, `ATR()` |
| Call Claude to parse WebSocket data | JSON parsing is code, not reasoning | `json.loads()` + field extraction |
| Call Claude for order placement | REST API call is deterministic | `BinanceRestClient.place_order()` |
| Call Claude for normal DCA-1 at -3% | Within parameters, auto-execute | MiniMax confirms, Execution Agent places |
| Skip MiniMax and call Claude directly | Violates gatekeeper pattern | Always route through MiniMax first |
| Call Claude within 30 min of last call | Violates cooldown policy | Check `last_claude_call` timestamp |

---

## Daily Token Budget Breakdown

```
+-------------------+--------------+---------------+-------------+
|  Agent            |  Model       |  Calls/day    |  Tokens/day |
+-------------------+--------------+---------------+-------------+
|  Market Data      |  Pure code   |  continuous   |  0          |
|  Signal Agent     |  MiniMax 2.5 |  ~50-100      |  ~30,000    |
|  Strategy Agent   |  Claude Opus |  ~2-5         |  ~2,000-5K  |
|  Execution Agent  |  Pure code   |  event-driven |  0          |
+-------------------+--------------+---------------+-------------+
```

Claude Opus savings: compressed JSON context reduces each call from ~2,000
tokens to ~200 tokens. At 5 calls/day, that is **1,000 tokens vs 10,000**.
