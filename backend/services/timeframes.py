from datetime import datetime, timezone

from backend.models.schemas import Candle


def aggregate_candles(candles: list[Candle], minutes: int) -> list[Candle]:
    if minutes <= 1:
        return candles.copy()

    buckets: dict[int, list[Candle]] = {}
    seconds = minutes * 60
    for candle in candles:
        timestamp = candle.time
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        bucket = int(timestamp.timestamp()) // seconds * seconds
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
                volume=sum(item.volume for item in group),
            )
        )
    return result
