# JARBIS Crypto — Project Memory

24/7 automated crypto trading bot running on PC, **single-venue execution
on Hyperliquid** (DEX perps, Metamask self-custody, no KYC). Vilkov 0DTE
framework adapted to crypto with dynamic leverage, news sentiment, and
on-chain confirmation.

## Repo

- Remote: `tristar512/3star`
- Primary dev branch: `claude/jarbis-crypto-bot-H4yXe`
- Open PR: #1 (base `main`)
- All bot code lives in `JARBIS_Crypto/` package
- Subscribed to PR #1 activity

## Hard rules (enforced in code, not suggestions)

1. **One venue only: Hyperliquid.** `PRIMARY_BROKER=hyperliquid`. Bybit
   and Binance clients are retained *only* as read-only data fallbacks
   for the candle / ticker chain. They never route orders.
2. **Top-10 coin universe.** `config.ALLOWED_COINS = [BTC, ETH, BNB, SOL,
   XRP, ADA, DOGE, AVAX, LINK, MATIC]`. A pydantic validator rejects
   any `TRADING_PAIRS` value outside this list at startup.
3. **Dynamic leverage scales with confidence** — the existing formula:
   ```
   leverage = clamp(
       base_leverage
       * (1 + sentiment_score * 0.5)    # [0.5, 1.5]
       * min(ATR20 / ATR50, 1.5)        # volatility factor
       * max(0.5, 1 - portfolio_heat),  # heat discount
       lo=1.0, hi=max_leverage          # 1x floor, 3x cap
   )
   ```
   Higher sentiment + lower vol + lower heat ⇒ more leverage, capped.
4. **Metamask self-custody for live mode.** `HL_WALLET_ADDRESS` +
   `HL_PRIVATE_KEY` (off-disk in production). Live order placement is
   stubbed with `NotImplementedError` until the signer is wired.
5. **Risk hard limits (unchanged):** 2% max loss / trade, 5% max notional,
   4 concurrent, 30-min timeout, 3% portfolio hard loss, emergency flatten.

## Run (PC, paper mode)

```bash
pip install -r JARBIS_Crypto/requirements.txt
cp JARBIS_Crypto/.env.example JARBIS_Crypto/.env   # optional keys
python -m JARBIS_Crypto.main --paper
```

Tests: `pytest JARBIS_Crypto/tests` — 38 tests, all passing.

## Architecture (file map)

| File | Purpose |
|---|---|
| `main.py` | Async event loop: `signal_loop`, `sentiment_loop`, `command_loop` + Rich Live dashboard. Has `bot_active` flag + `state_snapshot()` for the dashboard. `!start` / `!stop` CLI commands gate new entries without killing the process. |
| `config.py` | `pydantic-settings` typed config. Exports `ALLOWED_COINS` constant + validator that rejects non-top-10 tickers. `primary_broker` defaults to `"hyperliquid"`. |
| `broker.py` | `HyperliquidClient` (primary) + `BybitClient` + `BinanceClient` (data fallbacks only) + `PaperBroker`. `Broker._try_chain(...)` walks the fallback list for every data call. |
| `signals.py` | EMA / RSI / MACD / ATR / support-resistance + `SignalEngine` (4H trend, 1H momentum, 15m breakout). |
| `sentiment.py` | CryptoCompare + NewsAPI crawl, keyword scoring, per-ticker time-decayed score, manual injection. |
| `on_chain.py` | Santiment exchange-balance + Glassnode netflow bullish-signal check. |
| `leverage.py` | `calculate_leverage(LeverageInputs, …)` — formula above. |
| `risk.py` | `RiskManager` — sizing, heat, timeout/hard-loss gates, concurrency cap. |
| `orders.py` | `OrderRouter.execute(signal, atr_ratio)` — glue: leverage → sizing → broker. |
| `logger.py` | `TradeLogger` — SQLite (`trades`, `portfolio_snapshots`) + CSV mirror, stats. |
| `dashboard.py` | Rich terminal panels: metrics / risk / recent trades. |
| `webhooks.py` | Flask app (runs in thread) serving `/state` (public, CORS `*`), `/bot/start`, `/bot/stop`, `/news`, `/emergency`, `/healthz`. |
| `utils.py` | Formatters, `async_retry`, sentiment classifier. |
| `tests/` | `test_leverage.py`, `test_sentiment.py`, `test_risk.py`, `test_signals.py`, `test_config.py` — 38 tests, all passing. |
| `artifacts/JarbisDashboard.jsx` | **Live Artifact** — React dashboard. On/off bot button, confidence gauge (red→yellow→green gradient), @DeItaone X-timeline embed, Hyperliquid top-10 table, positions table, recent trades, stats. Sized for half-screen 1280×1440. Polls `/state` and issues `/bot/*` control calls. |
| `artifacts/README.md` | Live Artifacts index + usage notes. |

## Live Artifact dashboard (JarbisDashboard.jsx)

Single-file React component. Runs as a Claude Live Artifact on
claude.ai or in any React app. Points at the local bot via URL field
(default `http://127.0.0.1:5000`) + the webhook secret. CORS on the
Flask server permits loopback from https://claude.ai.

**Features**
- START BOT / STOP BOT toggle (POSTs `/bot/start` or `/bot/stop`)
- ⛔ Emergency flatten (POSTs `/emergency`)
- Stat tiles: balance, unrealized P&L, heat, available margin
- Open-positions table (click to focus the gauge)
- **Confidence gauge** — SVG semicircle with red→yellow→green gradient,
  auto-derived from sentiment + leverage headroom, manual slider override
- Top-10 Hyperliquid market table (price, 24h %, max lev, funding, dyn
  lev, sentiment, day vol)
- **@DeItaone** breaking-news embed via `platform.twitter.com/widgets.js`,
  with graceful fallback message + "open in X" link
- Recent trades table + stats panel

**Persistence** (`window.storage` → `localStorage` → memory):
`jarbis.botUrl`, `jarbis.secret`, `jarbis.refresh`,
`jarbis.selectedCoin`, `jarbis.manualConfidence`

## Flask API (for dashboard)

| Route | Auth | Purpose |
|---|---|---|
| `GET  /state` | public | Full bot snapshot (positions, prices, sentiment, confidence, stats) |
| `POST /bot/start` | `X-JARBIS-Secret` | Resume new entries |
| `POST /bot/stop` | `X-JARBIS-Secret` | Pause new entries (open positions still managed) |
| `POST /news` | `X-JARBIS-Secret` | Inject manual headline |
| `POST /emergency` | `X-JARBIS-Secret` | Flatten every open position |
| `GET  /healthz` | public | Liveness |

CORS enabled (`*`) so the Live Artifact on claude.ai can poll localhost.

## CLI commands

```
!start                 !stop                  !close [TICKER]
!emergency             !risk set 0.015        !leverage set 2.5
!leverage auto         !news TICKER: text     !paper
!live confirm (x3)     !stats | !heat         !sentiment | !positions
!on-chain TICKER       !quit | !help
```

## Conventions / gotchas

- No ta-lib; pandas-only indicators (keeps deps minimal)
- All market-data endpoints on Hyperliquid are public (no signing)
- `Broker` is async context manager — always used via `async with`
- RSI saturates to 100 when `avg_loss==0`; 50 when both gain/loss zero
- Paper sizing test uses `distance=50` to avoid the notional cap
- `state_snapshot()` runs on the Flask thread; reads are best-effort,
  no asyncio locks (all touched fields are plain dicts / numbers)
- `bot_active=False` leaves price-polling + mark-to-market running;
  only new entries are suppressed
- `.gitignore` excludes `__pycache__`, `.env`, `*.db`, `*.csv`

## PR status (as of last check)

- PR #1 open against `main`
- No check runs configured on the repo (no CI workflow yet)
- No review comments, no reviews, no issue comments
- Session subscribed to PR activity

## Next steps (not started)

- [ ] Wire Hyperliquid signed actions for live mode (`hyperliquid-python-sdk`)
- [ ] Hyperliquid testnet smoke run with a Metamask burner wallet
- [ ] Add a GitHub Actions CI workflow (pytest on push)
- [ ] Backtest engine over historical 15m/1h candles
- [ ] ≥ 2 weeks paper-mode validation before any live switch
