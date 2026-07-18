from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day.date(), time(hour, minute), tzinfo=ET)


def _next_sunday_1800(now_et: datetime) -> datetime:
    days = (6 - now_et.weekday()) % 7
    target = _at(now_et + timedelta(days=days), 18)
    if target <= now_et:
        target += timedelta(days=7)
    return target


def _session_name(now_et: datetime) -> tuple[str, str, datetime]:
    minutes = now_et.hour * 60 + now_et.minute
    if minutes >= 18 * 60 or minutes < 3 * 60:
        end = _at(now_et, 3) if minutes < 3 * 60 else _at(now_et + timedelta(days=1), 3)
        return "ASIA", "ASIA SESSION", end
    if minutes < 9 * 60 + 30:
        return "LONDON", "LONDON SESSION", _at(now_et, 9, 30)
    if minutes < 16 * 60:
        return "NEW_YORK", "NEW YORK SESSION", _at(now_et, 16)
    return "GLOBEX", "GLOBEX SESSION", _at(now_et, 17)


def get_session_status(now: datetime | None = None) -> dict:
    """Return CME Globex availability and the strategy session label.

    This gate is deliberately separate from the confidence score. It controls whether
    a new setup may be armed, but never changes confluence weights or confidence.
    """
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    weekday = now_et.weekday()  # Mon=0 ... Sun=6
    minutes = now_et.hour * 60 + now_et.minute

    is_open = True
    exchange_status = "OPEN"
    reason = "CME Globex open"
    next_open: datetime | None = None
    next_transition: datetime | None = None
    session_name = "CLOSED"
    display_name = "MARKET CLOSED"

    # Weekend: Friday 17:00 ET through Sunday 18:00 ET.
    if weekday == 4 and minutes >= 17 * 60:
        is_open = False
        reason = "Weekend close"
        next_open = _next_sunday_1800(now_et)
    elif weekday == 5:
        is_open = False
        reason = "Weekend close"
        next_open = _next_sunday_1800(now_et)
    elif weekday == 6 and minutes < 18 * 60:
        is_open = False
        reason = "Weekend close"
        next_open = _at(now_et, 18)
    # Daily maintenance Monday-Thursday 17:00-18:00 ET.
    elif weekday in {0, 1, 2, 3} and 17 * 60 <= minutes < 18 * 60:
        is_open = False
        reason = "Daily maintenance"
        next_open = _at(now_et, 18)
    # Equity-index trading halt on normal weekdays.
    elif weekday in {0, 1, 2, 3, 4} and 16 * 60 + 15 <= minutes < 16 * 60 + 30:
        is_open = False
        exchange_status = "HALT"
        reason = "Scheduled trading halt"
        next_open = _at(now_et, 16, 30)

    if is_open:
        session_name, display_name, session_end = _session_name(now_et)
        next_transition = session_end
        countdown_target = session_end
        countdown_label = "SESSION CHANGES IN"
    else:
        exchange_status = exchange_status if exchange_status == "HALT" else "CLOSED"
        countdown_target = next_open
        countdown_label = "OPENS IN"

    return {
        "exchange_status": exchange_status,
        "session_name": session_name,
        "display_name": display_name,
        "is_open": is_open,
        "can_trade_now": is_open,
        "reason": reason,
        "time_zone": "America/New_York",
        "now": now_et.isoformat(),
        "next_open_at": next_open.isoformat() if next_open else None,
        "next_transition_at": next_transition.isoformat() if next_transition else None,
        "countdown_target": countdown_target.isoformat() if countdown_target else None,
        "countdown_label": countdown_label,
    }
