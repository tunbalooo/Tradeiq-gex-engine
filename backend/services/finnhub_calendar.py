from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Any

import httpx

from backend.core.config import settings
from backend.models.schemas import EconomicEvent


class FinnhubEconomicCalendarService:
    """Cached upcoming US economic releases from Finnhub.

    This is intentionally separate from the market-headlines service. Headline
    timestamps are publication times; calendar timestamps are the scheduled
    release times traders care about. Calendar data is informational only and
    never changes confidence, actionability, order arming, stops, or targets.
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self) -> None:
        self._lock = Lock()
        self._items: list[EconomicEvent] = []
        self._cached_at: float = 0.0
        self._next_retry_at: float = 0.0
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None
        self._access: str = "unknown"

    @property
    def enabled(self) -> bool:
        return bool(settings.finnhub_api_key)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "source": "finnhub-economic-calendar" if self.enabled else "not-configured",
            "access": self._access,
            "cached_items": len(self._items),
            "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
            "last_error": self._last_error,
            "refresh_seconds": settings.finnhub_calendar_refresh_seconds,
        }

    def latest(self, limit: int = 10, days: int = 7) -> list[EconomicEvent]:
        if not self.enabled:
            self._access = "not-configured"
            return []

        if self._is_fresh():
            return self._upcoming(limit)
        if monotonic() < self._next_retry_at:
            return self._upcoming(limit)

        with self._lock:
            if not self._is_fresh():
                now = datetime.now(timezone.utc)
                try:
                    payload = self._fetch(now.date().isoformat(), (now.date() + timedelta(days=days)).isoformat())
                    self._items = self._parse(payload, now=now)
                    self._cached_at = monotonic()
                    self._next_retry_at = 0.0
                    self._last_error = None
                    self._last_success_at = now
                    self._access = "ready"
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    self._access = "premium-required" if code in {401, 402, 403} else "error"
                    self._last_error = f"Finnhub economic calendar request failed ({code})"
                    self._next_retry_at = monotonic() + min(300.0, float(settings.finnhub_calendar_refresh_seconds))
                except Exception as exc:  # keep the application usable during provider failure
                    self._access = "error"
                    self._last_error = str(exc)[:300]
                    self._next_retry_at = monotonic() + min(120.0, float(settings.finnhub_calendar_refresh_seconds))

        return self._upcoming(limit)

    def _is_fresh(self) -> bool:
        return bool(
            self._cached_at
            and monotonic() - self._cached_at < settings.finnhub_calendar_refresh_seconds
        )

    def _upcoming(self, limit: int) -> list[EconomicEvent]:
        now = datetime.now(timezone.utc)
        return [item for item in self._items if item.scheduled_at >= now - timedelta(minutes=2)][:limit]

    def _fetch(self, from_date: str, to_date: str) -> dict[str, Any]:
        headers = {"X-Finnhub-Token": settings.finnhub_api_key or ""}
        with httpx.Client(timeout=settings.finnhub_request_timeout_seconds, headers=headers) as client:
            response = client.get(
                f"{self.BASE_URL}/calendar/economic",
                params={"from": from_date, "to": to_date},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Finnhub returned an unexpected economic calendar response")
        return payload

    def _parse(self, payload: dict[str, Any], now: datetime | None = None) -> list[EconomicEvent]:
        now = now or datetime.now(timezone.utc)
        raw_items = payload.get("economicCalendar")
        if not isinstance(raw_items, list):
            raise RuntimeError("Finnhub economic calendar response did not contain economicCalendar")

        events: list[EconomicEvent] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            country = str(raw.get("country") or "").upper().strip()
            event_name = str(raw.get("event") or "").strip()
            scheduled_at = self._parse_time(raw.get("time"))
            if country not in {"US", "USA"} or not event_name or scheduled_at is None:
                continue
            if scheduled_at < now - timedelta(minutes=2):
                continue

            impact_raw = str(raw.get("impact") or "low").lower()
            impact = "High" if impact_raw.startswith("high") else "Med" if impact_raw.startswith(("med", "moderate")) else "Low"
            events.append(EconomicEvent(
                scheduled_at=scheduled_at,
                event=event_name,
                impact=impact,
                country=country,
                actual=raw.get("actual"),
                estimate=raw.get("estimate"),
                previous=raw.get("prev"),
                unit=str(raw.get("unit") or "") or None,
            ))

        events.sort(key=lambda item: (item.scheduled_at, {"High": 0, "Med": 1, "Low": 2}[item.impact]))
        return events

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        text = str(value).strip()
        try:
            # Finnhub calendar examples use UTC-style wall-clock values.
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None


finnhub_calendar_service = FinnhubEconomicCalendarService()
