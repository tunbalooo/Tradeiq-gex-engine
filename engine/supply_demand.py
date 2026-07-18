from backend.models.schemas import Candle, Zone


def _true_ranges(candles: list[Candle]) -> list[float]:
    if not candles:
        return []
    values = [candles[0].high - candles[0].low]
    for index in range(1, len(candles)):
        candle = candles[index]
        previous = candles[index - 1]
        values.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous.close),
                abs(candle.low - previous.close),
            )
        )
    return values


def _overlap_ratio(a: Zone, b: Zone) -> float:
    overlap = max(0.0, min(a.high, b.high) - max(a.low, b.low))
    width = max(min(a.high - a.low, b.high - b.low), 0.25)
    return overlap / width


def detect_supply_demand(
    candles: list[Candle],
    timeframe: str = "5m",
    lookback: int = 70,
) -> list[Zone]:
    """Detect fresh base-and-displacement zones and remove invalidated zones.

    The detector looks for one-to-three small overlapping base candles followed by
    a directional departure. It scores departure strength, freshness and number
    of retests. A close through the distal edge invalidates a zone.
    """
    if len(candles) < 20:
        return []

    recent = candles[-lookback:]
    tr = _true_ranges(recent)
    zones: list[Zone] = []

    for base_start in range(5, len(recent) - 3):
        for base_length in (1, 2, 3):
            base_end = base_start + base_length
            if base_end >= len(recent) - 1:
                continue
            base = recent[base_start:base_end]
            local_tr = tr[max(0, base_start - 14):base_start]
            atr = sum(local_tr) / len(local_tr) if local_tr else sum(tr) / len(tr)
            atr = max(atr, 0.25)

            base_high = max(item.high for item in base)
            base_low = min(item.low for item in base)
            base_range = base_high - base_low
            average_body = sum(abs(item.close - item.open) for item in base) / len(base)
            if base_range > atr * 1.45 or average_body > atr * 0.58:
                continue

            departures = recent[base_end:min(base_end + 2, len(recent))]
            bullish_extent = max((item.close - base_high for item in departures), default=0.0)
            bearish_extent = max((base_low - item.close for item in departures), default=0.0)
            bullish_body = max((item.close - item.open for item in departures), default=0.0)
            bearish_body = max((item.open - item.close for item in departures), default=0.0)

            kind: str | None = None
            departure_score = 0.0
            if bullish_extent >= atr * 0.65 and bullish_body >= atr * 0.55:
                kind = "DEMAND"
                departure_score = min(1.5, max(bullish_extent, bullish_body) / atr)
                zone_low = base_low
                zone_high = max(max(item.open, item.close) for item in base)
            elif bearish_extent >= atr * 0.65 and bearish_body >= atr * 0.55:
                kind = "SUPPLY"
                departure_score = min(1.5, max(bearish_extent, bearish_body) / atr)
                zone_low = min(min(item.open, item.close) for item in base)
                zone_high = base_high
            else:
                continue

            if zone_high - zone_low < 0.25:
                continue

            touches = 0
            invalidated = False
            was_inside = False
            for item in recent[base_end + len(departures):]:
                intersects = item.low <= zone_high and item.high >= zone_low
                if intersects and not was_inside:
                    touches += 1
                was_inside = intersects
                if kind == "DEMAND" and item.close < zone_low - atr * 0.05:
                    invalidated = True
                    break
                if kind == "SUPPLY" and item.close > zone_high + atr * 0.05:
                    invalidated = True
                    break

            if invalidated:
                continue

            fresh = touches == 0
            base_quality = max(0.0, 1.0 - base_range / (atr * 1.45))
            touch_penalty = min(touches, 3) * 0.55
            raw_strength = 2.0 + departure_score + base_quality + (0.8 if fresh else 0.2) - touch_penalty
            strength = max(1, min(5, round(raw_strength)))

            zones.append(
                Zone(
                    timeframe=timeframe,
                    kind=kind,
                    low=round(zone_low, 2),
                    high=round(zone_high, 2),
                    strength=strength,
                    fresh=fresh,
                    touches=touches,
                    created_at=base[-1].time,
                    displacement_score=round(departure_score, 2),
                    invalidated=False,
                )
            )

    deduped: list[Zone] = []
    for zone in sorted(
        zones,
        key=lambda item: (item.fresh, item.strength, item.created_at or candles[0].time),
        reverse=True,
    ):
        if any(zone.kind == existing.kind and _overlap_ratio(zone, existing) >= 0.55 for existing in deduped):
            continue
        deduped.append(zone)
        if len(deduped) >= 8:
            break
    return deduped
