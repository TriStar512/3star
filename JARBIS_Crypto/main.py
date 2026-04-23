"""JARBIS Crypto main entrypoint.

Runs three concurrent coroutines:
- ``signal_loop``: poll candles, generate signals, route orders, mark-to-market
- ``sentiment_loop``: refresh news feeds on a slower cadence
- ``command_loop``: read stdin for CLI commands (``!buy``, ``!close``, …)

The Rich Live display is rendered on the main event loop so the three
coroutines can touch the shared state without cross-thread locks.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal as os_signal
import sys
from typing import Dict, Optional

from rich.console import Console
from rich.live import Live

from .broker import Broker
from .config import get_settings
from .dashboard import build_layout
from .leverage import LeverageInputs, calculate_leverage
from .logger import TradeLogger
from .on_chain import OnChainEngine
from .orders import OrderRouter
from .risk import RiskManager
from .sentiment import SentimentEngine
from .signals import SignalEngine
from .utils import fmt_price, setup_logging
from .webhooks import WebhookServer, slack_notify

log = logging.getLogger("jarbis")


class JarbisBot:
    def __init__(self, paper_override: Optional[bool] = None):
        self.settings = get_settings()
        if paper_override is not None:
            self.settings.paper_trade = paper_override
        self.console = Console()
        self.broker = Broker(self.settings)
        self.sentiment = SentimentEngine(self.settings)
        self.on_chain = OnChainEngine(self.settings)
        self.logger = TradeLogger(self.settings)
        self.webhooks = WebhookServer(self.settings)
        self.running = True

        self.risk: Optional[RiskManager] = None
        self.signal_engine: Optional[SignalEngine] = None
        self.router: Optional[OrderRouter] = None

        self.prices: Dict[str, float] = {}
        self.current_leverage: Dict[str, float] = {}
        self._cooldown: Dict[str, float] = {}  # ticker -> unix timestamp until which we skip

    # ---- lifecycle ----

    async def start(self) -> None:
        setup_logging(self.settings.log_level)
        await self.broker.__aenter__()
        await self.sentiment.__aenter__()
        await self.on_chain.__aenter__()
        self.risk = RiskManager(self.broker, self.settings)
        self.signal_engine = SignalEngine(self.broker)
        self.router = OrderRouter(self.broker, self.risk, self.settings)
        self.webhooks.start()

        banner = "[PAPER]" if self.settings.paper_trade else "[LIVE]"
        self.console.print(f"[bold cyan]JARBIS Crypto starting {banner}[/]")
        slack_notify(f"JARBIS Crypto starting {banner}", self.settings)

    async def stop(self) -> None:
        self.running = False
        await self.broker.__aexit__(None, None, None)
        await self.sentiment.__aexit__(None, None, None)
        await self.on_chain.__aexit__(None, None, None)

    # ---- loops ----

    async def signal_loop(self, live: Live) -> None:
        assert self.signal_engine and self.router and self.risk
        import time
        poll = self.settings.signal_poll_seconds
        while self.running:
            # 1) pull fresh prices + mark-to-market existing positions
            for ticker in self.settings.trading_pairs:
                try:
                    price = await self.broker.get_price(ticker)
                    self.prices[ticker] = price
                    exit_reason = self.broker.mark_to_market(ticker, price)
                    if exit_reason in ("sl", "tp2"):
                        pos = next(
                            (p for p in self.broker.closed_positions() if p.order_id in self._just_closed_ids()),
                            None,
                        )
                        # fall back: write all closed positions not yet logged
                        self._flush_closed()
                except Exception as exc:  # noqa: BLE001
                    log.warning("price fetch %s: %s", ticker, exc)

            # 2) enforce timeouts / hard loss
            for ticker, reason in self.risk.scan_timeouts(self.prices):
                price = self.prices.get(ticker)
                if price is not None:
                    self.broker.force_close(ticker, price, reason)
            self._flush_closed()

            # 3) try to generate entries for unheld tickers not in cooldown
            now = time.time()
            for ticker in self.settings.trading_pairs:
                if ticker in self.broker.positions():
                    continue
                if now < self._cooldown.get(ticker, 0):
                    continue
                try:
                    score = self.sentiment.score_for(ticker)
                    oc = await self.on_chain.check(ticker)
                    sig = await self.signal_engine.generate(
                        ticker, sentiment_score=score, on_chain_confirmation=oc.bullish,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("signal %s: %s", ticker, exc)
                    continue
                if not sig:
                    continue
                try:
                    atr_ratio = await self.signal_engine.atr_ratio(ticker)
                    result = await self.router.execute(sig, atr_ratio=atr_ratio)
                except Exception as exc:  # noqa: BLE001
                    log.warning("execute %s: %s", ticker, exc)
                    continue
                if result:
                    self.logger.log_open(result, on_chain_label=oc.label)
                    self.current_leverage[ticker] = result.leverage.leverage
                    slack_notify(
                        f"[{ticker}] {sig.direction.upper()} @ {fmt_price(sig.entry_price)} "
                        f"lev={result.leverage.leverage:.2f}x",
                        self.settings,
                    )
                # brief cooldown even on rejection so we don't hammer the same pattern
                self._cooldown[ticker] = now + max(poll * 2, 60)

            # 4) update leverage estimates for UI (sentiment changes even without entries)
            for ticker in self.settings.trading_pairs:
                if ticker in self.broker.positions():
                    self.current_leverage[ticker] = self.broker.positions()[ticker].leverage
                else:
                    try:
                        atr_ratio = await self.signal_engine.atr_ratio(ticker)
                    except Exception:  # noqa: BLE001
                        atr_ratio = 1.0
                    lev = calculate_leverage(
                        LeverageInputs(
                            sentiment_score=self.sentiment.score_for(ticker),
                            atr_ratio=atr_ratio,
                            portfolio_heat=self.risk.portfolio_heat(),
                        ),
                        self.settings,
                    )
                    self.current_leverage[ticker] = lev.leverage

            # 5) drain webhooks
            for ev in self.webhooks.drain():
                if ev.kind == "news":
                    self.sentiment.inject_manual(
                        ev.payload["ticker"], ev.payload["headline"],
                        ev.payload.get("score"),
                    )
                elif ev.kind == "emergency":
                    await self._emergency_flatten()

            self._render(live)
            await asyncio.sleep(poll)

    async def sentiment_loop(self) -> None:
        while self.running:
            try:
                await self.sentiment.refresh()
            except Exception as exc:  # noqa: BLE001
                log.warning("sentiment refresh: %s", exc)
            await asyncio.sleep(300)  # 5 min

    async def command_loop(self) -> None:
        """Read commands from stdin without blocking the event loop."""
        loop = asyncio.get_running_loop()
        while self.running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except Exception:  # noqa: BLE001
                await asyncio.sleep(1)
                continue
            if not line:
                await asyncio.sleep(0.1)
                continue
            await self.handle_command(line.strip())

    # ---- command dispatch ----

    async def handle_command(self, raw: str) -> None:
        if not raw:
            return
        if not raw.startswith("!"):
            self.console.print("[dim]commands start with '!'. try !help[/]")
            return
        parts = raw[1:].split()
        cmd, *args = parts
        cmd = cmd.lower()
        try:
            if cmd == "help":
                self._print_help()
            elif cmd == "quit":
                self.running = False
            elif cmd == "paper":
                self.settings.paper_trade = True
                self.console.print("[yellow]paper mode ON[/]")
            elif cmd == "live":
                self.console.print(
                    "[red bold]LIVE mode requires 3 confirmations. Type !live confirm three times.[/]"
                )
                # simple confirmation flow: look at args
                if args and args[0] == "confirm":
                    self._live_confirms = getattr(self, "_live_confirms", 0) + 1
                    if self._live_confirms >= 3:
                        self.settings.paper_trade = False
                        self.console.print("[red bold]LIVE mode ON[/]")
                        self._live_confirms = 0
            elif cmd == "close":
                await self._close_positions(args[0] if args else None)
            elif cmd == "emergency":
                await self._emergency_flatten()
            elif cmd == "risk" and len(args) == 2 and args[0] in ("increase", "decrease", "set"):
                pct = float(args[1])
                self.risk.set_max_loss_pct(pct)  # type: ignore[union-attr]
            elif cmd == "leverage":
                if args and args[0] == "auto":
                    self.router.set_leverage_override(None)  # type: ignore[union-attr]
                elif len(args) == 2 and args[0] == "set":
                    self.router.set_leverage_override(float(args[1]))  # type: ignore[union-attr]
                else:
                    self.console.print("[dim]usage: !leverage set <x> | !leverage auto[/]")
            elif cmd == "news" and args:
                text = " ".join(args)
                if ":" in text:
                    ticker, headline = text.split(":", 1)
                    self.sentiment.inject_manual(ticker.strip(), headline.strip())
                else:
                    self.console.print("[dim]usage: !news BTC: headline text[/]")
            elif cmd == "stats":
                self._print_stats()
            elif cmd == "heat":
                self._print_heat()
            elif cmd == "sentiment":
                self._print_sentiment()
            elif cmd == "positions":
                self._print_positions()
            elif cmd == "on-chain" and args:
                sig = await self.on_chain.check(args[0].upper())
                self.console.print(
                    f"{sig.ticker}: bullish={sig.bullish} label={sig.label} "
                    f"source={sig.source} detail={sig.detail}"
                )
            else:
                self.console.print(f"[red]unknown: !{cmd}[/] — try !help")
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[red]command error:[/] {exc}")

    async def _close_positions(self, ticker: Optional[str]) -> None:
        tickers = [ticker] if ticker else list(self.broker.positions().keys())
        for t in tickers:
            price = self.prices.get(t) or await self.broker.get_price(t)
            pos = self.broker.force_close(t, price, "manual")
            if pos:
                self.console.print(
                    f"[yellow]closed {t} @ {fmt_price(price)} reason=manual[/]"
                )
        self._flush_closed()

    async def _emergency_flatten(self) -> None:
        self.console.print("[red bold]!! EMERGENCY FLATTEN !![/]")
        for ticker in list(self.broker.positions().keys()):
            price = self.prices.get(ticker) or await self.broker.get_price(ticker)
            self.broker.force_close(ticker, price, "emergency")
        self._flush_closed()
        slack_notify("EMERGENCY flatten triggered", self.settings)

    # ---- helpers ----

    _last_flushed_count = 0

    def _just_closed_ids(self) -> list[str]:
        return [p.order_id for p in self.broker.closed_positions()]

    def _flush_closed(self) -> None:
        closed = self.broker.closed_positions()
        for pos in closed[self._last_flushed_count:]:
            self.logger.log_close(pos)
        self._last_flushed_count = len(closed)

    def _print_help(self) -> None:
        self.console.print("""[bold]Commands[/]
  !buy / !sell TICKER PRICE   — (future: manual entries)
  !close [TICKER]             — close all or one
  !emergency                  — panic-close everything
  !risk set <pct>             — e.g. !risk set 0.015
  !leverage set <x> | auto    — override or resume dynamic
  !paper | !live confirm      — toggle modes (live needs 3 confirms)
  !news TICKER: headline      — inject manual news
  !stats | !heat | !sentiment | !positions
  !on-chain TICKER            — dump latest on-chain signal
  !quit                       — exit bot
""")

    def _print_stats(self) -> None:
        s = self.logger.stats(limit=50)
        self.console.print(
            f"trades={s.total_trades} win_rate={s.win_rate * 100:.1f}% "
            f"total_pnl={fmt_price(s.total_pnl)} best={fmt_price(s.best_trade)} "
            f"worst={fmt_price(s.worst_trade)}"
        )

    def _print_heat(self) -> None:
        heat = self.risk.portfolio_heat()  # type: ignore[union-attr]
        self.console.print(f"portfolio heat: {heat * 100:.1f}%  (cash={fmt_price(self.broker.cash())})")

    def _print_sentiment(self) -> None:
        for ticker in self.settings.trading_pairs:
            self.console.print(
                f"{ticker}: {self.sentiment.score_for(ticker):+.2f} "
                f"({self.sentiment.label_for(ticker)})"
            )

    def _print_positions(self) -> None:
        for ticker, pos in self.broker.positions().items():
            self.console.print(
                f"{ticker} {pos.direction.upper()} qty={pos.quantity:.6f} "
                f"entry={fmt_price(pos.entry_price)} SL={fmt_price(pos.stop_loss)} "
                f"TP1={fmt_price(pos.take_profit_1)} TP2={fmt_price(pos.take_profit_2)} "
                f"lev={pos.leverage:.2f}x"
            )

    def _render(self, live: Live) -> None:
        banner = "[PAPER]" if self.settings.paper_trade else "[LIVE]"
        layout = build_layout(
            self.broker, self.sentiment, self.risk,  # type: ignore[arg-type]
            self.logger, self.prices,
            self.settings.trading_pairs, self.current_leverage,
            banner,
        )
        live.update(layout)


async def _run(paper: Optional[bool]) -> None:
    bot = JarbisBot(paper_override=paper)
    await bot.start()

    def _handle_sigint(*_):
        bot.running = False

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(os_signal.SIGINT, _handle_sigint)
        loop.add_signal_handler(os_signal.SIGTERM, _handle_sigint)
    except NotImplementedError:
        pass

    with Live(console=bot.console, refresh_per_second=1, screen=False) as live:
        tasks = [
            asyncio.create_task(bot.signal_loop(live)),
            asyncio.create_task(bot.sentiment_loop()),
            asyncio.create_task(bot.command_loop()),
        ]
        try:
            while bot.running:
                await asyncio.sleep(0.5)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await bot.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="JARBIS Crypto 24/7 Trading Bot")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--paper", action="store_true", help="force paper trading")
    group.add_argument("--live", action="store_true", help="force live trading (careful)")
    args = ap.parse_args()

    paper: Optional[bool] = None
    if args.paper:
        paper = True
    elif args.live:
        paper = False

    asyncio.run(_run(paper))


if __name__ == "__main__":
    main()
