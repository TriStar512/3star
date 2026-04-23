from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Broker API Keys
    bybit_api_key: str
    bybit_api_secret: str
    bybit_testnet: bool = True

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = False

    # Portfolio & Risk
    portfolio_size_usd: float = 1000.0
    max_loss_pct: float = 0.02
    max_leverage: float = 3.0
    base_leverage: float = 2.0
    max_position_size_pct: float = 0.05

    # Trading Pairs
    trading_pairs: List[str] = ["BTC", "ETH", "SOL", "XRP"]
    timeframes: List[str] = ["4h", "1h", "15m"]

    # Sentiment & News
    cryptocompare_api_key: str = ""
    santiment_api_key: str = ""
    newsapi_api_key: str = ""
    glassnode_api_key: str = ""

    # Webhook & Alerts
    webhook_port: int = 5000
    webhook_secret: str = "your_secret_key"
    slack_webhook_url: str = ""

    # Paper/Live & Logging
    paper_trade: bool = True
    log_db: str = "trades.db"
    log_csv: str = "trades.csv"

    # Advanced
    emergency_iv_rank_threshold: float = 0.90
    position_timeout_minutes: int = 30
    enable_on_chain_signals: bool = True
    enable_funding_rate_harvest: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
