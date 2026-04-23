"""Tests for dynamic leverage calculation."""

import pytest
from leverage import LeverageCalculator, LeverageParams


class TestLeverageCalculator:
    """Test suite for leverage calculation."""

    def setup_method(self):
        """Setup for each test."""
        self.calc = LeverageCalculator(base_leverage=2.0, max_leverage=3.0)

    def test_neutral_leverage(self):
        """Test leverage with neutral sentiment and conditions."""
        params = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=0.0,  # Neutral
            volatility_factor=1.0,  # Normal vol
            portfolio_heat=0.0,  # No heat
        )
        leverage = self.calc.calculate(params)
        assert 1.9 < leverage < 2.1  # Should be close to base 2.0

    def test_bullish_leverage(self):
        """Test leverage increases with bullish sentiment."""
        params = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=1.0,  # Very bullish
            volatility_factor=1.0,
            portfolio_heat=0.0,
        )
        leverage = self.calc.calculate(params)
        assert leverage > 2.5  # Should increase with bullish sentiment

    def test_bearish_leverage(self):
        """Test leverage decreases with bearish sentiment."""
        params = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=-1.0,  # Very bearish
            volatility_factor=1.0,
            portfolio_heat=0.0,
        )
        leverage = self.calc.calculate(params)
        assert leverage < 1.5  # Should decrease with bearish sentiment

    def test_max_leverage_cap(self):
        """Test that leverage is capped at max."""
        params = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=1.0,  # Very bullish
            volatility_factor=1.5,  # High vol
            portfolio_heat=0.0,
        )
        leverage = self.calc.calculate(params)
        assert leverage <= 3.0  # Should not exceed max

    def test_high_portfolio_heat(self):
        """Test leverage decreases with high portfolio heat."""
        params_no_heat = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=0.5,
            volatility_factor=1.0,
            portfolio_heat=0.0,  # No heat
        )
        leverage_no_heat = self.calc.calculate(params_no_heat)

        params_heat = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=0.5,
            volatility_factor=1.0,
            portfolio_heat=0.8,  # High heat
        )
        leverage_heat = self.calc.calculate(params_heat)

        assert leverage_heat < leverage_no_heat

    def test_high_volatility(self):
        """Test leverage with high volatility."""
        params_low_vol = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=0.0,
            volatility_factor=0.5,  # Low vol
            portfolio_heat=0.0,
        )
        leverage_low_vol = self.calc.calculate(params_low_vol)

        params_high_vol = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=0.0,
            volatility_factor=1.5,  # High vol
            portfolio_heat=0.0,
        )
        leverage_high_vol = self.calc.calculate(params_high_vol)

        assert leverage_high_vol >= leverage_low_vol

    def test_minimum_leverage(self):
        """Test minimum leverage is enforced."""
        params = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=-1.0,  # Very bearish
            volatility_factor=0.5,  # Low vol
            portfolio_heat=1.0,  # Full heat
            minimum_leverage=1.0,
        )
        leverage = self.calc.calculate(params)
        assert leverage >= 1.0  # Should not go below minimum

    def test_sentiment_range(self):
        """Test sentiment multiplier range."""
        # Very bullish
        params_bullish = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=1.0,
            volatility_factor=1.0,
            portfolio_heat=0.0,
        )
        lev_bullish = self.calc.calculate(params_bullish)

        # Neutral
        params_neutral = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=0.0,
            volatility_factor=1.0,
            portfolio_heat=0.0,
        )
        lev_neutral = self.calc.calculate(params_neutral)

        # Very bearish
        params_bearish = LeverageParams(
            base_leverage=2.0,
            max_leverage=3.0,
            sentiment_score=-1.0,
            volatility_factor=1.0,
            portfolio_heat=0.0,
        )
        lev_bearish = self.calc.calculate(params_bearish)

        # Verify ordering
        assert lev_bullish > lev_neutral > lev_bearish

    def test_simple_calculate(self):
        """Test simplified calculate method."""
        leverage = self.calc.calculate_simple(
            sentiment_score=0.5,
            volatility_factor=1.0,
            portfolio_heat=0.2,
        )
        assert 1.0 <= leverage <= 3.0

    def test_sentiment_to_range(self):
        """Test sentiment to leverage range conversion."""
        min_lev, max_lev = self.calc.sentiment_to_leverage_range(0.0)
        assert min_lev >= 1.0
        assert max_lev <= 3.0
        assert min_lev <= max_lev

    def test_edge_cases(self):
        """Test edge cases."""
        # Extreme bullish
        lev_extreme_bull = self.calc.calculate_simple(1.0, 1.5, 0.0)
        assert lev_extreme_bull <= 3.0

        # Extreme bearish
        lev_extreme_bear = self.calc.calculate_simple(-1.0, 0.5, 1.0)
        assert lev_extreme_bear >= 1.0
