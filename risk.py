from dataclasses import dataclass
from typing import Optional
from config import settings
import logging

logger = logging.getLogger(__name__)


@dataclass
class PositionSizing:
    max_loss_dollars: float
    stop_loss_distance: float
    contracts: float
    adjusted_for_leverage: float
    total_cost: float
    reasoning: str


@dataclass
class RiskMetrics:
    portfolio_balance: float
    unrealized_pnl: float
    deployed_capital: float
    portfolio_heat_pct: float
    leverage_avg: float
    max_drawdown_pct: float
    win_rate_pct: float
    sharpe_ratio: Optional[float]


def calculate_position_size(
    entry_price: float,
    stop_loss_price: float,
    leverage: float,
    current_balance: float,
) -> PositionSizing:
    """
    Calculate position size based on risk parameters.

    Risk formula:
        max_loss = portfolio × max_loss_pct
        distance = |entry_price - stop_loss_price|
        contracts = max_loss / distance
        adjusted = contracts / leverage
    """
    max_loss_dollars = current_balance * settings.max_loss_pct
    stop_loss_distance = abs(entry_price - stop_loss_price)

    if stop_loss_distance <= 0:
        raise ValueError("Stop loss distance must be positive")

    # Raw contracts based on risk
    contracts = max_loss_dollars / stop_loss_distance

    # Cap at 5% of portfolio
    max_contracts = current_balance * settings.max_position_size_pct / entry_price
    contracts = min(contracts, max_contracts)

    # Adjust for leverage (higher leverage = smaller position)
    adjusted = contracts / leverage if leverage > 0 else contracts
    total_cost = adjusted * entry_price

    reasoning = (
        f"Max loss ${max_loss_dollars:.2f} ÷ "
        f"SL distance ${stop_loss_distance:.2f} = {contracts:.6f} contracts. "
        f"Capped at 5% ({max_contracts:.6f}). "
        f"Adjusted for {leverage:.2f}x leverage = {adjusted:.6f} contracts (${total_cost:.2f})"
    )

    return PositionSizing(
        max_loss_dollars=max_loss_dollars,
        stop_loss_distance=stop_loss_distance,
        contracts=contracts,
        adjusted_for_leverage=adjusted,
        total_cost=total_cost,
        reasoning=reasoning,
    )


def check_emergency_conditions(
    portfolio_loss_pct: float,
    iv_rank: Optional[float],
) -> tuple[bool, str]:
    """
    Check if emergency stop should be triggered.

    Returns (should_close_all, reason)
    """
    reason = ""

    # Portfolio loss > 3%
    if portfolio_loss_pct < -0.03:
        return True, "Portfolio loss exceeded 3%"

    # IV Rank > 90%
    if iv_rank and iv_rank > settings.emergency_iv_rank_threshold:
        return True, f"IV Rank {iv_rank:.1%} > {settings.emergency_iv_rank_threshold:.1%}"

    return False, ""


def validate_leverage(leverage: float) -> bool:
    """Check if leverage is within safe bounds."""
    return 1.0 <= leverage <= settings.max_leverage


def validate_position_size(
    position_size: float,
    entry_price: float,
    portfolio_balance: float,
) -> bool:
    """Check if position size respects portfolio limits."""
    position_value = position_size * entry_price
    max_size = portfolio_balance * settings.max_position_size_pct
    return position_value <= max_size
