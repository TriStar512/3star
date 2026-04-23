"""Unit tests for dynamic leverage calculation."""
from __future__ import annotations

import pytest

from JARBIS_Crypto.config import Settings
from JARBIS_Crypto.leverage import LeverageInputs, calculate_leverage


@pytest.fixture
def settings() -> Settings:
    return Settings(
        portfolio_size_usd=1000,
        max_loss_pct=0.02,
        max_leverage=3.0,
        base_leverage=2.0,
        max_position_size_pct=0.05,
    )


def test_neutral_sentiment_returns_base(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=0.0, atr_ratio=1.0, portfolio_heat=0.0),
        settings=settings,
    )
    # base * 1.0 * 1.0 * 1.0 = 2.0
    assert out.leverage == pytest.approx(2.0)


def test_bullish_sentiment_increases_leverage(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=0.8, atr_ratio=1.0, portfolio_heat=0.0),
        settings=settings,
    )
    # base 2.0 * (1 + 0.4) * 1.0 * 1.0 = 2.8
    assert out.leverage == pytest.approx(2.8, rel=1e-3)


def test_bearish_sentiment_decreases_leverage(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=-0.8, atr_ratio=1.0, portfolio_heat=0.0),
        settings=settings,
    )
    # base 2.0 * 0.6 * 1.0 * 1.0 = 1.2
    assert out.leverage == pytest.approx(1.2, rel=1e-3)


def test_hard_cap_at_max_leverage(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=1.0, atr_ratio=1.5, portfolio_heat=0.0),
        settings=settings,
    )
    # would be 2.0 * 1.5 * 1.5 * 1.0 = 4.5 but capped to 3.0
    assert out.leverage == pytest.approx(3.0)


def test_floor_at_one(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=-1.0, atr_ratio=0.1, portfolio_heat=1.0),
        settings=settings,
    )
    assert out.leverage == pytest.approx(1.0)


def test_volatility_dampener_cap(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=0.0, atr_ratio=5.0, portfolio_heat=0.0),
        settings=settings,
    )
    # vol factor capped at 1.5 -> 2.0 * 1.0 * 1.5 * 1.0 = 3.0
    assert out.leverage == pytest.approx(3.0)


def test_heat_discount_lowers_leverage(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=0.8, atr_ratio=1.1, portfolio_heat=0.2),
        settings=settings,
    )
    # 2.0 * 1.4 * 1.1 * 0.8 = 2.464
    assert out.leverage == pytest.approx(2.464, rel=1e-3)


def test_override_respects_cap(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=0.5, atr_ratio=1.0, portfolio_heat=0.0),
        settings=settings,
        override=10.0,
    )
    assert out.leverage == pytest.approx(settings.max_leverage)


def test_override_respects_floor(settings: Settings) -> None:
    out = calculate_leverage(
        LeverageInputs(sentiment_score=0.5, atr_ratio=1.0, portfolio_heat=0.0),
        settings=settings,
        override=0.3,
    )
    assert out.leverage == pytest.approx(1.0)
