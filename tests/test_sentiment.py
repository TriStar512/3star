"""Tests for sentiment analysis."""

import pytest
from sentiment import SentimentAnalyzer


class TestSentimentAnalyzer:
    """Test suite for sentiment analysis."""

    def setup_method(self):
        """Setup for each test."""
        self.analyzer = SentimentAnalyzer()

    def test_positive_sentiment(self):
        """Test positive sentiment detection."""
        text = "Bitcoin surge and bullish breakout with partnership announcement"
        score = self.analyzer.score_text(text)
        assert score > 0.3

    def test_negative_sentiment(self):
        """Test negative sentiment detection."""
        text = "Bitcoin crash and bearish collapse due to hacks and exploits"
        score = self.analyzer.score_text(text)
        assert score < -0.3

    def test_neutral_sentiment(self):
        """Test neutral sentiment detection."""
        text = "Bitcoin consolidation and stable trading pattern"
        score = self.analyzer.score_text(text)
        assert -0.3 <= score <= 0.3

    def test_mixed_sentiment(self):
        """Test mixed sentiment."""
        text = "Bitcoin gains but faces risks and bearish pressure"
        score = self.analyzer.score_text(text)
        # Mixed with more negative keywords = slightly negative
        assert -0.5 <= score <= 0.5

    def test_empty_text(self):
        """Test empty text."""
        score = self.analyzer.score_text("")
        assert score == 0.0

    def test_no_keywords(self):
        """Test text with no sentiment keywords."""
        score = self.analyzer.score_text("The quick brown fox jumps over the lazy dog")
        assert score == 0.0

    def test_ticker_extraction(self):
        """Test ticker extraction from text."""
        tickers = ["BTC", "ETH", "SOL"]

        # BTC in text
        ticker = self.analyzer.extract_ticker("BTC is rising", tickers)
        assert ticker == "BTC"

        # ETH in text
        ticker = self.analyzer.extract_ticker("ETH reaches new highs", tickers)
        assert ticker == "ETH"

        # Multiple tickers - should return first match
        ticker = self.analyzer.extract_ticker("BTC and ETH trading", tickers)
        assert ticker in ["BTC", "ETH"]

    def test_sentiment_labeling(self):
        """Test sentiment label generation."""
        assert self.analyzer.label_sentiment(0.9) == "very_bullish"
        assert self.analyzer.label_sentiment(0.4) == "bullish"
        assert self.analyzer.label_sentiment(0.0) == "neutral"
        assert self.analyzer.label_sentiment(-0.4) == "bearish"
        assert self.analyzer.label_sentiment(-0.9) == "very_bearish"

    def test_inject_news(self):
        """Test manual news injection."""
        self.analyzer.inject_news("BTC", "Bullish news")
        sentiment = self.analyzer.get_sentiment_for_ticker("BTC", window_minutes=60)
        assert sentiment > 0

    def test_get_sentiment_for_ticker(self):
        """Test getting sentiment for specific ticker."""
        self.analyzer.inject_news("BTC", "Bullish news")
        self.analyzer.inject_news("ETH", "Bearish news")

        btc_sentiment = self.analyzer.get_sentiment_for_ticker("BTC")
        eth_sentiment = self.analyzer.get_sentiment_for_ticker("ETH")

        assert btc_sentiment > eth_sentiment

    def test_get_all_sentiment(self):
        """Test getting sentiment for all tickers."""
        self.analyzer.inject_news("BTC", "Bullish")
        self.analyzer.inject_news("ETH", "Bearish")
        self.analyzer.inject_news("SOL", "Neutral")

        all_sentiment = self.analyzer.get_all_sentiment()

        assert "BTC" in all_sentiment
        assert "ETH" in all_sentiment
        assert "SOL" in all_sentiment

    def test_sentiment_window(self):
        """Test sentiment with time window."""
        self.analyzer.inject_news("BTC", "Bullish")
        sentiment_60m = self.analyzer.get_sentiment_for_ticker("BTC", window_minutes=60)
        sentiment_1m = self.analyzer.get_sentiment_for_ticker("BTC", window_minutes=1)

        # Wider window might include more data
        assert sentiment_60m != 0.0

    def test_clear_history(self):
        """Test clearing news history."""
        self.analyzer.inject_news("BTC", "Bullish")
        assert len(self.analyzer.recent_news) > 0

        self.analyzer.clear_history()
        assert len(self.analyzer.recent_news) == 0

    def test_recent_news_limit(self):
        """Test that recent news is capped at max_history."""
        # Inject more than max_history
        for i in range(150):
            self.analyzer.inject_news("BTC", f"News {i}")

        # Should only keep last 100
        assert len(self.analyzer.recent_news) <= 100

    def test_case_insensitive_keywords(self):
        """Test that keyword matching is case insensitive."""
        text_lower = "bitcoin surge and bullish breakout"
        text_upper = "BITCOIN SURGE AND BULLISH BREAKOUT"

        score_lower = self.analyzer.score_text(text_lower)
        score_upper = self.analyzer.score_text(text_upper)

        assert score_lower == score_upper

    def test_analyze_news(self):
        """Test analyzing news article."""
        tickers = ["BTC", "ETH"]
        news = self.analyzer.analyze_news(
            source="CryptoNews",
            title="Bitcoin surges on bullish news",
            description="BTC rises 10%",
            url="https://example.com",
            known_tickers=tickers,
        )

        assert news is not None
        assert news.ticker == "BTC"
        assert news.sentiment_score > 0
        assert news.source == "CryptoNews"

    def test_analyze_news_no_ticker(self):
        """Test analyzing news without matching ticker."""
        tickers = ["BTC", "ETH"]
        news = self.analyzer.analyze_news(
            source="News",
            title="Generic market news",
            description="No specific crypto mentioned",
            url="https://example.com",
            known_tickers=tickers,
        )

        assert news is None

    def test_weighted_sentiment(self):
        """Test that recent news is weighted more."""
        # Older news
        self.analyzer.inject_news("BTC", "Bearish", -0.8)
        # Wait a moment
        import time
        time.sleep(0.1)
        # Newer bullish news
        self.analyzer.inject_news("BTC", "Bullish", 0.8)

        sentiment = self.analyzer.get_sentiment_for_ticker("BTC", window_minutes=60)
        # Should be closer to the newer, more recent sentiment
        assert sentiment > 0
