from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc


def ensure_utc(value: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC datetime.

    SQLite commonly returns timezone-aware columns as naive values. TradeIQ stores
    every persisted timestamp in UTC, so a naive value from the database must be
    interpreted as UTC rather than as the Railway host or browser local time.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_iso(value: datetime | None) -> str | None:
    """Serialize a timestamp with an explicit UTC marker for browser safety."""
    resolved = ensure_utc(value)
    if resolved is None:
        return None
    return resolved.isoformat().replace("+00:00", "Z")
