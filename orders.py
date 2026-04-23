"""Order execution and position management."""

import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime, timedelta
from utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class ActivePosition:
    """Active trading position."""
    trade_id: str
    ticker: str
    direction: str  # 'long' or 'short'
    quantity: float
    entry_price: float
    entry_time: datetime
    leverage: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    tp1_filled: bool = False
    tp2_filled: bool = False
    remaining_quantity: float = None

    def __post_init__(self):
        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity


class OrderManager:
    """Manage order execution and position lifecycle."""

    def __init__(self, broker, risk_manager, logger_db):
        self.broker = broker
        self.risk_manager = risk_manager
        self.logger_db = logger_db
        self.active_positions: Dict[str, ActivePosition] = {}
        self.position_timeout_minutes = 30

    async def open_position(
        self,
        trade_id: str,
        ticker: str,
        direction: str,
        quantity: float,
        entry_price: float,
        leverage: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
        paper_mode: bool = True,
    ) -> bool:
        """
        Open a new position.

        Args:
            trade_id: Unique trade identifier
            ticker: Ticker symbol
            direction: 'long' or 'short'
            quantity: Position quantity
            entry_price: Entry price (limit order)
            leverage: Leverage multiplier
            stop_loss: Stop loss price
            take_profit_1: First take profit (50% close)
            take_profit_2: Second take profit (25% close)
            paper_mode: If True, don't execute on broker

        Returns:
            True if position opened successfully
        """
        try:
            if paper_mode:
                logger.info(
                    f"[PAPER] Open {direction.upper()} {ticker}: "
                    f"{quantity} @ {entry_price} with {leverage}x leverage"
                )
            else:
                # Execute on broker
                order = await self.broker.place_limit_order(
                    ticker=ticker,
                    direction=direction,
                    quantity=quantity,
                    entry_price=entry_price,
                    leverage=leverage,
                    stop_loss=stop_loss,
                    take_profit_1=take_profit_1,
                    take_profit_2=take_profit_2,
                )

                if not order:
                    logger.error(f"Failed to place order for {ticker}")
                    return False

                logger.info(f"Order placed: {order.order_id}")

            # Track in active positions
            position = ActivePosition(
                trade_id=trade_id,
                ticker=ticker,
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                entry_time=now_utc(),
                leverage=leverage,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
                remaining_quantity=quantity,
            )

            self.active_positions[trade_id] = position
            logger.info(f"Position tracked: {trade_id} - {ticker}")

            return True

        except Exception as e:
            logger.error(f"Failed to open position: {str(e)}")
            return False

    async def check_exits(
        self,
        current_prices: Dict[str, float],
        paper_mode: bool = True,
    ) -> List[Dict]:
        """
        Check for take profit and stop loss hits.

        Args:
            current_prices: Dict of ticker -> current price
            paper_mode: If True, simulate exits

        Returns:
            List of exit events
        """
        exits = []
        trades_to_close = []

        for trade_id, position in self.active_positions.items():
            ticker = position.ticker
            current_price = current_prices.get(ticker)

            if not current_price:
                continue

            # Check stop loss
            if position.direction == "long":
                if current_price <= position.stop_loss:
                    logger.warning(f"STOP LOSS HIT: {ticker} @ {current_price}")
                    exits.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "exit_price": position.stop_loss,
                        "exit_reason": "sl",
                    })
                    trades_to_close.append(trade_id)
                    continue

                # Check take profits
                if not position.tp1_filled and current_price >= position.take_profit_1:
                    logger.info(f"TP1 HIT: {ticker} @ {current_price}")
                    tp1_quantity = position.quantity * 0.5
                    exits.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "exit_price": position.take_profit_1,
                        "exit_reason": "tp1",
                        "quantity": tp1_quantity,
                        "partial": True,
                    })
                    position.tp1_filled = True
                    position.remaining_quantity -= tp1_quantity

                if not position.tp2_filled and current_price >= position.take_profit_2:
                    logger.info(f"TP2 HIT: {ticker} @ {current_price}")
                    tp2_quantity = position.remaining_quantity * 0.25
                    exits.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "exit_price": position.take_profit_2,
                        "exit_reason": "tp2",
                        "quantity": tp2_quantity,
                        "partial": True,
                    })
                    position.tp2_filled = True
                    position.remaining_quantity -= tp2_quantity
                    # Keep trailing stop for remaining 25%

            else:  # short
                if current_price >= position.stop_loss:
                    logger.warning(f"STOP LOSS HIT: {ticker} @ {current_price}")
                    exits.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "exit_price": position.stop_loss,
                        "exit_reason": "sl",
                    })
                    trades_to_close.append(trade_id)
                    continue

                # Check take profits
                if not position.tp1_filled and current_price <= position.take_profit_1:
                    logger.info(f"TP1 HIT: {ticker} @ {current_price}")
                    tp1_quantity = position.quantity * 0.5
                    exits.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "exit_price": position.take_profit_1,
                        "exit_reason": "tp1",
                        "quantity": tp1_quantity,
                        "partial": True,
                    })
                    position.tp1_filled = True
                    position.remaining_quantity -= tp1_quantity

                if not position.tp2_filled and current_price <= position.take_profit_2:
                    logger.info(f"TP2 HIT: {ticker} @ {current_price}")
                    tp2_quantity = position.remaining_quantity * 0.25
                    exits.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "exit_price": position.take_profit_2,
                        "exit_reason": "tp2",
                        "quantity": tp2_quantity,
                        "partial": True,
                    })
                    position.tp2_filled = True
                    position.remaining_quantity -= tp2_quantity

            # Check timeout
            time_held = (now_utc() - position.entry_time).total_seconds() / 60
            if time_held > self.position_timeout_minutes:
                logger.warning(f"TIMEOUT: {ticker} held for {time_held:.0f} minutes")
                exits.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "exit_price": current_price,
                    "exit_reason": "timeout",
                })
                trades_to_close.append(trade_id)

        # Clean up closed positions
        for trade_id in trades_to_close:
            if trade_id in self.active_positions:
                del self.active_positions[trade_id]

        return exits

    async def close_position(
        self,
        trade_id: str,
        exit_price: float,
        paper_mode: bool = True,
    ) -> bool:
        """
        Close a position completely.

        Args:
            trade_id: Trade ID to close
            exit_price: Price to exit at
            paper_mode: If True, don't execute on broker

        Returns:
            True if closed successfully
        """
        if trade_id not in self.active_positions:
            logger.warning(f"Position not found: {trade_id}")
            return False

        position = self.active_positions[trade_id]

        try:
            if not paper_mode:
                await self.broker.close_position(position.ticker)

            logger.info(
                f"Closed {position.direction.upper()} {position.ticker} "
                f"{position.remaining_quantity} @ {exit_price}"
            )

            del self.active_positions[trade_id]
            return True

        except Exception as e:
            logger.error(f"Failed to close position: {str(e)}")
            return False

    async def emergency_close_all(self, current_prices: Dict[str, float], paper_mode: bool = True):
        """
        Close all positions immediately (panic button).

        Args:
            current_prices: Dict of ticker -> current price
            paper_mode: If True, don't execute on broker
        """
        logger.critical("EMERGENCY CLOSE ALL POSITIONS")

        for trade_id in list(self.active_positions.keys()):
            position = self.active_positions[trade_id]
            exit_price = current_prices.get(position.ticker, position.entry_price)

            await self.close_position(trade_id, exit_price, paper_mode)

    def get_portfolio_exposure(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total open position notional value.

        Args:
            current_prices: Dict of ticker -> current price

        Returns:
            Total notional value in USD
        """
        total = 0.0
        for position in self.active_positions.values():
            price = current_prices.get(position.ticker, position.entry_price)
            notional = position.remaining_quantity * price
            total += notional

        return total

    def get_open_positions_summary(self) -> List[Dict]:
        """Get summary of open positions."""
        return [
            {
                "trade_id": pos.trade_id,
                "ticker": pos.ticker,
                "direction": pos.direction,
                "quantity": pos.remaining_quantity,
                "entry_price": pos.entry_price,
                "leverage": pos.leverage,
                "entry_time": pos.entry_time.isoformat(),
            }
            for pos in self.active_positions.values()
        ]
