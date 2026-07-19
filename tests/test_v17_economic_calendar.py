from datetime import datetime, timezone
from pathlib import Path

from backend.services.finnhub_calendar import FinnhubEconomicCalendarService


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")


def test_economic_calendar_filters_to_upcoming_us_events_and_normalizes_impact():
    service = FinnhubEconomicCalendarService()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    items = service._parse({
        "economicCalendar": [
            {"country": "US", "event": "CPI", "impact": "high", "time": "2026-07-20 12:30:00", "estimate": 2.7, "prev": 2.6, "unit": "%"},
            {"country": "US", "event": "Retail Sales", "impact": "medium", "time": "2026-07-19 12:30:00"},
            {"country": "CA", "event": "Canada CPI", "impact": "high", "time": "2026-07-19 12:30:00"},
            {"country": "US", "event": "Old Event", "impact": "low", "time": "2026-07-17 12:30:00"},
        ]
    }, now=now)

    assert [item.event for item in items] == ["Retail Sales", "CPI"]
    assert items[0].impact == "Med"
    assert items[1].impact == "High"
    assert items[1].scheduled_at.tzinfo == timezone.utc


def test_frontend_labels_calendar_time_as_scheduled_not_current_or_published():
    assert "function calendarDateParts" in APP_JS
    assert "item.scheduled_at" in APP_JS
    assert "Scheduled release time" in INDEX or "scheduled release time" in INDEX
    assert 'id="mobileCalendarList"' in INDEX
    assert 'id="economicCalendar"' in INDEX
    assert ".mobile-calendar-card" in STYLES


def test_service_worker_cache_is_v17():
    worker = (ROOT / "frontend" / "service-worker.js").read_text(encoding="utf-8")
    assert "tradeiq-v1.7-shell" in worker
    assert "?v=17" in worker
