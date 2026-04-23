#!/usr/bin/env python3
"""
JARBIS Crypto 24/7 Trading Bot - Main Entry Point

Automated trading bot using Vilkov 0DTE framework adapted for crypto,
with dynamic leverage scaling based on sentiment and volatility.
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

from config import settings
from broker import BybitBroker, BinanceBroker
from signals import SignalGenerator, Direction
from sentiment import SentimentBuffer, calculate_sentiment, SentimentInput
from on_chain import OnChainAnalyzer
from leverage import calculate_dynamic_leverage, LeverageInput
from risk import calculate_position_size, check_emergency_conditions
from orders import OrderManager, ExitReason
from logger import TradeLogger
from dashboard import Dashboard
from webhooks import WebhookServer
from utils import retry_async, utc_now, format_usd, format_crypto, format_pct

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("jarbis.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class JarbisTradingBot:
    """Main trading bot orchestration."""

    def __init__(self):
        self.broker = BybitBroker()
        self.signal_gen = SignalGenerator()
        self.sentiment_buffer = SentimentBuffer(ttl_minutes=60)
        self.on_chain = OnChainAnalyzer()
        self.order_manager = OrderManager(position_timeout_minutes=settings.position_timeout_minutes)
        self.trade_logger = TradeLogger(settings.log_db)
        self.dashboard = Dashboard()
        self.webhook_server: Optional[WebhookServer] = None

        self.portfolio_balance = settings.portfolio_size_usd
        self.paper_trade = settings.paper_trade
        self.is_running = False

    async def initialize(self) -> None:
        """Initialize bot and connections."""
        logger.info(
            f"Initializing JARBIS Bot | "
            f"Portfolio: {format_usd(self.portfolio_balance)} | "
            f"Mode: {'PAPER' if self.paper_trade else 'LIVE'}"
        )

        await self.broker.init_session()

        # Start webhook server
        self.webhook_server = WebhookServer(
            port=settings.webhook_port,
            secret=settings.webhook_secret,
            on_news_received=self._on_news_received,
            on_alert_received=self._on_alert_received,
        )
        self.webhook_server.start()

        self.dashboard.print_banner()
        self.dashboard.print_info(f"Initialized in {'PAPER' if self.paper_trade else 'LIVE'} mode")

    async def shutdown(self) -> None:
        """Shutdown bot and cleanup."""
        logger.info("Shutting down JARBIS Bot")
        self.is_running = False

        if self.webhook_server:
            self.webhook_server.stop()

        if self.broker.session:
            await self.broker.close_session()

        self.trade_logger.close()
        logger.info("Bot shutdown complete")

    async def run(self) -> None:
        """Main trading loop."""
        self.is_running = True
        logger.info("Starting main trading loop")

        scan_interval = 60  # Scan for signals every 60 seconds
        last_scan = datetime.utcnow() - timedelta(seconds=scan_interval)

        try:
            while self.is_running:
                now = utc_now()

                # Periodic signal scanning
                if (now - last_scan).total_seconds() >= scan_interval:
                    await self._scan_for_signals()
                    last_scan = now

                # Monitor open positions
                await self._monitor_open_positions()

                # Check emergency conditions
                await self._check_emergency_stop()

                await asyncio.sleep(5)  # Check every 5 seconds

        except KeyboardInterrupt:
            logger.info("Received shutdown signal (Ctrl+C)")
        except Exception as e:
            logger.error(f"Fatal error in trading loop: {e}", exc_info=True)
            self.dashboard.print_error(f"Trading loop error: {e}")
        finally:
            await self.shutdown()

    async def _scan_for_signals(self) -> None:
        """Scan all trading pairs for buy/sell signals."""
        logger.debug("Scanning for signals...")

        for ticker in settings.trading_pairs:
            try:
                # Fetch candles
                candles_4h = await retry_async(self.broker.get_candles, ticker, "4", 100)
                candles_1h = await retry_async(self.broker.get_candles, ticker, "1", 100)
                candles_15m = await retry_async(self.broker.get_candles, ticker, "15", 100)

                if not candles_4h or not candles_1h or not candles_15m:
                    logger.warning(f"Insufficient candle data for {ticker}")
                    continue

                # Convert to DataFrame for indicator calculation
                df_4h = self._candles_to_df(candles_4h)
                df_1h = self._candles_to_df(candles_1h)
                df_15m = self._candles_to_df(candles_15m)

                # Get sentiment
                sentiment_headlines = self.sentiment_buffer.get_active_headlines(ticker)
                sentiment = calculate_sentiment(SentimentInput(ticker=ticker, headlines=sentiment_headlines))

                # Get on-chain signals
                on_chain_signals = await self.on_chain.get_all_signals(ticker)
                on_chain_confirmation = self.on_chain.is_bullish_on_chain(ticker)

                # Generate signal
                signal = self.signal_gen.generate_signal(
                    ticker=ticker,
                    candles_4h=df_4h,
                    candles_1h=df_1h,
                    candles_15m=df_15m,
                    sentiment_score=sentiment.score,
                    on_chain_confirmation=on_chain_confirmation,
                )

                if signal:
                    await self._execute_signal(signal, sentiment.score)

            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}", exc_info=True)

    async def _execute_signal(self, signal, sentiment_score: float) -> None:
        """Execute a buy/sell signal."""
        logger.info(f"Executing signal: {signal.direction.value.upper()} {signal.ticker}")

        self.dashboard.print_signal_alert(
            signal.ticker,
            signal.direction.value,
            signal.entry_price,
            sentiment_score,
            signal.reason,
        )

        try:
            # Get current balance
            balance = await self.broker.get_balance()
            current_balance = balance.get("USDT", self.portfolio_balance)

            # Calculate dynamic leverage
            atr_20 = 100.0  # Simplified: would fetch from candles
            atr_50 = 90.0

            portfolio_heat = len(self.order_manager.open_trades) / 4.0  # Max 4 concurrent
            leverage_input = LeverageInput(
                sentiment_score=sentiment_score,
                atr_20=atr_20,
                atr_50=atr_50,
                portfolio_heat=portfolio_heat,
            )
            leverage_output = calculate_dynamic_leverage(leverage_input)

            # Position sizing
            position = calculate_position_size(
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,
                leverage=leverage_output.leverage,
                current_balance=current_balance,
            )

            # Place order
            order = await self.broker.place_limit_order(
                ticker=signal.ticker,
                direction=signal.direction.value,
                quantity=position.adjusted_for_leverage,
                price=signal.entry_price,
                leverage=leverage_output.leverage,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
                take_profit_2=signal.take_profit_2,
            )

            # Track trade
            from orders import TradeEntry
            trade_entry = TradeEntry(
                order_id=order.order_id,
                ticker=signal.ticker,
                direction=signal.direction.value,
                entry_price=signal.entry_price,
                quantity=position.adjusted_for_leverage,
                leverage=leverage_output.leverage,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
                take_profit_2=signal.take_profit_2,
                entry_time=utc_now(),
            )
            self.order_manager.add_entry(trade_entry)

            self.dashboard.print_order_status(
                order.order_id,
                order.ticker,
                order.direction,
                order.quantity,
                order.entry_price,
                order.status.value,
            )

        except Exception as e:
            logger.error(f"Error executing signal: {e}", exc_info=True)
            self.dashboard.print_error(f"Failed to execute signal: {e}")

    async def _monitor_open_positions(self) -> None:
        """Monitor open positions for TP/SL/timeout triggers."""
        if not self.order_manager.open_trades:
            return

        try:
            for order_id, trade in list(self.order_manager.open_trades.items()):
                # Get current price (simplified)
                current_price = 50000.0  # Would fetch from broker

                # Check TP1
                tp1_result = self.order_manager.check_tp1_trigger(order_id, current_price)
                if tp1_result:
                    await self._close_partial_position(trade, tp1_result[0], tp1_result[1])

                # Check TP2
                tp2_result = self.order_manager.check_tp2_trigger(order_id, current_price)
                if tp2_result:
                    await self._close_partial_position(trade, tp2_result[0], tp2_result[1])

                # Check trailing stop
                trailing_result = self.order_manager.check_trailing_stop(order_id, current_price)
                if trailing_result:
                    await self._close_partial_position(
                        trade, trailing_result[0], trailing_result[1], ExitReason.TRAILING_STOP
                    )

                # Check stop loss
                sl_result = self.order_manager.check_stop_loss(order_id, current_price)
                if sl_result:
                    await self._close_partial_position(
                        trade, sl_result[0], sl_result[1], ExitReason.STOP_LOSS
                    )

                # Check timeout
                timeout_result = self.order_manager.check_timeout(order_id)
                if timeout_result:
                    await self._close_partial_position(
                        trade, timeout_result[0], 50000.0, ExitReason.TIMEOUT
                    )

        except Exception as e:
            logger.error(f"Error monitoring positions: {e}", exc_info=True)

    async def _close_partial_position(
        self,
        trade,
        quantity: float,
        exit_price: float,
        exit_reason: ExitReason = ExitReason.TP1,
    ) -> None:
        """Close a portion of a position."""
        try:
            await self.broker.close_position(trade.ticker, quantity)

            # Record exit
            trade_exit = self.order_manager.close_position(
                trade.order_id, exit_price, exit_reason
            )

            if trade_exit:
                # Log to database
                self.trade_logger.log_trade(
                    trade_exit=trade_exit,
                    sentiment_score=trade.stop_loss,  # Placeholder
                    sentiment_label="neutral",
                    on_chain_signal="none",
                    paper_trade=self.paper_trade,
                )

                self.dashboard.print_trade_closed(trade_exit)

        except Exception as e:
            logger.error(f"Error closing position: {e}", exc_info=True)

    async def _check_emergency_stop(self) -> None:
        """Check for emergency stop conditions."""
        # Get current portfolio loss
        portfolio_loss = -0.01  # Placeholder

        should_close, reason = check_emergency_conditions(
            portfolio_loss_pct=portfolio_loss,
            iv_rank=0.5,  # Placeholder
        )

        if should_close:
            logger.critical(f"EMERGENCY STOP TRIGGERED: {reason}")
            self.dashboard.print_error(f"EMERGENCY STOP: {reason}")

            # Close all open positions
            for order_id in list(self.order_manager.open_trades.keys()):
                try:
                    trade = self.order_manager.open_trades[order_id]
                    await self._close_partial_position(
                        trade, trade.quantity, 50000.0, ExitReason.EMERGENCY
                    )
                except Exception as e:
                    logger.error(f"Error closing emergency position: {e}")

    def _candles_to_df(self, candles) -> pd.DataFrame:
        """Convert Candle objects to DataFrame."""
        data = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        return df

    def _on_news_received(self, ticker: str, headline: str, sentiment: float = None) -> None:
        """Webhook callback for manual news injection."""
        logger.info(f"News received: {ticker} | {headline}")
        self.sentiment_buffer.add_headline(ticker, headline)
        self.dashboard.print_info(f"News injected for {ticker}: {headline}")

    def _on_alert_received(self, data: dict) -> None:
        """Webhook callback for manual trading alerts."""
        logger.info(f"Alert received: {data}")
        # Handle manual trading commands
        # (Implementation depends on alert structure)


async def main():
    """Main entry point."""
    bot = JarbisTradingBot()

    try:
        await bot.initialize()
        await bot.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
        sys.exit(0)
