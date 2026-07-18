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
    ranges: list[float] = []
    for index in range(1, len(candles)):
        candle = candles[index]
        previous = candles[index - 1]
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous.close),
                abs(candle.low - previous.close),
            )
        )
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 1.0


def analyze_market_structure(candles: list[Candle]) -> dict:
    if not candles:
        return {
            "trend": "NEUTRAL",
            "ema_aligned": False,
            "bullish_ema_aligned": False,
            "bearish_ema_aligned": False,
            "liquidity_sweep": False,
            "sell_side_sweep": False,
            "buy_side_sweep": False,
            "sweep_direction": "NONE",
            "sweep_price": None,
            "displacement": False,
            "bullish_displacement": False,
            "bearish_displacement": False,
            "displacement_direction": "NONE",
            "bullish_fvg": False,
            "bearish_fvg": False,
            "swing_low": 0.0,
            "swing_high": 0.0,
            "previous_liquidity_low": 0.0,
            "previous_liquidity_high": 0.0,
        }

    closes = [candle.close for candle in candles]
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    ema55 = ema(closes, 55)
    bullish_ema = len(ema55) >= 1 and ema9[-1] > ema21[-1] > ema55[-1]
    bearish_ema = len(ema55) >= 1 and ema9[-1] < ema21[-1] < ema55[-1]
    trend = "BULLISH" if bullish_ema else "BEARISH" if bearish_ema else "NEUTRAL"

    recent = candles[-60:]
    atr = _atr(recent)
    sweep_event: tuple[int, str, float] | None = None
    displacement_event: tuple[int, str] | None = None
    bullish_fvg = False
    bearish_fvg = False

    start = max(3, len(recent) - 12)
    for index in range(start, len(recent)):
        candle = recent[index]
        context = recent[max(0, index - 15):index]
        if len(context) < 5:
            continue
        prior_low = min(item.low for item in context)
        prior_high = max(item.high for item in context)

        sell_side = candle.low < prior_low and candle.close > prior_low
        buy_side = candle.high > prior_high and candle.close < prior_high
        if sell_side:
            sweep_event = (index, "SELL_SIDE", float(prior_low))
        elif buy_side:
            sweep_event = (index, "BUY_SIDE", float(prior_high))

        average_body = sum(abs(item.close - item.open) for item in context[-10:]) / min(len(context), 10)
        body = abs(candle.close - candle.open)
        threshold = max(average_body * 1.5, atr * 0.65)
        previous = recent[index - 1]
        bull_disp = candle.close > candle.open and body >= threshold and candle.close > previous.high
        bear_disp = candle.close < candle.open and body >= threshold and candle.close < previous.low
        if bull_disp:
            displacement_event = (index, "BULLISH")
        elif bear_disp:
            displacement_event = (index, "BEARISH")

        if index >= 2:
            if candle.low > recent[index - 2].high:
                bullish_fvg = True
            if candle.high < recent[index - 2].low:
                bearish_fvg = True

    sweep_direction = sweep_event[1] if sweep_event else "NONE"
    sweep_price = sweep_event[2] if sweep_event else None
    displacement_direction = displacement_event[1] if displacement_event else "NONE"

    swing_window = recent[-30:]
    liquidity_window = recent[-21:-1] if len(recent) > 21 else recent[:-1]
    previous_low = min((item.low for item in liquidity_window), default=recent[-1].low)
    previous_high = max((item.high for item in liquidity_window), default=recent[-1].high)

    return {
        "trend": trend,
        "ema_aligned": bullish_ema or bearish_ema,
        "bullish_ema_aligned": bullish_ema,
        "bearish_ema_aligned": bearish_ema,
        "liquidity_sweep": sweep_event is not None,
        "sell_side_sweep": sweep_direction == "SELL_SIDE",
        "buy_side_sweep": sweep_direction == "BUY_SIDE",
        "sweep_direction": sweep_direction,
        "sweep_price": sweep_price,
        "displacement": displacement_event is not None,
        "bullish_displacement": displacement_direction == "BULLISH",
        "bearish_displacement": displacement_direction == "BEARISH",
        "displacement_direction": displacement_direction,
        "bullish_fvg": bullish_fvg,
        "bearish_fvg": bearish_fvg,
        "swing_low": min(item.low for item in swing_window),
        "swing_high": max(item.high for item in swing_window),
        "previous_liquidity_low": float(previous_low),
        "previous_liquidity_high": float(previous_high),
    }
