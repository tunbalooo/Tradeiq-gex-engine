from datetime import datetime
from zoneinfo import ZoneInfo

from backend.services.session_service import get_session_status

ET = ZoneInfo("America/New_York")


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def test_new_york_session_is_open():
    status = get_session_status(at(2026, 7, 15, 10, 0))
    assert status["is_open"] is True
    assert status["session_name"] == "NEW_YORK"


def test_daily_maintenance_is_closed_and_has_countdown_target():
    status = get_session_status(at(2026, 7, 15, 17, 15))
    assert status["is_open"] is False
    assert status["exchange_status"] == "CLOSED"
    assert status["next_open_at"].endswith("18:00:00-04:00")


def test_weekend_is_closed_until_sunday():
    status = get_session_status(at(2026, 7, 18, 12, 0))
    assert status["is_open"] is False
    assert status["reason"] == "Weekend close"
    assert "2026-07-19T18:00:00" in status["next_open_at"]
