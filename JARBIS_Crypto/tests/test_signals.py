"""Unit tests for technical indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from JARBIS_Crypto.signals import atr, ema, macd, rsi, support_resistance


def _series(values):
    return pd.Series(values, dtype=float)


def test_ema_matches_manual():
    s = _series([1, 2, 3, 4, 5])
    out = ema(s, 3)
    assert out.iloc[-1] == pytest.approx(s.ewm(span=3, adjust=False).mean().iloc[-1])


def test_rsi_bounds_in_0_100():
    s = _series(np.cumsum(np.random.default_rng(0).normal(0, 1, 200)) + 100)
    r = rsi(s, 14)
    assert r.min() >= 0.0 and r.max() <= 100.0


def test_rsi_strong_uptrend_is_high():
    s = _series(range(1, 101))
    assert rsi(s, 14).iloc[-1] > 70


def test_rsi_strong_downtrend_is_low():
    s = _series(range(100, 0, -1))
    assert rsi(s, 14).iloc[-1] < 30


def test_macd_histogram_positive_on_uptrend():
    s = _series(range(1, 101))
    m = macd(s)
    assert m.histogram.iloc[-1] > 0


def test_atr_matches_length():
    df = pd.DataFrame({
        "high": [1.1, 1.2, 1.3, 1.4, 1.5] * 10,
        "low":  [0.9, 1.0, 1.1, 1.2, 1.3] * 10,
        "close":[1.0, 1.1, 1.2, 1.3, 1.4] * 10,
    })
    a = atr(df, 14)
    assert len(a) == len(df)
    assert a.iloc[-1] > 0


def test_support_resistance_reports_min_max():
    df = pd.DataFrame({
        "high": [1, 2, 3, 4, 5],
        "low":  [0, 1, 2, 3, 4],
        "close":[1, 2, 3, 4, 5],
    })
    support, resistance = support_resistance(df, window=3)
    assert support == 2.0
    assert resistance == 5.0
