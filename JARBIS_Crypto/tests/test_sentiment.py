"""Unit tests for sentiment scoring + ticker tagging."""
from __future__ import annotations

import pytest

from JARBIS_Crypto.sentiment import SentimentEngine, score_text, tag_ticker


def test_positive_keywords_score_high():
    s = score_text("Bitcoin surges to record high on ETF approval")
    assert s > 0.3


def test_negative_keywords_score_low():
    s = score_text("Major exchange hacked; BTC plunges on liquidation cascade")
    assert s < -0.3


def test_neutral_text_scores_zero():
    assert score_text("The weather is mild today") == 0.0


def test_tag_ticker_detects_bitcoin():
    assert tag_ticker("Bitcoin rallies to new high") == "BTC"


def test_tag_ticker_detects_solana():
    assert tag_ticker("Solana network upgrade launches today") == "SOL"


def test_tag_ticker_no_match():
    assert tag_ticker("Stocks wobble on Fed meeting") is None


def test_engine_injects_manual_headline():
    eng = SentimentEngine()
    sh = eng.inject_manual("BTC", "BTC surges on approval")
    assert sh.ticker == "BTC"
    assert sh.score > 0.3
    assert eng.score_for("BTC") > 0.3


def test_engine_returns_zero_for_unknown_ticker():
    eng = SentimentEngine()
    assert eng.score_for("DOGE") == 0.0


def test_manual_score_overrides_heuristic():
    eng = SentimentEngine()
    eng.inject_manual("ETH", "Something neutral", score=0.9)
    assert eng.score_for("ETH") == pytest.approx(0.9)
