"""Fib Pullback Continuation model evidence.

The model is intentionally different from the anticipatory OTE model:
- the 50%–61.8% zone is only a monitoring location;
- a closed execution candle must reject/reclaim the zone;
- the executable limit is the 50% body retracement of that confirmation candle;
- the stop represents structural pullback invalidation, not a fixed Fibonacci ratio.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence


@dataclass(slots=True)
class FibPullbackEvidence:
    zone_low: float
    zone_high: float
    watch_price: float
    invalidation_price: float
    impulse_quality: float
    touched: bool
    rejection: bool
    confirmed: bool
    confirmation_entry: float | None
    entry_fresh: bool
    confirmation_candle_time: datetime | None


def _round_to_tick(value: float, tick_size: float) -> float:
    tick = max(float(tick_size), 1e-9)
    return round(round(float(value) / tick) * tick, 10)


def _closed_execution_candles(candles: Sequence, timeframe_minutes: int = 1) -> list:
    """Return candles that are closed when timestamps represent bar opens.

    Historical/test data is naturally retained because its bar end is in the past.
    For live data, the still-forming final bar is excluded from confirmation logic.
    """
    now = datetime.now(timezone.utc)
    closed = []
    for candle in candles:
        at = candle.time
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at + timedelta(minutes=timeframe_minutes) <= now:
            closed.append(candle)
    if len(closed) >= 2:
        return closed
    # Safe fallback for deterministic fixtures and providers that timestamp bars
    # by close rather than open: never use more than the final completed-looking bar.
    return list(candles[:-1] if len(candles) > 2 else candles)


def analyze_fib_pullback_continuation(
    execution_candles: Sequence,
    *,
    direction: str,
    swing_low: float,
    swing_high: float,
    current_price: float,
    atr: float,
    tick_size: float,
) -> FibPullbackEvidence:
    direction = direction.upper()
    span = max(float(swing_high) - float(swing_low), 0.0)
    safe_atr = max(float(atr), float(tick_size) * 8, 0.25)

    if direction == "LONG":
        fib_50 = float(swing_high) - span * 0.500
        fib_618 = float(swing_high) - span * 0.618
    elif direction == "SHORT":
        fib_50 = float(swing_low) + span * 0.500
        fib_618 = float(swing_low) + span * 0.618
    else:
        raise ValueError("direction must be LONG or SHORT")

    zone_low = _round_to_tick(min(fib_50, fib_618), tick_size)
    zone_high = _round_to_tick(max(fib_50, fib_618), tick_size)
    watch_price = _round_to_tick((zone_low + zone_high) / 2.0, tick_size)
    impulse_quality = max(0.0, min(1.0, span / max(safe_atr * 4.0, tick_size)))

    closed = _closed_execution_candles(execution_candles, 1)
    recent = closed[-4:]
    overlaps = [c for c in recent if float(c.low) <= zone_high and float(c.high) >= zone_low]
    touched = bool(overlaps)
    latest = closed[-1] if closed else None
    previous = closed[-2] if len(closed) >= 2 else None

    rejection = False
    confirmation_entry = None
    confirmation_time = None
    if latest is not None and touched:
        candle_range = max(float(latest.high) - float(latest.low), float(tick_size))
        body = abs(float(latest.close) - float(latest.open))
        body_ok = body >= max(safe_atr * 0.12, candle_range * 0.32)
        close_location = (float(latest.close) - float(latest.low)) / candle_range
        recent_touch = any(
            float(c.low) <= zone_high and float(c.high) >= zone_low
            for c in ([previous, latest] if previous is not None else [latest])
        )
        if direction == "LONG":
            directional = float(latest.close) > float(latest.open)
            reclaimed = float(latest.close) >= zone_high
            rejection_wick = (min(float(latest.open), float(latest.close)) - float(latest.low)) >= candle_range * 0.15
            continuation = previous is None or float(latest.close) > float(previous.close)
            rejection = bool(recent_touch and directional and reclaimed and body_ok and (rejection_wick or continuation) and close_location >= 0.58)
        else:
            directional = float(latest.close) < float(latest.open)
            reclaimed = float(latest.close) <= zone_low
            rejection_wick = (float(latest.high) - max(float(latest.open), float(latest.close))) >= candle_range * 0.15
            continuation = previous is None or float(latest.close) < float(previous.close)
            rejection = bool(recent_touch and directional and reclaimed and body_ok and (rejection_wick or continuation) and close_location <= 0.42)

        if rejection:
            confirmation_entry = _round_to_tick((float(latest.open) + float(latest.close)) / 2.0, tick_size)
            confirmation_time = latest.time

    pullback_extreme = None
    if overlaps:
        pullback_extreme = min(float(c.low) for c in overlaps) if direction == "LONG" else max(float(c.high) for c in overlaps)
    buffer = max(float(tick_size) * 2.0, safe_atr * 0.08)
    if direction == "LONG":
        structural = min(zone_low, pullback_extreme if pullback_extreme is not None else zone_low)
        invalidation = _round_to_tick(structural - buffer, tick_size)
    else:
        structural = max(zone_high, pullback_extreme if pullback_extreme is not None else zone_high)
        invalidation = _round_to_tick(structural + buffer, tick_size)

    entry_fresh = False
    if confirmation_entry is not None:
        if direction == "LONG":
            distance = float(current_price) - confirmation_entry
        else:
            distance = confirmation_entry - float(current_price)
        entry_fresh = 0.0 <= distance <= safe_atr * 1.15

    confirmed = bool(rejection and confirmation_entry is not None and entry_fresh)
    return FibPullbackEvidence(
        zone_low=zone_low,
        zone_high=zone_high,
        watch_price=watch_price,
        invalidation_price=invalidation,
        impulse_quality=round(impulse_quality, 4),
        touched=touched,
        rejection=rejection,
        confirmed=confirmed,
        confirmation_entry=confirmation_entry,
        entry_fresh=entry_fresh,
        confirmation_candle_time=confirmation_time,
    )
