"""Dynamic leverage calculation.

    leverage = base_leverage
             * (1 + sentiment_score * 0.5)      in [0.5, 1.5]
             * min(ATR20 / ATR50, 1.5)          volatility factor
             * max(0.5, 1 - portfolio_heat)     heat discount
    clamped to [1.0, max_leverage]
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, get_settings


@dataclass
class LeverageInputs:
    sentiment_score: float  # [-1, +1]
    atr_ratio: float        # ATR20/ATR50
    portfolio_heat: float   # fraction of portfolio at risk, 0..1


@dataclass
class LeverageBreakdown:
    leverage: float
    base: float
    sentiment_mult: float
    vol_factor: float
    heat_discount: float


def calculate_leverage(
    inputs: LeverageInputs,
    settings: Settings | None = None,
    override: float | None = None,
) -> LeverageBreakdown:
    s = settings or get_settings()
    base = s.base_leverage
    if override is not None:
        leverage = max(1.0, min(override, s.max_leverage))
        return LeverageBreakdown(
            leverage=leverage, base=base, sentiment_mult=1.0,
            vol_factor=1.0, heat_discount=1.0,
        )

    score = max(-1.0, min(1.0, inputs.sentiment_score))
    sentiment_mult = 1.0 + score * 0.5  # [0.5, 1.5]

    atr_ratio = max(0.0, inputs.atr_ratio)
    vol_factor = min(atr_ratio if atr_ratio > 0 else 1.0, 1.5)

    heat = max(0.0, min(1.0, inputs.portfolio_heat))
    heat_discount = max(0.5, 1.0 - heat)

    leverage = base * sentiment_mult * vol_factor * heat_discount
    leverage = max(1.0, min(leverage, s.max_leverage))

    return LeverageBreakdown(
        leverage=leverage,
        base=base,
        sentiment_mult=sentiment_mult,
        vol_factor=vol_factor,
        heat_discount=heat_discount,
    )
