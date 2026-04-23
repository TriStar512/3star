"""Broker abstraction: Bybit primary + Binance fallback + paper engine.

The paper broker simulates fills at the requested limit price and tracks
positions in-memory. Live brokers wrap the public REST endpoints (no
signing is required for candles and tickers, which is all we need for
signal generation). Actual order placement against a live exchange should
be wired in before enabling ``PAPER_TRADE=false``.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import aiohttp
import pandas as pd

from .config import Settings, get_settings
from .utils import async_retry, symbol_to_pair, utcnow

log = logging.getLogger(__name__)


# ----- Data types -----

@dataclass
class Candle:
    open_time: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Position:
    ticker: str
    direction: str  # "long" or "short"
    entry_price: float
    quantity: float
    leverage: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    opened_at: pd.Timestamp
    order_id: str
    tp1_hit: bool = False
    tp2_hit: bool = False
    closed: bool = False
    exit_price: Optional[float] = None
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: Optional[str] = None


@dataclass
class Order:
    id: str
    ticker: str
    direction: str
    quantity: float
    price: float
    leverage: float
    status: str = "filled"  # paper-mode assumes instant fill at limit
    timestamp: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.utcnow())


# ----- Bybit public market data -----

class BybitClient:
    """Read-only Bybit market data client (v5 public endpoints)."""

    INTERVAL_MAP = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}

    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.base_url = (
            "https://api-testnet.bybit.com" if settings.bybit_testnet else "https://api.bybit.com"
        )

    async def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        async with self.session.get(url, params=params, timeout=15) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if data.get("retCode") not in (0, None):
                raise RuntimeError(f"bybit error: {data.get('retMsg')}")
            return data

    async def get_candles(self, ticker: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        symbol = symbol_to_pair(ticker)
        interval = self.INTERVAL_MAP.get(timeframe, "15")
        data = await async_retry(
            self._get,
            "/v5/market/kline",
            {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit},
        )
        rows = data.get("result", {}).get("list", [])
        # bybit returns newest-first
        rows = list(reversed(rows))
        df = pd.DataFrame(
            rows,
            columns=["open_time", "open", "high", "low", "close", "volume", "turnover"],
        )
        if df.empty:
            return df
        df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df.set_index("open_time")

    async def get_ticker_price(self, ticker: str) -> float:
        symbol = symbol_to_pair(ticker)
        data = await async_retry(
            self._get, "/v5/market/tickers", {"category": "linear", "symbol": symbol}
        )
        items = data.get("result", {}).get("list", [])
        if not items:
            raise RuntimeError(f"no ticker for {symbol}")
        return float(items[0]["lastPrice"])

    async def get_funding_rate(self, ticker: str) -> float:
        symbol = symbol_to_pair(ticker)
        data = await async_retry(
            self._get, "/v5/market/tickers", {"category": "linear", "symbol": symbol}
        )
        items = data.get("result", {}).get("list", [])
        if not items:
            return 0.0
        return float(items[0].get("fundingRate", 0.0) or 0.0)


class BinanceClient:
    """Fallback: Binance public market data."""

    INTERVAL_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}

    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.base_url = (
            "https://testnet.binance.vision" if settings.binance_testnet else "https://api.binance.com"
        )

    async def _get(self, path: str, params: dict) -> list | dict:
        url = f"{self.base_url}{path}"
        async with self.session.get(url, params=params, timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_candles(self, ticker: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        symbol = symbol_to_pair(ticker)
        interval = self.INTERVAL_MAP.get(timeframe, "15m")
        rows = await async_retry(
            self._get,
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )
        df = pd.DataFrame(
            rows,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "tb_base", "tb_quote", "ignore",
            ],
        )
        if df.empty:
            return df
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df[["open_time", "open", "high", "low", "close", "volume"]].set_index("open_time")

    async def get_ticker_price(self, ticker: str) -> float:
        symbol = symbol_to_pair(ticker)
        data = await async_retry(self._get, "/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    async def get_funding_rate(self, ticker: str) -> float:
        # spot doesn't have funding; return 0
        return 0.0


# ----- Paper broker -----

class PaperBroker:
    """In-memory broker: fills at limit price, tracks positions, no fees."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cash: float = settings.portfolio_size_usd
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []

    def available_margin(self) -> float:
        deployed = sum(
            (p.entry_price * p.quantity) / max(p.leverage, 1.0)
            for p in self.positions.values()
        )
        return max(0.0, self.cash - deployed)

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
        if ticker in self.positions:
            raise RuntimeError(f"already have open position on {ticker}")
        order_id = str(uuid.uuid4())
        pos = Position(
            ticker=ticker,
            direction=direction,
            entry_price=price,
            quantity=quantity,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            opened_at=pd.Timestamp.utcnow(),
            order_id=order_id,
        )
        self.positions[ticker] = pos
        log.info(
            "[paper] opened %s %s qty=%.6f @ %.4f lev=%.2fx SL=%.4f TP1=%.4f TP2=%.4f",
            direction.upper(), ticker, quantity, price, leverage,
            stop_loss, take_profit_1, take_profit_2,
        )
        return Order(
            id=order_id, ticker=ticker, direction=direction,
            quantity=quantity, price=price, leverage=leverage,
        )

    def mark_to_market(self, ticker: str, price: float) -> Optional[str]:
        """Check SL/TP for a ticker; return an exit reason if triggered."""
        pos = self.positions.get(ticker)
        if not pos or pos.closed:
            return None
        if pos.direction == "long":
            if price <= pos.stop_loss:
                self._close(pos, price, "sl")
                return "sl"
            if not pos.tp2_hit and price >= pos.take_profit_2:
                self._close(pos, price, "tp2")
                return "tp2"
            if not pos.tp1_hit and price >= pos.take_profit_1:
                pos.tp1_hit = True
                return "tp1_partial"
        else:  # short
            if price >= pos.stop_loss:
                self._close(pos, price, "sl")
                return "sl"
            if not pos.tp2_hit and price <= pos.take_profit_2:
                self._close(pos, price, "tp2")
                return "tp2"
            if not pos.tp1_hit and price <= pos.take_profit_1:
                pos.tp1_hit = True
                return "tp1_partial"
        return None

    def force_close(self, ticker: str, price: float, reason: str) -> Optional[Position]:
        pos = self.positions.get(ticker)
        if not pos or pos.closed:
            return None
        self._close(pos, price, reason)
        return pos

    def _close(self, pos: Position, price: float, reason: str) -> None:
        pnl = (price - pos.entry_price) * pos.quantity
        if pos.direction == "short":
            pnl = -pnl
        pos.exit_price = price
        pos.exit_time = pd.Timestamp.utcnow()
        pos.exit_reason = reason
        pos.closed = True
        self.cash += pnl
        self.closed_positions.append(pos)
        del self.positions[pos.ticker]
        log.info(
            "[paper] closed %s %s @ %.4f reason=%s pnl=$%.2f",
            pos.direction.upper(), pos.ticker, price, reason, pnl,
        )


# ----- Broker facade -----

class Broker:
    """Single entry-point used by the rest of the bot."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.session: Optional[aiohttp.ClientSession] = None
        self.primary: BybitClient | BinanceClient | None = None
        self.fallback: BybitClient | BinanceClient | None = None
        self.paper = PaperBroker(self.settings)

    async def __aenter__(self) -> "Broker":
        self.session = aiohttp.ClientSession()
        if self.settings.primary_broker == "bybit":
            self.primary = BybitClient(self.settings, self.session)
            self.fallback = BinanceClient(self.settings, self.session)
        else:
            self.primary = BinanceClient(self.settings, self.session)
            self.fallback = BybitClient(self.settings, self.session)
        return self

    async def __aexit__(self, *exc) -> None:
        if self.session:
            await self.session.close()

    async def get_candles(self, ticker: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        assert self.primary and self.fallback
        try:
            return await self.primary.get_candles(ticker, timeframe, limit)
        except Exception as exc:  # noqa: BLE001
            log.warning("primary broker candles failed, falling back: %s", exc)
            return await self.fallback.get_candles(ticker, timeframe, limit)

    async def get_price(self, ticker: str) -> float:
        assert self.primary and self.fallback
        try:
            return await self.primary.get_ticker_price(ticker)
        except Exception as exc:  # noqa: BLE001
            log.warning("primary broker price failed, falling back: %s", exc)
            return await self.fallback.get_ticker_price(ticker)

    async def get_funding_rate(self, ticker: str) -> float:
        assert self.primary
        try:
            return await self.primary.get_funding_rate(ticker)
        except Exception:
            return 0.0

    # --- order routing ---
    async def place_limit_order(self, **kwargs) -> Order:
        if self.settings.paper_trade:
            return await self.paper.place_limit_order(**kwargs)
        raise NotImplementedError(
            "Live order placement not wired. Set PAPER_TRADE=true or add signed endpoints."
        )

    def positions(self) -> Dict[str, Position]:
        return self.paper.positions if self.settings.paper_trade else {}

    def closed_positions(self) -> List[Position]:
        return self.paper.closed_positions if self.settings.paper_trade else []

    def available_margin(self) -> float:
        return self.paper.available_margin() if self.settings.paper_trade else 0.0

    def cash(self) -> float:
        return self.paper.cash if self.settings.paper_trade else 0.0

    def mark_to_market(self, ticker: str, price: float) -> Optional[str]:
        if not self.settings.paper_trade:
            return None
        return self.paper.mark_to_market(ticker, price)

    def force_close(self, ticker: str, price: float, reason: str) -> Optional[Position]:
        if not self.settings.paper_trade:
            return None
        return self.paper.force_close(ticker, price, reason)
