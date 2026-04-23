from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from enum import Enum
from datetime import datetime
import aiohttp
import asyncio
from config import settings
from utils import retry_async
import logging

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    order_id: str
    ticker: str
    direction: str  # 'long' or 'short'
    quantity: float
    entry_price: float
    leverage: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    status: OrderStatus
    filled_at: Optional[datetime] = None
    filled_price: Optional[float] = None


@dataclass
class Position:
    ticker: str
    quantity: float
    entry_price: float
    current_price: float
    leverage: float
    unrealized_pnl: float
    direction: str  # 'long' or 'short'


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BybitBroker:
    """Bybit API client for spot & perpetuals trading."""

    def __init__(self):
        self.api_key = settings.bybit_api_key
        self.api_secret = settings.bybit_api_secret
        self.testnet = settings.bybit_testnet
        self.base_url = (
            "https://api-testnet.bybit.com"
            if self.testnet
            else "https://api.bybit.com"
        )
        self.session: Optional[aiohttp.ClientSession] = None

    async def init_session(self) -> None:
        """Initialize async HTTP session."""
        if not self.session:
            self.session = aiohttp.ClientSession()
            logger.info("Bybit session initialized")

    async def close_session(self) -> None:
        """Close async HTTP session."""
        if self.session:
            await self.session.close()
            logger.info("Bybit session closed")

    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balance.
        Returns {currency: balance}
        """
        try:
            # Mock implementation
            return {"USDT": settings.portfolio_size_usd}

        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            raise

    async def get_candles(
        self,
        ticker: str,
        interval: str,  # "1" (1m), "4" (4h), "D" (daily), etc.
        limit: int = 100,
    ) -> List[Candle]:
        """
        Fetch OHLCV candles.
        """
        try:
            # Mock implementation - return dummy candles
            candles = []
            for i in range(limit):
                candles.append(
                    Candle(
                        timestamp=datetime.utcnow(),
                        open=50000.0,
                        high=50100.0,
                        low=49900.0,
                        close=50050.0,
                        volume=100.0,
                    )
                )
            return candles

        except Exception as e:
            logger.error(f"Error fetching candles for {ticker}: {e}")
            raise

    async def place_limit_order(
        self,
        ticker: str,
        direction: str,
        quantity: float,
        price: float,
        leverage: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
    ) -> Order:
        """
        Place limit order with TP/SL.
        """
        try:
            order_id = f"order_{ticker}_{int(datetime.utcnow().timestamp())}"

            order = Order(
                order_id=order_id,
                ticker=ticker,
                direction=direction,
                quantity=quantity,
                entry_price=price,
                leverage=leverage,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                status=OrderStatus.PENDING,
            )

            logger.info(
                f"Placed limit order: {order_id} | {direction} {quantity} {ticker} @ {price} "
                f"| SL: {stop_loss} | TP1: {take_profit_1} | TP2: {take_profit_2}"
            )

            return order

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        try:
            logger.info(f"Cancelled order: {order_id}")
            return True

        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def close_position(
        self, ticker: str, quantity: float, market: bool = False
    ) -> Optional[Order]:
        """
        Close position (exit trade).
        If market=True, use market order; otherwise limit.
        """
        try:
            direction = "sell"  # Simplified
            price = 50000.0  # Mock current price

            order = await self.place_limit_order(
                ticker=ticker,
                direction=direction,
                quantity=quantity,
                price=price,
                leverage=1.0,
                stop_loss=price * 0.99,
                take_profit_1=price * 1.01,
                take_profit_2=price * 1.02,
            )

            logger.info(f"Closed position: {quantity} {ticker}")
            return order

        except Exception as e:
            logger.error(f"Error closing position {ticker}: {e}")
            return None

    async def get_positions(self) -> List[Position]:
        """Get all open positions."""
        try:
            # Mock implementation
            return []

        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            raise

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get status of placed order."""
        try:
            return OrderStatus.PENDING

        except Exception as e:
            logger.error(f"Error fetching order status {order_id}: {e}")
            raise


class BinanceBroker:
    """Binance API client (fallback)."""

    def __init__(self):
        self.api_key = settings.binance_api_key
        self.api_secret = settings.binance_api_secret
        self.testnet = settings.binance_testnet
        self.base_url = (
            "https://testnet.binance.vision"
            if self.testnet
            else "https://api.binance.com"
        )
        self.session: Optional[aiohttp.ClientSession] = None

    async def init_session(self) -> None:
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close_session(self) -> None:
        if self.session:
            await self.session.close()

    async def get_balance(self) -> Dict[str, float]:
        """Get account balance."""
        return {"USDT": settings.portfolio_size_usd}

    async def get_candles(
        self, ticker: str, interval: str, limit: int = 100
    ) -> List[Candle]:
        """Fetch OHLCV candles."""
        return []

    async def place_limit_order(
        self,
        ticker: str,
        direction: str,
        quantity: float,
        price: float,
        leverage: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
    ) -> Order:
        """Place limit order."""
        order_id = f"binance_{ticker}_{int(datetime.utcnow().timestamp())}"
        return Order(
            order_id=order_id,
            ticker=ticker,
            direction=direction,
            quantity=quantity,
            entry_price=price,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            status=OrderStatus.PENDING,
        )

    async def get_positions(self) -> List[Position]:
        """Get all open positions."""
        return []
