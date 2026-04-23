from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from config import settings
import logging
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class SentimentInput:
    ticker: str
    headlines: List[str]
    manual_injection: Optional[str] = None


@dataclass
class SentimentOutput:
    score: float  # [-1, +1]
    label: str  # 'very_bearish', 'bearish', 'neutral', 'bullish', 'very_bullish'
    headline_count: int
    last_update: datetime


POSITIVE_KEYWORDS = [
    "surge",
    "soar",
    "rally",
    "approve",
    "approval",
    "partnership",
    "breakout",
    "bull",
    "bullish",
    "gain",
    "profit",
    "growth",
    "moon",
]

NEGATIVE_KEYWORDS = [
    "crash",
    "dump",
    "plunge",
    "ban",
    "banned",
    "hack",
    "hacked",
    "exploit",
    "bear",
    "bearish",
    "loss",
    "decline",
    "drop",
]

NEUTRAL_KEYWORDS = [
    "mixed",
    "consolidation",
    "sideways",
    "range",
    "flat",
]


def score_headline(headline: str) -> float:
    """
    Score a single headline from -1 (very negative) to +1 (very positive).
    """
    headline_lower = headline.lower()

    positive_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in headline_lower)
    negative_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in headline_lower)
    neutral_count = sum(1 for kw in NEUTRAL_KEYWORDS if kw in headline_lower)

    # Neutral headlines don't move the score
    if neutral_count > 0 and positive_count == 0 and negative_count == 0:
        return 0.0

    total = positive_count + negative_count
    if total == 0:
        return 0.0

    # Normalize to [-1, +1]
    return (positive_count - negative_count) / (positive_count + negative_count)


def calculate_sentiment(input_data: SentimentInput) -> SentimentOutput:
    """
    Calculate aggregate sentiment from headlines.
    """
    headlines_to_score = input_data.headlines.copy()

    # Add manual injection if provided
    if input_data.manual_injection:
        headlines_to_score.append(input_data.manual_injection)

    if not headlines_to_score:
        return SentimentOutput(
            score=0.0,
            label="neutral",
            headline_count=0,
            last_update=datetime.utcnow(),
        )

    # Score each headline and average
    scores = [score_headline(h) for h in headlines_to_score]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    # Clamp to [-1, +1]
    avg_score = max(-1.0, min(1.0, avg_score))

    # Determine label
    if avg_score < -0.6:
        label = "very_bearish"
    elif avg_score < -0.2:
        label = "bearish"
    elif avg_score < 0.2:
        label = "neutral"
    elif avg_score < 0.6:
        label = "bullish"
    else:
        label = "very_bullish"

    return SentimentOutput(
        score=avg_score,
        label=label,
        headline_count=len(headlines_to_score),
        last_update=datetime.utcnow(),
    )


class SentimentBuffer:
    """
    Buffer headlines for a ticker with TTL (time-to-live).
    Older headlines decay in importance.
    """

    def __init__(self, ttl_minutes: int = 60):
        self.ttl = timedelta(minutes=ttl_minutes)
        self.headlines: Dict[str, List[tuple[str, datetime]]] = {}

    def add_headline(self, ticker: str, headline: str) -> None:
        """Add headline with timestamp."""
        if ticker not in self.headlines:
            self.headlines[ticker] = []
        self.headlines[ticker].append((headline, datetime.utcnow()))

    def get_active_headlines(self, ticker: str) -> List[str]:
        """Get headlines still within TTL."""
        if ticker not in self.headlines:
            return []

        now = datetime.utcnow()
        active = [
            h for h, ts in self.headlines[ticker]
            if (now - ts) < self.ttl
        ]

        # Clean old ones
        self.headlines[ticker] = [
            (h, ts) for h, ts in self.headlines[ticker]
            if (now - ts) < self.ttl
        ]

        return active

    def get_sentiment(self, ticker: str) -> SentimentOutput:
        """Get current sentiment for ticker."""
        active = self.get_active_headlines(ticker)
        return calculate_sentiment(SentimentInput(ticker=ticker, headlines=active))
