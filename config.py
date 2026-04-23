from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import List


class BrokerConfig(BaseModel):
    """Broker API configuration."""
    api_key: str
    api_secret: str
    testnet: bool = True


class RiskConfig(BaseModel):
    """Risk management parameters."""
    portfolio_size_usd: float = 1000
    max_loss_pct: float = 0.02
    max_leverage: float = 3.0
    base_leverage: float = 2.0
    max_position_size_pct: float = 0.05
    emergency_iv_rank_threshold: float = 0.90
    position_timeout_minutes: int = 30


class TradingConfig(BaseModel):
    """Trading parameters."""
    pairs: List[str] = ["BTC", "ETH", "SOL", "XRP"]
    timeframes: List[str] = ["4h", "1h", "15m"]


class Settings(BaseSettings):
    """Main configuration from .env."""

    # Broker configuration
    bybit_api_key: str = Field(default="", alias="BYBIT_API_KEY")
    bybit_api_secret: str = Field(default="", alias="BYBIT_API_SECRET")
    bybit_testnet: bool = Field(default=True, alias="BYBIT_TESTNET")

    binance_api_key: str = Field(default="", alias="BINANCE_API_KEY")
    binance_api_secret: str = Field(default="", alias="BINANCE_API_SECRET")
    binance_testnet: bool = Field(default=True, alias="BINANCE_TESTNET")

    # Portfolio & Risk
    portfolio_size_usd: float = Field(default=1000, alias="PORTFOLIO_SIZE_USD")
    max_loss_pct: float = Field(default=0.02, alias="MAX_LOSS_PCT")
    max_leverage: float = Field(default=3.0, alias="MAX_LEVERAGE")
    base_leverage: float = Field(default=2.0, alias="BASE_LEVERAGE")
    max_position_size_pct: float = Field(default=0.05, alias="MAX_POSITION_SIZE_PCT")

    # Trading Pairs
    trading_pairs: str = Field(default="BTC,ETH,SOL,XRP", alias="TRADING_PAIRS")
    timeframes: str = Field(default="4h,1h,15m", alias="TIMEFRAMES")

    # Sentiment & News APIs
    cryptocompare_api_key: str = Field(default="", alias="CRYPTOCOMPARE_API_KEY")
    santiment_api_key: str = Field(default="", alias="SANTIMENT_API_KEY")
    newsapi_api_key: str = Field(default="", alias="NEWSAPI_API_KEY")
    glassnode_api_key: str = Field(default="", alias="GLASSNODE_API_KEY")

    # Webhook & Alerts
    webhook_port: int = Field(default=5000, alias="WEBHOOK_PORT")
    webhook_secret: str = Field(default="your_secret_key", alias="WEBHOOK_SECRET")
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")

    # Paper/Live & Logging
    paper_trade: bool = Field(default=True, alias="PAPER_TRADE")
    log_db: str = Field(default="trades.db", alias="LOG_DB")
    log_csv: str = Field(default="trades.csv", alias="LOG_CSV")

    # Advanced
    emergency_iv_rank_threshold: float = Field(default=0.90, alias="EMERGENCY_IV_RANK_THRESHOLD")
    position_timeout_minutes: int = Field(default=30, alias="POSITION_TIMEOUT_MINUTES")
    enable_on_chain_signals: bool = Field(default=True, alias="ENABLE_ON_CHAIN_SIGNALS")
    enable_funding_rate_harvest: bool = Field(default=True, alias="ENABLE_FUNDING_RATE_HARVEST")

    class Config:
        env_file = ".env"
        case_sensitive = False

    def get_pairs(self) -> List[str]:
        """Get list of trading pairs."""
        return [p.strip().upper() for p in self.trading_pairs.split(",")]

    def get_timeframes(self) -> List[str]:
        """Get list of timeframes."""
        return [tf.strip() for tf in self.timeframes.split(",")]

    def get_bybit_config(self) -> BrokerConfig:
        """Get Bybit broker config."""
        return BrokerConfig(
            api_key=self.bybit_api_key,
            api_secret=self.bybit_api_secret,
            testnet=self.bybit_testnet,
        )

    def get_binance_config(self) -> BrokerConfig:
        """Get Binance broker config."""
        return BrokerConfig(
            api_key=self.binance_api_key,
            api_secret=self.binance_api_secret,
            testnet=self.binance_testnet,
        )

    def get_risk_config(self) -> RiskConfig:
        """Get risk management config."""
        return RiskConfig(
            portfolio_size_usd=self.portfolio_size_usd,
            max_loss_pct=self.max_loss_pct,
            max_leverage=self.max_leverage,
            base_leverage=self.base_leverage,
            max_position_size_pct=self.max_position_size_pct,
            emergency_iv_rank_threshold=self.emergency_iv_rank_threshold,
            position_timeout_minutes=self.position_timeout_minutes,
        )


# Global config instance
settings = Settings()
