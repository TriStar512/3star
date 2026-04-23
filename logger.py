"""Trade logging and statistics tracking."""

import sqlite3
import csv
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from utils import now_utc, format_timestamp, to_utc

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Trade record."""
    trade_id: str
    ticker: str
    direction: str  # 'long' or 'short'
    entry_price: float
    entry_time: datetime
    quantity: float
    leverage: float
    entry_leverage: float
    sentiment_score: float
    on_chain_signal: str
    paper_trade: bool
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl_dollars: Optional[float] = None
    pnl_pct: Optional[float] = None
    sentiment_label: Optional[str] = None
    exit_reason: Optional[str] = None  # 'tp1', 'tp2', 'sl', 'timeout', 'emergency'


@dataclass
class PortfolioSnapshot:
    """Portfolio state snapshot."""
    snapshot_id: str
    timestamp: datetime
    total_balance: float
    available_margin: float
    unrealized_pnl: float
    portfolio_heat_pct: float
    leverage_avg: float
    iv_rank: Optional[float] = None


class TradeLogger:
    """SQLite-based trade logger."""

    def __init__(self, db_path: str = "trades.db", csv_path: str = "trades.csv"):
        self.db_path = db_path
        self.csv_path = csv_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_time DATETIME NOT NULL,
                exit_price REAL,
                exit_time DATETIME,
                quantity REAL NOT NULL,
                leverage REAL NOT NULL,
                entry_leverage REAL NOT NULL,
                pnl_dollars REAL,
                pnl_pct REAL,
                sentiment_score REAL NOT NULL,
                sentiment_label TEXT,
                on_chain_signal TEXT,
                exit_reason TEXT,
                paper_trade BOOLEAN NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create portfolio snapshots table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                total_balance REAL NOT NULL,
                available_margin REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                portfolio_heat_pct REAL NOT NULL,
                leverage_avg REAL NOT NULL,
                iv_rank REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create signals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                timestamp DATETIME NOT NULL,
                sentiment_score REAL,
                on_chain_signal TEXT,
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")

    def log_trade(self, trade: Trade):
        """Log a trade entry."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO trades (
                    trade_id, ticker, direction, entry_price, entry_time,
                    exit_price, exit_time, quantity, leverage, entry_leverage,
                    pnl_dollars, pnl_pct, sentiment_score, sentiment_label,
                    on_chain_signal, exit_reason, paper_trade
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.trade_id,
                trade.ticker,
                trade.direction,
                trade.entry_price,
                format_timestamp(trade.entry_time),
                trade.exit_price,
                format_timestamp(trade.exit_time) if trade.exit_time else None,
                trade.quantity,
                trade.leverage,
                trade.entry_leverage,
                trade.pnl_dollars,
                trade.pnl_pct,
                trade.sentiment_score,
                trade.sentiment_label,
                trade.on_chain_signal,
                trade.exit_reason,
                trade.paper_trade,
            ))

            conn.commit()
            conn.close()
            logger.debug(f"Logged trade: {trade.trade_id}")
        except Exception as e:
            logger.error(f"Failed to log trade: {str(e)}")

    def update_trade(self, trade_id: str, exit_price: float, exit_time: datetime,
                    pnl_dollars: float, pnl_pct: float, exit_reason: str):
        """Update trade with exit information."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE trades
                SET exit_price = ?, exit_time = ?, pnl_dollars = ?, pnl_pct = ?, exit_reason = ?
                WHERE trade_id = ?
            """, (exit_price, format_timestamp(exit_time), pnl_dollars, pnl_pct, exit_reason, trade_id))

            conn.commit()
            conn.close()
            logger.debug(f"Updated trade: {trade_id}")
        except Exception as e:
            logger.error(f"Failed to update trade: {str(e)}")

    def log_portfolio_snapshot(self, snapshot: PortfolioSnapshot):
        """Log portfolio state snapshot."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO portfolio_snapshots (
                    snapshot_id, timestamp, total_balance, available_margin,
                    unrealized_pnl, portfolio_heat_pct, leverage_avg, iv_rank
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.snapshot_id,
                format_timestamp(snapshot.timestamp),
                snapshot.total_balance,
                snapshot.available_margin,
                snapshot.unrealized_pnl,
                snapshot.portfolio_heat_pct,
                snapshot.leverage_avg,
                snapshot.iv_rank,
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log portfolio snapshot: {str(e)}")

    def get_trades(self, limit: int = 100) -> List[Trade]:
        """Get recent trades."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?
            """, (limit,))

            trades = []
            for row in cursor.fetchall():
                trades.append(self._row_to_trade(row))

            conn.close()
            return trades
        except Exception as e:
            logger.error(f"Failed to get trades: {str(e)}")
            return []

    def get_trade_stats(self) -> Dict[str, Any]:
        """Calculate trade statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Total trades
            cursor.execute("SELECT COUNT(*) as count FROM trades WHERE exit_price IS NOT NULL")
            total_trades = cursor.fetchone()[0]

            if total_trades == 0:
                return {
                    "total_trades": 0,
                    "win_rate": 0,
                    "total_pnl_dollars": 0,
                    "total_pnl_pct": 0,
                    "avg_pnl_pct": 0,
                    "best_trade": 0,
                    "worst_trade": 0,
                    "sharpe_ratio": 0,
                }

            # Winning trades
            cursor.execute("SELECT COUNT(*) as count FROM trades WHERE pnl_dollars > 0 AND exit_price IS NOT NULL")
            winning_trades = cursor.fetchone()[0]

            # Total P&L
            cursor.execute("SELECT COALESCE(SUM(pnl_dollars), 0) as total FROM trades WHERE exit_price IS NOT NULL")
            total_pnl_dollars = cursor.fetchone()[0]

            cursor.execute("SELECT COALESCE(SUM(pnl_pct), 0) as total FROM trades WHERE exit_price IS NOT NULL")
            total_pnl_pct = cursor.fetchone()[0]

            # Best and worst
            cursor.execute("SELECT MAX(pnl_pct) as best FROM trades WHERE exit_price IS NOT NULL")
            best_pnl = cursor.fetchone()[0] or 0

            cursor.execute("SELECT MIN(pnl_pct) as worst FROM trades WHERE exit_price IS NOT NULL")
            worst_pnl = cursor.fetchone()[0] or 0

            # Average
            avg_pnl_pct = total_pnl_pct / total_trades if total_trades > 0 else 0

            conn.close()

            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            return {
                "total_trades": total_trades,
                "win_rate": win_rate,
                "total_pnl_dollars": total_pnl_dollars,
                "total_pnl_pct": total_pnl_pct,
                "avg_pnl_pct": avg_pnl_pct,
                "best_trade": best_pnl,
                "worst_trade": worst_pnl,
            }
        except Exception as e:
            logger.error(f"Failed to calculate trade stats: {str(e)}")
            return {}

    def export_csv(self):
        """Export trades to CSV."""
        try:
            trades = self.get_trades(limit=10000)
            if not trades:
                logger.warning("No trades to export")
                return

            with open(self.csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "trade_id", "ticker", "direction", "entry_price", "entry_time",
                    "exit_price", "exit_time", "quantity", "leverage", "entry_leverage",
                    "pnl_dollars", "pnl_pct", "sentiment_score", "sentiment_label",
                    "on_chain_signal", "exit_reason", "paper_trade"
                ])
                writer.writeheader()
                for trade in trades:
                    row = asdict(trade)
                    row["entry_time"] = format_timestamp(trade.entry_time)
                    row["exit_time"] = format_timestamp(trade.exit_time) if trade.exit_time else None
                    writer.writerow(row)

            logger.info(f"Exported {len(trades)} trades to {self.csv_path}")
        except Exception as e:
            logger.error(f"Failed to export CSV: {str(e)}")

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> Trade:
        """Convert database row to Trade object."""
        return Trade(
            trade_id=row["trade_id"],
            ticker=row["ticker"],
            direction=row["direction"],
            entry_price=row["entry_price"],
            entry_time=datetime.fromisoformat(row["entry_time"]) if isinstance(row["entry_time"], str) else row["entry_time"],
            exit_price=row["exit_price"],
            exit_time=datetime.fromisoformat(row["exit_time"]) if isinstance(row["exit_time"], str) and row["exit_time"] else None,
            quantity=row["quantity"],
            leverage=row["leverage"],
            entry_leverage=row["entry_leverage"],
            pnl_dollars=row["pnl_dollars"],
            pnl_pct=row["pnl_pct"],
            sentiment_score=row["sentiment_score"],
            sentiment_label=row["sentiment_label"],
            on_chain_signal=row["on_chain_signal"],
            exit_reason=row["exit_reason"],
            paper_trade=bool(row["paper_trade"]),
        )
