"""Broker API integration (Bybit primary, Binance fallback)."""

import logging
import aiohttp
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """Order representation."""
    order_id: str
    ticker: str
    direction: str  # 'long' or 'short'
    quantity: float
    entry_price: float
    leverage: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    status: str  # 'pending', 'filled', 'partially_filled', 'cancelled'
    created_at: datetime


@dataclass
class Position:
    """Open position."""
    ticker: str
    direction: str  # 'long' or 'short'
    quantity: float
    entry_price: float
    current_price: float
    leverage: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


class BrokerClient:
    """Base broker client interface."""

    async def get_balance(self) -> float:
        """Get account balance in USD."""
        raise NotImplementedError

    async def get_positions(self) -> List[Position]:
        """Get open positions."""
        raise NotImplementedError

    async def get_price(self, ticker: str) -> float:
        """Get current price."""
        raise NotImplementedError

    async def get_candles(
        self,
        ticker: str,
        timeframe: str,
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        Get OHLCV candles.

        Args:
            ticker: Ticker symbol (e.g., "BTC", "ETH")
            timeframe: Timeframe (e.g., "4h", "1h", "15m")
            limit: Number of candles to fetch

        Returns:
            DataFrame with columns: [timestamp, open, high, low, close, volume]
        """
        raise NotImplementedError

    async def place_limit_order(
        self,
        ticker: str,
        direction: str,
        quantity: float,
        entry_price: float,
        leverage: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
    ) -> Order:
        """Place limit order with stops and takes."""
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order by ID."""
        raise NotImplementedError

    async def close_position(self, ticker: str) -> bool:
        """Close position (market order)."""
        raise NotImplementedError


class BybitClient(BrokerClient):
    """Bybit API client."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.base_url = (
            "https://api-testnet.bybit.com"
            if testnet
            else "https://api.bybit.com"
        )
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request to Bybit API."""
        if not self.session:
            raise RuntimeError("Session not initialized")

        url = f"{self.base_url}{endpoint}"
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            async with self.session.request(
                method, url, params=params, json=data, headers=headers
            ) as response:
                result = await response.json()
                if result.get("retCode") != 0:
                    logger.error(f"API error: {result.get('retMsg')}")
                return result
        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            raise

    async def get_balance(self) -> float:
        """Get account balance."""
        try:
            result = await self._request("GET", "/v5/account/wallet-balance")
            if result.get("retCode") == 0:
                # Bybit returns multiple account types, get total
                accounts = result.get("result", {}).get("list", [])
                if accounts:
                    # Sum USD and stablecoin balances
                    balance = 0
                    for coin in accounts[0].get("coin", []):
                        if coin.get("coin") in ["USDT", "USDC", "USD"]:
                            balance += float(coin.get("walletBalance", 0))
                    return balance
        except Exception as e:
            logger.error(f"Failed to get balance: {str(e)}")

        return 0.0

    async def get_price(self, ticker: str) -> float:
        """Get current price."""
        try:
            result = await self._request(
                "GET",
                "/v5/market/tickers",
                params={"category": "linear", "symbol": f"{ticker}USDT"},
            )
            if result.get("retCode") == 0:
                tickers = result.get("result", {}).get("list", [])
                if tickers:
                    return float(tickers[0].get("lastPrice", 0))
        except Exception as e:
            logger.error(f"Failed to get price for {ticker}: {str(e)}")

        return 0.0

    async def get_candles(
        self,
        ticker: str,
        timeframe: str,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Get OHLCV candles."""
        try:
            # Map timeframe to Bybit format
            tf_map = {
                "1m": "1", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "D", "1w": "W"
            }
            tf_param = tf_map.get(timeframe, "60")

            result = await self._request(
                "GET",
                "/v5/market/kline",
                params={
                    "category": "linear",
                    "symbol": f"{ticker}USDT",
                    "interval": tf_param,
                    "limit": min(limit, 200),
                },
            )

            if result.get("retCode") == 0:
                candles = result.get("result", {}).get("list", [])
                if candles:
                    # Reverse to get oldest first
                    candles.reverse()
                    df = pd.DataFrame(candles)
                    df.columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
                    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
                    df[["open", "high", "low", "close", "volume"]] = df[
                        ["open", "high", "low", "close", "volume"]
                    ].astype(float)
                    return df[["timestamp", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.error(f"Failed to get candles for {ticker}: {str(e)}")

        return pd.DataFrame()

    async def get_positions(self) -> List[Position]:
        """Get open positions."""
        try:
            result = await self._request(
                "GET",
                "/v5/position/list",
                params={"category": "linear"},
            )

            positions = []
            if result.get("retCode") == 0:
                for pos_data in result.get("result", {}).get("list", []):
                    if float(pos_data.get("size", 0)) > 0:
                        symbol = pos_data.get("symbol", "")
                        ticker = symbol.replace("USDT", "")
                        direction = "long" if pos_data.get("side") == "Buy" else "short"

                        position = Position(
                            ticker=ticker,
                            direction=direction,
                            quantity=float(pos_data.get("size", 0)),
                            entry_price=float(pos_data.get("avgPrice", 0)),
                            current_price=float(pos_data.get("markPrice", 0)),
                            leverage=float(pos_data.get("leverage", 1)),
                            unrealized_pnl=float(pos_data.get("unrealizedPnl", 0)),
                            unrealized_pnl_pct=float(pos_data.get("unrealizedPnlPct", 0)),
                        )
                        positions.append(position)

            return positions
        except Exception as e:
            logger.error(f"Failed to get positions: {str(e)}")

        return []

    async def place_limit_order(
        self,
        ticker: str,
        direction: str,
        quantity: float,
        entry_price: float,
        leverage: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
    ) -> Order:
        """Place limit order with stops and takes."""
        try:
            side = "Buy" if direction == "long" else "Sell"

            order_data = {
                "category": "linear",
                "symbol": f"{ticker}USDT",
                "side": side,
                "orderType": "Limit",
                "qty": str(quantity),
                "price": str(entry_price),
                "leverage": str(leverage),
                "stopLoss": str(stop_loss),
                "takeProfit": str(take_profit_1),  # TP1
                "positionIdx": 0,
                "timeInForce": "GTC",
            }

            result = await self._request("POST", "/v5/order/create", data=order_data)

            if result.get("retCode") == 0:
                order_id = result.get("result", {}).get("orderId", "")
                order = Order(
                    order_id=order_id,
                    ticker=ticker,
                    direction=direction,
                    quantity=quantity,
                    entry_price=entry_price,
                    leverage=leverage,
                    stop_loss=stop_loss,
                    take_profit_1=take_profit_1,
                    take_profit_2=take_profit_2,
                    status="pending",
                    created_at=datetime.utcnow(),
                )
                logger.info(f"Placed order {order_id}: {direction.upper()} {quantity} {ticker} @ {entry_price}")
                return order

        except Exception as e:
            logger.error(f"Failed to place order: {str(e)}")

        return None

    async def close_position(self, ticker: str) -> bool:
        """Close position (market order)."""
        try:
            positions = await self.get_positions()
            pos = next((p for p in positions if p.ticker == ticker), None)

            if not pos:
                logger.warning(f"No position for {ticker}")
                return False

            # Close with market order
            side = "Sell" if pos.direction == "long" else "Buy"
            order_data = {
                "category": "linear",
                "symbol": f"{ticker}USDT",
                "side": side,
                "orderType": "Market",
                "qty": str(pos.quantity),
                "positionIdx": 0,
            }

            result = await self._request("POST", "/v5/order/create", data=order_data)

            if result.get("retCode") == 0:
                logger.info(f"Closed position: {ticker}")
                return True

        except Exception as e:
            logger.error(f"Failed to close position: {str(e)}")

        return False

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        try:
            result = await self._request(
                "POST",
                "/v5/order/cancel",
                data={"category": "linear", "orderId": order_id},
            )

            if result.get("retCode") == 0:
                logger.info(f"Cancelled order: {order_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to cancel order: {str(e)}")

        return False


class BinanceClient(BrokerClient):
    """Binance API client (fallback)."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.base_url = (
            "https://testnet.binancefuture.com"
            if testnet
            else "https://fapi.binance.com"
        )
        self.session: Optional[aiohttp.ClientSession] = None
        logger.info("BinanceClient initialized (fallback mode)")

    async def get_balance(self) -> float:
        """Placeholder for Binance balance."""
        return 0.0

    async def get_price(self, ticker: str) -> float:
        """Placeholder for Binance price."""
        return 0.0

    async def get_candles(
        self, ticker: str, timeframe: str, limit: int = 100
    ) -> pd.DataFrame:
        """Placeholder for Binance candles."""
        return pd.DataFrame()

    async def get_positions(self) -> List[Position]:
        """Placeholder for Binance positions."""
        return []

    async def place_limit_order(
        self,
        ticker: str,
        direction: str,
        quantity: float,
        entry_price: float,
        leverage: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
    ) -> Order:
        """Placeholder for Binance order placement."""
        return None

    async def close_position(self, ticker: str) -> bool:
        """Placeholder for Binance position close."""
        return False

    async def cancel_order(self, order_id: str) -> bool:
        """Placeholder for Binance order cancellation."""
        return False
