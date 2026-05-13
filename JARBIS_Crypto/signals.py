"""Multi-timeframe signal generation.

Pure numpy/pandas technical indicators (no ta-lib dependency) so the
bot runs in minimal Python environments. Signals are produced by combining
a 4H trend filter, a 1H momentum filter, and a 15m breakout trigger.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .broker import Broker

log = logging.getLogger(__name__)


# --------- Indicators ---------

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi_val = 100 - (100 / (1 + rs))
    # avg_loss==0 with gains -> RSI saturates at 100
    rsi_val = rsi_val.replace([np.inf, -np.inf], 100.0)
    # both flat -> neutral 50
    rsi_val = rsi_val.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return rsi_val.fillna(50.0)


@dataclass
class MACD:
    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> MACD:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return MACD(macd=macd_line, signal=signal_line, histogram=macd_line - signal_line)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def support_resistance(df: pd.DataFrame, window: int = 20) -> tuple[float, float]:
    """Rolling high / low of last ``window`` bars."""
    if len(df) < window:
        return float(df["low"].min()), float(df["high"].max())
    tail = df.iloc[-window:]
    return float(tail["low"].min()), float(tail["high"].max())


# --------- Signal ---------

@dataclass
class Signal:
    ticker: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    atr_15m: float
    rsi_1h: float
    trend_4h: str
    sentiment_score: float = 0.0
    on_chain_confirmation: bool = False
    reason: str = ""

    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.stop_loss)


# --------- Generator ---------

class SignalEngine:
    def __init__(self, broker: Broker):
        self.broker = broker

    async def _frames(self, ticker: str) -> dict[str, pd.DataFrame]:
        frames = {}
        for tf in ("4h", "1h", "15m"):
            df = await self.broker.get_candles(ticker, tf, limit=200)
            if df.empty or len(df) < 50:
                raise RuntimeError(f"insufficient candles for {ticker} {tf}")
            frames[tf] = df
        return frames

    async def generate(
        self,
        ticker: str,
        sentiment_score: float = 0.0,
        on_chain_confirmation: bool = False,
    ) -> Optional[Signal]:
        frames = await self._frames(ticker)

        # ---- 4H trend ----
        close_4h = frames["4h"]["close"]
        ema20_4h = ema(close_4h, 20).iloc[-1]
        ema50_4h = ema(close_4h, 50).iloc[-1]
        trend_up = ema20_4h > ema50_4h
        trend = "up" if trend_up else "down"

        # ---- 1H momentum ----
        close_1h = frames["1h"]["close"]
        rsi_1h = float(rsi(close_1h, 14).iloc[-1])
        macd_1h = macd(close_1h)
        macd_hist = float(macd_1h.histogram.iloc[-1])
        momentum_ok = 30 < rsi_1h < 70

        # ---- 15m entry ----
        df_15m = frames["15m"]
        current_price = float(df_15m["close"].iloc[-1])
        atr_15m = float(atr(df_15m, 14).iloc[-1])
        support, resistance = support_resistance(df_15m, window=20)

        # breakouts must align with macro trend and momentum direction
        breakout_up = trend_up and current_price > resistance and macd_hist > 0
        breakout_down = (not trend_up) and current_price < support and macd_hist < 0

        if not momentum_ok:
            return None
        if not (breakout_up or breakout_down):
            return None
        # Negative sentiment veto
        if sentiment_score < -0.3:
            log.info("%s: sentiment %.2f below -0.3, skipping", ticker, sentiment_score)
            return None

        direction = "long" if breakout_up else "short"
        if direction == "long":
            stop_loss = min(support, current_price - atr_15m * 1.0)
            tp1 = current_price + atr_15m * 1.5
            tp2 = current_price + atr_15m * 3.0
        else:
            stop_loss = max(resistance, current_price + atr_15m * 1.0)
            tp1 = current_price - atr_15m * 1.5
            tp2 = current_price - atr_15m * 3.0

        return Signal(
            ticker=ticker,
            direction=direction,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            atr_15m=atr_15m,
            rsi_1h=rsi_1h,
            trend_4h=trend,
            sentiment_score=sentiment_score,
            on_chain_confirmation=on_chain_confirmation,
            reason=(
                f"4H {trend} + RSI1h={rsi_1h:.1f} + "
                f"{'breakout' if breakout_up else 'breakdown'} "
                f"@{current_price:.2f}"
                + (" + on-chain" if on_chain_confirmation else "")
            ),
        )

    async def build_signal_from_alert(
        self,
        ticker: str,
        direction: str,
        sentiment_score: float = 0.0,
        on_chain_confirmation: bool = False,
    ) -> Optional[Signal]:
        """Construct a Signal from an external trigger (e.g. TradingView VMC).

        We trust the alert's direction — no veto on RSI/MACD/EMA — but
        we still derive ATR-scaled stops + TPs from the current 15m
        candles so the bracket placed by the broker is properly sized.
        """
        if direction not in ("long", "short"):
            return None
        df = await self.broker.get_candles(ticker, "15m", limit=80)
        if df.empty or len(df) < 30:
            return None
        current_price = float(df["close"].iloc[-1])
        atr_15m = float(atr(df, 14).iloc[-1])
        if atr_15m <= 0:
            return None
        support, resistance = support_resistance(df, window=20)
        if direction == "long":
            stop_loss = min(support, current_price - atr_15m * 1.0)
            tp1 = current_price + atr_15m * 1.5
            tp2 = current_price + atr_15m * 3.0
        else:
            stop_loss = max(resistance, current_price + atr_15m * 1.0)
            tp1 = current_price - atr_15m * 1.5
            tp2 = current_price - atr_15m * 3.0

        # Trend label is informational only here.
        close_4h = (await self.broker.get_candles(ticker, "4h", limit=80))["close"]
        if not close_4h.empty:
            trend = "up" if ema(close_4h, 20).iloc[-1] > ema(close_4h, 50).iloc[-1] else "down"
        else:
            trend = "unknown"

        return Signal(
            ticker=ticker,
            direction=direction,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            atr_15m=atr_15m,
            rsi_1h=0.0,  # not consulted for TV-driven entries
            trend_4h=trend,
            sentiment_score=sentiment_score,
            on_chain_confirmation=on_chain_confirmation,
            reason=f"tradingview alert · trend4h={trend}",
        )

    # Convenience for the leverage module: ATR ratio on 15m.
    async def atr_ratio(self, ticker: str) -> float:
        df = await self.broker.get_candles(ticker, "15m", limit=80)
        if df.empty or len(df) < 55:
            return 1.0
        atr_short = float(atr(df, 20).iloc[-1])
        atr_long = float(atr(df, 50).iloc[-1])
        if atr_long <= 0:
            return 1.0
        return atr_short / atr_long
