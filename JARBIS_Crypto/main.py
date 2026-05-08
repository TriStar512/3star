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
        self.webhooks = WebhookServer(self.settings, bot=self)
        self.running = True
        # Dashboard on/off toggle — when False, signal_loop still refreshes
        # prices/sentiment so the UI stays live, but no new entries fire.
        self.bot_active = True

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

        # Live boot: pull initial balance/position snapshot before we
        # render the first dashboard frame.
        if not self.settings.paper_trade:
            await self.broker.refresh_live_state()

        banner = self._mode_banner()
        self.console.print(f"[bold cyan]JARBIS Crypto starting[/] {banner}")
        slack_notify(f"JARBIS Crypto starting {banner}", self.settings)

    def _mode_banner(self) -> str:
        if self.settings.paper_trade:
            return "[yellow][PAPER][/]"
        net = "TESTNET" if self.settings.hl_testnet else "MAINNET"
        color = "yellow" if self.settings.hl_testnet else "red bold"
        return f"[{color}][LIVE · HL {net}][/]"

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
            # 0) live mode: refresh balance + positions from HL user_state
            if not self.settings.paper_trade:
                await self.broker.refresh_live_state()

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
            #    (skipped entirely when the bot is toggled OFF — UI still
            #    polls prices/sentiment, positions still mark-to-market)
            now = time.time()
            if not self.bot_active:
                await self._update_leverage_estimates()
                for ev in self.webhooks.drain():
                    await self._handle_webhook_event(ev)
                self._render(live)
                await asyncio.sleep(poll)
                continue
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

            # 4) update leverage estimates + drain webhooks + render
            await self._update_leverage_estimates()
            for ev in self.webhooks.drain():
                await self._handle_webhook_event(ev)
            self._render(live)
            await asyncio.sleep(poll)

    async def _update_leverage_estimates(self) -> None:
        """Refresh per-ticker dynamic leverage for the UI."""
        assert self.risk and self.signal_engine
        for ticker in self.settings.trading_pairs:
            if ticker in self.broker.positions():
                self.current_leverage[ticker] = self.broker.positions()[ticker].leverage
                continue
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

    async def _handle_webhook_event(self, ev) -> None:
        if ev.kind == "news":
            self.sentiment.inject_manual(
                ev.payload["ticker"], ev.payload["headline"],
                ev.payload.get("score"),
            )
        elif ev.kind == "emergency":
            await self._emergency_flatten()
        elif ev.kind == "bot_start":
            self.bot_active = True
            self.console.print("[green]bot activated via webhook[/]")
        elif ev.kind == "bot_stop":
            self.bot_active = False
            self.console.print("[yellow]bot deactivated via webhook[/]")

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
                await self._handle_live_command(args)
            elif cmd == "close":
                await self._close_positions(args[0] if args else None)
            elif cmd == "emergency":
                await self._emergency_flatten()
            elif cmd == "start":
                self.bot_active = True
                self.console.print("[green]bot ACTIVE — new entries enabled[/]")
            elif cmd == "stop":
                self.bot_active = False
                self.console.print("[yellow]bot IDLE — no new entries (open positions still managed)[/]")
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

    async def _handle_live_command(self, args: list) -> None:
        """!live confirm (x3) → testnet · !live mainnet confirm (x3) → mainnet.

        Three confirmations are still required even on testnet — habit
        forming. Mainnet additionally needs the explicit ``mainnet``
        keyword to flip ``hl_testnet=False`` before the first confirm.
        """
        want_mainnet = bool(args and args[0] == "mainnet")
        confirm_args = args[1:] if want_mainnet else args
        is_confirm = bool(confirm_args and confirm_args[0] == "confirm")

        if not self.settings.hl_wallet_address or not self.settings.hl_private_key:
            self.console.print(
                "[red]live mode requires HL_WALLET_ADDRESS and HL_PRIVATE_KEY in .env[/]"
            )
            return

        if not is_confirm:
            target = "MAINNET" if want_mainnet else f"TESTNET ({'mainnet' if not self.settings.hl_testnet else 'testnet'} currently)"
            self.console.print(
                f"[red bold]LIVE on {target} requires 3 confirmations.[/]\n"
                f"Type [bold]!live{' mainnet' if want_mainnet else ''} confirm[/] three times."
            )
            self._live_confirms = 0
            self._live_target_mainnet = want_mainnet
            return

        # accumulating confirmations — must stay on the same target
        existing_target = getattr(self, "_live_target_mainnet", False)
        if want_mainnet != existing_target:
            self._live_confirms = 0
            self._live_target_mainnet = want_mainnet
        self._live_confirms = getattr(self, "_live_confirms", 0) + 1
        remaining = 3 - self._live_confirms
        if remaining > 0:
            self.console.print(
                f"[yellow]live confirm {self._live_confirms}/3 "
                f"({'mainnet' if want_mainnet else 'testnet'})[/]"
            )
            return

        # 3/3 — flip the switch
        self.settings.paper_trade = False
        self.settings.hl_testnet = not want_mainnet
        try:
            self.broker._init_live_exchange()
            await self.broker.refresh_live_state()
        except Exception as exc:  # noqa: BLE001
            self.settings.paper_trade = True
            self.console.print(f"[red]live init failed, reverting to paper: {exc}[/]")
            self._live_confirms = 0
            return
        self._live_confirms = 0
        net = "MAINNET" if want_mainnet else "TESTNET"
        self.console.print(f"[red bold]LIVE mode ON · Hyperliquid {net}[/]")
        slack_notify(f"LIVE mode ON · Hyperliquid {net}", self.settings)

    async def _emergency_flatten(self) -> None:
        self.console.print("[red bold]!! EMERGENCY FLATTEN !![/]")
        for ticker in list(self.broker.positions().keys()):
            price = self.prices.get(ticker) or await self.broker.get_price(ticker)
            if self.settings.paper_trade:
                self.broker.force_close(ticker, price, "emergency")
            else:
                # live: cancel bracket + market close on Hyperliquid
                try:
                    await self.broker.emergency_close_live(ticker)
                except Exception as exc:  # noqa: BLE001
                    log.error("live emergency close %s failed: %s", ticker, exc)
        self._flush_closed()
        if not self.settings.paper_trade:
            await self.broker.refresh_live_state()
        slack_notify("EMERGENCY flatten triggered", self.settings)

    # ---- helpers ----

    _last_flushed_count = 0

    def state_snapshot(self) -> dict:
        """JSON-serializable state for the dashboard ``GET /state`` endpoint.

        Called from the Flask thread so it must not touch asyncio objects;
        it only reads plain dicts / numbers from the bot's current state.
        Confidence per coin = ((sentiment + 1) / 2) * 100 scaled by
        volatility alignment — purely visual, kept simple on purpose.
        """
        from .sentiment import classify_sentiment
        positions = []
        unrealized_total = 0.0
        for ticker, pos in self.broker.positions().items():
            price = self.prices.get(ticker, pos.entry_price)
            pnl = (price - pos.entry_price) * pos.quantity
            if pos.direction == "short":
                pnl = -pnl
            unrealized_total += pnl
            positions.append({
                "ticker": ticker,
                "direction": pos.direction,
                "quantity": pos.quantity,
                "entry": pos.entry_price,
                "current": price,
                "pnl": pnl,
                "pnl_pct": pnl / (pos.entry_price * pos.quantity) if pos.quantity else 0.0,
                "leverage": pos.leverage,
                "stop_loss": pos.stop_loss,
                "tp1": pos.take_profit_1,
                "tp2": pos.take_profit_2,
                "tp1_hit": pos.tp1_hit,
                "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            })

        sentiment_data = {}
        confidence = {}
        for ticker in self.settings.trading_pairs:
            score = self.sentiment.score_for(ticker)
            sentiment_data[ticker] = {
                "score": score,
                "label": classify_sentiment(score),
            }
            # Simple visual confidence: sentiment + leverage headroom.
            lev = self.current_leverage.get(ticker, self.settings.base_leverage)
            lev_pct = lev / max(self.settings.max_leverage, 1.0)  # 0..1
            raw = 0.5 + 0.4 * score + 0.1 * (lev_pct - 0.5)
            confidence[ticker] = max(0.0, min(1.0, raw)) * 100.0

        stats = self.logger.stats(limit=50)
        recent = []
        for row in self.logger.recent_trades(limit=10):
            (ticker, direction, entry_p, exit_p, qty, lev, pnl, pnl_pct,
             sent_label, exit_reason, entry_time) = row
            recent.append({
                "ticker": ticker, "direction": direction,
                "entry": entry_p, "exit": exit_p, "quantity": qty,
                "leverage": lev, "pnl": pnl, "pnl_pct": pnl_pct,
                "sentiment_label": sent_label, "exit_reason": exit_reason,
                "entry_time": entry_time,
            })

        # Active trade = most recently opened; confidence of that ticker.
        active_trade = None
        if positions:
            newest = max(positions, key=lambda p: p["opened_at"] or "")
            active_trade = {
                "ticker": newest["ticker"],
                "confidence": confidence.get(newest["ticker"], 50.0),
            }

        return {
            "mode": "LIVE" if not self.settings.paper_trade else "PAPER",
            "bot_active": self.bot_active,
            "venue": self.broker.venue_name,
            "trading_pairs": list(self.settings.trading_pairs),
            "balance": self.broker.cash(),
            "available_margin": self.broker.available_margin(),
            "unrealized_pnl": unrealized_total,
            "portfolio_heat": self.risk.portfolio_heat() if self.risk else 0.0,
            "max_loss_pct": self.risk.max_loss_pct if self.risk else self.settings.max_loss_pct,
            "max_leverage": self.settings.max_leverage,
            "base_leverage": self.settings.base_leverage,
            "prices": dict(self.prices),
            "leverage": dict(self.current_leverage),
            "sentiment": sentiment_data,
            "confidence": confidence,
            "active_trade": active_trade,
            "positions": positions,
            "recent_trades": recent,
            "stats": {
                "total_trades": stats.total_trades,
                "wins": stats.wins,
                "losses": stats.losses,
                "win_rate": stats.win_rate,
                "total_pnl": stats.total_pnl,
                "best": stats.best_trade,
                "worst": stats.worst_trade,
            },
        }

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
  !start | !stop              — enable/disable new entries
  !paper                      — switch to paper trading
  !live confirm (x3)          — go live on Hyperliquid TESTNET
  !live mainnet confirm (x3)  — go live on Hyperliquid MAINNET (real $$$)
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
