from dataclasses import dataclass, field
from typing import Optional, Tuple
from datetime import datetime
from enum import Enum
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Signal:
    ticker: str
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    sentiment_score: float
    on_chain_confirmation: bool
    reason: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class TechnicalIndicators:
    """Calculate technical indicators."""

    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return data.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index."""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD (Moving Average Convergence Divergence)."""
        ema_fast = data.ewm(span=fast, adjust=False).mean()
        ema_slow = data.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Average True Range."""
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    @staticmethod
    def support_resistance(data: pd.Series, lookback: int = 20) -> Tuple[float, float]:
        """Simple support/resistance from high/low."""
        recent = data.tail(lookback)
        support = recent.min()
        resistance = recent.max()
        return support, resistance


class SignalGenerator:
    """Multi-timeframe signal generation."""

    def __init__(self):
        self.ta = TechnicalIndicators()

    def generate_signal(
        self,
        ticker: str,
        candles_4h: pd.DataFrame,
        candles_1h: pd.DataFrame,
        candles_15m: pd.DataFrame,
        sentiment_score: float,
        on_chain_confirmation: bool,
    ) -> Optional[Signal]:
        """
        Generate signal from multi-timeframe analysis.

        candles format: {open, high, low, close, volume}
        """
        if candles_4h.empty or candles_1h.empty or candles_15m.empty:
            return None

        # 1. Macro trend (4H EMA)
        ema_20_4h = self.ta.ema(candles_4h["close"], 20).iloc[-1]
        ema_50_4h = self.ta.ema(candles_4h["close"], 50).iloc[-1]
        trend = "up" if ema_20_4h > ema_50_4h else "down"

        # 2. Momentum (1H RSI + MACD)
        rsi_1h = self.ta.rsi(candles_1h["close"], 14).iloc[-1]
        macd_line, signal_line, histogram = self.ta.macd(candles_1h["close"])
        macd_histogram = histogram.iloc[-1]

        momentum_ok = (30 < rsi_1h < 70) and (macd_histogram > 0)

        # 3. Entry trigger (15M breakout + ATR)
        atr_15m = self.ta.atr(candles_15m["high"], candles_15m["low"], candles_15m["close"], 14)
        support, resistance = self.ta.support_resistance(candles_15m["close"], 20)

        current_price = candles_15m["close"].iloc[-1]
        atr_value = atr_15m.iloc[-1] if not pd.isna(atr_15m.iloc[-1]) else 0
        tp1_distance = atr_value * 1.0
        tp2_distance = atr_value * 2.0

        # Check for breakout
        breakout_up = (current_price > resistance) and (trend == "up")
        breakout_down = (current_price < support) and (trend == "down")

        # 4. Generate signal if conditions met
        if momentum_ok and (breakout_up or breakout_down) and sentiment_score > -0.3:
            direction = Direction.LONG if breakout_up else Direction.SHORT

            if direction == Direction.LONG:
                stop_loss = support
                tp1 = current_price + tp1_distance
                tp2 = current_price + tp2_distance
            else:
                stop_loss = resistance
                tp1 = current_price - tp1_distance
                tp2 = current_price - tp2_distance

            reason = (
                f"EMA trend ({trend}) + RSI momentum ({rsi_1h:.0f}) + "
                f"breakout {'above' if direction == Direction.LONG else 'below'} "
                f"{('resistance' if direction == Direction.LONG else 'support')} "
                f"+ sentiment {sentiment_score:.2f} "
                f"{'+ on-chain confirm' if on_chain_confirmation else ''}"
            )

            return Signal(
                ticker=ticker,
                direction=direction,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit_1=tp1,
                take_profit_2=tp2,
                sentiment_score=sentiment_score,
                on_chain_confirmation=on_chain_confirmation,
                reason=reason,
            )

        return None
