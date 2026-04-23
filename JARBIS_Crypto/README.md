# JARBIS Crypto — 24/7 Trading Bot

Production-grade automated trading bot for the **top-10 liquid perpetuals**
(BTC / ETH / BNB / SOL / XRP / ADA / DOGE / AVAX / LINK / MATIC) on a
**single venue: Hyperliquid** — a DEX on its own EVM L1, self-custodied
via **Metamask** signing. No KYC. Built on the Vilkov 0DTE framework with
**dynamic leverage scaling** (more leverage during high-confidence
signals), real-time news sentiment, and on-chain momentum confirmation.

Bybit and Binance stay in the codebase only as **read-only data fallbacks**
when Hyperliquid's `/info` endpoint hiccups — they never route orders.

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

- **Single-venue execution** — Hyperliquid perpetuals, Metamask self-custody.
- **Top-10 universe lock** — `config.ALLOWED_COINS` rejects any non-top-10
  ticker at startup; default `TRADING_PAIRS` is the full ten.
- **Multi-timeframe signals** — 4H EMA trend + 1H RSI/MACD momentum + 15m
  breakout with ATR-scaled stops and 1.5R / 3R take-profits.
- **Dynamic leverage** — base 2x × sentiment multiplier × ATR20/ATR50 ×
  portfolio-heat discount, hard-capped at 3x, floor-clamped at 1x (spot).
- **News sentiment** — CryptoCompare + NewsAPI crawl, keyword scoring in
  [-1, +1], time-decayed, with manual-injection overrides.
- **On-chain confirmation** — Santiment exchange-balance delta and
  Glassnode net-exchange flow. Optional; missing keys degrade gracefully.
- **Risk hard limits** — 2% max loss per trade, 5% max position, 4 concurrent
  trades, 30-minute timeout, 3% portfolio hard loss, emergency flatten.
- **Paper broker built-in** — realistic fills at limit price, SL/TP/TP2
  mark-to-market, SQLite + CSV audit trail.
- **Rich terminal dashboard** — live metrics, risk gauges, last 15 trades.
- **Live Artifact dashboard** — single-file React component
  (`artifacts/JarbisDashboard.jsx`) that pairs with the Flask server on
  your PC: bot on/off button, confidence gauge (red→yellow→green gradient),
  @DeItaone breaking-news feed, Hyperliquid top-10 table.
- **Webhooks** — `GET /state`, `POST /bot/start`, `POST /bot/stop`,
  `POST /news`, `POST /emergency` (CORS enabled for claude.ai).

---

## Architecture

```
main.py ─┬─ signal_loop   (poll prices, generate signals, execute, MTM)
         ├─ sentiment_loop (refresh news every 5min)
         └─ command_loop  (stdin CLI)
         + bot_active flag (stop/start from dashboard or !start/!stop)
         + state_snapshot() used by GET /state

broker.py   HyperliquidClient (primary) + Bybit/Binance data fallbacks
            + PaperBroker (simulated fills)
signals.py  EMA / RSI / MACD / ATR / support-resistance
sentiment.py News crawl + keyword scoring + ticker tagging
on_chain.py  Santiment / Glassnode bullish-signal check
leverage.py  Dynamic leverage formula
risk.py     Position sizing, heat, timeouts, hard-loss guard
orders.py   Glue: signal -> leverage -> sizing -> broker
logger.py   SQLite trades + portfolio snapshots + CSV mirror
dashboard.py Rich panels (metrics / risk / trades)
webhooks.py  Flask: /news /emergency /bot/start /bot/stop /state (+ CORS)

artifacts/
  JarbisDashboard.jsx  React Live Artifact (on/off button, confidence
                       gauge, @DeItaone feed, top-10 markets)
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
!start  |  !stop                   enable/disable new entries (same as dashboard toggle)
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

## Webhooks / API

```bash
# Bot on/off (dashboard toggle uses these)
curl -X POST http://127.0.0.1:5000/bot/start -H "X-JARBIS-Secret: $WEBHOOK_SECRET" -d '{}'
curl -X POST http://127.0.0.1:5000/bot/stop  -H "X-JARBIS-Secret: $WEBHOOK_SECRET" -d '{}'

# Manual news injection
curl -X POST http://127.0.0.1:5000/news \
  -H "X-JARBIS-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"BTC","headline":"ETF approval imminent","score":0.9}'

# Panic button
curl -X POST http://127.0.0.1:5000/emergency \
  -H "X-JARBIS-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"confirm":true}'

# Read-only snapshot (public; the Live Artifact polls this)
curl http://127.0.0.1:5000/state
```

---

## Configuration

See `.env.example` for all tunables. Minimal paper-mode config needs zero
keys — the bot uses Hyperliquid's public `/info` endpoint for data.

Key knobs:

| Env var | Default | Notes |
|---|---|---|
| `PRIMARY_BROKER` | hyperliquid | Single venue: `hyperliquid` (DEX, Metamask) |
| `HL_API_URL` | https://api.hyperliquid.xyz | Override for testnet/mainnet |
| `HL_WALLET_ADDRESS` | — | 0x… Metamask account used for signing |
| `HL_PRIVATE_KEY` | — | Only when `PAPER_TRADE=false` |
| `TRADING_PAIRS` | top-10 | Must be a subset of `ALLOWED_COINS` |
| `PORTFOLIO_SIZE_USD` | 1000 | Starting paper capital |
| `MAX_LOSS_PCT` | 0.02 | 2% per trade (risk-first sizing) |
| `MAX_LEVERAGE` | 3.0 | Hard cap on dynamic leverage |
| `BASE_LEVERAGE` | 2.0 | Anchor before sentiment/vol scaling |
| `MAX_POSITION_SIZE_PCT` | 0.05 | 5% of portfolio notional per trade |
| `MAX_CONCURRENT_TRADES` | 4 | Prevent over-exposure |
| `POSITION_TIMEOUT_MINUTES` | 30 | Force-close slow trades |
| `WEBHOOK_PORT` | 5000 | Flask + dashboard API + CORS |
| `WEBHOOK_SECRET` | change_me_please | Required for control endpoints |
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

Live order placement against Hyperliquid is intentionally stubbed
(`broker.place_limit_order` raises `NotImplementedError` when
`PAPER_TRADE=false`). To enable it:

1. Add an EVM signer. Hyperliquid orders are signed L1 actions; the
   `hyperliquid-python-sdk` package wraps this. Store the key in a local
   OS keystore, **not** `.env`.
2. Seed the wallet on Hyperliquid via the UI (Metamask deposit) before
   the bot tries to place orders.
3. Run paper trading for **≥ 2 weeks** to validate your config.
4. Enable live with **≤ 1% of intended capital** first.
5. Monitor 24/7 for the first week; use `!emergency` or the dashboard's
   ⛔ button liberally.

## Live Artifact dashboard

The Flask server already exposes `/state` + `/bot/start` + `/bot/stop`
with CORS `*`, so you can open the React artifact on claude.ai and point
its **Bot URL** field at `http://127.0.0.1:5000`. Prefs persist in
`window.storage`. Source: `artifacts/JarbisDashboard.jsx`.

---

## Warning

This is research tooling, not financial advice. Past performance does not
predict future results. Liquidations happen in seconds at 3x leverage on
volatile assets. **You are responsible for your own trades.**
