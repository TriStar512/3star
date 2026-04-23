import unittest
from risk import calculate_position_size, check_emergency_conditions, validate_leverage


class TestPositionSizing(unittest.TestCase):
    """Unit tests for position sizing and risk management."""

    def test_position_size_calculation(self):
        """Test basic position sizing formula."""
        entry_price = 50000.0
        stop_loss = 49000.0
        leverage = 2.0
        portfolio = 1000.0

        result = calculate_position_size(entry_price, stop_loss, leverage, portfolio)

        # Max loss = 1000 * 0.02 = $20
        # SL distance = 50000 - 49000 = $1000
        # Contracts = 20 / 1000 = 0.02 BTC
        # Adjusted = 0.02 / 2.0 = 0.01 BTC

        self.assertAlmostEqual(result.max_loss_dollars, 20.0, places=1)
        self.assertAlmostEqual(result.stop_loss_distance, 1000.0, places=1)
        self.assertGreater(result.contracts, 0)

    def test_position_capped_at_5_percent(self):
        """Position size should not exceed 5% of portfolio."""
        entry_price = 50000.0
        stop_loss = 49000.0  # Very tight stop
        leverage = 1.0
        portfolio = 10000.0

        result = calculate_position_size(entry_price, stop_loss, leverage, portfolio)

        max_allowed = (portfolio * 0.05) / entry_price
        self.assertLessEqual(result.contracts, max_allowed * 1.01)  # Allow 1% rounding

    def test_invalid_stop_loss(self):
        """Should raise error if stop loss distance is 0."""
        entry_price = 50000.0
        stop_loss = 50000.0  # Same as entry
        leverage = 1.0
        portfolio = 1000.0

        with self.assertRaises(ValueError):
            calculate_position_size(entry_price, stop_loss, leverage, portfolio)

    def test_emergency_portfolio_loss(self):
        """Emergency stop should trigger on >3% portfolio loss."""
        should_close, reason = check_emergency_conditions(
            portfolio_loss_pct=-0.04,  # -4%
            iv_rank=None,
        )

        self.assertTrue(should_close)
        self.assertIn("loss exceeded 3%", reason)

    def test_emergency_iv_rank(self):
        """Emergency stop should trigger on high IV Rank."""
        should_close, reason = check_emergency_conditions(
            portfolio_loss_pct=0.0,
            iv_rank=0.95,  # 95% > 90% threshold
        )

        self.assertTrue(should_close)
        self.assertIn("IV Rank", reason)

    def test_no_emergency_conditions(self):
        """Should not trigger emergency under normal conditions."""
        should_close, reason = check_emergency_conditions(
            portfolio_loss_pct=-0.01,  # -1% (acceptable)
            iv_rank=0.60,  # 60% (normal)
        )

        self.assertFalse(should_close)

    def test_leverage_validation(self):
        """Test leverage bounds validation."""
        self.assertTrue(validate_leverage(1.0))
        self.assertTrue(validate_leverage(2.0))
        self.assertTrue(validate_leverage(3.0))

        self.assertFalse(validate_leverage(0.5))  # Too low
        self.assertFalse(validate_leverage(4.0))  # Too high


if __name__ == "__main__":
    unittest.main()
