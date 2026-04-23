# JARBIS Crypto — Project Memory

24/7 automated crypto trading bot for BTC/ETH/SOL/XRP on spot + perpetual
futures. Adapts the Vilkov 0DTE framework to crypto with dynamic leverage,
news sentiment, and on-chain confirmation.

## Repo

- Remote: `tristar512/3star`
- Primary dev branch: `claude/jarbis-crypto-bot-H4yXe`
- Open PR: #1 (base `main`)
- All bot code lives in `JARBIS_Crypto/` package

## Run

```bash
pip install -r JARBIS_Crypto/requirements.txt
cp JARBIS_Crypto/.env.example JARBIS_Crypto/.env   # fill keys (optional for paper)
python -m JARBIS_Crypto.main --paper
```

Tests: `pytest JARBIS_Crypto/tests` (32 tests, all passing).

## Architecture (file map)

| File | Purpose |
|---|---|
| `main.py` | Async event loop: `signal_loop`, `sentiment_loop`, `command_loop` + Rich Live dashboard |
| `config.py` | `pydantic-settings` typed config from `.env`; `get_settings()` memoized |
| `broker.py` | `BybitClient` (primary), `BinanceClient` (fallback), `PaperBroker`, `Broker` facade |
| `signals.py` | EMA / RSI / MACD / ATR / support-resistance + `SignalEngine` (4H trend, 1H momentum, 15m breakout) |
| `sentiment.py` | CryptoCompare + NewsAPI crawl, keyword scoring, per-ticker time-decayed score, manual injection |
| `on_chain.py` | Santiment exchange-balance + Glassnode netflow bullish-signal check |
| `leverage.py` | `calculate_leverage(LeverageInputs, …)` — formula below |
| `risk.py` | `RiskManager` — sizing, heat, timeout/hard-loss gates, concurrency cap |
| `orders.py` | `OrderRouter.execute(signal, atr_ratio)` — glue: leverage → sizing → broker |
| `logger.py` | `TradeLogger` — SQLite (`trades`, `portfolio_snapshots`) + CSV mirror, stats |
| `dashboard.py` | Rich panels: metrics / risk / recent trades |
| `webhooks.py` | Flask `POST /news`, `POST /emergency` (auth `X-JARBIS-Secret`) + Slack notify |
| `utils.py` | Formatters, `async_retry`, sentiment classifier |
| `tests/` | `test_leverage.py`, `test_sentiment.py`, `test_risk.py`, `test_signals.py` |

## Leverage formula (core invariant)

```
leverage = clamp(
    base_leverage
    * (1 + sentiment_score * 0.5)    # [0.5, 1.5] from score ∈ [-1, +1]
    * min(ATR20 / ATR50, 1.5)        # volatility dampener
    * max(0.5, 1 - portfolio_heat),  # heat discount
    lo=1.0, hi=max_leverage          # defaults: 1x floor, 3x cap
)
```

Worked example from spec: `base=2, sent=+0.8, ATR=1.1, heat=0.2` → **2.46x**.

## Risk hard limits (enforced in `risk.py`)

- 2% max loss per trade (risk-first sizing)
- 5% max notional per position
- 4 concurrent trades max
- 30-minute position timeout
- 3% portfolio hard-loss → auto-close
- Emergency flatten on CLI `!emergency` or `POST /emergency`

## Live-mode safety

- `PAPER_TRADE=true` is the default
- `Broker.place_limit_order` raises `NotImplementedError` when `paper_trade=False`
  — signed REST endpoints must be wired before live
- `!live` CLI requires 3 explicit confirmations

## CLI commands

```
!close [TICKER]        !emergency           !risk set 0.015
!leverage set 2.5      !leverage auto       !news TICKER: text
!paper                 !live confirm (x3)   !stats | !heat | !sentiment
!positions             !on-chain TICKER     !quit | !help
```

## Conventions / gotchas

- No ta-lib; pandas-only indicators (keeps deps minimal)
- Market data endpoints are public (no signing for candles/price/funding)
- `Broker` is async context manager — always used via `async with`
- RSI saturates to 100 when `avg_loss==0` (fixed in `signals.py`); default is 50 when both gain/loss zero
- Paper sizing test uses `distance=50` to avoid the notional cap — tight stops always cap at `portfolio × max_position_pct × leverage`
- `.gitignore` excludes `__pycache__`, `.env`, `*.db`, `*.csv`

## PR status (as of last check)

- PR #1 open against `main`
- No check runs configured on the repo yet (no CI workflow)
- No review comments, no reviews, no issue comments
- Session is subscribed to PR activity

## Next steps (not started)

- [ ] Wire signed Bybit REST endpoints for live order placement (HMAC, leverage + margin-mode setup, attached SL/TP)
- [ ] Bybit testnet smoke run with real keys
- [ ] Add a GitHub Actions CI workflow (pytest on push)
- [ ] Backtest engine over historical 15m/1h candles
- [ ] ≥ 2 weeks paper-mode validation before any live switch
