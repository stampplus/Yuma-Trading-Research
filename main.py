"""Entry point — wires all agents together and starts the trading system.

Startup sequence:
1. Load .env and initialize logging
2. Create shared services (EventBus, PositionState, Telegram)
3. Initialize Binance clients (REST, WebSocket, User Stream)
4. Set leverage and margin type on Binance
5. Create agents and register event handlers
6. Start WebSocket streams and user data stream
7. Run until interrupted
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import config
from agents.execution_agent import ExecutionAgent
from agents.market_data_agent import MarketDataAgent
from agents.signal_agent import SignalAgent
from agents.strategy_agent import StrategyAgent
from binance.rest_client import BinanceAPIError, BinanceRestClient
from binance.user_stream import UserStreamManager
from binance.websocket_client import BinanceWebSocketClient
from services.event_bus import EventBus
from services.logger import setup_logging
from services.state import PositionState
from services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize all components and start the trading system."""
    # 1. Logging
    setup_logging(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.info("=" * 60)
    logger.info("Binance Futures DCA Trading System — Starting")
    logger.info(
        "Symbol: %s | Leverage: %dx | Margin: %s",
        config.SYMBOL,
        config.LEVERAGE,
        config.MARGIN_TYPE,
    )
    logger.info("REST: %s", config.BINANCE_REST_BASE)
    logger.info("WS:   %s", config.BINANCE_WS_BASE)
    logger.info("Streams: %s", config.WS_STREAMS)
    logger.info("MiniMax model: %s", config.MINIMAX_MODEL)
    logger.info("Claude model:  %s", config.CLAUDE_MODEL)
    logger.info("=" * 60)

    # 2. Shared services
    event_bus = EventBus()
    state = PositionState()
    telegram = TelegramNotifier()

    # 3. Binance clients
    rest_client = BinanceRestClient()
    await rest_client.start()
    await telegram.start()

    # 4. Account setup — set leverage and margin type
    try:
        await rest_client.set_leverage(config.SYMBOL, config.LEVERAGE)
        await rest_client.set_margin_type(config.SYMBOL, config.MARGIN_TYPE)
        balance = await rest_client.get_usdt_balance()
        logger.info(
            "Account setup complete — available balance: %.2f | Mode: PRODUCTION",
            balance,
        )
    except BinanceAPIError as e:
        logger.error("Account setup failed: %s", e)
        logger.error("Check your API keys and testnet configuration")
        await rest_client.stop()
        await telegram.stop()
        return

    # 5. Agents
    market_data_agent = MarketDataAgent(event_bus)
    await market_data_agent.fetch_historical(60)  # Pre-load 60 candles for indicators

    signal_agent = SignalAgent(event_bus, state)
    strategy_agent = StrategyAgent(event_bus, state)
    execution_agent = ExecutionAgent(event_bus, state, rest_client, telegram)

    # Initialize AI agent sessions
    await signal_agent.start()
    await strategy_agent.start()

    # Register event handlers
    signal_agent.register()
    strategy_agent.register()
    execution_agent.register()

    # 6. User data stream (for fill/margin events)
    user_stream = UserStreamManager(event_bus, rest_client)
    await user_stream.start()

    # 7. WebSocket client — passes klines to market data agent
    ws_client = BinanceWebSocketClient(
        streams=config.WS_STREAMS,
        on_kline=market_data_agent.handle_kline,
    )

    # 8. Graceful shutdown handler + kill switch
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    # Kill switch: create /tmp/trading_bot_stop to stop bot
    import os
    STOP_FILE = "/tmp/trading_bot_stop"

    async def check_kill_switch() -> None:
        """Check for kill switch file periodically."""
        while not shutdown_event.is_set():
            if os.path.exists(STOP_FILE):
                logger.info("Kill switch activated!")
                os.remove(STOP_FILE)
                shutdown_event.set()
            await asyncio.sleep(2)

    loop = asyncio.get_running_loop()
    import contextlib

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    # 9. Send startup notification
    await telegram.notify_startup()

    # 10. Start streaming + kill switch checker
    logger.info("Starting WebSocket connection...")
    ws_task = asyncio.create_task(ws_client.start())
    kill_task = asyncio.create_task(check_kill_switch())

    try:
        if sys.platform == "win32":
            await ws_task
        else:
            await shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Interrupted — shutting down...")
    finally:
        # 11. Cleanup
        logger.info("Stopping components...")
        kill_task.cancel()
        await ws_client.stop()
        await user_stream.stop()
        await signal_agent.stop()
        await rest_client.stop()
        await telegram.stop()
        ws_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ws_task
        with contextlib.suppress(asyncio.CancelledError):
            await kill_task
        event_bus.clear()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    import contextlib as _contextlib

    with _contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
