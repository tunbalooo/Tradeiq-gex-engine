from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle
from engine.market_structure import analyze_market_structure, _swing_points


def test_directional_sell_side_sweep_is_identified():
    now = datetime.now(timezone.utc)
    candles = []
    price = 100.0
    for i in range(65):
        close = price + 0.3
        candles.append(Candle(time=now + timedelta(minutes=5*i), open=price, high=close+0.2, low=price-0.2, close=close, volume=100))
        price = close
    prior_low = min(c.low for c in candles[-15:])
    candles.append(Candle(time=now + timedelta(minutes=5*65), open=price, high=price+1, low=prior_low-1, close=prior_low+0.5, volume=500))
    result = analyze_market_structure(candles)
    assert result["sell_side_sweep"] is True
    assert result["buy_side_sweep"] is False


def _candle(i, o, h, l, c, base):
    return Candle(time=base + timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=100)


def test_swing_points_use_the_recent_coherent_leg_not_a_stray_old_wick():
    base = datetime.now(timezone.utc)
    candles = []
    price = 100.0
    for i in range(15):
        candles.append(_candle(i, price, price + 1, price - 1, price + 0.2, base))
        price += 0.2
    # A deep, unrelated wick far in the past. A blind rolling min/max over the
    # window could still pick this up; pivot detection must not.
    candles.append(_candle(15, price, price + 1, price - 40, price, base))
    price = candles[-1].close

    for i in range(16, 26):
        o = price
        price -= 2.0
        candles.append(_candle(i, o, o + 0.5, price - 0.5, price, base))
    for i in range(26, 46):
        o = price
        price += 2.5
        candles.append(_candle(i, o, price + 0.5, o - 0.5, price, base))
    for i in range(46, 60):
        o = price
        price -= 1.0
        candles.append(_candle(i, o, o + 0.5, price - 0.5, price, base))

    structure = analyze_market_structure(candles)
    # The stray wick dipped far below the real swing low; a correct pivot-based
    # anchor stays well above it.
    stray_wick_low = min(c.low for c in candles[:16])
    assert structure["swing_low"] > stray_wick_low + 10
    assert structure["swing_high"] > structure["swing_low"]


def test_swing_points_fall_back_to_rolling_window_without_confirmed_pivots():
    base = datetime.now(timezone.utc)
    # A pure, unbroken uptrend has no confirmed opposite-pivot pair within the
    # window; the function must still return a usable (low, high) via fallback
    # instead of erroring or returning a degenerate zero-width range.
    candles = [_candle(i, 100 + i, 100 + i + 0.5, 100 + i - 0.5, 100 + i + 0.2, base) for i in range(80)]
    low, high = _swing_points(candles)
    assert high > low
    assert low >= 100.0
