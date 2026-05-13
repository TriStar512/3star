"""Tests for the TradingView webhook integration."""
from __future__ import annotations

import json

import pytest

from JARBIS_Crypto.config import ALLOWED_COINS, Settings
from JARBIS_Crypto.tradingview import (
    TradingViewEvent,
    is_stale,
    normalize_ticker,
    parse_alert,
)
from JARBIS_Crypto.webhooks import WebhookServer


# -------- ticker normalization --------

@pytest.mark.parametrize("raw,expected", [
    ("BTC", "BTC"),
    ("BTCUSDT", "BTC"),
    ("BTCUSDT.P", "BTC"),
    ("BTCUSD", "BTC"),
    ("BTCPERP", "BTC"),
    ("BINANCE:BTCUSDT", "BTC"),
    ("BYBIT:BTCUSDT.P", "BTC"),
    ("HYPERLIQUID:BTC", "BTC"),
    ("eth", "ETH"),
    ("  doge  ", "DOGE"),
    ("DOGEUSDT", "DOGE"),
])
def test_normalize_ticker_accepts_common_forms(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("bad", ["", None, "$$$", "1234", "ABC/DEF"])
def test_normalize_ticker_rejects_garbage(bad):
    assert normalize_ticker(bad) is None


# -------- alert parsing --------

UNIVERSE = ALLOWED_COINS


def test_parse_alert_minimal_buy():
    ev = parse_alert(
        {"ticker": "BTCUSDT", "action": "buy"},
        allowed_tickers=UNIVERSE,
    )
    assert ev.ticker == "BTC"
    assert ev.direction == "long"


@pytest.mark.parametrize("action,expected_dir", [
    ("buy", "long"),
    ("long", "long"),
    ("sell", "short"),
    ("short", "short"),
    ("close", "close"),
    ("exit", "close"),
    ("flat", "close"),
])
def test_parse_alert_maps_actions_to_directions(action, expected_dir):
    ev = parse_alert({"ticker": "ETH", "action": action}, allowed_tickers=UNIVERSE)
    assert ev.direction == expected_dir


def test_parse_alert_keeps_indicator_signal_price():
    ev = parse_alert(
        {"ticker": "SOL", "action": "buy", "price": "175.4",
         "indicator": "vmc_cipher_b", "signal": "buy_diamond", "tf": "15"},
        allowed_tickers=UNIVERSE,
    )
    assert ev.price == pytest.approx(175.4)
    assert ev.indicator == "vmc_cipher_b"
    assert ev.signal == "buy_diamond"
    assert ev.timeframe == "15"


def test_parse_alert_rejects_unknown_ticker():
    with pytest.raises(ValueError, match="not in the trading universe"):
        parse_alert({"ticker": "PEPE", "action": "buy"}, allowed_tickers=UNIVERSE)


def test_parse_alert_rejects_unrecognized_ticker_form():
    with pytest.raises(ValueError, match="unrecognized ticker"):
        parse_alert({"ticker": "$$$", "action": "buy"}, allowed_tickers=UNIVERSE)


def test_parse_alert_rejects_bad_action():
    with pytest.raises(ValueError, match="unsupported action"):
        parse_alert({"ticker": "BTC", "action": "hold"}, allowed_tickers=UNIVERSE)


def test_parse_alert_rejects_non_dict_payload():
    with pytest.raises(ValueError, match="JSON object"):
        parse_alert("buy BTC now", allowed_tickers=UNIVERSE)


def test_is_stale_threshold():
    ev = TradingViewEvent(ticker="BTC", direction="long", received_at=0.0)
    assert is_stale(ev, max_age_seconds=60.0)


# -------- /tradingview HTTP endpoint --------

@pytest.fixture
def server():
    settings = Settings(webhook_secret="test-secret-please-rotate")
    s = WebhookServer(settings=settings)
    s.app.config["TESTING"] = True
    return s


def _post(server, body):
    client = server.app.test_client()
    return client.post(
        "/tradingview",
        data=json.dumps(body),
        content_type="application/json",
    )


def test_endpoint_rejects_bad_secret(server):
    r = _post(server, {"secret": "wrong", "ticker": "BTC", "action": "buy"})
    assert r.status_code == 401


def test_endpoint_rejects_bad_payload(server):
    r = _post(server, {"secret": "test-secret-please-rotate",
                       "ticker": "BTC", "action": "hold"})
    assert r.status_code == 400
    body = json.loads(r.data)
    assert "unsupported action" in body["error"]


def test_endpoint_enqueues_event_on_success(server):
    r = _post(server, {
        "secret": "test-secret-please-rotate",
        "ticker": "BINANCE:BTCUSDT",
        "action": "buy",
        "price": "65000",
        "indicator": "vmc_cipher_b",
        "signal": "buy_diamond",
    })
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["ok"] is True
    assert body["ticker"] == "BTC"
    assert body["direction"] == "long"

    events = server.drain()
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "tradingview"
    assert ev.payload["ticker"] == "BTC"
    assert ev.payload["direction"] == "long"
    assert ev.payload["price"] == 65000
    assert ev.payload["indicator"] == "vmc_cipher_b"


def test_endpoint_close_action_enqueues_close(server):
    r = _post(server, {
        "secret": "test-secret-please-rotate",
        "ticker": "ETHUSDT.P",
        "action": "exit",
    })
    assert r.status_code == 200
    events = server.drain()
    assert events[0].payload["direction"] == "close"
    assert events[0].payload["ticker"] == "ETH"
