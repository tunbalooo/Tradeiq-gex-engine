"""
Finnhub economic calendar — replaces the demo calendar with real upcoming
high-impact US events (FOMC, CPI, NFP, etc.), mapped to TradeIQ's NewsItem
schema (time / event / impact).

Adapted from the user's reference integration. Free tier: 60 calls/min.
Set FINNHUB_API_KEY in the environment (already set on Railway). If the key
is missing or the API fails, we fall back to the static demo list so the
panel is never empty.

Cached 30 min to stay well under the rate limit.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import requests

from backend.models.schemas import NewsItem

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"

_cache: dict = {"data": None, "ts": 0.0, "ttl": 1800}

# Fallback shown only if the key is missing or the API errors.
_DEMO = [
    NewsItem(time="10:00", event="US JOLTS Job Openings", impact="High"),
    NewsItem(time="10:30", event="Crude Oil Inventories", impact="Med"),
    NewsItem(time="11:00", event="Fed Chair / Member Speech", impact="High"),
    NewsItem(time="14:00", event="FOMC Member Speech", impact="Med"),
]

_ALWAYS_HIGH = ("FOMC", "NFP", "CPI", "PPI", "GDP", "PCE", "NON-FARM", "RATE DECISION", "POWELL")


def _impact_label(raw: str, event_name: str) -> str:
    name = (event_name or "").upper()
    if any(k in name for k in _ALWAYS_HIGH):
        return "High"
    raw = (raw or "").lower()
    if raw == "high":
        return "High"
    if raw == "medium":
        return "Med"
    return "Low"


def _fmt_time(raw_time: str) -> str:
    # Finnhub gives "YYYY-MM-DD HH:MM:SS"; show HH:MM, else the date.
    if not raw_time:
        return "—"
    try:
        if " " in raw_time:
            return raw_time.split(" ", 1)[1][:5]
        return raw_time[5:10]  # MM-DD
    except Exception:
        return raw_time[:5]


def get_calendar(days_ahead: int = 2) -> list[NewsItem]:
    """Upcoming medium/high-impact US events, newest window first. Never empty."""
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < _cache["ttl"]:
        return _cache["data"]

    if not FINNHUB_API_KEY:
        return _DEMO

    today = datetime.now(timezone.utc).date()
    try:
        resp = requests.get(
            f"{FINNHUB_BASE}/calendar/economic",
            params={
                "from": today.isoformat(),
                "to": (today + timedelta(days=days_ahead)).isoformat(),
                "token": FINNHUB_API_KEY,
            },
            timeout=8,
        )
        if resp.status_code != 200:
            return _cache["data"] or _DEMO
        events = (resp.json() or {}).get("economicCalendar", []) or []
    except Exception:
        return _cache["data"] or _DEMO

    now_utc = datetime.now(timezone.utc)
    items: list[tuple[str, NewsItem]] = []
    for ev in events:
        country = ev.get("country", "")
        raw_impact = ev.get("impact", "")
        name = ev.get("event", "")
        is_us = country == "US"
        important = raw_impact in ("medium", "high") or any(k in name.upper() for k in _ALWAYS_HIGH)
        if not (is_us and important):
            continue
        raw_time = ev.get("time", "")
        # keep only events still upcoming (or within the last hour)
        try:
            ev_dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if ev_dt < now_utc - timedelta(hours=1):
                continue
        except Exception:
            ev_dt = now_utc
        items.append((raw_time, NewsItem(time=_fmt_time(raw_time), event=name[:40] or "Event",
                                         impact=_impact_label(raw_impact, name))))

    items.sort(key=lambda x: x[0])
    result = [ni for _, ni in items[:6]] or _DEMO
    _cache.update(data=result, ts=now)
    return result
