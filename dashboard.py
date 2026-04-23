"""Rich terminal dashboard for JARBIS Crypto."""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from utils import format_usd, format_pct, format_crypto, pretty_timestamp

logger = logging.getLogger(__name__)


class Dashboard:
    """Terminal UI dashboard."""

    def __init__(self):
        self.console = Console()

    def render_metrics_panel(
        self,
        balance: float,
        current_leverage: float,
        sentiment_score: float,
        portfolio_heat: float,
        unrealized_pnl: float,
        unrealized_pnl_pct: float,
    ) -> Panel:
        """Render live metrics panel."""
        metrics_text = ""

        # Balance
        metrics_text += f"💰 Balance: {format_usd(balance)}\n"

        # Leverage
        leverage_color = "green" if current_leverage < 2.5 else "yellow" if current_leverage < 3.0 else "red"
        metrics_text += f"⚙️  Leverage: [bold {leverage_color}]{current_leverage:.2f}x[/]\n"

        # Sentiment
        if sentiment_score > 0.5:
            sentiment_label = "🔥 Very Bullish"
            sentiment_color = "green"
        elif sentiment_score > 0.2:
            sentiment_label = "📈 Bullish"
            sentiment_color = "light_green"
        elif sentiment_score > -0.2:
            sentiment_label = "➡️  Neutral"
            sentiment_color = "yellow"
        elif sentiment_score > -0.5:
            sentiment_label = "📉 Bearish"
            sentiment_color = "light_red"
        else:
            sentiment_label = "❄️  Very Bearish"
            sentiment_color = "red"

        metrics_text += f"📊 Sentiment: [{sentiment_color}]{sentiment_label} ({sentiment_score:.2f})[/]\n"

        # Portfolio heat
        heat_color = "green" if portfolio_heat < 0.3 else "yellow" if portfolio_heat < 0.6 else "red"
        metrics_text += f"🔥 Heat: [{heat_color}]{format_pct(portfolio_heat * 100)}[/]\n"

        # P&L
        pnl_color = "green" if unrealized_pnl >= 0 else "red"
        metrics_text += f"💹 Unrealized P&L: [{pnl_color}]{format_usd(unrealized_pnl)} ({format_pct(unrealized_pnl_pct)})[/]"

        return Panel(
            metrics_text.strip(),
            title="[bold cyan]JARBIS CRYPTO[/] Live Metrics",
            border_style="cyan",
        )

    def render_positions_panel(self, positions: List[Dict]) -> Panel:
        """Render open positions panel."""
        if not positions:
            return Panel(
                "[yellow]No open positions[/]",
                title="Open Positions",
                border_style="blue",
            )

        table = Table(title="Open Positions", show_header=True, header_style="bold magenta")
        table.add_column("Ticker", style="cyan")
        table.add_column("Direction", style="magenta")
        table.add_column("Qty", style="green")
        table.add_column("Entry", style="yellow")
        table.add_column("Leverage", style="blue")
        table.add_column("Time", style="white")

        for pos in positions:
            direction_text = f"[green]LONG[/]" if pos["direction"] == "long" else f"[red]SHORT[/]"
            table.add_row(
                pos["ticker"],
                direction_text,
                format_crypto(pos["quantity"]),
                f"${pos['entry_price']:.2f}",
                f"{pos['leverage']:.2f}x",
                pos["entry_time"].split("T")[1][:8] if "T" in pos["entry_time"] else pos["entry_time"],
            )

        return Panel(table, border_style="blue")

    def render_trades_panel(self, recent_trades: List[Dict]) -> Panel:
        """Render recent trades panel."""
        if not recent_trades:
            return Panel(
                "[yellow]No recent trades[/]",
                title="Recent Trades",
                border_style="green",
            )

        table = Table(title="Last 10 Trades", show_header=True, header_style="bold green")
        table.add_column("Ticker", style="cyan")
        table.add_column("Direction", style="magenta")
        table.add_column("Entry", style="yellow")
        table.add_column("Exit", style="yellow")
        table.add_column("P&L", style="white")
        table.add_column("Reason", style="blue")

        for trade in recent_trades[:10]:
            pnl = trade.get("pnl_dollars", 0)
            pnl_pct = trade.get("pnl_pct", 0)
            pnl_color = "green" if pnl >= 0 else "red"
            direction_text = f"[green]LONG[/]" if trade["direction"] == "long" else f"[red]SHORT[/]"

            table.add_row(
                trade["ticker"],
                direction_text,
                f"${trade['entry_price']:.2f}",
                f"${trade.get('exit_price', 0):.2f}" if trade.get("exit_price") else "-",
                f"[{pnl_color}]{format_usd(pnl)} ({format_pct(pnl_pct)})[/]",
                trade.get("exit_reason", "open"),
            )

        return Panel(table, border_style="green")

    def render_risk_panel(
        self,
        max_drawdown_pct: float,
        win_rate_pct: float,
        total_trades: int,
        avg_win_pct: float,
        avg_loss_pct: float,
    ) -> Panel:
        """Render risk metrics panel."""
        risk_text = ""

        # Drawdown
        dd_color = "green" if max_drawdown_pct > -5 else "yellow" if max_drawdown_pct > -10 else "red"
        risk_text += f"📉 Max Drawdown: [{dd_color}]{format_pct(max_drawdown_pct)}[/]\n"

        # Win rate
        wr_color = "green" if win_rate_pct > 55 else "yellow" if win_rate_pct > 50 else "red"
        risk_text += f"🎯 Win Rate: [{wr_color}]{format_pct(win_rate_pct)}[/] ({total_trades} trades)\n"

        # Avg win/loss
        risk_text += f"✅ Avg Win: {format_pct(avg_win_pct)}\n"
        risk_text += f"❌ Avg Loss: {format_pct(avg_loss_pct)}"

        return Panel(
            risk_text.strip(),
            title="Risk Metrics",
            border_style="red",
        )

    def print_banner(self):
        """Print startup banner."""
        banner = """
╔═══════════════════════════════════════════════════════╗
║         🚀 JARBIS CRYPTO 24/7 TRADING BOT 🚀         ║
║                                                       ║
║   Dynamic Leverage • Smart Money Signals • News      ║
║         Sentiment • On-Chain Data • Risk First       ║
║                                                       ║
║                   PAPER MODE ENABLED                 ║
╚═══════════════════════════════════════════════════════╝
        """
        self.console.print(banner, style="bold cyan")

    def print_command_help(self):
        """Print command help."""
        help_text = """
[bold cyan]COMMANDS:[/]

[bold]Trading:[/]
  !buy TICKER PRICE       Buy at limit price
  !sell TICKER PRICE      Sell at limit price
  !close [TICKER]         Close all or specific ticker
  !emergency              Close all positions (panic button)

[bold]Risk & Leverage:[/]
  !risk increase PCT      Increase max loss %
  !risk decrease PCT      Decrease max loss %
  !leverage set MULT      Override leverage
  !leverage auto          Return to dynamic leverage

[bold]Mode:[/]
  !paper                  Switch to paper trading
  !live                   Switch to live (⚠️ with 3x confirmation)

[bold]News:[/]
  !news TICKER: MESSAGE   Inject manual news

[bold]Info:[/]
  !stats                  Show cumulative stats
  !heat                   Show portfolio heat
  !positions              List open positions
  !sentiment              Show sentiment scores
  !help                   Show this help
  !quit                   Exit bot
        """
        self.console.print(help_text)

    def print_signal(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
        sentiment_score: float,
        reason: str,
    ):
        """Print signal alert."""
        direction_emoji = "🟢" if direction == "long" else "🔴"
        direction_text = f"[green]LONG[/]" if direction == "long" else f"[red]SHORT[/]"

        signal_text = f"""
{direction_emoji} [bold]{direction_text}[/] SIGNAL: {ticker}

Entry:  ${entry_price:.2f}
SL:     ${stop_loss:.2f}
TP1:    ${take_profit_1:.2f}
TP2:    ${take_profit_2:.2f}

Sentiment: {format_pct(sentiment_score * 100)}
Reason: {reason}
        """

        self.console.print(
            Panel(
                signal_text.strip(),
                title=f"[bold magenta]{ticker} Signal[/]",
                border_style="magenta",
            )
        )

    def print_trade_closed(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        pnl_dollars: float,
        pnl_pct: float,
        exit_reason: str,
    ):
        """Print trade closure alert."""
        pnl_color = "green" if pnl_dollars >= 0 else "red"
        reason_emoji = {
            "tp1": "✅",
            "tp2": "✅",
            "sl": "❌",
            "timeout": "⏱️ ",
            "emergency": "🚨",
        }.get(exit_reason, "❓")

        trade_text = f"""
{reason_emoji} {exit_reason.upper()}

{ticker} {direction.upper()}
Entry:  ${entry_price:.2f}
Exit:   ${exit_price:.2f}

P&L: [{pnl_color}]{format_usd(pnl_dollars)} ({format_pct(pnl_pct)})[/]
        """

        self.console.print(
            Panel(
                trade_text.strip(),
                title=f"[bold]{ticker} Closed[/]",
                border_style=pnl_color,
            )
        )

    def print_error(self, message: str):
        """Print error message."""
        self.console.print(f"[bold red]❌ ERROR: {message}[/]")

    def print_info(self, message: str):
        """Print info message."""
        self.console.print(f"[bold cyan]ℹ️  {message}[/]")

    def print_warning(self, message: str):
        """Print warning message."""
        self.console.print(f"[bold yellow]⚠️  {message}[/]")

    def print_success(self, message: str):
        """Print success message."""
        self.console.print(f"[bold green]✅ {message}[/]")
