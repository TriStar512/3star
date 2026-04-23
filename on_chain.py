from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime
import asyncio
import aiohttp
from config import settings
import logging

logger = logging.getLogger(__name__)


@dataclass
class OnChainSignal:
    ticker: str
    signal_type: str  # 'smart_money_buy', 'whale_withdraw', 'exchange_inflow', 'liquidation_cluster'
    confidence: float  # [0, 1]
    description: str
    timestamp: datetime


class OnChainAnalyzer:
    """Monitor on-chain signals from Nansen/Glassnode."""

    def __init__(self):
        self.nansen_api_key = settings.glassnode_api_key
        self.santiment_api_key = settings.santiment_api_key
        self.signals_cache: Dict[str, List[OnChainSignal]] = {}

    async def check_smart_money_accumulation(
        self, ticker: str
    ) -> Optional[OnChainSignal]:
        """
        Check if top 100 holders are accumulating.
        (Placeholder: real implementation requires Nansen API)
        """
        if not settings.enable_on_chain_signals:
            return None

        try:
            # In production, would call Nansen API
            # nansen_holders = await self._fetch_nansen_top_holders(ticker)
            # net_change = nansen_holders.net_change_usd_24h

            # For now, return mock
            return OnChainSignal(
                ticker=ticker,
                signal_type="smart_money_buy",
                confidence=0.5,
                description=f"Top 100 {ticker} holders net accumulation detected",
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Error checking smart money for {ticker}: {e}")
            return None

    async def check_exchange_flows(self, ticker: str) -> Optional[OnChainSignal]:
        """
        Check if crypto is flowing out of exchanges (bullish).
        """
        if not settings.enable_on_chain_signals:
            return None

        try:
            # In production: Glassnode/Santiment exchange inflow/outflow
            # For now: mock
            return OnChainSignal(
                ticker=ticker,
                signal_type="whale_withdraw",
                confidence=0.5,
                description=f"Net {ticker} outflow from major exchanges (hodling signal)",
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Error checking exchange flows for {ticker}: {e}")
            return None

    async def check_whale_transactions(
        self, ticker: str, min_usd: float = 1_000_000
    ) -> Optional[List[Dict]]:
        """
        Detect whale transactions > min_usd.
        """
        if not settings.enable_on_chain_signals:
            return None

        try:
            # In production: Nansen/Glassnode whale monitoring
            # For now: return empty
            return []

        except Exception as e:
            logger.error(f"Error checking whale txs for {ticker}: {e}")
            return None

    async def check_liquidation_heatmap(
        self, ticker: str
    ) -> Optional[Dict[str, float]]:
        """
        Get liquidation levels for support/resistance confirmation.
        Returns dict of price levels -> liquidation count
        """
        if not settings.enable_on_chain_signals:
            return None

        try:
            # In production: CoinGlass or similar liquidation heatmap
            # For now: return empty
            return {}

        except Exception as e:
            logger.error(f"Error checking liquidations for {ticker}: {e}")
            return None

    async def get_all_signals(self, ticker: str) -> List[OnChainSignal]:
        """
        Get all on-chain signals for a ticker.
        """
        signals = []

        smart_money = await self.check_smart_money_accumulation(ticker)
        if smart_money:
            signals.append(smart_money)

        exchange = await self.check_exchange_flows(ticker)
        if exchange:
            signals.append(exchange)

        # Cache for dashboard
        self.signals_cache[ticker] = signals

        return signals

    def is_bullish_on_chain(self, ticker: str) -> bool:
        """
        Return True if on-chain signals are bullish (net positive).
        """
        signals = self.signals_cache.get(ticker, [])
        if not signals:
            return False

        # Count bullish vs bearish (simplified)
        bullish_count = sum(
            1 for s in signals
            if s.signal_type in ["smart_money_buy", "whale_withdraw"]
        )
        bearish_count = len(signals) - bullish_count

        return bullish_count > bearish_count
