"""JARBIS Crypto - 24/7 Trading Bot Main Entry Point."""

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import settings
from broker import BybitClient, BinanceClient
from signals import signal_generator, Signal
from sentiment import sentiment_analyzer
from leverage import leverage_calc, LeverageParams
from risk import risk_manager
from orders import OrderManager
from logger import TradeLogger, Trade, PortfolioSnapshot
from on_chain import on_chain_analyzer
from dashboard import Dashboard
from webhooks import WebhookServer
from utils import format_usd, format_pct, now_utc

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class JarbisCrypto:
    """Main JARBIS Crypto trading bot."""

    def __init__(self):
        self.dashboard = Dashboard()
        self.trade_logger = TradeLogger(settings.log_db, settings.log_csv)
        self.webhook_server = WebhookServer(settings.webhook_port, settings.webhook_secret)

        # Broker
        self.broker = None
        self.fallback_broker = None

        # State
        self.paper_mode = settings.paper_trade
        self.running = False
        self.prices_cache: Dict[str, float] = {}
        self.candles_cache: Dict[str, Dict] = {}

        # Statistics
        self.last_signal_time = None
        self.max_drawdown = 0.0
        self.starting_balance = 0.0

    async def initialize(self):
        """Initialize bot and connections."""
        logger.info("Initializing JARBIS Crypto...")

        # Initialize broker
        bybit_config = settings.get_bybit_config()
        self.broker = BybitClient(
            bybit_config.api_key,
            bybit_config.api_secret,
            bybit_config.testnet,
        )

        binance_config = settings.get_binance_config()
        self.fallback_broker = BinanceClient(
            binance_config.api_key,
            binance_config.api_secret,
            binance_config.testnet,
        )

        # Initialize order manager
        self.order_manager = OrderManager(
            self.broker,
            risk_manager,
            self.trade_logger,
        )

        # Register webhook handlers
        self.webhook_server.register_handler("news", self._handle_news_webhook)
        self.webhook_server.register_handler("alert", self._handle_alert_webhook)
        self.webhook_server.register_handler("emergency", self._handle_emergency_webhook)
        self.webhook_server.register_handler("command", self._handle_command_webhook)

        # Get starting balance
        try:
            async with self.broker:
                balance = await self.broker.get_balance()
                self.starting_balance = balance if balance > 0 else settings.portfolio_size_usd
                risk_manager.update_portfolio_size(self.starting_balance)
                logger.info(f"Starting balance: {format_usd(self.starting_balance)}")
        except Exception as e:
            logger.warning(f"Could not fetch balance: {str(e)}. Using config value.")
            self.starting_balance = settings.portfolio_size_usd

        self.dashboard.print_banner()
        self.dashboard.print_info(
            f"Paper Mode: {'ENABLED' if self.paper_mode else 'LIVE (⚠️  BE CAREFUL)'}"
        )
        self.dashboard.print_command_help()

        logger.info("Bot initialized successfully")

    async def update_prices(self):
        """Update current prices for all trading pairs."""
        pairs = settings.get_pairs()

        try:
            async with self.broker:
                for pair in pairs:
                    try:
                        price = await self.broker.get_price(pair)
                        if price > 0:
                            self.prices_cache[pair] = price
                        else:
                            logger.warning(f"Invalid price for {pair}")
                    except Exception as e:
                        logger.error(f"Failed to get price for {pair}: {str(e)}")

            logger.debug(f"Updated prices: {self.prices_cache}")
        except Exception as e:
            logger.error(f"Failed to update prices: {str(e)}")

    async def fetch_candles(self):
        """Fetch OHLCV candles for all pairs and timeframes."""
        pairs = settings.get_pairs()
        timeframes = settings.get_timeframes()

        try:
            async with self.broker:
                for pair in pairs:
                    self.candles_cache[pair] = {}

                    for tf in timeframes:
                        try:
                            candles = await self.broker.get_candles(pair, tf, limit=200)
                            if not candles.empty:
                                self.candles_cache[pair][tf] = candles
                            else:
                                logger.warning(f"No candles for {pair} {tf}")
                        except Exception as e:
                            logger.error(f"Failed to fetch candles for {pair} {tf}: {str(e)}")

        except Exception as e:
            logger.error(f"Failed to fetch candles: {str(e)}")

    async def check_signals(self):
        """Check for new trading signals."""
        pairs = settings.get_pairs()
        risk_config = settings.get_risk_config()

        for pair in pairs:
            if pair not in self.candles_cache:
                continue

            candles = self.candles_cache[pair]

            # Check if we have all required timeframes
            if not all(tf in candles for tf in ["4h", "1h", "15m"]):
                logger.debug(f"Missing candles for {pair}")
                continue

            # Get sentiment
            sentiment_score = sentiment_analyzer.get_sentiment_for_ticker(pair)

            # Get on-chain signal
            on_chain_signal = None
            if settings.enable_on_chain_signals:
                best_signal = await on_chain_analyzer.get_best_signal(pair)
                if best_signal:
                    on_chain_signal = best_signal.signal_type

            # Generate signal
            signal = signal_generator.generate_signal(
                pair,
                candles["4h"],
                candles["1h"],
                candles["15m"],
                sentiment_score,
                on_chain_signal,
            )

            if signal:
                await self._execute_signal(signal)

    async def _execute_signal(self, signal: Signal):
        """Execute a trading signal."""
        logger.info(f"Executing signal for {signal.ticker}")

        # Calculate dynamic leverage
        portfolio_heat = self.order_manager.get_portfolio_exposure(self.prices_cache)
        heat_pct = risk_manager.calculate_portfolio_heat(portfolio_heat)

        leverage_params = LeverageParams(
            base_leverage=settings.base_leverage,
            max_leverage=settings.max_leverage,
            sentiment_score=signal.sentiment_score,
            volatility_factor=1.0,  # Would be calculated from ATR in real code
            portfolio_heat=heat_pct,
        )

        leverage = leverage_calc.calculate(leverage_params)
        logger.info(f"Calculated leverage: {leverage:.2f}x")

        # Calculate position size
        pos_size = risk_manager.calculate_position_size(
            signal.entry_price,
            signal.stop_loss,
            leverage,
        )

        logger.info(
            f"Position size: {pos_size.quantity:.8f} "
            f"(notional: {format_usd(pos_size.notional_value)}, "
            f"risk: {format_pct(pos_size.risk_pct)})"
        )

        # Open position
        trade_id = str(uuid.uuid4())

        success = await self.order_manager.open_position(
            trade_id=trade_id,
            ticker=signal.ticker,
            direction=signal.direction,
            quantity=pos_size.quantity,
            entry_price=signal.entry_price,
            leverage=leverage,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            paper_mode=self.paper_mode,
        )

        if success:
            # Log trade
            trade = Trade(
                trade_id=trade_id,
                ticker=signal.ticker,
                direction=signal.direction,
                entry_price=signal.entry_price,
                entry_time=signal.timestamp or now_utc(),
                quantity=pos_size.quantity,
                leverage=leverage,
                entry_leverage=leverage,
                sentiment_score=signal.sentiment_score,
                sentiment_label=sentiment_analyzer.label_sentiment(signal.sentiment_score),
                on_chain_signal=signal.on_chain_confirmation or "none",
                paper_trade=self.paper_mode,
            )
            self.trade_logger.log_trade(trade)

            # Display signal
            self.dashboard.print_signal(
                signal.ticker,
                signal.direction,
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit_1,
                signal.take_profit_2,
                signal.sentiment_score,
                signal.reason,
            )

            self.last_signal_time = now_utc()

    async def check_exits(self):
        """Check for take profit and stop loss triggers."""
        if not self.order_manager.active_positions:
            return

        exits = await self.order_manager.check_exits(self.prices_cache, self.paper_mode)

        for exit_event in exits:
            trade_id = exit_event["trade_id"]
            ticker = exit_event["ticker"]
            exit_price = exit_event["exit_price"]
            exit_reason = exit_event["exit_reason"]

            # Calculate P&L
            position = self.order_manager.active_positions.get(trade_id)
            if position:
                if position.direction == "long":
                    pnl = (exit_price - position.entry_price) * position.quantity
                else:
                    pnl = (position.entry_price - exit_price) * position.quantity

                pnl_pct = (pnl / (position.entry_price * position.quantity)) * 100

                # Update database
                self.trade_logger.update_trade(
                    trade_id,
                    exit_price,
                    now_utc(),
                    pnl,
                    pnl_pct,
                    exit_reason,
                )

                # Display
                self.dashboard.print_trade_closed(
                    ticker,
                    position.direction,
                    position.entry_price,
                    exit_price,
                    pnl,
                    pnl_pct,
                    exit_reason,
                )

            # Close position
            await self.order_manager.close_position(trade_id, exit_price, self.paper_mode)

    async def monitor_portfolio(self):
        """Monitor portfolio and check emergency conditions."""
        if not self.prices_cache:
            return

        total_exposure = self.order_manager.get_portfolio_exposure(self.prices_cache)
        heat = risk_manager.calculate_portfolio_heat(total_exposure)

        # Calculate unrealized P&L
        unrealized_pnl = 0.0
        for position in self.order_manager.active_positions.values():
            current_price = self.prices_cache.get(position.ticker, position.entry_price)
            if position.direction == "long":
                pnl = (current_price - position.entry_price) * position.remaining_quantity
            else:
                pnl = (position.entry_price - current_price) * position.remaining_quantity
            unrealized_pnl += pnl

        unrealized_pnl_pct = (unrealized_pnl / self.starting_balance) * 100

        # Check emergency conditions
        if risk_manager.check_emergency_conditions(unrealized_pnl_pct / 100):
            self.dashboard.print_warning(f"Emergency close triggered! Loss: {format_pct(unrealized_pnl_pct)}")
            await self.order_manager.emergency_close_all(self.prices_cache, self.paper_mode)

    async def display_status(self):
        """Display current status."""
        balance = self.starting_balance
        positions = self.order_manager.get_open_positions_summary()

        # Get sentiment
        sentiment_scores = sentiment_analyzer.get_all_sentiment()
        avg_sentiment = sum(sentiment_scores.values()) / len(sentiment_scores) if sentiment_scores else 0.0

        # Get leverage
        avg_leverage = (
            sum(p["leverage"] for p in positions) / len(positions)
            if positions
            else 1.0
        )

        # Portfolio heat
        exposure = self.order_manager.get_portfolio_exposure(self.prices_cache)
        heat = risk_manager.calculate_portfolio_heat(exposure)

        # P&L
        unrealized_pnl = 0.0
        for position in self.order_manager.active_positions.values():
            current_price = self.prices_cache.get(position.ticker, position.entry_price)
            if position.direction == "long":
                pnl = (current_price - position.entry_price) * position.remaining_quantity
            else:
                pnl = (position.entry_price - current_price) * position.remaining_quantity
            unrealized_pnl += pnl

        unrealized_pnl_pct = (unrealized_pnl / self.starting_balance) * 100 if self.starting_balance > 0 else 0

        # Print metrics
        metrics_panel = self.dashboard.render_metrics_panel(
            balance=balance,
            current_leverage=avg_leverage,
            sentiment_score=avg_sentiment,
            portfolio_heat=heat,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )
        self.dashboard.console.print(metrics_panel)

        if positions:
            positions_panel = self.dashboard.render_positions_panel(positions)
            self.dashboard.console.print(positions_panel)

    async def handle_commands(self):
        """Handle user commands from stdin."""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                command = await loop.run_in_executor(None, input, "> ")
                await self._process_command(command)
            except EOFError:
                self.running = False
            except Exception as e:
                self.dashboard.print_error(str(e))

    async def _process_command(self, command: str):
        """Process user command."""
        if not command:
            return

        parts = command.strip().split()
        cmd = parts[0].lower()

        try:
            if cmd == "!quit":
                self.running = False
                self.dashboard.print_info("Shutting down...")

            elif cmd == "!paper":
                self.paper_mode = True
                self.dashboard.print_success("Switched to PAPER mode")

            elif cmd == "!live":
                # Require 3x confirmation
                self.dashboard.print_warning("LIVE MODE - 3 confirmations required!")
                confirm = input("Type 'LIVE' to confirm (1/3): ")
                if confirm != "LIVE":
                    return
                confirm = input("Type 'LIVE' to confirm (2/3): ")
                if confirm != "LIVE":
                    return
                confirm = input("Type 'LIVE' to confirm (3/3): ")
                if confirm == "LIVE":
                    self.paper_mode = False
                    self.dashboard.print_success("Switched to LIVE mode (⚠️)")

            elif cmd == "!help":
                self.dashboard.print_command_help()

            elif cmd == "!stats":
                stats = self.trade_logger.get_trade_stats()
                self.dashboard.print_info(
                    f"Total Trades: {stats.get('total_trades', 0)}, "
                    f"Win Rate: {format_pct(stats.get('win_rate', 0))}, "
                    f"Total P&L: {format_usd(stats.get('total_pnl_dollars', 0))}"
                )

            elif cmd == "!positions":
                positions = self.order_manager.get_open_positions_summary()
                if positions:
                    panel = self.dashboard.render_positions_panel(positions)
                    self.dashboard.console.print(panel)
                else:
                    self.dashboard.print_info("No open positions")

            elif cmd == "!sentiment":
                sentiments = sentiment_analyzer.get_all_sentiment()
                for ticker, score in sentiments.items():
                    label = sentiment_analyzer.label_sentiment(score)
                    self.dashboard.print_info(f"{ticker}: {label} ({score:.2f})")

            elif cmd == "!emergency":
                self.dashboard.print_warning("EMERGENCY CLOSE ALL POSITIONS")
                await self.order_manager.emergency_close_all(self.prices_cache, self.paper_mode)

            else:
                self.dashboard.print_error(f"Unknown command: {cmd}. Type !help")

        except Exception as e:
            self.dashboard.print_error(f"Command error: {str(e)}")

    def _handle_news_webhook(self, ticker: str, title: str, sentiment: Optional[float] = None):
        """Handle news webhook."""
        if sentiment is not None:
            sentiment_analyzer.inject_news(ticker, title, sentiment)
        else:
            sentiment_analyzer.inject_news(ticker, title)

    def _handle_alert_webhook(self, alert_type: str, message: str, data: Dict):
        """Handle alert webhook."""
        self.dashboard.print_warning(f"[{alert_type}] {message}")

    def _handle_emergency_webhook(self):
        """Handle emergency webhook."""
        self.dashboard.print_warning("Emergency close from webhook!")
        # Trigger emergency close in async context
        asyncio.create_task(self.order_manager.emergency_close_all(self.prices_cache, self.paper_mode))

    def _handle_command_webhook(self, command: str, args: Dict):
        """Handle command webhook."""
        asyncio.create_task(self._process_command(command))

    async def run(self):
        """Main bot loop."""
        await self.initialize()

        self.running = True
        self.webhook_server.run_in_thread()

        # Create tasks for concurrent operations
        tasks = [
            asyncio.create_task(self.handle_commands()),
            asyncio.create_task(self._main_loop()),
        ]

        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("Shutdown signal received")
        finally:
            self.running = False

    async def _main_loop(self):
        """Main bot event loop."""
        last_update = now_utc()
        last_signal_check = now_utc()

        while self.running:
            try:
                current_time = now_utc()

                # Update prices every 5 seconds
                if (current_time - last_update).total_seconds() > 5:
                    await self.update_prices()
                    last_update = current_time

                # Fetch candles and check signals every 60 seconds
                if (current_time - last_signal_check).total_seconds() > 60:
                    await self.fetch_candles()
                    await self.check_signals()
                    last_signal_check = current_time

                # Check exits every tick
                await self.check_exits()

                # Monitor portfolio
                await self.monitor_portfolio()

                # Display status every 30 seconds
                if current_time.minute % 1 == 0:  # Every minute
                    await self.display_status()

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Error in main loop: {str(e)}")
                await asyncio.sleep(1)


async def main():
    """Entry point."""
    bot = JarbisCrypto()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
