import asyncio
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def format_usd(value: float) -> str:
    """Format value as USD."""
    return f"${value:,.2f}"


def format_crypto(value: float, decimals: int = 8) -> str:
    """Format crypto quantity."""
    return f"{value:.{decimals}f}"


def format_pct(value: float) -> str:
    """Format percentage."""
    return f"{value * 100:.2f}%"


def format_time(dt: Optional[datetime]) -> str:
    """Format datetime for display."""
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


async def retry_async(
    coro_func,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_wait: float = 1.0,
    *args,
    **kwargs
):
    """Async retry with exponential backoff."""
    wait_time = initial_wait
    last_error = None

    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
                wait_time *= backoff_factor
            else:
                logger.error(f"All {max_retries} attempts failed: {e}")

    raise last_error


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max."""
    return max(min_val, min(value, max_val))


def calculate_portfolio_heat(
    total_position_value: float, portfolio_size: float
) -> float:
    """Calculate portfolio heat (% of capital deployed)."""
    if portfolio_size <= 0:
        return 0.0
    return clamp(total_position_value / portfolio_size, 0.0, 1.0)
