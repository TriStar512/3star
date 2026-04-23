"""Order execution orchestration.

Glues Signal -> Leverage -> RiskManager -> Broker together. The caller
supplies a signal plus the current portfolio heat / sentiment / ATR ratio;
this module computes leverage, sizes the position, and routes the order.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .broker import Broker, Order
from .config import Settings, get_settings
from .leverage import LeverageBreakdown, LeverageInputs, calculate_leverage
from .risk import RiskManager
from .signals import Signal

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    order: Order
    signal: Signal
    leverage: LeverageBreakdown
    quantity: float
    notional_usd: float
    margin_usd: float
    max_loss_usd: float


class OrderRouter:
    def __init__(
        self,
        broker: Broker,
        risk: RiskManager,
        settings: Settings | None = None,
    ):
        self.broker = broker
        self.risk = risk
        self.settings = settings or get_settings()
        self._leverage_override: Optional[float] = None

    def set_leverage_override(self, leverage: Optional[float]) -> None:
        if leverage is None:
            self._leverage_override = None
            log.info("leverage override cleared; dynamic calc resumed")
            return
        if leverage < 1.0 or leverage > self.settings.max_leverage:
            raise ValueError(f"leverage must be in [1, {self.settings.max_leverage}]")
        self._leverage_override = leverage
        log.info("leverage override: %.2fx", leverage)

    async def execute(
        self,
        signal: Signal,
        atr_ratio: float,
    ) -> Optional[ExecutionResult]:
        ok, reason = self.risk.can_open_trade()
        if not ok:
            log.info("skip %s: %s", signal.ticker, reason)
            return None

        lev = calculate_leverage(
            LeverageInputs(
                sentiment_score=signal.sentiment_score,
                atr_ratio=atr_ratio,
                portfolio_heat=self.risk.portfolio_heat(),
            ),
            settings=self.settings,
            override=self._leverage_override,
        )

        size = self.risk.size_position(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            leverage=lev.leverage,
        )

        if size.quantity <= 0:
            log.warning("sizing produced zero quantity for %s", signal.ticker)
            return None

        order = await self.broker.place_limit_order(
            ticker=signal.ticker,
            direction=signal.direction,
            quantity=size.quantity,
            price=signal.entry_price,
            leverage=lev.leverage,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
        )

        return ExecutionResult(
            order=order,
            signal=signal,
            leverage=lev,
            quantity=size.quantity,
            notional_usd=size.notional_usd,
            margin_usd=size.margin_usd,
            max_loss_usd=size.max_loss_usd,
        )
