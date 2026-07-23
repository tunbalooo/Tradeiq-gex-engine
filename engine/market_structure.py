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
        }

    closes = [c.close for c in candles]
    ema9, ema21, ema55 = ema(closes, 9), ema(closes, 21), ema(closes, 55)
    bullish_ema = ema9[-1] > ema21[-1] > ema55[-1]
    bearish_ema = ema9[-1] < ema21[-1] < ema55[-1]
    trend = "BULLISH" if bullish_ema else "BEARISH" if bearish_ema else "NEUTRAL"

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

    bull_seq, bear_seq = find_sequence("LONG"), find_sequence("SHORT")
    latest_sell_sweep = latest_event("sweep", "LONG")
    latest_buy_sweep = latest_event("sweep", "SHORT")
    latest_bull_disp = latest_event("displacement", "LONG")
    latest_bear_disp = latest_event("displacement", "SHORT")
    latest_bull_fvg = latest_event("fvg", "LONG")
    latest_bear_fvg = latest_event("fvg", "SHORT")

    latest_sweep = max([e for e in (latest_sell_sweep, latest_buy_sweep) if e], key=lambda x: x["index"], default=None)
    latest_disp = max([e for e in (latest_bull_disp, latest_bear_disp) if e], key=lambda x: x["index"], default=None)

    swing_window = recent[-35:]
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
        "swing_low": min(item.low for item in swing_window),
        "swing_high": max(item.high for item in swing_window),
        "previous_liquidity_low": float(min(item.low for item in liquidity_window)),
        "previous_liquidity_high": float(max(item.high for item in liquidity_window)),
    }
