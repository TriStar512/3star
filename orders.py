from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from broker import Order, OrderStatus
import logging

logger = logging.getLogger(__name__)


class ExitReason(str, Enum):
    TP1 = "tp1"
    TP2 = "tp2"
    TRAILING_STOP = "trailing_stop"
    STOP_LOSS = "stop_loss"
    TIMEOUT = "timeout"
    EMERGENCY = "emergency"
    MANUAL = "manual"


@dataclass
class TradeEntry:
    order_id: str
    ticker: str
    direction: str
    entry_price: float
    quantity: float
    leverage: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    entry_time: datetime
    tp1_filled: bool = False
    tp2_filled: bool = False
    tp2_quantity_remaining: float = 0.0


@dataclass
class TradeExit:
    entry: TradeEntry
    exit_price: float
    exit_time: datetime
    exit_reason: ExitReason
    quantity_closed: float
    pnl_dollars: float = 0.0
    pnl_pct: float = 0.0


class OrderManager:
    """Manage order lifecycle and position scaling."""

    def __init__(self, position_timeout_minutes: int = 30):
        self.position_timeout = timedelta(minutes=position_timeout_minutes)
        self.open_trades: Dict[str, TradeEntry] = {}
        self.closed_trades: List[TradeExit] = []

    def add_entry(self, trade: TradeEntry) -> None:
        """Record a new entry."""
        self.open_trades[trade.order_id] = trade
        logger.info(
            f"Added entry: {trade.order_id} | {trade.direction} {trade.quantity} "
            f"{trade.ticker} @ {trade.entry_price} with {trade.leverage:.2f}x leverage"
        )

    def check_tp1_trigger(
        self, order_id: str, current_price: float
    ) -> Optional[Tuple[float, float]]:
        """
        Check if TP1 (1:1 R:R) is hit. Returns (quantity_to_close, exit_price).
        Closes 50% of position.
        """
        if order_id not in self.open_trades:
            return None

        trade = self.open_trades[order_id]
        if trade.tp1_filled:
            return None

        tp1_hit = False
        if trade.direction == "long":
            tp1_hit = current_price >= trade.take_profit_1
        else:
            tp1_hit = current_price <= trade.take_profit_1

        if tp1_hit:
            trade.tp1_filled = True
            quantity = trade.quantity * 0.5
            trade.tp2_quantity_remaining = trade.quantity * 0.25
            logger.info(f"TP1 hit for {order_id}: closing {quantity} @ {current_price}")
            return quantity, current_price

        return None

    def check_tp2_trigger(
        self, order_id: str, current_price: float
    ) -> Optional[Tuple[float, float]]:
        """
        Check if TP2 (1:2 R:R) is hit. Returns (quantity_to_close, exit_price).
        Closes 25% of position (remaining 25% trails).
        """
        if order_id not in self.open_trades:
            return None

        trade = self.open_trades[order_id]
        if trade.tp2_filled or trade.tp2_quantity_remaining <= 0:
            return None

        tp2_hit = False
        if trade.direction == "long":
            tp2_hit = current_price >= trade.take_profit_2
        else:
            tp2_hit = current_price <= trade.take_profit_2

        if tp2_hit:
            trade.tp2_filled = True
            quantity = trade.tp2_quantity_remaining
            logger.info(f"TP2 hit for {order_id}: closing {quantity} @ {current_price}")
            return quantity, current_price

        return None

    def check_trailing_stop(
        self, order_id: str, current_price: float, trailing_pct: float = 0.10
    ) -> Optional[Tuple[float, float]]:
        """
        Check trailing stop on remaining 25% position.
        Returns (quantity_to_close, exit_price) if triggered.
        """
        if order_id not in self.open_trades:
            return None

        trade = self.open_trades[order_id]
        if trade.tp2_quantity_remaining <= 0:
            return None

        # Calculate trailing stop price
        if trade.direction == "long":
            trailing_stop = trade.take_profit_2 * (1 - trailing_pct)
            triggered = current_price <= trailing_stop
        else:
            trailing_stop = trade.take_profit_2 * (1 + trailing_pct)
            triggered = current_price >= trailing_stop

        if triggered:
            quantity = trade.tp2_quantity_remaining
            logger.info(
                f"Trailing stop hit for {order_id}: closing {quantity} @ {current_price}"
            )
            return quantity, current_price

        return None

    def check_stop_loss(
        self, order_id: str, current_price: float
    ) -> Optional[Tuple[float, float]]:
        """
        Check if stop loss is hit. Returns (quantity_to_close, exit_price).
        """
        if order_id not in self.open_trades:
            return None

        trade = self.open_trades[order_id]

        sl_hit = False
        if trade.direction == "long":
            sl_hit = current_price <= trade.stop_loss
        else:
            sl_hit = current_price >= trade.stop_loss

        if sl_hit:
            quantity = trade.quantity - (
                (trade.quantity * 0.5 if trade.tp1_filled else 0)
                + (trade.tp2_quantity_remaining if trade.tp2_filled else 0)
            )
            if quantity > 0:
                logger.info(f"Stop loss hit for {order_id}: closing {quantity} @ {current_price}")
                return quantity, current_price

        return None

    def check_timeout(self, order_id: str) -> Optional[Tuple[float, float]]:
        """
        Check if position has been open too long (30 min default).
        Returns (quantity_to_close, None) if timeout triggered.
        """
        if order_id not in self.open_trades:
            return None

        trade = self.open_trades[order_id]
        if datetime.utcnow() - trade.entry_time > self.position_timeout:
            # Close remaining quantity
            quantity = trade.quantity - (
                (trade.quantity * 0.5 if trade.tp1_filled else 0)
                + (trade.tp2_quantity_remaining if trade.tp2_filled else 0)
            )
            if quantity > 0:
                logger.info(f"Timeout triggered for {order_id}: closing {quantity}")
                return quantity, None

        return None

    def close_position(
        self,
        order_id: str,
        current_price: float,
        exit_reason: ExitReason,
    ) -> Optional[TradeExit]:
        """Record position closure."""
        if order_id not in self.open_trades:
            return None

        trade = self.open_trades[order_id]

        # Calculate P&L
        if trade.direction == "long":
            pnl_dollars = (current_price - trade.entry_price) * trade.quantity
        else:
            pnl_dollars = (trade.entry_price - current_price) * trade.quantity

        pnl_pct = pnl_dollars / (trade.entry_price * trade.quantity) if trade.entry_price > 0 else 0

        exit = TradeExit(
            entry=trade,
            exit_price=current_price,
            exit_time=datetime.utcnow(),
            exit_reason=exit_reason,
            quantity_closed=trade.quantity,
            pnl_dollars=pnl_dollars,
            pnl_pct=pnl_pct,
        )

        self.closed_trades.append(exit)
        del self.open_trades[order_id]

        logger.info(
            f"Closed position {order_id}: {trade.direction} {trade.quantity} {trade.ticker} "
            f"| P&L: ${pnl_dollars:.2f} ({pnl_pct:.2%}) | Reason: {exit_reason}"
        )

        return exit

    def get_win_rate(self) -> float:
        """Calculate win rate from closed trades."""
        if not self.closed_trades:
            return 0.0

        wins = sum(1 for t in self.closed_trades if t.pnl_dollars > 0)
        return wins / len(self.closed_trades)

    def get_total_pnl(self) -> Tuple[float, float]:
        """Get total P&L in dollars and percent."""
        total_pnl_dollars = sum(t.pnl_dollars for t in self.closed_trades)
        total_invested = sum(t.entry.entry_price * t.entry.quantity for t in self.closed_trades)
        total_pnl_pct = total_pnl_dollars / total_invested if total_invested > 0 else 0.0

        return total_pnl_dollars, total_pnl_pct
