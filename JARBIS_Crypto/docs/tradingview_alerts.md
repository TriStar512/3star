# TradingView → JARBIS Alert Wiring

Your TradingView Pine Script alerts (VuManChu Cipher B, MACD crosses,
custom strategies, etc.) can drive the bot directly. The Flask server
exposes `POST /tradingview`; the bot then runs the alert through the
same risk + leverage + bracketed-order machinery as internally
generated signals.

---

## Quick Start (5 minutes)

**Checklist before you begin:**
- [ ] Bot is running in paper mode: `python -m JARBIS_Crypto.main --paper`
- [ ] You know your `.env` `WEBHOOK_SECRET` value (or it defaults to `change_me_please`)
- [ ] You have an indicator on a TradingView chart (e.g., VuManChu Cipher B, MACD, or a custom strategy)
- [ ] You have ngrok or Cloudflare Tunnel installed

---

## Step 1: Expose the Bot to the Internet (2 min)

TradingView's servers need to reach your PC at home. You'll use either ngrok (fastest,
simple) or Cloudflare Tunnel (no rate limits).

### Option A: ngrok (recommended for testing)

```bash
# Download once: https://ngrok.com/download
# Run it pointing at your bot
ngrok http 5000
```

You'll see output like:
```
Session Status                online
Version                       3.x.x
Region                        us (United States)
Latency                       14ms
Web Interface                 http://localhost:4040
Forwarding                    https://abc123.ngrok-free.app -> http://localhost:5000
```

**Copy the `https://abc123.ngrok-free.app` URL** — you'll need it in a few steps.

### Option B: Cloudflare Tunnel (production, unlimited)

```bash
cloudflared tunnel --url http://localhost:5000
```

Similar output; copy the HTTPS URL it prints.

**Your webhook URL is:** `https://<your-url>/tradingview` 
(e.g., `https://abc123.ngrok-free.app/tradingview`)

---

## Step 2: Set Up a TradingView Alert (3 min)

Go to **TradingView.com** and open a chart for one of the top-10 coins:
BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, LINK, or MATIC.

### On your chart:

1. **Open the Alerts panel** — look for the 🔔 (bell) icon in the toolbar, or use the menu.
2. **Click "Create Alert"** (or "+", depending on your UI version).
3. You'll see a form with **Condition** at the top.

### Fill in the Condition:

- **Condition Type:** Select your indicator (e.g., VuManChu Cipher B).
- **Signal:** Pick the buy/sell condition (e.g., "Buy Diamond" or "Sell Diamond").
- **Asset:** Make sure it's set to the coin you want (e.g., `BTC`, `BTCUSDT`, or `BTCUSD` — any format works).
- **Timeframe:** Pick the chart timeframe (e.g., 4h, 1h, 15m). The bot will use the live 15m ATR for stop-loss sizing, so be specific about your strategy's timeframe.

### Enable Webhook:

- Scroll down in the alert form.
- Find the **"Webhook URL"** option and **check the checkbox** to enable it.
- **Paste your URL:** `https://<your-ngrok-url>/tradingview`

### Add the Message:

TradingView can't send custom headers (that's why we embed the secret in the JSON body).
Paste this into the **Message** field, replacing `<your secret>` with your actual `WEBHOOK_SECRET`:

```json
{
  "secret":    "<your secret>",
  "ticker":    "{{ticker}}",
  "action":    "buy",
  "price":     "{{close}}",
  "indicator": "vmc_cipher_b",
  "signal":    "buy_diamond",
  "tf":        "{{interval}}"
}
```

**What these fields do:**
- `secret` — Must match your `.env` `WEBHOOK_SECRET` (bot rejects on mismatch).
- `ticker` — TradingView substitutes `{{ticker}}` with the actual symbol (e.g., `BTCUSDT`). The bot normalizes it to `BTC`.
- `action` — `"buy"` opens a long, `"sell"` opens a short, `"close"` flattens the position.
- `price` — TradingView substitutes `{{close}}` with the current close price (informational; bot uses live mark price).
- `indicator` — Free text; logged with the trade for auditing (e.g., `vmc_cipher_b`, `macd_cross`).
- `signal` — Free text; logged with the trade (e.g., `buy_diamond`, `wave_cross_up`).
- `tf` — TradingView substitutes `{{interval}}`; helps you track which timeframe triggered the alert.

### Save the Alert

Click **Create** or **Save**. You're done setting up TradingView.

---

## Step 3: Test It (2 min)

### Option A: Fire the actual TradingView alert (if condition is met)

If your indicator's condition is already true (e.g., buy diamond just printed), the alert will fire automatically.
Check the **bot's terminal** for a log line like:
```
[tv] BTC LONG vmc_cipher_b/buy_diamond @ 67500.0
```

If you see that, the webhook worked! Check the **positions table** — a new BTC position should appear (in paper mode).

### Option B: Smoke-test with curl (fastest)

Open **Git Bash** (or any terminal) and run:

```bash
curl -X POST https://<your-public-url>/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "secret":"<your secret>",
    "ticker":"BTCUSDT",
    "action":"buy",
    "price":"67500",
    "indicator":"smoke_test",
    "signal":"manual"
  }'
```

Replace:
- `https://<your-public-url>/tradingview` with your ngrok or Cloudflare URL
- `<your secret>` with your actual `WEBHOOK_SECRET`

You should see:
- **HTTP 200** response with `{"ok": true, "ticker": "BTC", "direction": "long"}`
- **Bot logs:** `[tv] BTC LONG smoke_test/manual @ 67500.0`
- **Positions table:** A new BTC LONG position (paper mode) or queued entry (live mode)

---

## Step 4: Customize for Your Strategies (ongoing)

For each new strategy or coin pair, create a new alert with the same pattern:
- Change `"action"` to `"buy"`, `"sell"`, or `"close"`
- Update `"indicator"` and `"signal"` to match your indicator name
- Adjust `"tf"` if you're using a different timeframe

---

## Reference: Accepted Actions & Payload

| Action | Bot Behavior |
|---|---|
| `buy` / `long` | Open a long position (entry limit + SL + TP1 + TP2) |
| `sell` / `short` | Open a short position (same bracket) |
| `close` / `exit` / `flat` | Flatten any open position on that ticker (market close) |

### Full Payload Schema

| Field | Required | Notes |
|---|---|---|
| `secret` | yes | Must match `WEBHOOK_SECRET` in `.env` |
| `ticker` | yes | Any form (BTC, BTCUSDT, BINANCE:BTCUSDT.P, etc.); bot normalizes to top-10 coin code. Must be in top-10. |
| `action` | yes | `buy` / `long` / `sell` / `short` / `close` / `exit` / `flat` |
| `price` | no | Informational; bot uses live mark price for entry |
| `indicator` | no | Free text, logged with trade |
| `signal` | no | Free text, logged with trade |
| `tf` | no | Timeframe; bot logs but doesn't enforce |

---

## Reference: What the Bot Does on Receipt

When your alert fires and the bot receives it:

| Alert | Current Position? | Bot Behavior |
|---|---|---|
| `buy` / `long` | None | Opens a long bracket: limit GTC entry + reduce-only SL (market) + reduce-only TP1 (50% qty) + reduce-only TP2 (50%) |
| `sell` / `short` | None | Opens a short bracket (same structure) |
| `buy` while short | Yes (short) | Closes the short, then opens long |
| `sell` while long | Yes (long) | Closes the long, then opens short |
| Same direction as existing | Yes | **Ignored** — no doubling down |
| `close` / `exit` / `flat` | Any | Market-closes the entire position immediately |
| Any action | `bot_active=false` | Entry actions **skipped**; close actions still **execute** |

**Important:** Stop-loss + TP1 + TP2 prices are derived from the **current 15-minute ATR**;
position size is computed by `RiskManager` using the standard gates (2% max loss, 5%
notional, 4 concurrent, leverage cap). **The webhook can't bypass any of these safety limits** — every alert flows through the same risk machinery as internal signals.

---

## Reference: VuManChu Cipher B Indicator (Pine Script v5)

If you're using the open-source **VuManChu Cipher B & Divergences** indicator, here are
the standard alert conditions and how to wire them:

### Buy/Sell Diamonds (Primary signals — highest confidence)

```json
{
  "secret":    "<your secret>",
  "ticker":    "{{ticker}}",
  "action":    "buy",
  "indicator": "vmc_cipher_b",
  "signal":    "buy_diamond",
  "tf":        "{{interval}}"
}
```

- **Buy Diamond** → use `"action": "buy", "signal": "buy_diamond"`
- **Sell Diamond** → use `"action": "sell", "signal": "sell_diamond"`

### Buy/Sell Circles (Secondary signals — medium confidence)

- **Buy Circle** → use `"action": "buy", "signal": "buy_circle"`
- **Sell Circle** → use `"action": "sell", "signal": "sell_circle"`

### Divergences (Optional weight — lower confidence)

- **Bullish Divergence** → use `"action": "buy", "signal": "bull_div"`
- **Bearish Divergence** → use `"action": "sell", "signal": "bear_div"`

**Strategy:** Use diamonds as your primary entry trigger. Treat circles and divergences as confirming context or separate alerts.

---

## Reference: Ticker Normalization

The bot recognizes these ticker formats and normalizes them all to the bare coin code:

| Input | Normalized |
|---|---|
| `BTC` | BTC |
| `BTCUSDT` | BTC |
| `BTCUSDT.P` | BTC |
| `BTCUSD` | BTC |
| `BTCPERP` | BTC |
| `BINANCE:BTCUSDT` | BTC |
| `BYBIT:BTCUSDT.P` | BTC |
| `HYPERLIQUID:BTC` | BTC |
| `ETH`, `ETHUSDT`, etc. | ETH |

**Note:** The bot enforces the top-10 universe. If you send a ticker not in
`[BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, LINK, MATIC]`, the alert is rejected.
