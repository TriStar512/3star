import unittest
from leverage import calculate_dynamic_leverage, LeverageInput


class TestDynamicLeverage(unittest.TestCase):
    """Unit tests for dynamic leverage calculation."""

    def test_max_leverage_cap(self):
        """Ensure leverage never exceeds 3x hard cap."""
        input_data = LeverageInput(
            sentiment_score=1.0,  # Very bullish
            atr_20=10.0,
            atr_50=5.0,  # High volatility
            portfolio_heat=0.0,  # No portfolio heat
        )

        output = calculate_dynamic_leverage(input_data)
        self.assertLessEqual(output.leverage, 3.0)

    def test_min_leverage_floor(self):
        """Ensure leverage never drops below 1x (spot)."""
        input_data = LeverageInput(
            sentiment_score=-1.0,  # Very bearish
            atr_20=5.0,
            atr_50=10.0,  # Low volatility
            portfolio_heat=1.0,  # Full portfolio deployed
        )

        output = calculate_dynamic_leverage(input_data)
        self.assertGreaterEqual(output.leverage, 1.0)

    def test_sentiment_positive_increases_leverage(self):
        """Positive sentiment should increase leverage."""
        input_bullish = LeverageInput(
            sentiment_score=0.8,
            atr_20=10.0,
            atr_50=10.0,
            portfolio_heat=0.0,
        )

        input_neutral = LeverageInput(
            sentiment_score=0.0,
            atr_20=10.0,
            atr_50=10.0,
            portfolio_heat=0.0,
        )

        bullish_lev = calculate_dynamic_leverage(input_bullish).leverage
        neutral_lev = calculate_dynamic_leverage(input_neutral).leverage

        self.assertGreater(bullish_lev, neutral_lev)

    def test_sentiment_negative_decreases_leverage(self):
        """Negative sentiment should decrease leverage."""
        input_bearish = LeverageInput(
            sentiment_score=-0.8,
            atr_20=10.0,
            atr_50=10.0,
            portfolio_heat=0.0,
        )

        input_neutral = LeverageInput(
            sentiment_score=0.0,
            atr_20=10.0,
            atr_50=10.0,
            portfolio_heat=0.0,
        )

        bearish_lev = calculate_dynamic_leverage(input_bearish).leverage
        neutral_lev = calculate_dynamic_leverage(input_neutral).leverage

        self.assertLess(bearish_lev, neutral_lev)

    def test_high_portfolio_heat_reduces_leverage(self):
        """High portfolio heat should reduce leverage."""
        input_low_heat = LeverageInput(
            sentiment_score=0.5,
            atr_20=10.0,
            atr_50=10.0,
            portfolio_heat=0.0,
        )

        input_high_heat = LeverageInput(
            sentiment_score=0.5,
            atr_20=10.0,
            atr_50=10.0,
            portfolio_heat=0.9,
        )

        low_heat_lev = calculate_dynamic_leverage(input_low_heat).leverage
        high_heat_lev = calculate_dynamic_leverage(input_high_heat).leverage

        self.assertGreater(low_heat_lev, high_heat_lev)

    def test_high_volatility_cap(self):
        """Volatility factor should cap at 1.5."""
        input_data = LeverageInput(
            sentiment_score=0.0,
            atr_20=100.0,  # Much higher than ATR50
            atr_50=10.0,
            portfolio_heat=0.0,
        )

        output = calculate_dynamic_leverage(input_data)
        # Volatility factor capped at 1.5
        self.assertLessEqual(output.volatility_factor, 1.5)


if __name__ == "__main__":
    unittest.main()
