"""Tests for the live Hyperliquid order client (mocked SDK)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from eth_account import Account


@pytest.fixture
def keypair():
    """Fresh deterministic key for each test (never used on mainnet)."""
    acct = Account.create()
    return acct.address, acct.key.hex()


def _ok(oid: int) -> dict:
    """Mock 'order' response shaped like Hyperliquid's real API."""
    return {"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": oid}}]}}}


def _err(msg: str) -> dict:
    return {"status": "ok", "response": {"data": {"statuses": [{"error": msg}]}}}


@pytest.fixture
def mocked_sdk():
    # Patch where the symbols are LOOKED UP (inside our module), not the
    # original location — the names were already imported by name.
    with patch("JARBIS_Crypto.hyperliquid_exchange.Exchange") as MockExchange, \
         patch("JARBIS_Crypto.hyperliquid_exchange.Info") as MockInfo:
        ex = MagicMock()
        info = MagicMock()
        MockExchange.return_value = ex
        MockInfo.return_value = info
        yield ex, info


def test_address_must_match_private_key(keypair):
    addr, key = keypair
    from JARBIS_Crypto.hyperliquid_exchange import HyperliquidExchange
    with pytest.raises(ValueError, match="does not derive"):
        HyperliquidExchange(
            wallet_address="0x" + "00" * 20,  # wrong address
            private_key=key,
            testnet=True,
        )


def test_place_bracketed_order_places_four_legs(mocked_sdk, keypair):
    ex, info = mocked_sdk
    addr, key = keypair
    ex.order.side_effect = [_ok(101), _ok(102), _ok(103), _ok(104)]

    from JARBIS_Crypto.hyperliquid_exchange import HyperliquidExchange
    client = HyperliquidExchange(addr, key, testnet=True)

    result = asyncio.run(client.place_bracketed_order(
        coin="BTC", is_buy=True, qty=0.01,
        entry_px=65000, sl_px=64000, tp1_px=66000, tp2_px=67000,
        leverage=2,
    ))

    assert result.ok is True
    assert result.entry_oid == 101
    assert result.sl_oid == 102
    assert result.tp1_oid == 103
    assert result.tp2_oid == 104

    # Leverage was set BEFORE the entry
    ex.update_leverage.assert_called_once_with(2, "BTC")

    # 4 calls in order: entry, SL, TP1, TP2 (close side = sell for a long)
    assert ex.order.call_count == 4
    calls = ex.order.call_args_list

    # entry
    args = calls[0].args
    assert args[0] == "BTC" and args[1] is True and args[2] == 0.01 and args[3] == 65000
    assert args[4] == {"limit": {"tif": "Gtc"}}
    assert args[5] is False  # reduce_only

    # SL: opposite side, full size, market trigger, reduce_only
    args = calls[1].args
    assert args[0] == "BTC" and args[1] is False and args[2] == 0.01 and args[3] == 64000
    assert args[4] == {"trigger": {"triggerPx": 64000, "isMarket": True, "tpsl": "sl"}}
    assert args[5] is True

    # TP1: half size, limit trigger, reduce_only
    args = calls[2].args
    assert args[0] == "BTC" and args[1] is False
    assert args[2] == pytest.approx(0.005)
    assert args[4] == {"trigger": {"triggerPx": 66000, "isMarket": False, "tpsl": "tp"}}
    assert args[5] is True

    # TP2: remaining half
    args = calls[3].args
    assert args[2] == pytest.approx(0.005)
    assert args[4] == {"trigger": {"triggerPx": 67000, "isMarket": False, "tpsl": "tp"}}
    assert args[5] is True


def test_short_entry_uses_buy_side_for_protection_legs(mocked_sdk, keypair):
    """For a short, the SL/TP legs must be BUY (close-side) reduce-only."""
    ex, info = mocked_sdk
    addr, key = keypair
    ex.order.side_effect = [_ok(1), _ok(2), _ok(3), _ok(4)]

    from JARBIS_Crypto.hyperliquid_exchange import HyperliquidExchange
    client = HyperliquidExchange(addr, key, testnet=True)
    asyncio.run(client.place_bracketed_order(
        coin="ETH", is_buy=False, qty=0.5,
        entry_px=3000, sl_px=3050, tp1_px=2950, tp2_px=2900, leverage=3,
    ))

    sides = [c.args[1] for c in ex.order.call_args_list]
    assert sides == [False, True, True, True]


def test_failed_leg_triggers_rollback_and_returns_error(mocked_sdk, keypair):
    """If TP1 fails after entry+SL succeed, cancel-all-for-coin runs."""
    ex, info = mocked_sdk
    addr, key = keypair
    ex.order.side_effect = [_ok(101), _ok(102), _err("price out of range"), _ok(104)]
    info.open_orders.return_value = [
        {"coin": "BTC", "oid": 101},
        {"coin": "BTC", "oid": 102},
        {"coin": "ETH", "oid": 999},  # different coin — must NOT be cancelled
    ]

    from JARBIS_Crypto.hyperliquid_exchange import HyperliquidExchange
    client = HyperliquidExchange(addr, key, testnet=True)
    result = asyncio.run(client.place_bracketed_order(
        coin="BTC", is_buy=True, qty=0.01,
        entry_px=65000, sl_px=64000, tp1_px=66000, tp2_px=67000, leverage=2,
    ))

    assert result.ok is False
    assert "price out of range" in result.error

    # Rollback only cancelled the BTC orders
    ex.bulk_cancel.assert_called_once()
    cancel_arg = ex.bulk_cancel.call_args.args[0]
    assert {c["oid"] for c in cancel_arg} == {101, 102}
    assert all(c["coin"] == "BTC" for c in cancel_arg)


def test_balance_and_positions_normalizes_user_state(mocked_sdk, keypair):
    ex, info = mocked_sdk
    addr, key = keypair
    info.user_state.return_value = {
        "marginSummary": {"accountValue": "1234.56", "totalMarginUsed": "100"},
        "withdrawable": "1100",
        "assetPositions": [
            {"position": {
                "coin": "BTC", "szi": "0.01", "entryPx": "65000",
                "unrealizedPnl": "5.5", "leverage": {"value": 2},
                "liquidationPx": "60000", "marginUsed": "325",
            }},
            {"position": {
                "coin": "SOL", "szi": "-12.0", "entryPx": "150",
                "unrealizedPnl": "-3.0", "leverage": {"value": 3},
                "liquidationPx": "180", "marginUsed": "600",
            }},
            {"position": {"coin": "DOGE", "szi": "0"}},  # zero-size, must be filtered
        ],
    }

    from JARBIS_Crypto.hyperliquid_exchange import HyperliquidExchange
    client = HyperliquidExchange(addr, key, testnet=True)
    snap = asyncio.run(client.get_balance_and_positions())

    assert snap["account_value"] == pytest.approx(1234.56)
    assert snap["withdrawable"] == pytest.approx(1100)
    coins = {p["coin"]: p for p in snap["positions"]}
    assert set(coins) == {"BTC", "SOL"}  # zero-size DOGE dropped
    assert coins["BTC"]["size"] == pytest.approx(0.01)
    assert coins["SOL"]["size"] == pytest.approx(-12.0)  # short stays negative
    assert coins["SOL"]["leverage"] == 3
