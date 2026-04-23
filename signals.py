"""Multi-timeframe signal generation with technical indicators."""

import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """Trading signal."""
    ticker: str
    direction: str  # 'long' or 'short'
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    sentiment_score: float
    on_chain_confirmation: Optional[str] = None
    reason: str = ""
    timestamp: Optional[datetime] = None


class SignalGenerator:
    """Generate trading signals from price data."""

    def __init__(self):
        self.cache = {}  # Cache for OHLCV data

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return ta.ema(prices, length=period)

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index."""
        return ta.rsi(prices, length=period)

    def calculate_macd(self, prices: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD (12, 26, 9)."""
        macd_result = ta.macd(prices, fast=12, slow=26, signal=9)
        return macd_result.iloc[:, 0], macd_result.iloc[:, 1], macd_result.iloc[:, 2]

    def calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        return ta.atr(high=high, low=low, close=close, length=period)

    def find_support_resistance(self, prices: pd.Series, lookback: int = 20) -> Tuple[float, float]:
        """
        Find support and resistance levels using recent high/low.

        Args:
            prices: Price series (OHLC data)
            lookback: Number of periods to look back

        Returns:
            (support, resistance) levels
        """
        if len(prices) < lookback:
            return prices.iloc[-1], prices.iloc[-1]

        recent = prices.iloc[-lookback:]
        support = recent.min()
        resistance = recent.max()

        return float(support), float(resistance)

    def generate_signal(
        self,
        ticker: str,
        ohlcv_4h: pd.DataFrame,  # 4-hour candles
        ohlcv_1h: pd.DataFrame,  # 1-hour candles
        ohlcv_15m: pd.DataFrame,  # 15-minute candles
        sentiment_score: float = 0.0,
        on_chain_signal: Optional[str] = None,
    ) -> Optional[Signal]:
        """
        Generate signal from multi-timeframe data.

        Args:
            ticker: Ticker symbol
            ohlcv_4h: 4-hour OHLCV data (at least 100 candles)
            ohlcv_1h: 1-hour OHLCV data (at least 50 candles)
            ohlcv_15m: 15-minute OHLCV data (at least 20 candles)
            sentiment_score: [-1, +1] sentiment from news
            on_chain_signal: Optional on-chain confirmation (e.g., "smart_money_buy")

        Returns:
            Signal if conditions met, None otherwise
        """
        # Validate data
        if len(ohlcv_4h) < 100 or len(ohlcv_1h) < 50 or len(ohlcv_15m) < 20:
            logger.warning(f"{ticker}: Insufficient data for signal generation")
            return None

        # 1. Macro trend (4H EMA)
        ema_20_4h = self.calculate_ema(ohlcv_4h["close"], 20).iloc[-1]
        ema_50_4h = self.calculate_ema(ohlcv_4h["close"], 50).iloc[-1]
        ema_200_4h = self.calculate_ema(ohlcv_4h["close"], 200).iloc[-1]

        current_price_4h = ohlcv_4h["close"].iloc[-1]
        trend = "up" if ema_20_4h > ema_50_4h else "down"

        # 2. Momentum (1H RSI + MACD)
        rsi_1h = self.calculate_rsi(ohlcv_1h["close"], period=14).iloc[-1]
        macd_line_1h, macd_signal_1h, macd_hist_1h = self.calculate_macd(ohlcv_1h["close"])
        macd_hist_value = macd_hist_1h.iloc[-1]

        # RSI should not be overbought/oversold, MACD histogram should be positive
        momentum_ok = (30 < rsi_1h < 70) and (macd_hist_value > 0)

        # 3. Entry (15M breakout)
        atr_15m = self.calculate_atr(
            ohlcv_15m["high"], ohlcv_15m["low"], ohlcv_15m["close"], period=14
        ).iloc[-1]

        current_price_15m = ohlcv_15m["close"].iloc[-1]
        support_15m, resistance_15m = self.find_support_resistance(ohlcv_15m["close"], lookback=20)

        breakout_up = current_price_15m > resistance_15m
        breakout_down = current_price_15m < support_15m

        # 4. Sentiment check (don't trade very bearish)
        sentiment_ok = sentiment_score > -0.5

        # 5. Generate signal if conditions met
        if momentum_ok and (breakout_up or breakout_down) and sentiment_ok:
            direction = "long" if breakout_up else "short"

            if direction == "long":
                entry_price = current_price_15m
                stop_loss = support_15m - (atr_15m * 0.5)
                tp1 = entry_price + (atr_15m * 1.0)  # 1:1 R:R
                tp2 = entry_price + (atr_15m * 2.0)  # 1:2 R:R
            else:  # short
                entry_price = current_price_15m
                stop_loss = resistance_15m + (atr_15m * 0.5)
                tp1 = entry_price - (atr_15m * 1.0)
                tp2 = entry_price - (atr_15m * 2.0)

            reason = (
                f"EMA {'uptrend' if trend == 'up' else 'downtrend'} "
                f"(20:{ema_20_4h:.0f} > 50:{ema_50_4h:.0f}) + "
                f"RSI momentum {rsi_1h:.0f} + "
                f"{'breakout' if breakout_up else 'breakdown'} @ {current_price_15m:.2f} + "
                f"sentiment {sentiment_score:.2f}"
            )

            if on_chain_signal:
                reason += f" + {on_chain_signal}"

            signal = Signal(
                ticker=ticker,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit_1=tp1,
                take_profit_2=tp2,
                sentiment_score=sentiment_score,
                on_chain_confirmation=on_chain_signal,
                reason=reason,
                timestamp=datetime.utcnow(),
            )

            logger.info(f"Signal generated for {ticker}: {direction.upper()} @ {entry_price:.2f}")
            return signal

        logger.debug(
            f"{ticker}: No signal (trend={trend}, momentum_ok={momentum_ok}, "
            f"breakout={breakout_up or breakout_down}, sentiment_ok={sentiment_ok})"
        )
        return None

    def confirm_trend(self, ohlcv: pd.DataFrame, period: int = 20) -> str:
        """
        Confirm trend direction.

        Returns:
            'up', 'down', or 'sideways'
        """
        if len(ohlcv) < period:
            return "sideways"

        ema_fast = self.calculate_ema(ohlcv["close"], period // 2).iloc[-1]
        ema_slow = self.calculate_ema(ohlcv["close"], period).iloc[-1]

        if ema_fast > ema_slow:
            return "up"
        elif ema_fast < ema_slow:
            return "down"
        else:
            return "sideways"


# Global instance
signal_generator = SignalGenerator()
