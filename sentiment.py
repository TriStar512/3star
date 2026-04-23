"""News sentiment analysis and scoring."""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """Single news item."""
    source: str
    title: str
    description: str
    url: str
    ticker: str
    sentiment_score: float
    timestamp: datetime


class SentimentAnalyzer:
    """Analyze sentiment from news and events."""

    # Sentiment keywords
    POSITIVE_KEYWORDS = {
        "surge", "approve", "approval", "bull", "bullish", "breakout",
        "partnership", "gain", "rally", "rocket", "moon", "pump",
        "buy", "accumulate", "breakthrough", "record", "new highs",
        "upgrade", "bullish", "optimistic", "boom"
    }

    NEGATIVE_KEYWORDS = {
        "crash", "ban", "hack", "exploit", "bear", "bearish", "collapse",
        "liquidation", "risk", "warning", "sell", "bearish", "pessimistic",
        "decline", "loss", "drop", "plunge", "doom", "panic", "fear",
        "attack", "scandal", "lawsuit", "investigate"
    }

    NEUTRAL_KEYWORDS = {
        "mixed", "consolidation", "sideways", "range", "stable",
        "steady", "flat", "neutral", "update", "report"
    }

    def __init__(self):
        self.recent_news: List[NewsItem] = []
        self.sentiment_history: List[float] = []
        self.max_history = 100

    def score_text(self, text: str) -> float:
        """
        Score sentiment of text.

        Returns:
            Sentiment score in [-1, +1]
            -1.0: very bearish
             0.0: neutral
            +1.0: very bullish
        """
        text_lower = text.lower()

        positive_count = sum(1 for word in self.POSITIVE_KEYWORDS if word in text_lower)
        negative_count = sum(1 for word in self.NEGATIVE_KEYWORDS if word in text_lower)
        neutral_count = sum(1 for word in self.NEUTRAL_KEYWORDS if word in text_lower)

        total = positive_count + negative_count + neutral_count
        if total == 0:
            return 0.0

        # Score: (positive - negative) / total, bounded by [-1, 1]
        score = (positive_count - negative_count) / (total + 1)
        score = max(-1.0, min(1.0, score))

        return score

    def extract_ticker(self, text: str, known_tickers: Optional[List[str]] = None) -> Optional[str]:
        """
        Extract ticker from text.

        Args:
            text: Text to search
            known_tickers: List of valid tickers (e.g., ["BTC", "ETH", "SOL"])

        Returns:
            Ticker if found, None otherwise
        """
        if known_tickers is None:
            known_tickers = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LINK"]

        text_upper = text.upper()
        for ticker in known_tickers:
            if ticker in text_upper:
                return ticker

        return None

    def analyze_news(
        self,
        source: str,
        title: str,
        description: str,
        url: str,
        known_tickers: Optional[List[str]] = None,
    ) -> Optional[NewsItem]:
        """
        Analyze news article.

        Args:
            source: News source name
            title: Article title
            description: Article description
            url: Article URL
            known_tickers: List of valid tickers

        Returns:
            NewsItem if ticker found, None otherwise
        """
        # Extract ticker
        text_to_analyze = f"{title} {description}"
        ticker = self.extract_ticker(text_to_analyze, known_tickers)

        if not ticker:
            return None

        # Score sentiment
        sentiment_score = self.score_text(text_to_analyze)

        # Create news item
        news_item = NewsItem(
            source=source,
            title=title,
            description=description,
            url=url,
            ticker=ticker,
            sentiment_score=sentiment_score,
            timestamp=now_utc(),
        )

        # Store in recent news
        self.recent_news.append(news_item)
        self.recent_news = self.recent_news[-100:]  # Keep last 100

        logger.info(
            f"News: {ticker} sentiment={sentiment_score:.2f} from {source}: {title[:60]}..."
        )

        return news_item

    def get_sentiment_for_ticker(self, ticker: str, window_minutes: int = 60) -> float:
        """
        Get aggregated sentiment for a ticker.

        Args:
            ticker: Ticker symbol
            window_minutes: Look back window in minutes

        Returns:
            Aggregated sentiment score [-1, +1]
        """
        if not self.recent_news:
            return 0.0

        cutoff_time = now_utc().timestamp() - (window_minutes * 60)
        relevant_news = [
            news
            for news in self.recent_news
            if news.ticker == ticker and news.timestamp.timestamp() > cutoff_time
        ]

        if not relevant_news:
            return 0.0

        # Weighted average: recent news weighted more
        total_weight = 0.0
        weighted_score = 0.0

        for news in relevant_news:
            # Weight decreases with age
            age_minutes = (now_utc() - news.timestamp).total_seconds() / 60
            weight = max(0.1, 1.0 - (age_minutes / window_minutes))
            weighted_score += news.sentiment_score * weight
            total_weight += weight

        return weighted_score / total_weight if total_weight > 0 else 0.0

    def get_all_sentiment(self, window_minutes: int = 60) -> Dict[str, float]:
        """
        Get sentiment for all tickers in recent news.

        Args:
            window_minutes: Look back window in minutes

        Returns:
            Dict of ticker -> sentiment score
        """
        tickers = {news.ticker for news in self.recent_news}
        return {ticker: self.get_sentiment_for_ticker(ticker, window_minutes) for ticker in tickers}

    def label_sentiment(self, score: float) -> str:
        """Label sentiment score."""
        if score > 0.6:
            return "very_bullish"
        elif score > 0.2:
            return "bullish"
        elif score > -0.2:
            return "neutral"
        elif score > -0.6:
            return "bearish"
        else:
            return "very_bearish"

    def inject_news(self, ticker: str, title: str, sentiment_override: Optional[float] = None):
        """
        Manually inject news (for breaking news or manual input).

        Args:
            ticker: Ticker symbol
            title: News title
            sentiment_override: Optional manual sentiment score
        """
        if sentiment_override is not None:
            score = max(-1.0, min(1.0, sentiment_override))
        else:
            score = self.score_text(title)

        news_item = NewsItem(
            source="MANUAL",
            title=title,
            description="",
            url="",
            ticker=ticker,
            sentiment_score=score,
            timestamp=now_utc(),
        )

        self.recent_news.append(news_item)
        self.recent_news = self.recent_news[-100:]

        logger.info(f"Injected news: {ticker} sentiment={score:.2f} - {title}")
        return news_item

    def clear_history(self):
        """Clear all news history."""
        self.recent_news = []
        self.sentiment_history = []


# Global instance
sentiment_analyzer = SentimentAnalyzer()
