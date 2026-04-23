"""JARBIS Crypto configuration.

Loads settings from .env via pydantic-settings. All runtime knobs
flow through a single ``Settings`` instance so the rest of the bot
can depend on typed values instead of raw env lookups.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ------------------------------------------------------------------
# Hard rule: bot only trades the 10 most liquid perpetual coins.
# Enforced below via a validator; mutating this list is intentional
# and should be accompanied by an updated dashboard universe too.
# ------------------------------------------------------------------
ALLOWED_COINS: List[str] = [
    "BTC", "ETH", "BNB", "SOL", "XRP",
    "ADA", "DOGE", "AVAX", "LINK", "MATIC",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Execution venue: Hyperliquid (DEX perps, Metamask self-custody, no KYC) ---
    # Hyperliquid is the single trading venue. Bybit + Binance are retained
    # only as read-only data redundancy for candles / tickers when the
    # Hyperliquid info endpoint is degraded.
    hl_api_url: str = "https://api.hyperliquid.xyz"
    hl_wallet_address: str = ""  # 0x... Metamask account used to sign trades
    hl_private_key: str = ""     # only used in live mode; keep off disk in prod

    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    primary_broker: Literal["hyperliquid", "bybit", "binance"] = "hyperliquid"

    # Portfolio & risk
    portfolio_size_usd: float = 1000.0
    max_loss_pct: float = 0.02
    max_leverage: float = 3.0
    base_leverage: float = 2.0
    max_position_size_pct: float = 0.05
    max_concurrent_trades: int = 4

    # Trading pairs & timeframes
    trading_pairs: List[str] = Field(default_factory=lambda: list(ALLOWED_COINS))
    timeframes: List[str] = Field(default_factory=lambda: ["4h", "1h", "15m"])

    # Sentiment & data APIs
    cryptocompare_api_key: str = ""
    santiment_api_key: str = ""
    newsapi_api_key: str = ""
    glassnode_api_key: str = ""
    nansen_api_key: str = ""

    # Webhooks / alerts
    webhook_port: int = 5000
    webhook_secret: str = "change_me_please"
    slack_webhook_url: Optional[str] = None

    # Paper / live & logging
    paper_trade: bool = True
    log_db: str = "trades.db"
    log_csv: str = "trades.csv"
    log_level: str = "INFO"

    # Advanced
    emergency_iv_rank_threshold: float = 0.90
    position_timeout_minutes: int = 30
    enable_on_chain_signals: bool = True
    enable_funding_rate_harvest: bool = True

    # Engine
    signal_poll_seconds: int = 30
    dashboard_refresh_seconds: int = 2

    @field_validator("trading_pairs", "timeframes", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip().upper() if p.strip().isalpha() else p.strip()
                    for p in v.split(",") if p.strip()]
        return v

    @field_validator("trading_pairs")
    @classmethod
    def _enforce_top10_universe(cls, v: List[str]) -> List[str]:
        invalid = [t for t in v if t not in ALLOWED_COINS]
        if invalid:
            raise ValueError(
                f"trading_pairs must be a subset of top-10: {ALLOWED_COINS}. "
                f"Disallowed: {invalid}"
            )
        return v

    @field_validator("max_loss_pct", "max_position_size_pct")
    @classmethod
    def _validate_pct(cls, v):
        if not 0 < v < 1:
            raise ValueError("percentage must be between 0 and 1")
        return v

    @field_validator("max_leverage", "base_leverage")
    @classmethod
    def _validate_leverage(cls, v):
        if v < 1.0:
            raise ValueError("leverage must be >= 1.0")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
