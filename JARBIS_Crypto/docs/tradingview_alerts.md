# TradingView → JARBIS alert wiring

Your TradingView Pine Script alerts (VuManChu Cipher B, MACD crosses,
custom strategies, etc.) can drive the bot directly. The Flask server
exposes `POST /tradingview`; the bot then runs the alert through the
same risk + leverage + bracketed-order machinery as internally
generated signals.

## 1. Expose the bot to the internet

TradingView's servers need to reach your PC. Pick one:

**ngrok** (free, fastest)
```bash
# install once: https://ngrok.com/download
ngrok http 5000
# copy the https URL it prints, e.g. https://abc123.ngrok-free.app
```

**Cloudflare Tunnel** (free, no rate limit)
```bash
cloudflared tunnel --url http://localhost:5000
```

The webhook URL you'll paste into TradingView is the public URL plus
`/tradingview`, e.g. `https://abc123.ngrok-free.app/tradingview`.

## 2. TradingView alert config

In TradingView → Alerts → Create Alert:

- **Condition**: pick your indicator (VuManChu Cipher B → e.g. *Buy Diamond* / *Sell Diamond*) and the asset.
- **Options**: ✅ Webhook URL
- **Webhook URL**: paste the ngrok / cloudflared URL from step 1.
- **Message**: paste this JSON, replacing `<your secret>` with the
  same string you set as `WEBHOOK_SECRET` in `.env`:

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

For a sell/short alert, change `"action": "sell"` and the `signal`
label. For exits, `"action": "close"`.

TradingView will substitute `{{ticker}}`, `{{close}}`, and
`{{interval}}` at firing time.

## 3. Accepted payload schema

| Field        | Required | Notes |
|--------------|----------|-------|
| `secret`     | yes      | Must match `WEBHOOK_SECRET` in `.env`. |
| `ticker`     | yes      | `BTC`, `BTCUSDT`, `BTCUSDT.P`, `BINANCE:BTCUSDT` — all normalize to `BTC`. Must be in the top-10 universe. |
| `action`     | yes      | `buy` / `long` / `sell` / `short` / `close` / `exit` / `flat`. |
| `price`      | no       | Informational; the bot uses live mark price for the entry. |
| `indicator`  | no       | Free text, logged with the trade (`vmc_cipher_b`, `macd_cross`, …). |
| `signal`     | no       | Free text (`buy_diamond`, `wave_crossover_up`, `red_diamond`, …). |
| `tf`         | no       | `15`, `60`, `240`, … TradingView interval. |

## 4. What the bot does on receipt

| Alert | Open position? | Bot behavior |
|-------|----------------|--------------|
| `buy` / `long` | none | Open a long bracket (entry + reduce-only SL/TP1/TP2). |
| `sell` / `short` | none | Open a short bracket. |
| `buy` while short | yes (short) | Close short, then open long. |
| `sell` while long | yes (long) | Close long, then open short. |
| Same direction as existing position | yes | Ignored (no doubling down). |
| `close` / `exit` | any | Flatten the position via market close. |
| any | `bot_active = false` | Entries skipped; closes still execute. |

Stop-loss + TP1 + TP2 prices are derived from the **current 15m ATR**;
position size is computed by `RiskManager` (still 2% max loss / 5%
notional / 4 concurrent / leverage cap). The TV alert can't bypass
any of those gates.

## 5. Smoke-test the wiring

With the bot running locally and ngrok up, fire a fake alert:

```bash
curl -X POST https://<your-public-url>/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "secret":"<your secret>",
    "ticker":"BTCUSDT",
    "action":"buy",
    "price":"65000",
    "indicator":"smoke_test",
    "signal":"manual"
  }'
```

The bot should log `[tv] BTC LONG smoke_test/manual @ 65000.0` and
attempt to open a long position (or report that it would, in paper
mode).

## 6. Pine Script v5 cheat-sheet for VuManChu Cipher B alerts

If you're using the open-source VuManChu Cipher B & Divergences
indicator, the built-in alert conditions you'll typically wire up are:

- *Buy Diamond* → `"action": "buy",  "signal": "buy_diamond"`
- *Sell Diamond* → `"action": "sell", "signal": "sell_diamond"`
- *Buy Circle* → `"action": "buy",  "signal": "buy_circle"`
- *Sell Circle* → `"action": "sell", "signal": "sell_circle"`
- *Bullish Divergence* (optional weight) → `"action": "buy", "signal": "bull_div"`
- *Bearish Divergence* → `"action": "sell", "signal": "bear_div"`

Use the highest-confidence variant (diamond / gold) as the entry
trigger; treat circles + divergences as confirming context.
