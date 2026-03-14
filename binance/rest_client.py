"""Binance Futures REST client with HMAC-SHA256 signed requests.

All API calls use retry logic with exponential backoff.
Targets testnet by default (config.BINANCE_REST_BASE).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any, cast
from urllib.parse import urlencode

import aiohttp

import config

logger = logging.getLogger(__name__)

# Retry settings
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 1.0


class BinanceAPIError(Exception):
    """Raised when Binance API returns an error response."""

    def __init__(self, status: int, code: int, msg: str) -> None:
        self.status = status
        self.code = code
        self.msg = msg
        super().__init__(f"Binance API error {code}: {msg} (HTTP {status})")


class BinanceRestClient:
    """HTTP client for Binance USDT-M Futures REST API.

    Handles request signing (HMAC SHA256), retries with exponential
    backoff, and provides methods for account setup and order management.

    Args:
        api_key: Binance API key.
        api_secret: Binance API secret.
    """

    def __init__(
        self,
        api_key: str = config.BINANCE_API_KEY,
        api_secret: str = config.BINANCE_API_SECRET,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = config.BINANCE_REST_BASE
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        """Initialize the HTTP session."""
        self._session = aiohttp.ClientSession(
            headers={"X-MBX-APIKEY": self._api_key},
        )
        logger.info("REST client initialized — base=%s", self._base_url)

    async def stop(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("REST client closed")

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add timestamp and HMAC signature to request parameters.

        Args:
            params: Request parameters to sign.

        Returns:
            Signed parameters with timestamp and signature.
        """
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = True,
    ) -> Any:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: API endpoint path (e.g. "/fapi/v1/order").
            params: Query/body parameters.
            signed: Whether to sign the request with HMAC.

        Returns:
            Parsed JSON response.

        Raises:
            BinanceAPIError: On API error response.
            RuntimeError: If session is not started.
        """
        if not self._session:
            raise RuntimeError("REST client not started — call start() first")

        if params is None:
            params = {}

        if signed:
            params = self._sign(params)

        url = f"{self._base_url}{path}"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if method in ("GET", "DELETE"):
                    resp = await self._session.request(method, url, params=params)
                else:
                    resp = await self._session.request(method, url, data=params)

                data = await resp.json()

                if resp.status >= 400:
                    code = data.get("code", resp.status)
                    msg = data.get("msg", str(data))
                    logger.error(
                        "%s %s failed: HTTP %d code=%s msg=%s | params=%s",
                        method,
                        path,
                        resp.status,
                        code,
                        msg,
                        {k: v for k, v in params.items() if k != "signature"},
                    )
                    # Don't retry client errors (4xx) except rate limits
                    if resp.status == 429:
                        wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                        logger.warning("Rate limited, retry in %.1fs...", wait)
                        await asyncio.sleep(wait)
                        continue
                    raise BinanceAPIError(resp.status, code, msg)

                return data

            except aiohttp.ClientError as e:
                logger.error(
                    "%s %s network error (attempt %d/%d): %s",
                    method,
                    path,
                    attempt,
                    MAX_RETRIES,
                    e,
                )
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                    await asyncio.sleep(wait)
                else:
                    raise

        raise RuntimeError(f"Exhausted {MAX_RETRIES} retries for {method} {path}")

    # --- Account Setup (run once at startup) ---

    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        """Set leverage for a symbol.

        POST /fapi/v1/leverage

        Args:
            symbol: Trading pair (e.g. "BTCUSDT").
            leverage: Leverage value (e.g. 3).

        Returns:
            API response with leverage and maxNotionalValue.
        """
        result = await self._request(
            "POST",
            "/fapi/v1/leverage",
            {
                "symbol": symbol,
                "leverage": leverage,
            },
        )
        logger.info("Leverage set: symbol=%s leverage=%d", symbol, leverage)
        return cast(dict[str, Any], result)

    async def set_margin_type(self, symbol: str, margin_type: str) -> dict[str, Any]:
        """Set margin type for a symbol.

        POST /fapi/v1/marginType

        Args:
            symbol: Trading pair (e.g. "BTCUSDT").
            margin_type: Margin type ("ISOLATED" or "CROSSED").

        Returns:
            API response.
        """
        try:
            result = await self._request(
                "POST",
                "/fapi/v1/marginType",
                {
                    "symbol": symbol,
                    "marginType": margin_type,
                },
            )
            logger.info("Margin type set: symbol=%s type=%s", symbol, margin_type)
            return cast(dict[str, Any], result)
        except BinanceAPIError as e:
            # -4046 = "No need to change margin type" — already set
            if e.code == -4046:
                logger.info("Margin type already %s for %s", margin_type, symbol)
                return {"symbol": symbol, "marginType": margin_type}
            raise

    # --- Account Info ---

    async def get_balance(self) -> list[dict[str, Any]]:
        """Get account balance.

        GET /fapi/v2/balance

        Returns:
            List of asset balances.
        """
        return cast(
            list[dict[str, Any]], await self._request("GET", "/fapi/v2/balance")
        )

    async def get_usdt_balance(self) -> float:
        """Get available margin balance (USDT or USDC).

        Checks USDT first, falls back to USDC.

        Returns:
            Available balance as float.
        """
        balances = await self.get_balance()
        for asset in ("USDT", "USDC"):
            for b in balances:
                if b.get("asset") == asset:
                    bal = float(b.get("availableBalance", 0))
                    if bal > 0:
                        return bal
        return 0.0

    async def get_position_risk(self, symbol: str) -> dict[str, Any]:
        """Get current position risk information.

        GET /fapi/v2/positionRisk

        Args:
            symbol: Trading pair (e.g. "BTCUSDT").

        Returns:
            Position risk data including liquidation price.
        """
        result = await self._request(
            "GET",
            "/fapi/v2/positionRisk",
            {
                "symbol": symbol,
            },
        )
        # API returns a list, find matching symbol
        if isinstance(result, list):
            for pos in result:
                if isinstance(pos, dict) and pos.get("symbol") == symbol:
                    return pos
            return {"symbol": symbol, "positionAmt": "0", "liquidationPrice": "0"}
        return cast(dict[str, Any], result)

    # --- Order Management ---

    async def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        """Place an order on Binance Futures.

        POST /fapi/v1/order

        Args:
            params: Order parameters (symbol, side, type, quantity, etc.).

        Returns:
            API response with orderId, status, etc.

        Raises:
            BinanceAPIError: On order rejection.
        """
        result: dict[str, Any] = cast(
            dict[str, Any],
            await self._request("POST", "/fapi/v1/order", params),
        )
        logger.info(
            "Order placed: orderId=%s symbol=%s side=%s type=%s qty=%s",
            result.get("orderId"),
            result.get("symbol"),
            result.get("side"),
            result.get("type"),
            result.get("origQty"),
        )
        return result

    async def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """Cancel an individual order.

        DELETE /fapi/v1/order

        Args:
            symbol: Trading pair.
            order_id: Order ID to cancel.

        Returns:
            API response.
        """
        result = await self._request(
            "DELETE",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "orderId": order_id,
            },
        )
        logger.info("Order cancelled: orderId=%d symbol=%s", order_id, symbol)
        return cast(dict[str, Any], result)

    async def cancel_all_orders(self, symbol: str) -> dict[str, Any]:
        """Cancel all open orders for a symbol (emergency).

        DELETE /fapi/v1/allOpenOrders

        Args:
            symbol: Trading pair.

        Returns:
            API response.
        """
        result = await self._request(
            "DELETE",
            "/fapi/v1/allOpenOrders",
            {
                "symbol": symbol,
            },
        )
        logger.warning("All orders cancelled for %s", symbol)
        return cast(dict[str, Any], result)

    # --- Listen Key (User Data Stream) ---

    async def get_listen_key(self) -> str:
        """Create a listen key for user data stream.

        POST /fapi/v1/listenKey

        Returns:
            Listen key string.
        """
        result = await self._request("POST", "/fapi/v1/listenKey", signed=False)
        key: str = result.get("listenKey", "") if isinstance(result, dict) else ""
        logger.info("Listen key obtained: %s...", key[:8] if key else "empty")
        return key

    async def renew_listen_key(self) -> dict[str, Any]:
        """Renew (keep-alive) the listen key.

        PUT /fapi/v1/listenKey

        Returns:
            API response.
        """
        result = cast(
            dict[str, Any],
            await self._request("PUT", "/fapi/v1/listenKey", signed=False),
        )
        logger.debug("Listen key renewed")
        return result
