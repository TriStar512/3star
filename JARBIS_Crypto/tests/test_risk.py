"""Unit tests for position sizing + risk gates."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from JARBIS_Crypto.config import Settings
from JARBIS_Crypto.risk import RiskManager


@pytest.fixture
def settings() -> Settings:
    return Settings(
        portfolio_size_usd=1000,
        max_loss_pct=0.02,
        max_leverage=3.0,
        base_leverage=2.0,
        max_position_size_pct=0.05,
        max_concurrent_trades=4,
    )


@pytest.fixture
def broker() -> MagicMock:
    b = MagicMock()
    b.cash.return_value = 1000.0
    b.positions.return_value = {}
    b.available_margin.return_value = 1000.0
    return b


def test_size_position_sets_quantity_to_max_loss(settings, broker):
    rm = RiskManager(broker, settings)
    # distance=50 -> risk-first qty=0.4; notional=$40 < cap ($100 at 2x)
    size = rm.size_position(entry_price=100.0, stop_loss=50.0, leverage=2.0)
    assert size.quantity == pytest.approx(0.4)
    assert size.max_loss_usd == pytest.approx(20.0)
    assert size.capped_reason == ""


def test_size_position_caps_at_max_notional(settings, broker):
    rm = RiskManager(broker, settings)
    # tight stop -> would imply huge qty, should be capped at 5% * lev * portfolio
    size = rm.size_position(entry_price=100.0, stop_loss=99.9, leverage=2.0)
    assert size.capped_reason == "max_position_size_pct"
    # max_notional = 1000 * 0.05 * 2 = 100 -> qty = 1
    assert size.quantity == pytest.approx(1.0)


def test_can_open_trade_respects_max_concurrent(settings, broker):
    rm = RiskManager(broker, settings)
    broker.positions.return_value = {f"T{i}": object() for i in range(4)}
    ok, reason = rm.can_open_trade()
    assert not ok
    assert "max concurrent" in reason


def test_set_max_loss_pct_valid(settings, broker):
    rm = RiskManager(broker, settings)
    rm.set_max_loss_pct(0.01)
    assert rm.max_loss_pct == 0.01


def test_set_max_loss_pct_rejects_out_of_range(settings, broker):
    rm = RiskManager(broker, settings)
    with pytest.raises(ValueError):
        rm.set_max_loss_pct(0.5)
    with pytest.raises(ValueError):
        rm.set_max_loss_pct(0)


def test_stop_loss_at_entry_raises(settings, broker):
    rm = RiskManager(broker, settings)
    with pytest.raises(ValueError):
        rm.size_position(entry_price=100, stop_loss=100, leverage=2.0)


def test_portfolio_heat_zero_when_no_positions(settings, broker):
    rm = RiskManager(broker, settings)
    assert rm.portfolio_heat() == 0.0
