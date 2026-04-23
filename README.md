# JARBIS Crypto 24/7 Trading Bot

A production-grade automated crypto trading bot using the Vilkov 0DTE framework adapted for crypto markets, featuring dynamic leverage scaling, real-time news sentiment analysis, and on-chain momentum indicators.

## Quick Start

1. Setup environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

2. Configure `.env` with your API keys

3. Run bot:
   ```bash
   python main.py
   ```

## Key Features

- **24/7 Multi-Timeframe Analysis**: 4H trend, 1H momentum, 15M entries
- **Dynamic Leverage**: 1x–3x based on sentiment + volatility
- **News Sentiment**: Real-time headline analysis
- **On-Chain Signals**: Whale flows, smart money, liquidations
- **Position Scaling**: TP1/TP2 + trailing stop
- **Risk Management**: Hard caps on leverage, loss, position size
- **Paper + Live**: Test mode before going live

## Architecture

- **Async-First**: Concurrent API calls for speed
- **Multi-Broker**: Bybit primary, Binance fallback
- **SQLite Logging**: Full trade audit trail
- **Rich Dashboard**: Live metrics, trades, risk panels

## Risk Management

| Rule | Value |
|------|-------|
| Max leverage | 3.0x |
| Max loss per trade | 2% of portfolio |
| Max position | 5% of portfolio |
| Max concurrent trades | 4 |
| Position timeout | 30 minutes |
| Emergency stop | Loss > 3% OR IV Rank > 90% |

## Testing

```bash
python -m pytest tests/ -v
```

## Disclaimer

**Research tool only. Not financial advice.**

- Crypto trading is high-risk
- Leverage amplifies losses
- Past performance ≠ future results
- Use capital you can afford to lose

**Trade smart. Manage risk.**
