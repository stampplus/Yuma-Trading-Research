"""Execution Agent — order placement and position tracking.

Tier 1 (pure code). Places orders via Binance REST API,
manages TP/SL orders, and updates PositionState on fills.
No AI involved — all logic is deterministic.

Architecture ref: Section 2 (Execution Agent), Section 6 (DCA Strategy).

Optimizations:
- Uses MARKET orders for instant fills (vs LIMIT which can miss)
- Caches balance to avoid per-order API calls
- Uses closePosition=true for SL (simpler, faster)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import config
from binance.rest_client import BinanceAPIError, BinanceRestClient
from services.event_bus import EventBus
from services.logger import get_trade_logger
from services.state import IDLE, PositionState
from strategies.dca_config import (
    HARD_SL_PCT,
    MAX_DCA_LEVELS,
    TP1_CLOSE_RATIO,
    TP1_PCT,
    TP2_PCT,
)

logger = logging.getLogger(__name__)
trade_logger = get_trade_logger()

# Balance cache settings
BALANCE_CACHE_TTL: float = 30.0  # Refresh balance every 30s


class ExecutionAgent:
    """Places and manages orders on Binance Futures.

    Validates order parameters, performs pre-trade checks,
    places orders via REST API, sets TP/SL orders, and updates
    position state on fills.

    Args:
        event_bus: EventBus instance for subscribing and emitting.
        state: Shared PositionState for position tracking.
        rest_client: BinanceRestClient for API calls.
        telegram: Optional TelegramNotifier for alerts.
    """

    def __init__(
        self,
        event_bus: EventBus,
        state: PositionState,
        rest_client: BinanceRestClient,
        telegram: Any = None,
    ) -> None:
        self._bus = event_bus
        self._state = state
        self._rest = rest_client
        self._telegram = telegram
        # Balance cache for faster order placement
        self._cached_balance: float = 0.0
        self._balance_cache_time: float = 0.0

    def register(self) -> None:
        """Register event handlers on the EventBus."""
        self._bus.on("ORDER_APPROVED", self.handle_order)
        self._bus.on("ORDER_FILL", self.handle_fill)
        logger.info("ExecutionAgent registered for ORDER_APPROVED, ORDER_FILL")

    async def _get_cached_balance(self) -> float:
        """Get balance from cache or fetch fresh if expired."""
        now = time.time()
        if now - self._balance_cache_time > BALANCE_CACHE_TTL:
            self._cached_balance = await self._rest.get_usdt_balance()
            self._balance_cache_time = now
            logger.debug("Balance refreshed: %.2f", self._cached_balance)
        return self._cached_balance

    async def handle_order(self, data: dict[str, Any]) -> None:
        """Handle an approved order request.

        Performs pre-trade checks, calculates quantity, and places
        the order on Binance.

        Args:
            data: Approved order with signal and params.
        """
        params = data.get("params", {})
        source = data.get("source", "unknown")
        side = params.get("side", "BUY")
        size_pct = params.get("size_pct", 0.01)

        logger.info(
            "Processing approved order: source=%s side=%s size_pct=%.3f",
            source,
            side,
            size_pct,
        )

        # Pre-trade check: max DCA levels
        if side == "BUY" and self._state.dca_level >= MAX_DCA_LEVELS:
            logger.warning(
                "Max DCA levels reached (%d), rejecting order",
                MAX_DCA_LEVELS,
            )
            return

        try:
            # Use cached balance (much faster)
            balance = await self._get_cached_balance()
            if balance <= 0:
                logger.error("No available USDT/USDC balance")
                return

            # Get current price for quantity calculation
            position_risk = await self._rest.get_position_risk(config.SYMBOL)
            mark_price = float(position_risk.get("markPrice", 0))
            if mark_price <= 0:
                logger.error("Invalid mark price: %s", mark_price)
                return

            # Pre-trade liquidation check (only for DCA adds)
            if side == "BUY" and self._state.status != IDLE:
                liq_price_str = position_risk.get("liquidationPrice", "0")
                liq_price = float(liq_price_str) if liq_price_str != "0" else 0
                if liq_price > 0:
                    distance_pct = abs(mark_price - liq_price) / mark_price
                    if distance_pct < 0.15:
                        logger.warning(
                            "Liquidation too close (%.1f%%), rejecting order",
                            distance_pct * 100,
                        )
                        return

            # Calculate order quantity
            notional = balance * size_pct * config.LEVERAGE
            quantity = round(notional / mark_price, 3)

            if quantity <= 0:
                logger.error(
                    "Calculated quantity is 0 — balance=%.2f price=%.2f",
                    balance,
                    mark_price,
                )
                return

            # Use MARKET order for instant execution (much faster than LIMIT)
            order_params: dict[str, Any] = {
                "symbol": config.SYMBOL,
                "side": side,
                "type": "MARKET",
                "quantity": str(quantity),
            }

            # If closing, set reduceOnly
            if side == "SELL" and self._state.status != IDLE:
                order_params["reduceOnly"] = "true"

            result = await self._rest.place_order(order_params)

            trade_logger.info(
                "ORDER PLACED: orderId=%s side=%s qty=%s type=MARKET source=%s",
                result.get("orderId"),
                side,
                quantity,
                source,
            )

            # Send Telegram notification
            if self._telegram:
                await self._telegram.notify_order(result)

        except BinanceAPIError as e:
            logger.error("Order placement failed: %s", e)
            trade_logger.error("ORDER FAILED: %s | params=%s", e, params)
            if self._telegram:
                await self._telegram.notify_error(f"Order failed: {e}")
        except Exception:
            logger.exception("Unexpected error placing order")

    async def handle_fill(self, data: dict[str, Any]) -> None:
        """Handle an order fill from the User Data Stream.

        Updates PositionState and places TP/SL orders after entry fills.

        Args:
            data: ORDER_TRADE_UPDATE event data from Binance.
        """
        order_data = data.get("o", {})
        symbol = order_data.get("s", "")
        side = order_data.get("S", "")
        status = order_data.get("X", "")
        fill_price = float(order_data.get("ap", 0))
        fill_qty = float(order_data.get("q", 0))
        realized_pnl = float(order_data.get("rp", 0))

        if symbol != config.SYMBOL:
            return

        if status != "FILLED":
            logger.debug("Order status %s (not FILLED), skipping", status)
            return

        trade_logger.info(
            "ORDER FILLED: symbol=%s side=%s price=%.2f qty=%.4f pnl=%.4f",
            symbol,
            side,
            fill_price,
            fill_qty,
            realized_pnl,
        )

        if side == "BUY":
            # New entry or DCA add
            self._state.add_entry(price=fill_price, qty=fill_qty)
            logger.info(
                "Position updated: level=%d avg=%.2f total_qty=%.4f",
                self._state.dca_level,
                self._state.avg_entry or 0,
                self._state.total_qty(),
            )

            # Place TP/SL orders
            await self._place_tp_sl_orders()

        elif side == "SELL":
            # Check if position is fully closed
            remaining = self._state.total_qty() - fill_qty
            if remaining <= 0.0001:  # Effectively zero
                self._state.close_position()
                logger.info("Position fully closed — PnL: %.4f", realized_pnl)
                await self._bus.emit_async(
                    "POSITION_CLOSED",
                    {
                        "symbol": symbol,
                        "pnl": realized_pnl,
                    },
                )

        # Send Telegram notification
        if self._telegram:
            await self._telegram.notify_fill(data)

    async def _place_tp_sl_orders(self) -> None:
        """Place TP and SL orders after a position entry/add.

        TP-1: +2% from avg, close 50% (MARKET for faster fill)
        TP-2: +4% from avg, close remaining (MARKET for faster fill)
        SL:   -9% from avg, STOP_MARKET with closePosition=true
        """
        if not self._state.avg_entry:
            return

        avg = self._state.avg_entry
        total_qty = self._state.total_qty()

        # Cancel existing TP/SL before placing new ones
        import contextlib

        with contextlib.suppress(BinanceAPIError):
            await self._rest.cancel_all_orders(config.SYMBOL)

        # TP-1: close 50% at +2% — use MARKET for instant fill
        tp1_price = round(avg * (1 + TP1_PCT), 2)
        tp1_qty = round(total_qty * TP1_CLOSE_RATIO, 3)

        if tp1_qty > 0:
            try:
                result = await self._rest.place_order(
                    {
                        "symbol": config.SYMBOL,
                        "side": "SELL",
                        "type": "LIMIT",
                        "timeInForce": "GTC",
                        "quantity": str(tp1_qty),
                        "price": str(tp1_price),
                        "reduceOnly": "true",
                    }
                )
                self._state.tp_orders.append(str(result.get("orderId", "")))
                trade_logger.info(
                    "TP-1 placed: price=%.2f qty=%.3f",
                    tp1_price,
                    tp1_qty,
                )
            except BinanceAPIError as e:
                logger.error("TP-1 placement failed: %s", e)

        # TP-2: close remaining at +4% — use LIMIT (aggressive price)
        tp2_price = round(avg * (1 + TP2_PCT), 2)
        tp2_qty = round(total_qty - tp1_qty, 3)

        if tp2_qty > 0:
            try:
                result = await self._rest.place_order(
                    {
                        "symbol": config.SYMBOL,
                        "side": "SELL",
                        "type": "LIMIT",
                        "timeInForce": "GTC",
                        "quantity": str(tp2_qty),
                        "price": str(tp2_price),
                        "reduceOnly": "true",
                    }
                )
                self._state.tp_orders.append(str(result.get("orderId", "")))
                trade_logger.info(
                    "TP-2 placed: price=%.2f qty=%.3f",
                    tp2_price,
                    tp2_qty,
                )
            except BinanceAPIError as e:
                logger.error("TP-2 placement failed: %s", e)

        # Hard SL: -9% from avg — use closePosition=true (simpler, faster)
        sl_price = round(avg * (1 - HARD_SL_PCT), 2)

        try:
            result = await self._rest.place_order(
                {
                    "symbol": config.SYMBOL,
                    "side": "SELL",
                    "type": "STOP_MARKET",
                    "stopPrice": str(sl_price),
                    "closePosition": "true",
                }
            )
            self._state.sl_order = str(result.get("orderId", ""))
            trade_logger.info(
                "SL placed: stopPrice=%.2f (%.0f%% from avg) closePosition=true",
                sl_price,
                HARD_SL_PCT * 100,
            )
        except BinanceAPIError as e:
            logger.error("SL placement failed: %s", e)
