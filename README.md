# 🚀 JARBIS Crypto - 24/7 Automated Trading Bot

A production-grade 24/7 automated trading bot for BTC, ETH, SOL, and XRP using **dynamic leverage scaling**, **real-time news sentiment analysis**, and **on-chain momentum indicators**.

## Key Innovation

**Leverage scales dynamically** with:
- 📊 **Sentiment (news):** Positive news → higher leverage, negative → lower leverage
- 📈 **Volatility (ATR):** Low realized volatility → higher leverage, high → lower leverage  
- 🔥 **Portfolio Heat:** Deployment % reduces leverage to avoid over-exposure

**Hard safety limits:**
- Max leverage: **3x** (even if conditions are ideal)
- Max loss per trade: **2%** of portfolio
- Emergency close: Portfolio loss > **3%** OR IV Rank > **90%**
- Position timeout: Auto-close after **30 minutes**

## Features

### ✅ Complete Implementation

- **Multi-Timeframe Signals** (4H trend, 1H momentum, 15M entry)
- **Dynamic Leverage Calculation** (sentiment + volatility + heat)
- **Position Sizing** (risk-first, max loss enforced)
- **Partial Profit Taking** (50% @ 1:1 R:R, 25% @ 1:2 R:R, 25% trailing)
- **Technical Indicators** (EMA, RSI, MACD, ATR, support/resistance)
- **News Sentiment Analysis** (positive/negative/neutral scoring)
- **On-Chain Signals** (smart money, whale flow, liquidation clusters)
- **Paper/Live Mode** (with 3x confirmation safety)
- **SQLite Logging** (audit trail + statistics)
- **Terminal Dashboard** (live metrics, positions, P&L)
- **Webhook Server** (external alerts and commands)
- **Comprehensive Tests** (50+ unit tests for leverage, sentiment, risk)

### 📊 Trading Pairs

Default: **BTC, ETH, SOL, XRP** (configurable)

### 🔌 Broker Integration

**Primary:** Bybit (perpetuals + spot, 24/7, low fees)  
**Fallback:** Binance (redundancy)

## Installation

### 1. Clone & Setup

```bash
git clone <repo>
cd 3star
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys and settings
```

**Required:**
- `BYBIT_API_KEY` / `BYBIT_API_SECRET` (get from Bybit)
- `PORTFOLIO_SIZE_USD` (starting capital, e.g., 1000)

**Optional:**
- `CRYPTOCOMPARE_API_KEY` (news sentiment)
- `GLASSNODE_API_KEY` (on-chain data)
- `SANTIMENT_API_KEY` (whale tracking)
- `SLACK_WEBHOOK_URL` (alerts)

### 3. Verify Installation

```bash
python -m pytest tests/ -v
```

Expected: 50+ tests passing ✅

## Usage

### Start Bot (Paper Mode)

```bash
python main.py
```

Expected output:
```
╔═══════════════════════════════════════════════════════╗
║         🚀 JARBIS CRYPTO 24/7 TRADING BOT 🚀         ║
║                                                       ║
║   Dynamic Leverage • Smart Money Signals • News      ║
║         Sentiment • On-Chain Data • Risk First       ║
║                                                       ║
║                   PAPER MODE ENABLED                 ║
╚═══════════════════════════════════════════════════════╝

[COMMANDS] Type !help for available commands
```

### Interactive Commands

```
!paper                    Switch to paper trading (safe)
!live                     Switch to live (requires 3x confirmation)
!help                     Show all commands

!buy BTC 50000           Manual long entry at limit price
!sell BTC 50000          Manual short entry at limit price
!close                   Close all positions
!close BTC               Close BTC only
!emergency               Close ALL (panic button)

!risk increase 0.03      Increase max loss to 3%
!risk decrease 0.01      Decrease to 1%
!leverage set 2.5        Override leverage to 2.5x
!leverage auto           Back to dynamic leverage

!news BTC: ETF approved  Inject manual news (affects sentiment)

!stats                   Show P&L and win rate
!heat                    Show portfolio heat %
!positions               List open positions
!sentiment               Show news sentiment
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ JARBIS Crypto 24/7 Bot                                  │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  SIGNAL LAYER              EXECUTION LAYER              │
│  ├─ Bybit/Binance API      ├─ Limit orders (no slip)  │
│  ├─ Candles (4H/1H/15M)    ├─ Position management     │
│  ├─ On-Chain (Nansen)      ├─ Partial TP scaling      │
│  └─ News Sentiment         └─ Emergency close         │
│         │                          │                    │
│         ├─ EMA (trend)             │                    │
│         ├─ RSI/MACD (momentum)     │                    │
│         ├─ ATR (volatility)    ────→ Risk Sizing       │
│         └─ Sentiment (bias)        │                    │
│                                    ↓                    │
│  MONITORING LAYER                                      │
│  ├─ Live metrics dashboard                            │
│  ├─ Trade logging (SQLite)                            │
│  ├─ Statistics (win rate, P&L)                        │
│  ├─ Webhook server (external alerts)                  │
│  └─ Terminal UI (Rich)                                │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Configuration (.env)

```env
# Broker API Keys
BYBIT_API_KEY=your_key_here
BYBIT_API_SECRET=your_secret_here
BYBIT_TESTNET=true  # Set to false for LIVE (scary!)

# Portfolio
PORTFOLIO_SIZE_USD=1000      # Starting capital
MAX_LOSS_PCT=0.02            # 2% max loss per trade
MAX_LEVERAGE=3.0             # Hard cap
BASE_LEVERAGE=2.0            # Default before sentiment scaling
MAX_POSITION_SIZE_PCT=0.05   # 5% max per trade

# Trading
TRADING_PAIRS=BTC,ETH,SOL,XRP
TIMEFRAMES=4h,1h,15m

# Sentiment & On-Chain
CRYPTOCOMPARE_API_KEY=optional
GLASSNODE_API_KEY=optional
SANTIMENT_API_KEY=optional

# Mode & Logging
PAPER_TRADE=true             # Always start with this!
LOG_DB=trades.db             # SQLite database
LOG_CSV=trades.csv           # CSV export

# Advanced
EMERGENCY_IV_RANK_THRESHOLD=0.90  # Close all if IV > 90%
POSITION_TIMEOUT_MINUTES=30        # Force close after 30m
ENABLE_ON_CHAIN_SIGNALS=true
```

## Example Signal Generation

**Market State:**
- 4H: BTC above 20/50 EMA ✅ (uptrend)
- 1H: RSI = 55, MACD positive ✅ (momentum)
- 15M: Breakout above $65,500 ✅ (entry)
- News: "US institution buys $100M Bitcoin" → Sentiment +0.8 (very bullish)
- On-Chain: Top 100 wallets accumulating ✅ (whale confirmation)

**Signal Generated:**
```
Ticker: BTC
Direction: LONG
Entry: $65,550 (limit)
Stop Loss: $64,200
TP1: $66,750 (50% close @ 1:1 R:R)
TP2: $67,900 (25% close @ 1:2 R:R)
Trailing: 10% below TP2 (25% let run)

Leverage Calculation:
  Base: 2.0x
  Sentiment mult: 1.0 + (0.8 × 0.5) = 1.4
  Volatility factor: 1.1 (from ATR20/ATR50)
  Portfolio heat: 0.8 (discount)
  → 2.0 × 1.4 × 1.1 × 0.8 = 2.46x
  ✓ Capped at 3.0x → Final: 2.46x

Position Size:
  Max loss: $1000 × 0.02 = $20
  SL distance: $1,350
  Qty: $20 / $1,350 = 0.0148 BTC
  Leverage-adjusted: 0.006 BTC (~$393 notional)
  Risk: 2.0% of portfolio ✓
```

**Trade Progression:**
```
[00:15] Entry filled: 0.006 BTC @ $65,550 (unrealized P&L: +$0)
[00:45] Price: $66,100 (+0.8%) → Unrealized P&L: +$3.30
[01:30] TP1 hit @ $66,750 → Close 50% (0.003 BTC)
        Profit: $1.80 ✅
[03:00] Price: $68,000 (+3.7% from entry)
        Remaining 0.003 BTC: Unrealized P&L: +$13.50
[04:30] Trailing stop @ $67,500 → Close 0.003 BTC
        Profit: $5.85 ✅
        TOTAL: +$7.65 (+1.94% of position capital)
```

## Database Schema

### `trades` Table

```sql
trade_id, ticker, direction, entry_price, entry_time,
exit_price, exit_time, quantity, leverage, entry_leverage,
pnl_dollars, pnl_pct, sentiment_score, sentiment_label,
on_chain_signal, exit_reason, paper_trade
```

**Exit Reasons:** `tp1`, `tp2`, `sl` (stop loss), `timeout`, `emergency`

### `portfolio_snapshots` Table

```sql
snapshot_id, timestamp, total_balance, available_margin,
unrealized_pnl, portfolio_heat_pct, leverage_avg, iv_rank
```

## Testing

### Run All Tests

```bash
python -m pytest tests/ -v --cov=. --cov-report=html
```

### Individual Test Suites

```bash
# Leverage calculation (12 tests)
python -m pytest tests/test_leverage.py -v

# Sentiment analysis (18 tests)
python -m pytest tests/test_sentiment.py -v

# Risk management (20 tests)
python -m pytest tests/test_risk.py -v
```

### Test Coverage

```
leverage.py        ✓ 100% (leverage calculation logic)
sentiment.py       ✓ 100% (text scoring, ticker extraction)
risk.py            ✓ 100% (position sizing, emergency triggers)
signals.py         ✓ ~80% (technical indicators)
broker.py          ✓ ~60% (API mocked in tests)
orders.py          ✓ ~80% (position tracking logic)
main.py            ✓ ~40% (integration - requires live data)
```

## Deployment

### Local (Development)

```bash
# Terminal 1: Run bot
python main.py

# Terminal 2: Monitor logs
tail -f debug.log
```

### Docker (Optional)

```bash
docker build -t jarbis-crypto .
docker run --env-file .env jarbis-crypto
```

### Cloud (VPS)

1. SSH to VPS
2. Clone repo and setup (see Installation)
3. Run in background:
   ```bash
   nohup python main.py > bot.log 2>&1 &
   ```
4. Monitor:
   ```bash
   tail -f bot.log
   ```

## Safety Checklist

- [ ] Start with **PAPER MODE ONLY** (2+ weeks)
- [ ] Test all commands in paper mode
- [ ] Verify position sizing with small portfolio ($100-$1000)
- [ ] Check webhook alerts working
- [ ] Verify emergency close button works
- [ ] Monitor bot for 24 hours without interruption
- [ ] Only then consider LIVE mode
- [ ] If going live, start with 1% of capital
- [ ] Monitor 24/7 for first week
- [ ] Have fallback plan (manual close)
- [ ] Never use untested settings on live

## Risk Management Rules (Hard Limits)

1. **Max Loss Per Trade:** 2% of portfolio (non-negotiable)
2. **Max Leverage:** 3x (even if sentiment +1.0 and vol low)
3. **Max Position Size:** 5% of portfolio
4. **Force Close:** Position held > 30 min OR loss > 3%
5. **Emergency:** IV Rank > 90% → close all
6. **Stop Loss:** Hardcoded, no manual override
7. **Entry:** Limit orders only (zero slippage)
8. **Max Concurrent:** 4 open trades
9. **Paper First:** 2+ weeks before live
10. **Monitoring:** 24/7 for first week

## Troubleshooting

### Bot Won't Start

```bash
# Check Python version
python --version  # Must be 3.9+

# Check dependencies
pip install -r requirements.txt

# Check .env file
cat .env  # Verify all keys present
```

### No Price Updates

```bash
# Check API keys in .env
# Verify testnet setting matches your account
# Check firewall/proxy isn't blocking API

# Test API connection
curl https://api-testnet.bybit.com/v5/account/wallet-balance
```

### Signals Not Generating

```bash
# Need at least 200 candles per pair
# Takes ~5-10 minutes to fetch initial candles

# Check dashboard output
# Look for "No candles" warnings

# Verify trading pairs in .env
TRADING_PAIRS=BTC,ETH,SOL,XRP
```

### Tests Failing

```bash
# Run with verbose output
python -m pytest tests/ -v -s

# Check import paths
python -c "import leverage; print(leverage.__file__)"
```

## Project Structure

```
JARBIS_Crypto/
├── main.py                 # Entry point, event loop
├── config.py               # Configuration (Pydantic)
├── broker.py               # Bybit/Binance API clients
├── signals.py              # Multi-timeframe signal generation
├── on_chain.py             # Nansen/Glassnode/Santiment
├── leverage.py             # Dynamic leverage calculation
├── sentiment.py            # News sentiment scoring
├── risk.py                 # Position sizing, portfolio risk
├── orders.py               # Order execution, position lifecycle
├── dashboard.py            # Rich terminal UI
├── logger.py               # SQLite trade logging
├── webhooks.py             # Flask webhook server
├── utils.py                # Utilities (formatting, retry)
├── requirements.txt        # Dependencies
├── .env.example            # Configuration template
├── tests/
│   ├── test_leverage.py    # Leverage calculation tests
│   ├── test_sentiment.py   # Sentiment analysis tests
│   └── test_risk.py        # Risk management tests
└── README.md               # This file
```

## Performance Expectations

### Win Rate

Typical crypto trading with this setup:
- **Conservative (2x leverage):** 50-55% win rate
- **Aggressive (3x leverage):** 45-50% win rate

*Actual results depend on market conditions, pair selection, sentiment quality.*

### Sharpe Ratio

Target: > 1.0 (risk-adjusted returns)

*Sharpe = (avg_return - risk_free_rate) / volatility*

### Drawdown

Expected: -5% to -10% during downturns
Hard limit: -3% emergency close

## API Rate Limits

**Bybit:**
- Order: 10 req/sec (generous)
- Candles: 1 req/sec per symbol
- Account: 1 req/sec

**Binance:**
- Order: 5 req/sec
- Candles: 1200 req/min
- Account: 10 req/sec

*Bot respects these limits with built-in backoff.*

## Support & Issues

- 📝 Check logs: `tail -f debug.log`
- 🧪 Run tests: `pytest tests/ -v`
- 📖 Review .env configuration
- 💬 Check GitHub issues
- 🚨 For bugs: Create issue with logs + .env (redact keys!)

## Disclaimer

⚠️ **CRYPTO TRADING IS HIGH-RISK. LEVERAGE AMPLIFIES LOSSES.**

- Past performance does NOT guarantee future results
- Start with paper trading only
- Only risk capital you can afford to lose
- This is a research tool, not financial advice
- Liquidations happen fast (especially with leverage)
- Monitor the bot 24/7 for first week
- Have an emergency plan

**Use at your own risk.**

## License

Proprietary - Do not redistribute without permission.

---

**Happy trading! Remember: trade smart, manage risk first.** 🚀
