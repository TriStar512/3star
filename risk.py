"""Position sizing and risk management."""

import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Position sizing result."""
    quantity: float  # Amount to trade
    contracts: int  # Number of contracts
    notional_value: float  # Total position value in USD
    risk_amount: float  # Max loss in USD
    risk_pct: float  # Risk as % of portfolio


class RiskManager:
    """Calculate position sizes and manage portfolio risk."""

    def __init__(
        self,
        portfolio_size: float = 1000,
        max_loss_pct: float = 0.02,
        max_position_pct: float = 0.05,
    ):
        self.portfolio_size = portfolio_size
        self.max_loss_pct = max_loss_pct
        self.max_position_pct = max_position_pct

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        leverage: float = 1.0,
    ) -> PositionSize:
        """
        Calculate position size based on risk parameters.

        Args:
            entry_price: Entry price
            stop_loss_price: Stop loss price
            leverage: Leverage multiplier (1.0 = spot)

        Returns:
            PositionSize with quantity, contracts, and risk info
        """
        # Max loss in dollars
        max_loss_dollars = self.portfolio_size * self.max_loss_pct

        # Distance to stop loss
        distance_to_sl = abs(entry_price - stop_loss_price)
        if distance_to_sl == 0:
            logger.error("Stop loss = entry price, invalid")
            return PositionSize(0, 0, 0, 0, 0)

        # Raw quantity based on max loss
        # quantity = max_loss / distance_to_sl
        quantity = max_loss_dollars / distance_to_sl

        # Cap by max position size
        max_position_value = self.portfolio_size * self.max_position_pct
        max_quantity = max_position_value / entry_price

        quantity = min(quantity, max_quantity)

        # Adjust for leverage
        # With leverage, we use less of our capital to control the position
        adjusted_quantity = quantity / leverage if leverage > 0 else quantity

        # Calculate notional value (what position is worth)
        notional_value = adjusted_quantity * entry_price

        # Risk calculation
        actual_risk = distance_to_sl * adjusted_quantity
        risk_pct = (actual_risk / self.portfolio_size) * 100 if self.portfolio_size > 0 else 0

        # Contracts (1 contract = 1 unit, could be 1 BTC, 10 ETH, etc.)
        contracts = int(adjusted_quantity)

        return PositionSize(
            quantity=adjusted_quantity,
            contracts=contracts,
            notional_value=notional_value,
            risk_amount=actual_risk,
            risk_pct=risk_pct,
        )

    def calculate_portfolio_heat(
        self,
        current_exposure: float,  # Current open position notional value
        total_portfolio: Optional[float] = None,
    ) -> float:
        """
        Calculate portfolio heat (% of capital deployed).

        Args:
            current_exposure: Total open position notional value
            total_portfolio: Total portfolio value (default: portfolio_size)

        Returns:
            Heat percentage [0, 1]
        """
        if total_portfolio is None:
            total_portfolio = self.portfolio_size

        if total_portfolio == 0:
            return 0

        heat = current_exposure / total_portfolio
        return max(0, min(1, heat))  # Clamp to [0, 1]

    def check_emergency_conditions(
        self,
        unrealized_pnl_pct: float,
        iv_rank: Optional[float] = None,
    ) -> bool:
        """
        Check if emergency close should be triggered.

        Args:
            unrealized_pnl_pct: Current unrealized P&L as % of portfolio
            iv_rank: IV Rank (0-1) or None

        Returns:
            True if emergency close should trigger
        """
        # Trigger if unrealized loss > 3%
        if unrealized_pnl_pct < -0.03:
            logger.warning(f"Emergency: unrealized loss {unrealized_pnl_pct:.2%}")
            return True

        # Trigger if IV Rank > 90th percentile
        if iv_rank is not None and iv_rank > 0.90:
            logger.warning(f"Emergency: IV Rank {iv_rank:.2%} > 90%")
            return True

        return False

    def update_max_loss_pct(self, new_max_loss_pct: float):
        """Update max loss percentage."""
        if new_max_loss_pct <= 0 or new_max_loss_pct > 0.10:
            logger.error(f"Invalid max loss: {new_max_loss_pct:.2%}. Must be (0, 10%]")
            return

        self.max_loss_pct = new_max_loss_pct
        logger.info(f"Updated max loss to {self.max_loss_pct:.2%}")

    def update_portfolio_size(self, new_size: float):
        """Update portfolio size (e.g., after deposit/withdrawal)."""
        if new_size <= 0:
            logger.error("Portfolio size must be positive")
            return

        old_size = self.portfolio_size
        self.portfolio_size = new_size
        logger.info(f"Portfolio size updated: ${old_size:.2f} → ${new_size:.2f}")


# Global instance
risk_manager = RiskManager()
