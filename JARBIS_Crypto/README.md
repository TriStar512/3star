# JARBIS Crypto — 24/7 Trading Bot

Production-grade automated trading bot for BTC / ETH / SOL / XRP on spot and
perpetual futures, built on the Vilkov 0DTE framework and adapted for crypto
with **dynamic leverage scaling**, real-time news sentiment, and on-chain
momentum confirmation.

> ⚠️ **Crypto trading is high-risk. Leverage amplifies losses.** Start in paper
> mode. Never deploy capital you cannot afford to lose.

---

## Quickstart

```bash
git clone <this repo>
cd JARBIS_Crypto
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # fill in API keys (all optional for paper mode)
python -m JARBIS_Crypto.main --paper
```

The bot will connect to Bybit (falling back to Binance), pull 4h / 1h / 15m
candles, score news sentiment, and wait for a signal on BTC / ETH / SOL / XRP.

---

## What it does

- **Multi-timeframe signals** — 4H EMA trend + 1H RSI/MACD momentum + 15m
  breakout with ATR-scaled stops and 1.5R / 3R take-profits.
- **Dynamic leverage** — base 2x × sentiment multiplier × ATR20/ATR50 ×
  portfolio-heat discount, hard-capped at 3x and floor-clamped at 1x (spot).
- **News sentiment** — CryptoCompare + NewsAPI crawl, keyword scoring in
  [-1, +1], time-decayed, with manual-injection overrides.
- **On-chain confirmation** — Santiment exchange-balance delta and Glassnode
  net-exchange flow. Optional; missing keys degrade gracefully.
- **Risk hard limits** — 2% max loss per trade, 5% max position, 4 concurrent
  trades, 30-minute timeout, 3% portfolio hard loss, emergency flatten.
- **Paper broker built-in** — realistic fills at limit price, SL/TP/TP2
  mark-to-market, SQLite + CSV audit trail.
- **Rich dashboard** — live metrics, risk gauges, and the last 15 trades.
- **Webhooks** — POST `/news` (manual headline injection) and `/emergency`
  (panic flatten), plus optional Slack outbound notifications.

---

## Architecture

```
main.py ─┬─ signal_loop   (poll prices, generate signals, execute, MTM)
         ├─ sentiment_loop (refresh news every 5min)
         └─ command_loop  (stdin CLI)

broker.py   Bybit primary + Binance fallback + PaperBroker
signals.py  EMA / RSI / MACD / ATR / support-resistance
sentiment.py News crawl + keyword scoring + ticker tagging
on_chain.py  Santiment / Glassnode bullish-signal check
leverage.py  Dynamic leverage formula
risk.py     Position sizing, heat, timeouts, hard-loss guard
orders.py   Glue: signal -> leverage -> sizing -> broker
logger.py   SQLite trades + portfolio snapshots + CSV mirror
dashboard.py Rich panels (metrics / risk / trades)
webhooks.py  Flask /news + /emergency + Slack notify
```

---

## Leverage formula

```
leverage = clamp(
    base_leverage
    * (1 + sentiment_score * 0.5)    # [0.5, 1.5]
    * min(ATR20 / ATR50, 1.5)        # vol dampener
    * max(0.5, 1 - portfolio_heat),  # heat discount
    lo=1.0, hi=max_leverage
)
```

Example: `base=2`, `sentiment=+0.8`, `ATR ratio=1.1`, `heat=0.2` →
`2 × 1.4 × 1.1 × 0.8 = 2.46x`.

---

## Commands (type into the running bot)

```
!help                              show all commands
!close [TICKER]                    close all or one
!emergency                         panic close everything
!risk set 0.015                    adjust max loss per trade
!leverage set 2.5  |  !leverage auto
!paper  |  !live confirm (x3)      toggle modes
!news BTC: SEC approval imminent   inject manual news
!stats | !heat | !sentiment | !positions
!on-chain BTC                      show latest on-chain signal
!quit
```

---

## Webhooks

```bash
# Manual news injection
curl -X POST http://localhost:5000/news \
  -H "X-JARBIS-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"BTC","headline":"ETF approval imminent","score":0.9}'

# Panic button
curl -X POST http://localhost:5000/emergency \
  -H "X-JARBIS-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"confirm":true}'
```

---

## Configuration

See `.env.example` for all tunables. Minimal paper-mode config needs zero
keys — the bot will use Bybit's public market-data endpoints.

Key knobs:

| Env var | Default | Notes |
|---|---|---|
| `PORTFOLIO_SIZE_USD` | 1000 | Starting paper capital |
| `MAX_LOSS_PCT` | 0.02 | 2% per trade (risk-first sizing) |
| `MAX_LEVERAGE` | 3.0 | Hard cap on dynamic leverage |
| `BASE_LEVERAGE` | 2.0 | Anchor before sentiment/vol scaling |
| `MAX_POSITION_SIZE_PCT` | 0.05 | 5% of portfolio notional per trade |
| `MAX_CONCURRENT_TRADES` | 4 | Prevent over-exposure |
| `POSITION_TIMEOUT_MINUTES` | 30 | Force-close slow trades |
| `PRIMARY_BROKER` | bybit | `bybit` or `binance` |
| `PAPER_TRADE` | true | Always default true |

---

## Testing

```bash
pytest JARBIS_Crypto/tests
```

The suite covers:
- Leverage formula edge cases (caps, floors, heat discount)
- Sentiment scoring + ticker tagging
- Position sizing (risk-first + notional cap)
- Indicators (EMA, RSI, MACD, ATR, support/resistance)

---

## Database schema

SQLite (`trades.db`) with two tables — `trades` (one row per trade) and
`portfolio_snapshots` (periodic balance + heat + leverage). Every trade
records: entry/exit price, leverage, sentiment score + label, on-chain
signal label, exit reason (`tp1`, `tp2`, `sl`, `timeout`, `emergency`,
`manual`), and paper/live flag.

---

## Going live

Live order placement against Bybit / Binance is intentionally stubbed
(`broker.place_limit_order` raises `NotImplementedError` when
`PAPER_TRADE=false`). To enable it:

1. Wire signed REST endpoints into `BybitClient` / `BinanceClient` (HMAC
   signing, leverage + margin-mode setup, SL/TP attached to the entry).
2. Run paper trading for **≥ 2 weeks** to validate your config.
3. Enable live with **≤ 1% of intended capital** first.
4. Monitor 24/7 for the first week; use `!emergency` liberally.

---

## Warning

This is research tooling, not financial advice. Past performance does not
predict future results. Liquidations happen in seconds at 3x leverage on
volatile assets. **You are responsible for your own trades.**
