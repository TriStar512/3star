"""On-chain signal analysis from Nansen, Glassnode, and Santiment."""

import logging
import aiohttp
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime
from utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class OnChainSignal:
    """On-chain signal result."""
    ticker: str
    signal_type: str  # 'smart_money_buy', 'whale_withdraw', 'exchange_inflow', etc.
    strength: float  # [0, 1] signal strength
    description: str
    timestamp: datetime


class OnChainAnalyzer:
    """Analyze on-chain signals from various providers."""

    def __init__(self, glassnode_key: str = "", santiment_key: str = ""):
        self.glassnode_key = glassnode_key
        self.santiment_key = santiment_key
        self.cache: Dict[str, OnChainSignal] = {}

    async def check_smart_money_accumulation(self, ticker: str) -> Optional[OnChainSignal]:
        """
        Check if smart money (top 100 holders) is accumulating.

        Glassnode: "Top 100 Profit/Loss Ratio" or similar metric

        Returns:
            OnChainSignal if bullish accumulation detected
        """
        if not self.glassnode_key:
            logger.warning("Glassnode API key not configured")
            return None

        try:
            # Placeholder for Glassnode API call
            # In production, call: https://api.glassnode.com/v1/metrics/...
            logger.debug(f"Checking smart money accumulation for {ticker}")

            # Simulated check
            is_accumulating = True  # In real code, query actual metric

            if is_accumulating:
                return OnChainSignal(
                    ticker=ticker,
                    signal_type="smart_money_buy",
                    strength=0.8,
                    description=f"Top 100 holders accumulating {ticker}",
                    timestamp=now_utc(),
                )

        except Exception as e:
            logger.error(f"Failed to check smart money: {str(e)}")

        return None

    async def check_exchange_flow(self, ticker: str) -> Optional[OnChainSignal]:
        """
        Check exchange inflow/outflow.

        Bullish if net withdrawal from exchanges (hodling).
        Bearish if net inflow (selling).

        Returns:
            OnChainSignal if significant flow detected
        """
        if not self.glassnode_key:
            return None

        try:
            logger.debug(f"Checking exchange flow for {ticker}")

            # Placeholder for Glassnode exchange flow API
            net_flow = 0  # Simulated
            is_withdrawal = net_flow < -100  # Net withdrawal in BTC/ETH equivalent

            if is_withdrawal:
                return OnChainSignal(
                    ticker=ticker,
                    signal_type="whale_withdraw",
                    strength=0.7,
                    description=f"Net exchange withdrawal detected for {ticker}",
                    timestamp=now_utc(),
                )

        except Exception as e:
            logger.error(f"Failed to check exchange flow: {str(e)}")

        return None

    async def check_whale_transactions(self, ticker: str, min_usd: float = 1_000_000) -> Optional[OnChainSignal]:
        """
        Detect large whale transactions.

        Args:
            ticker: Ticker symbol
            min_usd: Minimum transaction value in USD

        Returns:
            OnChainSignal if large transaction detected
        """
        if not self.glassnode_key:
            return None

        try:
            logger.debug(f"Checking whale transactions for {ticker}")

            # Placeholder for whale detection
            has_whale_activity = False  # In real code, query actual data

            if has_whale_activity:
                return OnChainSignal(
                    ticker=ticker,
                    signal_type="whale_transaction",
                    strength=0.6,
                    description=f"Large whale transaction detected for {ticker}",
                    timestamp=now_utc(),
                )

        except Exception as e:
            logger.error(f"Failed to check whale transactions: {str(e)}")

        return None

    async def check_liquidation_heatmap(self, ticker: str) -> Optional[OnChainSignal]:
        """
        Check liquidation cluster (support/resistance confirmation).

        High liquidation cluster = support/resistance zone.

        Returns:
            OnChainSignal if significant cluster detected
        """
        try:
            logger.debug(f"Checking liquidation heatmap for {ticker}")

            # Placeholder for liquidation data
            has_cluster = False  # In real code, query liquidation API

            if has_cluster:
                return OnChainSignal(
                    ticker=ticker,
                    signal_type="liquidation_cluster",
                    strength=0.5,
                    description=f"Liquidation cluster detected for {ticker}",
                    timestamp=now_utc(),
                )

        except Exception as e:
            logger.error(f"Failed to check liquidation heatmap: {str(e)}")

        return None

    async def get_all_signals(self, ticker: str) -> List[OnChainSignal]:
        """
        Get all available on-chain signals for a ticker.

        Returns:
            List of OnChainSignal
        """
        signals = []

        # Check all sources in parallel
        smart_money = await self.check_smart_money_accumulation(ticker)
        if smart_money:
            signals.append(smart_money)

        exchange_flow = await self.check_exchange_flow(ticker)
        if exchange_flow:
            signals.append(exchange_flow)

        whale = await self.check_whale_transactions(ticker)
        if whale:
            signals.append(whale)

        liquidation = await self.check_liquidation_heatmap(ticker)
        if liquidation:
            signals.append(liquidation)

        return signals

    async def get_best_signal(self, ticker: str) -> Optional[OnChainSignal]:
        """
        Get strongest on-chain signal for a ticker.

        Returns:
            Strongest OnChainSignal or None
        """
        signals = await self.get_all_signals(ticker)
        if not signals:
            return None

        # Return strongest signal
        return max(signals, key=lambda s: s.strength)

    def is_bullish(self, signal: Optional[OnChainSignal]) -> bool:
        """Check if signal is bullish."""
        if not signal:
            return False

        bullish_types = {
            "smart_money_buy",
            "whale_withdraw",
            "exchange_outflow",
            "liquidation_cluster",
        }

        return signal.signal_type in bullish_types


# Global instance
on_chain_analyzer = OnChainAnalyzer()
