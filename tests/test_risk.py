"""Tests for risk management and position sizing."""

import pytest
from risk import RiskManager


class TestRiskManager:
    """Test suite for risk management."""

    def setup_method(self):
        """Setup for each test."""
        self.risk_mgr = RiskManager(
            portfolio_size=1000,
            max_loss_pct=0.02,  # 2%
            max_position_pct=0.05,  # 5%
        )

    def test_position_size_basic(self):
        """Test basic position sizing."""
        # Long position: entry 100, SL 95
        pos_size = self.risk_mgr.calculate_position_size(
            entry_price=100,
            stop_loss_price=95,
            leverage=1.0,
        )

        # Max loss = 1000 * 0.02 = $20
        # Distance to SL = 5
        # Quantity = 20 / 5 = 4
        assert pos_size.quantity == 4.0
        assert pos_size.risk_amount == 20.0
        assert pos_size.risk_pct == 2.0

    def test_position_size_with_leverage(self):
        """Test position sizing with leverage."""
        pos_size_1x = self.risk_mgr.calculate_position_size(
            entry_price=100,
            stop_loss_price=95,
            leverage=1.0,
        )

        pos_size_2x = self.risk_mgr.calculate_position_size(
            entry_price=100,
            stop_loss_price=95,
            leverage=2.0,
        )

        # With 2x leverage, position should be smaller
        assert pos_size_2x.quantity < pos_size_1x.quantity
        assert pos_size_2x.quantity == pos_size_1x.quantity / 2

    def test_position_size_capped_by_max_position(self):
        """Test position size is capped by max position %."""
        # Try to open huge position
        pos_size = self.risk_mgr.calculate_position_size(
            entry_price=10,  # Low price
            stop_loss_price=9,  # High leverage
            leverage=1.0,
        )

        # Should be capped by max position (5% of portfolio)
        max_notional = 1000 * 0.05  # $50
        assert pos_size.notional_value <= max_notional

    def test_portfolio_heat_calculation(self):
        """Test portfolio heat calculation."""
        # No exposure
        heat = self.risk_mgr.calculate_portfolio_heat(current_exposure=0)
        assert heat == 0.0

        # 50% exposure
        heat = self.risk_mgr.calculate_portfolio_heat(current_exposure=500)
        assert heat == 0.5

        # 100% exposure
        heat = self.risk_mgr.calculate_portfolio_heat(current_exposure=1000)
        assert heat == 1.0

        # Over 100% (should be clamped)
        heat = self.risk_mgr.calculate_portfolio_heat(current_exposure=2000)
        assert heat == 1.0

    def test_portfolio_heat_with_custom_total(self):
        """Test portfolio heat with custom total."""
        # 500 exposure on 500 total = 100%
        heat = self.risk_mgr.calculate_portfolio_heat(
            current_exposure=500,
            total_portfolio=500,
        )
        assert heat == 1.0

    def test_emergency_conditions_loss(self):
        """Test emergency close trigger on loss."""
        # -2% loss should NOT trigger
        should_close = self.risk_mgr.check_emergency_conditions(unrealized_pnl_pct=-0.02)
        assert not should_close

        # -3% loss SHOULD trigger
        should_close = self.risk_mgr.check_emergency_conditions(unrealized_pnl_pct=-0.03)
        assert should_close

        # -5% loss definitely should trigger
        should_close = self.risk_mgr.check_emergency_conditions(unrealized_pnl_pct=-0.05)
        assert should_close

    def test_emergency_conditions_iv_rank(self):
        """Test emergency close trigger on IV Rank."""
        # IV Rank 80% should NOT trigger
        should_close = self.risk_mgr.check_emergency_conditions(
            unrealized_pnl_pct=0.0,
            iv_rank=0.80,
        )
        assert not should_close

        # IV Rank 91% SHOULD trigger
        should_close = self.risk_mgr.check_emergency_conditions(
            unrealized_pnl_pct=0.0,
            iv_rank=0.91,
        )
        assert should_close

    def test_emergency_conditions_combined(self):
        """Test emergency close with both conditions."""
        # Both bad: loss + high IV
        should_close = self.risk_mgr.check_emergency_conditions(
            unrealized_pnl_pct=-0.05,
            iv_rank=0.95,
        )
        assert should_close

    def test_update_max_loss_pct(self):
        """Test updating max loss percentage."""
        self.risk_mgr.update_max_loss_pct(0.03)
        assert self.risk_mgr.max_loss_pct == 0.03

        # Verify position sizing uses new value
        pos_size = self.risk_mgr.calculate_position_size(100, 95, 1.0)
        # New max loss = 1000 * 0.03 = $30
        assert pos_size.risk_amount == 30.0

    def test_update_max_loss_invalid(self):
        """Test invalid max loss updates are rejected."""
        original = self.risk_mgr.max_loss_pct

        # Negative
        self.risk_mgr.update_max_loss_pct(-0.01)
        assert self.risk_mgr.max_loss_pct == original

        # Zero
        self.risk_mgr.update_max_loss_pct(0.0)
        assert self.risk_mgr.max_loss_pct == original

        # Too high
        self.risk_mgr.update_max_loss_pct(0.15)
        assert self.risk_mgr.max_loss_pct == original

    def test_update_portfolio_size(self):
        """Test updating portfolio size."""
        self.risk_mgr.update_portfolio_size(2000)
        assert self.risk_mgr.portfolio_size == 2000

    def test_update_portfolio_size_invalid(self):
        """Test invalid portfolio size is rejected."""
        original = self.risk_mgr.portfolio_size

        # Negative
        self.risk_mgr.update_portfolio_size(-1000)
        assert self.risk_mgr.portfolio_size == original

        # Zero
        self.risk_mgr.update_portfolio_size(0)
        assert self.risk_mgr.portfolio_size == original

    def test_short_position_sizing(self):
        """Test position sizing for short positions."""
        # Short: entry 100, SL 105 (above entry)
        pos_size = self.risk_mgr.calculate_position_size(
            entry_price=100,
            stop_loss_price=105,
            leverage=1.0,
        )

        # Distance to SL = 5
        # Max loss = 20
        # Quantity = 4
        assert pos_size.quantity == 4.0
        assert pos_size.risk_amount == 20.0

    def test_zero_sl_distance(self):
        """Test handling of zero stop loss distance."""
        pos_size = self.risk_mgr.calculate_position_size(
            entry_price=100,
            stop_loss_price=100,  # SL = entry
            leverage=1.0,
        )

        # Should return zero position
        assert pos_size.quantity == 0
        assert pos_size.risk_amount == 0

    def test_tight_stop_loss(self):
        """Test with tight stop loss."""
        pos_size = self.risk_mgr.calculate_position_size(
            entry_price=100,
            stop_loss_price=99.9,  # Very tight: 0.1 pips
            leverage=1.0,
        )

        # Large quantity due to small SL distance
        # Max loss = 20, distance = 0.1, quantity = 200
        assert pos_size.quantity == pytest.approx(200.0)

    def test_wide_stop_loss(self):
        """Test with wide stop loss."""
        pos_size = self.risk_mgr.calculate_position_size(
            entry_price=100,
            stop_loss_price=80,  # Wide: 20 pips
            leverage=1.0,
        )

        # Small quantity due to large SL distance
        # Max loss = 20, distance = 20, quantity = 1
        assert pos_size.quantity == pytest.approx(1.0)

    def test_high_leverage_tight_sizing(self):
        """Test that high leverage produces appropriately tight sizing."""
        pos_size_1x = self.risk_mgr.calculate_position_size(100, 95, 1.0)
        pos_size_3x = self.risk_mgr.calculate_position_size(100, 95, 3.0)

        # 3x leverage should produce much smaller position
        assert pos_size_3x.quantity < pos_size_1x.quantity / 2
