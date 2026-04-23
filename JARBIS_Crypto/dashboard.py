"""Rich dashboard.

Three panels:
- Live metrics (balance, margin, leverage, sentiment per ticker)
- Risk panel (heat, drawdown, win rate)
- Trade log (last 20 trades)
"""
from __future__ import annotations

from typing import Dict, Iterable

from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .broker import Broker
from .logger import TradeLogger
from .risk import RiskManager
from .sentiment import SentimentEngine
from .utils import fmt_pct, fmt_price, fmt_qty, utcnow


def _sentiment_color(score: float) -> str:
    if score >= 0.5:
        return "bright_green"
    if score >= 0.15:
        return "green"
    if score <= -0.5:
        return "bright_red"
    if score <= -0.15:
        return "red"
    return "yellow"


def metrics_panel(
    broker: Broker,
    sentiment: SentimentEngine,
    prices: Dict[str, float],
    tickers: Iterable[str],
    current_leverage: Dict[str, float],
) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()

    table.add_row("Balance", f"[bold]{fmt_price(broker.cash())}[/]")
    table.add_row("Available margin", fmt_price(broker.available_margin()))

    positions = broker.positions()
    if positions:
        unrealized = 0.0
        for ticker, pos in positions.items():
            price = prices.get(ticker, pos.entry_price)
            pnl = (price - pos.entry_price) * pos.quantity
            if pos.direction == "short":
                pnl = -pnl
            unrealized += pnl
        table.add_row("Unrealized P&L", fmt_price(unrealized))
    else:
        table.add_row("Unrealized P&L", "$0.00")

    table.add_row("Open positions", str(len(positions)))

    # Per-ticker row: price, sentiment, leverage estimate
    for ticker in tickers:
        price = prices.get(ticker)
        score = sentiment.score_for(ticker)
        lev = current_leverage.get(ticker, 0.0)
        color = _sentiment_color(score)
        row = Text.assemble(
            ("  " + ticker.ljust(4), "bold"),
            (f" {fmt_price(price) if price else '—':>14}", ""),
            ("  sent=", "dim"),
            (f"{score:+.2f}", color),
            ("  lev=", "dim"),
            (f"{lev:.2f}x" if lev else "—", "cyan"),
        )
        table.add_row("", row)

    return Panel(table, title="[bold cyan]JARBIS Crypto — Live[/]", border_style="cyan")


def risk_panel(
    broker: Broker,
    risk: RiskManager,
    logger: TradeLogger,
) -> Panel:
    stats = logger.stats(limit=50)
    heat = risk.portfolio_heat()
    max_loss_pct = risk.max_loss_pct
    starting = risk.settings.portfolio_size_usd
    current = broker.cash()
    drawdown = (current - starting) / starting if starting else 0.0

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()

    heat_color = "green" if heat < 0.5 else ("yellow" if heat < 0.8 else "red")
    table.add_row("Portfolio heat", Text(f"{heat * 100:.1f}%", style=heat_color))
    table.add_row("Max loss / trade", f"{max_loss_pct * 100:.2f}%")
    dd_color = "green" if drawdown >= 0 else "red"
    table.add_row("P&L since start", Text(fmt_pct(drawdown), style=dd_color))
    table.add_row("Trades (last 50)", str(stats.total_trades))
    if stats.total_trades:
        wr_color = "green" if stats.win_rate >= 0.55 else ("yellow" if stats.win_rate >= 0.4 else "red")
        table.add_row("Win rate", Text(f"{stats.win_rate * 100:.1f}%", style=wr_color))
        table.add_row("Best / Worst", f"{fmt_price(stats.best_trade)} / {fmt_price(stats.worst_trade)}")
        table.add_row("Total P&L", fmt_price(stats.total_pnl))
    else:
        table.add_row("Win rate", "—")

    return Panel(table, title="[bold magenta]Risk[/]", border_style="magenta")


def trades_panel(logger: TradeLogger) -> Panel:
    rows = logger.recent_trades(limit=15)
    table = Table(expand=True, show_lines=False, border_style="dim")
    table.add_column("Ticker", style="bold")
    table.add_column("Dir")
    table.add_column("Qty", justify="right")
    table.add_column("Entry", justify="right")
    table.add_column("Exit", justify="right")
    table.add_column("Lev", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("Sent")
    table.add_column("Exit why")

    for r in rows:
        (ticker, direction, entry, exit_p, qty, lev, pnl, pnl_pct,
         sent_label, exit_reason, _entry_time) = r
        pnl_text = "—" if pnl is None else fmt_price(pnl)
        pnl_style = "green" if (pnl or 0) > 0 else ("red" if (pnl or 0) < 0 else "")
        table.add_row(
            ticker, direction,
            fmt_qty(qty),
            fmt_price(entry),
            fmt_price(exit_p) if exit_p else "—",
            f"{lev:.2f}x",
            Text(pnl_text, style=pnl_style),
            sent_label or "—",
            exit_reason or "open",
        )

    return Panel(table, title="[bold yellow]Trades[/]", border_style="yellow")


def build_layout(
    broker: Broker,
    sentiment: SentimentEngine,
    risk: RiskManager,
    logger: TradeLogger,
    prices: Dict[str, float],
    tickers: Iterable[str],
    current_leverage: Dict[str, float],
    mode_banner: str,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="trades", size=18),
    )
    layout["body"].split_row(Layout(name="metrics"), Layout(name="risk"))

    header = Panel(
        Text.assemble(
            ("JARBIS Crypto 24/7  ", "bold cyan"),
            (mode_banner + "  ", "bold yellow"),
            (utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), "dim"),
        ),
        border_style="cyan",
    )
    layout["header"].update(header)
    layout["metrics"].update(metrics_panel(broker, sentiment, prices, tickers, current_leverage))
    layout["risk"].update(risk_panel(broker, risk, logger))
    layout["trades"].update(trades_panel(logger))
    return layout
