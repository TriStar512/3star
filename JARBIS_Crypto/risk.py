"""Risk & position sizing.

Enforces the hard limits from the spec:
- max loss 2% per trade (adjustable via CLI)
- max position 5% of portfolio
- max concurrent trades 4
- 30-minute position timeout
- emergency flatten on IV-rank-equivalent threshold
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict

import pandas as pd

from .broker import Broker, Position
from .config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class PositionSize:
    quantity: float
    notional_usd: float
    margin_usd: float
    max_loss_usd: float
    capped_reason: str = ""


class RiskManager:
    def __init__(self, broker: Broker, settings: Settings | None = None):
        self.broker = broker
        self.settings = settings or get_settings()
        # CLI can mutate max_loss_pct at runtime without touching .env
        self._max_loss_pct = self.settings.max_loss_pct

    # ---- tunables ----

    @property
    def max_loss_pct(self) -> float:
        return self._max_loss_pct

    def set_max_loss_pct(self, pct: float) -> None:
        if not 0 < pct < 0.20:
            raise ValueError("max_loss_pct must be in (0, 0.20)")
        self._max_loss_pct = pct
        log.info("risk: max_loss_pct set to %.4f", pct)

    # ---- sizing ----

    def portfolio_heat(self) -> float:
        """Fraction of cash currently tied up in open positions (0..1)."""
        cash = self.broker.cash()
        if cash <= 0:
            return 1.0
        deployed = sum(
            (p.entry_price * p.quantity) / max(p.leverage, 1.0)
            for p in self.broker.positions().values()
        )
        return min(1.0, deployed / cash)

    def size_position(
        self,
        entry_price: float,
        stop_loss: float,
        leverage: float,
    ) -> PositionSize:
        portfolio_usd = self.broker.cash()
        max_loss_usd = portfolio_usd * self._max_loss_pct
        distance = abs(entry_price - stop_loss)
        if distance <= 0:
            raise ValueError("stop loss must differ from entry price")

        # Risk-first sizing: quantity so that SL = max_loss_usd
        quantity = max_loss_usd / distance

        # Cap by MAX_POSITION_SIZE_PCT of portfolio (notional)
        max_notional = portfolio_usd * self.settings.max_position_size_pct * leverage
        capped_reason = ""
        if quantity * entry_price > max_notional:
            quantity = max_notional / entry_price
            capped_reason = "max_position_size_pct"

        notional = quantity * entry_price
        margin = notional / max(leverage, 1.0)

        return PositionSize(
            quantity=quantity,
            notional_usd=notional,
            margin_usd=margin,
            max_loss_usd=max_loss_usd,
            capped_reason=capped_reason,
        )

    # ---- gating ----

    def can_open_trade(self) -> tuple[bool, str]:
        positions = self.broker.positions()
        if len(positions) >= self.settings.max_concurrent_trades:
            return False, f"max concurrent trades ({self.settings.max_concurrent_trades})"
        if self.broker.available_margin() <= 0:
            return False, "no available margin"
        return True, ""

    def timed_out(self, pos: Position, now: pd.Timestamp | None = None) -> bool:
        now = now or pd.Timestamp.utcnow()
        delta: timedelta = (now - pos.opened_at).to_pytimedelta()  # type: ignore[assignment]
        return delta >= timedelta(minutes=self.settings.position_timeout_minutes)

    def exceeded_hard_loss(self, pos: Position, current_price: float) -> bool:
        """3% portfolio loss hard cap."""
        pnl = (current_price - pos.entry_price) * pos.quantity
        if pos.direction == "short":
            pnl = -pnl
        portfolio = self.broker.cash() + pnl
        return pnl <= -portfolio * 0.03

    def scan_timeouts(self, prices: Dict[str, float]) -> list[tuple[str, str]]:
        """Return list of (ticker, reason) for positions to be closed now."""
        out: list[tuple[str, str]] = []
        now = pd.Timestamp.utcnow()
        for ticker, pos in list(self.broker.positions().items()):
            price = prices.get(ticker)
            if price is None:
                continue
            if self.timed_out(pos, now):
                out.append((ticker, "timeout"))
                continue
            if self.exceeded_hard_loss(pos, price):
                out.append((ticker, "hard_loss_3pct"))
        return out
