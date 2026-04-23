"""News sentiment pipeline.

Pulls from CryptoCompare and NewsAPI when keys are configured, scores
each headline with a simple keyword heuristic, and exposes a per-ticker
rolling sentiment score in [-1, +1]. Manual injections (via the CLI
``!news`` command or the webhook server) take priority for a short
decay window.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import aiohttp

from .config import Settings, get_settings
from .utils import async_retry, classify_sentiment

log = logging.getLogger(__name__)


POSITIVE = {
    "surge", "surges", "approve", "approved", "approval", "partnership", "breakout",
    "bull", "bullish", "rally", "soar", "soars", "record high", "all-time high",
    "adoption", "integration", "upgrade", "launch", "launches", "accumulate",
    "institutional", "etf", "inflow", "inflows", "buy", "bought",
}
NEGATIVE = {
    "crash", "crashes", "ban", "banned", "hack", "hacked", "exploit", "exploited",
    "bear", "bearish", "plunge", "plunges", "tumble", "tumbles", "lawsuit",
    "fraud", "scam", "dump", "dumps", "liquidated", "liquidation", "outflow",
    "outflows", "sell-off", "selloff", "bankruptcy", "delist", "halt",
}

TICKER_ALIASES: Dict[str, List[str]] = {
    "BTC": ["btc", "bitcoin", "xbt"],
    "ETH": ["eth", "ethereum", "ether"],
    "SOL": ["sol", "solana"],
    "XRP": ["xrp", "ripple"],
}


@dataclass
class ScoredHeadline:
    ticker: str
    headline: str
    score: float
    timestamp: float = field(default_factory=time.time)
    source: str = "auto"


def score_text(text: str) -> float:
    """Return a sentiment score in [-1, +1] from keyword counts."""
    lower = text.lower()
    pos = sum(1 for kw in POSITIVE if kw in lower)
    neg = sum(1 for kw in NEGATIVE if kw in lower)
    if pos == 0 and neg == 0:
        return 0.0
    raw = (pos - neg) / (pos + neg + 1)
    return max(-1.0, min(1.0, raw))


def tag_ticker(text: str) -> Optional[str]:
    lower = text.lower()
    for ticker, aliases in TICKER_ALIASES.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", lower):
                return ticker
    return None


class SentimentEngine:
    DECAY_SECONDS = 60 * 60  # 1h half-life window for scoring

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.headlines: List[ScoredHeadline] = []
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "SentimentEngine":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session:
            await self._session.close()

    def inject_manual(self, ticker: str, headline: str, score: Optional[float] = None) -> ScoredHeadline:
        ticker = ticker.upper()
        score = score if score is not None else score_text(headline)
        sh = ScoredHeadline(ticker=ticker, headline=headline, score=score, source="manual")
        self.headlines.append(sh)
        log.info("manual news %s (%.2f): %s", ticker, score, headline)
        return sh

    async def refresh(self) -> int:
        """Pull from configured feeds, score, and retain only fresh entries."""
        now = time.time()
        self.headlines = [h for h in self.headlines if now - h.timestamp < self.DECAY_SECONDS]
        added = 0
        added += await self._pull_cryptocompare()
        added += await self._pull_newsapi()
        log.debug("sentiment refresh added %d headlines, %d retained", added, len(self.headlines))
        return added

    async def _pull_cryptocompare(self) -> int:
        key = self.settings.cryptocompare_api_key
        if not key or not self._session:
            return 0
        try:
            url = "https://min-api.cryptocompare.com/data/v2/news/"
            params = {"lang": "EN", "api_key": key}
            async with self._session.get(url, params=params, timeout=15) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("cryptocompare fetch failed: %s", exc)
            return 0
        added = 0
        for item in data.get("Data", []) or []:
            title = item.get("title") or ""
            body = item.get("body") or ""
            text = f"{title}. {body[:240]}"
            ticker = tag_ticker(text)
            if not ticker:
                continue
            self.headlines.append(
                ScoredHeadline(ticker=ticker, headline=title, score=score_text(text),
                               source="cryptocompare")
            )
            added += 1
        return added

    async def _pull_newsapi(self) -> int:
        key = self.settings.newsapi_api_key
        if not key or not self._session:
            return 0
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": "crypto OR bitcoin OR ethereum OR solana OR xrp",
                "language": "en",
                "pageSize": 50,
                "sortBy": "publishedAt",
                "apiKey": key,
            }
            async with self._session.get(url, params=params, timeout=15) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("newsapi fetch failed: %s", exc)
            return 0
        added = 0
        for item in data.get("articles", []) or []:
            title = item.get("title") or ""
            desc = item.get("description") or ""
            text = f"{title}. {desc}"
            ticker = tag_ticker(text)
            if not ticker:
                continue
            self.headlines.append(
                ScoredHeadline(ticker=ticker, headline=title, score=score_text(text),
                               source="newsapi")
            )
            added += 1
        return added

    def score_for(self, ticker: str) -> float:
        """Weighted, time-decayed sentiment score for ``ticker``."""
        ticker = ticker.upper()
        now = time.time()
        relevant = [h for h in self.headlines if h.ticker == ticker]
        if not relevant:
            return 0.0
        weighted_sum = 0.0
        weight_total = 0.0
        for h in relevant:
            age = now - h.timestamp
            if age >= self.DECAY_SECONDS:
                continue
            decay = max(0.1, 1.0 - age / self.DECAY_SECONDS)
            bump = 2.0 if h.source == "manual" else 1.0
            w = decay * bump
            weighted_sum += h.score * w
            weight_total += w
        if weight_total == 0:
            return 0.0
        return max(-1.0, min(1.0, weighted_sum / weight_total))

    def label_for(self, ticker: str) -> str:
        return classify_sentiment(self.score_for(ticker))

    def recent(self, ticker: Optional[str] = None, limit: int = 10) -> List[ScoredHeadline]:
        items = self.headlines
        if ticker:
            ticker = ticker.upper()
            items = [h for h in items if h.ticker == ticker]
        return sorted(items, key=lambda h: h.timestamp, reverse=True)[:limit]
