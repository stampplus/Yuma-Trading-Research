"""Telegram bot for trade alert notifications.

Pure code service (Tier 1) — sends formatted messages via the
Telegram Bot API. No AI involved.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

import config

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE: str = "https://api.telegram.org"


class TelegramNotifier:
    """Sends trade alerts to a Telegram chat.

    Args:
        bot_token: Telegram bot token.
        chat_id: Target chat/group ID.
    """

    def __init__(
        self,
        bot_token: str = config.TELEGRAM_BOT_TOKEN,
        chat_id: str = config.TELEGRAM_CHAT_ID,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._session: aiohttp.ClientSession | None = None
        self._enabled: bool = bool(bot_token and chat_id)

    async def start(self) -> None:
        """Initialize the HTTP session."""
        if not self._enabled:
            logger.warning("Telegram notifier disabled — missing bot token or chat ID")
            return
        self._session = aiohttp.ClientSession()
        logger.info("Telegram notifier initialized")

    async def stop(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def send_message(self, text: str, parse_mode: str = "HTML") -> None:
        """Send a text message to the configured chat.

        Args:
            text: Message text (supports HTML formatting).
            parse_mode: Telegram parse mode (HTML or Markdown).
        """
        if not self._enabled or not self._session:
            return

        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "Telegram send failed: HTTP %d — %s",
                        resp.status,
                        body,
                    )
                else:
                    logger.debug("Telegram message sent")
        except aiohttp.ClientError as e:
            logger.error("Telegram network error: %s", e)

    @staticmethod
    def _get_time() -> str:
        """Get current time string."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    # --- Convenience methods for trade events ---

    async def notify_startup(self) -> None:
        """Send system startup notification."""
        await self.send_message(
            f"<b>🚀 DCA Bot Started</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Symbol: <code>{config.SYMBOL}</code>\n"
            f"📊 Leverage: <code>{config.LEVERAGE}x</code>\n"
            f"🔒 Margin: <code>{config.MARGIN_TYPE}</code>\n"
            f"🌐 Mode: <b>PRODUCTION</b>\n"
            f"⏰ Time: {self._get_time()}",
        )

    async def notify_signal(self, signal: dict[str, Any]) -> None:
        """Send signal detection notification.

        Args:
            signal: SignalResult dictionary.
        """
        signal_type = signal.get("type", "HOLD")
        confidence = signal.get("confidence", 0)
        dca_level = signal.get("dca_level", 0)
        needs_claude = signal.get("needs_claude", False)
        reasoning = signal.get("reasoning", "N/A")
        price = signal.get("price", 0)

        emoji = (
            "🟢" if signal_type == "LONG" else "🔴" if signal_type == "SHORT" else "⚪"
        )

        await self.send_message(
            f"<b>{emoji} Signal Detected</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Type: <b>{signal_type}</b>\n"
            f"🎯 Confidence: <code>{confidence:.2%}</code>\n"
            f"📈 DCA Level: <code>{dca_level}</code>\n"
            f"💰 Price: <code>${price:,.2f}</code>\n"
            f"🤖 AI Review: <b>{'Yes' if needs_claude else 'No'}</b>\n"
            f"📝 Reason: {reasoning[:100]}",
        )

    async def notify_order(self, order: dict[str, Any], balance: float = 0) -> None:
        """Send order placement notification.

        Args:
            order: Order response from Binance.
            balance: Current account balance.
        """
        symbol = order.get("symbol", "N/A")
        side = order.get("side", "N/A")
        qty = order.get("origQty", "N/A")
        price = order.get("price", order.get("avgPrice", "MARKET"))
        order_id = order.get("orderId", "N/A")
        order_type = order.get("type", "N/A")

        side_emoji = "🟢 BUY" if side == "BUY" else "🔴 SELL"

        await self.send_message(
            f"<b>📝 Order Placed</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{side_emoji} | <code>{symbol}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Quantity: <code>{qty}</code>\n"
            f"💰 Price: <code>${price}</code>\n"
            f"📋 Type: <code>{order_type}</code>\n"
            f"🆔 OrderID: <code>{order_id}</code>\n"
            f"💳 Balance: <code>${balance:.2f}</code>\n"
            f"⏰ {self._get_time()}",
        )

    async def notify_fill(
        self,
        fill: dict[str, Any],
        position_size: float = 0,
        avg_entry: float = 0,
        total_pnl: float = 0,
    ) -> None:
        """Send order fill notification with position details.

        Args:
            fill: Fill event data.
            position_size: Current position size.
            avg_entry: Average entry price.
            total_pnl: Total unrealized PnL.
        """
        o = fill.get("o", {})
        symbol = o.get("s", "N/A")
        side = o.get("S", "N/A")
        fill_price = o.get("ap", "N/A")
        fill_qty = o.get("q", "N/A")
        realized_pnl = float(o.get("rp", 0))

        side_emoji = "🟢 BUY" if side == "BUY" else "🔴 SELL"
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

        await self.send_message(
            f"<b>✅ Order Filled</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{side_emoji} | <code>{symbol}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Filled: <code>{fill_qty}</code> @ <code>${fill_price}</code>\n"
            f"📊 Position: <code>{position_size}</code> BTC\n"
            f"📈 Avg Entry: <code>${avg_entry}</code>\n"
            f"{pnl_emoji} Unrealized PnL: <code>${total_pnl:.2f}</code>\n"
            f"💵 Realized PnL: <code>${realized_pnl:.2f}</code>\n"
            f"⏰ {self._get_time()}",
        )

    async def notify_claude_decision(
        self,
        decision: dict[str, Any],
        source: str = "Groq",
    ) -> None:
        """Send AI strategy decision notification.

        Args:
            decision: AI's decision response.
            source: Which AI (Claude or Groq).
        """
        action = decision.get("decision", "N/A")
        reasoning = decision.get("reasoning", "N/A")

        action_emoji = "✅ APPROVE" if action == "APPROVE" else "❌ REJECT"

        await self.send_message(
            f"<b>🤖 AI Decision ({source})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{action_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 Reasoning: {reasoning[:150]}",
        )

    async def notify_error(self, error: str) -> None:
        """Send error notification.

        Args:
            error: Error description.
        """
        await self.send_message(
            f"<b>❌ ERROR</b>\n━━━━━━━━━━━━━━━━━━━━\n{error}\n⏰ {self._get_time()}",
        )

    async def notify_dca_trigger(
        self,
        level: int,
        price: float,
        size_pct: float,
    ) -> None:
        """Send DCA trigger notification.

        Args:
            level: DCA level (1, 2, 3).
            price: Current price.
            size_pct: Position size percentage.
        """
        await self.send_message(
            f"<b>📉 DCA Level {level} Triggered</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Price: <code>${price:,.2f}</code>\n"
            f"📊 Size: <code>{size_pct:.1%}</code> of balance\n"
            f"⚡ Auto-execute: {'Yes' if level <= 2 else 'No (Approval needed)'}\n"
            f"⏰ {self._get_time()}",
        )

    async def notify_tp_sl(
        self,
        tp_sl_type: str,
        price: float,
        pnl: float,
        close_pct: float,
    ) -> None:
        """Send take profit / stop loss notification.

        Args:
            tp_sl_type: TP1, TP2, or SL.
            price: Execution price.
            pnl: Realized PnL.
            close_pct: Percentage of position closed.
        """
        emoji = "🎯" if "TP" in tp_sl_type else "🛑"

        await self.send_message(
            f"<b>{emoji} {tp_sl_type} Triggered</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Price: <code>${price:,.2f}</code>\n"
            f"📊 Closed: <code>{close_pct:.0%}</code> of position\n"
            f"{'🟢' if pnl >= 0 else '🔴'} PnL: <code>${pnl:.2f}</code>\n"
            f"⏰ {self._get_time()}",
        )

    async def notify_position_update(
        self,
        position_size: float,
        avg_entry: float,
        mark_price: float,
        pnl: float,
        liquidation: float,
        leverage: int,
    ) -> None:
        """Send position update notification.

        Args:
            position_size: Current position size.
            avg_entry: Average entry price.
            mark_price: Current mark price.
            pnl: Unrealized PnL.
            liquidation: Liquidation price.
            leverage: Current leverage.
        """
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        await self.send_message(
            f"<b>📊 Position Update</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Size: <code>{position_size}</code> BTC\n"
            f"📈 Entry: <code>${avg_entry:,.2f}</code>\n"
            f"💵 Mark: <code>${mark_price:,.2f}</code>\n"
            f"{pnl_emoji} PnL: <code>${pnl:.2f}</code>\n"
            f"⚠️ Liq: <code>${liquidation:,.2f}</code>\n"
            f"📊 Leverage: <code>{leverage}x</code>",
        )

    async def notify_balance(self, balance: float, pnl_total: float) -> None:
        """Send balance update notification.

        Args:
            balance: Current balance.
            pnl_total: Total PnL.
        """
        pnl_emoji = "🟢" if pnl_total >= 0 else "🔴"

        await self.send_message(
            f"<b>💰 Balance Update</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Available: <code>${balance:.2f}</code>\n"
            f"{pnl_emoji} Total PnL: <code>${pnl_total:.2f}</code>\n"
            f"⏰ {self._get_time()}",
        )
