from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any

import httpx

from backend.core.config import settings
from backend.models.schemas import NewsItem


class FinnhubNewsService:
    """Small cached Finnhub connector for the TradeIQ news panel.

    The connector is informational only. It does not alter confidence,
    actionable state, order arming, stops, or targets.
    """

    BASE_URL = "https://finnhub.io/api/v1"
    NQ_TERMS = (
        "nasdaq", "nasdaq 100", "nq", "technology", "tech stocks",
        "federal reserve", "fed", "fomc", "inflation", "cpi", "ppi",
        "payroll", "jobs report", "treasury", "yield", "interest rate",
        "nvidia", "nvda", "microsoft", "msft", "apple", "aapl",
        "amazon", "amzn", "meta", "tesla", "tsla", "alphabet", "google",
    )

    def __init__(self) -> None:
        self._lock = Lock()
        self._cached: list[NewsItem] = []
        self._cached_at = 0.0
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.finnhub_api_key)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "source": "finnhub" if self.enabled else "not-configured",
            "cached_items": len(self._cached),
            "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
            "last_error": self._last_error,
            "refresh_seconds": settings.finnhub_news_refresh_seconds,
        }

    def latest(self, limit: int = 8) -> list[NewsItem]:
        if not self.enabled:
            return [NewsItem(
                time="—",
                event="Finnhub news connector is not configured",
                impact="Low",
                source="TradeIQ",
            )]

        now = monotonic()
        if self._cached and now - self._cached_at < settings.finnhub_news_refresh_seconds:
            return self._cached[:limit]

        with self._lock:
            now = monotonic()
            if self._cached and now - self._cached_at < settings.finnhub_news_refresh_seconds:
                return self._cached[:limit]
            try:
                items = self._fetch_general_news()
                self._cached = items
                self._cached_at = monotonic()
                self._last_error = None
                self._last_success_at = datetime.now(timezone.utc)
            except Exception as exc:  # keep dashboard usable during provider failure
                self._last_error = str(exc)[:300]
                if not self._cached:
                    self._cached = [NewsItem(
                        time="—",
                        event="Finnhub news is temporarily unavailable",
                        impact="Low",
                        source="Finnhub",
                    )]
                    self._cached_at = monotonic()
            return self._cached[:limit]

    def _fetch_general_news(self) -> list[NewsItem]:
        headers = {"X-Finnhub-Token": settings.finnhub_api_key or ""}
        with httpx.Client(timeout=settings.finnhub_request_timeout_seconds, headers=headers) as client:
            response = client.get(f"{self.BASE_URL}/news", params={"category": "general", "minId": 0})
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, list):
            raise RuntimeError("Finnhub returned an unexpected news response")

        scored: list[tuple[int, int, NewsItem]] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            headline = str(raw.get("headline") or "").strip()
            summary = str(raw.get("summary") or "").strip()
            if not headline:
                continue
            text = f"{headline} {summary}".lower()
            relevance = sum(1 for term in self.NQ_TERMS if term in text)
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
