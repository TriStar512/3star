"""Utility functions for JARBIS Crypto."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional, TypeVar
import pytz

logger = logging.getLogger(__name__)

T = TypeVar("T")


def format_usd(value: float, decimals: int = 2) -> str:
    """Format value as USD."""
    return f"${value:,.{decimals}f}"


def format_pct(value: float, decimals: int = 2) -> str:
    """Format value as percentage."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_crypto(value: float, decimals: int = 8) -> str:
    """Format crypto amount (BTC, ETH, etc)."""
    if value == 0:
        return "0"
    if abs(value) < 0.00000001:
        return f"{value:.10f}".rstrip("0")
    return f"{value:.{decimals}f}".rstrip("0")


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """Format datetime as ISO string."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.isoformat()


def now_utc() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Convert any datetime to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pretty_timestamp(dt: Optional[datetime] = None, tz: str = "UTC") -> str:
    """Pretty format timestamp with timezone."""
    if dt is None:
        dt = now_utc()
    else:
        dt = to_utc(dt)

    if tz != "UTC":
        try:
            tz_obj = pytz.timezone(tz)
            dt = dt.astimezone(tz_obj)
        except pytz.UnknownTimeZoneError:
            pass

    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


async def retry_async(
    func: Callable[..., Coroutine[Any, Any, T]],
    *args,
    max_retries: int = 4,
    backoff_base: float = 2.0,
    **kwargs,
) -> T:
    """
    Retry async function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retries
        backoff_base: Exponential backoff base (2^attempt)
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result of function call

    Raises:
        Last exception if all retries fail
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = backoff_base ** attempt
                logger.warning(
                    f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"All {max_retries} retries exhausted. Final error: {str(e)}")

    raise last_error


def retry_sync(
    func: Callable[..., T],
    *args,
    max_retries: int = 4,
    backoff_base: float = 2.0,
    **kwargs,
) -> T:
    """
    Retry sync function with exponential backoff.

    Args:
        func: Function to retry
        max_retries: Maximum number of retries
        backoff_base: Exponential backoff base
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result of function call
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = backoff_base ** attempt
                logger.warning(
                    f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {wait_time}s..."
                )
                asyncio.run(asyncio.sleep(wait_time))
            else:
                logger.error(f"All {max_retries} retries exhausted. Final error: {str(e)}")

    raise last_error


def pct_change(old: float, new: float) -> float:
    """Calculate percentage change from old to new value."""
    if old == 0:
        return 0
    return ((new - old) / abs(old)) * 100


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max."""
    return max(min_val, min(value, max_val))
