"""Tests for config rules (top-10 universe enforcement)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from JARBIS_Crypto.config import ALLOWED_COINS, Settings


def test_allowed_coins_is_exactly_ten():
    assert len(ALLOWED_COINS) == 10
    assert set(ALLOWED_COINS) == {
        "BTC", "ETH", "BNB", "SOL", "XRP",
        "ADA", "DOGE", "AVAX", "LINK", "MATIC",
    }


def test_default_pairs_equals_top_ten():
    s = Settings()
    assert set(s.trading_pairs) == set(ALLOWED_COINS)


def test_subset_of_allowed_coins_accepted():
    s = Settings(trading_pairs=["BTC", "ETH"])
    assert s.trading_pairs == ["BTC", "ETH"]


def test_non_top_ten_coin_rejected():
    with pytest.raises(ValidationError) as exc:
        Settings(trading_pairs=["BTC", "PEPE"])
    assert "PEPE" in str(exc.value)


def test_csv_string_input_parsed_and_validated():
    s = Settings(trading_pairs="BTC,ETH,SOL")
    assert s.trading_pairs == ["BTC", "ETH", "SOL"]


def test_csv_string_with_disallowed_coin_rejected():
    with pytest.raises(ValidationError):
        Settings(trading_pairs="BTC,DOGE,SHIB")
