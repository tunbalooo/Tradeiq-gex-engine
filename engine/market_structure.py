from backend.core.config import settings
from backend.models.schemas import Candle


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def _atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 1.0
    values = []
    for index in range(1, len(candles)):
        current, previous = candles[index], candles[index - 1]
        values.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    selected = values[-period:]
    return sum(selected) / len(selected) if selected else 1.0


def _confirmed_pivots(window: list[Candle], wing: int) -> list[dict]:
    """Confirmed swing high/low pivots: a local extreme with `wing` candles on
    each side that are lower (for a high) or higher (for a low). A pivot can
    only be confirmed once price has moved away from it for `wing` bars, so
    the most recent pivot is always at least that many bars old — that lag is
    the price of it being a real turning point rather than an arbitrary
    rolling min/max.
    """
    pivots: list[dict] = []
    for index in range(wing, len(window) - wing):
        candle = window[index]
        left = window[index - wing:index]
        right = window[index + 1:index + 1 + wing]
        if all(candle.high >= other.high for other in left) and all(candle.high >= other.high for other in right):
            pivots.append({"index": index, "type": "HIGH", "price": float(candle.high)})
        if all(candle.low <= other.low for other in left) and all(candle.low <= other.low for other in right):
            pivots.append({"index": index, "type": "LOW", "price": float(candle.low)})
    return pivots


def _swing_points(window: list[Candle], wing: int = 3, fallback_bars: int = 35) -> tuple[float, float]:
    """Return (swing_low, swing_high) for the most recent coherent leg.

    Finds the most recently confirmed pivot, then the most recent
    opposite-type pivot before it, so the pair belongs to one actual up/down
    leg instead of two unrelated extremes. Falls back to a simple rolling
    min/max when there aren't enough confirmed pivots yet (e.g. a strong
    one-directional run, or too little history).
    """
    if window:
        pivots = sorted(_confirmed_pivots(window, wing), key=lambda item: item["index"])
        if pivots:
            latest = pivots[-1]
            opposite_type = "LOW" if latest["type"] == "HIGH" else "HIGH"
            earlier_opposite = next(
                (item for item in reversed(pivots[:-1]) if item["type"] == opposite_type), None,
            )
            if earlier_opposite is not None:
                high_price = latest["price"] if latest["type"] == "HIGH" else earlier_opposite["price"]
                low_price = latest["price"] if latest["type"] == "LOW" else earlier_opposite["price"]
                if high_price > low_price:
                    return low_price, high_price

    fallback = window[-fallback_bars:] if window else []
    if not fallback:
        return 0.0, 0.0
    return min(c.low for c in fallback), max(c.high for c in fallback)


def analyze_market_structure(candles: list[Candle]) -> dict:
    if len(candles) < 60:
        last = candles[-1] if candles else None
        return {
            "trend": "NEUTRAL", "ema_aligned": False, "bullish_ema_aligned": False,
            "bearish_ema_aligned": False, "liquidity_sweep": False,
            "sell_side_sweep": False, "buy_side_sweep": False,
            "sweep_direction": "NONE", "sweep_price": None,
            "displacement": False, "bullish_displacement": False,
            "bearish_displacement": False, "displacement_direction": "NONE",
            "bullish_fvg": False, "bearish_fvg": False,
            "bullish_sequence": False, "bearish_sequence": False,
            "sequence_age_bars": None, "sequence_detail": "Insufficient bars",
            "swing_low": last.low if last else 0.0, "swing_high": last.high if last else 0.0,
            "previous_liquidity_low": last.low if last else 0.0,
            "previous_liquidity_high": last.high if last else 0.0,
            "long_term_ema_bullish": False, "long_term_ema_bearish": False,
            "ema50": None, "ema100": None, "ema200": None,
        }

    closes = [c.close for c in candles]
    ema9, ema21, ema55 = ema(closes, 9), ema(closes, 21), ema(closes, 55)
    bullish_ema = ema9[-1] > ema21[-1] > ema55[-1]
    bearish_ema = ema9[-1] < ema21[-1] < ema55[-1]
    trend = "BULLISH" if bullish_ema else "BEARISH" if bearish_ema else "NEUTRAL"

    # Additional swing/trend confluence beyond the fast 9/21/55 stack used for
    # `trend`. This never changes the trend classification itself; it only
    # supplies an extra independent factor a confluence cluster can stack.
    ema50, ema100, ema200 = ema(closes, 50), ema(closes, 100), ema(closes, 200)
    has_long_term_history = len(closes) >= 200
    long_term_bullish = bool(
        has_long_term_history and ema50[-1] > ema100[-1] > ema200[-1] and closes[-1] > ema50[-1]
    )
    long_term_bearish = bool(
        has_long_term_history and ema50[-1] < ema100[-1] < ema200[-1] and closes[-1] < ema50[-1]
    )

    recent = candles[-80:]
    atr = _atr(recent)
    events: list[dict] = []
    start = max(15, len(recent) - settings.event_max_age_bars - 8)

    for index in range(start, len(recent)):
        candle = recent[index]
        context = recent[max(0, index - 15):index]
        if len(context) < 8:
            continue
        prior_low = min(item.low for item in context)
        prior_high = max(item.high for item in context)
        sell_side = candle.low < prior_low and candle.close > prior_low
        buy_side = candle.high > prior_high and candle.close < prior_high
        if sell_side and buy_side:
            lower_excursion = prior_low - candle.low
            upper_excursion = candle.high - prior_high
            if lower_excursion >= upper_excursion:
                buy_side = False
            else:
                sell_side = False
        if sell_side:
            events.append({"index": index, "type": "sweep", "direction": "LONG", "price": float(prior_low), "time": candle.time})
        if buy_side:
            events.append({"index": index, "type": "sweep", "direction": "SHORT", "price": float(prior_high), "time": candle.time})

        average_body = sum(abs(item.close - item.open) for item in context[-10:]) / min(len(context), 10)
        body = abs(candle.close - candle.open)
        threshold = max(average_body * 1.5, atr * .65)
        previous = recent[index - 1]
        if candle.close > candle.open and body >= threshold and candle.close > previous.high:
            events.append({"index": index, "type": "displacement", "direction": "LONG", "time": candle.time})
        if candle.close < candle.open and body >= threshold and candle.close < previous.low:
            events.append({"index": index, "type": "displacement", "direction": "SHORT", "time": candle.time})

        if index >= 2 and candle.low > recent[index - 2].high:
            events.append({"index": index, "type": "fvg", "direction": "LONG", "low": recent[index - 2].high, "high": candle.low, "time": candle.time})
        if index >= 2 and candle.high < recent[index - 2].low:
            events.append({"index": index, "type": "fvg", "direction": "SHORT", "low": candle.high, "high": recent[index - 2].low, "time": candle.time})

    def latest_event(kind: str, direction: str):
        matches = [e for e in events if e["type"] == kind and e["direction"] == direction]
        return matches[-1] if matches else None

    def find_sequence(direction: str):
        sweeps = [e for e in events if e["type"] == "sweep" and e["direction"] == direction]
        for sweep in reversed(sweeps):
            displacements = [e for e in events if e["type"] == "displacement" and e["direction"] == direction and 0 <= e["index"] - sweep["index"] <= settings.event_sequence_max_bars]
            for displacement in displacements:
                fvgs = [e for e in events if e["type"] == "fvg" and e["direction"] == direction and displacement["index"] <= e["index"] <= displacement["index"] + 2]
                if fvgs:
                    age = len(recent) - 1 - fvgs[-1]["index"]
                    if age <= settings.event_max_age_bars:
                        return {"sweep": sweep, "displacement": displacement, "fvg": fvgs[-1], "age": age}
        return None

    def find_inverse_fvg(direction: str):
        """A directional FVG that price has since closed through (failed as its
        original support/resistance) and has not since failed the other way is
        an inverse FVG: the same zone now acts as opposite-direction support or
        resistance.
        """
        opposite = "SHORT" if direction == "LONG" else "LONG"
        candidates = [e for e in events if e["type"] == "fvg" and e["direction"] == opposite]
        for fvg in reversed(candidates):
            zone_low, zone_high = fvg["low"], fvg["high"]
            after = recent[fvg["index"] + 1:]
            inverted_index = None
            for offset, candle in enumerate(after):
                if direction == "LONG" and candle.close > zone_high:
                    inverted_index = fvg["index"] + 1 + offset
                    break
                if direction == "SHORT" and candle.close < zone_low:
                    inverted_index = fvg["index"] + 1 + offset
                    break
            if inverted_index is None:
                continue
            age = len(recent) - 1 - inverted_index
            if age > settings.event_max_age_bars:
                continue
            later = recent[inverted_index + 1:]
            failed_back = any(
                (c.close < zone_low if direction == "LONG" else c.close > zone_high)
                for c in later
            )
            if failed_back:
                continue
            return {"low": zone_low, "high": zone_high, "time": recent[inverted_index].time}
        return None

    bull_seq, bear_seq = find_sequence("LONG"), find_sequence("SHORT")
    bull_ifvg, bear_ifvg = find_inverse_fvg("LONG"), find_inverse_fvg("SHORT")
    latest_sell_sweep = latest_event("sweep", "LONG")
    latest_buy_sweep = latest_event("sweep", "SHORT")
    latest_bull_disp = latest_event("displacement", "LONG")
    latest_bear_disp = latest_event("displacement", "SHORT")
    latest_bull_fvg = latest_event("fvg", "LONG")
    latest_bear_fvg = latest_event("fvg", "SHORT")

    latest_sweep = max([e for e in (latest_sell_sweep, latest_buy_sweep) if e], key=lambda x: x["index"], default=None)
    latest_disp = max([e for e in (latest_bull_disp, latest_bear_disp) if e], key=lambda x: x["index"], default=None)

    swing_low, swing_high = _swing_points(recent)
    liquidity_window = recent[-25:-1]
    return {
        "trend": trend,
        "ema_aligned": bullish_ema or bearish_ema,
        "bullish_ema_aligned": bullish_ema,
        "bearish_ema_aligned": bearish_ema,
        "liquidity_sweep": latest_sweep is not None,
        "sell_side_sweep": latest_sell_sweep is not None,
        "buy_side_sweep": latest_buy_sweep is not None,
        "sweep_direction": "SELL_SIDE" if latest_sweep and latest_sweep["direction"] == "LONG" else "BUY_SIDE" if latest_sweep else "NONE",
        "sweep_price": latest_sweep.get("price") if latest_sweep else None,
        "sweep_time": latest_sweep.get("time") if latest_sweep else None,
        "sell_side_sweep_time": latest_sell_sweep.get("time") if latest_sell_sweep else None,
        "buy_side_sweep_time": latest_buy_sweep.get("time") if latest_buy_sweep else None,
        "displacement": latest_disp is not None,
        "displacement_time": latest_disp.get("time") if latest_disp else None,
        "bullish_displacement_time": latest_bull_disp.get("time") if latest_bull_disp else None,
        "bearish_displacement_time": latest_bear_disp.get("time") if latest_bear_disp else None,
        "bullish_displacement": latest_bull_disp is not None,
        "bearish_displacement": latest_bear_disp is not None,
        "displacement_direction": "BULLISH" if latest_disp and latest_disp["direction"] == "LONG" else "BEARISH" if latest_disp else "NONE",
        "bullish_fvg": latest_bull_fvg is not None,
        "bearish_fvg": latest_bear_fvg is not None,
        "bullish_inverse_fvg": bull_ifvg is not None,
        "bearish_inverse_fvg": bear_ifvg is not None,
        "bullish_inverse_fvg_low": bull_ifvg.get("low") if bull_ifvg else None,
        "bullish_inverse_fvg_high": bull_ifvg.get("high") if bull_ifvg else None,
        "bearish_inverse_fvg_low": bear_ifvg.get("low") if bear_ifvg else None,
        "bearish_inverse_fvg_high": bear_ifvg.get("high") if bear_ifvg else None,
        "bullish_sequence": bull_seq is not None,
        "bearish_sequence": bear_seq is not None,
        "sequence_age_bars": (bull_seq or bear_seq or {}).get("age"),
        "sequence_detail": "Sweep → displacement → FVG confirmed" if bull_seq or bear_seq else "No recent ordered sweep/displacement/FVG sequence",
        "bullish_sequence_time": bull_seq["fvg"].get("time") if bull_seq else None,
        "bearish_sequence_time": bear_seq["fvg"].get("time") if bear_seq else None,
        "bullish_fvg_low": bull_seq["fvg"].get("low") if bull_seq else None,
        "bullish_fvg_high": bull_seq["fvg"].get("high") if bull_seq else None,
        "bearish_fvg_low": bear_seq["fvg"].get("low") if bear_seq else None,
        "bearish_fvg_high": bear_seq["fvg"].get("high") if bear_seq else None,
        "swing_low": swing_low,
        "swing_high": swing_high,
        "previous_liquidity_low": float(min(item.low for item in liquidity_window)),
        "previous_liquidity_high": float(max(item.high for item in liquidity_window)),
        "long_term_ema_bullish": long_term_bullish,
        "long_term_ema_bearish": long_term_bearish,
        "ema50": float(ema50[-1]), "ema100": float(ema100[-1]), "ema200": float(ema200[-1]),
    }
