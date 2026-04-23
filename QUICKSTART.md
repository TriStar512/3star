# JARBIS Crypto - Quick Start Guide

Get trading in 5 minutes!

## Step 1: Install

```bash
# Clone and setup
git clone <repo>
cd 3star
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Step 2: Configure

```bash
# Copy template
cp .env.example .env

# Edit .env with your API keys
nano .env  # or open in your editor
```

**Minimum required:**
```env
BYBIT_API_KEY=your_key_here
BYBIT_API_SECRET=your_secret_here
BYBIT_TESTNET=true  # ALWAYS start with testnet!
```

## Step 3: Test

```bash
# Run tests to verify setup
python -m pytest tests/ -v

# Expected: 50+ tests pass ✅
```

## Step 4: Run (Paper Mode)

```bash
python main.py
```

You'll see:
```
╔═══════════════════════════════════════════════════════╗
║         🚀 JARBIS CRYPTO 24/7 TRADING BOT 🚀         ║
║                                                       ║
║   Dynamic Leverage • Smart Money Signals • News      ║
║         Sentiment • On-Chain Data • Risk First       ║
║                                                       ║
║                   PAPER MODE ENABLED                 ║
╚═══════════════════════════════════════════════════════╝
```

## Step 5: Test Commands

```
> !stats
ℹ️  Total Trades: 0, Win Rate: 0.00%, Total P&L: $0.00

> !sentiment
ℹ️  No sentiment data yet

> !positions
ℹ️  No open positions

> !help
[Command list...]
```

## Step 6: Monitor for 2+ Weeks

Keep the bot running in **PAPER MODE** and:

✅ Watch for signals being generated  
✅ Verify position sizing is reasonable  
✅ Check that take profits and stop losses work  
✅ Monitor stats and win rate  
✅ Test emergency close (!emergency)  

## Step 7: Go Live (Optional)

Only after 2+ weeks of successful paper trading:

```
> !live
⚠️  LIVE MODE - 3 confirmations required!
Type 'LIVE' to confirm (1/3): LIVE
Type 'LIVE' to confirm (2/3): LIVE
Type 'LIVE' to confirm (3/3): LIVE
✅ Switched to LIVE mode (⚠️)
```

Then change .env:
```env
BYBIT_TESTNET=false  # ⚠️ NOW TRADING REAL MONEY
```

## Key Commands

```
!paper              # Go back to paper (safe)
!help               # Show all commands
!close              # Close all positions
!emergency          # Close ALL (panic)
!stats              # Show performance
!positions          # List open trades
```

## Safety Reminders

1. **Always start with PAPER MODE** (2+ weeks)
2. **Always use TESTNET** until you're ready
3. **Test emergency close** (!emergency)
4. **Watch for 24 hours** without interruption
5. **Have a backup plan** (manual close)
6. **Never risk more than you can afford to lose**

## Troubleshooting

**Bot won't start?**
```bash
python --version  # Must be 3.9+
cat .env          # Check keys are present
```

**No signals?**
```bash
# Takes 5-10 min to fetch candles
# Check logs for "Updated prices"
```

**Tests failing?**
```bash
python -m pytest tests/ -v -s
```

## Next Steps

- Read [README.md](README.md) for full documentation
- Explore dashboard with `!stats` and `!positions`
- Try manual orders: `!buy BTC 50000`
- Inject news for sentiment testing: `!news BTC: bullish`
- Review trades with `!stats`

## FAQ

**Q: Can I use paper mode forever?**  
A: Yes! Paper mode never trades real money. Good for learning.

**Q: How do I change portfolio size?**  
Edit .env: `PORTFOLIO_SIZE_USD=5000`

**Q: What if I lose money?**  
You won't in paper mode. Emergency close limits losses to 3%.

**Q: Can I use this for other pairs?**  
Yes, edit .env: `TRADING_PAIRS=BTC,ETH,SOL,XRP,DOGE`

**Q: How often does it trade?**  
Depends on signals. Typically 2-5 trades per day.

**Q: Can I trade 24/7?**  
Yes! Crypto markets never close.

---

**You're all set! Good luck trading!** 🚀
