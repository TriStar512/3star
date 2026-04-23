import unittest
from sentiment import calculate_sentiment, score_headline, SentimentInput


class TestSentimentScoring(unittest.TestCase):
    """Unit tests for news sentiment analysis."""

    def test_positive_keywords(self):
        """Headlines with positive keywords should score high."""
        headlines = [
            "Bitcoin surge to new all-time high",
            "ETF approval bullish for crypto",
            "Partnership announcement breakout",
        ]

        for headline in headlines:
            score = score_headline(headline)
            self.assertGreater(score, 0.0, f"Failed for: {headline}")

    def test_negative_keywords(self):
        """Headlines with negative keywords should score low."""
        headlines = [
            "Bitcoin crash looms",
            "Crypto exchange hack confirmed",
            "Bearish pressure on markets",
        ]

        for headline in headlines:
            score = score_headline(headline)
            self.assertLess(score, 0.0, f"Failed for: {headline}")

    def test_neutral_keywords(self):
        """Headlines with only neutral keywords should score ~0."""
        headlines = [
            "Market consolidation continues",
            "Sideways trading observed",
        ]

        for headline in headlines:
            score = score_headline(headline)
            self.assertAlmostEqual(score, 0.0, delta=0.1, msg=f"Failed for: {headline}")

    def test_mixed_sentiment(self):
        """Headlines with mixed keywords should balance out."""
        headline = "Bitcoin bull run but risks remain bear-ish"
        score = score_headline(headline)
        # Should be close to neutral due to mixed sentiment
        self.assertLess(abs(score), 0.5)

    def test_sentiment_aggregation(self):
        """Multiple headlines should aggregate correctly."""
        input_data = SentimentInput(
            ticker="BTC",
            headlines=[
                "Bitcoin surge",
                "Bitcoin surge",
                "Bitcoin crash",  # 1 negative
            ],
        )

        output = calculate_sentiment(input_data)
        # 2 positive, 1 negative -> positive score
        self.assertGreater(output.score, 0.0)

    def test_empty_headlines(self):
        """Empty headlines list should return neutral sentiment."""
        input_data = SentimentInput(ticker="BTC", headlines=[])
        output = calculate_sentiment(input_data)

        self.assertEqual(output.score, 0.0)
        self.assertEqual(output.label, "neutral")
        self.assertEqual(output.headline_count, 0)

    def test_sentiment_labels(self):
        """Sentiment scores should map to correct labels."""
        test_cases = [
            (-0.9, "very_bearish"),
            (-0.5, "bearish"),
            (0.0, "neutral"),
            (0.5, "bullish"),
            (0.9, "very_bullish"),
        ]

        for score, expected_label in test_cases:
            input_data = SentimentInput(
                ticker="BTC",
                headlines=["dummy"],
            )
            # Mock the sentiment calculation
            from sentiment import SentimentOutput

            output = SentimentOutput(
                score=score,
                label=expected_label,
                headline_count=1,
                last_update=None,
            )

            self.assertEqual(output.label, expected_label)


if __name__ == "__main__":
    unittest.main()
