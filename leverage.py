from dataclasses import dataclass
from typing import Optional
from config import settings
from utils import clamp
import logging

logger = logging.getLogger(__name__)


@dataclass
class LeverageInput:
    sentiment_score: float  # [-1, +1]
    atr_20: float
    atr_50: float
    portfolio_heat: float  # [0, 1]


@dataclass
class LeverageOutput:
    leverage: float
    sentiment_multiplier: float
    volatility_factor: float
    heat_discount: float
    reasoning: str


def calculate_dynamic_leverage(
    input_data: LeverageInput,
) -> LeverageOutput:
    """
    Calculate dynamic leverage based on sentiment, volatility, and portfolio heat.

    Formula:
        leverage = base × sentiment_mult × vol_factor × heat_discount
        capped at [1.0, max_leverage]
    """
    base_leverage = settings.base_leverage
    max_leverage = settings.max_leverage

    # 1. Sentiment multiplier: -1 (0.5x) to +1 (1.5x)
    sentiment_multiplier = 1.0 + (input_data.sentiment_score * 0.5)
    sentiment_multiplier = clamp(sentiment_multiplier, 0.5, 1.5)

    # 2. Volatility factor: (ATR20 / ATR50), capped at 1.5x
    if input_data.atr_50 > 0:
        volatility_factor = input_data.atr_20 / input_data.atr_50
    else:
        volatility_factor = 1.0
    volatility_factor = clamp(volatility_factor, 0.5, 1.5)

    # 3. Heat discount: reduce leverage if portfolio is hot
    # Full leverage at 0% heat, 50% discount at 100% heat
    heat_discount = max(0.5, 1.0 - input_data.portfolio_heat)

    # 4. Calculate final leverage
    leverage = base_leverage * sentiment_multiplier * volatility_factor * heat_discount
    leverage = clamp(leverage, 1.0, max_leverage)

    # 5. Build reasoning
    sentiment_label = {
        -1.0: "very bearish",
        -0.5: "bearish",
        0.0: "neutral",
        0.5: "bullish",
        1.0: "very bullish",
    }

    sentiment_text = "neutral"
    if input_data.sentiment_score < -0.5:
        sentiment_text = "very bearish"
    elif input_data.sentiment_score < 0:
        sentiment_text = "bearish"
    elif input_data.sentiment_score > 0.5:
        sentiment_text = "very bullish"
    elif input_data.sentiment_score > 0:
        sentiment_text = "bullish"

    reasoning = (
        f"Base {base_leverage:.1f}x × Sentiment ({sentiment_text}, {sentiment_multiplier:.2f}) × "
        f"Volatility ({volatility_factor:.2f}) × Heat Discount ({heat_discount:.2f}) = {leverage:.2f}x"
    )

    return LeverageOutput(
        leverage=leverage,
        sentiment_multiplier=sentiment_multiplier,
        volatility_factor=volatility_factor,
        heat_discount=heat_discount,
        reasoning=reasoning,
    )
