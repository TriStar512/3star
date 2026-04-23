"""Dynamic leverage scaling calculation engine."""

import logging
from typing import Optional
from dataclasses import dataclass
from utils import clamp

logger = logging.getLogger(__name__)


@dataclass
class LeverageParams:
    """Parameters for leverage calculation."""
    base_leverage: float = 2.0  # Conservative default
    max_leverage: float = 3.0   # Hard cap
    sentiment_score: float = 0.0  # [-1, +1] very bearish to very bullish
    volatility_factor: float = 1.0  # ATR20/ATR50 ratio, capped at 1.5
    portfolio_heat: float = 0.0  # [0, 1] portfolio utilization
    minimum_leverage: float = 1.0  # Spot leverage minimum


class LeverageCalculator:
    """Calculate dynamic leverage based on market conditions."""

    def __init__(self, base_leverage: float = 2.0, max_leverage: float = 3.0):
        self.base_leverage = base_leverage
        self.max_leverage = max_leverage

    def calculate(self, params: LeverageParams) -> float:
        """
        Calculate dynamic leverage.

        Formula:
        leverage = base × sentiment_mult × vol_factor × heat_discount
        where:
          sentiment_mult = 1.0 + (sentiment_score × 0.5)  # [0.5, 1.5]
          vol_factor = min(ATR20/ATR50, 1.5)
          heat_discount = max(0.5, 1.0 - portfolio_heat)

        Args:
            params: LeverageParams with sentiment, volatility, heat

        Returns:
            Calculated leverage, clamped between min_leverage and max_leverage
        """
        # Sentiment multiplier: -1 (very bearish) → 0.5x, +1 (very bullish) → 1.5x
        sentiment_mult = 1.0 + (params.sentiment_score * 0.5)
        sentiment_mult = clamp(sentiment_mult, 0.5, 1.5)

        # Volatility factor (already capped at 1.5 in input)
        vol_factor = clamp(params.volatility_factor, 0.5, 1.5)

        # Portfolio heat discount: if portfolio is hot (deployed), reduce leverage
        # 0% heat → 1.0x multiplier, 50% heat → 0.5x multiplier, 100% heat → 0.0x
        heat_discount = max(0.5, 1.0 - params.portfolio_heat)
        heat_discount = clamp(heat_discount, 0.5, 1.0)

        # Calculate leverage
        leverage = (
            self.base_leverage
            * sentiment_mult
            * vol_factor
            * heat_discount
        )

        # Clamp to hard limits
        leverage = clamp(
            leverage,
            params.minimum_leverage,
            self.max_leverage
        )

        logger.debug(
            f"Leverage calc: base={self.base_leverage:.2f}, "
            f"sentiment={sentiment_mult:.2f}, vol={vol_factor:.2f}, "
            f"heat={heat_discount:.2f} → {leverage:.2f}x"
        )

        return leverage

    def calculate_simple(
        self,
        sentiment_score: float,
        volatility_factor: float = 1.0,
        portfolio_heat: float = 0.0,
    ) -> float:
        """
        Simplified version of calculate() for convenience.

        Args:
            sentiment_score: [-1, +1] sentiment from news
            volatility_factor: [0.5, 1.5] ATR20/ATR50
            portfolio_heat: [0, 1] portfolio utilization

        Returns:
            Calculated leverage
        """
        params = LeverageParams(
            base_leverage=self.base_leverage,
            max_leverage=self.max_leverage,
            sentiment_score=sentiment_score,
            volatility_factor=volatility_factor,
            portfolio_heat=portfolio_heat,
        )
        return self.calculate(params)

    def sentiment_to_leverage_range(self, sentiment_score: float) -> tuple:
        """
        Get the leverage range for a given sentiment score.

        Returns:
            (min_leverage, max_leverage) for this sentiment
        """
        sentiment_mult = clamp(1.0 + (sentiment_score * 0.5), 0.5, 1.5)

        # Best case: low volatility, no heat
        best_leverage = clamp(
            self.base_leverage * sentiment_mult * 1.5,  # vol = 1.5
            1.0,
            self.max_leverage,
        )

        # Worst case: high volatility, full heat
        worst_leverage = clamp(
            self.base_leverage * sentiment_mult * 0.5,  # vol = 0.5, heat = 1.0
            1.0,
            self.max_leverage,
        )

        return (min(best_leverage, worst_leverage), max(best_leverage, worst_leverage))


# Global instance
leverage_calc = LeverageCalculator()
