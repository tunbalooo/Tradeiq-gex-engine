from backend.models.schemas import Candle, Zone


def detect_supply_demand(
    candles: list[Candle],
    timeframe: str = "5m",
    lookback: int = 30,
) -> list[Zone]:
    if len(candles) < 8:
        return []

    recent = candles[-lookback:]
    ranges = [c.high - c.low for c in recent]
    avg_range = sum(ranges) / len(ranges)

    zones: list[Zone] = []

    for i in range(2, len(recent) - 2):
        prev = recent[i - 1]
        base = recent[i]
        nxt = recent[i + 1]

        bullish_displacement = nxt.close > base.high and (nxt.close - nxt.open) > avg_range * 0.8
        bearish_displacement = nxt.close < base.low and (nxt.open - nxt.close) > avg_range * 0.8

        if bullish_displacement and base.close <= base.open:
            zones.append(
                Zone(
                    timeframe=timeframe,
                    kind="DEMAND",
                    low=round(base.low, 2),
                    high=round(max(base.open, base.close), 2),
                    strength=4,
                    fresh=True,
                )
            )

        if bearish_displacement and base.close >= base.open:
            zones.append(
                Zone(
                    timeframe=timeframe,
                    kind="SUPPLY",
                    low=round(min(base.open, base.close), 2),
                    high=round(base.high, 2),
                    strength=4,
                    fresh=True,
                )
            )

    unique: list[Zone] = []
    for zone in reversed(zones):
        if not any(abs(zone.low - z.low) < avg_range * 0.4 for z in unique):
            unique.append(zone)
        if len(unique) >= 6:
            break

    return list(reversed(unique))
