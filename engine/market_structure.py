from backend.models.schemas import Candle


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def analyze_market_structure(candles: list[Candle]) -> dict:
    if len(candles) < 60:
        return {
            "trend": "NEUTRAL",
            "ema_aligned": False,
            "liquidity_sweep": False,
            "displacement": False,
            "swing_low": candles[-1].low if candles else 0.0,
            "swing_high": candles[-1].high if candles else 0.0,
        }

    closes = [c.close for c in candles]
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    ema55 = ema(closes, 55)

    bullish = ema9[-1] > ema21[-1] > ema55[-1]
    bearish = ema9[-1] < ema21[-1] < ema55[-1]
    trend = "BULLISH" if bullish else "BEARISH" if bearish else "NEUTRAL"

    recent = candles[-20:]
    prior_low = min(c.low for c in recent[:-1])
    prior_high = max(c.high for c in recent[:-1])
    last = recent[-1]

    sell_side_sweep = last.low < prior_low and last.close > prior_low
    buy_side_sweep = last.high > prior_high and last.close < prior_high

    avg_body = sum(abs(c.close - c.open) for c in recent[:-1]) / (len(recent) - 1)
    displacement = abs(last.close - last.open) > avg_body * 1.5

    return {
        "trend": trend,
        "ema_aligned": bullish or bearish,
        "liquidity_sweep": sell_side_sweep or buy_side_sweep,
        "sweep_direction": "SELL_SIDE" if sell_side_sweep else "BUY_SIDE" if buy_side_sweep else "NONE",
        "displacement": displacement,
        "swing_low": min(c.low for c in recent),
        "swing_high": max(c.high for c in recent),
    }
