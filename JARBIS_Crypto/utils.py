"""Shared utilities: formatters, retry logic, time helpers."""
from __future__ import annotations

import asyncio
import functools
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fmt_price(value: float, decimals: int = 2) -> str:
    if value >= 1000:
        return f"${value:,.{decimals}f}"
    if value >= 1:
        return f"${value:,.4f}"
    return f"${value:,.6f}"


def fmt_pct(value: float, decimals: int = 2) -> str:
    return f"{value * 100:+.{decimals}f}%"


def fmt_qty(value: float) -> str:
    if abs(value) >= 1:
        return f"{value:,.4f}"
    return f"{value:,.6f}"


def symbol_to_pair(symbol: str, quote: str = "USDT") -> str:
    symbol = symbol.upper()
    if symbol.endswith(quote):
        return symbol
    return f"{symbol}{quote}"


async def async_retry(
    fn: Callable[..., Awaitable[T]],
    *args,
    attempts: int = 4,
    base_delay: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """Exponential backoff retry for async calls (2s, 4s, 8s, 16s)."""
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return await fn(*args, **kwargs)
        except exceptions as exc:  # noqa: BLE001
            last_exc = exc
            if i == attempts - 1:
                break
            delay = base_delay * (2 ** i)
            log.warning("retry %s/%s for %s in %.1fs: %s", i + 1, attempts, fn.__name__, delay, exc)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def classify_sentiment(score: float) -> str:
    if score >= 0.5:
        return "very_bullish"
    if score >= 0.15:
        return "bullish"
    if score <= -0.5:
        return "very_bearish"
    if score <= -0.15:
        return "bearish"
    return "neutral"
