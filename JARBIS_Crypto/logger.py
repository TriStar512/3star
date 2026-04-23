"""SQLite trade logger + CSV mirror + in-memory stats."""
from __future__ import annotations

import csv
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Iterable, List, Optional

from .broker import Position
from .config import Settings, get_settings
from .orders import ExecutionResult
from .utils import classify_sentiment, utcnow

log = logging.getLogger(__name__)


SCHEMA = """
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
    paper_trade INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    total_balance REAL NOT NULL,
    available_margin REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    portfolio_heat_pct REAL NOT NULL,
    leverage_avg REAL NOT NULL,
    iv_rank REAL
);

CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_time);
"""


@dataclass
class Stats:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    best_trade: float
    worst_trade: float


class TradeLogger:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.db_path = self.settings.log_db
        self.csv_path = self.settings.log_csv
        self._init_db()
        self._init_csv()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as cx:
            cx.executescript(SCHEMA)

    def _init_csv(self) -> None:
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "trade_id", "ticker", "direction", "entry_price", "entry_time",
                    "exit_price", "exit_time", "quantity", "leverage", "pnl_dollars",
                    "pnl_pct", "sentiment_score", "sentiment_label", "on_chain_signal",
                    "exit_reason", "paper_trade",
                ])

    # ---- writes ----

    def log_open(
        self,
        result: ExecutionResult,
        on_chain_label: str = "none",
    ) -> None:
        sig = result.signal
        row = (
            result.order.id, sig.ticker, sig.direction,
            sig.entry_price, utcnow().isoformat(), None, None,
            result.quantity, result.leverage.leverage, result.leverage.leverage,
            None, None, sig.sentiment_score, classify_sentiment(sig.sentiment_score),
            on_chain_label, None, 1 if self.settings.paper_trade else 0,
        )
        with sqlite3.connect(self.db_path) as cx:
            cx.execute(
                """
                INSERT OR REPLACE INTO trades (
                    trade_id, ticker, direction, entry_price, entry_time,
                    exit_price, exit_time, quantity, leverage, entry_leverage,
                    pnl_dollars, pnl_pct, sentiment_score, sentiment_label,
                    on_chain_signal, exit_reason, paper_trade
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                row,
            )

    def log_close(self, pos: Position) -> None:
        if not pos.closed or pos.exit_price is None:
            return
        pnl = (pos.exit_price - pos.entry_price) * pos.quantity
        if pos.direction == "short":
            pnl = -pnl
        pnl_pct = pnl / (pos.entry_price * pos.quantity) if pos.quantity else 0.0
        with sqlite3.connect(self.db_path) as cx:
            cx.execute(
                """
                UPDATE trades SET
                    exit_price=?, exit_time=?, pnl_dollars=?, pnl_pct=?, exit_reason=?
                WHERE trade_id=?
                """,
                (
                    pos.exit_price,
                    (pos.exit_time or utcnow()).isoformat() if pos.exit_time else utcnow().isoformat(),
                    pnl,
                    pnl_pct,
                    pos.exit_reason,
                    pos.order_id,
                ),
            )
        with open(self.csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                pos.order_id, pos.ticker, pos.direction,
                pos.entry_price, pos.opened_at.isoformat(),
                pos.exit_price, (pos.exit_time or utcnow()).isoformat(),
                pos.quantity, pos.leverage, pnl, pnl_pct,
                "", "", "", pos.exit_reason,
                1 if self.settings.paper_trade else 0,
            ])

    def snapshot(
        self,
        total_balance: float,
        available_margin: float,
        unrealized_pnl: float,
        portfolio_heat: float,
        leverage_avg: float,
        iv_rank: Optional[float] = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as cx:
            cx.execute(
                """
                INSERT INTO portfolio_snapshots (
                    timestamp, total_balance, available_margin,
                    unrealized_pnl, portfolio_heat_pct, leverage_avg, iv_rank
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (utcnow().isoformat(), total_balance, available_margin,
                 unrealized_pnl, portfolio_heat, leverage_avg, iv_rank),
            )

    # ---- reads ----

    def stats(self, limit: int = 50) -> Stats:
        with sqlite3.connect(self.db_path) as cx:
            rows = cx.execute(
                "SELECT pnl_dollars FROM trades WHERE pnl_dollars IS NOT NULL "
                "ORDER BY exit_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        pnls = [r[0] for r in rows]
        if not pnls:
            return Stats(0, 0, 0, 0.0, 0.0, 0.0, 0.0)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        return Stats(
            total_trades=len(pnls),
            wins=wins,
            losses=losses,
            win_rate=wins / len(pnls),
            total_pnl=sum(pnls),
            best_trade=max(pnls),
            worst_trade=min(pnls),
        )

    def recent_trades(self, limit: int = 20) -> List[tuple]:
        with sqlite3.connect(self.db_path) as cx:
            return cx.execute(
                """
                SELECT ticker, direction, entry_price, exit_price, quantity,
                       leverage, pnl_dollars, pnl_pct, sentiment_label,
                       exit_reason, entry_time
                FROM trades ORDER BY entry_time DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
