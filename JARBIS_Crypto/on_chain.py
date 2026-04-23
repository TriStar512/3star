"""On-chain / smart-money signals (Nansen, Glassnode, Santiment).

All providers are optional. When no keys are configured the engine
returns a neutral signal. Live endpoints are best-effort and errors
degrade gracefully to ``OnChainSignal(bullish=False, source="none")``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from .config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class OnChainSignal:
    ticker: str
    bullish: bool
    label: str = "none"  # smart_money_buy, whale_withdraw, exchange_inflow, none
    source: str = "none"
    detail: str = ""


class OnChainEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "OnChainEngine":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session:
            await self._session.close()

    async def check(self, ticker: str) -> OnChainSignal:
        if not self.settings.enable_on_chain_signals:
            return OnChainSignal(ticker=ticker, bullish=False)

        # Providers tried in order; first bullish response wins.
        sig = await self._santiment_flow(ticker)
        if sig.bullish:
            return sig
        sig = await self._glassnode_netflow(ticker)
        if sig.bullish:
            return sig
        return OnChainSignal(ticker=ticker, bullish=False)

    async def _santiment_flow(self, ticker: str) -> OnChainSignal:
        key = self.settings.santiment_api_key
        if not key or not self._session:
            return OnChainSignal(ticker=ticker, bullish=False)
        slug_map = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "xrp"}
        slug = slug_map.get(ticker.upper())
        if not slug:
            return OnChainSignal(ticker=ticker, bullish=False)
        query = (
            "{ getMetric(metric: \"exchange_balance\") { timeseriesData("
            f"slug: \"{slug}\", from: \"utc_now-1d\", to: \"utc_now\", interval: \"1h\""
            ") { datetime value } } }"
        )
        try:
            async with self._session.post(
                "https://api.santiment.net/graphql",
                json={"query": query},
                headers={"Authorization": f"Apikey {key}"},
                timeout=15,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001
            log.debug("santiment failed: %s", exc)
            return OnChainSignal(ticker=ticker, bullish=False)

        series = (data.get("data", {}) or {}).get("getMetric", {}).get("timeseriesData") or []
        if len(series) < 2:
            return OnChainSignal(ticker=ticker, bullish=False)
        first = series[0].get("value") or 0.0
        last = series[-1].get("value") or 0.0
        # exchange balance falling = coins leaving exchanges = bullish
        if last < first * 0.995:
            return OnChainSignal(
                ticker=ticker,
                bullish=True,
                label="whale_withdraw",
                source="santiment",
                detail=f"exchange balance {first:.0f} -> {last:.0f}",
            )
        return OnChainSignal(ticker=ticker, bullish=False, source="santiment")

    async def _glassnode_netflow(self, ticker: str) -> OnChainSignal:
        key = self.settings.glassnode_api_key
        if not key or not self._session:
            return OnChainSignal(ticker=ticker, bullish=False)
        asset_map = {"BTC": "BTC", "ETH": "ETH"}
        asset = asset_map.get(ticker.upper())
        if not asset:
            return OnChainSignal(ticker=ticker, bullish=False)
        try:
            async with self._session.get(
                "https://api.glassnode.com/v1/metrics/transactions/transfers_volume_exchanges_net",
                params={"a": asset, "api_key": key, "i": "1h"},
                timeout=15,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001
            log.debug("glassnode failed: %s", exc)
            return OnChainSignal(ticker=ticker, bullish=False)

        if not isinstance(data, list) or len(data) < 3:
            return OnChainSignal(ticker=ticker, bullish=False)
        recent = data[-3:]
        net = sum((pt.get("v") or 0.0) for pt in recent)
        if net < 0:  # negative netflow = withdrawal from exchanges
            return OnChainSignal(
                ticker=ticker,
                bullish=True,
                label="smart_money_buy",
                source="glassnode",
                detail=f"3h net exchange flow={net:.0f}",
            )
        return OnChainSignal(ticker=ticker, bullish=False, source="glassnode")
