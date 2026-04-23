from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from datetime import datetime
from typing import Optional, List, Dict
from orders import TradeExit
import logging

logger = logging.getLogger(__name__)


class Dashboard:
    """Terminal UI with Rich."""

    def __init__(self):
        self.console = Console()

    def print_banner(self) -> None:
        """Print welcome banner."""
        banner = """
        [bold cyan]╔══════════════════════════════════════════╗[/bold cyan]
        [bold cyan]║   JARBIS CRYPTO 24/7 TRADING BOT        ║[/bold cyan]
        [bold cyan]║   Vilkov 0DTE + Dynamic Leverage        ║[/bold cyan]
        [bold cyan]╚══════════════════════════════════════════╝[/bold cyan]
        """
        self.console.print(banner)

    def print_signal_alert(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        sentiment_score: float,
        reason: str,
    ) -> None:
        """Print signal generation alert."""
        signal_type = "[bold green]BUY[/bold green]" if direction == "long" else "[bold red]SELL[/bold red]"
        sentiment_color = "green" if sentiment_score > 0.3 else "yellow" if sentiment_score > -0.3 else "red"

        panel = Panel(
            f"{signal_type} {ticker} @ ${entry_price:.2f}\n"
            f"Sentiment: [bold {sentiment_color}]{sentiment_score:.2f}[/bold {sentiment_color}]\n"
            f"Reason: {reason}",
            title="[bold yellow]New Signal[/bold yellow]",
            border_style="yellow",
        )
        self.console.print(panel)

    def print_order_status(
        self,
        order_id: str,
        ticker: str,
        direction: str,
        quantity: float,
        entry_price: float,
        status: str,
    ) -> None:
        """Print order execution status."""
        direction_text = "[bold green]BUY[/bold green]" if direction == "long" else "[bold red]SELL[/bold red]"
        status_color = "green" if status == "filled" else "yellow"

        self.console.print(
            f"[{status_color}]✓[/{status_color}] {direction_text} Order: {quantity:.6f} {ticker} @ "
            f"${entry_price:.2f} | Status: [{status_color}]{status.upper()}[/{status_color}]"
        )

    def print_trade_closed(
        self,
        trade_exit: TradeExit,
        pnl_color: str = "white",
    ) -> None:
        """Print trade closure summary."""
        trade = trade_exit.entry
        pnl_pct_text = f"{trade_exit.pnl_pct:.2%}"

        panel = Panel(
            f"[bold]{trade.direction.upper()}[/bold] {trade.ticker} CLOSED\n"
            f"Entry: ${trade.entry_price:.2f} | Exit: ${trade_exit.exit_price:.2f}\n"
            f"P&L: [bold {pnl_color}]${trade_exit.pnl_dollars:.2f} ({pnl_pct_text})[/bold {pnl_color}]\n"
            f"Reason: {trade_exit.exit_reason.value.upper()}",
            title="[bold cyan]Trade Closed[/bold cyan]",
            border_style="cyan",
        )
        self.console.print(panel)

    def print_metrics_panel(
        self,
        leverage: float,
        sentiment_score: float,
        open_positions: int,
        unrealized_pnl: float,
        portfolio_heat_pct: float,
        win_rate: Optional[float] = None,
    ) -> None:
        """Print live metrics panel."""
        sentiment_label = "Very Bearish" if sentiment_score < -0.6 else "Bearish" if sentiment_score < -0.2 else "Neutral" if sentiment_score < 0.2 else "Bullish" if sentiment_score < 0.6 else "Very Bullish"
        sentiment_color = "red" if sentiment_score < -0.3 else "yellow" if sentiment_score < 0.3 else "green"

        pnl_color = "green" if unrealized_pnl > 0 else "red"

        table = Table(title="[bold cyan]Live Metrics[/bold cyan]", border_style="cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        table.add_row("Current Leverage", f"[bold]{leverage:.2f}x[/bold]")
        table.add_row("Sentiment", f"[bold {sentiment_color}]{sentiment_label} ({sentiment_score:.2f})[/bold {sentiment_color}]")
        table.add_row("Open Positions", str(open_positions))
        table.add_row("Unrealized P&L", f"[bold {pnl_color}]${unrealized_pnl:.2f}[/bold {pnl_color}]")
        table.add_row("Portfolio Heat", f"{portfolio_heat_pct:.1%}")
        if win_rate is not None:
            table.add_row("Win Rate", f"{win_rate:.1%}")

        self.console.print(table)

    def print_recent_trades(self, trades: List[Dict], limit: int = 10) -> None:
        """Print table of recent trades."""
        if not trades:
            self.console.print("[yellow]No closed trades yet[/yellow]")
            return

        table = Table(title="[bold cyan]Recent Trades[/bold cyan]", border_style="cyan")
        table.add_column("Ticker", style="bold")
        table.add_column("Direction", justify="center")
        table.add_column("Entry", justify="right")
        table.add_column("Exit", justify="right")
        table.add_column("P&L %", justify="right")
        table.add_column("Exit Reason")

        for trade in trades[:limit]:
            pnl_pct = trade.get("pnl_pct", 0.0)
            pnl_color = "green" if pnl_pct > 0 else "red"

            direction_text = "LONG" if trade["direction"] == "long" else "SHORT"

            table.add_row(
                trade["ticker"],
                direction_text,
                f"${trade['entry_price']:.2f}",
                f"${trade['exit_price']:.2f}",
                f"[bold {pnl_color}]{pnl_pct:.2%}[/bold {pnl_color}]",
                trade.get("exit_reason", "N/A"),
            )

        self.console.print(table)

    def print_error(self, message: str) -> None:
        """Print error message."""
        panel = Panel(f"[bold red]{message}[/bold red]", title="[bold red]ERROR[/bold red]", border_style="red")
        self.console.print(panel)

    def print_info(self, message: str) -> None:
        """Print info message."""
        self.console.print(f"[bold cyan]ℹ[/bold cyan] {message}")

    def print_warning(self, message: str) -> None:
        """Print warning message."""
        self.console.print(f"[bold yellow]⚠[/bold yellow] {message}")

    def print_success(self, message: str) -> None:
        """Print success message."""
        self.console.print(f"[bold green]✓[/bold green] {message}")
