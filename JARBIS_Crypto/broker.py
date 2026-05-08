"""Broker abstraction: Hyperliquid primary + Bybit/Binance data fallback + paper engine.

Execution venue is Hyperliquid — a DEX on its own EVM L1, self-custodied
via Metamask signing. No KYC. Public REST (``/info``) needs no auth and
is used for candles / ticker context / funding / max-leverage metadata.

Bybit and Binance remain wired only as read-only fallbacks for market
data redundancy (same public endpoints as before, no keys required).

Two execution backends:
  - PaperBroker (in-memory) — used whenever ``PAPER_TRADE=true``; fills
    at the limit price and tracks SL/TP via ``mark_to_market``.
  - HyperliquidExchange (signed) — used when ``PAPER_TRADE=false``;
    places a limit entry plus three reduce-only trigger legs (SL, TP1
    50%, TP2 50%) on the user's Metamask-derived account. Live positions
    are read from Hyperliquid's ``user_state`` so the dashboard reflects
    on-chain truth instead of a local cache.
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


# ----- Hyperliquid public market data -----

class HyperliquidClient:
    """Read-only Hyperliquid ``/info`` client (no auth required).

    Public info endpoint accepts JSON POSTs with a ``type`` discriminator.
    All candles, mark prices, funding rates, and universe metadata flow
    through this single URL. Order placement is deferred until the
    signing layer is wired in (same pattern as the old Bybit live stub).
    """

    INTERVAL_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}

    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.base_url = settings.hl_api_url.rstrip("/")
        # cached universe / leverage caps — refreshed on first use
        self._universe: Optional[list] = None
        self._asset_ctxs: Optional[list] = None
        self._index_by_coin: Dict[str, int] = {}

    async def _post(self, body: dict) -> dict | list:
        url = f"{self.base_url}/info"
        async with self.session.post(url, json=body, timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _ensure_meta(self) -> None:
        if self._universe is not None and self._asset_ctxs is not None:
            return
        data = await async_retry(self._post, {"type": "metaAndAssetCtxs"})
        meta, ctxs = data[0], data[1]
        self._universe = meta.get("universe", [])
        self._asset_ctxs = ctxs
        self._index_by_coin = {u["name"].upper(): i for i, u in enumerate(self._universe)}

    async def _refresh_ctxs(self) -> None:
        """Re-pull only the changing asset contexts; universe is stable."""
        data = await async_retry(self._post, {"type": "metaAndAssetCtxs"})
        self._universe = data[0].get("universe", self._universe)
        self._asset_ctxs = data[1]
        self._index_by_coin = {u["name"].upper(): i for i, u in enumerate(self._universe or [])}

    async def get_candles(self, ticker: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        coin = ticker.upper()
        interval = self.INTERVAL_MAP.get(timeframe, "15m")
        interval_ms = _interval_to_ms(interval)
        end_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
        start_ms = end_ms - interval_ms * limit
        rows = await async_retry(
            self._post,
            {
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms},
            },
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            [
                {
                    "open_time": r["t"],
                    "open": float(r["o"]),
                    "high": float(r["h"]),
                    "low": float(r["l"]),
                    "close": float(r["c"]),
                    "volume": float(r.get("v", 0.0)),
                }
                for r in rows
            ]
        )
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        return df.set_index("open_time")

    async def get_ticker_price(self, ticker: str) -> float:
        await self._refresh_ctxs()
        coin = ticker.upper()
        idx = self._index_by_coin.get(coin)
        if idx is None or self._asset_ctxs is None:
            raise RuntimeError(f"hyperliquid: no such coin {coin}")
        ctx = self._asset_ctxs[idx]
        price = ctx.get("markPx") or ctx.get("midPx") or ctx.get("oraclePx")
        if price is None:
            raise RuntimeError(f"hyperliquid: no mark price for {coin}")
        return float(price)

    async def get_funding_rate(self, ticker: str) -> float:
        await self._refresh_ctxs()
        coin = ticker.upper()
        idx = self._index_by_coin.get(coin)
        if idx is None or self._asset_ctxs is None:
            return 0.0
        return float(self._asset_ctxs[idx].get("funding", 0.0) or 0.0)

    async def get_max_leverage(self, ticker: str) -> float:
        await self._ensure_meta()
        coin = ticker.upper()
        idx = self._index_by_coin.get(coin)
        if idx is None or self._universe is None:
            return 0.0
        return float(self._universe[idx].get("maxLeverage", 0.0) or 0.0)


def _interval_to_ms(interval: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    return int(interval[:-1]) * units.get(interval[-1], 60_000)


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

_DataClient = "HyperliquidClient | BybitClient | BinanceClient"


class Broker:
    """Single entry-point used by the rest of the bot.

    Execution venue = Hyperliquid. Bybit + Binance sit behind it only as
    read-only data fallbacks when the ``/info`` endpoint hiccups.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.session: Optional[aiohttp.ClientSession] = None
        self.primary: Optional[_DataClient] = None
        self.fallbacks: List[_DataClient] = []
        self.paper = PaperBroker(self.settings)
        self.venue_name: str = self.settings.primary_broker
        # Lazy: only constructed when paper_trade=False AND keys present.
        self.live_exchange = None  # type: Optional["HyperliquidExchange"]
        self._live_state_cache: dict = {}
        self._live_open_orders: Dict[str, dict] = {}

    async def __aenter__(self) -> "Broker":
        self.session = aiohttp.ClientSession()
        hl = HyperliquidClient(self.settings, self.session)
        by = BybitClient(self.settings, self.session)
        bn = BinanceClient(self.settings, self.session)
        order = {
            "hyperliquid": (hl, [by, bn]),
            "bybit":       (by, [hl, bn]),
            "binance":     (bn, [hl, by]),
        }
        self.primary, self.fallbacks = order[self.settings.primary_broker]
        if not self.settings.paper_trade:
            self._init_live_exchange()
        return self

    async def __aexit__(self, *exc) -> None:
        if self.session:
            await self.session.close()

    def _init_live_exchange(self) -> None:
        """Construct the Hyperliquid signed-order client.

        Only called when ``paper_trade=False``. Imports are local so that
        paper-only deployments don't pay the cost of pulling in
        ``hyperliquid-python-sdk`` / ``eth_account``.
        """
        from .hyperliquid_exchange import HyperliquidExchange
        if not self.settings.hl_wallet_address or not self.settings.hl_private_key:
            raise RuntimeError(
                "PAPER_TRADE=false but HL_WALLET_ADDRESS / HL_PRIVATE_KEY are not set"
            )
        self.live_exchange = HyperliquidExchange(
            wallet_address=self.settings.hl_wallet_address,
            private_key=self.settings.hl_private_key,
            testnet=self.settings.hl_testnet,
        )
        log.info(
            "live exchange ready (network=%s, address=%s)",
            "TESTNET" if self.settings.hl_testnet else "MAINNET",
            self.settings.hl_wallet_address,
        )

    async def _try_chain(self, fn_name: str, *args, **kwargs):
        assert self.primary
        clients = [self.primary, *self.fallbacks]
        last_exc: Exception | None = None
        for c in clients:
            try:
                return await getattr(c, fn_name)(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s on %s failed, trying next: %s",
                            fn_name, type(c).__name__, exc)
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def get_candles(self, ticker: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        return await self._try_chain("get_candles", ticker, timeframe, limit)

    async def get_price(self, ticker: str) -> float:
        return await self._try_chain("get_ticker_price", ticker)

    async def get_funding_rate(self, ticker: str) -> float:
        try:
            return await self._try_chain("get_funding_rate", ticker)
        except Exception:
            return 0.0

    async def get_max_leverage(self, ticker: str) -> float:
        """Only Hyperliquid exposes a universe-level max leverage today."""
        if isinstance(self.primary, HyperliquidClient):
            try:
                return await self.primary.get_max_leverage(ticker)
            except Exception:
                return 0.0
        return 0.0

    # --- order routing ---
    async def place_limit_order(self, **kwargs) -> Order:
        if self.settings.paper_trade:
            return await self.paper.place_limit_order(**kwargs)
        if self.live_exchange is None:
            raise RuntimeError("live_exchange not initialized — call _init_live_exchange()")

        ticker = kwargs["ticker"].upper()
        result = await self.live_exchange.place_bracketed_order(
            coin=ticker,
            is_buy=(kwargs["direction"] == "long"),
            qty=kwargs["quantity"],
            entry_px=kwargs["price"],
            sl_px=kwargs["stop_loss"],
            tp1_px=kwargs["take_profit_1"],
            tp2_px=kwargs["take_profit_2"],
            leverage=int(round(kwargs["leverage"])),
        )
        if not result.ok:
            raise RuntimeError(f"live order failed: {result.error}")

        # Track the bracket so we can cancel it on emergency / manual close.
        self._live_open_orders[ticker] = {
            "entry_oid": result.entry_oid,
            "sl_oid":    result.sl_oid,
            "tp1_oid":   result.tp1_oid,
            "tp2_oid":   result.tp2_oid,
            "direction": kwargs["direction"],
            "leverage":  kwargs["leverage"],
            "stop_loss": kwargs["stop_loss"],
            "tp1":       kwargs["take_profit_1"],
            "tp2":       kwargs["take_profit_2"],
        }
        log.info("[live] bracket placed for %s: entry=%s sl=%s tp1=%s tp2=%s",
                 ticker, result.entry_oid, result.sl_oid, result.tp1_oid, result.tp2_oid)

        return Order(
            id=str(result.entry_oid) if result.entry_oid else f"hl-{ticker}",
            ticker=ticker,
            direction=kwargs["direction"],
            quantity=kwargs["quantity"],
            price=kwargs["price"],
            leverage=kwargs["leverage"],
        )

    async def emergency_close_live(self, ticker: str) -> None:
        """Cancel the bracket and market-close any open position on ``ticker``."""
        if self.live_exchange is None:
            return
        await self.live_exchange.market_close(ticker.upper())
        self._live_open_orders.pop(ticker.upper(), None)

    # --- live-state refresh (called from the asyncio loop) ---
    async def refresh_live_state(self) -> None:
        """Pull the latest balance + positions from Hyperliquid."""
        if self.settings.paper_trade or self.live_exchange is None:
            return
        try:
            self._live_state_cache = await self.live_exchange.get_balance_and_positions()
        except Exception as exc:  # noqa: BLE001
            log.warning("live state refresh failed: %s", exc)

    # --- accessors used by the rest of the bot + dashboard ---

    def positions(self) -> Dict[str, Position]:
        if self.settings.paper_trade:
            return self.paper.positions
        # Synthesize Position objects from the cached live state.
        out: Dict[str, Position] = {}
        bracket_by_coin = self._live_open_orders
        for p in self._live_state_cache.get("positions", []) or []:
            coin = (p.get("coin") or "").upper()
            if not coin:
                continue
            size = float(p.get("size") or 0.0)
            if size == 0:
                continue
            bracket = bracket_by_coin.get(coin, {})
            out[coin] = Position(
                ticker=coin,
                direction="long" if size > 0 else "short",
                entry_price=float(p.get("entry_price") or 0.0),
                quantity=abs(size),
                leverage=float(p.get("leverage") or bracket.get("leverage") or 1.0),
                stop_loss=float(bracket.get("stop_loss") or 0.0),
                take_profit_1=float(bracket.get("tp1") or 0.0),
                take_profit_2=float(bracket.get("tp2") or 0.0),
                opened_at=pd.Timestamp.utcnow(),
                order_id=str(bracket.get("entry_oid") or f"hl-{coin}"),
            )
        return out

    def closed_positions(self) -> List[Position]:
        # Live trade history isn't synthesized here; the SQLite log is the
        # source of truth for closed trades regardless of mode.
        return self.paper.closed_positions

    def available_margin(self) -> float:
        if self.settings.paper_trade:
            return self.paper.available_margin()
        return float(self._live_state_cache.get("withdrawable") or 0.0)

    def cash(self) -> float:
        if self.settings.paper_trade:
            return self.paper.cash
        return float(self._live_state_cache.get("account_value") or 0.0)

    def mark_to_market(self, ticker: str, price: float) -> Optional[str]:
        if not self.settings.paper_trade:
            return None
        return self.paper.mark_to_market(ticker, price)

    def force_close(self, ticker: str, price: float, reason: str) -> Optional[Position]:
        if not self.settings.paper_trade:
            return None
        return self.paper.force_close(ticker, price, reason)
