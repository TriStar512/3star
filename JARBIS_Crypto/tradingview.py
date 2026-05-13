"""TradingView webhook integration.

Pine Script alerts (VuManChu Cipher B, MACD crosses, RSI divergences,
etc.) POST a JSON body to ``/tradingview`` on the bot's Flask server.
The payload is validated against the shared secret, normalized into
a ``TradingViewEvent``, and queued for the asyncio signal loop to
execute as an entry / exit instruction.

Configure your TradingView alert **message body** as JSON, e.g.:

    {
      "secret":    "<your WEBHOOK_SECRET>",
      "ticker":    "{{ticker}}",
      "action":    "buy",
      "price":     "{{close}}",
      "indicator": "vmc_cipher_b",
      "signal":    "buy_diamond",
      "tf":        "{{interval}}"
    }

The ``action`` field is required; everything else is optional metadata.

Accepted ``action`` values
    buy / long    -> open long
    sell / short  -> open short
    close / exit  -> flatten any position on this ticker

Accepted ``ticker`` forms (all normalize to bare coin code)
    BTC · BTCUSDT · BTCUSDT.P · BTCUSD · BTCPERP
    BINANCE:BTCUSDT · BYBIT:BTCUSDT.P · HYPERLIQUID:BTC etc.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

log = logging.getLogger(__name__)


_TICKER_RE = re.compile(
    r"""^
        (?:[A-Z0-9]+:)?           # optional exchange prefix, e.g. BINANCE:
        ([A-Z][A-Z0-9]{1,9}?)     # captured coin code (lazy so suffix matches)
        (?:USDT|USDC|USD|PERP)?   # common quote / suffix
        (?:\.P|PERP|-PERP)?       # perp markers
        $""",
    re.VERBOSE,
)

VALID_ACTIONS = {"buy", "long", "sell", "short", "close", "exit", "flat"}
ACTION_TO_DIRECTION = {
    "buy":   "long",
    "long":  "long",
    "sell":  "short",
    "short": "short",
    "close": "close",
    "exit":  "close",
    "flat":  "close",
}


@dataclass
class TradingViewEvent:
    ticker: str           # normalized: BTC, ETH, SOL, ...
    direction: str        # "long" | "short" | "close"
    price: Optional[float] = None
    indicator: str = ""
    signal: str = ""
    timeframe: str = ""
    raw: dict = field(default_factory=dict)
    received_at: float = field(default_factory=time.time)


def normalize_ticker(s: object) -> Optional[str]:
    """Map any TradingView ticker form to a bare coin code (BTC, ETH, …)."""
    if not isinstance(s, str):
        return None
    s = s.strip().upper().replace(" ", "")
    if not s:
        return None
    m = _TICKER_RE.match(s)
    if m:
        return m.group(1)
    return None


def parse_alert(payload: dict, allowed_tickers: Iterable[str]) -> TradingViewEvent:
    """Validate + normalize a TradingView JSON alert. Raises on bad input."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    raw_ticker = payload.get("ticker") or payload.get("symbol")
    ticker = normalize_ticker(raw_ticker)
    if not ticker:
        raise ValueError(f"unrecognized ticker: {raw_ticker!r}")

    allowed = {t.upper() for t in allowed_tickers}
    if ticker not in allowed:
        raise ValueError(
            f"{ticker} is not in the trading universe {sorted(allowed)}"
        )

    action_raw = payload.get("action") or payload.get("side") or ""
    action = str(action_raw).strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"unsupported action {action!r}; expected one of {sorted(VALID_ACTIONS)}"
        )
    direction = ACTION_TO_DIRECTION[action]

    price_raw = payload.get("price")
    try:
        price = float(price_raw) if price_raw not in (None, "", "NaN") else None
    except (TypeError, ValueError):
        price = None

    return TradingViewEvent(
        ticker=ticker,
        direction=direction,
        price=price,
        indicator=str(payload.get("indicator") or payload.get("strategy") or ""),
        signal=str(payload.get("signal") or ""),
        timeframe=str(payload.get("tf") or payload.get("timeframe") or ""),
        raw=payload,
    )


def is_stale(ev: TradingViewEvent, max_age_seconds: float = 120.0) -> bool:
    return (time.time() - ev.received_at) > max_age_seconds
