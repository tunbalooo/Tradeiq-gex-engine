from datetime import datetime, timezone

from backend.models.schemas import Candle


def _ordered_unique(candles: list[Candle]) -> list[Candle]:
    """Return strictly ordered, unique and structurally valid candles."""
    by_time: dict[datetime, Candle] = {}
    for candle in candles:
        timestamp = candle.time
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        values = (candle.open, candle.high, candle.low, candle.close)
        if not all(isinstance(value, (int, float)) for value in values):
            continue
        if candle.open <= 0 or candle.close <= 0:
            continue
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            continue
        by_time[timestamp] = candle.model_copy(update={"time": timestamp}, deep=True)
    return [by_time[key] for key in sorted(by_time)]


def aggregate_candles(candles: list[Candle], minutes: int) -> list[Candle]:
    ordered = _ordered_unique(candles)
    if minutes <= 1:
        return ordered

    buckets: dict[int, list[Candle]] = {}
    seconds = minutes * 60
    for candle in ordered:
        bucket = int(candle.time.timestamp()) // seconds * seconds
        buckets.setdefault(bucket, []).append(candle)

    result: list[Candle] = []
    for bucket in sorted(buckets):
        group = buckets[bucket]
        result.append(
            Candle(
                time=datetime.fromtimestamp(bucket, tz=timezone.utc),
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=sum(max(0, int(item.volume)) for item in group),
            )
        )
    return result
