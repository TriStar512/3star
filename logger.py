import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict
from orders import TradeExit, ExitReason
import logging

logger = logging.getLogger(__name__)


class TradeLogger:
    """Log trades to SQLite database."""

    def __init__(self, db_path: str = "trades.db"):
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()

        cursor.execute(
            """
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
                pnl_dollars REAL,
                pnl_pct REAL,
                sentiment_score REAL NOT NULL,
                sentiment_label TEXT,
                on_chain_signal TEXT,
                exit_reason TEXT,
                paper_trade BOOLEAN NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                total_balance REAL NOT NULL,
                available_margin REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                portfolio_heat_pct REAL NOT NULL,
                leverage_avg REAL NOT NULL,
                iv_rank REAL
            )
        """
        )

        self.conn.commit()
        logger.info(f"Initialized trade database at {self.db_path}")

    def log_trade(
        self,
        trade_exit: TradeExit,
        sentiment_score: float,
        sentiment_label: str,
        on_chain_signal: str,
        paper_trade: bool,
    ) -> None:
        """Log closed trade to database."""
        try:
            trade = trade_exit.entry
            trade_id = trade.order_id

            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO trades (
                    trade_id, ticker, direction, entry_price, entry_time,
                    exit_price, exit_time, quantity, leverage, pnl_dollars,
                    pnl_pct, sentiment_score, sentiment_label, on_chain_signal,
                    exit_reason, paper_trade
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    trade_id,
                    trade.ticker,
                    trade.direction,
                    trade.entry_price,
                    trade.entry_time,
                    trade_exit.exit_price,
                    trade_exit.exit_time,
                    trade_exit.quantity_closed,
                    trade.leverage,
                    trade_exit.pnl_dollars,
                    trade_exit.pnl_pct,
                    sentiment_score,
                    sentiment_label,
                    on_chain_signal,
                    trade_exit.exit_reason.value,
                    paper_trade,
                ),
            )

            self.conn.commit()
            logger.info(f"Logged trade {trade_id} to database")

        except Exception as e:
            logger.error(f"Error logging trade: {e}")
            if self.conn:
                self.conn.rollback()

    def get_recent_trades(self, limit: int = 20) -> List[Dict]:
        """Get recent closed trades."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trades
                ORDER BY exit_time DESC
                LIMIT ?
            """,
                (limit,),
            )

            columns = [desc[0] for desc in cursor.description]
            trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return trades

        except Exception as e:
            logger.error(f"Error fetching recent trades: {e}")
            return []

    def get_stats(self) -> Dict:
        """Get aggregate statistics."""
        try:
            cursor = self.conn.cursor()

            # Total trades
            cursor.execute("SELECT COUNT(*) FROM trades WHERE exit_time IS NOT NULL")
            total_trades = cursor.fetchone()[0]

            # Win rate
            cursor.execute(
                "SELECT COUNT(*) FROM trades WHERE exit_time IS NOT NULL AND pnl_dollars > 0"
            )
            winning_trades = cursor.fetchone()[0]
            win_rate = (
                winning_trades / total_trades if total_trades > 0 else 0.0
            )

            # Total P&L
            cursor.execute(
                "SELECT SUM(pnl_dollars) FROM trades WHERE exit_time IS NOT NULL"
            )
            total_pnl = cursor.fetchone()[0] or 0.0

            # Average trade
            cursor.execute(
                "SELECT AVG(pnl_dollars) FROM trades WHERE exit_time IS NOT NULL"
            )
            avg_trade = cursor.fetchone()[0] or 0.0

            return {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "avg_trade": avg_trade,
            }

        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            return {}

    def log_portfolio_snapshot(
        self,
        snapshot_id: str,
        total_balance: float,
        available_margin: float,
        unrealized_pnl: float,
        portfolio_heat_pct: float,
        leverage_avg: float,
        iv_rank: Optional[float] = None,
    ) -> None:
        """Log portfolio state snapshot."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_id, timestamp, total_balance, available_margin,
                    unrealized_pnl, portfolio_heat_pct, leverage_avg, iv_rank
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    snapshot_id,
                    datetime.utcnow(),
                    total_balance,
                    available_margin,
                    unrealized_pnl,
                    portfolio_heat_pct,
                    leverage_avg,
                    iv_rank,
                ),
            )
            self.conn.commit()

        except Exception as e:
            logger.error(f"Error logging portfolio snapshot: {e}")
            if self.conn:
                self.conn.rollback()

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Trade database connection closed")
