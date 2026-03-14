"""Trade logging and audit trail.

Configures structured logging for the trading system. All orders,
state changes, and AI decisions are logged with timestamps.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_DIR = Path("logs")


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for the trading system.

    Sets up both console and file handlers with structured formatting.

    Args:
        level: Logging level (default: INFO).
    """
    LOG_DIR.mkdir(exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # Console handler — all log levels
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT),
    )
    root_logger.addHandler(console_handler)

    # File handler — all log levels, append mode
    file_handler = logging.FileHandler(
        LOG_DIR / "trading.log",
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT),
    )
    root_logger.addHandler(file_handler)

    # Trade-specific file handler — INFO and above, for audit trail
    trade_handler = logging.FileHandler(
        LOG_DIR / "trades.log",
        encoding="utf-8",
    )
    trade_handler.setLevel(logging.INFO)
    trade_handler.setFormatter(
        logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT),
    )
    trade_logger = logging.getLogger("trades")
    trade_logger.addHandler(trade_handler)

    logging.getLogger(__name__).info(
        "Logging initialized — level=%s",
        logging.getLevelName(level),
    )


def get_trade_logger() -> logging.Logger:
    """Return the dedicated trade audit logger.

    Use this logger for all order placements, fills, and position
    state changes to maintain a clean audit trail.
    """
    return logging.getLogger("trades")


def log_trade_analysis(
    logger: logging.Logger,
    action: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    balance_before: float,
    balance_after: float,
    pnl: float = 0,
    fees: float = 0,
    dca_level: int = 0,
    position_size: float = 0,
    avg_entry: float = 0,
    leverage: int = 0,
) -> None:
    """Log detailed trade analysis for strategy improvement.

    Args:
        logger: Trade logger instance.
        action: Action type (ENTRY, DCA, TP, SL, CLOSE).
        symbol: Trading pair.
        side: BUY or SELL.
        quantity: Order quantity.
        price: Execution price.
        balance_before: Balance before trade.
        balance_after: Balance after trade.
        pnl: Profit/loss from trade.
        fees: Trading fees.
        dca_level: Current DCA level (0 for initial entry).
        position_size: Total position size after trade.
        avg_entry: Average entry price.
        leverage: Leverage used.
    """
    logger.info(
        "TRADE | action=%s | symbol=%s | side=%s | qty=%.6f | price=%.2f | "
        "balance_before=%.2f | balance_after=%.2f | pnl=%.2f | fees=%.2f | "
        "dca_level=%d | position_size=%.6f | avg_entry=%.2f | leverage=%dx",
        action,
        symbol,
        side,
        quantity,
        price,
        balance_before,
        balance_after,
        pnl,
        fees,
        dca_level,
        position_size,
        avg_entry,
        leverage,
    )


def log_strategy_signal(
    logger: logging.Logger,
    signal_type: str,
    confidence: float,
    price: float,
    rsi: float | None,
    ema: float | None,
    volume: float,
    needs_approval: bool,
    reasoning: str,
) -> None:
    """Log strategy signal analysis for improvement.

    Args:
        logger: Trade logger instance.
        signal_type: LONG, SHORT, or HOLD.
        confidence: Signal confidence (0-1).
        price: Current price.
        rsi: RSI indicator value.
        ema: EMA indicator value.
        volume: Trading volume.
        needs_approval: Whether AI approval was needed.
        reasoning: Signal reasoning.
    """
    logger.info(
        "SIGNAL | type=%s | confidence=%.2f | price=%.2f | rsi=%s | ema=%s | "
        "volume=%.2f | needs_approval=%s | reasoning=%s",
        signal_type,
        confidence,
        price,
        f"{rsi:.2f}" if rsi else "N/A",
        f"{ema:.2f}" if ema else "N/A",
        volume,
        needs_approval,
        reasoning[:100],
    )


def log_position_health(
    logger: logging.Logger,
    symbol: str,
    position_size: float,
    entry_price: float,
    mark_price: float,
    pnl: float,
    pnl_pct: float,
    liquidation_price: float,
    leverage: int,
    margin_used: float,
    balance: float,
) -> None:
    """Log position health metrics for monitoring.

    Args:
        logger: Trade logger instance.
        symbol: Trading pair.
        position_size: Current position size.
        entry_price: Average entry price.
        mark_price: Current mark price.
        pnl: Unrealized PnL.
        pnl_pct: PnL percentage.
        liquidation_price: Liquidation price.
        leverage: Leverage used.
        margin_used: Margin used.
        balance: Available balance.
    """
    logger.info(
        "HEALTH | symbol=%s | position=%.6f | entry=%.2f | mark=%.2f | "
        "pnl=%.2f (%.2f%%) | liq=%.2f | lev=%dx | margin=%.2f | balance=%.2f",
        symbol,
        position_size,
        entry_price,
        mark_price,
        pnl,
        pnl_pct * 100,
        liquidation_price,
        leverage,
        margin_used,
        balance,
    )
