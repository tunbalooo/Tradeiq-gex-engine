from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any

import httpx

from backend.core.config import settings
from backend.models.schemas import NewsItem
from backend.services.instruments import InstrumentProfile, get_instrument, instrument_registry


class FinnhubNewsService:
    """Shared cached Finnhub connector with instrument-aware filtering.

    Finnhub's general-news response is shared across NQ, ES, and Gold. TradeIQ
    downloads it once, then filters the same cached feed locally for the active
    market. News never changes confidence, actionability, order arming, stops,
    or targets.
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self) -> None:
        self._lock = Lock()
        self._raw_feed: list[dict[str, Any]] = []
        self._feed_cached_at: float = 0.0
        self._filtered_cache: dict[str, list[NewsItem]] = {}
        self._next_retry_at: float = 0.0
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.finnhub_api_key)

    def status(self, symbol: str | None = None) -> dict[str, Any]:
        profile = get_instrument(symbol) if symbol else instrument_registry.active
        items = self._filtered_cache.get(profile.symbol, [])
        return {
            "enabled": self.enabled,
            "source": "finnhub" if self.enabled else "not-configured",
            "symbol": profile.symbol,
            "market_family": profile.family,
            "cached_items": len(items),
            "shared_feed_cached": bool(self._raw_feed),
            "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
            "last_error": self._last_error,
            "refresh_seconds": settings.finnhub_news_refresh_seconds,
        }

    def latest(self, limit: int = 8, symbol: str | None = None) -> list[NewsItem]:
        profile = get_instrument(symbol) if symbol else instrument_registry.active
        if not self.enabled:
            return [NewsItem(
                time="—",
                event="Finnhub news connector is not configured",
                impact="Low",
                source="TradeIQ",
            )]

        if self._feed_is_fresh():
            return self._items_for(profile)[:limit]
        if monotonic() < self._next_retry_at:
            return self._items_for(profile)[:limit] if self._raw_feed else [NewsItem(
                time="—",
                event=f"Finnhub {profile.symbol} news is temporarily unavailable",
                impact="Low",
                source="Finnhub",
            )]

        with self._lock:
            if not self._feed_is_fresh():
                try:
                    self._raw_feed = self._fetch_general_news()
                    self._feed_cached_at = monotonic()
                    self._filtered_cache.clear()
                    self._next_retry_at = 0.0
                    self._last_error = None
                    self._last_success_at = datetime.now(timezone.utc)
                except Exception as exc:  # keep dashboard usable during provider failure
                    self._last_error = str(exc)[:300]
                    self._next_retry_at = monotonic() + min(60.0, float(settings.finnhub_news_refresh_seconds))
                    if not self._raw_feed:
                        return [NewsItem(
                            time="—",
                            event=f"Finnhub {profile.symbol} news is temporarily unavailable",
                            impact="Low",
                            source="Finnhub",
                        )]
            return self._items_for(profile)[:limit]

    def _feed_is_fresh(self) -> bool:
        return bool(
            self._raw_feed
            and monotonic() - self._feed_cached_at < settings.finnhub_news_refresh_seconds
        )

    def _items_for(self, profile: InstrumentProfile) -> list[NewsItem]:
        cached = self._filtered_cache.get(profile.symbol)
        if cached is not None:
            return cached
        items = self._score_news(self._raw_feed, profile.news_terms)
        self._filtered_cache[profile.symbol] = items
        return items

    def _fetch_general_news(self) -> list[dict[str, Any]]:
        headers = {"X-Finnhub-Token": settings.finnhub_api_key or ""}
        with httpx.Client(timeout=settings.finnhub_request_timeout_seconds, headers=headers) as client:
            response = client.get(f"{self.BASE_URL}/news", params={"category": "general", "minId": 0})
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, list):
            raise RuntimeError("Finnhub returned an unexpected news response")
        return [item for item in payload if isinstance(item, dict)]

    def _score_news(self, payload: list[dict[str, Any]], terms: tuple[str, ...]) -> list[NewsItem]:
        scored: list[tuple[int, int, NewsItem]] = []
        for raw in payload:
            headline = str(raw.get("headline") or "").strip()
            summary = str(raw.get("summary") or "").strip()
            if not headline:
                continue
            text = f"{headline} {summary}".lower()
            relevance = sum(1 for term in terms if term in text)
            timestamp = int(raw.get("datetime") or 0)
            impact = "High" if relevance >= 2 else "Med" if relevance == 1 else "Low"
            published = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone() if timestamp else None
            scored.append((relevance, timestamp, NewsItem(
                time=published.strftime("%H:%M") if published else "—",
                event=headline,
                impact=impact,
                source=str(raw.get("source") or "Finnhub"),
                url=str(raw.get("url") or "") or None,
                summary=summary or None,
                published_at=published,
            )))

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        relevant = [item for score, _, item in scored if score > 0]
        if len(relevant) < 5:
            relevant.extend(item for score, _, item in scored if score == 0)
        return relevant[:20] or [NewsItem(
            time="—", event="No recent Finnhub headlines returned", impact="Low", source="Finnhub"
        )]


finnhub_news_service = FinnhubNewsService()
